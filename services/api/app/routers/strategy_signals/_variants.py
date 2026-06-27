"""Variant and indicator signal endpoints: indicator-series, variant-detail, variant-backtest, batch-scores."""
from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any

import numpy as np
import pandas as pd

from fastapi import Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...db import get_db
from ...schemas.strategy_signals import (
    BatchScoresRequest,
    IndicatorSeriesRequest,
    VariantBacktestRequest,
    VariantDetailRequest,
)
from core.quant_core.signal_engine.domain import (
    ALL_FAMILIES,
    CATEGORY_FAMILIES,
    FAMILY_SIGNAL_TYPE,
    EnsemblePipelineDetail,
    VARIANT_FAMILIES,
    VariantDef,
    VariantRobustnessSummary,
    label_to_signal_value,
    signal_type_label,
    variant_signal_label,
)
from core.quant_core.signal_engine.ensemble import (
    family_signal_is_available,
    _score_to_label,
)
from core.quant_core.signal_engine.oos_eval import compute_signal_array
from core.quant_core.signal_engine.modes import (
    resolve_signal_mode,
    signal_mode_read_names,
    signal_mode_storage_name,
)
from core.quant_core.signal_engine.variant_detail import (
    compute_variant_detail,
    compute_variant_trade_register,
    _compute_indicator,
)
from core.quant_core.signal_engine.indicator_series import compute_atr_series
from core.quant_core.risk import monte_carlo_equity_paths
from core.quant_core.significance import sharpe_ratio
from core.quant_core.horizons import canonical_horizon
from core.quant_core.signal_engine.rsi_semantics import latest_rsi_variant_signal
from core.quant_core.signal_engine.ta_combo import factor_condition_to_dict
from ...market_data_loader import load_ohlcv_for_symbol
from ._support_resistance import (
    _validate_indicator_params,
    _indicator_variant,
    _indicator_current_score,
    _primary_indicator_series,
    _serialize_indicator_payload,
    _current_label_for_family,
)
from ._shared import (
    logger,
    router,
    CanonicalHorizon,
    _CACHE,
    _BACKTEST_CACHE,
    _BACKTEST_CACHE_TTL,
    _BACKTEST_CACHE_VERSION,
    _VOLUME_DEPENDENT,
    _HIGH_LOW_DEPENDENT,
    _INDICATOR_ARCHETYPES,
    _require_canonical_signal_horizon,
    _truncate_for_horizon,
    _clean_ohlcv,
    _validate_volume_data,
    _require_high_low,
    _variant_label,
    _methodology_context_payload,
    _fallback_variants_by_id,
    _get_or_compute,
    _safe_float,
    _safe_float_list,
    _apply_indicator_live_bar,
)

@router.post("/signal/indicator-series")
def indicator_series(body: IndicatorSeriesRequest, db: Session = Depends(get_db)):
    """Return raw indicator series plus the latest continuous score."""
    try:
        ohlcv = load_ohlcv_for_symbol(db, body.symbol, body.timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    validated_params = _validate_indicator_params(body.indicator, body.params)
    if "Close" not in ohlcv.columns:
        raise HTTPException(
            status_code=422,
            detail=f"Close column missing for {body.symbol} - cannot compute indicator series",
        )
    if body.indicator in _VOLUME_DEPENDENT and "Volume" not in ohlcv.columns:
        raise HTTPException(
            status_code=422,
            detail=f"Volume data missing for {body.symbol} - {body.indicator.upper()} cannot be computed. "
                   f"Available columns: {list(ohlcv.columns)}",
        )
    ohlcv = _clean_ohlcv(ohlcv)
    if len(ohlcv) == 0:
        raise HTTPException(status_code=422, detail=f"No usable OHLCV rows for {body.symbol}")
    ohlcv, live_bar_applied = _apply_indicator_live_bar(ohlcv, body.live_bar)

    try:
        close = ohlcv["Close"].values.astype("float64")
    except KeyError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Close column missing for {body.symbol} - cannot compute indicator series",
        ) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid Close values for {body.symbol} - cannot compute indicator series: {exc}",
        ) from exc

    try:
        volume = ohlcv["Volume"].values.astype("float64") if "Volume" in ohlcv.columns else None
        high = ohlcv["High"].values.astype("float64") if "High" in ohlcv.columns else None
        low = ohlcv["Low"].values.astype("float64") if "Low" in ohlcv.columns else None
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid OHLCV values for {body.symbol} - cannot compute indicator series: {exc}",
        ) from exc
    if body.indicator in _VOLUME_DEPENDENT:
        _validate_volume_data(body.indicator, body.symbol, ohlcv, volume)
    if body.indicator in _HIGH_LOW_DEPENDENT and (high is None or low is None):
        high, low = _require_high_low(body.indicator, body.symbol, ohlcv)

    dates = [str(idx)[:10] for idx in ohlcv.index]

    try:
        variant = _indicator_variant(body.indicator, validated_params)
        plot_payload = _compute_indicator(close, variant, volume=volume, high=high, low=low)
        indicator_values, indicator_overlay = _primary_indicator_series(plot_payload)
        latest_score, atr_value = _indicator_current_score(
            body.indicator,
            plot_payload,
            close,
            high=high,
            low=low,
        )
        latest_signal_arr = compute_signal_array(close, variant, volume=volume, high=high, low=low)
        latest_signal = float(latest_signal_arr[-1]) if len(latest_signal_arr) else 0.0
    except (KeyError, ValueError, TypeError, AssertionError, IndexError, RuntimeError, ArithmeticError) as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid {body.indicator.upper()} parameters for indicator-series: {exc}",
        ) from exc

    if latest_score is None or not np.isfinite(latest_score):
        raise HTTPException(
            status_code=422,
            detail=f"Insufficient history for {body.indicator} with params {validated_params}",
        )

    return {
        "symbol": body.symbol,
        "indicator": body.indicator,
        "params": {k: float(v) for k, v in validated_params.items()},
        "dates": dates,
        "close": _safe_float_list(close),
        "indicator_values": _safe_float_list(indicator_values),
        "indicator_overlay": _safe_float_list(indicator_overlay) if indicator_overlay is not None else None,
        "plot_payload": _serialize_indicator_payload(plot_payload),
        "current_score": round(float(latest_score), 4),
        "current_label": _current_label_for_family(body.indicator, latest_signal),
        "atr": round(atr_value, 4) if atr_value is not None else None,
        "live_bar_applied": live_bar_applied,
        "data_as_of": dates[-1] if dates else None,
    }


@router.post("/signal/variant-detail")
def variant_detail(body: VariantDetailRequest, db: Session = Depends(get_db)):
    """Return full detail for a single variant from the cached pipeline run."""
    detail = _get_or_compute(db, _family_for_variant(body.variant_id, db, body), body.symbol, body.horizon, body.timeframe, body.cost_bps, body.cooldown_bars, variant=body.variant)

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
    high = ohlcv["High"].values.astype("float64") if "High" in ohlcv.columns else None
    low = ohlcv["Low"].values.astype("float64") if "Low" in ohlcv.columns else None
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
        try:
            trades, _window_cash_starts = compute_variant_trade_register(
                ohlcv,
                close,
                summary.variant,
                detail.oos_windows.get(summary.variant.variant_id, []),
                volume=volume,
                high=high,
                low=low,
                cost_bps=body.cost_bps,
                cooldown_bars=body.cooldown_bars,
                force_valid_windows=summary.variant.variant_id in detail.representative_ids,
            )
        except Exception:
            trades = []
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
            "factor_condition": factor_condition_to_dict(getattr(s.variant, "factor_condition", None)),
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
        "factor_condition": factor_condition_to_dict(getattr(v, "factor_condition", None)),
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
    v = signal_mode_storage_name(getattr(body, "variant", "expanded"))
    families = list(
        dict.fromkeys(
            family
            for category_families in VARIANT_FAMILIES.get(v, {"all": ALL_FAMILIES}).values()
            for family in category_families
        )
    )
    for family in families:
        key = (family, body.symbol, body.horizon, body.timeframe, body.cost_bps, body.cooldown_bars, v)
        cached = _CACHE.get(key)
        if cached:
            _, detail = cached
            for s in detail.all_summaries:
                if s.variant.variant_id == variant_id:
                    return family
            if variant_id in detail.fallback_variant_ids:
                return family
    # Fallback: compute all families until we find it
    for family in families:
        detail = _get_or_compute(db, family, body.symbol, body.horizon, body.timeframe, body.cost_bps, body.cooldown_bars, variant=v)
        for s in detail.all_summaries:
            if s.variant.variant_id == variant_id:
                return family
        if variant_id in detail.fallback_variant_ids:
            return family
    return "sma"  # fallback


def _normalize_variant_backtest_mc_config(mc_config: dict[str, Any] | None) -> dict[str, Any] | None:
    if not mc_config:
        return None

    method = str(mc_config.get("method") or "block_bootstrap")
    if method not in {"block_bootstrap", "trade_bootstrap"}:
        method = "block_bootstrap"
    # Variant detail exposes the stitched OOS return stream, not trade event timing.
    # Fall back to block bootstrap if a caller asks for trade bootstrap here.
    if method == "trade_bootstrap":
        method = "block_bootstrap"

    try:
        n_paths = int(mc_config.get("n_paths") or 2000)
    except (TypeError, ValueError):
        n_paths = 2000
    n_paths = max(1, min(n_paths, 10_000))

    block_mean = mc_config.get("block_mean")
    if block_mean is not None:
        try:
            block_mean = max(1, int(block_mean))
        except (TypeError, ValueError):
            block_mean = None

    try:
        seed = int(mc_config.get("seed") or 42)
    except (TypeError, ValueError):
        seed = 42

    return {
        "method": method,
        "n_paths": n_paths,
        "block_mean": block_mean,
        "seed": seed,
    }


def _variant_backtest_mc_cache_key(mc_config: dict[str, Any] | None) -> tuple[Any, ...] | None:
    normalized = _normalize_variant_backtest_mc_config(mc_config)
    if normalized is None:
        return None
    return (
        normalized["method"],
        normalized["n_paths"],
        normalized["block_mean"],
        normalized["seed"],
    )


def _variant_equity_series_from_result(result: dict[str, Any]) -> tuple[list[str], list[float]]:
    plots = result.get("plots") if isinstance(result, dict) else None
    equity_plot = (plots or {}).get("oos_equity") if isinstance(plots, dict) else None
    traces = equity_plot.get("data") if isinstance(equity_plot, dict) else None
    if not isinstance(traces, list):
        return [], []

    for trace in traces:
        if not isinstance(trace, dict):
            continue
        y_values = trace.get("y")
        if not isinstance(y_values, list):
            continue
        x_values = trace.get("x")
        dates: list[str] = []
        equity: list[float] = []
        for idx, raw_value in enumerate(y_values):
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                continue
            if not np.isfinite(value):
                continue
            date_value = ""
            if isinstance(x_values, list) and idx < len(x_values):
                date_value = str(x_values[idx])[:10]
            dates.append(date_value or str(idx))
            equity.append(value)
        if equity:
            return dates, equity

    return [], []


def _returns_from_equity(equity: list[float]) -> np.ndarray:
    if not equity:
        return np.array([], dtype=np.float64)
    arr = np.asarray(equity, dtype=np.float64)
    prev = np.concatenate(([1.0], arr[:-1]))
    safe_prev = np.where(np.abs(prev) > 1e-12, prev, 1.0)
    returns = arr / safe_prev - 1.0
    return np.where(np.isfinite(returns), returns, 0.0).astype(np.float64)


def _variant_backtest_mc_payload(
    result: dict[str, Any],
    mc_config: dict[str, Any] | None,
) -> tuple[list[str], list[float], dict[str, Any] | None]:
    dates, equity = _variant_equity_series_from_result(result)
    normalized = _normalize_variant_backtest_mc_config(mc_config)
    if normalized is None:
        return dates, equity, None

    mc_result = monte_carlo_equity_paths(
        _returns_from_equity(equity),
        method=normalized["method"],
        n_paths=normalized["n_paths"],
        block_mean=normalized["block_mean"],
        seed=normalized["seed"],
    )
    return dates, equity, mc_result


@router.post("/signal/variant-backtest")
def variant_backtest(body: VariantBacktestRequest, db: Session = Depends(get_db)):
    """Return OOS plots, trade ledger, and performance for a single variant."""
    family = _family_for_variant(body.variant_id, db, body)
    detail = _get_or_compute(db, family, body.symbol, body.horizon, body.timeframe, body.cost_bps, body.cooldown_bars, variant=body.variant)

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
        body.timeframe,
        signal_mode_storage_name(body.variant),
        body.cost_bps,
        body.cooldown_bars,
        body.trade_cooldown_bars,
        _variant_backtest_mc_cache_key(body.mc_config),
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
    high = ohlcv["High"].values.astype("float64") if "High" in ohlcv.columns else None
    low = ohlcv["Low"].values.astype("float64") if "Low" in ohlcv.columns else None
    oos_windows = detail.oos_windows.get(body.variant_id, [])

    try:
        result = compute_variant_detail(
            ohlcv, close, target.variant, oos_windows,
            volume=volume, high=high, low=low, cost_bps=body.cost_bps, cooldown_bars=body.cooldown_bars,
            trade_cooldown_bars=body.trade_cooldown_bars,
            force_valid_windows=body.variant_id in detail.representative_ids,
        )
    except Exception as exc:
        result = {
            "metrics": {"note": f"Variant replay unavailable: {exc}"},
            "trade_performance": [],
            "trade_ledger": [],
            "plots": {},
            "per_window": [],
        }
    dates, equity, mc_payload = _variant_backtest_mc_payload(result, body.mc_config)

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
        "equity": equity,
        "dates": dates,
        "mc": mc_payload,
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
        response["equity"] = []
        response["dates"] = []
        response["mc"] = None
        response["oos_window_dates"] = []

    _BACKTEST_CACHE[cache_key] = (now, response)
    return response


@router.post("/signal/batch-scores")
def batch_scores(body: BatchScoresRequest, db: Session = Depends(get_db)):
    """Return aggregate signal scores across all configured families for multiple symbols.

    Response includes per-family scores, category grouping (Tendance/Oscillation/Volume),
    and an equal-weight aggregate (DeMiguel et al. 2009).
    """
    results: list[dict[str, Any]] = []
    for symbol in body.symbols:
        family_scores: dict[str, float] = {}
        family_labels: dict[str, str] = {}
        for family in ALL_FAMILIES:
            try:
                detail = _get_or_compute(
                    db, family, symbol, body.horizon, body.timeframe,
                    body.cost_bps, body.cooldown_bars, variant=body.variant,
                )
                if not family_signal_is_available(detail.signal):
                    continue
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


