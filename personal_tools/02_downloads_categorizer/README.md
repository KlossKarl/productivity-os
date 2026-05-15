# 02 Downloads Categorizer

Watches `C:\Users\Karl\Downloads` in real time and automatically moves files into typed subfolders (`PDFs/`, `Images/`, `Code/`, `Installers/`, `ZIPs/`, `Videos/`, `Docs/`, `Finance/`, `Reading/`). Extension rules handle most files instantly; ambiguous types (`.pdf`, `.txt`, `.md`, `.csv`, `.zip`, `.docx`) get a second pass through Ollama `llama3:8b` to determine the right bucket. Files it can't classify go to `_review/`. All moves are logged to a local SQLite DB.

## How to run

```
# Start the file watcher (runs until Ctrl+C)
python downloads_watcher.py

# Print today's move digest
python downloads_watcher.py digest

# Teach a custom keyword rule
python downloads_watcher.py teach stripe Finance
python downloads_watcher.py teach invoice Finance

# Register as a Windows startup task
.\install_startup_task.ps1
```

## What it outputs

- Moves files into subfolders under `C:\Users\Karl\Downloads\`
- Writes move log to `_categorizer_log.db` (tables: `moves`, `review_items`)
- Writes text log to `_categorizer.log`
- Prints daily digest on Ctrl+C showing files moved by folder and pending review items
- Saves custom keyword rules to `_categorizer_rules.json`

## Config

All paths are hardcoded. Key constants in the script header:

| Constant | Default |
|---|---|
| `DOWNLOADS_DIR` | `C:\Users\Karl\Downloads` |
| `OLLAMA_MODEL` | `llama3:8b` |

Requires Ollama running locally with `llama3:8b` pulled. Ollama is optional — falls back to rule-based classification if unavailable.
