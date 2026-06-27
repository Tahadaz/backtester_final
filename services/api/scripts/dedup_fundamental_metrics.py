"""Collapse each (symbol, metric_name, statement_year) to one authoritative row.

For each group the script:
1. Drops rows where metric_value IS NULL.
2. Rejects per-year candidates whose absolute magnitude is >100x off the group
   median (same outlier rule as the valuation resolver).
3. Keeps the highest-ranked survivor:
     non-proxy > most-recent as_of_date > highest source_document_id > lowest id.
4. DELETEs all other rows in the group.

Usage:
    # dry-run (default): print counts only
    python services/api/scripts/dedup_fundamental_metrics.py

    # show detailed report per metric
    python services/api/scripts/dedup_fundamental_metrics.py --verbose

    # limit to specific symbols
    python services/api/scripts/dedup_fundamental_metrics.py --symbols MNG ATW

    # apply changes (DELETE losing rows)
    python services/api/scripts/dedup_fundamental_metrics.py --apply
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import defaultdict
from math import isfinite
from pathlib import Path
from statistics import median

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "services" / "api") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "services" / "api"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import _ensure_session_factory  # noqa: E402
from app import models  # noqa: E402


# ---------------------------------------------------------------------------
# Rank / outlier helpers (mirrors projection._pick_best_row_per_year logic)
# ---------------------------------------------------------------------------

def _finite(value) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _row_rank(row: models.FundamentalAnnualMetric) -> tuple:
    """Higher tuple = more authoritative row."""
    return (
        1 if row.metric_value is not None else 0,
        0 if row.is_proxy else 1,
        (row.as_of_date or dt.date.min).toordinal(),
        int(row.source_document_id or 0),
        -int(row.id or 0),  # lower id = earlier insert (less preferred)
    )


def _is_outlier(value: float, reference: float) -> bool:
    if reference <= 0:
        return False
    mag = abs(value)
    if mag == 0:
        return False
    ratio = mag / reference if mag >= reference else reference / mag
    return ratio > 100.0


# ---------------------------------------------------------------------------
# Core dedup logic
# ---------------------------------------------------------------------------

def _dedup_group(
    rows: list[models.FundamentalAnnualMetric],
) -> tuple[models.FundamentalAnnualMetric | None, list[models.FundamentalAnnualMetric]]:
    """Return (winner, losers) for one (symbol, metric, year) group."""
    # Drop null rows — they are always losers
    finite_rows = [r for r in rows if _finite(r.metric_value) is not None]
    null_rows = [r for r in rows if _finite(r.metric_value) is None]

    if not finite_rows:
        # All null — nothing to keep; delete all
        return None, rows

    # Compute group magnitude median for outlier detection
    mags = [abs(float(r.metric_value)) for r in finite_rows]  # type: ignore[arg-type]
    group_med = float(median(mags))

    survivors = [r for r in finite_rows if not _is_outlier(float(r.metric_value), group_med)]  # type: ignore[arg-type]
    outlier_rows = [r for r in finite_rows if _is_outlier(float(r.metric_value), group_med)]  # type: ignore[arg-type]

    if not survivors:
        # All rejected as outliers (shouldn't happen) — keep best finite row
        survivors = [max(finite_rows, key=_row_rank)]
        outlier_rows = [r for r in finite_rows if r is not survivors[0]]

    winner = max(survivors, key=_row_rank)
    losers = [r for r in survivors if r is not winner] + outlier_rows + null_rows
    return winner, losers


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="DELETE losing rows (default: dry-run)")
    parser.add_argument("--symbols", nargs="*", metavar="SYM", help="Restrict to these symbols")
    parser.add_argument("--verbose", action="store_true", help="Print per-metric detail")
    args = parser.parse_args()

    session_factory = _ensure_session_factory()
    with session_factory() as db:
        _run(db, apply=args.apply, symbols=args.symbols, verbose=args.verbose)


def _run(
    db: Session,
    *,
    apply: bool,
    symbols: list[str] | None,
    verbose: bool,
) -> None:
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[dedup_fundamental_metrics] mode={mode}")

    # Load all annual metric rows (only the columns we need for ranking)
    query = db.query(models.FundamentalAnnualMetric)
    if symbols:
        query = query.filter(models.FundamentalAnnualMetric.symbol.in_([s.upper() for s in symbols]))
    query = query.order_by(
        models.FundamentalAnnualMetric.symbol,
        models.FundamentalAnnualMetric.metric_name,
        models.FundamentalAnnualMetric.statement_year,
    )

    # Group by (symbol, metric_name, statement_year)
    groups: dict[tuple[str, str, int], list[models.FundamentalAnnualMetric]] = defaultdict(list)
    total_rows = 0
    for row in query.all():
        key = (str(row.symbol).upper(), str(row.metric_name), int(row.statement_year))
        groups[key].append(row)
        total_rows += 1

    print(f"  Loaded {total_rows:,} rows across {len(groups):,} (symbol, metric, year) groups")

    # Identify groups that need cleanup
    dirty_groups: list[tuple[tuple, models.FundamentalAnnualMetric | None, list]] = []
    for key, rows in groups.items():
        if len(rows) <= 1 and all(_finite(r.metric_value) is not None for r in rows):
            continue  # already clean
        winner, losers = _dedup_group(rows)
        if losers:
            dirty_groups.append((key, winner, losers))

    if not dirty_groups:
        print("  No cleanup needed — database is already clean.")
        return

    # Aggregate statistics per metric
    metric_stats: dict[str, dict] = defaultdict(lambda: {"groups": 0, "rows_to_delete": 0, "null_deletions": 0, "outlier_deletions": 0})
    total_deletions = 0
    for key, winner, losers in dirty_groups:
        _sym, metric, _yr = key
        ms = metric_stats[metric]
        ms["groups"] += 1
        for loser in losers:
            ms["rows_to_delete"] += 1
            total_deletions += 1
            if _finite(loser.metric_value) is None:
                ms["null_deletions"] += 1
            elif winner is not None:
                winner_val = float(winner.metric_value)  # type: ignore[arg-type]
                loser_val = float(loser.metric_value)  # type: ignore[arg-type]
                ref = abs(winner_val) if winner_val != 0 else 1.0
                if _is_outlier(loser_val, ref):
                    ms["outlier_deletions"] += 1

    # Print summary
    print(f"\n  {'Metric':<45} {'Groups':>7} {'Delete':>7} {'Nulls':>7} {'Outliers':>9}")
    print("  " + "-" * 80)
    for metric in sorted(metric_stats):
        ms = metric_stats[metric]
        print(
            f"  {metric:<45} {ms['groups']:>7,} {ms['rows_to_delete']:>7,}"
            f" {ms['null_deletions']:>7,} {ms['outlier_deletions']:>9,}"
        )
    print("  " + "-" * 80)
    print(f"  Total rows to delete: {total_deletions:,}")

    if verbose:
        print("\n[Verbose: sample dirty groups]")
        for key, winner, losers in dirty_groups[:20]:
            sym, metric, yr = key
            wval = winner.metric_value if winner else None
            print(f"  {sym} / {metric} / {yr}  winner={wval}  losers={[r.metric_value for r in losers]}")

    if not apply:
        print(f"\n  [DRY-RUN] No changes made. Rerun with --apply to delete {total_deletions:,} rows.")
        return

    # Apply deletions
    deleted = 0
    for _key, _winner, losers in dirty_groups:
        loser_ids = [r.id for r in losers if r.id is not None]
        if loser_ids:
            db.execute(
                text("DELETE FROM fundamental_annual_metric WHERE id = ANY(:ids)"),
                {"ids": loser_ids},
            )
            deleted += len(loser_ids)

    db.commit()
    print(f"\n  [APPLY] Deleted {deleted:,} rows.")


if __name__ == "__main__":
    main()
