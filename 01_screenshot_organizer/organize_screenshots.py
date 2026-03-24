"""
Screenshot Organizer using Ollama LLaVA
Karl's Productivity OS - Project 1

Walks your ShareX screenshots folder, sends each image to LLaVA running
locally via Ollama, gets a description + tags, renames the file to something
meaningful, and builds a searchable index.csv.

Requirements:
    pip install requests pillow tqdm

Usage:
    python organize_screenshots.py                   # process new screenshots
    python organize_screenshots.py --reprocess-generic  # re-run on weak descriptions
    python organize_screenshots.py --dry-run         # preview without renaming
    python organize_screenshots.py --model llava:7b  # override model
    python organize_screenshots.py --stats           # show index stats
"""

import os
import re
import csv
import json
import time
import base64
import argparse
import io
from pathlib import Path
from datetime import datetime
from collections import defaultdict, Counter

import requests
from PIL import Image
from tqdm import tqdm


# ─── CONFIG ────────────────────────────────────────────────────────────────────

SCREENSHOTS_DIR  = r"C:\Users\Karl\Documents\ShareX\Screenshots"
INDEX_FILE       = r"C:\Users\Karl\Documents\ShareX\index.csv"
OLLAMA_URL       = "http://localhost:11434/api/generate"

# llava:13b = much better at reading text and identifying specific UI/content
# llava:7b  = faster, use if 13b is too slow on your machine
MODEL            = "llava:13b"

MAX_SLUG_WORDS   = 6
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
MAX_IMAGE_SIZE   = (1280, 720)
REQUEST_DELAY    = 0

# Descriptions that indicate LLaVA gave a generic/useless answer
# These get flagged for --reprocess-generic
GENERIC_PATTERNS = [
    "developer's work session",
    "developer work session",
    "computer screen screenshot",
    "screenshot of a computer",
    "screenshot of a developer",
    "work session with open",
    "workstation screenshot",
    "computer screen with content",
    "screen showing",
    "screenshot of a screen",
]

# ─── PROMPT ────────────────────────────────────────────────────────────────────

PROMPT = """Analyze this screenshot precisely. Look carefully at every visible element.

Respond in this exact JSON format with no extra text:
{
  "description": "specific one-sentence description naming the actual app, site, or content",
  "tags": ["tag1", "tag2", "tag3", "tag4"],
  "slug": "specific-kebab-case-filename"
}

Rules:
- description: name EXACTLY what you see — app names, website names, project names, specific content
  GOOD: "Brave browser showing NFL draft rankings on The Beast website"
  GOOD: "VSCode with Python ImportError in second_brain.py terminal output"
  GOOD: "Obsidian vault open to NTI scouting handoff document"
  GOOD: "Fantasy football waiver wire dashboard with player stats"
  GOOD: "Discord server with code snippet in productivity channel"
  BAD:  "Screenshot of a developer's work session"
  BAD:  "Computer screen with content"
  BAD:  "Screenshot of a computer screen"
- tags: use specific names — app names (obsidian, vscode, brave, discord), 
  site names (reddit, youtube, twitter), project names, content types (error, dashboard, rankings)
  4-6 tags, lowercase, single words or short phrases
- slug: name the specific thing visible, not the generic category
  GOOD: nti-scouting-dashboard, python-import-error, nfl-draft-rankings
  BAD: developer-work-session, computer-screenshot

Only return the JSON object, nothing else."""


# ─── HELPERS ───────────────────────────────────────────────────────────────────

def encode_image(path: Path) -> str:
    with Image.open(path) as img:
        if MAX_IMAGE_SIZE:
            img.thumbnail(MAX_IMAGE_SIZE, Image.LANCZOS)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode("utf-8")


def query_llava(image_path: Path, model: str) -> dict:
    image_b64 = encode_image(image_path)
    payload = {
        "model": model,
        "prompt": PROMPT,
        "images": [image_b64],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1}
    }
    response = requests.post(OLLAMA_URL, json=payload, timeout=180)
    response.raise_for_status()
    raw = response.json().get("response", "{}")
    raw = re.sub(r"```json|```", "", raw).strip()
    return json.loads(raw)


def safe_slug(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    words = text.split("-")[:MAX_SLUG_WORDS]
    return "-".join(words)


def get_date_prefix(path: Path) -> str:
    mtime = os.path.getmtime(path)
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")


def build_new_name(path: Path, slug: str) -> Path:
    date_prefix = get_date_prefix(path)
    clean_slug = safe_slug(slug)
    new_name = f"{date_prefix}_{clean_slug}{path.suffix.lower()}"
    return path.parent / new_name


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def is_generic(description: str) -> bool:
    desc_lower = description.lower()
    return any(pattern in desc_lower for pattern in GENERIC_PATTERNS)


def load_index(index_file: Path) -> list[dict]:
    if not index_file.exists():
        return []
    with open(index_file, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_index(index_file: Path, rows: list[dict]):
    fieldnames = ["original_name", "new_name", "folder", "date", "description", "tags", "path"]
    with open(index_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def load_processed_names(index_file: Path) -> set:
    rows = load_index(index_file)
    return {row.get("original_name", "") for row in rows}


# ─── STATS ─────────────────────────────────────────────────────────────────────

def print_stats(index_file: Path):
    rows = load_index(index_file)
    if not rows:
        print("No index found.")
        return

    generic_count = sum(1 for r in rows if is_generic(r.get("description", "")))
    tag_counts = Counter()
    by_month = defaultdict(int)

    for row in rows:
        date = row.get("date", "")
        month = date[:7] if len(date) >= 7 else "unknown"
        by_month[month] += 1
        for tag in row.get("tags", "").split(","):
            t = tag.strip().lower()
            if t:
                tag_counts[t] += 1

    print(f"\n  Screenshot Index Stats")
    print(f"  {'─'*45}")
    print(f"  Total indexed:     {len(rows)}")
    print(f"  Generic (weak):    {generic_count}  ({generic_count/len(rows)*100:.0f}%) — candidates for --reprocess-generic")
    print(f"  Good descriptions: {len(rows) - generic_count}")
    print(f"\n  By month:")
    for month in sorted(by_month):
        try:
            label = datetime.strptime(month, "%Y-%m").strftime("%B %Y")
        except ValueError:
            label = month
        print(f"    {label:<20} {by_month[month]:>5} screenshots")
    print(f"\n  Top 20 tags:")
    for tag, count in tag_counts.most_common(20):
        print(f"    {tag:<30} {count:>5}x")
    print()


# ─── MAIN PROCESS ──────────────────────────────────────────────────────────────

def run_process(dry_run: bool, model: str):
    """Process new (unindexed) screenshots."""
    screenshots_dir = Path(SCREENSHOTS_DIR)
    index_file = Path(INDEX_FILE)

    if not screenshots_dir.exists():
        print(f"❌ Screenshots folder not found: {screenshots_dir}")
        return

    all_images = [
        p for p in screenshots_dir.rglob("*")
        if p.suffix.lower() in IMAGE_EXTENSIONS and p.is_file()
    ]
    print(f"📁 Found {len(all_images)} images")

    processed = load_processed_names(index_file)
    remaining = [p for p in all_images if p.name not in processed]
    print(f"⏭️  {len(processed)} already processed, {len(remaining)} to go")

    if not remaining:
        print("✅ All images already processed! Try --reprocess-generic to improve weak ones.")
        return

    if dry_run:
        print("🔍 DRY RUN — no files will be renamed\n")

    print(f"🤖 Using model: {model}\n")

    write_header = not index_file.exists()
    csv_file = open(index_file, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(csv_file, fieldnames=[
        "original_name", "new_name", "folder", "date", "description", "tags", "path"
    ])
    if write_header:
        writer.writeheader()

    errors = []
    generic_count = 0

    for img_path in tqdm(remaining, desc="Processing", unit="img"):
        original_name = img_path.name
        try:
            result = query_llava(img_path, model)
            description = result.get("description", "screenshot")
            tags = result.get("tags", [])
            slug = result.get("slug", "screenshot")

            if is_generic(description):
                generic_count += 1

            new_path = build_new_name(img_path, slug)
            new_path = unique_path(new_path)

            if not dry_run:
                img_path.rename(new_path)

            writer.writerow({
                "original_name": original_name,
                "new_name": new_path.name,
                "folder": img_path.parent.name,
                "date": get_date_prefix(new_path if not dry_run else img_path),
                "description": description,
                "tags": ", ".join(tags),
                "path": str(new_path if not dry_run else img_path)
            })
            csv_file.flush()

            if REQUEST_DELAY:
                time.sleep(REQUEST_DELAY)

        except json.JSONDecodeError:
            errors.append((original_name, "LLaVA returned invalid JSON"))
        except requests.RequestException as e:
            errors.append((original_name, f"Ollama request failed: {e}"))
            print(f"\n⚠️  Ollama error on {original_name}, skipping...")
        except Exception as e:
            errors.append((original_name, str(e)))
            print(f"\n⚠️  Error on {original_name}: {e}")

    csv_file.close()

    print(f"\n✅ Done!")
    if generic_count:
        print(f"⚠️  {generic_count} generic descriptions detected — run --reprocess-generic to improve them")
    if errors:
        print(f"\n⚠️  {len(errors)} errors:")
        for name, reason in errors[:10]:
            print(f"   {name}: {reason}")


# ─── REPROCESS GENERIC ─────────────────────────────────────────────────────────

def run_reprocess_generic(dry_run: bool, model: str, limit: int = None):
    """
    Re-run LLaVA on entries with generic/weak descriptions.
    Updates index.csv in place. Does NOT rename files (already renamed).
    """
    index_file = Path(INDEX_FILE)
    rows = load_index(index_file)

    if not rows:
        print("No index found. Run normal processing first.")
        return

    # Find generic entries where the image file still exists at its current path
    to_reprocess = []
    for i, row in enumerate(rows):
        if is_generic(row.get("description", "")):
            img_path = Path(row.get("path", ""))
            if img_path.exists():
                to_reprocess.append((i, row, img_path))

    print(f"\n🔍 Found {len(to_reprocess)} entries with generic descriptions")

    if not to_reprocess:
        print("✅ Nothing to reprocess — all descriptions look specific!")
        return

    if limit:
        to_reprocess = to_reprocess[:limit]
        print(f"   Processing first {limit} (use --limit to adjust)")

    if dry_run:
        print("🔍 DRY RUN — index will not be updated\n")
        for _, row, _ in to_reprocess[:10]:
            print(f"  Would reprocess: {row.get('new_name', '')} — \"{row.get('description', '')}\"")
        return

    print(f"🤖 Using model: {model}")
    print(f"   Re-running LLaVA on {len(to_reprocess)} images...\n")

    improved = 0
    errors = []

    for idx, row, img_path in tqdm(to_reprocess, desc="Reprocessing", unit="img"):
        try:
            result = query_llava(img_path, model)
            new_desc = result.get("description", "").strip()
            new_tags = result.get("tags", [])
            new_slug = result.get("slug", "").strip()

            # Only update if the new description is actually better
            if new_desc and not is_generic(new_desc):
                rows[idx]["description"] = new_desc
                rows[idx]["tags"] = ", ".join(new_tags)
                # Update filename slug if it improved
                if new_slug and new_slug != "screenshot":
                    date = row.get("date", "")
                    new_name = f"{date}_{safe_slug(new_slug)}{Path(img_path).suffix.lower()}"
                    rows[idx]["new_name"] = new_name
                improved += 1
            else:
                # Still generic — note it but keep original
                pass

            if REQUEST_DELAY:
                time.sleep(REQUEST_DELAY)

        except Exception as e:
            errors.append((row.get("new_name", ""), str(e)))

    # Save updated index
    save_index(index_file, rows)

    print(f"\n✅ Reprocessing complete")
    print(f"   Improved: {improved}/{len(to_reprocess)} entries")
    print(f"   Still generic: {len(to_reprocess) - improved - len(errors)}")
    if errors:
        print(f"   Errors: {len(errors)}")
    print(f"\n   Run screenshots_to_md.py to update your Obsidian index notes")



# ─── COMPARE MODELS ────────────────────────────────────────────────────────────

def run_compare(limit: int = 20):
    """
    Run the same N images through both llava:7b and llava:13b and print
    descriptions side by side so you can decide which model to use for the
    full reprocess run.
    Does NOT update index.csv — purely for evaluation.
    """
    index_file = Path(INDEX_FILE)
    rows = load_index(index_file)

    # Pick N generic entries that exist on disk
    candidates = []
    for row in rows:
        if is_generic(row.get("description", "")):
            img_path = Path(row.get("path", ""))
            if img_path.exists():
                candidates.append((row, img_path))
        if len(candidates) >= limit:
            break

    if not candidates:
        print("No generic entries found to compare. Run --stats to check.")
        return

    print(f"\n  Model Comparison — {len(candidates)} images")
    print(f"  {'─'*60}")
    print(f"  Running each image through llava:7b AND llava:13b...")
    print(f"  This will take ~{len(candidates) * 25 // 60 + 1} minutes\n")

    results = []
    for i, (row, img_path) in enumerate(candidates):
        print(f"  [{i+1}/{len(candidates)}] {img_path.name[:50]}")
        original = row.get("description", "")

        try:
            r7b = query_llava(img_path, "llava:7b")
            desc_7b = r7b.get("description", "error")
        except Exception as e:
            desc_7b = f"ERROR: {e}"

        try:
            r13b = query_llava(img_path, "llava:13b")
            desc_13b = r13b.get("description", "error")
        except Exception as e:
            desc_13b = f"ERROR: {e}"

        results.append({
            "file": img_path.name,
            "original": original,
            "7b": desc_7b,
            "13b": desc_13b,
            "7b_generic": is_generic(desc_7b),
            "13b_generic": is_generic(desc_13b),
        })

        print(f"    original: {original}")
        print(f"    7b:       {desc_7b}  {'⚠ still generic' if is_generic(desc_7b) else '✓'}")
        print(f"    13b:      {desc_13b}  {'⚠ still generic' if is_generic(desc_13b) else '✓'}")
        print()

    # Summary
    generic_7b  = sum(1 for r in results if r["7b_generic"])
    generic_13b = sum(1 for r in results if r["13b_generic"])
    print(f"  {'─'*60}")
    print(f"  RESULTS ({len(results)} images):")
    print(f"    llava:7b  — {len(results)-generic_7b}/{len(results)} specific  ({generic_7b} still generic)")
    print(f"    llava:13b — {len(results)-generic_13b}/{len(results)} specific  ({generic_13b} still generic)")
    print()
    print(f"  RECOMMENDATION:")
    if generic_13b < generic_7b:
        diff = generic_7b - generic_13b
        print(f"    llava:13b is better — {diff} more specific descriptions")
        print(f"    Trade-off: ~2x slower (~{len(rows)//180:.0f}hrs vs ~{len(rows)//360:.0f}hrs for full run)")
    elif generic_7b <= generic_13b:
        print(f"    llava:7b is good enough — similar quality, ~2x faster")
        print(f"    Estimated full run time: ~{3096*5//3600:.0f}-{3096*8//3600:.0f} hours")
    print()

# ─── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Screenshot Organizer — Karl's Productivity OS"
    )
    parser.add_argument(
        "--reprocess-generic", action="store_true",
        help="Re-run LLaVA on entries with weak/generic descriptions"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview without making changes"
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="Show index stats and generic description count"
    )
    parser.add_argument(
        "--model", type=str, default=MODEL,
        help=f"Ollama model to use (default: {MODEL})"
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Limit number of images to reprocess (useful for testing)"
    )
    parser.add_argument(
        "--compare", action="store_true",
        help="Run same images through llava:7b AND llava:13b side by side for comparison"
    )
    args = parser.parse_args()

    if args.stats:
        print_stats(Path(INDEX_FILE))
    elif args.compare:
        run_compare(limit=args.limit or 20)
    elif args.reprocess_generic:
        run_reprocess_generic(
            dry_run=args.dry_run,
            model=args.model,
            limit=args.limit
        )
    else:
        run_process(dry_run=args.dry_run, model=args.model)
