# Personal Tools

These are personal productivity tracking tools built on top of the loom stack.
They are not part of the core knowledge base product but may be useful as examples or starting points.

## Tools

- **01_screenshot_organizer** — Renames ShareX screenshots to meaningful slugs using LLaVA (local vision model) and exports a searchable index to Obsidian
- **02_downloads_categorizer** — Watches the Downloads folder and auto-routes files into typed subfolders using extension rules + Ollama LLM for ambiguous types
- **07_browser_analyzer** — Reads Brave history, scores productive vs. distraction visits, and generates a weekly focus report in Obsidian via Ollama
- **09_window_tracker** — Polls the active window every 60 seconds, classifies apps by category, and logs productive/distraction minutes to the shared DB
- **11_daily_briefing** — Scans Obsidian notes for action items, pulls git log and browser stats, and generates a morning briefing note with LLM narrative
- **17_intent_switcher** — Switches work mode (Build/Debug/Learn/Admin/Review), opens the right VSCode workspace and Obsidian note, and writes site-blocking rules
- **18_git_watcher** — Polls configured repos every 5 minutes for new commits and logs coding sessions with LLM-generated summaries to the shared DB
- **19_deep_work_detector** — Correlates git commits and browser focus scores to identify and score deep work blocks, runs every 30 minutes as a scheduled task
- **21_energy_correlator** — Logs mood/energy level (low/medium/high) and correlates entries with same-day focus score, commits, and deep work minutes
