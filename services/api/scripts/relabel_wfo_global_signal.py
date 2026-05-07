#!/usr/bin/env python
"""One-time backfill: fix wfo_global_signals.signal_label from trend vocabulary to aggregate vocabulary.

All rows currently store "Haussier" / "Baissier" because the compute function
passed signal_type_label("trend", …) instead of signal_type_label("aggregate", …).
This script rewrites signal_label in-place from the already-correct global_score_pct.

Run from repo root:

    python -m services.api.scripts.relabel_wfo_global_signal [--dry-run]

or from services/api/:

    python -m scripts.relabel_wfo_global_signal [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from sqlalchemy import create_engine, text


AGGREGATE_CASES = """
CASE
    WHEN global_score_pct >  50 THEN 'Achat fort'
    WHEN global_score_pct >  15 THEN 'Achat'
    WHEN global_score_pct >= -15 THEN 'Neutre'
    WHEN global_score_pct >= -50 THEN 'Vente'
    ELSE 'Vente forte'
END
""".strip()

TREND_LABELS = {"Très haussier", "Haussier", "Neutre", "Baissier", "Très baissier"}


def relabel(db_url: str, dry_run: bool) -> None:
    engine = create_engine(db_url)

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, symbol, horizon, variant, global_score_pct, signal_label
                FROM wfo_global_signals
                WHERE status = 'succeeded'
                  AND global_score_pct IS NOT NULL
                ORDER BY symbol, horizon, variant
                """
            )
        ).mappings().all()

        to_update: list[tuple[int, float, str, str]] = []
        already_ok = 0

        for row in rows:
            score = float(row["global_score_pct"])
            if score > 50:
                new_label = "Achat fort"
            elif score > 15:
                new_label = "Achat"
            elif score >= -15:
                new_label = "Neutre"
            elif score >= -50:
                new_label = "Vente"
            else:
                new_label = "Vente forte"

            if row["signal_label"] == new_label:
                already_ok += 1
                continue

            to_update.append((row["id"], score, row["signal_label"] or "", new_label))
            print(
                f"  [{row['symbol']} / {row['horizon']} / {row['variant']}]"
                f"  {row['signal_label']!r} → {new_label!r}"
                f"  (score={score:+.1f})"
            )

        print(f"\nAlready correct: {already_ok}")
        print(f"To update:       {len(to_update)}")

        if not to_update:
            print("Nothing to do.")
            return

        if dry_run:
            print("\n--dry-run: no changes written.")
            return

        conn.execute(
            text(
                f"""
                UPDATE wfo_global_signals
                SET signal_label = {AGGREGATE_CASES}
                WHERE status = 'succeeded'
                  AND global_score_pct IS NOT NULL
                """
            )
        )
        conn.commit()
        print(f"\nUpdated {len(to_update)} rows.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Relabel WFO global signal_label from trend → aggregate vocabulary.")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    parser.add_argument("--db-url", default=os.environ.get("DATABASE_URL", ""), help="SQLAlchemy DB URL")
    args = parser.parse_args()

    db_url = args.db_url
    if not db_url:
        print("ERROR: provide --db-url or set DATABASE_URL environment variable.", file=sys.stderr)
        sys.exit(1)

    relabel(db_url=db_url, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
