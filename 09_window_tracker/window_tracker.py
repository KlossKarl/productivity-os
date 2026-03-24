"""
Window Activity Tracker
Karl's Productivity OS - Project 09 (lite)

Polls the active foreground window every 60 seconds.
Groups consecutive same-app windows into sessions.
Logs app sessions to the shared DB — feeds Deep Work Detector
with direct evidence of "VSCode active 47 min straight."

Usage:
    python window_tracker.py              # start tracking (runs forever)
    python window_tracker.py --today      # show today's app usage
    python window_tracker.py --week       # show last 7 days
    python window_tracker.py --install    # register as Windows startup task
"""

import sys
import json
import time
import sqlite3
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, date, timedelta
from collections import defaultdict

try:
    import pygetwindow as gw
except ImportError:
    print("[ERROR] pygetwindow not installed.")
    print("Run: pip install pygetwindow")
    sys.exit(1)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

SHARED_DB       = Path(r"C:\Users\Karl\Documents\productivity_os.db")
SCRIPT_DIR      = Path(__file__).parent
POLL_SECS       = 60        # check active window every 60 seconds
MIN_SESSION_SECS = 120      # ignore windows active for less than 2 minutes

# App categories — used for focus scoring
PRODUCTIVE_APPS = {
    "code", "vscode", "visual studio", "pycharm", "intellij",
    "terminal", "powershell", "cmd", "bash", "git",
    "obsidian", "notion", "word", "excel", "notepad",
    "cursor", "sublime", "vim", "neovim",
}

DISTRACTION_APPS = {
    "instagram", "tiktok", "facebook", "twitter",
    "9gag", "buzzfeed",
}

# Gaming is tracked but NEUTRAL — not productive, not a distraction.
# Recovery, social, and reconnection time. Doesn't penalize focus score.
GAMING_APPS = {
    "steam", "epic games", "battle.net", "origin", "ubisoft connect",
    "valorant", "league of legends", "fortnite", "minecraft",
    "xbox", "game pass", "twitch",
}

BROWSER_TITLES_PRODUCTIVE = {
    "github", "stackoverflow", "docs", "documentation", "localhost",
    "claude", "chatgpt", "ollama", "python", "tutorial",
}

# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────

def get_conn():
    if not SHARED_DB.exists():
        print(f"[ERROR] Shared DB not found: {SHARED_DB}")
        sys.exit(1)
    return sqlite3.connect(str(SHARED_DB))

def ensure_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS window_sessions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            TEXT NOT NULL,
            start_ts        TEXT NOT NULL,
            end_ts          TEXT,
            duration_secs   INTEGER DEFAULT 0,
            app_name        TEXT NOT NULL,
            window_title    TEXT,
            category        TEXT,
            is_productive   INTEGER DEFAULT 0,
            created_at      TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
    """)
    conn.commit()

# ─────────────────────────────────────────────
# APP CLASSIFICATION
# ─────────────────────────────────────────────

def get_active_window() -> dict | None:
    """Get the currently active foreground window."""
    try:
        active = gw.getActiveWindow()
        if not active:
            return None
        title = active.title or ""
        # Extract app name from title (usually "File — App Name" or just "App Name")
        app_name = extract_app_name(title)
        return {"title": title, "app_name": app_name}
    except Exception:
        return None

def extract_app_name(title: str) -> str:
    """Best-effort extraction of app name from window title."""
    if not title:
        return "unknown"

    # Common patterns: "file.py - Visual Studio Code"
    # "GitHub - Brave" etc.
    separators = [" - ", " — ", " | "]
    for sep in separators:
        if sep in title:
            parts = title.split(sep)
            # Last part is usually the app name
            return parts[-1].strip()

    return title.strip()[:50]

def classify_window(app_name: str, title: str) -> tuple[str, bool]:
    """
    Returns (category, is_productive).
    Categories: coding, browsing, communication, gaming, system, other
    """
    app_lower = app_name.lower()
    title_lower = title.lower()

    # Coding
    if any(p in app_lower for p in ["code", "vscode", "visual studio", "pycharm",
                                     "cursor", "sublime", "vim", "notepad++"]):
        return "coding", True

    # Terminal
    if any(p in app_lower for p in ["terminal", "powershell", "cmd", "bash",
                                     "windows terminal", "git"]):
        return "terminal", True

    # Browser — classify by title
    if any(p in app_lower for p in ["brave", "chrome", "firefox", "edge", "safari"]):
        is_productive = any(k in title_lower for k in BROWSER_TITLES_PRODUCTIVE)
        is_distraction = any(k in title_lower for k in DISTRACTION_APPS)
        if is_distraction:
            return "browsing_distraction", False
        if is_productive:
            return "browsing_productive", True
        return "browsing", True  # neutral browsing = productive by default

    # Notes / docs
    if any(p in app_lower for p in ["obsidian", "notion", "word", "excel",
                                     "onenote", "evernote"]):
        return "notes", True

    # Communication
    if any(p in app_lower for p in ["slack", "teams", "discord", "zoom",
                                     "outlook", "gmail"]):
        return "communication", True  # communication = productive

    # Gaming — neutral category, doesn't affect focus score either way
    if any(p in app_lower for p in ["steam", "epic", "battlenet", "battle.net",
                                     "origin", "ubisoft", "valorant", "league",
                                     "fortnite", "minecraft", "xbox", "gamepass"]):
        return "gaming", None  # None = neutral, not counted either way

    # System / OS
    if any(p in app_lower for p in ["explorer", "task manager", "settings",
                                     "control panel", "finder"]):
        return "system", True

    # Distraction check on app name
    if any(d in app_lower for d in DISTRACTION_APPS):
        return "distraction", False

    return "other", True

# ─────────────────────────────────────────────
# SESSION TRACKING
# ─────────────────────────────────────────────

def log_session(conn, app_name: str, title: str, start_ts: str,
                end_ts: str, duration_secs: int):
    """Write a completed window session to the DB."""
    if duration_secs < MIN_SESSION_SECS:
        return  # skip very short windows

    category, is_productive = classify_window(app_name, title)
    today = start_ts[:10]

    # is_productive: True = productive, False = distraction, None = neutral (gaming etc.)
    productive_flag = 1 if is_productive is True else 0

    ensure_tables(conn)
    conn.execute("""
        INSERT INTO window_sessions
            (date, start_ts, end_ts, duration_secs, app_name, window_title, category, is_productive)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (today, start_ts, end_ts, duration_secs, app_name, title[:200], category, productive_flag))

    # Also log to shared sessions table
    try:
        conn.execute("""
            INSERT INTO sessions (start_ts, source_tool, kind, summary, extra_json)
            VALUES (?, 'window_tracker', ?, ?, ?)
        """, (
            start_ts,
            category,
            f"{app_name} — {duration_secs // 60} min",
            json.dumps({
                "app_name": app_name,
                "duration_secs": duration_secs,
                "is_productive": is_productive,
                "category": category,
            })
        ))
    except Exception:
        pass

    # Update daily metrics — gaming is neutral, skip it for focus metrics
    try:
        if is_productive is not None:
            today_date = today
            metric = "productive_app_minutes" if is_productive else "distraction_app_minutes"
            minutes = duration_secs / 60
            existing = conn.execute(
                "SELECT id, value FROM metrics_daily WHERE date=? AND metric_name=? AND source_tool='window_tracker'",
                (today_date, metric)
            ).fetchone()
            if existing:
                conn.execute("UPDATE metrics_daily SET value=? WHERE id=?",
                            (existing[1] + minutes, existing[0]))
            else:
                conn.execute("""
                    INSERT INTO metrics_daily (date, metric_name, value, source_tool, notes)
                    VALUES (?, ?, ?, 'window_tracker', ?)
                """, (today_date, metric, minutes, app_name))
    except Exception:
        pass

    conn.commit()

# ─────────────────────────────────────────────
# MAIN POLLING LOOP
# ─────────────────────────────────────────────

def run_tracker():
    conn = get_conn()
    ensure_tables(conn)

    print(f"[Window Tracker] Started — polling every {POLL_SECS}s")
    print(f"  DB: {SHARED_DB}")
    print(f"  Sessions under {MIN_SESSION_SECS}s are ignored")
    print(f"  Press Ctrl+C to stop\n")

    current_app   = None
    current_title = None
    session_start = None

    while True:
        try:
            window = get_active_window()
            now = datetime.now()
            now_ts = now.isoformat()

            if window:
                app_name = window["app_name"]
                title    = window["title"]

                if app_name != current_app:
                    # App switched — close previous session
                    if current_app and session_start:
                        duration = int((now - session_start).total_seconds())
                        log_session(conn, current_app, current_title or "",
                                   session_start.isoformat(), now_ts, duration)
                        category, productive = classify_window(current_app, current_title or "")
                        mins = duration // 60
                        if mins > 0:
                            if productive is None:
                                prod_str = "~"  # neutral — gaming/recovery
                            else:
                                prod_str = "✓" if productive else "✗"
                            print(f"  [{now.strftime('%H:%M')}] {prod_str} {current_app} — {mins}m [{category}]")

                    # Start new session
                    current_app   = app_name
                    current_title = title
                    session_start = now

            time.sleep(POLL_SECS)

        except KeyboardInterrupt:
            # Clean shutdown — save current session
            if current_app and session_start:
                duration = int((datetime.now() - session_start).total_seconds())
                log_session(conn, current_app, current_title or "",
                           session_start.isoformat(), datetime.now().isoformat(), duration)
            conn.close()
            print("\n[Window Tracker] Stopped.")
            break
        except Exception as e:
            print(f"  [WARN] {e}")
            time.sleep(POLL_SECS)

# ─────────────────────────────────────────────
# DISPLAY
# ─────────────────────────────────────────────

def show_summary(days: int = 1):
    conn = get_conn()
    ensure_tables(conn)

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute("""
        SELECT app_name, category, SUM(duration_secs), is_productive
        FROM window_sessions
        WHERE date >= ?
        GROUP BY app_name, is_productive
        ORDER BY SUM(duration_secs) DESC
    """, (cutoff,)).fetchall()

    conn.close()

    label = "Today" if days == 1 else f"Last {days} days"
    print(f"\n{'═'*55}")
    print(f"  🖥️   App Usage — {label}")
    print(f"{'═'*55}\n")

    if not rows:
        print("  No window data yet.")
        print("  Run: python window_tracker.py\n")
        print(f"{'═'*55}\n")
        return

    total_secs = sum(r[2] for r in rows)
    productive_secs = sum(r[2] for r in rows if r[3] == 1)
    distraction_secs = sum(r[2] for r in rows if r[3] == 0 and r[1] != "gaming")
    focus_pct = round(productive_secs / (productive_secs + distraction_secs) * 100) if (productive_secs + distraction_secs) else 0

    print(f"  Total tracked: {total_secs // 3600}h {(total_secs % 3600) // 60}m")
    print(f"  Focus score:   {focus_pct}% productive\n")

    print(f"  {'App':<30} {'Time':>8}  {'Category'}")
    print(f"  {'─'*30} {'─'*8}  {'─'*15}")

    for app_name, category, secs, is_productive in rows[:20]:
        mins = secs // 60
        hours = mins // 60
        time_str = f"{hours}h {mins % 60}m" if hours else f"{mins}m"
        if category == "gaming":
            prod_str = "~"
        else:
            prod_str = "✓" if is_productive else "✗"
        print(f"  {prod_str} {app_name[:28]:<28} {time_str:>8}  {category}")

    print(f"\n{'═'*55}\n")

# ─────────────────────────────────────────────
# INSTALL
# ─────────────────────────────────────────────

def install_task():
    script_path = Path(__file__).resolve()
    python_path = sys.executable.replace("python.exe", "pythonw.exe")
    task_name   = "WindowActivityTracker"

    ps = f"""
Unregister-ScheduledTask -TaskName "{task_name}" -Confirm:$false -ErrorAction SilentlyContinue

$Action = New-ScheduledTaskAction `
    -Execute "{python_path}" `
    -Argument "{script_path}" `
    -WorkingDirectory "{script_path.parent}"

$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName "{task_name}" `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -RunLevel Highest `
    -Description "Productivity OS - Window Activity Tracker" | Out-Null

Write-Host "Task registered: {task_name}"
Write-Host "Start now: Start-ScheduledTask -TaskName '{task_name}'"
"""
    tmp = SCRIPT_DIR / "_install_wt.ps1"
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
# CLI
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Window Activity Tracker — Productivity OS")
    parser.add_argument("--today",   action="store_true", help="Show today's app usage")
    parser.add_argument("--week",    action="store_true", help="Show last 7 days")
    parser.add_argument("--install", action="store_true", help="Register as Windows startup task")
    args = parser.parse_args()

    if args.today:
        show_summary(days=1)
    elif args.week:
        show_summary(days=7)
    elif args.install:
        install_task()
    else:
        run_tracker()
