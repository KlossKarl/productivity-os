# productivity-os

A local-first personal knowledge base. Ingests audio, PDFs, web threads, and markdown. Indexes with ChromaDB (vector) + Neo4j (graph). Chat via local LLM.

## Architecture

```
intake/ folder
    ↓ intake_watcher.py (routes by file type)
    ↓
03_whisper_transcription/   — audio/video → markdown via Whisper
20_web_digest/              — URLs, HN threads, Wikipedia, arXiv, etc → markdown
    ↓
Obsidian Vault (markdown files)
    ↓
08_second_brain/second_brain.py
    --index       → ChromaDB (vector search, mxbai-embed-large via Ollama)
    --graph-index → Neo4j (entity extraction, typed relationships)
    --chat        → hybrid retrieval: vector + graph + HyDE + rerank
```

## Project Layout

```
08_second_brain/second_brain.py  — core engine: index, graph, chat, search, stats
20_web_digest/                   — all ingestion scripts (wiki_batch, web_digest, arxiv_batch, etc.)
20_web_digest/topics/            — URL lists for wiki_batch (one URL per line)
03_whisper_transcription/        — Whisper transcription + Claude summarizer
intake_watcher.py                — folder watcher, auto-routes files to pipelines
intake_tray.py                   — Windows system tray UI for intake_watcher
lightrag_test.py                 — LightRAG parallel graph experiment (not production)
config.yaml                      — all config (gitignored, never commit)
config.template.yaml             — safe template for new users
personal_tools/                  — personal lifestyle tracking tools, not core product
```

## Config

All paths, credentials, and model choices live in `config.yaml` at project root.
Load it with: `yaml.safe_load(open(PROJECT_ROOT / "config.yaml"))`

Key config paths:
- `second_brain.vaults[0]` — Obsidian vault path (where processed markdown lands)
- `paths.chroma_dir` — ChromaDB storage location
- `second_brain.neo4j_*` — Neo4j connection
- `anthropic.api_key` — Anthropic API key
- `ollama.url` — Ollama base URL (default http://localhost:11434)
- `second_brain.embed_model` — embedding model (default mxbai-embed-large)
- `second_brain.chat_model` — chat model (default deepseek-r1:14b)
- `second_brain.entity_types` — list of entity types for graph extraction (customizable)
- `intake.*` — intake folder path and options

## Common Commands

```bash
# Index vault into ChromaDB
python 08_second_brain/second_brain.py --index

# Force full re-index
python 08_second_brain/second_brain.py --index --force

# Build Neo4j knowledge graph (slow, run overnight for large vaults)
python 08_second_brain/second_brain.py --graph-index

# Check stats
python 08_second_brain/second_brain.py --stats

# Chat
python 08_second_brain/second_brain.py --chat

# Run intake watcher
python intake_watcher.py

# Run system tray app (Windows)
python intake_tray.py

# Wiki batch (one URL topic file)
python 20_web_digest/wiki_batch.py topics/ai_frontier.txt --free

# arXiv papers
python 20_web_digest/arxiv_batch.py --query "retrieval augmented generation" --max 20

# SEP philosophy
python 20_web_digest/sep_batch.py --topics topics/sep_philosophy.txt

# Gutenberg classics
python 20_web_digest/gutenberg_batch.py --classics art-of-war meditations republic

# Technical docs
python 20_web_digest/docs_batch.py --docs python neo4j anthropic

# LessWrong posts
python 20_web_digest/lesswrong_batch.py --tag "AI" --limit 30

# SEC regulatory docs
python 20_web_digest/sec_edgar_batch.py --rules all

# IRS publications
python 20_web_digest/irs_batch.py --category partnerships
```

## Coding Conventions

- All scripts load config via `yaml.safe_load(open(CONFIG_PATH))` — CONFIG_PATH is always `PROJECT_ROOT / "config.yaml"`
- PROJECT_ROOT is always `Path(__file__).parent` or `Path(__file__).parent.parent` depending on script location
- Vault path always comes from `cfg['second_brain']['vaults'][0]`
- Progress tracking uses `.done` text files in `20_web_digest/raw/{source}_done/` — one completed ID per line
- Output files: `vault/SubFolder/YYYY-MM-DD Title.md`
- All new ingestion scripts follow the same pattern: fetch → clean → markdown → save to vault → mark done
- Delay between requests: always include a `time.sleep(DELAY)` between external API calls. Default 2-3s for web scraping, 3s for arXiv (their requirement)
- Chunk/file caps: respect `max_chunks_per_file` from config (default 200) to prevent OOM

## Embedding + Graph

- Embeddings: Ollama HTTP calls to `mxbai-embed-large`. Known issue: 500 errors under load, mitigated with retry logic + 0.15s sleep between chunks. Project 37 = replace with in-process sentence-transformers to fix permanently.
- Graph extraction: `_extract_entities()` in second_brain.py — LLM prompt returns JSON `{entities, relationships}`. Entity types are configurable via `second_brain.entity_types` in config.
- Valid relationship types: `CITES | INFLUENCES | EXTENDS | CONTRASTS_WITH | POSSIBLY_SAME_AS | CO_OCCURS_WITH`
- Graph checkpoint: `.graph_checkpoint.json` in `08_second_brain/` — supports pause/resume with Ctrl+C

## Do Not

- Never commit `config.yaml` — it contains API keys and personal paths
- Never run `--graph-index` while `--index --force` is running — both hammer the LLM simultaneously
- Never modify files inside `personal_tools/` as part of core product work
- Don't hardcode vault paths — always read from config
- Don't run wiki_batch on a topic file that's already in progress in another terminal

## Key Dependencies

```
chromadb          — vector store
neo4j             — graph database driver  
requests          — HTTP (used everywhere)
beautifulsoup4    — HTML parsing for web scrapers
pyyaml            — config loading
watchdog          — intake folder watcher
pystray + pillow  — system tray app
tkinterdnd2       — drag-and-drop in tray app
openai-whisper    — transcription
pymupdf (fitz)    — PDF text extraction
```

## Active Projects / Known Issues

- **Project 37**: Replace Ollama embed HTTP calls with in-process `sentence-transformers` — eliminates 500 errors. Needs changes to `embed()` function in second_brain.py.
- **LightRAG test**: `lightrag_test.py` is a parallel experiment — run after graph-index completes, use `--ingest --limit 20` first to test quality before full vault ingest.
- **Max chunks cap**: Default 200 chunks/file. Raise `max_chunks_per_file` in config for large PDFs (textbooks, long papers).
- **Windows paths**: Project is Windows-primary. Path separators use `Path()` throughout — should be cross-platform but untested on Mac/Linux.
