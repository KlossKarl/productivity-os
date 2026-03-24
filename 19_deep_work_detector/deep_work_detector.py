"""
Deep Work Detector
Karl's Productivity OS - Project 19

Correlates browser sessions (high focus) + git coding sessions within
rolling 30-minute windows. Scores blocks as "deep work" if they meet
the threshold. Logs deep_work sessions to the shared DB.

Runs as a scheduled task every 30 minutes, or on-demand.

Usage:
    python deep_work_detector.py              # run detection + log results
    python deep_work_detector.py --today      # show today's deep work summary
    python deep_work_detector.py --week       # show last 7 days
    python deep_work_detector.py --install    # register as scheduled task
"""

import sys
import json
import sqlite3
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, date, timedelta

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

SHARED_DB   = Path(r"C:\Users\Karl\Documents\productivity_os.db")
SCRIPT_DIR  = Path(__file__).parent

# A window counts as deep work if it has:
# - At least 1 coding session (git commit), OR
# - A browser focus score >= this threshold with no distractions
FOCUS_SCORE_THRESHOLD   = 65.0   # minimum browser focus % to count
WINDOW_MINUTES          = 30     # rolling window size
MIN_DEEP_WORK_MINUTES   = 20     # minimum continuous time to count as deep work

# ─────────────────────────────────────────────
# DB HELPERS
# ─────────────────────────────────────────────

def get_conn():
    if not SHARED_DB.exists():
        print(f"[ERROR] Shared DB not found: {SHARED_DB}")
        print("        Run at least one tool first to create it.")
        sys.exit(1)
    return sqlite3.connect(str(SHARED_DB))

def ensure_deep_work_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS deep_work_blocks (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT NOT NULL,
            start_ts        TEXT NOT NULL,
            end_ts          TEXT,
            duration_min    REAL,
            score           REAL,
            had_commits     INTEGER DEFAULT 0,
            commit_count    INTEGER DEFAULT 0,
            focus_score     REAL,
            kind            TEXT DEFAULT 'deep_work',
            notes           TEXT,
            created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
    """)
    conn.commit()

def already_logged(conn, start_ts: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM deep_work_blocks WHERE start_ts = ?", (start_ts,)
    ).fetchone()
    return row is not None

# ─────────────────────────────────────────────
# DATA FETCHING
# ─────────────────────────────────────────────

def get_sessions(conn, days: int = 1) -> list:
    """Pull recent sessions from the shared DB."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT kind, start_ts, end_ts, summary, source_tool, extra_json
        FROM sessions
        WHERE start_ts > ?
        ORDER BY start_ts ASC
    """, (cutoff,)).fetchall()

    sessions = []
    for kind, start_ts, end_ts, summary, source_tool, extra_json in rows:
        extra = {}
        if extra_json:
            try:
                extra = json.loads(extra_json)
            except Exception:
                pass
        sessions.append({
            "kind":        kind,
            "start_ts":    start_ts,
            "end_ts":      end_ts,
            "summary":     summary or "",
            "source_tool": source_tool or "",
            "extra":       extra,
        })
    return sessions

def get_daily_metrics(conn, target_date: str) -> dict:
    """Pull all metrics for a given date."""
    rows = conn.execute(
        "SELECT metric_name, value FROM metrics_daily WHERE date = ?",
        (target_date,)
    ).fetchall()
    return {r[0]: r[1] for r in rows}

# ─────────────────────────────────────────────
# DEEP WORK DETECTION
# ─────────────────────────────────────────────

def parse_ts(ts: str) -> datetime | None:
    """Parse ISO timestamp, return None on failure."""
    if not ts:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ts[:26], fmt)
        except ValueError:
            continue
    return None

def score_window(coding_sessions: list, focus_score: float | None) -> float:
    """
    Score a time window as deep work. Returns 0-100.
    - Base: browser focus score (if available)
    - Bonus: +20 per coding session (git commits = strong signal)
    - Penalty: if focus score is below threshold and no commits
    """
    score = 0.0

    if focus_score is not None:
        score += focus_score * 0.6  # browser focus is 60% of score

    commit_bonus = min(len(coding_sessions) * 20, 40)  # up to +40 for commits
    score += commit_bonus

    # Hard floor: no commits + low focus = not deep work
    if not coding_sessions and (focus_score is None or focus_score < FOCUS_SCORE_THRESHOLD):
        score = 0.0

    return round(min(score, 100.0), 1)

def detect_deep_work_blocks(sessions: list, daily_metrics: dict) -> list:
    """
    Find deep work blocks by looking for windows where:
    - There are coding sessions (git commits), OR
    - Browser focus is high + sustained duration

    Returns list of detected blocks.
    """
    blocks = []

    # Get focus score from metrics
    focus_score = (
        daily_metrics.get("browser_focus_score_7d") or
        daily_metrics.get("browser_focus_score") or
        daily_metrics.get("briefing_focus_score")
    )

    # Separate session types
    coding_sessions = [s for s in sessions if s["kind"] == "coding"]
    browser_sessions = [s for s in sessions if s["kind"] in ("browsing", "browser")]
    listening_sessions = [s for s in sessions if s["kind"] == "listening"]

    # ── Strategy 1: Each coding session = a deep work block
    for s in coding_sessions:
        start = parse_ts(s["start_ts"])
        if not start:
            continue

        commits = s["extra"].get("commits", 1)
        summary = s["summary"] or f"Coding session: {commits} commit(s)"

        block_score = score_window([s], focus_score)
        if block_score < 40:
            continue

        # Estimate duration: 20 min per commit, capped at 90
        duration = min(commits * 20, 90)

        blocks.append({
            "date":         start.date().isoformat(),
            "start_ts":     s["start_ts"],
            "end_ts":       (start + timedelta(minutes=duration)).isoformat(),
            "duration_min": duration,
            "score":        block_score,
            "had_commits":  1,
            "commit_count": commits,
            "focus_score":  focus_score,
            "notes":        summary,
        })

    # ── Strategy 2: If daily focus score is high and there were sessions, log a focus block
    if focus_score and focus_score >= FOCUS_SCORE_THRESHOLD and not coding_sessions:
        # Check if there's substantial activity today
        total_sessions = len(sessions)
        if total_sessions >= 2:
            earliest = min(
                (parse_ts(s["start_ts"]) for s in sessions if parse_ts(s["start_ts"])),
                default=None
            )
            if earliest:
                block_score = score_window([], focus_score)
                if block_score >= 40:
                    blocks.append({
                        "date":         earliest.date().isoformat(),
                        "start_ts":     earliest.isoformat(),
                        "end_ts":       None,
                        "duration_min": MIN_DEEP_WORK_MINUTES,
                        "score":        block_score,
                        "had_commits":  0,
                        "commit_count": 0,
                        "focus_score":  focus_score,
                        "notes":        f"High focus session — {focus_score}% focus score, {total_sessions} activity sessions",
                    })

    return blocks

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

def log_blocks_to_db(conn, blocks: list) -> int:
    """Write detected blocks to deep_work_blocks table. Returns count of new blocks."""
    ensure_deep_work_table(conn)
    new_count = 0

    for b in blocks:
        if already_logged(conn, b["start_ts"]):
            continue
        conn.execute("""
            INSERT INTO deep_work_blocks
                (date, start_ts, end_ts, duration_min, score, had_commits,
                 commit_count, focus_score, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            b["date"], b["start_ts"], b["end_ts"], b["duration_min"],
            b["score"], b["had_commits"], b["commit_count"],
            b["focus_score"], b["notes"],
        ))

        # Also write to sessions table as kind=deep_work
        conn.execute("""
            INSERT INTO sessions (start_ts, source_tool, kind, summary, extra_json)
            VALUES (?, 'deep_work_detector', 'deep_work', ?, ?)
        """, (
            b["start_ts"],
            b["notes"],
            json.dumps({"score": b["score"], "had_commits": b["had_commits"],
                        "focus_score": b["focus_score"]}),
        ))

        # Write metric
        conn.execute("""
            INSERT INTO metrics_daily (date, metric_name, value, source_tool, notes)
            VALUES (?, 'deep_work_minutes', ?, 'deep_work_detector', ?)
            ON CONFLICT DO NOTHING
        """, (b["date"], b["duration_min"], b["notes"][:100] if b["notes"] else ""))

        new_count += 1

    conn.commit()
    return new_count

# ─────────────────────────────────────────────
# DISPLAY
# ─────────────────────────────────────────────

def show_summary(days: int = 1):
    conn = get_conn()
    ensure_deep_work_table(conn)

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT date, start_ts, duration_min, score, had_commits, commit_count, focus_score, notes
        FROM deep_work_blocks
        WHERE date >= ?
        ORDER BY start_ts ASC
    """, (cutoff,)).fetchall()
    conn.close()

    label = "Today" if days == 1 else f"Last {days} days"
    print(f"\n{'═'*58}")
    print(f"  🧠  Deep Work — {label}")
    print(f"{'═'*58}\n")

    if not rows:
        print("  No deep work blocks detected yet.")
        print("  Make some commits or run a browser analysis to generate data.\n")
        print(f"{'═'*58}\n")
        return

    total_minutes = sum(r[2] or 0 for r in rows)
    avg_score = sum(r[3] or 0 for r in rows) / len(rows)
    total_commits = sum(r[5] or 0 for r in rows)

    print(f"  Total deep work: {total_minutes:.0f} min across {len(rows)} block(s)")
    print(f"  Avg score:       {avg_score:.0f}/100")
    print(f"  Commits logged:  {total_commits}\n")

    by_date = {}
    for row in rows:
        d = row[0]
        by_date.setdefault(d, []).append(row)

    for d, day_rows in sorted(by_date.items()):
        day_total = sum(r[2] or 0 for r in day_rows)
        print(f"  {d}  ({day_total:.0f} min)")
        for _, start_ts, duration, score, had_commits, commits, focus, notes in day_rows:
            time_str = start_ts[11:16] if start_ts else "?"
            commit_str = f" | {commits} commit(s)" if commits else ""
            focus_str = f" | focus {focus:.0f}%" if focus else ""
            bar_filled = int((score or 0) / 10)
            bar = "█" * bar_filled + "░" * (10 - bar_filled)
            print(f"    [{time_str}] [{bar}] {score:.0f}/100{commit_str}{focus_str}")
            if notes:
                print(f"           {notes[:70]}")
        print()

    print(f"{'═'*58}\n")

# ─────────────────────────────────────────────
# INSTALL
# ─────────────────────────────────────────────

def install_task():
    script_path = Path(__file__).resolve()
    python_path = sys.executable.replace("python.exe", "pythonw.exe")
    task_name   = "DeepWorkDetector"

    ps = f"""
Unregister-ScheduledTask -TaskName "{task_name}" -Confirm:$false -ErrorAction SilentlyContinue

$Action = New-ScheduledTaskAction `
    -Execute "{python_path}" `
    -Argument "{script_path}" `
    -WorkingDirectory "{script_path.parent}"

# Run every 30 minutes
$Trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 30) -Once -At (Get-Date)

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName "{task_name}" `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -RunLevel Highest `
    -Description "Productivity OS - Deep Work Detector" | Out-Null

Write-Host "Task registered: {task_name} (runs every 30 min)"
Write-Host "Start now: Start-ScheduledTask -TaskName '{task_name}'"
"""
    tmp = SCRIPT_DIR / "_install_dw.ps1"
    tmp.write_text(ps)
    result = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(tmp)],
        capture_output=True, text=True
    )
    tmp.unlink(missing_ok=True)
    print(result.stdout)
    if result.returncode != 0:
        print(f"[ERROR] {result.stderr}")

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def run_detection(verbose: bool = True):
    conn = get_conn()
    ensure_deep_work_table(conn)

    today = date.today().isoformat()
    sessions = get_sessions(conn, days=1)
    daily_metrics = get_daily_metrics(conn, today)

    if verbose:
        print(f"\n[Deep Work Detector] {datetime.now().strftime('%H:%M')}")
        print(f"  Sessions found:  {len(sessions)}")
        print(f"  Focus score:     {daily_metrics.get('browser_focus_score_7d') or daily_metrics.get('browser_focus_score', 'N/A')}%")

    blocks = detect_deep_work_blocks(sessions, daily_metrics)
    new_count = log_blocks_to_db(conn, blocks)
    conn.close()

    if verbose:
        if new_count:
            print(f"  ✓ {new_count} new deep work block(s) logged")
            for b in blocks:
                print(f"    [{b['start_ts'][11:16]}] score={b['score']} | {b['notes'][:60]}")
        else:
            print(f"  No new blocks detected")
        print()

    return new_count

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deep Work Detector — Productivity OS")
    parser.add_argument("--today",   action="store_true", help="Show today's deep work summary")
    parser.add_argument("--week",    action="store_true", help="Show last 7 days")
    parser.add_argument("--install", action="store_true", help="Register as scheduled task (run every 30 min)")
    args = parser.parse_args()

    if args.today:
        show_summary(days=1)
    elif args.week:
        show_summary(days=7)
    elif args.install:
        install_task()
    else:
        run_detection(verbose=True)
