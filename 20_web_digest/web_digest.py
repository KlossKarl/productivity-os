#!/usr/bin/env python3
"""
web_digest.py — Web Content Digest
Loom — Project 20

Ingests HN threads, Reddit threads, or any article URL.
Analyzes with Claude Sonnet, writes rich Markdown to Obsidian vault.
Logs session to shared productivity DB.

Usage:
    python web_digest.py <URL> [max_comments]
    python web_digest.py <URL> [max_comments] --raw
    python web_digest.py https://news.ycombinator.com/item?id=12345678 600
    python web_digest.py https://reddit.com/r/MachineLearning/comments/xxx/title/
    python web_digest.py https://some-article.com/post

    --raw   Skip Claude API, dump scraped text to raw/ for Claude Code (free via Max).
"""

import re
import sys
import json
import sqlite3
import textwrap
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen, Request

try:
    import yaml
except ImportError:
    print("[ERROR] pyyaml not installed. Run: pip install pyyaml")
    sys.exit(1)

try:
    import anthropic
except ImportError:
    print("[ERROR] anthropic not installed. Run: pip install anthropic")
    sys.exit(1)


# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_PATH  = Path(__file__).parent.parent / "config.yaml"
ALGOLIA_HN   = "https://hn.algolia.com/api/v1/items"
REDDIT_API   = "https://www.reddit.com"

MODEL              = "claude-sonnet-4-6"
MAX_COMMENTS       = 400
ARTICLE_CHAR_LIMIT = 20000


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"[WARN] config.yaml not found at {CONFIG_PATH} — using defaults.")
        return {}
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f) or {}


def get_vault_path(cfg: dict) -> Path:
    vault = cfg.get("obsidian_vault") or r"C:\Users\Karl\Documents\Obsidian Vault"
    return Path(vault)


def get_db_path(cfg: dict) -> Path:
    db = cfg.get("db_path") or str(
        Path(__file__).parent.parent / "productivity_os.db"
    )
    return Path(db)


def get_api_key(cfg: dict) -> str:
    import os
    return (
        cfg.get("anthropic", {}).get("api_key")
        or os.environ.get("ANTHROPIC_API_KEY")
        or ""
    )


# ── Source detection ──────────────────────────────────────────────────────────

def detect_source(url: str) -> str:
    """Return 'hn', 'reddit', 'wikipedia', 'lobsters', or 'article'."""
    host = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()
    if "ycombinator.com" in host:
        return "hn"
    if "reddit.com" in host:
        return "reddit"
    if "wikipedia.org" in host:
        return "wikipedia"
    if "lobste.rs" in host:
        return "lobsters"
    return "article"


# ── HN fetcher ────────────────────────────────────────────────────────────────

def extract_hn_id(url: str) -> int:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "id" in qs:
        return int(qs["id"][0])
    m = re.search(r"/item/(\d+)", parsed.path)
    if m:
        return int(m.group(1))
    raise ValueError(f"Could not extract HN item ID from: {url}")


def fetch_hn_thread(item_id: int) -> dict:
    url = f"{ALGOLIA_HN}/{item_id}"
    req = Request(url, headers={"User-Agent": "web-digest/1.0"})
    with urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def render_hn_comments(children: list, depth: int = 0, budget: list = None) -> list:
    if budget is None:
        budget = [MAX_COMMENTS]
    lines = []
    for child in children:
        if budget[0] <= 0:
            break
        if child.get("type") != "comment":
            continue
        text   = clean_html(child.get("text") or "")
        author = child.get("author") or "[deleted]"
        if not text:
            continue
        lines.append(f"{'  ' * depth}**{author}:** {text}\n")
        budget[0] -= 1
        if child.get("children") and budget[0] > 0:
            lines.extend(render_hn_comments(child["children"], depth + 1, budget))
    return lines


def ingest_hn(url: str, max_comments: int):
    """Returns (meta, article_text, comments_text)."""
    item_id = extract_hn_id(url)
    print(f"Fetching HN thread {item_id} via Algolia...")
    story = fetch_hn_thread(item_id)

    title = story.get("title", "Unknown")
    print(f"  '{title}' by {story.get('author','?')} ({story.get('points') or 0} pts)")

    article_url  = story.get("url", "")
    article_text = fetch_article(article_url) if article_url else ""

    print(f"  Processing comments (up to {max_comments})...")
    budget        = [max_comments]
    comment_lines = render_hn_comments(story.get("children", []), budget=budget)
    comments_text = "\n".join(comment_lines)
    comment_count = max_comments - budget[0]
    print(f"  Got {comment_count} comments.")

    meta = {
        "title":      title,
        "source_url": article_url,
        "origin_url": f"https://news.ycombinator.com/item?id={item_id}",
        "author":     story.get("author", ""),
        "points":     story.get("points") or 0,
        "source_type": "hn_thread",
        "comment_count": comment_count,
    }
    return meta, article_text, comments_text


# ── Reddit fetcher ────────────────────────────────────────────────────────────

def ingest_reddit(url: str, max_comments: int):
    """Fetch Reddit thread via JSON API."""
    print(f"Fetching Reddit thread...")
    # Reddit's JSON API: append .json to thread URL
    clean = url.split("?")[0].rstrip("/")
    json_url = clean + ".json?limit=500&sort=top"
    req = Request(
        json_url,
        headers={"User-Agent": "web-digest/1.0 (personal knowledge base tool)"}
    )
    with urlopen(req, timeout=15) as r:
        data = json.loads(r.read())

    post    = data[0]["data"]["children"][0]["data"]
    title   = post.get("title", "Unknown")
    selftext = post.get("selftext", "")
    link_url = post.get("url", "")
    subreddit = post.get("subreddit", "")

    print(f"  r/{subreddit}: '{title}' ({post.get('score',0)} pts)")

    # Fetch linked article if not a self-post
    article_text = ""
    if link_url and not link_url.startswith("https://www.reddit.com"):
        article_text = fetch_article(link_url)

    # Flatten comments
    comment_nodes = data[1]["data"]["children"]
    lines  = []
    budget = [max_comments]

    def flatten(nodes, depth=0):
        for node in nodes:
            if budget[0] <= 0:
                return
            if node.get("kind") != "t1":
                continue
            d = node["data"]
            body   = d.get("body", "").strip()
            author = d.get("author", "[deleted]")
            if not body or body == "[deleted]" or body == "[removed]":
                continue
            lines.append(f"{'  ' * depth}**{author}:** {body}\n")
            budget[0] -= 1
            replies = d.get("replies")
            if replies and isinstance(replies, dict) and budget[0] > 0:
                flatten(replies["data"]["children"], depth + 1)

    flatten(comment_nodes)
    comment_count = max_comments - budget[0]
    print(f"  Got {comment_count} comments.")

    body_block = f"\n\n**Post body:**\n{selftext}" if selftext else ""
    comments_text = "\n".join(lines)

    meta = {
        "title":       title,
        "source_url":  link_url,
        "origin_url":  url,
        "author":      post.get("author", ""),
        "points":      post.get("score", 0),
        "source_type": "reddit_thread",
        "subreddit":   subreddit,
        "comment_count": comment_count,
        "post_body":   body_block,
    }
    return meta, article_text, comments_text



# ── Wikipedia fetcher ─────────────────────────────────────────────────────────

def extract_wiki_title(url: str) -> str:
    """Extract article title from Wikipedia URL."""
    path = urlparse(url).path
    # /wiki/Article_Title or /en/Article_Title
    parts = path.strip("/").split("/")
    title = parts[-1] if parts else ""
    return title.replace("_", " ")


def ingest_wikipedia(url: str):
    """Fetch Wikipedia article via the free REST API — clean, structured, no scraping needed."""
    title = extract_wiki_title(url)
    print(f"Fetching Wikipedia article: {title}...")

    # Use Wikipedia REST API for clean HTML extract
    lang = "en"
    host = urlparse(url).netloc.lower()
    if ".wikipedia.org" in host:
        lang = host.split(".")[0]

    api_url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}"
    req = Request(api_url, headers={"User-Agent": "web-digest/1.0"})

    try:
        with urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"  Summary API failed: {e}, falling back to article scraper...")
        return ingest_article(url)

    summary = data.get("extract", "")
    display_title = data.get("title", title)

    # Now get full article text via the mobile-html or parse endpoint
    full_url = f"https://{lang}.wikipedia.org/w/api.php?action=parse&page={title.replace(' ', '_')}&prop=text&format=json&formatversion=2"
    req2 = Request(full_url, headers={"User-Agent": "web-digest/1.0"})

    full_text = ""
    try:
        with urlopen(req2, timeout=20) as r:
            parse_data = json.loads(r.read())
        html = parse_data.get("parse", {}).get("text", "")
        if html:
            # Strip HTML same way as article fetcher
            for tag in ["script", "style", "nav", "footer", "aside",
                        "noscript", "figure", "form", "table", "sup"]:
                html = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", " ", html,
                              flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r"<(?:br|/p|/div|/li|/h[1-6]|/blockquote|/tr)\s*/?>",
                          "\n", html, flags=re.IGNORECASE)
            full_text = re.sub(r"<[^>]+>", "", html)
            for ent, char in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                               ("&quot;", '"'), ("&#x27;", "'"), ("&nbsp;", " "),
                               ("&#39;", "'"), ("&mdash;", "\u2014"), ("&ndash;", "\u2013")]:
                full_text = full_text.replace(ent, char)
            lines = [l.strip() for l in full_text.splitlines() if l.strip()]
            full_text = "\n\n".join(lines)
            full_text = re.sub(r"\n{3,}", "\n\n", full_text)
            if len(full_text) > ARTICLE_CHAR_LIMIT:
                full_text = (full_text[:ARTICLE_CHAR_LIMIT].rsplit("\n\n", 1)[0]
                            + "\n\n[... article truncated for length ...]")
    except Exception as e:
        print(f"  Full article fetch failed: {e}, using summary only.")
        full_text = summary

    print(f"  Wikipedia fetched ({len(full_text):,} chars).")

    meta = {
        "title":        display_title,
        "source_url":   url,
        "origin_url":   url,
        "author":       "Wikipedia contributors",
        "points":       0,
        "source_type":  "wikipedia",
        "comment_count": 0,
    }
    return meta, full_text, ""


# ── Lobsters fetcher ──────────────────────────────────────────────────────────

def ingest_lobsters(url: str, max_comments: int):
    """Fetch Lobsters thread via JSON API."""
    print(f"Fetching Lobsters thread...")
    clean = url.split("?")[0].rstrip("/")
    json_url = clean + ".json"
    req = Request(json_url, headers={"User-Agent": "web-digest/1.0"})

    with urlopen(req, timeout=15) as r:
        data = json.loads(r.read())

    title = data.get("title", "Unknown")
    story_url = data.get("url", "")
    author = data.get("submitter_user", {}).get("username", "") if isinstance(data.get("submitter_user"), dict) else data.get("submitter_user", "")

    print(f"  '{title}' by {author} ({data.get('score', 0)} pts)")

    article_text = fetch_article(story_url) if story_url and story_url != url else ""

    # Flatten comments
    lines = []
    budget = [max_comments]

    def flatten(comments, depth=0):
        for c in comments:
            if budget[0] <= 0:
                return
            body = c.get("comment_plain", "").strip()
            commenter = c.get("commenting_user", {}).get("username", "[deleted]") if isinstance(c.get("commenting_user"), dict) else c.get("commenting_user", "[deleted]")
            if not body:
                continue
            lines.append(f"{'  ' * depth}**{commenter}:** {body}\n")
            budget[0] -= 1
            if c.get("comments") and budget[0] > 0:
                flatten(c["comments"], depth + 1)

    flatten(data.get("comments", []))
    comment_count = max_comments - budget[0]
    print(f"  Got {comment_count} comments.")

    meta = {
        "title":        title,
        "source_url":   story_url,
        "origin_url":   url,
        "author":       author,
        "points":       data.get("score", 0),
        "source_type":  "lobsters_thread",
        "comment_count": comment_count,
    }
    return meta, article_text, "\n".join(lines)


# ── Article-only fetcher ──────────────────────────────────────────────────────

def ingest_article(url: str):
    """Just fetch and digest a standalone article — no comments."""
    print(f"Fetching article: {url[:80]}...")
    text = fetch_article(url)

    # Try to extract a title from the HTML
    title = url.split("/")[-1].replace("-", " ").replace("_", " ").title() or "Article"

    meta = {
        "title":       title,
        "source_url":  url,
        "origin_url":  url,
        "author":      "",
        "points":      0,
        "source_type": "article",
        "comment_count": 0,
    }
    return meta, text, ""


# ── Generic article scraper ───────────────────────────────────────────────────

def fetch_article(url: str) -> str:
    if not url:
        return ""
    try:
        print(f"  Fetching article: {url[:80]}...")
        req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; web-digest/1.0)"})
        with urlopen(req, timeout=15) as r:
            raw      = r.read()
            encoding = r.headers.get_content_charset() or "utf-8"

        html = raw.decode(encoding, errors="replace")

        for tag in ["script", "style", "nav", "footer", "header",
                    "aside", "noscript", "figure", "form"]:
            html = re.sub(rf"<{tag}[^>]*>.*?</{tag}>", " ", html,
                          flags=re.DOTALL | re.IGNORECASE)

        html = re.sub(r"<(?:br|/p|/div|/li|/h[1-6]|/blockquote|/tr)\s*/?>",
                      "\n", html, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", html)

        for ent, char in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                           ("&quot;", '"'), ("&#x27;", "'"), ("&nbsp;", " "),
                           ("&#39;", "'"), ("&mdash;", "—"), ("&ndash;", "–"),
                           ("&hellip;", "…"), ("&copy;", "©")]:
            text = text.replace(ent, char)

        lines = [l.strip() for l in text.splitlines() if l.strip()]
        text  = "\n\n".join(lines)
        text  = re.sub(r"\n{3,}", "\n\n", text)

        if len(text) > ARTICLE_CHAR_LIMIT:
            text = (text[:ARTICLE_CHAR_LIMIT].rsplit("\n\n", 1)[0]
                    + "\n\n[... article truncated for length ...]")

        print(f"  Article fetched ({len(text):,} chars).")
        return text.strip()

    except Exception as e:
        print(f"  Could not fetch article: {e}")
        return f"[Article could not be fetched: {e}]"


# ── HTML cleaner ──────────────────────────────────────────────────────────────

def clean_html(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<p>", "\n\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    for ent, char in [("&#x27;", "'"), ("&gt;", ">"), ("&lt;", "<"),
                      ("&amp;", "&"), ("&#x2F;", "/"), ("&quot;", '"'),
                      ("&nbsp;", " "), ("&#39;", "'")]:
        text = text.replace(ent, char)
    return text.strip()


# ── Claude analysis ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = textwrap.dedent("""
    You are an expert technical analyst and educator. Your job is to read web
    content — articles, discussion threads, comment sections — and produce a
    thorough, insightful Markdown document that a curious reader can use as a
    self-contained reference on the topic.

    Write with clarity and depth. Avoid filler. Prioritize insight over summary.
    The output will be indexed into a personal knowledge base / second brain,
    so structure it well with headers, lists, and code blocks where appropriate.

    If comments are present, mine them thoroughly — the best insights often come
    from deep in the thread, not just the top comments.
""").strip()


def build_prompt(meta: dict, article_text: str, comments_text: str) -> str:
    title      = meta.get("title", "")
    origin_url = meta.get("origin_url", "")
    source_url = meta.get("source_url", "")
    post_body  = meta.get("post_body", "")

    if article_text and not article_text.startswith("[Article could not"):
        article_block = f"## Article / Linked Content\n\n{article_text}"
    elif article_text.startswith("[Article could not"):
        article_block = f"## Article / Linked Content\n\n{article_text}\n\n(Analyze from title and comments.)"
    elif post_body:
        article_block = f"## Post Body\n\n{post_body}"
    else:
        article_block = "## Content\n\n[No article — self-post or direct discussion.]"

    comment_section = f"\n\n---\n\n## Comments ({meta.get('comment_count',0)} shown)\n\n{comments_text}" \
                      if comments_text else ""

    return f"""# Content to analyze

**Title:** {title}
**Origin:** {origin_url}
**Source:** {source_url}

---

{article_block}
{comment_section}

---

Please produce a Markdown document with these sections:

## 1. TL;DR
2-3 sentence executive summary.

## 2. Core Concept & Context
What is this actually about? Explain the central idea as if teaching someone
smart but unfamiliar. Include background, history, and why it matters now.

## 3. Content Breakdown
What is the author/poster arguing, demonstrating, or announcing?
What evidence do they use? What do they get right or wrong?

## 4. Key Arguments & Positions
Main stances, claims, or debates. Surface the strongest arguments
and the most interesting disagreements. Go wide across all perspectives.

## 5. Technical Deep Dive
Expand on the most technical or conceptually dense parts.
Include examples, pseudocode, or diagrams in ASCII where helpful.
Do not dumb it down.

## 6. Comment Highlights & Interconnections
The most insightful, surprising, or contrarian contributions.
How do different voices relate to each other and to the central idea?
Surface hidden gems buried deep in threads.

## 7. Broader Implications
What does this mean for the field, industry, or builders?
What questions does it open up?

## 8. Further Exploration
- Key terms, papers, or concepts worth researching
- Related resources and threads
- Open questions worth investigating

## 9. Tags
Generate a flat list of 5-10 specific, lowercase tags for this content.
These will be used to auto-categorize this document in a knowledge base.
Format exactly as: `tags: [tag1, tag2, tag3, ...]`
Be specific — not just "technology" but "graph-database" or "version-control".
Include: topic tags, technology tags, concept tags, and one domain tag
(e.g. ml, systems, security, web, devtools, science, history, economics).
""".strip()


# ── Output ────────────────────────────────────────────────────────────────────

def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text[:60].strip("-")


def write_digest(meta: dict, content: str, vault_path: Path) -> Path:
    """Write final MD to Obsidian vault under Web Digests/."""
    out_dir = vault_path / "Web Digests"
    out_dir.mkdir(parents=True, exist_ok=True)

    date  = datetime.now().strftime("%Y-%m-%d")
    slug  = slugify(meta.get("title", "digest"))
    fname = out_dir / f"{date}_{slug}.md"

    source_type = meta.get("source_type", "article")
    subreddit   = meta.get("subreddit", "")
    tag = source_type
    if subreddit:
        tag = f"reddit/{subreddit}"

    header = (
        f'---\n'
        f'title: "{meta.get("title","").replace(chr(34), chr(39))}"\n'
        f'origin_url: "{meta.get("origin_url","")}"\n'
        f'source_url: "{meta.get("source_url","")}"\n'
        f'author: "{meta.get("author","")}"\n'
        f'points: {meta.get("points", 0)}\n'
        f'comments: {meta.get("comment_count", 0)}\n'
        f'source_type: "{source_type}"\n'
        f'tags: [web-digest, {tag}]\n'
        f'date_analyzed: "{datetime.now().isoformat()}"\n'
        f'---\n\n'
    )

    fname.write_text(header + content, encoding="utf-8")
    return fname


def write_raw(meta: dict, article_text: str, comments_text: str) -> Path:
    """Dump raw content for Claude Code analysis (--raw mode)."""
    raw_dir = Path(__file__).parent / "raw"
    raw_dir.mkdir(exist_ok=True)
    date  = datetime.now().strftime("%Y-%m-%d")
    slug  = slugify(meta.get("title", "digest"))
    fname = raw_dir / f"{date}_{slug}.txt"

    prompt_hint = """INSTRUCTIONS FOR CLAUDE CODE:
Analyze the content below and produce a rich Markdown digest.
Sections: TL;DR, Core Concept & Context, Content Breakdown, Key Arguments,
Technical Deep Dive, Comment Highlights & Interconnections,
Broader Implications, Further Exploration.
Write with depth. Avoid filler. This goes into a personal knowledge base.
---
"""
    body = (
        f"{prompt_hint}\n"
        f"TITLE: {meta.get('title','')}\n"
        f"URL: {meta.get('origin_url','')}\n\n"
        f"--- ARTICLE CONTENT ---\n\n{article_text}\n\n"
        f"--- COMMENTS ---\n\n{comments_text}"
    )
    fname.write_text(body, encoding="utf-8")
    return fname


# ── SQLite logging ────────────────────────────────────────────────────────────

def log_to_db(db_path: Path, meta: dict, out_path: Path, cost: float):
    """Log this digest session to the shared productivity DB."""
    if not db_path.exists():
        return  # DB not set up yet, skip silently
    try:
        con = sqlite3.connect(db_path)
        cur = con.cursor()
        cur.execute("""
            INSERT INTO sessions
                (session_type, source, title, summary, artifact_path, cost_usd, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "web_digest",
            meta.get("source_type", "article"),
            meta.get("title", ""),
            f"{meta.get('comment_count',0)} comments | {meta.get('source_url','')}",
            str(out_path),
            round(cost, 6),
            datetime.now().isoformat(),
        ))
        con.commit()
        con.close()
    except Exception as e:
        print(f"  [WARN] Could not log to DB: {e}")


# ── Main ──────────────────────────────────────────────────────────────────────

def run_free_mode(raw_path: Path, out_path: Path, meta: dict, db_path: Path):
    """
    Shell out to Claude Code -p (print/non-interactive mode).
    Uses Max subscription — zero API cost.
    Embeds content directly in prompt to avoid file tool interactions.
    """
    import subprocess

    raw_content = raw_path.read_text(encoding="utf-8")

    prompt = (
        "Produce a detailed markdown digest of the following web content. "
        "Output ONLY the markdown document — no preamble, no commentary, "
        "no intro sentence, just raw markdown starting with the YAML frontmatter block. "
        "YAML frontmatter fields: title, origin_url, source_url, author, "
        "points, comments, source_type, tags, date_analyzed. "
        "Then write ALL 8 sections completely — no placeholders, no skipping: "
        "1. TL;DR (2-3 sentences), "
        "2. Core Concept & Context (deep explanation, history, why it matters now), "
        "3. Content Breakdown (what the author argues, evidence, what is right/wrong), "
        "4. Key Arguments & Positions (main debates, strongest arguments, disagreements), "
        "5. Technical Deep Dive (go deep, pseudocode or examples where helpful), "
        "6. Comment Highlights & Interconnections (best comments, how they connect), "
        "7. Broader Implications (what this means for the field and builders), "
        "8. Further Exploration (key terms, papers, resources, open questions), 9. Tags (generate 5-10 specific lowercase tags as: tags: [tag1, tag2, ...] — be specific: graph-database not technology, version-control not software). "
        "Depth and insight matter — this goes into a personal knowledge base. "
        "\n\n---CONTENT START---\n\n"
        + raw_content
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Running Claude Code -p (non-interactive, free via Max plan)...")
    print(f"  Input:  {raw_path}")
    print(f"  Output: {out_path}")

    claude_cmd = (
        r"C:\Users\Karl\AppData\Roaming\npm\claude.cmd"
        if sys.platform == "win32"
        else "claude"
    )

    # -p = print mode: non-interactive, outputs directly, no permission prompts
    cmd = [claude_cmd, "-p", "--output-format", "text"]

    try:
        # Encode as UTF-8 bytes — avoids Windows cp1252 errors with special chars
        import os as _os
        result = subprocess.run(
            cmd,
            input=prompt.encode("utf-8", errors="replace"),
            capture_output=True,
            timeout=600,
            env={**_os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
        stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""

        if result.returncode != 0:
            print(f"[ERROR] Claude Code failed:\n{stderr}")
            print(f"\nFallback — run manually:\n  {cmd} > \"{out_path}\"")
            return

        content = stdout.strip()
        if not content:
            print("[ERROR] Claude Code returned empty output.")
            print(f"\nFallback — run manually:\n  {cmd} > \"{out_path}\"")
            return

        out_path.write_text(content, encoding="utf-8")
        print(f"\nSaved to vault: {out_path}")
        log_to_db(db_path, meta, out_path, 0.0)
        print(f"Run 'python second_brain.py --index' to make it queryable.\n")

    except subprocess.TimeoutExpired:
        print("[ERROR] Claude Code timed out after 5 minutes.")
        print(f"Try running manually:\n  {cmd} > \"{out_path}\"")
    except FileNotFoundError:
        print("[ERROR] 'claude' command not found.")
        print("Make sure Claude Code is installed: npm install -g @anthropic-ai/claude-code")
        print(f"\nOr use the paid API mode (drop --free flag).")


def main():
    if len(sys.argv) < 2:
        print("Usage: python web_digest.py <URL> [max_comments] [--free | --raw]")
        print()
        print("  HN:      python web_digest.py https://news.ycombinator.com/item?id=12345678 600")
        print("  Reddit:  python web_digest.py https://reddit.com/r/MachineLearning/comments/xxx/")
        print("  Article: python web_digest.py https://example.com/some-article")
        print()
        print("  --free   Use Claude Code (Max plan) — fully automatic, zero API cost")
        print("  --raw    Dump raw file + print Claude Code command (manual paste)")
        sys.exit(1)

    args         = sys.argv[1:]
    raw_mode     = "--raw"  in args
    free_mode    = "--free" in args
    args         = [a for a in args if a not in ("--raw", "--free")]
    url          = args[0]
    max_comments = int(args[1]) if len(args) > 1 else MAX_COMMENTS

    cfg        = load_config()
    vault_path = get_vault_path(cfg)
    db_path    = get_db_path(cfg)
    api_key    = get_api_key(cfg)

    # Route to correct ingester
    source = detect_source(url)
    print(f"\nSource type: {source.upper()}")

    if source == "hn":
        meta, article_text, comments_text = ingest_hn(url, max_comments)
    elif source == "reddit":
        meta, article_text, comments_text = ingest_reddit(url, max_comments)
    elif source == "wikipedia":
        meta, article_text, comments_text = ingest_wikipedia(url)
    elif source == "lobsters":
        meta, article_text, comments_text = ingest_lobsters(url, max_comments)
    else:
        meta, article_text, comments_text = ingest_article(url)

    # Raw mode — dump for manual Claude Code
    if raw_mode:
        raw_path = write_raw(meta, article_text, comments_text)
        digest_slug = slugify(meta.get("title","digest"))
        out_dir  = vault_path / "Web Digests"
        out_dir.mkdir(parents=True, exist_ok=True)
        date     = datetime.now().strftime("%Y-%m-%d")
        out_md   = out_dir / f"{date}_{digest_slug}.md"
        print(f"\nRaw file: {raw_path}")
        print(f"\nRun Claude Code:")
        print(f'  claude "Read this file and produce a detailed markdown digest. '
              f'Sections: TL;DR, Core Concept, Content Breakdown, Key Arguments, '
              f'Technical Deep Dive, Comment Highlights, Broader Implications, '
              f'Further Exploration." "{raw_path}" > "{out_md}"')
        return

    # Free mode — auto Claude Code, no API cost
    if free_mode:
        raw_path    = write_raw(meta, article_text, comments_text)
        digest_slug = slugify(meta.get("title", "digest"))
        out_dir     = vault_path / "Web Digests"
        date        = datetime.now().strftime("%Y-%m-%d")
        out_md      = out_dir / f"{date}_{digest_slug}.md"
        run_free_mode(raw_path, out_md, meta, db_path)
        return

    # Analyze with Claude
    if not api_key:
        print("[ERROR] No Anthropic API key found in config.yaml or ANTHROPIC_API_KEY env var.")
        sys.exit(1)

    print(f"Analyzing with {MODEL}...")
    client  = anthropic.Anthropic(api_key=api_key)
    prompt  = build_prompt(meta, article_text, comments_text)

    message = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    content = message.content[0].text

    usage       = message.usage
    input_cost  = (usage.input_tokens  / 1_000_000) * 3.00
    output_cost = (usage.output_tokens / 1_000_000) * 15.00
    total_cost  = input_cost + output_cost
    print(f"  Tokens: {usage.input_tokens:,} in / {usage.output_tokens:,} out "
          f"— cost: ${total_cost:.4f}")

    # Write to vault
    out_path = write_digest(meta, content, vault_path)
    print(f"\nSaved to vault: {out_path}")

    # Log to shared DB
    log_to_db(db_path, meta, out_path, total_cost)

    print(f"Run 'python second_brain.py --index' to make it queryable.\n")


if __name__ == "__main__":
    main()
