# Topics — Wikipedia Batch Ingestion Lists

All files in this folder are URL lists for wiki_batch.py.
Run any of them to ingest that topic cluster into your Obsidian vault.

---

## How to run

```powershell
cd C:\Users\Karl\Documents\productivity-os\20_web_digest

# Dry run first to see what's queued
python wiki_batch.py topics/rag_and_knowledge.txt --free --dry-run

# Actually run it
python wiki_batch.py topics/rag_and_knowledge.txt --free
```

---

## Topic Files (run in this order for maximum knowledge compounding)

### Tier 1 — Most relevant to what you're building RIGHT NOW
| File | Articles | Description |
|---|---|---|
| `rag_and_knowledge.txt` | 27 | RAG, knowledge graphs, vector DBs, PKM — directly what you're building |
| `llm_internals.txt` | 25 | How LLMs actually work under the hood |
| `ai_agents.txt` | 27 | Agents, planning, memory, tool use — the frontier |

### Tier 2 — Deep foundations that make everything else make sense
| File | Articles | Description |
|---|---|---|
| `ml_foundations.txt` | 33 | Core ML concepts — transformers, RL, safety |
| `cs_theory.txt` | 35 | Complexity, information theory, algorithms, linear algebra |
| `data_science.txt` | 26 | Statistics, causal inference, evaluation — how to measure things |

### Tier 3 — Elite developer knowledge
| File | Articles | Description |
|---|---|---|
| `software_engineering.txt` | 30 | Design patterns, system design, code quality |
| `systems_and_devtools.txt` | 31 | Version control, browsers, networking, security |
| `future_of_computing.txt` | 25 | Quantum, neuromorphic, decentralized, privacy |

### Tier 4 — Bigger picture thinking
| File | Articles | Description |
|---|---|---|
| `multimodal_ai.txt` | 24 | Vision, audio, generative models, robotics |
| `ai_safety.txt` | 25 | Alignment, interpretability, governance, existential risk |
| `cognitive_science.txt` | 26 | How intelligence actually works — bio and artificial |
| `philosophy_of_tech.txt` | 26 | Epistemology, ethics, systems thinking, history |
| `economics_and_markets.txt` | 20 | Network effects, platform dynamics, data economy |

---

## Total: ~380 Wikipedia articles across 14 topic clusters

That's a comprehensive foundation layer for anyone wanting to be at the
cutting edge of AI/ML/systems. Combined with your HN thread digests,
research papers, and transcripts — this becomes a genuinely powerful
second brain.

---

## The Wikipedia graph idea

Wikipedia is already a knowledge graph — every article links to dozens
of others. A future enhancement: given a seed topic, automatically
crawl all linked Wikipedia articles to a depth of 2-3 hops.

Example: "Transformer (machine learning)" links to:
- Attention mechanism → links to Memory network, Neural Turing Machine
- Positional encoding → links to Fourier transform, Embedding
- BERT → links to Pre-training, Masked language model

A crawl from one seed article could yield 50-100 highly related articles
automatically, without manually curating the list. This is on the roadmap.
