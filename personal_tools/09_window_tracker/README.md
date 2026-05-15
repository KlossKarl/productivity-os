# 09 Window Tracker

Polls the active foreground window every 60 seconds using `pygetwindow`. Groups consecutive same-app windows into sessions and classifies them as coding, terminal, browsing, notes, communication, gaming (neutral — doesn't affect focus score), or system. Logs sessions and daily productive/distraction minutes to the shared `productivity_os.db`, where they feed the Deep Work Detector.

## How to run

```
# Start tracking (runs until Ctrl+C)
python window_tracker.py

# Show today's app usage breakdown
python window_tracker.py --today

# Show last 7 days
python window_tracker.py --week

# Register as a Windows startup task (runs at login)
python window_tracker.py --install
```

## What it outputs

- Writes to `window_sessions` table in shared DB with: date, start/end timestamps, duration, app name, window title, category, is_productive flag
- Also increments `productive_app_minutes` / `distraction_app_minutes` in `metrics_daily`
- Terminal display shows per-app time with ✓ (productive) / ✗ (distraction) / ~ (gaming/neutral) markers

## Config

All paths are hardcoded. Key constants:

| Constant | Default |
|---|---|
| `SHARED_DB` | `C:\Users\Karl\Documents\productivity_os.db` |
| `POLL_SECS` | `60` |
| `MIN_SESSION_SECS` | `120` (2 min — shorter sessions ignored) |

Requires `pygetwindow`: `pip install pygetwindow`. Shared DB must exist (created by any other tool that runs first).
