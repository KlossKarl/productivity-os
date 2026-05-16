# loom

> I built this because I kept losing things I had already read.

A local-first personal knowledge base. It ingests audio, PDFs, web threads, browser history, and markdown notes, indexes everything with vector search and a knowledge graph, and lets you chat with all of it through a local LLM. No cloud, no subscriptions, your data stays on your machine.

Most local RAG tools just embed chunks and hope. loom builds an entity-resolved, relation-typed knowledge graph and uses an adaptive router to decide when to hit vectors vs graph. That lets it answer structural cross-document questions that pure vector systems can't express.

---

## What it actually does

Drop a file into the intake folder. It routes itself.

```
lecture.mp3          ->  Whisper transcription -> vault -> indexed
paper.pdf            ->  PDF to markdown -> vault -> indexed
thread.txt           ->  Web digest -> structured note -> vault -> indexed  
https://...url       ->  Same as above
note.md              ->  Copied directly to vault -> indexed
```

Then ask questions:

```
> what did the stanford cs229 lecture say about attention mechanisms?
> compare the risk frameworks across my last 5 papers
> what connects OODA loop to predictive coding?
> find everything I've read about CLO structures
```

Retrieves from ChromaDB (vector search), traverses Neo4j (knowledge graph), generates answers using a local LLM. Everything runs on your hardware.

---

## Architecture

```
intake/                     <- drop anything here
    |
intake_watcher.py           <- watches folder, routes by file type
    |
+--------------------------------------------------+
|  transcribe.py   pdf_to_md.py   web_digest.py   |
|        Whisper      pymupdf        Claude Code   |
+--------------------------------------------------+
    |
Obsidian Vault              <- all content lands here as markdown
    |
second_brain.py --index     <- chunks + embeds into ChromaDB
second_brain.py --graph     <- extracts entities/relationships into Neo4j
    |
second_brain.py --chat      <- hybrid retrieval: vector + graph + HyDE + rerank
```

---

## What's actually different

A few specific things, since "local-first RAG" is a crowded space.

**Constrained typed relationships, not LLM-emergent slop.** The Neo4j schema uses a fixed set of relationship types: CITES, INFLUENCES, EXTENDS, CONTRASTS_WITH, POSSIBLY_SAME_AS, and CO_OCCURS_WITH. Anything the LLM tries to emit outside that set gets rewritten to POSSIBLY_SAME_AS or dropped. This is more restrictive than letting the model invent edge types, but the graph stays coherent at scale instead of fragmenting into thousands of one-off predicate names. The validation happens at the graph write layer, not just in the prompt.

**Entity resolution with canonical keys + aliases.** "PAC-learning", "PAC learning", and "pac learning" all collapse to the same canonical key in the graph, with the original surface forms preserved as Alias nodes linked via HAS_ALIAS. This handles the entity dedup problem most LLM-extracted graphs ignore. Without it, the graph fills with near-duplicate nodes and cross-document traversal breaks down.

**Agentic routing, not blind hybrid retrieval.** Most personal RAG tools run the same retrieval pipeline regardless of query type. This one classifies the query first (semantic, relational, or hybrid), routes to the appropriate store (ChromaDB, Neo4j, or both), then runs a sufficiency check and loops up to 3 times if context is insufficient. The router falls back to vector if graph comes up empty, or expands into graph if vector results don't answer the question. The route taken is logged so you can see how the system is thinking.

**Cross-document queries vector search cannot answer.** Because entities are shared nodes across documents, you can traverse Document -> Chunk -> Entity <- Chunk <- Document to find pairs of documents that both reference the same concept. That's a single Cypher traversal. Pure vector RAG cannot answer this structurally no matter how big the context window gets.

---

## Requirements

Be honest with yourself about this list before starting.

- **Python 3.10+**
- **[Ollama](https://ollama.ai)** - local LLM inference
  - `ollama pull deepseek-r1:14b` (~9GB, used for chat + graph extraction)
  - `ollama pull mxbai-embed-large` (~670MB, used for embeddings)
- **[Neo4j Desktop](https://neo4j.com/download/)** - knowledge graph database
  - Free, but requires manual setup (see below)
- **[Obsidian](https://obsidian.md)** - vault is just a folder of markdown, Obsidian is optional but recommended
- **[Claude Code](https://claude.ai/code)** - used for free-tier web digest processing (optional but recommended)
- Decent hardware. 16GB RAM minimum. A GPU with 8GB+ VRAM makes graph indexing significantly faster.

---

## Installation

```bash
git clone https://github.com/KlossKarl/loom
cd loom
pip install -r requirements.txt
```

Copy and fill in the config:

```bash
cp config.template.yaml config.yaml
# edit config.yaml with your paths
```

**Neo4j setup** (annoying but only once):

1. Install Neo4j Desktop
2. Create a new Project, add a Local DBMS
3. Set a password, start the instance
4. Put the password in `config.yaml` under `second_brain.neo4j_password`

---

## config.yaml reference

```yaml
paths:
  obsidian_vault: C:\Users\you\Documents\Obsidian Vault
  chroma_dir: C:\Users\you\Documents\second_brain_db

second_brain:
  vaults:
    - C:\Users\you\Documents\Obsidian Vault
  
  embed_model: mxbai-embed-large
  chat_model: deepseek-r1:14b
  
  neo4j_uri: neo4j://127.0.0.1:7687
  neo4j_password: yourpassword
  
  # customize entity types for your domain
  entity_types:
    - Person
    - Concept
    - Method
    - Paper
    - Organization
    - Dataset

intake:
  folder: C:\Users\you\Documents\loom\intake
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

Or use the system tray app if you want something that lives in the taskbar:

```bash
pip install pystray pillow tkinterdnd2
python intake_tray.py
```

Drop files into `intake/`. They get processed and land in your vault automatically.

### Manual commands

```bash
# index vault into ChromaDB
python 08_second_brain/second_brain.py --index

# force full re-index
python 08_second_brain/second_brain.py --index --force

# build the knowledge graph in Neo4j (slow on large vaults, run overnight)
python 08_second_brain/second_brain.py --graph-index

# check what's indexed
python 08_second_brain/second_brain.py --stats

# chat
python 08_second_brain/second_brain.py --chat

# search without chat
python 08_second_brain/second_brain.py --search "attention mechanism"
```

### Web digests

```bash
python 20_web_digest/web_digest.py https://news.ycombinator.com/item?id=12345 400 --free
```

### Transcription

```bash
python 03_transcribe/transcribe.py lecture.mp3 --summarizer claude
```

### Wiki batch

Build a knowledge base on any topic from the included topic files:

```bash
python 20_web_digest/wiki_batch.py topics/ai_frontier.txt --free
python 20_web_digest/wiki_batch.py topics/quant_finance.txt --free
```

### Research papers and other sources

```bash
# arXiv papers by search query or ID
python 20_web_digest/arxiv_batch.py --query "retrieval augmented generation" --max 20
python 20_web_digest/arxiv_batch.py --ids 1706.03762 2005.11401

# Stanford Encyclopedia of Philosophy
python 20_web_digest/sep_batch.py --topics topics/sep_philosophy.txt

# Project Gutenberg classics
python 20_web_digest/gutenberg_batch.py --classics art-of-war meditations republic

# technical docs
python 20_web_digest/docs_batch.py --docs python neo4j anthropic

# LessWrong posts
python 20_web_digest/lesswrong_batch.py --tag "AI" --limit 30

# legal/finance papers
python 20_web_digest/ssrn_batch.py --curated legal
python 20_web_digest/sec_edgar_batch.py --rules ia
python 20_web_digest/irs_batch.py --category partnerships
```

---

## Pre-built topic packs

Run any of these with `wiki_batch` and you have a structured knowledge base on that domain in a few hours. All free via Claude Code.

| File | Domain | Articles |
|------|--------|----------|
| `topics/ai_frontier.txt` | LLMs, agents, alignment, compute | ~55 |
| `topics/quant_finance.txt` | Options, HFT, ML in finance | ~75 |
| `topics/mathematics.txt` | Analysis, linear algebra, optimization | ~45 |
| `topics/physics.txt` | Classical to quantum to theoretical | ~80 |
| `topics/biology.txt` | Cell to organism to ecosystem | ~55 |
| `topics/evolution.txt` | Darwin to evo-devo to cultural evolution | ~50 |
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

In `--chat` mode you can toggle retrieval strategies mid-conversation:

```
/hyde      - hypothetical document embeddings (better query expansion)
/expand    - query expansion
/rerank    - cross-encoder reranking of results
/graph     - include Neo4j knowledge graph traversal
/model     - switch LLM
```

All four are on by default. Turn them off if you want faster responses.

---

## Why local-first

Privacy is the main thing. Research that isn't published yet, client work, personal notes, anything confidential stays on your machine. There's no document limit either, so you can index your entire working history rather than 50 files at a time. And once the graph index runs, you can ask questions that span hundreds of documents in ways that pure vector search can't handle.

The tradeoff is real though. Setup takes time and you need decent hardware. This isn't a consumer product.

---

## Known issues

- Windows-primary. Paths use `Path()` throughout so it should work elsewhere but hasn't been tested. PRs welcome.
- Ollama throws 500 errors under heavy embedding load. There's retry logic but it's noticeable on large index runs. Replacing with in-process sentence-transformers is on the roadmap.
- Graph indexing is slow on large vaults, roughly 0.5 seconds per chunk. For a vault with thousands of files this means running overnight.
- No web UI. Everything is command line or the intake tray app.

---

## Roadmap

- [ ] **Argument layer**: extract claims, evidence, and debate structure into the graph (supports/contradicts/refines relationships between assertions, not just entities)
- [ ] Replace Ollama HTTP embeddings with in-process sentence-transformers (kills the 500 errors)
- [ ] LightRAG integration as alternative graph layer
- [ ] Graph-native query primitives: co-reference explorer, bridge finder, relational filter
- [ ] `--entities` CLI flag to inspect canonical entities, aliases, and document counts
- [ ] Graph visualization UI
- [ ] Mac/Linux testing and fixes
- [ ] One-command installer
- [ ] Browser extension for web digest
- [ ] Export and share pre-built domain graphs

---

## Project structure

```
loom/
├── 03_whisper_transcription/   # audio/video to markdown
├── 08_second_brain/            # core: index, chat, graph
├── 20_web_digest/              # all ingestion scripts + topic files
├── personal_tools/             # personal tracking tools, separate from core
├── intake_watcher.py           # folder watcher
├── intake_tray.py              # system tray app (Windows)
├── lightrag_test.py            # LightRAG experiment
├── config.yaml                 # your config (gitignored)
└── config.template.yaml        # starting point
```

---

## Contributing

Started as something I built for myself. Issues and PRs welcome, especially for Mac/Linux compatibility, new topic packs, or alternative embedding backends.

---

## License

MIT
