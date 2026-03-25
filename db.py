"""
productivity_os/db.py
─────────────────────
Shared database access layer for all Productivity OS tools.

Usage in any tool:
    from productivity_os.db import get_conn, log_artifact, log_event,
                                    log_session, log_task, log_metric

Every tool should import from here — never open productivity_os.db directly.
"""

import json
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime, date
from uuid import uuid4

# ─────────────────────────────────────────────
# CONFIG — reads from config.yaml at repo root
# ─────────────────────────────────────────────

def _get_db_path() -> Path:
    """Read shared_db path from config.yaml, fallback to Documents if not found."""
    try:
        import yaml
        config_path = Path(__file__).parent / "config.yaml"
        if config_path.exists():
            with open(config_path, 'r') as f:
                cfg = yaml.safe_load(f)
            return Path(cfg['paths']['shared_db'])
    except Exception:
        pass
    # Fallback — safe default next to the repo
    return Path.home() / "Documents" / "productivity_os.db"

DB_PATH = _get_db_path()
SCHEMA_PATH = Path(__file__).parent / "productivity_os_schema.sql"


# ─────────────────────────────────────────────
# CONNECTION
# ─────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    """Return a WAL-mode connection with row_factory set."""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """
    Create all tables if they don't exist.
    Safe to call every time a tool starts up.
    """
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema file not found: {SCHEMA_PATH}")
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    conn = get_conn()
    conn.executescript(schema)
    conn.commit()
    conn.close()
    print(f"[db] Initialized: {DB_PATH}")


# ─────────────────────────────────────────────
# ARTIFACTS
# ─────────────────────────────────────────────

def log_artifact(
    *,
    artifact_type: str,          # screenshot | transcript | download | note | browser_report | briefing
    source_tool: str,
    path_or_url: str | None = None,
    title: str | None = None,
    summary: str | None = None,
    project_id: str | None = None,
    obsidian_path: str | None = None,
    word_count: int | None = None,
    duration_secs: float | None = None,
    language: str | None = None,
    quality_score: float | None = None,
    source_file: str | None = None,
    tags: list[str] | None = None,      # list of tag name strings — auto-created if new
    extra: dict | None = None,
) -> str:
    """
    Insert an artifact row and optionally associate tags.
    Returns the new artifact_id (UUID).

    Example:
        artifact_id = log_artifact(
            artifact_type="transcript",
            source_tool="whisper",
            path_or_url=str(obsidian_path),
            title="Meeting with Alex 2026-03-24",
            summary="Discussed Q2 roadmap...",
            tags=["meeting", "roadmap", "q2"],
            duration_secs=2340.5,
            language="en",
        )
    """
    artifact_id = str(uuid4())
    now = _now()
    conn = get_conn()

    conn.execute(
        """INSERT INTO artifacts
           (artifact_id, type, source_tool, path_or_url, title, summary,
            project_id, obsidian_path, word_count, duration_secs, language,
            quality_score, source_file, extra_json, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            artifact_id, artifact_type, source_tool, path_or_url, title, summary,
            project_id, obsidian_path, word_count, duration_secs, language,
            quality_score, source_file,
            json.dumps(extra) if extra else None,
            now, now,
        )
    )

    if tags:
        _associate_tags(conn, artifact_id, tags)

    conn.commit()
    conn.close()

    log_event(
        source_tool=source_tool,
        event_type="artifact.created",
        artifact_id=artifact_id,
        payload={"artifact_id": artifact_id, "type": artifact_type, "title": title},
    )

    return artifact_id


def update_artifact(artifact_id: str, source_tool: str, **kwargs):
    """Update specific fields on an existing artifact."""
    if not kwargs:
        return
    allowed = {"summary", "title", "quality_score", "obsidian_path", "project_id", "extra_json"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return

    fields["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    conn = get_conn()
    conn.execute(
        f"UPDATE artifacts SET {set_clause} WHERE artifact_id = ?",
        list(fields.values()) + [artifact_id]
    )
    conn.commit()
    conn.close()

    log_event(
        source_tool=source_tool,
        event_type="artifact.updated",
        artifact_id=artifact_id,
        payload={"artifact_id": artifact_id, "fields_updated": list(fields.keys())},
    )


# ─────────────────────────────────────────────
# TAGS
# ─────────────────────────────────────────────

def _associate_tags(conn: sqlite3.Connection, artifact_id: str, tag_names: list[str]):
    """Create tags if needed, then link to artifact. Internal use."""
    for raw_name in tag_names:
        name = raw_name.lower().strip().replace(" ", "-")
        if not name:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,)
        )
        row = conn.execute("SELECT tag_id FROM tags WHERE name = ?", (name,)).fetchone()
        tag_id = row["tag_id"]
        conn.execute(
            "INSERT OR IGNORE INTO artifact_tags (artifact_id, tag_id) VALUES (?,?)",
            (artifact_id, tag_id)
        )


def get_or_create_tag(name: str, kind: str = "topic") -> int:
    """Return tag_id, creating the tag if it doesn't exist."""
    name = name.lower().strip().replace(" ", "-")
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO tags (name, kind) VALUES (?,?)", (name, kind))
    row = conn.execute("SELECT tag_id FROM tags WHERE name = ?", (name,)).fetchone()
    tag_id = row["tag_id"]
    conn.commit()
    conn.close()
    return tag_id


# ─────────────────────────────────────────────
# SESSIONS
# ─────────────────────────────────────────────

def log_session(
    *,
    kind: str,                   # browser | coding | listening | deep_work
    source_tool: str,
    start_ts: str,               # ISO 8601 UTC
    end_ts: str | None = None,
    focus_score: float | None = None,
    project_id: str | None = None,
    summary: str | None = None,
    artifact_id: str | None = None,
    extra: dict | None = None,
) -> str:
    """
    Insert a session row. Returns session_id (UUID).

    Example:
        session_id = log_session(
            kind="browser",
            source_tool="browser_analyzer",
            start_ts="2026-03-24T09:00:00Z",
            end_ts="2026-03-24T11:30:00Z",
            focus_score=74.2,
            summary="Deep dive on Ollama RAG patterns",
        )
    """
    session_id = str(uuid4())
    duration_min = None

    if start_ts and end_ts:
        try:
            s = datetime.fromisoformat(start_ts.replace("Z", "+00:00"))
            e = datetime.fromisoformat(end_ts.replace("Z", "+00:00"))
            duration_min = (e - s).total_seconds() / 60
        except Exception:
            pass

    conn = get_conn()
    conn.execute(
        """INSERT INTO sessions
           (session_id, kind, start_ts, end_ts, duration_min, focus_score,
            project_id, summary, source_tool, artifact_id, extra_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            session_id, kind, start_ts, end_ts, duration_min, focus_score,
            project_id, summary, source_tool, artifact_id,
            json.dumps(extra) if extra else None,
        )
    )
    conn.commit()
    conn.close()

    log_event(
        source_tool=source_tool,
        event_type="session.created",
        session_id=session_id,
        payload={"session_id": session_id, "kind": kind, "focus_score": focus_score},
    )

    return session_id


# ─────────────────────────────────────────────
# TASKS
# ─────────────────────────────────────────────

def log_task(
    *,
    title: str,
    source_tool: str,
    status: str = "unconfirmed",
    priority: str | None = None,
    project_id: str | None = None,
    source_artifact: str | None = None,
    source_note_path: str | None = None,
    due_date: str | None = None,
    notes: str | None = None,
) -> str | None:
    """
    Insert a task. Skips duplicates based on title hash (case-insensitive).
    Returns task_id or None if it was a duplicate.

    Example:
        task_id = log_task(
            title="Follow up with Alex on Q2 timeline",
            source_tool="whisper",
            source_artifact=artifact_id,
            priority="high",
        )
    """
    content_hash = hashlib.md5(title.strip().lower().encode()).hexdigest()
    now = _now()

    conn = get_conn()

    # Check for existing open task with same content hash
    existing = conn.execute(
        "SELECT task_id FROM tasks WHERE content_hash = ? AND status NOT IN ('done','dismissed')",
        (content_hash,)
    ).fetchone()

    if existing:
        # Update last_seen_at so briefing knows it's still active
        conn.execute(
            "UPDATE tasks SET last_seen_at = ?, updated_at = ? WHERE task_id = ?",
            (now, now, existing["task_id"])
        )
        conn.commit()
        conn.close()
        return existing["task_id"]  # already exists

    task_id = str(uuid4())
    conn.execute(
        """INSERT INTO tasks
           (task_id, title, status, priority, project_id, source_tool,
            source_artifact, source_note_path, due_date, notes,
            content_hash, created_at, updated_at, last_seen_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            task_id, title.strip(), status, priority, project_id, source_tool,
            source_artifact, source_note_path, due_date, notes,
            content_hash, now, now, now,
        )
    )
    conn.commit()
    conn.close()

    log_event(
        source_tool=source_tool,
        event_type="task.created",
        task_id=task_id,
        payload={"task_id": task_id, "title": title, "priority": priority},
    )

    return task_id


def update_task_status(task_id: str, new_status: str, source_tool: str = "manual"):
    """Promote/dismiss a task. new_status: high|medium|low|done|dismissed|snoozed"""
    now = _now()
    completed_at = now if new_status == "done" else None
    conn = get_conn()
    conn.execute(
        """UPDATE tasks SET status = ?, priority = ?,
           completed_at = COALESCE(?, completed_at),
           updated_at = ?
           WHERE task_id = ?""",
        (
            new_status,
            new_status if new_status in ("high", "medium", "low") else None,
            completed_at, now, task_id,
        )
    )
    conn.commit()
    conn.close()

    log_event(
        source_tool=source_tool,
        event_type="task.updated",
        task_id=task_id,
        payload={"task_id": task_id, "new_status": new_status},
    )


# ─────────────────────────────────────────────
# METRICS
# ─────────────────────────────────────────────

def log_metric(
    *,
    metric_name: str,
    value: float,
    source_tool: str,
    date_str: str | None = None,        # YYYY-MM-DD, defaults to today
    notes: str | None = None,
):
    """
    Upsert a daily metric. Overwrites existing value for same date+name+tool.

    Common metric_name values:
        browser_focus_score     (0-100, from browser_analyzer)
        git_commits             (count, from git_watcher)
        transcript_minutes      (float, from whisper)
        screenshots_processed   (count, from screenshot_organizer)
        tasks_completed         (count, from briefing)
        tasks_created           (count, from briefing/whisper)
        deep_work_minutes       (float, future)

    Example:
        log_metric(metric_name="browser_focus_score", value=74.2,
                   source_tool="browser_analyzer")
    """
    date_str = date_str or date.today().isoformat()
    conn = get_conn()
    conn.execute(
        """INSERT INTO metrics_daily (date, metric_name, value, source_tool, notes)
           VALUES (?,?,?,?,?)
           ON CONFLICT(date, metric_name, source_tool) DO UPDATE SET
               value = excluded.value,
               notes = excluded.notes,
               created_at = created_at""",
        (date_str, metric_name, value, source_tool, notes)
    )
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# EVENTS
# ─────────────────────────────────────────────

def log_event(
    *,
    source_tool: str,
    event_type: str,
    payload: dict,
    artifact_id: str | None = None,
    session_id: str | None = None,
    task_id: str | None = None,
    correlation_id: str | None = None,
):
    """
    Append an event to the event log. Fire-and-forget — never fails silently.

    This is called automatically by log_artifact, log_session, log_task.
    You can also call it directly for custom events.

    Example:
        log_event(
            source_tool="browser_analyzer",
            event_type="focus.metrics.updated",
            payload={"date": "2026-03-24", "focus_score": 74.2},
        )
    """
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO events
               (ts, source_tool, event_type, artifact_id, session_id,
                task_id, payload_json, correlation_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                _now(), source_tool, event_type, artifact_id, session_id,
                task_id, json.dumps(payload), correlation_id,
            )
        )
        conn.commit()
    except Exception as e:
        print(f"[db] Warning: event logging failed: {e}")
    finally:
        conn.close()


# ─────────────────────────────────────────────
# DAILY ROLLUP
# ─────────────────────────────────────────────

def write_daily_rollup(
    *,
    date_str: str,
    browser_focus_score: float | None = None,
    git_commits: int | None = None,
    tasks_completed: int | None = None,
    tasks_created: int | None = None,
    transcript_minutes: float | None = None,
    screenshots_new: int | None = None,
    artifacts_created: int | None = None,
    top_topics: list[str] | None = None,
    top_domains: list[str] | None = None,
    briefing_path: str | None = None,
):
    """Called once per day by Daily Briefing."""
    conn = get_conn()
    conn.execute(
        """INSERT INTO daily_rollups
           (date, browser_focus_score, git_commits, tasks_completed, tasks_created,
            transcript_minutes, screenshots_new, artifacts_created,
            top_topics, top_domains, briefing_path)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(date) DO UPDATE SET
               browser_focus_score = COALESCE(excluded.browser_focus_score, browser_focus_score),
               git_commits         = COALESCE(excluded.git_commits, git_commits),
               tasks_completed     = COALESCE(excluded.tasks_completed, tasks_completed),
               tasks_created       = COALESCE(excluded.tasks_created, tasks_created),
               transcript_minutes  = COALESCE(excluded.transcript_minutes, transcript_minutes),
               screenshots_new     = COALESCE(excluded.screenshots_new, screenshots_new),
               artifacts_created   = COALESCE(excluded.artifacts_created, artifacts_created),
               top_topics          = COALESCE(excluded.top_topics, top_topics),
               top_domains         = COALESCE(excluded.top_domains, top_domains),
               briefing_path       = COALESCE(excluded.briefing_path, briefing_path)""",
        (
            date_str, browser_focus_score, git_commits, tasks_completed, tasks_created,
            transcript_minutes, screenshots_new, artifacts_created,
            json.dumps(top_topics) if top_topics else None,
            json.dumps(top_domains) if top_domains else None,
            briefing_path,
        )
    )
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# CONVENIENCE QUERIES
# ─────────────────────────────────────────────

def get_todays_metrics() -> dict:
    """Quick read for Daily Briefing — all metrics for today."""
    today = date.today().isoformat()
    conn = get_conn()
    rows = conn.execute(
        "SELECT metric_name, value, source_tool FROM metrics_daily WHERE date = ?",
        (today,)
    ).fetchall()
    conn.close()
    return {r["metric_name"]: r["value"] for r in rows}


def get_open_tasks(priority: str | None = None) -> list[dict]:
    """Return open tasks, optionally filtered by priority."""
    conn = get_conn()
    if priority:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status = ? ORDER BY created_at ASC",
            (priority,)
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM tasks
               WHERE status NOT IN ('done','dismissed')
               ORDER BY
                 CASE status
                   WHEN 'high' THEN 1
                   WHEN 'medium' THEN 2
                   WHEN 'low' THEN 3
                   WHEN 'unconfirmed' THEN 4
                   ELSE 5
                 END,
                 created_at ASC"""
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_artifacts(artifact_type: str = None, limit: int = 20) -> list[dict]:
    """Return recent artifacts, optionally filtered by type."""
    conn = get_conn()
    if artifact_type:
        rows = conn.execute(
            "SELECT * FROM artifacts WHERE type = ? ORDER BY created_at DESC LIMIT ?",
            (artifact_type, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM artifacts ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_trend(metric_name: str, days: int = 30) -> list[dict]:
    """Return daily values for a metric over the last N days."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT date, value FROM metrics_daily
           WHERE metric_name = ?
           AND date >= date('now', ?)
           ORDER BY date ASC""",
        (metric_name, f"-{days} days")
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# INTERNAL
# ─────────────────────────────────────────────

def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


# ─────────────────────────────────────────────
# CLI — quick diagnostics
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "init":
        init_db()
        print("Done.")

    elif len(sys.argv) > 1 and sys.argv[1] == "stats":
        conn = get_conn()
        for table in ["artifacts", "sessions", "tasks", "events", "metrics_daily"]:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:<20} {count} rows")
        conn.close()

    elif len(sys.argv) > 1 and sys.argv[1] == "tasks":
        tasks = get_open_tasks()
        print(f"\n  Open tasks ({len(tasks)}):")
        for t in tasks:
            print(f"  [{t['status']:<12}] {t['title']}")

    elif len(sys.argv) > 1 and sys.argv[1] == "metrics":
        m = get_todays_metrics()
        print(f"\n  Today's metrics:")
        for k, v in m.items():
            print(f"  {k:<30} {v}")

    else:
        print("Usage:")
        print("  python db.py init     — create tables")
        print("  python db.py stats    — row counts per table")
        print("  python db.py tasks    — show open tasks")
        print("  python db.py metrics  — show today's metrics")
