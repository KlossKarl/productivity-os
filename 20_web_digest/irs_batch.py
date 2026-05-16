"""
IRS Publications Batch — Loom
Fetch IRS publications as structured markdown.

IRS publications are authoritative, free, and comprehensive.
Most useful for: tax planning, fund taxation, international tax,
partnership taxation, corporate transactions.

Usage:
    python irs_batch.py --pubs 550 541 946 970
    python irs_batch.py --category partnerships
    python irs_batch.py --category all
    python irs_batch.py --list

Output: vault/Regulatory/IRS/
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
IRS_BASE     = "https://www.irs.gov"
DELAY        = 2.0

# ── Curated IRS Publications ──────────────────────────────────────────────────
# Format: pub_number: (title, category)
IRS_PUBS = {
    # INVESTMENT + CAPITAL GAINS
    "550": ("Investment Income and Expenses",               "investment"),
    "551": ("Basis of Assets",                              "investment"),
    "544": ("Sales and Other Dispositions of Assets",       "investment"),
    "505": ("Tax Withholding and Estimated Tax",            "investment"),

    # PARTNERSHIPS + PASS-THROUGH
    "541": ("Partnerships",                                 "partnerships"),
    "542": ("Corporations",                                 "corporate"),
    "946": ("How to Depreciate Property",                   "corporate"),

    # INTERNATIONAL TAX
    "514": ("Foreign Tax Credit for Individuals",           "international"),
    "519": ("U.S. Tax Guide for Aliens",                    "international"),
    "515": ("Withholding of Tax on Nonresident Aliens",     "international"),
    "54":  ("Tax Guide for U.S. Citizens and Resident Aliens Abroad", "international"),

    # GENERAL BUSINESS
    "334": ("Tax Guide for Small Business",                 "business"),
    "535": ("Business Expenses",                            "business"),
    "538": ("Accounting Periods and Methods",               "business"),
    "560": ("Retirement Plans for Small Business",          "business"),

    # ESTATE + GIFT
    "950": ("Introduction to Estate and Gift Taxes",        "estate"),
    "559": ("Survivors, Executors, and Administrators",     "estate"),

    # GENERAL REFERENCE
    "17":  ("Your Federal Income Tax (comprehensive guide)", "general"),
    "15":  ("Employer's Tax Guide (Circular E)",            "general"),
    "1":   ("Your Rights as a Taxpayer",                    "general"),
}

CATEGORIES = {
    "investment":    [k for k,v in IRS_PUBS.items() if v[1] == "investment"],
    "partnerships":  [k for k,v in IRS_PUBS.items() if v[1] == "partnerships"],
    "corporate":     [k for k,v in IRS_PUBS.items() if v[1] == "corporate"],
    "international": [k for k,v in IRS_PUBS.items() if v[1] == "international"],
    "business":      [k for k,v in IRS_PUBS.items() if v[1] == "business"],
    "estate":        [k for k,v in IRS_PUBS.items() if v[1] == "estate"],
    "general":       [k for k,v in IRS_PUBS.items() if v[1] == "general"],
}

HEADERS = {"User-Agent": "loom/1.0 personal-research@example.com"}


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)

def get_vault_path() -> Path:
    cfg = load_config()
    return Path(cfg['second_brain']['vaults'][0])

def get_output_dir() -> Path:
    d = get_vault_path() / "Regulatory" / "IRS"
    d.mkdir(parents=True, exist_ok=True)
    return d

def get_done_path() -> Path:
    d = PROJECT_ROOT / "20_web_digest" / "raw" / "irs_done"
    d.mkdir(parents=True, exist_ok=True)
    return d / "done.txt"

def load_done() -> set:
    p = get_done_path()
    return set(p.read_text().splitlines()) if p.exists() else set()

def mark_done(pub: str):
    with open(get_done_path(), 'a') as f:
        f.write(pub + "\n")


def fetch_pub(pub_num: str) -> str:
    """Fetch IRS publication HTML and extract text."""
    # IRS publications are at /publications/p{num}
    url = f"{IRS_BASE}/publications/p{pub_num}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code == 404:
            # Try alternate URL pattern
            url = f"{IRS_BASE}/pub/irs-pdf/p{pub_num}.pdf"
            return f"[PDF only — available at {url}]"
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Remove navigation + boilerplate
        for tag in soup.find_all(['nav', 'header', 'footer', 'script', 'style',
                                   'aside', '.sidebar']):
            tag.decompose()

        # Try to find main content
        main = (soup.find('main') or
                soup.find('div', class_='main-content') or
                soup.find('div', id='content') or
                soup)

        text = main.get_text("\n", strip=True)
        # Clean up excessive whitespace
        text = re.sub(r'\n{4,}', '\n\n\n', text)
        return text[:80_000]   # cap at 80k chars

    except Exception as e:
        return f"[ERROR: {e}]"


def process_pub(pub_num: str):
    done = load_done()
    if pub_num in done:
        print(f"  SKIP Pub {pub_num} (already done)")
        return

    info = IRS_PUBS.get(pub_num)
    if info:
        title, category = info
    else:
        title    = f"IRS Publication {pub_num}"
        category = "other"

    print(f"  Pub {pub_num}: {title}")
    text = fetch_pub(pub_num)

    if text.startswith("[ERROR") or text.startswith("[PDF only"):
        print(f"    {text}")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    md = f"""# IRS Publication {pub_num}: {title}

**Source:** IRS.gov
**URL:** https://www.irs.gov/publications/p{pub_num}
**Fetched:** {today}
**Category:** {category}

---

{text}
"""
    safe = re.sub(r'[<>:"/\\|?*]', '', title)[:80]
    path = get_output_dir() / f"IRS Pub {pub_num} {safe}.md"
    path.write_text(md, encoding='utf-8')
    mark_done(pub_num)
    print(f"    → {path.name}  ({len(text):,} chars)")


def main():
    parser = argparse.ArgumentParser(description="Fetch IRS publications")
    parser.add_argument("--pubs",     nargs="+", help="Publication numbers (e.g. 550 541 946)")
    parser.add_argument("--category", type=str,
                        choices=list(CATEGORIES.keys()) + ["all"],
                        help="Fetch all pubs in a category")
    parser.add_argument("--list",     action="store_true", help="List all curated publications")
    args = parser.parse_args()

    if args.list:
        for cat, pubs in CATEGORIES.items():
            print(f"\n  [{cat.upper()}]")
            for p in pubs:
                title = IRS_PUBS[p][0]
                print(f"    Pub {p:<5} {title}")
        sys.exit(0)

    pub_list = []
    if args.pubs:
        pub_list.extend(args.pubs)
    if args.category:
        if args.category == "all":
            pub_list.extend(IRS_PUBS.keys())
        else:
            pub_list.extend(CATEGORIES[args.category])

    if not pub_list:
        parser.print_help()
        print("\nExamples:")
        print("  python irs_batch.py --list")
        print("  python irs_batch.py --pubs 550 541 946")
        print("  python irs_batch.py --category partnerships")
        print("  python irs_batch.py --category all")
        sys.exit(0)

    print(f"\n{'='*56}")
    print(f"  IRS Publications Batch — Loom")
    print(f"{'='*56}")
    print(f"  Publications: {len(pub_list)}\n")

    for i, pub in enumerate(pub_list, 1):
        print(f"[{i}/{len(pub_list)}]", end=" ")
        process_pub(pub)
        time.sleep(DELAY)

    print(f"\n  Output: {get_output_dir()}")


if __name__ == "__main__":
    main()
