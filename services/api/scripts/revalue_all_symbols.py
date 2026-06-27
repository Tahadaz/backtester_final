"""Recompute all scenario valuations for every canonical fundamental snapshot.

Use after a valuation-methodology code change (no data change needed).
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

from app.db import _ensure_session_factory  # noqa: E402
from app.services.fundamentals import (  # noqa: E402
    VALUATION_SCENARIOS,
    latest_snapshot_rows_by_symbol,
    recompute_symbol_valuations_all_scenarios,
)


def main() -> None:
    session_factory = _ensure_session_factory()
    with session_factory() as db:
        snapshots = latest_snapshot_rows_by_symbol(db)
        symbols = sorted(snapshots)
        print(f"Revaluing {len(symbols)} symbols …", flush=True)
        for i, symbol in enumerate(symbols, 1):
            snap = snapshots[symbol]
            recompute_symbol_valuations_all_scenarios(
                db,
                import_id=snap.import_id,
                symbol=symbol,
                scenarios=VALUATION_SCENARIOS,
            )
            if i % 10 == 0 or i == len(symbols):
                print(f"  {i}/{len(symbols)} done", flush=True)
        db.commit()
    print("Done.")


if __name__ == "__main__":
    main()
