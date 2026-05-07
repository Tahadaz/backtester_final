"""
Factor selection router.

Exposes horizon-aware diagnostics for the econometric factor-selection pipeline.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import get_db
from ..queue import _get_macro_ingest_queue
from ..services.factor_selection_state import normalize_selection_horizon

router = APIRouter(prefix="/factor-selection", tags=["factor-selection"])


class FactorRelevanceOut(BaseModel):
    symbol: str
    horizon: str
    factor_canonical_id: str
    rank: int | None
    ic: float | None
    spearman_ic: float | None = None
    pearson_corr: float | None = None
    ic_t_stat: float | None
    bh_p_adj: float | None
    lasso_coef: float | None
    relevance_score: float | None = None
    n_obs: int | None = None
    selected_reason: str | None = None
    cusum_status: str
    low_confidence: bool
    next_forced_recal: str | None
    history_n_days: int | None
    last_calibrated_at: str
    cusum_drift_score: float | None
    is_active: bool


class Stage1CacheOut(BaseModel):
    symbol: str
    horizon: str
    factor_canonical_id: str
    ic_mean: float
    spearman_ic: float | None = None
    pearson_corr: float | None = None
    ic_tstat: float
    bh_p_adj: float | None
    relevance_score: float | None = None
    n_obs: int | None = None
    selected_reason: str | None = None
    passed_fdr: bool
    regime_start: str | None
    low_confidence: bool
    history_n_days: int | None
    calculated_at: str


@router.get("/stocks/{symbol}/active", response_model=list[FactorRelevanceOut])
def get_active_factors_for_stock(
    symbol: str,
    horizon: str | None = Query(None),
    db: Session = Depends(get_db),
) -> Any:
    clauses = ["symbol = :symbol", "cusum_status = 'valid'"]
    params: dict[str, Any] = {"symbol": symbol.upper()}
    if horizon:
        params["horizon"] = normalize_selection_horizon(horizon)
        clauses.append("horizon = :horizon")
    rows = db.execute(
        text(
            f"""
            SELECT symbol, horizon, factor_canonical_id, rank, ic, ic_t_stat, bh_p_adj, lasso_coef,
                   COALESCE(spearman_ic, ic) AS spearman_ic, pearson_corr, relevance_score, n_obs, selected_reason,
                   cusum_status, low_confidence, next_forced_recal, history_n_days,
                   last_calibrated_at, cusum_drift_score
            FROM stock_factor_relevance
            WHERE {' AND '.join(clauses)}
            ORDER BY horizon,
                     CASE WHEN rank IS NULL THEN 1 ELSE 0 END,
                     rank ASC,
                     ABS(relevance_score) DESC,
                     factor_canonical_id
            """
        ),
        params,
    ).mappings().all()
    return [
        {
            **dict(row),
            "last_calibrated_at": row["last_calibrated_at"].isoformat() if row["last_calibrated_at"] else "",
            "next_forced_recal": row["next_forced_recal"].isoformat() if row["next_forced_recal"] else None,
            "regime_start": None,
            "is_active": row["cusum_status"] == "valid",
        }
        for row in rows
    ]


@router.get("/stocks/{symbol}/stage1-cache", response_model=list[Stage1CacheOut])
def get_stage1_cache_for_stock(
    symbol: str,
    horizon: str | None = Query(None),
    db: Session = Depends(get_db),
) -> Any:
    clauses = ["symbol = :symbol"]
    params: dict[str, Any] = {"symbol": symbol.upper()}
    if horizon:
        params["horizon"] = normalize_selection_horizon(horizon)
        clauses.append("horizon = :horizon")
    rows = db.execute(
        text(
            f"""
            SELECT symbol, horizon, factor_canonical_id, ic_mean, ic_tstat, bh_p_adj, passed_fdr,
                   COALESCE(spearman_ic, ic_mean) AS spearman_ic, pearson_corr, relevance_score, n_obs, selected_reason,
                   regime_start, low_confidence, history_n_days, calculated_at
            FROM stock_factor_stage1_cache
            WHERE {' AND '.join(clauses)}
            ORDER BY horizon, relevance_score DESC NULLS LAST, ABS(ic_tstat) DESC, factor_canonical_id
            """
        ),
        params,
    ).mappings().all()
    return [
        {
            **dict(row),
            "regime_start": row["regime_start"].isoformat() if row["regime_start"] else None,
            "calculated_at": row["calculated_at"].isoformat() if row["calculated_at"] else "",
        }
        for row in rows
    ]


@router.post("/stocks/{symbol}/trigger-recalibration")
def trigger_factor_recalibration(
    symbol: str,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    symbol = symbol.upper()
    exists = db.execute(
        text("SELECT 1 FROM stock_master WHERE symbol = :symbol"),
        {"symbol": symbol},
    ).scalar()
    if not exists:
        raise HTTPException(status_code=404, detail=f"Stock {symbol} not found")

    from services.worker.tasks.factor_selection_full import run_factor_selection_for_symbol

    q = _get_macro_ingest_queue()
    job = q.enqueue(run_factor_selection_for_symbol, symbol, True)
    return {"status": "enqueued", "job_id": job.id, "symbol": symbol}


@router.post("/trigger-quarterly-recalibration-all")
def trigger_quarterly_recalibration_all() -> dict[str, str]:
    q = _get_macro_ingest_queue()
    job = q.enqueue("services.worker.tasks.factor_selection_quarterly.run_quarterly_factor_recalibration")
    return {"status": "enqueued", "job_id": job.id}
