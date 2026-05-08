"""Strategy signals API — signal generation engine endpoints."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict
from typing import Any

import numpy as np
import pandas as pd

from fastapi import APIRouter, Depends, HTTPException
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from ..auth import rate_limit_trigger, require_admin
from ..db import get_db
from ..market_data_loader import load_close_for_symbol, load_ohlcv_for_symbol
from ..schemas.strategy import PivotPoints
from ..services.signal_engine_persistence import resolve_signal_engine_result
from ..schemas.strategy_signals import (
    BatchScoresRequest,
    FamilyEnsembleRequest,
    IndicatorSeriesRequest,
    PersistedSignalEngineSummariesRequest,
    RegimeConsensusRequest,
    SignalZoneChartRequest,
    SmaEnsembleRequest,
    SupportResistanceMethodDetailRequest,
    SupportResistanceMethodDetailResponse,
    SupportResistanceRequest,
    SupportResistanceResponse,
    SupportResistanceVariantRequest,
    VariantBacktestRequest,
    VariantDetailRequest,
)

from core.quant_core.signal_engine.ensemble import (
    run_family_ensemble_full,
    compute_family_score_timeseries,
    family_signal_is_available,
    _score_to_label,
)
from core.quant_core.signal_engine.domain import (
    ALL_FAMILIES,
    CATEGORY_FAMILIES,
    FAMILY_SIGNAL_TYPE,
    EnsemblePipelineDetail,
    HORIZON_PARAMS,
    OOSWindowResult,
    VariantDef,
    VariantRobustnessSummary,
    label_to_signal_value,
    signal_type_label,
    variant_signal_label,
)
from core.quant_core.signal_engine.support_resistance import (
    build_ma_anchor_method,
    compute_representative_ma_anchor,
    compute_score_inversion_levels,
    finalize_support_resistance_methods,
    round_number,
)
from core.quant_core.signal_engine.variant_detail import (
    compute_variant_detail,
    compute_variant_trade_register,
    _compute_indicator,
)
from core.quant_core.significance import sharpe_ratio
from core.quant_core.signal_engine.indicator_series import (
    compute_atr_series,
)
from core.quant_core.data import drop_incomplete_ohlcv_rows
from core.quant_core.signal_engine.rsi_semantics import latest_rsi_variant_signal
from core.quant_core.signal_engine.oos_eval import compute_signal_array
from core.quant_core.signal_engine.regime import validate_regime_oos, compute_regime_consensus
from core.quant_core.strategy_plan.execution_policy import build_execution_horizon_policy
from core.quant_core.strategy_plan.levels import compute_atr, compute_pivot_points, detect_swing_levels, compute_fibonacci_retracement_levels
from core.quant_core.decision.levels import compute_levels_support_resistance

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
_SR_INVERSION_CACHE: dict[tuple, tuple[float, dict[str, Any]]] = {}
_SR_INVERSION_CACHE_TTL = 180.0
_SR_INVERSION_SCAN_POINTS = 41
_SR_INVERSION_REFINE_STEPS = 6
_SR_INVERSION_MAX_EVALS = 320
_SR_VARIANTS_CACHE: dict[tuple, tuple[float, dict[str, Any]]] = {}
_SR_VARIANTS_CACHE_TTL = 240.0
_SR_VARIANT_BACKTEST_CACHE: dict[tuple, tuple[float, dict[str, Any]]] = {}
_SR_VARIANT_BACKTEST_CACHE_TTL = 240.0


def _sr_variants_cache_key(
    symbol: str,
    horizon: str,
    timeframe: str,
    as_of: str,
    cost_bps: float,
    cooldown_bars: int,
) -> tuple:
    return (
        symbol,
        horizon,
        timeframe,
        as_of,
        round(float(cost_bps), 4),
        int(cooldown_bars),
    )

_VOLUME_DEPENDENT = {"obv", "cmf", "ad", "vwap", "fi", "mfi"}
_HIGH_LOW_DEPENDENT = {"ichimoku", "psar", "adx", "stochastic", "cci", "mfi", "uo", "cmf"}
_INDICATOR_ARCHETYPES = {
    "sma": "price_vs_sma",
    "ema": "price_vs_ema",
    "ema_cross": "ema_cross",
    "ichimoku": "ichi_cloud",
    "psar": "psar_trend",
    "macd": "macd_cross",
    "roc": "roc_zero",
    "trix": "trix_zero",
    "adx": "adx_trend",
    "tsi": "tsi_zero",
    "rsi": "rsi_level",
    "stochastic": "stoch_level",
    "cci": "cci_level",
    "mfi": "mfi_level",
    "uo": "uo_level",
    "obv": "obv_trend",
    "cmf": "cmf_flow",
    "ad": "ad_trend",
    "vwap": "vwap_dev",
    "fi": "fi_trend",
}


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
    return drop_incomplete_ohlcv_rows(ohlcv)


def _validate_volume_data(family: str, symbol: str, ohlcv, volume: np.ndarray | None) -> None:
    """Raise 422 when a volume-based family lacks meaningful volume history."""
    if volume is None:
        logger.warning("%s requested for %s but Volume column missing from OHLCV", family, symbol)
        raise HTTPException(
            status_code=422,
            detail=f"Volume data missing for {symbol} - {family.upper()} cannot be computed. "
                   f"Available columns: {list(ohlcv.columns)}",
        )
    finite_volume = volume[np.isfinite(volume)]
    nonzero_ratio = (finite_volume != 0).mean() if len(finite_volume) > 0 else 0.0
    if nonzero_ratio < 0.01:
        logger.warning(
            "%s requested for %s but Volume is %.1f%% zeros/NaN",
            family,
            symbol,
            (1 - nonzero_ratio) * 100,
        )
        raise HTTPException(
            status_code=422,
            detail=f"Volume data for {symbol} is {(1 - nonzero_ratio)*100:.0f}% zeros/NaN - "
                   f"{family.upper()} requires real volume data to produce meaningful signals.",
        )


def _require_high_low(
    family: str,
    symbol: str,
    ohlcv,
) -> tuple[np.ndarray, np.ndarray]:
    if "High" not in ohlcv.columns or "Low" not in ohlcv.columns:
        raise HTTPException(
            status_code=422,
            detail=f"High/Low data missing for {symbol} - {family.upper()} cannot be computed.",
        )
    return (
        ohlcv["High"].values.astype("float64"),
        ohlcv["Low"].values.astype("float64"),
    )


def _variant_label(variant) -> str:
    """Generic human-readable label for any variant."""
    p = variant.params
    arch = variant.archetype
    if arch == "price_vs_sma":
        return f"SMA-{p.get('window', '?')}"
    if arch == "price_vs_ema":
        return f"EMA-{p.get('window', '?')}"
    if arch == "sma_cross":
        return f"SMA({p.get('fast')},{p.get('slow')})"
    if arch == "slope_confirmed":
        return f"SMA-{p.get('window')} Slope"
    if arch == "ema_cross":
        return f"EMA({p.get('fast')},{p.get('slow')})"
    if arch == "ichi_cloud":
        return f"Ichimoku({p.get('tenkan')},{p.get('kijun')},{p.get('senkou_b')})"
    if arch == "psar_trend":
        return f"PSAR({p.get('af_step')},{p.get('af_max')})"
    if arch == "rsi_level":
        return f"RSI({p.get('period', '?')},{p.get('oversold')},{p.get('overbought')})"
    if arch == "macd_cross":
        return f"MACD({p.get('fast')},{p.get('slow')},{p.get('signal')})"
    if arch == "roc_zero":
        return f"ROC-{p.get('period', '?')}"
    if arch == "trix_zero":
        return f"TRIX-{p.get('period', '?')}"
    if arch == "adx_trend":
        return f"ADX({p.get('period')},{p.get('adx_threshold')})"
    if arch == "tsi_zero":
        return f"TSI({p.get('long_period')},{p.get('short_period')})"
    if arch == "stoch_level":
        return f"Stoch({p.get('k_period')},{p.get('d_period')})"
    if arch == "cci_level":
        return f"CCI-{p.get('period', '?')}"
    if arch == "mfi_level":
        return f"MFI({p.get('period')},{p.get('oversold')},{p.get('overbought')})"
    if arch == "uo_level":
        return f"UO({p.get('period_1')},{p.get('period_2')},{p.get('period_3')})"
    if arch == "obv_trend":
        return f"OBV-EMA-{p.get('ema_period', '?')}"
    if arch == "cmf_flow":
        return f"CMF-{p.get('period', '?')}"
    if arch == "ad_trend":
        return f"AD-EMA-{p.get('ema_period', '?')}"
    if arch == "vwap_dev":
        return f"VWAP({p.get('period')},{p.get('threshold_pct')}%)"
    if arch == "fi_trend":
        return f"FI-{p.get('period', '?')}"
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
    cost_bps: float, cooldown_bars: int = 0, variant: str = "expanded",
) -> EnsemblePipelineDetail:
    """Return cached detail or compute and cache it."""
    key = (family, symbol, horizon, timeframe, cost_bps, cooldown_bars, variant)
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
    high = ohlcv["High"].values.astype("float64") if "High" in ohlcv.columns else None
    low = ohlcv["Low"].values.astype("float64") if "Low" in ohlcv.columns else None

    if family in _VOLUME_DEPENDENT:
        _validate_volume_data(family, symbol, ohlcv, volume)
    if family in _HIGH_LOW_DEPENDENT and (high is None or low is None):
        high, low = _require_high_low(family, symbol, ohlcv)

    if variant == "factor_x_ta":
        from core.quant_core.signal_engine.factor_x_ta import run_factor_x_ta_ensemble_for_family
        from services.worker.tasks.factor_x_ta_batch import (
            _build_channel_tag_gate,
            _build_conditions,
            _build_ticker_to_canonical,
            _get_enabled_factor_tickers,
            _get_selected_factor_tickers,
            _get_stock_sector,
            _load_channel_tags,
            _load_factor_series_from_store,
            _load_pre_registration,
        )

        all_conditions = _build_conditions(_load_pre_registration())
        selected_tickers = _get_selected_factor_tickers(db, symbol, horizon)
        enabled_tickers = _get_enabled_factor_tickers(db, symbol) or {c.factor_ticker for c in all_conditions}
        if selected_tickers:
            enabled_tickers &= selected_tickers
        active_conditions = [c for c in all_conditions if c.factor_ticker in enabled_tickers]
        ticker_to_canonical = _build_ticker_to_canonical()
        aligned_factor_arrays = {}
        for condition in active_conditions:
            ticker = condition.factor_ticker
            if ticker in aligned_factor_arrays:
                continue
            canonical_id = ticker_to_canonical.get(ticker, ticker)
            arr = _load_factor_series_from_store(db, canonical_id)
            if arr is not None:
                aligned_factor_arrays[ticker] = arr
        channel_gate = _build_channel_tag_gate(_load_channel_tags(), enabled_tickers)
        stock_sector = _get_stock_sector(db, symbol)
        detail = run_factor_x_ta_ensemble_for_family(
            family,
            close,
            aligned_factor_arrays,
            active_conditions,
            volume=volume,
            high=high,
            low=low,
            symbol=symbol,
            horizon=horizon,
            timeframe=timeframe,
            cost_bps=cost_bps,
            cooldown_bars=cooldown_bars,
            channel_tags=channel_gate,
            stock_sector=stock_sector,
        )
    else:
        detail = run_family_ensemble_full(
            family, close, volume=volume, high=high, low=low, symbol=symbol, horizon=horizon,
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
    detail = _get_or_compute(db, "sma", body.symbol, body.horizon, body.timeframe, body.cost_bps, body.cooldown_bars, variant="expanded")
    return asdict(detail.signal)


@router.post("/signal/family-ensemble")
def family_ensemble(body: FamilyEnsembleRequest, db: Session = Depends(get_db)):
    """Run the full signal engine pipeline for any family (Layers A->G)."""
    detail = _get_or_compute(db, body.family, body.symbol, body.horizon, body.timeframe, body.cost_bps, body.cooldown_bars, variant=body.variant)
    return asdict(detail.signal)


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
        pivot_method.update(
            {
                "support": max(support_candidates) if support_candidates else None,
                "resistance": min(resistance_candidates) if resistance_candidates else None,
                "status": "available" if support_candidates or resistance_candidates else "ignored",
                "explanation": (
                    "Calcul classique des points pivots (S1/S2, R1/R2) base sur "
                    "le Haut, Bas, Cloture de la seance precedente."
                ),
                "inputs": {
                    "pp": pivot.pp,
                    "s1": pivot.s1,
                    "s2": pivot.s2,
                    "r1": pivot.r1,
                    "r2": pivot.r2,
                    "prev_high": float(prev["High"]),
                    "prev_low": float(prev["Low"]),
                    "prev_close": float(prev["Close"]),
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
                "inputs": dict(quantile_levels.get("inputs") or {}),
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
                "inputs": fib.get("inputs") or {},
            }
        )
    methods.append(fib_method)
    return methods


def _sr_add_line(lines: dict[str, float], label: str, value: Any) -> None:
    numeric = round_number(value, 6)
    if numeric is not None:
        lines[label] = numeric


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
    elif method_id == "pivot_points":
        tail_len = min(30, len(ohlcv))
        inputs = method.get("inputs", {})
        _sr_add_line(lines, "PP", inputs.get("pp"))
        _sr_add_line(lines, "S1", inputs.get("s1"))
        _sr_add_line(lines, "S2", inputs.get("s2"))
        _sr_add_line(lines, "R1", inputs.get("r1"))
        _sr_add_line(lines, "R2", inputs.get("r2"))
    elif method_id == "quantile_extrema_atr":
        tail_len = min(120, len(ohlcv))
        _sr_add_line(lines, "Support quantile", method.get("support"))
        _sr_add_line(lines, "Resistance quantile", method.get("resistance"))
        inputs = method.get("inputs", {})
        _sr_add_line(lines, "Q20 support", inputs.get("support_q20"))
        _sr_add_line(lines, "Q80 resistance", inputs.get("resistance_q80"))
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
        "selected_support_method_id": (
            str(optimal["optimal_variant_id"]).split("sr:", 1)[-1].split("__", 1)[0]
            if optimal["optimal_status"] == "ready" and optimal["optimal_variant_id"]
            else None
        ),
        "selected_resistance_method_id": (
            str(optimal["optimal_variant_id"]).split("__", 1)[1]
            if optimal["optimal_status"] == "ready" and optimal["optimal_variant_id"] and "__" in str(optimal["optimal_variant_id"])
            else None
        ),
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
    "quantile_extrema_atr",
)


def _sr_method_rank(method_id: str) -> int:
    try:
        return _SR_VARIANT_METHOD_ORDER.index(method_id)
    except ValueError:
        return len(_SR_VARIANT_METHOD_ORDER)


def _sr_variant_id(support_method_id: str, resistance_method_id: str) -> str:
    return f"sr:{support_method_id}__{resistance_method_id}"


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
    return support_method_id, resistance_method_id


def _sr_signal_from_levels(current_close: float, support: float | None, resistance: float | None) -> tuple[float, str]:
    if support is not None and current_close <= support:
        return 1.0, "HAUSSIER"
    if resistance is not None and current_close >= resistance:
        return -1.0, "BAISSIER"
    return 0.0, "NEUTRE"


def _sr_methodology_context(horizon: str, available_bars: int) -> dict[str, Any]:
    hp = HORIZON_PARAMS.get(horizon, HORIZON_PARAMS["medium"])
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
    hp = HORIZON_PARAMS.get(horizon, HORIZON_PARAMS["medium"])
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
    hp = HORIZON_PARAMS.get(horizon, HORIZON_PARAMS["medium"])
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
    method_series: dict[str, dict[str, np.ndarray]],
    support_method_id: str,
    resistance_method_id: str,
    window: tuple[int, int, int, int, int],
    cost_bps: float,
    cooldown_bars: int,
) -> tuple[OOSWindowResult | None, dict[str, Any] | None]:
    close = context["close"]
    high = context["high"]
    low = context["low"]
    if high is None or low is None:
        return None, None
    support_series = method_series.get(support_method_id, {}).get("support")
    resistance_series = method_series.get(resistance_method_id, {}).get("resistance")
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
    method_series: dict[str, dict[str, np.ndarray]],
    support_method_id: str,
    resistance_method_id: str,
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
) -> dict[str, dict[str, np.ndarray]]:
    close = context["close"]
    high = context["high"]
    low = context["low"]
    volume = context["volume"]
    ohlcv = context["ohlcv"]
    policy = context["policy"]
    n = len(close)

    output: dict[str, dict[str, np.ndarray]] = {
        method_id: {
            "support": np.full(n, np.nan, dtype="float64"),
            "resistance": np.full(n, np.nan, dtype="float64"),
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

    if high is None or low is None:
        return output

    quantile_lookback = max(140, int(policy.structural_lookback))
    swing_padding = max(int(policy.swing_left_bars), int(policy.swing_right_bars)) + 8
    swing_lookback = int(policy.structural_lookback) + swing_padding

    for bar_index in range(1, n):
        prev_close = float(close[bar_index - 1]) if np.isfinite(close[bar_index - 1]) else None
        if prev_close is None:
            continue

        if "pivot_points" in output and bar_index >= 2:
            prev_high = float(high[bar_index - 1])
            prev_low = float(low[bar_index - 1])
            prev_close_bar = float(close[bar_index - 1])
            pivot = compute_pivot_points(
                prev_high=prev_high,
                prev_low=prev_low,
                prev_close=prev_close_bar,
            )
            support_candidates = [float(v) for v in (pivot.get("s1"), pivot.get("s2")) if v is not None and float(v) <= prev_close]
            resistance_candidates = [float(v) for v in (pivot.get("r1"), pivot.get("r2")) if v is not None and float(v) >= prev_close]
            if support_candidates:
                output["pivot_points"]["support"][bar_index] = max(support_candidates)
            if resistance_candidates:
                output["pivot_points"]["resistance"][bar_index] = min(resistance_candidates)

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
            if resistance is not None and resistance >= prev_close:
                output["quantile_extrema_atr"]["resistance"][bar_index] = resistance

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
            if fib_s is not None and fib_s <= prev_close:
                output["fibonacci_retracement"]["support"][bar_index] = fib_s
            if fib_r is not None and fib_r >= prev_close:
                output["fibonacci_retracement"]["resistance"][bar_index] = fib_r

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
    support_methods = [
        m
        for m in finalized["methods"]
        if str(m.get("id")) != "score_inversion"
        and str(m.get("status")) == "available"
        and _sr_level_or_none(m.get("support")) is not None
    ]
    resistance_methods = [
        m
        for m in finalized["methods"]
        if str(m.get("id")) != "score_inversion"
        and str(m.get("status")) == "available"
        and _sr_level_or_none(m.get("resistance")) is not None
    ]
    support_methods.sort(key=lambda m: (_sr_method_rank(str(m.get("id"))), str(m.get("id"))))
    resistance_methods.sort(key=lambda m: (_sr_method_rank(str(m.get("id"))), str(m.get("id"))))

    candidate_method_ids = {
        str(m.get("id"))
        for m in [*support_methods, *resistance_methods]
        if str(m.get("id") or "")
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
        for support_method in support_methods:
            sid = str(support_method.get("id"))
            support_current = _sr_level_or_none(support_method.get("support"))
            support_label = str(support_method.get("label") or sid)
            for resistance_method in resistance_methods:
                rid = str(resistance_method.get("id"))
                resistance_current = _sr_level_or_none(resistance_method.get("resistance"))
                resistance_label = str(resistance_method.get("label") or rid)
                variant_id = _sr_variant_id(sid, rid)
                tested_variant_ids.append(variant_id)
                variant_def = VariantDef(
                    variant_id=variant_id,
                    family="sr",
                    archetype="sr_combo",
                    params={"support_method_id": sid, "resistance_method_id": rid},
                    description=f"Support {support_label} / Resistance {resistance_label}",
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
            }
        )

    representative_rows = [row for row in all_variants if row["is_representative"]]
    methods_for_response = []
    for method in finalized["methods"]:
        row = dict(method)
        row["selected_for_support"] = bool(row.get("id") == selected_support_method_id)
        row["selected_for_resistance"] = bool(row.get("id") == selected_resistance_method_id)
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
        support_method_id, resistance_method_id = _sr_parse_variant_id(variant_id)
        detail_windows, total_realized = _sr_compute_variant_windows(
            context=payload["context"],
            method_series=payload["method_series"],
            support_method_id=support_method_id,
            resistance_method_id=resistance_method_id,
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

    support_method_id, resistance_method_id = _sr_parse_variant_id(variant_id)
    method_series = payload["method_series"]
    support_series = method_series.get(support_method_id, {}).get("support")
    resistance_series = method_series.get(resistance_method_id, {}).get("resistance")
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
    v = getattr(body, "variant", "expanded")
    for family in ALL_FAMILIES:
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
    for family in ALL_FAMILIES:
        detail = _get_or_compute(db, family, body.symbol, body.horizon, body.timeframe, body.cost_bps, body.cooldown_bars, variant=v)
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
    high = ohlcv["High"].values.astype("float64") if "High" in ohlcv.columns else None
    low = ohlcv["Low"].values.astype("float64") if "Low" in ohlcv.columns else None
    oos_windows = detail.oos_windows.get(body.variant_id, [])

    result = compute_variant_detail(
        ohlcv, close, target.variant, oos_windows,
        volume=volume, high=high, low=low, cost_bps=body.cost_bps, cooldown_bars=body.cooldown_bars,
        force_valid_windows=body.variant_id in detail.representative_ids,
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


@router.post("/engine/persisted-summaries", summary="Get persisted signal engine summaries for multiple symbols")
def persisted_signal_engine_summaries(
    body: PersistedSignalEngineSummariesRequest,
    db: Session = Depends(get_db),
):
    """Return sidebar-ready persisted Signal Engine summaries.

    Unlike /signal/batch-scores, this endpoint never recomputes from ALL_FAMILIES.
    It mirrors the saved signal-engine page state for the requested variant.
    """
    from ..models import MarketDataStore, SignalEngineGlobalResult

    symbols = [symbol.strip().upper() for symbol in body.symbols if symbol and symbol.strip()]
    if not symbols:
        return []

    symbol_set = set(symbols)
    global_rows = [
        row
        for row in db.query(SignalEngineGlobalResult)
        .filter_by(horizon=body.horizon, variant=body.variant)
        .all()
        if row.symbol in symbol_set
    ]
    market_rows = [
        row
        for row in db.query(MarketDataStore)
        .filter_by(timeframe=body.timeframe)
        .all()
        if row.symbol in symbol_set
    ]
    global_by_symbol = {row.symbol: row for row in global_rows}
    market_as_of_by_symbol = {row.symbol: row.data_as_of for row in market_rows}

    results: list[dict[str, Any]] = []
    for symbol in symbols:
        row = global_by_symbol.get(symbol)
        market_data_as_of = market_as_of_by_symbol.get(symbol)
        score = None
        label = None
        data_as_of = None
        computed_at = None
        is_stale = False

        if row is not None:
            score = (
                row.aggregate_score_pct
                if body.variant == "legacy"
                else row.expanded_aggregate_score_pct
            )
            label = row.signal_label
            data_as_of = row.data_as_of.isoformat() if row.data_as_of else None
            computed_at = row.computed_at.isoformat() if row.computed_at else None
            is_stale = bool(
                row.data_as_of
                and market_data_as_of
                and row.data_as_of < market_data_as_of
            )

        results.append(
            {
                "symbol": symbol,
                "aggregate_score_pct": score,
                "aggregate_signal_label": label,
                "data_as_of": data_as_of,
                "market_data_as_of": market_data_as_of.isoformat() if market_data_as_of else None,
                "computed_at": computed_at,
                "is_stale": is_stale,
            }
        )

    # Best-effort: auto-enqueue a lightweight refresh for any stale signal that has no active job.
    if any(r["is_stale"] for r in results):
        try:
            from ..models import SignalEngineBatchJob
            from services.worker.tasks.signal_enqueue import enqueue_signal_engine_refresh_for_symbol
            for r in results:
                if not r["is_stale"]:
                    continue
                already_active = (
                    db.query(SignalEngineBatchJob)
                    .filter(
                        SignalEngineBatchJob.symbol == r["symbol"],
                        SignalEngineBatchJob.horizon == body.horizon,
                        SignalEngineBatchJob.variant == body.variant,
                        SignalEngineBatchJob.job_type == "signal_engine",
                        SignalEngineBatchJob.status.in_(["queued", "running", "pending"]),
                    )
                    .first()
                )
                if not already_active:
                    enqueue_signal_engine_refresh_for_symbol(
                        r["symbol"], body.horizon, variant=body.variant, triggered_by="auto_stale"
                    )
        except Exception:
            pass

    return results


# ---------------------------------------------------------------------------
# Layer H — Regime-aware consensus
# ---------------------------------------------------------------------------

_REGIME_CACHE: dict[tuple, tuple[float, dict]] = {}
_REGIME_CACHE_TTL = 600.0  # 10 minutes
_REGIME_CONSENSUS_ENABLED = True


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

    # 1. Compute all family ensembles (each individually cached at 5min TTL)
    family_scores: dict[str, float] = {}
    family_details: dict[str, EnsemblePipelineDetail] = {}
    for family in ALL_FAMILIES:
        try:
            detail = _get_or_compute(
                db, family, body.symbol, body.horizon, body.timeframe,
                body.cost_bps, body.cooldown_bars, variant=body.variant,
            )
            if not family_signal_is_available(detail.signal):
                continue
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
    high = ohlcv["High"].values.astype("float64") if "High" in ohlcv.columns else None
    low = ohlcv["Low"].values.astype("float64") if "Low" in ohlcv.columns else None

    # 3. Extract top variant per family (highest reliability) and compute signal arrays
    family_signals: dict[str, np.ndarray] = {}
    for family, detail in family_details.items():
        if not detail.all_summaries:
            continue
        top_variant = max(detail.all_summaries, key=lambda s: s.reliability_score).variant
        try:
            sig = compute_signal_array(close, top_variant, volume=volume, high=high, low=low)
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
    high: np.ndarray | None,
    low: np.ndarray | None,
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

        ind = _compute_indicator(close, s.variant, volume=volume, high=high, low=low)
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
    high: np.ndarray | None,
    low: np.ndarray | None,
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
    ind = _compute_indicator(close, top.variant, volume=volume, high=high, low=low)
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
    high = ohlcv["High"].values.astype("float64") if "High" in ohlcv.columns else None
    low = ohlcv["Low"].values.astype("float64") if "Low" in ohlcv.columns else None
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
                variant=body.variant,
            )
        except HTTPException:
            continue  # skip family if data insufficient (e.g. OBV without volume)

        scores = compute_family_score_timeseries(
            detail,
            close,
            volume=volume,
            high=high,
            low=low,
            cooldown_bars=body.cooldown_bars,
            family_history_mode=body.family_history_mode,
            symbol=body.symbol,
            horizon=body.horizon,
            timeframe=body.timeframe,
            signal_cost_bps=body.cost_bps,
        )

        families[fam] = {
            "scores": [round(float(s), 2) for s in scores],
            "representatives": _get_all_representative_indicators(detail, close, volume, high, low),
            "indicator": _get_top_representative_indicator(detail, close, volume, high, low),
        }

    return {
        "symbol": body.symbol,
        "horizon": body.horizon,
        "bars": bars,
        "families": families,
    }


# ---------------------------------------------------------------------------
# Signal Engine Persistence API — added 2026-04-20
# ---------------------------------------------------------------------------

from pydantic import BaseModel as _BaseModel
from typing import Optional as _Optional


class _TriggerBody(_BaseModel):
    symbol: str
    horizon: str
    variant: str = "expanded"
    triggered_by: str = "manual"


class _BacktestTriggerBody(_BaseModel):
    symbol: str
    horizon: str
    variant: str = "expanded"
    window_start: str = "2026-01-01"
    window_end: _Optional[str] = None
    mc_config: _Optional[dict] = None
    triggered_by: str = "manual"


class _TriggerAllBody(_BaseModel):
    variants: list[str] = ["legacy", "expanded"]


@router.post(
    "/engine/trigger",
    summary="Trigger signal engine batch for one symbol/horizon",
    dependencies=[Depends(rate_limit_trigger)],
)
def trigger_signal_engine(body: _TriggerBody, db: Session = Depends(get_db)):
    """Enqueue computation of A→G engine results for (symbol, horizon).

    Returns the RQ job_id. Results are persisted to signal_engine_family_result
    and signal_engine_global_result.
    """
    from services.worker.tasks.signal_enqueue import enqueue_signal_engine_for_symbol

    try:
        if str(body.variant or "").strip().lower() == "factor_x_ta":
            from services.api.app.queue import _get_macro_ingest_queue
            from services.worker.tasks.factor_selection_full import run_factor_selection_for_symbol
            from services.worker.tasks.factor_x_ta_batch import enqueue_factor_x_ta_for_symbol
            from services.worker.tasks.wfo_factor_x_ta_batch import enqueue_wfo_factor_x_ta_for_symbol

            q = _get_macro_ingest_queue()
            fs_job = q.enqueue(
                run_factor_selection_for_symbol,
                body.symbol,
                False,
                job_timeout=3600,
            )
            engine_job_id = enqueue_factor_x_ta_for_symbol(
                body.symbol,
                body.horizon,
                triggered_by=body.triggered_by,
                depends_on=fs_job.id,
            )
            wfo_job_id = enqueue_wfo_factor_x_ta_for_symbol(
                body.symbol,
                body.horizon,
                triggered_by=body.triggered_by,
                depends_on=fs_job.id,
            )
            return {
                "job_id": engine_job_id,
                "factor_selection_job_id": fs_job.id,
                "engine_job_id": engine_job_id,
                "wfo_job_id": wfo_job_id,
                "status": "queued",
            }

        job_id = enqueue_signal_engine_for_symbol(
            body.symbol, body.horizon,
            variant=body.variant,
            triggered_by=body.triggered_by,
        )
        return {"job_id": job_id, "status": "queued"}
    except RedisError as exc:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/engine/trigger-all",
    summary="Trigger signal engine batch for all active symbols/horizons",
    dependencies=[Depends(require_admin), Depends(rate_limit_trigger)],
)
def trigger_all_signal_engine(body: _TriggerAllBody, db: Session = Depends(get_db)):
    """Fan out signal-engine jobs for every active symbol × horizon × variant."""
    from services.api.app.models import StockMaster
    from services.worker.tasks.signal_enqueue import enqueue_signal_engine_for_symbol

    horizons = ["short", "medium", "long"]
    allowed_variants = {"legacy", "expanded"}
    batch_id = uuid.uuid4().hex

    variants: list[str] = []
    for raw in body.variants or ["legacy", "expanded"]:
        value = str(raw or "").strip().lower()
        if not value:
            continue
        if value not in allowed_variants:
            raise HTTPException(status_code=422, detail=f"Invalid variant '{raw}'. Allowed: legacy, expanded.")
        if value not in variants:
            variants.append(value)
    if not variants:
        variants = ["legacy", "expanded"]

    symbols = [row.symbol for row in db.query(StockMaster).filter_by(is_active=True).all()]

    total_jobs = 0
    try:
        for symbol in symbols:
            for horizon in horizons:
                for variant in variants:
                    enqueue_signal_engine_for_symbol(
                        symbol,
                        horizon,
                        variant=variant,
                        triggered_by="manual_global",
                        batch_id=batch_id,
                    )
                    total_jobs += 1
    except RedisError as exc:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "batch_id": batch_id,
        "total_jobs": total_jobs,
        "symbols": len(symbols),
        "horizons": horizons,
        "variants": variants,
    }


@router.post(
    "/backtest-mc/trigger",
    summary="Trigger signal backtest + MC for one symbol/horizon",
    dependencies=[Depends(rate_limit_trigger)],
)
def trigger_signal_backtest(body: _BacktestTriggerBody, db: Session = Depends(get_db)):
    """Enqueue signal-based backtest + Monte Carlo computation.

    Results are persisted to signal_backtest_run. Use GET /signal/backtest-mc
    to read results once the job completes.
    """
    from services.worker.tasks.signal_enqueue import enqueue_signal_backtest_for_symbol

    try:
        job_id = enqueue_signal_backtest_for_symbol(
            body.symbol, body.horizon,
            variant=body.variant,
            window_start=body.window_start,
            window_end=body.window_end,
            mc_config=body.mc_config,
            triggered_by=body.triggered_by,
        )
        return {"job_id": job_id, "status": "queued"}
    except RedisError as exc:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/engine/result", summary="Get persisted signal engine results for one symbol/horizon")
def get_signal_engine_result(
    symbol: str,
    horizon: str,
    variant: str = "expanded",
    cooldown_bars: int = 0,
    db: Session = Depends(get_db),
):
    """Return persisted Signal Engine state for this tuple without mutating it."""
    try:
        return resolve_signal_engine_result(
            db,
            symbol=symbol,
            horizon=horizon,
            variant=variant,
            cooldown_bars=max(0, int(cooldown_bars)),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to resolve signal engine result for %s/%s/%s", symbol, horizon, variant)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/backtest-mc", summary="Get persisted signal backtest + MC results for one symbol/horizon")
def get_signal_backtest_results(
    symbol: str,
    horizon: str,
    variant: str = "expanded",
    source: _Optional[str] = None,
    scope: _Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Return all signal_backtest_run rows for (symbol, horizon).

    Optional filters:
      - source: "engine" | "wfo"
      - scope: "per_category" | "global" | "combination"

    Returns 404 when no results exist yet.
    Includes is_stale flag based on data_as_of vs market_data_store.data_as_of.
    """
    from services.api.app.models import SignalBacktestRun, MarketDataStore

    q = db.query(SignalBacktestRun).filter_by(symbol=symbol, horizon=horizon, variant=variant)
    if source:
        q = q.filter(SignalBacktestRun.source == source)
    if scope:
        q = q.filter(SignalBacktestRun.scope == scope)

    rows = q.order_by(SignalBacktestRun.scope, SignalBacktestRun.scope_key, SignalBacktestRun.source).all()
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=f"No backtest results for {symbol}/{horizon}/{variant}. Trigger /strategy/backtest-mc/trigger first.",
        )

    mds = db.query(MarketDataStore).filter_by(symbol=symbol, timeframe="1D").first()
    market_data_as_of = mds.data_as_of.isoformat() if (mds and mds.data_as_of) else None

    results = []
    for row in rows:
        row_data_as_of = row.data_as_of.isoformat() if row.data_as_of else None
        is_stale = (
            row_data_as_of is None
            or (market_data_as_of and row_data_as_of < market_data_as_of)
        )
        results.append({
            "source": row.source,
            "scope": row.scope,
            "scope_key": row.scope_key,
            "status": row.status,
            "warning_code": row.warning_code,
            "window_start": row.window_start.isoformat() if row.window_start else None,
            "window_end": row.window_end.isoformat() if row.window_end else None,
            "n_bars": row.n_bars,
            "n_trades": row.n_trades,
            "equity": row.equity_json,
            "dates": row.dates_json,
            "trades": row.trades_json,
            "close_series": row.close_series_json,
            "position_series": row.position_series_json,
            "signal_diagnostics": row.signal_diagnostics_json,
            "metrics": {
                "total_return": row.total_return,
                "cagr": row.cagr,
                "sharpe": row.sharpe,
                "max_drawdown": row.max_drawdown,
                "win_rate": row.win_rate,
                "n_trades": row.n_trades,
            },
            "mc": {
                "method": row.mc_method,
                "n_paths": row.n_paths,
                "envelope": row.mc_envelope_json,
                "stats": row.mc_stats_json,
            },
            "shuffle_stats": row.shuffle_stats_json,
            "computed_at": row.computed_at.isoformat() if row.computed_at else None,
            "data_as_of": row_data_as_of,
            "is_stale": is_stale,
        })

    return {
        "symbol": symbol,
        "horizon": horizon,
        "variant": variant,
        "market_data_as_of": market_data_as_of,
        "results": results,
    }


def _batch_job_status_payload(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    variant: str,
    job_type: str,
):
    from services.api.app.models import SignalEngineBatchJob

    rows = (
        db.query(SignalEngineBatchJob)
        .filter_by(symbol=symbol, horizon=horizon, variant=variant, job_type=job_type)
        .order_by(
            SignalEngineBatchJob.started_at.desc().nullslast(),
            SignalEngineBatchJob.created_at.desc(),
        )
        .limit(5)
        .all()
    )
    return {
        "symbol": symbol,
        "horizon": horizon,
        "variant": variant,
        "job_type": job_type,
        "jobs": [
            {
                "id": str(row.id),
                "job_type": row.job_type,
                "status": row.status,
                "rq_job_id": row.rq_job_id,
                "triggered_by": row.triggered_by,
                "batch_id": row.batch_id,
                "total_units": row.total_units,
                "completed_units": row.completed_units,
                "failed_units": row.failed_units,
                "error_message": row.error_message,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
    }


@router.get("/engine/batch-status", summary="Get latest signal engine batch job status")
def get_signal_engine_batch_status(
    symbol: str,
    horizon: str,
    variant: str = "expanded",
    db: Session = Depends(get_db),
):
    """Return recent signal_engine batch jobs for this (symbol, horizon)."""
    return _batch_job_status_payload(
        db,
        symbol=symbol,
        horizon=horizon,
        variant=variant,
        job_type="signal_engine",
    )


@router.get("/engine/batch-status-global", summary="Get global signal engine batch status for manual global runs")
def get_signal_engine_batch_status_global(
    batch_id: _Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Aggregate latest status per tuple for one manual global launch batch."""
    from services.api.app.models import SignalEngineBatchJob

    query = db.query(SignalEngineBatchJob).filter_by(
        job_type="signal_engine",
        triggered_by="manual_global",
    )
    if batch_id:
        query = query.filter_by(batch_id=batch_id)
        effective_batch_id = batch_id
    else:
        seed_rows = query.all()
        latest_with_batch = None
        latest_ts = 0.0
        for row in seed_rows:
            current_batch = str(getattr(row, "batch_id", "") or "").strip()
            if not current_batch:
                continue
            created_ts = row.created_at.timestamp() if getattr(row, "created_at", None) else 0.0
            if created_ts >= latest_ts:
                latest_ts = created_ts
                latest_with_batch = current_batch
        effective_batch_id = latest_with_batch
        if effective_batch_id:
            query = query.filter_by(batch_id=effective_batch_id)

    rows = query.all()

    latest_by_key: dict[tuple[str, str, str], Any] = {}
    for row in rows:
        key = (str(row.symbol), str(row.horizon), str(row.variant))
        previous = latest_by_key.get(key)
        row_created = row.created_at.timestamp() if getattr(row, "created_at", None) else 0.0
        prev_created = previous.created_at.timestamp() if (previous and getattr(previous, "created_at", None)) else 0.0
        if previous is None or row_created >= prev_created:
            latest_by_key[key] = row

    counts = {
        "succeeded": 0,
        "running": 0,
        "failed": 0,
        "pending": 0,
        "partial": 0,
    }
    for row in latest_by_key.values():
        status = str(getattr(row, "status", "") or "pending").strip().lower()
        if status in counts:
            counts[status] += 1
        elif status in ("queued",):
            counts["pending"] += 1
        elif status == "no_signal":
            # Computation completed normally — no tradeable signal found. Count as done.
            counts["succeeded"] += 1
        else:
            counts["failed"] += 1

    return {
        "batch_id": effective_batch_id,
        "total": len(latest_by_key),
        "succeeded": counts["succeeded"],
        "running": counts["running"],
        "failed": counts["failed"],
        "pending": counts["pending"],
        "partial": counts["partial"],
    }


@router.get("/backtest-mc/batch-status", summary="Get latest signal backtest batch job status")
def get_signal_backtest_batch_status(
    symbol: str,
    horizon: str,
    variant: str = "expanded",
    db: Session = Depends(get_db),
):
    """Return recent signal_backtest batch jobs for this (symbol, horizon)."""
    return _batch_job_status_payload(
        db,
        symbol=symbol,
        horizon=horizon,
        variant=variant,
        job_type="signal_backtest",
    )
