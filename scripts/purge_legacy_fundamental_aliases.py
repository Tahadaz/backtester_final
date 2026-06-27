"""Purge legacy alias rows from fundamental DB tables.

Targets:
  - FundamentalAnnualMetric rows whose metric_name is a known alias
    (i.e. resolvable via resolve_metric_name to a different canonical name).
    GUARD: only deleted when the resolved canonical (symbol, year, canonical_name)
    row already exists in FundamentalAnnualMetric.  Alias rows with no canonical
    replacement are preserved.
  - FundamentalLatestSnapshot rows: strip alias keys from metrics_json.
    GUARD: only stripped when the resolved canonical key is already present in
    that same snapshot's metrics_json.

SAFETY: defaults to DRY-RUN.  Pass --apply only after the canonical
StockAnalysis re-ingest (Phase 4) has completed and been validated.

Usage:
  python scripts/purge_legacy_fundamental_aliases.py              # dry-run
  python scripts/purge_legacy_fundamental_aliases.py --apply      # write to DB
  python scripts/purge_legacy_fundamental_aliases.py --symbol CIH # limit scope
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

# Allow running from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.quant_core.fundamentals.cgnc_mapping import _ALIAS_TO_CANONICAL, resolve_metric_name
from services.api.app import models
from services.worker.db import SessionLocal

ALIAS_NAMES: frozenset[str] = frozenset(_ALIAS_TO_CANONICAL)
_CANONICAL_NAMES: frozenset[str] = frozenset(_ALIAS_TO_CANONICAL.values())


def _purge_annual_metrics(db, *, symbol: str | None, apply: bool) -> dict[str, int]:
    # Load all alias rows.
    alias_q = db.query(models.FundamentalAnnualMetric).filter(
        models.FundamentalAnnualMetric.metric_name.in_(list(ALIAS_NAMES))
    )
    if symbol:
        alias_q = alias_q.filter(models.FundamentalAnnualMetric.symbol == symbol.upper())
    alias_rows = alias_q.all()

    # Build the set of (symbol, year, canonical_name) that already exist so we
    # can gate each alias row on whether its canonical replacement is present.
    canonical_q = db.query(
        models.FundamentalAnnualMetric.symbol,
        models.FundamentalAnnualMetric.statement_year,
        models.FundamentalAnnualMetric.metric_name,
    ).filter(models.FundamentalAnnualMetric.metric_name.in_(list(_CANONICAL_NAMES)))
    if symbol:
        canonical_q = canonical_q.filter(models.FundamentalAnnualMetric.symbol == symbol.upper())
    canonical_exists: set[tuple[str, int, str]] = {
        (str(sym).upper(), int(year), name)
        for sym, year, name in canonical_q
    }

    # Partition alias rows into safe-to-delete vs preserved.
    to_delete: list[models.FundamentalAnnualMetric] = []
    by_alias_delete: dict[str, int] = defaultdict(int)
    by_alias_preserve: dict[str, int] = defaultdict(int)
    preserved_symbols: dict[str, set[str]] = defaultdict(set)  # alias -> symbols

    for row in alias_rows:
        canonical = resolve_metric_name(row.metric_name)
        key = (str(row.symbol).upper(), int(row.statement_year), canonical)
        if key in canonical_exists:
            to_delete.append(row)
            by_alias_delete[row.metric_name] += 1
        else:
            by_alias_preserve[row.metric_name] += 1
            preserved_symbols[row.metric_name].add(str(row.symbol).upper())

    total_delete = len(to_delete)
    total_preserve = len(alias_rows) - total_delete

    print(f"\n[FundamentalAnnualMetric] {len(alias_rows)} alias rows found:")
    print(f"  Safe to purge (canonical replacement found): {total_delete}")
    print(f"  Preserved (no canonical replacement yet)  : {total_preserve}")

    if by_alias_delete:
        print("\n  -- WILL DELETE --")
        for alias in sorted(by_alias_delete):
            canonical = resolve_metric_name(alias)
            print(f"  {alias!r:40s} -> {canonical!r:30s}  ({by_alias_delete[alias]} rows)")

    if by_alias_preserve:
        print("\n  -- PRESERVED (no canonical replacement) --")
        for alias in sorted(by_alias_preserve):
            canonical = resolve_metric_name(alias)
            syms = sorted(preserved_symbols[alias])
            print(f"  {alias!r:40s} -> {canonical!r:30s}  ({by_alias_preserve[alias]} rows) symbols: {syms}")

    if apply and to_delete:
        for row in to_delete:
            db.delete(row)
        print(f"\n  [APPLY] Deleted {total_delete} rows ({total_preserve} preserved).")
    elif not apply:
        print("\n  [DRY-RUN] No rows deleted.")

    return dict(by_alias_delete)


def _purge_snapshot_alias_keys(db, *, symbol: str | None, apply: bool) -> int:
    query = db.query(models.FundamentalLatestSnapshot)
    if symbol:
        query = query.filter(models.FundamentalLatestSnapshot.symbol == symbol.upper())

    rows = query.all()
    snapshots_modified = 0
    total_stripped = 0
    total_preserved = 0
    preserved_detail: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for snap in rows:
        metrics = snap.metrics_json or {}
        alias_keys = [k for k in metrics if k in ALIAS_NAMES]
        if not alias_keys:
            continue

        safe_to_strip = []
        to_keep = []
        for alias in alias_keys:
            canonical = resolve_metric_name(alias)
            if canonical in metrics:
                safe_to_strip.append(alias)
            else:
                to_keep.append(alias)
                preserved_detail[str(snap.symbol).upper()][alias] += 1

        if safe_to_strip:
            snapshots_modified += 1
            total_stripped += len(safe_to_strip)
            if apply:
                cleaned = {k: v for k, v in metrics.items() if k not in safe_to_strip}
                snap.metrics_json = cleaned
        total_preserved += len(to_keep)

    print(
        f"\n[FundamentalLatestSnapshot] alias key summary:"
    )
    print(f"  Safe to strip (canonical key present in same snapshot): {total_stripped}  (across {snapshots_modified} snapshots)")
    print(f"  Preserved (no canonical key in same snapshot)         : {total_preserved}")

    if preserved_detail:
        print("\n  -- PRESERVED snapshot alias keys --")
        for sym in sorted(preserved_detail):
            for alias, count in sorted(preserved_detail[sym].items()):
                canonical = resolve_metric_name(alias)
                print(f"  {sym:10s}  {alias!r:40s} -> {canonical!r}  (no canonical key present)")

    if apply and snapshots_modified:
        print(f"\n  [APPLY] Stripped alias keys from {snapshots_modified} snapshots ({total_preserved} keys preserved).")
    elif not apply:
        print("\n  [DRY-RUN] No snapshots modified.")

    return total_stripped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Write changes to DB (default: dry-run).")
    parser.add_argument("--symbol", default=None, help="Limit to a single ticker symbol.")
    args = parser.parse_args()

    if args.apply:
        print("*** APPLY MODE - changes will be written to the database ***")
    else:
        print("*** DRY-RUN MODE - no changes will be written (pass --apply to write) ***")

    db = SessionLocal()
    try:
        _purge_annual_metrics(db, symbol=args.symbol, apply=args.apply)
        _purge_snapshot_alias_keys(db, symbol=args.symbol, apply=args.apply)
        if args.apply:
            db.commit()
            print("\nCommitted.")
        else:
            db.rollback()
            print("\nDry-run complete - nothing committed.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
