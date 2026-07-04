"""
Task A probe: scan cached Attijari morning-brief PDFs (no DB, no network).
Reports metric labels, fiscal years, and counts of forward-year estimates.
READ-ONLY — never touches the DB.
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.backfill_attijari_morning_brief_fundamentals import (
    PERIOD_RE,
    extract_pdf_text,
    _parse_table_line,
    _periods_from_header,
    _unit_from_header,
    _normalize_text,
)

CACHE_DIR = ROOT / ".cache" / "attijari_morning_briefs"
EARNINGS_KEYWORDS = {"BPA", "DPA", "PER", "RNPG", "RESULTAT NET", "BENEFICE", "BÉNÉFICE", "RN PART", "RNPG"}

INDICATEURS_RE = re.compile(r"indicateurs", re.IGNORECASE)

def scan_pdf(path: Path):
    """Return (found_years, raw_metric_names, tables_with_forward) for one PDF."""
    try:
        text = extract_pdf_text(path)
    except Exception as exc:
        return None, None, str(exc)

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    found_years: Counter = Counter()
    raw_metric_names: list[str] = []
    tables_with_forward: list[dict] = []

    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if INDICATEURS_RE.search(line):
            periods = _periods_from_header(line)
            unit = _unit_from_header(line)
            years = [y for y, _, _ in periods]
            forward_years = [y for y in years if y >= 2025]
            for y in years:
                found_years[y] += 1

            if periods:
                table_rows: list[str] = []
                idx += 1
                while idx < len(lines):
                    candidate = lines[idx]
                    norm = _normalize_text(candidate)
                    if (
                        candidate.startswith("|")
                        or INDICATEURS_RE.search(candidate)
                        or norm.startswith("ACTUALITES")
                    ):
                        break
                    parsed = _parse_table_line(candidate, periods)
                    if parsed is not None:
                        raw_name, values = parsed
                        raw_metric_names.append(raw_name)
                        table_rows.append(raw_name)
                    idx += 1
                if forward_years and table_rows:
                    tables_with_forward.append({
                        "periods": periods,
                        "forward_years": forward_years,
                        "metrics": table_rows,
                        "unit": unit,
                    })
                continue
        idx += 1

    return found_years, raw_metric_names, tables_with_forward


def main():
    pdfs = sorted(CACHE_DIR.glob("*.pdf"))
    print(f"Found {len(pdfs)} cached PDFs in {CACHE_DIR}")

    # Pick a spread of PDFs — recent ones most likely to have forward years
    # Sort by filename (has date embedded), take recent 30 and some older for variety
    recent = [p for p in pdfs if "2025" in p.name or "2026" in p.name]
    older = [p for p in pdfs if "2024" in p.name]
    sample = recent[:20] + older[:10]
    print(f"Scanning {len(sample)} PDFs (20 from 2025/2026, up to 10 from 2024)\n")

    all_years: Counter = Counter()
    all_raw_metrics: Counter = Counter()
    forward_tables_count = 0
    forward_years_found: Counter = Counter()
    earnings_labels: list[tuple[str, str]] = []  # (pdf_name, raw_metric)

    for pdf in sample:
        found_years, raw_metrics, tables_with_forward = scan_pdf(pdf)
        if found_years is None:
            print(f"  ERROR reading {pdf.name}: {tables_with_forward}")
            continue
        all_years.update(found_years)
        if raw_metrics:
            for m in raw_metrics:
                all_raw_metrics[m] += 1
        if tables_with_forward:
            forward_tables_count += len(tables_with_forward)
            for t in tables_with_forward:
                for fy in t["forward_years"]:
                    forward_years_found[fy] += 1
                for m in t["metrics"]:
                    norm_m = _normalize_text(m)
                    for kw in EARNINGS_KEYWORDS:
                        if kw in norm_m:
                            earnings_labels.append((pdf.name, m))

    print("=" * 70)
    print("FISCAL YEAR HISTOGRAM (all parsed tables, all sampled PDFs)")
    print("=" * 70)
    for year, count in sorted(all_years.items()):
        label = " <-- FORWARD" if year >= 2026 else (" <-- near-fwd" if year == 2025 else "")
        print(f"  {year}: {count:4d} table-column appearances{label}")

    print()
    print("=" * 70)
    print("FORWARD YEARS (>=2025) appearing in tables with parsed rows:")
    print("=" * 70)
    for year, count in sorted(forward_years_found.items()):
        print(f"  {year}: {count:4d} tables")

    print()
    print("=" * 70)
    print(f"ALL DISTINCT RAW METRIC LABELS (top 60 by frequency):")
    print("=" * 70)
    for metric, count in all_raw_metrics.most_common(60):
        norm = _normalize_text(metric)
        is_earnings = any(kw in norm for kw in EARNINGS_KEYWORDS)
        tag = "  ** EARNINGS **" if is_earnings else ""
        print(f"  {count:4d}x  {metric!r}{tag}")

    print()
    print("=" * 70)
    print("EARNINGS-RELATED LABELS IN FORWARD-YEAR TABLES:")
    print("=" * 70)
    if earnings_labels:
        for pdf_name, label in earnings_labels[:40]:
            print(f"  {label!r}  (from {pdf_name})")
    else:
        print("  NONE FOUND")

    print()
    # Check specifically for BPA, DPA, PER in all metrics
    print("=" * 70)
    print("BPA / DPA / PER presence across ALL parsed metrics (any year):")
    print("=" * 70)
    bpa_hits = [(m, c) for m, c in all_raw_metrics.items() if "BPA" in _normalize_text(m)]
    dpa_hits = [(m, c) for m, c in all_raw_metrics.items() if "DPA" in _normalize_text(m)]
    per_hits = [(m, c) for m, c in all_raw_metrics.items() if "PER" in _normalize_text(m) or "P/E" in _normalize_text(m)]
    rnpg_hits = [(m, c) for m, c in all_raw_metrics.items() if "RNPG" in _normalize_text(m) or "RESULTAT NET" in _normalize_text(m)]
    print(f"  BPA hits:  {bpa_hits}")
    print(f"  DPA hits:  {dpa_hits}")
    print(f"  PER hits:  {per_hits}")
    print(f"  RNPG/RN hits: {rnpg_hits}")


if __name__ == "__main__":
    main()
