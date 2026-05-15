"""
Obsidian Second Brain
Karl's Productivity OS - Project 8

Indexes your Obsidian vault + selected codebases into ChromaDB.
Chat with all of it — pick Claude or any local Ollama model interactively.

Usage:
    python second_brain.py --index               # index new/changed files only (fast after first run)
    python second_brain.py --index --force       # force re-index everything + clear checkpoint
    python second_brain.py --chat                # start chat with interactive model picker
    python second_brain.py --chat --model claude-haiku   # skip picker, go straight in
    python second_brain.py --chat --model llama3:8b      # skip picker, use local model
    python second_brain.py --index --chat        # index then chat
    python second_brain.py --search "query"
    python second_brain.py --stats
"""

import os
import sys
import json
import re
import sqlite3
import argparse
import requests
from pathlib import Path
from datetime import datetime

try:
    import yaml
except ImportError:
    print("[ERROR] pyyaml not installed. Run: pip install pyyaml")
    sys.exit(1)

try:
    import chromadb
except ImportError:
    print("[ERROR] chromadb not installed. Run: pip install chromadb")
    sys.exit(1)

try:
    from neo4j import GraphDatabase as _Neo4jDriver
    NEO4J_AVAILABLE = True
except ImportError:
    NEO4J_AVAILABLE = False
    print("[WARN] neo4j not installed — graph features disabled. Run: pip install neo4j")

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

CONFIG_PATH      = Path(__file__).parent.parent / "config.yaml"  # repo root
OLLAMA_URL       = "http://localhost:11434/api/generate"
OLLAMA_EMBED_URL = "http://localhost:11434/api/embeddings"
OLLAMA_TAGS_URL  = "http://localhost:11434/api/tags"
ANTHROPIC_URL    = "https://api.anthropic.com/v1/messages"

# Claude model shorthands — what you type → actual model string
CLAUDE_MODELS = {
    "claude-haiku":  "claude-haiku-4-5-20251001",
    "claude-sonnet": "claude-sonnet-4-6",
    "claude-opus":   "claude-opus-4-6",
    # also accept full strings directly
    "claude-haiku-4-5-20251001": "claude-haiku-4-5-20251001",
    "claude-sonnet-4-6":         "claude-sonnet-4-6",
    "claude-opus-4-6":           "claude-opus-4-6",
}

def is_claude(model: str) -> bool:
    return "claude" in model.lower()

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"[ERROR] config.yaml not found. Run: python setup.py")
        sys.exit(1)
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)

def get_chroma_dir() -> Path:
    cfg = load_config()
    return Path(cfg['paths']['chroma_dir'])

def get_user_name() -> str:
    cfg = load_config()
    return cfg.get('user', {}).get('name', 'User')

def get_anthropic_key() -> str:
    cfg = load_config()
    return cfg.get('anthropic', {}).get('api_key', '') or os.environ.get('ANTHROPIC_API_KEY', '')

# ─────────────────────────────────────────────
# CHECKPOINT DB
# ─────────────────────────────────────────────
# Replaces the broken collection.get() skip logic.
# Writes one row per file after successful indexing.
# On next --index run, checks this table first — instant, never fails silently.
# Lives at: <chroma_dir>/index_checkpoint.db

def _checkpoint_path() -> Path:
    return get_chroma_dir() / "index_checkpoint.db"

def _checkpoint_conn():
    db = _checkpoint_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS indexed_files (
            file_id     TEXT PRIMARY KEY,
            mtime       REAL NOT NULL,
            chunks      INTEGER,
            indexed_at  TEXT
        )
    """)
    conn.commit()
    return conn

def _load_checkpoint() -> dict:
    """Returns {file_id: mtime} for all successfully indexed files."""
    try:
        conn = _checkpoint_conn()
        rows = conn.execute("SELECT file_id, mtime FROM indexed_files").fetchall()
        conn.close()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}

def _save_checkpoint(file_id: str, mtime: float, chunks: int):
    """Call this only after collection.add() succeeds."""
    try:
        conn = _checkpoint_conn()
        conn.execute(
            "INSERT OR REPLACE INTO indexed_files (file_id, mtime, chunks, indexed_at) VALUES (?,?,?,?)",
            (file_id, mtime, chunks, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"\n  [WARN] Checkpoint write failed: {e}")

def _clear_checkpoint():
    """Wipe all checkpoints — used with --force."""
    try:
        conn = _checkpoint_conn()
        conn.execute("DELETE FROM indexed_files")
        conn.commit()
        conn.close()
    except Exception:
        pass

# ─────────────────────────────────────────────
# MODEL DISCOVERY + PICKER
# ─────────────────────────────────────────────

def get_ollama_models() -> list[str]:
    """Fetch list of pulled models from Ollama."""
    try:
        resp = requests.get(OLLAMA_TAGS_URL, timeout=5)
        resp.raise_for_status()
        return sorted([m['name'] for m in resp.json().get('models', [])])
    except Exception:
        return []

def pick_model_interactively(current_model: str = None) -> str:
    """
    Show a numbered list of all available models (Claude + Ollama)
    and let the user pick. Returns the selected model string.
    """
    cfg = load_config()
    sb = cfg.get('second_brain', cfg)
    default_model = current_model or sb.get('chat_model', 'deepseek-r1:14b')
    has_key = bool(get_anthropic_key())

    options = []

    # Claude options (only if API key is configured)
    if has_key:
        options.append(("claude-haiku-4-5-20251001", "Claude Haiku   — fast, cheap  (~$0.002/query)  ☁"))
        options.append(("claude-sonnet-4-6",          "Claude Sonnet  — smart, great (~$0.02/query)   ☁"))
        options.append(("claude-opus-4-6",            "Claude Opus    — best, costly (~$0.15/query)   ☁"))
    else:
        print("  [No Anthropic API key found — Claude options unavailable]")

    # Local Ollama models
    ollama_models = get_ollama_models()
    if ollama_models:
        for m in ollama_models:
            options.append((m, f"{m:<40} 🖥  local"))
    else:
        print("  [Ollama not running or no models pulled — local options unavailable]")

    if not options:
        print("[ERROR] No models available. Check Ollama is running and/or API key is set.")
        sys.exit(1)

    print(f"  {'─'*56}")
    print(f"  Choose a model:")
    print(f"  {'─'*56}")
    for i, (model_id, label) in enumerate(options, 1):
        is_default = (model_id == default_model or
                      model_id.split(':')[0] == default_model.split(':')[0])
        marker = "  ◀ default" if is_default else ""
        print(f"  {i:>2}. {label}{marker}")
    print(f"  {'─'*56}")
    print(f"  Press Enter to use default ({default_model})")
    print()

    while True:
        try:
            raw = input(f"  Select [1-{len(options)}]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            sys.exit(0)

        if raw == "":
            return default_model
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return options[idx][0]
        print(f"  Please enter a number between 1 and {len(options)}")

# ─────────────────────────────────────────────
# CHROMADB
# ─────────────────────────────────────────────

def get_collection():
    chroma_dir = get_chroma_dir()
    chroma_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_dir))
    return client.get_or_create_collection(
        name="second_brain",
        metadata={"hnsw:space": "cosine"}
    )

# ─────────────────────────────────────────────
# EMBEDDING
# ─────────────────────────────────────────────

def embed(text: str, model: str, retries: int = 3) -> list:
    """Embed text with retry logic and exponential backoff. Raises on total failure."""
    import time
    for attempt in range(retries):
        try:
            resp = requests.post(
                OLLAMA_EMBED_URL,
                json={"model": model, "prompt": text},
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()["embedding"]
        except Exception as e:
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"\n  [embed] Attempt {attempt+1} failed ({e}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise

# ─────────────────────────────────────────────
# CHUNKING
# ─────────────────────────────────────────────

def chunk_text(text: str, chunk_size: int, overlap: int) -> list:
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    if len(text) <= chunk_size:
        return [text] if text else []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end < len(text):
            para_break = text.rfind('\n\n', start, end)
            if para_break > start + chunk_size // 2:
                end = para_break
            else:
                sent_break = max(
                    text.rfind('. ', start, end),
                    text.rfind('? ', start, end),
                )
                if sent_break > start + chunk_size // 2:
                    end = sent_break + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end - overlap
    return chunks

def strip_frontmatter(text: str):
    metadata = {}
    if text.startswith('---'):
        end = text.find('---', 3)
        if end != -1:
            for line in text[3:end].strip().split('\n'):
                if ':' in line:
                    key, _, val = line.partition(':')
                    metadata[key.strip()] = val.strip()
            return metadata, text[end+3:].strip()
    return metadata, text

# ─────────────────────────────────────────────
# FILE COLLECTION
# ─────────────────────────────────────────────

def collect_files(cfg: dict) -> list:
    files = []
    sb = cfg.get('second_brain', cfg)
    skip_folders = set(sb.get('skip_folders', []))
    code_extensions = set(sb.get('code_extensions', ['.py', '.md', '.js', '.ts']))

    for vault_path in sb.get('vaults', []):
        vault = Path(vault_path)
        if not vault.exists():
            print(f"  [WARN] Vault not found: {vault}")
            continue
        for ext in ['.md', '.txt']:
            for f in vault.rglob(f"*{ext}"):
                if any(s in f.parts for s in skip_folders):
                    continue
                files.append((f, 'note', vault.name, vault))

    for repo_path in sb.get('codebases', []):
        repo = Path(repo_path)
        if not repo.exists():
            print(f"  [WARN] Repo not found: {repo}")
            continue
        for ext in code_extensions:
            for f in repo.rglob(f"*{ext}"):
                if any(s in f.parts for s in skip_folders):
                    continue
                files.append((f, 'code', repo.name, repo))

    seen, unique = set(), []
    for item in files:
        if item[0] not in seen:
            seen.add(item[0])
            unique.append(item)
    return unique

# ─────────────────────────────────────────────
# INDEXING
# ─────────────────────────────────────────────

def index_all(force: bool = False):
    cfg = load_config()
    collection = get_collection()
    sb = cfg.get('second_brain', cfg)
    embed_model = sb.get('embed_model', 'mxbai-embed-large')

    # ── Content-aware chunking ──────────────────────────────────────────────
    # Notes/papers need larger chunks — academic arguments span paragraphs.
    # Code needs even larger chunks — explanations need surrounding context.
    # These can be overridden per-type in config.yaml if needed.
    chunk_size_notes = sb.get('chunk_size_notes', sb.get('chunk_size', 1200))
    chunk_size_code  = sb.get('chunk_size_code',  sb.get('chunk_size', 1600))
    chunk_overlap_notes = sb.get('chunk_overlap_notes', sb.get('chunk_overlap', 200))
    chunk_overlap_code  = sb.get('chunk_overlap_code',  sb.get('chunk_overlap', 300))

    files = collect_files(cfg)
    print(f"\n[INDEX] Found {len(files)} files across vault + codebases")

    if force:
        print("[INDEX] --force: clearing checkpoint, re-indexing everything")
        _clear_checkpoint()

    # Load checkpoint — {file_id: mtime} for every previously indexed file
    checkpoint = _load_checkpoint()
    print(f"[INDEX] Checkpoint: {len(checkpoint)} files already indexed")

    indexed = skipped = total_chunks = 0

    for i, (filepath, source_type, repo_name, base_path) in enumerate(files):
        try:
            content = filepath.read_text(encoding='utf-8', errors='ignore')
            if not content.strip():
                continue

            mtime = filepath.stat().st_mtime
            try:
                rel = str(filepath.relative_to(base_path)).replace('\\', '/')
            except ValueError:
                rel = filepath.name

            file_id = f"{repo_name}/{rel}"

            # ── Skip check — compare mtime against checkpoint ──
            if not force and checkpoint.get(file_id) == mtime:
                skipped += 1
                continue

            # Delete old chunks for this file from ChromaDB before re-indexing
            try:
                old = collection.get(where={"file_id": file_id})
                if old['ids']:
                    collection.delete(ids=old['ids'])
            except Exception:
                pass

            frontmatter = {}
            if source_type == 'note':
                frontmatter, content = strip_frontmatter(content)
            else:
                content = f"# File: {filepath.name}\n# Repo: {repo_name}\n# Path: {rel}\n\n{content}"

            chunk_size   = chunk_size_code   if source_type == 'code' else chunk_size_notes
            chunk_overlap = chunk_overlap_code if source_type == 'code' else chunk_overlap_notes
            chunks = chunk_text(content, chunk_size, chunk_overlap)
            if not chunks:
                continue

            # Cap chunks per file — prevents OOM on giant PDFs (textbooks, long reports)
            # References/appendices at the tail are dropped; core content is preserved
            max_chunks = sb.get('max_chunks_per_file', 200)
            if len(chunks) > max_chunks:
                print(f"\n  [{i+1}/{len(files)}] [{source_type.upper()}] {filepath.name:<40} {len(chunks)} chunks → capped at {max_chunks}")
                chunks = chunks[:max_chunks]
            elif len(chunks) > 100:
                print(f"\n  [{i+1}/{len(files)}] [{source_type.upper()}] {filepath.name:<40} {len(chunks)} chunks (large file, may take a minute...)")
            else:
                print(f"  [{i+1}/{len(files)}] [{source_type.upper()}] {filepath.name:<40} {len(chunks)} chunks", end='\r')

            ids, embeddings, documents, metadatas = [], [], [], []
            for j, chunk in enumerate(chunks):
                chunk_id = f"{file_id}::{mtime}::{j}"
                try:
                    if j > 0:
                        import time; time.sleep(0.15)  # throttle — prevents Ollama 500s on rapid-fire requests
                    embedding = embed(chunk, embed_model)
                except Exception:
                    continue
                ids.append(chunk_id)
                embeddings.append(embedding)
                documents.append(chunk)
                metadatas.append({
                    "file_id": file_id,
                    "filename": filepath.stem,
                    "source_type": source_type,
                    "repo": repo_name,
                    "extension": filepath.suffix,
                    "chunk": j,
                    "mtime": mtime,
                    "date": frontmatter.get("date", ""),
                    "type": frontmatter.get("type", source_type),
                })

            if ids:
                collection.add(ids=ids, embeddings=embeddings,
                               documents=documents, metadatas=metadatas)
                total_chunks += len(ids)
                indexed += 1
                # ── Write checkpoint ONLY after successful add ──
                _save_checkpoint(file_id, mtime, len(ids))

        except Exception as e:
            print(f"\n  [ERROR] {filepath.name}: {e}")

    print(f"\n\n[INDEX] Complete")
    print(f"  Files indexed:  {indexed}")
    print(f"  Files skipped:  {skipped} (unchanged)")
    print(f"  Total chunks:   {total_chunks}")

def show_stats():
    cfg = load_config()
    sb = cfg.get('second_brain', cfg)
    collection = get_collection()
    count = collection.count()
    try:
        notes = len(collection.get(where={"source_type": "note"})['ids'])
        code  = len(collection.get(where={"source_type": "code"})['ids'])
    except Exception:
        notes = code = 0

    checkpoint = _load_checkpoint()

    print(f"\n  Second Brain Stats")
    print(f"  {'─'*40}")
    print(f"  Total chunks:     {count}")
    print(f"  Note chunks:      {notes}")
    print(f"  Code chunks:      {code}")
    print(f"  Checkpointed:     {len(checkpoint)} files")
    print(f"  Embed model:      {sb.get('embed_model', 'mxbai-embed-large')}")
    print(f"  Chat model:       {sb.get('chat_model', 'deepseek-r1:14b')}")
    print(f"  HyDE:             {'on' if sb.get('hyde', True) else 'off'}")
    print(f"  Query expansion:  {'on' if sb.get('query_expansion', True) else 'off'}")
    print(f"  Reranking:        {'on' if sb.get('rerank', True) else 'off'}")
    print(f"  DB:               {get_chroma_dir()}")

    # Graph stats (only if Neo4j is available and graph is enabled)
    if NEO4J_AVAILABLE and sb.get('graph', False):
        try:
            driver = _get_neo4j_driver()
            with driver.session() as s:
                n_docs     = s.run("MATCH (d:Document) RETURN count(d) AS n").single()["n"]
                n_chunks   = s.run("MATCH (c:Chunk)    RETURN count(c) AS n").single()["n"]
                n_entities = s.run("MATCH (e:Entity)   RETURN count(e) AS n").single()["n"]
                n_aliases  = s.run("MATCH (a:Alias)    RETURN count(a) AS n").single()["n"]
                n_edges    = s.run("MATCH ()-[r]->()   RETURN count(r) AS n").single()["n"]
            driver.close()
            print(f"\n  Graph (Neo4j v2 schema):")
            print(f"  {'─'*40}")
            print(f"  Documents:        {n_docs}")
            print(f"  Chunks:           {n_chunks}")
            print(f"  Entities:         {n_entities}")
            print(f"  Aliases:          {n_aliases}")
            print(f"  Total edges:      {n_edges}")
        except Exception as e:
            print(f"\n  Graph:            unavailable ({e})")


# ─────────────────────────────────────────────
# NEO4J — KNOWLEDGE GRAPH LAYER
#
# Sits alongside ChromaDB. Vector store handles semantic similarity.
# Graph store handles relationships, entity connections, cross-document
# traversal. The agentic retriever decides which to use per query.
#
# Graph schema v2:
#   (:Document {id, filename, source_type, date})
#   (:Chunk    {id, text, chunk_index, file_id, mtime})
#   (:Entity   {canonical_key, canonical_name, type})
#   (:Alias    {value})
#
#   (Document)-[:HAS_CHUNK]       ->(Chunk)
#   (Chunk)   -[:PART_OF]         ->(Document)
#   (Chunk)   -[:MENTIONS]        ->(Entity)
#   (Entity)  -[:HAS_ALIAS]       ->(Alias)
#   (Entity)  -[:CO_OCCURS_WITH {count, window}]->(Entity)
#   (Entity)  -[:CITES]           ->(Entity)
#   (Entity)  -[:INFLUENCES]      ->(Entity)
#   (Entity)  -[:EXTENDS]         ->(Entity)
#   (Entity)  -[:CONTRASTS_WITH]  ->(Entity)
#   (Entity)  -[:POSSIBLY_SAME_AS]->(Entity)
#   (Document)-[:REFERS_TO]       ->(Document)
# ─────────────────────────────────────────────

def _get_neo4j_creds() -> tuple[str, str, str]:
    """Read Neo4j connection info from config.yaml — never hardcoded."""
    cfg = load_config()
    sb  = cfg.get('second_brain', cfg)
    uri  = sb.get('neo4j_uri',      'neo4j://127.0.0.1:7687')
    user = sb.get('neo4j_user',     'neo4j')
    pw   = sb.get('neo4j_password', '') or os.environ.get('NEO4J_PASSWORD', '')
    return uri, user, pw


def _get_neo4j_driver():
    if not NEO4J_AVAILABLE:
        raise RuntimeError("neo4j package not installed. Run: pip install neo4j")
    uri, user, pw = _get_neo4j_creds()
    return _Neo4jDriver.driver(uri, auth=(user, pw))


def _neo4j_setup(driver):
    """
    Create constraints and indexes for graph schema v2.

    Node types:
      Document  {id, filename, source_type, date}
      Chunk     {id, text, chunk_index, file_id, mtime}
      Entity    {canonical_key, canonical_name, type}
      Alias     {value}

    Edge types:
      (Document)-[:HAS_CHUNK]       ->(Chunk)
      (Chunk)   -[:PART_OF]         ->(Document)
      (Chunk)   -[:MENTIONS]        ->(Entity)
      (Entity)  -[:HAS_ALIAS]       ->(Alias)
      (Entity)  -[:CO_OCCURS_WITH {count, window}]->(Entity)
      (Entity)  -[:CITES]           ->(Entity)
      (Entity)  -[:INFLUENCES]      ->(Entity)
      (Entity)  -[:EXTENDS]         ->(Entity)
      (Entity)  -[:CONTRASTS_WITH]  ->(Entity)
      (Entity)  -[:POSSIBLY_SAME_AS]->(Entity)
      (Document)-[:REFERS_TO]       ->(Document)
    """
    with driver.session() as s:
        # Node uniqueness constraints
        s.run("CREATE CONSTRAINT doc_id      IF NOT EXISTS FOR (d:Document) REQUIRE d.id            IS UNIQUE")
        s.run("CREATE CONSTRAINT chunk_id    IF NOT EXISTS FOR (c:Chunk)    REQUIRE c.id            IS UNIQUE")
        # canonical_key replaces the old name constraint — normalised for dedup
        s.run("CREATE CONSTRAINT entity_ckey IF NOT EXISTS FOR (e:Entity)   REQUIRE e.canonical_key IS UNIQUE")
        s.run("CREATE CONSTRAINT alias_value IF NOT EXISTS FOR (a:Alias)    REQUIRE a.value         IS UNIQUE")
        # Indexes for common traversals
        s.run("CREATE INDEX entity_type  IF NOT EXISTS FOR (e:Entity)  ON (e.type)")
        s.run("CREATE INDEX chunk_file   IF NOT EXISTS FOR (c:Chunk)   ON (c.file_id)")
        s.run("CREATE INDEX doc_source   IF NOT EXISTS FOR (d:Document) ON (d.source_type)")


def _extract_entities(text: str, filename: str, model: str,
                      entity_types: list = None) -> dict:
    """
    Use LLM to extract named entities and typed relationships from a text chunk.

    Entity types are configurable via config.yaml → second_brain.entity_types.
    Defaults: Person | Concept | Method | Paper | Organization | Dataset | Tool | Event

    Relationship types (typed, not freeform):
      CITES           — one work formally references another
      INFLUENCES      — one concept/person shaped another
      EXTENDS         — one method/concept builds on another
      CONTRASTS_WITH  — ideas are in opposition or compete
      POSSIBLY_SAME_AS — uncertain whether two names refer to the same thing
    """
    _default_types = ["Person", "Concept", "Method", "Paper",
                      "Organization", "Dataset", "Tool", "Event"]
    types = entity_types or _default_types
    type_str = "|".join(types)

    prompt = f"""Extract named entities and typed relationships from this text excerpt.
Source document: {filename}

Text: {text[:1500]}

Return ONLY a JSON object, no markdown, no explanation:
{{
  "entities": [
    {{"name": "canonical entity name", "type": "{type_str}"}}
  ],
  "relationships": [
    {{"from": "entity1", "to": "entity2", "type": "CITES|INFLUENCES|EXTENDS|CONTRASTS_WITH|POSSIBLY_SAME_AS"}}
  ]
}}

Rules:
- Use the most canonical form of each name (e.g. "PAC learning" not "pac learning" or "PAC-learning")
- Only extract entities clearly present in the text
- Relationships must use two entities from your entities list
- Use POSSIBLY_SAME_AS when you're not sure two names are truly different entities
- Max 8 entities, max 6 relationships per chunk
- If nothing clear, return {{"entities": [], "relationships": []}}"""

    try:
        if is_claude(model):
            api_key = get_anthropic_key()
            resp = requests.post(
                ANTHROPIC_URL,
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": model, "max_tokens": 500, "messages": [{"role": "user", "content": prompt}]},
                timeout=20,
            )
            raw = resp.json()["content"][0]["text"].strip()
        else:
            resp = requests.post(
                OLLAMA_URL,
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=30,
            )
            raw = resp.json().get("response", "").strip()

        raw = re.sub(r"```json\s*|```\s*", "", raw)
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    except Exception:
        pass
    return {"entities": [], "relationships": []}


def _canonical_key(name: str) -> str:
    """
    Normalize an entity name to a stable lookup key.
    Lowercases, strips punctuation, collapses hyphens/spaces → single space.
    "PAC-learning" and "PAC learning" and "pac learning" all → "pac learning".
    This is the deduplication key — NOT the display name.
    """
    key = name.lower()
    key = re.sub(r'[-_]+', ' ', key)          # hyphens/underscores → space
    key = re.sub(r'[^\w\s]', '', key)          # strip remaining punctuation
    key = re.sub(r'\s+', ' ', key).strip()     # collapse whitespace
    return key


# Typed relationship labels allowed in the graph.
# Any LLM response not in this set falls back to POSSIBLY_SAME_AS.
_VALID_REL_TYPES = {"CITES", "INFLUENCES", "EXTENDS", "CONTRASTS_WITH", "POSSIBLY_SAME_AS"}


def _write_to_graph(driver, doc_id: str, filename: str, source_type: str,
                    date: str, entities: list, relationships: list,
                    chunk_idx: int, chunk_text: str = "", chunk_mtime: float = 0.0):
    """
    Write extracted entities and relationships into Neo4j using schema v2.

    Creates / merges:
      - Document node (upserted by doc_id)
      - Chunk node (upserted by chunk id = doc_id::chunk_idx)
      - HAS_CHUNK / PART_OF edges between Document and Chunk
      - Entity nodes keyed by canonical_key (not raw name → prevents fragmentation)
      - Alias node for the raw surface form, linked via HAS_ALIAS
      - Chunk -[:MENTIONS]-> Entity edges
      - CO_OCCURS_WITH edges between all entities mentioned in the same chunk
      - Typed relationship edges (CITES / INFLUENCES / EXTENDS / etc.)
    """
    chunk_id = f"{doc_id}::{chunk_idx}"

    with driver.session() as s:
        # ── Document node ────────────────────────────────────────────────
        s.run(
            "MERGE (d:Document {id: $id}) "
            "SET d.filename = $filename, d.source_type = $source_type, d.date = $date",
            id=doc_id, filename=filename, source_type=source_type, date=date,
        )

        # ── Chunk node + Document↔Chunk edges ───────────────────────────
        s.run(
            "MERGE (c:Chunk {id: $cid}) "
            "SET c.chunk_index = $idx, c.file_id = $fid, c.mtime = $mtime, c.text = $text",
            cid=chunk_id, idx=chunk_idx, fid=doc_id, mtime=chunk_mtime,
            text=chunk_text[:500],   # store a preview, not the full chunk
        )
        s.run(
            "MATCH (d:Document {id: $did}), (c:Chunk {id: $cid}) "
            "MERGE (d)-[:HAS_CHUNK]->(c) "
            "MERGE (c)-[:PART_OF]->(d)",
            did=doc_id, cid=chunk_id,
        )

        # ── Entity upsert with Alias handling ───────────────────────────
        # canonical_key is the stable dedup key; canonical_name is best display form.
        # On first encounter we set canonical_name = raw surface form.
        # On subsequent encounters we keep whichever was stored first (no overwrite).
        written_entities = []   # canonical_keys successfully written this chunk
        for ent in entities:
            raw_name = ent.get("name", "").strip()
            etype    = ent.get("type", "Concept").strip()
            if not raw_name:
                continue

            ckey = _canonical_key(raw_name)
            if not ckey:
                continue

            # Upsert Entity by canonical_key; set canonical_name only on creation
            s.run(
                "MERGE (e:Entity {canonical_key: $ckey}) "
                "ON CREATE SET e.canonical_name = $name, e.type = $type "
                "ON MATCH  SET e.type = $type",   # update type if we learn better
                ckey=ckey, name=raw_name, type=etype,
            )

            # Register this surface form as an Alias (idempotent)
            alias_val = raw_name.lower()
            s.run(
                "MERGE (a:Alias {value: $val})",
                val=alias_val,
            )
            s.run(
                "MATCH (e:Entity {canonical_key: $ckey}), (a:Alias {value: $val}) "
                "MERGE (e)-[:HAS_ALIAS]->(a)",
                ckey=ckey, val=alias_val,
            )

            # Chunk -[:MENTIONS]-> Entity
            s.run(
                "MATCH (c:Chunk {id: $cid}), (e:Entity {canonical_key: $ckey}) "
                "MERGE (c)-[:MENTIONS]->(e)",
                cid=chunk_id, ckey=ckey,
            )

            written_entities.append(ckey)

        # ── CO_OCCURS_WITH edges (all entity pairs in this chunk) ────────
        # Empirical co-mention is the cheapest form of conceptual proximity.
        for i in range(len(written_entities)):
            for j in range(i + 1, len(written_entities)):
                a_key = written_entities[i]
                b_key = written_entities[j]
                s.run(
                    "MATCH (a:Entity {canonical_key: $ak}), (b:Entity {canonical_key: $bk}) "
                    "MERGE (a)-[r:CO_OCCURS_WITH]->(b) "
                    "ON CREATE SET r.count = 1, r.window = $win "
                    "ON MATCH  SET r.count = r.count + 1",
                    ak=a_key, bk=b_key, win=chunk_id,
                )

        # ── Typed relationship edges ─────────────────────────────────────
        # LLM returns {from, to, type} — we validate the type before writing.
        # Unknown/freeform types become POSSIBLY_SAME_AS (soft, reversible link).
        for rel in relationships:
            frm_raw = rel.get("from", "").strip()
            to_raw  = rel.get("to",   "").strip()
            rel_type = rel.get("type", "").strip().upper()
            if not frm_raw or not to_raw:
                continue
            if rel_type not in _VALID_REL_TYPES:
                rel_type = "POSSIBLY_SAME_AS"

            frm_key = _canonical_key(frm_raw)
            to_key  = _canonical_key(to_raw)
            if not frm_key or not to_key or frm_key == to_key:
                continue

            # Only write if both entities were actually created/found this chunk.
            # Prevents dangling edges from hallucinated entity names.
            if frm_key not in written_entities or to_key not in written_entities:
                continue

            s.run(
                f"MATCH (a:Entity {{canonical_key: $ak}}), (b:Entity {{canonical_key: $bk}}) "
                f"MERGE (a)-[r:{rel_type}]->(b)",
                ak=frm_key, bk=to_key,
            )


# ── Graph index checkpoint path ───────────────────────────────────────────────
GRAPH_CHECKPOINT = Path(__file__).parent / ".graph_checkpoint.json"
GRAPH_CHUNK_SLEEP = 0.5   # seconds between chunks — reduces GPU pressure


def _load_graph_checkpoint() -> dict:
    if GRAPH_CHECKPOINT.exists():
        try:
            return json.loads(GRAPH_CHECKPOINT.read_text())
        except Exception:
            pass
    return {"offset": 0, "processed": 0, "skipped": 0,
            "entities_total": 0, "rels_total": 0}


def _save_graph_checkpoint(data: dict):
    GRAPH_CHECKPOINT.write_text(json.dumps(data, indent=2))


def _clear_graph_checkpoint():
    if GRAPH_CHECKPOINT.exists():
        GRAPH_CHECKPOINT.unlink()


def graph_index_all(force: bool = False, model: str = None):
    """
    Build / update the Neo4j knowledge graph from all indexed vault files.
    Reads chunks from ChromaDB (already processed) and runs entity extraction
    on each one. Skips documents already in the graph unless --force.

    Supports pause/resume — Ctrl+C saves progress, restart picks up where
    it left off. Use --force to start over from scratch.
    """
    import time
    import signal

    if not NEO4J_AVAILABLE:
        print("[ERROR] neo4j package not installed. Run: pip install neo4j")
        return

    cfg = load_config()
    sb  = cfg.get('second_brain', cfg)
    extract_model = model or sb.get('chat_model', 'deepseek-r1:14b')
    chunk_sleep   = sb.get('graph_chunk_sleep', GRAPH_CHUNK_SLEEP)
    entity_types  = sb.get('entity_types', None)  # None → _extract_entities uses defaults

    neo4j_uri, _, _ = _get_neo4j_creds()
    print(f"\n[GRAPH] Connecting to Neo4j at {neo4j_uri}...")
    try:
        driver = _get_neo4j_driver()
        driver.verify_connectivity()
        print(f"[GRAPH] Connected. Setting up schema...")
        _neo4j_setup(driver)
    except Exception as e:
        print(f"[GRAPH ERROR] Cannot connect to Neo4j: {e}")
        print(f"  Make sure Neo4j Desktop is running and 'second-brain' instance is started.")
        return

    # Check what's already in the graph
    with driver.session() as s:
        existing_docs = {r["id"] for r in s.run("MATCH (d:Document) RETURN d.id as id")}

    # Load checkpoint (or start fresh if --force)
    if force:
        _clear_graph_checkpoint()
        checkpoint = {"offset": 0, "processed": 0, "skipped": 0,
                      "entities_total": 0, "rels_total": 0}
        print(f"[GRAPH] --force: starting from scratch, clearing checkpoint.")
    else:
        checkpoint = _load_graph_checkpoint()
        if checkpoint["offset"] > 0:
            print(f"[GRAPH] Resuming from chunk offset {checkpoint['offset']} "
                  f"({checkpoint['processed']} already processed this run).")

    print(f"[GRAPH] Already in graph: {len(existing_docs)} documents")

    # Pull all chunks from ChromaDB
    collection = get_collection()
    total = collection.count()
    if total == 0:
        print("[GRAPH] Nothing in ChromaDB yet. Run --index first.")
        driver.close()
        return

    print(f"[GRAPH] Extracting entities from {total} chunks using {extract_model}...")
    print(f"[GRAPH] Chunk sleep: {chunk_sleep}s — Ctrl+C saves progress and exits cleanly.\n")

    batch_size     = 100
    offset         = checkpoint["offset"]
    processed      = checkpoint["processed"]
    skipped        = checkpoint["skipped"]
    entities_total = checkpoint["entities_total"]
    rels_total     = checkpoint["rels_total"]

    # Graceful Ctrl+C handler
    interrupted = False
    def _handle_interrupt(sig, frame):
        nonlocal interrupted
        interrupted = True
        print(f"\n\n[GRAPH] Interrupt received — saving checkpoint and exiting cleanly...")

    signal.signal(signal.SIGINT, _handle_interrupt)

    try:
        while offset < total and not interrupted:
            try:
                batch = collection.get(
                    limit=batch_size,
                    offset=offset,
                    include=["documents", "metadatas"]
                )
            except Exception as e:
                print(f"\n[GRAPH ERROR] ChromaDB batch fetch failed: {e}")
                break

            for doc_text, meta in zip(batch["documents"], batch["metadatas"]):
                if interrupted:
                    break

                doc_id      = meta.get("file_id", meta.get("filename", "unknown"))
                filename    = meta.get("filename", "unknown")
                source_type = meta.get("source_type", "note")
                date        = meta.get("date", "")
                chunk_idx   = meta.get("chunk", 0)

                if not force and doc_id in existing_docs and chunk_idx > 0:
                    skipped += 1
                    continue

                extracted = _extract_entities(doc_text, filename, extract_model,
                                             entity_types=entity_types)
                entities  = extracted.get("entities", [])
                rels      = extracted.get("relationships", [])

                _write_to_graph(driver, doc_id, filename, source_type, date,
                                entities, rels, chunk_idx,
                                chunk_text=doc_text,
                                chunk_mtime=meta.get("mtime", 0.0))

                entities_total += len(entities)
                rels_total     += len(rels)
                processed      += 1

                print(f"  [{processed+skipped}/{total}] {filename:<40} "
                      f"+{len(entities)} entities  +{len(rels)} rels", end='\r')

                # Save checkpoint every 50 chunks
                if processed % 50 == 0:
                    _save_graph_checkpoint({
                        "offset": offset,
                        "processed": processed,
                        "skipped": skipped,
                        "entities_total": entities_total,
                        "rels_total": rels_total,
                    })

                time.sleep(chunk_sleep)

            offset += batch_size

    finally:
        # Always save checkpoint on exit (clean or interrupted)
        _save_graph_checkpoint({
            "offset": offset,
            "processed": processed,
            "skipped": skipped,
            "entities_total": entities_total,
            "rels_total": rels_total,
        })
        driver.close()

    if interrupted:
        print(f"\n[GRAPH] Paused at offset {offset}/{total}.")
        print(f"  Progress saved. Run 'python second_brain.py --graph-index' to resume.")
        print(f"  Run with --force to start over from scratch.")
    else:
        _clear_graph_checkpoint()
        print(f"\n\n[GRAPH] Complete!")
        print(f"  View graph: Neo4j Desktop → Query → MATCH (n) RETURN n LIMIT 100")

    print(f"  Chunks processed : {processed}")
    print(f"  Chunks skipped   : {skipped} (already in graph)")
    print(f"  Entities found   : {entities_total}")
    print(f"  Relationships    : {rels_total}")


def graph_retrieve(query: str, model: str, top_k: int = 10) -> list:
    """
    Query the Neo4j knowledge graph for entities and relationships
    relevant to the query. Returns list of context strings for the LLM.

    Strategy:
    1. Extract key entities from the query using the LLM
    2. Normalize to canonical_key and find matching Entity nodes
    3. Traverse typed edges and Alias nodes for rich relational context
    4. Find Chunks that mention those entities (sub-document evidence)
    5. Find cross-document connections via shared entity mention
    """
    if not NEO4J_AVAILABLE:
        return []

    # Extract entities from query
    prompt = f"""Extract the key named entities from this search query.
Query: {query}
Return ONLY a JSON array of entity name strings, no explanation:
["entity1", "entity2"]"""

    query_entities = []
    try:
        if is_claude(model):
            api_key = get_anthropic_key()
            resp = requests.post(
                ANTHROPIC_URL,
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": model, "max_tokens": 100, "messages": [{"role": "user", "content": prompt}]},
                timeout=10,
            )
            raw = resp.json()["content"][0]["text"].strip()
        else:
            resp = requests.post(
                OLLAMA_URL,
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=15,
            )
            raw = resp.json().get("response", "").strip()
        raw = re.sub(r"```.*?```", "", raw, flags=re.DOTALL).strip()
        query_entities = json.loads(raw)
    except Exception:
        query_entities = [query]

    if not query_entities:
        return []

    # Normalize query entity names the same way the indexer does
    query_keys = [_canonical_key(e) for e in query_entities[:4] if _canonical_key(e)]

    try:
        driver = _get_neo4j_driver()
    except Exception:
        return []

    results = []
    with driver.session() as s:
        for ckey in query_keys:
            # ── Entity match (by canonical_key or alias substring) ───────
            rows = s.run(
                """
                MATCH (e:Entity)
                WHERE e.canonical_key CONTAINS $ckey
                   OR EXISTS {
                       MATCH (e)-[:HAS_ALIAS]->(a:Alias)
                       WHERE a.value CONTAINS $ckey
                   }
                OPTIONAL MATCH (e)-[r1:CITES|INFLUENCES|EXTENDS|CONTRASTS_WITH]->(e2:Entity)
                OPTIONAL MATCH (e)-[:CO_OCCURS_WITH]->(e3:Entity)
                OPTIONAL MATCH (c:Chunk)-[:MENTIONS]->(e)
                OPTIONAL MATCH (c)-[:PART_OF]->(d:Document)
                RETURN e.canonical_name   AS entity,
                       e.canonical_key    AS ckey,
                       e.type             AS type,
                       collect(DISTINCT {name: e2.canonical_name, rel: type(r1)})[..5] AS typed_rels,
                       collect(DISTINCT e3.canonical_name)[..5]                         AS co_occurs,
                       collect(DISTINCT d.filename)[..5]                                AS sources
                LIMIT $lim
                """,
                ckey=ckey, lim=top_k,
            )
            for row in rows:
                typed_rel_str = ", ".join(
                    f"{r['name']} ({r['rel']})" for r in row["typed_rels"] if r["name"]
                ) or "none"
                co_occur_str = ", ".join(r for r in row["co_occurs"] if r) or "none"
                sources_str  = ", ".join(row["sources"]) if row["sources"] else "unknown"
                results.append({
                    "text": (
                        f"[GRAPH] Entity: {row['entity']} (type: {row['type']})\n"
                        f"Typed relationships: {typed_rel_str}\n"
                        f"Co-occurs with: {co_occur_str}\n"
                        f"Found in: {sources_str}"
                    ),
                    "filename": sources_str,
                    "source_type": "graph",
                    "relevance": 0.95,
                    "date": "",
                })

            # ── Cross-document connections via shared entity ──────────────
            rows = s.run(
                """
                MATCH (d1:Document)-[:HAS_CHUNK]->(c1:Chunk)-[:MENTIONS]->(e:Entity)
                      <-[:MENTIONS]-(c2:Chunk)<-[:HAS_CHUNK]-(d2:Document)
                WHERE e.canonical_key CONTAINS $ckey
                  AND d1.id <> d2.id
                RETURN e.canonical_name AS shared,
                       d1.filename AS doc1, d2.filename AS doc2
                LIMIT 5
                """,
                ckey=ckey,
            )
            for row in rows:
                results.append({
                    "text": (
                        f"[GRAPH] Cross-document connection via '{row['shared']}':\n"
                        f"  '{row['doc1']}' and '{row['doc2']}' both discuss this concept."
                    ),
                    "filename": f"{row['doc1']}, {row['doc2']}",
                    "source_type": "graph",
                    "relevance": 0.90,
                    "date": "",
                })

    driver.close()
    return results[:top_k]


def graph_search_cli(query: str):
    """CLI entry point for --graph-search."""
    cfg = load_config()
    sb  = cfg.get('second_brain', cfg)
    model = sb.get('chat_model', 'deepseek-r1:14b')
    print(f"\n[GRAPH] Searching: '{query}'\n")
    results = graph_retrieve(query, model)
    if not results:
        print("No graph results found. Run --graph-index first.")
        return
    for i, r in enumerate(results):
        print(f"─── {i+1}. {r['filename']} ───")
        print(r['text'])
        print()


# ─────────────────────────────────────────────
# RETRIEVAL — enhanced pipeline
#
# Query flow:
#   1. Query expansion   — LLM rewrites query 3 ways, catches synonyms/phrasings
#   2. HyDE              — LLM imagines ideal answer, embeds that for better recall
#   3. ChromaDB search   — cosine similarity across all expanded+HyDE embeddings
#   4. Deduplication     — merge results, keep best score per unique chunk
#   5. Reranking         — cross-encoder scores each candidate against original query
#   6. Return top_k      — LLM only sees the best chunks, not just closest vectors
# ─────────────────────────────────────────────

def _expand_query(query: str, chat_model: str) -> list[str]:
    """
    Query expansion: ask the LLM to rephrase the query 3 different ways.
    Catches cases where the user's phrasing doesn't match how the source
    was written — academic papers especially use different vocabulary than
    natural questions.
    Returns list of query variants including the original.
    """
    prompt = f"""Rephrase the following search query in 3 different ways to improve document retrieval.
Use different vocabulary, synonyms, and phrasings. Each rephrasing should capture the same intent.

Original query: {query}

Respond with ONLY a JSON array of 3 strings, no explanation, no markdown:
["rephrasing 1", "rephrasing 2", "rephrasing 3"]"""

    try:
        if is_claude(chat_model):
            api_key = get_anthropic_key()
            resp = requests.post(
                ANTHROPIC_URL,
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": chat_model, "max_tokens": 200, "messages": [{"role": "user", "content": prompt}]},
                timeout=15,
            )
            raw = resp.json()["content"][0]["text"].strip()
        else:
            resp = requests.post(
                OLLAMA_URL,
                json={"model": chat_model, "prompt": prompt, "stream": False},
                timeout=20,
            )
            raw = resp.json().get("response", "").strip()

        raw = re.sub(r"```json\s*|```\s*", "", raw)
        variants = json.loads(raw)
        if isinstance(variants, list):
            return [query] + [v for v in variants if isinstance(v, str)][:3]
    except Exception:
        pass
    return [query]


def _hyde_query(query: str, chat_model: str) -> str:
    """
    HyDE (Hypothetical Document Embedding): instead of embedding the raw
    question, ask the LLM to write what a perfect answer would look like,
    then embed THAT. Academic papers are written as answers, not questions —
    this closes the vocabulary gap dramatically.
    """
    prompt = f"""Write a short paragraph (3-5 sentences) that would be a perfect answer to this question.
Write it as if it were an excerpt from an academic paper or technical document.
Do not say 'the answer is' — just write the content directly.

Question: {query}"""

    try:
        if is_claude(chat_model):
            api_key = get_anthropic_key()
            resp = requests.post(
                ANTHROPIC_URL,
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": chat_model, "max_tokens": 300, "messages": [{"role": "user", "content": prompt}]},
                timeout=15,
            )
            return resp.json()["content"][0]["text"].strip()
        else:
            resp = requests.post(
                OLLAMA_URL,
                json={"model": chat_model, "prompt": prompt, "stream": False},
                timeout=25,
            )
            return resp.json().get("response", "").strip()
    except Exception:
        return query


def _rerank(query: str, candidates: list, chat_model: str, top_k: int) -> list:
    """
    Reranking: after embedding retrieval, score each candidate chunk against
    the original query using the LLM as a cross-encoder. This is more expensive
    but far more accurate than cosine similarity alone — the LLM reads both
    the query AND the chunk together and judges actual relevance.
    Pulls 3x top_k candidates, reranks, returns top_k.
    """
    if len(candidates) <= top_k:
        return candidates

    scored = []
    for chunk in candidates:
        prompt = f"""Rate how relevant this text passage is to answering the query.

Query: {query}

Passage: {chunk['text'][:600]}

Respond with ONLY a single integer from 1-10. No explanation."""
        try:
            if is_claude(chat_model):
                api_key = get_anthropic_key()
                resp = requests.post(
                    ANTHROPIC_URL,
                    headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    json={"model": chat_model, "max_tokens": 5, "messages": [{"role": "user", "content": prompt}]},
                    timeout=10,
                )
                score_str = resp.json()["content"][0]["text"].strip()
            else:
                resp = requests.post(
                    OLLAMA_URL,
                    json={"model": chat_model, "prompt": prompt, "stream": False},
                    timeout=15,
                )
                score_str = resp.json().get("response", "").strip()

            score = int(re.search(r'\d+', score_str).group())
            scored.append({**chunk, "rerank_score": min(10, max(1, score))})
        except Exception:
            scored.append({**chunk, "rerank_score": 5})

    scored.sort(key=lambda x: x["rerank_score"], reverse=True)
    return scored[:top_k]


def _chroma_search(collection, query_embedding: list, where: dict, n: int) -> list:
    """Run one ChromaDB similarity search, return raw result rows."""
    kwargs = dict(
        query_embeddings=[query_embedding],
        n_results=min(n, collection.count()),
        include=["documents", "metadatas", "distances"],
    )
    if where:
        kwargs["where"] = where
    results = collection.query(**kwargs)
    return list(zip(
        results['documents'][0],
        results['metadatas'][0],
        results['distances'][0],
    ))


def retrieve(query: str, cfg: dict, source_filter: str = None, chat_model: str = None) -> list:
    collection = get_collection()
    sb = cfg.get('second_brain', cfg)
    embed_model = sb.get('embed_model', 'mxbai-embed-large')
    top_k = sb.get('top_k', 10)
    use_hyde = sb.get('hyde', True)
    use_expansion = sb.get('query_expansion', True)
    use_rerank = sb.get('rerank', True)
    # Pull 3x candidates before reranking so reranker has real choices
    fetch_k = top_k * 3

    if collection.count() == 0:
        print("[WARN] Nothing indexed yet. Run: python second_brain.py --index")
        return []

    # ── Source filter (notes / code / research / all) ──────────────────
    where = None
    if source_filter == 'notes':
        where = {"source_type": "note"}
    elif source_filter == 'code':
        where = {"source_type": "code"}
    elif source_filter == 'research':
        where = {"type": "pdf-extract"}

    # ── Use a fast local model for retrieval helpers if available ───────
    # Falls back to llama3:8b or whatever chat_model is set to.
    helper_model = chat_model or sb.get('chat_model', 'llama3:8b')

    all_rows = {}  # doc_text -> best (meta, distance) — deduplication key

    def _add_rows(rows):
        for doc, meta, dist in rows:
            if doc not in all_rows or dist < all_rows[doc][1]:
                all_rows[doc] = (meta, dist)

    # ── 1. Base query (always runs) ──────────────────────────────────────
    enriched = f"Search query: {query}"
    _add_rows(_chroma_search(collection, embed(enriched, embed_model), where, fetch_k))

    # ── 2. Query expansion ───────────────────────────────────────────────
    if use_expansion and chat_model:
        print("  [retrieve] Expanding query...", end='\r')
        variants = _expand_query(query, helper_model)
        for v in variants[1:]:  # skip original, already searched
            try:
                _add_rows(_chroma_search(collection, embed(f"Search query: {v}", embed_model), where, fetch_k // 2))
            except Exception:
                pass

    # ── 3. HyDE ─────────────────────────────────────────────────────────
    if use_hyde and chat_model:
        print("  [retrieve] HyDE pass...      ", end='\r')
        try:
            hypothetical = _hyde_query(query, helper_model)
            _add_rows(_chroma_search(collection, embed(hypothetical, embed_model), where, fetch_k // 2))
        except Exception:
            pass

    # ── 4. Build candidate list (deduplicated) ───────────────────────────
    candidates = [{
        "text": doc,
        "filename": meta.get("filename", "unknown"),
        "source_type": meta.get("source_type", "note"),
        "repo": meta.get("repo", ""),
        "extension": meta.get("extension", ""),
        "date": meta.get("date", ""),
        "relevance": round(1 - dist, 3),
    } for doc, (meta, dist) in sorted(all_rows.items(), key=lambda x: x[1][1])]

    # ── 5. Reranking ─────────────────────────────────────────────────────
    if use_rerank and chat_model and len(candidates) > top_k:
        print("  [retrieve] Reranking...      ", end='\r')
        candidates = _rerank(query, candidates[:fetch_k], helper_model, top_k)
    else:
        candidates = candidates[:top_k]

    print("                               ", end='\r')  # clear status line
    return candidates


def quick_search(query: str):
    cfg = load_config()
    print(f"\nSearching: '{query}'\n")
    for i, c in enumerate(retrieve(query, cfg)):
        tag = f"[{c['source_type'].upper()}]"
        print(f"─── {i+1}. {tag} {c['filename']} | relevance: {c['relevance']} ───")
        print(c['text'][:400])
        print()



# ─────────────────────────────────────────────
# AGENTIC RETRIEVAL ROUTER
#
# Sits above retrieve() and graph_retrieve().
# The agent classifies the query, decides which store(s) to hit,
# and can loop if the first pass doesn't yield enough context.
#
# Query types:
#   semantic   → ChromaDB only  (factual, "what does X say about Y")
#   relational → Neo4j only     (connections, "how does X relate to Y")
#   hybrid     → both stores    (complex, needs both semantic + graph context)
#   agentic    → multi-hop loop (agent decides when it has enough)
# ─────────────────────────────────────────────

def _classify_query(query: str, model: str) -> str:
    """
    Classify query intent to route to the right retrieval store.
    Returns: 'semantic' | 'relational' | 'hybrid'
    """
    prompt = f"""Classify this search query into one of three retrieval strategies.

Query: {query}

Options:
- semantic: Looking for specific content, facts, explanations, or summaries from documents.
  Examples: "what does Valiant argue", "explain PAC learning", "summarize the paper"
- relational: Looking for connections, comparisons, or relationships between concepts/papers/people.
  Examples: "how does X relate to Y", "which papers cite Z", "compare X and Y", "what connects X to Y"
- hybrid: Needs both specific content AND relationship context.
  Examples: "how has PAC learning influenced modern ML", "what are all papers on X and how do they connect"

Respond with ONLY one word: semantic, relational, or hybrid"""

    try:
        if is_claude(model):
            api_key = get_anthropic_key()
            resp = requests.post(
                ANTHROPIC_URL,
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": model, "max_tokens": 10, "messages": [{"role": "user", "content": prompt}]},
                timeout=10,
            )
            result = resp.json()["content"][0]["text"].strip().lower()
        else:
            resp = requests.post(
                OLLAMA_URL,
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=15,
            )
            result = resp.json().get("response", "").strip().lower()

        if "relational" in result:
            return "relational"
        elif "hybrid" in result:
            return "hybrid"
        return "semantic"
    except Exception:
        return "semantic"  # safe default


def _agent_has_enough_context(query: str, chunks: list, model: str) -> bool:
    """
    Ask the LLM if the retrieved context is sufficient to answer the query,
    or if another retrieval pass is needed.
    """
    context_preview = "\n".join([c["text"][:300] for c in chunks[:4]])
    prompt = f"""Given this query and the retrieved context, is there enough information to give a good answer?

Query: {query}

Retrieved context preview:
{context_preview}

Answer with ONLY: yes or no"""

    try:
        if is_claude(model):
            api_key = get_anthropic_key()
            resp = requests.post(
                ANTHROPIC_URL,
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": model, "max_tokens": 5, "messages": [{"role": "user", "content": prompt}]},
                timeout=10,
            )
            return "yes" in resp.json()["content"][0]["text"].lower()
        else:
            resp = requests.post(
                OLLAMA_URL,
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=15,
            )
            return "yes" in resp.json().get("response", "").lower()
    except Exception:
        return True  # assume sufficient on failure


def agentic_retrieve(query: str, cfg: dict, source_filter: str = None,
                     chat_model: str = None, max_hops: int = 3) -> tuple[list, str]:
    """
    Agentic retrieval router. Classifies the query, hits the right store(s),
    and loops if context is insufficient. Returns (chunks, route_used).

    route_used is one of: 'semantic' | 'relational' | 'hybrid' | 'multi-hop'
    """
    if not chat_model:
        # No model available for routing — fall back to basic vector search
        return retrieve(query, cfg, source_filter, chat_model=None), "semantic"

    sb = cfg.get("second_brain", cfg)
    top_k = sb.get("top_k", 10)
    use_graph = NEO4J_AVAILABLE and sb.get("graph", True)

    # ── Step 1: Classify the query ──────────────────────────────────────
    print("  [agent] Classifying query...", end="\r")
    route = _classify_query(query, chat_model)

    # Force semantic if graph is unavailable or disabled
    if not use_graph and route in ("relational", "hybrid"):
        route = "semantic"

    all_chunks = []

    # ── Step 2: First retrieval pass ────────────────────────────────────
    if route == "semantic":
        print("  [agent] Vector search...    ", end="\r")
        all_chunks = retrieve(query, cfg, source_filter, chat_model=chat_model)

    elif route == "relational":
        print("  [agent] Graph traversal...  ", end="\r")
        all_chunks = graph_retrieve(query, chat_model, top_k=top_k)
        # If graph comes up empty, fall back to vector
        if not all_chunks:
            print("  [agent] Graph empty, falling back to vector...", end="\r")
            all_chunks = retrieve(query, cfg, source_filter, chat_model=chat_model)
            route = "semantic"

    elif route == "hybrid":
        print("  [agent] Hybrid search...    ", end="\r")
        vector_chunks = retrieve(query, cfg, source_filter, chat_model=chat_model)
        graph_chunks  = graph_retrieve(query, chat_model, top_k=top_k // 2)
        # Interleave: vector results first (more content), graph adds relationships
        all_chunks = vector_chunks + graph_chunks

    # ── Step 3: Agentic loop — check if context is sufficient ───────────
    hop = 1
    while hop < max_hops and all_chunks:
        print(f"  [agent] Checking context sufficiency (hop {hop})...", end="\r")
        if _agent_has_enough_context(query, all_chunks, chat_model):
            break
        # Not enough — try a different angle
        hop += 1
        route = "multi-hop"
        print(f"  [agent] Insufficient context — hop {hop}...", end="\r")
        # Expand with graph if not already used
        if use_graph and not any(c.get("source_type") == "graph" for c in all_chunks):
            extra = graph_retrieve(query, chat_model, top_k=5)
            all_chunks = all_chunks + extra
        else:
            # Try query expansion with a different framing
            variants = _expand_query(query, chat_model)
            if len(variants) > 1:
                extra = retrieve(variants[1], cfg, source_filter, chat_model=None)
                seen = {c["text"] for c in all_chunks}
                all_chunks += [c for c in extra if c["text"] not in seen]

    print("                                        ", end="\r")  # clear status
    return all_chunks[:top_k + 5], route  # give LLM a bit more on hybrid/multi-hop

# ─────────────────────────────────────────────
# CHAT BACKENDS
# ─────────────────────────────────────────────

def build_prompt(query: str, chunks: list, history: list, user_name: str) -> str:
    context_parts = []
    for c in chunks:
        tag = "CODE" if c['source_type'] == 'code' else "NOTE"
        label = f"[{tag}: {c['filename']}]"
        if c['date']:
            label += f" ({c['date']})"
        context_parts.append(f"{label}\n{c['text']}")

    context = "\n\n---\n\n".join(context_parts)
    history_str = ""
    if history:
        lines = []
        for turn in history[-6:]:
            lines.append(f"{user_name}: {turn['user']}")
            lines.append(f"Assistant: {turn['assistant']}")
        history_str = "\n".join(lines)

    return f"""You are {user_name}'s Second Brain assistant with access to their Obsidian notes, transcripts, browser reports, and codebase. Answer using the context below. Be direct and specific. Reference source names. Surface cross-source patterns when relevant.

CONTEXT:
{context}

{"HISTORY:" + chr(10) + history_str if history_str else ""}

{user_name}: {query}

Answer directly. Cite sources by name. Connect dots across notes when you see patterns."""


def stream_ollama(prompt: str, model: str) -> str:
    """Stream a response from Ollama, filtering <think> blocks."""
    full_response = ""
    in_think = False
    resp = requests.post(
        OLLAMA_URL,
        json={"model": model, "prompt": prompt, "stream": True},
        stream=True, timeout=180,
    )
    for line in resp.iter_lines():
        if line:
            data = json.loads(line)
            token = data.get("response", "")
            if "<think>" in token:
                in_think = True
            if "</think>" in token:
                in_think = False
                token = token.split("</think>")[-1]
            if not in_think:
                print(token, end='', flush=True)
                full_response += token
            if data.get("done"):
                break
    return re.sub(r'<think>.*?</think>', '', full_response, flags=re.DOTALL).strip()


def stream_claude(prompt: str, model: str) -> str:
    """Stream a response from the Claude API."""
    api_key = get_anthropic_key()
    if not api_key:
        raise ValueError("No Anthropic API key found. Check config.yaml or set ANTHROPIC_API_KEY env var.")

    full_response = ""
    resp = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 2048,
            "stream": True,
            "messages": [{"role": "user", "content": prompt}],
        },
        stream=True,
        timeout=180,
    )
    resp.raise_for_status()

    for line in resp.iter_lines():
        if not line:
            continue
        line = line.decode("utf-8") if isinstance(line, bytes) else line
        if line.startswith("data: "):
            data_str = line[6:]
            if data_str.strip() == "[DONE]":
                break
            try:
                data = json.loads(data_str)
                if data.get("type") == "content_block_delta":
                    token = data.get("delta", {}).get("text", "")
                    print(token, end='', flush=True)
                    full_response += token
            except json.JSONDecodeError:
                continue

    return full_response.strip()

# ─────────────────────────────────────────────
# CHAT LOOP
# ─────────────────────────────────────────────

def chat_with_brain(model_override: str = None):
    cfg = load_config()
    user_name = cfg.get('user', {}).get('name', 'User')
    collection = get_collection()

    if collection.count() == 0:
        print("\n[ERROR] Nothing indexed. Run: python second_brain.py --index")
        return

    # ── Index stats ──────────────────────────────────────────
    try:
        notes = len(collection.get(where={"source_type": "note"})['ids'])
        code  = len(collection.get(where={"source_type": "code"})['ids'])
        total = collection.count()
        index_str = f"{total} chunks  ({notes} notes · {code} code)"
    except Exception:
        index_str = f"{collection.count()} total chunks"

    print(f"\n{'='*60}")
    print(f"  Second Brain")
    print(f"  {'─'*56}")
    print(f"  Index:  {index_str}")
    print()

    # ── Model selection ──────────────────────────────────────
    if model_override:
        chat_model = CLAUDE_MODELS.get(model_override, model_override)
    else:
        chat_model = pick_model_interactively()

    backend = "claude" if is_claude(chat_model) else "ollama"
    short_label = chat_model.split('-')[1] if is_claude(chat_model) else chat_model.split(':')[0]

    print(f"\n{'='*60}")
    print(f"  Model:  {chat_model}  ({'☁ Claude API' if backend == 'claude' else '🖥 Local Ollama'})")
    print(f"  {'─'*56}")
    print(f"  Commands: quit | clear | sources | /notes | /code | /research | /all")
    print(f"            /model — switch model   /route — show last query route")
    print(f"            /hyde /expand /rerank /graph — toggle retrieval features")
    print(f"{'='*60}\n")

    history, last_chunks, source_filter = [], [], None

    while True:
        try:
            query = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break

        if not query:
            continue
        if query.lower() in ('quit', 'exit', 'q'):
            break
        if query.lower() == 'clear':
            history = []
            print("  [History cleared]\n")
            continue
        if query.lower() == 'sources':
            if last_chunks:
                print("\n  Sources:")
                for c in last_chunks:
                    print(f"    [{c['source_type'].upper()}] {c['filename']} ({c['relevance']})")
                print()
            continue
        if query.lower() == '/notes':
            source_filter = 'notes'
            print("  [Notes only mode]\n")
            continue
        if query.lower() == '/code':
            source_filter = 'code'
            print("  [Code only mode]\n")
            continue
        if query.lower() == '/research':
            source_filter = 'research'
            print("  [Research/papers only mode — searches PDFs and Research folder]\n")
            continue
        if query.lower() == '/all':
            source_filter = None
            print("  [All sources mode]\n")
            continue
        if query.lower() == '/model':
            chat_model = pick_model_interactively(current_model=chat_model)
            backend = "claude" if is_claude(chat_model) else "ollama"
            short_label = chat_model.split('-')[1] if is_claude(chat_model) else chat_model.split(':')[0]
            history = []
            print(f"  [Switched to {chat_model} — history cleared]\n")
            continue
        if query.lower() == '/hyde':
            cfg.setdefault('second_brain', {})['hyde'] = not cfg.get('second_brain', {}).get('hyde', True)
            state = "ON" if cfg['second_brain']['hyde'] else "OFF"
            print(f"  [HyDE {state}]\n")
            continue
        if query.lower() == '/expand':
            cfg.setdefault('second_brain', {})['query_expansion'] = not cfg.get('second_brain', {}).get('query_expansion', True)
            state = "ON" if cfg['second_brain']['query_expansion'] else "OFF"
            print(f"  [Query expansion {state}]\n")
            continue
        if query.lower() == '/rerank':
            cfg.setdefault('second_brain', {})['rerank'] = not cfg.get('second_brain', {}).get('rerank', True)
            state = "ON" if cfg['second_brain']['rerank'] else "OFF"
            print(f"  [Reranking {state}]\n")
            continue
        if query.lower() == '/graph':
            cfg.setdefault('second_brain', {})['graph'] = not cfg.get('second_brain', {}).get('graph', True)
            state = "ON" if cfg['second_brain']['graph'] else "OFF"
            print(f"  [Graph retrieval {state}]\n")
            continue
        if query.lower() == '/route':
            if last_chunks:
                route = next((c.get('source_type','?') for c in last_chunks), '?')
                graph_count = sum(1 for c in last_chunks if c.get('source_type') == 'graph')
                vec_count = len(last_chunks) - graph_count
                print(f"\n  Last query route:")
                print(f"    Vector chunks: {vec_count}")
                print(f"    Graph chunks:  {graph_count}")
                print()
            continue

        chunks, route_used = agentic_retrieve(
            query, cfg, source_filter, chat_model=chat_model
        )
        last_chunks = chunks

        if not chunks:
            print("Brain: No relevant content found.\n")
            continue

        route_label = f"{short_label}\u00b7{route_used}"
        prompt = build_prompt(query, chunks, history, user_name)
        print(f"\nBrain [{route_label}]: ", end='', flush=True)

        try:
            if backend == "claude":
                full_response = stream_claude(prompt, chat_model)
            else:
                full_response = stream_ollama(prompt, chat_model)
        except Exception as e:
            print(f"\n[ERROR] {e}")
            continue

        source_labels = list(set(
            f"[{'CODE' if c['source_type']=='code' else 'NOTE'}] {c['filename']}"
            for c in chunks
        ))
        print(f"\n  [Sources: {', '.join(source_labels)}]\n")
        history.append({"user": query, "assistant": full_response[:600]})

# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Second Brain — Hybrid GraphRAG + Vector RAG + Agentic retrieval")
    parser.add_argument("--index",        action="store_true", help="Vector index new/changed files")
    parser.add_argument("--force",        action="store_true", help="Force full re-index")
    parser.add_argument("--graph-index",  action="store_true", help="Build/update Neo4j knowledge graph")
    parser.add_argument("--graph-search", type=str,            help="Query the knowledge graph directly")
    parser.add_argument("--chat",         action="store_true", help="Start agentic chat session")
    parser.add_argument("--model",        type=str, default=None,
                        help="Skip model picker: claude-haiku | claude-sonnet | claude-opus | llama3:8b etc")
    parser.add_argument("--search",       type=str,            help="Quick vector search")
    parser.add_argument("--stats",        action="store_true", help="Show index stats")
    args = parser.parse_args()

    if args.stats:
        show_stats()
    elif args.search:
        quick_search(args.search)
    elif args.graph_search:
        graph_search_cli(args.graph_search)
    elif args.graph_index:
        cfg = load_config()
        sb  = cfg.get("second_brain", cfg)
        model = args.model or sb.get("chat_model", "deepseek-r1:14b")
        graph_index_all(force=args.force, model=model)
    elif args.index and args.chat:
        index_all(force=args.force)
        chat_with_brain(model_override=args.model)
    elif args.index:
        index_all(force=args.force)
    elif args.chat:
        chat_with_brain(model_override=args.model)
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python second_brain.py --index                         # vector index only")
        print("  python second_brain.py --index --force                 # full re-index")
        print("  python second_brain.py --graph-index                   # build knowledge graph")
        print("  python second_brain.py --graph-index --force           # rebuild graph from scratch")
        print("  python second_brain.py --chat                          # agentic chat, model picker")
        print("  python second_brain.py --chat --model claude-haiku")
        print("  python second_brain.py --chat --model claude-sonnet")
        print("  python second_brain.py --chat --model llama3:8b")
        print("  python second_brain.py --index --chat")
        print("  python second_brain.py --search \'how does focus score work\'")
        print("  python second_brain.py --graph-search \'how does Valiant relate to Vapnik\'")
        print("  python second_brain.py --stats")
