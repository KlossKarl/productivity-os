"""
LightRAG Test — Productivity OS
Parallel GraphRAG test alongside existing Neo4j/ChromaDB stack.

Ingests your Obsidian vault into LightRAG and lets you query it.
Run this AFTER --graph-index finishes (they both use deepseek-r1:14b).

Install first:
    pip install "lightrag-hku[api]"

Usage:
    python lightrag_test.py --ingest        # ingest vault (slow, ~2-8 hrs for full vault)
    python lightrag_test.py --ingest --limit 50   # test with 50 files first
    python lightrag_test.py --chat          # chat against existing LightRAG index
    python lightrag_test.py --compare "your question"  # same question → both systems
"""

import os
import sys
import argparse
from pathlib import Path

try:
    import yaml
except ImportError:
    print("[ERROR] pip install pyyaml")
    sys.exit(1)

try:
    from lightrag import LightRAG, QueryParam
    from lightrag.llm.ollama import ollama_model_complete, ollama_embed
    from lightrag.utils import EmbeddingFunc
except ImportError:
    print("[ERROR] LightRAG not installed.")
    print("  Run: pip install \"lightrag-hku[api]\"")
    sys.exit(1)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

PROJECT_ROOT   = Path(__file__).parent
CONFIG_PATH    = PROJECT_ROOT / "config.yaml"
LIGHTRAG_DIR   = PROJECT_ROOT / "lightrag_db"   # LightRAG stores its own graph + vectors here

def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)

def get_vault_path() -> Path:
    cfg = load_config()
    sb = cfg.get('second_brain', cfg)
    return Path(sb['vaults'][0])

def get_skip_folders() -> set:
    cfg = load_config()
    sb = cfg.get('second_brain', cfg)
    return set(sb.get('skip_folders', []))


# ─────────────────────────────────────────────
# LIGHTRAG SETUP
# ─────────────────────────────────────────────

def build_rag() -> LightRAG:
    """
    Initialize LightRAG with Ollama backend — fully local, zero API cost.
    Uses same models already on your machine: deepseek-r1:14b + mxbai-embed-large.
    """
    cfg = load_config()
    sb  = cfg.get('second_brain', cfg)

    llm_model   = sb.get('chat_model', 'deepseek-r1:14b')
    embed_model = sb.get('embed_model', 'mxbai-embed-large')
    ollama_host = cfg.get('ollama', {}).get('url', 'http://localhost:11434')

    print(f"  LLM:       {llm_model}  (Ollama)")
    print(f"  Embeddings: {embed_model}  (Ollama)")
    print(f"  Storage:    {LIGHTRAG_DIR}")

    LIGHTRAG_DIR.mkdir(exist_ok=True)

    rag = LightRAG(
        working_dir=str(LIGHTRAG_DIR),
        llm_model_func=ollama_model_complete,
        llm_model_name=llm_model,
        llm_model_kwargs={"host": ollama_host, "options": {"num_ctx": 8192}},
        embedding_func=EmbeddingFunc(
            embedding_dim=1024,          # mxbai-embed-large dimension
            max_token_size=512,
            func=lambda texts: ollama_embed(
                texts,
                embed_model=embed_model,
                host=ollama_host,
            )
        ),
    )
    return rag


# ─────────────────────────────────────────────
# INGESTION
# ─────────────────────────────────────────────

def collect_vault_files(limit: int = None) -> list[Path]:
    vault    = get_vault_path()
    skip     = get_skip_folders()
    files    = []

    for f in vault.rglob("*.md"):
        if any(s in f.parts for s in skip):
            continue
        if f.stat().st_size < 100:   # skip empty/stub files
            continue
        files.append(f)

    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)  # newest first
    if limit:
        files = files[:limit]
    return files


def ingest(limit: int = None):
    """
    Feed vault markdown files into LightRAG.
    LightRAG handles entity extraction, graph building, and vector indexing internally.

    This is SLOW — LightRAG calls the LLM for every document chunk.
    With deepseek-r1:14b locally: ~30-90 seconds per document.
    Recommended: test with --limit 20 first to verify quality before full run.
    """
    files = collect_vault_files(limit)
    print(f"\n[LIGHTRAG] Ingesting {len(files)} files from vault")
    if limit:
        print(f"  (limited to {limit} — remove --limit for full vault)")
    print(f"  Expected time: ~{len(files) * 1} min at 1 min/doc estimate")
    print(f"  Ctrl+C to stop — LightRAG checkpoints internally\n")

    rag = build_rag()

    success = fail = 0
    for i, path in enumerate(files, 1):
        try:
            content = path.read_text(encoding='utf-8', errors='ignore').strip()
            if not content:
                continue

            # Prepend filename as context — same pattern as second_brain.py
            labeled = f"# {path.stem}\n\n{content}"

            print(f"  [{i}/{len(files)}] {path.name:<50}", end='\r')
            rag.insert(labeled)
            success += 1
        except KeyboardInterrupt:
            print(f"\n\n  Interrupted at {i}/{len(files)}. Progress saved internally.")
            break
        except Exception as e:
            fail += 1
            print(f"\n  [WARN] {path.name}: {e}")

    print(f"\n\n[LIGHTRAG] Ingestion complete")
    print(f"  Indexed: {success}  Failed: {fail}")
    print(f"  Run --chat to test it\n")


# ─────────────────────────────────────────────
# CHAT
# ─────────────────────────────────────────────

MODES = {
    'h': ('hybrid',  'hybrid  — graph + vector (best for most questions)'),
    'l': ('local',   'local   — specific entities, precise facts'),
    'g': ('global',  'global  — big picture, themes across everything'),
    'n': ('naive',   'naive   — pure vector only (baseline comparison)'),
}

def chat():
    print(f"\n{'='*56}")
    print(f"  LightRAG Chat — Productivity OS")
    print(f"{'='*56}")
    print(f"  Modes: h=hybrid  l=local  g=global  n=naive")
    print(f"  Type /mode to switch, quit to exit")
    print(f"{'='*56}\n")

    rag = build_rag()
    mode = 'hybrid'

    while True:
        try:
            query = input(f"You [{mode}]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break

        if not query:
            continue
        if query.lower() in ('quit', 'exit', 'q'):
            break
        if query.lower() == '/mode':
            print("\n  Available modes:")
            for k, (m, label) in MODES.items():
                marker = "  ◀" if m == mode else ""
                print(f"    {k} — {label}{marker}")
            choice = input("  Select: ").strip().lower()
            if choice in MODES:
                mode = MODES[choice][0]
                print(f"  Switched to {mode}\n")
            continue

        try:
            print(f"\nBrain [lightrag·{mode}]: ", end='', flush=True)
            result = rag.query(query, param=QueryParam(mode=mode))
            print(result)
            print()
        except Exception as e:
            print(f"\n[ERROR] {e}\n")


# ─────────────────────────────────────────────
# COMPARE — same question to both systems
# ─────────────────────────────────────────────

def compare(question: str):
    """
    Ask the same question to LightRAG and second_brain.py --search.
    Side-by-side quality comparison.
    """
    import subprocess

    print(f"\n{'='*56}")
    print(f"  COMPARE: {question}")
    print(f"{'='*56}\n")

    # LightRAG hybrid answer
    print("── LightRAG (hybrid) ──────────────────────────────")
    try:
        rag = build_rag()
        result = rag.query(question, param=QueryParam(mode="hybrid"))
        print(result)
    except Exception as e:
        print(f"[ERROR] {e}")

    print()

    # second_brain vector search
    print("── Second Brain (vector search) ───────────────────")
    sb_script = PROJECT_ROOT / "08_second_brain" / "second_brain.py"
    if sb_script.exists():
        subprocess.run([sys.executable, str(sb_script), "--search", question])
    else:
        print("[WARN] second_brain.py not found for comparison")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="LightRAG test — parallel GraphRAG alongside Neo4j/ChromaDB"
    )
    parser.add_argument("--ingest",  action="store_true",
                        help="Ingest vault into LightRAG (slow, run after graph-index)")
    parser.add_argument("--limit",   type=int, default=None,
                        help="Limit ingestion to N most recent files (test mode)")
    parser.add_argument("--chat",    action="store_true",
                        help="Chat against LightRAG index")
    parser.add_argument("--compare", type=str, default=None,
                        help="Ask same question to LightRAG + second_brain side-by-side")
    args = parser.parse_args()

    if args.ingest:
        ingest(limit=args.limit)
    elif args.chat:
        chat()
    elif args.compare:
        compare(args.compare)
    else:
        parser.print_help()
        print("\nQuick start:")
        print("  1. pip install \"lightrag-hku[api]\"")
        print("  2. python lightrag_test.py --ingest --limit 20    # test with 20 files first")
        print("  3. python lightrag_test.py --chat                  # test quality")
        print("  4. python lightrag_test.py --compare \"how does attention work\"")
        print("  5. python lightrag_test.py --ingest               # full vault if happy")


if __name__ == "__main__":
    main()
