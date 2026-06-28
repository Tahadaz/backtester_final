"""Recompute scenario valuations for MarketScreener-covered symbols.

Run after backfill_ms_consensus.py to push the forward Revenue/NI view through
build_projection stage-1 seeding and write updated fundamental_ensemble_result rows.

Usage:
    python services/api/scripts/recompute_ms_covered.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "services" / "api") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

os.environ.setdefault("FUNDAMENTAL_DISABLE_LIVE_QUOTES", "1")

from core.quant_core.fundamentals.consensus.marketscreener import KNOWN_IDS  # noqa: E402
from app.db import _ensure_session_factory  # noqa: E402
from app.services.fundamentals import (  # noqa: E402
    VALUATION_SCENARIOS,
    latest_snapshot_rows_by_symbol,
    make_bulk_overrides_loader,
    recompute_symbol_valuations_all_scenarios,
)

# All known MS-covered Casablanca names
MS_TICKERS = sorted(set(KNOWN_IDS.values()))


def main() -> None:
    print(f"MS-covered tickers to recompute: {MS_TICKERS}", flush=True)

    session_factory = _ensure_session_factory()
    with session_factory() as db:
        all_snapshots = latest_snapshot_rows_by_symbol(db)
        covered = [t for t in MS_TICKERS if t in all_snapshots]
        missing = [t for t in MS_TICKERS if t not in all_snapshots]
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
            print(f"  {i}/{len(covered)} done: {symbol}", flush=True)
        db.commit()
    print("Done.")


if __name__ == "__main__":
    main()
