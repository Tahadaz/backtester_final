"""
Extract BPA / PER / DPA from BKGR stock guide for all tickers.
Parses the compact per-ticker block format found in the PDF.
READ-ONLY.
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pypdf import PdfReader

PDF_PATH = ROOT / "bkgr-stock-guide-juin-2026.pdf"

# BPA / PER / DPA lines have 4 numeric values matching year columns
# Pattern: "BPA  x.x  y.y  z.z  w.w" or "PER  x.xx  y.xx  z.xx  w.xx"
NUMBER_PAT = r"[-+]?\d+(?:[,\.]\d+)?(?:x)?"
ROW_RE = re.compile(
    r"\b(BPA|PER|DPA|D/Y)\b\s+(" + NUMBER_PAT + r"|ns|-)\s+(" + NUMBER_PAT + r"|ns|-)\s+(" + NUMBER_PAT + r"|ns|-)\s+(" + NUMBER_PAT + r"|ns|-)",
    re.IGNORECASE
)

# Year header line pattern
YEAR_HEADER_RE = re.compile(r"En MAD\s+(20\d{2}[Ee]?)\s+(20\d{2}[Ee]?)\s+(20\d{2}[Ee]?)\s+(20\d{2}[Ee]?)")

# Company/ticker line
TICKER_RE = re.compile(r"\b([A-Z]{2,5})\s+Maroc\b|\bObjectif de cours\s*:\s*MAD\s*([\d\s,]+)")

def main():
    reader = PdfReader(str(PDF_PATH))
    all_pages = [page.extract_text() or "" for page in reader.pages]
    full_text = "\n".join(all_pages)
    lines = full_text.splitlines()

    # Find all BPA/PER/DPA rows with context
    # Strategy: For each BPA hit, look backward for the company name and year header
    results: list[dict] = []

    # Collect all BPA/PER/DPA entries with their surrounding context
    i = 0
    current_ticker = None
    current_years = None
    company_name = None

    # Parse page by page to get better context
    for page_no, page_text in enumerate(all_pages):
        page_lines = page_text.splitlines()
        page_ticker = None
        page_years = None
        page_company = None

        # Detect company and year structure
        for ln in page_lines:
            # Look for "En MAD 2024 2025 2026e 2027e" style header
            ym = YEAR_HEADER_RE.search(ln)
            if ym:
                page_years = [ym.group(1), ym.group(2), ym.group(3), ym.group(4)]

            # Look for "SYMBOL Maroc" or "Objectif de cours" line
            if "Objectif de cours" in ln:
                # On the company detail page
                pass

        # Find BPA/PER/DPA in this page
        page_rows: dict[str, list[str]] = {}
        for ln in page_lines:
            rm = ROW_RE.search(ln)
            if rm:
                metric = rm.group(1).upper()
                vals = [rm.group(2), rm.group(3), rm.group(4), rm.group(5)]
                page_rows[metric] = vals

        if page_rows and page_years:
            results.append({
                "page": page_no + 1,
                "years": page_years,
                "rows": page_rows,
            })

    print("=" * 70)
    print("BPA / PER / DPA by PAGE (BKGR Stock Guide June 2026)")
    print("=" * 70)
    print(f"{'Page':>4}  {'Years':40}  {'Metric':6}  {'V1':>8}  {'V2':>8}  {'V3':>8}  {'V4':>8}")
    print("-" * 100)
    for entry in results:
        years = "  ".join(entry["years"])
        for metric, vals in sorted(entry["rows"].items()):
            print(f"{entry['page']:>4}  {years:40}  {metric:6}  {vals[0]:>8}  {vals[1]:>8}  {vals[2]:>8}  {vals[3]:>8}")

    # Now map page numbers to ticker names using synthese table
    print()
    print("=" * 70)
    print("SYNTHESIS TABLE — Tickers from Synthese page (page 3)")
    print("=" * 70)

    # The synthese table on page 3 maps company name to ticker
    # Let me extract it
    synth_text = all_pages[2]  # page 3 is index 2
    synth_lines = synth_text.splitlines()
    print("Synthesis page lines with tickers:")
    for ln in synth_lines:
        if any(ln.strip().startswith(t) for t in ["ADDOHA", "AFRIQUIA", "AKDITAL", "ATT", "BCP", "IAM", "ITISSALAT",
                                                     "HOLCIM", "MANAGEM", "COSUMAR", "SONASID", "TAQA", "LABEL VIE",
                                                     "ATTIJARIWAFA", "BMCI", "CIH", "CIMENTS", "TICKER"]):
            print(f"  {ln.strip()}")

    # Try to associate page entries with ticker names from structure
    # Company detail pages start after the synthese. Let's find company headers in detail pages.
    print()
    print("=" * 70)
    print("COMPANY PAGE DETECTION")
    print("=" * 70)
    company_pages: list[tuple[int, str]] = []
    for page_no, page_text in enumerate(all_pages[3:], start=4):  # skip cover, abbrev, synthese
        plines = page_text.splitlines()
        for ln in plines:
            # Company pages typically have "Objectif de cours : MAD XXX  Upside : +XX%"
            if "Objectif de cours" in ln and "Upside" in ln:
                # Extract company header from page
                header_line = ""
                for prev_ln in plines:
                    if "Maroc" in prev_ln or any(sec in prev_ln for sec in ["SECTEUR", "Banques", "Telecom", "Mines", "Sante", "Energie", "BTP", "Agroalimentaire", "Immobilier", "Assurance", "Transport"]):
                        header_line = prev_ln.strip()
                        break
                company_pages.append((page_no, ln.strip()[:80]))
                break

    for page_no, info in company_pages[:40]:
        print(f"  P{page_no:02d}: {info}")

    # Now match company pages to our BPA results
    print()
    print("=" * 70)
    print("SUMMARY: Forward BPA 2026e / PER 2026e (sample tickers)")
    print("=" * 70)
    # From our results, which pages have 2026e in position 3 (index 2)?
    for entry in results:
        years = entry["years"]
        # Find 2026e position
        try:
            idx_2026 = next(i for i, y in enumerate(years) if "2026" in y.upper())
            idx_2027 = next(i for i, y in enumerate(years) if "2027" in y.upper())
        except StopIteration:
            continue
        bpa = entry["rows"].get("BPA", ["-"]*4)
        per = entry["rows"].get("PER", ["-"]*4)
        dpa = entry["rows"].get("DPA", ["-"]*4)
        bpa_2026 = bpa[idx_2026] if idx_2026 < len(bpa) else "-"
        per_2026 = per[idx_2026] if idx_2026 < len(per) else "-"
        bpa_2027 = bpa[idx_2027] if idx_2027 < len(bpa) else "-"
        per_2027 = per[idx_2027] if idx_2027 < len(per) else "-"
        print(f"  Page {entry['page']:02d}:  BPA 2026e={bpa_2026}  PER 2026e={per_2026}  BPA 2027e={bpa_2027}  PER 2027e={per_2027}")


if __name__ == "__main__":
    main()
