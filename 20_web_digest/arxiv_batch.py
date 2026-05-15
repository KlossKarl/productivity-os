"""
arXiv Batch — Productivity OS
Fetch research papers from arXiv by search query or paper IDs.
Converts to structured markdown and drops into vault.

arXiv has a free public API — no key needed, just be polite (3s delay between requests).

Usage:
    # Search by query
    python arxiv_batch.py --query "retrieval augmented generation" --max 20
    python arxiv_batch.py --query "transformer attention mechanism" --max 10

    # Fetch specific papers by ID
    python arxiv_batch.py --ids 2005.11401 2307.03172 1706.03762

    # Search a topic file (one query per line)
    python arxiv_batch.py --topics topics/arxiv_ai_frontier.txt --max 10

    # Use --abstracts-only for faster runs (no full PDF extraction)
    python arxiv_batch.py --query "graph neural networks" --max 30 --abstracts-only

Output: vault/Research Papers/YYYY-MM-DD {Title}.md
"""

import os
import sys
import time
import re
import argparse
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

try:
    import yaml
except ImportError:
    print("[ERROR] pip install pyyaml")
    sys.exit(1)

# Optional: full PDF text extraction
try:
    import fitz  # pymupdf
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH  = PROJECT_ROOT / "config.yaml"
ARXIV_API    = "https://export.arxiv.org/api/query"
ARXIV_NS     = "http://www.w3.org/2005/Atom"
DELAY        = 3.0   # arXiv asks for 3s between requests — respect it

def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)

def get_vault_path() -> Path:
    cfg = load_config()
    sb = cfg.get('second_brain', cfg)
    return Path(sb['vaults'][0])

def get_output_dir() -> Path:
    vault = get_vault_path()
    d = vault / "Research Papers"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ─────────────────────────────────────────────
# arXiv API
# ─────────────────────────────────────────────

def search_arxiv(query: str, max_results: int = 20, start: int = 0) -> list[dict]:
    """Search arXiv and return list of paper metadata dicts."""
    params = urllib.parse.urlencode({
        "search_query": f"all:{query}",
        "start": start,
        "max_results": max_results,
        "sortBy": "relevance",
        "sortOrder": "descending",
    })
    url = f"{ARXIV_API}?{params}"

    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            xml_data = resp.read()
    except Exception as e:
        print(f"[ERROR] arXiv API request failed: {e}")
        return []

    return _parse_arxiv_response(xml_data)


def fetch_arxiv_by_ids(ids: list[str]) -> list[dict]:
    """Fetch specific papers by arXiv ID."""
    id_list = ",".join(ids)
    params = urllib.parse.urlencode({
        "id_list": id_list,
        "max_results": len(ids),
    })
    url = f"{ARXIV_API}?{params}"

    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            xml_data = resp.read()
    except Exception as e:
        print(f"[ERROR] arXiv API request failed: {e}")
        return []

    return _parse_arxiv_response(xml_data)


def _parse_arxiv_response(xml_data: bytes) -> list[dict]:
    """Parse arXiv Atom XML response into list of paper dicts."""
    root = ET.fromstring(xml_data)
    ns = {"atom": ARXIV_NS, "arxiv": "http://arxiv.org/schemas/atom"}
    papers = []

    for entry in root.findall("atom:entry", ns):
        def get(tag):
            el = entry.find(f"atom:{tag}", ns)
            return el.text.strip() if el is not None and el.text else ""

        arxiv_id_raw = get("id")
        # ID is a URL like https://arxiv.org/abs/2005.11401v3 — extract the ID
        arxiv_id = re.search(r'(\d{4}\.\d{4,5}(v\d+)?|[a-z\-]+/\d+)', arxiv_id_raw)
        arxiv_id = arxiv_id.group(0) if arxiv_id else arxiv_id_raw

        # Strip version suffix for clean ID
        base_id = re.sub(r'v\d+$', '', arxiv_id)

        authors = [
            a.find("atom:name", ns).text.strip()
            for a in entry.findall("atom:author", ns)
            if a.find("atom:name", ns) is not None
        ]

        categories = [
            c.get("term", "")
            for c in entry.findall("atom:category", ns)
        ]

        papers.append({
            "id": base_id,
            "title": re.sub(r'\s+', ' ', get("title")),
            "authors": authors,
            "abstract": re.sub(r'\s+', ' ', get("summary")),
            "published": get("published")[:10],   # YYYY-MM-DD
            "updated": get("updated")[:10],
            "categories": categories,
            "pdf_url": f"https://arxiv.org/pdf/{base_id}",
            "abs_url": f"https://arxiv.org/abs/{base_id}",
        })

    return papers


# ─────────────────────────────────────────────
# PDF TEXT EXTRACTION (optional)
# ─────────────────────────────────────────────

def fetch_pdf_text(pdf_url: str, max_pages: int = 20) -> str:
    """
    Download arXiv PDF and extract text.
    Limited to first max_pages — arXiv papers have references at the end
    that add noise without value.
    """
    if not PDF_AVAILABLE:
        return ""

    try:
        import tempfile
        import urllib.request

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name

        headers = {"User-Agent": "productivity-os/1.0 (personal research tool)"}
        req = urllib.request.Request(pdf_url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            with open(tmp_path, 'wb') as f:
                f.write(resp.read())

        doc = fitz.open(tmp_path)
        pages = min(len(doc), max_pages)
        text_parts = []
        for i in range(pages):
            text = doc[i].get_text("text")
            if text.strip():
                text_parts.append(text)
        doc.close()
        os.unlink(tmp_path)

        return "\n\n".join(text_parts)

    except Exception as e:
        print(f"    [WARN] PDF extraction failed: {e}")
        return ""


# ─────────────────────────────────────────────
# MARKDOWN GENERATION
# ─────────────────────────────────────────────

def paper_to_markdown(paper: dict, full_text: str = "") -> str:
    authors_str = ", ".join(paper["authors"][:6])
    if len(paper["authors"]) > 6:
        authors_str += f" +{len(paper['authors']) - 6} more"

    categories_str = ", ".join(paper["categories"][:5])

    md = f"""# {paper['title']}

**Authors:** {authors_str}
**Published:** {paper['published']}
**arXiv ID:** [{paper['id']}]({paper['abs_url']})
**Categories:** {categories_str}
**PDF:** {paper['pdf_url']}

---

## Abstract

{paper['abstract']}

"""

    if full_text:
        md += f"""---

## Full Text (first 20 pages)

{full_text}
"""

    return md


def safe_filename(title: str) -> str:
    """Convert paper title to safe filename."""
    name = re.sub(r'[<>:"/\\|?*]', '', title)
    name = re.sub(r'\s+', ' ', name).strip()
    return name[:120]   # cap length


# ─────────────────────────────────────────────
# PROGRESS TRACKING
# ─────────────────────────────────────────────

def get_done_file(query_slug: str) -> Path:
    done_dir = PROJECT_ROOT / "20_web_digest" / "raw" / "arxiv_done"
    done_dir.mkdir(parents=True, exist_ok=True)
    return done_dir / f"{query_slug}.txt"

def load_done(query_slug: str) -> set:
    f = get_done_file(query_slug)
    if f.exists():
        return set(f.read_text().splitlines())
    return set()

def mark_done(query_slug: str, arxiv_id: str):
    with open(get_done_file(query_slug), 'a') as f:
        f.write(arxiv_id + "\n")


# ─────────────────────────────────────────────
# MAIN PROCESSING
# ─────────────────────────────────────────────

def process_papers(papers: list[dict], abstracts_only: bool, query_slug: str):
    if not papers:
        print("  No papers found.")
        return

    out_dir = get_output_dir()
    done    = load_done(query_slug)
    total   = len(papers)
    success = skip = fail = 0

    for i, paper in enumerate(papers, 1):
        pid = paper['id']

        if pid in done:
            skip += 1
            print(f"  [{i}/{total}] SKIP (already done): {paper['title'][:60]}")
            continue

        print(f"  [{i}/{total}] {paper['title'][:70]}")

        full_text = ""
        if not abstracts_only and PDF_AVAILABLE:
            print(f"    Fetching PDF...")
            full_text = fetch_pdf_text(paper['pdf_url'])
            if full_text:
                print(f"    Extracted {len(full_text):,} chars from PDF")
            time.sleep(DELAY)
        elif not abstracts_only and not PDF_AVAILABLE:
            print(f"    [INFO] pymupdf not installed — abstract only. pip install pymupdf")

        md = paper_to_markdown(paper, full_text)

        date_str  = paper['published']
        safe_name = safe_filename(paper['title'])
        out_path  = out_dir / f"{date_str} {safe_name}.md"

        # Collision protection
        if out_path.exists():
            out_path = out_dir / f"{date_str} {safe_name} [{pid.replace('/', '-')}].md"

        try:
            out_path.write_text(md, encoding='utf-8')
            mark_done(query_slug, pid)
            success += 1
            print(f"    → {out_path.name}")
        except Exception as e:
            fail += 1
            print(f"    [ERROR] Could not write file: {e}")

        time.sleep(DELAY)

    print(f"\n  Done: {success} saved, {skip} skipped, {fail} failed")
    print(f"  Output: {out_dir}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fetch arXiv papers into your vault"
    )
    parser.add_argument("--query",          type=str, help="Search query")
    parser.add_argument("--ids",            nargs="+", help="Specific arXiv IDs (e.g. 2005.11401)")
    parser.add_argument("--topics",         type=str, help="Text file with one query per line")
    parser.add_argument("--max",            type=int, default=20, help="Max papers per query (default 20)")
    parser.add_argument("--abstracts-only", action="store_true", help="Skip PDF download, abstract only")
    args = parser.parse_args()

    if not any([args.query, args.ids, args.topics]):
        parser.print_help()
        print("\nExamples:")
        print('  python arxiv_batch.py --query "retrieval augmented generation" --max 20')
        print('  python arxiv_batch.py --ids 2005.11401 1706.03762')
        print('  python arxiv_batch.py --topics topics/arxiv_queries.txt --max 10')
        sys.exit(0)

    print(f"\n{'='*56}")
    print(f"  arXiv Batch — Productivity OS")
    print(f"{'='*56}\n")

    if args.ids:
        print(f"  Fetching {len(args.ids)} papers by ID...")
        papers = fetch_arxiv_by_ids(args.ids)
        process_papers(papers, args.abstracts_only, "ids")

    elif args.query:
        slug = re.sub(r'\W+', '_', args.query.lower())[:40]
        print(f"  Query: '{args.query}'  max={args.max}")
        papers = search_arxiv(args.query, max_results=args.max)
        print(f"  Found: {len(papers)} papers\n")
        process_papers(papers, args.abstracts_only, slug)

    elif args.topics:
        topics_path = Path(args.topics)
        if not topics_path.exists():
            print(f"[ERROR] Topics file not found: {topics_path}")
            sys.exit(1)

        queries = [
            line.strip() for line in topics_path.read_text().splitlines()
            if line.strip() and not line.startswith('#')
        ]
        print(f"  Topics file: {topics_path.name} ({len(queries)} queries)")

        for q in queries:
            slug = re.sub(r'\W+', '_', q.lower())[:40]
            print(f"\n── Query: '{q}' ─────────────────────────")
            papers = search_arxiv(q, max_results=args.max)
            print(f"  Found: {len(papers)} papers")
            process_papers(papers, args.abstracts_only, slug)
            time.sleep(DELAY)


if __name__ == "__main__":
    main()
