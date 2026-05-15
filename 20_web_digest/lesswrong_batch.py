"""
LessWrong Batch — Productivity OS
Fetch posts from LessWrong using their public GraphQL API.

LessWrong is the highest-quality source for AI alignment, rationality,
decision theory, and epistemology. The API is free, no key needed.
Also works for the EA Forum (same codebase).

Usage:
    python lesswrong_batch.py --tag "AI" --limit 30
    python lesswrong_batch.py --tag "rationality" --limit 20
    python lesswrong_batch.py --curated --limit 50
    python lesswrong_batch.py --sequence "codex"
    python lesswrong_batch.py --topics topics/lesswrong_tags.txt
    python lesswrong_batch.py --url https://www.lesswrong.com/ea-forum  # EA Forum

Tags to try: AI, alignment, rationality, decision-theory, epistemology,
             forecasting, AI-safety, interpretability, agency, consciousness

Output: vault/LessWrong/YYYY-MM-DD {Title}.md
"""

import sys
import re
import time
import json
import argparse
from pathlib import Path
from datetime import datetime

try:
    import yaml
    import requests
except ImportError:
    print("[ERROR] pip install pyyaml requests")
    sys.exit(1)

PROJECT_ROOT  = Path(__file__).parent.parent
CONFIG_PATH   = PROJECT_ROOT / "config.yaml"
LW_API        = "https://www.lesswrong.com/graphql"
EA_API        = "https://forum.effectivealtruism.org/graphql"
DELAY         = 1.5

def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)

def get_vault_path() -> Path:
    cfg = load_config()
    return Path(cfg['second_brain']['vaults'][0])

def get_output_dir() -> Path:
    d = get_vault_path() / "LessWrong"
    d.mkdir(parents=True, exist_ok=True)
    return d

def get_done_path() -> Path:
    d = PROJECT_ROOT / "20_web_digest" / "raw" / "lw_done"
    d.mkdir(parents=True, exist_ok=True)
    return d / "done.txt"

def load_done() -> set:
    p = get_done_path()
    return set(p.read_text().splitlines()) if p.exists() else set()

def mark_done(post_id: str):
    with open(get_done_path(), 'a') as f:
        f.write(post_id + "\n")


POSTS_QUERY = """
query GetPosts($terms: JSON) {
  posts(input: { terms: $terms }) {
    results {
      _id
      title
      slug
      postedAt
      score
      commentCount
      wordCount
      tags { name }
      user { username displayName }
      contents { html plaintext }
    }
  }
}
"""

def fetch_posts(api_url: str, terms: dict) -> list[dict]:
    try:
        resp = requests.post(
            api_url,
            json={"query": POSTS_QUERY, "variables": {"terms": terms}},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("posts", {}).get("results", [])
    except Exception as e:
        print(f"  [ERROR] API request failed: {e}")
        return []


def post_to_markdown(post: dict) -> str:
    author = post.get("user", {})
    author_name = author.get("displayName") or author.get("username") or "Unknown"
    tags = ", ".join(t["name"] for t in post.get("tags", []))
    posted = post.get("postedAt", "")[:10]
    score = post.get("score", 0)
    comments = post.get("commentCount", 0)
    words = post.get("wordCount", 0)
    slug = post.get("slug", "")
    url = f"https://www.lesswrong.com/posts/{post['_id']}/{slug}"

    # Use plaintext if available, otherwise strip HTML
    content = post.get("contents", {})
    text = content.get("plaintext", "") if content else ""
    if not text:
        html = content.get("html", "") if content else ""
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text).strip()

    return f"""# {post['title']}

**Author:** {author_name}
**Posted:** {posted}
**Score:** {score}  |  **Comments:** {comments}  |  **Words:** {words}
**Tags:** {tags}
**URL:** {url}

---

{text}
"""


def process_posts(posts: list[dict], min_score: int = 10):
    if not posts:
        print("  No posts found.")
        return

    done    = load_done()
    out_dir = get_output_dir()
    total   = len(posts)
    success = skip = low_score = 0

    for i, post in enumerate(posts, 1):
        pid   = post.get("_id", "")
        title = post.get("title", "untitled")
        score = post.get("score", 0)

        print(f"  [{i}/{total}] {title[:65]}")

        if pid in done:
            skip += 1
            print(f"    SKIP (already done)")
            continue

        if score < min_score:
            low_score += 1
            print(f"    SKIP (score {score} < {min_score})")
            continue

        md = post_to_markdown(post)
        posted = post.get("postedAt", "")[:10] or datetime.now().strftime("%Y-%m-%d")
        safe   = re.sub(r'[<>:"/\\|?*]', '', title)[:100]
        path   = out_dir / f"{posted} {safe}.md"
        if path.exists():
            path = out_dir / f"{posted} {safe} [{pid[:6]}].md"

        path.write_text(md, encoding='utf-8')
        mark_done(pid)
        success += 1
        print(f"    → {path.name}")
        time.sleep(DELAY)

    print(f"\n  Saved: {success}  Skipped: {skip}  Low score: {low_score}")


def main():
    parser = argparse.ArgumentParser(description="Fetch LessWrong posts")
    parser.add_argument("--tag",      type=str, help="Tag/topic to fetch")
    parser.add_argument("--curated",  action="store_true", help="Fetch curated posts")
    parser.add_argument("--limit",    type=int, default=30)
    parser.add_argument("--min-score",type=int, default=20, help="Min karma score (default 20)")
    parser.add_argument("--ea-forum", action="store_true", help="Use EA Forum instead")
    parser.add_argument("--topics",   type=str, help="Text file with one tag per line")
    args = parser.parse_args()

    api = EA_API if args.ea_forum else LW_API
    source = "EA Forum" if args.ea_forum else "LessWrong"

    print(f"\n{'='*56}")
    print(f"  LessWrong Batch — {source}")
    print(f"{'='*56}\n")

    tags = []
    if args.tag:
        tags = [args.tag]
    if args.topics:
        p = Path(args.topics)
        if p.exists():
            tags = [l.strip() for l in p.read_text().splitlines()
                    if l.strip() and not l.startswith('#')]

    if args.curated or not tags:
        print("  Fetching curated posts...")
        terms = {"view": "curated", "limit": args.limit}
        posts = fetch_posts(api, terms)
        print(f"  Found: {len(posts)} posts\n")
        process_posts(posts, args.min_score)
    else:
        for tag in tags:
            print(f"\n── Tag: '{tag}' ──────────────────────────")
            terms = {"view": "tagRelevance", "tag": tag, "limit": args.limit}
            posts = fetch_posts(api, terms)
            print(f"  Found: {len(posts)} posts")
            process_posts(posts, args.min_score)
            time.sleep(DELAY)


if __name__ == "__main__":
    main()
