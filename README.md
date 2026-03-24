# Productivity OS

> Build a personal productivity OS from tools that run natively on your machine.
> No subscriptions. No cloud lock-in. Your data stays yours.

---

## Why This Exists

Google, Microsoft, and your browser already track everything this OS tracks — they do it silently, send it to their servers, and sell the insights. This project does the same thing openly, locally, and gives you the data instead.

Every tool runs on your machine. All data stays in a SQLite file you own and can read. No accounts, no telemetry, no network calls except to localhost. You can delete the entire thing in 30 seconds.

This is built for developers and builders who want to understand their own work patterns without handing that data to anyone else.

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
| 09 | Screenpipe Integration | ⬜ Planned | Searchable record of everything on screen |
| 10 | Browser Agent | ⬜ Planned | Automate web tasks with browser-use |
| 11 | Daily Briefing | ✅ Live | Morning summary of open tasks, recent commits, focus score — Obsidian note + terminal output |
| 12 | Unified Dashboard | ⬜ Planned | Single local web UI showing all OS metrics and a command palette |
| 13 | Unified Task Brain | ⬜ Planned | SQLite-backed canonical task list fed by all sources with CLI interface |
| 14 | Focus Guardian | ⬜ Planned | Context-aware distraction blocker tied to your actual focus data |
| 15 | Communication Command Center | ⬜ Planned | Extract action items and deadlines from email into the Task Brain |
| 16 | Time & Energy Observatory | ⬜ Planned | Correlate browser, git, and session data to map your peak productivity windows |
| 17 | Intent-Aware Environment Switcher | ✅ Live | One keystroke to switch your entire work environment by declared mode |
| 18 | Git Activity Watcher | ✅ Live | Polls repos every 5 min, summarizes commits with LLM, logs coding sessions to shared DB |
| 19 | Deep Work Detector | ✅ Live | Correlates browser + git sessions to automatically score and log deep work blocks |
| 20 | Forgotten Recall | ⬜ Planned | Weekly resurface of high-value notes not touched in 30+ days — adds to Daily Briefing |
| 21 | Energy Correlator | ✅ Live | Quick mood logging CLI that correlates energy levels with productivity metrics over time |
| 22 | Vault Cleanup Scanner | ⬜ Planned | Detects duplicate, stale, and orphaned Obsidian notes using embedding similarity |
| 23 | Distraction Blocker | ⬜ Planned | Analyzes distraction patterns, generates Brave focus rules, reports effectiveness |
| 24 | Idea Capture Processor | ⬜ Planned | Watches an Inbox folder for text/audio, transcribes, routes to the right project in Obsidian |
| 25 | Project Health Checker | ⬜ Planned | Scores each project by commit velocity, task staleness, and focus allocation |
| 26 | Productivity Dashboard | ⬜ Planned | Queries all metrics for 30/90-day KPI charts and narrative summaries saved to Obsidian |
| 27 | Email Intelligence | ⬜ Planned | Gmail semantic search, action item extraction, thread summarization, attachment parsing |
| 28 | Contact Memory Builder | ⬜ Planned | Builds per-person Obsidian profiles from mentions across transcripts and emails |
| 29 | Receipt OCR Processor | ⬜ Planned | LLaVA OCR on receipt images, extracts merchant/amount/category, tracks monthly spend |

---

## Stack

- **OS:** Windows (PowerShell)
- **Language:** Python 3.12
- **Local LLMs:** Ollama — llava:7b, llava:13b, deepseek-coder:6.7b, llama3:8b, deepseek-r1:14b, gemma3:4b
- **Embeddings:** mxbai-embed-large (ChromaDB)
- **Editor:** VSCode
- **Storage:** SQLite + ChromaDB (shared across all projects)
- **Philosophy:** Free, local, private. No subscriptions, no cloud lock-in.

---

## What's Built

### 01 — Screenshot Organizer
Walks a screenshots folder and sends each image to a local LLaVA vision model. Generates a plain-English description and tags for every screenshot, renames files from timestamps to descriptive names, and builds a fully searchable `index.csv`. A companion script converts the index to an Obsidian markdown note for Second Brain indexing. Resumable — safe to stop and restart at any point.

### 02 — Downloads Auto-Categorizer
Runs silently at Windows startup via Task Scheduler. Watches your Downloads folder in real time and sorts every file into `PDFs/`, `Images/`, `Code/`, `Finance/`, `Reading/` and more. Uses extension rules first, Ollama LLM for ambiguous files (invoice vs whitepaper), quarantines unknowns to `_review/` with a daily digest. Learns from corrections via a `teach` command.

### 03 — Whisper Transcription Pipeline
Point it at any `.mp4`, `.mp3`, `.m4a`, `.webm` or other audio/video file. Runs OpenAI Whisper locally — no API key, no cost. Outputs a full timestamped transcript, then sends it to Ollama for a structured summary with key points, action items, decisions, and people mentioned. Saves a formatted note directly into Obsidian. Supports watch mode for auto-transcription.

### 07 — Browser History Analyzer
Reads your Brave/Chrome history (local SQLite DB) and generates a structured weekly and monthly report. Smart classification — YouTube and Reddit are judged by page title and subreddit, not just domain. Reports include focus score, peak hours, topics you're deep in, focus killers, and personalized recommendations. Saves to Obsidian.

### 08 — Obsidian Second Brain
Full RAG system. Indexes your entire Obsidian vault and selected codebases into ChromaDB using `mxbai-embed-large` embeddings. Chat with all of it using `deepseek-r1:14b`. Supports `/notes`, `/code`, `/all` source filters. Includes a PDF-to-markdown converter for adding any PDF to the knowledge base. Gets smarter as your vault grows.

### 11 — Daily Briefing
Runs every morning via Task Scheduler. Scans recent transcripts, browser reports, and vault notes for action items. Auto-extracts tasks into `Tasks.md` marked as unconfirmed. Interactive triage mode (`--triage`) for single-keypress promotion or dismissal. Pulls yesterday's git commits and focus score. Generates a narrative briefing using `deepseek-r1:14b` and saves it to Obsidian. Reads from and writes to the shared DB.

### 17 — Intent-Aware Environment Switcher
Declare a work mode — Build, Debug, Learn, Admin, or Review — via a single hotkey or CLI command. Automatically opens the right VSCode workspace, Obsidian note, and applies focus rules. Can infer your mode from recent browser activity, open tasks, and git commits using Ollama. Saves a re-entry note to Obsidian at session end so you can pick up exactly where you left off.

### 18 — Git Activity Watcher
Runs silently at startup. Polls all configured repos every 5 minutes for new commits. Sends commit messages and diff stats to Ollama for a one-sentence summary of what was accomplished. Logs coding sessions, lines changed, and files touched to the shared database. `--today` command gives a full daily coding summary.

### 19 — Deep Work Detector
Runs every 30 minutes via Task Scheduler. Correlates git coding sessions and browser focus scores within rolling time windows. Scores each block 0-100 based on commit activity and distraction-free browsing. Logs deep work sessions to the shared DB — feeds into the Time & Energy Observatory when built.

### 21 — Energy Correlator
Quick CLI mood check-in — log your energy level (low/medium/high), a one-word reason, and an optional note in under 10 seconds. Correlates energy logs with same-day focus score, commit count, and deep work minutes. After a week of logging, `insights` shows real patterns: "high energy days average +23% focus and 2x the commits."

---

## Shared Infrastructure

Every tool writes to a shared SQLite database (`productivity_os.db`) instead of staying siloed. A shared access layer (`db.py`) handles all logging of artifacts, sessions, tasks, and daily metrics.

```
productivity_os.db   — 9-table shared SQLite DB
db.py                — shared access layer (import and use, never open DB directly)
```

### What each tool writes today

| Tool | Sessions | Tasks | Metrics | Artifacts |
|------|----------|-------|---------|-----------|
| Whisper Transcription | ✅ | ✅ action items | ✅ transcript_minutes | ✅ |
| Browser History Analyzer | ✅ | — | ✅ focus scores | ✅ |
| Git Activity Watcher | ✅ coding | — | ✅ commits, lines | ✅ |
| Daily Briefing | — | ✅ read + write | ✅ daily rollup | — |
| Deep Work Detector | ✅ deep_work | — | ✅ deep_work_minutes | — |
| Energy Correlator | — | — | ✅ energy_score | — |
| Intent Switcher | ✅ mode sessions | — | — | — |

---

## Privacy

This OS reads your browser history, file activity, git commits, and audio recordings. Here is exactly what it does with that data:

- **Everything stays on your machine.** No data is sent anywhere except to `localhost:11434` (your local Ollama instance).
- **No accounts, no telemetry, no API keys required.** The LLMs run locally via Ollama.
- **All data lives in one SQLite file** at a path you choose. Open it with any SQLite viewer. Delete it whenever you want.
- **No background phone-home.** All scheduled tasks are registered under your own Windows account and visible in Task Scheduler.
- **You own the code.** Read every line before running anything.

The difference between this and spyware: you run it, you read it, you own it.

---

## Setup

Clone the repo and go project by project. Each project lives in its own numbered folder with its own README and install instructions.

```powershell
git clone https://github.com/KlossKarl/productivity-os.git
cd productivity-os
```

**Core dependencies:**
```powershell
pip install watchdog requests openai-whisper chromadb pyyaml pdfplumber
ollama pull llama3:8b
ollama pull deepseek-r1:14b
ollama pull mxbai-embed-large
```

---

*Living document — updated as each project ships.*
*Last updated: March 2026 — Projects 1, 2, 3, 7, 8, 11, 17, 18, 19, 21 live.*
