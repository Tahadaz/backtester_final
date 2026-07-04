"""
Task B probe: extract text/tables from bkgr-stock-guide-juin-2026.pdf
using pypdf. Report forward-EPS columns, forward P/E, target price, fiscal years.
READ-ONLY.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Force UTF-8 output on Windows
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pypdf import PdfReader

PDF_PATH = ROOT / "bkgr-stock-guide-juin-2026.pdf"

BPA_RE = re.compile(r"\bBPA\b", re.IGNORECASE)
PER_RE = re.compile(r"\bP[/]?E\b|\bPER\b|\bP\.E\b", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(202[4-9])([Ee]?)\b")
CIBLE_RE = re.compile(r"cours\s+cible|objectif\s+de\s+cours|price\s+target|target\s+price", re.IGNORECASE)
RATING_RE = re.compile(r"\b(acheter|accumuler|conserver|vendre|buy|hold|sell|neutral|accumulate)\b", re.IGNORECASE)

def safe(s: str) -> str:
    return s.encode("utf-8", errors="replace").decode("utf-8")

def main():
    if not PDF_PATH.exists():
        print(f"ERROR: {PDF_PATH} not found")
        return

    print(f"Reading {safe(str(PDF_PATH))}")
    reader = PdfReader(str(PDF_PATH))
    n_pages = len(reader.pages)
    print(f"Total pages: {n_pages}\n")

    all_pages: list[str] = []
    for i, page in enumerate(reader.pages):
        txt = page.extract_text() or ""
        all_pages.append(txt)

    full_text = "\n".join(all_pages)

    # 1. Year mentions
    print("=" * 70)
    print("YEAR MENTIONS ACROSS DOCUMENT (with 'e' suffix = estimate)")
    print("=" * 70)
    year_counts: dict[str, int] = {}
    for m in YEAR_RE.finditer(full_text):
        key = m.group(1) + (m.group(2).upper() if m.group(2) else "")
        year_counts[key] = year_counts.get(key, 0) + 1
    for k, v in sorted(year_counts.items()):
        fwd = " <-- FORWARD ESTIMATE" if k.endswith("E") else ""
        print(f"  {k}: {v:4d} mentions{fwd}")

    # 2. BPA occurrences
    print()
    print("=" * 70)
    print("BPA (EPS) OCCURRENCES — first 25 with context")
    print("=" * 70)
    bpa_count = 0
    for m in BPA_RE.finditer(full_text):
        start = max(0, m.start() - 80)
        end = min(len(full_text), m.end() + 150)
        snippet = full_text[start:end].replace("\n", " | ")
        print(f"  [{bpa_count+1:02d}] {safe(snippet)}")
        bpa_count += 1
        if bpa_count >= 25:
            print("  (truncated at 25)")
            break
    if bpa_count == 0:
        print("  NO BPA mentions found.")
    else:
        print(f"\n  TOTAL BPA mentions: {bpa_count} (showed first 25)")

    # 3. PER occurrences
    print()
    print("=" * 70)
    print("PER / P/E OCCURRENCES — first 20 with context")
    print("=" * 70)
    per_count = 0
    all_per = list(PER_RE.finditer(full_text))
    print(f"  Total PER/P/E regex hits: {len(all_per)}")
    for m in all_per[:20]:
        start = max(0, m.start() - 80)
        end = min(len(full_text), m.end() + 150)
        snippet = full_text[start:end].replace("\n", " | ")
        print(f"  [{per_count+1:02d}] {safe(snippet)}")
        per_count += 1
    if per_count == 0:
        print("  NO PER/P/E mentions found.")

    # 4. Cours cible / target price
    print()
    print("=" * 70)
    print("'COURS CIBLE' / TARGET OCCURRENCES (first 10)")
    print("=" * 70)
    cible_count = 0
    for m in CIBLE_RE.finditer(full_text):
        start = max(0, m.start() - 30)
        end = min(len(full_text), m.end() + 120)
        snippet = full_text[start:end].replace("\n", " | ")
        print(f"  [{cible_count+1:02d}] {safe(snippet)}")
        cible_count += 1
        if cible_count >= 10:
            break
    print(f"  Total 'cours cible' hits: {cible_count}")

    # 5. Per-page summary of key tickers
    print()
    print("=" * 70)
    print("PAGE-BY-PAGE CONTENT FOR IAM / ATW / BCP (first match per ticker)")
    print("=" * 70)
    for ticker in ["IAM", "ITISSALAT", "ATW", "ATTIJARIWAFA", "BCP", "BANQUE CENTRALE"]:
        for page_no, page_text in enumerate(all_pages):
            if ticker.upper() in page_text.upper():
                pg_lines = page_text.splitlines()
                print(f"\n  --- '{ticker}' on page {page_no+1} ---")
                for ln in pg_lines:
                    print(f"    {safe(ln)}")
                break

    # 6. Try to identify the table structure
    print()
    print("=" * 70)
    print("LINES CONTAINING BOTH A YEAR AND BPA/PER (table headers?)")
    print("=" * 70)
    lines = full_text.splitlines()
    for i, line in enumerate(lines):
        if YEAR_RE.search(line) and (BPA_RE.search(line) or PER_RE.search(line)):
            print(f"  L{i:4d}: {safe(line.strip())}")

    # 7. First 80 lines of full text to see doc structure
    print()
    print("=" * 70)
    print("FIRST 80 LINES OF FULL EXTRACTED TEXT (structure)")
    print("=" * 70)
    for i, ln in enumerate(lines[:80]):
        print(f"  {i+1:3d}: {safe(ln)}")


if __name__ == "__main__":
    main()
