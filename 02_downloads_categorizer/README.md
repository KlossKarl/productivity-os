# Downloads Auto-Categorizer
Karl's Productivity OS — Project 2

---

## Setup (one time, ~5 minutes)

### 1. Install dependencies
```powershell
pip install watchdog requests
```
Ollama must be running with llama3:8b pulled:
```powershell
ollama pull llama3:8b
```

### 2. Copy files
```powershell
mkdir $env:USERPROFILE\productivity_os\downloads_categorizer
# Copy downloads_watcher.py here
```

### 3. Test it manually first
```powershell
python downloads_watcher.py
# Drop a file into Downloads and watch the log
# Ctrl+C to stop
```

### 4. Install as background startup task (run as Administrator)
```powershell
.\install_startup_task.ps1
Start-ScheduledTask -TaskName "DownloadsCategorizer"
```

---

## Daily usage

The script runs silently. You'll never notice it.

**Check today's digest:**
```powershell
python downloads_watcher.py digest
```

**Teach it a custom rule** (it'll remember forever):
```powershell
python downloads_watcher.py teach invoice Finance
python downloads_watcher.py teach "annual report" Reading
python downloads_watcher.py teach "setup_" Installers
```

**Check the log:**
```powershell
Get-Content $env:USERPROFILE\Downloads\_categorizer.log -Tail 50
```

---

## How it decides

1. **Custom rules** (your corrections) — checked first, always win
2. **Extension rules** — fast lookup for 50+ file types
3. **LLM pass** — for ambiguous types (.pdf, .txt, .md, .csv, .zip, .docx)
   - e.g. a PDF named "invoice_march_2026.pdf" → Finance/
   - e.g. a PDF named "deep-learning-whitepaper.pdf" → Reading/
4. **Unknown extension** → _review/ quarantine

---

## Folder structure created in Downloads/

```
Downloads/
├── PDFs/
├── Images/
├── Code/
├── Installers/
├── ZIPs/
├── Videos/
├── Docs/
├── Finance/
├── Reading/
├── _review/          ← uncertain files, check these
├── _categorizer.log  ← full activity log
├── _categorizer_log.db  ← SQLite history
└── _categorizer_rules.json  ← your learned rules
```

---

## Integration with Productivity OS

The SQLite DB (`_categorizer_log.db`) feeds into the central `events` table in Phase 3.
Every move becomes an event: `{"source": "downloads", "type": "file_moved", "folder": "Finance", ...}`
