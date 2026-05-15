# Browser History Analyzer
Karl's Productivity OS — Project 7

Reads your local Brave history, analyzes it with Ollama, and generates
a structured report answering: what are you deep in, what's killing your
focus, when are you most productive, and what should you explore next.
100% local — your browsing data never leaves your machine.

---

## Setup

No installs needed — uses only Python standard library + requests (already installed).

Just run it:
```powershell
python browser_analysis.py
```

---

## Usage

```powershell
# Full report — both 7 day and 30 day windows
python browser_analysis.py

# Custom window
python browser_analysis.py --days 14

# Print to terminal only, skip Obsidian
python browser_analysis.py --no-obsidian
```

---

## Output

Two reports saved to `Obsidian Vault/Browser Reports/`:
- `YYYY-MM-DD Browser Report (7d).md`
- `YYYY-MM-DD Browser Report (30d).md`

Each report contains:
- **Focus Score** — % of visits to productive vs distraction sites
- **Topics you're deep in** — LLM-inferred from your page titles
- **Actively building/researching** — what projects/areas you're working on
- **Focus killers** — sites eating your attention
- **Peak productivity window** — when you're most active
- **Recommendations** — concrete suggestions based on your patterns
- **Explore next** — topics worth diving into given your interests
- **Top sites table** — productive vs distraction split
- **Activity by hour** — sparkline chart of when you browse

---

## How it works

1. Copies the Brave SQLite history DB to a temp file (Brave locks the original)
2. Reads all visits within the time window
3. Counts domains, hours, days, classifies productive vs distraction
4. Sends a condensed summary + page title sample to Ollama for narrative analysis
5. Builds a structured markdown report and saves it to Obsidian

---

## Integration with Productivity OS

- Focus scores feed into Project 14 (Focus Guardian) to auto-schedule blockers
- Peak hour data feeds into Project 16 (Time & Energy Observatory)
- Run weekly as a scheduled task for ongoing tracking
