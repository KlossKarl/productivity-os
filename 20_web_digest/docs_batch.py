"""
Docs Batch — Loom
Fetch technical documentation into your vault.

Covers: Python, Neo4j, ChromaDB, LangChain, FastAPI, PostgreSQL,
        NumPy, Pandas, PyTorch, and more.

Usage:
    python docs_batch.py --docs python neo4j chroma
    python docs_batch.py --docs all
    python docs_batch.py --list
    python docs_batch.py --url https://docs.example.com/page --title "Example Docs"

Output: vault/Technical Docs/{library}/
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
DELAY        = 1.5

# ── Documentation sources ─────────────────────────────────────────────────────
# Format: key: (name, pages_list)
# Each page: (page_title, url)
DOC_SOURCES = {
    "python": ("Python", [
        ("Built-in Types",         "https://docs.python.org/3/library/stdtypes.html"),
        ("Built-in Functions",     "https://docs.python.org/3/library/functions.html"),
        ("Itertools",              "https://docs.python.org/3/library/itertools.html"),
        ("Pathlib",                "https://docs.python.org/3/library/pathlib.html"),
        ("Asyncio",                "https://docs.python.org/3/library/asyncio.html"),
        ("Dataclasses",            "https://docs.python.org/3/library/dataclasses.html"),
        ("Typing",                 "https://docs.python.org/3/library/typing.html"),
        ("Subprocess",             "https://docs.python.org/3/library/subprocess.html"),
        ("Logging",                "https://docs.python.org/3/library/logging.html"),
        ("Regular Expressions",    "https://docs.python.org/3/library/re.html"),
    ]),
    "neo4j": ("Neo4j", [
        ("Cypher Introduction",    "https://neo4j.com/docs/cypher-manual/current/introduction/"),
        ("MATCH clause",           "https://neo4j.com/docs/cypher-manual/current/clauses/match/"),
        ("MERGE clause",           "https://neo4j.com/docs/cypher-manual/current/clauses/merge/"),
        ("Graph Data Modeling",    "https://neo4j.com/docs/getting-started/data-modeling/"),
        ("Python Driver",          "https://neo4j.com/docs/python-manual/current/"),
        ("Graph Algorithms",       "https://neo4j.com/docs/graph-data-science/current/algorithms/"),
    ]),
    "chroma": ("ChromaDB", [
        ("Getting Started",        "https://docs.trychroma.com/getting-started"),
        ("Collections",            "https://docs.trychroma.com/usage-guide"),
        ("Embeddings",             "https://docs.trychroma.com/embeddings"),
        ("Querying",               "https://docs.trychroma.com/querying"),
    ]),
    "fastapi": ("FastAPI", [
        ("Introduction",           "https://fastapi.tiangolo.com/"),
        ("Path Parameters",        "https://fastapi.tiangolo.com/tutorial/path-params/"),
        ("Request Body",           "https://fastapi.tiangolo.com/tutorial/body/"),
        ("Dependencies",           "https://fastapi.tiangolo.com/tutorial/dependencies/"),
        ("Security",               "https://fastapi.tiangolo.com/tutorial/security/"),
        ("Background Tasks",       "https://fastapi.tiangolo.com/tutorial/background-tasks/"),
        ("WebSockets",             "https://fastapi.tiangolo.com/advanced/websockets/"),
    ]),
    "pytorch": ("PyTorch", [
        ("Tensors",                "https://pytorch.org/docs/stable/tensors.html"),
        ("Autograd",               "https://pytorch.org/docs/stable/autograd.html"),
        ("nn.Module",              "https://pytorch.org/docs/stable/nn.html"),
        ("Optimizers",             "https://pytorch.org/docs/stable/optim.html"),
        ("DataLoader",             "https://pytorch.org/docs/stable/data.html"),
    ]),
    "numpy": ("NumPy", [
        ("Array Creation",         "https://numpy.org/doc/stable/user/basics.creation.html"),
        ("Indexing",               "https://numpy.org/doc/stable/user/basics.indexing.html"),
        ("Broadcasting",           "https://numpy.org/doc/stable/user/basics.broadcasting.html"),
        ("Linear Algebra",         "https://numpy.org/doc/stable/reference/routines.linalg.html"),
        ("Random",                 "https://numpy.org/doc/stable/reference/random/index.html"),
    ]),
    "pandas": ("Pandas", [
        ("10 Minutes to Pandas",   "https://pandas.pydata.org/docs/user_guide/10min.html"),
        ("Indexing and Selecting", "https://pandas.pydata.org/docs/user_guide/indexing.html"),
        ("GroupBy",                "https://pandas.pydata.org/docs/user_guide/groupby.html"),
        ("Time Series",            "https://pandas.pydata.org/docs/user_guide/timeseries.html"),
        ("Merging",                "https://pandas.pydata.org/docs/user_guide/merging.html"),
    ]),
    "anthropic": ("Anthropic", [
        ("Messages API",           "https://docs.anthropic.com/en/api/messages"),
        ("Models Overview",        "https://docs.anthropic.com/en/docs/about-claude/models/overview"),
        ("Tool Use",               "https://docs.anthropic.com/en/docs/build-with-claude/tool-use"),
        ("Prompt Engineering",     "https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview"),
        ("Vision",                 "https://docs.anthropic.com/en/docs/build-with-claude/vision"),
        ("Streaming",              "https://docs.anthropic.com/en/api/streaming"),
    ]),
    "git": ("Git", [
        ("Git Basics",             "https://git-scm.com/book/en/v2/Git-Basics-Getting-a-Git-Repository"),
        ("Branching",              "https://git-scm.com/book/en/v2/Git-Branching-Branches-in-a-Nutshell"),
        ("Rebasing",               "https://git-scm.com/book/en/v2/Git-Branching-Rebasing"),
        ("Internals",              "https://git-scm.com/book/en/v2/Git-Internals-Plumbing-and-Porcelain"),
    ]),
    "sql": ("SQL / PostgreSQL", [
        ("SELECT",                 "https://www.postgresql.org/docs/current/sql-select.html"),
        ("Window Functions",       "https://www.postgresql.org/docs/current/tutorial-window.html"),
        ("Indexes",                "https://www.postgresql.org/docs/current/indexes.html"),
        ("Query Planning",         "https://www.postgresql.org/docs/current/using-explain.html"),
        ("JSON",                   "https://www.postgresql.org/docs/current/functions-json.html"),
    ]),
}


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)

def get_vault_path() -> Path:
    cfg = load_config()
    return Path(cfg['second_brain']['vaults'][0])

def get_output_dir(lib_name: str) -> Path:
    d = get_vault_path() / "Technical Docs" / lib_name
    d.mkdir(parents=True, exist_ok=True)
    return d

def get_done_path() -> Path:
    d = PROJECT_ROOT / "20_web_digest" / "raw" / "docs_done"
    d.mkdir(parents=True, exist_ok=True)
    return d / "done.txt"

def load_done() -> set:
    p = get_done_path()
    return set(p.read_text().splitlines()) if p.exists() else set()

def mark_done(key: str):
    with open(get_done_path(), 'a') as f:
        f.write(key + "\n")

HEADERS = {"User-Agent": "loom/1.0 (personal research tool)"}


def fetch_doc_page(url: str) -> str:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Remove nav/sidebar/footer noise
        for tag in soup.find_all(['nav', 'header', 'footer', 'script',
                                   'style', 'aside']):
            tag.decompose()
        for tag in soup.find_all(class_=re.compile(r'sidebar|nav|menu|toc|breadcrumb')):
            tag.decompose()

        # Find main content
        main = (soup.find('main') or
                soup.find('article') or
                soup.find('div', class_=re.compile(r'content|main|doc')) or
                soup.find('div', role='main') or
                soup)

        text = main.get_text("\n", strip=True)
        text = re.sub(r'\n{4,}', '\n\n\n', text)
        return text[:30_000]

    except Exception as e:
        return f"[ERROR: {e}]"


def process_doc_source(key: str):
    if key not in DOC_SOURCES:
        print(f"  [WARN] Unknown doc source: {key}")
        return

    lib_name, pages = DOC_SOURCES[key]
    done    = load_done()
    out_dir = get_output_dir(lib_name)
    today   = datetime.now().strftime("%Y-%m-%d")

    print(f"\n── {lib_name} ({len(pages)} pages) ─────────────────────")

    for page_title, url in pages:
        page_key = f"{key}::{page_title}"
        if page_key in done:
            print(f"  SKIP: {page_title}")
            continue

        print(f"  Fetching: {page_title}")
        text = fetch_doc_page(url)

        if text.startswith("[ERROR"):
            print(f"    {text}")
            continue

        md = f"""# {lib_name}: {page_title}

**Source:** {url}
**Fetched:** {today}

---

{text}
"""
        safe = re.sub(r'[<>:"/\\|?*]', '', page_title)[:80]
        path = out_dir / f"{lib_name} - {safe}.md"
        path.write_text(md, encoding='utf-8')
        mark_done(page_key)
        print(f"    → {path.name}")
        time.sleep(DELAY)


def main():
    parser = argparse.ArgumentParser(description="Fetch technical documentation")
    parser.add_argument("--docs", nargs="+",
                        help="Doc sources to fetch (e.g. python neo4j fastapi)")
    parser.add_argument("--list", action="store_true", help="List available doc sources")
    parser.add_argument("--url",  type=str, help="Fetch a custom URL")
    parser.add_argument("--title",type=str, help="Title for custom URL", default="Custom Doc")
    args = parser.parse_args()

    if args.list:
        print("\nAvailable documentation sources:")
        for key, (name, pages) in DOC_SOURCES.items():
            print(f"  {key:<15} {name} ({len(pages)} pages)")
        sys.exit(0)

    if args.url:
        text = fetch_doc_page(args.url)
        md   = f"# {args.title}\n\n**URL:** {args.url}\n\n---\n\n{text}"
        safe = re.sub(r'[<>:"/\\|?*]', '', args.title)[:80]
        out  = get_vault_path() / "Technical Docs" / f"{safe}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding='utf-8')
        print(f"→ {out}")
        sys.exit(0)

    if not args.docs:
        parser.print_help()
        print("\nExamples:")
        print("  python docs_batch.py --list")
        print("  python docs_batch.py --docs python neo4j anthropic")
        print("  python docs_batch.py --docs all")
        sys.exit(0)

    keys = list(DOC_SOURCES.keys()) if "all" in args.docs else args.docs

    print(f"\n{'='*56}")
    print(f"  Docs Batch — Loom")
    print(f"{'='*56}")
    print(f"  Sources: {', '.join(keys)}\n")

    for key in keys:
        process_doc_source(key)

    print(f"\n  Output: {get_vault_path() / 'Technical Docs'}")


if __name__ == "__main__":
    main()
