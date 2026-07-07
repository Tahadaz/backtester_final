"""Fix 3: CMG t6_ni_link — reclassify NetIncome as consolidated and add NetIncome_Group.

Dry-run by default; pass --apply to write.

Root cause: stockanalysis stored CMG's RNPG (244.01M) as NetIncome.  The consolidated
total (252.75M) is confirmed by CFS_Net_Income_Top_Of_CFS and by Pretax_Income - Tax
(368.31M - 115.55M = 252.76M).

Two metric_override rows (symbol+year keyed, no import_id dependency):
  (CMG, 2025, NetIncome)       = 252_750_000   [consolidated — matches CFS]
  (CMG, 2025, NetIncome_Group) = 244_010_000   [RNPG — reclassified from original NetIncome]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from services.api.app import models

DB_URL = "postgresql+psycopg2://app:app@127.0.0.1:5555/quant"

OVERRIDES = [
    {"symbol": "CMG", "statement_year": 2025, "metric_name": "NetIncome",
     "metric_value": 252_750_000.0,
     "note": "fix3: consolidated NI from CFS_Net_Income_Top_Of_CFS; original 244.01M was RNPG"},
    {"symbol": "CMG", "statement_year": 2025, "metric_name": "NetIncome_Group",
     "metric_value": 244_010_000.0,
     "note": "fix3: RNPG reclassified from original NetIncome stored by stockanalysis"},
]


def _show_current(db, sym: str, year: int) -> None:
    rows = db.execute(text("""
        SELECT metric_name, metric_value, note, is_current, created_by, created_at
        FROM fundamental_metric_override
        WHERE symbol = :sym AND statement_year = :year
        ORDER BY metric_name, created_at DESC
    """), {"sym": sym, "year": year}).fetchall()
    if rows:
        print(f"  Existing overrides for ({sym}, {year}):")
        for r in rows:
            print(f"    {r[0]}: {r[1]}  note={r[2]!r}  is_current={r[3]}  by={r[4]}  at={r[5]}")
    else:
        print(f"  No existing overrides for ({sym}, {year})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    engine = create_engine(DB_URL)
    Session = sessionmaker(bind=engine)

    print(f"{'DRY RUN' if not args.apply else 'APPLY'} — CMG NetIncome reclassification\n")

    with Session() as db:
        _show_current(db, "CMG", 2025)
        print()
        print("Planned changes:")
        for ov in OVERRIDES:
            print(f"  INSERT/UPDATE fundamental_metric_override")
            print(f"    symbol={ov['symbol']}  year={ov['statement_year']}  metric={ov['metric_name']}")
            print(f"    value={ov['metric_value']:,.0f}  note={ov['note']!r}")
            print()

        if not args.apply:
            print("Pass --apply to execute.")
            return

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
                created_by="fix_cmg_ni_group.py",
                is_current=True,
            )
            db.add(row)

        db.commit()
        print("WRITTEN. Run reverify_symbols.py CMG to confirm t6_ni_link passes.")


if __name__ == "__main__":
    main()
