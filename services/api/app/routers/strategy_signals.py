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
    SmaEnsembleRequest,
    VariantBacktestRequest,
    VariantDetailRequest,
)

from core.quant_core.signal_engine.ensemble import run_family_ensemble_full, _score_to_label
from core.quant_core.signal_engine.domain import (
    CATEGORY_FAMILIES,
    FAMILY_SIGNAL_TYPE,
    EnsemblePipelineDetail,
    HORIZON_PARAMS,
    label_to_signal_value,
    signal_type_label,
)
from core.quant_core.signal_engine.variant_detail import compute_variant_detail

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/strategy", tags=["strategy-signals"])

# ---------------------------------------------------------------------------
# In-process TTL cache — keyed by (family, symbol, horizon, timeframe, cost_bps)
# ---------------------------------------------------------------------------

_CACHE: dict[tuple, tuple[float, EnsemblePipelineDetail]] = {}
_CACHE_TTL = 300.0  # 5 minutes

_BACKTEST_CACHE: dict[tuple, tuple[float, dict]] = {}
_BACKTEST_CACHE_TTL = 600.0


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

    # Determine signal for this variant — use current_signal_labels for all,
    # override with representative-quality signal if available
    target_signal_label = detail.current_signal_labels.get(body.variant_id, "NEUTRE")
    target_signal = label_to_signal_value(target_signal_label)
    target_selection_status = fallback_lookup.get(body.variant_id, {}).get("selection_status", "")
    for rep in detail.signal.representatives:
        if rep["variant_id"] == body.variant_id:
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
        sig_label = detail.current_signal_labels.get(vid, "NEUTRE")
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
        ohlcv = load_ohlcv_for_symbol(db, body.symbol, body.timeframe)
        ohlcv = _truncate_for_horizon(ohlcv, body.horizon)
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
    cache_key = (body.symbol, body.variant_id, body.horizon, body.cost_bps, body.cooldown_bars)
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
