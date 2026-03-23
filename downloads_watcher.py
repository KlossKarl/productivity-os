"""
Downloads Auto-Categorizer
Karl's Productivity OS - Project 2

Watches C:/Users/Karl/Downloads in real time.
Rules-based sorting first, Ollama LLM fallback for ambiguous files.
Uncertain files quarantined to _review/ with daily digest.
"""

import os
import sys
import json
import shutil
import logging
import sqlite3
import requests
import time
from pathlib import Path
from datetime import datetime, date
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

DOWNLOADS_DIR   = Path(r"C:\Users\Karl\Downloads")
DB_PATH         = DOWNLOADS_DIR / "_categorizer_log.db"
RULES_PATH      = DOWNLOADS_DIR / "_categorizer_rules.json"
LOG_PATH        = DOWNLOADS_DIR / "_categorizer.log"
OLLAMA_URL      = "http://localhost:11434/api/generate"
OLLAMA_MODEL    = "llama3:8b"

FOLDERS = [
    "PDFs",
    "Images",
    "Code",
    "Installers",
    "ZIPs",
    "Videos",
    "Docs",
    "Finance",
    "Reading",
    "_review",
]

# ─────────────────────────────────────────────
# RULE-BASED EXTENSION MAP
# ─────────────────────────────────────────────

EXTENSION_RULES: dict[str, str] = {
    # PDFs (default — may be overridden by LLM to Finance/Reading)
    ".pdf":    "PDFs",

    # Images
    ".png":    "Images",
    ".jpg":    "Images",
    ".jpeg":   "Images",
    ".gif":    "Images",
    ".webp":   "Images",
    ".svg":    "Images",
    ".bmp":    "Images",
    ".tiff":   "Images",
    ".heic":   "Images",
    ".ico":    "Images",

    # Code
    ".py":     "Code",
    ".js":     "Code",
    ".ts":     "Code",
    ".jsx":    "Code",
    ".tsx":    "Code",
    ".html":   "Code",
    ".css":    "Code",
    ".json":   "Code",
    ".yaml":   "Code",
    ".yml":    "Code",
    ".toml":   "Code",
    ".sh":     "Code",
    ".ps1":    "Code",
    ".sql":    "Code",
    ".rs":     "Code",
    ".go":     "Code",
    ".cpp":    "Code",
    ".c":      "Code",
    ".h":      "Code",
    ".ipynb":  "Code",

    # Installers
    ".exe":    "Installers",
    ".msi":    "Installers",
    ".dmg":    "Installers",
    ".pkg":    "Installers",
    ".deb":    "Installers",
    ".rpm":    "Installers",
    ".appx":   "Installers",
    ".msix":   "Installers",

    # ZIPs / Archives
    ".zip":    "ZIPs",
    ".rar":    "ZIPs",
    ".7z":     "ZIPs",
    ".tar":    "ZIPs",
    ".gz":     "ZIPs",
    ".bz2":    "ZIPs",
    ".xz":     "ZIPs",

    # Videos
    ".mp4":    "Videos",
    ".mkv":    "Videos",
    ".mov":    "Videos",
    ".avi":    "Videos",
    ".webm":   "Videos",
    ".m4v":    "Videos",
    ".flv":    "Videos",
    ".wmv":    "Videos",

    # Docs
    ".docx":   "Docs",
    ".doc":    "Docs",
    ".xlsx":   "Docs",
    ".xls":    "Docs",
    ".pptx":   "Docs",
    ".ppt":    "Docs",
    ".odt":    "Docs",
    ".rtf":    "Docs",
    ".txt":    "Docs",
    ".md":     "Docs",
    ".csv":    "Docs",

    # Audio (bonus — not in folders list, lands in _review)
    ".mp3":    "_review",
    ".wav":    "_review",
    ".m4a":    "_review",
    ".flac":   "_review",
    ".aac":    "_review",
}

# These extensions get a SECOND PASS via LLM to refine the destination
LLM_REFINE_EXTENSIONS = {".pdf", ".txt", ".md", ".csv", ".zip", ".docx", ".doc"}

# Filenames that are temp/incomplete — skip entirely
SKIP_PATTERNS = [".crdownload", ".part", ".tmp", ".download", "~$"]

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS moves (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT    NOT NULL,
            filename    TEXT    NOT NULL,
            source      TEXT    NOT NULL,
            destination TEXT    NOT NULL,
            method      TEXT    NOT NULL,   -- 'rule' | 'llm' | 'fallback'
            folder      TEXT    NOT NULL,
            confirmed   INTEGER DEFAULT 1,  -- 0 = in _review, 1 = auto-moved
            notes       TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS review_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          TEXT    NOT NULL,
            filename    TEXT    NOT NULL,
            path        TEXT    NOT NULL,
            reason      TEXT,
            resolved    INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def log_move(filename, source, destination, method, folder, confirmed=1, notes=""):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "INSERT INTO moves (ts, filename, source, destination, method, folder, confirmed, notes) VALUES (?,?,?,?,?,?,?,?)",
        (datetime.now().isoformat(), filename, str(source), str(destination), method, folder, confirmed, notes)
    )
    conn.commit()
    conn.close()

def log_review(filename, path, reason):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "INSERT INTO review_items (ts, filename, path, reason) VALUES (?,?,?,?)",
        (datetime.now().isoformat(), filename, str(path), reason)
    )
    conn.commit()
    conn.close()

# ─────────────────────────────────────────────
# CUSTOM RULES (learned from corrections)
# ─────────────────────────────────────────────

def load_custom_rules() -> dict:
    if RULES_PATH.exists():
        return json.loads(RULES_PATH.read_text())
    return {}

def save_custom_rule(keyword: str, folder: str):
    rules = load_custom_rules()
    rules[keyword.lower()] = folder
    RULES_PATH.write_text(json.dumps(rules, indent=2))
    log.info(f"Saved custom rule: '{keyword}' → {folder}")

def apply_custom_rules(filename: str) -> str | None:
    rules = load_custom_rules()
    name_lower = filename.lower()
    for keyword, folder in rules.items():
        if keyword in name_lower:
            return folder
    return None

# ─────────────────────────────────────────────
# LLM CLASSIFICATION
# ─────────────────────────────────────────────

VALID_FOLDERS = ["PDFs", "Images", "Code", "Installers", "ZIPs", "Videos", "Docs", "Finance", "Reading", "_review"]

def classify_with_llm(filename: str, rule_guess: str) -> tuple[str, str]:
    """
    Returns (folder, notes) — folder is the LLM's classification,
    notes explains the reasoning.
    Falls back to rule_guess if Ollama is unavailable.
    """
    prompt = f"""You are a file organizer. Given a filename, decide which folder it belongs in.

Available folders: {", ".join(VALID_FOLDERS)}

Rules:
- PDFs: generic PDF files
- Finance: invoices, receipts, bank statements, tax docs, payslips, quotes, contracts with money
- Reading: ebooks, whitepapers, research papers, articles saved for later
- Images: photos, screenshots, graphics
- Code: source code, scripts, notebooks, config files
- Installers: setup files, .exe, .msi, .dmg
- ZIPs: archives, compressed files
- Videos: video files
- Docs: office documents, spreadsheets, presentations, text files
- _review: audio files, or anything truly ambiguous

Filename: {filename}
Rule-based guess: {rule_guess}

Respond with ONLY a JSON object, no markdown, no explanation:
{{"folder": "<folder_name>", "reason": "<one sentence why>"}}"""

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=20,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()
        data = json.loads(raw)
        folder = data.get("folder", rule_guess)
        reason = data.get("reason", "LLM classification")
        if folder not in VALID_FOLDERS:
            folder = rule_guess
        return folder, reason
    except Exception as e:
        log.warning(f"LLM fallback for '{filename}': {e}")
        return rule_guess, "LLM unavailable — rule-based fallback"

# ─────────────────────────────────────────────
# CORE MOVE LOGIC
# ─────────────────────────────────────────────

def safe_destination(dest_dir: Path, filename: str) -> Path:
    """Avoid overwriting existing files — append _2, _3, etc."""
    dest = dest_dir / filename
    if not dest.exists():
        return dest
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 2
    while True:
        candidate = dest_dir / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1

def categorize_file(filepath: Path):
    filename = filepath.name
    ext = filepath.suffix.lower()

    # Skip temp/incomplete files
    if any(filename.endswith(p) or p in filename for p in SKIP_PATTERNS):
        log.debug(f"Skipping temp file: {filename}")
        return

    # Skip system files and the categorizer's own files
    if filename.startswith("_") or filename.startswith("."):
        return

    # Wait briefly for file to finish writing
    time.sleep(1.5)
    if not filepath.exists():
        return

    log.info(f"Processing: {filename}")

    # 1. Check custom learned rules first
    custom = apply_custom_rules(filename)
    if custom:
        folder, method, notes = custom, "rule", f"Custom rule match"
    else:
        # 2. Extension-based rule
        rule_folder = EXTENSION_RULES.get(ext)

        if rule_folder is None:
            # Unknown extension — quarantine
            folder, method, notes = "_review", "fallback", f"Unknown extension: {ext}"
        elif ext in LLM_REFINE_EXTENSIONS:
            # 3. LLM refinement pass for ambiguous types
            folder, notes = classify_with_llm(filename, rule_folder)
            method = "llm"
        else:
            folder, method, notes = rule_folder, "rule", f"Extension rule: {ext}"

    # Ensure destination folder exists
    dest_dir = DOWNLOADS_DIR / folder
    dest_dir.mkdir(exist_ok=True)

    dest_path = safe_destination(dest_dir, filename)

    try:
        shutil.move(str(filepath), str(dest_path))  # type: ignore[arg-type]
        confirmed = 0 if folder == "_review" else 1
        log_move(filename, filepath, dest_path, method, folder, confirmed, notes)

        if folder == "_review":
            log_review(filename, dest_path, notes)
            log.info(f"  → _review/  [{method}] {notes}")
        else:
            log.info(f"  → {folder}/  [{method}] {notes}")

    except Exception as e:
        log.error(f"Failed to move '{filename}': {e}")

# ─────────────────────────────────────────────
# DAILY DIGEST
# ─────────────────────────────────────────────

def generate_daily_digest():
    """Print a summary of today's moves and pending review items."""
    today = date.today().isoformat()
    conn = sqlite3.connect(str(DB_PATH))

    moves = conn.execute(
        "SELECT folder, COUNT(*) FROM moves WHERE ts LIKE ? AND confirmed=1 GROUP BY folder ORDER BY COUNT(*) DESC",
        (f"{today}%",)
    ).fetchall()

    review = conn.execute(
        "SELECT filename, reason FROM review_items WHERE ts LIKE ? AND resolved=0",
        (f"{today}%",)
    ).fetchall()

    conn.close()

    print("\n" + "═"*55)
    print(f"  📁 Downloads Digest — {today}")
    print("═"*55)

    if moves:
        print("\n  Auto-moved today:")
        for folder, count in moves:
            print(f"    {folder:<15} {count} file{'s' if count != 1 else ''}")
    else:
        print("\n  No files moved today.")

    if review:
        print(f"\n  ⚠  {len(review)} file(s) waiting in _review/:")
        for filename, reason in review:
            print(f"    • {filename}")
            print(f"      {reason}")
        print(f"\n  Check: {DOWNLOADS_DIR / '_review'}")
    else:
        print("\n  ✓ No files in review queue.")

    print("═"*55 + "\n")

# ─────────────────────────────────────────────
# FILE WATCHER
# ─────────────────────────────────────────────

class DownloadHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory:
            categorize_file(Path(event.src_path))

    def on_moved(self, event):
        # Catches browser completing a .crdownload → final file rename
        if not event.is_directory:
            categorize_file(Path(event.dest_path))

# ─────────────────────────────────────────────
# ENTRYPOINTS
# ─────────────────────────────────────────────

def run_watcher():
    init_db()
    log.info("Downloads Auto-Categorizer starting up...")
    log.info(f"Watching: {DOWNLOADS_DIR}")
    log.info(f"Model: {OLLAMA_MODEL} (LLM fallback for ambiguous files)")

    # Create all destination folders upfront
    for folder in FOLDERS:
        (DOWNLOADS_DIR / folder).mkdir(exist_ok=True)

    observer = Observer()
    observer.schedule(DownloadHandler(), str(DOWNLOADS_DIR), recursive=False)
    observer.start()
    log.info("Watcher running. Press Ctrl+C to stop.\n")

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        log.info("Stopping watcher...")
        observer.stop()
        generate_daily_digest()

    observer.join()

def run_digest():
    init_db()
    generate_daily_digest()

def teach_rule(keyword: str, folder: str):
    """CLI: teach the categorizer a new rule."""
    if folder not in VALID_FOLDERS:
        print(f"Invalid folder. Choose from: {', '.join(VALID_FOLDERS)}")
        sys.exit(1)
    save_custom_rule(keyword, folder)
    print(f"✓ Rule saved: any file containing '{keyword}' → {folder}/")

if __name__ == "__main__":
    if len(sys.argv) == 1:
        run_watcher()
    elif sys.argv[1] == "digest":
        run_digest()
    elif sys.argv[1] == "teach" and len(sys.argv) == 4:
        teach_rule(sys.argv[2], sys.argv[3])
    else:
        print("Usage:")
        print("  python downloads_watcher.py              # start watcher")
        print("  python downloads_watcher.py digest       # show today's digest")
        print("  python downloads_watcher.py teach <keyword> <folder>  # add rule")
