"""Fix 4: BCI re-canonicalization — promote 17fa82d2 (2026-06-18) as canonical for BCI.

Dry-run by default; pass --apply to write.

Root cause: BCI's is_canonical=True is pinned on 9aef3b72 (2026-05-26, stockanalysis).
That import has a genuine t3 failure (RNPG=434.83M > total NI=420.18M) AND carries a
brief42_fy2025_reingestion proof flag (proof_rank=1) that overrides the status_rank
comparison in _latest_symbol_rank.  So even after 17fa82d2 gets a verified verdict
(status_rank=2), the ranking still picks 9aef3b72 (proof_rank=1 > 0, earlier in tuple).

Import 17fa82d2 (2026-06-18) has correct BCI data (NetIncome = CFS = 434.83M, verified).
It cannot win via refresh_canonical_snapshot_flags because of the proof_rank asymmetry.

Fix: directly set is_canonical on all BCI snapshot rows, bypassing the ranking.  This is
a one-time correction for a defective re-ingest; the proof flag on 9aef3b72 remains
intact (it is not erased) — it just no longer pins a wrong snapshot as canonical.
"""
from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.api.app import models
from services.api.app.services.fundamentals import (
    canonical_snapshot_for_symbol,
    _load_history,
    _rows_by_metric_from_history,
    _prev_rows_by_metric_from_history,
    _upsert_auto_verification,
    _table_exists,
)
from core.quant_core.fundamentals.integrity import build_data_tieout_report

DB_URL = "postgresql+psycopg2://app:app@127.0.0.1:5555/quant"
IMPORT_17FA = uuid.UUID("17fa82d2-7490-438e-9fa3-72244540c40a")
IMPORT_9AEF = uuid.UUID("9aef3b72-35d1-4298-ac1a-ab292924298f")


def _tieout_on_import(db, import_id: uuid.UUID, symbol: str, sy: int):
    hist = _load_history(db, import_id, symbol)
    rows, my = _rows_by_metric_from_history(hist, sy)
    prev = _prev_rows_by_metric_from_history(hist, sy)
    return build_data_tieout_report(symbol, sy, rows, previous_rows_by_metric=prev,
                                    snapshot_year=sy, metric_years=my, period_type="annual")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    engine = create_engine(DB_URL)
    Session = sessionmaker(bind=engine)

    print(f"{'DRY RUN' if not args.apply else 'APPLY'} -- BCI canonical fix\n")

    with Session() as db:
        current = canonical_snapshot_for_symbol(db, "BCI")
        print(f"Current canonical:   {str(current.import_id)[:8]}  sy={current.latest_statement_year}")
        print(f"  proof_rank blocker: source_json['brief42_fy2025_reingestion']="
              f"{bool((current.source_json or {}).get('brief42_fy2025_reingestion'))}")

        snap_new = (
            db.query(models.FundamentalLatestSnapshot)
            .filter(
                models.FundamentalLatestSnapshot.import_id == IMPORT_17FA,
                models.FundamentalLatestSnapshot.symbol == "BCI",
            )
            .one_or_none()
        )
        if snap_new is None:
            print(f"ERROR: no snapshot row for BCI on {IMPORT_17FA} -- abort")
            return

        rep_old = _tieout_on_import(db, IMPORT_9AEF, "BCI", current.latest_statement_year)
        rep_new = _tieout_on_import(db, IMPORT_17FA, "BCI", snap_new.latest_statement_year)
        print(f"  tieout ({str(IMPORT_9AEF)[:8]}): {rep_old.status!r}  reason={rep_old.reason!r}")
        print(f"  tieout ({str(IMPORT_17FA)[:8]}):  {rep_new.status!r}  reason={rep_new.reason!r}")
        print()

        all_bci_snaps = (
            db.query(models.FundamentalLatestSnapshot)
            .filter(models.FundamentalLatestSnapshot.symbol == "BCI")
            .all()
        )
        print("Planned changes to fundamental_latest_snapshot.is_canonical:")
        for s in all_bci_snaps:
            want = s.import_id == IMPORT_17FA
            if bool(getattr(s, "is_canonical", False)) != want:
                print(f"  {str(s.import_id)[:8]}  {bool(getattr(s,'is_canonical',False))} -> {want}")
        print(f"Also: persist verified verdict for BCI on {str(IMPORT_17FA)[:8]}")
        print()

        if not args.apply:
            print("Pass --apply to execute.")
            return

        if not _table_exists(db, models.FundamentalDataVerification):
            print("ERROR: fundamental_data_verification table absent -- abort")
            return

        # Step 1: set is_canonical directly on all BCI snapshots
        for s in all_bci_snaps:
            s.is_canonical = (s.import_id == IMPORT_17FA)
            db.add(s)
        db.flush()

        # Step 2: persist verified verdict for 17fa82d2 BCI (idempotent)
        _upsert_auto_verification(
            db,
            snapshot_row=snap_new,
            import_id=IMPORT_17FA,
            symbol="BCI",
            statement_year=snap_new.latest_statement_year,
            report=rep_new,
        )
        db.commit()

        updated = canonical_snapshot_for_symbol(db, "BCI")
        print(f"WRITTEN. New canonical = {str(updated.import_id)[:8]}")
        if updated.import_id == IMPORT_17FA:
            print("SUCCESS: BCI canonical is now 17fa82d2 (verified)")
        else:
            print(f"WARNING: canonical did not move (still {str(updated.import_id)[:8]})")


if __name__ == "__main__":
    main()
