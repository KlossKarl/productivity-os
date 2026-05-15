# 17 Intent Switcher

Declares a work mode (Build, Debug, Learn, Admin, Review) and configures your environment in one shot: opens the VSCode workspace, opens an Obsidian note, writes a `active_focus_rules.json` file listing blocked sites, runs optional terminal commands, plays a mode-specific audio cue, and logs the session. Can also infer your mode from recent browser history, git activity, and open tasks using Ollama `llama3:8b`. Ending a session saves a re-entry note to Obsidian.

## How to run

```
# Interactive mode picker
python switcher.py

# Switch directly to a mode
python switcher.py build
python switcher.py debug
python switcher.py learn
python switcher.py admin
python switcher.py review

# Let Ollama infer mode from recent activity
python switcher.py --infer

# Show current session status
python switcher.py --status

# Show session history
python switcher.py --history

# End current session and save re-entry note to Obsidian
python switcher.py --end
```

## What it outputs

- Writes `active_focus_rules.json` with blocked sites list (consumed by other blocking tools)
- Writes `current_session.json` tracking the active mode and start time
- Logs sessions to local `switcher_history.db`
- Saves `Obsidian Vault/Re-entry Notes/YYYY-MM-DD_HHMM reentry-{mode}.md` on `--end`
- Logs session start to shared `productivity_os.db` if available

## Config

Mode definitions live in `modes.yaml` (auto-created on first run with defaults for all 5 modes). Edit this file to change VSCode workspaces, Obsidian notes, blocked sites, and welcome messages per mode.

| Constant | Default |
|---|---|
| `OLLAMA_MODEL` | `llama3:8b` |
| `OBSIDIAN_VAULT` | `C:\Users\Karl\Documents\Obsidian Vault` |
| `VSCODE_PATH` | `C:\Users\Karl\AppData\Local\Programs\Microsoft VS Code\Code.exe` |
