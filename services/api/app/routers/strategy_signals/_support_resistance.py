"""Support/Resistance endpoints and all _sr_* helpers (including overlay cache)."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from fastapi import Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...db import get_db
from ...schemas.strategy import PivotPoints
from ...schemas.strategy_signals import (
    SupportResistanceMethodDetailRequest,
    SupportResistanceMethodDetailResponse,
    SupportResistanceRequest,
    SupportResistanceResponse,
    SupportResistanceVariantRequest,
    VariantBacktestRequest,
)
from core.quant_core.signal_engine.support_resistance import (
    build_ma_anchor_method,
    compute_representative_ma_anchor,
    compute_score_inversion_levels,
    finalize_support_resistance_methods,
    round_number,
)
from core.quant_core.signal_engine.sr_levels import (
    compute_pivot_family_levels,
    finite_float as _sr_finite_float,
    nearest_support_resistance_from_lines,
    normalize_line_id,
    split_support_resistance_lines,
)
from core.quant_core.signal_engine.sr_validation import (
    baseline_returns_from_position,
    validate_sr_overlay_candidate,
)
from core.quant_core.signal_engine.domain import (
    ALL_FAMILIES,
    CATEGORY_FAMILIES,
    FAMILY_SIGNAL_TYPE,
    EnsemblePipelineDetail,
    HORIZON_PARAMS,
    OOSWindowResult,
    VARIANT_FAMILIES,
    VariantDef,
    VariantRobustnessSummary,
    LEGACY_CATEGORY_FAMILIES,
    label_to_signal_value,
    signal_type_label,
    variant_signal_label,
)
from core.quant_core.signal_engine.ensemble import (
    run_family_ensemble_full,
    compute_family_score_timeseries,
    family_signal_is_available,
)
from core.quant_core.signal_engine.modes import (
    ALL_SIGNAL_MODE_NAMES,
    resolve_signal_mode,
    signal_mode_read_names,
    signal_mode_storage_name,
)
from core.quant_core.signal_engine.oos_eval import compute_signal_array
from core.quant_core.signal_engine.variant_detail import _compute_indicator
from core.quant_core.signal_engine.indicator_series import compute_atr_series
from core.quant_core.significance import sharpe_ratio
from core.quant_core.horizons import canonical_horizon, LEGACY_HORIZON_ALIASES, HORIZON_SPECS
from core.quant_core.signal_engine.sr_wfo import line_touch_stats, run_sr_wfo
from core.quant_core.risk import monte_carlo_equity_paths
from core.quant_core.strategy_plan.execution_policy import build_execution_horizon_policy
from core.quant_core.strategy_plan.levels import (
    compute_atr,
    compute_pivot_points,
    detect_swing_levels,
    compute_fibonacci_retracement_levels,
)
from core.quant_core.decision.levels import compute_levels_support_resistance
from core.quant_core.data import drop_incomplete_ohlcv_rows
from ...market_data_loader import format_ohlcv_timestamp, load_close_for_symbol, load_ohlcv_for_symbol
from ._shared import (
    logger,
    router,
    CanonicalHorizon,
    _CACHE,
    _CACHE_TTL,
    _SR_INVERSION_CACHE,
    _SR_INVERSION_CACHE_TTL,
    _SR_INVERSION_SCAN_POINTS,
    _SR_INVERSION_REFINE_STEPS,
    _SR_INVERSION_MAX_EVALS,
    _SR_VARIANTS_CACHE,
    _SR_VARIANTS_CACHE_TTL,
    _SR_VARIANT_BACKTEST_CACHE,
    _SR_VARIANT_BACKTEST_CACHE_TTL,
    _SR_WFO_CACHE,
    _SR_WFO_CACHE_TTL,
    _require_canonical_signal_horizon,
    _sr_variants_cache_key,
    _truncate_for_horizon,
    _clean_ohlcv,
    _finite_live_number,
    _normalized_bar_date,
    _apply_indicator_live_bar,
    _validate_volume_data,
    _require_high_low,
    _variant_label,
    _methodology_context_payload,
    _fallback_variants_by_id,
    _get_or_compute,
    _safe_float,
    _safe_float_list,
    _INDICATOR_ARCHETYPES,
    _evidence_sharpe,
    _evidence_max_drawdown,
    _evidence_float,
)

def _signal_snapshot_from_detail(family: str, detail: EnsemblePipelineDetail) -> dict[str, Any]:
    signal = detail.signal
    representatives = [entry for entry in (signal.representatives or []) if isinstance(entry, dict)]
    fallback_variants = [entry for entry in (signal.fallback_variants or []) if isinstance(entry, dict)]
    return {
        "family": family,
        "family_score_pct": float(signal.family_score_pct),
        "family_signal_label": str(signal.family_signal_label),
        "representatives": representatives,
        "fallback_variants": fallback_variants,
        "as_of": str(signal.as_of or ""),
        "latest_close": signal.latest_close,
    }


def _build_sr_chart(
    ohlcv: pd.DataFrame,
    tail_n: int,
    horizontal_lines: dict[str, float] | None = None,
    time_series_lines: dict[str, list[float | None]] | None = None,
) -> dict[str, Any]:
    tail = ohlcv.tail(max(2, int(tail_n)))
    bars = []
    for index, row in tail.iterrows():
        bars.append({
            "date": str(index)[:10],
            "open": _safe_float(row.get("Open")),
            "high": _safe_float(row.get("High")),
            "low": _safe_float(row.get("Low")),
            "close": _safe_float(row.get("Close")),
            "volume": _safe_float(row.get("Volume")) if "Volume" in tail.columns else None,
        })
    
    sources = []
    if horizontal_lines:
        for label, val in horizontal_lines.items():
            if val is not None and pd.notna(val):
                sources.append({
                    "label": label,
                    "indicator": {
                        "type": "overlay",
                        "plot_kind": "line",
                        "plot_axis": "price",
                        "plot_values": [float(val)] * len(bars)
                    }
                })
                
    if time_series_lines:
        for label, vals in time_series_lines.items():
            if vals is not None and len(vals) == len(bars):
                sources.append({
                    "label": label,
                    "indicator": {
                        "type": "overlay",
                        "plot_kind": "line",
                        "plot_axis": "price",
                        "plot_values": vals
                    }
                })
                
    return {
        "bars": bars,
        "sources": sources
    }


def _compute_signal_page_support_resistance_legacy_unused(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    timeframe: str,
    cost_bps: float,
    cooldown_bars: int,
    variant: str = "expanded",
) -> dict[str, Any]:
    try:
        ohlcv = load_ohlcv_for_symbol(db, symbol, timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    ohlcv = _truncate_for_horizon(ohlcv, horizon)
    ohlcv = _clean_ohlcv(ohlcv)
    if ohlcv.empty or len(ohlcv) < 2:
        raise HTTPException(status_code=422, detail=f"Insufficient data for {symbol}.")

    close = ohlcv["Close"].values.astype("float64")
    high = ohlcv["High"].values.astype("float64") if "High" in ohlcv.columns else None
    low = ohlcv["Low"].values.astype("float64") if "Low" in ohlcv.columns else None
    volume = ohlcv["Volume"].values.astype("float64") if "Volume" in ohlcv.columns else None
    current_close = float(close[-1])
    as_of = str(ohlcv.index[-1])[:10]

    family_snapshots: dict[str, dict[str, Any]] = {}
    trend_scores: list[float] = []
    for family in ALL_FAMILIES:
        try:
            detail = _get_or_compute(db, family, symbol, horizon, timeframe, cost_bps, cooldown_bars, variant=variant)
        except HTTPException:
            continue

        family_snapshots[family] = _signal_snapshot_from_detail(family, detail)
        if family_signal_is_available(detail.signal) and FAMILY_SIGNAL_TYPE.get(family) == "trend":
            trend_scores.append(float(detail.signal.family_score_pct))

    trend_score_pct = float(sum(trend_scores) / len(trend_scores)) if trend_scores else None
    trend_label = signal_type_label("trend", trend_score_pct) if trend_score_pct is not None else "Indisponible"

    ma_anchor_payload = compute_representative_ma_anchor(family_snapshots)
    methods: list[dict[str, Any]] = [
        build_ma_anchor_method(ma_anchor_payload, trend_score_pct=trend_score_pct),
    ]
    ma_method = build_ma_anchor_method(ma_anchor_payload, trend_score_pct=trend_score_pct)
    ma_lines = {}
    if ma_method.get("support"): ma_lines["Support MA"] = ma_method["support"]
    if ma_method.get("resistance"): ma_lines["Résistance MA"] = ma_method["resistance"]
    
    tail_len = min(150, len(ohlcv))
    ts_lines = {}
    if ma_anchor_payload.get("representatives"):
        close_full = ohlcv["Close"].values.astype("float64")
        for rep in ma_anchor_payload["representatives"]:
            params = rep.get("params") or {}
            arch = rep.get("archetype") or "price_vs_sma"
            vid = rep.get("variant_id") or "ma"
            label = rep.get("label") or vid
            if not label or label == "ma":
                w = params.get("window", params.get("span", ""))
                label = f"SMA {w}" if "sma" in arch else f"EMA {w}"
            
            variant = VariantDef(
                variant_id=vid, family="sma", archetype=arch, params=params, description=label
            )
            try:
                ind_data = _compute_indicator(close_full, variant)
                if ind_data and "values" in ind_data:
                    vals_tail = ind_data["values"][-tail_len:]
                    ts_lines[label] = [_safe_float(v) for v in vals_tail]
            except Exception:
                pass

    ma_method.setdefault("inputs", {})
    ma_method["inputs"]["chart"] = _build_sr_chart(ohlcv, tail_len, horizontal_lines=ma_lines, time_series_lines=ts_lines)
    ma_method["inputs"]["ma_representatives"] = ma_anchor_payload.get("representatives", [])
    reps_count = len(ma_anchor_payload.get("representatives", []))
    ma_method["explanation"] = f"Moyenne pondérée des {reps_count} moyennes mobiles représentatives, orientée par la tendance globale."
    methods: list[dict[str, Any]] = [ma_method]

    # DISABLED: This brute-force numeric simulation belongs in offline exports, 
    # not on a live API thread. It was pegging the CPU to 100%+.
    score_levels = {}
    methods.append(
        {
            "id": "score_inversion",
            "label": "Seuils par inversion du score",
            "support": score_levels.get("support_buy_trigger"),
            "resistance": score_levels.get("resistance_sell_trigger"),
            "status": (
                "available"
                if score_levels.get("support_buy_trigger") is not None
                or score_levels.get("resistance_sell_trigger") is not None
                else "unavailable"
            ),
            "selected_for_support": False,
            "selected_for_resistance": False,
            "explanation": "Prix ou le score agrege des representatives bascule en zone achat/vente.",
            "explanation": "Simulation du prix exact où le consensus technique global bascule mathématiquement en zone d'achat (support) ou de vente (résistance).",
            "inputs": {
                "close_used": score_levels.get("close_used"),
                "support_reference": score_levels.get("support_reference"),
                "thresholds": score_levels.get("thresholds"),
                "method": score_levels.get("method"),
            },
        }
    )

    policy = build_execution_horizon_policy(horizon, timeframe=timeframe)
    if high is not None and low is not None and len(close) >= 3:
        swing_levels = detect_swing_levels(
            high,
            low,
            close,
            left_bars=policy.swing_left_bars,
            right_bars=policy.swing_right_bars,
            max_levels=policy.max_levels,
            lookback=policy.structural_lookback,
            max_distance_atr=policy.max_level_distance_atr,
        )
        swing_lines = {}
        if swing_levels.get("nearest_support"): swing_lines["Support (Swing)"] = swing_levels["nearest_support"]
        if swing_levels.get("nearest_resistance"): swing_lines["Résistance (Swing)"] = swing_levels["nearest_resistance"]

        methods.append(
            {
                "id": "swing_levels",
                "label": "Swings structurels",
                "support": swing_levels.get("nearest_support"),
                "resistance": swing_levels.get("nearest_resistance"),
                "status": (
                    "available"
                    if swing_levels.get("nearest_support") is not None
                    or swing_levels.get("nearest_resistance") is not None
                    else "unavailable"
                ),
                "selected_for_support": False,
                "selected_for_resistance": False,
                "explanation": f"Niveaux pivots historiques identifiés à partir des sommets (résistances) et creux (supports) locaux sur les {policy.structural_lookback} dernières barres.",
                "inputs": {
                    "lookback": policy.structural_lookback,
                    "left_bars": policy.swing_left_bars,
                    "right_bars": policy.swing_right_bars,
                    "max_levels": policy.max_levels,
                    "supports": swing_levels.get("supports") or [],
                    "resistances": swing_levels.get("resistances") or [],
                    "chart": _build_sr_chart(ohlcv, policy.structural_lookback, swing_lines),
                },
            }
        )
    else:
        methods.append(
            {
                "id": "swing_levels",
                "label": "Swings structurels",
                "support": None,
                "resistance": None,
                "status": "unavailable",
                "selected_for_support": False,
                "selected_for_resistance": False,
                "explanation": "High/Low insuffisants pour calculer les swings historiques.",
                "inputs": {},
            }
        )

    pivot_method = {
        "id": "pivot_points",
        "label": "Pivots classiques",
        "support": None,
        "resistance": None,
        "status": "unavailable",
        "selected_for_support": False,
        "selected_for_resistance": False,
        "explanation": "Au moins deux barres (avec High/Low) sont requises pour les pivots.",
        "inputs": {},
    }
    if len(ohlcv) >= 2 and high is not None and low is not None:
        prev = ohlcv.iloc[-2]
        pivot = PivotPoints(**compute_pivot_points(
            prev_high=float(prev["High"]),
            prev_low=float(prev["Low"]),
            prev_close=float(prev["Close"]),
        ))
        support_candidates = [value for value in (pivot.s1, pivot.s2) if value <= current_close]
        resistance_candidates = [value for value in (pivot.r1, pivot.r2) if value >= current_close]
        pivot_lines = {"Pivot": pivot.pp, "S1": pivot.s1, "S2": pivot.s2, "R1": pivot.r1, "R2": pivot.r2}
        
        pivot_method.update(
            {
                "support": max(support_candidates) if support_candidates else None,
                "resistance": min(resistance_candidates) if resistance_candidates else None,
                "status": "available" if support_candidates or resistance_candidates else "ignored",
                "explanation": "Calcul classique des points pivots (S1/S2, R1/R2) basé sur la volatilité (Haut, Bas, Clôture) de la séance précédente.",
                "inputs": {
                    "pp": pivot.pp,
                    "s1": pivot.s1,
                    "s2": pivot.s2,
                    "r1": pivot.r1,
                    "r2": pivot.r2,
                    "prev_high": float(prev["High"]),
                    "prev_low": float(prev["Low"]),
                    "prev_close": float(prev["Close"]),
                    "chart": _build_sr_chart(ohlcv, 15, pivot_lines),
                },
            }
        )
    methods.append(pivot_method)

    quantile_method = {
        "id": "quantile_extrema_atr",
        "label": "Quantiles + extremes + ATR",
        "support": None,
        "resistance": None,
        "status": "unavailable",
        "selected_for_support": False,
        "selected_for_resistance": False,
        "explanation": "Données OHLC insuffisantes pour calculer les bornes de volatilité.",
        "inputs": {},
    }
    if high is not None and low is not None:
        quantile_levels = compute_levels_support_resistance(
            pd.DataFrame(
                {
                    "Open": ohlcv["Open"].values.astype("float64") if "Open" in ohlcv.columns else close,
                    "High": high,
                    "Low": low,
                    "Close": close,
                    "Volume": volume if volume is not None else np.zeros(len(close), dtype="float64"),
                }
            ),
            direction=0,
        )
        q_lines = {}
        if quantile_levels.get("support"): q_lines["Support (Volatilité)"] = quantile_levels["support"]
        if quantile_levels.get("resistance"): q_lines["Résistance (Volatilité)"] = quantile_levels["resistance"]

        quantile_method.update(
            {
                "support": quantile_levels.get("support"),
                "resistance": quantile_levels.get("resistance"),
                "status": (
                    "available"
                    if quantile_levels.get("support") is not None or quantile_levels.get("resistance") is not None
                    else "unavailable"
                ),
                "explanation": str(quantile_levels.get("explain") or "Zones de probabilité dérivées des quantiles historiques extrêmes et de l'ATR (volatilité récente)."),
                "inputs": {
                    **dict(quantile_levels.get("inputs") or {}),
                    "chart": _build_sr_chart(ohlcv, 100, q_lines),
                },
            }
        )
    methods.append(quantile_method)

    fib_method: dict[str, Any] = {
        "id": "fibonacci_retracement",
        "label": "Retracements Fibonacci",
        "support": None,
        "resistance": None,
        "status": "unavailable",
        "selected_for_support": False,
        "selected_for_resistance": False,
        "explanation": "Données OHLC insuffisantes pour calculer les retracements Fibonacci.",
        "inputs": {},
    }
    if high is not None and low is not None and len(close) >= 30:
        fib = compute_fibonacci_retracement_levels(
            high,
            low,
            close,
            lookback=policy.structural_lookback,
            left_bars=policy.swing_left_bars,
            right_bars=policy.swing_right_bars,
        )
        fib_lines: dict[str, float] = {}
        if fib.get("support") is not None:
            fib_lines["Support (Fib)"] = fib["support"]
        if fib.get("resistance") is not None:
            fib_lines["Résistance (Fib)"] = fib["resistance"]
        for ratio_label, price in (fib.get("levels") or {}).items():
            fib_lines[f"Fib {ratio_label}"] = price
        fib_method.update(
            {
                "support": fib.get("support"),
                "resistance": fib.get("resistance"),
                "status": (
                    "available"
                    if fib.get("support") is not None or fib.get("resistance") is not None
                    else "unavailable"
                ),
                "explanation": fib.get("explanation", "Retracements Fibonacci dérivés du swing dominant."),
                "inputs": {
                    **(fib.get("inputs") or {}),
                    "chart": _build_sr_chart(ohlcv, policy.structural_lookback, fib_lines),
                },
            }
        )
    methods.append(fib_method)

    finalized = finalize_support_resistance_methods(current_close, methods)
    summary = finalized["summary_explanation"]
    if trend_score_pct is not None:
        summary = (
            f"Contexte tendance: {trend_label} ({round_number(trend_score_pct, 2)}). "
            f"{summary}"
        )
    else:
        summary = f"Contexte tendance indisponible. {summary}"

    return {
        "symbol": symbol,
        "horizon": horizon,
        "timeframe": timeframe,
        "as_of": as_of,
        "current_close": round_number(current_close, 6),
        "trend_score_pct": round_number(trend_score_pct, 2) if trend_score_pct is not None else None,
        "trend_label": trend_label,
        "methods": finalized["methods"],
        "preview_support": finalized["final_support"],
        "preview_resistance": finalized["final_resistance"],
        "preview_support_method_id": finalized["selected_support_method_id"],
        "preview_resistance_method_id": finalized["selected_resistance_method_id"],
        "final_support": finalized["final_support"],
        "final_resistance": finalized["final_resistance"],
        "selected_support_method_id": finalized["selected_support_method_id"],
        "selected_resistance_method_id": finalized["selected_resistance_method_id"],
        "summary_explanation": summary,
    }


@router.post("/signal/support-resistance", response_model=SupportResistanceResponse)
def signal_support_resistance(body: SupportResistanceRequest, db: Session = Depends(get_db)):
    """Return informational support/resistance comparison for the signal page."""
    return _sr_compute_summary_support_resistance(
        db,
        symbol=body.symbol,
        horizon=body.horizon,
        timeframe=body.timeframe,
        cost_bps=body.cost_bps,
        cooldown_bars=body.cooldown_bars,
        variant=getattr(body, "variant", "expanded"),
    )


def _sr_prepare_context(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    timeframe: str,
    cost_bps: float,
    cooldown_bars: int,
    variant: str = "expanded",
) -> dict[str, Any]:
    try:
        ohlcv = load_ohlcv_for_symbol(db, symbol, timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    ohlcv = _truncate_for_horizon(ohlcv, horizon)
    ohlcv = _clean_ohlcv(ohlcv)
    if ohlcv.empty or len(ohlcv) < 2:
        raise HTTPException(status_code=422, detail=f"Insufficient data for {symbol}.")

    close = ohlcv["Close"].values.astype("float64")
    high = ohlcv["High"].values.astype("float64") if "High" in ohlcv.columns else None
    low = ohlcv["Low"].values.astype("float64") if "Low" in ohlcv.columns else None
    volume = ohlcv["Volume"].values.astype("float64") if "Volume" in ohlcv.columns else None
    current_close = float(close[-1])
    as_of = str(ohlcv.index[-1])[:10]

    family_snapshots: dict[str, dict[str, Any]] = {}
    trend_scores: list[float] = []
    for family in ALL_FAMILIES:
        try:
            detail = _get_or_compute(db, family, symbol, horizon, timeframe, cost_bps, cooldown_bars, variant=variant)
        except HTTPException:
            continue
        family_snapshots[family] = _signal_snapshot_from_detail(family, detail)
        if family_signal_is_available(detail.signal) and FAMILY_SIGNAL_TYPE.get(family) == "trend":
            trend_scores.append(float(detail.signal.family_score_pct))

    trend_score_pct = float(sum(trend_scores) / len(trend_scores)) if trend_scores else None
    trend_label = signal_type_label("trend", trend_score_pct) if trend_score_pct is not None else "Indisponible"
    return {
        "symbol": symbol,
        "horizon": horizon,
        "timeframe": timeframe,
        "as_of": as_of,
        "ohlcv": ohlcv,
        "close": close,
        "high": high,
        "low": low,
        "volume": volume,
        "current_close": current_close,
        "family_snapshots": family_snapshots,
        "trend_score_pct": trend_score_pct,
        "trend_label": trend_label,
        "ma_anchor_payload": compute_representative_ma_anchor(family_snapshots),
        "policy": build_execution_horizon_policy(horizon, timeframe=timeframe),
        "cost_bps": float(cost_bps),
        "cooldown_bars": int(cooldown_bars),
    }


def _sr_build_base_methods(context: dict[str, Any]) -> list[dict[str, Any]]:
    close = context["close"]
    high = context["high"]
    low = context["low"]
    volume = context["volume"]
    current_close = float(context["current_close"])
    ohlcv = context["ohlcv"]
    policy = context["policy"]

    ma_method = build_ma_anchor_method(
        context["ma_anchor_payload"],
        trend_score_pct=context["trend_score_pct"],
    )
    rep_count = len((context["ma_anchor_payload"].get("representatives") or []))
    if rep_count > 0:
        ma_method["explanation"] = (
            f"Moyenne ponderee des {rep_count} moyennes mobiles representatives, "
            "orientee par la tendance agregee."
        )
    methods: list[dict[str, Any]] = [ma_method]

    methods.append(
        {
            "id": "score_inversion",
            "label": "Seuils par inversion du score",
            "support": None,
            "resistance": None,
            "status": "ignored",
            "selected_for_support": False,
            "selected_for_resistance": False,
            "explanation": (
                "Calcul desactive sur le chargement principal. "
                "Le detail de cette methode est calcule a la demande."
            ),
            "inputs": {
                "thresholds": {"buy": 15.0, "sell": -15.0},
                "method": "rep_inversion_v2",
                "on_demand": True,
            },
        }
    )

    if high is not None and low is not None and len(close) >= 3:
        swing_levels = detect_swing_levels(
            high,
            low,
            close,
            left_bars=policy.swing_left_bars,
            right_bars=policy.swing_right_bars,
            max_levels=policy.max_levels,
            lookback=policy.structural_lookback,
            max_distance_atr=policy.max_level_distance_atr,
        )
        methods.append(
            {
                "id": "swing_levels",
                "label": "Swings structurels",
                "support": swing_levels.get("nearest_support"),
                "resistance": swing_levels.get("nearest_resistance"),
                "status": (
                    "available"
                    if swing_levels.get("nearest_support") is not None
                    or swing_levels.get("nearest_resistance") is not None
                    else "unavailable"
                ),
                "selected_for_support": False,
                "selected_for_resistance": False,
                "explanation": (
                    "Niveaux pivots historiques identifies a partir des sommets (resistances) "
                    f"et creux (supports) locaux sur les {policy.structural_lookback} dernieres barres."
                ),
                "inputs": {
                    "lookback": policy.structural_lookback,
                    "left_bars": policy.swing_left_bars,
                    "right_bars": policy.swing_right_bars,
                    "max_levels": policy.max_levels,
                    "supports": swing_levels.get("supports") or [],
                    "resistances": swing_levels.get("resistances") or [],
                    "support_lines": {
                        f"S{idx}": round_number(entry.get("price"), 6)
                        for idx, entry in enumerate(swing_levels.get("supports") or [], start=1)
                        if isinstance(entry, dict)
                        and round_number(entry.get("price"), 6) is not None
                        and float(round_number(entry.get("price"), 6)) <= current_close
                    },
                    "resistance_lines": {
                        f"R{idx}": round_number(entry.get("price"), 6)
                        for idx, entry in enumerate(swing_levels.get("resistances") or [], start=1)
                        if isinstance(entry, dict)
                        and round_number(entry.get("price"), 6) is not None
                        and float(round_number(entry.get("price"), 6)) >= current_close
                    },
                },
            }
        )
    else:
        methods.append(
            {
                "id": "swing_levels",
                "label": "Swings structurels",
                "support": None,
                "resistance": None,
                "status": "unavailable",
                "selected_for_support": False,
                "selected_for_resistance": False,
                "explanation": "High/Low insuffisants pour calculer les swings historiques.",
                "inputs": {},
            }
        )

    methods.extend(
        [
            _sr_build_pivot_family_method(
                context,
                "pivot_points",
                "Pivots classiques",
                "Pivots classiques (P, S1-S3, R1-R3) bases sur le Haut, Bas, Cloture de la seance precedente.",
            ),
            _sr_build_pivot_family_method(
                context,
                "fibonacci_pivot",
                "Pivots Fibonacci",
                "Pivots Fibonacci: P classique puis extensions 38.2%, 61.8% et 100% de l'amplitude precedente.",
            ),
            _sr_build_pivot_family_method(
                context,
                "camarilla",
                "Pivots Camarilla",
                "Pivots Camarilla: niveaux S1-S3/R1-R3 construits autour de la cloture precedente.",
            ),
            _sr_build_pivot_family_method(
                context,
                "woodie",
                "Pivots Woodie",
                "Pivots Woodie: pivot pondere par la cloture precedente puis S1-S3/R1-R3.",
            ),
            _sr_build_pivot_family_method(
                context,
                "dm",
                "Pivots DeMark",
                "Pivots DeMark: P, S1 et R1 conditionnes par la relation entre ouverture et cloture precedentes.",
            ),
        ]
    )

    quantile_method = {
        "id": "quantile_extrema_atr",
        "label": "Quantiles + extremes + ATR",
        "support": None,
        "resistance": None,
        "status": "unavailable",
        "selected_for_support": False,
        "selected_for_resistance": False,
        "explanation": "Donnees OHLC insuffisantes pour calculer les bornes de volatilite.",
        "inputs": {},
    }
    if high is not None and low is not None:
        quantile_levels = compute_levels_support_resistance(
            pd.DataFrame(
                {
                    "Open": ohlcv["Open"].values.astype("float64") if "Open" in ohlcv.columns else close,
                    "High": high,
                    "Low": low,
                    "Close": close,
                    "Volume": volume if volume is not None else np.zeros(len(close), dtype="float64"),
                }
            ),
            direction=0,
        )
        quantile_method.update(
            {
                "support": quantile_levels.get("support"),
                "resistance": quantile_levels.get("resistance"),
                "status": (
                    "available"
                    if quantile_levels.get("support") is not None or quantile_levels.get("resistance") is not None
                    else "unavailable"
                ),
                "explanation": str(
                    quantile_levels.get("explain")
                    or "Zones derivees des quantiles historiques extremes et de l'ATR."
                ),
                "inputs": {
                    **dict(quantile_levels.get("inputs") or {}),
                    "support_lines": (
                        {"S1": round_number(quantile_levels.get("support"), 6)}
                        if round_number(quantile_levels.get("support"), 6) is not None
                        and float(round_number(quantile_levels.get("support"), 6)) <= current_close
                        else {}
                    ),
                    "resistance_lines": (
                        {"R1": round_number(quantile_levels.get("resistance"), 6)}
                        if round_number(quantile_levels.get("resistance"), 6) is not None
                        and float(round_number(quantile_levels.get("resistance"), 6)) >= current_close
                        else {}
                    ),
                },
            }
        )
    methods.append(quantile_method)

    fib_method: dict[str, Any] = {
        "id": "fibonacci_retracement",
        "label": "Retracements Fibonacci",
        "support": None,
        "resistance": None,
        "status": "unavailable",
        "selected_for_support": False,
        "selected_for_resistance": False,
        "explanation": "Données OHLC insuffisantes pour calculer les retracements Fibonacci.",
        "inputs": {},
    }
    if high is not None and low is not None and len(close) >= 30:
        fib = compute_fibonacci_retracement_levels(
            high,
            low,
            close,
            lookback=policy.structural_lookback,
            left_bars=policy.swing_left_bars,
            right_bars=policy.swing_right_bars,
        )
        fib_level_map: dict[str, float] = {}
        raw_fib_levels = fib.get("levels") if isinstance(fib.get("levels"), dict) else {}
        for raw_ratio, raw_price in raw_fib_levels.items():
            ratio_value = _sr_finite_float(raw_ratio)
            price_value = round_number(raw_price, 6)
            if ratio_value is None or price_value is None:
                continue
            fib_level_map[f"F{int(round(ratio_value * 1000)):03d}"] = price_value
        fib_support_lines, fib_resistance_lines = split_support_resistance_lines(
            fib_level_map,
            current_close,
        )
        fib_inputs = dict(fib.get("inputs") or {})
        fib_inputs["lines"] = fib_level_map
        fib_inputs["support_lines"] = fib_support_lines
        fib_inputs["resistance_lines"] = fib_resistance_lines
        fib_method.update(
            {
                "support": fib.get("support"),
                "resistance": fib.get("resistance"),
                "status": (
                    "available"
                    if fib.get("support") is not None or fib.get("resistance") is not None
                    else "unavailable"
                ),
                "explanation": fib.get("explanation", "Retracements Fibonacci dérivés du swing dominant."),
                "inputs": fib_inputs,
            }
        )
    methods.append(fib_method)
    return [_sr_enrich_method_lines(method, current_close) for method in methods]


def _sr_add_line(lines: dict[str, float], label: str, value: Any) -> None:
    numeric = round_number(value, 6)
    if numeric is not None:
        lines[label] = numeric


def _sr_line_maps_from_method(
    method: dict[str, Any],
    current_close: float,
) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    inputs = method.get("inputs") if isinstance(method.get("inputs"), dict) else {}
    raw_lines = inputs.get("lines") if isinstance(inputs.get("lines"), dict) else {}
    raw_support = inputs.get("support_lines") if isinstance(inputs.get("support_lines"), dict) else {}
    raw_resistance = inputs.get("resistance_lines") if isinstance(inputs.get("resistance_lines"), dict) else {}

    lines: dict[str, float] = {}
    for raw_line, raw_value in raw_lines.items():
        line = normalize_line_id(raw_line)
        value = round_number(raw_value, 6)
        if line and value is not None:
            lines[line] = value

    support_lines: dict[str, float] = {}
    for raw_line, raw_value in raw_support.items():
        line = normalize_line_id(raw_line)
        value = round_number(raw_value, 6)
        if line and value is not None and value <= current_close:
            support_lines[line] = value

    resistance_lines: dict[str, float] = {}
    for raw_line, raw_value in raw_resistance.items():
        line = normalize_line_id(raw_line)
        value = round_number(raw_value, 6)
        if line and value is not None and value >= current_close:
            resistance_lines[line] = value

    if lines and (not support_lines or not resistance_lines):
        split_support, split_resistance = split_support_resistance_lines(lines, current_close)
        support_lines = support_lines or split_support
        resistance_lines = resistance_lines or split_resistance

    raw_support_value = round_number(method.get("support"), 6)
    raw_resistance_value = round_number(method.get("resistance"), 6)
    if raw_support_value is not None and raw_support_value <= current_close and not support_lines:
        support_lines["S1"] = raw_support_value
    if raw_resistance_value is not None and raw_resistance_value >= current_close and not resistance_lines:
        resistance_lines["R1"] = raw_resistance_value

    return lines, support_lines, resistance_lines


def _sr_enrich_method_lines(method: dict[str, Any], current_close: float) -> dict[str, Any]:
    row = dict(method)
    inputs = dict(row.get("inputs") or {})
    row["inputs"] = inputs

    lines, support_lines, resistance_lines = _sr_line_maps_from_method(row, current_close)
    if lines:
        inputs["lines"] = lines
    if support_lines:
        inputs["support_lines"] = support_lines
    if resistance_lines:
        inputs["resistance_lines"] = resistance_lines

    support_line: str | None = None
    support_value: float | None = None
    if support_lines:
        support_line, support_value = max(support_lines.items(), key=lambda item: item[1])

    resistance_line: str | None = None
    resistance_value: float | None = None
    if resistance_lines:
        resistance_line, resistance_value = min(resistance_lines.items(), key=lambda item: item[1])

    if support_value is not None:
        row["support"] = round_number(support_value, 6)
        inputs["selected_support_line"] = support_line
    if resistance_value is not None:
        row["resistance"] = round_number(resistance_value, 6)
        inputs["selected_resistance_line"] = resistance_line

    if support_value is not None or resistance_value is not None:
        if str(row.get("status") or "unavailable") == "unavailable":
            row["status"] = "available"
    return row


def _sr_support_resistance_lines_for_levels(
    levels: dict[str, Any],
    current_close: float,
) -> tuple[dict[str, float], dict[str, float], float | None, float | None, str | None, str | None]:
    support_lines, resistance_lines = split_support_resistance_lines(levels, current_close)
    support, resistance, support_line, resistance_line = nearest_support_resistance_from_lines(
        levels,
        current_close,
    )
    return support_lines, resistance_lines, support, resistance, support_line, resistance_line


def _sr_build_pivot_family_method(
    context: dict[str, Any],
    method_id: str,
    label: str,
    explanation: str,
) -> dict[str, Any]:
    ohlcv = context["ohlcv"]
    high = context["high"]
    low = context["low"]
    current_close = float(context["current_close"])
    method = {
        "id": method_id,
        "label": label,
        "support": None,
        "resistance": None,
        "status": "unavailable",
        "selected_for_support": False,
        "selected_for_resistance": False,
        "explanation": "Au moins deux barres OHLC sont requises pour ce pivot.",
        "inputs": {},
    }
    if len(ohlcv) < 2 or high is None or low is None:
        return method

    prev = ohlcv.iloc[-2]
    prev_open = float(prev["Open"]) if "Open" in ohlcv.columns else None
    levels = compute_pivot_family_levels(
        method_id,
        prev_high=float(prev["High"]),
        prev_low=float(prev["Low"]),
        prev_close=float(prev["Close"]),
        prev_open=prev_open,
    )
    if not levels:
        method["explanation"] = "Niveaux indisponibles pour cette famille de pivots."
        return method

    support_lines, resistance_lines, support, resistance, support_line, resistance_line = (
        _sr_support_resistance_lines_for_levels(levels, current_close)
    )
    method.update(
        {
            "support": support,
            "resistance": resistance,
            "status": "available" if support_lines or resistance_lines else "ignored",
            "explanation": explanation,
            "inputs": {
                "lines": levels,
                "support_lines": support_lines,
                "resistance_lines": resistance_lines,
                "selected_support_line": support_line,
                "selected_resistance_line": resistance_line,
                "prev_open": prev_open,
                "prev_high": float(prev["High"]),
                "prev_low": float(prev["Low"]),
                "prev_close": float(prev["Close"]),
            },
        }
    )
    for line, value in levels.items():
        method["inputs"][line.lower()] = value
    return method


def _sr_build_ma_time_series(
    close: np.ndarray,
    representatives: list[dict[str, Any]],
    tail_len: int,
) -> dict[str, list[float | None]]:
    ts_lines: dict[str, list[float | None]] = {}
    for rep in representatives:
        params = rep.get("params") if isinstance(rep.get("params"), dict) else {}
        archetype = str(rep.get("archetype") or "price_vs_sma")
        variant_id = str(rep.get("variant_id") or "ma_rep")
        rep_label = str(rep.get("label") or "").strip()
        if not rep_label:
            window = params.get("window", params.get("span", "?"))
            rep_label = f"{'EMA' if 'ema' in archetype else 'SMA'} {window}"
        weight = round_number(rep.get("normalized_weight"), 3)
        indicator_value = round_number(rep.get("indicator_value"), 4)
        display = rep_label
        if weight is not None or indicator_value is not None:
            parts = []
            if weight is not None:
                parts.append(f"w {weight}")
            if indicator_value is not None:
                parts.append(f"v {indicator_value}")
            display = f"{rep_label} ({', '.join(parts)})"

        variant = VariantDef(
            variant_id=variant_id,
            family="sma",
            archetype=archetype,
            params=params,
            description=rep_label,
        )
        try:
            indicator_payload = _compute_indicator(close, variant)
            values = indicator_payload.get("values") if isinstance(indicator_payload, dict) else None
            if isinstance(values, np.ndarray):
                ts_lines[display] = [_safe_float(v) for v in values[-tail_len:]]
        except Exception:
            continue
    return ts_lines


def _sr_build_method_chart(
    method_id: str,
    method: dict[str, Any],
    context: dict[str, Any],
    finalized: dict[str, Any],
) -> dict[str, Any] | None:
    ohlcv = context["ohlcv"]
    close = context["close"]
    policy = context["policy"]
    lines: dict[str, float] = {}
    time_series_lines: dict[str, list[float | None]] = {}
    tail_len = min(140, len(ohlcv))

    _sr_add_line(lines, "Support preview", finalized.get("final_support"))
    _sr_add_line(lines, "Resistance preview", finalized.get("final_resistance"))

    if method_id == "ma_anchor":
        tail_len = min(180, len(ohlcv))
        reps = method.get("inputs", {}).get("representatives")
        representatives = reps if isinstance(reps, list) else []
        time_series_lines = _sr_build_ma_time_series(close, representatives, tail_len)
        _sr_add_line(lines, "Moyenne ponderee", method.get("inputs", {}).get("anchor"))
        _sr_add_line(lines, "Support MA", method.get("support"))
        _sr_add_line(lines, "Resistance MA", method.get("resistance"))
    elif method_id == "score_inversion":
        tail_len = min(180, len(ohlcv))
        _sr_add_line(lines, "Support inversion", method.get("support"))
        _sr_add_line(lines, "Resistance inversion", method.get("resistance"))
        _sr_add_line(lines, "Reference MA", method.get("inputs", {}).get("support_reference"))
    elif method_id == "swing_levels":
        tail_len = min(int(policy.structural_lookback), len(ohlcv))
        _sr_add_line(lines, "Support swing", method.get("support"))
        _sr_add_line(lines, "Resistance swing", method.get("resistance"))
        supports = method.get("inputs", {}).get("supports")
        resistances = method.get("inputs", {}).get("resistances")
        if isinstance(supports, list):
            for idx, entry in enumerate(supports[:3], start=1):
                if isinstance(entry, dict):
                    _sr_add_line(lines, f"Swing S{idx}", entry.get("price"))
        if isinstance(resistances, list):
            for idx, entry in enumerate(resistances[:3], start=1):
                if isinstance(entry, dict):
                    _sr_add_line(lines, f"Swing R{idx}", entry.get("price"))
    elif method_id in {"pivot_points", "fibonacci_pivot", "camarilla", "woodie", "dm"}:
        tail_len = min(30, len(ohlcv))
        inputs = method.get("inputs", {})
        raw_lines = inputs.get("lines") if isinstance(inputs.get("lines"), dict) else {}
        if raw_lines:
            for label, value in raw_lines.items():
                _sr_add_line(lines, str(label), value)
        else:
            _sr_add_line(lines, "P", inputs.get("p") or inputs.get("pp"))
            for label in ("S1", "S2", "S3", "R1", "R2", "R3"):
                _sr_add_line(lines, label, inputs.get(label.lower()))
    elif method_id == "quantile_extrema_atr":
        tail_len = min(120, len(ohlcv))
        _sr_add_line(lines, "Support quantile", method.get("support"))
        _sr_add_line(lines, "Resistance quantile", method.get("resistance"))
        inputs = method.get("inputs", {})
        _sr_add_line(lines, "Q20 support", inputs.get("support_q20"))
        _sr_add_line(lines, "Q80 resistance", inputs.get("resistance_q80"))
    elif method_id == "fibonacci_retracement":
        tail_len = min(int(policy.structural_lookback), len(ohlcv))
        inputs = method.get("inputs", {})
        raw_lines = inputs.get("lines") if isinstance(inputs.get("lines"), dict) else {}
        for label, value in raw_lines.items():
            _sr_add_line(lines, str(label), value)
        _sr_add_line(lines, "Support fib", method.get("support"))
        _sr_add_line(lines, "Resistance fib", method.get("resistance"))
    else:
        return None

    if not lines and not time_series_lines:
        return None
    return _build_sr_chart(ohlcv, tail_len, horizontal_lines=lines, time_series_lines=time_series_lines)


def _sr_get_score_inversion_levels(
    context: dict[str, Any],
    *,
    cost_bps: float,
    cooldown_bars: int,
) -> tuple[dict[str, Any], bool]:
    key = (
        context["symbol"],
        context["horizon"],
        context["timeframe"],
        context["as_of"],
        round(float(cost_bps), 4),
        int(cooldown_bars),
    )
    now = time.monotonic()
    cached = _SR_INVERSION_CACHE.get(key)
    if cached and (now - cached[0]) < _SR_INVERSION_CACHE_TTL:
        return cached[1], True

    levels = compute_score_inversion_levels(
        context["close"],
        context["volume"],
        context["family_snapshots"],
        high=context["high"],
        low=context["low"],
        scan_points=_SR_INVERSION_SCAN_POINTS,
        refine_steps=_SR_INVERSION_REFINE_STEPS,
        max_evals=_SR_INVERSION_MAX_EVALS,
        support_scan_multipliers=(0.9, 0.75, 0.6, 0.45),
        resistance_scan_multipliers=(1.1, 1.25, 1.5, 2.0, 2.8),
    )
    _SR_INVERSION_CACHE[key] = (now, levels)
    return levels, False


def _sr_get_cached_variants_payload(context: dict[str, Any]) -> dict[str, Any] | None:
    key = _sr_variants_cache_key(
        context["symbol"],
        context["horizon"],
        context["timeframe"],
        context["as_of"],
        float(context.get("cost_bps", 10.0)),
        int(context.get("cooldown_bars", 0)),
    )
    cached = _SR_VARIANTS_CACHE.get(key)
    if not cached:
        return None
    cached_at, payload = cached
    if (time.monotonic() - cached_at) >= _SR_VARIANTS_CACHE_TTL:
        return None
    return payload


def _sr_cached_optimal_fields(context: dict[str, Any]) -> dict[str, Any]:
    cached_payload = _sr_get_cached_variants_payload(context)
    response = cached_payload.get("response") if isinstance(cached_payload, dict) else None
    if not isinstance(response, dict):
        return {
            "optimal_support": None,
            "optimal_resistance": None,
            "optimal_variant_id": None,
            "optimal_status": "pending",
        }
    best_variant_id = response.get("best_variant_id")
    status = "ready" if best_variant_id else "unavailable"
    return {
        "optimal_support": response.get("final_support"),
        "optimal_resistance": response.get("final_resistance"),
        "optimal_variant_id": best_variant_id,
        "optimal_status": status,
    }


def _sr_summary_payload(context: dict[str, Any], finalized: dict[str, Any]) -> dict[str, Any]:
    trend_score_pct = context["trend_score_pct"]
    trend_label = context["trend_label"]
    summary = str(finalized["summary_explanation"])
    if trend_score_pct is not None:
        summary = f"Contexte tendance: {trend_label} ({round_number(trend_score_pct, 2)}). {summary}"
    else:
        summary = f"Contexte tendance indisponible. {summary}"
    optimal = _sr_cached_optimal_fields(context)
    final_support = optimal["optimal_support"] if optimal["optimal_status"] == "ready" else None
    final_resistance = optimal["optimal_resistance"] if optimal["optimal_status"] == "ready" else None
    selected_support_method_id = None
    selected_resistance_method_id = None
    selected_support_line_id = None
    selected_resistance_line_id = None
    if optimal["optimal_status"] == "ready" and optimal["optimal_variant_id"]:
        try:
            (
                selected_support_method_id,
                selected_support_line_id,
                selected_resistance_method_id,
                selected_resistance_line_id,
            ) = _sr_parse_variant_components(str(optimal["optimal_variant_id"]))
        except HTTPException:
            selected_support_method_id = None
            selected_resistance_method_id = None
    return {
        "symbol": context["symbol"],
        "horizon": context["horizon"],
        "timeframe": context["timeframe"],
        "as_of": context["as_of"],
        "current_close": round_number(context["current_close"], 6),
        "trend_score_pct": round_number(trend_score_pct, 2) if trend_score_pct is not None else None,
        "trend_label": trend_label,
        "methods": finalized["methods"],
        "preview_support": finalized["final_support"],
        "preview_resistance": finalized["final_resistance"],
        "preview_support_method_id": finalized["selected_support_method_id"],
        "preview_resistance_method_id": finalized["selected_resistance_method_id"],
        "optimal_support": optimal["optimal_support"],
        "optimal_resistance": optimal["optimal_resistance"],
        "optimal_variant_id": optimal["optimal_variant_id"],
        "optimal_status": optimal["optimal_status"],
        "final_support": final_support,
        "final_resistance": final_resistance,
        "selected_support_method_id": selected_support_method_id,
        "selected_resistance_method_id": selected_resistance_method_id,
        "selected_support_line_id": selected_support_line_id,
        "selected_resistance_line_id": selected_resistance_line_id,
        "summary_explanation": (
            f"{summary} Optimal SR: {optimal['optimal_status']}."
        ),
    }


def _sr_compute_summary_support_resistance(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    timeframe: str,
    cost_bps: float,
    cooldown_bars: int,
    variant: str = "expanded",
) -> dict[str, Any]:
    context = _sr_prepare_context(
        db,
        symbol=symbol,
        horizon=horizon,
        timeframe=timeframe,
        cost_bps=cost_bps,
        cooldown_bars=cooldown_bars,
        variant=variant,
    )
    methods = _sr_build_base_methods(context)
    finalized = finalize_support_resistance_methods(context["current_close"], methods)
    return _sr_summary_payload(context, finalized)


def _compute_signal_page_support_resistance_method_detail(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    timeframe: str,
    method_id: str,
    cost_bps: float,
    cooldown_bars: int,
    variant: str = "expanded",
) -> dict[str, Any]:
    context = _sr_prepare_context(
        db,
        symbol=symbol,
        horizon=horizon,
        timeframe=timeframe,
        cost_bps=cost_bps,
        cooldown_bars=cooldown_bars,
        variant=variant,
    )
    methods = _sr_build_base_methods(context)

    if method_id == "score_inversion":
        score_levels, from_cache = _sr_get_score_inversion_levels(
            context,
            cost_bps=cost_bps,
            cooldown_bars=cooldown_bars,
        )
        support = score_levels.get("support_buy_trigger")
        resistance = score_levels.get("resistance_sell_trigger")
        score_inputs = dict(score_levels.get("inputs") or {})
        budget_exceeded = bool(score_inputs.get("budget_exceeded"))
        status = (
            "available"
            if support is not None or resistance is not None
            else ("ignored" if budget_exceeded else "unavailable")
        )
        explanation = (
            "Prix theorique ou le score agrege bascule en zone achat/vente."
            if status == "available"
            else (
                "Budget de calcul atteint avant de trouver des seuils fiables."
                if budget_exceeded
                else "Aucun seuil detecte dans la grille de recherche."
            )
        )
        score_method = {
            "id": "score_inversion",
            "label": "Seuils par inversion du score",
            "support": support,
            "resistance": resistance,
            "status": status,
            "selected_for_support": False,
            "selected_for_resistance": False,
            "explanation": explanation,
            "inputs": {
                "close_used": score_levels.get("close_used"),
                "support_reference": score_levels.get("support_reference"),
                "thresholds": score_levels.get("thresholds") or {"buy": 15.0, "sell": -15.0},
                "method": score_levels.get("method") or "rep_inversion_v2",
                "cached": from_cache,
                **score_inputs,
            },
        }
        methods = [score_method if str(item.get("id")) == "score_inversion" else item for item in methods]

    finalized = finalize_support_resistance_methods(context["current_close"], methods)
    by_id = {str(item.get("id")): item for item in finalized["methods"]}
    if method_id not in by_id:
        raise HTTPException(status_code=422, detail=f"Unsupported method_id: {method_id}")

    method = dict(by_id[method_id])
    chart = _sr_build_method_chart(method_id, method, context, finalized)
    method_inputs = dict(method.get("inputs") or {})
    if chart is not None:
        method_inputs["chart"] = chart
    method["inputs"] = method_inputs

    payload = _sr_summary_payload(context, finalized)
    payload["method_id"] = method_id
    payload["method"] = method
    payload["chart"] = chart
    return payload


@router.post("/signal/support-resistance/method-detail", response_model=SupportResistanceMethodDetailResponse)
def signal_support_resistance_method_detail(
    body: SupportResistanceMethodDetailRequest,
    db: Session = Depends(get_db),
):
    """Return method-level support/resistance detail with chart-ready payload."""
    return _compute_signal_page_support_resistance_method_detail(
        db,
        symbol=body.symbol,
        horizon=body.horizon,
        timeframe=body.timeframe,
        method_id=body.method_id,
        cost_bps=body.cost_bps,
        cooldown_bars=body.cooldown_bars,
        variant=getattr(body, "variant", "expanded"),
    )


_SR_VARIANT_METHOD_ORDER = (
    "ma_anchor",
    "score_inversion",
    "swing_levels",
    "pivot_points",
    "fibonacci_pivot",
    "camarilla",
    "woodie",
    "dm",
    "quantile_extrema_atr",
    "fibonacci_retracement",
)


def _sr_method_rank(method_id: str) -> int:
    try:
        return _SR_VARIANT_METHOD_ORDER.index(method_id)
    except ValueError:
        return len(_SR_VARIANT_METHOD_ORDER)


def _sr_line_rank(line_id: str | None) -> int:
    line = normalize_line_id(line_id)
    order = {
        "P": 0,
        "S1": 1,
        "R1": 1,
        "S2": 2,
        "R2": 2,
        "S3": 3,
        "R3": 3,
    }
    if line in order:
        return order[line]
    if line.startswith("F"):
        return 10
    return 99


def _sr_method_line_options(method: dict[str, Any], side: str) -> list[dict[str, Any]]:
    method_id = str(method.get("id") or "").strip()
    if not method_id or str(method.get("status")) != "available":
        return []
    inputs = method.get("inputs") if isinstance(method.get("inputs"), dict) else {}
    key = "support_lines" if side == "support" else "resistance_lines"
    raw_lines = inputs.get(key) if isinstance(inputs.get(key), dict) else {}
    options: list[dict[str, Any]] = []
    for raw_line, raw_value in raw_lines.items():
        line = normalize_line_id(raw_line)
        value = round_number(raw_value, 6)
        if not line or value is None:
            continue
        options.append(
            {
                "method_id": method_id,
                "line_id": line,
                "level": value,
                "method_label": str(method.get("label") or method_id),
                "line_label": line,
            }
        )
    if not options:
        fallback_value = round_number(method.get(side), 6)
        if fallback_value is not None:
            options.append(
                {
                    "method_id": method_id,
                    "line_id": "S1" if side == "support" else "R1",
                    "level": fallback_value,
                    "method_label": str(method.get("label") or method_id),
                    "line_label": "S1" if side == "support" else "R1",
                }
            )
    options.sort(
        key=lambda item: (
            _sr_method_rank(str(item["method_id"])),
            _sr_line_rank(str(item.get("line_id") or "")),
            str(item.get("line_id") or ""),
        )
    )
    return options


def _sr_component_id(method_id: str, line_id: str | None = None) -> str:
    method = str(method_id or "").strip()
    line = normalize_line_id(line_id)
    return f"{method}:{line}" if line else method


def _sr_variant_id(
    support_method_id: str,
    resistance_method_id: str,
    support_line_id: str | None = None,
    resistance_line_id: str | None = None,
) -> str:
    return (
        f"sr:{_sr_component_id(support_method_id, support_line_id)}"
        f"__{_sr_component_id(resistance_method_id, resistance_line_id)}"
    )


def _sr_parse_component_id(component_id: str) -> tuple[str, str | None]:
    raw = str(component_id or "").strip()
    if not raw:
        return "", None
    if ":" not in raw:
        return raw, None
    method_id, line_id = raw.split(":", 1)
    return method_id, normalize_line_id(line_id) or None


def _sr_parse_variant_id(variant_id: str) -> tuple[str, str]:
    raw = str(variant_id or "").strip()
    if not raw.startswith("sr:"):
        raise HTTPException(status_code=422, detail=f"Invalid SR variant id: {variant_id!r}")
    payload = raw[3:]
    if "__" not in payload:
        raise HTTPException(status_code=422, detail=f"Invalid SR variant id: {variant_id!r}")
    support_method_id, resistance_method_id = payload.split("__", 1)
    if not support_method_id or not resistance_method_id:
        raise HTTPException(status_code=422, detail=f"Invalid SR variant id: {variant_id!r}")
    support_method_id, _support_line_id = _sr_parse_component_id(support_method_id)
    resistance_method_id, _resistance_line_id = _sr_parse_component_id(resistance_method_id)
    if not support_method_id or not resistance_method_id:
        raise HTTPException(status_code=422, detail=f"Invalid SR variant id: {variant_id!r}")
    return support_method_id, resistance_method_id


def _sr_parse_variant_components(variant_id: str) -> tuple[str, str | None, str, str | None]:
    raw = str(variant_id or "").strip()
    if not raw.startswith("sr:"):
        raise HTTPException(status_code=422, detail=f"Invalid SR variant id: {variant_id!r}")
    payload = raw[3:]
    if "__" not in payload:
        raise HTTPException(status_code=422, detail=f"Invalid SR variant id: {variant_id!r}")
    support_component, resistance_component = payload.split("__", 1)
    support_method_id, support_line_id = _sr_parse_component_id(support_component)
    resistance_method_id, resistance_line_id = _sr_parse_component_id(resistance_component)
    if not support_method_id or not resistance_method_id:
        raise HTTPException(status_code=422, detail=f"Invalid SR variant id: {variant_id!r}")
    return support_method_id, support_line_id, resistance_method_id, resistance_line_id


def _sr_signal_from_levels(current_close: float, support: float | None, resistance: float | None) -> tuple[float, str]:
    if support is not None and current_close <= support:
        return 1.0, "HAUSSIER"
    if resistance is not None and current_close >= resistance:
        return -1.0, "BAISSIER"
    return 0.0, "NEUTRE"


def _sr_methodology_context(horizon: str, available_bars: int) -> dict[str, Any]:
    hp = HORIZON_PARAMS.get(horizon, HORIZON_PARAMS["monthly"])
    nominal = {
        "train": int(hp["train"]),
        "test": int(hp["test"]),
        "step": int(hp["step"]),
        "target_windows": 0,
    }
    return {
        "methodology_mode": "sr_dynamic_touch",
        "available_bars": int(available_bars),
        "nominal_window": nominal,
        "effective_window": nominal,
        "warning_message": "",
        "is_provisional": False,
    }


def _sr_window_plan(horizon: str, n_bars: int) -> list[tuple[int, int, int, int, int]]:
    hp = HORIZON_PARAMS.get(horizon, HORIZON_PARAMS["monthly"])
    train_len = int(hp["train"])
    test_len = int(hp["test"])
    step = int(hp["step"])
    if n_bars < (train_len + test_len + 1):
        return []
    windows: list[tuple[int, int, int, int, int]] = []
    window_index = 0
    for start in range(0, n_bars - train_len - test_len, step):
        train_end = start + train_len
        test_start = train_end
        test_end = min(test_start + test_len, n_bars - 1)
        oos_len = test_end - test_start
        if oos_len < 2:
            continue
        windows.append((window_index, start, train_end, test_start, test_end))
        window_index += 1
    return windows


def _sr_ranking_window(horizon: str, n_bars: int) -> tuple[int, int, int, int, int] | None:
    if n_bars < 22:
        return None
    hp = HORIZON_PARAMS.get(horizon, HORIZON_PARAMS["monthly"])
    lookback = min(n_bars - 1, max(int(hp["test"]), min(int(hp["train"]), 504)))
    test_start = max(0, n_bars - lookback - 1)
    test_end = n_bars - 1
    if test_end - test_start < 20:
        return None
    return (0, 0, test_start, test_start, test_end)


def _sr_max_drawdown(returns: np.ndarray) -> float:
    if returns.size == 0:
        return 0.0
    equity = np.cumprod(1.0 + returns.astype("float64"))
    if equity.size == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    drawdown = (peak - equity) / np.where(peak > 0.0, peak, 1.0)
    if drawdown.size == 0:
        return 0.0
    return float(np.nanmax(drawdown))


def _sr_clamp01(value: float) -> float:
    if not np.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, float(value)))


def _sr_direct_objective_summary(
    variant: VariantDef,
    *,
    returns: np.ndarray,
    fills: list[dict[str, Any]],
    total_realized_1u: float,
    n_bars: int,
) -> tuple[VariantRobustnessSummary, dict[str, float]]:
    safe_returns = returns.astype("float64") if isinstance(returns, np.ndarray) else np.zeros(0, dtype="float64")
    total_return = float(np.prod(1.0 + safe_returns) - 1.0) if safe_returns.size > 0 else 0.0
    cagr = (1.0 + total_return) ** (252.0 / max(int(n_bars), 1)) - 1.0 if total_return > -1.0 else -1.0
    sharpe = sharpe_ratio(safe_returns) if safe_returns.size > 1 else 0.0
    if not np.isfinite(sharpe):
        sharpe = 0.0
    max_drawdown = _sr_max_drawdown(safe_returns)
    closing_fills = [
        fill
        for fill in fills
        if str(fill.get("side") or "").upper() == "VENTE" and float(fill.get("pnl_realise", 0.0)) != 0.0
    ]
    n_trades = len(closing_fills)
    win_rate = (
        sum(1 for fill in closing_fills if float(fill.get("pnl_realise", 0.0)) > 0.0) / n_trades
        if n_trades > 0
        else 0.0
    )

    net_return_score = _sr_clamp01(0.5 + total_return * 2.5)
    consistency_score = _sr_clamp01(win_rate)
    drawdown_score = _sr_clamp01(1.0 - (max_drawdown / 0.25))
    trade_activity_score = _sr_clamp01(n_trades / 3.0)
    sr_objective_score = (
        0.45 * net_return_score
        + 0.25 * consistency_score
        + 0.20 * drawdown_score
        + 0.10 * trade_activity_score
    )
    is_viable = bool(n_bars >= 20 and n_trades > 0)

    summary = VariantRobustnessSummary(
        variant=variant,
        n_oos_windows=1 if n_bars >= 20 else 0,
        n_valid_windows=1 if is_viable else 0,
        mean_sharpe=float(sharpe),
        std_sharpe=0.0,
        median_sharpe=float(sharpe),
        fraction_positive_windows=float(win_rate),
        mean_max_drawdown=float(max_drawdown),
        reliability_score=float(sr_objective_score if is_viable else 0.0),
        is_viable=is_viable,
        sharpe_score=_sr_clamp01(0.5 + float(sharpe) / 4.0),
        stability_score=drawdown_score,
        consistency_score=consistency_score,
        drawdown_score=drawdown_score,
        cagr=float(cagr),
        total_pnl=float(100_000.0 * total_return),
    )
    parts = {
        "sr_objective_score": float(summary.reliability_score),
        "net_return_score": float(net_return_score),
        "consistency_score": float(consistency_score),
        "drawdown_score": float(drawdown_score),
        "trade_activity_score": float(trade_activity_score),
        "n_trades": float(n_trades),
        "total_return": float(total_return),
        "cagr": float(cagr),
        "max_drawdown": float(max_drawdown),
        "win_rate": float(win_rate),
        "total_pnl_realise_1u": float(total_realized_1u),
    }
    return summary, parts


def _sr_simulate_pair_window(
    *,
    context: dict[str, Any],
    method_series: dict[str, dict[str, Any]],
    support_method_id: str,
    resistance_method_id: str,
    support_line_id: str | None = None,
    resistance_line_id: str | None = None,
    window: tuple[int, int, int, int, int],
    cost_bps: float,
    cooldown_bars: int,
) -> tuple[OOSWindowResult | None, dict[str, Any] | None]:
    close = context["close"]
    high = context["high"]
    low = context["low"]
    if high is None or low is None:
        return None, None
    support_series = _sr_get_component_series(
        method_series,
        support_method_id,
        support_line_id,
        "support",
    )
    resistance_series = _sr_get_component_series(
        method_series,
        resistance_method_id,
        resistance_line_id,
        "resistance",
    )
    if (
        not isinstance(support_series, np.ndarray)
        or not isinstance(resistance_series, np.ndarray)
        or len(support_series) != len(close)
        or len(resistance_series) != len(close)
    ):
        return None, None

    window_index, train_start, train_end, test_start, test_end = window
    sim = _sr_simulate_window_touch(
        close=close,
        high=high,
        low=low,
        support_series=support_series,
        resistance_series=resistance_series,
        test_start=test_start,
        test_end=test_end,
        cost_bps=cost_bps,
        cooldown_bars=cooldown_bars,
        window_index=window_index,
        dates=context["ohlcv"].index,
    )
    returns = sim["returns"]
    n_bars = int(len(returns))
    total_return = float(np.prod(1.0 + returns) - 1.0) if n_bars > 0 else 0.0
    cagr = (1.0 + total_return) ** (252.0 / max(n_bars, 1)) - 1.0 if total_return > -1.0 else -1.0
    sr = sharpe_ratio(returns) if n_bars > 0 else 0.0
    if not np.isfinite(sr):
        sr = 0.0
    fills = sim["fills"]
    n_trades = len([fill for fill in fills if str(fill.get("side") or "").upper() == "VENTE"])
    positive_trades = [
        fill
        for fill in fills
        if str(fill.get("side") or "").upper() == "VENTE" and float(fill.get("pnl_realise", 0.0)) > 0.0
    ]
    window_result = OOSWindowResult(
        window_index=window_index,
        train_start=train_start,
        train_end=train_end,
        test_start=test_start,
        test_end=test_end,
        n_trades=int(n_trades),
        mean_return_net=float(np.mean(returns)) if n_bars > 0 else 0.0,
        sharpe=float(sr),
        max_drawdown=float(_sr_max_drawdown(returns)),
        fraction_positive_bars=float(len(positive_trades) / n_trades) if n_trades > 0 else 0.0,
        n_bars=n_bars,
        is_valid=n_bars >= 20,
        total_return=float(total_return),
        cagr=float(cagr),
        pnl=float(100_000.0 * total_return),
    )
    return window_result, sim


def _sr_compute_variant_windows(
    *,
    context: dict[str, Any],
    method_series: dict[str, dict[str, Any]],
    support_method_id: str,
    resistance_method_id: str,
    support_line_id: str | None = None,
    resistance_line_id: str | None = None,
    horizon: str,
    cost_bps: float,
    cooldown_bars: int,
) -> tuple[list[OOSWindowResult], float]:
    windows_plan = _sr_window_plan(horizon, len(context["close"]))
    if not windows_plan:
        ranking_window = _sr_ranking_window(horizon, len(context["close"]))
        windows_plan = [ranking_window] if ranking_window is not None else []

    windows: list[OOSWindowResult] = []
    total_realized_1u = 0.0
    for window in windows_plan:
        window_result, sim = _sr_simulate_pair_window(
            context=context,
            method_series=method_series,
            support_method_id=support_method_id,
            resistance_method_id=resistance_method_id,
            support_line_id=support_line_id,
            resistance_line_id=resistance_line_id,
            window=window,
            cost_bps=cost_bps,
            cooldown_bars=cooldown_bars,
        )
        if window_result is None or sim is None:
            continue
        windows.append(window_result)
        total_realized_1u += float(sim.get("realized_total", 0.0))
    return windows, total_realized_1u


def _sr_level_or_none(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    if not np.isfinite(out):
        return None
    return out


def _sr_line_series_bucket(
    method_bucket: dict[str, Any],
    side: str,
) -> dict[str, np.ndarray]:
    key = "support_lines" if side == "support" else "resistance_lines"
    bucket = method_bucket.get(key)
    if not isinstance(bucket, dict):
        bucket = {}
        method_bucket[key] = bucket
    return bucket


def _sr_store_line_series_value(
    output: dict[str, dict[str, Any]],
    method_id: str,
    side: str,
    line_id: str,
    bar_index: int,
    value: Any,
    n_bars: int,
) -> None:
    method_bucket = output.get(method_id)
    if method_bucket is None:
        return
    numeric = _sr_level_or_none(value)
    line = normalize_line_id(line_id)
    if numeric is None or not line:
        return
    side_bucket = _sr_line_series_bucket(method_bucket, side)
    series = side_bucket.get(line)
    if not isinstance(series, np.ndarray) or len(series) != n_bars:
        series = np.full(n_bars, np.nan, dtype="float64")
        side_bucket[line] = series
    series[bar_index] = float(numeric)


def _sr_get_component_series(
    method_series: dict[str, dict[str, Any]],
    method_id: str,
    line_id: str | None,
    side: str,
) -> np.ndarray | None:
    method_bucket = method_series.get(method_id)
    if not isinstance(method_bucket, dict):
        return None
    line = normalize_line_id(line_id)
    if line:
        side_bucket = method_bucket.get("support_lines" if side == "support" else "resistance_lines")
        if isinstance(side_bucket, dict) and isinstance(side_bucket.get(line), np.ndarray):
            return side_bucket[line]
    series = method_bucket.get(side)
    return series if isinstance(series, np.ndarray) else None


def _sr_build_trend_score_series(context: dict[str, Any]) -> np.ndarray:
    close = context["close"]
    n = len(close)
    if n == 0:
        return np.zeros(0, dtype="float64")
    volume = context["volume"]
    high = context["high"]
    low = context["low"]
    snapshots = context["family_snapshots"]
    trend_series: list[np.ndarray] = []
    for family in CATEGORY_FAMILIES.get("tendance", []):
        snapshot = snapshots.get(family) if isinstance(snapshots, dict) else None
        reps = snapshot.get("representatives") if isinstance(snapshot, dict) else None
        if not isinstance(reps, list) or not reps:
            continue
        weighted = np.zeros(n, dtype="float64")
        has_any = False
        for rep in reps:
            if not isinstance(rep, dict):
                continue
            weight = float(rep.get("normalized_weight") or 0.0)
            if weight <= 0.0:
                continue
            archetype = str(rep.get("archetype") or "")
            params = rep.get("params") if isinstance(rep.get("params"), dict) else {}
            variant = VariantDef(
                variant_id=str(rep.get("variant_id") or f"{family}_{archetype}"),
                family=family,
                archetype=archetype,
                params=dict(params),
                description=str(rep.get("label") or ""),
            )
            try:
                sig = compute_signal_array(close, variant, volume=volume, high=high, low=low)
            except Exception:
                continue
            weighted += weight * sig.astype("float64")
            has_any = True
        if has_any:
            trend_series.append(100.0 * weighted)
    if not trend_series:
        return np.full(n, np.nan, dtype="float64")
    stacked = np.vstack(trend_series)
    return np.nanmean(stacked, axis=0)


def _sr_compute_ma_anchor_series(context: dict[str, Any], trend_score_series: np.ndarray) -> dict[str, np.ndarray]:
    close = context["close"]
    n = len(close)
    support_series = np.full(n, np.nan, dtype="float64")
    resistance_series = np.full(n, np.nan, dtype="float64")
    reps = context["ma_anchor_payload"].get("representatives") if isinstance(context.get("ma_anchor_payload"), dict) else None
    representatives = reps if isinstance(reps, list) else []
    if n == 0 or not representatives:
        return {
            "support": support_series,
            "resistance": resistance_series,
            "anchor": np.full(n, np.nan, dtype="float64"),
        }

    weighted_sum = np.zeros(n, dtype="float64")
    weight_sum = np.zeros(n, dtype="float64")
    plain_sum = np.zeros(n, dtype="float64")
    plain_count = np.zeros(n, dtype="float64")

    for rep in representatives:
        if not isinstance(rep, dict):
            continue
        params = rep.get("params") if isinstance(rep.get("params"), dict) else {}
        archetype = str(rep.get("archetype") or "price_vs_sma")
        variant_id = str(rep.get("variant_id") or "ma_rep")
        variant = VariantDef(
            variant_id=variant_id,
            family="sma",
            archetype=archetype,
            params=dict(params),
            description=str(rep.get("label") or ""),
        )
        try:
            indicator_payload = _compute_indicator(close, variant)
            values = indicator_payload.get("values") if isinstance(indicator_payload, dict) else None
            if not isinstance(values, np.ndarray) or len(values) != n:
                continue
            line = values.astype("float64")
        except Exception:
            continue
        valid = np.isfinite(line)
        plain_sum[valid] += line[valid]
        plain_count[valid] += 1.0
        weight = float(rep.get("normalized_weight") or 0.0)
        if weight > 0.0:
            weighted_sum[valid] += weight * line[valid]
            weight_sum[valid] += weight

    with np.errstate(divide="ignore", invalid="ignore"):
        weighted_anchor = np.where(weight_sum > 0.0, weighted_sum / weight_sum, np.nan)
        plain_anchor = np.where(plain_count > 0.0, plain_sum / plain_count, np.nan)
    anchor = np.where(np.isfinite(weighted_anchor), weighted_anchor, plain_anchor)

    for bar_index in range(1, n):
        anchor_value = float(anchor[bar_index - 1]) if np.isfinite(anchor[bar_index - 1]) else None
        prev_close = float(close[bar_index - 1]) if np.isfinite(close[bar_index - 1]) else None
        trend_score = float(trend_score_series[bar_index - 1]) if np.isfinite(trend_score_series[bar_index - 1]) else None
        if anchor_value is None or prev_close is None or trend_score is None:
            continue
        if trend_score > 15.0 and anchor_value <= prev_close:
            support_series[bar_index] = anchor_value
        elif trend_score < -15.0 and anchor_value >= prev_close:
            resistance_series[bar_index] = anchor_value

    return {
        "support": support_series,
        "resistance": resistance_series,
        "anchor": anchor,
    }


def _sr_compute_method_series(
    context: dict[str, Any],
    methods_by_id: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    close = context["close"]
    high = context["high"]
    low = context["low"]
    volume = context["volume"]
    ohlcv = context["ohlcv"]
    policy = context["policy"]
    n = len(close)

    output: dict[str, dict[str, Any]] = {
        method_id: {
            "support": np.full(n, np.nan, dtype="float64"),
            "resistance": np.full(n, np.nan, dtype="float64"),
            "support_lines": {},
            "resistance_lines": {},
        }
        for method_id in methods_by_id
    }
    if n == 0:
        return output

    trend_score_series = _sr_build_trend_score_series(context)
    ma_series = _sr_compute_ma_anchor_series(context, trend_score_series)
    if "ma_anchor" in output:
        output["ma_anchor"]["support"] = ma_series["support"]
        output["ma_anchor"]["resistance"] = ma_series["resistance"]
        output["ma_anchor"]["support_lines"]["S1"] = ma_series["support"].copy()
        output["ma_anchor"]["resistance_lines"]["R1"] = ma_series["resistance"].copy()

    if high is None or low is None:
        return output

    quantile_lookback = max(140, int(policy.structural_lookback))
    swing_padding = max(int(policy.swing_left_bars), int(policy.swing_right_bars)) + 8
    swing_lookback = int(policy.structural_lookback) + swing_padding

    for bar_index in range(1, n):
        prev_close = float(close[bar_index - 1]) if np.isfinite(close[bar_index - 1]) else None
        if prev_close is None:
            continue

        for pivot_method_id in ("pivot_points", "fibonacci_pivot", "camarilla", "woodie", "dm"):
            if pivot_method_id not in output or bar_index < 2:
                continue
            prev_high = float(high[bar_index - 1])
            prev_low = float(low[bar_index - 1])
            prev_close_bar = float(close[bar_index - 1])
            prev_open_bar = (
                float(ohlcv["Open"].values[bar_index - 1])
                if "Open" in ohlcv.columns
                else None
            )
            pivot = compute_pivot_family_levels(
                pivot_method_id,
                prev_high=prev_high,
                prev_low=prev_low,
                prev_close=prev_close_bar,
                prev_open=prev_open_bar,
            )
            support_lines, resistance_lines = split_support_resistance_lines(pivot, prev_close)
            support_candidates = list(support_lines.values())
            resistance_candidates = list(resistance_lines.values())
            if support_candidates:
                output[pivot_method_id]["support"][bar_index] = max(support_candidates)
            if resistance_candidates:
                output[pivot_method_id]["resistance"][bar_index] = min(resistance_candidates)
            for line, value in support_lines.items():
                _sr_store_line_series_value(output, pivot_method_id, "support", line, bar_index, value, n)
            for line, value in resistance_lines.items():
                _sr_store_line_series_value(output, pivot_method_id, "resistance", line, bar_index, value, n)

        if "swing_levels" in output and bar_index >= 4:
            start = max(0, bar_index - swing_lookback)
            swing = detect_swing_levels(
                high[start:bar_index],
                low[start:bar_index],
                close[start:bar_index],
                left_bars=policy.swing_left_bars,
                right_bars=policy.swing_right_bars,
                max_levels=policy.max_levels,
                lookback=min(policy.structural_lookback, bar_index - start),
                max_distance_atr=policy.max_level_distance_atr,
            )
            support = _sr_level_or_none(swing.get("nearest_support"))
            resistance = _sr_level_or_none(swing.get("nearest_resistance"))
            if support is not None and support <= prev_close:
                output["swing_levels"]["support"][bar_index] = support
            if resistance is not None and resistance >= prev_close:
                output["swing_levels"]["resistance"][bar_index] = resistance
            for idx, entry in enumerate(swing.get("supports") or [], start=1):
                if not isinstance(entry, dict):
                    continue
                line_support = _sr_level_or_none(entry.get("price"))
                if line_support is not None and line_support <= prev_close:
                    _sr_store_line_series_value(output, "swing_levels", "support", f"S{idx}", bar_index, line_support, n)
            for idx, entry in enumerate(swing.get("resistances") or [], start=1):
                if not isinstance(entry, dict):
                    continue
                line_resistance = _sr_level_or_none(entry.get("price"))
                if line_resistance is not None and line_resistance >= prev_close:
                    _sr_store_line_series_value(output, "swing_levels", "resistance", f"R{idx}", bar_index, line_resistance, n)

        if "quantile_extrema_atr" in output and bar_index >= 30:
            start = max(0, bar_index - quantile_lookback)
            frame = pd.DataFrame(
                {
                    "Open": ohlcv["Open"].values[start:bar_index].astype("float64") if "Open" in ohlcv.columns else close[start:bar_index],
                    "High": high[start:bar_index],
                    "Low": low[start:bar_index],
                    "Close": close[start:bar_index],
                    "Volume": (
                        volume[start:bar_index].astype("float64")
                        if volume is not None
                        else np.zeros(bar_index - start, dtype="float64")
                    ),
                }
            )
            levels = compute_levels_support_resistance(frame, direction=0)
            support = _sr_level_or_none(levels.get("support"))
            resistance = _sr_level_or_none(levels.get("resistance"))
            if support is not None and support <= prev_close:
                output["quantile_extrema_atr"]["support"][bar_index] = support
                _sr_store_line_series_value(
                    output,
                    "quantile_extrema_atr",
                    "support",
                    "S1",
                    bar_index,
                    support,
                    n,
                )
            if resistance is not None and resistance >= prev_close:
                output["quantile_extrema_atr"]["resistance"][bar_index] = resistance
                _sr_store_line_series_value(
                    output,
                    "quantile_extrema_atr",
                    "resistance",
                    "R1",
                    bar_index,
                    resistance,
                    n,
                )

        if "fibonacci_retracement" in output and bar_index >= 30:
            fib_start = max(0, bar_index - int(policy.structural_lookback))
            fib = compute_fibonacci_retracement_levels(
                high[fib_start:bar_index],
                low[fib_start:bar_index],
                close[fib_start:bar_index],
                lookback=min(int(policy.structural_lookback), bar_index - fib_start),
                left_bars=policy.swing_left_bars,
                right_bars=policy.swing_right_bars,
            )
            fib_s = _sr_level_or_none(fib.get("support"))
            fib_r = _sr_level_or_none(fib.get("resistance"))
            fib_line_map: dict[str, float] = {}
            raw_fib_levels = fib.get("levels") if isinstance(fib.get("levels"), dict) else {}
            for raw_ratio, raw_price in raw_fib_levels.items():
                ratio_value = _sr_finite_float(raw_ratio)
                price_value = _sr_level_or_none(raw_price)
                if ratio_value is None or price_value is None:
                    continue
                fib_line_map[f"F{int(round(ratio_value * 1000)):03d}"] = float(price_value)
            fib_support_lines, fib_resistance_lines = split_support_resistance_lines(fib_line_map, prev_close)
            if fib_s is not None and fib_s <= prev_close:
                output["fibonacci_retracement"]["support"][bar_index] = fib_s
            if fib_r is not None and fib_r >= prev_close:
                output["fibonacci_retracement"]["resistance"][bar_index] = fib_r
            for line, value in fib_support_lines.items():
                _sr_store_line_series_value(output, "fibonacci_retracement", "support", line, bar_index, value, n)
            for line, value in fib_resistance_lines.items():
                _sr_store_line_series_value(output, "fibonacci_retracement", "resistance", line, bar_index, value, n)

    return output


def _sr_simulate_window_touch(
    *,
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    support_series: np.ndarray,
    resistance_series: np.ndarray,
    test_start: int,
    test_end: int,
    cost_bps: float,
    cooldown_bars: int,
    window_index: int,
    dates: pd.DatetimeIndex,
) -> dict[str, Any]:
    if test_end <= test_start:
        return {"returns": np.zeros(0, dtype="float64"), "fills": [], "realized_total": 0.0}

    cost_factor = float(cost_bps) / 10_000.0
    returns = np.zeros(max(0, test_end - test_start), dtype="float64")
    fills: list[dict[str, Any]] = []
    position = 0
    cmp = 0.0
    cash = 0.0
    realized_cum = 0.0
    cooldown_left = 0

    for bar_index in range(test_start + 1, test_end + 1):
        prev_close = float(close[bar_index - 1])
        cur_close = float(close[bar_index])
        hi = float(high[bar_index])
        lo = float(low[bar_index])
        support = _sr_level_or_none(support_series[bar_index])
        resistance = _sr_level_or_none(resistance_series[bar_index])

        pos_before = position
        fills_this_bar = 0
        exited = False

        if position > 0 and resistance is not None and hi >= resistance:
            exec_price = resistance
            cost = cost_factor * exec_price
            pnl_realise = exec_price - cmp - cost
            realized_cum += pnl_realise
            cash += exec_price - cost
            position = 0
            fills_this_bar += 1
            exited = True
            fills.append(
                {
                    "bar_index": bar_index,
                    "date": str(dates[bar_index])[:10],
                    "side": "VENTE",
                    "open_t_plus_1": round(exec_price, 4),
                    "prix_execution": round(exec_price, 4),
                    "close_du_jour": round(cur_close, 4),
                    "cmp": round(cmp, 4),
                    "position": 0.0,
                    "cash_cumulee": round(cash, 4),
                    "tresorerie": round(cash, 4),
                    "pnl_realise": round(pnl_realise, 4),
                    "pnl_realise_cumule": round(realized_cum, 4),
                    "pnl_latent": 0.0,
                    "cout": round(cost, 4),
                    "oos_window": window_index,
                    "support_level": round_number(support, 6),
                    "resistance_level": round_number(resistance, 6),
                }
            )
            cmp = 0.0

        can_enter = (
            position == 0
            and cooldown_left <= 0
            and support is not None
            and lo <= support
            and (resistance is None or support < resistance)
        )
        if can_enter:
            exec_price = support
            cost = cost_factor * exec_price
            cmp = exec_price + cost
            cash -= exec_price + cost
            position = 1
            fills_this_bar += 1
            fills.append(
                {
                    "bar_index": bar_index,
                    "date": str(dates[bar_index])[:10],
                    "side": "ACHAT",
                    "open_t_plus_1": round(exec_price, 4),
                    "prix_execution": round(exec_price, 4),
                    "close_du_jour": round(cur_close, 4),
                    "cmp": round(cmp, 4),
                    "position": 1.0,
                    "cash_cumulee": round(cash, 4),
                    "tresorerie": round(cash, 4),
                    "pnl_realise": 0.0,
                    "pnl_realise_cumule": round(realized_cum, 4),
                    "pnl_latent": round(cur_close - cmp, 4),
                    "cout": round(cost, 4),
                    "oos_window": window_index,
                    "support_level": round_number(support, 6),
                    "resistance_level": round_number(resistance, 6),
                }
            )
            if resistance is not None and hi >= resistance and resistance > support:
                exec_exit = resistance
                cost_exit = cost_factor * exec_exit
                pnl_realise = exec_exit - cmp - cost_exit
                realized_cum += pnl_realise
                cash += exec_exit - cost_exit
                position = 0
                cmp = 0.0
                fills_this_bar += 1
                exited = True
                fills.append(
                    {
                        "bar_index": bar_index,
                        "date": str(dates[bar_index])[:10],
                        "side": "VENTE",
                        "open_t_plus_1": round(exec_exit, 4),
                        "prix_execution": round(exec_exit, 4),
                        "close_du_jour": round(cur_close, 4),
                        "cmp": round(exec_price + cost, 4),
                        "position": 0.0,
                        "cash_cumulee": round(cash, 4),
                        "tresorerie": round(cash, 4),
                        "pnl_realise": round(pnl_realise, 4),
                        "pnl_realise_cumule": round(realized_cum, 4),
                        "pnl_latent": 0.0,
                        "cout": round(cost_exit, 4),
                        "oos_window": window_index,
                        "support_level": round_number(support, 6),
                        "resistance_level": round_number(resistance, 6),
                    }
                )

        ret_index = bar_index - test_start - 1
        bar_return = (pos_before * ((cur_close / prev_close) - 1.0)) - (cost_factor * fills_this_bar) if prev_close > 0 else 0.0
        returns[ret_index] = float(bar_return if np.isfinite(bar_return) else 0.0)

        if exited:
            cooldown_left = max(0, int(cooldown_bars))
        elif position == 0 and cooldown_left > 0:
            cooldown_left -= 1

    if position > 0:
        px = float(close[test_end])
        cost = cost_factor * px
        pnl_realise = px - cmp - cost
        realized_cum += pnl_realise
        cash += px - cost
        fills.append(
            {
                "bar_index": test_end,
                "date": str(dates[test_end])[:10],
                "side": "VENTE",
                "open_t_plus_1": round(px, 4),
                "prix_execution": round(px, 4),
                "close_du_jour": round(px, 4),
                "cmp": round(cmp, 4),
                "position": 0.0,
                "cash_cumulee": round(cash, 4),
                "tresorerie": round(cash, 4),
                "pnl_realise": round(pnl_realise, 4),
                "pnl_realise_cumule": round(realized_cum, 4),
                "pnl_latent": 0.0,
                "cout": round(cost, 4),
                "oos_window": window_index,
                "support_level": round_number(_sr_level_or_none(support_series[test_end]), 6),
                "resistance_level": round_number(_sr_level_or_none(resistance_series[test_end]), 6),
            }
        )
        if returns.size > 0:
            returns[-1] -= cost_factor

    return {
        "returns": returns,
        "fills": fills,
        "realized_total": float(realized_cum),
    }


def _sr_trade_performance_summary(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not trades:
        return []
    closing = [t for t in trades if float(t.get("pnl_realise", 0.0)) != 0.0]
    n = len(closing)
    wins = [t for t in closing if float(t.get("pnl_realise", 0.0)) > 0.0]
    losses = [t for t in closing if float(t.get("pnl_realise", 0.0)) <= 0.0]
    n_wins = len(wins)
    n_losses = len(losses)
    win_rate = (n_wins / n) if n > 0 else 0.0
    avg_win = (sum(float(t.get("pnl_realise", 0.0)) for t in wins) / n_wins) if n_wins > 0 else 0.0
    avg_loss = (sum(float(t.get("pnl_realise", 0.0)) for t in losses) / n_losses) if n_losses > 0 else 0.0
    total_pnl = sum(float(t.get("pnl_realise", 0.0)) for t in closing)
    total_cost = sum(float(t.get("cout", 0.0)) for t in trades)
    gross_wins = sum(float(t.get("pnl_realise", 0.0)) for t in wins)
    gross_losses = abs(sum(float(t.get("pnl_realise", 0.0)) for t in losses))
    if gross_losses > 0:
        profit_factor = gross_wins / gross_losses
    else:
        profit_factor = float("inf") if gross_wins > 0 else 0.0
    return [
        {"metric": "total_fills", "value": len(trades)},
        {"metric": "closing_fills", "value": n},
        {"metric": "win_rate", "value": round(win_rate * 100.0, 1)},
        {"metric": "avg_win_pnl", "value": round(avg_win, 2)},
        {"metric": "avg_loss_pnl", "value": round(avg_loss, 2)},
        {"metric": "profit_factor", "value": round(profit_factor, 2) if np.isfinite(profit_factor) else 999.99},
        {"metric": "total_pnl_realise", "value": round(total_pnl, 2)},
        {"metric": "total_cost", "value": round(total_cost, 2)},
    ]


def _sr_plot_price_levels(
    *,
    ohlcv: pd.DataFrame,
    support_series: np.ndarray,
    resistance_series: np.ndarray,
    fills: list[dict[str, Any]],
    title: str,
    start: int = 0,
    end: int | None = None,
) -> dict[str, Any]:
    last = (len(ohlcv) - 1) if end is None else min(int(end), len(ohlcv) - 1)
    first = max(0, int(start))
    if first > last:
        first = 0
        last = len(ohlcv) - 1
    frame = ohlcv.iloc[first:last + 1]
    dates = [str(idx)[:10] for idx in frame.index]
    close = frame["Close"].to_numpy(dtype="float64")
    support_vals = support_series[first:last + 1]
    resistance_vals = resistance_series[first:last + 1]

    traces: list[dict[str, Any]] = [
        {
            "type": "candlestick",
            "x": dates,
            "open": [float(v) for v in frame["Open"].to_numpy(dtype="float64")],
            "high": [float(v) for v in frame["High"].to_numpy(dtype="float64")],
            "low": [float(v) for v in frame["Low"].to_numpy(dtype="float64")],
            "close": [float(v) for v in close],
            "name": "Prix",
        },
        {
            "type": "scatter",
            "x": dates,
            "y": [float(v) if np.isfinite(v) else None for v in support_vals],
            "mode": "lines",
            "name": "Support dynamique",
            "line": {"color": "#16a34a", "width": 1.6},
        },
        {
            "type": "scatter",
            "x": dates,
            "y": [float(v) if np.isfinite(v) else None for v in resistance_vals],
            "mode": "lines",
            "name": "Resistance dynamique",
            "line": {"color": "#dc2626", "width": 1.6},
        },
    ]

    buy_x: list[str] = []
    buy_y: list[float] = []
    sell_x: list[str] = []
    sell_y: list[float] = []
    for fill in fills:
        bar_index = int(fill.get("bar_index", -1))
        if bar_index < first or bar_index > last:
            continue
        side = str(fill.get("side") or "")
        px = float(fill.get("prix_execution", np.nan))
        if not np.isfinite(px):
            continue
        label_date = str(fill.get("date") or "")
        if side == "ACHAT":
            buy_x.append(label_date)
            buy_y.append(px)
        elif side == "VENTE":
            sell_x.append(label_date)
            sell_y.append(px)
    if buy_x:
        traces.append(
            {
                "type": "scatter",
                "x": buy_x,
                "y": buy_y,
                "mode": "markers",
                "name": "ACHAT",
                "marker": {"symbol": "triangle-up", "size": 8, "color": "#16a34a"},
            }
        )
    if sell_x:
        traces.append(
            {
                "type": "scatter",
                "x": sell_x,
                "y": sell_y,
                "mode": "markers",
                "name": "VENTE",
                "marker": {"symbol": "triangle-down", "size": 8, "color": "#dc2626"},
            }
        )

    return {
        "data": traces,
        "layout": {
            "title": {"text": title, "font": {"size": 14}},
            "xaxis": {"title": "Date", "type": "date"},
            "yaxis": {"title": "Prix"},
            "showlegend": True,
            "margin": {"l": 50, "r": 20, "t": 40, "b": 40},
            "hovermode": "x unified",
        },
    }


def _sr_plot_equity_drawdown(
    *,
    returns: np.ndarray,
    dates: list[str],
    title_prefix: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if returns.size == 0 or len(dates) == 0:
        return None, None
    equity = np.cumprod(1.0 + returns.astype("float64"))
    peak = np.maximum.accumulate(equity)
    drawdown = np.where(peak > 0.0, (peak - equity) / peak, 0.0)
    eq_fig = {
        "data": [
            {
                "type": "scatter",
                "x": dates,
                "y": [float(v) for v in equity],
                "mode": "lines",
                "name": "Equity",
                "line": {"color": "#2563eb", "width": 1.6},
                "fill": "tozeroy",
                "fillcolor": "rgba(37,99,235,0.08)",
            }
        ],
        "layout": {
            "title": {"text": f"{title_prefix} - Equity", "font": {"size": 13}},
            "xaxis": {"title": "Date", "type": "date"},
            "yaxis": {"title": "Equity (base 1.0)"},
            "margin": {"l": 50, "r": 20, "t": 40, "b": 40},
            "hovermode": "x unified",
        },
    }
    dd_fig = {
        "data": [
            {
                "type": "scatter",
                "x": dates,
                "y": [float(-v) for v in drawdown],
                "mode": "lines",
                "name": "Drawdown",
                "line": {"color": "#dc2626", "width": 1.6},
                "fill": "tozeroy",
                "fillcolor": "rgba(220,38,38,0.12)",
            }
        ],
        "layout": {
            "title": {"text": f"{title_prefix} - Drawdown", "font": {"size": 13}},
            "xaxis": {"title": "Date", "type": "date"},
            "yaxis": {"title": "Drawdown", "tickformat": ".1%"},
            "margin": {"l": 50, "r": 20, "t": 40, "b": 40},
            "hovermode": "x unified",
        },
    }
    return eq_fig, dd_fig


def _sr_get_or_compute_variants(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    timeframe: str,
    cost_bps: float,
    cooldown_bars: int,
) -> dict[str, Any]:
    context = _sr_prepare_context(
        db,
        symbol=symbol,
        horizon=horizon,
        timeframe=timeframe,
        cost_bps=cost_bps,
        cooldown_bars=cooldown_bars,
    )
    cache_key = _sr_variants_cache_key(
        symbol,
        horizon,
        timeframe,
        context["as_of"],
        cost_bps,
        cooldown_bars,
    )
    now = time.monotonic()
    cached = _SR_VARIANTS_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _SR_VARIANTS_CACHE_TTL:
        return cached[1]

    methods = _sr_build_base_methods(context)
    finalized = finalize_support_resistance_methods(context["current_close"], methods)
    eligible_methods = [
        m
        for m in finalized["methods"]
        if str(m.get("id")) != "score_inversion"
    ]
    support_options = [
        option
        for method in eligible_methods
        for option in _sr_method_line_options(dict(method), "support")
    ]
    resistance_options = [
        option
        for method in eligible_methods
        for option in _sr_method_line_options(dict(method), "resistance")
    ]

    candidate_method_ids = {
        str(option.get("method_id"))
        for option in [*support_options, *resistance_options]
        if str(option.get("method_id") or "")
    }
    methods_by_id = {
        method_id: dict(method)
        for method_id, method in ((str(m.get("id")), m) for m in finalized["methods"])
        if method_id in candidate_method_ids
    }
    method_series = _sr_compute_method_series(context, methods_by_id)
    ranking_window = _sr_ranking_window(horizon, len(context["close"]))
    close = context["close"]
    high = context["high"]
    low = context["low"]

    variants_internal: dict[str, dict[str, Any]] = {}
    tested_variant_ids: list[str] = []

    if high is not None and low is not None and ranking_window is not None:
        for support_option in support_options:
            sid = str(support_option.get("method_id"))
            support_line_id = normalize_line_id(support_option.get("line_id"))
            support_current = _sr_level_or_none(support_option.get("level"))
            support_label = str(support_option.get("method_label") or sid)
            support_line_label = str(support_option.get("line_label") or support_line_id)
            for resistance_option in resistance_options:
                rid = str(resistance_option.get("method_id"))
                resistance_line_id = normalize_line_id(resistance_option.get("line_id"))
                resistance_current = _sr_level_or_none(resistance_option.get("level"))
                resistance_label = str(resistance_option.get("method_label") or rid)
                resistance_line_label = str(resistance_option.get("line_label") or resistance_line_id)
                variant_id = _sr_variant_id(sid, rid, support_line_id, resistance_line_id)
                tested_variant_ids.append(variant_id)
                variant_def = VariantDef(
                    variant_id=variant_id,
                    family="sr",
                    archetype="sr_combo",
                    params={
                        "support_method_id": sid,
                        "support_line_id": support_line_id,
                        "resistance_method_id": rid,
                        "resistance_line_id": resistance_line_id,
                    },
                    description=(
                        f"Support {support_label} {support_line_label} / "
                        f"Resistance {resistance_label} {resistance_line_label}"
                    ),
                )

                invalid_pair = (
                    support_current is None
                    or resistance_current is None
                    or support_current >= resistance_current
                )
                total_realized_1u = 0.0
                summary = VariantRobustnessSummary(
                    variant=variant_def,
                    n_oos_windows=0,
                    n_valid_windows=0,
                    mean_sharpe=0.0,
                    std_sharpe=0.0,
                    median_sharpe=0.0,
                    fraction_positive_windows=0.0,
                    mean_max_drawdown=0.0,
                    reliability_score=0.0,
                    is_viable=False,
                    sharpe_score=0.0,
                    stability_score=0.0,
                    consistency_score=0.0,
                    drawdown_score=0.0,
                    cagr=0.0,
                    total_pnl=0.0,
                )
                objective_parts: dict[str, float] = {
                    "sr_objective_score": 0.0,
                    "net_return_score": 0.0,
                    "consistency_score": 0.0,
                    "drawdown_score": 0.0,
                    "trade_activity_score": 0.0,
                    "n_trades": 0.0,
                    "total_return": 0.0,
                    "cagr": 0.0,
                    "max_drawdown": 0.0,
                    "win_rate": 0.0,
                    "total_pnl_realise_1u": 0.0,
                }
                if not invalid_pair:
                    _window_result, sim = _sr_simulate_pair_window(
                        context=context,
                        method_series=method_series,
                        support_method_id=sid,
                        resistance_method_id=rid,
                        support_line_id=support_line_id,
                        resistance_line_id=resistance_line_id,
                        window=ranking_window,
                        cost_bps=cost_bps,
                        cooldown_bars=cooldown_bars,
                    )
                    if sim is not None:
                        total_realized_1u = float(sim.get("realized_total", 0.0))
                        summary, objective_parts = _sr_direct_objective_summary(
                            variant_def,
                            returns=sim["returns"],
                            fills=sim["fills"],
                            total_realized_1u=total_realized_1u,
                            n_bars=int(len(sim["returns"])),
                        )
                signal_value, signal_label = _sr_signal_from_levels(
                    context["current_close"],
                    support_current,
                    resistance_current,
                )
                variants_internal[variant_id] = {
                    "variant": variant_def,
                    "support_method_id": sid,
                    "resistance_method_id": rid,
                    "support_line_id": support_line_id,
                    "resistance_line_id": resistance_line_id,
                    "support_current": round_number(support_current, 6),
                    "resistance_current": round_number(resistance_current, 6),
                    "invalid_pair": invalid_pair,
                    "summary": summary,
                    "windows": [],
                    "objective_parts": objective_parts,
                    "signal_value": signal_value,
                    "signal_label": signal_label,
                    "total_pnl_realise_1u": round(float(total_realized_1u), 2),
                }

    sorted_variants = sorted(
        variants_internal.values(),
        key=lambda item: (-float(item["summary"].reliability_score), item["variant"].variant_id),
    )
    viable_variants = [item for item in sorted_variants if item["summary"].is_viable]
    tested_count = len(tested_variant_ids)
    viable_count = len(viable_variants)

    all_variants: list[dict[str, Any]] = []
    best_item = viable_variants[0] if viable_variants else None
    best_variant_id = best_item["variant"].variant_id if best_item is not None else None
    selected_support_method_id = str(best_item["support_method_id"]) if best_item is not None else None
    selected_resistance_method_id = str(best_item["resistance_method_id"]) if best_item is not None else None
    selected_support_line_id = str(best_item["support_line_id"]) if best_item is not None else None
    selected_resistance_line_id = str(best_item["resistance_line_id"]) if best_item is not None else None
    final_support = round_number(best_item["support_current"], 6) if best_item is not None else None
    final_resistance = round_number(best_item["resistance_current"], 6) if best_item is not None else None
    competitive_count = 1 if best_item is not None else 0
    representative_count = 1 if best_item is not None else 0
    competitive_threshold = float(best_item["summary"].reliability_score) if best_item is not None else 0.0

    for item in sorted_variants:
        variant = item["variant"]
        summary = item["summary"]
        vid = variant.variant_id
        is_best_pair = vid == best_variant_id
        is_survivor = is_best_pair
        is_representative = is_best_pair
        elimination_reason = "selected" if is_best_pair else ("tested" if summary.is_viable else "not_viable")
        viability_detail = None
        if item["invalid_pair"]:
            viability_detail = "Paire invalide: support >= resistance."
        elif not summary.is_viable:
            viability_detail = "Aucun trade exploitable sur la fenetre de ranking SR."
        objective_parts = item.get("objective_parts") if isinstance(item.get("objective_parts"), dict) else {}
        all_variants.append(
            {
                "variant_id": vid,
                "archetype": variant.archetype,
                "params": dict(variant.params),
                "description": variant.description,
                "reliability_score": round(float(summary.reliability_score), 4),
                "is_viable": bool(summary.is_viable),
                "is_survivor": bool(is_survivor),
                "is_representative": bool(is_representative),
                "elimination_reason": elimination_reason,
                "mean_sharpe": round(float(summary.mean_sharpe), 4),
                "mean_max_drawdown": round(float(summary.mean_max_drawdown), 4),
                "fraction_positive_windows": round(float(summary.fraction_positive_windows), 4),
                "cagr": round(float(summary.cagr), 4),
                "total_pnl": round(float(summary.total_pnl), 2),
                "total_pnl_100k": round(float(summary.total_pnl), 2),
                "total_pnl_realise_1u": float(item["total_pnl_realise_1u"]),
                "signal_value": float(item["signal_value"]),
                "signal_label": str(item["signal_label"]),
                "correlated_with": None,
                "correlated_with_label": None,
                "correlation": None,
                "threshold_score": None,
                "viability_detail": viability_detail,
                "selection_status": elimination_reason,
                "sr_objective_score": round(float(objective_parts.get("sr_objective_score", summary.reliability_score)), 4),
                "net_return_score": round(float(objective_parts.get("net_return_score", 0.0)), 4),
                "consistency_score": round(float(objective_parts.get("consistency_score", summary.consistency_score)), 4),
                "drawdown_score": round(float(objective_parts.get("drawdown_score", summary.drawdown_score)), 4),
                "trade_activity_score": round(float(objective_parts.get("trade_activity_score", 0.0)), 4),
                "support_level": round_number(item["support_current"], 6),
                "resistance_level": round_number(item["resistance_current"], 6),
                "support_method_id": str(item["support_method_id"]),
                "resistance_method_id": str(item["resistance_method_id"]),
                "support_line_id": str(item.get("support_line_id") or ""),
                "resistance_line_id": str(item.get("resistance_line_id") or ""),
            }
        )

    representative_rows = [row for row in all_variants if row["is_representative"]]
    methods_for_response = []
    for method in finalized["methods"]:
        row = dict(method)
        row["selected_for_support"] = bool(row.get("id") == selected_support_method_id)
        row["selected_for_resistance"] = bool(row.get("id") == selected_resistance_method_id)
        inputs = dict(row.get("inputs") or {})
        if row["selected_for_support"] and selected_support_line_id:
            inputs["optimal_support_line"] = selected_support_line_id
        if row["selected_for_resistance"] and selected_resistance_line_id:
            inputs["optimal_resistance_line"] = selected_resistance_line_id
        row["inputs"] = inputs
        methods_for_response.append(row)
    response = {
        "family": "support_resistance",
        "symbol": symbol,
        "horizon": horizon,
        "timeframe": timeframe,
        "as_of": context["as_of"],
        "current_close": round_number(context["current_close"], 6),
        "trend_score_pct": round_number(context["trend_score_pct"], 2) if context["trend_score_pct"] is not None else None,
        "trend_label": context["trend_label"],
        "methods": methods_for_response,
        "preview_support": finalized["final_support"],
        "preview_resistance": finalized["final_resistance"],
        "preview_support_method_id": finalized["selected_support_method_id"],
        "preview_resistance_method_id": finalized["selected_resistance_method_id"],
        "optimal_support": final_support,
        "optimal_resistance": final_resistance,
        "optimal_variant_id": best_variant_id,
        "optimal_status": "ready" if best_variant_id else "unavailable",
        "final_support": final_support,
        "final_resistance": final_resistance,
        "selected_support_method_id": selected_support_method_id,
        "selected_resistance_method_id": selected_resistance_method_id,
        "selected_support_line_id": selected_support_line_id,
        "selected_resistance_line_id": selected_resistance_line_id,
        "best_variant_id": best_variant_id,
        "funnel": {
            "tested": tested_count,
            "viable": viable_count,
            "competitive": competitive_count,
            "representative": representative_count,
        },
        "tested_count": tested_count,
        "viable_count": viable_count,
        "competitive_count": competitive_count,
        "representative_count": representative_count,
        "competitive_threshold": round(competitive_threshold, 4) if competitive_count > 0 else None,
        "representatives": representative_rows,
        "all_variants": all_variants,
        "score_explanation": (
            "Couples SR: grille complete support x resistance sur methodes disponibles. "
            "Le support et la resistance optimaux viennent du meilleur couple classe par objectif SR direct."
        ),
        "methodology_context": _sr_methodology_context(horizon, len(close)),
    }

    payload = {
        "response": response,
        "context": context,
        "method_series": method_series,
        "variants_internal": variants_internal,
        "ranking_window": ranking_window,
    }
    _SR_VARIANTS_CACHE[cache_key] = (now, payload)
    return payload


@router.post("/signal/support-resistance/variants")
def signal_support_resistance_variants(
    body: SupportResistanceRequest,
    db: Session = Depends(get_db),
):
    payload = _sr_get_or_compute_variants(
        db,
        symbol=body.symbol,
        horizon=body.horizon,
        timeframe=body.timeframe,
        cost_bps=body.cost_bps,
        cooldown_bars=body.cooldown_bars,
    )
    return payload["response"]


@router.post("/signal/support-resistance/variant-detail")
def signal_support_resistance_variant_detail(
    body: SupportResistanceVariantRequest,
    db: Session = Depends(get_db),
):
    payload = _sr_get_or_compute_variants(
        db,
        symbol=body.symbol,
        horizon=body.horizon,
        timeframe=body.timeframe,
        cost_bps=body.cost_bps,
        cooldown_bars=body.cooldown_bars,
    )
    response = payload["response"]
    variants_internal = payload["variants_internal"]
    variant_id = body.variant_id
    if variant_id not in variants_internal:
        raise HTTPException(status_code=404, detail=f"SR variant {variant_id!r} not found")

    variant_data = variants_internal[variant_id]
    summary = variant_data["summary"]
    variant = variant_data["variant"]
    all_variants = response["all_variants"]
    target_row = next((row for row in all_variants if row["variant_id"] == variant_id), None)
    if target_row is None:
        raise HTTPException(status_code=404, detail=f"SR variant {variant_id!r} not found")

    ohlcv = payload["context"]["ohlcv"]
    idx = ohlcv.index
    if not variant_data.get("windows"):
        support_method_id, support_line_id, resistance_method_id, resistance_line_id = (
            _sr_parse_variant_components(variant_id)
        )
        detail_windows, total_realized = _sr_compute_variant_windows(
            context=payload["context"],
            method_series=payload["method_series"],
            support_method_id=support_method_id,
            resistance_method_id=resistance_method_id,
            support_line_id=support_line_id,
            resistance_line_id=resistance_line_id,
            horizon=body.horizon,
            cost_bps=body.cost_bps,
            cooldown_bars=body.cooldown_bars,
        )
        variant_data["windows"] = detail_windows
        variant_data["detail_total_pnl_realise_1u"] = round(float(total_realized), 2)
    oos_windows_dicts: list[dict[str, Any]] = []
    for window in variant_data["windows"]:
        wd = asdict(window)
        ts = int(window.test_start)
        te = int(window.test_end)
        if ts < len(idx):
            wd["test_start_date"] = str(idx[ts])[:10]
        if te < len(idx):
            wd["test_end_date"] = str(idx[min(te, len(idx) - 1)])[:10]
        oos_windows_dicts.append(wd)

    return {
        "variant_id": variant_id,
        "archetype": variant.archetype,
        "params": dict(variant.params),
        "description": variant.description,
        "signal": float(variant_data["signal_value"]),
        "signal_label": str(variant_data["signal_label"]),
        "selection_status": str(target_row.get("selection_status") or "not_viable"),
        "robustness": {
            "mean_sharpe": round(float(summary.mean_sharpe), 4),
            "std_sharpe": round(float(summary.std_sharpe), 4),
            "median_sharpe": round(float(summary.median_sharpe), 4),
            "fraction_positive_windows": round(float(summary.fraction_positive_windows), 4),
            "mean_max_drawdown": round(float(summary.mean_max_drawdown), 4),
            "reliability_score": round(float(summary.reliability_score), 4),
            "is_viable": bool(summary.is_viable),
            "sharpe_score": round(float(summary.sharpe_score), 4),
            "stability_score": round(float(summary.stability_score), 4),
            "consistency_score": round(float(summary.consistency_score), 4),
            "drawdown_score": round(float(summary.drawdown_score), 4),
            "total_pnl_100k": round(float(summary.total_pnl), 2),
            "total_pnl_realise_1u": float(variant_data.get("detail_total_pnl_realise_1u", variant_data["total_pnl_realise_1u"])),
        },
        "oos_windows": oos_windows_dicts,
        "all_variants": all_variants,
        "fallback_variants": [],
        "funnel": response["funnel"],
        "correlation_matrix": {},
        "methodology_context": response["methodology_context"],
    }


@router.post("/signal/support-resistance/variant-backtest")
def signal_support_resistance_variant_backtest(
    body: SupportResistanceVariantRequest,
    db: Session = Depends(get_db),
):
    payload = _sr_get_or_compute_variants(
        db,
        symbol=body.symbol,
        horizon=body.horizon,
        timeframe=body.timeframe,
        cost_bps=body.cost_bps,
        cooldown_bars=body.cooldown_bars,
    )
    response = payload["response"]
    context = payload["context"]
    variants_internal = payload["variants_internal"]
    variant_id = body.variant_id
    if variant_id not in variants_internal:
        raise HTTPException(status_code=404, detail=f"SR variant {variant_id!r} not found")

    cache_key = (
        body.symbol,
        body.horizon,
        body.timeframe,
        context["as_of"],
        round(float(body.cost_bps), 4),
        int(body.cooldown_bars),
        variant_id,
    )
    now = time.monotonic()
    cached = _SR_VARIANT_BACKTEST_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _SR_VARIANT_BACKTEST_CACHE_TTL:
        return cached[1]

    support_method_id, support_line_id, resistance_method_id, resistance_line_id = _sr_parse_variant_components(variant_id)
    method_series = payload["method_series"]
    support_series = _sr_get_component_series(method_series, support_method_id, support_line_id, "support")
    resistance_series = _sr_get_component_series(method_series, resistance_method_id, resistance_line_id, "resistance")
    if not isinstance(support_series, np.ndarray) or not isinstance(resistance_series, np.ndarray):
        raise HTTPException(status_code=422, detail=f"Missing series for SR variant {variant_id!r}")

    close = context["close"]
    high = context["high"]
    low = context["low"]
    if high is None or low is None:
        raise HTTPException(status_code=422, detail=f"High/Low data missing for SR variant {variant_id!r}")
    ohlcv = context["ohlcv"]
    dates_idx = ohlcv.index

    variant_data = variants_internal[variant_id]
    windows: list[OOSWindowResult] = variant_data["windows"]
    if not windows:
        windows, total_realized = _sr_compute_variant_windows(
            context=context,
            method_series=method_series,
            support_method_id=support_method_id,
            resistance_method_id=resistance_method_id,
            support_line_id=support_line_id,
            resistance_line_id=resistance_line_id,
            horizon=body.horizon,
            cost_bps=body.cost_bps,
            cooldown_bars=body.cooldown_bars,
        )
        variant_data["windows"] = windows
        variant_data["detail_total_pnl_realise_1u"] = round(float(total_realized), 2)
    all_fills: list[dict[str, Any]] = []
    stitched_dates: list[str] = []
    stitched_returns: list[float] = []
    per_window: list[dict[str, Any]] = []
    cum_realized = 0.0

    for window in windows:
        sim = _sr_simulate_window_touch(
            close=close,
            high=high,
            low=low,
            support_series=support_series,
            resistance_series=resistance_series,
            test_start=window.test_start,
            test_end=window.test_end,
            cost_bps=body.cost_bps,
            cooldown_bars=body.cooldown_bars,
            window_index=window.window_index,
            dates=dates_idx,
        )
        returns = sim["returns"]
        fills = sim["fills"]
        local_dates = [str(dates_idx[i])[:10] for i in range(window.test_start + 1, window.test_end + 1)]
        stitched_dates.extend(local_dates)
        stitched_returns.extend([float(v) for v in returns])

        for fill in fills:
            cum_realized += float(fill.get("pnl_realise", 0.0))
            fill["pnl_realise_cumule"] = round(cum_realized, 4)
            all_fills.append(fill)

        eq_plot_w, dd_plot_w = _sr_plot_equity_drawdown(
            returns=returns,
            dates=local_dates,
            title_prefix=f"Fenetre #{window.window_index + 1}",
        )
        plot_w = _sr_plot_price_levels(
            ohlcv=ohlcv,
            support_series=support_series,
            resistance_series=resistance_series,
            fills=fills,
            title=f"Fenetre OOS #{window.window_index + 1}",
            start=window.test_start,
            end=window.test_end,
        )
        per_window.append(
            {
                "window_index": int(window.window_index),
                "start_date": str(dates_idx[window.test_start])[:10] if window.test_start < len(dates_idx) else "",
                "end_date": str(dates_idx[min(window.test_end, len(dates_idx) - 1)])[:10] if window.test_end < len(dates_idx) else "",
                "sharpe": round(float(window.sharpe), 4),
                "pnl": round(float(window.pnl), 2),
                "pnl_100k": round(float(window.pnl), 2),
                "n_trades": int(window.n_trades),
                "is_valid": bool(window.is_valid),
                "plot": plot_w,
                "equity_plot": eq_plot_w,
                "drawdown_plot": dd_plot_w,
                "trades": fills,
            }
        )

    stitched_returns_arr = np.asarray(stitched_returns, dtype="float64")
    eq_plot, dd_plot = _sr_plot_equity_drawdown(
        returns=stitched_returns_arr,
        dates=stitched_dates,
        title_prefix="Periodes OOS",
    )
    price_plot = _sr_plot_price_levels(
        ohlcv=ohlcv,
        support_series=support_series,
        resistance_series=resistance_series,
        fills=all_fills,
        title=f"{variant_data['variant'].description} - Prix + S/R",
        start=0,
        end=len(ohlcv) - 1,
    )

    metrics = {
        "total_pnl_realise_1u": round(sum(float(fill.get("pnl_realise", 0.0)) for fill in all_fills), 2),
        "mean_sharpe": round(float(variant_data["summary"].mean_sharpe), 4),
        "mean_max_drawdown": round(float(variant_data["summary"].mean_max_drawdown), 4),
        "fraction_positive_windows": round(float(variant_data["summary"].fraction_positive_windows), 4),
        "cagr": round(float(variant_data["summary"].cagr), 4),
        "total_pnl": round(float(variant_data["summary"].total_pnl), 2),
        "total_pnl_100k": round(float(variant_data["summary"].total_pnl), 2),
        "n_oos_windows": len(windows),
        "n_valid_windows": sum(1 for w in windows if w.is_valid),
        "total_trades": len(all_fills),
    }
    trade_performance = _sr_trade_performance_summary(all_fills)
    plots: dict[str, Any] = {"price_indicator_signal": price_plot}
    if eq_plot is not None:
        plots["oos_equity"] = eq_plot
    if dd_plot is not None:
        plots["drawdown"] = dd_plot

    backtest_response = {
        "variant_id": variant_id,
        "description": variant_data["variant"].description,
        "metrics": metrics,
        "trade_performance": trade_performance,
        "trade_ledger": all_fills,
        "plots": plots,
        "per_window": per_window,
        "methodology_context": response["methodology_context"],
        "warning_message": "",
    }
    _SR_VARIANT_BACKTEST_CACHE[cache_key] = (now, backtest_response)
    return backtest_response


def _int_param(params: dict[str, float], key: str, *, minimum: int, maximum: int) -> int:
    value = params.get(key)
    if value is None:
        raise HTTPException(status_code=422, detail=f"Missing parameter: {key}")
    numeric = float(value)
    if not numeric.is_integer():
        raise HTTPException(status_code=422, detail=f"Parameter {key} must be an integer")
    integer = int(numeric)
    if integer < minimum or integer > maximum:
        raise HTTPException(
            status_code=422,
            detail=f"Parameter {key} must be between {minimum} and {maximum}",
        )
    return integer


def _float_param(params: dict[str, float], key: str, *, minimum: float, maximum: float) -> float:
    value = params.get(key)
    if value is None:
        raise HTTPException(status_code=422, detail=f"Missing parameter: {key}")
    numeric = float(value)
    if numeric < minimum or numeric > maximum:
        raise HTTPException(
            status_code=422,
            detail=f"Parameter {key} must be between {minimum} and {maximum}",
        )
    return numeric


def _validate_indicator_params(indicator: str, params: dict[str, float]) -> dict[str, int | float]:
    keys = set(params.keys())
    if indicator == "sma":
        if keys == {"period"}:
            return {"window": _int_param(params, "period", minimum=5, maximum=500)}
        if keys == {"window"}:
            return {"window": _int_param(params, "window", minimum=5, maximum=500)}
        raise HTTPException(status_code=422, detail="SMA params must be exactly: period or window")
    if indicator == "ema":
        if keys != {"window"}:
            raise HTTPException(status_code=422, detail="EMA params must be exactly: window")
        return {"window": _int_param(params, "window", minimum=2, maximum=500)}
    if indicator == "ema_cross":
        if keys != {"fast", "slow"}:
            raise HTTPException(status_code=422, detail="EMA Cross params must be exactly: fast, slow")
        validated = {
            "fast": _int_param(params, "fast", minimum=2, maximum=200),
            "slow": _int_param(params, "slow", minimum=3, maximum=500),
        }
        if validated["fast"] >= validated["slow"]:
            raise HTTPException(status_code=422, detail="EMA Cross params require fast < slow")
        return validated
    if indicator == "ichimoku":
        if keys != {"tenkan", "kijun", "senkou_b"}:
            raise HTTPException(status_code=422, detail="Ichimoku params must be exactly: tenkan, kijun, senkou_b")
        validated = {
            "tenkan": _int_param(params, "tenkan", minimum=2, maximum=100),
            "kijun": _int_param(params, "kijun", minimum=3, maximum=200),
            "senkou_b": _int_param(params, "senkou_b", minimum=5, maximum=400),
        }
        if not (validated["tenkan"] < validated["kijun"] < validated["senkou_b"]):
            raise HTTPException(status_code=422, detail="Ichimoku params require tenkan < kijun < senkou_b")
        return validated
    if indicator == "psar":
        if keys != {"af_step", "af_max"}:
            raise HTTPException(status_code=422, detail="PSAR params must be exactly: af_step, af_max")
        validated = {
            "af_step": round(_float_param(params, "af_step", minimum=0.001, maximum=0.1), 4),
            "af_max": round(_float_param(params, "af_max", minimum=0.05, maximum=1.0), 4),
        }
        if validated["af_step"] >= validated["af_max"]:
            raise HTTPException(status_code=422, detail="PSAR params require af_step < af_max")
        return validated
    if indicator == "rsi":
        if keys != {"period", "oversold", "overbought"}:
            raise HTTPException(
                status_code=422,
                detail="RSI params must be exactly: period, oversold, overbought",
            )
        validated = {
            "period": _int_param(params, "period", minimum=2, maximum=200),
            "oversold": _int_param(params, "oversold", minimum=0, maximum=50),
            "overbought": _int_param(params, "overbought", minimum=50, maximum=100),
        }
        if validated["oversold"] >= validated["overbought"]:
            raise HTTPException(status_code=422, detail="RSI params require oversold < overbought")
        return validated
    if indicator == "macd":
        if keys != {"fast", "slow", "signal"}:
            raise HTTPException(status_code=422, detail="MACD params must be exactly: fast, slow, signal")
        validated = {
            "fast": _int_param(params, "fast", minimum=2, maximum=100),
            "slow": _int_param(params, "slow", minimum=5, maximum=200),
            "signal": _int_param(params, "signal", minimum=2, maximum=50),
        }
        if validated["fast"] >= validated["slow"]:
            raise HTTPException(status_code=422, detail="MACD params require fast < slow")
        return validated
    if indicator == "roc":
        if keys != {"period"}:
            raise HTTPException(status_code=422, detail="ROC params must be exactly: period")
        return {"period": _int_param(params, "period", minimum=1, maximum=400)}
    if indicator == "trix":
        if keys != {"period"}:
            raise HTTPException(status_code=422, detail="TRIX params must be exactly: period")
        return {"period": _int_param(params, "period", minimum=2, maximum=400)}
    if indicator == "adx":
        if keys != {"period", "adx_threshold"}:
            raise HTTPException(status_code=422, detail="ADX params must be exactly: period, adx_threshold")
        return {
            "period": _int_param(params, "period", minimum=2, maximum=200),
            "adx_threshold": _int_param(params, "adx_threshold", minimum=1, maximum=100),
        }
    if indicator == "tsi":
        if keys != {"long_period", "short_period"}:
            raise HTTPException(status_code=422, detail="TSI params must be exactly: long_period, short_period")
        validated = {
            "long_period": _int_param(params, "long_period", minimum=2, maximum=200),
            "short_period": _int_param(params, "short_period", minimum=1, maximum=100),
        }
        if validated["long_period"] <= validated["short_period"]:
            raise HTTPException(status_code=422, detail="TSI params require long_period > short_period")
        return validated
    if indicator == "stochastic":
        if keys != {"k_period", "d_period"}:
            raise HTTPException(status_code=422, detail="Stochastic params must be exactly: k_period, d_period")
        return {
            "k_period": _int_param(params, "k_period", minimum=2, maximum=200),
            "d_period": _int_param(params, "d_period", minimum=1, maximum=50),
        }
    if indicator == "cci":
        if keys != {"period"}:
            raise HTTPException(status_code=422, detail="CCI params must be exactly: period")
        return {"period": _int_param(params, "period", minimum=2, maximum=400)}
    if indicator == "mfi":
        if keys != {"period", "oversold", "overbought"}:
            raise HTTPException(status_code=422, detail="MFI params must be exactly: period, oversold, overbought")
        validated = {
            "period": _int_param(params, "period", minimum=2, maximum=200),
            "oversold": _int_param(params, "oversold", minimum=0, maximum=50),
            "overbought": _int_param(params, "overbought", minimum=50, maximum=100),
        }
        if validated["oversold"] >= validated["overbought"]:
            raise HTTPException(status_code=422, detail="MFI params require oversold < overbought")
        return validated
    if indicator == "uo":
        if keys != {"period_1", "period_2", "period_3"}:
            raise HTTPException(status_code=422, detail="UO params must be exactly: period_1, period_2, period_3")
        validated = {
            "period_1": _int_param(params, "period_1", minimum=1, maximum=100),
            "period_2": _int_param(params, "period_2", minimum=2, maximum=200),
            "period_3": _int_param(params, "period_3", minimum=3, maximum=400),
        }
        if not (validated["period_1"] < validated["period_2"] < validated["period_3"]):
            raise HTTPException(status_code=422, detail="UO params require period_1 < period_2 < period_3")
        return validated
    if indicator == "obv":
        if keys != {"ema_period"}:
            raise HTTPException(status_code=422, detail="OBV params must be exactly: ema_period")
        return {"ema_period": _int_param(params, "ema_period", minimum=2, maximum=200)}
    if indicator == "cmf":
        if keys != {"period"}:
            raise HTTPException(status_code=422, detail="CMF params must be exactly: period")
        return {"period": _int_param(params, "period", minimum=2, maximum=400)}
    if indicator == "ad":
        if keys != {"ema_period"}:
            raise HTTPException(status_code=422, detail="A/D params must be exactly: ema_period")
        return {"ema_period": _int_param(params, "ema_period", minimum=2, maximum=200)}
    if indicator == "vwap":
        if keys != {"period", "threshold_pct"}:
            raise HTTPException(status_code=422, detail="VWAP params must be exactly: period, threshold_pct")
        return {
            "period": _int_param(params, "period", minimum=2, maximum=300),
            "threshold_pct": round(_float_param(params, "threshold_pct", minimum=0.1, maximum=10.0), 4),
        }
    if indicator == "fi":
        if keys != {"period"}:
            raise HTTPException(status_code=422, detail="Force Index params must be exactly: period")
        return {"period": _int_param(params, "period", minimum=2, maximum=200)}
    raise HTTPException(status_code=422, detail=f"Unsupported indicator: {indicator}")


def _trend_label(signal_val: float) -> str:
    if signal_val > 0:
        return "Haussier"
    if signal_val < 0:
        return "Baissier"
    return "Neutre"


def _momentum_label(signal_val: float) -> str:
    if signal_val > 0:
        return "Momentum haussier"
    if signal_val < 0:
        return "Momentum baissier"
    return "Pas de momentum"


def _oscillator_label(signal_val: float) -> str:
    if signal_val > 0:
        return "Survendu"
    if signal_val < 0:
        return "Surachete"
    return "Normal"


def _volume_label(signal_val: float) -> str:
    if signal_val > 0:
        return "Accumulation"
    if signal_val < 0:
        return "Distribution"
    return "Neutre"


def _sma_label(score: float) -> str:
    if score < -2.0:
        return "Fortement Baissier"
    if score < -0.5:
        return "Baissier"
    if score < 0.5:
        return "Neutre"
    if score < 2.0:
        return "Haussier"
    return "Fortement Haussier"


def _macd_label(score: float) -> str:
    return _sma_label(score)


def _rsi_label(score: float) -> str:
    if score <= 30:
        return "Survendu"
    if score <= 50:
        return "Baissier"
    if score <= 70:
        return "Haussier"
    return "Surachete"


def _obv_label(score: float) -> str:
    if score < -0.10:
        return "Forte Distribution"
    if score < -0.03:
        return "Distribution"
    if score < 0.03:
        return "Neutre"
    if score < 0.10:
        return "Accumulation"
    return "Forte Accumulation"


def _current_label_for_family(family: str, signal_val: float) -> str:
    st = FAMILY_SIGNAL_TYPE.get(family, "trend")
    if st == "trend":
        return _trend_label(signal_val)
    if st == "momentum":
        return _momentum_label(signal_val)
    if st == "oscillator":
        return _oscillator_label(signal_val)
    if st == "volume":
        return _volume_label(signal_val)
    if signal_val == 0:
        return "Neutre"
    return signal_type_label(st, signal_val * 100.0)


def _indicator_variant(indicator: str, params: dict[str, int | float]) -> VariantDef:
    return VariantDef(
        variant_id=f"indicator-series-{indicator}",
        family=indicator,
        archetype=_INDICATOR_ARCHETYPES[indicator],
        params=dict(params),
        description=indicator.upper(),
    )


def _serialize_indicator_payload(indicator: dict[str, Any]) -> dict[str, Any] | None:
    if indicator.get("type") == "none":
        return None
    serialized: dict[str, Any] = {}
    for key, value in indicator.items():
        if isinstance(value, np.ndarray):
            serialized[key] = _safe_float_list(value)
        elif isinstance(value, (list, tuple)):
            serialized[key] = [
                round(float(v), 4) if isinstance(v, (int, float, np.floating)) and np.isfinite(float(v)) else v
                for v in value
            ]
        else:
            serialized[key] = value
    return serialized


def _primary_indicator_series(indicator: dict[str, Any]) -> tuple[np.ndarray, np.ndarray | None]:
    kind = indicator.get("type")
    if kind == "overlay":
        return indicator["values"], None
    if kind == "overlay_dual":
        return indicator["fast"], indicator["slow"]
    if kind == "overlay_cloud":
        return indicator["tenkan_sen"], indicator["kijun_sen"]
    if kind == "overlay_dots":
        return indicator["values"], None
    if kind == "overlay_band":
        return indicator["values"], indicator["upper"]
    if kind == "secondary_yaxis":
        if "histogram" in indicator:
            return indicator["histogram"], indicator.get("signal_line")
        if "values" in indicator:
            return indicator["values"], None
        if "adx" in indicator:
            return indicator["adx"], indicator.get("plus_di")
        if "k" in indicator:
            return indicator["k"], indicator.get("d")
        if "obv" in indicator:
            return indicator["obv"], indicator.get("ema_values")
        if "ad" in indicator:
            return indicator["ad"], indicator.get("ema_values")
    return np.full(0, np.nan), None


def _last_finite(arr: np.ndarray | None) -> float | None:
    if arr is None or len(arr) == 0:
        return None
    finite = arr[np.isfinite(arr)]
    if len(finite) == 0:
        return None
    return float(finite[-1])


def _indicator_current_score(
    family: str,
    indicator: dict[str, Any],
    close: np.ndarray,
    *,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
) -> tuple[float | None, float | None]:
    atr_last: float | None = None
    if high is not None and low is not None:
        atr_last = _last_finite(compute_atr_series(high, low, close, window=14))

    if family in {"sma", "ema"} and "values" in indicator:
        base = float(indicator["values"][-1])
        if atr_last and atr_last > 0:
            return (float(close[-1]) - base) / atr_last, atr_last
        return float(close[-1]) - base, atr_last
    if family == "ema_cross":
        diff = float(indicator["fast"][-1]) - float(indicator["slow"][-1])
        return (diff / atr_last, atr_last) if atr_last and atr_last > 0 else (diff, atr_last)
    if family == "ichimoku":
        cloud_mid = 0.5 * (float(indicator["cloud_top"][-1]) + float(indicator["cloud_bottom"][-1]))
        diff = float(close[-1]) - cloud_mid
        return (diff / atr_last, atr_last) if atr_last and atr_last > 0 else (diff, atr_last)
    if family == "psar":
        diff = float(close[-1]) - float(indicator["values"][-1])
        return (diff / atr_last, atr_last) if atr_last and atr_last > 0 else (diff, atr_last)
    if family == "macd":
        hist = float(indicator["histogram"][-1])
        return (hist / atr_last, atr_last) if atr_last and atr_last > 0 else (hist, atr_last)
    if family == "adx":
        adx = float(indicator["adx"][-1])
        direction = np.sign(float(indicator["plus_di"][-1]) - float(indicator["minus_di"][-1]))
        threshold = float(indicator.get("thresholds", [25.0])[0])
        return ((adx * direction) if adx >= threshold else 0.0, atr_last)
    if family == "obv":
        return float(indicator["obv"][-1]) - float(indicator["ema_values"][-1]), atr_last
    if family == "ad":
        return float(indicator["ad"][-1]) - float(indicator["ema_values"][-1]), atr_last
    if family == "vwap":
        vwap_last = float(indicator["values"][-1])
        if not np.isfinite(vwap_last) or vwap_last == 0:
            return None, atr_last
        return ((float(close[-1]) - vwap_last) / vwap_last) * 100.0, atr_last

    primary, _overlay = _primary_indicator_series(indicator)
    return _last_finite(primary), atr_last


def _sr_overlay_empty(status: str, reason: str, baseline_metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": status,
        "decision": status,
        "reason": reason,
        "best_variant_id": None,
        "best_support_method": None,
        "best_support_line": None,
        "best_resistance_method": None,
        "best_resistance_line": None,
        "baseline_metrics": baseline_metrics or {},
        "overlay_metrics": None,
        "uplift": {},
        "top_variants": [],
        "validation": {
            "status": status,
            "decision": status,
            "reason": reason,
            "reason_codes": [reason],
            "gates": {},
        },
        "tested_count": 0,
        "viable_count": 0,
        "invalid_pair_count": 0,
        "unavailable_count": 0,
    }


def _sr_overlay_metric_value(metrics: dict[str, Any], key: str) -> float | None:
    value = _evidence_float(metrics.get(key))
    return float(value) if value is not None else None


def _sr_overlay_uplift(
    baseline_metrics: dict[str, Any],
    overlay_metrics: dict[str, Any],
) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for key in ("total_return", "cagr", "sharpe", "win_rate"):
        base = _sr_overlay_metric_value(baseline_metrics, key)
        over = _sr_overlay_metric_value(overlay_metrics, key)
        out[key] = (over - base) if base is not None and over is not None else None
    base_dd = _sr_overlay_metric_value(baseline_metrics, "max_drawdown")
    over_dd = _sr_overlay_metric_value(overlay_metrics, "max_drawdown")
    out["max_drawdown"] = (base_dd - over_dd) if base_dd is not None and over_dd is not None else None
    base_trades = _sr_overlay_metric_value(baseline_metrics, "n_trades")
    over_trades = _sr_overlay_metric_value(overlay_metrics, "n_trades")
    out["n_trades"] = (over_trades - base_trades) if base_trades is not None and over_trades is not None else None
    return out


def _sr_overlay_metrics_from_returns(returns: np.ndarray, trades: list[dict[str, Any]]) -> dict[str, Any]:
    safe_returns = returns.astype("float64") if isinstance(returns, np.ndarray) else np.zeros(0, dtype="float64")
    equity = np.concatenate(([1.0], np.cumprod(1.0 + safe_returns)))
    total_return = float(equity[-1] - 1.0) if len(equity) else 0.0
    years = max(len(safe_returns), 1) / 252.0
    cagr = float((1.0 + total_return) ** (1.0 / years) - 1.0) if total_return > -1.0 else -1.0
    sharpe = _evidence_sharpe([float(v) for v in safe_returns]) if safe_returns.size > 1 else 0.0
    win_rate = float(np.mean([float(t.get("pnl_return", 0.0)) > 0.0 for t in trades])) if trades else 0.0
    return {
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe,
        "max_drawdown": _evidence_max_drawdown(equity.tolist()),
        "win_rate": win_rate,
        "n_trades": len(trades),
    }


def _sr_overlay_position_episodes(position: np.ndarray) -> list[tuple[int, int, int]]:
    episodes: list[tuple[int, int, int]] = []
    n = len(position)
    idx = 0
    while idx < n:
        side = 1 if position[idx] > 0.0 else (-1 if position[idx] < 0.0 else 0)
        if side == 0:
            idx += 1
            continue
        start = idx
        idx += 1
        while idx < n:
            next_side = 1 if position[idx] > 0.0 else (-1 if position[idx] < 0.0 else 0)
            if next_side != side:
                break
            idx += 1
        end = max(start, idx - 1)
        episodes.append((start, end, side))
    return episodes


def _sr_simulate_signal_overlay(
    *,
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    dates: list[str],
    baseline_position: np.ndarray,
    support_series: np.ndarray,
    resistance_series: np.ndarray,
    cost_bps: float,
    slippage_bps: float,
    cooldown_bars: int,
    allow_short: bool,
) -> dict[str, Any]:
    n = min(
        len(close),
        len(high),
        len(low),
        len(dates),
        len(baseline_position),
        len(support_series),
        len(resistance_series),
    )
    if n < 2:
        returns = np.zeros(0, dtype="float64")
        return {"returns": returns, "equity": [1.0], "trades": [], "position_series": [], "metrics": _sr_overlay_metrics_from_returns(returns, [])}

    friction = (float(cost_bps) + float(slippage_bps)) / 10_000.0
    returns = np.zeros(n - 1, dtype="float64")
    overlay_position = np.zeros(n, dtype="float64")
    trades: list[dict[str, Any]] = []
    cooldown_until = -1

    for start, end, side in _sr_overlay_position_episodes(baseline_position[:n]):
        if side < 0 and not allow_short:
            continue
        if start <= cooldown_until:
            continue
        entry_idx: int | None = None
        exit_idx: int | None = None
        entry_price: float | None = None
        exit_price: float | None = None
        exit_reason = "horizon"

        for bar_idx in range(start, end + 1):
            support = _sr_level_or_none(support_series[bar_idx])
            resistance = _sr_level_or_none(resistance_series[bar_idx])
            if support is None or resistance is None or support >= resistance:
                continue
            if side > 0:
                if float(low[bar_idx]) <= support:
                    entry_idx = bar_idx
                    entry_price = float(support)
                    if float(high[bar_idx]) >= resistance:
                        exit_idx = bar_idx
                        exit_price = float(resistance)
                        exit_reason = "resistance"
                    break
            else:
                if float(high[bar_idx]) >= resistance:
                    entry_idx = bar_idx
                    entry_price = float(resistance)
                    if float(low[bar_idx]) <= support:
                        exit_idx = bar_idx
                        exit_price = float(support)
                        exit_reason = "support"
                    break

        if entry_idx is None or entry_price is None:
            continue

        if exit_idx is None:
            for bar_idx in range(entry_idx + 1, end + 1):
                support = _sr_level_or_none(support_series[bar_idx])
                resistance = _sr_level_or_none(resistance_series[bar_idx])
                if support is None or resistance is None or support >= resistance:
                    continue
                if side > 0 and float(high[bar_idx]) >= resistance:
                    exit_idx = bar_idx
                    exit_price = float(resistance)
                    exit_reason = "resistance"
                    break
                if side < 0 and float(low[bar_idx]) <= support:
                    exit_idx = bar_idx
                    exit_price = float(support)
                    exit_reason = "support"
                    break

        if exit_idx is None or exit_price is None:
            exit_idx = end
            exit_price = float(close[exit_idx])
            exit_reason = "horizon"
        if exit_idx < entry_idx:
            continue

        gross_return = (
            (float(exit_price) / float(entry_price) - 1.0)
            if side > 0
            else (float(entry_price) / float(exit_price) - 1.0 if exit_price else 0.0)
        )
        net_return = float(gross_return - 2.0 * friction)
        if exit_idx > 0:
            returns[min(exit_idx - 1, len(returns) - 1)] += net_return
        overlay_position[entry_idx:exit_idx + 1] = float(side)
        trade = {
            "open_idx": int(entry_idx),
            "close_idx": int(exit_idx),
            "open_date": dates[entry_idx],
            "close_date": dates[exit_idx],
            "open_price": float(entry_price),
            "close_price": float(exit_price),
            "bars_held": int(exit_idx - entry_idx),
            "pnl_return": net_return,
            "direction": float(side),
            "entry_reason": "support" if side > 0 else "resistance",
            "exit_reason": exit_reason,
            "support_level": round_number(support_series[entry_idx], 6),
            "resistance_level": round_number(resistance_series[entry_idx], 6),
        }
        trades.append(trade)
        cooldown_until = exit_idx + max(0, int(cooldown_bars or 0))

    equity = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    return {
        "returns": returns,
        "equity": equity.tolist(),
        "trades": trades,
        "position_series": overlay_position.tolist(),
        "metrics": _sr_overlay_metrics_from_returns(returns, trades),
    }


def _sr_align_position_to_context(
    context: dict[str, Any],
    dates: list[Any],
    position: list[Any],
) -> np.ndarray:
    index = pd.DatetimeIndex(context["ohlcv"].index)
    by_date: dict[str, float] = {}
    for raw_date, raw_pos in zip(dates, position):
        try:
            key = pd.Timestamp(raw_date).date().isoformat()
        except Exception:
            continue
        value = _evidence_float(raw_pos)
        by_date[key] = float(value or 0.0)
    aligned = np.zeros(len(index), dtype="float64")
    for idx, ts in enumerate(index):
        aligned[idx] = by_date.get(pd.Timestamp(ts).date().isoformat(), 0.0)
    return aligned


def _sr_overlay_context_payload(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    variant: str,
    cost_bps: float,
    cooldown_bars: int,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    context = _sr_prepare_context(
        db,
        symbol=symbol,
        horizon=horizon,
        timeframe="1D",
        cost_bps=cost_bps,
        cooldown_bars=cooldown_bars,
        variant=variant,
    )
    methods = _sr_build_base_methods(context)
    finalized = finalize_support_resistance_methods(context["current_close"], methods)
    eligible_methods = [
        dict(method)
        for method in finalized["methods"]
        if str(method.get("id")) != "score_inversion"
    ]
    support_options = [
        option
        for method in eligible_methods
        for option in _sr_method_line_options(method, "support")
    ]
    resistance_options = [
        option
        for method in eligible_methods
        for option in _sr_method_line_options(method, "resistance")
    ]
    candidate_method_ids = {
        str(option.get("method_id"))
        for option in [*support_options, *resistance_options]
        if str(option.get("method_id") or "")
    }
    methods_by_id = {
        str(method.get("id")): dict(method)
        for method in eligible_methods
        if str(method.get("id")) in candidate_method_ids
    }
    return context, _sr_compute_method_series(context, methods_by_id), support_options, resistance_options


def _sr_overlay_for_position_series(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    variant: str,
    dates: list[Any],
    baseline_position: list[Any],
    baseline_metrics: dict[str, Any],
    cost_bps: float,
    slippage_bps: float = 0.0,
    cooldown_bars: int = 0,
    side_policy: str = "long_only",
    top_n: int = 10,
) -> dict[str, Any]:
    if not dates or not baseline_position:
        return _sr_overlay_empty("unavailable", "missing_baseline_position", baseline_metrics)

    try:
        context, method_series, support_options, resistance_options = _sr_overlay_context_payload(
            db,
            symbol=symbol,
            horizon=horizon,
            variant=variant,
            cost_bps=cost_bps,
            cooldown_bars=cooldown_bars,
        )
    except Exception:
        logger.debug("SR overlay context unavailable", exc_info=True)
        return _sr_overlay_empty("unavailable", "context_unavailable", baseline_metrics)

    high = context["high"]
    low = context["low"]
    if high is None or low is None:
        return _sr_overlay_empty("unavailable", "missing_high_low", baseline_metrics)

    aligned_position = _sr_align_position_to_context(context, dates, baseline_position)
    if not np.any(aligned_position != 0.0):
        return _sr_overlay_empty("unavailable", "baseline_has_no_positions", baseline_metrics)

    close = context["close"]
    context_dates = [pd.Timestamp(ts).date().isoformat() for ts in context["ohlcv"].index]
    allow_short = str(side_policy or "long_only").strip().lower() == "long_short"
    baseline_returns = baseline_returns_from_position(
        close,
        aligned_position,
        cost_bps=cost_bps,
        slippage_bps=slippage_bps,
    )
    top_rows: list[dict[str, Any]] = []
    invalid_pair_count = 0
    unavailable_count = 0
    tested_count = 0

    for support_option in support_options:
        sid = str(support_option.get("method_id"))
        support_line_id = normalize_line_id(support_option.get("line_id"))
        support_current = _sr_level_or_none(support_option.get("level"))
        for resistance_option in resistance_options:
            rid = str(resistance_option.get("method_id"))
            resistance_line_id = normalize_line_id(resistance_option.get("line_id"))
            resistance_current = _sr_level_or_none(resistance_option.get("level"))
            variant_id = _sr_variant_id(sid, rid, support_line_id, resistance_line_id)
            tested_count += 1
            if support_current is None or resistance_current is None or support_current >= resistance_current:
                invalid_pair_count += 1
                continue
            support_series = _sr_get_component_series(method_series, sid, support_line_id, "support")
            resistance_series = _sr_get_component_series(method_series, rid, resistance_line_id, "resistance")
            if not isinstance(support_series, np.ndarray) or not isinstance(resistance_series, np.ndarray):
                unavailable_count += 1
                continue
            sim = _sr_simulate_signal_overlay(
                close=close,
                high=high,
                low=low,
                dates=context_dates,
                baseline_position=aligned_position,
                support_series=support_series,
                resistance_series=resistance_series,
                cost_bps=cost_bps,
                slippage_bps=slippage_bps,
                cooldown_bars=cooldown_bars,
                allow_short=allow_short,
            )
            metrics = sim["metrics"]
            if int(metrics.get("n_trades") or 0) <= 0:
                continue
            validation = validate_sr_overlay_candidate(
                baseline_returns=baseline_returns,
                overlay_returns=sim["returns"],
                overlay_trades=sim["trades"],
                seed=int(uuid.uuid5(uuid.NAMESPACE_URL, variant_id).int % 1_000_000),
            )
            uplift = _sr_overlay_uplift(baseline_metrics, metrics)
            total_uplift = uplift.get("total_return")
            sharpe_uplift = uplift.get("sharpe")
            dd_uplift = uplift.get("max_drawdown")
            proof_uplift = (
                ((validation.get("proof") or {}).get("uplift") or {})
                if isinstance(validation.get("proof"), dict)
                else {}
            )
            rank_score = (
                (10.0 if validation.get("decision") == "actionable" else 0.0)
                + float(proof_uplift.get("total_return") or total_uplift or 0.0)
                + 0.05 * float(sharpe_uplift or 0.0)
                + 0.25 * float(dd_uplift or 0.0)
            )
            top_rows.append(
                {
                    "variant_id": variant_id,
                    "support_method": sid,
                    "support_line": support_line_id,
                    "resistance_method": rid,
                    "resistance_line": resistance_line_id,
                    "support_level": round_number(support_current, 6),
                    "resistance_level": round_number(resistance_current, 6),
                    "metrics": metrics,
                    "uplift": uplift,
                    "validation": validation,
                    "decision": str(validation.get("decision") or "research_only"),
                    "status": str(validation.get("status") or "research_only"),
                    "rank_score": rank_score,
                    "trade_count": int(metrics.get("n_trades") or 0),
                    "trades": sim["trades"][-25:],
                }
            )

    if not top_rows:
        reason = "no_viable_overlay_trades" if tested_count else "no_candidate_pairs"
        return {
            **_sr_overlay_empty("unavailable", reason, baseline_metrics),
            "tested_count": tested_count,
            "invalid_pair_count": invalid_pair_count,
            "unavailable_count": unavailable_count,
        }

    top_rows.sort(
        key=lambda row: (
            0 if str(row.get("decision") or "") == "actionable" else 1,
            -float(row.get("rank_score") or 0.0),
            -float((row.get("metrics") or {}).get("total_return") or 0.0),
            str(row.get("variant_id") or ""),
        )
    )
    best = top_rows[0]
    overlay_metrics = dict(best.get("metrics") or {})
    validation = dict(best.get("validation") or {})
    decision = str(validation.get("decision") or best.get("decision") or "research_only")
    return {
        "status": decision,
        "decision": decision,
        "reason": "validated" if decision == "actionable" else "failed_validation_gates",
        "best_variant_id": best["variant_id"],
        "best_support_method": best["support_method"],
        "best_support_line": best["support_line"],
        "best_resistance_method": best["resistance_method"],
        "best_resistance_line": best["resistance_line"],
        "baseline_metrics": baseline_metrics,
        "overlay_metrics": overlay_metrics,
        "uplift": best.get("uplift") or {},
        "validation": validation,
        "top_variants": top_rows[: max(1, int(top_n))],
        "tested_count": tested_count,
        "viable_count": len(top_rows),
        "invalid_pair_count": invalid_pair_count,
        "unavailable_count": unavailable_count,
    }


# ---------------------------------------------------------------------------
# Walk-forward evaluation (WFO) endpoint
# ---------------------------------------------------------------------------


def _sr_wfo_bar_date(index: pd.DatetimeIndex, bar_index: int | None) -> str | None:
    if bar_index is None:
        return None
    try:
        pos = int(bar_index)
    except Exception:
        return None
    if pos < 0 or pos >= len(index):
        return None
    return str(index[pos])[:10]


def _sr_wfo_attach_dates(payload: dict[str, Any], index: pd.DatetimeIndex) -> dict[str, Any]:
    windows = payload.get("windows")
    if not isinstance(windows, list):
        return payload
    for window in windows:
        if not isinstance(window, dict):
            continue
        window["train_start_date"] = _sr_wfo_bar_date(index, window.get("train_start"))
        window["train_end_date"] = _sr_wfo_bar_date(index, window.get("train_end"))
        window["test_start_date"] = _sr_wfo_bar_date(index, window.get("test_start"))
        window["test_end_date"] = _sr_wfo_bar_date(index, window.get("test_end"))
        trades = window.get("test_trades")
        if isinstance(trades, list):
            for trade in trades:
                if not isinstance(trade, dict):
                    continue
                trade["entry_date"] = _sr_wfo_bar_date(index, trade.get("entry_bar"))
                trade["exit_date"] = _sr_wfo_bar_date(index, trade.get("exit_bar"))
    return payload


def _sr_get_or_compute_wfo(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    timeframe: str,
    cost_bps: float,
    cooldown_bars: int,
) -> dict[str, Any]:
    context = _sr_prepare_context(
        db,
        symbol=symbol,
        horizon=horizon,
        timeframe=timeframe,
        cost_bps=cost_bps,
        cooldown_bars=cooldown_bars,
    )
    cache_key = _sr_variants_cache_key(
        symbol,
        horizon,
        timeframe,
        context["as_of"],
        cost_bps,
        cooldown_bars,
    )
    now = time.monotonic()
    cached = _SR_WFO_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _SR_WFO_CACHE_TTL:
        return cached[1]

    close = context["close"]
    high = context["high"]
    low = context["low"]
    ohlcv = context["ohlcv"]
    open_ = ohlcv["Open"].values.astype("float64") if "Open" in ohlcv.columns else None

    methods = _sr_build_base_methods(context)
    finalized = finalize_support_resistance_methods(context["current_close"], methods)
    eligible_methods = [
        m
        for m in finalized["methods"]
        if str(m.get("id")) != "score_inversion"
    ]
    support_options = [
        option
        for method in eligible_methods
        for option in _sr_method_line_options(dict(method), "support")
    ]
    resistance_options = [
        option
        for method in eligible_methods
        for option in _sr_method_line_options(dict(method), "resistance")
    ]

    candidate_method_ids = {
        str(option.get("method_id"))
        for option in [*support_options, *resistance_options]
        if str(option.get("method_id") or "")
    }
    methods_by_id = {
        method_id: dict(method)
        for method_id, method in ((str(m.get("id")), m) for m in finalized["methods"])
        if method_id in candidate_method_ids
    }

    if high is None or low is None:
        response = {
            "family": "support_resistance_wfo",
            "symbol": symbol,
            "horizon": horizon,
            "timeframe": timeframe,
            "as_of": context["as_of"],
            "wfo": {
                "status": "insufficient_history",
                "windows": [],
                "procedure_oos": {},
                "baselines": {},
                "stability": {},
                "live_recommendation": {},
                "decision": "no_edge",
                "explanation": "Donnees High/Low indisponibles pour cette instrument.",
                "params_echo": {},
            },
            "line_touch_stats": {"support": {}, "resistance": {}},
        }
        payload = {"response": response, "context": context}
        _SR_WFO_CACHE[cache_key] = (now, payload)
        return payload

    method_series = _sr_compute_method_series(context, methods_by_id)

    pair_series: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    pair_meta: dict[str, dict[str, Any]] = {}
    for support_option in support_options:
        sid = str(support_option.get("method_id"))
        support_line_id = normalize_line_id(support_option.get("line_id"))
        support_series = _sr_get_component_series(method_series, sid, support_line_id, "support")
        if not isinstance(support_series, np.ndarray) or len(support_series) != len(close):
            continue
        for resistance_option in resistance_options:
            rid = str(resistance_option.get("method_id"))
            resistance_line_id = normalize_line_id(resistance_option.get("line_id"))
            resistance_series = _sr_get_component_series(method_series, rid, resistance_line_id, "resistance")
            if not isinstance(resistance_series, np.ndarray) or len(resistance_series) != len(close):
                continue
            pair_id = _sr_variant_id(sid, rid, support_line_id, resistance_line_id)
            pair_series[pair_id] = (support_series, resistance_series)
            pair_meta[pair_id] = {
                "support_method_id": sid,
                "support_line_id": support_line_id,
                "support_label": str(support_option.get("method_label") or sid),
                "support_line_label": str(support_option.get("line_label") or support_line_id),
                "resistance_method_id": rid,
                "resistance_line_id": resistance_line_id,
                "resistance_label": str(resistance_option.get("method_label") or rid),
                "resistance_line_label": str(resistance_option.get("line_label") or resistance_line_id),
            }

    hp = HORIZON_PARAMS.get(horizon, HORIZON_PARAMS["monthly"])
    if pair_series:
        wfo_result = run_sr_wfo(
            close=close,
            high=high,
            low=low,
            open_=open_,
            pair_series=pair_series,
            pair_meta=pair_meta,
            train=int(hp["train"]),
            test=int(hp["test"]),
            step=int(hp["step"]),
            cost_bps=float(cost_bps),
            cooldown_bars=int(cooldown_bars),
            min_train_trades=3,
            bootstrap_iter=1000,
            seed=42,
        )
    else:
        wfo_result = {
            "status": "insufficient_history",
            "windows": [],
            "procedure_oos": {},
            "baselines": {},
            "stability": {},
            "live_recommendation": {},
            "decision": "no_edge",
            "explanation": "Aucune paire support/resistance disponible.",
            "params_echo": {},
        }
    wfo_result = _sr_wfo_attach_dates(wfo_result, ohlcv.index)

    forward_bars = HORIZON_SPECS.get(horizon, HORIZON_SPECS["monthly"]).reference_forward_days
    touch_stats: dict[str, dict[str, Any]] = {"support": {}, "resistance": {}}
    for support_option in support_options:
        sid = str(support_option.get("method_id"))
        support_line_id = normalize_line_id(support_option.get("line_id"))
        series = _sr_get_component_series(method_series, sid, support_line_id, "support")
        if not isinstance(series, np.ndarray) or len(series) != len(close):
            continue
        component_id = _sr_component_id(sid, support_line_id)
        touch_stats["support"][component_id] = line_touch_stats(
            close=close,
            high=high,
            low=low,
            level_series=series,
            side="support",
            forward_bars=int(forward_bars),
        )
    for resistance_option in resistance_options:
        rid = str(resistance_option.get("method_id"))
        resistance_line_id = normalize_line_id(resistance_option.get("line_id"))
        series = _sr_get_component_series(method_series, rid, resistance_line_id, "resistance")
        if not isinstance(series, np.ndarray) or len(series) != len(close):
            continue
        component_id = _sr_component_id(rid, resistance_line_id)
        touch_stats["resistance"][component_id] = line_touch_stats(
            close=close,
            high=high,
            low=low,
            level_series=series,
            side="resistance",
            forward_bars=int(forward_bars),
        )

    response = {
        "family": "support_resistance_wfo",
        "symbol": symbol,
        "horizon": horizon,
        "timeframe": timeframe,
        "as_of": context["as_of"],
        "current_close": round_number(context["current_close"], 6),
        "wfo": wfo_result,
        "line_touch_stats": touch_stats,
    }
    payload = {"response": response, "context": context}
    _SR_WFO_CACHE[cache_key] = (now, payload)
    return payload


@router.post("/signal/support-resistance/wfo")
def signal_support_resistance_wfo(
    body: SupportResistanceRequest,
    db: Session = Depends(get_db),
):
    payload = _sr_get_or_compute_wfo(
        db,
        symbol=body.symbol,
        horizon=body.horizon,
        timeframe=body.timeframe,
        cost_bps=body.cost_bps,
        cooldown_bars=body.cooldown_bars,
    )
    return payload["response"]


