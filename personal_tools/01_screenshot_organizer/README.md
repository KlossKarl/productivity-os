# Project 1 — Screenshot Organizer

> Renames 4,000+ screenshots from gibberish to meaningful names using LLaVA vision model locally. Builds a searchable index. Feeds into the Second Brain.

**Status:** ✅ Live — 4,237 screenshots indexed

---

## What It Does

- Walks your ShareX screenshots folder recursively
- Sends each image to LLaVA (local vision model via Ollama) — no API key, no cost
- Gets a plain-English description, tags, and a meaningful filename slug
- Renames files from `brave_7x1UknX58l.png` → `2026-03-19_nfl-draft-rankings-dashboard.png`
- Builds `index.csv` with description, tags, date, and path for every screenshot
- Converts index to Obsidian markdown notes for Second Brain indexing
- Resumable — safe to stop and restart anytime

---

## Scripts

| Script | What it does |
|--------|-------------|
| `organize_screenshots.py` | Main organizer — processes new screenshots, reprocesses weak ones |
| `screenshots_to_md.py` | Converts index.csv → Obsidian markdown for Second Brain indexing |

---

## Setup

```powershell
pip install requests pillow tqdm
ollama pull llava:13b   # recommended — better at reading text and UI
# or
ollama pull llava:7b    # faster, weaker descriptions
```

---

## Usage

### Process new screenshots
```powershell
python organize_screenshots.py
```
Skips already-processed files automatically. Safe to run repeatedly.

### Check how many descriptions are generic/weak
```powershell
python organize_screenshots.py --stats
```

### Re-run on weak descriptions only
```powershell
# Test first — see what would be reprocessed
python organize_screenshots.py --reprocess-generic --dry-run

# Reprocess all generic entries (can take a while — ~1800 images)
python organize_screenshots.py --reprocess-generic

# Reprocess just the first 50 to test quality
python organize_screenshots.py --reprocess-generic --limit 50

# Use a specific model
python organize_screenshots.py --reprocess-generic --model llava:13b
```

### Convert index to Obsidian markdown
```powershell
python screenshots_to_md.py              # convert all months
python screenshots_to_md.py --stats     # show stats
python screenshots_to_md.py --month 2026-03  # single month
```

### Index into Second Brain
```powershell
cd ..\08_second_brain
python second_brain.py --index
```

### Search screenshots via Second Brain
```powershell
python second_brain.py --search "NTI scouting dashboard"
python second_brain.py --search "fantasy football rankings february"
python second_brain.py --search "python error terminal"
```

---

## File Structure

```
ShareX/
  Screenshots/
    2025-12/   — 6 screenshots
    2026-01/   — 15 screenshots
    2026-02/   — 1,707 screenshots
    2026-03/   — 2,509 screenshots
  index.csv    — master index (4,237 entries)

Obsidian Vault/
  Screenshots/
    Screenshots 2025-12.md
    Screenshots 2026-01.md
    Screenshots 2026-02.md
    Screenshots 2026-03.md
```

---

## Model Notes

| Model | Speed | Quality | VRAM |
|-------|-------|---------|------|
| `llava:7b` | Fast (~2s/img) | Generic descriptions | ~5GB |
| `llava:13b` | Slower (~5s/img) | Much better at reading text and UI | ~9GB |

RTX 4070 Ti (12GB) handles `llava:13b` comfortably.

---

## Improving Description Quality

If descriptions are too generic ("developer work session"), run:
```powershell
python organize_screenshots.py --reprocess-generic --model llava:13b
```

The improved prompt forces LLaVA to name specific apps, websites, and content
instead of defaulting to generic descriptions. Then re-run `screenshots_to_md.py`
and re-index the Second Brain.

---

## Dependencies

- Python 3.12
- `requests`, `pillow`, `tqdm`
- Ollama running locally with `llava:7b` or `llava:13b`
