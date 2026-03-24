# Obsidian Second Brain
Karl's Productivity OS — Project 8

Chat with your entire Obsidian vault using local AI. Ask questions, find
patterns, surface forgotten notes. Everything runs locally — your notes
never leave your machine.

---

## Setup (one time)

```powershell
pip install chromadb
ollama pull nomic-embed-text
ollama pull deepseek-r1:14b
```

---

## Usage

### Step 1 — Index your vault (run whenever you add new notes)
```powershell
python second_brain.py --index
```

### Step 2 — Chat
```powershell
python second_brain.py --chat
```

### Do both at once
```powershell
python second_brain.py --index --chat
```

### Quick search (no chat, just see matching chunks)
```powershell
python second_brain.py --search "China tech industry"
```

### Check index stats
```powershell
python second_brain.py --stats
```

### Force re-index everything (if notes changed significantly)
```powershell
python second_brain.py --index --force
```

---

## Example questions to ask

- *"What did the China tech interview say about open source culture?"*
- *"What action items am I sitting on across all my notes?"*
- *"What topics have I been researching most this month?"*
- *"What patterns do you see in my browser reports?"*
- *"What decisions have I made recently?"*
- *"Summarize everything I know about NFL analytics"*

---

## How it works

1. **Indexing** — reads every `.md` file in your vault, splits into overlapping chunks, converts each chunk to a vector embedding using `nomic-embed-text`, stores in ChromaDB locally
2. **Query** — your question gets embedded the same way, ChromaDB finds the most similar chunks (cosine similarity)
3. **Answer** — top matching chunks are sent to `deepseek-r1:14b` as context, which reasons over your actual notes to answer

## Chat commands
- `sources` — show which notes were used in the last response
- `clear` — reset conversation history
- `quit` — exit

---

## The compounding effect

The more notes in your vault, the better this gets:
- Transcripts from Whisper → searchable conversations
- Browser reports → searchable patterns
- Your own notes → searchable thinking
- Everything cross-referenced automatically

---

## Integration with Productivity OS

- Re-index automatically after Whisper saves new transcripts
- Feed action items into Unified Task Brain (Project 13)
- Powers the Daily Briefing (Project 11) with vault-aware context
