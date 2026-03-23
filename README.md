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
| 07 | Browser History Analyzer | ⬜ Planned | Weekly report of what you actually worked on |
| 08 | Obsidian Second Brain | ⬜ Planned | Chat with all your notes via local LLM |
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
- **Local LLMs:** Ollama — llava:7b, deepseek-coder:6.7b, llama3:8b, gemma3:4b
- **Editor:** VSCode
- **Storage:** SQLite (shared across all projects)
- **Philosophy:** Free, local, private. No subscriptions, no cloud lock-in.

---

## Setup

Each project lives in its own numbered folder with its own README and install instructions.
Clone the repo and go project by project:

```powershell
git clone https://github.com/KlossKarl/productivity-os.git
cd productivity-os
```

---

*Living document — updated as each project ships.*
