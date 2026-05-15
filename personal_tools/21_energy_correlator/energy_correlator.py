"""
Energy Correlator
Karl's Productivity OS - Project 21

Quick mood/energy logging that correlates with same-day productivity metrics.
Builds a model over time: "low energy days your focus drops 40%, avoid deep work."
Surfaces insights in Daily Briefing.

Usage:
    python energy_correlator.py log                    # log current energy level
    python energy_correlator.py log --level high --reason focused --note "slept well"
    python energy_correlator.py today                  # show today's energy + correlated metrics
    python energy_correlator.py insights               # show patterns across all logs
    python energy_correlator.py history                # show recent log history
"""

import sys
import json
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime, date, timedelta
from collections import defaultdict

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

SHARED_DB  = Path(r"C:\Users\Karl\Documents\productivity_os.db")
SCRIPT_DIR = Path(__file__).parent

ENERGY_LEVELS = ["low", "medium", "high"]

ONE_WORD_REASONS = [
    "focused", "tired", "stressed", "rested", "distracted",
    "motivated", "anxious", "calm", "sick", "energized",
    "sluggish", "sharp", "scattered", "flow", "blocked",
]

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
        CREATE TABLE IF NOT EXISTS energy_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            logged_at   TEXT NOT NULL,
            date        TEXT NOT NULL,
            hour        INTEGER,
            level       TEXT NOT NULL,
            reason      TEXT,
            note        TEXT,
            created_at  TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )
    """)
    conn.commit()

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

def log_energy(level: str, reason: str = None, note: str = None, silent: bool = False):
    if level not in ENERGY_LEVELS:
        print(f"[ERROR] Level must be: low, medium, high")
        sys.exit(1)

    conn = get_conn()
    ensure_tables(conn)

    now = datetime.now()
    conn.execute("""
        INSERT INTO energy_logs (logged_at, date, hour, level, reason, note)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (now.isoformat(), now.date().isoformat(), now.hour, level, reason, note))

    # Also write to metrics_daily
    level_score = {"low": 25, "medium": 60, "high": 90}[level]
    today = now.date().isoformat()
    existing = conn.execute(
        "SELECT id FROM metrics_daily WHERE date=? AND metric_name='energy_score' AND source_tool='energy_correlator'",
        (today,)
    ).fetchone()
    if existing:
        conn.execute("UPDATE metrics_daily SET value=? WHERE id=?", (level_score, existing[0]))
    else:
        conn.execute("""
            INSERT INTO metrics_daily (date, metric_name, value, source_tool, notes)
            VALUES (?, 'energy_score', ?, 'energy_correlator', ?)
        """, (today, level_score, reason or ""))

    conn.commit()
    conn.close()

    if not silent:
        emoji = {"low": "🔴", "medium": "🟡", "high": "🟢"}[level]
        print(f"\n  {emoji} Energy logged: {level.upper()}")
        if reason:
            print(f"     Reason: {reason}")
        if note:
            print(f"     Note:   {note}")
        print(f"     Time:   {now.strftime('%H:%M')}\n")

# ─────────────────────────────────────────────
# CORRELATION
# ─────────────────────────────────────────────

def get_day_metrics(conn, target_date: str) -> dict:
    rows = conn.execute(
        "SELECT metric_name, value FROM metrics_daily WHERE date=?",
        (target_date,)
    ).fetchall()
    return {r[0]: r[1] for r in rows}

def get_day_deep_work(conn, target_date: str) -> dict:
    try:
        rows = conn.execute(
            "SELECT COUNT(*), SUM(duration_min), AVG(score) FROM deep_work_blocks WHERE date=?",
            (target_date,)
        ).fetchone()
        return {
            "blocks":       rows[0] or 0,
            "total_min":    rows[1] or 0,
            "avg_score":    rows[2] or 0,
        }
    except Exception:
        return {"blocks": 0, "total_min": 0, "avg_score": 0}

def show_today(conn):
    today = date.today().isoformat()
    ensure_tables(conn)

    logs = conn.execute(
        "SELECT logged_at, level, reason, note FROM energy_logs WHERE date=? ORDER BY logged_at",
        (today,)
    ).fetchall()

    metrics = get_day_metrics(conn, today)
    deep_work = get_day_deep_work(conn, today)

    print(f"\n{'═'*55}")
    print(f"  ⚡  Energy — Today ({today})")
    print(f"{'═'*55}\n")

    if not logs:
        print("  No energy logs today.")
        print("  Run: python energy_correlator.py log\n")
    else:
        for logged_at, level, reason, note in logs:
            time_str = logged_at[11:16]
            emoji = {"low": "🔴", "medium": "🟡", "high": "🟢"}.get(level, "⚪")
            reason_str = f" — {reason}" if reason else ""
            note_str = f" ({note})" if note else ""
            print(f"  [{time_str}] {emoji} {level.upper()}{reason_str}{note_str}")

    print(f"\n  Today's productivity:")
    focus = metrics.get("browser_focus_score_7d") or metrics.get("browser_focus_score") or metrics.get("briefing_focus_score")
    commits = int(metrics.get("git_commits", 0))
    dw_min = deep_work["total_min"]
    dw_score = deep_work["avg_score"]

    if focus:    print(f"    Focus score:    {focus:.0f}%")
    if commits:  print(f"    Git commits:    {commits}")
    if dw_min:   print(f"    Deep work:      {dw_min:.0f} min (avg score {dw_score:.0f}/100)")
    if not any([focus, commits, dw_min]):
        print("    No productivity data yet today.")

    print(f"\n{'═'*55}\n")

# ─────────────────────────────────────────────
# INSIGHTS
# ─────────────────────────────────────────────

def show_insights(conn):
    ensure_tables(conn)

    # Get all energy logs joined with same-day metrics
    logs = conn.execute("""
        SELECT date, level, reason
        FROM energy_logs
        ORDER BY date DESC
        LIMIT 90
    """).fetchall()

    if len(logs) < 3:
        print(f"\n  Not enough data yet — log your energy for a few days first.")
        print(f"  Run: python energy_correlator.py log\n")
        return

    # Build per-day picture
    days = defaultdict(lambda: {"levels": [], "reasons": []})
    for log_date, level, reason in logs:
        days[log_date]["levels"].append(level)
        if reason:
            days[log_date]["reasons"].append(reason)

    # Correlate with metrics
    level_data = defaultdict(lambda: {
        "focus_scores": [], "commits": [], "deep_work_mins": [], "count": 0
    })

    for log_date, day in days.items():
        # Use the most common level for the day
        level_counts = {"low": 0, "medium": 0, "high": 0}
        for l in day["levels"]:
            level_counts[l] = level_counts.get(l, 0) + 1
        dominant_level = max(level_counts, key=level_counts.get)

        metrics = get_day_metrics(conn, log_date)
        deep = get_day_deep_work(conn, log_date)

        focus = metrics.get("browser_focus_score_7d") or metrics.get("browser_focus_score")
        commits = metrics.get("git_commits", 0)

        d = level_data[dominant_level]
        d["count"] += 1
        if focus:       d["focus_scores"].append(focus)
        if commits:     d["commits"].append(commits)
        if deep["total_min"]: d["deep_work_mins"].append(deep["total_min"])

    print(f"\n{'═'*55}")
    print(f"  ⚡  Energy Insights ({len(days)} days logged)")
    print(f"{'═'*55}\n")

    def avg(lst):
        return sum(lst) / len(lst) if lst else None

    rows_data = []
    for level in ["high", "medium", "low"]:
        d = level_data[level]
        if d["count"] == 0:
            continue
        focus_avg  = avg(d["focus_scores"])
        commit_avg = avg(d["commits"])
        dw_avg     = avg(d["deep_work_mins"])
        rows_data.append((level, d["count"], focus_avg, commit_avg, dw_avg))

    emoji_map = {"high": "🟢", "medium": "🟡", "low": "🔴"}

    for level, count, focus_avg, commit_avg, dw_avg in rows_data:
        emoji = emoji_map[level]
        print(f"  {emoji} {level.upper()} energy days ({count} logged)")
        if focus_avg:  print(f"     Avg focus score:  {focus_avg:.0f}%")
        if commit_avg: print(f"     Avg commits/day:  {commit_avg:.1f}")
        if dw_avg:     print(f"     Avg deep work:    {dw_avg:.0f} min")
        print()

    # Surface the most useful insight
    if len(rows_data) >= 2:
        print(f"  Key insight:")
        high_focus = next((r[2] for r in rows_data if r[0] == "high" and r[2]), None)
        low_focus  = next((r[2] for r in rows_data if r[0] == "low"  and r[2]), None)
        if high_focus and low_focus:
            diff = high_focus - low_focus
            print(f"    High energy → {diff:+.0f}% focus vs low energy days")

        high_dw = next((r[4] for r in rows_data if r[0] == "high" and r[4]), None)
        low_dw  = next((r[4] for r in rows_data if r[0] == "low"  and r[4]), None)
        if high_dw and low_dw:
            print(f"    High energy → {high_dw:.0f} min deep work vs {low_dw:.0f} min on low days")

    # Most common reasons
    all_reasons = [r for _, day in days.items() for r in day["reasons"]]
    if all_reasons:
        from collections import Counter
        top_reasons = Counter(all_reasons).most_common(3)
        print(f"\n  Most logged reasons: {', '.join(r for r, _ in top_reasons)}")

    print(f"\n{'═'*55}\n")

# ─────────────────────────────────────────────
# HISTORY
# ─────────────────────────────────────────────

def show_history(conn, limit: int = 14):
    ensure_tables(conn)

    logs = conn.execute("""
        SELECT date, logged_at, level, reason, note
        FROM energy_logs
        ORDER BY logged_at DESC
        LIMIT ?
    """, (limit * 3,)).fetchall()

    if not logs:
        print("\n  No energy logs yet.\n")
        return

    print(f"\n{'═'*55}")
    print(f"  ⚡  Energy History")
    print(f"{'═'*55}\n")

    current_date = None
    for log_date, logged_at, level, reason, note in logs:
        if log_date != current_date:
            current_date = log_date
            print(f"  {log_date}")
        emoji = {"low": "🔴", "medium": "🟡", "high": "🟢"}.get(level, "⚪")
        time_str = logged_at[11:16]
        reason_str = f" — {reason}" if reason else ""
        note_str = f" ({note})" if note else ""
        print(f"    [{time_str}] {emoji} {level}{reason_str}{note_str}")

    print(f"\n{'═'*55}\n")

# ─────────────────────────────────────────────
# INTERACTIVE LOG
# ─────────────────────────────────────────────

def interactive_log():
    """Guided interactive energy log — 3 keypresses."""
    print(f"\n{'═'*55}")
    print(f"  ⚡  Energy Check-in — {datetime.now().strftime('%H:%M')}")
    print(f"{'═'*55}\n")

    # Level
    print("  Energy level?")
    print("  [1] 🔴 Low    [2] 🟡 Medium    [3] 🟢 High")
    print()

    level = None
    while level is None:
        choice = input("  > ").strip()
        if choice == "1" or choice.lower() == "low":
            level = "low"
        elif choice == "2" or choice.lower() == "medium":
            level = "medium"
        elif choice == "3" or choice.lower() == "high":
            level = "high"
        else:
            print("  Enter 1, 2, or 3")

    # Reason
    print(f"\n  One word reason (or Enter to skip):")
    print(f"  {' | '.join(ONE_WORD_REASONS[:8])}")
    print(f"  {' | '.join(ONE_WORD_REASONS[8:])}")
    reason_input = input("\n  > ").strip().lower() or None

    # Optional note
    note_input = input("\n  Quick note (or Enter to skip): ").strip() or None

    log_energy(level, reason_input, note_input)

# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Energy Correlator — Productivity OS")
    subparsers = parser.add_subparsers(dest="command")

    # log
    log_parser = subparsers.add_parser("log", help="Log your current energy level")
    log_parser.add_argument("--level",  choices=ENERGY_LEVELS, help="Energy level")
    log_parser.add_argument("--reason", help="One-word reason")
    log_parser.add_argument("--note",   help="Optional free-text note")

    # other commands
    subparsers.add_parser("today",    help="Show today's energy + correlated metrics")
    subparsers.add_parser("insights", help="Show patterns across all logged days")
    subparsers.add_parser("history",  help="Show recent log history")

    args = parser.parse_args()
    conn = get_conn()
    ensure_tables(conn)

    if args.command == "log":
        if args.level:
            log_energy(args.level, args.reason, args.note)
        else:
            interactive_log()
    elif args.command == "today":
        show_today(conn)
    elif args.command == "insights":
        show_insights(conn)
    elif args.command == "history":
        show_history(conn)
    else:
        # No command — default to interactive log
        interactive_log()

    conn.close()
