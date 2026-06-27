"""Ensemble signal endpoints: sma-ensemble, family-ensemble."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import Depends
from sqlalchemy.orm import Session

from ...db import get_db
from ...schemas.strategy_signals import FamilyEnsembleRequest, SmaEnsembleRequest
from ._shared import router, _get_or_compute

@router.post("/signal/sma-ensemble")
def sma_ensemble(body: SmaEnsembleRequest, db: Session = Depends(get_db)):
    """Run the full SMA signal engine pipeline (Layers A->G)."""
    detail = _get_or_compute(db, "sma", body.symbol, body.horizon, body.timeframe, body.cost_bps, body.cooldown_bars, variant="expanded")
    return asdict(detail.signal)


@router.post("/signal/family-ensemble")
def family_ensemble(body: FamilyEnsembleRequest, db: Session = Depends(get_db)):
    """Run the full signal engine pipeline for any family (Layers A->G)."""
    detail = _get_or_compute(db, body.family, body.symbol, body.horizon, body.timeframe, body.cost_bps, body.cooldown_bars, variant=body.variant)
    return asdict(detail.signal)

