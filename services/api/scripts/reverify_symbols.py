"""Fix 1: flush stale auto-verdicts for specific symbols.

Dry-run by default; pass --apply to write.

Usage:
  python services/api/scripts/reverify_symbols.py [--apply] [SYM ...]

If no symbols are given, defaults to the four known stale-cache symbols:
  ATW BCP CMA TQM
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from services.api.app.services.fundamentals import (
    canonical_snapshot_for_symbol,
    latest_data_verification,
    reverify_symbol,
)
from core.quant_core.fundamentals.integrity import build_data_tieout_report
from services.api.app.services.fundamentals import (
    _load_history,
    _rows_by_metric_from_history,
    _prev_rows_by_metric_from_history,
)

DB_URL = "postgresql+psycopg2://app:app@127.0.0.1:5555/quant"
DEFAULT_SYMBOLS = ["ATW", "BCP", "CMA", "TQM"]


def _dry_run_row(db, sym: str) -> None:
    snap = canonical_snapshot_for_symbol(db, sym)
    if snap is None:
        print(f"  {sym}: no canonical snapshot — skip")
        return
    sy = snap.latest_statement_year
    cached = latest_data_verification(db, import_id=snap.import_id, symbol=sym, statement_year=sy)
    hist = _load_history(db, snap.import_id, sym)
    rows, my = _rows_by_metric_from_history(hist, sy)
    prev = _prev_rows_by_metric_from_history(hist, sy)
    fresh = build_data_tieout_report(sym, sy, rows, previous_rows_by_metric=prev,
                                     snapshot_year=sy, metric_years=my, period_type="annual")
    cached_str = f"{cached.status}:{cached.reason}" if cached else "NONE"
    fresh_str = f"{fresh.status}:{fresh.reason}"
    will_change = cached is None or cached.status != fresh.status or cached.reason != fresh.reason
    tag = "WOULD UPDATE" if will_change else "no-op"
    has_curated = cached and (bool(cached.corrections_json) or bool(cached.provenance_json))
    if has_curated:
        tag = "SKIP (curated)"
    print(f"  {sym:6s}  import={str(snap.import_id)[:8]}  sy={sy}")
    print(f"         cached: {cached_str!r}")
    print(f"         fresh:  {fresh_str!r}")
    print(f"         -> {tag}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("symbols", nargs="*")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    symbols = [s.upper() for s in args.symbols] if args.symbols else DEFAULT_SYMBOLS

    engine = create_engine(DB_URL)
    Session = sessionmaker(bind=engine)

    print(f"{'DRY RUN' if not args.apply else 'APPLY'} — reverify {symbols}\n")

    with Session() as db:
        for sym in symbols:
            snap = canonical_snapshot_for_symbol(db, sym)
            if snap is None:
                print(f"  {sym}: no canonical snapshot — skip\n")
                continue

            sy = snap.latest_statement_year
            cached = latest_data_verification(db, import_id=snap.import_id, symbol=sym, statement_year=sy)
            has_curated = cached and (bool(cached.corrections_json) or bool(cached.provenance_json))
            if has_curated:
                print(f"  {sym}: SKIP — row has curated corrections/provenance\n")
                continue

            hist = _load_history(db, snap.import_id, sym)
            rows, my = _rows_by_metric_from_history(hist, sy)
            prev = _prev_rows_by_metric_from_history(hist, sy)
            fresh = build_data_tieout_report(sym, sy, rows, previous_rows_by_metric=prev,
                                             snapshot_year=sy, metric_years=my, period_type="annual")
            cached_str = f"{cached.status}:{cached.reason}" if cached else "NONE"
            fresh_str = f"{fresh.status}:{fresh.reason}"
            print(f"  {sym:6s}  import={str(snap.import_id)[:8]}  sy={sy}")
            print(f"         cached:  {cached_str!r}")
            print(f"         fresh:   {fresh_str!r}")

            if args.apply:
                from services.api.app.services.fundamentals import reverify_symbol
                row = reverify_symbol(db, sym)
                db.commit()
                print(f"         -> WRITTEN: status={row.status!r}  reason={row.reason!r}")
            else:
                will_change = cached is None or cached.status != fresh.status or cached.reason != fresh.reason
                print(f"         -> {'WOULD UPDATE' if will_change else 'no-op (already current)'}")
            print()


if __name__ == "__main__":
    main()
