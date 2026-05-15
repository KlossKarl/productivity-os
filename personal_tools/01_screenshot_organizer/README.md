# 01 Screenshot Organizer

Walks your ShareX screenshots folder, sends each image to LLaVA running locally via Ollama, and renames the file to a meaningful slug (`2026-03-14_vscode-python-import-error.png`). Builds a searchable `index.csv` and can export monthly markdown notes into your Obsidian vault for second-brain indexing.

## How to run

```
# Process new screenshots (skips already-indexed ones)
python organize_screenshots.py

# Preview renames without touching files
python organize_screenshots.py --dry-run

# Re-run LLaVA on entries with weak/generic descriptions
python organize_screenshots.py --reprocess-generic

# Show index stats and top tags
python organize_screenshots.py --stats

# Override the default model (llava:13b)
python organize_screenshots.py --model llava:7b

# Compare llava:7b vs llava:13b on 20 generic images
python organize_screenshots.py --compare

# Convert index.csv to Obsidian markdown notes
python screenshots_to_md.py
python screenshots_to_md.py --month 2026-03
```

## What it outputs

- Renames image files in-place to `YYYY-MM-DD_kebab-slug.ext`
- Appends rows to `index.csv` with: original name, new name, date, description, tags, path
- `screenshots_to_md.py` writes one `Screenshots YYYY-MM.md` per month into `Obsidian Vault/Screenshots/`

## Config

All paths are hardcoded in the script headers. Key constants:

| Constant | Default |
|---|---|
| `SCREENSHOTS_DIR` | `C:\Users\Karl\Documents\ShareX\Screenshots` |
| `INDEX_FILE` | `C:\Users\Karl\Documents\ShareX\index.csv` |
| `MODEL` | `llava:13b` |
| `OBSIDIAN_VAULT` | `C:\Users\Karl\Documents\Obsidian Vault` |

Requires Ollama running locally with `llava:13b` (or `llava:7b`) pulled.
