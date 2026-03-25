"""
Whisper Transcription Pipeline
Karl's Productivity OS - Project 3

Usage:
    python transcribe.py <file>                          # transcribe + summarize + save to Obsidian
    python transcribe.py <file> --transcript-only        # just transcribe, no summary
    python transcribe.py <file> --no-obsidian            # transcribe + summarize, don't save to Obsidian
    python transcribe.py <file> --summarizer claude      # use Claude API for summary (default from config)
    python transcribe.py <file> --summarizer local       # use local Ollama for summary
    python transcribe.py --batch <folder>                # process all audio files in a folder
    python transcribe.py --batch <folder> --limit 5      # process first 5 files only
    python transcribe.py --watch                         # watch _review/ folder for audio files

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

try:
    import yaml
except ImportError:
    print("[ERROR] pyyaml not installed. Run: pip install pyyaml")
    sys.exit(1)

_config_path = (_repo_root / "config.yaml") if _repo_root else None

def _load_config() -> dict:
    if _config_path and _config_path.exists():
        with open(_config_path, 'r') as f:
            return yaml.safe_load(f)
    return {}

_cfg = _load_config()

if _cfg:
    OBSIDIAN_VAULT      = Path(_cfg['paths']['obsidian_vault'])
    DOWNLOADS_REVIEW    = Path(_cfg['paths']['downloads_dir']) / "_review"
    OUTPUT_DIR          = Path(_cfg['paths']['output_dir'])
    OLLAMA_MODEL        = _cfg.get('models', {}).get('transcription', 'deepseek-r1:14b')
    WHISPER_MODEL       = _cfg.get('whisper', {}).get('model', 'medium')
    SUMMARIZER          = _cfg.get('summarizer', 'claude')
    ANTHROPIC_API_KEY   = _cfg.get('anthropic', {}).get('api_key', '') or os.environ.get('ANTHROPIC_API_KEY', '')
    CLAUDE_MODEL        = _cfg.get('anthropic', {}).get('model', 'claude-sonnet-4-5')
else:
    print("[config] config.yaml not found — run setup.py to configure paths")
    OBSIDIAN_VAULT      = Path(r"C:\Users\Karl\Documents\Obsidian Vault")
    DOWNLOADS_REVIEW    = Path(r"C:\Users\Karl\Downloads\_review")
    OUTPUT_DIR          = Path(r"C:\Users\Karl\Documents\transcripts")
    OLLAMA_MODEL        = "deepseek-r1:14b"
    WHISPER_MODEL       = "medium"
    SUMMARIZER          = "claude"
    ANTHROPIC_API_KEY   = os.environ.get('ANTHROPIC_API_KEY', '')
    CLAUDE_MODEL        = "claude-sonnet-4-5"

OBSIDIAN_FOLDER     = OBSIDIAN_VAULT / "Transcripts"
DB_PATH             = OUTPUT_DIR / "transcripts.db"
OLLAMA_URL          = "http://localhost:11434/api/generate"
ANTHROPIC_URL       = "https://api.anthropic.com/v1/messages"

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

def detect_content_type(filename: str, transcript_text: str) -> str:
    name_lower = filename.lower()
    text_lower = transcript_text[:600].lower()

    if any(k in name_lower for k in ['lecture', 'lec', 'lesson', 'class', 'course',
                                      'cs1', 'cs2', 'cs3', 'ee', 'math', 'phys']):
        return 'lecture'
    if any(k in name_lower for k in ['meeting', 'standup', 'sync', 'call', 'interview']):
        return 'meeting'
    if any(k in name_lower for k in ['podcast', 'episode']):
        return 'podcast'
    if any(k in text_lower for k in ["welcome to", "today we're going to", "in today's lecture",
                                      "today i want to", "so today we'll", "let's start with",
                                      "this is lecture", "i'm your instructor", "welcome back"]):
        return 'lecture'
    return 'other'


def _build_prompt(transcript_text: str, filename: str, content_type: str) -> str:
    max_chars = 40000 if content_type == 'lecture' else 12000
    text = transcript_text[:max_chars]
    if len(transcript_text) > max_chars:
        text += "\n\n[Transcript continues — summarize based on what's here]"

    if content_type == 'lecture':
        return f"""You are analyzing a university or technical lecture transcript. Produce a dense, detailed study guide — not a shallow summary. Be specific and thorough.

Recording: "{filename}"

Transcript:
{text}

Respond with ONLY raw JSON on a single line, no markdown, no code fences, no text before or after.

{{"summary":"A rich 4-6 sentence analytical paragraph capturing the lecture thesis, arc, key arguments, and conclusions. Write this as something a student could read instead of attending — specific, not generic.","key_concepts":["ConceptName: one sentence explanation of what it is and why it matters"],"key_points":["Specific factual or conceptual point made — detailed enough for revision"],"definitions":["Term: its definition as given in the lecture"],"examples":["Concrete example, analogy, or case study the instructor used"],"action_items":["Any assignments, readings, or follow-up tasks mentioned"],"people":["Names of researchers, theorists, or figures mentioned"],"topics":["High-level subject tags e.g. machine learning, neural networks"],"tags":["obsidian-friendly tags"],"type":"lecture"}}

Use empty arrays [] for fields with no content. Aim for 6-10 key_concepts and 8-12 key_points."""

    elif content_type == 'meeting':
        return f"""Analyze this meeting transcript. Extract decisions, actions, and context.

Recording: "{filename}"

Transcript:
{text}

Respond with ONLY raw JSON on a single line, no markdown, no code fences:
{{"summary":"3-4 sentence summary of what was discussed and decided","key_points":["..."],"action_items":["Verb-first action item"],"decisions":["decision made"],"people":["name"],"topics":["topic"],"tags":["tag"],"type":"meeting"}}"""

    else:
        return f"""Analyze this transcript and return a single-line JSON object with no newlines inside string values.

Recording: "{filename}"

Transcript:
{text}

Rules: respond with ONLY raw JSON, no markdown, no code fences, no text before or after.
{{"summary":"summary here","key_points":["point1","point2"],"action_items":["Do something"],"decisions":["decision1"],"people":["name1"],"topics":["topic1"],"tags":["tag1"],"type":"{content_type}"}}

Use empty arrays [] for fields with no content. Action items must start with a verb."""


def _parse_llm_response(raw: str, content_type: str) -> dict:
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        raw = match.group(0)
    return json.loads(raw)


def _empty_analysis(content_type: str, reason: str) -> dict:
    return {
        "summary": f"Summary unavailable — {reason}.",
        "key_concepts": [], "key_points": [], "action_items": [], "decisions": [],
        "definitions": [], "examples": [], "people": [], "topics": [], "tags": [],
        "type": content_type
    }


def summarize_with_claude(transcript_text: str, filename: str, content_type: str) -> dict:
    if not ANTHROPIC_API_KEY:
        print("      [WARN] No Anthropic API key found — falling back to local")
        return summarize_with_ollama(transcript_text, filename, content_type)

    prompt = _build_prompt(transcript_text, filename, content_type)

    try:
        resp = requests.post(
            ANTHROPIC_URL,
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=120,
        )
        resp.raise_for_status()
        raw = resp.json()["content"][0]["text"].strip()
        data = _parse_llm_response(raw, content_type)
        n_concepts = len(data.get('key_concepts', data.get('key_points', [])))
        print(f"      Done. Type: {data.get('type','unknown')} | Concepts/points: {n_concepts} | Action items: {len(data.get('action_items', []))}")
        return data

    except json.JSONDecodeError as e:
        print(f"      [WARN] Could not parse Claude response as JSON: {e}")
        return _empty_analysis(content_type, "Claude response could not be parsed")
    except Exception as e:
        print(f"      [WARN] Claude API error: {e}")
        print("      Falling back to local Ollama...")
        return summarize_with_ollama(transcript_text, filename, content_type)


def summarize_with_ollama(transcript_text: str, filename: str, content_type: str) -> dict:
    prompt = _build_prompt(transcript_text, filename, content_type)

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=300,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "").strip()
        data = _parse_llm_response(raw, content_type)
        n_concepts = len(data.get('key_concepts', data.get('key_points', [])))
        print(f"      Done. Type: {data.get('type','unknown')} | Concepts/points: {n_concepts} | Action items: {len(data.get('action_items', []))}")
        return data

    except json.JSONDecodeError as e:
        print(f"      [WARN] Could not parse Ollama response as JSON: {e}")
        return _empty_analysis(content_type, "Ollama response could not be parsed")
    except Exception as e:
        print(f"      [WARN] Ollama unavailable: {e}")
        return _empty_analysis(content_type, "Ollama not running")


def summarize(transcript_text: str, filename: str, summarizer: str = None) -> dict:
    active = summarizer or SUMMARIZER
    content_type = detect_content_type(filename, transcript_text)

    if active == 'claude':
        print(f"\n[2/3] Summarizing with Claude ({CLAUDE_MODEL}) (detected: {content_type})...")
    else:
        print(f"\n[2/3] Summarizing with Ollama ({OLLAMA_MODEL}) (detected: {content_type})...")

    if active == 'claude':
        return summarize_with_claude(transcript_text, filename, content_type)
    else:
        return summarize_with_ollama(transcript_text, filename, content_type)

# ─────────────────────────────────────────────
# OBSIDIAN NOTE
# ─────────────────────────────────────────────

def build_obsidian_note(filepath: Path, transcript: dict, analysis: dict, summarizer: str = None) -> str:
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    duration_min = transcript["duration_secs"] / 60
    word_count = len(transcript["text"].split())
    active_summarizer = summarizer or SUMMARIZER

    tags = analysis.get("tags", [])
    rec_type = analysis.get("type", "other")
    if rec_type not in tags:
        tags.insert(0, rec_type)

    tag_str = "\n".join([f"  - {t}" for t in tags]) if tags else "  - transcript"

    key_concepts  = analysis.get("key_concepts", [])
    key_points    = analysis.get("key_points", [])
    definitions   = analysis.get("definitions", [])
    examples      = analysis.get("examples", [])
    action_items  = analysis.get("action_items", [])
    decisions     = analysis.get("decisions", [])
    people        = analysis.get("people", [])
    topics        = analysis.get("topics", [])

    timestamped = format_transcript_with_timestamps(transcript.get("segments", []))
    if not timestamped:
        timestamped = transcript["text"]

    summarizer_label = CLAUDE_MODEL if active_summarizer == 'claude' else OLLAMA_MODEL

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
summarizer: {summarizer_label}
tags:
{tag_str}
---

# {filepath.stem}

> **Date:** {date_str} {time_str}  |  **Duration:** {duration_min:.1f} min  |  **Words:** {word_count}

---

## Summary

{analysis.get("summary", "No summary available.")}

"""

    if key_concepts:
        note += "## Key Concepts\n\n"
        for concept in key_concepts:
            if ':' in concept:
                name, _, desc = concept.partition(':')
                note += f"- **{name.strip()}**: {desc.strip()}\n"
            else:
                note += f"- {concept}\n"
        note += "\n"

    if key_points:
        note += "## Key Points\n\n"
        for point in key_points:
            note += f"- {point}\n"
        note += "\n"

    if definitions:
        note += "## Definitions\n\n"
        for d in definitions:
            if ':' in d:
                term, _, defn = d.partition(':')
                note += f"- **{term.strip()}**: {defn.strip()}\n"
            else:
                note += f"- {d}\n"
        note += "\n"

    if examples:
        note += "## Examples & Analogies\n\n"
        for ex in examples:
            note += f"- {ex}\n"
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
    if not SHARED_DB_AVAILABLE:
        return

    duration_secs = transcript.get("duration_secs", 0)
    word_count    = len(transcript["text"].split())
    tags          = analysis.get("tags", [])
    rec_type      = analysis.get("type", "other")
    action_items  = analysis.get("action_items", [])
    people        = analysis.get("people", [])
    topics        = analysis.get("topics", [])

    all_tags = list(set([rec_type] + tags + [t.lower().replace(" ", "-") for t in topics[:5]]))

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
            "key_concepts":   analysis.get("key_concepts", []),
            "action_items":   action_items,
        }
    )

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

    log_metric(
        metric_name="transcript_minutes",
        value=round(duration_secs / 60, 2),
        source_tool="whisper",
        notes=f"{filepath.name} ({rec_type})",
    )

    print(f"  [db] artifact {artifact_id[:8]}... | {task_count} tasks | {duration_secs/60:.1f} min logged")


# ─────────────────────────────────────────────
# MAIN PIPELINE — single file
# ─────────────────────────────────────────────

def process_file(filepath: Path, transcript_only: bool = False,
                 no_obsidian: bool = False, summarizer: str = None):
    filepath = Path(filepath).resolve()

    if not filepath.exists():
        print(f"[ERROR] File not found: {filepath}")
        return False

    if filepath.suffix.lower() not in SUPPORTED_EXTENSIONS:
        print(f"[ERROR] Unsupported file type: {filepath.suffix}")
        return False

    setup()
    print(f"\n{'='*60}")
    print(f"  Productivity OS - Whisper Pipeline")
    print(f"  File: {filepath.name}")
    print(f"  Summarizer: {summarizer or SUMMARIZER}")
    print(f"{'='*60}")

    transcript = transcribe(filepath)

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
        return True

    analysis = summarize(transcript["text"], filepath.name, summarizer)

    obsidian_path = Path("(skipped)")
    if not no_obsidian:
        print(f"\n[3/3] Saving to Obsidian...")
        note_content = build_obsidian_note(filepath, transcript, analysis, summarizer)
        obsidian_path = save_obsidian_note(filepath, note_content)
    else:
        print(f"\n[3/3] Skipping Obsidian (--no-obsidian flag)")

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

    write_to_shared_db(filepath, transcript, analysis, obsidian_path, transcript_path)

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

    key_concepts = analysis.get("key_concepts", [])
    if key_concepts:
        print(f"\n  Key Concepts ({len(key_concepts)}):")
        for c in key_concepts[:5]:
            print(f"    • {c[:80]}")

    print(f"{'='*60}\n")
    return True


# ─────────────────────────────────────────────
# BATCH MODE
# ─────────────────────────────────────────────

def run_batch(folder: Path, limit: int = None, transcript_only: bool = False,
              no_obsidian: bool = False, summarizer: str = None):
    """
    Process all audio files in a folder.
    Files are sorted alphabetically — works naturally for numbered lecture series.
    Skips files that already have a matching Obsidian note.
    """
    folder = Path(folder).resolve()
    if not folder.exists():
        print(f"[ERROR] Folder not found: {folder}")
        return

    # Collect all supported audio files, sorted
    all_files = sorted([
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ])

    if not all_files:
        print(f"[ERROR] No supported audio files found in: {folder}")
        print(f"        Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
        return

    # Check which already have Obsidian notes (skip already-processed)
    already_done = set()
    if OBSIDIAN_FOLDER.exists():
        existing_notes = {n.stem for n in OBSIDIAN_FOLDER.glob("*.md")}
        for f in all_files:
            safe_stem = re.sub(r'[<>:"/\\|?*]', "-", f.stem)
            # Match any date-prefixed version of this file
            for note_stem in existing_notes:
                if safe_stem in note_stem:
                    already_done.add(f)
                    break

    pending = [f for f in all_files if f not in already_done]

    if not pending:
        print(f"\n  All {len(all_files)} files already processed. Nothing to do.")
        return

    # Apply limit
    if limit:
        pending = pending[:limit]

    skipped_count = len(all_files) - len([f for f in all_files if f not in already_done])

    print(f"\n{'='*60}")
    print(f"  Batch Transcription")
    print(f"  Folder:     {folder}")
    print(f"  Found:      {len(all_files)} audio files")
    print(f"  Skipping:   {len(already_done)} already processed")
    print(f"  Processing: {len(pending)} files{f' (limit: {limit})' if limit else ''}")
    print(f"  Summarizer: {summarizer or SUMMARIZER}")
    print(f"{'='*60}")

    if already_done:
        print(f"\n  Already done (skipping):")
        for f in sorted(already_done):
            print(f"    ✓ {f.name}")

    setup()

    succeeded = []
    failed = []
    start_time = time.time()

    for i, filepath in enumerate(pending, 1):
        print(f"\n  ── File {i}/{len(pending)} ──────────────────────────────────")
        try:
            ok = process_file(
                filepath,
                transcript_only=transcript_only,
                no_obsidian=no_obsidian,
                summarizer=summarizer,
            )
            if ok:
                succeeded.append(filepath.name)
            else:
                failed.append(filepath.name)
        except Exception as e:
            print(f"  [ERROR] {filepath.name}: {e}")
            failed.append(filepath.name)

    elapsed = time.time() - start_time
    elapsed_str = f"{elapsed/60:.1f} min" if elapsed > 60 else f"{elapsed:.0f}s"

    print(f"\n{'='*60}")
    print(f"  BATCH COMPLETE")
    print(f"{'='*60}")
    print(f"  Processed:  {len(succeeded)}/{len(pending)} files")
    print(f"  Time:       {elapsed_str}")
    if succeeded:
        print(f"\n  ✓ Done:")
        for name in succeeded:
            print(f"    • {name}")
    if failed:
        print(f"\n  ✗ Failed:")
        for name in failed:
            print(f"    • {name}")
    print(f"\n  Notes saved to: Obsidian/Transcripts/")
    print(f"{'='*60}\n")


# ─────────────────────────────────────────────
# WATCH MODE
# ─────────────────────────────────────────────

class AudioHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            time.sleep(2)
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
        description="Whisper transcription + summarization pipeline"
    )
    parser.add_argument("file", nargs="?", help="Single audio/video file to transcribe")
    parser.add_argument("--batch", type=str, metavar="FOLDER",
                        help="Process all audio files in a folder")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max files to process in batch mode (e.g. --limit 5)")
    parser.add_argument("--transcript-only", action="store_true", help="Skip summarization")
    parser.add_argument("--no-obsidian", action="store_true", help="Skip saving to Obsidian")
    parser.add_argument("--watch", action="store_true", help="Watch _review/ folder for audio files")
    parser.add_argument("--model", default=WHISPER_MODEL,
                        help=f"Whisper model to use (default: {WHISPER_MODEL})")
    parser.add_argument("--summarizer", choices=["claude", "local"], default=None,
                        help="'claude' (Anthropic API) or 'local' (Ollama). Defaults to config.")

    args = parser.parse_args()

    if args.watch:
        run_watch_mode()
    elif args.batch:
        WHISPER_MODEL = args.model
        run_batch(
            folder=Path(args.batch),
            limit=args.limit,
            transcript_only=args.transcript_only,
            no_obsidian=args.no_obsidian,
            summarizer=args.summarizer,
        )
    elif args.file:
        WHISPER_MODEL = args.model
        process_file(
            Path(args.file),
            transcript_only=args.transcript_only,
            no_obsidian=args.no_obsidian,
            summarizer=args.summarizer,
        )
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python transcribe.py lecture.mp3                           # single file, Claude summary")
        print("  python transcribe.py lecture.mp3 --summarizer local        # single file, local Ollama")
        print('  python transcribe.py --batch "C:\\yt-dlp\\out"              # whole folder')
        print('  python transcribe.py --batch "C:\\yt-dlp\\out" --limit 5    # first 5 files only')
        print('  python transcribe.py --batch "C:\\yt-dlp\\out" --limit 5 --summarizer claude')
        print("  python transcribe.py meeting.mp4 --no-obsidian")
        print("  python transcribe.py interview.m4a --transcript-only")
        print("  python transcribe.py --watch")
