"""
Git Activity Watcher
Karl's Productivity OS - Project 18 (new)

Polls configured git repos every 5 minutes for new commits.
Summarizes what was accomplished using llama3:8b.
Logs coding sessions and metrics to the shared productivity_os.db.

Usage:
    python git_watcher.py              # start polling (runs forever)
    python git_watcher.py --once       # single scan right now, then exit
    python git_watcher.py --today      # print today's coding summary
    python git_watcher.py --install    # register as Windows startup task
"""

import os
import sys
import json
import sqlite3
import subprocess
import argparse
import requests
import time
import hashlib
from pathlib import Path
from datetime import datetime, date, timedelta

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).parent
LOCAL_DB     = SCRIPT_DIR / "git_watcher.db"
SHARED_DB    = Path(r"C:\Users\Karl\Documents\productivity_os.db")
LOG_PATH     = SCRIPT_DIR / "git_watcher.log"

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3:8b"

POLL_INTERVAL_SECS = 300  # 5 minutes

# Repos to watch — add any project folder here
WATCHED_REPOS = [
    Path(r"C:\Users\Karl\Documents\productivity-os"),
    # Path(r"C:\Users\Karl\Documents\your-other-repo"),  # uncomment to add
]

# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(str(LOCAL_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen_commits (
            commit_hash TEXT PRIMARY KEY,
            repo        TEXT NOT NULL,
            ts          TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS coding_sessions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ts              TEXT NOT NULL,
            repo            TEXT NOT NULL,
            commits         INTEGER NOT NULL,
            lines_added     INTEGER DEFAULT 0,
            lines_removed   INTEGER DEFAULT 0,
            files_changed   INTEGER DEFAULT 0,
            commit_hashes   TEXT,
            summary         TEXT,
            raw_messages    TEXT
        )
    """)
    conn.commit()
    conn.close()

def is_seen(commit_hash: str) -> bool:
    conn = sqlite3.connect(str(LOCAL_DB))
    row = conn.execute("SELECT 1 FROM seen_commits WHERE commit_hash=?", (commit_hash,)).fetchone()
    conn.close()
    return row is not None

def mark_seen(commit_hash: str, repo: str):
    conn = sqlite3.connect(str(LOCAL_DB))
    conn.execute(
        "INSERT OR IGNORE INTO seen_commits (commit_hash, repo, ts) VALUES (?,?,?)",
        (commit_hash, repo, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()

def save_session(repo: str, commits: list, stats: dict, summary: str):
    messages = [c["message"] for c in commits]
    hashes   = [c["hash"] for c in commits]
    conn = sqlite3.connect(str(LOCAL_DB))
    conn.execute("""
        INSERT INTO coding_sessions
        (ts, repo, commits, lines_added, lines_removed, files_changed, commit_hashes, summary, raw_messages)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        datetime.now().isoformat(),
        repo,
        len(commits),
        stats.get("added", 0),
        stats.get("removed", 0),
        stats.get("files", 0),
        json.dumps(hashes),
        summary,
        json.dumps(messages),
    ))
    conn.commit()
    conn.close()

# ─────────────────────────────────────────────
# SHARED DB WRITES
# ─────────────────────────────────────────────

def write_to_shared_db(repo: str, commits: list, stats: dict, summary: str):
    """
    Log to productivity_os.db — graceful fallback if not present.
    Writes: session (kind=coding) + metrics (git_commits, lines_changed).
    """
    if not SHARED_DB.exists():
        return

    try:
        conn = sqlite3.connect(str(SHARED_DB))
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}

        now = datetime.now().isoformat()
        today = date.today().isoformat()
        repo_name = Path(repo).name

        # ── Write session
        if "sessions" in tables:
            conn.execute("""
                INSERT INTO sessions (start_ts, source_tool, kind, summary, extra_json)
                VALUES (?, 'git_watcher', 'coding', ?, ?)
            """, (now, summary, json.dumps({
                "repo": repo_name,
                "commits": len(commits),
                "lines_added": stats.get("added", 0),
                "lines_removed": stats.get("removed", 0),
                "files_changed": stats.get("files", 0),
            })))

        # ── Write metrics
        if "metrics_daily" in tables:
            metrics = [
                ("git_commits",   len(commits)),
                ("lines_added",   stats.get("added", 0)),
                ("lines_removed", stats.get("removed", 0)),
                ("files_changed", stats.get("files", 0)),
            ]
            for metric_name, value in metrics:
                # Upsert — add to existing value for today
                existing = conn.execute(
                    "SELECT id, value FROM metrics_daily WHERE date=? AND metric_name=? AND source_tool=?",
                    (today, metric_name, "git_watcher")
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE metrics_daily SET value=? WHERE id=?",
                        (existing[1] + value, existing[0])
                    )
                else:
                    conn.execute("""
                        INSERT INTO metrics_daily (date, metric_name, value, source_tool, notes)
                        VALUES (?, ?, ?, 'git_watcher', ?)
                    """, (today, metric_name, value, repo_name))

        # ── Write artifact
        if "artifacts" in tables:
            conn.execute("""
                INSERT INTO artifacts (type, source_tool, title, extra_json)
                VALUES ('git_session', 'git_watcher', ?, ?)
            """, (
                f"{repo_name}: {len(commits)} commit{'s' if len(commits) != 1 else ''}",
                json.dumps({"repo": repo_name, "commits": len(commits), "summary": summary, **stats}),
            ))

        conn.commit()
        conn.close()

    except Exception as e:
        print(f"  [WARN] Shared DB write failed: {e}")

# ─────────────────────────────────────────────
# GIT QUERIES
# ─────────────────────────────────────────────

def get_new_commits(repo_path: Path, since_minutes: int = 10) -> list[dict]:
    """
    Returns list of new (unseen) commits from the last N minutes.
    Each commit: {hash, message, author, ts, files, added, removed}
    """
    if not repo_path.exists():
        return []

    # Get commits from last N minutes
    since = (datetime.now() - timedelta(minutes=since_minutes)).strftime("%Y-%m-%d %H:%M:%S")

    try:
        result = subprocess.run(
            ["git", "log", f"--since={since}", "--format=%H|%s|%an|%ai", "--no-merges"],
            capture_output=True, text=True, cwd=str(repo_path)
        )
    except FileNotFoundError:
        print("  [WARN] git not found in PATH")
        return []

    if not result.stdout.strip():
        return []

    commits = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue
        h, msg, author, ts = parts
        if is_seen(h):
            continue
        commits.append({"hash": h, "message": msg, "author": author, "ts": ts})

    return commits

def get_diff_stats(repo_path: Path, commit_hashes: list[str]) -> dict:
    """Get aggregate lines added/removed/files changed for a set of commits."""
    if not commit_hashes:
        return {"added": 0, "removed": 0, "files": 0}

    total_added = total_removed = total_files = 0

    for h in commit_hashes:
        try:
            result = subprocess.run(
                ["git", "show", "--stat", "--format=", h],
                capture_output=True, text=True, cwd=str(repo_path)
            )
            # Parse the summary line: "X files changed, Y insertions(+), Z deletions(-)"
            for line in result.stdout.split("\n"):
                if "changed" in line:
                    import re
                    files  = re.search(r'(\d+) file', line)
                    added  = re.search(r'(\d+) insertion', line)
                    removed = re.search(r'(\d+) deletion', line)
                    if files:   total_files   += int(files.group(1))
                    if added:   total_added   += int(added.group(1))
                    if removed: total_removed += int(removed.group(1))
        except Exception:
            pass

    return {"added": total_added, "removed": total_removed, "files": total_files}

# ─────────────────────────────────────────────
# LLM SUMMARIZATION
# ─────────────────────────────────────────────

def summarize_commits(repo_name: str, commits: list[dict], stats: dict) -> str:
    """Ask Ollama what was accomplished in these commits."""
    messages_str = "\n".join([f"  - {c['message']}" for c in commits])

    prompt = f"""A developer just pushed {len(commits)} commit(s) to the '{repo_name}' repo.

Commit messages:
{messages_str}

Stats: {stats.get('added', 0)} lines added, {stats.get('removed', 0)} removed, {stats.get('files', 0)} files changed.

Write one concise sentence (max 20 words) describing what was accomplished.
Focus on the outcome, not the mechanics. Start with a past-tense verb.
Examples: "Built the git activity watcher and wired it into the shared database."
          "Fixed authentication bug and added rate limiting to the API."

Respond with ONLY the sentence, no quotes, no punctuation at the end."""

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=30,
        )
        resp.raise_for_status()
        summary = resp.json().get("response", "").strip().strip('"\'')
        return summary if summary else f"Pushed {len(commits)} commit(s) to {repo_name}"
    except Exception:
        messages = [c["message"] for c in commits[:3]]
        return f"Pushed {len(commits)} commit(s): {'; '.join(messages)}"

# ─────────────────────────────────────────────
# CORE POLLING LOOP
# ─────────────────────────────────────────────

def scan_repos(verbose: bool = True) -> int:
    """
    Scan all watched repos for new commits.
    Returns total number of new commits found.
    """
    total_new = 0

    for repo_path in WATCHED_REPOS:
        if not repo_path.exists():
            if verbose:
                print(f"  [SKIP] Repo not found: {repo_path}")
            continue

        repo_name = repo_path.name
        new_commits = get_new_commits(repo_path, since_minutes=POLL_INTERVAL_SECS // 60 + 2)

        if not new_commits:
            if verbose:
                print(f"  {repo_name}: no new commits")
            continue

        # Get diff stats
        hashes = [c["hash"] for c in new_commits]
        stats = get_diff_stats(repo_path, hashes)

        # Summarize
        summary = summarize_commits(repo_name, new_commits, stats)

        # Save locally
        save_session(repo_name, new_commits, stats, summary)

        # Write to shared DB
        write_to_shared_db(str(repo_path), new_commits, stats, summary)

        # Mark all commits as seen
        for c in new_commits:
            mark_seen(c["hash"], repo_name)

        total_new += len(new_commits)

        if verbose:
            print(f"\n  📦 {repo_name}: {len(new_commits)} new commit{'s' if len(new_commits) != 1 else ''}")
            print(f"     +{stats['added']} / -{stats['removed']} lines | {stats['files']} files")
            print(f"     → {summary}")

    return total_new

def run_watcher():
    init_db()
    print(f"\n{'═'*55}")
    print(f"  Git Activity Watcher — starting up")
    print(f"  Watching {len(WATCHED_REPOS)} repo(s)")
    print(f"  Poll interval: {POLL_INTERVAL_SECS // 60} minutes")
    print(f"  Press Ctrl+C to stop")
    print(f"{'═'*55}\n")

    for repo in WATCHED_REPOS:
        status = "✓" if repo.exists() else "✗ NOT FOUND"
        print(f"  {status}  {repo}")
    print()

    while True:
        ts = datetime.now().strftime("%H:%M")
        print(f"[{ts}] Scanning...", end=" ", flush=True)
        try:
            found = scan_repos(verbose=True)
            if found == 0:
                print("quiet")
        except Exception as e:
            print(f"\n  [ERROR] {e}")
        time.sleep(POLL_INTERVAL_SECS)

# ─────────────────────────────────────────────
# TODAY'S SUMMARY
# ─────────────────────────────────────────────

def show_today():
    init_db()
    today = date.today().isoformat()
    conn = sqlite3.connect(str(LOCAL_DB))

    sessions = conn.execute("""
        SELECT repo, commits, lines_added, lines_removed, files_changed, summary, ts
        FROM coding_sessions
        WHERE ts LIKE ?
        ORDER BY ts ASC
    """, (f"{today}%",)).fetchall()

    conn.close()

    print(f"\n{'═'*55}")
    print(f"  Git Activity — {today}")
    print(f"{'═'*55}\n")

    if not sessions:
        print("  No commits today.\n")
        print(f"{'═'*55}\n")
        return

    total_commits = sum(s[1] for s in sessions)
    total_added   = sum(s[2] for s in sessions)
    total_removed = sum(s[3] for s in sessions)
    total_files   = sum(s[4] for s in sessions)

    print(f"  Total: {total_commits} commits | +{total_added} / -{total_removed} lines | {total_files} files\n")

    for repo, commits, added, removed, files, summary, ts in sessions:
        time_str = ts[11:16]
        print(f"  [{time_str}] {repo}")
        print(f"           {commits} commit{'s' if commits != 1 else ''} | +{added}/-{removed} lines")
        print(f"           {summary}\n")

    print(f"{'═'*55}\n")

# ─────────────────────────────────────────────
# INSTALL AS STARTUP TASK
# ─────────────────────────────────────────────

def install_startup_task():
    script_path = Path(__file__).resolve()
    python_path = sys.executable
    task_name   = "GitActivityWatcher"

    ps = f"""
$TaskName   = "{task_name}"
$ScriptPath = "{script_path}"
$PythonPath = "{python_path}"

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$Action = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "`"$ScriptPath`"" `
    -WorkingDirectory "{script_path.parent}"

$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -RunLevel Highest `
    -Description "Karl Productivity OS - Git Activity Watcher" | Out-Null

Write-Host "Task registered: $TaskName"
Write-Host "Start now: Start-ScheduledTask -TaskName '$TaskName'"
"""
    # Write temp PS1 and run it
    tmp_ps = SCRIPT_DIR / "_install_task.ps1"
    tmp_ps.write_text(ps)
    result = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(tmp_ps)],
        capture_output=True, text=True
    )
    tmp_ps.unlink(missing_ok=True)
    print(result.stdout)
    if result.returncode != 0:
        print(f"[ERROR] {result.stderr}")

# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Git Activity Watcher — Productivity OS")
    parser.add_argument("--once",    action="store_true", help="Scan once and exit")
    parser.add_argument("--today",   action="store_true", help="Show today's coding summary")
    parser.add_argument("--install", action="store_true", help="Register as Windows startup task")
    args = parser.parse_args()

    if args.today:
        show_today()
    elif args.install:
        install_startup_task()
    elif args.once:
        init_db()
        print(f"\nScanning repos...")
        found = scan_repos(verbose=True)
        print(f"\nDone. {found} new commit(s) found.")
    else:
        run_watcher()
