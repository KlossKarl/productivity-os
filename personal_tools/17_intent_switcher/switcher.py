"""
Intent-Aware Environment Switcher
Karl's Productivity OS - Project 17

Declares a work mode (Build, Debug, Learn, Admin, Review) and configures
your entire environment in one shot: VSCode workspace, Obsidian notes,
focus rules, terminal layout, audio cues.

Can also INFER your mode from recent browser + git + transcript activity
using Ollama — no manual declaration needed.

Usage:
    python switcher.py                     # interactive mode picker
    python switcher.py build               # switch to Build mode
    python switcher.py debug               # switch to Debug mode
    python switcher.py learn               # switch to Learn mode
    python switcher.py admin               # switch to Admin mode
    python switcher.py review              # switch to Review mode
    python switcher.py --infer             # let Ollama pick based on recent activity
    python switcher.py --status            # show current mode + session info
    python switcher.py --history           # show recent mode history
    python switcher.py --end               # end current session, save re-entry note
"""

import os
import sys
import json
import sqlite3
import subprocess
import argparse
import requests
import webbrowser
from pathlib import Path
from datetime import datetime, timedelta

try:
    import yaml
except ImportError:
    print("[ERROR] pyyaml not installed. Run: pip install pyyaml")
    sys.exit(1)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

SCRIPT_DIR       = Path(__file__).parent
MODES_CONFIG     = SCRIPT_DIR / "modes.yaml"
SESSION_FILE     = SCRIPT_DIR / "current_session.json"
HISTORY_DB       = SCRIPT_DIR / "switcher_history.db"

OBSIDIAN_VAULT   = Path(r"C:\Users\Karl\Documents\Obsidian Vault")
VSCODE_PATH      = Path(r"C:\Users\Karl\AppData\Local\Programs\Microsoft VS Code\Code.exe")
SHARED_DB        = Path(r"C:\Users\Karl\Documents\productivity_os.db")

OLLAMA_URL       = "http://localhost:11434/api/generate"
OLLAMA_MODEL     = "llama3:8b"

BRAVE_HISTORY    = Path(r"C:\Users\Karl\AppData\Local\BraveSoftware\Brave-Browser\User Data\Default\History")

# Mode display metadata
MODE_META = {
    "build":   {"emoji": "🔨", "color": "\033[94m",  "label": "BUILD"},
    "debug":   {"emoji": "🐛", "color": "\033[91m",  "label": "DEBUG"},
    "learn":   {"emoji": "📚", "color": "\033[92m",  "label": "LEARN"},
    "admin":   {"emoji": "📋", "color": "\033[93m",  "label": "ADMIN"},
    "review":  {"emoji": "🔍", "color": "\033[95m",  "label": "REVIEW"},
}

RESET = "\033[0m"
BOLD  = "\033[1m"
DIM   = "\033[2m"

# ─────────────────────────────────────────────
# MODES CONFIG
# ─────────────────────────────────────────────

DEFAULT_MODES = {
    "build": {
        "description": "Deep coding — shipping features, writing scripts, building projects",
        "vscode_workspace": r"C:\Users\Karl\Documents\productivity-os\.vscode\productivity-os.code-workspace",
        "obsidian_notes": ["Tasks", "Projects"],
        "obsidian_open": "Tasks.md",
        "focus_level": "strict",
        "blocked_sites": ["reddit.com", "x.com", "instagram.com", "youtube.com", "twitch.tv", "netflix.com"],
        "welcome_message": "Time to ship. Distractions blocked. Let's build.",
        "terminal_commands": [],
        "git_repos": [r"C:\Users\Karl\Documents\productivity-os"],
    },
    "debug": {
        "description": "Investigating bugs, reading logs, tracing through issues",
        "vscode_workspace": r"C:\Users\Karl\Documents\productivity-os\.vscode\productivity-os.code-workspace",
        "obsidian_notes": ["Bugs", "Notes"],
        "obsidian_open": None,
        "focus_level": "moderate",
        "blocked_sites": ["instagram.com", "tiktok.com", "netflix.com"],
        "welcome_message": "Debug mode. Stack Overflow permitted. Stay systematic.",
        "terminal_commands": [],
        "git_repos": [r"C:\Users\Karl\Documents\productivity-os"],
    },
    "learn": {
        "description": "Studying, reading docs, watching tutorials, taking notes",
        "vscode_workspace": None,
        "obsidian_notes": ["Learning", "Transcripts"],
        "obsidian_open": None,
        "focus_level": "moderate",
        "blocked_sites": ["instagram.com", "tiktok.com", "netflix.com", "x.com"],
        "welcome_message": "Learn mode. YouTube whitelisted for tutorials. Take notes.",
        "terminal_commands": [],
        "git_repos": [],
    },
    "admin": {
        "description": "Email, planning, scheduling, non-coding work tasks",
        "vscode_workspace": None,
        "obsidian_notes": ["Tasks", "Briefings"],
        "obsidian_open": "Tasks.md",
        "focus_level": "light",
        "blocked_sites": ["tiktok.com", "netflix.com", "twitch.tv"],
        "welcome_message": "Admin mode. Clear the inbox, update the task list, then get back to building.",
        "terminal_commands": [],
        "git_repos": [],
    },
    "review": {
        "description": "Code review, reading PRs, reviewing docs or reports",
        "vscode_workspace": r"C:\Users\Karl\Documents\productivity-os\.vscode\productivity-os.code-workspace",
        "obsidian_notes": ["Browser Reports", "Briefings"],
        "obsidian_open": None,
        "focus_level": "moderate",
        "blocked_sites": ["instagram.com", "tiktok.com", "netflix.com"],
        "welcome_message": "Review mode. Read carefully. Flag everything worth flagging.",
        "terminal_commands": [],
        "git_repos": [],
    },
}

def load_modes() -> dict:
    if MODES_CONFIG.exists():
        with open(MODES_CONFIG, "r") as f:
            return yaml.safe_load(f) or DEFAULT_MODES
    # Write defaults on first run
    with open(MODES_CONFIG, "w") as f:
        yaml.dump(DEFAULT_MODES, f, default_flow_style=False, allow_unicode=True)
    print(f"  Created default modes config: {MODES_CONFIG}")
    return DEFAULT_MODES

# ─────────────────────────────────────────────
# SESSION PERSISTENCE
# ─────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(str(HISTORY_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at  TEXT NOT NULL,
            ended_at    TEXT,
            mode        TEXT NOT NULL,
            duration_min REAL,
            inferred    INTEGER DEFAULT 0,
            reentry_note TEXT,
            notes       TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_session(mode: str, inferred: bool = False) -> int:
    conn = sqlite3.connect(str(HISTORY_DB))
    cursor = conn.execute(
        "INSERT INTO sessions (started_at, mode, inferred) VALUES (?, ?, ?)",
        (datetime.now().isoformat(), mode, 1 if inferred else 0)
    )
    session_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return session_id

def end_session(session_id: int, reentry_note: str = ""):
    conn = sqlite3.connect(str(HISTORY_DB))
    row = conn.execute("SELECT started_at FROM sessions WHERE id=?", (session_id,)).fetchone()
    if row:
        started = datetime.fromisoformat(row[0])
        duration = (datetime.now() - started).total_seconds() / 60
        conn.execute(
            "UPDATE sessions SET ended_at=?, duration_min=?, reentry_note=? WHERE id=?",
            (datetime.now().isoformat(), round(duration, 1), reentry_note, session_id)
        )
        conn.commit()
    conn.close()

def load_current_session() -> dict | None:
    if SESSION_FILE.exists():
        return json.loads(SESSION_FILE.read_text())
    return None

def save_current_session(data: dict):
    SESSION_FILE.write_text(json.dumps(data, indent=2))

def clear_current_session():
    if SESSION_FILE.exists():
        SESSION_FILE.unlink()

# ─────────────────────────────────────────────
# RE-ENTRY NOTE
# ─────────────────────────────────────────────

def build_reentry_note(mode: str, session_data: dict) -> str:
    """
    Snapshot of the current session — what was open, what was being worked on.
    Saved to Obsidian so you can pick up exactly where you left off.
    """
    now = datetime.now()
    started = datetime.fromisoformat(session_data.get("started_at", now.isoformat()))
    duration = (now - started).total_seconds() / 60
    meta = MODE_META.get(mode, {})

    note = f"""---
date: {now.strftime("%Y-%m-%d")}
time: {now.strftime("%H:%M")}
mode: {mode}
session_duration: {duration:.0f} min
type: reentry-note
tags:
  - reentry
  - {mode}
---

# Re-entry: {meta.get('label', mode.upper())} session — {now.strftime("%Y-%m-%d %H:%M")}

> **Mode:** {meta.get('emoji', '')} {meta.get('label', mode.upper())}  
> **Duration:** {duration:.0f} minutes  
> **Started:** {started.strftime("%H:%M")}  
> **Ended:** {now.strftime("%H:%M")}

---

## What You Were Working On

*(Fill this in before closing — what's the exact next step when you return?)*

- 

## Open Threads

- 

## Next Action (when you return, start here)

> 

---
*Generated by Intent Switcher — {now.strftime("%Y-%m-%d %H:%M")}*
"""
    return note

def save_reentry_note(mode: str, session_data: dict) -> Path:
    note = build_reentry_note(mode, session_data)
    folder = OBSIDIAN_VAULT / "Re-entry Notes"
    folder.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d_%H%M")
    filename = f"{date_str} reentry-{mode}.md"
    path = folder / filename
    path.write_text(note, encoding="utf-8")
    return path

# ─────────────────────────────────────────────
# MODE INFERENCE
# ─────────────────────────────────────────────

def get_recent_activity_summary() -> str:
    """Pull recent signals from browser history and shared DB for inference."""
    lines = []

    # Recent browser domains
    try:
        import shutil
        tmp = Path(r"C:\Users\Karl\AppData\Local\Temp\brave_hist_infer.db")
        shutil.copy2(str(BRAVE_HISTORY), str(tmp))
        cutoff = int((datetime.now() - timedelta(hours=2) - datetime(1601,1,1)).total_seconds() * 1_000_000)
        conn = sqlite3.connect(str(tmp))
        rows = conn.execute(
            "SELECT u.url, u.title FROM visits v JOIN urls u ON v.url=u.id WHERE v.visit_time > ? ORDER BY v.visit_time DESC LIMIT 30",
            (cutoff,)
        ).fetchall()
        conn.close()
        tmp.unlink(missing_ok=True)
        if rows:
            lines.append("Recent browser activity (last 2 hours):")
            for url, title in rows[:15]:
                lines.append(f"  - {title or url}")
    except Exception:
        pass

    # Recent tasks from shared DB
    try:
        if SHARED_DB.exists():
            conn = sqlite3.connect(str(SHARED_DB))
            tasks = conn.execute(
                "SELECT title FROM tasks WHERE status='open' ORDER BY created_at DESC LIMIT 10"
            ).fetchall()
            conn.close()
            if tasks:
                lines.append("\nOpen tasks:")
                for (t,) in tasks:
                    lines.append(f"  - {t}")
    except Exception:
        pass

    # Recent git activity
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "--since=2 hours ago"],
            capture_output=True, text=True,
            cwd=r"C:\Users\Karl\Documents\productivity-os"
        )
        if result.stdout.strip():
            lines.append("\nRecent git commits:")
            for line in result.stdout.strip().split("\n")[:5]:
                lines.append(f"  - {line}")
    except Exception:
        pass

    return "\n".join(lines) if lines else "No recent activity data available."

def infer_mode_with_llm() -> tuple[str, str]:
    """
    Ask Ollama to infer the best mode from recent activity signals.
    Returns (mode_name, reasoning).
    """
    print("\n  Analyzing recent activity...")
    activity = get_recent_activity_summary()

    prompt = f"""You are helping a developer named Karl decide which work mode to enter based on his recent activity.

Available modes:
- build: Deep coding, shipping features, writing scripts
- debug: Investigating bugs, reading logs, tracing issues  
- learn: Studying, reading docs, watching tutorials
- admin: Email, planning, scheduling, non-coding tasks
- review: Code review, reading PRs, reviewing reports

Recent activity signals:
{activity}

Based on this activity, what mode should Karl enter? Consider:
- What has he been doing in the last 2 hours?
- What would be the most natural continuation?
- What does his task list suggest is urgent?

Respond with ONLY a JSON object, no markdown:
{{"mode": "build", "confidence": "high", "reason": "one sentence explanation"}}

mode must be one of: build, debug, learn, admin, review"""

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()
        import re
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            mode = data.get("mode", "build")
            if mode not in MODE_META:
                mode = "build"
            reason = data.get("reason", "Based on recent activity")
            confidence = data.get("confidence", "medium")
            return mode, f"{reason} (confidence: {confidence})"
    except Exception as e:
        print(f"  [WARN] Inference failed: {e}")

    return "build", "Default fallback — could not analyze activity"

# ─────────────────────────────────────────────
# ENVIRONMENT ACTIONS
# ─────────────────────────────────────────────

def open_vscode(workspace_path: str | None):
    if not workspace_path:
        return
    path = Path(workspace_path)
    if not path.exists():
        # Try opening the folder instead
        folder = path.parent
        if folder.exists():
            subprocess.Popen([str(VSCODE_PATH), str(folder)])
            print(f"    VSCode → {folder.name}/")
        return
    subprocess.Popen([str(VSCODE_PATH), str(path)])
    print(f"    VSCode → {path.name}")

def open_obsidian_note(note: str | None):
    if not note:
        return
    # Obsidian URI scheme: obsidian://open?vault=VaultName&file=NoteName
    vault_name = OBSIDIAN_VAULT.name
    # Build the URI
    import urllib.parse
    file_encoded = urllib.parse.quote(note.replace(".md", ""))
    vault_encoded = urllib.parse.quote(vault_name)
    uri = f"obsidian://open?vault={vault_encoded}&file={file_encoded}"
    webbrowser.open(uri)
    print(f"    Obsidian → {note}")

def write_focus_rules(blocked_sites: list, focus_level: str, mode: str):
    """
    Write a focus rules file that other tools (distraction_blocker) can read.
    Does NOT modify hosts file directly — uses a JSON rules file as the
    canonical source of truth that Focus Guardian will enforce.
    """
    rules = {
        "mode": mode,
        "focus_level": focus_level,
        "blocked_sites": blocked_sites,
        "active_since": datetime.now().isoformat(),
        "auto_unblock_after_hours": None,
    }
    rules_path = SCRIPT_DIR / "active_focus_rules.json"
    rules_path.write_text(json.dumps(rules, indent=2))
    print(f"    Focus rules → {focus_level} ({len(blocked_sites)} sites blocked)")

def play_mode_sound(mode: str):
    """Optional audio cue using Windows PowerShell beep. Non-blocking."""
    # Different tones per mode
    tones = {
        "build":  [(800, 100), (1000, 150)],
        "debug":  [(400, 200), (300, 200)],
        "learn":  [(600, 100), (700, 100), (800, 100)],
        "admin":  [(500, 200)],
        "review": [(700, 100), (600, 100)],
    }
    sequence = tones.get(mode, [(600, 150)])
    ps_commands = []
    for freq, dur in sequence:
        ps_commands.append(f"[console]::beep({freq},{dur})")
    ps_script = "; ".join(ps_commands)
    try:
        subprocess.Popen(
            ["powershell", "-WindowStyle", "Hidden", "-Command", ps_script],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except Exception:
        pass  # Audio is optional — never break on this

def write_shared_db_session(mode: str, session_id: int):
    """Log session start to shared productivity_os.db if available."""
    try:
        if not SHARED_DB.exists():
            return
        conn = sqlite3.connect(str(SHARED_DB))
        # Check if sessions table exists
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
        ).fetchone()
        if tables:
            conn.execute(
                """INSERT OR IGNORE INTO sessions
                   (started_at, source, kind, metadata)
                   VALUES (?, 'intent_switcher', ?, ?)""",
                (
                    datetime.now().isoformat(),
                    f"mode_{mode}",
                    json.dumps({"mode": mode, "switcher_session_id": session_id})
                )
            )
            conn.commit()
        conn.close()
    except Exception:
        pass  # Graceful fallback — shared DB is optional

# ─────────────────────────────────────────────
# MAIN SWITCH LOGIC
# ─────────────────────────────────────────────

def switch_to_mode(mode: str, inferred: bool = False):
    modes = load_modes()

    if mode not in modes:
        print(f"[ERROR] Unknown mode: '{mode}'")
        print(f"        Available: {', '.join(modes.keys())}")
        sys.exit(1)

    cfg = modes[mode]
    meta = MODE_META.get(mode, {"emoji": "⚙", "color": "\033[0m", "label": mode.upper()})
    color = meta["color"]

    # ── End previous session if one is active
    prev = load_current_session()
    if prev and prev.get("mode") != mode:
        print(f"\n  Ending previous session: {prev['mode'].upper()} ({prev.get('started_at', '?')[:16]})")
        end_session(prev.get("db_id", -1))
        clear_current_session()

    print(f"\n{'═'*55}")
    print(f"  {color}{BOLD}{meta['emoji']}  Switching to {meta['label']} mode{RESET}")
    print(f"{'═'*55}")
    print(f"\n  {DIM}{cfg.get('description', '')}{RESET}\n")

    if inferred:
        print(f"  {DIM}(mode inferred from recent activity){RESET}\n")

    print("  Configuring environment:")

    # 1. Open VSCode workspace
    workspace = cfg.get("vscode_workspace")
    if workspace:
        open_vscode(workspace)
    else:
        print("    VSCode → (not configured for this mode)")

    # 2. Open Obsidian note
    obsidian_note = cfg.get("obsidian_open")
    if obsidian_note:
        open_obsidian_note(obsidian_note)
    else:
        print("    Obsidian → (no default note for this mode)")

    # 3. Write focus rules
    blocked = cfg.get("blocked_sites", [])
    focus_level = cfg.get("focus_level", "moderate")
    write_focus_rules(blocked, focus_level, mode)

    # 4. Run any terminal commands
    for cmd in cfg.get("terminal_commands", []):
        try:
            subprocess.Popen(cmd, shell=True)
            print(f"    CMD → {cmd}")
        except Exception as e:
            print(f"    CMD → [FAILED] {cmd}: {e}")

    # 5. Save session to DB
    db_id = save_session(mode, inferred)
    write_shared_db_session(mode, db_id)

    # 6. Save current session state
    session_data = {
        "mode": mode,
        "started_at": datetime.now().isoformat(),
        "db_id": db_id,
        "inferred": inferred,
        "config": cfg,
    }
    save_current_session(session_data)

    # 7. Audio cue
    play_mode_sound(mode)

    # ── Print welcome
    welcome = cfg.get("welcome_message", f"Entering {mode} mode.")
    print(f"\n  {color}{BOLD}» {welcome}{RESET}")

    if blocked:
        print(f"\n  {DIM}Blocked: {', '.join(blocked[:4])}{'...' if len(blocked) > 4 else ''}{RESET}")

    print(f"\n  Session started at {datetime.now().strftime('%H:%M')}")
    print(f"  Run 'python switcher.py --end' to close and save re-entry note.")
    print(f"{'═'*55}\n")

# ─────────────────────────────────────────────
# STATUS & HISTORY
# ─────────────────────────────────────────────

def show_status():
    session = load_current_session()

    print(f"\n{'═'*55}")
    print(f"  Intent Switcher — Status")
    print(f"{'═'*55}\n")

    if not session:
        print("  No active session.\n")
        print("  Run: python switcher.py <mode>")
        print(f"{'═'*55}\n")
        return

    mode = session.get("mode", "unknown")
    started = datetime.fromisoformat(session.get("started_at", datetime.now().isoformat()))
    duration = (datetime.now() - started).total_seconds() / 60
    meta = MODE_META.get(mode, {})
    color = meta.get("color", "")

    print(f"  {color}{BOLD}{meta.get('emoji', '⚙')}  {meta.get('label', mode.upper())}{RESET}")
    print(f"  Started:    {started.strftime('%H:%M')}")
    print(f"  Duration:   {duration:.0f} min")
    print(f"  Inferred:   {'Yes (auto-detected)' if session.get('inferred') else 'No (manual)'}")

    cfg = session.get("config", {})
    blocked = cfg.get("blocked_sites", [])
    if blocked:
        print(f"  Blocked:    {', '.join(blocked[:3])}{'...' if len(blocked) > 3 else ''}")

    print(f"\n{'═'*55}\n")

def show_history(limit: int = 10):
    init_db()
    conn = sqlite3.connect(str(HISTORY_DB))
    rows = conn.execute(
        "SELECT started_at, ended_at, mode, duration_min, inferred FROM sessions ORDER BY started_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()

    print(f"\n{'═'*55}")
    print(f"  Intent Switcher — Recent History")
    print(f"{'═'*55}\n")

    if not rows:
        print("  No history yet.\n")
        print(f"{'═'*55}\n")
        return

    for started, ended, mode, duration, inferred in rows:
        meta = MODE_META.get(mode, {})
        color = meta.get("color", "")
        label = meta.get("label", mode.upper())
        emoji = meta.get("emoji", "⚙")
        dur_str = f"{duration:.0f}m" if duration else "active"
        inf_str = " (auto)" if inferred else ""
        dt = started[:16].replace("T", " ")
        print(f"  {color}{emoji} {label:<8}{RESET}  {dt}  {dur_str}{inf_str}")

    print(f"\n{'═'*55}\n")

# ─────────────────────────────────────────────
# END SESSION
# ─────────────────────────────────────────────

def end_current_session():
    session = load_current_session()
    if not session:
        print("\n  No active session to end.\n")
        return

    mode = session.get("mode", "unknown")
    started = datetime.fromisoformat(session.get("started_at", datetime.now().isoformat()))
    duration = (datetime.now() - started).total_seconds() / 60
    meta = MODE_META.get(mode, {})

    print(f"\n{'═'*55}")
    print(f"  Ending {meta.get('emoji', '')} {meta.get('label', mode.upper())} session")
    print(f"  Duration: {duration:.0f} minutes")
    print(f"{'═'*55}\n")

    # Save re-entry note to Obsidian
    note_path = save_reentry_note(mode, session)
    print(f"  Re-entry note saved: Re-entry Notes/{note_path.name}")
    print(f"  Open it in Obsidian to fill in your next action before leaving.\n")

    # End DB session
    end_session(session.get("db_id", -1), reentry_note=str(note_path))
    clear_current_session()

    # Clear focus rules
    rules_path = SCRIPT_DIR / "active_focus_rules.json"
    if rules_path.exists():
        rules_path.unlink()
        print("  Focus rules cleared.")

    print(f"\n  Session ended. Good work.")
    print(f"{'═'*55}\n")

# ─────────────────────────────────────────────
# INTERACTIVE MODE PICKER
# ─────────────────────────────────────────────

def interactive_pick() -> str:
    modes = load_modes()
    print(f"\n{'═'*55}")
    print(f"  {BOLD}Intent Switcher — What are you working on?{RESET}")
    print(f"{'═'*55}\n")

    mode_list = list(modes.keys())
    for i, m in enumerate(mode_list, 1):
        meta = MODE_META.get(m, {})
        color = meta.get("color", "")
        cfg = modes[m]
        print(f"  {color}{BOLD}[{i}]{RESET} {meta.get('emoji', '')} {meta.get('label', m.upper()):<10} {DIM}{cfg.get('description', '')}{RESET}")

    print(f"\n  {DIM}[i] Let Ollama infer from recent activity{RESET}")
    print()

    while True:
        try:
            choice = input("  Enter number or mode name: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\n  Cancelled.")
            sys.exit(0)

        if choice == "i":
            return "__infer__"
        if choice in modes:
            return choice
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(mode_list):
                return mode_list[idx]
        except ValueError:
            pass
        print("  Invalid choice. Try again.")

# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def main():
    init_db()

    parser = argparse.ArgumentParser(
        description="Intent-Aware Environment Switcher — Project 17",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "mode", nargs="?",
        help="Mode to switch to: build | debug | learn | admin | review"
    )
    parser.add_argument("--infer", action="store_true", help="Infer mode from recent activity via Ollama")
    parser.add_argument("--status", action="store_true", help="Show current session status")
    parser.add_argument("--history", action="store_true", help="Show recent session history")
    parser.add_argument("--end", action="store_true", help="End current session + save re-entry note")

    args = parser.parse_args()

    if args.status:
        show_status()
    elif args.history:
        show_history()
    elif args.end:
        end_current_session()
    elif args.infer:
        mode, reason = infer_mode_with_llm()
        print(f"\n  Inferred mode: {MODE_META[mode]['emoji']} {mode.upper()}")
        print(f"  Reason: {reason}")
        confirm = input(f"\n  Switch to {mode.upper()}? [Y/n]: ").strip().lower()
        if confirm in ("", "y", "yes"):
            switch_to_mode(mode, inferred=True)
        else:
            print("  Cancelled.")
    elif args.mode:
        mode = args.mode.lower()
        switch_to_mode(mode)
    else:
        # Interactive picker
        choice = interactive_pick()
        if choice == "__infer__":
            mode, reason = infer_mode_with_llm()
            print(f"\n  Inferred: {MODE_META[mode]['emoji']} {mode.upper()} — {reason}")
            confirm = input(f"  Switch to {mode.upper()}? [Y/n]: ").strip().lower()
            if confirm in ("", "y", "yes"):
                switch_to_mode(mode, inferred=True)
            else:
                print("  Cancelled.")
        else:
            switch_to_mode(choice)

if __name__ == "__main__":
    main()
