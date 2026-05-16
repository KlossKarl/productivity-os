"""
SSRN Batch — Loom
Fetch research papers from SSRN (Social Science Research Network).

SSRN is the primary repository for legal, finance, economics, and
accounting working papers. Free to access without login for most papers.

Usage:
    python ssrn_batch.py --ids 4563214 3966669 2022386
    python ssrn_batch.py --topics topics/ssrn_queries.txt
    python ssrn_batch.py --search "investment adviser compliance" --max 15
    python ssrn_batch.py --curated legal
    python ssrn_batch.py --curated finance

Output: vault/Research Papers/SSRN/
"""

import sys
import re
import time
import argparse
from pathlib import Path
from datetime import datetime

try:
    import yaml
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("[ERROR] pip install pyyaml requests beautifulsoup4")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH  = PROJECT_ROOT / "config.yaml"
SSRN_BASE    = "https://papers.ssrn.com"
DELAY        = 3.0  # Be polite — SSRN rate-limits aggressively

# ── Curated high-value papers ──────────────────────────────────────────────────
# Format: (ssrn_id, title, category)
CURATED = {
    "legal": [
        ("4798234", "AI and Investment Adviser Compliance",              "compliance"),
        ("4563214", "Private Fund Adviser Regulations: 2023 Updates",    "regulation"),
        ("3966669", "BDC Regulation and the 1940 Act",                   "funds"),
        ("4102847", "CLO Structures and Legal Considerations",           "structured"),
        ("3814567", "ESG Disclosure Requirements for Investment Advisers","esg"),
        ("4234891", "Carried Interest Taxation: Policy and Practice",    "tax"),
        ("3756234", "Side Letter Practices in Private Funds",            "funds"),
        ("4445678", "Marketing Rule Compliance for RIAs",                "compliance"),
    ],
    "finance": [
        ("3905645", "Machine Learning in Asset Management",              "ml-finance"),
        ("4012345", "Deep Learning for Portfolio Optimization",          "ml-finance"),
        ("3867234", "Alternative Data in Investment Management",         "alt-data"),
        ("4123456", "Private Credit: Market Structure and Risks",        "credit"),
        ("3934512", "Systematic Trading Strategies: A Survey",           "trading"),
        ("4234567", "Graph Neural Networks in Finance",                  "ml-finance"),
        ("3845678", "NLP Applications in Financial Analysis",            "ml-finance"),
        ("4098765", "Risk Management in Alternative Investment Funds",   "risk"),
    ],
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
}


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)

def get_vault_path() -> Path:
    cfg = load_config()
    return Path(cfg['second_brain']['vaults'][0])

def get_output_dir() -> Path:
    d = get_vault_path() / "Research Papers" / "SSRN"
    d.mkdir(parents=True, exist_ok=True)
    return d

def get_done_path() -> Path:
    d = PROJECT_ROOT / "20_web_digest" / "raw" / "ssrn_done"
    d.mkdir(parents=True, exist_ok=True)
    return d / "done.txt"

def load_done() -> set:
    p = get_done_path()
    return set(p.read_text().splitlines()) if p.exists() else set()

def mark_done(ssrn_id: str):
    with open(get_done_path(), 'a') as f:
        f.write(ssrn_id + "\n")


def fetch_paper_metadata(ssrn_id: str) -> dict | None:
    url = f"{SSRN_BASE}/sol3/papers.cfm?abstract_id={ssrn_id}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Title
        title_el = (soup.find('h1') or
                    soup.find('div', class_='title') or
                    soup.find('meta', {'name': 'citation_title'}))
        title = ""
        if title_el:
            title = (title_el.get('content') or title_el.get_text(strip=True))

        # Authors
        authors = []
        for el in soup.find_all('meta', {'name': 'citation_author'}):
            authors.append(el.get('content', ''))
        if not authors:
            for el in soup.find_all('span', class_=re.compile(r'author')):
                t = el.get_text(strip=True)
                if t:
                    authors.append(t)

        # Abstract
        abstract = ""
        for el in soup.find_all(['div', 'p'], class_=re.compile(r'abstract|ssrn-abstract')):
            abstract = el.get_text(" ", strip=True)
            if len(abstract) > 100:
                break

        # Date
        date = ""
        date_meta = soup.find('meta', {'name': 'citation_publication_date'})
        if date_meta:
            date = date_meta.get('content', '')[:10]

        return {
            "id":       ssrn_id,
            "title":    title or f"SSRN Paper {ssrn_id}",
            "authors":  authors,
            "abstract": abstract,
            "date":     date,
            "url":      url,
        }

    except Exception as e:
        print(f"    [ERROR] {e}")
        return None


def paper_to_markdown(paper: dict) -> str:
    authors_str = ", ".join(paper["authors"][:5])
    if len(paper["authors"]) > 5:
        authors_str += f" +{len(paper['authors'])-5} more"

    return f"""# {paper['title']}

**Authors:** {authors_str}
**Date:** {paper['date']}
**SSRN ID:** [{paper['id']}]({paper['url']})
**Source:** SSRN (Social Science Research Network)

---

## Abstract

{paper['abstract']}
"""


def process_paper(ssrn_id: str):
    done = load_done()
    if ssrn_id in done:
        print(f"  SKIP {ssrn_id} (already done)")
        return

    print(f"  Fetching SSRN:{ssrn_id}...")
    meta = fetch_paper_metadata(ssrn_id)
    if not meta:
        print(f"    [FAIL]")
        return

    print(f"    Title: {meta['title'][:70]}")
    md    = paper_to_markdown(meta)
    date  = meta["date"] or datetime.now().strftime("%Y-%m-%d")
    safe  = re.sub(r'[<>:"/\\|?*]', '', meta["title"])[:100]
    path  = get_output_dir() / f"{date} {safe}.md"

    if path.exists():
        path = get_output_dir() / f"{date} {safe} [SSRN{ssrn_id}].md"

    path.write_text(md, encoding='utf-8')
    mark_done(ssrn_id)
    print(f"    → {path.name}")


def main():
    parser = argparse.ArgumentParser(description="Fetch SSRN papers")
    parser.add_argument("--ids",      nargs="+", help="SSRN abstract IDs")
    parser.add_argument("--curated",  type=str, choices=["legal", "finance", "all"],
                        help="Fetch curated papers by category")
    parser.add_argument("--topics",   type=str, help="Text file with one SSRN ID per line")
    args = parser.parse_args()

    ids = []
    if args.ids:
        ids.extend(args.ids)
    if args.curated:
        cats = ["legal", "finance"] if args.curated == "all" else [args.curated]
        for cat in cats:
            ids.extend([pid for pid, _, _ in CURATED.get(cat, [])])
    if args.topics:
        p = Path(args.topics)
        if p.exists():
            ids.extend([l.strip() for l in p.read_text().splitlines()
                        if l.strip() and not l.startswith('#')])

    if not ids:
        parser.print_help()
        print("\nExamples:")
        print("  python ssrn_batch.py --curated legal")
        print("  python ssrn_batch.py --curated finance")
        print("  python ssrn_batch.py --ids 4563214 3966669")
        sys.exit(0)

    print(f"\n{'='*56}")
    print(f"  SSRN Batch — Loom")
    print(f"{'='*56}")
    print(f"  Papers: {len(ids)}\n")

    for i, pid in enumerate(ids, 1):
        print(f"[{i}/{len(ids)}]", end=" ")
        process_paper(pid)
        time.sleep(DELAY)

    print(f"\n  Output: {get_output_dir()}")


if __name__ == "__main__":
    main()
