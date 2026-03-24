# productivity-os

Local productivity intelligence stack.

**Ingests:** git activity, browser history, app/window usage, audio/video files, filesystem events, mood logs.<br>
**Processes:** locally via Ollama (llama3:8b, deepseek-r1:14b) and Whisper.<br>
**Stores:** single SQLite DB + ChromaDB vector store. Nothing else.<br>
**Outputs:** daily briefings, focus scores, deep work blocks, RAG search over everything.

No accounts. No cloud dependencies. No data leaving your machine.

`Python 3.12` · `SQLite` · `ChromaDB` · `Ollama` · `Whisper` · `pygetwindow`

---

## Why This Exists

The tools that do this well are either expensive, cloud-dependent, or abandoned. The ones that are free don't integrate. This fixes that.

One local stack. One database. Everything talks to everything else. Built for people who want the insight without the subscription — and who'd rather own their data than rent access to it.

The entire pipeline — activity capture, transcription, browser analysis, LLM inference, vector search — runs on local hardware. Data lives in a SQLite file. Models run via Ollama. Nothing is transmitted. Nothing is monetized.

---

## Projects

| # | Project | Status | What it does |
|---|---------|--------|--------------|
| 01 | Screenshot Organizer | ✅ Live | Renames screenshots using a local vision model, builds a searchable index, feeds Second Brain |
| 02 | Downloads Auto-Categorizer | ✅ Live | Watches Downloads folder, sorts files automatically using rules + LLM fallback |
| 03 | Whisper Transcription | ✅ Live | Transcribes any audio/video locally, summarizes with Ollama, saves structured notes to Obsidian |
| 04 | Git Commit Generator | ⬜ Planned | Auto-writes conventional commit messages from staged diffs |
| 05 | Changelog Generator | ⬜ Planned | Generates CHANGELOG.md from git history |
| 06 | Code Search Engine | ⬜ Planned | Natural language search across all local projects |
| 07 | Browser History Analyzer | ✅ Live | Weekly report of browsing patterns, focus score, peak hours, and topic recommendations |
| 08 | Obsidian Second Brain | ✅ Live | Chat with your notes and codebase via a local LLM — fully private RAG system |
| 09 | Window Activity Tracker | ✅ Live | Tracks active app every 60s, classifies sessions, feeds focus scoring pipeline |
| 10 | Browser Agent | ⬜ Planned | Automate web tasks with browser-use |
| 11 | Daily Briefing | ✅ Live | Morning summary of open tasks, commits, focus score — reads from and writes to shared DB |
| 12 | Unified Dashboard | ⬜ Planned | Single local web UI across all OS metrics |
| 13 | Unified Task Brain | ⬜ Planned | CLI interface over the shared tasks table — fed by all sources |
| 14 | Focus Guardian | ⬜ Planned | Context-aware distraction blocker driven by your actual focus history |
| 15 | Communication Command Center | ⬜ Planned | Extract action items and deadlines from email into the task pipeline |
| 16 | Time & Energy Observatory | ⬜ Planned | Cross-source correlation to map peak productivity windows |
| 17 | Intent Switcher | ✅ Live | Hotkey-driven environment switching — opens workspace, Obsidian note, and focus rules per mode |
| 18 | Git Activity Watcher | ✅ Live | Polls repos every 5 min, summarizes commits via LLM, logs coding sessions to shared DB |
| 19 | Deep Work Detector | ✅ Live | Correlates browser + git sessions into scored deep work blocks, runs every 30 min |
| 20 | Forgotten Recall | ⬜ Planned | Surfaces high-value notes not touched in 30+ days — pushes to Daily Briefing |
| 21 | Energy Correlator | ✅ Live | CLI mood logging correlated against same-day focus score, commits, and deep work |
| 22 | Vault Cleanup Scanner | ⬜ Planned | Detects duplicate and orphaned Obsidian notes via embedding similarity |
| 23 | Distraction Blocker | ⬜ Planned | Analyzes distraction patterns, generates and installs Brave focus rules |
| 24 | Idea Capture Processor | ⬜ Planned | Watches an Inbox folder for text/audio, transcribes, routes to the right project |
| 25 | Project Health Checker | ⬜ Planned | Scores projects by commit velocity, task staleness, and focus allocation |
| 26 | Productivity Dashboard | ⬜ Planned | 30/90-day KPI charts and narrative summaries from the shared DB |
| 27 | Email Intelligence | ⬜ Planned | Gmail IMAP semantic search, action item extraction, thread summarization |
| 28 | Contact Memory Builder | ⬜ Planned | Per-person Obsidian profiles built from mentions across transcripts and email |
| 29 | Receipt OCR Processor | ⬜ Planned | LLaVA OCR on receipts — extracts merchant, amount, category, tracks spend |

---

## What's Built

### 01 — Screenshot Organizer
Walks a screenshots folder and sends each image to a local LLaVA vision model. Generates plain-English descriptions and tags, renames files from timestamps to descriptive names, builds a fully searchable `index.csv`. Companion script converts the index to Obsidian markdown for Second Brain indexing. Resumable — progress is saved after every file.

### 02 — Downloads Auto-Categorizer
Runs at startup via Task Scheduler. Watches Downloads in real time and sorts every incoming file by extension rules first, Ollama LLM for ambiguous cases. Quarantines unknowns to `_review/` with a daily digest. Learns new rules via `teach` command.

### 03 — Whisper Transcription Pipeline
Runs OpenAI Whisper locally — no API key, no cost. Outputs a full timestamped transcript, then sends it to Ollama for a structured summary: key points, action items, decisions, people mentioned. Saves to Obsidian. Watch mode monitors a folder and auto-processes anything dropped in.

### 07 — Browser History Analyzer
Reads Brave/Chrome history from the local SQLite DB. YouTube and Reddit are classified by page title and subreddit, not just domain. Generates 7-day and 30-day reports with focus score, peak hours, deep topics, and distractions. Saves to Obsidian, writes metrics to shared DB.

### 08 — Obsidian Second Brain
Full RAG pipeline. Indexes the entire Obsidian vault and configured codebases into ChromaDB using `mxbai-embed-large`. Chat against all of it with `deepseek-r1:14b`. Source filters: `/notes`, `/code`, `/all`. Includes `pdf_to_md.py` for adding PDFs to the knowledge base.

### 09 — Window Activity Tracker
Polls the active foreground window every 60 seconds via `pygetwindow`. Groups consecutive same-app windows into sessions. Classifies by category: coding, terminal, browsing, notes, communication, gaming (neutral — doesn't affect focus score), distraction. Logs to `window_sessions` table and shared DB metrics. Startup task — runs silently.

### 11 — Daily Briefing
Runs at 8am via Task Scheduler. Scans Obsidian notes for action items and extracts them to `Tasks.md` as unconfirmed. Interactive triage mode for single-keypress promotion or dismissal. Reads open tasks from shared DB, pulls yesterday's commits and focus score, generates a narrative briefing with `deepseek-r1:14b`. Writes `daily_rollups` and metrics back to shared DB.

### 17 — Intent Switcher
Win+1 through Win+5 for Build / Debug / Learn / Admin / Review modes. Each mode opens the configured VSCode workspace and Obsidian note, writes focus rules to `active_focus_rules.json`, logs the session to shared DB. Win+0 lets Ollama infer the right mode from recent browser activity, open tasks, and git commits. Win+- ends the session and saves a re-entry note to Obsidian.

### 18 — Git Activity Watcher
Polls all configured repos every 5 minutes. On new commits: extracts diff stats, sends commit messages to Ollama for a one-sentence summary, logs a coding session to shared DB with lines added/removed/files changed. `--today` gives a full daily summary. Runs as a startup task.

### 19 — Deep Work Detector
Runs every 30 minutes via Task Scheduler. Correlates git coding sessions with browser focus scores in rolling time windows. Scores each block 0-100: commit activity weighted at 40%, browser focus at 60%. Logs to `deep_work_blocks` table and shared sessions. `--today` and `--week` for summaries.

### 21 — Energy Correlator
Three-question CLI check-in: energy level (low/medium/high), one-word reason, optional note. Logs to `energy_logs`, writes `energy_score` to `metrics_daily`. After a week of data, `insights` shows cross-correlated patterns: how focus score, commit count, and deep work minutes shift by energy level.

---

## Shared Infrastructure

All tools write to a single shared database rather than staying siloed.

```
productivity_os.db      SQLite — sessions, tasks, metrics, artifacts, rollups
db.py                   shared access layer — import and call, never open DB directly
```

| Tool | Sessions | Tasks | Metrics | Artifacts |
|------|----------|-------|---------|-----------|
| Whisper | ✅ listening | ✅ action items | ✅ transcript_min | ✅ |
| Browser Analyzer | ✅ browsing | — | ✅ focus scores | ✅ |
| Git Watcher | ✅ coding | — | ✅ commits, lines | ✅ |
| Daily Briefing | — | ✅ read/write | ✅ daily rollup | — |
| Deep Work Detector | ✅ deep_work | — | ✅ dw_minutes | — |
| Energy Correlator | — | — | ✅ energy_score | — |
| Intent Switcher | ✅ mode | — | — | — |
| Window Tracker | ✅ app sessions | — | ✅ productive_min | — |

---

## Privacy

This stack reads browser history, file activity, git commits, app usage, and audio. Here is exactly what happens to that data:

- All processing runs on `localhost`. The only network calls are to `localhost:11434` (Ollama).
- No accounts. No API keys required for core functionality. No telemetry.
- Everything lands in one SQLite file at a path you set. Open it with any SQLite viewer, delete it whenever you want.
- All scheduled tasks are registered under your own Windows account and visible in Task Scheduler. Nothing is hidden.
- The code is here. Read it before running it.

---

## Setup

```powershell
git clone https://github.com/KlossKarl/productivity-os.git
cd productivity-os
pip install watchdog requests openai-whisper chromadb pyyaml pdfplumber pygetwindow
ollama pull llama3:8b
ollama pull deepseek-r1:14b
ollama pull mxbai-embed-large
```

Each project has its own folder and install instructions. Start with whichever tool solves your most immediate problem — they're independent but designed to compound.

---

*Last updated: March 2026 — Projects 1, 2, 3, 7, 8, 9, 11, 17, 18, 19, 21 live.*
