"""
Obsidian Second Brain
Karl's Productivity OS - Project 8

Indexes your Obsidian vault + selected codebases into ChromaDB.
Chat with all of it using deepseek-r1:14b via Ollama.

Usage:
    python second_brain.py --index        # index everything in config.yaml
    python second_brain.py --chat         # start chat session
    python second_brain.py --index --chat # index then chat
    python second_brain.py --search "query"
    python second_brain.py --stats
    python second_brain.py --index --force  # force re-index all
"""

import sys
import json
import re
import argparse
import requests
from pathlib import Path

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

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

CONFIG_PATH      = Path(__file__).parent / "config.yaml"
CHROMA_DIR       = Path(r"C:\Users\Karl\Documents\second_brain_db")
OLLAMA_URL       = "http://localhost:11434/api/generate"
OLLAMA_EMBED_URL = "http://localhost:11434/api/embeddings"

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"[ERROR] config.yaml not found at {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)

# ─────────────────────────────────────────────
# CHROMADB
# ─────────────────────────────────────────────

def get_collection():
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_or_create_collection(
        name="second_brain",
        metadata={"hnsw:space": "cosine"}
    )

# ─────────────────────────────────────────────
# EMBEDDING
# ─────────────────────────────────────────────

def embed(text: str, model: str) -> list:
    resp = requests.post(
        OLLAMA_EMBED_URL,
        json={"model": model, "prompt": text},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["embedding"]

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
    skip_folders = set(cfg.get('skip_folders', []))
    code_extensions = set(cfg.get('code_extensions', ['.py', '.md', '.js', '.ts']))

    for vault_path in cfg.get('vaults', []):
        vault = Path(vault_path)
        if not vault.exists():
            print(f"  [WARN] Vault not found: {vault}")
            continue
        for ext in ['.md', '.txt']:
            for f in vault.rglob(f"*{ext}"):
                if any(s in f.parts for s in skip_folders):
                    continue
                files.append((f, 'note', vault.name, vault))

    for repo_path in cfg.get('codebases', []):
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
    embed_model = cfg.get('embed_model', 'nomic-embed-text')
    chunk_size = cfg.get('chunk_size', 800)
    chunk_overlap = cfg.get('chunk_overlap', 150)

    files = collect_files(cfg)
    print(f"\n[INDEX] Found {len(files)} files across vault + codebases")

    existing = set()
    if not force:
        try:
            existing = set(collection.get()['ids'])
        except Exception:
            pass

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
            chunk_0_id = f"{file_id}::{mtime}::0"

            if chunk_0_id in existing and not force:
                skipped += 1
                continue

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

            chunks = chunk_text(content, chunk_size, chunk_overlap)
            if not chunks:
                continue

            print(f"  [{i+1}/{len(files)}] [{source_type.upper()}] {filepath.name:<40} {len(chunks)} chunks", end='\r')

            ids, embeddings, documents, metadatas = [], [], [], []
            for j, chunk in enumerate(chunks):
                chunk_id = f"{file_id}::{mtime}::{j}"
                try:
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

        except Exception as e:
            print(f"\n  [ERROR] {filepath.name}: {e}")

    print(f"\n\n[INDEX] Complete")
    print(f"  Files indexed:  {indexed}")
    print(f"  Files skipped:  {skipped} (unchanged)")
    print(f"  Total chunks:   {total_chunks}")

def show_stats():
    cfg = load_config()
    collection = get_collection()
    count = collection.count()
    try:
        notes = len(collection.get(where={"source_type": "note"})['ids'])
        code  = len(collection.get(where={"source_type": "code"})['ids'])
    except Exception:
        notes = code = 0

    print(f"\n  Second Brain Stats")
    print(f"  {'─'*40}")
    print(f"  Total chunks:   {count}")
    print(f"  Note chunks:    {notes}")
    print(f"  Code chunks:    {code}")
    print(f"  Embed model:    {cfg.get('embed_model', 'nomic-embed-text')}")
    print(f"  Chat model:     {cfg.get('chat_model', 'deepseek-r1:14b')}")
    print(f"  DB:             {CHROMA_DIR}")

# ─────────────────────────────────────────────
# RETRIEVAL
# ─────────────────────────────────────────────

def retrieve(query: str, cfg: dict, source_filter: str = None) -> list:
    collection = get_collection()
    embed_model = cfg.get('embed_model', 'nomic-embed-text')
    top_k = cfg.get('top_k', 6)

    if collection.count() == 0:
        print("[WARN] Nothing indexed yet. Run: python second_brain.py --index")
        return []

    query_embedding = embed(query, embed_model)

    where = None
    if source_filter == 'notes':
        where = {"source_type": "note"}
    elif source_filter == 'code':
        where = {"source_type": "code"}

    kwargs = dict(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
        include=["documents", "metadatas", "distances"],
    )
    if where:
        kwargs["where"] = where

    results = collection.query(**kwargs)

    return [{
        "text": doc,
        "filename": meta.get("filename", "unknown"),
        "source_type": meta.get("source_type", "note"),
        "repo": meta.get("repo", ""),
        "extension": meta.get("extension", ""),
        "date": meta.get("date", ""),
        "relevance": round(1 - dist, 3),
    } for doc, meta, dist in zip(
        results['documents'][0],
        results['metadatas'][0],
        results['distances'][0]
    )]

def quick_search(query: str):
    cfg = load_config()
    print(f"\nSearching: '{query}'\n")
    for i, c in enumerate(retrieve(query, cfg)):
        tag = f"[{c['source_type'].upper()}]"
        print(f"─── {i+1}. {tag} {c['filename']} | relevance: {c['relevance']} ───")
        print(c['text'][:400])
        print()

# ─────────────────────────────────────────────
# CHAT
# ─────────────────────────────────────────────

def build_prompt(query: str, chunks: list, history: list) -> str:
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
            lines.append(f"Karl: {turn['user']}")
            lines.append(f"Assistant: {turn['assistant']}")
        history_str = "\n".join(lines)

    return f"""You are Karl's Second Brain assistant with access to his Obsidian notes, transcripts, browser reports, and codebase. Answer using the context below. Be direct and specific. Reference source names. Surface cross-source patterns when relevant.

CONTEXT:
{context}

{"HISTORY:" + chr(10) + history_str if history_str else ""}

Karl: {query}

Answer directly. Cite sources by name. Connect dots across notes when you see patterns."""

def chat_with_brain():
    cfg = load_config()
    chat_model = cfg.get('chat_model', 'deepseek-r1:14b')
    collection = get_collection()

    if collection.count() == 0:
        print("\n[ERROR] Nothing indexed. Run: python second_brain.py --index")
        return

    try:
        notes = len(collection.get(where={"source_type": "note"})['ids'])
        code  = len(collection.get(where={"source_type": "code"})['ids'])
        type_str = f"{notes} note chunks | {code} code chunks"
    except Exception:
        type_str = f"{collection.count()} total chunks"

    print(f"\n{'='*60}")
    print(f"  Second Brain — {type_str}")
    print(f"  Model: {chat_model}")
    print(f"  Commands: quit | clear | sources | /notes | /code | /all")
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
        if query.lower() == '/all':
            source_filter = None
            print("  [All sources mode]\n")
            continue

        chunks = retrieve(query, cfg, source_filter)
        last_chunks = chunks

        if not chunks:
            print("Brain: No relevant content found.\n")
            continue

        prompt = build_prompt(query, chunks, history)
        print(f"\nBrain: ", end='', flush=True)
        full_response = ""
        in_think = False

        try:
            resp = requests.post(
                OLLAMA_URL,
                json={"model": chat_model, "prompt": prompt, "stream": True},
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
        except Exception as e:
            print(f"\n[ERROR] {e}")
            continue

        full_response = re.sub(r'<think>.*?</think>', '', full_response, flags=re.DOTALL).strip()
        labels = list(set(f"[{'CODE' if c['source_type']=='code' else 'NOTE'}] {c['filename']}" for c in chunks))
        print(f"\n  [Sources: {', '.join(labels)}]\n")
        history.append({"user": query, "assistant": full_response[:600]})

# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Second Brain — chat with your notes + code")
    parser.add_argument("--index", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--chat", action="store_true")
    parser.add_argument("--search", type=str)
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()

    if args.stats:
        show_stats()
    elif args.search:
        quick_search(args.search)
    elif args.index and args.chat:
        index_all(force=args.force)
        chat_with_brain()
    elif args.index:
        index_all(force=args.force)
    elif args.chat:
        chat_with_brain()
    else:
        parser.print_help()
        print("\nExamples:")
        print("  python second_brain.py --index --chat")
        print("  python second_brain.py --search 'how does focus score work'")
        print("  python second_brain.py --stats")
