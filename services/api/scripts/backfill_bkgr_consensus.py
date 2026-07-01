"""Backfill fundamental_consensus_estimate from the BKGR stock-guide PDF.

Reads the BKGR PDF, parses EPS_Forward / PER_Forward / Target_Price / Rating
for all covered MASI names, derives NetIncome_Forward = EPS_Forward x
Shares_Outstanding from the latest snapshot (brief 54 §3.3 — BKGR never
tabulates NI directly), and upserts everything into
fundamental_consensus_estimate.

Run once after applying migration f8a9b0c1d2e3.  Safe to re-run: latest
as_of_date wins per (symbol, fiscal_year, metric, source).

Usage:
    python services/api/scripts/backfill_bkgr_consensus.py
    python services/api/scripts/backfill_bkgr_consensus.py --pdf /path/to/bkgr.pdf
    python services/api/scripts/backfill_bkgr_consensus.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "services" / "api") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

DEFAULT_PDF = REPO_ROOT / "bkgr-stock-guide-juin-2026.pdf"


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill BKGR consensus estimates into the DB.")
    parser.add_argument("--pdf", type=Path, default=DEFAULT_PDF,
                        help=f"Path to BKGR stock-guide PDF (default: {DEFAULT_PDF})")
    parser.add_argument("--database-url",
                        default=os.getenv("DATABASE_URL", "postgresql+psycopg2://app:app@127.0.0.1:5555/quant"))
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse the PDF and print counts without writing to the DB.")
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"ERROR: PDF not found at {args.pdf}", file=sys.stderr)
        print("Pass --pdf /path/to/bkgr-stock-guide-juin-2026.pdf", file=sys.stderr)
        return 1

    from core.quant_core.fundamentals.consensus.bkgr import BkgrAdapter, derive_net_income_forward
    from core.quant_core.fundamentals.consensus.domain import METRIC_EPS_FORWARD

    print(f"Parsing {args.pdf.name} …", flush=True)
    adapter = BkgrAdapter(args.pdf)
    estimates = adapter.fetch()

    covered = {e.symbol for e in estimates if e.metric == METRIC_EPS_FORWARD}
    print(f"  Parsed {len(estimates)} estimate rows across {len(covered)} symbols")

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.services.fundamentals import latest_snapshot_rows_by_symbol

    engine = create_engine(args.database_url)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with SessionLocal() as db:
        snapshots = latest_snapshot_rows_by_symbol(db, symbols=sorted(covered))
    shares_by_symbol = {
        symbol: float(row.metrics_json["Shares_Outstanding"])
        for symbol, row in snapshots.items()
        if (row.metrics_json or {}).get("Shares_Outstanding")
    }
    missing_shares = sorted(covered - shares_by_symbol.keys())
    if missing_shares:
        print(f"  No Shares_Outstanding for: {missing_shares} — NetIncome_Forward skipped for these")
    ni_estimates = derive_net_income_forward(estimates, shares_by_symbol)
    estimates = [*estimates, *ni_estimates]

    by_metric: dict[str, int] = {}
    for e in estimates:
        by_metric[e.metric] = by_metric.get(e.metric, 0) + 1
    for metric, count in sorted(by_metric.items()):
        print(f"    {metric}: {count}")

    if args.dry_run:
        print("Dry run — nothing written.")
        return 0

    from app.services.consensus import upsert_consensus_estimates

    with SessionLocal() as db:
        written = upsert_consensus_estimates(db, estimates)
        db.commit()

    print(f"Done. {written} rows written to fundamental_consensus_estimate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
