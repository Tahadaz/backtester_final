"""Strategy signals API — signal generation engine endpoints."""

from __future__ import annotations

import logging
import time
from dataclasses import asdict
from typing import Any

import numpy as np

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..market_data_loader import load_close_for_symbol, load_ohlcv_for_symbol
from ..schemas.strategy_signals import (
    BatchScoresRequest,
    FamilyEnsembleRequest,
    RegimeConsensusRequest,
    SignalZoneChartRequest,
    SmaEnsembleRequest,
    VariantBacktestRequest,
    VariantDetailRequest,
)

from core.quant_core.signal_engine.ensemble import (
    run_family_ensemble_full,
    compute_family_score_timeseries,
    _score_to_label,
)
from core.quant_core.signal_engine.domain import (
    CATEGORY_FAMILIES,
    FAMILY_SIGNAL_TYPE,
    EnsemblePipelineDetail,
    HORIZON_PARAMS,
    label_to_signal_value,
    signal_type_label,
)
from core.quant_core.signal_engine.variant_detail import (
    compute_variant_detail,
    compute_variant_trade_register,
    _compute_indicator,
)
from core.quant_core.signal_engine.rsi_semantics import latest_rsi_variant_signal
from core.quant_core.signal_engine.oos_eval import compute_signal_array
from core.quant_core.signal_engine.regime import validate_regime_oos, compute_regime_consensus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/strategy", tags=["strategy-signals"])

# ---------------------------------------------------------------------------
# In-process TTL cache — keyed by (family, symbol, horizon, timeframe, cost_bps)
# ---------------------------------------------------------------------------

_CACHE: dict[tuple, tuple[float, EnsemblePipelineDetail]] = {}
_CACHE_TTL = 300.0  # 5 minutes

_BACKTEST_CACHE: dict[tuple, tuple[float, dict]] = {}
_BACKTEST_CACHE_TTL = 600.0
_BACKTEST_CACHE_VERSION = 3


def _truncate_for_horizon(ohlcv, horizon: str):
    """Keep only the last N years of OHLCV data for the given horizon."""
    max_bars = HORIZON_PARAMS[horizon]["max_years"] * 252
    if len(ohlcv) > max_bars:
        return ohlcv.iloc[-max_bars:]
    return ohlcv


def _clean_ohlcv(ohlcv):
    """Drop rows with NaN in any OHLCV column before signal computation.

    Suspended trading days, holidays with partial data, and ingestion gaps
    produce NaN values that poison cumulative indicators (e.g. OBV via cumsum).
    The data page still sees the raw DataFrame for calendar flagging.
    """
    cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in ohlcv.columns]
    if cols:
        ohlcv = ohlcv.dropna(subset=cols)
    return ohlcv


def _variant_label(variant) -> str:
    """Generic human-readable label for any variant."""
    p = variant.params
    arch = variant.archetype
    if arch == "price_vs_sma":
        return f"SMA-{p.get('window', '?')}"
    if arch == "sma_cross":
        return f"SMA({p.get('fast')},{p.get('slow')})"
    if arch == "slope_confirmed":
        return f"SMA-{p.get('window')} Slope"
    if arch == "rsi_level":
        return f"RSI-{p.get('period', '?')}"
    if arch == "macd_cross":
        return f"MACD({p.get('fast')},{p.get('slow')},{p.get('signal')})"
    if arch == "obv_trend":
        return f"OBV-EMA-{p.get('ema_period', '?')}"
    return variant.variant_id[:12]


def _methodology_context_payload(signal) -> dict[str, Any]:
    return {
        "methodology_mode": signal.methodology_mode,
        "available_bars": signal.available_bars,
        "nominal_window": asdict(signal.nominal_window),
        "effective_window": asdict(signal.effective_window),
        "warning_message": signal.warning_message,
        "is_provisional": signal.is_provisional,
    }


def _fallback_variants_by_id(detail: EnsemblePipelineDetail) -> dict[str, dict[str, Any]]:
    return {entry["variant_id"]: entry for entry in detail.signal.fallback_variants}


def _get_or_compute(
    db: Session, family: str, symbol: str, horizon: str, timeframe: str,
    cost_bps: float, cooldown_bars: int = 0,
) -> EnsemblePipelineDetail:
    """Return cached detail or compute and cache it."""
    key = (family, symbol, horizon, timeframe, cost_bps, cooldown_bars)
    now = time.monotonic()
    cached = _CACHE.get(key)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return cached[1]

    try:
        ohlcv = load_ohlcv_for_symbol(db, symbol, timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    ohlcv = _truncate_for_horizon(ohlcv, horizon)
    ohlcv = _clean_ohlcv(ohlcv)
    close = ohlcv["Close"].values.astype("float64")
    volume = ohlcv["Volume"].values.astype("float64") if "Volume" in ohlcv.columns else None

    # Guard: volume-dependent families need real volume data
    _VOLUME_DEPENDENT = {"obv"}
    if family in _VOLUME_DEPENDENT:
        if volume is None:
            logger.warning("OBV requested for %s but Volume column missing from OHLCV", symbol)
            raise HTTPException(
                status_code=422,
                detail=f"Volume data missing for {symbol} — OBV cannot be computed. "
                       f"Available columns: {list(ohlcv.columns)}",
            )
        finite_volume = volume[np.isfinite(volume)]
        nonzero_ratio = (finite_volume != 0).mean() if len(finite_volume) > 0 else 0.0
        if nonzero_ratio < 0.01:
            logger.warning(
                "OBV requested for %s but Volume is %.1f%% zeros/NaN",
                symbol, (1 - nonzero_ratio) * 100,
            )
            raise HTTPException(
                status_code=422,
                detail=f"Volume data for {symbol} is {(1 - nonzero_ratio)*100:.0f}% zeros/NaN — "
                       f"OBV requires real volume data to produce meaningful signals.",
            )

    detail = run_family_ensemble_full(
        family, close, volume=volume, symbol=symbol, horizon=horizon,
        timeframe=timeframe, cost_bps=cost_bps, cooldown_bars=cooldown_bars,
    )

    # Override as_of with actual last data date (not server timestamp)
    last_date = str(ohlcv.index[-1])[:10]
    detail.signal.as_of = last_date
    detail.signal.latest_close = float(close[-1]) if len(close) else None

    _CACHE[key] = (now, detail)
    return detail


@router.post("/signal/sma-ensemble")
def sma_ensemble(body: SmaEnsembleRequest, db: Session = Depends(get_db)):
    """Run the full SMA signal engine pipeline (Layers A->G)."""
    detail = _get_or_compute(db, "sma", body.symbol, body.horizon, body.timeframe, body.cost_bps, body.cooldown_bars)
    return asdict(detail.signal)


@router.post("/signal/family-ensemble")
def family_ensemble(body: FamilyEnsembleRequest, db: Session = Depends(get_db)):
    """Run the full signal engine pipeline for any family (Layers A->G)."""
    detail = _get_or_compute(db, body.family, body.symbol, body.horizon, body.timeframe, body.cost_bps, body.cooldown_bars)
    return asdict(detail.signal)


@router.post("/signal/variant-detail")
def variant_detail(body: VariantDetailRequest, db: Session = Depends(get_db)):
    """Return full detail for a single variant from the cached pipeline run."""
    detail = _get_or_compute(db, _family_for_variant(body.variant_id, db, body), body.symbol, body.horizon, body.timeframe, body.cost_bps, body.cooldown_bars)

    # Find the requested variant
    target_summary = None
    for s in detail.all_summaries:
        if s.variant.variant_id == body.variant_id:
            target_summary = s
            break

    if target_summary is None:
        raise HTTPException(
            status_code=404,
            detail=f"Variant {body.variant_id!r} not found in {body.horizon} universe",
        )

    v = target_summary.variant
    windows = detail.oos_windows.get(body.variant_id, [])
    fallback_lookup = _fallback_variants_by_id(detail)
    methodology_context = _methodology_context_payload(detail.signal)
    try:
        ohlcv = load_ohlcv_for_symbol(db, body.symbol, body.timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    ohlcv = _truncate_for_horizon(ohlcv, body.horizon)
    ohlcv = _clean_ohlcv(ohlcv)
    close = ohlcv["Close"].values.astype("float64")
    volume = ohlcv["Volume"].values.astype("float64") if "Volume" in ohlcv.columns else None
    variant_signal_labels: dict[str, str] = {}
    variant_realized_totals: dict[str, float] = {}

    if detail.signal.family == "rsi":
        for summary in detail.all_summaries:
            _signal_val, signal_label = latest_rsi_variant_signal(
                close,
                summary.variant,
                cooldown_bars=body.cooldown_bars,
            )
            variant_signal_labels[summary.variant.variant_id] = signal_label

    for summary in detail.all_summaries:
        trades, _window_cash_starts = compute_variant_trade_register(
            ohlcv,
            close,
            summary.variant,
            detail.oos_windows.get(summary.variant.variant_id, []),
            volume=volume,
            cost_bps=body.cost_bps,
            cooldown_bars=body.cooldown_bars,
        )
        variant_realized_totals[summary.variant.variant_id] = round(
            sum(float(row.get("pnl_realise", 0.0)) for row in trades),
            2,
        )

    # Determine signal for this variant — use current_signal_labels for all,
    # override with representative-quality signal if available
    target_signal_label = (
        variant_signal_labels.get(body.variant_id)
        or detail.current_signal_labels.get(body.variant_id, "NEUTRE")
    )
    target_signal = label_to_signal_value(target_signal_label)
    target_selection_status = fallback_lookup.get(body.variant_id, {}).get("selection_status", "")
    for rep in detail.signal.representatives:
        if rep["variant_id"] == body.variant_id:
            if not variant_signal_labels:
                target_signal = rep["signal"]
                target_signal_label = rep["signal_label"]
            target_selection_status = rep.get("selection_status", "selected")
            break
    if body.variant_id in detail.representative_ids and not target_selection_status:
        target_selection_status = "selected"
    elif body.variant_id in detail.survivor_ids and not target_selection_status:
        target_selection_status = "redundancy_filtered"

    # Compute competitive threshold (the cutoff reliability score)
    viable_summaries = [s for s in detail.all_summaries if s.is_viable]
    competitive_threshold = 0.0
    if viable_summaries:
        above_floor = sorted(
            [s for s in viable_summaries if s.reliability_score >= 0.25],
            key=lambda s: s.reliability_score, reverse=True,
        )
        if above_floor:
            n_keep = max(1, int(len(above_floor) * 0.60 + 0.5))
            competitive_threshold = above_floor[min(n_keep - 1, len(above_floor) - 1)].reliability_score

    # Build description lookup for correlation display
    desc_lookup: dict[str, str] = {}
    for s in detail.all_summaries:
        desc_lookup[s.variant.variant_id] = _variant_label(s.variant)

    # Build all_variants list with elimination reasons + signal + correlation
    all_variants: list[dict[str, Any]] = []
    for s in detail.all_summaries:
        vid = s.variant.variant_id
        is_survivor = vid in detail.survivor_ids
        is_rep = vid in detail.representative_ids
        fallback_entry = fallback_lookup.get(vid)
        selection_status = fallback_entry.get("selection_status") if fallback_entry else ""

        if is_rep:
            elim = "selected"
        elif is_survivor:
            elim = "redundancy_filtered"
        elif s.is_viable:
            elim = "percentile_cutoff"
        else:
            elim = "not_viable"

        # Signal value for this variant (type-specific label → numeric)
        sig_label = variant_signal_labels.get(vid) or detail.current_signal_labels.get(vid, "NEUTRE")
        sig_value = label_to_signal_value(sig_label)

        # Correlation info for redundancy-filtered variants
        correlated_with: str | None = None
        correlated_with_label: str | None = None
        correlation: float | None = None
        if elim == "redundancy_filtered" and vid in detail.redundancy_info:
            cw_id, cw_val = detail.redundancy_info[vid]
            correlated_with = cw_id
            correlated_with_label = desc_lookup.get(cw_id, cw_id)
            correlation = cw_val

        # Threshold info for eliminated variants
        threshold_score: float | None = None
        viability_detail: str | None = None
        if elim == "percentile_cutoff":
            threshold_score = round(competitive_threshold, 4)
        elif elim == "not_viable":
            viability_detail = (
                f"{round(s.fraction_positive_windows * 100, 1)}% fenetres positives (seuil 40%)"
            )

        all_variants.append({
            "variant_id": vid,
            "archetype": s.variant.archetype,
            "params": s.variant.params,
            "description": s.variant.description,
            "reliability_score": round(s.reliability_score, 4),
            "is_viable": s.is_viable,
            "is_survivor": is_survivor,
            "is_representative": is_rep,
            "elimination_reason": elim,
            "mean_sharpe": round(s.mean_sharpe, 4),
            "mean_max_drawdown": round(s.mean_max_drawdown, 4),
            "fraction_positive_windows": round(s.fraction_positive_windows, 4),
            "cagr": round(s.cagr, 4),
            "total_pnl_100k": round(s.total_pnl, 2),
            "total_pnl_realise_1u": variant_realized_totals.get(vid, 0.0),
            "total_pnl": round(s.total_pnl, 2),
            "signal_value": sig_value,
            "signal_label": sig_label,
            "correlated_with": correlated_with,
            "correlated_with_label": correlated_with_label,
            "correlation": correlation,
            "threshold_score": threshold_score,
            "viability_detail": viability_detail,
            "selection_status": selection_status or elim,
        })

    # Sort by reliability descending
    all_variants.sort(key=lambda x: x["reliability_score"], reverse=True)

    # Enrich OOS windows with date strings
    oos_windows_dicts = [asdict(w) for w in windows]
    try:
        if ohlcv is None:
            ohlcv = load_ohlcv_for_symbol(db, body.symbol, body.timeframe)
            ohlcv = _truncate_for_horizon(ohlcv, body.horizon)
            ohlcv = _clean_ohlcv(ohlcv)
        idx = ohlcv.index
        for wd in oos_windows_dicts:
            ts = wd.get("test_start", 0)
            te = wd.get("test_end", 0)
            if ts < len(idx):
                wd["test_start_date"] = str(idx[ts])[:10]
            if te < len(idx):
                wd["test_end_date"] = str(idx[min(te, len(idx) - 1)])[:10]
    except Exception:
        pass  # dates are optional enrichment

    # Build correlation matrix with labels for frontend heatmap
    corr_matrix_labeled: dict[str, Any] = {}
    if detail.correlation_matrix:
        labels: list[str] = []
        ids: list[str] = []
        for vid in detail.correlation_matrix:
            ids.append(vid)
            labels.append(desc_lookup.get(vid, vid))
        z_matrix: list[list[float]] = []
        for vid_row in ids:
            row_data = detail.correlation_matrix[vid_row]
            z_matrix.append([row_data.get(vid_col, 0.0) for vid_col in ids])
        rep_flags = [vid in detail.representative_ids for vid in ids]
        corr_matrix_labeled = {
            "labels": labels,
            "ids": ids,
            "z": z_matrix,
            "is_representative": rep_flags,
        }

    return {
        "variant_id": body.variant_id,
        "archetype": v.archetype,
        "params": v.params,
        "description": v.description,
        "signal": target_signal,
        "signal_label": target_signal_label,
        "selection_status": target_selection_status or "not_viable",
        "robustness": {
            "mean_sharpe": round(target_summary.mean_sharpe, 4),
            "std_sharpe": round(target_summary.std_sharpe, 4),
            "median_sharpe": round(target_summary.median_sharpe, 4),
            "fraction_positive_windows": round(target_summary.fraction_positive_windows, 4),
            "mean_max_drawdown": round(target_summary.mean_max_drawdown, 4),
            "reliability_score": round(target_summary.reliability_score, 4),
            "is_viable": target_summary.is_viable,
            "sharpe_score": round(target_summary.sharpe_score, 4),
            "stability_score": round(target_summary.stability_score, 4),
            "consistency_score": round(target_summary.consistency_score, 4),
            "drawdown_score": round(target_summary.drawdown_score, 4),
            "total_pnl_100k": round(target_summary.total_pnl, 2),
            "total_pnl_realise_1u": variant_realized_totals.get(body.variant_id, 0.0),
        },
        "oos_windows": oos_windows_dicts,
        "all_variants": all_variants,
        "fallback_variants": detail.signal.fallback_variants,
        "funnel": {
            "tested": detail.signal.tested_count,
            "viable": detail.signal.viable_count,
            "competitive": detail.signal.competitive_count,
            "representative": detail.signal.representative_count,
        },
        "correlation_matrix": corr_matrix_labeled,
        "methodology_context": methodology_context,
    }


def _family_for_variant(variant_id: str, db: Session, body) -> str:
    """Try each family cache to find which one contains the variant."""
    for family in ("sma", "rsi", "macd", "obv"):
        key = (family, body.symbol, body.horizon, body.timeframe, body.cost_bps, body.cooldown_bars)
        cached = _CACHE.get(key)
        if cached:
            _, detail = cached
            for s in detail.all_summaries:
                if s.variant.variant_id == variant_id:
                    return family
            if variant_id in detail.fallback_variant_ids:
                return family
    # Fallback: compute all families until we find it
    for family in ("sma", "rsi", "macd", "obv"):
        detail = _get_or_compute(db, family, body.symbol, body.horizon, body.timeframe, body.cost_bps, body.cooldown_bars)
        for s in detail.all_summaries:
            if s.variant.variant_id == variant_id:
                return family
        if variant_id in detail.fallback_variant_ids:
            return family
    return "sma"  # fallback


@router.post("/signal/variant-backtest")
def variant_backtest(body: VariantBacktestRequest, db: Session = Depends(get_db)):
    """Return OOS plots, trade ledger, and performance for a single variant."""
    family = _family_for_variant(body.variant_id, db, body)
    detail = _get_or_compute(db, family, body.symbol, body.horizon, body.timeframe, body.cost_bps, body.cooldown_bars)

    # Find variant
    target = None
    for s in detail.all_summaries:
        if s.variant.variant_id == body.variant_id:
            target = s
            break
    if target is None:
        raise HTTPException(status_code=404, detail=f"Variant {body.variant_id!r} not found")

    # Check cache
    cache_key = (
        _BACKTEST_CACHE_VERSION,
        body.symbol,
        body.variant_id,
        body.horizon,
        body.cost_bps,
        body.cooldown_bars,
    )
    now = time.monotonic()
    cached = _BACKTEST_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _BACKTEST_CACHE_TTL:
        return cached[1]

    # Load OHLCV (with timestamps) and close array
    try:
        ohlcv = load_ohlcv_for_symbol(db, body.symbol, body.timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    ohlcv = _truncate_for_horizon(ohlcv, body.horizon)
    ohlcv = _clean_ohlcv(ohlcv)
    close = ohlcv["Close"].values.astype("float64")
    volume = ohlcv["Volume"].values.astype("float64") if "Volume" in ohlcv.columns else None
    oos_windows = detail.oos_windows.get(body.variant_id, [])

    result = compute_variant_detail(
        ohlcv, close, target.variant, oos_windows,
        volume=volume, cost_bps=body.cost_bps, cooldown_bars=body.cooldown_bars,
    )

    # Build oos_window_dates from OHLCV index
    idx = ohlcv.index
    oos_window_dates: list[dict[str, Any]] = []
    for w in oos_windows:
        wd: dict[str, Any] = {
            "window_index": w.window_index,
            "is_valid": w.is_valid,
        }
        if w.test_start < len(idx):
            wd["test_start_date"] = str(idx[w.test_start])[:10]
        if w.test_end < len(idx):
            wd["test_end_date"] = str(idx[min(w.test_end, len(idx) - 1)])[:10]
        oos_window_dates.append(wd)

    response: dict[str, Any] = {
        "variant_id": body.variant_id,
        "description": target.variant.description,
        "metrics": result["metrics"],
        "trade_performance": result["trade_performance"],
        "trade_ledger": result["trade_ledger"],
        "plots": result["plots"],
        "per_window": result.get("per_window", []),
        "oos_window_dates": oos_window_dates,
        "methodology_context": _methodology_context_payload(detail.signal),
        "warning_message": detail.signal.warning_message,
    }

    if detail.signal.methodology_mode == "live_signal_only":
        response["metrics"] = result["metrics"] or {"note": "Signal live uniquement"}
        response["trade_performance"] = []
        response["trade_ledger"] = []
        response["plots"] = {}
        response["per_window"] = []
        response["oos_window_dates"] = []

    _BACKTEST_CACHE[cache_key] = (now, response)
    return response


@router.post("/signal/batch-scores")
def batch_scores(body: BatchScoresRequest, db: Session = Depends(get_db)):
    """Return aggregate signal scores across all 4 families for multiple symbols.

    Response includes per-family scores, category grouping (Tendance/Oscillation/Volume),
    and an equal-weight aggregate (DeMiguel et al. 2009).
    """
    results: list[dict[str, Any]] = []
    for symbol in body.symbols:
        family_scores: dict[str, float] = {}
        family_labels: dict[str, str] = {}
        for family in ("sma", "rsi", "macd", "obv"):
            try:
                detail = _get_or_compute(
                    db, family, symbol, body.horizon, body.timeframe,
                    body.cost_bps, body.cooldown_bars,
                )
                family_scores[family] = detail.signal.family_score_pct
                family_labels[family] = detail.signal.family_signal_label
            except HTTPException:
                pass  # skip families that fail

        # Category grouping (Elder 1993 Triple Screen)
        categories: dict[str, dict[str, Any]] = {}
        for cat_name, cat_fams in CATEGORY_FAMILIES.items():
            cat_scores = [family_scores[f] for f in cat_fams if f in family_scores]
            if cat_scores:
                cat_avg = sum(cat_scores) / len(cat_scores)
                st = FAMILY_SIGNAL_TYPE.get(cat_fams[0], "trend")
                categories[cat_name] = {
                    "score_pct": round(cat_avg, 2),
                    "label": signal_type_label(st, cat_avg),
                    "families": cat_fams,
                }

        # Aggregate: equal weight across all families (DeMiguel et al. 2009)
        all_scores = list(family_scores.values())
        if all_scores:
            agg = sum(all_scores) / len(all_scores)
            results.append({
                "symbol": symbol,
                "aggregate_score_pct": round(agg, 2),
                "aggregate_signal_label": _score_to_label(agg),
                "categories": categories,
                "per_family": {
                    f: {"score_pct": round(s, 2), "label": family_labels.get(f, "N/A")}
                    for f, s in family_scores.items()
                },
            })
        else:
            results.append({
                "symbol": symbol,
                "aggregate_score_pct": None,
                "aggregate_signal_label": None,
                "categories": {},
                "per_family": {},
            })
    return results


# ---------------------------------------------------------------------------
# Layer H — Regime-aware consensus
# ---------------------------------------------------------------------------

_REGIME_CACHE: dict[tuple, tuple[float, dict]] = {}
_REGIME_CACHE_TTL = 600.0  # 10 minutes
_REGIME_CONSENSUS_ENABLED = False


@router.post("/signal/regime-consensus")
def regime_consensus(body: RegimeConsensusRequest, db: Session = Depends(get_db)):
    """Return regime-aware consensus: Kaufman ER detection + OOS-validated weights.

    Layer H: runs AFTER per-family A→G pipelines.
    If regime weighting beats equal-weight OOS → regime-weighted consensus.
    Otherwise → transparent equal-weight fallback.
    """
    if not _REGIME_CONSENSUS_ENABLED:
        raise HTTPException(status_code=404, detail="Regime-aware consensus is currently disabled.")

    cache_key = (body.symbol, body.horizon, body.timeframe, body.cost_bps, body.cooldown_bars)
    now = time.monotonic()
    cached = _REGIME_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _REGIME_CACHE_TTL:
        return cached[1]

    # 1. Compute all 4 family ensembles (each individually cached at 5min TTL)
    family_scores: dict[str, float] = {}
    family_details: dict[str, EnsemblePipelineDetail] = {}
    for family in ("sma", "rsi", "macd", "obv"):
        try:
            detail = _get_or_compute(
                db, family, body.symbol, body.horizon, body.timeframe,
                body.cost_bps, body.cooldown_bars,
            )
            family_scores[family] = detail.signal.family_score_pct
            family_details[family] = detail
        except HTTPException:
            pass  # skip unavailable families

    if not family_scores:
        return {
            "symbol": body.symbol,
            "final_consensus": None,
            "family_weights": {},
            "per_family": {},
            "regime_active": False,
            "regime_label": "insufficient_data",
            "er_value": None,
            "improvement": 0.0,
            "tercile_bounds": [0.33, 0.67],
            "equal_consensus": None,
            "n_families": 0,
            "window_results": [],
            "n_folds": 0,
            "folds_regime_wins": 0,
            "top_variants": {},
        }

    # 2. Load OHLCV for signal array computation
    try:
        ohlcv = load_ohlcv_for_symbol(db, body.symbol, body.timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    ohlcv = _truncate_for_horizon(ohlcv, body.horizon)
    ohlcv = _clean_ohlcv(ohlcv)
    close = ohlcv["Close"].values.astype("float64")
    volume = ohlcv["Volume"].values.astype("float64") if "Volume" in ohlcv.columns else None

    # 3. Extract top variant per family (highest reliability) and compute signal arrays
    family_signals: dict[str, np.ndarray] = {}
    for family, detail in family_details.items():
        if not detail.all_summaries:
            continue
        top_variant = max(detail.all_summaries, key=lambda s: s.reliability_score).variant
        try:
            sig = compute_signal_array(close, top_variant, volume=volume)
            family_signals[family] = sig
        except Exception as exc:
            logger.warning("Failed to compute signal array for %s/%s: %s", body.symbol, family, exc)

    # 4. Run OOS regime validation
    regime_result = validate_regime_oos(
        close, family_signals, body.horizon, body.cost_bps,
    )

    # 5. Compute regime consensus
    consensus = compute_regime_consensus(family_scores, regime_result)

    # 6. Enrich window_results with date strings
    idx = ohlcv.index
    enriched_windows: list[dict[str, Any]] = []
    for wr in regime_result.window_results:
        ew = dict(wr)
        ts, te = wr["test_start"], wr["test_end"]
        trs = wr["train_start"]
        if trs < len(idx):
            ew["train_start_date"] = str(idx[trs])[:10]
        if wr["train_end"] < len(idx):
            ew["train_end_date"] = str(idx[wr["train_end"] - 1])[:10]
        if ts < len(idx):
            ew["test_start_date"] = str(idx[ts])[:10]
        if te < len(idx):
            ew["test_end_date"] = str(idx[min(te, len(idx) - 1)])[:10]
        # Compute delta for easy display
        ew["delta"] = round(wr["regime_sharpe"] - wr["equal_sharpe"], 4)
        enriched_windows.append(ew)

    # 7. Equal-weight consensus for comparison
    n_avail = len(family_scores)
    equal_consensus = round(sum(family_scores.values()) / n_avail, 2) if n_avail > 0 else None

    # 8. Top variant info per family (what was used for regime validation)
    top_variants: dict[str, dict[str, Any]] = {}
    for family, detail in family_details.items():
        if not detail.all_summaries:
            continue
        top = max(detail.all_summaries, key=lambda s: s.reliability_score)
        top_variants[family] = {
            "variant_id": top.variant.variant_id,
            "archetype": top.variant.archetype,
            "params": top.variant.params,
            "reliability_score": round(top.reliability_score, 4),
            "label": _variant_label(top.variant),
        }

    # 9. Compute win rate across folds
    n_folds = len(enriched_windows)
    folds_regime_wins = sum(1 for w in enriched_windows if w.get("delta", 0) > 0)

    response = {
        "symbol": body.symbol,
        **consensus,
        "tercile_bounds": list(consensus.get("tercile_bounds", (0.33, 0.67))),
        "equal_consensus": equal_consensus,
        "n_families": regime_result.n_families,
        "window_results": enriched_windows,
        "n_folds": n_folds,
        "folds_regime_wins": folds_regime_wins,
        "top_variants": top_variants,
    }

    _REGIME_CACHE[cache_key] = (now, response)
    return response


# ---------------------------------------------------------------------------
# Signal zone chart — per-bar family consensus presentation
# ---------------------------------------------------------------------------

def _safe_float(v) -> float | None:
    """Convert numpy scalar to Python float, NaN → None."""
    if v is None:
        return None
    f = float(v)
    return None if np.isnan(f) else f


def _safe_float_list(arr: np.ndarray) -> list[float | None]:
    """Convert numpy array to list of floats, NaN → None."""
    return [None if np.isnan(float(v)) else round(float(v), 4) for v in arr]


def _detect_macd_crossovers(macd_line: list, signal_line: list) -> list[dict]:
    """Detect MACD / signal-line crossover bar indices."""
    crossovers: list[dict] = []
    for i in range(1, len(macd_line)):
        prev_m, curr_m = macd_line[i - 1], macd_line[i]
        prev_s, curr_s = signal_line[i - 1], signal_line[i]
        if prev_m is None or curr_m is None or prev_s is None or curr_s is None:
            continue
        prev_diff = prev_m - prev_s
        curr_diff = curr_m - curr_s
        if prev_diff <= 0 < curr_diff:
            crossovers.append({"bar_index": i, "direction": "bullish"})
        elif prev_diff >= 0 > curr_diff:
            crossovers.append({"bar_index": i, "direction": "bearish"})
    return crossovers


def _compute_obv_bar_signals(obv: list, ema_vals: list) -> list[str]:
    """Per-bar accumulation / distribution / neutral classification."""
    signals: list[str] = []
    for i in range(len(obv)):
        o, e = obv[i], ema_vals[i]
        if o is None or e is None:
            signals.append("neutral")
        elif o > e:
            signals.append("accumulation")
        elif o < e:
            signals.append("distribution")
        else:
            signals.append("neutral")
    return signals


def _get_all_representative_indicators(
    detail: EnsemblePipelineDetail,
    close: np.ndarray,
    volume: np.ndarray | None,
) -> list[dict]:
    """Representative entries enriched with per-variant indicator data."""
    reps = [
        s for s in detail.all_summaries
        if s.variant.variant_id in detail.representative_ids
    ]
    if not reps:
        reps = [
            s for s in detail.all_summaries
            if s.variant.variant_id in detail.fallback_variant_ids
        ]

    result: list[dict] = []
    for s in reps:
        entry: dict = {
            "variant_id": s.variant.variant_id,
            "weight": round(s.reliability_score, 4),
            "label": _variant_label(s.variant),
        }

        ind = _compute_indicator(close, s.variant, volume=volume)
        if ind["type"] == "none":
            entry["indicator"] = None
        else:
            ind_serialized: dict = {"type": ind["type"], "name": ind.get("name", "")}
            for key, val in ind.items():
                if key in ("type", "name"):
                    continue
                if isinstance(val, np.ndarray):
                    ind_serialized[key] = _safe_float_list(val)
                else:
                    ind_serialized[key] = val

            if "macd_line" in ind_serialized and "signal_line" in ind_serialized:
                ind_serialized["crossovers"] = _detect_macd_crossovers(
                    ind_serialized["macd_line"], ind_serialized["signal_line"],
                )
            if "obv" in ind_serialized and "ema_values" in ind_serialized:
                ind_serialized["bar_signals"] = _compute_obv_bar_signals(
                    ind_serialized["obv"], ind_serialized["ema_values"],
                )

            entry["indicator"] = ind_serialized

        result.append(entry)
    return result


def _get_top_representative_indicator(
    detail: EnsemblePipelineDetail,
    close: np.ndarray,
    volume: np.ndarray | None,
) -> dict | None:
    """Indicator overlay data from the top representative variant."""
    reps = [
        s for s in detail.all_summaries
        if s.variant.variant_id in detail.representative_ids
    ]
    if not reps:
        reps = [
            s for s in detail.all_summaries
            if s.variant.variant_id in detail.fallback_variant_ids
        ]
    if not reps:
        return None

    top = max(reps, key=lambda s: s.reliability_score)
    ind = _compute_indicator(close, top.variant, volume=volume)
    if ind["type"] == "none":
        return None

    result: dict = {"type": ind["type"], "name": ind.get("name", "")}
    for key, val in ind.items():
        if key in ("type", "name"):
            continue
        if isinstance(val, np.ndarray):
            result[key] = _safe_float_list(val)
        else:
            result[key] = val
    return result


def _get_representatives_info(detail: EnsemblePipelineDetail) -> list[dict]:
    """Representative variant labels and weights."""
    reps = [
        s for s in detail.all_summaries
        if s.variant.variant_id in detail.representative_ids
    ]
    if not reps:
        reps = [
            s for s in detail.all_summaries
            if s.variant.variant_id in detail.fallback_variant_ids
        ]
    return [
        {
            "variant_id": s.variant.variant_id,
            "weight": round(s.reliability_score, 4),
            "label": _variant_label(s.variant),
        }
        for s in reps
    ]


@router.post("/signal/zone-chart")
def signal_zone_chart(body: SignalZoneChartRequest, db: Session = Depends(get_db)):
    """Per-bar family consensus with representative overlays for chart rendering."""
    try:
        ohlcv = load_ohlcv_for_symbol(db, body.symbol, body.timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    ohlcv = _truncate_for_horizon(ohlcv, body.horizon)
    ohlcv = _clean_ohlcv(ohlcv)

    if len(ohlcv) == 0:
        raise HTTPException(status_code=422, detail=f"No OHLCV data for {body.symbol}")

    close = ohlcv["Close"].values.astype("float64")
    volume = (
        ohlcv["Volume"].values.astype("float64")
        if "Volume" in ohlcv.columns
        else None
    )
    dates = [str(d)[:10] for d in ohlcv.index]

    # Format OHLCV bars
    bars: list[dict] = []
    has_volume = "Volume" in ohlcv.columns
    for i, d in enumerate(dates):
        bars.append({
            "date": d,
            "open": _safe_float(ohlcv["Open"].iloc[i]),
            "high": _safe_float(ohlcv["High"].iloc[i]),
            "low": _safe_float(ohlcv["Low"].iloc[i]),
            "close": _safe_float(ohlcv["Close"].iloc[i]),
            "volume": _safe_float(ohlcv["Volume"].iloc[i]) if has_volume else None,
        })

    # Per-family signal computation
    families: dict[str, dict] = {}

    for fam in body.enabled_families:
        try:
            detail = _get_or_compute(
                db, fam, body.symbol, body.horizon,
                body.timeframe, body.cost_bps, body.cooldown_bars,
            )
        except HTTPException:
            continue  # skip family if data insufficient (e.g. OBV without volume)

        scores = compute_family_score_timeseries(
            detail, close, volume=volume, cooldown_bars=body.cooldown_bars,
        )

        families[fam] = {
            "scores": [round(float(s), 2) for s in scores],
            "representatives": _get_all_representative_indicators(detail, close, volume),
            "indicator": _get_top_representative_indicator(detail, close, volume),
        }

    return {
        "symbol": body.symbol,
        "horizon": body.horizon,
        "bars": bars,
        "families": families,
    }
