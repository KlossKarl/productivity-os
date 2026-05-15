# 11 Daily Briefing

Generates a morning briefing by scanning recent Obsidian notes (Transcripts, Browser Reports, road maps) for action items using `llama3:8b`, then building a narrative summary with `deepseek-r1:14b` that references your actual task names, yesterday's commits, and browser focus score. Saves the briefing note to Obsidian and prints a terminal summary. Also supports interactive triage of auto-extracted tasks.

## How to run

```
# Full morning briefing (scan notes + pull data + generate narrative + save to Obsidian)
python briefing.py

# Scan notes and update Tasks.md only — no briefing generated
python briefing.py --extract

# Print current Tasks.md to terminal
python briefing.py --tasks

# Interactively sort unconfirmed tasks (h=High / m=Medium / l=Low / d=Dismiss / s=Skip)
python briefing.py --triage

# Scan further back (default: 7 days)
python briefing.py --days 14
```

## What it outputs

- Writes `Obsidian Vault/Briefings/YYYY-MM-DD Daily Briefing.md` with: yesterday summary, focus score, commits, stale tasks, top 3 priorities, watch-out, recommendation
- Appends auto-extracted action items to `Obsidian Vault/Tasks.md` under `⚠ Unconfirmed` section
- Writes daily rollup and metrics to shared `productivity_os.db`
- Prints terminal summary

## Config

All paths are hardcoded. Key constants:

| Constant | Default |
|---|---|
| `OBSIDIAN_VAULT` | `C:\Users\Karl\Documents\Obsidian Vault` |
| `OLLAMA_MODEL_FAST` | `llama3:8b` (per-note task extraction) |
| `OLLAMA_MODEL_SMART` | `deepseek-r1:14b` (briefing narrative) |
| `GIT_REPOS` | `C:\Users\Karl\Documents\productivity-os` |
| `SHARED_DB` | `C:\Users\Karl\Documents\productivity_os.db` |

Requires Ollama with both models pulled. Shared DB is optional — degrades gracefully to standalone mode.
