# 21 Energy Correlator

Quick mood/energy logger (low / medium / high) that correlates entries with same-day productivity metrics from the shared DB — focus score, git commits, and deep work minutes. After a few days of logging the `insights` command surfaces patterns like "high energy days → +23% focus vs low energy days."

## How to run

```
# Interactive log (3 prompts: level, one-word reason, optional note)
python energy_correlator.py log
python energy_correlator.py

# Log directly without prompts
python energy_correlator.py log --level high --reason focused --note "slept 8hrs"
python energy_correlator.py log --level low --reason tired

# Show today's energy logs + correlated productivity metrics
python energy_correlator.py today

# Show patterns across all logged days
python energy_correlator.py insights

# Show recent log history
python energy_correlator.py history
```

## What it outputs

- Writes to `energy_logs` table in shared DB: timestamp, level, reason, note
- Writes `energy_score` metric to `metrics_daily` (low=25, medium=60, high=90)
- `insights` correlates dominant daily energy level with avg focus score, avg commits/day, avg deep work minutes across all logged days
- `today` shows today's logs alongside same-day focus score, commits, and deep work minutes

## Config

No config.yaml keys. One hardcoded path:

| Constant | Default |
|---|---|
| `SHARED_DB` | `C:\Users\Karl\Documents\productivity_os.db` |

Requires shared DB to exist. Run any other tool first to create it.
