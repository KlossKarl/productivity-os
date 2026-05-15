# productivity-os

> I built this because I kept losing things I had already read.

A local-first personal knowledge base that ingests everything — audio, PDFs, web threads, browser history, markdown notes — indexes it with vector search and a knowledge graph, and lets you chat with all of it through a local LLM. No cloud. No subscriptions. Your data stays on your machine.

---

## What it actually does

Drop a file into the intake folder. It routes itself.

```
lecture.mp3          →  Whisper transcription → vault → indexed
paper.pdf            →  PDF to markdown → vault → indexed
thread.txt           →  Web digest → structured note → vault → indexed  
https://...url       →  Same as above
note.md              →  Copied directly to vault → indexed
```

Then ask questions:

```
> what did the stanford cs229 lecture say about attention mechanisms?
> compare the risk frameworks across my last 5 papers
> what connects OODA loop to predictive coding?
> find everything I've read about CLO structures
```

The system retrieves from ChromaDB (vector search), traverses Neo4j (knowledge graph), and generates answers using a local LLM. Everything runs on your hardware.

---

## Architecture

```
intake/                     ← drop anything here
    ↓
intake_watcher.py           ← watches folder, routes by file type
    ↓
┌─────────────────────────────────────────────────┐
│  transcribe.py   pdf_to_md.py   web_digest.py   │
│         Whisper     pymupdf        Claude Code   │
└─────────────────────────────────────────────────┘
    ↓
Obsidian Vault              ← all content lands here as markdown
    ↓
second_brain.py --index     ← chunks + embeds into ChromaDB
second_brain.py --graph     ← extracts entities/relationships into Neo4j
    ↓
second_brain.py --chat      ← hybrid retrieval: vector + graph + HyDE + rerank
```

---

## Requirements

Be honest with yourself about this list before starting.

- **Python 3.10+**
- **[Ollama](https://ollama.ai)** — local LLM inference
  - `ollama pull deepseek-r1:14b` (~9GB, used for chat + graph extraction)
  - `ollama pull mxbai-embed-large` (~670MB, used for embeddings)
- **[Neo4j Desktop](https://neo4j.com/download/)** — knowledge graph database
  - Free, but requires manual setup (see below)
- **[Obsidian](https://obsidian.md)** — vault is just a folder of markdown, Obsidian is optional but recommended
- **[Claude Code](https://claude.ai/code)** — used for free-tier web digest processing (optional but recommended)
- Decent hardware. 16GB RAM minimum. A GPU with 8GB+ VRAM makes the graph indexing significantly faster.

---

## Installation

```bash
git clone https://github.com/yourusername/productivity-os
cd productivity-os
pip install -r requirements.txt
```

Copy and edit the config:

```bash
cp config.example.yaml config.yaml
# Edit config.yaml with your paths (vault, downloads, chroma DB location)
```

**Neo4j setup** (the annoying part, do it once):

1. Install Neo4j Desktop
2. Create a new Project → Add → Local DBMS
3. Set a password, start the instance
4. Update `config.yaml` with your password under `second_brain.neo4j_password`

---

## config.yaml reference

```yaml
paths:
  obsidian_vault: C:\Users\you\Documents\Obsidian Vault   # where markdown lands
  chroma_dir: C:\Users\you\Documents\second_brain_db      # vector index storage

second_brain:
  vaults:
    - C:\Users\you\Documents\Obsidian Vault
  
  embed_model: mxbai-embed-large    # Ollama embedding model
  chat_model: deepseek-r1:14b       # Ollama chat model
  
  neo4j_uri: neo4j://127.0.0.1:7687
  neo4j_password: yourpassword
  
  # Custom entity types for your domain — add whatever fits
  entity_types:
    - Person
    - Concept
    - Method
    - Paper
    - Organization
    - Dataset

intake:
  folder: C:\Users\you\Documents\productivity-os\intake
  auto_index: true
  web_digest_free: true    # true = Claude Code (free), false = Anthropic API
```

---

## Usage

### The intake system (recommended)

Run the watcher once and forget about it:

```bash
python intake_watcher.py
```

Or use the system tray app:

```bash
pip install pystray pillow tkinterdnd2
python intake_tray.py
```

Drop files into the `intake/` folder. They process automatically and land in your vault.

### Manual commands

```bash
# Index your vault into ChromaDB (vector search)
python 08_second_brain/second_brain.py --index

# Force full re-index (after adding many files)
python 08_second_brain/second_brain.py --index --force

# Build the knowledge graph in Neo4j (slow, run overnight for large vaults)
python 08_second_brain/second_brain.py --graph-index

# Check what's indexed
python 08_second_brain/second_brain.py --stats

# Chat with your vault
python 08_second_brain/second_brain.py --chat

# Search without chat
python 08_second_brain/second_brain.py --search "attention mechanism"
```

### Web digests

Process a URL directly:

```bash
python 20_web_digest/web_digest.py https://news.ycombinator.com/item?id=12345 400 --free
```

### Transcription

```bash
python 03_transcribe/transcribe.py lecture.mp3 --summarizer claude
```

### Wiki batch (pre-built knowledge bases)

Build a knowledge base on any topic by running a batch of Wikipedia articles:

```bash
python 20_web_digest/wiki_batch.py topics/ai_frontier.txt --free
python 20_web_digest/wiki_batch.py topics/quant_finance.txt --free
```

---

## Pre-built topic packs

Drop one of these into `wiki_batch` and you have a structured knowledge base on that domain in a few hours. All free via Claude Code.

| File | Domain | Articles |
|------|--------|----------|
| `topics/ai_frontier.txt` | LLMs, agents, alignment, compute | ~55 |
| `topics/quant_finance.txt` | Options, HFT, ML in finance | ~75 |
| `topics/mathematics.txt` | Analysis, linear algebra, optimization | ~45 |
| `topics/physics.txt` | Classical → quantum → theoretical | ~80 |
| `topics/biology.txt` | Cell → organism → ecosystem | ~55 |
| `topics/evolution.txt` | Darwin → evo-devo → cultural evolution | ~50 |
| `topics/neuroscience_ai.txt` | Computational neuro + brain-AI bridges | ~50 |
| `topics/complex_systems.txt` | Emergence, chaos, network theory | ~40 |
| `topics/cs_theory.txt` | Algorithms, complexity, theory | ~60 |
| `topics/software_engineering.txt` | Systems, architecture, practices | ~55 |
| `topics/cryptography_security.txt` | Post-quantum, ZK proofs, adversarial ML | ~45 |
| `topics/computational_biology.txt` | AlphaFold era drug discovery | ~45 |
| `topics/medicine_ai.txt` | Clinical AI, precision medicine | ~50 |
| `topics/law_ai.txt` | IP, AI regulation, data privacy | ~50 |
| `topics/tax_law.txt` | Federal, corporate, partnership, international | ~45 |
| `topics/private_equity_funds.txt` | PE, private credit, BDC, CLO | ~45 |
| `topics/securities_regulation.txt` | SEC, investment adviser compliance | ~45 |
| `topics/mergers_acquisitions.txt` | Deal structure, diligence, documentation | ~45 |
| `topics/corporate_compliance.txt` | CCO stack: AML, sanctions, employment | ~45 |
| `topics/economics_macro.txt` | Macro, behavioral, complexity economics | ~45 |
| `topics/geopolitics.txt` | Power dynamics, tech competition | ~40 |
| `topics/climate_energy.txt` | Grid, carbon markets, AI + climate | ~40 |
| `topics/space_astrophysics.txt` | Cosmology, space tech, AI in astronomy | ~50 |
| `topics/weather_earth_systems.txt` | AI weather prediction, earth systems | ~45 |
| `topics/military_strategy.txt` | Art of War through autonomous weapons | ~45 |
| `topics/politics.txt` | Political theory, institutions, AI + democracy | ~50 |
| `topics/philosophy_mind.txt` | Consciousness, AGI, ethics | ~50 |
| `topics/nature.txt` | Patterns, remarkable organisms, natural systems | ~45 |

---

## Chat features

In `--chat` mode, toggle enhanced retrieval with slash commands:

```
/hyde      — hypothetical document embeddings (better query expansion)
/expand    — query expansion
/rerank    — cross-encoder reranking of results
/graph     — include Neo4j knowledge graph traversal
/model     — switch LLM
```

Default behavior uses all four. Toggle them off if you want faster/cheaper responses.

---

## Why local-first

- **Privacy**: Your unpublished research, confidential work, personal notes never leave your machine
- **No limits**: Index your entire career of notes, not 50 documents
- **No subscription**: Runs on hardware you own
- **Graph queries**: Ask how concepts connect across hundreds of documents — vector search alone can't do this

The tradeoff is setup complexity and hardware requirements. This is not a consumer product. Yet.

---

## Current limitations

- Windows-primary (paths and some scripts assume Windows; PRs for Mac/Linux welcome)
- Ollama under heavy embedding load throws intermittent 500 errors — mitigated with retry logic, but noticeable on large index runs
- Graph indexing is slow on large vaults (~0.5s per chunk, runs overnight for 10k+ chunks)
- No web UI — everything is CLI or the intake tray app

---

## Roadmap

- [ ] Replace Ollama HTTP embeddings with in-process `sentence-transformers` (eliminates 500 errors)
- [ ] LightRAG integration as alternative/parallel graph layer
- [ ] Graph visualization UI
- [ ] Mac/Linux path compatibility
- [ ] `setup.py` / one-command installer
- [ ] Browser extension for one-click web digest
- [ ] Export/share graph snapshots (pre-built domain graphs)

---

## Project structure

```
productivity-os/
├── 03_transcribe/          # Whisper transcription pipeline
├── 08_second_brain/        # Core: indexing, chat, graph (second_brain.py)
├── 20_web_digest/          # Web scraping, HN/Reddit/Wikipedia digests, wiki_batch
├── intake/                 # Drop files here
├── topics/                 # Pre-built wiki batch topic files
├── intake_watcher.py       # Folder watcher — routes files automatically
├── intake_tray.py          # System tray app (Windows)
├── lightrag_test.py        # LightRAG parallel graph experiment
├── config.yaml             # Your config (gitignored)
└── config.example.yaml     # Template
```

---

## Contributing

This started as a personal tool. Issues and PRs welcome, especially:

- Mac/Linux compatibility
- Additional topic pack files for domains not yet covered
- Alternative embedding backends
- Documentation improvements

---

## License

MIT
