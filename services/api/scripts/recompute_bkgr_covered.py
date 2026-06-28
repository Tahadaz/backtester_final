"""Recompute scenario valuations for BKGR-covered symbols only.

Run after backfill_bkgr_consensus.py to push the new forward-estimate view
through compute_symbol_valuations and write updated fundamental_ensemble_result
rows.  Scoped to the 37 BKGR-covered names so it's fast (~2 min vs ~20 min for
a full revalue).

Usage:
    python services/api/scripts/recompute_bkgr_covered.py
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "services" / "api") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

os.environ.setdefault("FUNDAMENTAL_DISABLE_LIVE_QUOTES", "1")

FIXTURE = REPO_ROOT / "core" / "tests" / "fixtures" / "bkgr_jun2026.csv"

from app.db import _ensure_session_factory  # noqa: E402
from app.services.fundamentals import (  # noqa: E402
    VALUATION_SCENARIOS,
    latest_snapshot_rows_by_symbol,
    make_bulk_overrides_loader,
    recompute_symbol_valuations_all_scenarios,
)


def _bkgr_tickers() -> list[str]:
    tickers: list[str] = []
    with FIXTURE.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            tickers.append(str(row["ticker"]).strip().upper())
    return tickers


def main() -> None:
    bkgr_tickers = _bkgr_tickers()
    print(f"BKGR-covered tickers: {len(bkgr_tickers)}", flush=True)

    session_factory = _ensure_session_factory()
    with session_factory() as db:
        all_snapshots = latest_snapshot_rows_by_symbol(db)
        covered = [t for t in bkgr_tickers if t in all_snapshots]
        missing = [t for t in bkgr_tickers if t not in all_snapshots]
        if missing:
            print(f"  No snapshot for: {missing} — skipped", flush=True)
        print(f"  Recomputing {len(covered)} symbols …", flush=True)

        overrides_loader = make_bulk_overrides_loader(db, covered)
        for i, symbol in enumerate(covered, 1):
            snap = all_snapshots[symbol]
            recompute_symbol_valuations_all_scenarios(
                db,
                import_id=snap.import_id,
                symbol=symbol,
                scenarios=VALUATION_SCENARIOS,
                overrides_loader=overrides_loader,
            )
            if i % 10 == 0 or i == len(covered):
                print(f"  {i}/{len(covered)} done", flush=True)
        db.commit()
    print("Done.")


if __name__ == "__main__":
    main()
