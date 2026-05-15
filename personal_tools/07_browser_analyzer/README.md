# 07 Browser Analyzer

Reads Brave browser history (local SQLite DB), scores visits as productive vs. distraction with smart YouTube/Reddit classification, then sends the data to Ollama `llama3:8b` for a narrative summary. Outputs a structured markdown report saved to Obsidian and backed up locally. Also writes focus score, visit counts, and session data to the shared `productivity_os.db`.

## How to run

```
# Run full report for both 7-day and 30-day windows
python browser_analysis.py

# Custom window
python browser_analysis.py --days 14

# Print to terminal only, skip Obsidian
python browser_analysis.py --no-obsidian
```

## What it outputs

- Markdown report at `Obsidian Vault/Browser Reports/YYYY-MM-DD Browser Report (Nd).md`
- Local backup at `C:\Users\Karl\Documents\transcripts\`
- Report includes: focus score %, top productive/distraction domains, peak hours, LLM narrative, topics deep in, focus killers, explore-next suggestions
- Writes to shared DB: 1 artifact row, 1 session row, 4 metric rows (focus score, total visits, productive/distraction visit counts)

## Config

All paths are hardcoded. Key constants:

| Constant | Default |
|---|---|
| `BRAVE_HISTORY` | `C:\Users\Karl\AppData\Local\BraveSoftware\...\History` |
| `OBSIDIAN_VAULT` | `C:\Users\Karl\Documents\Obsidian Vault` |
| `OLLAMA_MODEL` | `llama3:8b` |
| `SHARED_DB` | `C:\Users\Karl\Documents\productivity_os.db` |

Requires Brave installed and Ollama running with `llama3:8b`. The script copies the DB to a temp file automatically so Brave doesn't need to be closed.
