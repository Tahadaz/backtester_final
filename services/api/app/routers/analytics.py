"""Analytics router — signal evaluation and factor relevance.

Endpoints:
  GET  /analytics/signals              — overview table (all symbols × categories × horizons)
  GET  /analytics/stocks/{symbol}      — per-stock summary
  GET  /analytics/stocks/{symbol}/evaluate/{category}/{horizon}  — full report (on-demand)
  GET  /analytics/factors/{symbol}     — factor-relevance matrix
  POST /analytics/macro/ingest         — enqueue macro series ingestion
  GET  /analytics/macro/catalog        — list ingested macro series with freshness
"""
from __future__ import annotations

import math
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Any, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import rate_limit_trigger, require_admin
from ..db import get_db
from .. import models
from ..market_data_loader import load_ohlcv_for_symbol
from ..schemas.analytics import (
    SignalEvaluationReportOut,
    SignalOverviewRow,
    ICCurveOut,
    PortfolioStatsOut,
    RobustnessOut,
    MacroIngestRequestOut,
    FactorRelevanceRow,
    FactorRelevanceMatrixOut,
    AllFactorRelevanceOut,
    FactorLeaderboardRow,
    PredictiveAbilityCell,
    PredictiveAbilityMatrix,
    CategoryCombinationRow,
    CategoryCombinationsOut,
    PredictiveHistoryStatus,
    PredictiveHistoryTriggerOut,
    StatArbTriggerOut,
    StatArbStatusOut,
    StatArbPairRow,
    StatArbLeaderboardOut,
    StatArbPairDetailOut,
    LeaderboardRow,
    LeaderboardOut,
    MethodEvaluationRow,
    MethodEvaluationOut,
    EdgeMetricsOut,
    EdgeGatesOut,
    ExpectancyDecompOut,
)
from core.quant_core.research.evaluate import evaluate_signal
from core.quant_core.macro import MACRO_SERIES,MACRO_SERIES_BY_ID
from core.quant_core.signal_engine.oos_eval import compute_signal_array
from core.quant_core.signal_engine.domain import VariantDef
from core.quant_core.research.factors.relevance import compute_pair_relevance
from core.quant_core.research.alignment import align_factor_to_target
from core.quant_core.research.evaluate import evaluate_signal
from core.quant_core.research.stats.fdr import benjamini_hochberg
from core.quant_core.research.factors.signals import (
    REGISTERED_FACTOR_SIGNALS,
    compute_factor_signal,
    is_applicable,
    )
from core.quant_core.research.score_history import (
        BUCKET_NAMES, aggregate_subset, bucketed_forward_returns,_bucket_for, ic_table, _calculate_forward_returns, _strip_tz,
    )
from core.quant_core.horizons import LEGACY_HORIZON_ALIASES, canonical_horizon
from core.quant_core.signal_engine.modes import SIGNAL_MODE_ALIASES, SIGNAL_MODES, resolve_signal_mode, signal_mode_read_names

router = APIRouter(prefix="/analytics", tags=["analytics"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _report_to_out(report) -> SignalEvaluationReportOut:
    """Convert a SignalEvaluationReport domain object to the Pydantic schema."""
    def _safe(v: float) -> float:
        return 0.0 if (v is None or (isinstance(v, float) and math.isnan(v))) else v

    return SignalEvaluationReportOut(
        signal_id=report.signal_id,
        symbol=report.symbol,
        n_obs=report.n_obs,
        horizons=report.horizons,
        ic_curve=ICCurveOut(
            horizons=report.ic_curve.horizons,
            ic_values=[_safe(v) for v in report.ic_curve.ic_values],
            ic_se=[_safe(v) for v in report.ic_curve.ic_se],
            ic_ci_lower=[_safe(v) for v in report.ic_curve.ic_ci_lower],
            ic_ci_upper=[_safe(v) for v in report.ic_curve.ic_ci_upper],
            n_obs=report.ic_curve.n_obs,
        ),
        hit_rate_h1=_safe(report.hit_rate_h1),
        hit_rate_ci=[_safe(report.hit_rate_ci_lower), _safe(report.hit_rate_ci_upper)],
        conditional_return_tstat=_safe(report.conditional_return_tstat),
        portfolio=PortfolioStatsOut(
            sharpe=_safe(report.portfolio.sharpe),
            sortino=_safe(report.portfolio.sortino),
            max_drawdown=_safe(report.portfolio.max_drawdown),
            calmar=_safe(report.portfolio.calmar),
            turnover=_safe(report.portfolio.turnover),
            hit_rate=_safe(report.portfolio.hit_rate),
            profit_factor=_safe(report.portfolio.profit_factor),
            avg_win=_safe(report.portfolio.avg_win),
            avg_loss=_safe(report.portfolio.avg_loss),
            after_cost_sharpe=_safe(report.portfolio.after_cost_sharpe),
            n_trades=report.portfolio.n_trades,
            total_return=_safe(report.portfolio.total_return),
        ),
        robustness=RobustnessOut(
            dsr=_safe(report.robustness.dsr),
            psr=_safe(report.robustness.psr),
            sharpe_bootstrap_ci=[_safe(report.robustness.sharpe_bootstrap_ci_lower), _safe(report.robustness.sharpe_bootstrap_ci_upper)],
            ic_bootstrap_ci=[_safe(report.robustness.ic_bootstrap_ci_lower), _safe(report.robustness.ic_bootstrap_ci_upper)],
            ic_cv=_safe(report.robustness.ic_cv),
            sharpe_cv=_safe(report.robustness.sharpe_cv),
            n_variants=report.robustness.n_variants,
        ),
    )


def _compute_signal_series(
    summary: models.WfoSignalSummary,
    prices: pd.DataFrame,
) -> pd.Series | None:
    """Reconstruct the full historical signal series for a WFO summary.

    Uses the first representative variant from the summary's best variant config.
    Returns None if signal cannot be computed (missing dispatcher, bad config).
    """
    

    reps = summary.representatives_json or []
    if not reps:
        return None

    best_rep = reps[0]
    variant_id = best_rep.get("variant_id", "")
    family = best_rep.get("family", "")
    archetype = best_rep.get("archetype", "")
    params = best_rep.get("params", {})

    if not (family and archetype):
        return None

    try:
        variant = VariantDef(
            variant_id=variant_id,
            family=family,
            archetype=archetype,
            params=params,
        )
        close = prices["Close"].values
        high = prices.get("High", pd.Series(dtype=float)).values if "High" in prices.columns else None
        low = prices.get("Low", pd.Series(dtype=float)).values if "Low" in prices.columns else None
        volume = prices.get("Volume", pd.Series(dtype=float)).values if "Volume" in prices.columns else None

        sig_arr = compute_signal_array(close, variant, volume=volume, high=high, low=low)
        return pd.Series(sig_arr, index=prices.index, name=variant_id)
    except Exception:
        return None


def _safe_float(v) -> float:
    if v is None:
        return float("nan")
    try:
        f = float(v)
        return f if not math.isnan(f) and not math.isinf(f) else float("nan")
    except Exception:
        return float("nan")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/signals", response_model=list[SignalOverviewRow])
def get_signals_overview(
    symbol: Optional[str] = Query(None, description="Filter by stock symbol"),
    horizon: Optional[str] = Query(None, description="Filter by horizon (short|medium|long)"),
    db: Session = Depends(get_db),
):
    """Overview table: IC/DSR/Sharpe summary for all signals × stocks × horizons.

    Light endpoint — returns pre-computed WFO metrics without re-running evaluate_signal.
    For full statistical reports, use the per-symbol /evaluate endpoint.
    """
    query = db.query(models.WfoSignalSummary).filter(
        models.WfoSignalSummary.status == "succeeded"
    )
    if symbol:
        query = query.filter(models.WfoSignalSummary.symbol == symbol.upper())
    if horizon:
        query = query.filter(models.WfoSignalSummary.horizon == horizon)

    rows = query.order_by(
        models.WfoSignalSummary.symbol,
        models.WfoSignalSummary.category,
        models.WfoSignalSummary.horizon,
    ).limit(1000).all()

    # Deduplicate: multiple variants (legacy/expanded) share the same signal_id.
    # Keep the row with the highest mean_oos_sharpe per (symbol, category, horizon).
    best: dict[tuple, Any] = {}
    for r in rows:
        key = (r.symbol, r.category, r.horizon)
        existing = best.get(key)
        if existing is None or (r.mean_oos_sharpe or 0) > (existing.mean_oos_sharpe or 0):
            best[key] = r

    # Fetch signal engine global results to enrich with engine_score_pct / engine_label.
    # SignalEngineGlobalResult.per_category_json: {category: {score_pct, label, ...}}
    symbols_in_result = list({k[0] for k in best})
    horizons_in_result = list({k[2] for k in best})
    engine_lookup: dict[tuple, dict] = {}
    if symbols_in_result and horizons_in_result:
        engine_rows = (
            db.query(models.SignalEngineGlobalResult)
            .filter(
                models.SignalEngineGlobalResult.symbol.in_(symbols_in_result),
                models.SignalEngineGlobalResult.horizon.in_(horizons_in_result),
                models.SignalEngineGlobalResult.status == "succeeded",
            )
            .all()
        )
        for er in engine_rows:
            key = (er.symbol, er.horizon)
            # Keep the most recent / highest-score variant per (symbol, horizon)
            existing = engine_lookup.get(key)
            new_score = er.aggregate_score_pct or 0
            old_score = (existing or {}).get("_score", -1)
            if existing is None or new_score > old_score:
                per_cat = er.per_category_json or {}
                engine_lookup[key] = {**per_cat, "_score": new_score}

    result = []
    for r in sorted(best.values(), key=lambda x: (x.symbol, x.category, x.horizon)):
        signal_id = f"{r.symbol}:{r.category}:{r.horizon}"
        cat_data = engine_lookup.get((r.symbol, r.horizon), {}).get(r.category, {})
        result.append(SignalOverviewRow(
            symbol=r.symbol,
            category=r.category,
            horizon=r.horizon,
            signal_id=signal_id,
            sharpe=_safe_float(r.mean_oos_sharpe),
            n_obs=0,
            fdr_pass=False,
            engine_score_pct=cat_data.get("score_pct") if cat_data else None,
            engine_label=cat_data.get("label") if cat_data else None,
        ))

    return result


@router.get("/stocks/{symbol}", response_model=list[SignalOverviewRow])
def get_stock_analytics(
    symbol: str,
    db: Session = Depends(get_db),
):
    """Per-stock summary: all families × horizons for this symbol."""
    return get_signals_overview(symbol=symbol.upper(), horizon=None, db=db)


@router.get("/stocks/{symbol}/evaluate/{category}/{horizon}", response_model=SignalEvaluationReportOut)
def evaluate_stock_signal(
    symbol: str,
    category: str,
    horizon: str,
    variant: str = Query(default="expanded"),
    n_variants: int = Query(default=1, ge=1, le=500),
    spread_bps: float = Query(default=15.0),
    commission_bps: float = Query(default=10.0),
    db: Session = Depends(get_db),
):
    """Compute full SignalEvaluationReport for one (symbol, category, horizon) on demand.

    Reconstructs the signal series from the WFO summary's best representative,
    applies it to the full price history, and runs the complete statistical battery.

    Production note: this is computationally intensive (~1-3s per call).
    Results should be cached; this endpoint is the cache-miss path.
    """
    

    symbol_upper = symbol.upper()

    # Load WFO summary
    summary = db.query(models.WfoSignalSummary).filter(
        models.WfoSignalSummary.symbol == symbol_upper,
        models.WfoSignalSummary.category == category,
        models.WfoSignalSummary.horizon == horizon,
        models.WfoSignalSummary.variant == variant,
        models.WfoSignalSummary.status == "succeeded",
    ).first()

    if summary is None:
        raise HTTPException(
            status_code=404,
            detail=f"No succeeded WFO summary for {symbol_upper!r} category={category!r} horizon={horizon!r}",
        )

    # Load prices
    try:
        prices = load_ohlcv_for_symbol(db, symbol_upper)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    prices = prices.sort_index()
    close_series = prices["Close"].dropna()

    # Reconstruct signal series
    signal_series = _compute_signal_series(summary, prices)
    if signal_series is None:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot reconstruct signal series for {symbol_upper!r} — check representative config",
        )

    signal_id = f"{symbol_upper}:{category}:{horizon}"
    report = evaluate_signal(
        signal=signal_series,
        prices=close_series,
        signal_id=signal_id,
        symbol=symbol_upper,
        n_variants=n_variants,
        costs={"spread_bps": spread_bps, "commission_bps": commission_bps},
        bootstrap_samples=300,
    )

    return _report_to_out(report)


@router.get("/macro/catalog")
def get_macro_catalog(db: Session = Depends(get_db)):
    """List ingested macro series with freshness."""

    canonical_ids = [s.canonical_id for s in MACRO_SERIES]
    from sqlalchemy import text
    rows = db.execute(
        text("""
            SELECT symbol, data_as_of, row_count, end_ts, start_ts
            FROM market_data_store
            WHERE asset_class = 'factor'
              AND timeframe = '1D'
            ORDER BY symbol
        """)
    ).mappings().all()

    stored = {r["symbol"]: r for r in rows}

    result = []
    for spec in MACRO_SERIES:
        row = stored.get(spec.canonical_id, {})
        result.append({
            "canonical_id": spec.canonical_id,
            "yahoo_symbol": spec.symbol,
            "description": spec.description,
            "channel_tags": spec.channel_tags,
            "data_as_of": str(row.get("data_as_of", "")) if row.get("data_as_of") else None,
            "row_count": row.get("row_count"),
            "has_data": bool(row),
        })

    return result


@router.post("/macro/ingest/{canonical_id}", response_model=MacroIngestRequestOut)
def enqueue_macro_ingest(
    canonical_id: str,
    start: str = Query(default="2010-01-01"),
    end: Optional[str] = Query(default=None),
):
    """Enqueue a macro series ingestion job via RQ."""
    from ..queue import get_queue

    if canonical_id not in MACRO_SERIES_BY_ID:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown macro series: {canonical_id!r}. Known: {list(MACRO_SERIES_BY_ID.keys())}",
        )

    q = get_queue()
    job = q.enqueue(
        "services.worker.tasks.ingest_macro_series.ingest_macro_series",
        canonical_id,
        start,
        end,
        job_timeout=300,
    )

    return MacroIngestRequestOut(
        canonical_id=canonical_id,
        job_id=job.id,
        status="enqueued",
    )


@router.post("/macro/ingest-all")
def enqueue_all_macro_ingest(
    start: str = Query(default="2010-01-01"),
):
    """Enqueue ingestion jobs for all six macro series."""
    from ..queue import get_queue

    q = get_queue()
    jobs = []
    for spec in MACRO_SERIES:
        job = q.enqueue(
            "services.worker.tasks.ingest_macro_series.ingest_macro_series",
            spec.canonical_id,
            start,
            None,
            job_timeout=300,
        )
        jobs.append({"canonical_id": spec.canonical_id, "job_id": job.id})

    return {"enqueued": jobs}


# ---------------------------------------------------------------------------
# Factor relevance endpoints
# ---------------------------------------------------------------------------

def _load_factor_series(db: Session, canonical_id: str) -> Optional[pd.Series]:
    """Load a macro factor's close price series from the parquet store."""
    try:
        prices = load_ohlcv_for_symbol(db, canonical_id, timeframe="1D")
    except (ValueError, Exception):
        return None
    if prices is None or prices.empty:
        return None
    close_col = next((c for c in ["Close", "close", "Adj Close"] if c in prices.columns), None)
    if close_col is None:
        return None
    series = prices[close_col].dropna()
    return series if not series.empty else None


def _channel_tags_for(canonical_id: str, sector: Optional[str]) -> bool:
    """Check if a factor has a channel-tag match to this sector (qualitative only)."""
    spec = MACRO_SERIES_BY_ID.get(canonical_id)
    if spec is None:
        return False
    if "all" in spec.channel_tags:
        return True
    if sector and sector.lower() in spec.channel_tags:
        return True
    return False


def _get_ohlcv_cols(stock_prices: pd.DataFrame) -> tuple[Optional[str], Optional[str]]:
    """Return (close_col, open_col) from OHLCV dataframe."""
    close_col = next((c for c in ["Close", "close", "Adj Close"] if c in stock_prices.columns), None)
    open_col = next((c for c in ["Open", "open"] if c in stock_prices.columns), None)
    return close_col, open_col


def _compute_target_returns(
    stock_prices: pd.DataFrame,
    return_method: str,
    close_col: str,
    open_col: Optional[str],
) -> Optional[pd.Series]:
    """Pre-compute stock forward returns for the given return_method.

    Returns a pd.Series aligned to the stock price index, or None for
    close_to_close (handled internally by compute_pair_relevance default).

    close_to_close  : close[t+1]/close[t] - 1  (1-day, shift -1)
    close_to_open   : open[t+1]/close[t] - 1   (overnight gap)
    open_to_open    : open[t+2]/open[t+1] - 1  (entry t+1, exit t+2)
    open_to_close   : close[t+1]/open[t+1] - 1 (intraday t+1, no shift)
    """
    close = stock_prices[close_col].dropna()
    if return_method == "close_to_close":
        return close.pct_change(fill_method=None).shift(-1)
    if open_col is None:
        return close.pct_change(fill_method=None).shift(-1)
    open_ = stock_prices[open_col].dropna()
    if return_method == "close_to_open":
        return (open_.shift(-1) - close) / close
    if return_method == "open_to_open":
        # entry open[t+1], exit open[t+2]
        return open_.pct_change(fill_method=None).shift(-2)
    if return_method == "open_to_close":
        # entry open[t+1], exit close[t+1] — intraday
        return (close.shift(-1) - open_.shift(-1)) / open_.shift(-1)
    # fallback
    return close.pct_change(fill_method=None).shift(-1)


def _compute_cutoff(reference_index: pd.Index, lookback_days: int) -> Optional[pd.Timestamp]:
    """Return a tz-aligned cutoff timestamp matching reference_index, or None if lookback_days <= 0.

    Why: comparing a tz-naive Timestamp against a tz-aware DatetimeIndex raises
    TypeError. Caller should pass the index it intends to filter on.
    """
    if lookback_days <= 0:
        return None
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=lookback_days)
    tz = getattr(reference_index, "tz", None)
    if tz is None:
        return cutoff.tz_localize(None)
    return cutoff.tz_convert(tz)


def _json_float(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if np.isfinite(parsed) else None


def _series_json_values(series: pd.Series, index: pd.Index) -> list[Optional[float]]:
    aligned = series.reindex(index)
    return [_json_float(value) for value in aligned.tolist()]


def _iso_index_value(value: Any) -> str:
    try:
        return pd.Timestamp(value).date().isoformat()
    except Exception:
        return str(value)[:10]


def _next_index_dates(index: pd.Index) -> pd.Series:
    values = list(index)
    shifted = values[1:] + values[-1:] if values else []
    return pd.Series(shifted, index=index)


def _macro_execution_price_series(
    stock_prices: pd.DataFrame,
    *,
    return_method: str,
    close_col: str,
    open_col: Optional[str],
) -> tuple[pd.Series, pd.Series]:
    close = stock_prices[close_col].dropna()
    if return_method in {"open_to_open", "open_to_close"} and open_col is not None:
        execution = stock_prices[open_col].dropna().shift(-1)
        execution_dates = _next_index_dates(stock_prices.index)
        return execution, execution_dates
    return close, pd.Series(stock_prices.index, index=stock_prices.index)


def _build_macro_backtest_replay(
    *,
    stock_prices: pd.DataFrame,
    close_col: str,
    open_col: Optional[str],
    stock_close: pd.Series,
    aligned_factors: dict[str, pd.Series],
    signal: pd.Series,
    spec: Any,
    forward_returns: Optional[pd.Series],
    return_method: str,
    cost_bps: float,
    signal_threshold: float = 0.0,
) -> dict[str, Any] | None:
    primary_factor = aligned_factors.get(spec.factor_id)
    if primary_factor is None:
        return None

    fwd = forward_returns if forward_returns is not None else stock_close.pct_change(fill_method=None).shift(-1)
    frame = pd.concat(
        {
            "signal": signal,
            "stock_close": stock_close,
            "forward_return": fwd,
            "factor_close": primary_factor,
            "factor_return": primary_factor.pct_change(fill_method=None),
        },
        axis=1,
    )
    for factor_id in spec.requires:
        factor_series = aligned_factors.get(factor_id)
        if factor_series is not None:
            frame[f"factor_{factor_id}"] = factor_series

    frame = frame.dropna(subset=["signal", "stock_close"]).copy()
    if len(frame) < 2:
        return None
    frame["forward_return"] = frame["forward_return"].fillna(0.0)

    position = pd.Series(0.0, index=frame.index, dtype=float)
    position[frame["signal"] > signal_threshold] = 1.0
    position[frame["signal"] < -signal_threshold] = -1.0

    position_change = position.diff().fillna(position).abs()
    cost_rate = float(cost_bps) / 10_000.0
    strategy_returns = (position * frame["forward_return"]).astype(float) - position_change * cost_rate
    strategy_returns = strategy_returns.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    equity = (1.0 + strategy_returns).cumprod()
    peak = equity.cummax().replace(0.0, np.nan)
    drawdown = (equity - peak) / peak
    drawdown = drawdown.replace([np.inf, -np.inf], np.nan).fillna(0.0)

    execution_price, execution_dates = _macro_execution_price_series(
        stock_prices,
        return_method=return_method,
        close_col=close_col,
        open_col=open_col,
    )
    execution_price = execution_price.reindex(frame.index)
    execution_dates = execution_dates.reindex(frame.index)

    ledger: list[dict[str, Any]] = []
    previous_position = 0.0
    for date_value in frame.index:
        current_position = float(position.loc[date_value])
        if abs(current_position - previous_position) < 1e-12:
            continue
        quantity_delta = current_position - previous_position
        side = "ACHAT" if quantity_delta > 0 else "VENTE"
        equity_value = _json_float(equity.loc[date_value])
        ledger.append(
            {
                "date": _iso_index_value(date_value),
                "execution_date": _iso_index_value(execution_dates.loc[date_value]),
                "side": side,
                "position": _json_float(current_position),
                "previous_position": _json_float(previous_position),
                "quantity_delta": _json_float(quantity_delta),
                "signal_value": _json_float(frame.at[date_value, "signal"]),
                "factor_id": spec.factor_id,
                "factor_value": _json_float(frame.at[date_value, "factor_close"]),
                "factor_return": _json_float(frame.at[date_value, "factor_return"]),
                "prix_execution": _json_float(execution_price.loc[date_value]),
                "stock_close": _json_float(frame.at[date_value, "stock_close"]),
                "strategy_return": _json_float(strategy_returns.loc[date_value]),
                "return_cumule": None if equity_value is None else equity_value - 1.0,
                "equity": equity_value,
                "cout": _json_float(abs(quantity_delta) * cost_rate),
            }
        )
        previous_position = current_position

    return {
        "factor_id": spec.factor_id,
        "signal_name": spec.signal_name,
        "return_method": return_method,
        "cost_bps": float(cost_bps),
        "dates": [_iso_index_value(value) for value in frame.index],
        "stock_close": _series_json_values(frame["stock_close"], frame.index),
        "factor_close": _series_json_values(frame["factor_close"], frame.index),
        "factor_return": _series_json_values(frame["factor_return"], frame.index),
        "factor_close_by_id": {
            factor_id: _series_json_values(frame[f"factor_{factor_id}"], frame.index)
            for factor_id in spec.requires
            if f"factor_{factor_id}" in frame.columns
        },
        "signal": _series_json_values(frame["signal"], frame.index),
        "position": _series_json_values(position, frame.index),
        "strategy_returns": _series_json_values(strategy_returns, frame.index),
        "equity": _series_json_values(equity, frame.index),
        "drawdown": _series_json_values(drawdown, frame.index),
        "trade_ledger": ledger,
    }


@router.get("/factors/leaderboard", response_model=list[FactorLeaderboardRow])
def get_factor_leaderboard(
    lookback_days: int = Query(default=0, ge=0),
    forward_horizon: int = Query(default=1, ge=1, le=21),
    return_method: str = Query(default="close_to_close"),
    db: Session = Depends(get_db),
):
    """Cross-stock leaderboard: rank stocks by macro-factor statistical significance.

    For each tracked symbol computes Spearman IC vs all active macro factors and
    returns one row per stock sorted by n_significant DESC, max_t_stat DESC.
    """
    cache_key = f"{lookback_days}:{forward_horizon}:{return_method}"
    hit = _FACTOR_LEADERBOARD_CACHE.get(cache_key)
    now = time.monotonic()
    if hit is not None and now - hit[0] < _FACTOR_LEADERBOARD_TTL_S:
        return hit[1]

    symbols = [
        row[0] for row in
        db.query(models.WfoSignalSummary.symbol).distinct().limit(200).all()
    ]

    # cutoff is computed per-symbol inside the loop (each symbol's index may differ in tz)

    # Load each factor series once for all symbols (avoids ~73× redundant DB reads).
    factor_cache: dict[str, pd.Series | None] = {
        spec.canonical_id: _load_factor_series(db, spec.canonical_id)
        for spec in MACRO_SERIES
    }

    rows: list[FactorLeaderboardRow] = []
    for sym in symbols:
        try:
            stock_prices = load_ohlcv_for_symbol(db, sym)
        except Exception:
            continue
        close_col, open_col = _get_ohlcv_cols(stock_prices)
        if close_col is None:
            continue

        stock_close = stock_prices[close_col].dropna()
        cutoff = _compute_cutoff(stock_close.index, lookback_days)
        if cutoff is not None:
            stock_close = stock_close[stock_close.index >= cutoff]
        if len(stock_close) < 30:
            continue

        target_returns = _compute_target_returns(stock_prices, return_method, close_col, open_col)
        if cutoff is not None and target_returns is not None:
            target_returns = target_returns[target_returns.index >= cutoff]

        best_factor = ""
        max_t_stat = 0.0
        max_ic = 0.0
        n_sig = 0
        n_obs_total = 0

        for spec in MACRO_SERIES:
            factor_series = factor_cache.get(spec.canonical_id)
            if factor_series is None:
                continue
            pair = compute_pair_relevance(
                factor_id=spec.canonical_id,
                symbol=sym,
                factor=factor_series,
                stock_prices=stock_close,
                forward_horizon=forward_horizon,
                target_returns=target_returns,
            )
            if pair is None:
                continue
            n_obs_total = max(n_obs_total, pair.n_obs)
            if pair.significant:
                n_sig += 1
            if abs(pair.t_stat) > abs(max_t_stat):
                max_t_stat = pair.t_stat
                max_ic = pair.ic
                best_factor = pair.factor_id

        if n_obs_total < 30:
            continue
        rows.append(FactorLeaderboardRow(
            symbol=sym,
            n_significant=n_sig,
            best_factor=best_factor or "—",
            max_t_stat=round(max_t_stat, 4),
            max_ic=round(max_ic, 6),
            n_obs=n_obs_total,
        ))

    rows.sort(key=lambda r: (-r.n_significant, -abs(r.max_t_stat)))
    _FACTOR_LEADERBOARD_CACHE[cache_key] = (time.monotonic(), rows)
    return rows


@router.get("/factors/{symbol}", response_model=FactorRelevanceMatrixOut)
def get_factor_relevance_for_stock(
    symbol: str,
    lag_rule: str = Query(default="precede_open"),
    forward_horizon: int = Query(default=1, ge=1, le=21),
    return_method: str = Query(default="close_to_close"),
    lookback_days: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Compute factor-relevance matrix for one stock vs all active macro factors.

    Spearman rank IC + Newey-West t-stat for each (factor, stock) pair.
    Factor series are loaded from market_data_store (asset_class='factor').

    return_method: close_to_close | close_to_open | open_to_open | open_to_close
    """
    import datetime

    symbol_upper = symbol.upper()

    try:
        stock_prices = load_ohlcv_for_symbol(db, symbol_upper)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    close_col, open_col = _get_ohlcv_cols(stock_prices)
    if close_col is None:
        raise HTTPException(status_code=422, detail=f"No close column for {symbol_upper!r}")

    stock_close = stock_prices[close_col].dropna()

    cutoff = _compute_cutoff(stock_close.index, lookback_days)
    if cutoff is not None:
        stock_close = stock_close[stock_close.index >= cutoff]

    target_returns = _compute_target_returns(stock_prices, return_method, close_col, open_col)
    if cutoff is not None and target_returns is not None:
        target_returns = target_returns[target_returns.index >= cutoff]

    pairs_out: list[FactorRelevanceRow] = []
    as_of = datetime.date.today().isoformat()

    for spec in MACRO_SERIES:
        factor_series = _load_factor_series(db, spec.canonical_id)
        if factor_series is None:
            continue

        result = compute_pair_relevance(
            factor_id=spec.canonical_id,
            symbol=symbol_upper,
            factor=factor_series,
            stock_prices=stock_close,
            lag_rule=lag_rule,
            forward_horizon=forward_horizon,
            target_returns=target_returns,
        )
        if result is None:
            continue

        pairs_out.append(FactorRelevanceRow(
            factor_id=result.factor_id,
            symbol=result.symbol,
            ic=round(result.ic, 6),
            t_stat=round(result.t_stat, 4),
            p_value=round(result.p_value, 6),
            ic_cv=round(result.ic_cv, 4) if math.isfinite(result.ic_cv) else 0.0,
            n_obs=result.n_obs,
            significant=result.significant,
        ))

    return FactorRelevanceMatrixOut(
        symbol=symbol_upper,
        as_of=as_of,
        pairs=pairs_out,
    )


@router.get("/factors", response_model=list[AllFactorRelevanceOut])
def get_all_factor_relevance_summary(
    db: Session = Depends(get_db),
):
    """Summary: for each factor, how many stocks show significant IC.

    Returns a quick overview without computing per-pair detail; uses only
    pre-stored WFO signal summaries as a proxy for tracked symbols.
    """

    # Get all tracked symbols that have WFO results
    symbols = [
        row[0] for row in
        db.query(models.WfoSignalSummary.symbol).distinct().limit(200).all()
    ]

    result = []
    for spec in MACRO_SERIES:
        factor_series = _load_factor_series(db, spec.canonical_id)
        if factor_series is None:
            result.append(AllFactorRelevanceOut(
                factor_id=spec.canonical_id,
                n_significant=0,
                n_total=0,
                top_symbols=[],
            ))
            continue

        

        sig_pairs = []
        total = 0
        for sym in symbols:
            try:
                stock_prices = load_ohlcv_for_symbol(db, sym)
            except Exception:
                continue
            close_col = next((c for c in ["Close", "close", "Adj Close"] if c in stock_prices.columns), None)
            if close_col is None:
                continue
            stock_close = stock_prices[close_col].dropna()

            pair = compute_pair_relevance(
                factor_id=spec.canonical_id,
                symbol=sym,
                factor=factor_series,
                stock_prices=stock_close,
            )
            if pair is None:
                continue
            total += 1
            if pair.significant:
                sig_pairs.append((sym, abs(pair.ic)))

        sig_pairs.sort(key=lambda x: x[1], reverse=True)
        result.append(AllFactorRelevanceOut(
            factor_id=spec.canonical_id,
            n_significant=len(sig_pairs),
            n_total=total,
            top_symbols=[s for s, _ in sig_pairs[:5]],
        ))

    return result


# ---------------------------------------------------------------------------
# Phase 1 — factor signal evaluation
# ---------------------------------------------------------------------------

def _zeroed_ic_curve() -> ICCurveOut:
    horizons = [1, 2, 3, 5, 10]
    n = len(horizons)
    return ICCurveOut(
        horizons=horizons,
        ic_values=[0.0] * n,
        ic_se=[0.0] * n,
        ic_ci_lower=[0.0] * n,
        ic_ci_upper=[0.0] * n,
        n_obs=[0] * n,
    )


def _zeroed_portfolio() -> PortfolioStatsOut:
    return PortfolioStatsOut(
        sharpe=0.0, sortino=0.0, max_drawdown=0.0, calmar=0.0,
        turnover=0.0, hit_rate=0.0, profit_factor=0.0,
        avg_win=0.0, avg_loss=0.0, after_cost_sharpe=0.0,
        n_trades=0, total_return=0.0,
    )


def _zeroed_robustness() -> RobustnessOut:
    return RobustnessOut(
        dsr=0.0, psr=0.0,
        sharpe_bootstrap_ci=[0.0, 0.0],
        ic_bootstrap_ci=[0.0, 0.0],
        ic_cv=0.0, sharpe_cv=0.0, n_variants=len(REGISTERED_FACTOR_SIGNALS),
    )


@router.get("/factors/{symbol}/evaluate", response_model=list)
def evaluate_factor_signals(
    symbol: str,
    return_method: str = Query(default="open_to_open"),
    lookback_days: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Phase 1: evaluate all pre-registered factor signals for one stock.

    Returns one FactorSignalEvalOut per registered signal.
    Sector channel gate removed; all registered signals are evaluated for every stock.
    BH-FDR at q=0.10 applied across all conditional-return p-values.

    return_method: open_to_open | open_to_close
    """
    import datetime
    import math as _math

    from ..schemas.analytics import FactorSignalEvalOut

    symbol_upper = symbol.upper()

    try:
        stock_prices = load_ohlcv_for_symbol(db, symbol_upper)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    close_col, open_col = _get_ohlcv_cols(stock_prices)
    if close_col is None:
        raise HTTPException(status_code=422, detail=f"No close column for {symbol_upper!r}")

    stock_close = stock_prices[close_col].dropna()

    cutoff = _compute_cutoff(stock_close.index, lookback_days)
    if cutoff is not None:
        stock_close = stock_close[stock_close.index >= cutoff]

    # Pre-compute forward returns for the chosen return method (OOS only supports open-based)
    forward_returns = _compute_target_returns(stock_prices, return_method, close_col, open_col)
    if cutoff is not None and forward_returns is not None:
        forward_returns = forward_returns[forward_returns.index >= cutoff]

    # ic_prices for multi-horizon IC decay curve
    ic_prices: Optional[pd.Series] = None
    if open_col is not None and return_method == "open_to_open":
        open_series = stock_prices[open_col].dropna()
        if cutoff is not None:
            open_series = open_series[open_series.index >= cutoff]
        ic_prices = open_series.shift(-1)  # shift so pct_change(h).shift(-h) = open[t+h+1]/open[t+1]-1

    # Load all active macro factors and align
    aligned_factors: dict[str, pd.Series] = {}
    for macro_spec in MACRO_SERIES:
        factor_series = _load_factor_series(db, macro_spec.canonical_id)
        if factor_series is None:
            continue
        try:
            aligned_factors[macro_spec.canonical_id] = align_factor_to_target(
                target=stock_close,
                factor=factor_series,
                lag_rule="precede_open",
                max_staleness=3,
            )
        except Exception:
            continue  # treat corrupt/misaligned factor as missing

    # Evaluate each registered signal — no sector gate
    n_signals = len(REGISTERED_FACTOR_SIGNALS)
    reports: list[tuple[object, object | None]] = []
    macro_cost_bps = 33.0

    for spec in REGISTERED_FACTOR_SIGNALS:
        has_data = all(req in aligned_factors for req in spec.requires)
        if not has_data:
            reports.append((spec, None))
            continue
        try:
            sig_series = compute_factor_signal(spec, aligned_factors)
        except Exception:
            reports.append((spec, None))
            continue
        try:
            report = evaluate_signal(
                signal=sig_series,
                prices=stock_close,
                signal_id=spec.signal_name,
                symbol=symbol_upper,
                horizons=[1, 2, 3, 5, 10],
                costs={"spread_bps": 0.0, "commission_bps": macro_cost_bps},
                n_variants=n_signals,
                bootstrap_samples=500,
                forward_returns=forward_returns,
                ic_prices=ic_prices,
            )
            reports.append((spec, report))
        except Exception:
            reports.append((spec, None))

    # BH-FDR at q=0.10 across conditional-return p-values
    p_values: list[float] = []
    for spec, report in reports:
        if report is None:
            p_values.append(float("nan"))
        else:
            t = getattr(report, "conditional_return_tstat", 0.0) or 0.0
            if _math.isfinite(t) and t != 0.0:
                # Two-tailed p via normal approximation (math.erf, no scipy needed)
                p = float(min(1.0, 2.0 * (1.0 - 0.5 * (1.0 + _math.erf(abs(t) / _math.sqrt(2.0))))))
            else:
                p = 1.0
            p_values.append(p)

    finite_p = [(i, p) for i, p in enumerate(p_values) if _math.isfinite(p)]
    if finite_p:
        indices, pvals = zip(*finite_p)
        fdr_results = benjamini_hochberg(list(pvals), q=0.10)
        fdr_map = {idx: fdr_results[j] for j, idx in enumerate(indices)}
    else:
        fdr_map = {}

    # Assemble output
    out: list[FactorSignalEvalOut] = []
    for i, (spec, report) in enumerate(reports):
        has_data = all(req in aligned_factors for req in spec.requires)
        fdr_pass = bool(fdr_map.get(i, False))

        if report is None or not has_data:
            out.append(FactorSignalEvalOut(
                factor_id=spec.factor_id,
                signal_name=spec.signal_name,
                symbol=symbol_upper,
                citation=spec.citation,
                channel_filter=list(spec.channel_filter),
                applicable=True,
                ic_h1=0.0, ic_h5=0.0,
                hit_rate=0.0, sharpe=0.0, after_cost_sharpe=0.0,
                dsr=0.0, psr=0.0, conditional_return_tstat=0.0,
                n_obs=0, fdr_pass=False,
                ic_curve=_zeroed_ic_curve(),
                portfolio=_zeroed_portfolio(),
                robustness=_zeroed_robustness(),
                backtest=None,
            ))
            continue

        ic_vals = report.ic_curve.ic_values
        ic_h1 = _safe_float(ic_vals[0]) if ic_vals else 0.0
        ic_h5 = _safe_float(ic_vals[4]) if len(ic_vals) > 4 else 0.0
        try:
            signal_for_replay = compute_factor_signal(spec, aligned_factors)
            backtest_replay = _build_macro_backtest_replay(
                stock_prices=stock_prices,
                close_col=close_col,
                open_col=open_col,
                stock_close=stock_close,
                aligned_factors=aligned_factors,
                signal=signal_for_replay,
                spec=spec,
                forward_returns=forward_returns,
                return_method=return_method,
                cost_bps=macro_cost_bps,
            )
        except Exception:
            backtest_replay = None

        out.append(FactorSignalEvalOut(
            factor_id=spec.factor_id,
            signal_name=spec.signal_name,
            symbol=symbol_upper,
            citation=spec.citation,
            channel_filter=list(spec.channel_filter),
            applicable=True,
            ic_h1=ic_h1,
            ic_h5=ic_h5,
            hit_rate=_safe_float(report.hit_rate_h1),
            sharpe=_safe_float(report.portfolio.sharpe),
            after_cost_sharpe=_safe_float(report.portfolio.after_cost_sharpe),
            dsr=_safe_float(report.robustness.dsr),
            psr=_safe_float(report.robustness.psr),
            conditional_return_tstat=_safe_float(report.conditional_return_tstat),
            n_obs=report.n_obs,
            fdr_pass=fdr_pass,
            ic_curve=ICCurveOut(
                horizons=report.ic_curve.horizons,
                ic_values=[_safe_float(v) for v in report.ic_curve.ic_values],
                ic_se=[_safe_float(v) for v in report.ic_curve.ic_se],
                ic_ci_lower=[_safe_float(v) for v in report.ic_curve.ic_ci_lower],
                ic_ci_upper=[_safe_float(v) for v in report.ic_curve.ic_ci_upper],
                n_obs=report.ic_curve.n_obs,
            ),
            portfolio=PortfolioStatsOut(
                sharpe=_safe_float(report.portfolio.sharpe),
                sortino=_safe_float(report.portfolio.sortino),
                max_drawdown=_safe_float(report.portfolio.max_drawdown),
                calmar=_safe_float(report.portfolio.calmar),
                turnover=_safe_float(report.portfolio.turnover),
                hit_rate=_safe_float(report.portfolio.hit_rate),
                profit_factor=_safe_float(report.portfolio.profit_factor),
                avg_win=_safe_float(report.portfolio.avg_win),
                avg_loss=_safe_float(report.portfolio.avg_loss),
                after_cost_sharpe=_safe_float(report.portfolio.after_cost_sharpe),
                n_trades=report.portfolio.n_trades,
                total_return=_safe_float(report.portfolio.total_return),
            ),
            robustness=RobustnessOut(
                dsr=_safe_float(report.robustness.dsr),
                psr=_safe_float(report.robustness.psr),
                sharpe_bootstrap_ci=[
                    _safe_float(report.robustness.sharpe_bootstrap_ci_lower),
                    _safe_float(report.robustness.sharpe_bootstrap_ci_upper),
                ],
                ic_bootstrap_ci=[
                    _safe_float(report.robustness.ic_bootstrap_ci_lower),
                    _safe_float(report.robustness.ic_bootstrap_ci_upper),
                ],
                ic_cv=_safe_float(report.robustness.ic_cv),
                sharpe_cv=_safe_float(report.robustness.sharpe_cv),
                n_variants=n_signals,
            ),
            backtest=backtest_replay,
        ))

    return out


# ---------------------------------------------------------------------------
# Predictive ability (bucket × forward-horizon matrix)
# ---------------------------------------------------------------------------

_DEFAULT_FWD_HORIZONS = [1, 2, 3, 4, 5, 6, 10, 15, 21, 30, 60, 120, 200]
_VALID_CATEGORIES = ["tendance", "momentum", "oscillation", "volume"]


@dataclass(frozen=True)
class _ScoreSourceSpec:
    axis: str
    variant: str
    canonical_source: str
    read_sources: tuple[str, ...]


def _score_source(axis: str, variant: str) -> str:
    return f"{axis}:{resolve_signal_mode(variant).name}"


def _score_source_aliases(axis: str, variant: str) -> tuple[str, ...]:
    variant = resolve_signal_mode(variant).name
    aliases: list[str] = []
    if axis == "engine":
        if variant == "legacy_ta_simple":
            aliases.append("engine_legacy")
        elif variant == "expanded_ta_simple":
            aliases.append("engine_expanded")
        elif variant == "expanded_factor_x_ta_simple":
            aliases.append("factor_x_ta")
    elif axis == "wfo" and variant == "expanded_ta_simple":
        aliases.append("wfo")
    return tuple(aliases)


def _resolve_score_source(source: str, variant: str | None = None) -> _ScoreSourceSpec:
    raw_source = str(source or "").strip().lower()
    raw_variant = str(variant or "").strip().lower() or None

    if raw_source in {"signal_engine", "engine"}:
        axis = "engine"
        selected_variant = raw_variant or "expanded_ta_simple"
    elif raw_source == "wfo":
        axis = "wfo"
        selected_variant = raw_variant or "expanded_ta_simple"
    elif raw_source in {"engine_legacy", "legacy"}:
        axis = "engine"
        selected_variant = "legacy_ta_simple"
    elif raw_source in {"engine_expanded", "expanded"}:
        axis = "engine"
        selected_variant = "expanded_ta_simple"
    elif raw_source == "factor_x_ta":
        axis = "engine"
        selected_variant = "expanded_factor_x_ta_simple"
    elif ":" in raw_source:
        axis_part, variant_part = raw_source.split(":", 1)
        if axis_part in {"signal_engine", "engine"}:
            axis = "engine"
        elif axis_part == "wfo":
            axis = "wfo"
        else:
            raise ValueError("source axis must be engine|signal_engine|wfo")
        selected_variant = raw_variant or variant_part
    elif raw_source in SIGNAL_MODES or raw_source in SIGNAL_MODE_ALIASES:
        axis = "engine"
        selected_variant = raw_variant or raw_source
    else:
        raise ValueError(
            "source must be engine|wfo, an old alias, or axis:signal_mode"
        )

    mode = resolve_signal_mode(selected_variant)
    canonical = _score_source(axis, mode.name)
    read_sources = tuple(dict.fromkeys((canonical, *_score_source_aliases(axis, mode.name))))
    return _ScoreSourceSpec(
        axis=axis,
        variant=mode.name,
        canonical_source=canonical,
        read_sources=read_sources,
    )


def _score_history_horizons(horizon: str) -> tuple[str, ...]:
    try:
        canonical = canonical_horizon(horizon, allow_legacy=True)
    except ValueError:
        return (str(horizon).strip().lower(),)
    aliases = [
        legacy
        for legacy, mapped in LEGACY_HORIZON_ALIASES.items()
        if mapped == canonical
    ]
    return tuple(dict.fromkeys((canonical, *aliases)))


def _load_score_history(
    db: Session, *, symbol: str, source: str, horizon: str,
) -> dict[str, pd.Series]:
    spec = _resolve_score_source(source)
    source_priority = {name: idx for idx, name in enumerate(spec.read_sources)}
    rows = (
        db.query(models.SignalScoreHistory)
        .filter(
            models.SignalScoreHistory.symbol == symbol,
            models.SignalScoreHistory.source.in_(spec.read_sources),
            models.SignalScoreHistory.horizon.in_(_score_history_horizons(horizon)),
        )
        .order_by(models.SignalScoreHistory.date.asc())
        .all()
    )
    by_cat: dict[str, dict[pd.Timestamp, tuple[int, float]]] = {}
    for r in rows:
        ts = pd.Timestamp(r.date)
        if ts.tzinfo is not None:
            ts = ts.tz_convert(None)
        priority = source_priority.get(r.source, len(source_priority))
        current = by_cat.setdefault(r.category, {}).get(ts)
        if current is None or priority < current[0]:
            by_cat[r.category][ts] = (priority, r.score_pct)
    out: dict[str, pd.Series] = {}
    for cat, mapping in by_cat.items():
        idx = pd.DatetimeIndex(sorted(mapping.keys()))
        vals = [mapping[t][1] for t in idx]
        out[cat] = pd.Series(vals, index=idx, name=cat)
    return out


def _load_current_live_score(
    db: Session, *, symbol: str, source: str, horizon: str,
) -> float | None:
    """Return the latest live signal score from the appropriate table.

    WFO stores discretized {-100,0,+100} per category in SignalScoreHistory, so
    averaging them gives wrong values (e.g. -50 instead of -72). Instead we read
    directly from WfoGlobalSignal / SignalEngineGlobalResult which hold the true
    continuous ensemble scores.
    """
    spec = _resolve_score_source(source)
    horizons = _score_history_horizons(horizon)
    variants = signal_mode_read_names(spec.variant)
    if spec.axis == "wfo":
        row = (
            db.query(models.WfoGlobalSignal)
            .filter(
                models.WfoGlobalSignal.symbol == symbol,
                models.WfoGlobalSignal.horizon.in_(horizons),
                models.WfoGlobalSignal.variant.in_(variants),
            )
            .order_by(models.WfoGlobalSignal.updated_at.desc())
            .first()
        )
        if row is None or row.raw_score_pct is None:
            return None
        return float(row.raw_score_pct)

    row = (
        db.query(models.SignalEngineGlobalResult)
        .filter(
            models.SignalEngineGlobalResult.symbol == symbol,
            models.SignalEngineGlobalResult.horizon.in_(horizons),
            models.SignalEngineGlobalResult.variant.in_(variants),
        )
        .order_by(models.SignalEngineGlobalResult.updated_at.desc())
        .first()
    )
    if row is None:
        return None
    mode = resolve_signal_mode(spec.variant)
    score = (
        row.aggregate_score_pct
        if mode.is_legacy and row.aggregate_score_pct is not None
        else row.expanded_aggregate_score_pct
    )
    if score is None:
        score = row.aggregate_score_pct
    return float(score) if score is not None else None


def _load_pricing_data(db: Session, symbol: str) -> pd.DataFrame:
    from ..market_data_loader import load_ohlcv_for_symbol

    df = load_ohlcv_for_symbol(db, symbol)
    # Ensure index is DatetimeIndex
    df.index = pd.DatetimeIndex(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_convert(None)
    return df


def _load_close_series(db: Session, symbol: str) -> pd.Series:
    """Legacy helper for single close series."""
    df = _load_pricing_data(db, symbol)
    col = next((c for c in ["Close", "close", "Adj Close"] if c in df.columns), None)
    if col is None:
        raise ValueError(f"No close column in OHLCV frame for {symbol}")
    return df[col].dropna()


@router.get("/predictive-ability", response_model=PredictiveAbilityMatrix)
def get_predictive_ability(
    symbol: str = Query(...),
    source: str = Query(...),
    horizon: str = Query(...),
    variant: Optional[str] = Query(None, description="Canonical signal mode when source is engine|wfo"),
    categories: Optional[str] = Query(None, description="CSV subset of categories"),
    fwd_horizons: Optional[str] = Query(None, description="CSV of forward horizons"),
    lookback_days: int = Query(0, ge=0),
    return_calc_method: str = Query("close_to_close"),
    db: Session = Depends(get_db),
) -> PredictiveAbilityMatrix:
    """Return the bucket × forward-horizon matrix for one (symbol, source, horizon)."""

    try:
        source_spec = _resolve_score_source(source, variant)
        canonical_horizon(horizon, allow_legacy=True)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    if categories:
        cats = [c.strip() for c in categories.split(",") if c.strip()]
    else:
        cats = list(_VALID_CATEGORIES)
    bad = [c for c in cats if c not in _VALID_CATEGORIES]
    if bad:
        raise HTTPException(400, f"unknown categories: {bad}")

    if fwd_horizons:
        try:
            fhs = [int(x) for x in fwd_horizons.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(400, "fwd_horizons must be CSV of ints")
    else:
        fhs = list(_DEFAULT_FWD_HORIZONS)

    series_by_cat = _load_score_history(
        db,
        symbol=symbol,
        source=source_spec.canonical_source,
        horizon=horizon,
    )
    if not series_by_cat:
        return PredictiveAbilityMatrix(
            symbol=symbol, source=source_spec.canonical_source, horizon=horizon,
            categories=cats, n_obs=0,
            buckets=list(BUCKET_NAMES), fwd_horizons=fhs, cells=[],
            available=False,
            message="No score history yet — trigger predictive-history recompute.",
        )

    sample_idx = next((s.index for s in series_by_cat.values() if len(s) > 0), None)
    if sample_idx is not None:
        cutoff = _compute_cutoff(sample_idx, lookback_days)
        if cutoff is not None:
            series_by_cat = {cat: s[s.index >= cutoff] for cat, s in series_by_cat.items()}

    score = aggregate_subset(series_by_cat, cats)
    if score is None or score.dropna().empty:
        return PredictiveAbilityMatrix(
            symbol=symbol, source=source_spec.canonical_source, horizon=horizon,
            categories=cats, n_obs=0,
            buckets=list(BUCKET_NAMES), fwd_horizons=fhs, cells=[],
            available=False,
            message="Selected categories have no data for this (source, horizon).",
        )

    score_clean = score.dropna()
    current_score = _load_current_live_score(
        db,
        symbol=symbol,
        source=source_spec.canonical_source,
        horizon=horizon,
    )
    current_bucket = _bucket_for(current_score) if current_score is not None else None

    try:
        prices = _load_pricing_data(db, symbol)
    except Exception as exc:
        raise HTTPException(404, f"No price data for {symbol}: {exc}")

    cells_raw = bucketed_forward_returns(score, prices, fhs, return_calc_method=return_calc_method)
    cells = [PredictiveAbilityCell(**c) for c in cells_raw]
    return PredictiveAbilityMatrix(
        symbol=symbol, source=source_spec.canonical_source, horizon=horizon,
        categories=cats, n_obs=int(score_clean.shape[0]),
        buckets=list(BUCKET_NAMES), fwd_horizons=fhs, cells=cells,
        available=True,
        current_score=current_score,
        current_bucket=current_bucket,
    )


@router.get("/predictive-ability/combinations", response_model=CategoryCombinationsOut)
def get_category_combinations(
    symbol: str = Query(...),
    source: str = Query(...),
    horizon: str = Query(...),
    variant: Optional[str] = Query(None, description="Canonical signal mode when source is engine|wfo"),
    fwd_h: int = Query(5, ge=1, le=400),
    lookback_days: int = Query(0, ge=0),
    return_calc_method: str = Query("close_to_close"),
    db: Session = Depends(get_db),
) -> CategoryCombinationsOut:
    """For each non-empty subset of the 4 categories, evaluate the bucket matrix
    at one forward horizon and return a ranked list."""
    from itertools import combinations as _comb

    try:
        source_spec = _resolve_score_source(source, variant)
        canonical_horizon(horizon, allow_legacy=True)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    series_by_cat = _load_score_history(
        db,
        symbol=symbol,
        source=source_spec.canonical_source,
        horizon=horizon,
    )
    if not series_by_cat:
        return CategoryCombinationsOut(symbol=symbol, source=source_spec.canonical_source, horizon=horizon,
                                       fwd_h=fwd_h, rows=[])
    sample_idx = next((s.index for s in series_by_cat.values() if len(s) > 0), None)
    if sample_idx is not None:
        cutoff = _compute_cutoff(sample_idx, lookback_days)
        if cutoff is not None:
            series_by_cat = {cat: s[s.index >= cutoff] for cat, s in series_by_cat.items()}
    try:
        prices = _load_pricing_data(db, symbol)
    except Exception:
        return CategoryCombinationsOut(symbol=symbol, source=source_spec.canonical_source, horizon=horizon,
                                       fwd_h=fwd_h, rows=[])

    rows: list[CategoryCombinationRow] = []
    cats_present = [c for c in _VALID_CATEGORIES if c in series_by_cat]

    for r in range(1, len(cats_present) + 1):
        for subset in _comb(cats_present, r):
            score = aggregate_subset(series_by_cat, subset)
            if score is None:
                continue
            cells = bucketed_forward_returns(
                score, prices, [fwd_h], n_bootstrap=50, return_calc_method=return_calc_method
            )
            sb = next((c for c in cells if c["bucket"] == "strong_buy"), None)
            ss = next((c for c in cells if c["bucket"] == "strong_sell"), None)
            sb_mean = sb.get("mean") if sb else None
            ss_mean = ss.get("mean") if ss else None
            mono = (sb_mean - ss_mean) if (sb_mean is not None and ss_mean is not None) else None
            rows.append(CategoryCombinationRow(
                categories=list(subset),
                n_strong_buy=int(sb["n"]) if sb else 0,
                n_strong_sell=int(ss["n"]) if ss else 0,
                strong_buy_mean=sb_mean,
                strong_sell_mean=ss_mean,
                monotonicity_score=mono,
            ))

    rows.sort(key=lambda x: (x.monotonicity_score is None, -(x.monotonicity_score or 0)))
    return CategoryCombinationsOut(
        symbol=symbol, source=source_spec.canonical_source, horizon=horizon, fwd_h=fwd_h, rows=rows,
    )


# ---------------------------------------------------------------------------
# Leaderboard — IC of every (symbol, source) at a given engine_horizon
# ---------------------------------------------------------------------------

_FWD_BY_ENGINE_H = {
    "short": [1, 2, 3, 4, 5],
    "medium": [6, 10, 15, 21],
    "long": [30, 60, 120, 200],
}

# In-process cache keyed by engine_horizon. Cleared on score-history triggers.
_LEADERBOARD_CACHE: dict[str, LeaderboardOut] = {}

# In-process cache for the factor leaderboard (TTL-based, 5 min).
_FACTOR_LEADERBOARD_CACHE: dict[str, tuple[float, list[FactorLeaderboardRow]]] = {}
_FACTOR_LEADERBOARD_TTL_S = 300


def _invalidate_leaderboard_cache() -> None:
    _LEADERBOARD_CACHE.clear()
    _FACTOR_LEADERBOARD_CACHE.clear()


@router.get("/predictive-ability/leaderboard", response_model=LeaderboardOut)
def get_predictive_ability_leaderboard(
    engine_horizon: str = Query("short"),
    lookback_days: int = Query(0, ge=0),
    return_calc_method: str = Query("close_to_close"),
    db: Session = Depends(get_db),
) -> LeaderboardOut:
    """For every (symbol, source) at the given engine_horizon, compute IC and
    Newey-West t-stat at each forward horizon in that engine_horizon's natural set."""

    if engine_horizon not in _FWD_BY_ENGINE_H:
        raise HTTPException(400, "engine_horizon must be short|medium|long")

    cache_key = f"{engine_horizon}:{lookback_days}:{return_calc_method}"
    cached = _LEADERBOARD_CACHE.get(cache_key)
    if cached is not None:
        return cached

    fwd_horizons = _FWD_BY_ENGINE_H[engine_horizon]

    pairs = (
        db.query(models.SignalScoreHistory.symbol, models.SignalScoreHistory.source)
        .filter(models.SignalScoreHistory.horizon.in_(_score_history_horizons(engine_horizon)))
        .distinct()
        .all()
    )

    price_cache: dict[str, pd.DataFrame] = {}
    rows: list[LeaderboardRow] = []
    seen_pairs: set[tuple[str, str]] = set()

    for sym, src in pairs:
        try:
            source_spec = _resolve_score_source(src)
        except ValueError:
            continue
        pair_key = (sym, source_spec.canonical_source)
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        try:
            series_by_cat = _load_score_history(
                db, symbol=sym, source=source_spec.canonical_source, horizon=engine_horizon,
            )
        except Exception:
            continue
        if not series_by_cat:
            continue
        sample_idx = next((s.index for s in series_by_cat.values() if len(s) > 0), None)
        if sample_idx is not None:
            cutoff = _compute_cutoff(sample_idx, lookback_days)
            if cutoff is not None:
                series_by_cat = {cat: s[s.index >= cutoff] for cat, s in series_by_cat.items()}
        score = aggregate_subset(series_by_cat, _VALID_CATEGORIES)
        if score is None or score.dropna().empty:
            continue

        if sym not in price_cache:
            try:
                price_cache[sym] = _load_pricing_data(db, sym)
            except Exception:
                price_cache[sym] = pd.DataFrame()
        prices = price_cache[sym]
        if prices.empty:
            continue

        ic_by_h, t_by_h, n = ic_table(score, prices, fwd_horizons, return_calc_method=return_calc_method)
        if not ic_by_h:
            continue
        valid_ics = [v for v in ic_by_h.values() if v is not None]
        mean_ic = float(np.mean(valid_ics)) if valid_ics else None

        # --- mean hit rate ---
        # Compute bucketed cells at h=1 to get per-bucket hit rates, then average
        # directional accuracy: (buy+strong_buy hit_rate + sell+strong_sell hit_rate) / 2
        mean_hit_rate: float | None = None
        mean_sharpe: float | None = None
        try:
            from core.quant_core.research.score_history import bucketed_forward_returns as _bfr
            cells_h1 = _bfr(score, prices, [1], n_bootstrap=0, return_calc_method=return_calc_method)
            hr_vals = []
            for cell in cells_h1:
                if cell["bucket"] in ("buy", "strong_buy", "sell", "strong_sell"):
                    hr = cell.get("hit_rate")
                    if hr is not None:
                        hr_vals.append(hr)
            if hr_vals:
                mean_hit_rate = float(np.mean(hr_vals))

            # --- mean_sharpe: annualised Sharpe of a long/short PnL stream ---
            # Signal > 0 → long (1), signal < 0 → short (-1), else flat
            prices_clean = _strip_tz(prices)
            score_clean = _strip_tz(score)
            fwd_1 = _calculate_forward_returns(prices_clean, 1, method=return_calc_method)
            df_sh = pd.concat([score_clean, fwd_1], axis=1, keys=["s", "r"]).dropna()
            if len(df_sh) >= 30:
                direction = np.sign(df_sh["s"].to_numpy(dtype="float64"))
                pnl = direction * df_sh["r"].to_numpy(dtype="float64")
                mu = float(np.mean(pnl))
                sigma = float(np.std(pnl, ddof=1))
                if sigma > 1e-9:
                    mean_sharpe = float(mu / sigma * np.sqrt(252))
        except Exception:
            pass

        rows.append(LeaderboardRow(
            symbol=sym,
            source=source_spec.canonical_source,
            n=n,
            ic_by_fwd_h={int(k): v for k, v in ic_by_h.items()},
            tstat_by_fwd_h={int(k): v for k, v in t_by_h.items()},
            mean_ic=mean_ic,
            mean_hit_rate=mean_hit_rate,
            mean_sharpe=mean_sharpe,
        ))

    rows.sort(key=lambda r: (r.mean_ic is None, -(r.mean_ic or 0)))
    out = LeaderboardOut(
        engine_horizon=engine_horizon, fwd_horizons=fwd_horizons, rows=rows,
    )
    _LEADERBOARD_CACHE[cache_key] = out
    return out


def _finite_float(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    if not math.isfinite(out):
        return None
    return out


def _median_or_none(values: list[float]) -> float | None:
    finite = [float(v) for v in values if math.isfinite(float(v))]
    if not finite:
        return None
    return float(np.median(finite))


def _method_source_label(source: str) -> str:
    try:
        spec = _resolve_score_source(source)
        mode = resolve_signal_mode(spec.variant)
    except Exception:
        return source
    axis = "WFO" if spec.axis == "wfo" else "Signal Engine"
    universe = "Legacy" if mode.is_legacy else "Expanded"
    conditioning = "Factor x TA" if mode.is_factor_x_ta else "TA"
    complexity = "Combo" if mode.is_combo else "Simple"
    return f"{axis} - {universe} {conditioning} {complexity}"


def _symbols_for_method_universe(
    db: Session,
    *,
    universe: str,
    min_adv: float,
) -> set[str] | None:
    normalized = str(universe or "all").strip().lower()
    if normalized == "all":
        return None

    if normalized not in {"masi", "liquid_masi"}:
        raise HTTPException(400, "universe must be all|masi|liquid_masi")

    try:
        masters = db.query(models.StockMaster).filter(models.StockMaster.is_active == True).all()  # noqa: E712
    except Exception:
        db.rollback()
        return None

    masi_symbols = {
        str(row.symbol).upper()
        for row in masters
        if (getattr(row, "asset_type", None) or "equity") == "equity"
        and (getattr(row, "market_region", None) or "masi") == "masi"
    }
    if normalized == "masi":
        return masi_symbols

    try:
        from sqlalchemy import text as _text

        rows = db.execute(
            _text("""
            SELECT DISTINCT ON (symbol) symbol, adv_20d
            FROM market_data_store
            WHERE asset_class = 'equity'
              AND timeframe IN ('1D', '1d')
            ORDER BY symbol, CASE WHEN timeframe = '1D' THEN 0 ELSE 1 END
            """)
        ).mappings().all()
    except Exception:
        db.rollback()
        return masi_symbols

    liquid = {
        str(row["symbol"]).upper()
        for row in rows
        if _finite_float(row.get("adv_20d")) is not None
        and float(row.get("adv_20d") or 0.0) >= min_adv
    }
    return masi_symbols & liquid


def _is_method_row_eligible(row: LeaderboardRow) -> bool:
    ic = _finite_float(row.mean_ic)
    sharpe = _finite_float(row.mean_sharpe)
    hit = _finite_float(row.mean_hit_rate)
    return (
        row.n >= 30
        and ic is not None
        and sharpe is not None
        and hit is not None
        and ic > 0.0
        and sharpe > 0.0
        and hit >= 0.50
    )


@router.get("/method-evaluation", response_model=MethodEvaluationOut)
def get_method_evaluation(
    engine_horizon: str = Query("short"),
    universe: str = Query("liquid_masi"),
    lookback_days: int = Query(0, ge=0),
    return_calc_method: str = Query("open_to_open"),
    min_adv: float = Query(1_000_000.0, ge=0.0),
    db: Session = Depends(get_db),
) -> MethodEvaluationOut:
    """Evaluate each signal method across the selected universe.

    The output answers the operational question: which method families have
    enough positive OOS evidence to keep using, and which should be demoted.
    """

    if engine_horizon not in _FWD_BY_ENGINE_H:
        raise HTTPException(400, "engine_horizon must be short|medium|long")

    leaderboard = get_predictive_ability_leaderboard(
        engine_horizon=engine_horizon,
        lookback_days=lookback_days,
        return_calc_method=return_calc_method,
        db=db,
    )

    symbol_filter = _symbols_for_method_universe(db, universe=universe, min_adv=min_adv)
    source_groups: dict[str, list[LeaderboardRow]] = defaultdict(list)
    for row in leaderboard.rows:
        if symbol_filter is not None and row.symbol.upper() not in symbol_filter:
            continue
        source_groups[row.source].append(row)
    for axis in ("engine", "wfo"):
        for mode_name in SIGNAL_MODES:
            source_groups.setdefault(_score_source(axis, mode_name), [])

    out_rows: list[MethodEvaluationRow] = []
    for source, rows in source_groups.items():
        tested = len(rows)
        eligible = [row for row in rows if _is_method_row_eligible(row)]
        med_n = _median_or_none([float(row.n) for row in rows])
        med_ic = _median_or_none([v for row in rows for v in [_finite_float(row.mean_ic)] if v is not None])
        med_sharpe = _median_or_none([v for row in rows for v in [_finite_float(row.mean_sharpe)] if v is not None])
        med_hit = _median_or_none([v for row in rows for v in [_finite_float(row.mean_hit_rate)] if v is not None])
        med_abs_t = _median_or_none([
            abs(v)
            for row in rows
            for raw in row.tstat_by_fwd_h.values()
            for v in [_finite_float(raw)]
            if v is not None
        ])
        coverage = (eligible and tested > 0) and (len(eligible) / tested) or 0.0

        evidence_score: float | None = None
        if med_ic is not None and med_sharpe is not None and med_hit is not None and med_n is not None:
            sample_penalty = min(1.0, max(0.0, med_n / 120.0))
            evidence_score = med_ic * med_sharpe * (med_hit - 0.5) * sample_penalty

        reasons: list[str] = []
        if med_n is not None and med_n < 30:
            reasons.append("low_sample")
        if med_ic is not None and med_ic <= 0:
            reasons.append("negative_ic")
        if med_sharpe is not None and med_sharpe <= 0:
            reasons.append("negative_sharpe")
        if med_hit is not None and med_hit < 0.50:
            reasons.append("weak_hit_rate")

        min_keep = max(3, math.ceil(tested * 0.20))
        if tested <= 0:
            verdict = "no_data"
            reasons.append("no_history")
        elif len(eligible) >= min_keep and (med_ic or 0.0) > 0 and (med_sharpe or 0.0) > 0 and (med_hit or 0.0) >= 0.50:
            verdict = "keep"
            reasons.append("enough_positive_rows")
        elif tested >= 5 and len(eligible) == 0 and reasons:
            verdict = "discard"
        else:
            verdict = "watch"
            if len(eligible) < min_keep:
                reasons.append("sparse_eligible_rows")

        out_rows.append(MethodEvaluationRow(
            source=source,
            label=_method_source_label(source),
            verdict=verdict,
            tested_count=tested,
            eligible_count=len(eligible),
            coverage_pct=round(float(coverage) * 100.0, 2),
            median_n=round(med_n, 2) if med_n is not None else None,
            median_ic=round(med_ic, 6) if med_ic is not None else None,
            median_abs_tstat=round(med_abs_t, 4) if med_abs_t is not None else None,
            median_hit_rate=round(med_hit, 6) if med_hit is not None else None,
            median_sharpe=round(med_sharpe, 6) if med_sharpe is not None else None,
            evidence_score=round(evidence_score, 8) if evidence_score is not None else None,
            reason_codes=list(dict.fromkeys(reasons)),
        ))

    if not out_rows:
        out_rows.append(MethodEvaluationRow(
            source="none",
            label="No method history",
            verdict="no_data",
            tested_count=0,
            eligible_count=0,
            coverage_pct=0.0,
            reason_codes=["no_history"],
        ))

    verdict_order = {"keep": 0, "watch": 1, "discard": 2, "no_data": 3}
    out_rows.sort(
        key=lambda row: (
            verdict_order.get(row.verdict, 9),
            -(row.evidence_score if row.evidence_score is not None else -999.0),
            row.label,
        )
    )

    return MethodEvaluationOut(
        engine_horizon=engine_horizon,
        universe=universe,
        return_calc_method=return_calc_method,
        rows=out_rows,
    )


# ---------------------------------------------------------------------------
# Predictive-history population (RQ batch)
# ---------------------------------------------------------------------------

@router.post(
    "/predictive-history/trigger",
    response_model=PredictiveHistoryTriggerOut,
    dependencies=[Depends(rate_limit_trigger)],
)
def trigger_predictive_history(
    symbol: str = Query(...),
    db: Session = Depends(get_db),
) -> PredictiveHistoryTriggerOut:
    from redis import Redis
    from rq import Queue
    from ..config import settings

    row = db.query(models.ScoreHistoryJob).filter_by(symbol=symbol).first()
    if row is None:
        row = models.ScoreHistoryJob(symbol=symbol, status="pending")
        db.add(row)
    else:
        row.status = "pending"
        row.error_message = None
    db.commit()

    redis_conn = Redis.from_url(settings.REDIS_URL, decode_responses=False)
    q = Queue("score_history", connection=redis_conn)
    job = q.enqueue(
        "services.worker.tasks.score_history_batch.enqueue_score_history_for_symbol",
        symbol,
        job_timeout=7200,
    )
    row.rq_job_id = str(job.id)
    db.commit()
    _invalidate_leaderboard_cache()
    return PredictiveHistoryTriggerOut(triggered=1, job_ids=[str(job.id)])


@router.post(
    "/predictive-history/trigger-all",
    response_model=PredictiveHistoryTriggerOut,
    dependencies=[Depends(require_admin), Depends(rate_limit_trigger)],
)
def trigger_all_predictive_history(db: Session = Depends(get_db)) -> PredictiveHistoryTriggerOut:
    from redis import Redis
    from rq import Queue
    from ..config import settings

    wfo_syms = {s for (s,) in db.query(models.WfoSignalSummary.symbol).distinct().all()}
    eng_syms = {s for (s,) in db.query(models.SignalEngineGlobalResult.symbol).distinct().all()}
    symbols = list(wfo_syms | eng_syms)
    if not symbols:
        return PredictiveHistoryTriggerOut(triggered=0, job_ids=[])

    redis_conn = Redis.from_url(settings.REDIS_URL, decode_responses=False)
    q = Queue("score_history", connection=redis_conn)

    job_ids: list[str] = []
    for sym in symbols:
        row = db.query(models.ScoreHistoryJob).filter_by(symbol=sym).first()
        if row is None:
            row = models.ScoreHistoryJob(symbol=sym, status="pending")
            db.add(row)
        else:
            row.status = "pending"
            row.error_message = None
        job = q.enqueue(
            "services.worker.tasks.score_history_batch.enqueue_score_history_for_symbol",
            sym,
            job_timeout=7200,
        )
        row.rq_job_id = str(job.id)
        job_ids.append(str(job.id))
    db.commit()
    _invalidate_leaderboard_cache()
    return PredictiveHistoryTriggerOut(triggered=len(symbols), job_ids=job_ids)


@router.get("/predictive-history/batch-status", response_model=PredictiveHistoryStatus)
def predictive_history_batch_status(db: Session = Depends(get_db)) -> PredictiveHistoryStatus:
    from sqlalchemy import func as sa_func

    rows = (
        db.query(models.ScoreHistoryJob.status, sa_func.count().label("cnt"))
        .group_by(models.ScoreHistoryJob.status)
        .all()
    )
    counts: dict[str, int] = {r.status: r.cnt for r in rows}
    total = sum(counts.values())
    return PredictiveHistoryStatus(
        total=total,
        succeeded=counts.get("succeeded", 0),
        running=counts.get("running", 0),
        failed=counts.get("failed", 0),
        pending=counts.get("pending", 0),
    )


# ---------------------------------------------------------------------------
# Statistical arbitrage pair diagnostics (analytics-only)
# ---------------------------------------------------------------------------

def _stat_arb_iso(value: Any) -> str | None:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else None


def _stat_arb_warnings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _stat_arb_row_out(row: models.StatArbPairSignal) -> StatArbPairRow:
    return StatArbPairRow(
        pair_id=row.pair_id,
        symbol_y=row.symbol_y,
        symbol_x=row.symbol_x,
        horizon=row.horizon,
        archetype=row.archetype,
        lag_bars=row.lag_bars or 0,
        action_type=row.action_type or "none",
        current_signal=row.current_signal or "none",
        direction=row.direction or "none",
        validation_status=row.validation_status or "pending",
        status=row.status or "pending",
        n_obs=row.n_obs or 0,
        n_folds=row.n_folds or 0,
        hedge_ratio=row.hedge_ratio,
        intercept=row.intercept,
        zscore=row.zscore,
        half_life=row.half_life,
        adf_pvalue=row.adf_pvalue,
        raw_pvalue=row.raw_pvalue,
        fdr_qvalue=row.fdr_qvalue,
        oos_sharpe=row.oos_sharpe,
        oos_return=row.oos_return,
        max_drawdown=row.max_drawdown,
        profitable_fold_ratio=row.profitable_fold_ratio,
        data_as_of=_stat_arb_iso(row.data_as_of),
        cost_bps_per_side=float(row.cost_bps_per_side or 0.0),
        slippage_bps_per_side=float(row.slippage_bps_per_side or 0.0),
        borrow_bps_annual=float(row.borrow_bps_annual or 0.0),
        warnings=_stat_arb_warnings(row.warnings_json),
        updated_at=_stat_arb_iso(row.updated_at),
    )


def _stat_arb_detail_out(row: models.StatArbPairSignal) -> StatArbPairDetailOut:
    base = _stat_arb_row_out(row)
    data = base.model_dump() if hasattr(base, "model_dump") else base.dict()
    return StatArbPairDetailOut(
        **data,
        metrics=row.metrics_json if isinstance(row.metrics_json, dict) else {},
        chart=row.chart_json if isinstance(row.chart_json, dict) else {},
    )


def _stat_arb_job_out(row: models.StatArbBatchJob | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": str(row.id),
        "horizon": row.horizon,
        "status": row.status,
        "rq_job_id": row.rq_job_id,
        "total_pairs": row.total_pairs,
        "completed_pairs": row.completed_pairs,
        "failed_pairs": row.failed_pairs,
        "error_message": row.error_message,
        "started_at": _stat_arb_iso(row.started_at),
        "finished_at": _stat_arb_iso(row.finished_at),
        "created_at": _stat_arb_iso(row.created_at),
        "updated_at": _stat_arb_iso(row.updated_at),
    }


@router.post(
    "/stat-arb/recompute",
    response_model=StatArbTriggerOut,
    dependencies=[Depends(require_admin), Depends(rate_limit_trigger)],
)
def trigger_stat_arb_recompute(
    horizon: str = Query("short", description="Signal horizon: short|medium|long"),
    cost_bps_per_side: float | None = Query(None, ge=0),
    slippage_bps_per_side: float | None = Query(None, ge=0),
    borrow_bps_annual: float | None = Query(None, ge=0),
    max_drawdown_floor: float | None = Query(None, ge=-1, le=0),
    db: Session = Depends(get_db),
) -> StatArbTriggerOut:
    from redis import Redis
    from rq import Queue
    from ..config import settings

    canonical = canonical_horizon(horizon, allow_legacy=True)
    config = {
        key: value
        for key, value in {
            "cost_bps_per_side": cost_bps_per_side,
            "slippage_bps_per_side": slippage_bps_per_side,
            "borrow_bps_annual": borrow_bps_annual,
            "max_drawdown_floor": max_drawdown_floor,
        }.items()
        if value is not None
    }
    job_uuid = uuid.uuid4()
    row = models.StatArbBatchJob(
        id=job_uuid,
        horizon=canonical,
        status="pending",
        total_pairs=0,
        completed_pairs=0,
        failed_pairs=0,
    )
    db.add(row)
    db.commit()

    try:
        from os import getenv

        redis_conn = Redis.from_url(settings.REDIS_URL, decode_responses=False)
        queue = Queue(getenv("STAT_ARB_QUEUE_NAME", "score_history"), connection=redis_conn)
        job = queue.enqueue(
            "services.worker.tasks.stat_arb.compute_stat_arb_for_horizon",
            canonical,
            config,
            str(job_uuid),
            job_id=str(job_uuid),
            job_timeout=7200,
        )
        row.rq_job_id = str(job.id)
        db.commit()
    except Exception as exc:
        row.status = "failed"
        row.error_message = str(exc)
        db.commit()
        raise HTTPException(status_code=503, detail=f"Could not enqueue stat-arb recompute: {exc}") from exc

    return StatArbTriggerOut(triggered=1, job_ids=[str(job_uuid)])


@router.get("/stat-arb/status", response_model=StatArbStatusOut)
def stat_arb_batch_status(db: Session = Depends(get_db)) -> StatArbStatusOut:
    from sqlalchemy import func as sa_func

    rows = (
        db.query(models.StatArbBatchJob.status, sa_func.count().label("cnt"))
        .group_by(models.StatArbBatchJob.status)
        .all()
    )
    counts: dict[str, int] = {r.status: r.cnt for r in rows}
    latest = (
        db.query(models.StatArbBatchJob)
        .order_by(models.StatArbBatchJob.created_at.desc())
        .first()
    )
    total = sum(counts.values())
    return StatArbStatusOut(
        total=total,
        pending=counts.get("pending", 0),
        running=counts.get("running", 0),
        succeeded=counts.get("succeeded", 0),
        failed=counts.get("failed", 0),
        latest=_stat_arb_job_out(latest),
    )


@router.get("/stat-arb/leaderboard", response_model=StatArbLeaderboardOut)
def get_stat_arb_leaderboard(
    horizon: str = Query("short"),
    archetype: str | None = Query(None),
    action_type: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> StatArbLeaderboardOut:
    from sqlalchemy import case, desc, nullslast

    canonical = canonical_horizon(horizon, allow_legacy=True)
    query = db.query(models.StatArbPairSignal).filter(models.StatArbPairSignal.horizon == canonical)
    if archetype:
        query = query.filter(models.StatArbPairSignal.archetype == archetype)
    if action_type:
        query = query.filter(models.StatArbPairSignal.action_type == action_type)
    if status:
        query = query.filter(models.StatArbPairSignal.status == status)

    status_rank = case(
        (models.StatArbPairSignal.status == "actionable", 0),
        (models.StatArbPairSignal.status == "watch", 1),
        (models.StatArbPairSignal.status == "rejected", 2),
        (models.StatArbPairSignal.status == "failed", 3),
        else_=9,
    )
    rows = (
        query.order_by(
            status_rank,
            nullslast(desc(models.StatArbPairSignal.oos_sharpe)),
            nullslast(desc(models.StatArbPairSignal.profitable_fold_ratio)),
            models.StatArbPairSignal.symbol_y,
            models.StatArbPairSignal.symbol_x,
        )
        .limit(limit)
        .all()
    )
    return StatArbLeaderboardOut(horizon=canonical, rows=[_stat_arb_row_out(row) for row in rows])


@router.get("/stat-arb/pairs/{pair_id}", response_model=StatArbPairDetailOut)
def get_stat_arb_pair_detail(pair_id: str, db: Session = Depends(get_db)) -> StatArbPairDetailOut:
    row = db.get(models.StatArbPairSignal, pair_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Stat-arb pair not found")
    return _stat_arb_detail_out(row)


# ---------------------------------------------------------------------------
# Edge metrics endpoint (§4.2.b of the edge-deploy plan)
# ---------------------------------------------------------------------------

def _edge_redis() -> "Any":
    """Return a Redis client for edge cache operations, or None if unavailable."""
    try:
        from redis import Redis
        from ..config import settings
        return Redis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception:
        return None


def _edge_cache_key(
    *,
    source: str,
    variant: str,
    symbol: str,
    horizon: str,
    cost_bps: float,
    methodology_version: str,
    score_revision_hash: str,
) -> str:
    return (
        f"edge:v{methodology_version}:{source}:{variant}:{symbol}:{horizon}"
        f":c{int(cost_bps)}:{score_revision_hash}"
    )


def _score_revision_hash(
    *,
    data_as_of: Any,
    row_count: int,
    folds_hash: str,
) -> str:
    import hashlib
    raw = f"{data_as_of}|{row_count}|{folds_hash}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _folds_hash(folds_json: Any) -> str:
    import hashlib, json
    if folds_json is None:
        return "none"
    try:
        serialized = json.dumps(folds_json, sort_keys=True, default=str)
    except Exception:
        serialized = str(folds_json)
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]


def _edge_db_horizons(canonical_horizon_name: str) -> list[str]:
    from core.quant_core.horizons import LEGACY_HORIZON_ALIASES

    out = [canonical_horizon_name]
    out.extend(legacy for legacy, new in LEGACY_HORIZON_ALIASES.items() if new == canonical_horizon_name)
    return out


def _edge_multiple_testing_count() -> int:
    return 2 * len(SIGNAL_MODES)


def _oos_sample_from_dates(base: Any, dates: Any) -> Any:
    from core.quant_core.research.oos_index import OosSample, OosWindow

    idx = pd.DatetimeIndex(dates).dropna().sort_values().unique()
    windows: tuple[Any, ...]
    if len(idx) == 0:
        windows = ()
    else:
        windows = (
            OosWindow(
                fold_id=None,
                start=pd.Timestamp(idx[0]),
                end=pd.Timestamp(idx[-1]),
                winner_variant_id=None,
                winner_params=None,
            ),
        )
    return OosSample(
        source=base.source,
        horizon=base.horizon,
        windows=windows,
        dates=idx,
        score_mode=base.score_mode,
    )


def _date_union_from_windows(windows: tuple[Any, ...]) -> pd.DatetimeIndex:
    parts: list[pd.DatetimeIndex] = []
    for w in windows:
        parts.append(pd.date_range(start=w.start, end=w.end, freq="B"))
    if not parts:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex(sorted(set().union(*[set(part) for part in parts])))


def _oos_sample_from_windows(base: Any, windows: tuple[Any, ...]) -> Any:
    from core.quant_core.research.oos_index import OosSample

    return OosSample(
        source=base.source,
        horizon=base.horizon,
        windows=windows,
        dates=_date_union_from_windows(windows),
        score_mode=base.score_mode,
    )


def _split_wfo_oos_for_edge(oos_sample: Any) -> tuple[Any, Any]:
    windows = tuple(
        sorted(
            tuple(oos_sample.windows or ()),
            key=lambda w: (pd.Timestamp(w.start), pd.Timestamp(w.end), str(w.fold_id)),
        )
    )
    if len(windows) >= 2:
        proof_count = max(1, int(math.ceil(len(windows) / 3.0)))
        proof_count = min(proof_count, len(windows) - 1)
        return (
            _oos_sample_from_windows(oos_sample, windows[:-proof_count]),
            _oos_sample_from_windows(oos_sample, windows[-proof_count:]),
        )

    dates = pd.DatetimeIndex(oos_sample.dates).dropna().sort_values().unique()
    if len(dates) < 2:
        return _oos_sample_from_dates(oos_sample, []), _oos_sample_from_dates(oos_sample, [])
    cut = max(1, min(len(dates) - 1, int(math.floor(len(dates) * 2.0 / 3.0))))
    return _oos_sample_from_dates(oos_sample, dates[:cut]), _oos_sample_from_dates(oos_sample, dates[cut:])


def _signal_engine_selection_sample(
    oos_sample: Any,
    *,
    score_index: pd.DatetimeIndex,
    holdout_bars: int,
) -> Any:
    dates = pd.DatetimeIndex(score_index).dropna().sort_values().unique()
    proof_dates = pd.DatetimeIndex(oos_sample.dates).dropna().sort_values().unique()
    if len(proof_dates) > 0:
        dates = dates[dates < pd.Timestamp(proof_dates[0])]
    elif int(holdout_bars) > 0 and len(dates) > int(holdout_bars):
        dates = dates[:-int(holdout_bars)]
    selection_bars = max(1, int(holdout_bars or 0))
    return _oos_sample_from_dates(oos_sample, dates[-selection_bars:])


def _edge_revision_context(
    *,
    db: "Session",
    symbol: str,
    horizon: str,
    source: str,
    variant: str | None = None,
) -> tuple[str, str, str] | None:
    from core.quant_core.horizons import canonical_horizon
    from sqlalchemy import func as _func

    try:
        canonical_h = canonical_horizon(horizon, allow_legacy=True)
        source_spec = _resolve_score_source(source, variant)
    except ValueError:
        return None

    symbol_upper = symbol.upper()
    db_horizons = _edge_db_horizons(canonical_h)
    variants = signal_mode_read_names(source_spec.variant)

    if source_spec.axis == "wfo":
        summary = (
            db.query(models.WfoSignalSummary)
            .filter(
                models.WfoSignalSummary.symbol == symbol_upper,
                models.WfoSignalSummary.horizon.in_(db_horizons),
                models.WfoSignalSummary.variant.in_(variants),
                models.WfoSignalSummary.status == "succeeded",
            )
            .order_by(models.WfoSignalSummary.updated_at.desc())
            .first()
        )
        if summary is None:
            return None
        row_count = int(
            db.query(_func.count())
            .select_from(models.SignalScoreHistory)
            .filter(
                models.SignalScoreHistory.symbol == symbol_upper,
                models.SignalScoreHistory.source.in_(source_spec.read_sources),
                models.SignalScoreHistory.horizon.in_(db_horizons),
            )
            .scalar()
            or 0
        )
        if row_count <= 0:
            return None
        rev_hash = _score_revision_hash(
            data_as_of=str(summary.data_as_of or summary.updated_at or ""),
            row_count=row_count,
            folds_hash=_folds_hash(summary.folds_json),
        )
        return canonical_h, source_spec.variant, rev_hash

    if source_spec.axis == "engine":
        global_row = (
            db.query(models.SignalEngineGlobalResult)
            .filter(
                models.SignalEngineGlobalResult.symbol == symbol_upper,
                models.SignalEngineGlobalResult.horizon.in_(db_horizons),
                models.SignalEngineGlobalResult.variant.in_(variants),
                models.SignalEngineGlobalResult.status == "succeeded",
            )
            .order_by(models.SignalEngineGlobalResult.updated_at.desc())
            .first()
        )
        row_count = int(
            db.query(_func.count())
            .select_from(models.SignalScoreHistory)
            .filter(
                models.SignalScoreHistory.symbol == symbol_upper,
                models.SignalScoreHistory.source.in_(source_spec.read_sources),
                models.SignalScoreHistory.horizon.in_(db_horizons),
            )
            .scalar()
            or 0
        )
        if global_row is None and row_count <= 0:
            return None
        data_as_of = getattr(global_row, "data_as_of", None) if global_row is not None else None
        if data_as_of is None:
            data_as_of = (
                db.query(_func.max(models.SignalScoreHistory.date))
                .filter(
                    models.SignalScoreHistory.symbol == symbol_upper,
                    models.SignalScoreHistory.source.in_(source_spec.read_sources),
                    models.SignalScoreHistory.horizon.in_(db_horizons),
                )
                .scalar()
            )
        rev_hash = _score_revision_hash(
            data_as_of=str(data_as_of or ""),
            row_count=row_count,
            folds_hash="none",
        )
        return canonical_h, source_spec.variant, rev_hash

    return None


def _edge_cache_payload(
    *,
    db: "Session",
    symbol: str,
    horizon: str,
    source: str,
    variant: str | None = None,
    cost_bps: float,
) -> tuple[dict[str, Any] | None, str]:
    import json
    from core.quant_core.research.edge import METHODOLOGY_VERSION

    ctx = _edge_revision_context(db=db, symbol=symbol, horizon=horizon, source=source, variant=variant)
    if ctx is None:
        return None, "missing"

    canonical_h, canonical_variant, rev_hash = ctx
    cache_key = _edge_cache_key(
        source=source,
        variant=canonical_variant,
        symbol=symbol.upper(),
        horizon=canonical_h,
        cost_bps=cost_bps,
        methodology_version=METHODOLOGY_VERSION,
        score_revision_hash=rev_hash,
    )
    redis = _edge_redis()
    if redis is None:
        return None, "cold"
    try:
        cached = redis.get(cache_key)
    except Exception:
        return None, "cold"
    if not cached:
        return None, "cold"
    try:
        return json.loads(cached), "hit"
    except Exception:
        return None, "cold"


def _store_edge_cache_payload(
    *,
    db: "Session",
    symbol: str,
    horizon: str,
    source: str,
    variant: str | None = None,
    cost_bps: float,
    out_json: str,
) -> bool:
    from core.quant_core.research.edge import METHODOLOGY_VERSION

    ctx = _edge_revision_context(db=db, symbol=symbol, horizon=horizon, source=source, variant=variant)
    if ctx is None:
        return False
    canonical_h, canonical_variant, rev_hash = ctx
    redis = _edge_redis()
    if redis is None:
        return False
    cache_key = _edge_cache_key(
        source=source,
        variant=canonical_variant,
        symbol=symbol.upper(),
        horizon=canonical_h,
        cost_bps=cost_bps,
        methodology_version=METHODOLOGY_VERSION,
        score_revision_hash=rev_hash,
    )
    try:
        redis.setex(cache_key, 25 * 3600, out_json)
        return True
    except Exception:
        return False


def _build_edge_metrics_from_db(
    *,
    symbol: str,
    horizon: str,
    source: str,
    variant: str | None = None,
    cost_bps: float,
    db: "Session",
    multiple_testing_count: int | None = None,
    bucket_override: str | None = None,
) -> "EdgeMetrics | None":
    """Load all required data from DB and compute EdgeMetrics. Returns None on missing data."""
    from core.quant_core.horizons import HORIZON_SPECS, canonical_horizon
    from core.quant_core.research.edge import build_edge_payload
    from core.quant_core.research.oos_index import oos_sample_for
    from core.quant_core.research.score_history import aggregate_subset, _bucket_for

    # Resolve legacy horizon aliases (short/medium/long → weekly/monthly/quarterly).
    try:
        canonical_h = canonical_horizon(horizon, allow_legacy=True)
        source_spec = _resolve_score_source(source, variant)
    except ValueError:
        return None

    spec = HORIZON_SPECS[canonical_h]
    public_source = "wfo" if source_spec.axis == "wfo" else "signal_engine"
    db_sources = source_spec.read_sources
    variants = signal_mode_read_names(source_spec.variant)
    multiple_testing_count = int(multiple_testing_count or _edge_multiple_testing_count())

    # --- Load score history rows for all categories ---
    # Try candidate horizons: canonical first, then legacy alias.
    db_horizons = _edge_db_horizons(canonical_h)

    symbol_upper = symbol.upper()
    series_by_cat = _load_score_history(
        db,
        symbol=symbol_upper,
        source=source_spec.canonical_source,
        horizon=canonical_h,
    )

    if not series_by_cat:
        return None

    score = aggregate_subset(series_by_cat, list(series_by_cat.keys()))
    if score is None or score.dropna().empty:
        return None

    # --- Determine today's bucket ---
    live_score_raw = _load_current_live_score(
        db, symbol=symbol_upper, source=source_spec.canonical_source, horizon=canonical_h,
    )
    if live_score_raw is None:
        # Fall back to the latest bar in score history.
        live_score_raw = float(score.dropna().iloc[-1])
    today_bucket = str(bucket_override or _bucket_for(live_score_raw))

    # --- Load prices ---
    try:
        prices = _load_pricing_data(db, symbol_upper)
    except Exception:
        return None

    # --- OOS loaders ---
    ohlcv_idx = pd.DatetimeIndex(prices.index)

    def wfo_loader(sym: str, h: str) -> dict:
        from ..services.wfo_folds import normalize_wfo_folds_json

        for db_h in db_horizons:
            summary = (
                db.query(models.WfoSignalSummary)
                .filter(
                    models.WfoSignalSummary.symbol == sym,
                    models.WfoSignalSummary.horizon == db_h,
                    models.WfoSignalSummary.variant.in_(variants),
                    models.WfoSignalSummary.status == "succeeded",
                    models.WfoSignalSummary.folds_json.isnot(None),
                )
                .order_by(models.WfoSignalSummary.updated_at.desc())
                .first()
            )
            if summary is not None and summary.folds_json:
                return {
                    "folds_json": normalize_wfo_folds_json(
                        summary.folds_json,
                        config_json=summary.config_json,
                        ohlcv_index=ohlcv_idx,
                    )
                }
        return {}

    def score_history_loader(sym: str, h: str) -> list[dict]:
        out = []
        rows = (
            db.query(models.SignalScoreHistory)
            .filter(
                models.SignalScoreHistory.symbol == sym,
                models.SignalScoreHistory.source.in_(db_sources),
                models.SignalScoreHistory.horizon.in_(db_horizons),
            )
            .order_by(models.SignalScoreHistory.date.asc())
            .all()
        )
        if rows:
            out.extend({"date": r.date, "is_oos": bool(getattr(r, "is_oos", False))} for r in rows)
        return out

    oos_sample = oos_sample_for(
        symbol=symbol_upper,
        horizon=canonical_h,
        source=public_source,
        wfo_loader=wfo_loader if public_source == "wfo" else None,
        score_history_loader=score_history_loader if public_source == "signal_engine" else None,
        ohlcv_index_loader=lambda sym: ohlcv_idx,
        holdout_bars=spec.signal_engine_holdout_bars,
    )
    if public_source == "wfo":
        selection_oos_sample, proof_oos_sample = _split_wfo_oos_for_edge(oos_sample)
    else:
        selection_oos_sample = _signal_engine_selection_sample(
            oos_sample,
            score_index=pd.DatetimeIndex(score.dropna().index),
            holdout_bars=spec.signal_engine_holdout_bars,
        )
        proof_oos_sample = oos_sample

    if len(pd.DatetimeIndex(selection_oos_sample.dates)) == 0 or len(pd.DatetimeIndex(proof_oos_sample.dates)) == 0:
        return None

    metrics = build_edge_payload(
        symbol=symbol_upper,
        horizon=canonical_h,
        source=public_source,
        score_series=score,
        prices=prices,
        oos_sample=proof_oos_sample,
        today_bucket=today_bucket,
        fwd_horizon_bars=spec.reference_forward_days,
        holding_period_candidates=tuple(range(spec.prediction_min_days, spec.prediction_max_days + 1)),
        cost_bps_per_side=cost_bps,
        return_calc_method="open_to_exit_ladder",
        variant=source_spec.variant,
        selection_oos_sample=selection_oos_sample,
        multiple_testing_count=multiple_testing_count,
    )
    if public_source != "wfo":
        return metrics

    fragility = _edge_fragility_from_db(
        db=db,
        symbol=symbol_upper,
        db_horizons=db_horizons,
        variant=source_spec.variant,
    )
    return replace(
        metrics,
        fragility_label=str(fragility.get("label") or "unavailable"),
        fragility_fold_count=int(fragility.get("fold_count") or 0),
        fragility_details=tuple(fragility.get("details") or ()),
    )


def _edge_fragility_from_db(
    *,
    db: "Session",
    symbol: str,
    db_horizons: list[str],
    variant: str | None = None,
) -> dict[str, Any]:
    severity = {
        "unavailable": 0,
        "no_severe_fragility": 1,
        "mixed_local_sensitivity": 2,
        "fragility_in_most_folds": 3,
    }
    rows = (
        db.query(models.WfoSignalSummary)
        .filter(
            models.WfoSignalSummary.symbol == symbol.upper(),
            models.WfoSignalSummary.horizon.in_(db_horizons),
            models.WfoSignalSummary.variant.in_(signal_mode_read_names(variant or "expanded_ta_simple")),
            models.WfoSignalSummary.status == "succeeded",
            models.WfoSignalSummary.fragility_json.isnot(None),
        )
        .all()
    )
    if not rows:
        return {"label": "unavailable", "fold_count": 0, "details": []}
    best_label = "unavailable"
    fold_count = 0
    details: list[dict[str, Any]] = []
    for row in rows:
        payload = dict(row.fragility_json or {})
        label = str(payload.get("label") or "unavailable")
        if severity.get(label, 0) > severity.get(best_label, 0):
            best_label = label
        fold_count += int(payload.get("fold_count") or 0)
        for item in list(payload.get("details") or []):
            if isinstance(item, dict):
                details.append({"category": row.category, **item})
    return {"label": best_label, "fold_count": fold_count, "details": details}


def _edge_metrics_to_out(m: "EdgeMetrics") -> "EdgeMetricsOut":
    def _exp(e: Any) -> "ExpectancyDecompOut | None":
        if e is None:
            return None
        return ExpectancyDecompOut(
            p_win=e.p_win, avg_win=e.avg_win,
            p_loss=e.p_loss, avg_loss=e.avg_loss, expectancy=e.expectancy,
        )

    return EdgeMetricsOut(
        symbol=m.symbol,
        horizon=m.horizon,
        source=m.source,
        variant=m.variant,
        bucket=m.bucket,
        direction=m.direction,
        n=m.n,
        window_start=m.window_start.date().isoformat() if m.window_start else None,
        window_end=m.window_end.date().isoformat() if m.window_end else None,
        fwd_horizon_bars=m.fwd_horizon_bars,
        return_calc_method=m.return_calc_method,
        entry_price_kind=m.entry_price_kind,
        entry_lag_bars=m.entry_lag_bars,
        exit_price_kind=m.exit_price_kind,
        exit_lag_bars=m.exit_lag_bars,
        exit_timing_label=m.exit_timing_label,
        holding_period_min_bars=m.holding_period_min_bars,
        holding_period_max_bars=m.holding_period_max_bars,
        holding_period_candidate_count=m.holding_period_candidate_count,
        holding_period_selection_metric=m.holding_period_selection_metric,
        side_policy=m.side_policy,
        action_expected_return_gross=m.action_expected_return_gross,
        action_expected_return_gross_ci_lower=m.action_expected_return_gross_ci_lower,
        action_expected_return_gross_ci_upper=m.action_expected_return_gross_ci_upper,
        action_expected_return_net=m.action_expected_return_net,
        action_expected_return_net_ci_lower=m.action_expected_return_net_ci_lower,
        action_expected_return_net_ci_upper=m.action_expected_return_net_ci_upper,
        stock_expected_return=m.stock_expected_return,
        stock_expected_return_ci_lower=m.stock_expected_return_ci_lower,
        stock_expected_return_ci_upper=m.stock_expected_return_ci_upper,
        expected_return_gross=m.expected_return_gross,
        expected_return_gross_ci_lower=m.expected_return_gross_ci_lower,
        expected_return_gross_ci_upper=m.expected_return_gross_ci_upper,
        expected_return_net=m.expected_return_net,
        expected_return_net_ci_lower=m.expected_return_net_ci_lower,
        expected_return_net_ci_upper=m.expected_return_net_ci_upper,
        hit_rate=m.hit_rate,
        hit_ci_lower=m.hit_ci_lower,
        hit_ci_upper=m.hit_ci_upper,
        expectancy_gross=_exp(m.expectancy_gross),
        expectancy_net=_exp(m.expectancy_net),
        edge_ratio_gross=m.edge_ratio_gross,
        edge_ratio_net=m.edge_ratio_net,
        profit_factor_gross=m.profit_factor_gross,
        profit_factor_net=m.profit_factor_net,
        mc_luck_pvalue_gross=m.mc_luck_pvalue_gross,
        mc_luck_pvalue_net=m.mc_luck_pvalue_net,
        label_shuffle_pvalue_gross=m.label_shuffle_pvalue_gross,
        label_shuffle_pvalue_net=m.label_shuffle_pvalue_net,
        mc_luck_pvalue_gross_adj=m.mc_luck_pvalue_gross_adj,
        mc_luck_pvalue_net_adj=m.mc_luck_pvalue_net_adj,
        label_shuffle_pvalue_gross_adj=m.label_shuffle_pvalue_gross_adj,
        label_shuffle_pvalue_net_adj=m.label_shuffle_pvalue_net_adj,
        proven_edge_gross=m.proven_edge_gross,
        proven_edge_net=m.proven_edge_net,
        edge_score=m.edge_score,
        edge_score_components=dict(m.edge_score_components or {}),
        gates=EdgeGatesOut(
            mc_gross=m.gates.mc_gross,
            mc_net=m.gates.mc_net,
            label_shuffle_gross=m.gates.label_shuffle_gross,
            label_shuffle_net=m.gates.label_shuffle_net,
            wilson=m.gates.wilson,
            n=m.gates.n,
            freshness_gross=m.gates.freshness_gross,
            freshness_net=m.gates.freshness_net,
        ),
        cost_bps_per_side=m.cost_bps_per_side,
        methodology_version=m.methodology_version,
        proof_max_lookback_years=m.proof_max_lookback_years,
        freshness_lookback_years=m.freshness_lookback_years,
        freshness_min_n=m.freshness_min_n,
        freshness_n=m.freshness_n,
        freshness_window_start=m.freshness_window_start.date().isoformat() if m.freshness_window_start else None,
        freshness_window_end=m.freshness_window_end.date().isoformat() if m.freshness_window_end else None,
        freshness_action_expected_return_gross=m.freshness_action_expected_return_gross,
        freshness_action_expected_return_net=m.freshness_action_expected_return_net,
        freshness_hit_rate=m.freshness_hit_rate,
        freshness_status=m.freshness_status,
        selection_n=m.selection_n,
        selection_window_start=m.selection_window_start.date().isoformat() if m.selection_window_start else None,
        selection_window_end=m.selection_window_end.date().isoformat() if m.selection_window_end else None,
        selection_action_expected_return_gross=m.selection_action_expected_return_gross,
        selection_action_expected_return_net=m.selection_action_expected_return_net,
        selection_hit_rate=m.selection_hit_rate,
        proof_n=m.proof_n,
        proof_window_start=m.proof_window_start.date().isoformat() if m.proof_window_start else None,
        proof_window_end=m.proof_window_end.date().isoformat() if m.proof_window_end else None,
        proof_method=m.proof_method,
        multiple_testing_count=m.multiple_testing_count,
        fragility_label=m.fragility_label,
        fragility_fold_count=m.fragility_fold_count,
        fragility_details=list(m.fragility_details or ()),
    )


def _warm_edge_cache_entries(
    *,
    db: "Session",
    symbols: list[str] | None,
    horizons: list[str] | None,
    sources: list[str] | None,
    variants: list[str] | None,
    cost_bps: float,
) -> dict[str, int]:
    from core.quant_core.horizons import VALID_HORIZONS, canonical_horizon

    if not horizons:
        horizons = list(VALID_HORIZONS)
    if not sources:
        sources = ["signal_engine", "wfo"]
    if not variants:
        variants = list(SIGNAL_MODES)
    variants = [resolve_signal_mode(v).name for v in variants]
    if not symbols:
        wfo_syms = {s for (s,) in db.query(models.WfoSignalSummary.symbol).distinct().all()}
        eng_syms = {s for (s,) in db.query(models.SignalEngineGlobalResult.symbol).distinct().all()}
        symbols = sorted(wfo_syms | eng_syms)

    warmed = 0
    errors = 0
    for sym in symbols:
        for h in horizons:
            try:
                canonical_h = canonical_horizon(h, allow_legacy=True)
            except ValueError:
                continue
            for src in sources:
                for variant in variants:
                    try:
                        metrics = _build_edge_metrics_from_db(
                            symbol=sym,
                            horizon=canonical_h,
                            source=src,
                            variant=variant,
                            cost_bps=cost_bps,
                            db=db,
                            multiple_testing_count=_edge_multiple_testing_count(),
                        )
                        if metrics is None:
                            continue
                        out_json = _edge_metrics_to_out(metrics).model_dump_json()
                        if _store_edge_cache_payload(
                            db=db,
                            symbol=sym,
                            horizon=canonical_h,
                            source=src,
                            variant=variant,
                            cost_bps=cost_bps,
                            out_json=out_json,
                        ):
                            warmed += 1
                    except Exception:
                        errors += 1

    return {"warmed": warmed, "errors": errors, "symbols": len(symbols)}


@router.get("/edge", response_model=EdgeMetricsOut | None)
def get_edge_metrics(
    symbol: str = Query(...),
    horizon: str = Query(..., description="weekly | monthly | quarterly (short/medium/long also accepted)"),
    source: str = Query(..., description="signal_engine | wfo"),
    variant: Optional[str] = Query(None, description="Signal mode variant; defaults to expanded_ta_simple"),
    cost_bps: float | None = Query(default=None, ge=0.0, le=500.0),
    db: Session = Depends(get_db),
) -> Any:
    """Return cached Edge metrics for one (symbol, horizon, source) cell.

    Returns 200 with the EdgeMetricsOut JSON body on a cache hit.
    Returns 200 with null body and X-Edge-Cache: cold on a cache miss.
    Returns 404 if the underlying score-history inputs do not exist.
    """
    from fastapi.responses import JSONResponse
    from ..config import settings

    _VALID_EDGE_SOURCES = {"signal_engine", "wfo"}
    if source not in _VALID_EDGE_SOURCES:
        raise HTTPException(400, f"source must be one of {sorted(_VALID_EDGE_SOURCES)}")
    if variant is not None:
        try:
            variant = resolve_signal_mode(variant).name
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    cost_bps_value = float(settings.EDGE_COST_BPS_PER_SIDE if cost_bps is None else cost_bps)
    payload, state = _edge_cache_payload(
        db=db,
        symbol=symbol.upper(),
        horizon=horizon,
        source=source,
        variant=variant,
        cost_bps=cost_bps_value,
    )
    if state == "missing":
        raise HTTPException(
            status_code=404,
            detail=f"No edge inputs for symbol={symbol!r} horizon={horizon!r} source={source!r}",
        )
    if payload is None:
        return JSONResponse(content=None, headers={"X-Edge-Cache": "cold"})
    return JSONResponse(content=payload, headers={"X-Edge-Cache": "hit"})


@router.post(
    "/edge/warm",
    dependencies=[Depends(require_admin), Depends(rate_limit_trigger)],
)
def warm_edge_cache(
    symbols: Optional[list[str]] = None,
    horizons: Optional[list[str]] = None,
    sources: Optional[list[str]] = None,
    variants: Optional[list[str]] = None,
    cost_bps: float | None = Query(default=None, ge=0.0, le=500.0),
    db: Session = Depends(get_db),
) -> dict:
    """Pre-populate the Edge cache for a set of (symbols × horizons × sources).

    Called after the daily score refresh. Body params are optional — defaults
    to all symbols × all horizons × both sources.
    """
    from ..config import settings

    return _warm_edge_cache_entries(
        db=db,
        symbols=symbols,
        horizons=horizons,
        sources=sources,
        variants=variants,
        cost_bps=float(settings.EDGE_COST_BPS_PER_SIDE if cost_bps is None else cost_bps),
    )
