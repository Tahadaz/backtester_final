from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import sqlalchemy as sa

from services.api.app.db import get_db  

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])

@router.get("")
def global_leaderboard(
    freq: str = "1D",
    portfolio_hash: str | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
    session: Session = Depends(get_db),
):
    # MVP: return all snapshot rows filtered
    stmt = sa.text("""
        SELECT *
        FROM best_strategy_snapshot
        WHERE freq = :freq
          AND (:portfolio_hash IS NULL OR portfolio_hash = :portfolio_hash)
          AND (:start_at IS NULL OR start_at = :start_at::timestamptz)
          AND (:end_at IS NULL OR end_at = :end_at::timestamptz)
        ORDER BY ticker, strategy_name
    """)
    rows = session.execute(stmt, {
        "freq": freq,
        "portfolio_hash": portfolio_hash,
        "start_at": start_at,
        "end_at": end_at,
    }).mappings().all()
    return {"items": list(rows)}

@router.get("/{ticker}")
def ticker_leaderboard(
    ticker: str,
    freq: str = "1D",
    portfolio_hash: str | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
    session: Session = Depends(get_db),
):
    stmt = sa.text("""
        SELECT *
        FROM best_strategy_snapshot
        WHERE ticker = :ticker
          AND freq = :freq
          AND (:portfolio_hash IS NULL OR portfolio_hash = :portfolio_hash)
          AND (:start_at IS NULL OR start_at = :start_at::timestamptz)
          AND (:end_at IS NULL OR end_at = :end_at::timestamptz)
        ORDER BY strategy_name
    """)
    rows = session.execute(stmt, {
        "ticker": ticker,
        "freq": freq,
        "portfolio_hash": portfolio_hash,
        "start_at": start_at,
        "end_at": end_at,
    }).mappings().all()
    return {"items": list(rows)}
