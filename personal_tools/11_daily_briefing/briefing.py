"""
Daily Briefing
Karl's Productivity OS - Project 11

Pulls from: Tasks.md, Obsidian notes (transcripts + browser reports),
            git log, Brave browser history.

Writes:  - Updates Tasks.md with newly found unconfirmed tasks
         - Daily briefing note to Obsidian Vault/Briefings/
         - Prints terminal summary

Usage:
    python briefing.py                  # full morning briefing
    python briefing.py --extract        # scan notes + update Tasks.md only
    python briefing.py --tasks          # print current Tasks.md to terminal
    python briefing.py --days 3         # look back N days when scanning (default: 7)
"""

import os
import sys
import re
import json
import shutil
import sqlite3
import argparse
import subprocess
import requests
from pathlib import Path
from datetime import datetime, timedelta, date
from collections import Counter
from urllib.parse import urlparse

# ─────────────────────────────────────────────
# CONFIG — adjust paths if needed
# ─────────────────────────────────────────────

OBSIDIAN_VAULT      = Path(r"C:\Users\Karl\Documents\Obsidian Vault")
TASKS_FILE          = OBSIDIAN_VAULT / "Tasks.md"
BRIEFINGS_FOLDER    = OBSIDIAN_VAULT / "Briefings"
TRANSCRIPTS_FOLDER  = OBSIDIAN_VAULT / "Transcripts"
BROWSER_REPORTS_FOLDER = OBSIDIAN_VAULT / "Browser Reports"
ROADMAPS_FOLDER     = OBSIDIAN_VAULT / "road maps"

# Folders to scan for task extraction — add any Obsidian folder here
SCAN_FOLDERS = [
    (TRANSCRIPTS_FOLDER,     "transcript"),
    (BROWSER_REPORTS_FOLDER, "browser-report"),
    (ROADMAPS_FOLDER,        "roadmap"),
]

# Files in vault ROOT to always scan (master docs, context files)
# Add filenames here — scanned every run regardless of modification date
ROOT_ALWAYS_SCAN = [
    "_karl_context.md",
    "productivity_os_roadmap.md",
]

BRAVE_HISTORY       = Path(r"C:\Users\Karl\AppData\Local\BraveSoftware\Brave-Browser\User Data\Default\History")
BRAVE_HISTORY_TMP   = Path(r"C:\Users\Karl\AppData\Local\Temp\brave_history_briefing.db")

GIT_REPOS           = [
    Path(r"C:\Users\Karl\Documents\productivity-os"),
    # add more repos here
]

OLLAMA_URL          = "http://localhost:11434/api/generate"
OLLAMA_MODEL_FAST   = "llama3:8b"        # used for per-note task extraction
OLLAMA_MODEL_SMART  = "deepseek-r1:14b"  # used for briefing narrative only

SCAN_DAYS_DEFAULT   = 7             # how far back to scan for new tasks

SHARED_DB           = Path(r"C:\Users\Karl\Documents\productivity_os.db")

# ─────────────────────────────────────────────
# SHARED DB — read tasks, write rollups/metrics
# ─────────────────────────────────────────────

class SharedDB:
    """
    Thin wrapper around productivity_os.db.
    Graceful fallback — if DB not found, all methods return empty/None silently.
    """

    def __init__(self):
        self.available = SHARED_DB.exists()

    def _conn(self):
        return sqlite3.connect(str(SHARED_DB))

    def get_open_tasks(self) -> list:
        """Read open tasks from the shared tasks table."""
        if not self.available:
            return []
        try:
            conn = self._conn()
            rows = conn.execute("""
                SELECT title, priority, source_tool, created_at
                FROM tasks
                WHERE status = 'open'
                ORDER BY
                    CASE priority
                        WHEN 'high'   THEN 1
                        WHEN 'medium' THEN 2
                        WHEN 'low'    THEN 3
                        ELSE 4
                    END,
                    created_at DESC
                LIMIT 50
            """).fetchall()
            conn.close()
            return [
                {"title": r[0], "priority": r[1] or "medium",
                 "source": r[2] or "manual", "created_at": r[3]}
                for r in rows
            ]
        except Exception as e:
            print(f"  [DB] Could not read tasks: {e}")
            return []

    def get_yesterday_metrics(self) -> dict:
        """Pull yesterday's key metrics from metrics_daily."""
        if not self.available:
            return {}
        try:
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            conn = self._conn()
            rows = conn.execute(
                "SELECT metric_name, value FROM metrics_daily WHERE date = ?",
                (yesterday,)
            ).fetchall()
            conn.close()
            return {r[0]: r[1] for r in rows}
        except Exception:
            return {}

    def get_recent_sessions(self, days: int = 1) -> list:
        """Pull recent sessions for briefing context."""
        if not self.available:
            return []
        try:
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            conn = self._conn()
            rows = conn.execute("""
                SELECT kind, summary, start_ts, source_tool
                FROM sessions
                WHERE start_ts > ?
                ORDER BY start_ts DESC
                LIMIT 20
            """, (cutoff,)).fetchall()
            conn.close()
            return [
                {"kind": r[0], "summary": r[1], "start_ts": r[2], "source": r[3]}
                for r in rows
            ]
        except Exception:
            return []

    def write_daily_rollup(self, briefing_date, task_stats, browser, commits, narrative):
        """Write one daily_rollup row summarizing the entire day."""
        if not self.available:
            return
        try:
            conn = self._conn()
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()}

            if "daily_rollups" not in tables:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS daily_rollups (
                        id               INTEGER PRIMARY KEY AUTOINCREMENT,
                        date             TEXT NOT NULL UNIQUE,
                        focus_score      REAL,
                        open_tasks       INTEGER,
                        done_tasks       INTEGER,
                        commits          INTEGER,
                        briefing_summary TEXT,
                        top_priorities   TEXT,
                        created_at       TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
                    )
                """)

            conn.execute("""
                INSERT INTO daily_rollups
                    (date, focus_score, open_tasks, done_tasks, commits, briefing_summary, top_priorities)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    focus_score      = excluded.focus_score,
                    open_tasks       = excluded.open_tasks,
                    done_tasks       = excluded.done_tasks,
                    commits          = excluded.commits,
                    briefing_summary = excluded.briefing_summary,
                    top_priorities   = excluded.top_priorities
            """, (
                briefing_date,
                browser.get("focus_score"),
                task_stats.get("open", 0),
                task_stats.get("done", 0),
                len(commits),
                narrative.get("yesterday_summary", ""),
                json.dumps(narrative.get("top_3_priorities", [])),
            ))
            conn.commit()
            conn.close()
            print(f"  [DB] Daily rollup written for {briefing_date}")
        except Exception as e:
            print(f"  [DB] Could not write daily rollup: {e}")

    def write_briefing_metrics(self, browser, task_stats, commits):
        """Write per-metric rows to metrics_daily for today."""
        if not self.available:
            return
        try:
            today = date.today().isoformat()
            conn = self._conn()
            metrics = [
                ("briefing_focus_score",  browser.get("focus_score", 0)),
                ("briefing_open_tasks",   task_stats.get("open", 0)),
                ("briefing_done_tasks",   task_stats.get("done", 0)),
                ("briefing_unconfirmed",  task_stats.get("unconfirmed", 0)),
                ("briefing_commits",      len(commits)),
            ]
            for metric_name, value in metrics:
                existing = conn.execute(
                    "SELECT id FROM metrics_daily WHERE date=? AND metric_name=? AND source_tool='briefing'",
                    (today, metric_name)
                ).fetchone()
                if existing:
                    conn.execute("UPDATE metrics_daily SET value=? WHERE id=?", (value, existing[0]))
                else:
                    conn.execute("""
                        INSERT INTO metrics_daily (date, metric_name, value, source_tool)
                        VALUES (?, ?, ?, 'briefing')
                    """, (today, metric_name, value))
            conn.commit()
            conn.close()
            print(f"  [DB] Briefing metrics written")
        except Exception as e:
            print(f"  [DB] Could not write metrics: {e}")

# Noise domains — skip for focus stats
NOISE_DOMAINS = {
    "google.com", "googleapis.com", "gstatic.com",
    "bing.com", "duckduckgo.com", "brave.com",
    "localhost", "127.0.0.1",
}
DISTRACTION_DOMAINS = {
    "instagram.com", "facebook.com", "tiktok.com",
    "9gag.com", "twitter.com", "x.com", "netflix.com", "twitch.tv",
}

# ─────────────────────────────────────────────
# TASKS.MD — READ / WRITE / PARSE
# ─────────────────────────────────────────────

TASKS_TEMPLATE = """# Tasks

> Managed by Productivity OS — safe to edit manually.
> Unconfirmed tasks are extracted automatically and need your review.
> Mark done with [x]. Delete lines freely.

---

## High Priority
<!-- Add your most urgent tasks here -->

## Medium Priority
<!-- Day-to-day work -->

## Low Priority / Someday
<!-- Things that can wait -->

## ⚠ Unconfirmed (auto-extracted — review these)
<!-- Auto-added by briefing.py — move up, delete, or ignore -->

---
*Last updated: {date}*
"""

def ensure_tasks_file():
    """Create Tasks.md if it doesn't exist."""
    if not TASKS_FILE.exists():
        OBSIDIAN_VAULT.mkdir(parents=True, exist_ok=True)
        TASKS_FILE.write_text(
            TASKS_TEMPLATE.format(date=date.today().isoformat()),
            encoding="utf-8"
        )
        print(f"  [TASKS] Created Tasks.md at {TASKS_FILE}")

def read_tasks_raw() -> str:
    ensure_tasks_file()
    return TASKS_FILE.read_text(encoding="utf-8")

def parse_tasks(raw: str) -> dict:
    """
    Parse Tasks.md into sections.
    Returns dict: { section_name: [task_line, ...] }
    """
    sections = {}
    current_section = "misc"
    for line in raw.split("\n"):
        if line.startswith("## "):
            current_section = line[3:].strip()
            sections[current_section] = []
        elif line.strip().startswith("- ["):
            sections.setdefault(current_section, []).append(line.strip())
    return sections

def get_all_task_texts(raw: str) -> list[str]:
    """Extract plain text of all tasks (for dedup checks)."""
    texts = []
    for line in raw.split("\n"):
        stripped = line.strip()
        if stripped.startswith("- [ ]") or stripped.startswith("- [x]"):
            # Remove checkbox, tags, metadata
            text = re.sub(r"^- \[.\]\s*", "", stripped)
            text = re.sub(r"#\w+:[^\s]+", "", text).strip()
            text = re.sub(r"⚠\s*", "", text).strip()
            text = re.sub(r"<!--.*?-->", "", text).strip()
            texts.append(text.lower())
    return texts

def append_unconfirmed_tasks(new_tasks: list[str], source: str):
    """
    Append newly found tasks to the Unconfirmed section of Tasks.md.
    Skips tasks that are too similar to existing ones.
    """
    if not new_tasks:
        return 0

    raw = read_tasks_raw()
    existing_texts = get_all_task_texts(raw)

    today = date.today().isoformat()
    added = []

    for task in new_tasks:
        task_clean = task.strip().lstrip("-").strip()
        if not task_clean:
            continue
        # Simple dedup: skip if very similar text already exists
        task_lower = task_clean.lower()
        if any(_similarity(task_lower, e) > 0.7 for e in existing_texts):
            continue
        # Store source compactly — just what's needed for triage display
        short_source = source.split(":")[-1][:35]  # last part, trimmed
        line = f"- [ ] ⚠ {task_clean} <!-- {short_source} {today} -->"
        added.append(line)
        existing_texts.append(task_lower)  # prevent dupes within this batch

    if not added:
        return 0

    # Find Unconfirmed section and append after it
    unconfirmed_marker = "## ⚠ Unconfirmed"
    if unconfirmed_marker not in raw:
        raw += f"\n\n{unconfirmed_marker} (auto-extracted — review these)\n"

    insert_after = raw.find(unconfirmed_marker)
    # Find end of that header line
    line_end = raw.find("\n", insert_after) + 1
    insertion = "\n".join(added) + "\n"
    raw = raw[:line_end] + insertion + raw[line_end:]

    # Update "last updated" line
    raw = re.sub(r"\*Last updated:.*?\*", f"*Last updated: {today}*", raw)

    TASKS_FILE.write_text(raw, encoding="utf-8")
    return len(added)

def _similarity(a: str, b: str) -> float:
    """Very lightweight similarity — word overlap ratio."""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    return len(words_a & words_b) / max(len(words_a), len(words_b))

def clean_task_text(line: str) -> str:
    """Strip checkbox, tags, and unconfirmed marker from a task line."""
    text = re.sub(r"^- \[.\]\s*", "", line.strip())
    text = re.sub(r"#\w+:[^\s]+", "", text).strip()
    text = re.sub(r"⚠\s*unconfirmed\s*—\s*", "", text).strip()
    return text

def count_open_tasks(raw: str) -> dict:
    """Parse Tasks.md into sections, returning all tasks by priority."""
    open_count = 0
    done_count = 0
    unconfirmed_count = 0
    tasks_by_section = {
        "high": [],
        "medium": [],
        "low": [],
        "unconfirmed": [],
    }
    current_section = None

    for line in raw.split("\n"):
        stripped = line.strip()

        if "## High Priority" in line:
            current_section = "high"
        elif "## Medium Priority" in line:
            current_section = "medium"
        elif "## Low Priority" in line:
            current_section = "low"
        elif "## ⚠ Unconfirmed" in line:
            current_section = "unconfirmed"
        elif line.startswith("## "):
            current_section = None

        if stripped.startswith("- [ ]"):
            open_count += 1
            text = clean_task_text(stripped)
            if "⚠" in stripped or current_section == "unconfirmed":
                unconfirmed_count += 1
                tasks_by_section["unconfirmed"].append(text)
            elif current_section in tasks_by_section:
                tasks_by_section[current_section].append(text)
        elif stripped.startswith("- [x]"):
            done_count += 1

    return {
        "open": open_count,
        "done": done_count,
        "unconfirmed": unconfirmed_count,
        "high_priority": tasks_by_section["high"],
        "medium_priority": tasks_by_section["medium"],
        "low_priority": tasks_by_section["low"],
        "unconfirmed_tasks": tasks_by_section["unconfirmed"][:5],
    }

def get_stale_tasks(raw: str, stale_days: int = 3) -> list[str]:
    """Find tasks added more than N days ago that are still open."""
    stale = []
    today = date.today()
    for line in raw.split("\n"):
        stripped = line.strip()
        if not stripped.startswith("- [ ]"):
            continue
        if "⚠ unconfirmed" in stripped:
            continue
        match = re.search(r"#added:(\d{4}-\d{2}-\d{2})", stripped)
        if match:
            added_date = date.fromisoformat(match.group(1))
            age = (today - added_date).days
            if age >= stale_days:
                text = re.sub(r"^- \[ \]\s*", "", stripped)
                text = re.sub(r"#\w+:[^\s]+", "", text).strip()
                stale.append(f"{text} (sitting {age}d)")
    return stale

# ─────────────────────────────────────────────
# OBSIDIAN NOTE SCANNING
# ─────────────────────────────────────────────

def get_recent_notes(folder: Path, days: int) -> list[dict]:
    """Return notes modified within the last N days."""
    if not folder.exists():
        return []
    cutoff = datetime.now() - timedelta(days=days)
    notes = []
    for f in folder.glob("*.md"):
        if f.stat().st_mtime > cutoff.timestamp():
            notes.append({
                "path": f,
                "name": f.stem,
                "content": f.read_text(encoding="utf-8", errors="ignore"),
                "mtime": datetime.fromtimestamp(f.stat().st_mtime),
            })
    return sorted(notes, key=lambda x: x["mtime"], reverse=True)

# ─────────────────────────────────────────────
# GIT LOG
# ─────────────────────────────────────────────

def get_git_log(repo: Path, days: int = 1) -> list[dict]:
    """Get recent commits from a repo."""
    if not repo.exists():
        return []
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        result = subprocess.run(
            ["git", "log", f"--since={since}", "--oneline", "--no-merges"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=10,
        )
        commits = []
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                parts = line.strip().split(" ", 1)
                commits.append({
                    "hash": parts[0],
                    "message": parts[1] if len(parts) > 1 else "",
                    "repo": repo.name,
                })
        return commits
    except Exception:
        return []

def get_all_recent_commits(days: int = 1) -> list[dict]:
    commits = []
    for repo in GIT_REPOS:
        commits.extend(get_git_log(repo, days))
    return commits

# ─────────────────────────────────────────────
# BROWSER HISTORY — quick stats only
# ─────────────────────────────────────────────

def get_browser_stats(days: int = 1) -> dict:
    """Pull quick focus stats from Brave history."""
    if not BRAVE_HISTORY.exists():
        return {}
    try:
        shutil.copy2(str(BRAVE_HISTORY), str(BRAVE_HISTORY_TMP))
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_ts = int((cutoff - datetime(1601, 1, 1)).total_seconds() * 1_000_000)

        conn = sqlite3.connect(str(BRAVE_HISTORY_TMP))
        rows = conn.execute("""
            SELECT u.url, u.title, v.visit_time
            FROM visits v JOIN urls u ON v.url = u.id
            WHERE v.visit_time > ?
            ORDER BY v.visit_time DESC
        """, (cutoff_ts,)).fetchall()
        conn.close()
        BRAVE_HISTORY_TMP.unlink(missing_ok=True)

        domain_counts = Counter()
        distraction_count = 0
        productive_count = 0

        for url, title, _ in rows:
            try:
                domain = urlparse(url).netloc.replace("www.", "")
            except Exception:
                continue
            if not domain or any(n in domain for n in NOISE_DOMAINS):
                continue
            domain_counts[domain] += 1
            if any(d in domain for d in DISTRACTION_DOMAINS):
                distraction_count += 1
            else:
                productive_count += 1

        total = productive_count + distraction_count
        focus_score = round(productive_count / total * 100, 1) if total > 0 else 0

        top_sites = domain_counts.most_common(8)
        top_distractions = [(d, c) for d, c in domain_counts.most_common(20)
                            if any(x in d for x in DISTRACTION_DOMAINS)]

        return {
            "total_visits": len(rows),
            "focus_score": focus_score,
            "productive": productive_count,
            "distraction": distraction_count,
            "top_sites": top_sites,
            "top_distractions": top_distractions[:5],
        }
    except Exception as e:
        return {"error": str(e)}

# ─────────────────────────────────────────────
# LLM — TASK EXTRACTION
# ─────────────────────────────────────────────

def extract_tasks_from_text(text: str, source_name: str, existing_tasks: list[str]) -> list[str]:
    """
    Ask LLM to extract action items from a note.
    Returns list of task strings (plain text, no markdown).
    """
    existing_str = "\n".join(f"- {t}" for t in existing_tasks[:30]) if existing_tasks else "none"

    # Trim very long notes
    text = text[:6000]

    prompt = f"""You are extracting real action items from Karl's personal notes. Karl is a developer building a local productivity OS.

Note name: {source_name}

Note content:
{text}

Existing tasks already tracked (do NOT repeat these):
{existing_str}

STRICT RULES — a task only qualifies if it meets ALL of these:
1. References something SPECIFIC — a named project, tool, person, file, repo, or decision
   GOOD: "Build Screenpipe integration for Project 9"
   GOOD: "Re-index second brain after adding new transcripts"
   BAD:  "Use a Pomodoro timer to stay focused" (generic advice)
   BAD:  "Implement a consistent sleep schedule" (lifestyle tip, not a work task)
   BAD:  "Explore new tools" (vague, no named thing)
2. Starts with a concrete verb (Build, Fix, Add, Review, Test, Update, Run, Write, etc.)
3. Is something Karl himself needs to DO — not a recommendation or observation
4. Is NOT already in the existing tasks list

Skip entire sections titled "Recommendations", "Explore Next", "Suggestions" — these are auto-generated boilerplate.
Skip anything that sounds like generic productivity advice.
Return empty array if nothing specific qualifies.
Maximum 6 tasks.

Respond with ONLY raw JSON, no markdown, no explanation:
{{"tasks": ["Build X for project Y", "Fix Z in repo W"]}}"""

    try:
        print(f"        LLM scanning: {source_name[:50]}...", end="", flush=True)
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL_FAST, "prompt": prompt, "stream": False},
            timeout=120,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()
        raw = re.sub(r"```json\s*|```\s*", "", raw)
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            tasks = [t for t in data.get("tasks", []) if isinstance(t, str) and t.strip()]
            print(f" {len(tasks)} tasks found")
            return tasks
        else:
            print(f" no JSON in response")
    except requests.exceptions.Timeout:
        print(f" TIMEOUT (120s) — skipping")
    except Exception as e:
        print(f" ERROR: {e}")
    return []

# ─────────────────────────────────────────────
# LLM — BRIEFING NARRATIVE
# ─────────────────────────────────────────────

def generate_briefing_narrative(context: dict) -> dict:
    """
    Send full context to LLM and get a structured morning briefing.
    Returns dict with sections.
    """
    tasks_raw = context.get("tasks_raw", "")
    task_stats = context.get("task_stats", {})
    stale_tasks = context.get("stale_tasks", [])
    commits = context.get("commits", [])
    browser = context.get("browser", {})
    recent_notes = context.get("recent_note_names", [])
    new_tasks_found = context.get("new_tasks_found", 0)

    commits_str = "\n".join(f"  - [{c['repo']}] {c['message']}" for c in commits) or "  No commits yesterday."
    stale_str = "\n".join(f"  - {t}" for t in stale_tasks) or "  None — you're on top of things."
    notes_str = ", ".join(recent_notes[:6]) or "None"

    # Build full task lists by section — no tags required
    def fmt_tasks(items, limit=8):
        return "\n".join(f"  - {t}" for t in items[:limit]) or "  (none)"

    high_str   = fmt_tasks(task_stats.get("high_priority", []))
    medium_str = fmt_tasks(task_stats.get("medium_priority", []))
    low_str    = fmt_tasks(task_stats.get("low_priority", []))
    unconf_str = fmt_tasks(task_stats.get("unconfirmed_tasks", []), limit=5)

    browser_str = ""
    if browser and "focus_score" in browser:
        browser_str = f"  Focus score yesterday: {browser['focus_score']}%\n"
        if browser.get("top_distractions"):
            distractions = ", ".join(d for d, _ in browser["top_distractions"][:3])
            browser_str += f"  Top distractions: {distractions}"

    prompt = f"""You are Karl's personal productivity assistant giving him his morning briefing. Karl is a developer and builder working across multiple projects.

TASK LIST:
High Priority:
{high_str}

Medium Priority:
{medium_str}

Low Priority / Someday:
{low_str}

Unconfirmed (auto-extracted, not yet reviewed):
{unconf_str}

STATS: {task_stats.get('open', 0)} open | {task_stats.get('done', 0)} done | {task_stats.get('unconfirmed', 0)} unconfirmed

Tasks sitting 3+ days:
{stale_str}

YESTERDAY'S COMMITS:
{commits_str}

BROWSER ACTIVITY:
{browser_str or '  No data available.'}

Recently updated notes: {notes_str}
New tasks auto-extracted this run: {new_tasks_found}

Give Karl a sharp, direct morning briefing. Reference his actual task names — not generic advice. 
Top 3 priorities must come from his High Priority list by name.
Call out x.com/distractions directly if focus score is under 80%.

Respond with ONLY raw JSON on a single line, no markdown:
{{"yesterday_summary":"2-3 sentences referencing actual commit names and what shipped","open_loops":"1-2 sentences on specific tasks that need attention","focus_callout":"honest 1 sentence on yesterday's focus score and main distraction","top_3_priorities":["Exact task name from High Priority","Second exact task","Third exact task"],"watch_out":"1 specific thing Karl might be overlooking","recommendation":"1 concrete next action — name the specific task or project"}}"""

    try:
        print("       Waiting for LLM response...", end="", flush=True)
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL_SMART, "prompt": prompt, "stream": False},
            timeout=300,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()
        raw = re.sub(r"```json\s*|```\s*", "", raw)
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            print(" done")
            return json.loads(match.group(0))
        else:
            print(f" ERROR: no JSON found in response")
            print(f"       Raw response: {raw[:300]}")
    except requests.exceptions.Timeout:
        print(f" TIMEOUT (180s)")
    except Exception as e:
        print(f" ERROR: {e}")

    return {
        "yesterday_summary": "Could not generate summary — Ollama unavailable.",
        "open_loops": "",
        "focus_callout": "",
        "top_3_priorities": task_stats.get("high_priority", [])[:3],
        "watch_out": "",
        "recommendation": "",
    }

# ─────────────────────────────────────────────
# BRIEFING NOTE BUILDER
# ─────────────────────────────────────────────

def build_briefing_note(narrative: dict, context: dict) -> str:
    today = date.today()
    now = datetime.now()
    task_stats = context.get("task_stats", {})
    commits = context.get("commits", [])
    browser = context.get("browser", {})
    stale_tasks = context.get("stale_tasks", [])
    new_tasks_found = context.get("new_tasks_found", 0)

    focus_score = browser.get("focus_score", "N/A")
    focus_emoji = ""
    if isinstance(focus_score, (int, float)):
        focus_emoji = "🟢" if focus_score >= 70 else "🟡" if focus_score >= 50 else "🔴"

    top_3 = narrative.get("top_3_priorities", [])
    top_3_str = "\n".join(f"- [ ] {p}" for p in top_3) if top_3 else "- [ ] Set your priorities"

    commits_str = ""
    if commits:
        commits_str = "\n".join(f"- `{c['hash']}` [{c['repo']}] {c['message']}" for c in commits)
    else:
        commits_str = "*No commits yesterday*"

    stale_str = ""
    if stale_tasks:
        stale_str = "\n".join(f"- ⏳ {t}" for t in stale_tasks)
    else:
        stale_str = "*All tasks are recent*"

    distractions_str = ""
    if browser.get("top_distractions"):
        distractions_str = ", ".join(f"{d} ({c})" for d, c in browser["top_distractions"][:4])

    note = f"""---
date: {today.isoformat()}
time: {now.strftime("%H:%M")}
type: daily-briefing
tags:
  - briefing
  - productivity
---

# 📋 Daily Briefing — {today.strftime("%A, %B")} {today.day}

---

## Yesterday

{narrative.get('yesterday_summary', '')}

**Focus:** {focus_score}% {focus_emoji}{"  |  Distractions: " + distractions_str if distractions_str else ""}

**Commits:**
{commits_str}

---

## Open Loops

{narrative.get('open_loops', '')}

**Stale tasks (3+ days old):**
{stale_str}

---

## Focus Check

{narrative.get('focus_callout', '')}

---

## Today's Top 3

{top_3_str}

---

## Watch Out For

{narrative.get('watch_out', '')}

---

## Recommendation

{narrative.get('recommendation', '')}

---

## Task Snapshot

| | Count |
|---|---|
| Open tasks | {task_stats.get('open', 0)} |
| Done tasks | {task_stats.get('done', 0)} |
| Unconfirmed (needs review) | {task_stats.get('unconfirmed', 0)} |
| New tasks extracted today | {new_tasks_found} |

→ [[Tasks]] — edit your full task list here

---
*Generated {now.strftime("%Y-%m-%d %H:%M")} by Productivity OS*
"""
    return note

# ─────────────────────────────────────────────
# TERMINAL SUMMARY
# ─────────────────────────────────────────────

def print_terminal_summary(narrative: dict, context: dict, briefing_path: Path):
    task_stats = context.get("task_stats", {})
    browser = context.get("browser", {})
    today = date.today()

    focus_score = browser.get("focus_score", "N/A")
    focus_bar = ""
    if isinstance(focus_score, (int, float)):
        filled = int(focus_score / 10)
        focus_bar = f" [{'█' * filled}{'░' * (10 - filled)}]"

    print("\n" + "═" * 58)
    print(f"  📋  Daily Briefing — {today.strftime('%A, %B')} {today.day}")
    print("═" * 58)

    print(f"\n  Yesterday")
    print(f"  {narrative.get('yesterday_summary', 'N/A')}")

    if focus_score != "N/A":
        print(f"\n  Focus Score: {focus_score}%{focus_bar}")

    commits = context.get("commits", [])
    if commits:
        print(f"\n  Commits ({len(commits)}):")
        for c in commits[:5]:
            print(f"    [{c['repo']}] {c['message']}")

    stale = context.get("stale_tasks", [])
    if stale:
        print(f"\n  ⏳ Stale tasks ({len(stale)}):")
        for t in stale[:4]:
            print(f"    • {t}")

    print(f"\n  Focus check")
    print(f"  {narrative.get('focus_callout', 'N/A')}")

    top3 = narrative.get("top_3_priorities", [])
    if top3:
        print(f"\n  Today's Top 3:")
        for i, p in enumerate(top3, 1):
            print(f"    {i}. {p}")

    watch = narrative.get("watch_out", "")
    if watch:
        print(f"\n  ⚠  Watch out: {watch}")

    rec = narrative.get("recommendation", "")
    if rec:
        print(f"\n  💡 {rec}")

    print(f"\n  Tasks: {task_stats.get('open', 0)} open  |  "
          f"{task_stats.get('unconfirmed', 0)} unconfirmed  |  "
          f"{context.get('new_tasks_found', 0)} new extracted")

    print(f"\n  Full briefing: Briefings/{briefing_path.name}")
    print(f"  Task list:     Tasks.md")
    print("═" * 58 + "\n")

# ─────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────

def scan_notes_for_tasks(days: int, existing: list) -> tuple[int, list]:
    """
    Scan all configured folders + root files for tasks.
    Returns (total_added, updated_existing).
    """
    total_added = 0

    # Scan configured folders (time-filtered)
    for folder, label in SCAN_FOLDERS:
        if not folder.exists():
            print(f"  [{label}] folder not found: {folder}")
            continue
        notes = get_recent_notes(folder, days)
        print(f"  [{label}] {len(notes)} notes in last {days} days")
        for note in notes:
            tasks = extract_tasks_from_text(note["content"], note["name"], existing)
            added = append_unconfirmed_tasks(tasks, f"{label}:{note['name'][:30]}")
            if added:
                total_added += added
                existing = get_all_task_texts(read_tasks_raw())

    # Always scan root files regardless of age (master docs, context files)
    for filename in ROOT_ALWAYS_SCAN:
        filepath = OBSIDIAN_VAULT / filename
        if not filepath.exists():
            continue
        content = filepath.read_text(encoding="utf-8", errors="ignore")
        label = f"root:{filename[:20]}"
        print(f"  [root] scanning: {filename}")
        tasks = extract_tasks_from_text(content, filename, existing)
        added = append_unconfirmed_tasks(tasks, label)
        if added:
            total_added += added
            existing = get_all_task_texts(read_tasks_raw())

    return total_added, existing


def run_extract_only(days: int):
    """Scan recent notes and update Tasks.md with new unconfirmed tasks."""
    print(f"\n[EXTRACT] Scanning last {days} days of notes...")
    ensure_tasks_file()
    existing = get_all_task_texts(read_tasks_raw())

    total_added, _ = scan_notes_for_tasks(days, existing)

    print(f"\n  Done. {total_added} new tasks added to Tasks.md (marked unconfirmed).")
    if total_added > 0:
        print(f"  Review them at: {TASKS_FILE}")

def run_full_briefing(days: int):
    """Full morning briefing — extract tasks, pull all data, generate note + terminal output."""
    today = date.today()
    print(f"\n  Productivity OS — Daily Briefing")
    print(f"  {today.strftime('%A, %B')} {today.day}, {today.year}\n")

    # 0. Connect to shared DB (graceful fallback if unavailable)
    db = SharedDB()
    if db.available:
        print(f"  [DB] Connected to shared productivity_os.db")
        db_tasks = db.get_open_tasks()
        db_sessions = db.get_recent_sessions(days=1)
        yesterday_metrics = db.get_yesterday_metrics()
        if db_tasks:
            print(f"  [DB] {len(db_tasks)} open tasks in shared DB")
        if db_sessions:
            print(f"  [DB] {len(db_sessions)} sessions yesterday")
        if yesterday_metrics:
            git_commits = int(yesterday_metrics.get("git_commits", 0))
            focus = yesterday_metrics.get("browser_focus_score_7d") or yesterday_metrics.get("browser_focus_score")
            if git_commits:
                print(f"  [DB] Yesterday: {git_commits} commits logged by git watcher")
            if focus:
                print(f"  [DB] Yesterday focus score: {focus}%")
    else:
        db_tasks = []
        db_sessions = []
        yesterday_metrics = {}
        print(f"  [DB] Shared DB not found — running in standalone mode")

    # 1. Ensure Tasks.md exists
    ensure_tasks_file()

    # 2. Extract tasks from recent notes
    print("[1/4] Scanning notes for new tasks...")
    existing = get_all_task_texts(read_tasks_raw())
    total_new = 0

    total_new, existing = scan_notes_for_tasks(days, existing)
    print(f"       {total_new} new tasks found and added as unconfirmed")

    # 3. Pull all data
    print("[2/4] Pulling git, browser, and task data...")
    commits = get_all_recent_commits(days=1)
    browser = get_browser_stats(days=1)
    tasks_raw = read_tasks_raw()
    task_stats = count_open_tasks(tasks_raw)
    stale_tasks = get_stale_tasks(tasks_raw, stale_days=3)

    # Enrich commits with git watcher data if available
    if not commits and yesterday_metrics.get("git_commits"):
        print(f"       (git watcher logged {int(yesterday_metrics['git_commits'])} commits yesterday)")

    recent_notes = (
        get_recent_notes(TRANSCRIPTS_FOLDER, 3) +
        get_recent_notes(BROWSER_REPORTS_FOLDER, 3)
    )
    note_names = [n["name"] for n in recent_notes]

    # Enrich context with DB sessions summary
    sessions_summary = ""
    if db_sessions:
        kinds = [s["kind"] for s in db_sessions if s.get("kind")]
        kind_counts = {}
        for k in kinds:
            kind_counts[k] = kind_counts.get(k, 0) + 1
        sessions_summary = ", ".join(f"{v}x {k}" for k, v in kind_counts.items())

    print(f"       {len(commits)} commits | {task_stats['open']} open tasks | focus: {browser.get('focus_score', 'N/A')}%")
    if db_tasks:
        print(f"       {len(db_tasks)} tasks in shared DB ({sum(1 for t in db_tasks if t['priority']=='high')} high priority)")

    # 4. Generate narrative
    print("[3/4] Generating briefing with LLM...")
    context = {
        "tasks_raw": tasks_raw,
        "task_stats": task_stats,
        "stale_tasks": stale_tasks,
        "commits": commits,
        "browser": browser,
        "recent_note_names": note_names,
        "new_tasks_found": total_new,
        "db_tasks": db_tasks,
        "db_sessions": db_sessions,
        "sessions_summary": sessions_summary,
        "yesterday_metrics": yesterday_metrics,
    }
    narrative = generate_briefing_narrative(context)

    # 5. Save briefing note to Obsidian
    print("[4/4] Saving briefing to Obsidian...")
    BRIEFINGS_FOLDER.mkdir(parents=True, exist_ok=True)
    note_content = build_briefing_note(narrative, context)
    briefing_filename = f"{today.isoformat()} Daily Briefing.md"
    briefing_path = BRIEFINGS_FOLDER / briefing_filename
    briefing_path.write_text(note_content, encoding="utf-8")
    print(f"       Saved: Briefings/{briefing_filename}")

    # 6. Write to shared DB
    if db.available:
        db.write_daily_rollup(today.isoformat(), task_stats, browser, commits, narrative)
        db.write_briefing_metrics(browser, task_stats, commits)

    # 7. Print terminal summary
    print_terminal_summary(narrative, context, briefing_path)

def run_tasks_only():
    """Print current Tasks.md to terminal in a clean format."""
    ensure_tasks_file()
    raw = read_tasks_raw()
    task_stats = count_open_tasks(raw)
    stale = get_stale_tasks(raw, stale_days=3)

    print("\n" + "═" * 58)
    print("  📝  Current Tasks")
    print("═" * 58)

    current_section = None
    for line in raw.split("\n"):
        if line.startswith("## "):
            current_section = line[3:].strip()
            print(f"\n  {line.strip()}")
        elif line.strip().startswith("- [ ]"):
            text = re.sub(r"#\w+:[^\s]+", "", line).strip()
            print(f"  {text}")
        elif line.strip().startswith("- [x]"):
            text = re.sub(r"#\w+:[^\s]+", "", line).strip()
            print(f"  {text}")

    print(f"\n  Open: {task_stats['open']}  |  Done: {task_stats['done']}  |  "
          f"Unconfirmed: {task_stats['unconfirmed']}")
    if stale:
        print(f"  Stale (3+ days): {len(stale)}")
    print("═" * 58 + "\n")


# ─────────────────────────────────────────────
# TRIAGE MODE
# ─────────────────────────────────────────────

def run_triage():
    """
    Interactive single-keypress triage of unconfirmed tasks.
    h=High  m=Medium  l=Low  d=Delete/dismiss  s=Skip
    """
    import msvcrt  # Windows only

    ensure_tasks_file()
    raw = read_tasks_raw()

    # Collect unconfirmed tasks with their line indices
    lines = raw.split("\n")
    unconfirmed = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("- [ ]") and "⚠" in stripped:
            # Extract clean task text
            text = re.sub(r"^- \[ \]\s*⚠\s*", "", stripped)
            text = re.sub(r"<!--.*?-->", "", text).strip()
            source = ""
            src_match = re.search(r"<!--(.*?)-->", stripped)
            if src_match:
                source = src_match.group(1).strip()
            unconfirmed.append({"idx": i, "text": text, "source": source, "line": line})

    if not unconfirmed:
        print("\n  No unconfirmed tasks to triage.\n")
        return

    print("\n" + "═" * 58)
    print(f"  📋  Triage — {len(unconfirmed)} unconfirmed tasks")
    print("  h=High  m=Medium  l=Low  d=Dismiss  s=Skip  q=Quit")
    print("═" * 58)

    moves = []  # list of (line_idx, action)
    skipped = 0

    for i, task in enumerate(unconfirmed):
        print(f"\n  [{i+1}/{len(unconfirmed)}] {task['text']}")
        if task["source"]:
            print(f"         from: {task['source']}")
        print("  > ", end="", flush=True)

        while True:
            key = msvcrt.getwch().lower()
            if key in ("h", "m", "l", "d", "s", "q"):
                break

        if key == "q":
            print("q — quitting triage")
            break
        elif key == "s":
            print("s — skipped")
            skipped += 1
            continue
        elif key == "d":
            print("d — dismissed")
            moves.append((task["idx"], "dismiss", task["text"]))
        else:
            section = {"h": "High Priority", "m": "Medium Priority", "l": "Low Priority / Someday"}[key]
            label = {"h": "High ↑", "m": "Medium", "l": "Low ↓"}[key]
            print(f"{key} — {label}")
            moves.append((task["idx"], section, task["text"]))

    if not moves:
        print("\n  Nothing changed.\n")
        return

    # Apply all moves to Tasks.md
    raw = read_tasks_raw()
    lines = raw.split("\n")

    # Collect line indices to remove (processed tasks)
    indices_to_remove = {m[0] for m in moves}

    # Build new tasks to insert into sections
    section_additions = {}
    dismissed_count = 0
    for line_idx, action, text in moves:
        if action == "dismiss":
            # Replace with [x] version so dedup remembers it
            lines[line_idx] = f"- [x] ⚠ {text} <!-- dismissed {date.today().isoformat()} -->"
            dismissed_count += 1
        else:
            lines[line_idx] = ""  # remove from unconfirmed
            section_additions.setdefault(action, []).append(f"- [ ] {text} #added:{date.today().isoformat()}")

    # Insert into target sections
    new_lines = []
    for line in lines:
        new_lines.append(line)
        for section, tasks in section_additions.items():
            if line.strip() == f"## {section}":
                for t in tasks:
                    new_lines.append(t)
                section_additions[section] = []  # only insert once

    # Clean up empty lines left by removals
    result = "\n".join(l for l in new_lines)
    result = re.sub(r"\n{4,}", "\n\n\n", result)

    today_str = date.today().isoformat()
    result = re.sub(r"\*Last updated:.*?\*", f"*Last updated: {today_str}*", result)
    TASKS_FILE.write_text(result, encoding="utf-8")

    promoted = len(moves) - dismissed_count
    print(f"\n  Done. {promoted} tasks promoted | {dismissed_count} dismissed | {skipped} skipped")
    print(f"  Tasks.md updated — refresh Obsidian to see changes\n")

# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Daily Briefing — Karl's Productivity OS"
    )
    parser.add_argument(
        "--extract", action="store_true",
        help="Scan notes and update Tasks.md only (no briefing)"
    )
    parser.add_argument(
        "--tasks", action="store_true",
        help="Print current Tasks.md to terminal"
    )
    parser.add_argument(
        "--triage", action="store_true",
        help="Interactively sort unconfirmed tasks (h/m/l/d/s)"
    )
    parser.add_argument(
        "--days", type=int, default=SCAN_DAYS_DEFAULT,
        help=f"Days to scan for new tasks (default: {SCAN_DAYS_DEFAULT})"
    )
    args = parser.parse_args()

    if args.tasks:
        run_tasks_only()
    elif args.extract:
        run_extract_only(args.days)
    elif args.triage:
        run_triage()
    else:
        run_full_briefing(args.days)
