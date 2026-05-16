#!/usr/bin/env python3
"""
wiki_batch.py — Batch Web Digest Ingestion
Loom — Project 20 utility

Reads a text file of URLs (one per line) and runs web_digest.py
on each one sequentially. Saves progress after each URL so you can
stop/resume at any time without losing work.

Usage:
    python wiki_batch.py topics/rag_and_knowledge.txt --free
    python wiki_batch.py topics/rag_and_knowledge.txt --free --resume
    python wiki_batch.py topics/rag_and_knowledge.txt --free --dry-run
    python wiki_batch.py topics/rag_and_knowledge.txt --free --reset

Checkpoint: a .progress file is saved next to the topic file.
--resume   skips URLs already completed (default behavior on restart)
--reset    clears checkpoint and starts from scratch
"""

import sys
import time
import json
import subprocess
from pathlib import Path
from datetime import datetime


def load_urls(filepath: str) -> list:
    """Load URLs from file, skipping comments and blank lines."""
    urls = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            urls.append(line)
    return urls


def checkpoint_path(filepath: str) -> Path:
    return Path(filepath).with_suffix(".progress")


def load_checkpoint(filepath: str) -> set:
    """Load set of already-completed URLs."""
    cp = checkpoint_path(filepath)
    if cp.exists():
        try:
            data = json.loads(cp.read_text())
            return set(data.get("completed", []))
        except Exception:
            pass
    return set()


def save_checkpoint(filepath: str, completed: set):
    """Save completed URLs to checkpoint file."""
    cp = checkpoint_path(filepath)
    cp.write_text(json.dumps({"completed": list(completed)}, indent=2))


def clear_checkpoint(filepath: str):
    cp = checkpoint_path(filepath)
    if cp.exists():
        cp.unlink()
        print(f"  Checkpoint cleared: {cp}")


def run_digest(url: str, free: bool, max_comments: int) -> bool:
    """Run web_digest.py for a single URL. Returns True on success."""
    script = Path(__file__).parent / "web_digest.py"
    cmd = ["python", str(script), url, str(max_comments)]
    if free:
        cmd.append("--free")

    try:
        result = subprocess.run(
            cmd,
            timeout=600,
            text=True,
            capture_output=False,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"\n  [TIMEOUT] {url}")
        return False
    except Exception as e:
        print(f"\n  [ERROR] {url}: {e}")
        return False


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Batch web digest ingestion")
    parser.add_argument("file", help="Text file with URLs, one per line")
    parser.add_argument("--free", action="store_true",
                        help="Use Claude Code (free via Max plan)")
    parser.add_argument("--max-comments", type=int, default=400,
                        help="Max comments to fetch for threads (default: 400)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print URLs that would be processed without running")
    parser.add_argument("--delay", type=int, default=5,
                        help="Seconds to wait between digests (default: 5)")
    parser.add_argument("--resume", action="store_true",
                        help="Skip already-completed URLs (default on restart)")
    parser.add_argument("--reset", action="store_true",
                        help="Clear checkpoint and start from scratch")
    args = parser.parse_args()

    # Handle --reset
    if args.reset:
        clear_checkpoint(args.file)

    urls = load_urls(args.file)
    if not urls:
        print(f"No URLs found in {args.file}")
        sys.exit(1)

    # Load checkpoint — always skip completed unless --reset was used
    completed = load_checkpoint(args.file)
    pending   = [u for u in urls if u not in completed]
    skipping  = len(urls) - len(pending)

    mode = "FREE (Claude Code)" if args.free else "PAID (Claude API)"
    print(f"\n{'='*60}")
    print(f"  Batch Web Digest")
    print(f"  File:      {args.file}")
    print(f"  Total:     {len(urls)} URLs")
    print(f"  Done:      {skipping} (already completed)")
    print(f"  Remaining: {len(pending)}")
    print(f"  Mode:      {mode}")
    print(f"{'='*60}\n")

    if skipping > 0:
        print(f"  Skipping {skipping} already-completed URLs.")
        print(f"  Run with --reset to start over from scratch.\n")

    if not pending:
        print("  All URLs already completed! Nothing to do.")
        print(f"  Run with --reset to reprocess everything.")
        return

    if args.dry_run:
        print("DRY RUN — URLs that would be processed:")
        for i, url in enumerate(pending, 1):
            status = "✓ done" if url in completed else "→ pending"
            print(f"  {i:3}. [{status}] {url}")
        return

    results  = {"success": [], "failed": []}
    start_time = datetime.now()

    for i, url in enumerate(pending, 1):
        print(f"\n{'─'*60}")
        print(f"[{i}/{len(pending)}] {url}")
        print(f"{'─'*60}")

        success = run_digest(url, args.free, args.max_comments)

        if success:
            results["success"].append(url)
            completed.add(url)
            save_checkpoint(args.file, completed)  # save after every success
        else:
            results["failed"].append(url)

        if i < len(pending):
            print(f"\n  Waiting {args.delay}s before next URL...")
            time.sleep(args.delay)

    # Summary
    elapsed = datetime.now() - start_time
    print(f"\n{'='*60}")
    print(f"  BATCH COMPLETE")
    print(f"  Time elapsed:  {elapsed}")
    print(f"  Succeeded:     {len(results['success'])}/{len(pending)}")
    print(f"  Total done:    {len(completed)}/{len(urls)}")
    if results["failed"]:
        print(f"  Failed (will retry on next run):")
        for url in results["failed"]:
            print(f"    - {url}")
    print(f"\n  Run 'python second_brain.py --index' to make everything queryable.")
    if results["failed"]:
        print(f"  Re-run this command to retry failed URLs automatically.")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
