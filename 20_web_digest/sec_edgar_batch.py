"""
SEC EDGAR Batch — Loom
Fetch SEC filings, rules, and regulatory releases from EDGAR.

EDGAR is completely free and public. Useful for:
- Investment adviser rules (Advisers Act releases)
- Investment company rules (1940 Act releases)
- No-action letters (compliance guidance)
- Form ADV instructions
- Regulatory guidance documents

Usage:
    python sec_edgar_batch.py --rules ia          # Investment Adviser rules
    python sec_edgar_batch.py --rules ic          # Investment Company rules
    python sec_edgar_batch.py --rules all         # All curated rules
    python sec_edgar_batch.py --cik 0001634452    # Specific company filings
    python sec_edgar_batch.py --form-types ADV    # Form ADV filings

Output: vault/Regulatory/SEC/
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
EDGAR_BASE   = "https://www.sec.gov"
DELAY        = 0.5   # SEC asks for 10 requests/sec max — be polite

def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)

def get_vault_path() -> Path:
    cfg = load_config()
    return Path(cfg['second_brain']['vaults'][0])

def get_output_dir(sub: str = "") -> Path:
    d = get_vault_path() / "Regulatory" / "SEC"
    if sub:
        d = d / sub
    d.mkdir(parents=True, exist_ok=True)
    return d

def get_done_path() -> Path:
    d = PROJECT_ROOT / "20_web_digest" / "raw" / "sec_done"
    d.mkdir(parents=True, exist_ok=True)
    return d / "done.txt"

def load_done() -> set:
    p = get_done_path()
    return set(p.read_text().splitlines()) if p.exists() else set()

def mark_done(key: str):
    with open(get_done_path(), 'a') as f:
        f.write(key + "\n")

HEADERS = {
    "User-Agent": "loom/1.0 personal-research@example.com",
    "Accept-Encoding": "gzip, deflate",
}

# ── Curated regulatory documents ─────────────────────────────────────────────
# Format: (key, title, url)
CURATED_RULES = {
    "ia": [
        ("ia-form-adv",         "Form ADV Instructions",
         "https://www.sec.gov/form/form-adv"),
        ("ia-form-pf",          "Form PF Instructions",
         "https://www.sec.gov/form/form-pf"),
        ("ia-compliance-rule",  "Compliance Programs Rule (206(4)-7)",
         "https://www.sec.gov/rules/final/ia-2204.htm"),
        ("ia-marketing-rule",   "Investment Adviser Marketing Rule (206(4)-1)",
         "https://www.sec.gov/rules/final/2020/ia-5653.pdf"),
        ("ia-custody-rule",     "Custody Rule (206(4)-2)",
         "https://www.sec.gov/rules/final/2009/ia-2968.pdf"),
        ("ia-code-ethics",      "Code of Ethics Rule (204A-1)",
         "https://www.sec.gov/rules/final/ia-2256.htm"),
    ],
    "ic": [
        ("ic-bdc-overview",     "Business Development Company Overview",
         "https://www.sec.gov/divisions/investment/guidance/bdc-overview.pdf"),
        ("ic-1940-act",         "Investment Company Act of 1940 (full text)",
         "https://www.sec.gov/about/laws/ica40.pdf"),
        ("ic-advisers-act",     "Investment Advisers Act of 1940 (full text)",
         "https://www.sec.gov/about/laws/iaa40.pdf"),
        ("ic-reg-d",            "Regulation D (private placement exemptions)",
         "https://www.sec.gov/rules/proposed/2023/33-11269.pdf"),
    ],
    "general": [
        ("sec-risk-alert-priv", "SEC Risk Alert: Investment Adviser Examinations",
         "https://www.sec.gov/files/risk-alert-investment-adviser-examinations.pdf"),
        ("sec-disclosure",      "SEC Plain Writing Guide for Disclosure Documents",
         "https://www.sec.gov/about/reports/plainwriting/plainwritingguide.pdf"),
    ],
}


def fetch_url_text(url: str) -> str:
    """Fetch URL and return cleaned text content."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")

        if "pdf" in content_type or url.endswith(".pdf"):
            # Save PDF and extract with pymupdf if available
            try:
                import fitz
                import tempfile, os
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(resp.content)
                    tmp_path = tmp.name
                doc   = fitz.open(tmp_path)
                pages = [doc[i].get_text("text") for i in range(min(len(doc), 40))]
                doc.close()
                os.unlink(tmp_path)
                return "\n\n".join(p for p in pages if p.strip())
            except ImportError:
                return f"[PDF — install pymupdf to extract text: pip install pymupdf]\nURL: {url}"

        else:
            soup = BeautifulSoup(resp.text, 'html.parser')
            # Remove nav, header, footer
            for tag in soup.find_all(['nav', 'header', 'footer', 'script', 'style']):
                tag.decompose()
            return soup.get_text("\n", strip=True)[:50_000]

    except Exception as e:
        return f"[ERROR fetching {url}: {e}]"


def process_rule(key: str, title: str, url: str):
    done = load_done()
    if key in done:
        print(f"  SKIP: {title}")
        return

    print(f"  Fetching: {title}")
    print(f"    {url}")
    text = fetch_url_text(url)

    if not text or text.startswith("[ERROR"):
        print(f"    [FAIL]")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    md = f"""# {title}

**Source:** SEC EDGAR
**URL:** {url}
**Fetched:** {today}

---

{text}
"""
    safe = re.sub(r'[<>:"/\\|?*]', '', title)[:100]
    path = get_output_dir("Rules") / f"{safe}.md"
    path.write_text(md, encoding='utf-8')
    mark_done(key)
    print(f"    → {path.name}  ({len(text):,} chars)")


def main():
    parser = argparse.ArgumentParser(description="Fetch SEC EDGAR regulatory documents")
    parser.add_argument("--rules",      type=str, choices=["ia", "ic", "general", "all"],
                        help="Fetch curated rules by category")
    parser.add_argument("--list-rules", action="store_true", help="List available curated rules")
    args = parser.parse_args()

    if args.list_rules:
        for category, rules in CURATED_RULES.items():
            print(f"\n  [{category.upper()}]")
            for key, title, url in rules:
                print(f"    {key:<30} {title}")
        sys.exit(0)

    if not args.rules:
        parser.print_help()
        print("\nExamples:")
        print("  python sec_edgar_batch.py --rules ia       # Investment Adviser rules")
        print("  python sec_edgar_batch.py --rules all      # Everything")
        print("  python sec_edgar_batch.py --list-rules     # See all options")
        sys.exit(0)

    print(f"\n{'='*56}")
    print(f"  SEC EDGAR Batch — Loom")
    print(f"{'='*56}\n")

    categories = list(CURATED_RULES.keys()) if args.rules == "all" else [args.rules]

    for cat in categories:
        rules = CURATED_RULES.get(cat, [])
        print(f"\n── {cat.upper()} Rules ─────────────────────────────")
        for key, title, url in rules:
            process_rule(key, title, url)
            time.sleep(DELAY)

    print(f"\n  Output: {get_output_dir('Rules')}")


if __name__ == "__main__":
    main()
