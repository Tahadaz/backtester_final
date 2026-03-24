from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.worker.db import SessionLocal
from services.worker.tasks.ingest_market_data import ingest_excel_to_store

CASABLANCA_TZ = ZoneInfo("Africa/Casablanca")


def market_today() -> str:
    return datetime.now(CASABLANCA_TZ).date().isoformat()


def main() -> int:
    db = SessionLocal()
    try:
        today = market_today()
        rows = db.execute(
            text(
                """
                SELECT symbol, last_dataset_id, end_ts::date AS end_date
                FROM market_data_store
                WHERE timeframe = '1D' AND end_ts::date > :today
                ORDER BY symbol
                """
            ),
            {"today": today},
        ).mappings().all()

        if not rows:
            print("No contaminated symbols found.")
            return 0

        print("Contaminated symbols before repair:")
        for row in rows:
            print(f"  {row['symbol']}: {row['end_date']} (dataset={row['last_dataset_id']})")

        dataset_ids = []
        missing_dataset_symbols = []
        seen = set()
        for row in rows:
            dataset_id = row["last_dataset_id"]
            if dataset_id is None:
                missing_dataset_symbols.append(str(row["symbol"]))
                continue
            dataset_id = str(dataset_id)
            if dataset_id in seen:
                continue
            seen.add(dataset_id)
            dataset_ids.append(dataset_id)

        if missing_dataset_symbols:
            print("Symbols without a last_dataset_id; manual follow-up may be needed:")
            for symbol in missing_dataset_symbols:
                print(f"  {symbol}")

        for dataset_id in dataset_ids:
            print(f"\nRe-ingesting dataset {dataset_id}")
            result = ingest_excel_to_store(dataset_id)
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

        remaining = db.execute(
            text(
                """
                SELECT symbol, end_ts::date AS end_date
                FROM market_data_store
                WHERE timeframe = '1D' AND end_ts::date > :today
                ORDER BY symbol
                """
            ),
            {"today": today},
        ).mappings().all()

        if remaining:
            print("\nRemaining contaminated symbols after repair:")
            for row in remaining:
                print(f"  {row['symbol']}: {row['end_date']}")
            return 1

        print("\nRepair complete. No future-dated symbols remain.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
