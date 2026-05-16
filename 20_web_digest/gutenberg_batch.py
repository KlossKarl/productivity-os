"""
Project Gutenberg Batch — Loom
Fetch public domain books from Project Gutenberg.

All books are completely free and public domain (pre-1928 US copyright).
No API key needed. Gutenberg has 70,000+ books.

Usage:
    python gutenberg_batch.py --ids 1342 84 11 2701   # Pride & Prejudice, Frankenstein, Alice, Moby Dick
    python gutenberg_batch.py --topics topics/gutenberg_books.txt
    python gutenberg_batch.py --search "sun tzu"
    python gutenberg_batch.py --list-classics

Find book IDs: https://www.gutenberg.org/browse/scores/top

Output: vault/Books/YYYY {Title} - {Author}.md
"""

import sys
import re
import time
import argparse
import urllib.request
import json
from pathlib import Path
from datetime import datetime

try:
    import yaml
    import requests
except ImportError:
    print("[ERROR] pip install pyyaml requests")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH  = PROJECT_ROOT / "config.yaml"
GUTENBERG_API = "https://gutendex.com/books"   # Free Gutenberg REST API
DELAY         = 2.0

# ── Curated classics by ID ────────────────────────────────────────────────────
CLASSICS = {
    # Strategy + Philosophy
    "art-of-war":           (132,  "The Art of War",                    "Sun Tzu"),
    "meditations":          (2680, "Meditations",                       "Marcus Aurelius"),
    "republic":             (1497, "The Republic",                      "Plato"),
    "nicomachean-ethics":   (8438, "Nicomachean Ethics",                "Aristotle"),
    "prince":               (1232, "The Prince",                        "Machiavelli"),
    "leviathan":            (3207, "Leviathan",                         "Hobbes"),
    "wealth-of-nations":    (3300, "The Wealth of Nations",             "Adam Smith"),
    "beyond-good-evil":     (4363, "Beyond Good and Evil",              "Nietzsche"),
    "thus-spoke":           (1998, "Thus Spoke Zarathustra",            "Nietzsche"),
    "utilitarianism":       (11224,"Utilitarianism",                    "Mill"),
    "on-liberty":           (34901,"On Liberty",                        "Mill"),
    "communist-manifesto":  (61,   "The Communist Manifesto",           "Marx"),
    "pragmatism":           (5116, "Pragmatism",                        "William James"),
    # Science
    "origin-of-species":    (1228, "On the Origin of Species",          "Darwin"),
    "relativity":           (5001, "Relativity: The Special and General Theory", "Einstein"),
    "principia":            (28233,"Principia Mathematica (excerpts)",   "Newton"),
    # Literature + Fiction
    "moby-dick":            (2701, "Moby Dick",                         "Melville"),
    "frankenstein":         (84,   "Frankenstein",                      "Shelley"),
    "dracula":              (345,  "Dracula",                           "Stoker"),
    "war-of-worlds":        (36,   "The War of the Worlds",             "H.G. Wells"),
    "time-machine":         (35,   "The Time Machine",                  "H.G. Wells"),
    "1984-precursor":       (5230, "Brave New World (predecessor text)", "Various"),
    # Psychology + Self
    "interpretation-dreams":(33048,"The Interpretation of Dreams",      "Freud"),
    "beyond-pleasure":      (596,  "Beyond the Pleasure Principle",     "Freud"),
}

def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)

def get_vault_path() -> Path:
    cfg = load_config()
    return Path(cfg['second_brain']['vaults'][0])

def get_output_dir() -> Path:
    d = get_vault_path() / "Books"
    d.mkdir(parents=True, exist_ok=True)
    return d

def get_done_path() -> Path:
    d = PROJECT_ROOT / "20_web_digest" / "raw" / "gutenberg_done"
    d.mkdir(parents=True, exist_ok=True)
    return d / "done.txt"

def load_done() -> set:
    p = get_done_path()
    return set(p.read_text().splitlines()) if p.exists() else set()

def mark_done(book_id: str):
    with open(get_done_path(), 'a') as f:
        f.write(str(book_id) + "\n")


def fetch_book_metadata(book_id: int) -> dict | None:
    url = f"{GUTENBERG_API}/{book_id}"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  [ERROR] Metadata fetch failed: {e}")
        return None


def fetch_book_text(meta: dict) -> str:
    """Find and download the plain text version of a book."""
    formats = meta.get("formats", {})
    # Prefer UTF-8 plain text
    for mime in ["text/plain; charset=utf-8", "text/plain; charset=us-ascii", "text/plain"]:
        if mime in formats:
            url = formats[mime]
            try:
                resp = requests.get(url, timeout=60,
                                    headers={"User-Agent": "loom/1.0"})
                resp.raise_for_status()
                return resp.text
            except Exception as e:
                print(f"  [WARN] Text download failed ({url}): {e}")

    print(f"  [WARN] No plain text format found for this book")
    return ""


def clean_gutenberg_text(text: str) -> str:
    """Strip Gutenberg header/footer boilerplate."""
    # Find where actual content starts
    start_markers = [
        "*** START OF THE PROJECT GUTENBERG",
        "***START OF THE PROJECT GUTENBERG",
        "*** START OF THIS PROJECT GUTENBERG",
        "END OF THE PROJECT GUTENBERG EBOOK",
    ]
    start = 0
    for marker in start_markers[:3]:
        idx = text.find(marker)
        if idx != -1:
            newline = text.find('\n', idx)
            if newline != -1:
                start = newline + 1
                break

    # Find where content ends
    end = len(text)
    for marker in ["*** END OF THE PROJECT GUTENBERG", "***END OF THE PROJECT GUTENBERG",
                   "End of the Project Gutenberg", "END OF PROJECT GUTENBERG"]:
        idx = text.rfind(marker)
        if idx != -1:
            end = idx
            break

    cleaned = text[start:end].strip()

    # Cap very long books at ~200k chars (plenty for indexing, avoids OOM)
    if len(cleaned) > 200_000:
        cleaned = cleaned[:200_000] + "\n\n[... text truncated for indexing ...]"

    return cleaned


def book_to_markdown(meta: dict, text: str) -> str:
    title    = meta.get("title", "Unknown Title")
    authors  = ", ".join(a["name"] for a in meta.get("authors", []))
    subjects = ", ".join(meta.get("subjects", [])[:8])
    bid      = meta.get("id", "")
    url      = f"https://www.gutenberg.org/ebooks/{bid}"

    return f"""# {title}

**Author(s):** {authors}
**Gutenberg ID:** [{bid}]({url})
**Subjects:** {subjects}

---

{text}
"""


def process_book(book_id: int):
    bid_str = str(book_id)
    done = load_done()

    if bid_str in done:
        print(f"  SKIP {book_id} (already done)")
        return

    print(f"  Fetching metadata for ID {book_id}...")
    meta = fetch_book_metadata(book_id)
    if not meta:
        return

    title   = meta.get("title", f"Book {book_id}")
    authors = " ".join(a["name"].split(",")[0] for a in meta.get("authors", []))
    print(f"  Title: {title}")
    print(f"  Downloading text...")

    text = fetch_book_text(meta)
    if not text:
        print(f"  [SKIP] No text available")
        return

    text = clean_gutenberg_text(text)
    md   = book_to_markdown(meta, text)

    # Parse year from author death date as proxy
    year = ""
    for a in meta.get("authors", []):
        death = a.get("death_year")
        if death:
            year = str(death)
            break

    safe   = re.sub(r'[<>:"/\\|?*]', '', title)[:80]
    safe_a = re.sub(r'[<>:"/\\|?*]', '', authors)[:30]
    fname  = f"{year} {safe} - {safe_a}.md" if year else f"{safe} - {safe_a}.md"
    path   = get_output_dir() / fname

    path.write_text(md, encoding='utf-8')
    mark_done(bid_str)
    print(f"  → {path.name}  ({len(text):,} chars)")


def search_gutenberg(query: str, limit: int = 10) -> list[dict]:
    try:
        resp = requests.get(GUTENBERG_API, params={"search": query, "mime_type": "text/plain"},
                            timeout=20)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return results[:limit]
    except Exception as e:
        print(f"[ERROR] Search failed: {e}")
        return []


def main():
    parser = argparse.ArgumentParser(description="Fetch Project Gutenberg books")
    parser.add_argument("--ids",            nargs="+", type=int, help="Gutenberg book IDs")
    parser.add_argument("--topics",         type=str,  help="Text file with one ID per line")
    parser.add_argument("--search",         type=str,  help="Search Gutenberg by title/author")
    parser.add_argument("--list-classics",  action="store_true", help="List curated classics")
    parser.add_argument("--classics",       nargs="*", help="Fetch classics by key (or all if empty)")
    args = parser.parse_args()

    if args.list_classics:
        print("\nCurated classics:")
        for key, (bid, title, author) in CLASSICS.items():
            print(f"  {bid:<6} {title:<45} — {author}")
        sys.exit(0)

    if args.search:
        results = search_gutenberg(args.search)
        print(f"\nSearch results for '{args.search}':")
        for r in results:
            authors = ", ".join(a["name"] for a in r.get("authors", []))
            print(f"  ID {r['id']:<6} {r['title']:<50} — {authors}")
        sys.exit(0)

    ids = []
    if args.ids:
        ids.extend(args.ids)
    if args.classics is not None:
        keys = args.classics if args.classics else list(CLASSICS.keys())
        for key in keys:
            if key in CLASSICS:
                ids.append(CLASSICS[key][0])
            else:
                print(f"[WARN] Unknown classic key: {key}")
    if args.topics:
        p = Path(args.topics)
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith('#'):
                    try:
                        ids.append(int(line.split()[0]))
                    except ValueError:
                        pass

    if not ids:
        parser.print_help()
        print("\nExamples:")
        print("  python gutenberg_batch.py --list-classics")
        print("  python gutenberg_batch.py --classics art-of-war meditations republic")
        print("  python gutenberg_batch.py --ids 1342 84 2701")
        print("  python gutenberg_batch.py --search 'charles darwin'")
        sys.exit(0)

    print(f"\n{'='*56}")
    print(f"  Gutenberg Batch — Loom")
    print(f"{'='*56}")
    print(f"  Books: {len(ids)}\n")

    for i, bid in enumerate(ids, 1):
        print(f"\n[{i}/{len(ids)}]", end=" ")
        process_book(bid)
        time.sleep(DELAY)


if __name__ == "__main__":
    main()
