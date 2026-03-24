"""
Whisper Transcription Pipeline
Karl's Productivity OS - Project 3

Usage:
    python transcribe.py <file>                        # transcribe + summarize + save to Obsidian
    python transcribe.py <file> --transcript-only      # just transcribe, no summary
    python transcribe.py <file> --no-obsidian          # transcribe + summarize, don't save to Obsidian
    python transcribe.py --watch                       # watch _review/ folder for audio files

Supports: .mp4 .mp3 .wav .m4a .mkv .mov .avi .webm .flac .aac .ogg
"""

import os
import sys
import json
import re
import sqlite3
import requests
import argparse
import time
import shutil
from pathlib import Path
from datetime import datetime, timezone
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# ─────────────────────────────────────────────
# SHARED DB — finds db.py at repo root regardless of CWD
# ─────────────────────────────────────────────
def _find_repo_root():
    candidate = Path(__file__).resolve().parent
    for _ in range(4):
        if (candidate / "db.py").exists():
            return candidate
        candidate = candidate.parent
    return None

_repo_root = _find_repo_root()
if _repo_root and str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

try:
    from db import log_artifact, log_session, log_task, log_metric
    SHARED_DB_AVAILABLE = True
    print(f"[db] Loaded from: {_repo_root}")
except ImportError:
    SHARED_DB_AVAILABLE = False
    print("[db] db.py not found — shared DB writes disabled")

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

OBSIDIAN_VAULT      = Path(r"C:\Users\Karl\Documents\Obsidian Vault")
OBSIDIAN_FOLDER     = OBSIDIAN_VAULT / "Transcripts"   # subfolder inside vault
DOWNLOADS_REVIEW    = Path(r"C:\Users\Karl\Downloads\_review")
OUTPUT_DIR          = Path(r"C:\Users\Karl\Documents\transcripts")  # local backup
DB_PATH             = Path(r"C:\Users\Karl\Documents\transcripts\transcripts.db")

OLLAMA_URL          = "http://localhost:11434/api/generate"
OLLAMA_MODEL        = "llama3:8b"
WHISPER_MODEL       = "medium"   # tiny | base | small | medium | large
                                  # medium = best quality/speed balance (~1.5GB)

SUPPORTED_EXTENSIONS = {
    ".mp4", ".mp3", ".wav", ".m4a", ".mkv",
    ".mov", ".avi", ".webm", ".flac", ".aac", ".ogg"
}

# ─────────────────────────────────────────────
# SETUP
# ─────────────────────────────────────────────

def setup():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OBSIDIAN_FOLDER.mkdir(parents=True, exist_ok=True)
    init_db()

def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS transcripts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ts              TEXT NOT NULL,
            filename        TEXT NOT NULL,
            source_path     TEXT NOT NULL,
            transcript_path TEXT,
            obsidian_path   TEXT,
            duration_secs   REAL,
            word_count      INTEGER,
            model           TEXT,
            summary         TEXT,
            action_items    TEXT,
            tags            TEXT
        )
    """)
    conn.commit()
    conn.close()

def log_transcript(filename, source_path, transcript_path, obsidian_path,
                   duration_secs, word_count, model, summary, action_items, tags):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        """INSERT INTO transcripts
           (ts, filename, source_path, transcript_path, obsidian_path,
            duration_secs, word_count, model, summary, action_items, tags)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            datetime.now().isoformat(), filename, str(source_path),
            str(transcript_path), str(obsidian_path),
            duration_secs, word_count, model,
            summary, json.dumps(action_items), json.dumps(tags)
        )
    )
    conn.commit()
    conn.close()

# ─────────────────────────────────────────────
# TRANSCRIPTION
# ─────────────────────────────────────────────

def transcribe(filepath: Path, model_name: str = WHISPER_MODEL) -> dict:
    """
    Run Whisper on a file. Returns dict with text, segments, language, duration.
    """
    try:
        import whisper
    except ImportError:
        print("\n[ERROR] openai-whisper not installed.")
        print("Run: pip install openai-whisper")
        sys.exit(1)

    print(f"\n[1/3] Transcribing: {filepath.name}")
    print(f"      Model: {model_name}  |  This may take a few minutes...")

    model = whisper.load_model(model_name)
    result = model.transcribe(str(filepath), verbose=False)

    duration = 0.0
    if result.get("segments"):
        duration = result["segments"][-1].get("end", 0.0)

    print(f"      Done. Duration: {duration/60:.1f} min | Language: {result.get('language', 'unknown')}")
    return {
        "text": result["text"].strip(),
        "language": result.get("language", "unknown"),
        "duration_secs": duration,
        "segments": result.get("segments", [])
    }

def format_transcript_with_timestamps(segments: list) -> str:
    """Format segments into a readable timestamped transcript."""
    lines = []
    for seg in segments:
        start = seg.get("start", 0)
        mins = int(start // 60)
        secs = int(start % 60)
        text = seg.get("text", "").strip()
        lines.append(f"[{mins:02d}:{secs:02d}] {text}")
    return "\n".join(lines)

# ─────────────────────────────────────────────
# SUMMARIZATION
# ─────────────────────────────────────────────

def summarize(transcript_text: str, filename: str) -> dict:
    """
    Send transcript to Ollama for structured analysis.
    Returns dict with summary, action_items, key_points, people, decisions, tags.
    """
    print(f"\n[2/3] Summarizing with {OLLAMA_MODEL}...")

    # Truncate very long transcripts to fit context window
    max_chars = 12000
    text = transcript_text[:max_chars]
    if len(transcript_text) > max_chars:
        text += "\n\n[Transcript truncated for summarization]"

    prompt = f"""Analyze this transcript and return a single-line JSON object with no newlines inside string values.

Recording: "{filename}"

Transcript:
{text}

Rules: respond with ONLY raw JSON, no markdown, no code fences, no text before or after.
Use this exact structure on a single line:
{{"summary":"short summary here","key_points":["point1","point2"],"action_items":["Do something","Follow up on X"],"decisions":["decision1"],"people":["name1"],"topics":["topic1","topic2"],"tags":["tag1","tag2"],"type":"interview"}}

type must be one of: meeting, voice_memo, podcast, lecture, interview, other
Use empty arrays [] for fields with no content.
Action items must start with a verb."""

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=120,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()

        # Strip markdown code fences if present
        raw = re.sub(r"```json\s*", "", raw)
        raw = re.sub(r"```\s*", "", raw)

        # Extract JSON object if there's surrounding text
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            raw = match.group(0)

        data = json.loads(raw)
        print(f"      Done. Type: {data.get('type', 'unknown')} | Action items: {len(data.get('action_items', []))}")
        return data

    except json.JSONDecodeError as e:
        print(f"      [WARN] Could not parse LLM response as JSON: {e}")
        return {
            "summary": "Summary unavailable - LLM response could not be parsed.",
            "key_points": [], "action_items": [], "decisions": [],
            "people": [], "topics": [], "tags": [], "type": "other"
        }
    except Exception as e:
        print(f"      [WARN] Ollama unavailable: {e}")
        return {
            "summary": "Summary unavailable - Ollama not running.",
            "key_points": [], "action_items": [], "decisions": [],
            "people": [], "topics": [], "tags": [], "type": "other"
        }

# ─────────────────────────────────────────────
# OBSIDIAN NOTE
# ─────────────────────────────────────────────

def build_obsidian_note(filepath: Path, transcript: dict, analysis: dict) -> str:
    """Build a formatted Obsidian markdown note."""
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    duration_min = transcript["duration_secs"] / 60
    word_count = len(transcript["text"].split())

    tags = analysis.get("tags", [])
    rec_type = analysis.get("type", "other")
    if rec_type not in tags:
        tags.insert(0, rec_type)

    tag_str = "\n".join([f"  - {t}" for t in tags]) if tags else "  - transcript"

    key_points = analysis.get("key_points", [])
    action_items = analysis.get("action_items", [])
    decisions = analysis.get("decisions", [])
    people = analysis.get("people", [])
    topics = analysis.get("topics", [])

    timestamped = format_transcript_with_timestamps(transcript.get("segments", []))
    if not timestamped:
        timestamped = transcript["text"]

    note = f"""---
title: "{filepath.stem}"
date: {date_str}
time: {time_str}
type: {rec_type}
source: "{filepath.name}"
duration: {duration_min:.1f} min
words: {word_count}
language: {transcript.get("language", "en")}
whisper_model: {WHISPER_MODEL}
tags:
{tag_str}
---

# {filepath.stem}

> **Date:** {date_str} {time_str}  |  **Duration:** {duration_min:.1f} min  |  **Words:** {word_count}

---

## Summary

{analysis.get("summary", "No summary available.")}

"""

    if key_points:
        note += "## Key Points\n\n"
        for point in key_points:
            note += f"- {point}\n"
        note += "\n"

    if action_items:
        note += "## Action Items\n\n"
        for item in action_items:
            note += f"- [ ] {item}\n"
        note += "\n"

    if decisions:
        note += "## Decisions\n\n"
        for d in decisions:
            note += f"- {d}\n"
        note += "\n"

    if people:
        note += f"## People Mentioned\n\n{', '.join(people)}\n\n"

    if topics:
        note += f"## Topics\n\n{', '.join(topics)}\n\n"

    note += f"""---

## Full Transcript

{timestamped}
"""
    return note

def save_obsidian_note(filepath: Path, content: str) -> Path:
    """Save note to Obsidian vault, return the path."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    safe_stem = re.sub(r'[<>:"/\\|?*]', "-", filepath.stem)
    note_filename = f"{date_str} {safe_stem}.md"
    note_path = OBSIDIAN_FOLDER / note_filename
    note_path.write_text(content, encoding="utf-8")
    print(f"      Saved: {note_path}")
    return note_path

# ─────────────────────────────────────────────
# SHARED DB INTEGRATION
# ─────────────────────────────────────────────

def write_to_shared_db(filepath, transcript, analysis, obsidian_path, transcript_path):
    """
    Write transcription results to the shared productivity_os.db.
    Called at the end of process_file() after everything is saved.
    Writes:
      - 1 artifact  (the transcript note)
      - 1 session   (the listening/recording session)
      - N tasks     (one per action item Ollama extracted)
      - 1 metric    (transcript_minutes for today)
    """
    if not SHARED_DB_AVAILABLE:
        return

    duration_secs = transcript.get("duration_secs", 0)
    word_count    = len(transcript["text"].split())
    tags          = analysis.get("tags", [])
    rec_type      = analysis.get("type", "other")
    action_items  = analysis.get("action_items", [])
    people        = analysis.get("people", [])
    topics        = analysis.get("topics", [])

    # Combine tags — include rec_type and people as person-kind tags
    all_tags = list(set([rec_type] + tags + [t.lower().replace(" ", "-") for t in topics[:5]]))

    # ── 1. Artifact ───────────────────────────────────────────────────────
    artifact_id = log_artifact(
        artifact_type="transcript",
        source_tool="whisper",
        path_or_url=str(obsidian_path) if str(obsidian_path) != "(skipped)" else str(transcript_path),
        title=filepath.stem,
        summary=analysis.get("summary", ""),
        obsidian_path=str(obsidian_path) if str(obsidian_path) != "(skipped)" else None,
        word_count=word_count,
        duration_secs=duration_secs,
        language=transcript.get("language", "en"),
        source_file=str(filepath),
        tags=all_tags,
        extra={
            "whisper_model":  WHISPER_MODEL,
            "rec_type":       rec_type,
            "people":         people,
            "decisions":      analysis.get("decisions", []),
            "key_points":     analysis.get("key_points", []),
            "action_items":   action_items,
        }
    )

    # ── 2. Session ────────────────────────────────────────────────────────
    # Approximate: session ended now, started duration_secs ago
    from datetime import timedelta
    end_ts   = datetime.now(timezone.utc)
    start_ts = end_ts - timedelta(seconds=max(duration_secs, 1))

    log_session(
        kind="listening",
        source_tool="whisper",
        start_ts=start_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end_ts=end_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        summary=f"{rec_type.title()}: {filepath.stem} ({duration_secs/60:.1f} min, {word_count} words)",
        artifact_id=artifact_id,
        extra={"source_file": str(filepath), "rec_type": rec_type, "people": people}
    )

    # ── 3. Tasks (one per action item) ────────────────────────────────────
    task_count = 0
    for item in action_items:
        task_id = log_task(
            title=item,
            source_tool="whisper",
            status="unconfirmed",
            source_artifact=artifact_id,
            source_note_path=str(obsidian_path) if str(obsidian_path) != "(skipped)" else None,
            notes=f"Extracted from: {filepath.name}",
        )
        if task_id:
            task_count += 1

    # ── 4. Metric ─────────────────────────────────────────────────────────
    log_metric(
        metric_name="transcript_minutes",
        value=round(duration_secs / 60, 2),
        source_tool="whisper",
        notes=f"{filepath.name} ({rec_type})",
    )

    print(f"  [db] artifact {artifact_id[:8]}... | {task_count} tasks | {duration_secs/60:.1f} min logged")


# ─────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────

def process_file(filepath: Path, transcript_only: bool = False, no_obsidian: bool = False):
    filepath = Path(filepath).resolve()

    if not filepath.exists():
        print(f"[ERROR] File not found: {filepath}")
        return

    if filepath.suffix.lower() not in SUPPORTED_EXTENSIONS:
        print(f"[ERROR] Unsupported file type: {filepath.suffix}")
        print(f"        Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
        return

    setup()
    print(f"\n{'='*60}")
    print(f"  Productivity OS - Whisper Pipeline")
    print(f"  File: {filepath.name}")
    print(f"{'='*60}")

    # Step 1: Transcribe
    transcript = transcribe(filepath)

    # Save raw transcript to local backup
    date_str = datetime.now().strftime("%Y-%m-%d")
    safe_stem = re.sub(r'[<>:"/\\|?*]', "-", filepath.stem)
    transcript_path = OUTPUT_DIR / f"{date_str}_{safe_stem}_transcript.md"
    transcript_path.write_text(
        f"# Transcript: {filepath.name}\n\nDate: {date_str}\nDuration: {transcript['duration_secs']/60:.1f} min\n\n---\n\n"
        + format_transcript_with_timestamps(transcript.get("segments", []))
        + "\n\n---\n\n## Raw Text\n\n" + transcript["text"],
        encoding="utf-8"
    )

    if transcript_only:
        print(f"\n[DONE] Transcript saved: {transcript_path}")
        print(f"       Words: {len(transcript['text'].split())}")
        return

    # Step 2: Summarize
    analysis = summarize(transcript["text"], filepath.name)

    # Step 3: Save to Obsidian
    obsidian_path = Path("(skipped)")
    if not no_obsidian:
        print(f"\n[3/3] Saving to Obsidian...")
        note_content = build_obsidian_note(filepath, transcript, analysis)
        obsidian_path = save_obsidian_note(filepath, note_content)
    else:
        print(f"\n[3/3] Skipping Obsidian (--no-obsidian flag)")

    # Log to SQLite (existing private DB)
    log_transcript(
        filename=filepath.name,
        source_path=filepath,
        transcript_path=transcript_path,
        obsidian_path=obsidian_path,
        duration_secs=transcript["duration_secs"],
        word_count=len(transcript["text"].split()),
        model=WHISPER_MODEL,
        summary=analysis.get("summary", ""),
        action_items=analysis.get("action_items", []),
        tags=analysis.get("tags", [])
    )

    # Write to shared productivity_os.db
    write_to_shared_db(filepath, transcript, analysis, obsidian_path, transcript_path)

    # Print summary
    print(f"\n{'='*60}")
    print(f"  DONE")
    print(f"{'='*60}")
    print(f"  Duration:     {transcript['duration_secs']/60:.1f} min")
    print(f"  Words:        {len(transcript['text'].split())}")
    print(f"  Language:     {transcript.get('language', 'unknown')}")
    print(f"  Transcript:   {transcript_path.name}")
    if not no_obsidian:
        print(f"  Obsidian:     Transcripts/{obsidian_path.name}")

    action_items = analysis.get("action_items", [])
    if action_items:
        print(f"\n  Action Items:")
        for item in action_items:
            print(f"    [ ] {item}")

    print(f"{'='*60}\n")

# ─────────────────────────────────────────────
# WATCH MODE (monitors _review/ for audio files)
# ─────────────────────────────────────────────

class AudioHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            time.sleep(2)  # wait for file to finish copying
            print(f"\n[WATCH] Detected audio file: {path.name}")
            process_file(path)

def run_watch_mode():
    setup()
    if not DOWNLOADS_REVIEW.exists():
        DOWNLOADS_REVIEW.mkdir(parents=True, exist_ok=True)

    print(f"\nWhisper Watch Mode")
    print(f"Monitoring: {DOWNLOADS_REVIEW}")
    print(f"Drop any audio/video file in _review/ to auto-transcribe.")
    print(f"Press Ctrl+C to stop.\n")

    observer = Observer()
    observer.schedule(AudioHandler(), str(DOWNLOADS_REVIEW), recursive=False)
    observer.start()
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Whisper transcription + Ollama summarization pipeline"
    )
    parser.add_argument("file", nargs="?", help="Audio/video file to transcribe")
    parser.add_argument("--transcript-only", action="store_true", help="Skip summarization")
    parser.add_argument("--no-obsidian", action="store_true", help="Skip saving to Obsidian")
    parser.add_argument("--watch", action="store_true", help="Watch _review/ folder for audio files")
    parser.add_argument("--model", default=WHISPER_MODEL,
                        help=f"Whisper model to use (default: {WHISPER_MODEL})")

    args = parser.parse_args()

    if args.watch:
        run_watch_mode()
    elif args.file:
        WHISPER_MODEL = args.model
        process_file(
            Path(args.file),
            transcript_only=args.transcript_only,
            no_obsidian=args.no_obsidian
        )
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python transcribe.py meeting.mp4")
        print("  python transcribe.py podcast.mp3 --no-obsidian")
        print("  python transcribe.py interview.m4a --transcript-only")
        print("  python transcribe.py meeting.mp4 --model large")
        print("  python transcribe.py --watch")
