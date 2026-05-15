# 18 Git Watcher

Polls configured git repos every 5 minutes for new commits. For each batch of new commits it gets diff stats (lines added/removed, files changed) and asks Ollama `llama3:8b` to summarize what was accomplished in one sentence. Logs coding sessions and metrics to the shared `productivity_os.db`, where they feed the Deep Work Detector and Daily Briefing.

## How to run

```
# Start polling (runs forever, press Ctrl+C to stop)
python git_watcher.py

# Scan once and exit
python git_watcher.py --once

# Print today's coding activity summary
python git_watcher.py --today

# Register as a Windows startup task (runs at login)
python git_watcher.py --install
```

## What it outputs

- Local `git_watcher.db` with tables: `seen_commits` (dedup), `coding_sessions` (per-batch summary + stats)
- Shared DB writes: 1 session row (kind=coding) + 4 metric rows (git_commits, lines_added, lines_removed, files_changed) per batch — values accumulate throughout the day
- Terminal output: repo name, commit count, lines changed, one-sentence LLM summary

## Config

Edit `WATCHED_REPOS` at the top of `git_watcher.py` to add repos. All other paths are hardcoded.

| Constant | Default |
|---|---|
| `POLL_INTERVAL_SECS` | `300` (5 minutes) |
| `OLLAMA_MODEL` | `llama3:8b` |
| `SHARED_DB` | `C:\Users\Karl\Documents\productivity_os.db` |

Requires Ollama with `llama3:8b` pulled. Shared DB is optional — local DB always works.
