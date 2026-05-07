"""API endpoints for Phase 2/3 Factor×TA signal configuration and results.

Routes:
    GET  /factor-signals/{symbol}/config                   — per-stock factor enable state
    PUT  /factor-signals/{symbol}/config                   — update per-stock factor enables
    GET  /factor-signals/{symbol}/{horizon}                — Factor×TA family results (engine + wfo)
    POST /factor-signals/{symbol}/{horizon}/run            — enqueue both engine AND wfo jobs
    POST /factor-signals/{symbol}/{horizon}/wfo/run        — enqueue wfo job only
    GET  /factor-signals/{symbol}/{horizon}/detail         — full detail for one family (click-to-expand)
    GET  /factor-signals/{symbol}/{horizon}/factor-state   — current macro factor values + condition outcomes
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from services.api.app.db import get_db
from services.api.app.models import SignalEngineFamilyResult, WfoSignalSummary
from core.quant_core.macro import MACRO_SERIES_BY_SYMBOL
from core.quant_core.research.factors.conditions import evaluate_condition
from core.quant_core.signal_engine.domain import FactorConditionMeta

router = APIRouter(prefix="/factor-signals", tags=["factor-signals"])

_FACTOR_TICKERS = ["^VIX", "^GSPC", "BZ=F", "DX-Y.NYB", "EURUSD=X", "^TNX"]

_FACTOR_LABELS = {
    "^VIX": "VIX — Risk appetite",
    "^GSPC": "S&P 500 — Global equity",
    "BZ=F": "Brent Crude — Oil/energy",
    "DX-Y.NYB": "DXY — USD strength",
    "EURUSD=X": "EUR/USD — MAD peg",
    "^TNX": "US 10Y — Global rates",
}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class FactorConfigItem(BaseModel):
    factor_ticker: str
    label: str
    enabled: bool


class FactorConfigResponse(BaseModel):
    stock_symbol: str
    factors: list[FactorConfigItem]


class FactorConfigUpdate(BaseModel):
    factors: list[FactorConfigItem]


class FamilyResultSummary(BaseModel):
    family: str
    category: str
    status: str
    family_score_pct: float | None
    representative_count: int | None
    is_provisional: bool | None
    representatives: list[dict[str, Any]]
    as_of: str | None


class PipelineResult(BaseModel):
    families: list[FamilyResultSummary]
    as_of: str | None


class FactorXTaSignalResponse(BaseModel):
    symbol: str
    horizon: str
    engine: PipelineResult
    wfo: PipelineResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_config_rows(db: Session, symbol: str) -> None:
    count = db.execute(
        text("SELECT COUNT(*) FROM stock_factor_config WHERE stock_symbol = :sym"),
        {"sym": symbol},
    ).scalar()
    if count == 0:
        db.execute(
            text(
                "INSERT INTO stock_factor_config (stock_symbol, factor_ticker, enabled) "
                "VALUES (:sym, :ticker, true) "
                "ON CONFLICT (stock_symbol, factor_ticker) DO NOTHING"
            ),
            [{"sym": symbol, "ticker": t} for t in _FACTOR_TICKERS],
        )
        db.commit()


def _get_config_rows(db: Session, symbol: str) -> dict[str, bool]:
    rows = db.execute(
        text("SELECT factor_ticker, enabled FROM stock_factor_config WHERE stock_symbol = :sym"),
        {"sym": symbol},
    ).fetchall()
    return {r[0]: bool(r[1]) for r in rows}


def _load_factor_prices(db: Session, canonical_id: str):
    """Return (close_array, last_date_str) or (None, None)."""
    try:
        from services.api.app.market_data_loader import load_ohlcv_for_symbol
        prices = load_ohlcv_for_symbol(db, canonical_id, timeframe="1D")
    except Exception:
        return None, None
    if prices is None or prices.empty:
        return None, None
    close_col = next((c for c in ["Close", "close", "Adj Close"] if c in prices.columns), None)
    if close_col is None:
        return None, None
    series = prices[close_col].dropna()
    arr = series.values.astype(np.float64)
    last_idx = series.index[-1]
    as_of = last_idx.strftime("%Y-%m-%d") if hasattr(last_idx, "strftime") else str(last_idx)
    return arr, as_of


def _compute_current_metric(condition: FactorConditionMeta, factor_close: np.ndarray) -> float | None:
    arr = factor_close
    n = len(arr)
    if n == 0:
        return None
    form = condition.form
    lookback = condition.lookback
    try:
        if form == "zscore":
            if n < lookback:
                return None
            seg = arr[max(0, n - lookback):]
            mu = float(np.nanmean(seg))
            sigma = float(np.nanstd(seg, ddof=1))
            if sigma == 0 or np.isnan(sigma):
                return None
            return float((arr[-1] - mu) / sigma)
        elif form == "momentum":
            if n <= lookback:
                return None
            base = float(arr[-1 - lookback])
            if base == 0 or np.isnan(base):
                return None
            return float((arr[-1] - base) / base)
        elif form == "change":
            if n <= lookback:
                return None
            return float(arr[-1] - arr[-1 - lookback])
        elif form == "level":
            return float(arr[-1])
        elif form == "direction":
            if n < 2:
                return None
            return float(arr[-1] - arr[-2])
    except Exception:
        return None
    return None


def _format_human_rule(condition: FactorConditionMeta) -> str:
    sym = "<" if condition.direction == "below" else ">"
    form = condition.form
    lookback = condition.lookback
    threshold = condition.threshold
    if form == "zscore":
        return f"z{lookback} {sym} {threshold}"
    elif form == "momentum":
        pct = threshold * 100
        return f"mom{lookback} {sym} {pct:.1f}%"
    elif form == "change":
        return f"change({lookback}) {sym} {threshold}"
    elif form == "level":
        return f"level {sym} {threshold}"
    elif form == "direction":
        return f"dir {sym} 0"
    return f"{form}({lookback}) {sym} {threshold}"


def _collect_factor_conditions_from_reps(reps_list: list[dict]) -> dict[str, dict[str, dict]]:
    """Walk representatives and collect unique conditions by factor_ticker → condition_id."""
    result: dict[str, dict[str, dict]] = {}
    for rep in reps_list:
        cond = rep.get("factor_condition")
        if not cond:
            continue
        ticker = cond.get("factor_ticker")
        cond_id = cond.get("condition_id")
        if ticker and cond_id:
            result.setdefault(ticker, {})[cond_id] = cond
    return result


def _build_factor_state(db: Session, factor_conditions: dict[str, dict[str, dict]]) -> list[dict]:
    """Compute current value + is_active for each used factor condition."""
    state_list = []
    for factor_ticker, conditions_by_id in factor_conditions.items():
        spec = MACRO_SERIES_BY_SYMBOL.get(factor_ticker)
        if spec is None:
            continue
        canonical_id = spec.canonical_id

        factor_close, as_of_str = _load_factor_prices(db, canonical_id)
        if factor_close is None or len(factor_close) == 0:
            continue

        conditions_out = []
        for cond_id, cond_dict in conditions_by_id.items():
            try:
                condition = FactorConditionMeta(
                    condition_id=cond_dict["condition_id"],
                    factor_ticker=cond_dict["factor_ticker"],
                    form=cond_dict["form"],
                    lookback=int(cond_dict["lookback"]),
                    threshold=float(cond_dict["threshold"]),
                    direction=cond_dict["direction"],
                )
                mask = evaluate_condition(condition, factor_close)
                is_active = bool(mask[-1]) if len(mask) > 0 else False
                current_metric = _compute_current_metric(condition, factor_close)
                human_rule = _format_human_rule(condition)
                conditions_out.append({
                    "condition_id": cond_id,
                    "form": condition.form,
                    "lookback": condition.lookback,
                    "threshold": condition.threshold,
                    "direction": condition.direction,
                    "current_metric_value": current_metric,
                    "is_active": is_active,
                    "human_rule": human_rule,
                })
            except Exception:
                pass

        state_list.append({
            "factor_ticker": factor_ticker,
            "canonical_id": canonical_id,
            "current_value": float(factor_close[-1]),
            "as_of": as_of_str,
            "conditions": conditions_out,
        })

    return state_list


# ---------------------------------------------------------------------------
# Routes — config
# ---------------------------------------------------------------------------

@router.get("/{symbol}/config", response_model=FactorConfigResponse)
def get_factor_config(symbol: str, db: Session = Depends(get_db)) -> FactorConfigResponse:
    _ensure_config_rows(db, symbol)
    config = _get_config_rows(db, symbol)
    items = [
        FactorConfigItem(
            factor_ticker=ticker,
            label=_FACTOR_LABELS.get(ticker, ticker),
            enabled=config.get(ticker, True),
        )
        for ticker in _FACTOR_TICKERS
    ]
    return FactorConfigResponse(stock_symbol=symbol, factors=items)


@router.put("/{symbol}/config", response_model=FactorConfigResponse)
def update_factor_config(
    symbol: str,
    body: FactorConfigUpdate,
    db: Session = Depends(get_db),
) -> FactorConfigResponse:
    for item in body.factors:
        db.execute(
            text(
                "INSERT INTO stock_factor_config (stock_symbol, factor_ticker, enabled, updated_at) "
                "VALUES (:sym, :ticker, :enabled, :now) "
                "ON CONFLICT (stock_symbol, factor_ticker) DO UPDATE SET "
                "enabled = EXCLUDED.enabled, updated_at = EXCLUDED.updated_at"
            ),
            {
                "sym": symbol,
                "ticker": item.factor_ticker,
                "enabled": item.enabled,
                "now": datetime.now(timezone.utc),
            },
        )
    db.commit()
    config = _get_config_rows(db, symbol)
    items = [
        FactorConfigItem(
            factor_ticker=ticker,
            label=_FACTOR_LABELS.get(ticker, ticker),
            enabled=config.get(ticker, True),
        )
        for ticker in _FACTOR_TICKERS
    ]
    return FactorConfigResponse(stock_symbol=symbol, factors=items)


# ---------------------------------------------------------------------------
# Routes — results (dual engine + wfo)
# ---------------------------------------------------------------------------

@router.get("/{symbol}/{horizon}", response_model=FactorXTaSignalResponse)
def get_factor_x_ta_signals(
    symbol: str,
    horizon: str,
    db: Session = Depends(get_db),
) -> FactorXTaSignalResponse:
    """Return Factor×TA results for both Signal Engine ×fx and WFO ×fx pipelines."""
    # --- Engine ×fx: read from signal_engine_family_result ---
    engine_rows = (
        db.query(SignalEngineFamilyResult)
        .filter_by(symbol=symbol, horizon=horizon, variant="factor_x_ta")
        .filter(SignalEngineFamilyResult.status.in_(["succeeded", "no_signal"]))
        .all()
    )
    engine_families = [
        FamilyResultSummary(
            family=row.family,
            category=row.category or "",
            status=row.status,
            family_score_pct=row.family_score_pct,
            representative_count=row.representative_count,
            is_provisional=row.is_provisional,
            representatives=row.representatives_json or [],
            as_of=row.data_as_of.isoformat() if row.data_as_of else None,
        )
        for row in engine_rows
    ]
    engine_as_of = (
        max((r.data_as_of.isoformat() for r in engine_rows if r.data_as_of), default=None)
    )

    # --- WFO ×fx: read from wfo_signal_summary ---
    wfo_rows = (
        db.query(WfoSignalSummary)
        .filter_by(symbol=symbol, horizon=horizon, variant="factor_x_ta")
        .filter(WfoSignalSummary.status.in_(["succeeded", "no_signal"]))
        .all()
    )
    wfo_families = [
        FamilyResultSummary(
            family=row.category,          # WFO is stored per-category, not per-family
            category=row.category or "",
            status=row.status,
            family_score_pct=row.score_pct,
            representative_count=len(row.representatives_json or []),
            is_provisional=None,
            representatives=row.representatives_json or [],
            as_of=row.data_as_of.isoformat() if row.data_as_of else None,
        )
        for row in wfo_rows
    ]
    wfo_as_of = (
        max((r.data_as_of.isoformat() for r in wfo_rows if r.data_as_of), default=None)
    )

    return FactorXTaSignalResponse(
        symbol=symbol,
        horizon=horizon,
        engine=PipelineResult(families=engine_families, as_of=engine_as_of),
        wfo=PipelineResult(families=wfo_families, as_of=wfo_as_of),
    )


# ---------------------------------------------------------------------------
# Routes — detail + factor state
# ---------------------------------------------------------------------------

@router.get("/{symbol}/{horizon}/detail")
def get_factor_x_ta_detail(
    symbol: str,
    horizon: str,
    family: str = Query(..., description="Family name, e.g. 'sma@fx' or category 'tendance'"),
    variant: str = Query("engine", description="'engine' or 'wfo'"),
    db: Session = Depends(get_db),
) -> dict:
    """Return full detail for one Factor×TA family (click-to-expand)."""
    if variant == "engine":
        family_fx = family if family.endswith("@fx") else f"{family}@fx"
        row = (
            db.query(SignalEngineFamilyResult)
            .filter_by(symbol=symbol, horizon=horizon, variant="factor_x_ta")
            .filter(SignalEngineFamilyResult.family.in_([family, family_fx]))
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail=f"No Factor×TA engine result for family={family!r}")
        detail = row.family_detail_json or {}
        return {
            "family": row.family,
            "category": row.category or "",
            "status": row.status,
            "family_score_pct": row.family_score_pct,
            "viable_count": row.viable_count,
            "tested_count": row.tested_count,
            "competitive_count": row.competitive_count,
            "representative_count": row.representative_count,
            "is_provisional": row.is_provisional,
            "methodology_mode": detail.get("methodology_mode"),
            "warning_message": row.warning_message,
            "representatives": row.representatives_json or [],
            "family_detail": detail,
            "as_of": row.data_as_of.isoformat() if row.data_as_of else None,
        }

    elif variant == "wfo":
        row = (
            db.query(WfoSignalSummary)
            .filter_by(symbol=symbol, horizon=horizon, variant="factor_x_ta", category=family)
            .first()
        )
        if row is None:
            raise HTTPException(status_code=404, detail=f"No Factor×TA WFO result for category={family!r}")
        return {
            "family": row.category,
            "category": row.category or "",
            "status": row.status,
            "family_score_pct": row.score_pct,
            "viable_count": None,
            "tested_count": None,
            "competitive_count": None,
            "representative_count": len(row.representatives_json or []),
            "is_provisional": None,
            "methodology_mode": "wfo",
            "wfe_pct": row.wfe_pct,
            "robustness_ratio": row.robustness_ratio,
            "robustness_grade": row.robustness_grade,
            "total_folds": row.total_folds,
            "profitable_folds": row.profitable_folds,
            "warning_message": None,
            "representatives": row.representatives_json or [],
            "family_detail": row.config_json or {},
            "as_of": row.data_as_of.isoformat() if row.data_as_of else None,
        }

    raise HTTPException(status_code=400, detail=f"Unknown variant {variant!r}. Use 'engine' or 'wfo'.")


@router.get("/{symbol}/{horizon}/factor-state")
def get_factor_x_ta_factor_state(
    symbol: str,
    horizon: str,
    variant: str = Query("engine", description="'engine' or 'wfo'"),
    db: Session = Depends(get_db),
) -> list:
    """Return current value + condition outcome for every macro factor used by survivors."""
    if variant == "engine":
        rows = (
            db.query(SignalEngineFamilyResult)
            .filter_by(symbol=symbol, horizon=horizon, variant="factor_x_ta")
            .filter(SignalEngineFamilyResult.status == "succeeded")
            .all()
        )
        all_reps = [rep for row in rows for rep in (row.representatives_json or [])]

    elif variant == "wfo":
        rows = (
            db.query(WfoSignalSummary)
            .filter_by(symbol=symbol, horizon=horizon, variant="factor_x_ta")
            .filter(WfoSignalSummary.status == "succeeded")
            .all()
        )
        all_reps = [rep for row in rows for rep in (row.representatives_json or [])]

    else:
        raise HTTPException(status_code=400, detail=f"Unknown variant {variant!r}. Use 'engine' or 'wfo'.")

    factor_conditions = _collect_factor_conditions_from_reps(all_reps)
    if not factor_conditions:
        return []

    return _build_factor_state(db, factor_conditions)


# ---------------------------------------------------------------------------
# Routes — enqueue
# ---------------------------------------------------------------------------

@router.post("/{symbol}/{horizon}/run")
def enqueue_factor_x_ta_run(
    symbol: str,
    horizon: str,
    db: Session = Depends(get_db),
) -> dict:
    """Enqueue Factor Selection followed by Signal Engine ×fx AND WFO ×fx jobs in parallel."""
    try:
        from services.api.app.queue import _get_macro_ingest_queue
        from services.worker.tasks.factor_selection_full import run_factor_selection_for_symbol
        from services.worker.tasks.factor_x_ta_batch import enqueue_factor_x_ta_for_symbol
        from services.worker.tasks.wfo_factor_x_ta_batch import enqueue_wfo_factor_x_ta_for_symbol

        # 1. Enqueue the econometric factor selection pipeline
        q = _get_macro_ingest_queue()
        fs_job = q.enqueue(
            run_factor_selection_for_symbol,
            symbol,
            False,
            job_timeout=3600
        )

        # 2. Enqueue the factor_x_ta jobs dependent on the factor selection job
        engine_job_id = enqueue_factor_x_ta_for_symbol(symbol, horizon, triggered_by="api", depends_on=fs_job.id)
        wfo_job_id = enqueue_wfo_factor_x_ta_for_symbol(symbol, horizon, triggered_by="api", depends_on=fs_job.id)
        
        return {
            "symbol": symbol,
            "horizon": horizon,
            "factor_selection_job_id": fs_job.id,
            "engine_job_id": engine_job_id,
            "wfo_job_id": wfo_job_id,
            "status": "enqueued",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/{symbol}/{horizon}/wfo/run")
def enqueue_wfo_factor_x_ta_run(
    symbol: str,
    horizon: str,
    db: Session = Depends(get_db),
) -> dict:
    """Enqueue Factor Selection followed by the WFO ×fx job."""
    try:
        from services.api.app.queue import _get_macro_ingest_queue
        from services.worker.tasks.factor_selection_full import run_factor_selection_for_symbol
        from services.worker.tasks.wfo_factor_x_ta_batch import enqueue_wfo_factor_x_ta_for_symbol

        # 1. Enqueue the econometric factor selection pipeline
        q = _get_macro_ingest_queue()
        fs_job = q.enqueue(
            run_factor_selection_for_symbol,
            symbol,
            False,
            job_timeout=3600
        )

        # 2. Enqueue the wfo job dependent on the factor selection job
        job_id = enqueue_wfo_factor_x_ta_for_symbol(symbol, horizon, triggered_by="api", depends_on=fs_job.id)
        
        return {
            "job_id": job_id, 
            "factor_selection_job_id": fs_job.id,
            "symbol": symbol, 
            "horizon": horizon, 
            "status": "enqueued"
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
