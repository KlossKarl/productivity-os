"""
Browser History Analyzer
Karl's Productivity OS - Project 7

Reads Brave browser history (local SQLite DB), analyzes with Ollama,
generates a structured weekly + monthly report saved to Obsidian.

Usage:
    python browser_analysis.py              # run full report
    python browser_analysis.py --days 14   # custom window
    python browser_analysis.py --no-obsidian  # print only, skip Obsidian
"""

import os
import sys
import json
import re
import shutil
import sqlite3
import argparse
import requests
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict, Counter
from urllib.parse import urlparse

# ─────────────────────────────────────────────
# SHARED DB — finds db.py at repo root regardless of CWD
# Works whether run from repo root or any subfolder
# ─────────────────────────────────────────────
def _find_repo_root():
    candidate = Path(__file__).resolve().parent
    for _ in range(4):
        if (candidate / "db.py").exists():
            return candidate
        candidate = candidate.parent
    return None

_repo_root = _find_repo_root()
if _repo_root and str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

try:
    from db import log_artifact, log_session, log_metric, log_event, init_db
    SHARED_DB_AVAILABLE = True
    print(f"[db] Loaded from: {_repo_root}")
except ImportError:
    SHARED_DB_AVAILABLE = False
    print("[db] db.py not found — shared DB writes disabled")

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

BRAVE_HISTORY   = Path(r"C:\Users\Karl\AppData\Local\BraveSoftware\Brave-Browser\User Data\Default\History")
OBSIDIAN_VAULT  = Path(r"C:\Users\Karl\Documents\Obsidian Vault")
OBSIDIAN_FOLDER = OBSIDIAN_VAULT / "Browser Reports"
OUTPUT_DIR      = Path(r"C:\Users\Karl\Documents\transcripts")  # local backup

OLLAMA_URL      = "http://localhost:11434/api/generate"
OLLAMA_MODEL    = "llama3:8b"

# Domains that are noise — filter from analysis but still count for focus scoring
NOISE_DOMAINS = {
    "google.com", "googleapis.com", "gstatic.com", "accounts.google.com",
    "bing.com", "duckduckgo.com", "yahoo.com",
    "brave.com", "bravesoftware.com",
    "localhost", "127.0.0.1",
    "chrome-extension", "newtab",
}

# Domains that are ALWAYS distractions regardless of content
DISTRACTION_DOMAINS = {
    "instagram.com", "facebook.com", "tiktok.com",
    "9gag.com", "buzzfeed.com", "dailymail.co.uk", "tmz.com",
}

# YouTube is productive if the title contains these keywords
YOUTUBE_PRODUCTIVE_KEYWORDS = [
    "science", "math", "physics", "chemistry", "biology", "quantum",
    "nature", "space", "nasa", "climate", "ocean", "evolution",
    "documentary", "explained", "how does", "how to", "tutorial",
    "3blue1brown", "veritasium", "kurzgesagt", "vsauce", "numberphile",
    "smarter every day", "minutephysics", "real engineering",
    "ai", "artificial intelligence", "machine learning", "neural", "llm",
    "python", "programming", "coding", "software", "data science",
    "deep learning", "gpt", "claude", "ollama", "model",
    "history", "ancient", "war", "empire", "philosophy", "religion",
    "theology", "civilization", "historical", "myth", "culture",
    "live", "concert", "performance", "session", "full album",
    "official audio", "music video", "symphony", "jazz", "classical",
]

# Reddit subreddits that count as productive
REDDIT_PRODUCTIVE_SUBS = [
    "dynastyff", "fantasyfootball", "ffadvice", "dynastyleague",
    "nfldraft", "nfl", "cfb", "collegebasketball",
    "sportsanalytics", "sportsbetting", "dfsports", "analytics",
    "programming", "python", "learnprogramming", "webdev", "machinelearning",
    "artificial", "localllama", "ollama", "datascience", "cscareerquestions",
    "entrepreneurship", "startups", "sideproject",
]

# ─────────────────────────────────────────────
# HISTORY READING
# ─────────────────────────────────────────────

def read_history(days: int) -> list[dict]:
    """
    Copy Brave history DB (it's locked while Brave is open) and read it.
    Returns list of {url, title, visit_time, domain} dicts.
    """
    if not BRAVE_HISTORY.exists():
        print(f"[ERROR] Brave history not found at: {BRAVE_HISTORY}")
        print("        Is Brave installed? Check the path.")
        sys.exit(1)

    # Copy to temp file — Brave locks the original
    tmp = Path(r"C:\Users\Karl\AppData\Local\Temp\brave_history_tmp.db")
    shutil.copy2(str(BRAVE_HISTORY), str(tmp))

    # Chrome/Brave timestamps are microseconds since Jan 1, 1601
    cutoff_days = datetime.now() - timedelta(days=days)
    cutoff_ts = int((cutoff_days - datetime(1601, 1, 1)).total_seconds() * 1_000_000)

    conn = sqlite3.connect(str(tmp))
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT
            u.url,
            u.title,
            v.visit_time,
            u.visit_count
        FROM visits v
        JOIN urls u ON v.url = u.id
        WHERE v.visit_time > ?
        ORDER BY v.visit_time DESC
    """, (cutoff_ts,)).fetchall()

    conn.close()
    tmp.unlink(missing_ok=True)

    results = []
    for row in rows:
        url = row["url"] or ""
        title = row["title"] or ""
        try:
            domain = urlparse(url).netloc.replace("www.", "")
        except Exception:
            domain = ""

        # Convert Chrome timestamp to datetime
        chrome_epoch = datetime(1601, 1, 1)
        visit_dt = chrome_epoch + timedelta(microseconds=row["visit_time"])

        results.append({
            "url": url,
            "title": title,
            "domain": domain,
            "visit_time": visit_dt,
            "hour": visit_dt.hour,
            "day_of_week": visit_dt.strftime("%A"),
        })

    return results

# ─────────────────────────────────────────────
# ANALYSIS
# ─────────────────────────────────────────────

def is_distraction(domain: str, url: str, title: str) -> bool:
    """Smart classification — considers content not just domain."""
    title_lower = (title or "").lower()
    url_lower = (url or "").lower()

    # Always distraction
    if any(d in domain for d in DISTRACTION_DOMAINS):
        return True

    # X / Twitter — always distraction
    if "x.com" in domain or "twitter.com" in domain:
        return True

    # YouTube — check title for productive keywords
    if "youtube.com" in domain:
        if any(kw in title_lower for kw in YOUTUBE_PRODUCTIVE_KEYWORDS):
            return False  # productive
        return True  # distraction by default

    # Reddit — check subreddit in URL
    if "reddit.com" in domain:
        if any(sub in url_lower for sub in REDDIT_PRODUCTIVE_SUBS):
            return False  # productive
        return True  # distraction by default

    # Twitch — treat as distraction
    if "twitch.tv" in domain:
        return True

    # Netflix — distraction
    if "netflix.com" in domain:
        return True

    return False

def analyze_history(visits: list[dict]) -> dict:
    """Build statistical analysis from raw visits."""

    domain_counts = Counter()
    hour_counts = Counter()
    day_counts = Counter()
    distraction_count = 0
    productive_count = 0

    for v in visits:
        domain = v["domain"]
        if not domain or any(n in domain for n in NOISE_DOMAINS):
            continue
        domain_counts[domain] += 1
        hour_counts[v["hour"]] += 1
        day_counts[v["day_of_week"]] += 1
        if is_distraction(domain, v.get("url",""), v.get("title","")):
            distraction_count += 1
        else:
            productive_count += 1

    total = productive_count + distraction_count
    focus_score = round((productive_count / total * 100) if total > 0 else 0, 1)

    # Peak hours — top 3
    peak_hours = [f"{h:02d}:00-{h+1:02d}:00" for h, _ in hour_counts.most_common(3)]

    # Most active day
    most_active_day = day_counts.most_common(1)[0][0] if day_counts else "N/A"

    # Top domains split into productive vs distraction
    top_all = domain_counts.most_common(40)
    top_distractions = [(d, c) for d, c in top_all if any(x in d for x in DISTRACTION_DOMAINS)]
    top_productive = [(d, c) for d, c in top_all if not any(x in d for x in DISTRACTION_DOMAINS)]

    return {
        "total_visits": len(visits),
        "unique_domains": len(domain_counts),
        "focus_score": focus_score,
        "distraction_visits": distraction_count,
        "productive_visits": productive_count,
        "peak_hours": peak_hours,
        "most_active_day": most_active_day,
        "top_domains": top_all[:25],
        "top_productive_domains": top_productive[:15],
        "top_distraction_domains": top_distractions[:10],
        "hour_counts": dict(hour_counts),
        "day_counts": dict(day_counts),
    }

def build_llm_summary(visits: list[dict], stats: dict, days: int) -> dict:
    """Send browsing data to Ollama for narrative analysis."""

    # Build a condensed picture for the LLM
    top_domains_str = "\n".join([f"  {d}: {c} visits" for d, c in stats["top_productive_domains"][:20]])
    distraction_str = "\n".join([f"  {d}: {c} visits" for d, c in stats["top_distraction_domains"][:10]])

    # Sample of page titles for topic detection
    titles = [v["title"] for v in visits if v["title"] and len(v["title"]) > 5]
    title_sample = "\n".join(titles[:120])

    prompt = f"""You are analyzing {days} days of browser history for a developer/builder named Karl.

STATS:
- Total visits: {stats['total_visits']}
- Focus score: {stats['focus_score']}% (productive vs distraction sites)
- Peak active hours: {', '.join(stats['peak_hours'])}
- Most active day: {stats['most_active_day']}

TOP PRODUCTIVE DOMAINS:
{top_domains_str}

TOP DISTRACTION DOMAINS:
{distraction_str}

SAMPLE OF PAGE TITLES VISITED:
{title_sample}

Based on this data, respond with ONLY raw JSON on a single line, no markdown, no explanation:
{{"topics_deep_in":["topic1","topic2","topic3","topic4","topic5"],"actively_building":["project or thing 1","project or thing 2"],"focus_killers":["site or pattern 1","site or pattern 2"],"peak_productivity_window":"description of when Karl is most active","weekly_summary":"3-4 sentence narrative of what Karl has been working on and how focused he has been","recommendations":["suggestion 1","suggestion 2","suggestion 3"],"explore_next":["interesting topic 1 based on his interests","interesting topic 2","interesting topic 3"]}}"""

    try:
        print(f"      Sending to {OLLAMA_MODEL}...")
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=180,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()

        # Extract JSON
        raw = re.sub(r"```json\s*", "", raw)
        raw = re.sub(r"```\s*", "", raw)
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            raw = match.group(0)

        data = json.loads(raw)
        print(f"      Done.")
        return data

    except Exception as e:
        print(f"      [WARN] LLM analysis failed: {e}")
        return {
            "topics_deep_in": [],
            "actively_building": [],
            "focus_killers": [],
            "peak_productivity_window": "N/A",
            "weekly_summary": "LLM analysis unavailable.",
            "recommendations": [],
            "explore_next": [],
        }

# ─────────────────────────────────────────────
# REPORT BUILDING
# ─────────────────────────────────────────────

def build_hour_sparkline(hour_counts: dict) -> str:
    """Build a simple text-based activity chart by hour."""
    bars = []
    max_count = max(hour_counts.values()) if hour_counts else 1
    for h in range(24):
        count = hour_counts.get(h, 0)
        filled = int((count / max_count) * 8)
        bar = "█" * filled + "░" * (8 - filled)
        label = f"{h:02d}h"
        bars.append(f"{label} {bar} {count}")
    return "\n".join(bars)

def build_report(stats: dict, llm: dict, days: int) -> str:
    """Build the full markdown report."""
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    period = f"Last {days} days"

    focus_emoji = "🟢" if stats["focus_score"] >= 70 else "🟡" if stats["focus_score"] >= 50 else "🔴"

    report = f"""---
date: {date_str}
time: {time_str}
period: {period}
focus_score: {stats['focus_score']}
total_visits: {stats['total_visits']}
tags:
  - browser-report
  - productivity
---

# Browser Report — {date_str}
**Period:** {period}  |  **Generated:** {time_str}

---

## Focus Score: {stats['focus_score']}% {focus_emoji}

| Metric | Value |
|--------|-------|
| Total visits | {stats['total_visits']} |
| Unique domains | {stats['unique_domains']} |
| Productive visits | {stats['productive_visits']} |
| Distraction visits | {stats['distraction_visits']} |
| Most active day | {stats['most_active_day']} |
| Peak hours | {', '.join(stats['peak_hours'])} |

---

## What You've Been Working On

{llm.get('weekly_summary', 'N/A')}

---

## Topics You're Deep In

"""
    for topic in llm.get("topics_deep_in", []):
        report += f"- {topic}\n"

    report += "\n## Actively Building / Researching\n\n"
    for item in llm.get("actively_building", []):
        report += f"- {item}\n"

    report += "\n## Focus Killers\n\n"
    for killer in llm.get("focus_killers", []):
        report += f"- {killer}\n"

    report += f"\n## Peak Productivity Window\n\n{llm.get('peak_productivity_window', 'N/A')}\n"

    report += "\n## Recommendations\n\n"
    for rec in llm.get("recommendations", []):
        report += f"- [ ] {rec}\n"

    report += "\n## Explore Next (based on your interests)\n\n"
    for item in llm.get("explore_next", []):
        report += f"- {item}\n"

    report += "\n---\n\n## Top Sites\n\n"
    report += "### Productive\n\n"
    report += "| Domain | Visits |\n|--------|--------|\n"
    for domain, count in stats["top_productive_domains"][:15]:
        report += f"| {domain} | {count} |\n"

    report += "\n### Distractions\n\n"
    report += "| Domain | Visits |\n|--------|--------|\n"
    for domain, count in stats["top_distraction_domains"][:10]:
        report += f"| {domain} | {count} |\n"

    report += f"\n---\n\n## Activity by Hour\n\n```\n{build_hour_sparkline(stats['hour_counts'])}\n```\n"

    return report

# ─────────────────────────────────────────────
# SHARED DB INTEGRATION
# ─────────────────────────────────────────────

def write_to_shared_db(stats: dict, llm: dict, visits: list, days: int,
                       obsidian_path: str = None, date_str: str = None):
    """
    Write browser analysis results into the shared productivity_os.db.
    Called once per report run (per days window).
    Writes:
      - 1 artifact row  (the report itself)
      - 1 session row   (the browsing window as a session)
      - N metric rows   (focus score, visit counts, distraction counts)
    """
    if not SHARED_DB_AVAILABLE:
        return

    date_str = date_str or datetime.now().strftime("%Y-%m-%d")
    topics   = llm.get("topics_deep_in", [])
    killers  = llm.get("focus_killers", [])

    # ── 1. Artifact: the report note ──────────────────────────────────────
    artifact_id = log_artifact(
        artifact_type="browser_report",
        source_tool="browser_analyzer",
        path_or_url=str(obsidian_path) if obsidian_path else None,
        title=f"Browser Report {date_str} ({days}d)",
        summary=llm.get("weekly_summary", ""),
        obsidian_path=str(obsidian_path) if obsidian_path else None,
        tags=(
            ["browser-report", f"{days}d"]
            + [t.lower().replace(" ", "-") for t in topics[:5]]
        ),
        extra={
            "days_window":         days,
            "focus_score":         stats["focus_score"],
            "total_visits":        stats["total_visits"],
            "unique_domains":      stats["unique_domains"],
            "productive_visits":   stats["productive_visits"],
            "distraction_visits":  stats["distraction_visits"],
            "peak_hours":          stats["peak_hours"],
            "most_active_day":     stats["most_active_day"],
            "topics_deep_in":      topics,
            "focus_killers":       killers,
            "explore_next":        llm.get("explore_next", []),
            "recommendations":     llm.get("recommendations", []),
        }
    )

    # ── 2. Session: the browsing window itself ─────────────────────────────
    # Approximate start = N days ago at midnight
    window_start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    window_end   = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    log_session(
        kind="browser",
        source_tool="browser_analyzer",
        start_ts=window_start,
        end_ts=window_end,
        focus_score=stats["focus_score"],
        summary=f"{days}-day window: {stats['total_visits']} visits, "
                f"focus {stats['focus_score']}%. "
                f"Top topics: {', '.join(topics[:3]) if topics else 'N/A'}",
        artifact_id=artifact_id,
        extra={
            "days_window":        days,
            "unique_domains":     stats["unique_domains"],
            "top_productive":     [d for d, _ in stats["top_productive_domains"][:5]],
            "top_distractions":   [d for d, _ in stats["top_distraction_domains"][:5]],
        }
    )

    # ── 3. Metrics: one row per metric for today ───────────────────────────
    # Only write the 7-day window as "today's" metrics to avoid overwriting
    # with stale 30-day aggregates. 30-day run still writes its own extras.
    if days == 7:
        log_metric(
            metric_name="browser_focus_score",
            value=stats["focus_score"],
            source_tool="browser_analyzer",
            date_str=date_str,
            notes=f"7-day window, {stats['total_visits']} visits",
        )
        log_metric(
            metric_name="browser_total_visits_7d",
            value=stats["total_visits"],
            source_tool="browser_analyzer",
            date_str=date_str,
        )
        log_metric(
            metric_name="browser_distraction_visits_7d",
            value=stats["distraction_visits"],
            source_tool="browser_analyzer",
            date_str=date_str,
        )
        log_metric(
            metric_name="browser_productive_visits_7d",
            value=stats["productive_visits"],
            source_tool="browser_analyzer",
            date_str=date_str,
        )

    # Always write the window-specific focus score so trends are queryable
    log_metric(
        metric_name=f"browser_focus_score_{days}d",
        value=stats["focus_score"],
        source_tool="browser_analyzer",
        date_str=date_str,
        notes=f"{stats['total_visits']} visits over {days} days",
    )

    print(f"  [db] Written to shared DB — artifact {artifact_id[:8]}...")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def run_report(days_list: list[int], no_obsidian: bool = False):
    OBSIDIAN_FOLDER.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for days in days_list:
        print(f"\n{'='*60}")
        print(f"  Browser History Analyzer — Last {days} days")
        print(f"{'='*60}")

        print(f"\n[1/3] Reading Brave history ({days} days)...")
        visits = read_history(days)
        print(f"      {len(visits)} visits loaded")

        print(f"\n[2/3] Analyzing patterns...")
        stats = analyze_history(visits)
        print(f"      Focus score: {stats['focus_score']}%")
        print(f"      Unique domains: {stats['unique_domains']}")

        print(f"\n[3/3] Running LLM analysis...")
        llm = build_llm_summary(visits, stats, days)

        report = build_report(stats, llm, days)

        # Save to Obsidian
        date_str = datetime.now().strftime("%Y-%m-%d")
        filename = f"{date_str} Browser Report ({days}d).md"
        obsidian_path = OBSIDIAN_FOLDER / filename

        if not no_obsidian:
            obsidian_path.write_text(report, encoding="utf-8")
            print(f"\n  Saved to Obsidian: Browser Reports/{filename}")

        # Always save local backup
        local_path = OUTPUT_DIR / filename
        local_path.write_text(report, encoding="utf-8")

        # Write to shared productivity_os.db
        write_to_shared_db(
            stats=stats,
            llm=llm,
            visits=visits,
            days=days,
            obsidian_path=obsidian_path if not no_obsidian else None,
            date_str=date_str,
        )

        # Print key findings to terminal
        print(f"\n{'='*60}")
        print(f"  REPORT — Last {days} days")
        print(f"{'='*60}")
        print(f"  Focus Score:    {stats['focus_score']}%")
        print(f"  Total Visits:   {stats['total_visits']}")
        print(f"  Peak Hours:     {', '.join(stats['peak_hours'])}")
        print(f"  Most Active:    {stats['most_active_day']}")

        topics = llm.get("topics_deep_in", [])
        if topics:
            print(f"\n  Topics you're deep in:")
            for t in topics:
                print(f"    • {t}")

        killers = llm.get("focus_killers", [])
        if killers:
            print(f"\n  Focus killers:")
            for k in killers:
                print(f"    ⚠ {k}")

        explore = llm.get("explore_next", [])
        if explore:
            print(f"\n  Explore next:")
            for e in explore:
                print(f"    → {e}")

        print(f"\n  Full report: Browser Reports/{filename}")
        print(f"{'='*60}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Browser History Analyzer")
    parser.add_argument("--days", type=int, help="Days to analyze (default: both 7 and 30)")
    parser.add_argument("--no-obsidian", action="store_true", help="Skip saving to Obsidian")
    args = parser.parse_args()

    days_list = [args.days] if args.days else [7, 30]
    run_report(days_list, no_obsidian=args.no_obsidian)
