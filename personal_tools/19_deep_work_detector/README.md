# 19 Deep Work Detector

Runs every 30 minutes (or on demand) and correlates coding sessions (git commits from the Git Watcher) with browser focus scores to identify "deep work" blocks. Scores each block 0–100 using a weighted formula: browser focus (60%) + commit bonus (up to +40). Blocks scoring below 40 are discarded. Logs detected blocks to the shared `productivity_os.db`.

## How to run

```
# Run detection now and log any new blocks
python deep_work_detector.py

# Show today's deep work blocks
python deep_work_detector.py --today

# Show last 7 days
python deep_work_detector.py --week

# Register as a Windows scheduled task (runs every 30 min)
python deep_work_detector.py --install
```

## What it outputs

- Writes to `deep_work_blocks` table in shared DB: start/end timestamps, duration, score, commit count, focus score, notes
- Also writes a session row (kind=deep_work) and a `deep_work_minutes` metric to shared DB
- Terminal display shows blocks with score bar, commit count, and focus score

## Detection logic

- **Strategy 1 (primary):** Each coding session (git commit batch) with score ≥ 40 = a deep work block. Duration estimated at 20 min/commit, capped at 90 min.
- **Strategy 2 (fallback):** If no commits but browser focus score ≥ 65% and ≥ 2 activity sessions exist, log a focus block.

## Config

All paths are hardcoded. Key thresholds:

| Constant | Default |
|---|---|
| `FOCUS_SCORE_THRESHOLD` | `65.0` % |
| `WINDOW_MINUTES` | `30` |
| `MIN_DEEP_WORK_MINUTES` | `20` |
| `SHARED_DB` | `C:\Users\Karl\Documents\productivity_os.db` |

Requires shared DB to exist. Run Git Watcher and Browser Analyzer first to populate session data.
