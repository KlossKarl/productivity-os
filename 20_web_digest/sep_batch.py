"""
Stanford Encyclopedia of Philosophy Batch — Loom
Fetches SEP articles by entry name and converts to structured markdown.

SEP is the gold standard for philosophy — peer-reviewed, comprehensive,
regularly updated. Free to read, no API key needed.

Usage:
    python sep_batch.py --topics topics/sep_entries.txt
    python sep_batch.py --entries consciousness free-will artificial-intelligence
    python sep_batch.py --entries consciousness --preview

Output: vault/Philosophy/YYYY-MM-DD {Title}.md
"""

import sys
import re
import time
import argparse
from pathlib import Path
from datetime import datetime

try:
    import yaml
except ImportError:
    print("[ERROR] pip install pyyaml")
    sys.exit(1)

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("[ERROR] pip install requests beautifulsoup4")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH  = PROJECT_ROOT / "config.yaml"
SEP_BASE     = "https://plato.stanford.edu/entries"
DELAY        = 2.0

def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)

def get_vault_path() -> Path:
    cfg = load_config()
    return Path(cfg['second_brain']['vaults'][0])

def get_output_dir() -> Path:
    d = get_vault_path() / "Philosophy"
    d.mkdir(parents=True, exist_ok=True)
    return d

def get_done_path() -> Path:
    d = PROJECT_ROOT / "20_web_digest" / "raw" / "sep_done"
    d.mkdir(parents=True, exist_ok=True)
    return d / "done.txt"

def load_done() -> set:
    p = get_done_path()
    return set(p.read_text().splitlines()) if p.exists() else set()

def mark_done(entry: str):
    with open(get_done_path(), 'a') as f:
        f.write(entry + "\n")


def fetch_sep_entry(entry_slug: str) -> dict | None:
    """
    Fetch a SEP article by its URL slug (e.g. 'consciousness', 'free-will').
    Returns dict with title, authors, content sections, or None on failure.
    """
    url = f"{SEP_BASE}/{entry_slug}/"
    try:
        resp = requests.get(url, timeout=30,
                            headers={"User-Agent": "loom/1.0 (personal research)"})
        resp.raise_for_status()
    except Exception as e:
        print(f"    [ERROR] {e}")
        return None

    soup = BeautifulSoup(resp.text, 'html.parser')

    # Title
    title_el = soup.find('h1')
    title = title_el.get_text(strip=True) if title_el else entry_slug.replace('-', ' ').title()

    # Authors + publication date
    pub_info = soup.find('div', id='pubinfo')
    authors = ""
    pub_date = ""
    if pub_info:
        authors = pub_info.get_text(" ", strip=True)

    # Preamble (intro before first section header)
    preamble_parts = []
    main = soup.find('div', id='main-text') or soup.find('div', id='article')
    if main:
        for el in main.children:
            if hasattr(el, 'name'):
                if el.name in ('h2', 'h3') and el.get('id'):
                    break
                if el.name == 'p':
                    text = el.get_text(" ", strip=True)
                    if text:
                        preamble_parts.append(text)

    # Sections
    sections = []
    if main:
        current_section = None
        current_paras = []
        for el in main.find_all(['h2', 'h3', 'p']):
            if el.name in ('h2', 'h3'):
                if current_section and current_paras:
                    sections.append((current_section, current_paras))
                current_section = el.get_text(strip=True)
                current_paras = []
            elif el.name == 'p' and current_section:
                text = el.get_text(" ", strip=True)
                if text and len(text) > 40:
                    current_paras.append(text)
        if current_section and current_paras:
            sections.append((current_section, current_paras))

    # Bibliography entries (just authors + titles, not full citations)
    bib = soup.find('div', id='bibliography')
    bib_entries = []
    if bib:
        for li in bib.find_all('li')[:30]:   # cap at 30
            text = li.get_text(" ", strip=True)
            if text:
                bib_entries.append(text)

    return {
        "slug": entry_slug,
        "title": title,
        "authors": authors,
        "url": url,
        "preamble": " ".join(preamble_parts),
        "sections": sections,
        "bibliography": bib_entries,
    }


def entry_to_markdown(entry: dict) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    md = f"""# {entry['title']}

**Source:** Stanford Encyclopedia of Philosophy
**URL:** {entry['url']}
**Authors/Editors:** {entry['authors']}
**Fetched:** {today}

---

"""
    if entry['preamble']:
        md += entry['preamble'] + "\n\n---\n\n"

    for section_title, paras in entry['sections']:
        # Skip bibliography/notes sections — captured separately
        if any(x in section_title.lower() for x in ['bibliograph', 'references', 'notes', 'citation']):
            continue
        md += f"## {section_title}\n\n"
        md += "\n\n".join(paras) + "\n\n"

    if entry['bibliography']:
        md += "## Key References\n\n"
        for b in entry['bibliography']:
            md += f"- {b}\n"
        md += "\n"

    return md


def process_entry(slug: str, preview: bool = False) -> bool:
    slug = slug.strip().lower().replace(' ', '-')
    print(f"  Fetching: {slug}")

    data = fetch_sep_entry(slug)
    if not data:
        print(f"    [FAIL] Could not fetch {slug}")
        return False

    print(f"    Title: {data['title']}")
    print(f"    Sections: {len(data['sections'])}")

    md = entry_to_markdown(data)

    if preview:
        print("\n" + "─"*50)
        print(md[:1500])
        print("─"*50 + "\n")
        return True

    out_dir   = get_output_dir()
    safe_name = re.sub(r'[<>:"/\\|?*]', '', data['title'])[:100]
    today     = datetime.now().strftime("%Y-%m-%d")
    out_path  = out_dir / f"{today} {safe_name}.md"

    out_path.write_text(md, encoding='utf-8')
    mark_done(slug)
    print(f"    → {out_path.name}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Stanford Encyclopedia of Philosophy articles"
    )
    parser.add_argument("--entries", nargs="+",
                        help="SEP entry slugs (e.g. consciousness free-will artificial-intelligence)")
    parser.add_argument("--topics",  type=str,
                        help="Text file with one entry slug per line")
    parser.add_argument("--preview", action="store_true",
                        help="Print first 1500 chars instead of saving")
    args = parser.parse_args()

    if not args.entries and not args.topics:
        parser.print_help()
        print("\nExamples:")
        print("  python sep_batch.py --entries consciousness free-will")
        print("  python sep_batch.py --topics topics/sep_philosophy.txt")
        print("\nFind entry slugs at: https://plato.stanford.edu/contents.html")
        sys.exit(0)

    entries = []
    if args.entries:
        entries.extend(args.entries)
    if args.topics:
        p = Path(args.topics)
        if p.exists():
            entries.extend([
                l.strip() for l in p.read_text().splitlines()
                if l.strip() and not l.startswith('#')
            ])

    done    = load_done()
    total   = len(entries)
    success = skip = fail = 0

    print(f"\n{'='*56}")
    print(f"  SEP Batch — Stanford Encyclopedia of Philosophy")
    print(f"{'='*56}")
    print(f"  Entries: {total}\n")

    for i, slug in enumerate(entries, 1):
        print(f"\n[{i}/{total}]", end=" ")
        if slug in done and not args.preview:
            print(f"SKIP (done): {slug}")
            skip += 1
            continue
        ok = process_entry(slug, args.preview)
        if ok:
            success += 1
        else:
            fail += 1
        time.sleep(DELAY)

    print(f"\n{'='*56}")
    print(f"  Saved: {success}  Skipped: {skip}  Failed: {fail}")
    print(f"  Output: {get_output_dir()}")


if __name__ == "__main__":
    main()
