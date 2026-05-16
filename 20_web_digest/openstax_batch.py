"""
OpenStax + MIT OCW Batch — Loom
Fetches free textbook chapters (OpenStax) and MIT OCW lecture notes.

OpenStax: Free peer-reviewed textbooks, fully online
MIT OCW: Free course materials from MIT — lecture notes, problem sets, readings

Usage:
    python openstax_batch.py --book "University Physics" --chapters 1-5
    python openstax_batch.py --ocw 6.006                    # MIT course number
    python openstax_batch.py --topics topics/openstax.txt

Output: vault/Textbooks/
"""

import sys
import re
import time
import argparse
from pathlib import Path
from datetime import datetime

try:
    import yaml
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("[ERROR] pip install pyyaml requests beautifulsoup4")
    sys.exit(1)

PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH  = PROJECT_ROOT / "config.yaml"
DELAY        = 2.0

# ── Known OpenStax books and their base URLs ──────────────────────────────────
# Full list: https://openstax.org/subjects
OPENSTAX_BOOKS = {
    "university-physics-1":      "https://openstax.org/books/university-physics-volume-1/pages",
    "university-physics-2":      "https://openstax.org/books/university-physics-volume-2/pages",
    "university-physics-3":      "https://openstax.org/books/university-physics-volume-3/pages",
    "calculus-1":                "https://openstax.org/books/calculus-volume-1/pages",
    "calculus-2":                "https://openstax.org/books/calculus-volume-2/pages",
    "calculus-3":                "https://openstax.org/books/calculus-volume-3/pages",
    "statistics":                "https://openstax.org/books/introductory-statistics/pages",
    "biology-2e":                "https://openstax.org/books/biology-2e/pages",
    "microbiology":              "https://openstax.org/books/microbiology/pages",
    "chemistry-atoms-first":     "https://openstax.org/books/chemistry-atoms-first-2e/pages",
    "economics":                 "https://openstax.org/books/principles-economics-3e/pages",
    "microeconomics":            "https://openstax.org/books/principles-microeconomics-3e/pages",
    "macroeconomics":            "https://openstax.org/books/principles-macroeconomics-3e/pages",
    "psychology-2e":             "https://openstax.org/books/psychology-2e/pages",
    "sociology-3e":              "https://openstax.org/books/introduction-sociology-3e/pages",
    "us-history":                "https://openstax.org/books/us-history/pages",
    "world-history":             "https://openstax.org/books/world-history-volume-1/pages",
    "astronomy-2e":              "https://openstax.org/books/astronomy-2e/pages",
    "anatomy-physiology":        "https://openstax.org/books/anatomy-and-physiology-2e/pages",
    "college-algebra":           "https://openstax.org/books/college-algebra-2e/pages",
    "linear-algebra":            "https://openstax.org/books/college-algebra-with-corequisite-support/pages",
    "computer-science":          "https://openstax.org/books/introduction-computer-science/pages",
}

# ── MIT OCW course catalog (curated high-value courses) ──────────────────────
# Each entry: (course_number, title, notes_url)
MIT_OCW_COURSES = {
    "6.006":  ("Introduction to Algorithms",           "https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-fall-2011/pages/lecture-notes/"),
    "6.046":  ("Design and Analysis of Algorithms",    "https://ocw.mit.edu/courses/6-046j-design-and-analysis-of-algorithms-spring-2015/pages/lecture-notes/"),
    "18.06":  ("Linear Algebra",                       "https://ocw.mit.edu/courses/18-06-linear-algebra-spring-2010/pages/readings/"),
    "18.650": ("Statistics for Applications",          "https://ocw.mit.edu/courses/18-650-statistics-for-applications-fall-2016/pages/lecture-slides/"),
    "6.034":  ("Artificial Intelligence",              "https://ocw.mit.edu/courses/6-034-artificial-intelligence-fall-2010/pages/readings/"),
    "6.S191": ("Introduction to Deep Learning",        "https://ocw.mit.edu/courses/6-s191-introduction-to-deep-learning-january-iap-2020/pages/lectures/"),
    "15.401": ("Finance Theory",                       "https://ocw.mit.edu/courses/15-401-finance-theory-i-fall-2008/pages/lecture-notes/"),
    "14.01":  ("Principles of Microeconomics",         "https://ocw.mit.edu/courses/14-01-principles-of-microeconomics-fall-2018/pages/lecture-notes/"),
    "7.012":  ("Introductory Biology",                 "https://ocw.mit.edu/courses/7-012-introductory-biology-fall-2004/pages/readings/"),
    "8.01":   ("Physics I: Classical Mechanics",       "https://ocw.mit.edu/courses/8-01-physics-i-fall-2003/pages/readings/"),
    "8.03":   ("Physics III: Vibrations and Waves",    "https://ocw.mit.edu/courses/8-03-physics-iii-vibrations-and-waves-fall-2004/pages/readings/"),
}


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)

def get_vault_path() -> Path:
    cfg = load_config()
    return Path(cfg['second_brain']['vaults'][0])

def get_output_dir(subdir: str = "Textbooks") -> Path:
    d = get_vault_path() / subdir
    d.mkdir(parents=True, exist_ok=True)
    return d


def fetch_page(url: str) -> BeautifulSoup | None:
    try:
        resp = requests.get(url, timeout=30,
                            headers={"User-Agent": "loom/1.0"})
        resp.raise_for_status()
        return BeautifulSoup(resp.text, 'html.parser')
    except Exception as e:
        print(f"    [ERROR] {e}")
        return None


def fetch_ocw_course(course_id: str) -> bool:
    """Fetch MIT OCW lecture notes index for a course."""
    if course_id not in MIT_OCW_COURSES:
        print(f"  [WARN] Course {course_id} not in known courses list.")
        print(f"  Known: {', '.join(MIT_OCW_COURSES.keys())}")
        return False

    title, url = MIT_OCW_COURSES[course_id]
    print(f"  Course: {course_id} — {title}")
    print(f"  URL: {url}")

    soup = fetch_page(url)
    if not soup:
        return False

    # Extract lecture links and titles
    links = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        text = a.get_text(strip=True)
        if 'lecture' in href.lower() or 'lec' in href.lower():
            if text and len(text) > 5:
                full_url = f"https://ocw.mit.edu{href}" if href.startswith('/') else href
                links.append((text, full_url))

    if not links:
        print(f"  [WARN] No lecture links found at {url}")
        # Save the index page itself
        content = soup.get_text("\n", strip=True)
        md = f"# MIT OCW {course_id}: {title}\n\n**Source:** {url}\n\n---\n\n{content[:8000]}"
        out = get_output_dir("Textbooks") / f"MIT OCW {course_id} {title}.md"
        out.write_text(md, encoding='utf-8')
        print(f"  → Saved index: {out.name}")
        return True

    # Save a curated index note
    today = datetime.now().strftime("%Y-%m-%d")
    md = f"# MIT OCW {course_id}: {title}\n\n"
    md += f"**Source:** {url}\n"
    md += f"**Fetched:** {today}\n\n---\n\n## Lecture Notes\n\n"
    for text, link in links[:40]:
        md += f"- [{text}]({link})\n"

    out = get_output_dir("Textbooks") / f"{today} MIT OCW {course_id} {title}.md"
    out.write_text(md, encoding='utf-8')
    print(f"  → {out.name}  ({len(links)} lectures indexed)")
    return True


def list_openstax():
    print("\nAvailable OpenStax books:")
    for key in OPENSTAX_BOOKS:
        print(f"  {key}")

def list_ocw():
    print("\nCurated MIT OCW courses:")
    for cid, (title, _) in MIT_OCW_COURSES.items():
        print(f"  {cid:<10} {title}")


def main():
    parser = argparse.ArgumentParser(
        description="Fetch OpenStax textbooks and MIT OCW lecture notes"
    )
    parser.add_argument("--ocw",         type=str, nargs="+",
                        help="MIT OCW course numbers (e.g. 6.006 18.06)")
    parser.add_argument("--list-books",  action="store_true",
                        help="List available OpenStax books")
    parser.add_argument("--list-ocw",    action="store_true",
                        help="List curated MIT OCW courses")
    args = parser.parse_args()

    if args.list_books:
        list_openstax()
        sys.exit(0)

    if args.list_ocw:
        list_ocw()
        sys.exit(0)

    if not args.ocw:
        parser.print_help()
        print("\nExamples:")
        print("  python openstax_batch.py --list-ocw")
        print("  python openstax_batch.py --ocw 6.006 18.06 15.401")
        sys.exit(0)

    print(f"\n{'='*56}")
    print(f"  OpenStax + MIT OCW Batch — Loom")
    print(f"{'='*56}\n")

    if args.ocw:
        for course in args.ocw:
            print(f"\n── OCW: {course} ────────────────────")
            fetch_ocw_course(course)
            time.sleep(DELAY)


if __name__ == "__main__":
    main()
