"""Prune superseded fundamental valuation artifacts.

For each symbol, keep the canonical import's current snapshot and valuation
artifacts. Delete only superseded per-symbol latest snapshot, valuation,
ensemble, and projection rows. Import audit rows, annual/period metrics, and
source-document provenance are preserved.

Usage:
    # dry-run (default)
    python services/api/scripts/prune_superseded_fundamentals.py

    # restrict to symbols
    python services/api/scripts/prune_superseded_fundamentals.py --symbols MNG ATW

    # apply deletes
    python services/api/scripts/prune_superseded_fundamentals.py --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "services" / "api") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

from sqlalchemy.orm import Session  # noqa: E402

from app import models  # noqa: E402
from app.db import _ensure_session_factory  # noqa: E402
from app.services.fundamentals import (  # noqa: E402
    SUCCEEDED_IMPORT_STATUSES,
    _table_exists,
    latest_snapshot_rows_by_symbol,
    refresh_canonical_snapshot_flags,
)


def _import_key(row: models.FundamentalImport) -> dt.datetime:
    return (
        row.completed_at
        or row.imported_at
        or row.created_at
        or dt.datetime.min.replace(tzinfo=dt.timezone.utc)
    )


def _artifact_counts(db: Session, *, symbol: str, import_ids: set[uuid.UUID] | None = None) -> dict[str, int]:
    def _count(model: Any) -> int:
        if not _table_exists(db, model):
            return 0
        query = db.query(model).filter(model.symbol == symbol)
        if import_ids is not None:
            query = query.filter(model.import_id.in_(import_ids))
        return int(query.count())

    counts = {
        "snapshots": _count(models.FundamentalLatestSnapshot),
        "valuations": _count(models.FundamentalValuationResult),
        "ensembles": _count(models.FundamentalEnsembleResult),
    }
    counts["projections"] = _count(models.FundamentalProjection)
    return counts


def _delete_artifacts(db: Session, *, symbol: str, import_ids: set[uuid.UUID]) -> dict[str, int]:
    deleted: dict[str, int] = {}

    def _delete(model: Any, key: str) -> None:
        if not _table_exists(db, model):
            deleted[key] = 0
            return
        deleted[key] = (
            db.query(model)
            .filter(model.symbol == symbol, model.import_id.in_(import_ids))
            .delete(synchronize_session=False)
        )

    _delete(models.FundamentalProjection, "projections")
    _delete(models.FundamentalValuationResult, "valuations")
    _delete(models.FundamentalEnsembleResult, "ensembles")
    _delete(models.FundamentalLatestSnapshot, "snapshots")
    return deleted


def prune_superseded_fundamentals(
    db: Session,
    *,
    symbols: list[str] | None = None,
    apply: bool = False,
) -> list[dict[str, Any]]:
    wanted = sorted({symbol.strip().upper() for symbol in symbols or [] if symbol and symbol.strip()})
    refresh_canonical_snapshot_flags(db, symbols=wanted or None)
    canonical = latest_snapshot_rows_by_symbol(db, symbols=wanted or None)
    if wanted:
        canonical = {symbol: row for symbol, row in canonical.items() if symbol in wanted}
    if not canonical:
        return []

    candidate_rows = (
        db.query(models.FundamentalLatestSnapshot, models.FundamentalImport)
        .join(models.FundamentalImport, models.FundamentalLatestSnapshot.import_id == models.FundamentalImport.id)
        .filter(models.FundamentalImport.status.in_(SUCCEEDED_IMPORT_STATUSES))
        .filter(models.FundamentalLatestSnapshot.symbol.in_(sorted(canonical)))
        .all()
    )
    imports_by_id = {row.id: row for _snapshot, row in candidate_rows}
    snapshots_by_symbol: dict[str, list[models.FundamentalLatestSnapshot]] = {}
    for snapshot, _import_row in candidate_rows:
        snapshots_by_symbol.setdefault(str(snapshot.symbol).upper(), []).append(snapshot)

    report: list[dict[str, Any]] = []
    for symbol, canonical_snapshot in sorted(canonical.items()):
        canonical_import = imports_by_id.get(canonical_snapshot.import_id) or db.get(models.FundamentalImport, canonical_snapshot.import_id)
        if canonical_import is None:
            continue
        canonical_key = _import_key(canonical_import)
        stale_import_ids: set[uuid.UUID] = set()
        for snapshot in snapshots_by_symbol.get(symbol, []):
            if snapshot.import_id == canonical_snapshot.import_id:
                continue
            import_row = imports_by_id.get(snapshot.import_id)
            if import_row is None:
                continue
            if _import_key(import_row) <= canonical_key:
                stale_import_ids.add(snapshot.import_id)
        before_all = _artifact_counts(db, symbol=symbol)
        before_stale = _artifact_counts(db, symbol=symbol, import_ids=stale_import_ids) if stale_import_ids else {
            "snapshots": 0,
            "valuations": 0,
            "ensembles": 0,
            "projections": 0,
        }
        deleted = {"snapshots": 0, "valuations": 0, "ensembles": 0, "projections": 0}
        if apply and stale_import_ids:
            deleted = _delete_artifacts(db, symbol=symbol, import_ids=stale_import_ids)
            refresh_canonical_snapshot_flags(db, symbols=[symbol])
        after_all = _artifact_counts(db, symbol=symbol)
        report.append(
            {
                "symbol": symbol,
                "canonical_import_id": str(canonical_snapshot.import_id),
                "stale_import_count": len(stale_import_ids),
                "stale_import_ids": sorted(str(item) for item in stale_import_ids),
                "before": before_all,
                "stale_rows": before_stale,
                "deleted": deleted,
                "after": after_all,
            }
        )
    if apply:
        db.commit()
    else:
        db.rollback()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="Delete superseded artifacts (default: dry-run)")
    parser.add_argument("--symbols", nargs="*", metavar="SYM", help="Restrict to these symbols")
    args = parser.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[prune_superseded_fundamentals] mode={mode}")
    session_factory = _ensure_session_factory()
    with session_factory() as db:
        report = prune_superseded_fundamentals(db, symbols=args.symbols, apply=args.apply)
        if not report:
            print("  No canonical snapshots found.")
            return
        for item in report:
            print(
                "  {symbol}: canonical={canonical_import_id} stale_imports={stale_import_count} "
                "stale_rows={stale_rows} deleted={deleted} after={after}".format(**item)
            )
        if not args.apply:
            print("  [DRY-RUN] No changes made. Rerun with --apply to delete superseded artifacts.")


if __name__ == "__main__":
    main()
