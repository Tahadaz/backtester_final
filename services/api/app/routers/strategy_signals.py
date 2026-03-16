"""Strategy signals API — signal generation engine endpoints."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..market_data_loader import load_close_for_symbol
from ..schemas.strategy_signals import SmaEnsembleRequest

from quant_core.signal_engine.ensemble import run_sma_ensemble

router = APIRouter(prefix="/strategy", tags=["strategy-signals"])


@router.post("/signal/sma-ensemble")
def sma_ensemble(body: SmaEnsembleRequest, db: Session = Depends(get_db)):
    """Run the full SMA signal engine pipeline (Layers A→G)."""
    try:
        close = load_close_for_symbol(db, body.symbol, body.timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    result = run_sma_ensemble(
        close,
        symbol=body.symbol,
        horizon=body.horizon,
        timeframe=body.timeframe,
    )
    return asdict(result)
