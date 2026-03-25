# productivity-os

Local productivity intelligence stack. Everything runs on your machine. Your data stays yours.

**Ingests:** git activity, browser history, app/window usage, audio/video files, filesystem events, mood logs.<br>
**Processes:** locally via Ollama (llama3:8b, deepseek-r1:14b) and Whisper on GPU. Claude API for high-quality summarization.<br>
**Stores:** single SQLite DB + ChromaDB vector store. Nothing leaves your machine except optional Claude API calls.<br>
**Outputs:** daily briefings, focus scores, deep work blocks, RAG search over everything.

`Python 3.12` · `SQLite` · `ChromaDB` · `Ollama` · `Whisper` · `pygetwindow` · `Claude API (optional)`

---

## Why this exists

Most productivity tools are either expensive, cloud-dependent, or siloed. The ones that are free don't integrate. The ones that integrate want your data.

This is a personal stack — built for one person, on one machine, with one database everything writes to. The goal isn't to compete with Notion or RescueTime. It's to build something those tools structurally can't: a system that sees your notes, your code, your transcripts, your browser history, and your git commits together — and lets you query all of it with a local LLM.

---

## The core: Second Brain (Project 08)

The most useful thing here is the RAG system. It indexes your entire Obsidian vault, configured codebases, transcripts, and browser reports into ChromaDB and lets you chat against all of it with `deepseek-r1:14b`.

No cloud tool does this. Notion AI doesn't know your code. Mem doesn't know your transcripts. Granola doesn't talk to your notes. This does — because all the other tools in this stack feed the same database.

```powershell
python second_brain.py --index   # index everything
python second_brain.py --chat    # start a session
```

Filter by source:
- `/notes` — Obsidian vault only
- `/code` — codebases only
- `/all` — everything (default)

The more you add to the vault — transcripts, browser reports, PDFs — the more useful it gets.

---

## What's built

### 01 — Screenshot Organizer
Walks a screenshots folder, sends each image to LLaVA vision model, renames files from timestamps to plain-English descriptions, builds a searchable `index.csv`. Companion script converts the index to Obsidian markdown for Second Brain indexing.

### 02 — Downloads Auto-Categorizer
Runs at startup via Task Scheduler. Watches Downloads in real time, sorts by extension rules first, Ollama LLM for ambiguous cases. Quarantines unknowns to `_review/` with a daily digest. Learns new rules via `teach` command.

### 03 — Whisper Transcription + Learning Pipeline
Runs OpenAI Whisper locally on GPU — no API key, no cost for transcription. Full timestamped transcript, structured summary saved to Obsidian. Watch mode auto-processes anything dropped into a folder. Outputs feed the Second Brain.

**Summarization:** routes to Claude API (Haiku, ~$0.002/lecture) or local Ollama depending on config. Claude produces dense study guides with key concepts, definitions, examples, and action items — not shallow bullet points.

**Batch mode:** point at any folder and process an entire course overnight. Skips files already processed. Supports `--limit N` for test runs.

```powershell
# Single file
python transcribe.py lecture.mp3

# Whole course folder
python transcribe.py --batch "C:\yt-dlp\out\CS221"

# Test run — first 5 only
python transcribe.py --batch "C:\yt-dlp\out\CS221" --limit 5

# Force summarizer
python transcribe.py --batch "C:\yt-dlp\out" --summarizer claude
python transcribe.py --batch "C:\yt-dlp\out" --summarizer local
```

### 07 — Browser History Analyzer
Reads Brave/Chrome history from the local SQLite DB. YouTube and Reddit are classified by page title and subreddit — not just domain. Generates 7-day and 30-day reports: focus score, peak hours, deep topics, distractions. Saves to Obsidian, writes metrics to shared DB.

> The YouTube/Reddit classification is the meaningful part. Tools that call all of YouTube "entertainment" are useless for developers.

### 08 — Obsidian Second Brain
Full RAG pipeline over Obsidian vault + codebases. `mxbai-embed-large` embeddings, `deepseek-r1:14b` for chat. Source filters: `/notes`, `/code`, `/all`. Includes `pdf_to_md.py` for adding PDFs to the knowledge base. The more context you give it, the better it gets.

As lecture transcripts accumulate, cross-lecture queries become possible: *"how does the alignment problem evolve across CS221?"* or *"connect the tensor concepts from lecture 1 to the backprop discussion in lecture 4."*

### 09 — Window Activity Tracker
Polls the active foreground window every 60 seconds via `pygetwindow`. Groups sessions, classifies by category (coding, terminal, browsing, notes, communication, gaming, distraction). Gaming is neutral — doesn't affect focus score. Logs to shared DB.

### 11 — Daily Briefing
Runs at 8am via Task Scheduler. Scans Obsidian for action items, extracts unconfirmed tasks. Interactive triage mode — single keypress to promote or dismiss. Reads from shared DB (commits, focus score, open tasks), generates a narrative briefing with `deepseek-r1:14b`, writes daily rollup back.

### 17 — Intent Switcher
Win+1–5 for Build / Debug / Learn / Admin / Review modes. Each opens the configured VSCode workspace and Obsidian note, writes focus rules to `active_focus_rules.json`, logs to shared DB. Win+0 lets Ollama infer the mode from recent activity. Win+- ends the session and saves a re-entry note.

### 18 — Git Activity Watcher
Polls configured repos every 5 minutes. On new commits: extracts diff stats, generates a one-sentence summary via Ollama, logs a coding session to shared DB. `--today` for a full daily summary. Runs as a startup task.

### 19 — Deep Work Detector
Runs every 30 minutes. Correlates git sessions with browser focus scores in rolling windows. Scores blocks 0–100: 40% commit activity, 60% browser focus. Logs to `deep_work_blocks`, writes to shared DB. `--today` and `--week` for summaries.

### 21 — Energy Correlator
CLI check-in: energy level, one-word reason, optional note. After a week of data, `insights` shows how focus score, commit count, and deep work minutes shift by energy level.

---

## Roadmap

### Near term
| # | Feature | Status |
|---|---------|--------|
| 03a | Course index note — auto-generate a master summary + lecture index after batch processing a full course | ⬜ Planned |
| 03b | Flashcard extraction — Claude already has definitions and key concepts, one more prompt generates Anki-ready cards | ⬜ Planned |
| 04 | Git Commit Generator — auto-writes commit messages from staged diff | ⬜ Planned |
| 05 | Changelog Generator — generates CHANGELOG.md from git history | ⬜ Planned |
| 06 | Code Search Engine — natural language search across all local projects | ⬜ Planned |

### Ambitious
| # | Feature | Status |
|---|---------|--------|
| 08a | Interactive quiz mode — "test me on CS221 lecture 1" via Second Brain | ⬜ Planned |
| 08b | Cross-lecture concept tracking — "how does alignment evolve across the course?" | ⬜ Planned |
| 08c | Prerequisite mapping — Claude reads syllabus and builds concept dependency graph | ⬜ Planned |
| 09 | Screenpipe Integration — searchable record of everything on screen | ⬜ Planned |
| 10 | Browser Agent — automate web tasks with browser-use | ⬜ Planned |
| 12 | Unified Dashboard — single view of the entire OS | ⬜ Planned |
| 13 | Unified Task Brain — SQLite-backed task list fed by all sources | ⬜ Planned |
| 14 | Focus Guardian — context-aware distraction blocker | ⬜ Planned |
| 15 | Communication Command Center — extract action items from email/Slack/Discord | ⬜ Planned |
| 16 | Time & Energy Observatory — correlate activity data to find peak hours | ⬜ Planned |

---

## Shared infrastructure

All tools write to one database. Nothing stays siloed.

```
productivity_os.db      SQLite — sessions, tasks, metrics, artifacts, rollups
db.py                   shared access layer
```

| Tool | Sessions | Tasks | Metrics |
|------|----------|-------|---------|
| Whisper | ✅ listening | ✅ action items | ✅ transcript_min |
| Browser Analyzer | ✅ browsing | — | ✅ focus scores |
| Git Watcher | ✅ coding | — | ✅ commits, lines |
| Daily Briefing | — | ✅ read/write | ✅ daily rollup |
| Deep Work Detector | ✅ deep_work | — | ✅ dw_minutes |
| Energy Correlator | — | — | ✅ energy_score |
| Intent Switcher | ✅ mode | — | — |
| Window Tracker | ✅ app sessions | — | ✅ productive_min |

The shared DB is what makes the Second Brain useful over time. Every transcript, focus report, and coding session that gets logged is context it can retrieve.

---

## What this doesn't do

Being explicit about the ceiling:

- **No live meeting transcription.** Whisper is file-in / file-out. It doesn't join calls or caption in real time.
- **No dynamic calendar scheduling.** There's no write-back to Google Calendar. Analysis only.
- **No mobile.** Everything runs on Windows desktop.
- **No team features.** Single user, single machine, by design — that's what makes the privacy guarantee possible.
- **No polished UI.** This is a CLI/terminal stack. If you want a beautiful app, use the SaaS tools.

If those are dealbreakers, the tools that do them well are Granola (meetings), Reclaim (calendar), and Notion (collaboration). They're good. They just cost money and they have your data.

---

## Honest hardware note

The stack is tuned for an RTX 4070 Ti (12GB VRAM) with 32GB RAM. `deepseek-r1:14b` needs the VRAM. `mxbai-embed-large` runs fine on CPU but indexing is faster on GPU. Whisper runs on GPU automatically when CUDA PyTorch is installed — ~5x faster than CPU. On lower-end hardware, swap `deepseek-r1:14b` for `llama3:8b` and `mxbai-embed-large` for `nomic-embed-text`.

---

## Privacy

This stack reads browser history, file activity, git commits, app usage, and audio. Here is exactly what happens to that data:

- All processing runs on `localhost`. The only external network call is the optional Claude API for summarization — transcript text is sent, nothing else.
- No accounts required. No telemetry.
- Everything lands in one SQLite file at a path you set. Open it, inspect it, delete it whenever you want.
- All scheduled tasks are registered under your own Windows account and visible in Task Scheduler.
- The code is here. Read it before running it.

---

## Setup

```powershell
git clone https://github.com/KlossKarl/productivity-os.git
cd productivity-os
python setup.py   # auto-detects paths, pulls models, writes config.yaml
pip install watchdog requests openai-whisper chromadb pyyaml pdfplumber pygetwindow anthropic
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

Optional — add your Anthropic API key to `config.yaml` for Claude summaries:
```yaml
anthropic:
  api_key: "sk-ant-..."
  model: claude-haiku-4-5-20251001
```

Start with Project 08 (Second Brain) — it's the most immediately useful and gives you a reason to add everything else.

---

*Last updated: March 2026 — Projects 1, 2, 3, 7, 8, 9, 11, 17, 18, 19, 21 live.*
