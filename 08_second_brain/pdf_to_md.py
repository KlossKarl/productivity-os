"""
PDF to Markdown Converter
Karl's Productivity OS - Second Brain Utility

Converts any PDF to a clean .md file saved directly into your Obsidian vault.
Supports full extraction or page ranges for large textbooks.

Usage:
    python pdf_to_md.py "C:\path\to\file.pdf"                    # full PDF
    python pdf_to_md.py "C:\path\to\file.pdf" --pages 1-50       # page range
    python pdf_to_md.py "C:\path\to\file.pdf" --pages 10-25 45-60  # multiple ranges
    python pdf_to_md.py "C:\path\to\file.pdf" --folder Research   # save to subfolder
    python pdf_to_md.py --batch "C:\folder\of\pdfs"              # convert whole folder
"""

import sys
import re
import argparse
from pathlib import Path
from datetime import datetime

try:
    import pdfplumber
except ImportError:
    print("[ERROR] pdfplumber not installed. Run: pip install pdfplumber")
    sys.exit(1)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

OBSIDIAN_VAULT = Path(r"C:\Users\Karl\Documents\Obsidian Vault")

# ─────────────────────────────────────────────
# TEXT CLEANING
# ─────────────────────────────────────────────

def clean_text(text: str) -> str:
    if not text:
        return ""

    # Remove excessive whitespace
    text = re.sub(r'\n{4,}', '\n\n\n', text)
    text = re.sub(r' {3,}', ' ', text)

    # Remove common PDF artifacts
    text = re.sub(r'(\w)-\n(\w)', r'\1\2', text)  # fix hyphenated line breaks
    text = re.sub(r'(?<!\n)\n(?!\n)(?![•\-\*\d])', ' ', text)  # join single line breaks

    # Clean up headers (all caps lines are likely headers)
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append('')
            continue
        # Detect likely headers — all caps, short lines
        if stripped.isupper() and 5 < len(stripped) < 80:
            cleaned.append(f"\n## {stripped.title()}\n")
        else:
            cleaned.append(stripped)

    return '\n'.join(cleaned).strip()

def extract_tables_as_md(page) -> str:
    """Extract tables from a page and format as markdown."""
    tables = page.extract_tables()
    if not tables:
        return ""

    md_tables = []
    for table in tables:
        if not table or not table[0]:
            continue
        # Header row
        header = [str(cell or '').strip() for cell in table[0]]
        md = '| ' + ' | '.join(header) + ' |\n'
        md += '| ' + ' | '.join(['---'] * len(header)) + ' |\n'
        # Data rows
        for row in table[1:]:
            cells = [str(cell or '').strip() for cell in row]
            md += '| ' + ' | '.join(cells) + ' |\n'
        md_tables.append(md)

    return '\n\n'.join(md_tables)

# ─────────────────────────────────────────────
# PAGE RANGE PARSING
# ─────────────────────────────────────────────

def parse_page_ranges(ranges: list, total_pages: int) -> list:
    """Parse page range strings like '1-50' or '10-25' into page indices."""
    pages = set()
    for r in ranges:
        if '-' in r:
            start, end = r.split('-')
            start = max(0, int(start) - 1)  # convert to 0-indexed
            end = min(total_pages, int(end))
            pages.update(range(start, end))
        else:
            p = int(r) - 1
            if 0 <= p < total_pages:
                pages.add(p)
    return sorted(pages)

# ─────────────────────────────────────────────
# CONVERSION
# ─────────────────────────────────────────────

def pdf_to_markdown(
    pdf_path: Path,
    page_ranges: list = None,
    output_folder: str = None,
    verbose: bool = True
) -> Path:
    """
    Convert a PDF to markdown and save to Obsidian vault.
    Returns the path of the created .md file.
    """
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.exists():
        print(f"[ERROR] File not found: {pdf_path}")
        sys.exit(1)

    if verbose:
        print(f"\n{'='*60}")
        print(f"  PDF to Markdown Converter")
        print(f"  File: {pdf_path.name}")
        print(f"{'='*60}")

    # Determine output location
    if output_folder:
        out_dir = OBSIDIAN_VAULT / output_folder
    else:
        out_dir = OBSIDIAN_VAULT / "PDFs"
    out_dir.mkdir(parents=True, exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    safe_stem = re.sub(r'[<>:"/\\|?*]', '-', pdf_path.stem)
    out_path = out_dir / f"{date_str} {safe_stem}.md"

    with pdfplumber.open(str(pdf_path)) as pdf:
        total_pages = len(pdf.pages)

        if verbose:
            print(f"\n  Total pages: {total_pages}")

        # Determine which pages to extract
        if page_ranges:
            page_indices = parse_page_ranges(page_ranges, total_pages)
            if verbose:
                print(f"  Extracting pages: {page_indices[0]+1}-{page_indices[-1]+1} ({len(page_indices)} pages)")
        else:
            page_indices = list(range(total_pages))
            if verbose:
                print(f"  Extracting all {total_pages} pages")

        # Try to get PDF metadata
        meta = pdf.metadata or {}
        title = meta.get('Title', pdf_path.stem) or pdf_path.stem
        author = meta.get('Author', '') or ''
        subject = meta.get('Subject', '') or ''

        # Build markdown
        parts = []

        # Frontmatter
        range_str = f"{page_indices[0]+1}-{page_indices[-1]+1}" if page_ranges else f"1-{total_pages}"
        parts.append(f"""---
title: "{safe_stem}"
source: "{pdf_path.name}"
author: "{author}"
subject: "{subject}"
date: {date_str}
pages_extracted: "{range_str} of {total_pages}"
type: pdf-extract
tags:
  - pdf
  - reference
---

# {title}

> **Source:** {pdf_path.name}  
> **Pages:** {range_str} of {total_pages}  
> **Extracted:** {date_str}
{">" + f"  **Author:** {author}" if author else ""}

---
""")

        # Extract text page by page
        print(f"\n  Extracting", end='')
        for idx in page_indices:
            page = pdf.pages[idx]
            page_num = idx + 1

            # Extract text
            text = page.extract_text() or ''
            text = clean_text(text)

            # Extract tables
            tables_md = extract_tables_as_md(page)

            if text or tables_md:
                parts.append(f"\n\n<!-- Page {page_num} -->\n")
                if text:
                    parts.append(text)
                if tables_md:
                    parts.append(f"\n\n{tables_md}")

            if verbose and page_num % 10 == 0:
                print(f".", end='', flush=True)

        print(f" done\n")

    # Write file
    full_content = '\n'.join(parts)
    out_path.write_text(full_content, encoding='utf-8')

    word_count = len(full_content.split())
    char_count = len(full_content)

    if verbose:
        print(f"  Saved: {out_path}")
        print(f"  Words: {word_count:,}")
        print(f"  Chars: {char_count:,}")
        print(f"  Ready to index into Second Brain")
        print(f"{'='*60}\n")

    return out_path

def batch_convert(folder: Path, output_folder: str = None):
    """Convert all PDFs in a folder."""
    folder = Path(folder)
    pdfs = list(folder.glob("*.pdf"))

    if not pdfs:
        print(f"[WARN] No PDF files found in {folder}")
        return

    print(f"\nFound {len(pdfs)} PDFs to convert\n")
    converted = []

    for i, pdf in enumerate(pdfs):
        print(f"[{i+1}/{len(pdfs)}] {pdf.name}")
        try:
            out = pdf_to_markdown(pdf, output_folder=output_folder, verbose=False)
            print(f"  → {out.name}")
            converted.append(out)
        except Exception as e:
            print(f"  [ERROR] {e}")

    print(f"\nConverted {len(converted)}/{len(pdfs)} files")
    print(f"Saved to: {OBSIDIAN_VAULT / (output_folder or 'PDFs')}")
    print(f"\nRun indexer to add to Second Brain:")
    print(f"  python second_brain.py --index")

# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert PDFs to Markdown for Second Brain indexing"
    )
    parser.add_argument("pdf", nargs="?", help="PDF file to convert")
    parser.add_argument(
        "--pages", nargs="+",
        help="Page ranges to extract, e.g. --pages 1-50 or --pages 10-25 45-60"
    )
    parser.add_argument(
        "--folder", type=str, default=None,
        help="Obsidian subfolder to save into (default: PDFs/)"
    )
    parser.add_argument(
        "--batch", type=str,
        help="Convert all PDFs in a folder"
    )
    args = parser.parse_args()

    if args.batch:
        batch_convert(Path(args.batch), output_folder=args.folder)
    elif args.pdf:
        pdf_to_markdown(
            Path(args.pdf),
            page_ranges=args.pages,
            output_folder=args.folder,
        )
    else:
        parser.print_help()
        print("\nExamples:")
        print('  python pdf_to_md.py "C:\\Downloads\\book.pdf"')
        print('  python pdf_to_md.py "C:\\Downloads\\textbook.pdf" --pages 1-100')
        print('  python pdf_to_md.py "C:\\Downloads\\paper.pdf" --folder Research')
        print('  python pdf_to_md.py --batch "C:\\Downloads\\PDFs" --folder Reference')
