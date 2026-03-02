from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..db import get_db

router = APIRouter(prefix="/snapshots", tags=["snapshots"])

@router.get("")
def list_snapshots(
    spec_hash: str,
    timeframe: str = "1D",
    db: Session = Depends(get_db),
):
    rows = db.execute(
        text("""
        SELECT *
        FROM best_strategy_snapshot
        WHERE spec_hash = :spec_hash AND timeframe = :timeframe
        ORDER BY symbol, strategy_kind
        """),
        {"spec_hash": spec_hash, "timeframe": timeframe},
    ).mappings().all()
    return {"items": list(rows)}

@router.get("/{symbol}")
def symbol_snapshots(
    symbol: str,
    spec_hash: str,
    timeframe: str = "1D",
    db: Session = Depends(get_db),
):
    rows = db.execute(
        text("""
        SELECT *
        FROM best_strategy_snapshot
        WHERE spec_hash = :spec_hash AND timeframe = :timeframe AND symbol = :symbol
        ORDER BY strategy_kind
        """),
        {"spec_hash": spec_hash, "timeframe": timeframe, "symbol": symbol},
    ).mappings().all()
    return {"items": list(rows)}
