"""
Screenshots Index → Obsidian Markdown
Karl's Productivity OS — Screenshot Organizer Utility

Converts index.csv (from organize_screenshots.py) into a searchable
markdown file in your Obsidian vault, ready to be indexed by second_brain.py.

Groups entries by month so the second brain can retrieve by time period.
Each screenshot becomes a single searchable line with date, description, tags, and path.

Usage:
    python screenshots_to_md.py                    # convert and save to Obsidian
    python screenshots_to_md.py --stats            # just print summary stats
    python screenshots_to_md.py --month 2026-03    # convert single month only
"""

import csv
import sys
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

INDEX_CSV      = Path(r"C:\Users\Karl\Documents\ShareX\index.csv")
OBSIDIAN_VAULT = Path(r"C:\Users\Karl\Documents\Obsidian Vault")
OUTPUT_FOLDER  = OBSIDIAN_VAULT / "Screenshots"   # subfolder in vault

# ─────────────────────────────────────────────
# READ CSV
# ─────────────────────────────────────────────

def load_index(csv_path: Path) -> list[dict]:
    if not csv_path.exists():
        print(f"[ERROR] index.csv not found: {csv_path}")
        sys.exit(1)
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows

def group_by_month(rows: list[dict]) -> dict:
    """Group rows by YYYY-MM."""
    groups = defaultdict(list)
    for row in rows:
        date = row.get("date", "")
        month = date[:7] if len(date) >= 7 else "unknown"
        groups[month].append(row)
    return dict(sorted(groups.items()))

# ─────────────────────────────────────────────
# BUILD MARKDOWN
# ─────────────────────────────────────────────

def build_month_note(month: str, rows: list[dict]) -> str:
    """
    Build a markdown note for one month's worth of screenshots.
    Each row becomes a searchable entry.
    """
    try:
        dt = datetime.strptime(month, "%Y-%m")
        month_label = dt.strftime("%B %Y")
    except ValueError:
        month_label = month

    # Collect all unique tags for frontmatter
    all_tags = set()
    for row in rows:
        for tag in row.get("tags", "").split(","):
            t = tag.strip().lower().replace(" ", "-")
            if t:
                all_tags.add(t)

    top_tags = sorted(all_tags)[:15]
    tag_str = "\n".join(f"  - {t}" for t in top_tags)

    note = f"""---
title: "Screenshots — {month_label}"
month: {month}
screenshot_count: {len(rows)}
type: screenshot-index
tags:
  - screenshots
  - screenshot-index
{tag_str}
---

# Screenshots — {month_label}

> **{len(rows)} screenshots** captured in {month_label}.
> Indexed by LLaVA vision model. Search by description, tags, or filename.

---

"""
    # Group by week for easier scanning
    weeks = defaultdict(list)
    for row in rows:
        date = row.get("date", "")
        try:
            d = datetime.strptime(date, "%Y-%m-%d")
            week = d.isocalendar()[1]
            week_label = f"Week {week} — {d.strftime('%b %-d')}"
        except (ValueError, AttributeError):
            # Windows doesn't support %-d, fallback
            try:
                d = datetime.strptime(date, "%Y-%m-%d")
                week = d.isocalendar()[1]
                week_label = f"Week {week} — {d.strftime('%b')} {d.day}"
            except Exception:
                week_label = "Unknown week"
        weeks[week_label].append(row)

    for week_label in sorted(weeks.keys()):
        week_rows = weeks[week_label]
        note += f"## {week_label} ({len(week_rows)} screenshots)\n\n"
        for row in week_rows:
            date      = row.get("date", "")
            desc      = row.get("description", "").strip()
            tags      = row.get("tags", "").strip()
            new_name  = row.get("new_name", "").strip()
            path      = row.get("path", "").strip()
            folder    = row.get("folder", "").strip()

            # Format tags as inline list
            tag_list = " · ".join(t.strip() for t in tags.split(",") if t.strip())

            note += f"- **{date}** — {desc}  \n"
            note += f"  `{new_name}` | {tag_list}  \n"
            note += f"  path: `{path}`\n\n"

    return note

# ─────────────────────────────────────────────
# STATS
# ─────────────────────────────────────────────

def print_stats(rows: list[dict]):
    groups = group_by_month(rows)
    all_tags = defaultdict(int)
    for row in rows:
        for tag in row.get("tags", "").split(","):
            t = tag.strip().lower()
            if t:
                all_tags[t] += 1

    print(f"\n  Screenshot Index Stats")
    print(f"  {'─'*40}")
    print(f"  Total screenshots: {len(rows)}")
    print(f"\n  By month:")
    for month, month_rows in groups.items():
        try:
            dt = datetime.strptime(month, "%Y-%m")
            label = dt.strftime("%B %Y")
        except ValueError:
            label = month
        print(f"    {label:<20} {len(month_rows):>5} screenshots")

    print(f"\n  Top 15 tags:")
    for tag, count in sorted(all_tags.items(), key=lambda x: -x[1])[:15]:
        print(f"    {tag:<30} {count:>4}x")
    print()

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def run(month_filter: str = None):
    print(f"\n  Screenshots → Obsidian Markdown Converter")
    print(f"  {'─'*40}")

    rows = load_index(INDEX_CSV)
    print(f"  Loaded {len(rows)} entries from index.csv")

    groups = group_by_month(rows)
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    if month_filter:
        if month_filter not in groups:
            print(f"[ERROR] Month '{month_filter}' not found in index.")
            print(f"  Available: {', '.join(groups.keys())}")
            sys.exit(1)
        groups = {month_filter: groups[month_filter]}

    saved = []
    for month, month_rows in groups.items():
        note = build_month_note(month, month_rows)
        filename = f"Screenshots {month}.md"
        out_path = OUTPUT_FOLDER / filename
        out_path.write_text(note, encoding="utf-8")
        saved.append((month, len(month_rows), out_path))
        print(f"  ✓ {filename} ({len(month_rows)} screenshots)")

    print(f"\n  Saved {len(saved)} notes to: {OUTPUT_FOLDER}")
    print(f"\n  Next step — re-index your Second Brain:")
    print(f"    python second_brain.py --index")
    print(f"\n  Then search like:")
    print(f'    python second_brain.py --search "fantasy sports dashboard"')
    print(f'    python second_brain.py --search "terminal error march"')
    print(f'    python second_brain.py --search "NTI scouting tool screenshot"')
    print()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert screenshot index to Obsidian markdown")
    parser.add_argument("--stats", action="store_true", help="Print index stats only")
    parser.add_argument("--month", type=str, help="Convert single month only (e.g. 2026-03)")
    args = parser.parse_args()

    rows = load_index(INDEX_CSV)

    if args.stats:
        print_stats(rows)
    else:
        run(month_filter=args.month)
