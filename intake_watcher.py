"""
Intake Folder Watcher — Productivity OS Project 38
Karl's Productivity OS

Drop anything into the intake/ folder. It gets routed automatically:

  .mp3 / .wav / .m4a / .mp4 / .mkv / .webm  →  Whisper transcription (transcribe.py)
  .pdf                                         →  PDF to Markdown (pdf_to_md.py)
  .url / .txt (containing a URL on line 1)     →  Web digest analysis (web_digest.py)
  .md / .markdown                              →  Copy directly to vault/Intake/

After each successful file, the vault is re-indexed automatically (--index).
  Processed files  →  intake/done/
  Failed files     →  intake/failed/

Usage:
    python intake_watcher.py              # watch forever
    python intake_watcher.py --dry-run    # log routing only, don't process
    python intake_watcher.py --no-index   # process but skip re-indexing

Add to config.yaml:
    intake:
      folder: "C:/Users/Karl/Documents/productivity-os/intake"  # default
      auto_index: true
      web_digest_comments: 400
      web_digest_free: true    # true = --free mode (Claude Code), false = paid API
"""

import os
import sys
import re
import shutil
import subprocess
import logging
import argparse
import time
from pathlib import Path
from datetime import datetime

try:
    import yaml
except ImportError:
    print("[ERROR] pyyaml not installed. Run: pip install pyyaml")
    sys.exit(1)

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    print("[ERROR] watchdog not installed. Run: pip install watchdog")
    sys.exit(1)

# ─────────────────────────────────────────────
# PATHS + CONFIG
# ─────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent
CONFIG_PATH  = PROJECT_ROOT / "config.yaml"

AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.m4b', '.ogg', '.flac'}
VIDEO_EXTENSIONS  = {'.mp4', '.mkv', '.webm', '.avi', '.mov', '.m4v'}
ALL_MEDIA         = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS
PDF_EXTENSIONS    = {'.pdf'}
MD_EXTENSIONS     = {'.md', '.markdown'}
URL_EXTENSIONS    = {'.url'}
TXT_EXTENSIONS    = {'.txt'}

URL_REGEX = re.compile(r'https?://[^\s]+', re.IGNORECASE)


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"[ERROR] config.yaml not found at {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)


def get_intake_cfg() -> dict:
    return load_config().get('intake', {})


def get_intake_folder() -> Path:
    cfg = get_intake_cfg()
    default = PROJECT_ROOT / "intake"
    folder = Path(cfg.get('folder', default))
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "done").mkdir(exist_ok=True)
    (folder / "failed").mkdir(exist_ok=True)
    return folder


def get_vault_path() -> Path:
    cfg = load_config()
    sb = cfg.get('second_brain', cfg)
    vaults = sb.get('vaults', [])
    if vaults:
        return Path(vaults[0])
    raise RuntimeError("No vault path in config.yaml → second_brain.vaults")


def find_script(relative: str) -> Path | None:
    """
    Try config-relative path first, then glob the whole project for it.
    Returns None if not found — callers handle the fallback.
    """
    direct = PROJECT_ROOT / relative
    if direct.exists():
        return direct
    name = Path(relative).name
    for candidate in PROJECT_ROOT.glob(f"**/{name}"):
        # Don't pick up files inside intake/ or .git/
        if 'intake' not in candidate.parts and '.git' not in candidate.parts:
            return candidate
    return None


# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

def setup_logging():
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"intake_{datetime.now().strftime('%Y%m')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s  %(levelname)-8s  %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(sys.stdout),
        ]
    )


log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# URL EXTRACTION
# ─────────────────────────────────────────────

def extract_url(path: Path) -> str | None:
    """
    Pull a URL out of:
      .url files  — Windows Internet Shortcut (URL=https://...)
      .txt files  — first URL found within the first 5 lines
    Returns URL string or None.
    """
    try:
        content = path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return None

    if path.suffix.lower() == '.url':
        for line in content.splitlines():
            if line.strip().upper().startswith('URL='):
                return line.strip()[4:].strip()
        m = URL_REGEX.search(content)
        return m.group(0) if m else None

    if path.suffix.lower() == '.txt':
        for line in content.splitlines()[:5]:
            line = line.strip()
            if URL_REGEX.match(line):
                return line

    return None


# ─────────────────────────────────────────────
# ROUTING
# ─────────────────────────────────────────────

def detect_route(path: Path) -> tuple[str, str | None]:
    """
    Returns (route, url_or_none).
    route is one of: 'audio' | 'pdf' | 'markdown' | 'web_digest' | 'unknown'
    """
    ext = path.suffix.lower()

    if ext in ALL_MEDIA:
        return 'audio', None
    if ext in PDF_EXTENSIONS:
        return 'pdf', None
    if ext in MD_EXTENSIONS:
        return 'markdown', None
    if ext in URL_EXTENSIONS or ext in TXT_EXTENSIONS:
        url = extract_url(path)
        if url:
            return 'web_digest', url

    return 'unknown', None


# ─────────────────────────────────────────────
# HANDLERS — one per route
# ─────────────────────────────────────────────

def handle_audio(path: Path, dry_run: bool) -> bool:
    script = find_script("03_transcribe/transcribe.py")
    if not script:
        log.error("  transcribe.py not found anywhere in project.")
        return False

    cmd = [sys.executable, str(script), str(path), "--summarizer", "claude"]
    log.info(f"  → AUDIO/VIDEO  {path.name}")
    log.info(f"    {' '.join(str(c) for c in cmd)}")
    if dry_run:
        return True

    result = subprocess.run(cmd)
    if result.returncode != 0:
        log.error(f"  transcribe.py exited {result.returncode}")
        return False
    return True


def handle_pdf(path: Path, dry_run: bool) -> bool:
    script = find_script("pdf_to_md.py")

    if not script:
        # Graceful fallback: drop the PDF into vault/Research/ as-is
        # It won't be indexed as text but at least it's not lost
        try:
            vault = get_vault_path()
            dest_dir = vault / "Research"
            dest_dir.mkdir(exist_ok=True)
            dest = dest_dir / path.name
            log.warning("  pdf_to_md.py not found — copying raw PDF to vault/Research/")
            log.info(f"  → PDF (raw)  {path.name}")
            if not dry_run:
                shutil.copy2(path, dest)
            return True
        except Exception as e:
            log.error(f"  PDF fallback copy failed: {e}")
            return False

    cmd = [sys.executable, str(script), str(path)]
    log.info(f"  → PDF  {path.name}")
    log.info(f"    {' '.join(str(c) for c in cmd)}")
    if dry_run:
        return True

    result = subprocess.run(cmd)
    return result.returncode == 0


def handle_markdown(path: Path, dry_run: bool) -> bool:
    try:
        vault = get_vault_path()
        dest_dir = vault / "Intake"
        dest_dir.mkdir(exist_ok=True)
        dest = dest_dir / path.name
        log.info(f"  → MARKDOWN  {path.name}  →  vault/Intake/")
        if not dry_run:
            shutil.copy2(path, dest)
        return True
    except Exception as e:
        log.error(f"  Markdown copy failed: {e}")
        return False


def handle_web_digest(path: Path, url: str, dry_run: bool) -> bool:
    script = find_script("20_web_digest/web_digest.py")
    if not script:
        log.error("  web_digest.py not found anywhere in project.")
        return False

    cfg = get_intake_cfg()
    comments = str(cfg.get('web_digest_comments', 400))
    free_mode = cfg.get('web_digest_free', True)

    cmd = [sys.executable, str(script), url, comments]
    if free_mode:
        cmd.append("--free")

    log.info(f"  → WEB DIGEST  {url}")
    log.info(f"    MODE: {'free (Claude Code)' if free_mode else 'paid API'}")
    log.info(f"    {' '.join(str(c) for c in cmd)}")
    if dry_run:
        return True

    # Run from the script's directory so relative imports inside web_digest work
    result = subprocess.run(cmd, cwd=str(script.parent))
    return result.returncode == 0


# ─────────────────────────────────────────────
# POST-PROCESSING
# ─────────────────────────────────────────────

def archive_file(path: Path, success: bool, intake_folder: Path):
    """Move the source file to done/ or failed/ with collision protection."""
    subfolder = "done" if success else "failed"
    dest_dir = intake_folder / subfolder
    dest = dest_dir / path.name
    if dest.exists():
        ts = datetime.now().strftime('%H%M%S')
        dest = dest_dir / f"{path.stem}_{ts}{path.suffix}"
    try:
        shutil.move(str(path), str(dest))
        log.info(f"  Archived → {subfolder}/{dest.name}")
    except Exception as e:
        log.warning(f"  Could not archive file: {e}")


def trigger_index(dry_run: bool):
    script = find_script("08_second_brain/second_brain.py")
    if not script:
        log.warning("  second_brain.py not found — skipping auto-index")
        return

    log.info("  Running --index...")
    if dry_run:
        log.info("  [dry-run] skipped")
        return

    result = subprocess.run(
        [sys.executable, str(script), "--index"],
        cwd=str(script.parent)
    )
    if result.returncode == 0:
        log.info("  ✓ Index updated")
    else:
        log.warning(f"  --index exited {result.returncode}")


# ─────────────────────────────────────────────
# WATCHDOG EVENT HANDLER
# ─────────────────────────────────────────────

class IntakeHandler(FileSystemEventHandler):
    def __init__(self, intake_folder: Path, dry_run: bool, auto_index: bool):
        self.intake_folder = intake_folder
        self.dry_run       = dry_run
        self.auto_index    = auto_index
        self._processing: set[str] = set()  # debounce
        super().__init__()

    def on_created(self, event):
        if not event.is_directory:
            self._queue(Path(event.src_path))

    def on_moved(self, event):
        # Fires when a file is dragged/moved into the watched folder
        if not event.is_directory:
            self._queue(Path(event.dest_path))

    def _queue(self, path: Path):
        # Ignore the done/ and failed/ subfolders
        if path.parent.name in ('done', 'failed'):
            return
        # Debounce: watchdog fires multiple events per write
        key = str(path)
        if key in self._processing:
            return
        self._processing.add(key)

        # Wait for the file write to finish before reading it
        time.sleep(1.5)

        if path.exists():
            self._dispatch(path)

        self._processing.discard(key)

    def _dispatch(self, path: Path):
        log.info(f"\n{'─' * 54}")
        log.info(f"  FILE: {path.name}")

        route, url = detect_route(path)
        log.info(f"  ROUTE: {route.upper()}" + (f"  ({url})" if url else ""))

        if   route == 'audio':      success = handle_audio(path, self.dry_run)
        elif route == 'pdf':        success = handle_pdf(path, self.dry_run)
        elif route == 'markdown':   success = handle_markdown(path, self.dry_run)
        elif route == 'web_digest': success = handle_web_digest(path, url, self.dry_run)
        else:
            log.warning(f"  No handler for '{path.suffix}' — moving to failed/")
            success = False

        archive_file(path, success, self.intake_folder)
        log.info(f"  {'✓ OK' if success else '✗ FAILED'}: {path.name}")

        if success and self.auto_index:
            trigger_index(self.dry_run)

        log.info(f"{'─' * 54}\n")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Intake Folder Watcher — drop any file in, it routes itself"
    )
    parser.add_argument("--dry-run",  action="store_true",
                        help="Detect and log routing decisions without actually processing")
    parser.add_argument("--no-index", action="store_true",
                        help="Process files but skip the auto --index afterward")
    args = parser.parse_args()

    setup_logging()

    cfg        = get_intake_cfg()
    intake_dir = get_intake_folder()
    auto_index = cfg.get('auto_index', True) and not args.no_index

    log.info("=" * 54)
    log.info("  Intake Watcher  —  Productivity OS")
    log.info("=" * 54)
    log.info(f"  Watching:   {intake_dir}")
    log.info(f"  Auto-index: {'yes' if auto_index else 'no'}")
    log.info(f"  Dry-run:    {'yes' if args.dry_run else 'no'}")
    log.info("")
    log.info("  Drop files here:")
    log.info("    .mp3 .wav .m4a .mp4 .mkv ...  →  transcribe.py")
    log.info("    .pdf                           →  pdf_to_md.py")
    log.info("    .md                            →  vault/Intake/")
    log.info("    .url / .txt (URL on line 1)    →  web_digest.py")
    log.info("")
    log.info("  Ctrl+C to stop")
    log.info("=" * 54 + "\n")

    handler  = IntakeHandler(intake_dir, args.dry_run, auto_index)
    observer = Observer()
    observer.schedule(handler, str(intake_dir), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("\nStopping...")
        observer.stop()
    observer.join()
    log.info("Watcher stopped.")


if __name__ == "__main__":
    main()
