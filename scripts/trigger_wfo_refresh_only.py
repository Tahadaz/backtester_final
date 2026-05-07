"""Enqueue lightweight WFO signal refresh for all active symbols.

This does NOT recompute WFO folds — it only re-evaluates the persisted
representative signals against the latest OHLCV close prices.
Takes seconds per symbol instead of minutes.

Usage (from repo root):
    docker exec infra-quant_worker-1 python /repo/scripts/trigger_wfo_refresh_only.py
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.worker.db import SessionLocal
from services.worker.tasks.wfo_signal_batch import enqueue_wfo_refresh_for_symbol_horizon

HORIZONS = ("short", "medium", "long")
VARIANTS = ("legacy", "expanded")


def main():
    db = SessionLocal()
    try:
        from services.api.app.models import StockMaster

        symbols = [row.symbol for row in db.query(StockMaster).filter_by(is_active=True).all()]
        print(f"Found {len(symbols)} active symbols")

        total = 0
        for symbol in symbols:
            for horizon in HORIZONS:
                for variant in VARIANTS:
                    job_id = enqueue_wfo_refresh_for_symbol_horizon(
                        symbol, horizon, variant=variant, triggered_by="manual_refresh"
                    )
                    total += 1
                    print(f"  Enqueued: {symbol}/{horizon}/{variant} : {job_id}")

        print(f"\nDone. Enqueued {total} lightweight refresh jobs.")
        print("These will re-evaluate persisted representatives against latest OHLCV data.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
