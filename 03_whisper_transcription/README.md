# Whisper Transcription Pipeline
Karl's Productivity OS — Project 3

Transcribe any audio or video file completely locally. No API key. No cost.
Outputs a full timestamped transcript + structured summary with action items,
saved directly into your Obsidian vault.

---

## Setup (one time, ~10 minutes + model download)

### 1. Install dependencies
```powershell
pip install openai-whisper requests watchdog
```

### 2. Install ffmpeg (required by Whisper)
```powershell
winget install ffmpeg
```
Then restart your terminal so ffmpeg is on your PATH.

### 3. First run downloads the Whisper model (~1.5GB for medium)
The model downloads automatically on first use. Just run it and wait.

---

## Usage

### Transcribe a single file
```powershell
python transcribe.py "C:\path\to\your\meeting.mp4"
```

### Transcript only (no summary)
```powershell
python transcribe.py recording.mp3 --transcript-only
```

### Skip saving to Obsidian
```powershell
python transcribe.py podcast.mp3 --no-obsidian
```

### Use a different Whisper model
```powershell
python transcribe.py meeting.mp4 --model large    # slower, more accurate
python transcribe.py voicememo.m4a --model small  # faster, less accurate
```

### Watch mode — drop files in Downloads/_review/ to auto-transcribe
```powershell
python transcribe.py --watch
```

---

## Output

Every file produces:

1. **Timestamped transcript** saved to `C:\Users\Karl\Documents\transcripts\`
2. **Obsidian note** saved to `Obsidian Vault\Transcripts\` with:
   - Summary
   - Key points
   - Action items (as checkboxes)
   - Decisions made
   - People mentioned
   - Topics
   - Full timestamped transcript

3. **SQLite log** entry in `transcripts.db` for future integration with the Task Brain

---

## Whisper Model Guide

| Model  | Size   | Speed      | Accuracy  | Best for |
|--------|--------|------------|-----------|----------|
| tiny   | 75MB   | Very fast  | Basic     | Quick voice memos |
| base   | 145MB  | Fast       | Good      | Clear audio |
| small  | 466MB  | Moderate   | Very good | Most use cases |
| medium | 1.5GB  | Slower     | Excellent | Meetings, podcasts |
| large  | 3GB    | Slow       | Best      | Accents, noisy audio |

Default is `medium` — best balance for meetings and podcast clips.

---

## Supported Formats

`.mp4` `.mp3` `.wav` `.m4a` `.mkv` `.mov` `.avi` `.webm` `.flac` `.aac` `.ogg`

---

## Integration with Productivity OS

- Audio files in `Downloads/_review/` are auto-detected in watch mode
- Action items are logged to `transcripts.db` — ready to feed into the Unified Task Brain (Project 13)
- Obsidian notes are tagged and dated for the Second Brain (Project 8)
