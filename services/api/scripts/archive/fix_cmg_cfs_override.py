"""Correction A: revert wrong CMG overrides and apply correct CFS correction.

Dry-run by default; pass --apply to write.

Evidence for 244.01M being the IS truth:
  - FY2021-2024: CFS_Net_Income_Top_Of_CFS == IS NetIncome every year (no minority gap).
  - FY2025: stockanalysis (NetIncome=244.01M) and bvc (NetIncome=244.00M) independently
    agree on IS. Only the lone CFS figure says 252.75M.
  - NetIncome_Growth=33.68% = 244.01/182.53 - 1 corroborates 244.01M.

The previous fix3 was wrong: it invented an 8.74M minority by setting NetIncome=252.75M
and NetIncome_Group=244.01M.  That direction inflates the reported figure.

Correct fix:
  1. Retire the two wrong overrides (id=10, id=11 in fundamental_metric_override).
  2. Add override CFS_Net_Income_Top_Of_CFS = 244,010,000 for CMG FY2025.
  3. Re-run reverify for CMG to refresh the cached tieout verdict.
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
    reverify_symbol,
    latest_data_verification,
    _load_history,
    _rows_by_metric_from_history,
    _prev_rows_by_metric_from_history,
)
from core.quant_core.fundamentals.integrity import build_data_tieout_report

DB_URL = "postgresql+psycopg2://app:app@127.0.0.1:5555/quant"


def _show_overrides(db) -> list:
    rows = db.execute(text("""
        SELECT id, statement_year, metric_name, metric_value, is_current, note
        FROM fundamental_metric_override
        WHERE symbol = 'CMG'
        ORDER BY statement_year, metric_name, is_current DESC
    """)).fetchall()
    return rows


def _fresh_tieout(db) -> tuple:
    snap = canonical_snapshot_for_symbol(db, "CMG")
    sy = snap.latest_statement_year
    hist = _load_history(db, snap.import_id, "CMG")
    rows, my = _rows_by_metric_from_history(hist, sy)
    prev = _prev_rows_by_metric_from_history(hist, sy)
    rep = build_data_tieout_report("CMG", sy, rows, previous_rows_by_metric=prev,
                                   snapshot_year=sy, metric_years=my, period_type="annual")
    ni = rows.get("NetIncome") or rows.get("Resultat_net")
    cfs = rows.get("CFS_Net_Income_Top_Of_CFS")
    return rep, ni, cfs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    engine = create_engine(DB_URL)
    Session = sessionmaker(bind=engine)

    print(f"{'DRY RUN' if not args.apply else 'APPLY'} -- CMG Correction A\n")

    with Session() as db:
        print("Current overrides:")
        for r in _show_overrides(db):
            print(f"  id={r[0]}  FY{r[1]}  {r[2]}={r[3]}  is_current={r[4]}  note={r[5]!r}")

        rep_before, ni_before, cfs_before = _fresh_tieout(db)
        print(f"\nPre-change tieout: status={rep_before.status!r}  NetIncome={ni_before}  CFS={cfs_before}")

        print("\nPlanned changes:")
        print("  1. Retire id=10 (CMG FY2025 NetIncome=252750000)  -> is_current=False")
        print("  2. Retire id=11 (CMG FY2025 NetIncome_Group=244010000) -> is_current=False")
        print("  3. INSERT fundamental_metric_override:")
        print("       symbol=CMG  year=2025  metric=CFS_Net_Income_Top_Of_CFS")
        print("       value=244,010,000")
        print("       note='correction-a: anomalous CFS-top corrected to match two independent IS sources'")
        print("  4. reverify CMG -> update fundamental_data_verification cache")
        print()

        if not args.apply:
            print("Pass --apply to execute.")
            return

        # Step 1+2: retire the wrong overrides
        for ov_id in [10, 11]:
            db.execute(text("""
                UPDATE fundamental_metric_override SET is_current = false WHERE id = :id
            """), {"id": ov_id})

        # Step 3: insert correct CFS override
        existing_cfs = (
            db.query(models.FundamentalMetricOverride)
            .filter(
                models.FundamentalMetricOverride.symbol == "CMG",
                models.FundamentalMetricOverride.statement_year == 2025,
                models.FundamentalMetricOverride.metric_name == "CFS_Net_Income_Top_Of_CFS",
                models.FundamentalMetricOverride.is_current.is_(True),
            )
            .one_or_none()
        )
        if existing_cfs is not None:
            existing_cfs.is_current = False
            db.add(existing_cfs)

        row = models.FundamentalMetricOverride(
            symbol="CMG",
            statement_year=2025,
            metric_name="CFS_Net_Income_Top_Of_CFS",
            metric_value=244_010_000.0,
            note="correction-a: anomalous CFS-top corrected to match two independent IS sources (stockanalysis 244.01M + bvc 244.00M); FY2021-2024 show CFS==IS with no minority gap",
            created_by="fix_cmg_cfs_override.py",
            is_current=True,
        )
        db.add(row)
        db.flush()
        print("Steps 1-3 done.")

        # Step 4: reverify
        snap = canonical_snapshot_for_symbol(db, "CMG")
        ver = reverify_symbol(db, "CMG")
        db.commit()
        print(f"Step 4 done: CMG verification -> status={ver.status!r}  reason={ver.reason!r}")

        # Confirm post-change tieout
        with Session() as db2:
            rep_after, ni_after, cfs_after = _fresh_tieout(db2)
            print(f"\nPost-change tieout: status={rep_after.status!r}  NetIncome={ni_after}  CFS={cfs_after}")
            cached = latest_data_verification(db2, import_id=snap.import_id, symbol="CMG", statement_year=snap.latest_statement_year)
            print(f"Cached verdict:     status={cached.status!r}  reason={cached.reason!r}")


if __name__ == "__main__":
    main()
