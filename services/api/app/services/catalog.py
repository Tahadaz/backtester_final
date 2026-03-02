from __future__ import annotations
import sqlalchemy as sa
from sqlalchemy.orm import Session

def list_tickers(session: Session, freq: str):
    # “best dataset per ticker” = latest dataset_ticker row per ticker
    # Use DISTINCT ON (Postgres) for simplicity/performance
    stmt = sa.text("""
        SELECT DISTINCT ON (dt.ticker)
            dt.ticker, dt.freq, dt.start_at, dt.end_at, dt.bars_count, dt.dataset_id
        FROM dataset_ticker dt
        WHERE dt.freq = :freq
        ORDER BY dt.ticker, dt.created_at DESC
    """)
    rows = session.execute(stmt, {"freq": freq}).mappings().all()
    return list(rows)

def resolve_ticker(session: Session, ticker: str, freq: str):
    stmt = sa.text("""
        SELECT
            dt.ticker, dt.freq, dt.start_at, dt.end_at, dt.bars_count, dt.dataset_id, dt.object_key
        FROM dataset_ticker dt
        WHERE dt.ticker = :ticker AND dt.freq = :freq
        ORDER BY dt.created_at DESC
        LIMIT 1
    """)
    row = session.execute(stmt, {"ticker": ticker, "freq": freq}).mappings().first()
    return row
