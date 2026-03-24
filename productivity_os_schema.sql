-- ============================================================
-- productivity_os.db  —  Shared Schema
-- Karl's Productivity OS
-- 
-- Philosophy:
--   Every tool writes here. No tool reads another tool's private DB.
--   Integration happens through these tables, not file scraping.
--
-- Tools that populate this DB:
--   Project 1  — Screenshot Organizer       → artifacts, tags, artifact_tags
--   Project 2  — Downloads Categorizer      → artifacts, tags, artifact_tags
--   Project 3  — Whisper Transcription      → artifacts, sessions, tags, metrics_daily
--   Project 7  — Browser History Analyzer   → sessions, metrics_daily
--   Project 8  — Second Brain (RAG)         → (reads mostly; writes indexing_runs)
--   Project 11 — Daily Briefing             → tasks, events, daily_rollups
-- ============================================================

PRAGMA journal_mode=WAL;   -- safe concurrent writes from multiple scripts
PRAGMA foreign_keys=ON;

-- ============================================================
-- PROJECTS
-- Everything else can reference a project_id.
-- Manually maintained — add rows as needed.
-- ============================================================

CREATE TABLE IF NOT EXISTS projects (
    project_id      TEXT PRIMARY KEY,          -- e.g. 'productivity-os', 'fantasy-football'
    name            TEXT NOT NULL,
    status          TEXT DEFAULT 'active',      -- active | paused | archived
    obsidian_note   TEXT,                       -- relative vault path
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ============================================================
-- ARTIFACTS
-- Anything content-like that a tool produced or processed.
-- One row per file/note/report/transcript/screenshot.
-- ============================================================

CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id     TEXT PRIMARY KEY,           -- UUID
    type            TEXT NOT NULL,              -- screenshot | transcript | download | note
                                                -- browser_report | briefing | pdf | code_file
    source_tool     TEXT NOT NULL,              -- screenshot_organizer | downloads_categorizer
                                                -- whisper | browser_analyzer | second_brain | briefing
    path_or_url     TEXT,                       -- absolute local path or URL
    title           TEXT,                       -- human-readable name / filename stem
    summary         TEXT,                       -- LLM-generated or extracted summary
    project_id      TEXT REFERENCES projects(project_id),
    obsidian_path   TEXT,                       -- relative path inside vault (if saved there)
    word_count      INTEGER,
    duration_secs   REAL,                       -- for audio/video artifacts
    language        TEXT,                       -- e.g. 'en', for transcripts
    quality_score   REAL,                       -- 0-1, tool-assigned confidence/quality
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    source_file     TEXT,                       -- original file that produced this artifact
    extra_json      TEXT                        -- catch-all for tool-specific metadata (JSON)
);

CREATE INDEX IF NOT EXISTS idx_artifacts_type        ON artifacts(type);
CREATE INDEX IF NOT EXISTS idx_artifacts_source_tool ON artifacts(source_tool);
CREATE INDEX IF NOT EXISTS idx_artifacts_created_at  ON artifacts(created_at);
CREATE INDEX IF NOT EXISTS idx_artifacts_project_id  ON artifacts(project_id);

-- ============================================================
-- TAGS
-- Canonical tag vocabulary. All tools share this.
-- Prevents tag explosion (e.g. "nfl" vs "NFL" vs "football-nfl").
-- ============================================================

CREATE TABLE IF NOT EXISTS tags (
    tag_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,       -- always lowercase, hyphen-separated
    kind            TEXT DEFAULT 'topic',       -- topic | person | project | source | type
    canonical_of    INTEGER REFERENCES tags(tag_id)  -- point to canonical if this is an alias
);

-- ============================================================
-- ARTIFACT_TAGS  (many-to-many)
-- ============================================================

CREATE TABLE IF NOT EXISTS artifact_tags (
    artifact_id     TEXT NOT NULL REFERENCES artifacts(artifact_id) ON DELETE CASCADE,
    tag_id          INTEGER NOT NULL REFERENCES tags(tag_id),
    role            TEXT DEFAULT 'auto',        -- auto | confirmed | rejected
    confidence      REAL DEFAULT 1.0,           -- 0-1
    PRIMARY KEY (artifact_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_artifact_tags_tag ON artifact_tags(tag_id);

-- ============================================================
-- SESSIONS
-- Time-bounded activity blocks.
-- Browser sessions, work blocks, transcription listening sessions,
-- deep work windows (future), Screenpipe sessions (future).
-- ============================================================

CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT PRIMARY KEY,           -- UUID
    kind            TEXT NOT NULL,              -- browser | coding | listening | deep_work
    start_ts        TEXT NOT NULL,              -- ISO 8601 UTC
    end_ts          TEXT,                       -- NULL if still active
    duration_min    REAL,                       -- computed: (end_ts - start_ts) in minutes
    focus_score     REAL,                       -- 0-100
    project_id      TEXT REFERENCES projects(project_id),
    summary         TEXT,                       -- short LLM description of the session
    source_tool     TEXT NOT NULL,
    artifact_id     TEXT REFERENCES artifacts(artifact_id),  -- the report/transcript artifact
    extra_json      TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_kind     ON sessions(kind);
CREATE INDEX IF NOT EXISTS idx_sessions_start_ts ON sessions(start_ts);
CREATE INDEX IF NOT EXISTS idx_sessions_project  ON sessions(project_id);

-- ============================================================
-- TASKS
-- Canonical task list. Fed by: briefing (extraction),
-- whisper (action items), future comms center.
-- This is the single source of truth — NOT Tasks.md alone.
-- Tasks.md is rendered output; this table is the DB.
-- ============================================================

CREATE TABLE IF NOT EXISTS tasks (
    task_id         TEXT PRIMARY KEY,           -- UUID
    title           TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'unconfirmed',
                                                -- unconfirmed | high | medium | low
                                                -- done | dismissed | snoozed
    priority        TEXT,                       -- high | medium | low (after triage)
    project_id      TEXT REFERENCES projects(project_id),
    source_tool     TEXT,                       -- briefing | whisper | comms_center
    source_artifact TEXT REFERENCES artifacts(artifact_id),  -- which note/transcript it came from
    source_note_path TEXT,                      -- raw vault path for traceability
    due_date        TEXT,                       -- ISO date, optional
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    completed_at    TEXT,
    last_seen_at    TEXT,                       -- last time briefing confirmed this still exists in notes
    content_hash    TEXT,                       -- MD5 of title — deduplication guard
    notes           TEXT                        -- free-form context / original excerpt
);

CREATE INDEX IF NOT EXISTS idx_tasks_status     ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_project    ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_hash ON tasks(content_hash)
    WHERE status NOT IN ('done', 'dismissed');  -- don't dedupe completed tasks

-- ============================================================
-- METRICS_DAILY
-- One row per (date, metric_name, source_tool).
-- Easy to query trends: SELECT * FROM metrics_daily WHERE metric_name = 'browser_focus_score'
-- ============================================================

CREATE TABLE IF NOT EXISTS metrics_daily (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            TEXT NOT NULL,              -- YYYY-MM-DD
    metric_name     TEXT NOT NULL,              -- browser_focus_score | git_commits
                                                -- transcript_minutes | screenshots_processed
                                                -- tasks_completed | tasks_created
                                                -- deep_work_minutes (future)
    value           REAL NOT NULL,
    source_tool     TEXT NOT NULL,
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (date, metric_name, source_tool)     -- one value per metric per tool per day
);

CREATE INDEX IF NOT EXISTS idx_metrics_date   ON metrics_daily(date);
CREATE INDEX IF NOT EXISTS idx_metrics_name   ON metrics_daily(metric_name);

-- ============================================================
-- EVENTS  (append-only event log)
-- Every tool appends rows here when something meaningful happens.
-- Used for: debugging, correlation, future event-driven triggers.
-- Never update or delete rows — append only.
-- ============================================================

CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    source_tool     TEXT NOT NULL,
    event_type      TEXT NOT NULL,              -- artifact.created | artifact.updated
                                                -- session.created | task.created
                                                -- task.updated | task.completed
                                                -- focus.metrics.updated | indexing.completed
                                                -- daily.rollup.completed
    artifact_id     TEXT,                       -- denormalized for fast lookups
    session_id      TEXT,
    task_id         TEXT,
    payload_json    TEXT NOT NULL,              -- full event payload as JSON
    correlation_id  TEXT                        -- group related events (e.g. one briefing run)
);

CREATE INDEX IF NOT EXISTS idx_events_ts         ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_type       ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_source     ON events(source_tool);
CREATE INDEX IF NOT EXISTS idx_events_artifact   ON events(artifact_id);
CREATE INDEX IF NOT EXISTS idx_events_corr       ON events(correlation_id);

-- ============================================================
-- DAILY_ROLLUPS
-- One row per day, written by Daily Briefing at EOD/morning.
-- Quick summary stats — no need to re-aggregate every query.
-- ============================================================

CREATE TABLE IF NOT EXISTS daily_rollups (
    date                TEXT PRIMARY KEY,       -- YYYY-MM-DD
    browser_focus_score REAL,
    git_commits         INTEGER,
    tasks_completed     INTEGER,
    tasks_created       INTEGER,
    transcript_minutes  REAL,
    screenshots_new     INTEGER,
    artifacts_created   INTEGER,
    top_topics          TEXT,                   -- JSON array of strings
    top_domains         TEXT,                   -- JSON array of strings
    briefing_path       TEXT,                   -- vault path to briefing note
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ============================================================
-- INDEXING_RUNS
-- Tracks every Second Brain re-index: what ran, how long, 
-- what changed. Lets tools know if RAG is stale.
-- ============================================================

CREATE TABLE IF NOT EXISTS indexing_runs (
    run_id          TEXT PRIMARY KEY,           -- UUID
    scope           TEXT NOT NULL,              -- notes | code | transcripts | screenshots | all
    started_at      TEXT NOT NULL,
    completed_at    TEXT,
    files_indexed   INTEGER DEFAULT 0,
    files_skipped   INTEGER DEFAULT 0,
    chunks_total    INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'running',     -- running | completed | failed
    error_msg       TEXT
);

-- ============================================================
-- SEED DATA — Canonical tag kinds
-- ============================================================

INSERT OR IGNORE INTO tags (name, kind) VALUES
    ('meeting', 'type'),
    ('podcast', 'type'),
    ('lecture', 'type'),
    ('voice-memo', 'type'),
    ('transcript', 'type'),
    ('screenshot', 'type'),
    ('browser-report', 'type'),
    ('briefing', 'type'),
    ('pdf', 'type'),
    ('finance', 'topic'),
    ('code', 'topic'),
    ('ai', 'topic'),
    ('nfl', 'topic'),
    ('fantasy-football', 'topic'),
    ('productivity', 'topic');

-- ============================================================
-- SEED DATA — Default projects
-- ============================================================

INSERT OR IGNORE INTO projects (project_id, name, status, obsidian_note) VALUES
    ('productivity-os', 'Productivity OS', 'active', 'Projects/productivity-os.md'),
    ('inbox', 'Inbox (unclassified)', 'active', NULL);
