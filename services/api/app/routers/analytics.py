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
from typing import Any, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

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
    LeaderboardRow,
    LeaderboardOut,
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


@router.get("/factors/leaderboard", response_model=list[FactorLeaderboardRow])
def get_factor_leaderboard(
    lookback_days: int = Query(default=0, ge=0),
    forward_horizon: int = Query(default=1, ge=1, le=21),
    return_method: str = Query(default="close_to_close"),
    db: Session = Depends(get_db),
):
    """Cross-stock leaderboard: rank stocks by macro-factor statistical significance.

    For each tracked symbol computes Spearman IC vs all 6 macro factors and
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
    """Compute factor-relevance matrix for one stock vs all 6 macro factors.

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
        ic_cv=0.0, sharpe_cv=0.0, n_variants=6,
    )


@router.get("/factors/{symbol}/evaluate", response_model=list)
def evaluate_factor_signals(
    symbol: str,
    return_method: str = Query(default="open_to_open"),
    lookback_days: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Phase 1: evaluate all 6 pre-registered factor signals for one stock.

    Returns one FactorSignalEvalOut per registered signal.
    Sector channel gate removed — all 6 signals evaluated for every stock.
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

    # Load all 6 macro factors and align
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
                costs={"spread_bps": 0.0, "commission_bps": 33.0},
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
            ))
            continue

        ic_vals = report.ic_curve.ic_values
        ic_h1 = _safe_float(ic_vals[0]) if ic_vals else 0.0
        ic_h5 = _safe_float(ic_vals[4]) if len(ic_vals) > 4 else 0.0

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
        ))

    return out


# ---------------------------------------------------------------------------
# Predictive ability (bucket × forward-horizon matrix)
# ---------------------------------------------------------------------------

_DEFAULT_FWD_HORIZONS = [1, 2, 3, 4, 5, 6, 10, 15, 21, 30, 60, 120, 200]
_VALID_SOURCES = {"engine_legacy", "engine_expanded", "wfo"}
_VALID_CATEGORIES = ["tendance", "momentum", "oscillation", "volume"]


def _load_score_history(
    db: Session, *, symbol: str, source: str, horizon: str,
) -> dict[str, pd.Series]:
    rows = (
        db.query(models.SignalScoreHistory)
        .filter_by(symbol=symbol, source=source, horizon=horizon)
        .order_by(models.SignalScoreHistory.date.asc())
        .all()
    )
    by_cat: dict[str, dict[pd.Timestamp, float]] = {}
    for r in rows:
        by_cat.setdefault(r.category, {})[pd.Timestamp(r.date)] = r.score_pct
    out: dict[str, pd.Series] = {}
    for cat, mapping in by_cat.items():
        idx = pd.DatetimeIndex(sorted(mapping.keys()))
        vals = [mapping[t] for t in idx]
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
    if source == "wfo":
        row = (
            db.query(models.WfoGlobalSignal)
            .filter_by(symbol=symbol, horizon=horizon)
            .order_by(models.WfoGlobalSignal.updated_at.desc())
            .first()
        )
        if row is None or row.raw_score_pct is None:
            return None
        return float(row.raw_score_pct)
    else:
        row = (
            db.query(models.SignalEngineGlobalResult)
            .filter_by(symbol=symbol, horizon=horizon)
            .order_by(models.SignalEngineGlobalResult.updated_at.desc())
            .first()
        )
        if row is None:
            return None
        score = (
            row.aggregate_score_pct
            if source == "engine_legacy"
            else row.expanded_aggregate_score_pct
        )
        return float(score) if score is not None else None


def _load_pricing_data(db: Session, symbol: str) -> pd.DataFrame:
    from ..market_data_loader import load_ohlcv_for_symbol

    df = load_ohlcv_for_symbol(db, symbol)
    # Ensure index is DatetimeIndex
    df.index = pd.DatetimeIndex(df.index)
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
    categories: Optional[str] = Query(None, description="CSV subset of categories"),
    fwd_horizons: Optional[str] = Query(None, description="CSV of forward horizons"),
    lookback_days: int = Query(0, ge=0),
    return_calc_method: str = Query("close_to_close"),
    db: Session = Depends(get_db),
) -> PredictiveAbilityMatrix:
    """Return the bucket × forward-horizon matrix for one (symbol, source, horizon)."""

    if source not in _VALID_SOURCES:
        raise HTTPException(400, f"source must be one of {sorted(_VALID_SOURCES)}")
    if horizon not in {"short", "medium", "long"}:
        raise HTTPException(400, "horizon must be short|medium|long")

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

    series_by_cat = _load_score_history(db, symbol=symbol, source=source, horizon=horizon)
    if not series_by_cat:
        return PredictiveAbilityMatrix(
            symbol=symbol, source=source, horizon=horizon,
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
            symbol=symbol, source=source, horizon=horizon,
            categories=cats, n_obs=0,
            buckets=list(BUCKET_NAMES), fwd_horizons=fhs, cells=[],
            available=False,
            message="Selected categories have no data for this (source, horizon).",
        )

    score_clean = score.dropna()
    current_score = _load_current_live_score(db, symbol=symbol, source=source, horizon=horizon)
    current_bucket = _bucket_for(current_score) if current_score is not None else None

    try:
        prices = _load_pricing_data(db, symbol)
    except Exception as exc:
        raise HTTPException(404, f"No price data for {symbol}: {exc}")

    cells_raw = bucketed_forward_returns(score, prices, fhs, return_calc_method=return_calc_method)
    cells = [PredictiveAbilityCell(**c) for c in cells_raw]
    return PredictiveAbilityMatrix(
        symbol=symbol, source=source, horizon=horizon,
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
    fwd_h: int = Query(5, ge=1, le=400),
    lookback_days: int = Query(0, ge=0),
    return_calc_method: str = Query("close_to_close"),
    db: Session = Depends(get_db),
) -> CategoryCombinationsOut:
    """For each non-empty subset of the 4 categories, evaluate the bucket matrix
    at one forward horizon and return a ranked list."""
    from itertools import combinations as _comb

    if source not in _VALID_SOURCES:
        raise HTTPException(400, f"source must be one of {sorted(_VALID_SOURCES)}")
    series_by_cat = _load_score_history(db, symbol=symbol, source=source, horizon=horizon)
    if not series_by_cat:
        return CategoryCombinationsOut(symbol=symbol, source=source, horizon=horizon,
                                       fwd_h=fwd_h, rows=[])
    sample_idx = next((s.index for s in series_by_cat.values() if len(s) > 0), None)
    if sample_idx is not None:
        cutoff = _compute_cutoff(sample_idx, lookback_days)
        if cutoff is not None:
            series_by_cat = {cat: s[s.index >= cutoff] for cat, s in series_by_cat.items()}
    try:
        prices = _load_pricing_data(db, symbol)
    except Exception:
        return CategoryCombinationsOut(symbol=symbol, source=source, horizon=horizon,
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
        symbol=symbol, source=source, horizon=horizon, fwd_h=fwd_h, rows=rows,
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
        .filter(models.SignalScoreHistory.horizon == engine_horizon)
        .distinct()
        .all()
    )

    price_cache: dict[str, pd.DataFrame] = {}
    rows: list[LeaderboardRow] = []

    for sym, src in pairs:
        if src not in _VALID_SOURCES:
            continue
        try:
            series_by_cat = _load_score_history(
                db, symbol=sym, source=src, horizon=engine_horizon,
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
            source=src,
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


# ---------------------------------------------------------------------------
# Predictive-history population (RQ batch)
# ---------------------------------------------------------------------------

@router.post("/predictive-history/trigger", response_model=PredictiveHistoryTriggerOut)
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
        job_timeout=1800,
    )
    row.rq_job_id = str(job.id)
    db.commit()
    _invalidate_leaderboard_cache()
    return PredictiveHistoryTriggerOut(triggered=1, job_ids=[str(job.id)])


@router.post("/predictive-history/trigger-all", response_model=PredictiveHistoryTriggerOut)
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
            job_timeout=1800,
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
    symbol: str,
    horizon: str,
    cost_bps: float,
    methodology_version: str,
    score_revision_hash: str,
) -> str:
    return (
        f"edge:v{methodology_version}:{source}:{symbol}:{horizon}"
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


def _edge_revision_context(
    *,
    db: "Session",
    symbol: str,
    horizon: str,
    source: str,
) -> tuple[str, str] | None:
    from core.quant_core.horizons import canonical_horizon
    from sqlalchemy import func as _func

    try:
        canonical_h = canonical_horizon(horizon, allow_legacy=True)
    except ValueError:
        return None

    symbol_upper = symbol.upper()
    db_horizons = _edge_db_horizons(canonical_h)

    if source == "wfo":
        summary = (
            db.query(models.WfoSignalSummary)
            .filter(
                models.WfoSignalSummary.symbol == symbol_upper,
                models.WfoSignalSummary.horizon.in_(db_horizons),
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
                models.SignalScoreHistory.source == "wfo",
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
        return canonical_h, rev_hash

    if source == "signal_engine":
        global_row = (
            db.query(models.SignalEngineGlobalResult)
            .filter(
                models.SignalEngineGlobalResult.symbol == symbol_upper,
                models.SignalEngineGlobalResult.horizon.in_(db_horizons),
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
                models.SignalScoreHistory.source.in_(("engine_expanded", "engine_legacy")),
                models.SignalScoreHistory.horizon.in_(db_horizons),
            )
            .scalar()
            or 0
        )
        if global_row is None and row_count <= 0:
            return None
        rev_hash = _score_revision_hash(
            data_as_of=str(getattr(global_row, "data_as_of", "") or ""),
            row_count=row_count,
            folds_hash="none",
        )
        return canonical_h, rev_hash

    return None


def _edge_cache_payload(
    *,
    db: "Session",
    symbol: str,
    horizon: str,
    source: str,
    cost_bps: float,
) -> tuple[dict[str, Any] | None, str]:
    import json
    from core.quant_core.research.edge import METHODOLOGY_VERSION

    ctx = _edge_revision_context(db=db, symbol=symbol, horizon=horizon, source=source)
    if ctx is None:
        return None, "missing"

    canonical_h, rev_hash = ctx
    cache_key = _edge_cache_key(
        source=source,
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
    cost_bps: float,
    out_json: str,
) -> bool:
    from core.quant_core.research.edge import METHODOLOGY_VERSION

    ctx = _edge_revision_context(db=db, symbol=symbol, horizon=horizon, source=source)
    if ctx is None:
        return False
    canonical_h, rev_hash = ctx
    redis = _edge_redis()
    if redis is None:
        return False
    cache_key = _edge_cache_key(
        source=source,
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
    cost_bps: float,
    db: "Session",
) -> "EdgeMetrics | None":
    """Load all required data from DB and compute EdgeMetrics. Returns None on missing data."""
    from core.quant_core.horizons import HORIZON_SPECS, canonical_horizon
    from core.quant_core.research.edge import build_edge_payload
    from core.quant_core.research.oos_index import oos_sample_for
    from core.quant_core.research.score_history import aggregate_subset, _bucket_for

    # Resolve legacy horizon aliases (short/medium/long → weekly/monthly/quarterly).
    try:
        canonical_h = canonical_horizon(horizon, allow_legacy=True)
    except ValueError:
        return None

    spec = HORIZON_SPECS[canonical_h]

    # --- Determine DB source strings ---
    # API source: 'signal_engine' | 'wfo'
    # DB source column: 'engine_legacy' | 'engine_expanded' | 'wfo'
    if source == "signal_engine":
        db_sources = ("engine_expanded", "engine_legacy")
    elif source == "wfo":
        db_sources = ("wfo",)
    else:
        return None

    # --- Load score history rows for all categories ---
    # Try candidate horizons: canonical first, then legacy alias.
    db_horizons = _edge_db_horizons(canonical_h)

    series_by_cat: dict[str, pd.Series] = {}
    used_horizon_key = None
    for db_src in db_sources:
        for db_h in db_horizons:
            series_by_cat = _load_score_history(db, symbol=symbol, source=db_src, horizon=db_h)
            if series_by_cat:
                used_horizon_key = db_h
                break
        if series_by_cat:
            break

    if not series_by_cat:
        return None

    score = aggregate_subset(series_by_cat, list(series_by_cat.keys()))
    if score is None or score.dropna().empty:
        return None

    # --- Determine today's bucket ---
    live_source = "wfo" if source == "wfo" else (
        "engine_expanded" if "engine_expanded" in db_sources else "engine_legacy"
    )
    live_score_raw = _load_current_live_score(
        db, symbol=symbol, source=live_source, horizon=used_horizon_key or canonical_h,
    )
    if live_score_raw is None:
        # Fall back to the latest bar in score history.
        live_score_raw = float(score.dropna().iloc[-1])
    today_bucket = _bucket_for(live_score_raw)

    # --- Load prices ---
    try:
        prices = _load_pricing_data(db, symbol)
    except Exception:
        return None

    # --- OOS loaders ---
    ohlcv_idx = pd.DatetimeIndex(prices.index)

    def wfo_loader(sym: str, h: str) -> dict:
        for db_h in db_horizons:
            summary = (
                db.query(models.WfoSignalSummary)
                .filter(
                    models.WfoSignalSummary.symbol == sym,
                    models.WfoSignalSummary.horizon == db_h,
                    models.WfoSignalSummary.status == "succeeded",
                    models.WfoSignalSummary.folds_json.isnot(None),
                )
                .order_by(models.WfoSignalSummary.updated_at.desc())
                .first()
            )
            if summary is not None and summary.folds_json:
                return {"folds_json": summary.folds_json}
        return {}

    def score_history_loader(sym: str, h: str) -> list[dict]:
        out = []
        for db_src in db_sources:
            for db_h in db_horizons:
                rows = (
                    db.query(models.SignalScoreHistory)
                    .filter_by(symbol=sym, source=db_src, horizon=db_h)
                    .order_by(models.SignalScoreHistory.date.asc())
                    .all()
                )
                if rows:
                    out.extend({"date": r.date, "is_oos": bool(getattr(r, "is_oos", False))} for r in rows)
                    return out
        return out

    oos_sample = oos_sample_for(
        symbol=symbol,
        horizon=canonical_h,
        source=source,
        wfo_loader=wfo_loader if source == "wfo" else None,
        score_history_loader=score_history_loader if source == "signal_engine" else None,
        ohlcv_index_loader=lambda sym: ohlcv_idx,
        holdout_bars=spec.signal_engine_holdout_bars,
    )

    return build_edge_payload(
        symbol=symbol,
        horizon=canonical_h,
        source=source,
        score_series=score,
        prices=prices,
        oos_sample=oos_sample,
        today_bucket=today_bucket,
        fwd_horizon_bars=spec.reference_forward_days,
        cost_bps_per_side=cost_bps,
    )


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
        bucket=m.bucket,
        direction=m.direction,
        n=m.n,
        window_start=m.window_start.date().isoformat() if m.window_start else None,
        window_end=m.window_end.date().isoformat() if m.window_end else None,
        expected_return_gross=m.expected_return_gross,
        expected_return_net=m.expected_return_net,
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
        proven_edge_gross=m.proven_edge_gross,
        proven_edge_net=m.proven_edge_net,
        gates=EdgeGatesOut(
            mc_gross=m.gates.mc_gross,
            mc_net=m.gates.mc_net,
            wilson=m.gates.wilson,
            n=m.gates.n,
        ),
        cost_bps_per_side=m.cost_bps_per_side,
        methodology_version=m.methodology_version,
    )


def _warm_edge_cache_entries(
    *,
    db: "Session",
    symbols: list[str] | None,
    horizons: list[str] | None,
    sources: list[str] | None,
    cost_bps: float,
) -> dict[str, int]:
    from core.quant_core.horizons import VALID_HORIZONS, canonical_horizon

    if not horizons:
        horizons = list(VALID_HORIZONS)
    if not sources:
        sources = ["signal_engine", "wfo"]
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
                try:
                    metrics = _build_edge_metrics_from_db(
                        symbol=sym,
                        horizon=canonical_h,
                        source=src,
                        cost_bps=cost_bps,
                        db=db,
                    )
                    if metrics is None:
                        continue
                    out_json = _edge_metrics_to_out(metrics).model_dump_json()
                    if _store_edge_cache_payload(
                        db=db,
                        symbol=sym,
                        horizon=canonical_h,
                        source=src,
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
    cost_bps_value = float(settings.EDGE_COST_BPS_PER_SIDE if cost_bps is None else cost_bps)
    payload, state = _edge_cache_payload(
        db=db,
        symbol=symbol.upper(),
        horizon=horizon,
        source=source,
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


@router.post("/edge/warm")
def warm_edge_cache(
    symbols: Optional[list[str]] = None,
    horizons: Optional[list[str]] = None,
    sources: Optional[list[str]] = None,
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
        cost_bps=float(settings.EDGE_COST_BPS_PER_SIDE if cost_bps is None else cost_bps),
    )
