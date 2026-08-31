"""Audit or apply exact StockAnalysis-to-BVC publication-date reconciliation."""
from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.api.app.services.fundamental_publication_reconciliation import reconcile_stockanalysis_publication_dates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Persist exact verified matches; default is read-only audit.")
    parser.add_argument("--symbols", default="", help="Optional comma-separated symbol scope.")
    args = parser.parse_args()
    symbols = {part.strip().upper() for part in args.symbols.split(",") if part.strip()} or None
    engine = create_engine(os.environ.get("DATABASE_URL", "postgresql+psycopg2://app:app@127.0.0.1:5555/quant"))
    with Session(engine) as db:
        result = reconcile_stockanalysis_publication_dates(db, apply=args.apply, symbols=symbols)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
