# Productivity OS

> Build a personal productivity OS from tools that run natively on your machine.
> No subscriptions. No cloud lock-in. Your data stays yours.

---

## Projects

| # | Project | Status | What it does |
|---|---------|--------|--------------|
| 02 | [Downloads Auto-Categorizer](./02_downloads_categorizer/) | ✅ Live | Watches Downloads, sorts files automatically using rules + LLM |
| 03 | [Whisper Transcription](./03_whisper_transcription/) | ✅ Live | Transcribes any audio/video locally, summarizes with Ollama, saves to Obsidian |
| 04 | Git Commit Generator | ⬜ Planned | Auto-writes commit messages from your staged diff |
| 05 | Changelog Generator | ⬜ Planned | Generates CHANGELOG.md from git history |
| 06 | Code Search Engine | ⬜ Planned | Natural language search across all local projects |
| 07 | [Browser History Analyzer](./07_browser_analyzer/) | ✅ Live | Weekly report of topics, focus score, peak hours, and what to explore next |
| 08 | [Obsidian Second Brain](./08_second_brain/) | ✅ Live | Chat with all your notes + codebase via local LLM — fully private RAG system |
| 09 | Screenpipe Integration | ⬜ Planned | Searchable record of everything on screen |
| 10 | Browser Agent | ⬜ Planned | Automate web tasks with browser-use |
| 11 | Daily Briefing | ⬜ Planned | Morning summary of tasks, commits, calendar |
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
- **Local LLMs:** Ollama — llava:7b, deepseek-coder:6.7b, llama3:8b, deepseek-r1:14b, gemma3:4b
- **Embeddings:** mxbai-embed-large (ChromaDB)
- **Editor:** VSCode
- **Storage:** SQLite + ChromaDB (shared across all projects)
- **Philosophy:** Free, local, private. No subscriptions, no cloud lock-in.

---

## What's Built

### 02 — Downloads Auto-Categorizer
Runs silently at Windows startup. Watches your Downloads folder in real time and sorts every file into `PDFs/`, `Images/`, `Code/`, `Finance/`, `Reading/` etc. Uses extension rules first, Ollama LLM for ambiguous files (invoice vs whitepaper), quarantines unknowns to `_review/`. Learns from corrections via `teach` command.

### 03 — Whisper Transcription Pipeline
Point it at any `.mp4`, `.mp3`, `.m4a`, `.webm` or other audio/video file. Runs OpenAI Whisper locally — no API, no cost. Outputs a full timestamped transcript, sends it to Ollama for structured summary with key points, action items, decisions, and people mentioned. Saves a formatted note directly into Obsidian. Supports watch mode for auto-transcription.

### 07 — Browser History Analyzer
Reads your Brave/Chrome history (local SQLite DB) and generates a structured weekly + monthly report. Smart classification — YouTube and Reddit are judged by page title and subreddit, not just domain. Reports include focus score, peak hours, topics you're deep in, focus killers, and personalized "explore next" recommendations. Saves to Obsidian.

### 08 — Obsidian Second Brain
Full RAG system. Indexes your entire Obsidian vault + selected codebases into ChromaDB using `mxbai-embed-large` embeddings. Chat with all of it using `deepseek-r1:14b`. Supports `/notes`, `/code`, `/all` filters. Includes PDF-to-markdown converter for adding any PDF to the knowledge base. The more notes you add, the smarter it gets.

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
pip install watchdog requests openai-whisper chromadb pyyaml pdfplumber
ollama pull llama3:8b
ollama pull deepseek-r1:14b
ollama pull mxbai-embed-large
```

---

*Living document — updated as each project ships.*
*Last updated: March 2026 — Projects 2, 3, 7, 8 live.*
