# Productivity OS

> Build a personal productivity OS from tools that run natively on your machine.
> No subscriptions. No cloud lock-in. Your data stays yours.

---

## Projects

| # | Project | Status | What it does |
|---|---------|--------|--------------|
| 01 | [Screenshot Organizer](./01_screenshot_organizer/) | ✅ Live | Renames 4,237 screenshots using LLaVA vision model, builds searchable index, feeds Second Brain |
| 02 | [Downloads Auto-Categorizer](./02_downloads_categorizer/) | ✅ Live | Watches Downloads, sorts files automatically using rules + LLM |
| 03 | [Whisper Transcription](./03_whisper_transcription/) | ✅ Live | Transcribes any audio/video locally, summarizes with Ollama, saves to Obsidian |
| 04 | Git Commit Generator | ⬜ Planned | Auto-writes commit messages from your staged diff |
| 05 | Changelog Generator | ⬜ Planned | Generates CHANGELOG.md from git history |
| 06 | Code Search Engine | ⬜ Planned | Natural language search across all local projects |
| 07 | [Browser History Analyzer](./07_browser_analyzer/) | ✅ Live | Weekly report of topics, focus score, peak hours, and what to explore next |
| 08 | [Obsidian Second Brain](./08_second_brain/) | ✅ Live | Chat with all your notes + codebase via local LLM — fully private RAG system |
| 09 | Screenpipe Integration | ⬜ Planned | Searchable record of everything on screen |
| 10 | Browser Agent | ⬜ Planned | Automate web tasks with browser-use |
| 11 | [Daily Briefing](./11_daily_briefing/) | ✅ Live | Morning summary of tasks, commits, focus score — Obsidian note + terminal output |
| 12 | Unified Dashboard | ⬜ Planned | Single view of the entire OS |
| 13 | Unified Task Brain | ⬜ Planned | SQLite-backed task list fed by all sources |
| 14 | Focus Guardian | ⬜ Planned | Context-aware distraction blocker |
| 15 | Communication Command Center | ⬜ Planned | Extract action items from email/Slack/Discord |
| 16 | Time & Energy Observatory | ⬜ Planned | Correlate activity data to find your peak hours |
| 17 | Intent-Aware Environment Switcher | ⬜ Planned | One keystroke to switch your entire work environment |

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
Walks your entire ShareX screenshots folder and sends every image to LLaVA (local vision model) for analysis. Renames files from gibberish (`brave_7x1UknX58l.png`) to meaningful names (`2026-03-19_nfl-draft-rankings-dashboard.png`). Builds a fully searchable `index.csv` with descriptions, tags, dates, and paths for 4,237 screenshots. `screenshots_to_md.py` converts the index into Obsidian markdown notes so the Second Brain can search across your entire screenshot history. Supports `--reprocess-generic` to re-run weak descriptions and `--compare` to benchmark llava:7b vs llava:13b side by side. Resumable — safe to stop and restart anytime.

### 02 — Downloads Auto-Categorizer
Runs silently at Windows startup via Task Scheduler (no console window). Watches your Downloads folder in real time and sorts every file into `PDFs/`, `Images/`, `Code/`, `Finance/`, `Reading/` etc. Uses extension rules first, Ollama LLM for ambiguous files (invoice vs whitepaper), quarantines unknowns to `_review/`. Learns from corrections via `teach` command.

### 03 — Whisper Transcription Pipeline
Point it at any `.mp4`, `.mp3`, `.m4a`, `.webm` or other audio/video file. Runs OpenAI Whisper locally — no API, no cost. Outputs a full timestamped transcript, sends it to Ollama for structured summary with key points, action items, decisions, and people mentioned. Saves a formatted note directly into Obsidian. Supports watch mode for auto-transcription.

### 07 — Browser History Analyzer
Reads your Brave/Chrome history (local SQLite DB) and generates a structured weekly + monthly report. Smart classification — YouTube and Reddit are judged by page title and subreddit, not just domain. Reports include focus score, peak hours, topics you're deep in, focus killers, and personalized "explore next" recommendations. Saves to Obsidian.

### 08 — Obsidian Second Brain
Full RAG system. Indexes your entire Obsidian vault + selected codebases into ChromaDB using `mxbai-embed-large` embeddings. Chat with all of it using `deepseek-r1:14b`. Supports `/notes`, `/code`, `/all` filters. Includes PDF-to-markdown converter for adding any PDF to the knowledge base. The more notes you add, the smarter it gets.

### 11 — Daily Briefing
Runs every morning via Task Scheduler. Scans your Obsidian vault (transcripts, browser reports, roadmaps) for action items and auto-populates `Tasks.md` with unconfirmed tasks. Interactive `--triage` mode lets you sort the unconfirmed queue with a single keypress. Pulls yesterday's git commits, browser focus score, and stale tasks. Generates a sharp morning narrative using `deepseek-r1:14b`, saves a briefing note to `Obsidian Vault/Briefings/`, and prints a terminal summary. No manual tagging required — reads your task list exactly as you wrote it.

---

## Setup

Each project lives in its own numbered folder with its own README and install instructions.
Clone the repo and go project by project:

```powershell
git clone https://github.com/KlossKarl/productivity-os.git
cd productivity-os
```

**Core dependencies:**
```powershell
pip install watchdog requests openai-whisper chromadb pyyaml pdfplumber pillow tqdm
ollama pull llama3:8b
ollama pull deepseek-r1:14b
ollama pull mxbai-embed-large
ollama pull llava:13b
```

---

*Living document — updated as each project ships.*
*Last updated: March 2026 — v3.0 — Projects 1, 2, 3, 7, 8, 11 live.*
