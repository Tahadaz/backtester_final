"""Fix CTM FY2025: CFS_Net_Income_Top_Of_CFS scrape error + add NetIncome_Group.

Root cause: stockanalysis.com inconsistently used the RNPG (16.08M, parent-attributable)
as the CFS starting point for FY2025, but used the consolidated total (46.62M) in FY2024.
Under IFRS indirect method, the CFS must start from consolidated profit.

IS (consolidated): Pretax=33.05M - Tax=16.97M = Earnings 16.08M + Minority 40.12M
  -> Net Income (consolidated) = 56.2M  [our NetIncome field, correct]
CFS (scraped):     16.08M              [wrong -- should be 56.2M]

Two overrides for CTM FY2025:
  CFS_Net_Income_Top_Of_CFS = 56,200,000   (consolidated, matches IS)
  NetIncome_Group            = 16,080,000   (RNPG -- parent-attributable after minority)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from services.api.app import models
from services.api.app.services.fundamentals import (
    canonical_snapshot_for_symbol,
    latest_data_verification,
    reverify_symbol,
    _load_history,
    _rows_by_metric_from_history,
    _prev_rows_by_metric_from_history,
)
from core.quant_core.fundamentals.integrity import build_data_tieout_report

DB_URL = "postgresql+psycopg2://app:app@127.0.0.1:5555/quant"

OVERRIDES = [
    {
        "symbol": "CTM",
        "statement_year": 2025,
        "metric_name": "CFS_Net_Income_Top_Of_CFS",
        "metric_value": 56_200_000.0,
        "note": "fix_ctm_cfs_minority: stockanalysis scraped RNPG (16.08M) instead of consolidated profit (56.2M) as CFS start; IFRS indirect method requires consolidated total",
    },
    {
        "symbol": "CTM",
        "statement_year": 2025,
        "metric_name": "NetIncome_Group",
        "metric_value": 16_080_000.0,
        "note": "fix_ctm_cfs_minority: RNPG (parent-attributable after 40.12M NCI), sourced from IS Earnings from Continuing Operations line",
    },
]


def _show_current(db) -> None:
    existing = db.execute(text("""
        SELECT metric_name, metric_value, note, is_current, created_at
        FROM fundamental_metric_override
        WHERE symbol = 'CTM' AND statement_year = 2025
        ORDER BY metric_name, created_at DESC
    """)).fetchall()
    if existing:
        print("  Existing overrides for (CTM, 2025):")
        for r in existing:
            print(f"    {r[0]:45s} = {r[1]/1e6:.3f}M  current={r[3]}  note={r[2]!r}")
    else:
        print("  No existing overrides for (CTM, 2025)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    engine = create_engine(DB_URL)
    Session = sessionmaker(bind=engine)

    print(f"{'DRY RUN' if not args.apply else 'APPLY'} -- CTM CFS + minority fix\n")

    with Session() as db:
        _show_current(db)
        print()

        snap = canonical_snapshot_for_symbol(db, "CTM")
        sy = snap.latest_statement_year

        # Show current tieout state
        cached = latest_data_verification(db, import_id=snap.import_id, symbol="CTM", statement_year=sy)
        print(f"  Current cached verdict: {cached.status if cached else 'NONE'}:{cached.reason if cached else ''}")

        # Show planned overrides
        print("\n  Planned overrides:")
        for ov in OVERRIDES:
            print(f"    INSERT/UPDATE fundamental_metric_override")
            print(f"      symbol=CTM  year=2025  metric={ov['metric_name']}")
            print(f"      value={ov['metric_value']/1e6:.3f}M  note={ov['note']!r}")
        print()

        # Simulate fresh tieout after override (in-memory)
        hist = _load_history(db, snap.import_id, "CTM")
        rows_bm, my = _rows_by_metric_from_history(hist, sy)
        # Patch in the override values for simulation
        rows_bm["CFS_Net_Income_Top_Of_CFS"] = 56_200_000.0
        rows_bm["NetIncome_Group"] = 16_080_000.0
        prev = _prev_rows_by_metric_from_history(hist, sy)
        rep_sim = build_data_tieout_report("CTM", sy, rows_bm, previous_rows_by_metric=prev,
                                           snapshot_year=sy, metric_years=my, period_type="annual")
        print(f"  Simulated tieout after override: {rep_sim.status!r}  reason={rep_sim.reason!r}")
        print(f"  failed_checks: {rep_sim.failed_checks}")
        print()

        if not args.apply:
            print("Pass --apply to execute.")
            return

        # Apply overrides
        for ov in OVERRIDES:
            existing = (
                db.query(models.FundamentalMetricOverride)
                .filter(
                    models.FundamentalMetricOverride.symbol == ov["symbol"],
                    models.FundamentalMetricOverride.statement_year == ov["statement_year"],
                    models.FundamentalMetricOverride.metric_name == ov["metric_name"],
                    models.FundamentalMetricOverride.is_current.is_(True),
                )
                .one_or_none()
            )
            if existing is not None:
                existing.is_current = False
                db.add(existing)

            row = models.FundamentalMetricOverride(
                symbol=ov["symbol"],
                statement_year=ov["statement_year"],
                metric_name=ov["metric_name"],
                metric_value=ov["metric_value"],
                note=ov["note"],
                created_by="fix_ctm_cfs_minority.py",
                is_current=True,
            )
            db.add(row)
        db.flush()

        # Reverify CTM
        result = reverify_symbol(db, "CTM")
        db.commit()
        print(f"  WRITTEN. New verdict: status={result.status!r}  reason={result.reason!r}")
        print(f"  failed_checks: {result.failed_checks_json}")


if __name__ == "__main__":
    main()
