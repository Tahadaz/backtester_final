"""Strategy signals API — signal generation engine endpoints."""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict
from typing import Any, Literal

import numpy as np
import pandas as pd

from fastapi import APIRouter, Depends, HTTPException, Query
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
    VARIANT_FAMILIES,
    VariantDef,
    VariantRobustnessSummary,
    LEGACY_CATEGORY_FAMILIES,
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
from core.quant_core.signal_engine.sr_levels import (
    compute_pivot_family_levels,
    finite_float as _sr_finite_float,
    nearest_support_resistance_from_lines,
    normalize_line_id,
    split_support_resistance_lines,
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
from core.quant_core.signal_engine.ta_combo import factor_condition_to_dict
from core.quant_core.strategy_plan.execution_policy import build_execution_horizon_policy
from core.quant_core.strategy_plan.levels import compute_atr, compute_pivot_points, detect_swing_levels, compute_fibonacci_retracement_levels
from core.quant_core.decision.levels import compute_levels_support_resistance
from core.quant_core.horizons import LEGACY_HORIZON_ALIASES, canonical_horizon
from core.quant_core.risk import monte_carlo_equity_paths
from core.quant_core.signal_engine.modes import (
    ALL_SIGNAL_MODE_NAMES,
    resolve_signal_mode,
    signal_mode_read_names,
    signal_mode_storage_name,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/strategy", tags=["strategy-signals"])

CanonicalHorizon = Literal["weekly", "monthly", "quarterly"]


def _require_canonical_signal_horizon(horizon: str) -> str:
    try:
        return canonical_horizon(horizon, allow_legacy=False)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Signal Engine requires canonical horizon weekly/monthly/quarterly; got {horizon!r}.",
        ) from exc

# ---------------------------------------------------------------------------
# In-process TTL cache — keyed by (family, symbol, horizon, timeframe, cost_bps)
# ---------------------------------------------------------------------------

_CACHE: dict[tuple, tuple[float, EnsemblePipelineDetail]] = {}
_CACHE_TTL = 300.0  # 5 minutes

_BACKTEST_CACHE: dict[tuple, tuple[float, dict]] = {}
_BACKTEST_CACHE_TTL = 600.0
_BACKTEST_CACHE_VERSION = 5
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


def _finite_live_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if np.isfinite(parsed) else None


def _normalized_bar_date(value: Any) -> pd.Timestamp:
    try:
        parsed = pd.Timestamp(value).normalize()
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid live_bar date: {value!r}") from exc
    if pd.isna(parsed):
        raise HTTPException(status_code=422, detail=f"Invalid live_bar date: {value!r}")
    if parsed.tzinfo is not None:
        parsed = parsed.tz_convert(None)
    return parsed


def _apply_indicator_live_bar(ohlcv, live_bar) -> tuple[pd.DataFrame, bool]:
    """Merge a dashboard live quote into the transient OHLCV frame only."""
    if live_bar is None:
        return ohlcv, False

    live_close = _finite_live_number(live_bar.close)
    if live_close is None or live_close <= 0:
        raise HTTPException(status_code=422, detail="live_bar.close must be a finite positive number")

    live_date = _normalized_bar_date(live_bar.date)
    last_index = ohlcv.index[-1]
    last_date = _normalized_bar_date(last_index)
    if live_date < last_date:
        return ohlcv, False

    same_date = live_date == last_date
    frame = ohlcv.copy()
    target_index = last_index if same_date else live_date
    existing = frame.iloc[-1] if same_date else None

    def existing_number(column: str) -> float | None:
        if existing is None or column not in frame.columns:
            return None
        return _finite_live_number(existing[column])

    live_open = _finite_live_number(live_bar.open)
    open_value = live_open if live_open is not None else existing_number("Open") or live_close

    high_seed = _finite_live_number(live_bar.high)
    if high_seed is None:
        high_seed = existing_number("High") if same_date else None
    high_value = max(value for value in [high_seed, open_value, live_close] if value is not None)

    low_seed = _finite_live_number(live_bar.low)
    if low_seed is None:
        low_seed = existing_number("Low") if same_date else None
    low_value = min(value for value in [low_seed, open_value, live_close] if value is not None)

    volume_value = _finite_live_number(live_bar.volume)
    if volume_value is None:
        volume_value = existing_number("Volume") if same_date else 0.0
    volume_value = max(0.0, volume_value or 0.0)

    if same_date:
        if "Open" in frame.columns:
            frame.at[target_index, "Open"] = open_value
        if "High" in frame.columns:
            frame.at[target_index, "High"] = high_value
        if "Low" in frame.columns:
            frame.at[target_index, "Low"] = low_value
        frame.at[target_index, "Close"] = live_close
        if "Volume" in frame.columns:
            frame.at[target_index, "Volume"] = volume_value
        return frame, True

    row = frame.iloc[-1].copy()
    if "Open" in frame.columns:
        row["Open"] = open_value
    if "High" in frame.columns:
        row["High"] = high_value
    if "Low" in frame.columns:
        row["Low"] = low_value
    row["Close"] = live_close
    if "Volume" in frame.columns:
        row["Volume"] = volume_value
    frame.loc[target_index] = row
    return frame, True


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
    horizon = canonical_horizon(horizon, allow_legacy=True)
    variant = signal_mode_storage_name(variant)
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

    mode = resolve_signal_mode(variant)
    variant = mode.name
    if mode.is_factor_x_ta:
        from core.quant_core.signal_engine.factor_x_ta import (
            run_factor_x_ta_combo_ensemble_for_category,
            run_factor_x_ta_ensemble_for_family,
        )
        from services.worker.tasks.factor_x_ta_batch import (
            _build_runtime_inputs,
            _build_conditions,
            _load_channel_tags,
            _load_pre_registration,
        )

        all_conditions = _build_conditions(_load_pre_registration())
        runtime = _build_runtime_inputs(
            db,
            symbol=symbol,
            horizon=horizon,
            ohlcv=ohlcv,
            all_conditions=all_conditions,
            channel_tags_yaml=_load_channel_tags(),
        )
        if mode.is_combo:
            category = family.rsplit("_", 1)[-1]
            category_families = LEGACY_CATEGORY_FAMILIES if mode.universe == "legacy" else CATEGORY_FAMILIES
            detail = run_factor_x_ta_combo_ensemble_for_category(
                category=category,
                combo_family=family,
                category_families=category_families,
                close=close,
                aligned_factor_arrays=runtime.aligned_factor_arrays,
                conditions=runtime.conditions,
                volume=volume,
                high=high,
                low=low,
                symbol=symbol,
                horizon=horizon,
                timeframe=timeframe,
                cost_bps=cost_bps,
                cooldown_bars=cooldown_bars,
                channel_tags=runtime.channel_gate,
                stock_sector=runtime.stock_sector,
            )
        else:
            detail = run_factor_x_ta_ensemble_for_family(
                family,
                close,
                runtime.aligned_factor_arrays,
                runtime.conditions,
                volume=volume,
                high=high,
                low=low,
                symbol=symbol,
                horizon=horizon,
                timeframe=timeframe,
                cost_bps=cost_bps,
                cooldown_bars=cooldown_bars,
                channel_tags=runtime.channel_gate,
                stock_sector=runtime.stock_sector,
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
    horizon: CanonicalHorizon
    variant: str = "expanded"
    triggered_by: str = "manual"


class _BacktestTriggerBody(_BaseModel):
    symbol: str
    horizon: CanonicalHorizon
    variant: str = "expanded"
    window_start: str = "2026-01-01"
    window_end: _Optional[str] = None
    cooldown_bars: _Optional[int] = None
    mc_config: _Optional[dict] = None
    triggered_by: str = "manual"


class _TriggerAllBody(_BaseModel):
    variants: list[str] = list(ALL_SIGNAL_MODE_NAMES)


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
        horizon = _require_canonical_signal_horizon(body.horizon)
        mode = resolve_signal_mode(body.variant)
        variant = mode.name
        if mode.is_factor_x_ta:
            from services.api.app.queue import _get_macro_ingest_queue
            from services.worker.tasks.factor_x_ta_batch import enqueue_factor_x_ta_for_symbol
            from services.worker.tasks.wfo_factor_x_ta_batch import enqueue_wfo_factor_x_ta_for_symbol

            q = _get_macro_ingest_queue()
            fs_job = q.enqueue(
                "services.worker.tasks.factor_selection_full.run_factor_selection_for_symbol",
                body.symbol,
                False,
                job_timeout=3600,
            )
            engine_job_id = enqueue_factor_x_ta_for_symbol(
                body.symbol,
                horizon,
                variant=variant,
                triggered_by=body.triggered_by,
                depends_on=fs_job.id,
            )
            wfo_job_id = enqueue_wfo_factor_x_ta_for_symbol(
                body.symbol,
                horizon,
                variant=variant,
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
            body.symbol, horizon,
            variant=variant,
            triggered_by=body.triggered_by,
        )
        return {"job_id": job_id, "status": "queued"}
    except RedisError as exc:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/engine/trigger-all",
    summary="Trigger signal engine batch for all data-backed symbols/horizons",
    dependencies=[Depends(require_admin), Depends(rate_limit_trigger)],
)
def trigger_all_signal_engine(body: _TriggerAllBody, db: Session = Depends(get_db)):
    """Fan out signal-engine jobs for every data-backed symbol x horizon x variant."""
    from services.api.app.queue import _get_macro_ingest_queue
    from services.api.app.services.market_universe import list_signal_universe_symbols
    from services.worker.tasks.signal_enqueue import enqueue_signal_engine_for_symbol

    horizons: list[CanonicalHorizon] = ["weekly", "monthly", "quarterly"]
    batch_id = uuid.uuid4().hex

    variants: list[str] = []
    for raw in body.variants or list(ALL_SIGNAL_MODE_NAMES):
        value = str(raw or "").strip().lower()
        if not value:
            continue
        try:
            normalized = signal_mode_storage_name(value)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if normalized not in variants:
            variants.append(normalized)
    if not variants:
        variants = list(ALL_SIGNAL_MODE_NAMES)

    symbols = list_signal_universe_symbols(db)

    total_jobs = 0
    factor_selection_jobs: dict[str, str] = {}
    try:
        if any(resolve_signal_mode(variant).is_factor_x_ta for variant in variants):
            factor_queue = _get_macro_ingest_queue()
            for symbol in symbols:
                job = factor_queue.enqueue(
                    "services.worker.tasks.factor_selection_full.run_factor_selection_for_symbol",
                    symbol,
                    False,
                    job_timeout=3600,
                )
                factor_selection_jobs[symbol] = str(job.id)

        for symbol in symbols:
            for horizon in horizons:
                for variant in variants:
                    mode = resolve_signal_mode(variant)
                    enqueue_signal_engine_for_symbol(
                        symbol,
                        horizon,
                        variant=variant,
                        triggered_by="manual_global",
                        batch_id=batch_id,
                        depends_on=factor_selection_jobs.get(symbol) if mode.is_factor_x_ta else None,
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
        "factor_selection_jobs": len(factor_selection_jobs),
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
        horizon = _require_canonical_signal_horizon(body.horizon)
        mc_config = dict(body.mc_config or {})
        raw_cooldown = body.cooldown_bars
        if raw_cooldown is None:
            raw_cooldown = mc_config.get("cooldown_bars", 0)
        mc_config["cooldown_bars"] = min(252, max(0, int(raw_cooldown or 0)))
        job_id = enqueue_signal_backtest_for_symbol(
            body.symbol, horizon,
            variant=body.variant,
            window_start=body.window_start,
            window_end=body.window_end,
            mc_config=mc_config,
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
    horizon: CanonicalHorizon,
    variant: str = "expanded",
    cooldown_bars: int = 0,
    db: Session = Depends(get_db),
):
    """Return persisted Signal Engine state for this tuple without mutating it."""
    try:
        horizon = _require_canonical_signal_horizon(horizon)
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


def _evidence_source(value: str | None) -> str:
    token = str(value or "auto").strip().lower()
    if token in {"", "auto", "best"}:
        return "auto"
    if token in {"engine", "signal_engine"}:
        return "signal_engine"
    if token == "wfo":
        return "wfo"
    raise HTTPException(status_code=422, detail="source must be auto, signal_engine, or wfo")


def _evidence_proof_limit(value: str | int | None) -> tuple[int | None, str]:
    token = str(value if value is not None else "100").strip().lower()
    if token == "all":
        return None, "all"
    try:
        limit = int(token)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="proof_limit must be one of 100, 250, 500, or all")
    if limit not in {100, 250, 500}:
        raise HTTPException(status_code=422, detail="proof_limit must be one of 100, 250, 500, or all")
    return limit, str(limit)


def _evidence_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return number


def _evidence_db_horizons(horizon: str) -> list[str]:
    canonical = canonical_horizon(horizon, allow_legacy=True)
    return [
        canonical,
        *[
            legacy
            for legacy, mapped in LEGACY_HORIZON_ALIASES.items()
            if mapped == canonical
        ],
    ]


def _edge_payload_for_evidence(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    source: str,
    variant: str,
    cost_bps: float,
    multiple_testing_count: int,
) -> dict[str, Any] | None:
    from ..routers.analytics import _build_edge_metrics_from_db, _edge_metrics_to_out

    metrics = _build_edge_metrics_from_db(
        symbol=symbol,
        horizon=horizon,
        source=source,
        variant=variant,
        cost_bps=cost_bps,
        db=db,
        multiple_testing_count=multiple_testing_count,
    )
    if metrics is None:
        return None
    return json.loads(_edge_metrics_to_out(metrics).model_dump_json())


def _select_signal_evidence_edge(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    source: str,
    variant: str | None,
    cost_bps: float,
) -> tuple[dict[str, Any], str, str, str]:
    """Return (edge, source, variant, method_label) for evidence.

    Requests without an explicit variant are WFO-first for the evidence page.
    The dashboard best-signal rank intentionally rejects weak signals; evidence
    must still be auditable when the current WFO signal has too few samples or
    fails proof gates.  Explicit variant requests keep their requested
    source/variant behavior.
    """
    from ..services.dashboard_builder import (
        EDGE_CANDIDATE_COUNT,
        _apply_wfo_all_oos_proof_to_edge,
        _best_signal_rank,
        _is_actionable_edge_bucket,
        _signal_method_label,
    )

    if variant is not None:
        try:
            variants = [resolve_signal_mode(variant).name]
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    else:
        variants = list(ALL_SIGNAL_MODE_NAMES)

    prefer_relaxed_wfo = variant is None
    if prefer_relaxed_wfo:
        candidate_sources = ["wfo"]
    elif source == "auto":
        candidate_sources = ["signal_engine", "wfo"]
    else:
        candidate_sources = [source]
        if variant is None and source != "wfo":
            variants = [resolve_signal_mode("expanded").name]

    best: tuple[tuple[int, float, float, float], dict[str, Any], str, str] | None = None
    relaxed_best: tuple[tuple[int, int, float, float, float], dict[str, Any], str, str] | None = None
    first_payload: tuple[dict[str, Any], str, str] | None = None
    for candidate_source in candidate_sources:
        for candidate_variant in variants:
            try:
                edge = _edge_payload_for_evidence(
                    db,
                    symbol=symbol,
                    horizon=horizon,
                    source=candidate_source,
                    variant=candidate_variant,
                    cost_bps=cost_bps,
                    multiple_testing_count=EDGE_CANDIDATE_COUNT,
                )
            except Exception:
                logger.exception(
                    "signal evidence edge build failed",
                    extra={
                        "symbol": symbol,
                        "horizon": horizon,
                        "source": candidate_source,
                        "variant": candidate_variant,
                    },
                )
                try:
                    db.rollback()
                except Exception:
                    pass
                continue
            if edge is None:
                continue
            if candidate_source == "wfo":
                edge = _apply_wfo_all_oos_proof_to_edge(
                    db,
                    symbol=symbol,
                    horizon=horizon,
                    variant=candidate_variant,
                    edge=edge,
                    cost_bps=cost_bps,
                )
            first_payload = first_payload or (edge, candidate_source, candidate_variant)
            if prefer_relaxed_wfo:
                direction = str(edge.get("direction") or "none").strip().lower()
                actionable = 1 if _is_actionable_edge_bucket(edge.get("bucket"), direction) else 0
                proven = 1 if bool(edge.get("proven_edge_net")) else 0
                edge_score = _evidence_float(edge.get("edge_score"))
                expected = _evidence_float(edge.get("action_expected_return_net"))
                if expected is None:
                    expected = _evidence_float(edge.get("expected_return_net"))
                n = _evidence_float(edge.get("n")) or 0.0
                relaxed_rank = (
                    actionable,
                    proven,
                    edge_score if edge_score is not None else -1.0,
                    expected if expected is not None else -1e12,
                    n,
                )
                if relaxed_best is None or relaxed_rank > relaxed_best[0]:
                    relaxed_best = (relaxed_rank, edge, candidate_source, candidate_variant)
            else:
                rank = _best_signal_rank(edge)
                if rank is None:
                    continue
                if best is None or rank > best[0]:
                    best = (rank, edge, candidate_source, candidate_variant)

    if prefer_relaxed_wfo:
        if relaxed_best is None:
            if first_payload is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No WFO signal evidence for {symbol}/{horizon}.",
                )
            edge, selected_source, selected_variant = first_payload
        else:
            _rank, edge, selected_source, selected_variant = relaxed_best
    elif source == "auto":
        if best is None:
            if first_payload is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No actionable signal evidence for {symbol}/{horizon}.",
                )
            edge, selected_source, selected_variant = first_payload
        else:
            _rank, edge, selected_source, selected_variant = best
    else:
        if first_payload is None:
            raise HTTPException(
                status_code=404,
                detail=f"No signal evidence for {symbol}/{horizon}/{source}/{variants[0]}.",
            )
        edge, selected_source, selected_variant = first_payload

    return edge, selected_source, selected_variant, _signal_method_label(selected_source, selected_variant)


def _current_evidence_signal(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    source: str,
    variant: str,
) -> dict[str, Any]:
    from services.api.app import models

    horizons = _evidence_db_horizons(horizon)
    variants = signal_mode_read_names(variant)
    mode = resolve_signal_mode(variant)

    if source == "wfo":
        row = (
            db.query(models.WfoGlobalSignal)
            .filter(
                models.WfoGlobalSignal.symbol == symbol,
                models.WfoGlobalSignal.horizon.in_(horizons),
                models.WfoGlobalSignal.variant.in_(variants),
                models.WfoGlobalSignal.status == "succeeded",
            )
            .order_by(models.WfoGlobalSignal.updated_at.desc())
            .first()
        )
        if row is None:
            return {}
        return {
            "score_pct": _evidence_float(row.global_score_pct),
            "raw_score_pct": _evidence_float(row.raw_score_pct),
            "signal_label": row.signal_label or row.recommendation,
            "recommendation": row.recommendation,
            "best_category": row.best_category,
            "best_category_score": _evidence_float(row.best_category_score),
            "data_as_of": row.data_as_of.isoformat() if row.data_as_of else None,
            "computed_at": row.computed_at.isoformat() if row.computed_at else None,
        }

    row = (
        db.query(models.SignalEngineGlobalResult)
        .filter(
            models.SignalEngineGlobalResult.symbol == symbol,
            models.SignalEngineGlobalResult.horizon.in_(horizons),
            models.SignalEngineGlobalResult.variant.in_(variants),
            models.SignalEngineGlobalResult.status == "succeeded",
        )
        .order_by(models.SignalEngineGlobalResult.updated_at.desc())
        .first()
    )
    if row is None:
        return {}
    preferred = row.aggregate_score_pct if mode.is_legacy else row.expanded_aggregate_score_pct
    fallback = row.expanded_aggregate_score_pct if mode.is_legacy else row.aggregate_score_pct
    return {
        "score_pct": _evidence_float(preferred if preferred is not None else fallback),
        "raw_score_pct": None,
        "signal_label": row.signal_label,
        "recommendation": row.signal_label,
        "best_category": None,
        "best_category_score": None,
        "data_as_of": row.data_as_of.isoformat() if row.data_as_of else None,
        "computed_at": row.computed_at.isoformat() if row.computed_at else None,
    }


def _factor_condition_payload(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    condition = raw.get("factor_condition") if isinstance(raw.get("factor_condition"), dict) else raw
    if not isinstance(condition, dict):
        return None
    if not condition.get("condition_id") and not condition.get("factor_ticker"):
        return None
    return {
        "condition_id": str(condition.get("condition_id") or ""),
        "factor_ticker": str(condition.get("factor_ticker") or ""),
        "form": str(condition.get("form") or ""),
        "lookback": _evidence_float(condition.get("lookback")),
        "threshold": _evidence_float(condition.get("threshold")),
        "direction": str(condition.get("direction") or ""),
    }


def _factor_conditions_from_rep(rep: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    top_level = _factor_condition_payload(rep.get("factor_condition"))
    if top_level is not None:
        key = (top_level["condition_id"], top_level["factor_ticker"])
        seen.add(key)
        out.append(top_level)

    params = rep.get("params")
    if isinstance(params, dict):
        for component in params.get("components", []):
            payload = _factor_condition_payload(component)
            if payload is None:
                continue
            key = (payload["condition_id"], payload["factor_ticker"])
            if key in seen:
                continue
            seen.add(key)
            out.append(payload)
    return out


def _normalise_evidence_rep(
    rep: Any,
    *,
    category: str,
    family: str | None = None,
    category_score_pct: float | None = None,
    category_signal_label: str | None = None,
) -> dict[str, Any] | None:
    if not isinstance(rep, dict):
        return None
    params = rep.get("params") if isinstance(rep.get("params"), dict) else {}
    variant_id = str(rep.get("variant_id") or "").strip()
    rep_family = str(rep.get("family") or family or "").strip()
    if not variant_id and not rep_family:
        return None
    description = (
        str(rep.get("description") or "").strip()
        or str(rep.get("label") or "").strip()
        or variant_id
        or rep_family
    )
    factor_conditions = _factor_conditions_from_rep(rep)
    return {
        "category": category,
        "category_score_pct": category_score_pct,
        "category_signal_label": category_signal_label,
        "family": rep_family,
        "archetype": str(rep.get("archetype") or ""),
        "variant_id": variant_id,
        "description": description,
        "params": params,
        "normalized_weight": _evidence_float(rep.get("normalized_weight")),
        "reliability_weight": _evidence_float(rep.get("reliability_weight")),
        "signal_label": str(rep.get("signal_label") or ""),
        "indicator_value": _evidence_float(rep.get("indicator_value")),
        "current_close": _evidence_float(rep.get("current_close")),
        "factor_conditions": factor_conditions,
        "is_factor_conditioned": bool(factor_conditions or rep_family.endswith("@fx")),
    }


def _signal_evidence_contributors(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    source: str,
    variant: str,
) -> list[dict[str, Any]]:
    from services.api.app import models

    horizons = _evidence_db_horizons(horizon)
    variants = signal_mode_read_names(variant)
    contributors: list[dict[str, Any]] = []

    if source == "wfo":
        rows = (
            db.query(models.WfoSignalSummary)
            .filter(
                models.WfoSignalSummary.symbol == symbol,
                models.WfoSignalSummary.horizon.in_(horizons),
                models.WfoSignalSummary.variant.in_(variants),
                models.WfoSignalSummary.status == "succeeded",
            )
            .order_by(models.WfoSignalSummary.category.asc())
            .all()
        )
        for row in rows:
            for rep in row.representatives_json or []:
                normalized = _normalise_evidence_rep(
                    rep,
                    category=str(row.category or ""),
                    category_score_pct=_evidence_float(row.score_pct),
                    category_signal_label=row.signal_label,
                )
                if normalized is not None:
                    contributors.append(normalized)
    else:
        rows = (
            db.query(models.SignalEngineFamilyResult)
            .filter(
                models.SignalEngineFamilyResult.symbol == symbol,
                models.SignalEngineFamilyResult.horizon.in_(horizons),
                models.SignalEngineFamilyResult.variant.in_(variants),
                models.SignalEngineFamilyResult.status == "succeeded",
            )
            .order_by(models.SignalEngineFamilyResult.category.asc(), models.SignalEngineFamilyResult.family.asc())
            .all()
        )
        for row in rows:
            for rep in row.representatives_json or []:
                normalized = _normalise_evidence_rep(
                    rep,
                    category=str(row.category or ""),
                    family=str(row.family or ""),
                    category_score_pct=_evidence_float(row.family_score_pct),
                    category_signal_label=row.signal_label,
                )
                if normalized is not None:
                    contributors.append(normalized)

    contributors.sort(
        key=lambda item: (
            -(item.get("normalized_weight") or item.get("reliability_weight") or 0.0),
            str(item.get("category") or ""),
            str(item.get("family") or ""),
            str(item.get("variant_id") or ""),
        )
    )
    return contributors


def _evidence_iso_date(value: Any) -> str | None:
    if value is None:
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return str(value)[:10] if str(value) else None
    if pd.isna(ts):
        return None
    return ts.date().isoformat()


def _period_contributors_for_evidence(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    source: str,
    variant: str,
    windows: list[Any],
    fallback_contributors: list[dict[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    if source != "wfo":
        return {idx: list(fallback_contributors) for idx, _window in enumerate(windows)}

    from services.api.app import models

    horizons = _evidence_db_horizons(horizon)
    variants = signal_mode_read_names(variant)
    rows = (
        db.query(models.WfoSignalSummary)
        .filter(
            models.WfoSignalSummary.symbol == symbol,
            models.WfoSignalSummary.horizon.in_(horizons),
            models.WfoSignalSummary.variant.in_(variants),
            models.WfoSignalSummary.status == "succeeded",
        )
        .order_by(models.WfoSignalSummary.category.asc())
        .all()
    )

    by_fold_id: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        reps = [rep for rep in (row.representatives_json or []) if isinstance(rep, dict)]
        reps_by_id = {str(rep.get("variant_id") or ""): rep for rep in reps}
        for fold in row.folds_json or []:
            if not isinstance(fold, dict):
                continue
            fold_id = str(fold.get("index") if fold.get("index") is not None else "")
            if not fold_id:
                continue
            winner_id = str(fold.get("winner_variant_id") or "").strip()
            if not winner_id:
                continue
            rep = dict(reps_by_id.get(winner_id) or {})
            rep.setdefault("variant_id", winner_id)
            rep.setdefault("description", str(fold.get("winner_description") or winner_id))
            rep.setdefault("params", fold.get("winner_params") if isinstance(fold.get("winner_params"), dict) else {})
            normalized = _normalise_evidence_rep(
                rep,
                category=str(row.category or ""),
                category_score_pct=_evidence_float(row.score_pct),
                category_signal_label=row.signal_label,
            )
            if normalized is not None:
                by_fold_id.setdefault(fold_id, []).append(normalized)

    out: dict[int, list[dict[str, Any]]] = {}
    for idx, window in enumerate(windows):
        fold_id = str(getattr(window, "fold_id", "") if getattr(window, "fold_id", None) is not None else "")
        items = by_fold_id.get(fold_id, [])
        if not items:
            items = fallback_contributors
        seen: set[tuple[str, str, str]] = set()
        deduped: list[dict[str, Any]] = []
        for item in items:
            key = (
                str(item.get("category") or ""),
                str(item.get("family") or ""),
                str(item.get("variant_id") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        out[idx] = deduped
    return out


def _evidence_mean(values: list[float]) -> float | None:
    finite = [float(value) for value in values if np.isfinite(value)]
    return float(np.mean(finite)) if finite else None


def _evidence_trade_proof_summary(
    trades: list[dict[str, Any]],
    *,
    direction: str,
    proof_limit_label: str,
) -> dict[str, Any]:
    action_trades = [
        trade
        for trade in trades
        if str(trade.get("direction") or "").strip().lower() in {"long", "short"}
    ]
    proof_trades = action_trades if action_trades else list(trades)
    signal_dates = [
        str(trade.get("signal_date") or "")[:10]
        for trade in proof_trades
        if str(trade.get("signal_date") or "")[:10]
    ]
    gross_values = [
        float(value)
        for trade in proof_trades
        for value in [_evidence_float(trade.get("action_return_gross"))]
        if value is not None
    ]
    net_values = [
        float(value)
        for trade in proof_trades
        for value in [_evidence_float(trade.get("action_return_net"))]
        if value is not None
    ]
    stock_values = [
        float(value)
        for trade in proof_trades
        for value in [_evidence_float(trade.get("stock_return"))]
        if value is not None
    ]

    hit_ci_lower = None
    hit_ci_upper = None
    hit_rate = None
    if gross_values:
        from core.quant_core.research.stats.hit_rate import wilson_ci

        hits = int(np.sum(np.asarray(gross_values, dtype="float64") > 0.0))
        hit_rate = float(hits / len(gross_values))
        hit_ci_lower, hit_ci_upper = wilson_ci(hits, len(gross_values))

    from core.quant_core.research.edge import bootstrap_mean_ci

    gross_ci = bootstrap_mean_ci(np.asarray(gross_values, dtype="float64"), n_iter=1000, seed=6101)
    net_ci = bootstrap_mean_ci(np.asarray(net_values, dtype="float64"), n_iter=1000, seed=6102)
    stock_ci = bootstrap_mean_ci(np.asarray(stock_values, dtype="float64"), n_iter=1000, seed=6103)

    has_action = str(direction or "").strip().lower() in {"long", "short"}
    n = len(action_trades) if has_action else len(stock_values)
    return {
        "limit": proof_limit_label,
        "n_trades": n,
        "window_start": min(signal_dates) if signal_dates else None,
        "window_end": max(signal_dates) if signal_dates else None,
        "expected_return_gross": _evidence_mean(gross_values),
        "expected_return_gross_ci_lower": gross_ci[0],
        "expected_return_gross_ci_upper": gross_ci[1],
        "expected_return_net": _evidence_mean(net_values),
        "expected_return_net_ci_lower": net_ci[0],
        "expected_return_net_ci_upper": net_ci[1],
        "stock_expected_return": _evidence_mean(stock_values),
        "stock_expected_return_ci_lower": stock_ci[0],
        "stock_expected_return_ci_upper": stock_ci[1],
        "hit_rate": hit_rate,
        "hit_ci_lower": float(hit_ci_lower) if hit_ci_lower is not None else None,
        "hit_ci_upper": float(hit_ci_upper) if hit_ci_upper is not None else None,
    }


def _evidence_sharpe(returns: list[float]) -> float:
    arr = np.asarray([value for value in returns if np.isfinite(value)], dtype=np.float64)
    if len(arr) < 2:
        return 0.0
    sigma = float(np.std(arr, ddof=1))
    if sigma <= 0.0:
        return 0.0
    return float(np.mean(arr) / sigma * np.sqrt(252.0))


def _evidence_max_drawdown(equity: list[float]) -> float:
    arr = np.asarray([value for value in equity if np.isfinite(value)], dtype=np.float64)
    if len(arr) == 0:
        return 0.0
    peak = np.maximum.accumulate(arr)
    safe_peak = np.where(peak <= 0.0, 1.0, peak)
    drawdown = 1.0 - arr / safe_peak
    return float(np.max(drawdown))


EVIDENCE_MIN_SAMPLE_N = 30


def _evidence_chart_frame(
    price_index: pd.DatetimeIndex,
    price_frame: pd.DataFrame,
    windows: list[Any],
    trades: list[dict[str, Any]],
) -> tuple[list[str], list[float], list[float], list[float], list[float]]:
    starts = [
        pd.Timestamp(getattr(window, "start", None))
        for window in windows
        if getattr(window, "start", None) is not None
    ]
    ends = [
        pd.Timestamp(getattr(window, "end", None))
        for window in windows
        if getattr(window, "end", None) is not None
    ]
    for trade in trades:
        for key in ("signal_date", "entry_date", "exit_date"):
            value = trade.get(key)
            if value:
                starts.append(pd.Timestamp(value))
                ends.append(pd.Timestamp(value))
    if not starts or not ends:
        return [], [], [], [], []

    start = min(starts)
    end = max(ends)
    start_pos = int(price_index.searchsorted(start, side="left"))
    end_pos = int(price_index.searchsorted(end, side="right")) - 1
    if len(price_index) == 0 or start_pos >= len(price_index) or end_pos < 0:
        return [], [], [], [], []
    start_pos = max(0, min(start_pos, len(price_index) - 1))
    end_pos = max(0, min(end_pos, len(price_index) - 1))
    if end_pos < start_pos:
        start_pos, end_pos = end_pos, start_pos
    if end_pos - start_pos + 1 < 2 and len(price_index) > 1:
        start_pos = max(0, start_pos - 1)
        end_pos = min(len(price_index) - 1, end_pos + 1)
    chart_index = pd.DatetimeIndex(price_index[start_pos:end_pos + 1])
    rows: list[tuple[str, float | None, float | None, float | None, float]] = []
    for ts in chart_index:
        if ts not in price_frame.index:
            continue
        close_value = _evidence_float(price_frame.loc[ts, "close"])
        if close_value is None:
            continue
        open_value = _evidence_float(price_frame.loc[ts, "open"]) if "open" in price_frame.columns else close_value
        high_value = _evidence_float(price_frame.loc[ts, "high"]) if "high" in price_frame.columns else None
        low_value = _evidence_float(price_frame.loc[ts, "low"]) if "low" in price_frame.columns else None
        rows.append((
            pd.Timestamp(ts).date().isoformat(),
            open_value,
            high_value,
            low_value,
            float(close_value),
        ))

    dates = [row[0] for row in rows]
    close = [row[4] for row in rows]
    has_complete_ohlc = all(row[1] is not None and row[2] is not None and row[3] is not None for row in rows)
    if not has_complete_ohlc:
        return dates, [], [], [], close
    return (
        dates,
        [float(row[1]) for row in rows if row[1] is not None],
        [float(row[2]) for row in rows if row[2] is not None],
        [float(row[3]) for row in rows if row[3] is not None],
        close,
    )


def _apply_evidence_trade_cooldown(
    trades: list[dict[str, Any]],
    price_index: pd.DatetimeIndex,
    cooldown_bars: int,
) -> list[dict[str, Any]]:
    cooldown = max(0, int(cooldown_bars or 0))
    action_trades = [
        trade
        for trade in trades
        if str(trade.get("direction") or "").strip().lower() in {"long", "short"}
    ]
    if cooldown <= 0 or not action_trades:
        return list(trades)

    date_to_pos = {
        pd.Timestamp(ts).date().isoformat(): idx
        for idx, ts in enumerate(pd.DatetimeIndex(price_index))
    }

    def _bar_pos(value: Any) -> int | None:
        if value is None:
            return None
        try:
            key = pd.Timestamp(value).date().isoformat()
        except Exception:
            return None
        return date_to_pos.get(key)

    ordered = sorted(
        trades,
        key=lambda trade: (
            _bar_pos(trade.get("entry_date")) if _bar_pos(trade.get("entry_date")) is not None else 10**12,
            _bar_pos(trade.get("exit_date")) if _bar_pos(trade.get("exit_date")) is not None else 10**12,
            str(trade.get("signal_date") or ""),
            str(trade.get("trade_id") or ""),
        ),
    )
    kept: list[dict[str, Any]] = []
    cooldown_until = -1
    for trade in ordered:
        direction = str(trade.get("direction") or "").strip().lower()
        if direction not in {"long", "short"}:
            kept.append(trade)
            continue
        entry_pos = _bar_pos(trade.get("entry_date"))
        exit_pos = _bar_pos(trade.get("exit_date"))
        if entry_pos is None or exit_pos is None:
            kept.append(trade)
            continue
        if entry_pos <= cooldown_until:
            continue
        kept.append(trade)
        cooldown_until = max(cooldown_until, exit_pos + cooldown)
    return kept


def _evidence_trade_ledger(
    trades: list[dict[str, Any]],
    *,
    cost_bps: float,
) -> list[dict[str, Any]]:
    def _price_kind_rank(value: Any, event_type: str) -> int:
        token = str(value or "").strip().lower()
        if token == "open":
            return 0
        if token == "close":
            return 1
        return 0 if event_type == "entry" else 1

    def _trade_quantity(trade: dict[str, Any]) -> float:
        for key in ("quantity", "qty", "shares", "units"):
            value = _evidence_float(trade.get(key))
            if value is not None and value > 0.0:
                return float(value)
        return 1.0

    friction = float(cost_bps) * 1e-4
    ordered = sorted(
        trades,
        key=lambda item: (
            str(item.get("entry_date") or item.get("signal_date") or ""),
            str(item.get("exit_date") or ""),
            str(item.get("trade_id") or ""),
        ),
    )
    events: list[dict[str, Any]] = []

    sequence = 0
    for trade in ordered:
        direction = str(trade.get("direction") or "").lower()
        if direction not in {"long", "short"}:
            continue
        sequence += 1
        is_short = direction == "short"
        entry_side = "VENTE" if is_short else "ACHAT"
        exit_side = "ACHAT" if is_short else "VENTE"
        entry_label = f"{'Short' if is_short else 'Buy'} {sequence}"
        exit_label = f"{'Cover' if is_short else 'Sell'} {sequence}"
        entry_price = _evidence_float(trade.get("entry_price")) or 0.0
        exit_price = _evidence_float(trade.get("exit_price")) or 0.0
        entry_close_price = _evidence_float(trade.get("entry_close_price"))
        exit_close_price = _evidence_float(trade.get("exit_close_price"))
        quantity = _trade_quantity(trade)
        entry_cost = entry_price * friction * quantity
        exit_cost = exit_price * friction * quantity
        net_return = _evidence_float(trade.get("action_return_net"))
        trade_id = str(trade.get("trade_id") or f"evidence-{sequence}")
        score = _evidence_float(trade.get("score_pct"))
        entry_price_kind = str(trade.get("entry_price_kind") or "open").strip().lower() or "open"
        exit_price_kind = str(trade.get("exit_price_kind") or "close").strip().lower() or "close"

        events.append({
            "date": trade.get("entry_date"),
            "side": entry_side,
            "marker_label": entry_label,
            "event_type": "entry",
            "trade_sequence": sequence,
            "trade_id": trade_id,
            "price_kind": entry_price_kind,
            "signal_date": trade.get("signal_date"),
            "bucket": trade.get("bucket"),
            "global_score_pct": score,
            "prix_execution": round(entry_price, 4),
            "open_t_plus_1": round(entry_price, 4),
            "close_du_jour": round(entry_close_price if entry_close_price is not None else entry_price, 4),
            "cmp": round(entry_price, 4),
            "quantity": round(quantity, 4),
            "position_delta": -quantity if is_short else quantity,
            "return_cumule": None,
            "cash_cumulee": None,
            "tresorerie": None,
            "pnl_realise": 0.0,
            "pnl_realise_cumule": None,
            "pnl_latent": 0.0,
            "cout": round(entry_cost, 4),
            "notional_ouvert": round(entry_price * quantity, 4),
        })

        events.append({
            "date": trade.get("exit_date"),
            "side": exit_side,
            "marker_label": exit_label,
            "event_type": "exit",
            "trade_sequence": sequence,
            "trade_id": trade_id,
            "price_kind": exit_price_kind,
            "signal_date": trade.get("signal_date"),
            "bucket": trade.get("bucket"),
            "global_score_pct": score,
            "prix_execution": round(exit_price, 4),
            "open_t_plus_1": round(exit_price, 4),
            "close_du_jour": round(exit_close_price if exit_close_price is not None else exit_price, 4),
            "cmp": round(entry_price, 4),
            "quantity": round(quantity, 4),
            "position_delta": quantity if is_short else -quantity,
            "return_cumule": None,
            "cash_cumulee": None,
            "tresorerie": None,
            "pnl_realise": 0.0,
            "pnl_realise_cumule": None,
            "pnl_latent": 0.0,
            "cout": round(exit_cost, 4),
            "pnl_return_net": net_return,
            "notional_ouvert": 0.0,
        })

    events.sort(
        key=lambda item: (
            str(item.get("date") or "")[:10],
            _price_kind_rank(item.get("price_kind"), str(item.get("event_type") or "")),
            int(item.get("trade_sequence") or 0),
            0 if item.get("event_type") == "entry" else 1,
        )
    )

    ledger: list[dict[str, Any]] = []
    current_position = 0.0
    cmp = 0.0
    cash = 0.0
    realized_cumulative = 0.0
    opened_notional = 0.0

    def _apply_delta(exec_price: float, mark_price: float, delta: float) -> tuple[float, float, float]:
        nonlocal cash, cmp, current_position, opened_notional

        remaining = abs(delta)
        direction = 1.0 if delta > 0.0 else -1.0
        cost_per_unit = friction * exec_price
        realized = 0.0

        while remaining > 1e-12:
            if current_position == 0.0 or np.sign(current_position) == direction:
                qty = remaining
                previous_abs = abs(current_position)
                current_position += direction * qty
                opened_notional += exec_price * qty
                if direction > 0.0:
                    basis = exec_price + cost_per_unit
                    cash -= basis * qty
                else:
                    basis = exec_price - cost_per_unit
                    cash += basis * qty
                cmp = (
                    (previous_abs * cmp + qty * basis) / abs(current_position)
                    if abs(current_position) > 0.0
                    else 0.0
                )
                remaining = 0.0
                continue

            closing_qty = min(remaining, abs(current_position))
            if current_position > 0.0:
                realized += (exec_price - cmp - cost_per_unit) * closing_qty
                cash += (exec_price - cost_per_unit) * closing_qty
            else:
                realized += (cmp - exec_price - cost_per_unit) * closing_qty
                cash -= (exec_price + cost_per_unit) * closing_qty

            current_position += direction * closing_qty
            if abs(current_position) <= 1e-12:
                current_position = 0.0
                cmp = 0.0
            remaining -= closing_qty

        latent = 0.0
        if current_position > 0.0:
            latent = (mark_price - cmp) * abs(current_position)
        elif current_position < 0.0:
            latent = (cmp - mark_price) * abs(current_position)
        return realized, cash, latent

    for transaction_index, event in enumerate(events, start=1):
        delta = float(event.pop("position_delta", 0.0) or 0.0)
        price = _evidence_float(event.get("prix_execution")) or 0.0
        mark_price = _evidence_float(event.get("close_du_jour"))
        if mark_price is None:
            mark_price = price
        previous_position = current_position
        previous_cmp = cmp
        realized, cash_value, latent = _apply_delta(price, float(mark_price), delta)
        realized_cumulative += realized
        is_reducing = previous_position != 0.0 and (
            np.sign(previous_position) != np.sign(delta) or abs(current_position) < abs(previous_position)
        )
        event["transaction_index"] = transaction_index
        event["cmp"] = round(previous_cmp if is_reducing else cmp, 4)
        event["position"] = round(current_position, 4)
        event["cash_cumulee"] = round(cash_value, 4)
        event["tresorerie"] = round(cash_value, 4)
        event["pnl_realise"] = round(realized, 4)
        event["pnl_realise_cumule"] = round(realized_cumulative, 4)
        event["pnl_latent"] = round(latent, 4)
        event["return_cumule"] = round(realized_cumulative / opened_notional, 10) if opened_notional > 0.0 else 0.0
        ledger.append(event)

    return ledger


def _evidence_stitched_backtest(
    *,
    dates: list[str],
    close: list[float],
    open_prices: list[float] | None = None,
    high: list[float] | None = None,
    low: list[float] | None = None,
    trades: list[dict[str, Any]],
    bucket: str,
    direction: str,
    score_mode: str | None,
    cost_bps: float,
    cooldown_bars: int = 0,
    raw_trade_count: int | None = None,
    proof_summary: dict[str, Any] | None = None,
    stitched_window_start: str | None = None,
    stitched_window_end: str | None = None,
) -> dict[str, Any]:
    action_trades = [
        trade
        for trade in trades
        if str(trade.get("direction") or "").strip().lower() in {"long", "short"}
    ]
    ledger = _evidence_trade_ledger(action_trades, cost_bps=cost_bps)
    net_returns = [
        float(value)
        for trade in action_trades
        for value in [_evidence_float(trade.get("action_return_net"))]
        if value is not None
    ]
    gross_returns = [
        float(value)
        for trade in action_trades
        for value in [_evidence_float(trade.get("action_return_gross"))]
        if value is not None
    ]
    stock_returns = [
        float(value)
        for trade in trades
        for value in [_evidence_float(trade.get("stock_return"))]
        if value is not None
    ]
    opened_notional = sum(
        float(value)
        for event in ledger
        for value in [_evidence_float(event.get("notional_ouvert"))]
        if value is not None and value > 0.0
    )
    pnl_by_date: dict[str, float] = {}
    for event in ledger:
        event_date = str(event.get("date") or "")[:10]
        realized = _evidence_float(event.get("pnl_realise"))
        if event_date and realized is not None:
            pnl_by_date[event_date] = pnl_by_date.get(event_date, 0.0) + float(realized)

    equity: list[float] = []
    realized_cumulative = 0.0
    for date in dates:
        realized_cumulative += pnl_by_date.get(str(date)[:10], 0.0)
        current_equity = 1.0
        if opened_notional > 0.0:
            current_equity += realized_cumulative / opened_notional
        equity.append(float(current_equity))

    ledger_by_date: dict[str, list[dict[str, Any]]] = {}
    for event in ledger:
        event_date = str(event.get("date") or "")[:10]
        if event_date:
            ledger_by_date.setdefault(event_date, []).append(event)

    position_series: list[float] = []
    current_position = 0.0
    for date in dates:
        for event in ledger_by_date.get(str(date)[:10], []):
            event_position = _evidence_float(event.get("position"))
            if event_position is not None:
                current_position = float(event_position)
        position_series.append(round(current_position, 4))

    total_realized = sum(
        float(value)
        for event in ledger
        for value in [_evidence_float(event.get("pnl_realise"))]
        if value is not None
    )
    total_return = float(total_realized / opened_notional) if opened_notional > 0.0 else 0.0
    years = max(len(dates), 1) / 252.0
    cagr = float((1.0 + total_return) ** (1.0 / years) - 1.0) if total_return > -1.0 else -1.0
    hit_rate = float(np.mean([value > 0.0 for value in gross_returns])) if gross_returns else None

    warning_sample_n = len(action_trades) if direction in {"long", "short"} else len(stock_returns)
    warnings: list[str] = []
    if warning_sample_n < EVIDENCE_MIN_SAMPLE_N:
        sample_label = "OOS trades" if direction in {"long", "short"} else "neutral OOS samples"
        warnings.append(
            f"Too few {sample_label}: n={warning_sample_n}, minimum={EVIDENCE_MIN_SAMPLE_N}. "
            "Shown for audit only; do not treat as a proven edge."
        )

    has_candles = (
        open_prices is not None
        and high is not None
        and low is not None
        and len(open_prices) == len(dates)
        and len(high) == len(dates)
        and len(low) == len(dates)
        and len(close) == len(dates)
    )

    return {
        "status": "succeeded",
        "source": "wfo",
        "score_mode": score_mode or "fold_scoped_winner",
        "match_mode": "exact_bucket",
        "bucket": bucket,
        "direction": direction,
        "cooldown_bars": max(0, int(cooldown_bars or 0)),
        "stitched_window_start": stitched_window_start or (dates[0] if dates else None),
        "stitched_window_end": stitched_window_end or (dates[-1] if dates else None),
        "proof": proof_summary or {},
        "dates": dates,
        "open_series": open_prices if has_candles else [],
        "high_series": high if has_candles else [],
        "low_series": low if has_candles else [],
        "close_series": close,
        "position_series": position_series,
        "equity": equity,
        "trades": trades,
        "trade_ledger": ledger,
        "warnings": warnings,
        "metrics": {
            "total_return": total_return,
            "cagr": cagr,
            "sharpe": _evidence_sharpe(net_returns) if net_returns else None,
            "max_drawdown": _evidence_max_drawdown(equity),
            "win_rate": hit_rate,
            "hit_rate": hit_rate,
            "n_trades": len(action_trades),
            "cooldown_bars": max(0, int(cooldown_bars or 0)),
            "cooldown_filtered_trades": max(0, int(raw_trade_count or len(action_trades)) - len(action_trades)),
            "expected_return_gross": _evidence_mean(gross_returns),
            "expected_return_net": _evidence_mean(net_returns),
            "stock_expected_return": _evidence_mean(stock_returns),
        },
    }


def _signal_evidence_oos_periods(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    source: str,
    variant: str,
    edge: dict[str, Any],
    contributors: list[dict[str, Any]],
    cost_bps: float,
    cooldown_bars: int = 0,
    proof_limit: int | None = 100,
    proof_limit_label: str = "100",
) -> tuple[list[dict[str, Any]], int, dict[str, Any] | None]:
    """Rebuild the exact OOS sample behind edge E[R] and hit-rate metrics."""
    try:
        from services.api.app import models
        from ..routers.analytics import (
            _edge_db_horizons,
            _load_pricing_data,
            _load_score_history,
            _resolve_score_source,
        )
        from core.quant_core.horizons import HORIZON_SPECS
        from core.quant_core.research.edge import (
            ExitCandidate,
            _normalized_price_frame,
            _sample_frames,
            _strategy_returns_array,
        )
        from core.quant_core.research.oos_index import oos_sample_for
        from core.quant_core.research.score_history import aggregate_subset, _bucket_for
    except Exception:
        logger.exception("signal evidence imports failed")
        return [], 0, None

    try:
        source_spec = _resolve_score_source(source, variant)
        canonical_h = canonical_horizon(horizon, allow_legacy=True)
        spec = HORIZON_SPECS[canonical_h]
        public_source = "wfo" if source_spec.axis == "wfo" else "signal_engine"
        if public_source != "wfo":
            return [], 0, None
        db_sources = source_spec.read_sources
        variants = signal_mode_read_names(source_spec.variant)
        db_horizons = _edge_db_horizons(canonical_h)

        series_by_cat = _load_score_history(
            db,
            symbol=symbol,
            source=source_spec.canonical_source,
            horizon=canonical_h,
        )
        score = aggregate_subset(series_by_cat, list(series_by_cat.keys())) if series_by_cat else None
        if score is None or score.dropna().empty:
            return [], 0, None

        prices = _load_pricing_data(db, symbol)
        price_frame = _normalized_price_frame(prices)
        price_index = pd.DatetimeIndex(price_frame.index)

        def wfo_loader(sym: str, _h: str) -> dict[str, Any]:
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
                            ohlcv_index=price_index,
                        )
                    }
            return {}

        def score_history_loader(sym: str, _h: str) -> list[dict[str, Any]]:
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
            return [
                {"date": row.date, "is_oos": bool(getattr(row, "is_oos", False))}
                for row in rows
            ]

        oos_sample = oos_sample_for(
            symbol=symbol,
            horizon=canonical_h,
            source=public_source,
            wfo_loader=wfo_loader,
            score_history_loader=None,
            ohlcv_index_loader=lambda _sym: price_index,
            holdout_bars=spec.signal_engine_holdout_bars,
        )
        proof_oos_sample = oos_sample

        bucket = str(edge.get("bucket") or "").strip()
        if not bucket:
            live_score = float(score.dropna().iloc[-1])
            bucket = _bucket_for(live_score)
        direction = str(edge.get("direction") or "").strip().lower()
        fwd_horizon = int(edge.get("fwd_horizon_bars") or spec.reference_forward_days)
        return_calc_method = str(edge.get("return_calc_method") or "open_to_exit_ladder")
        exit_price_kind = str(edge.get("exit_price_kind") or "close").strip().lower()
        if exit_price_kind not in {"open", "close"}:
            exit_price_kind = "close"
        selected_exit = ExitCandidate(
            horizon_bars=fwd_horizon,
            exit_price_kind=exit_price_kind,  # type: ignore[arg-type]
            return_calc_method=return_calc_method,
        )

        _full_oos_df, sample_df = _sample_frames(
            score_series=score,
            prices=prices,
            oos_sample=proof_oos_sample,
            today_bucket=bucket,
            fwd_horizon_bars=fwd_horizon,
            return_calc_method=return_calc_method,
            max_lookback_years=None,
            n_target=None,
            exit_candidate=selected_exit,
        )

        windows = list(proof_oos_sample.windows or [])
        if not windows and not sample_df.empty:
            from core.quant_core.research.oos_index import OosWindow

            windows = [
                OosWindow(
                    fold_id=None,
                    start=pd.Timestamp(sample_df.index.min()),
                    end=pd.Timestamp(sample_df.index.max()),
                )
            ]

        period_contributors = _period_contributors_for_evidence(
            db,
            symbol=symbol,
            horizon=canonical_h,
            source=public_source,
            variant=source_spec.variant,
            windows=windows,
            fallback_contributors=contributors,
        )

        periods: list[dict[str, Any]] = []
        for idx, window in enumerate(windows):
            periods.append({
                "window_index": idx,
                "fold_id": getattr(window, "fold_id", None),
                "start_date": _evidence_iso_date(getattr(window, "start", None)),
                "end_date": _evidence_iso_date(getattr(window, "end", None)),
                "score_mode": getattr(proof_oos_sample, "score_mode", None),
                "sample_n": 0,
                "hit_rate": None,
                "action_expected_return_gross": None,
                "action_expected_return_net": None,
                "stock_expected_return": None,
                "indicator_count": len(period_contributors.get(idx, [])),
                "contributors": period_contributors.get(idx, []),
                "trades": [],
            })

        def _period_index_for_date(ts: pd.Timestamp) -> int | None:
            for idx, window in enumerate(windows):
                start = pd.Timestamp(getattr(window, "start", None))
                end = pd.Timestamp(getattr(window, "end", None))
                if start <= ts <= end:
                    return idx
            return None

        c = float(cost_bps) * 1e-4
        sample_df = sample_df.sort_index()
        raw_returns = sample_df["fwd"].to_numpy(dtype="float64") if not sample_df.empty else np.array([], dtype="float64")
        gross_returns = _strategy_returns_array(raw_returns, direction, c, include_costs=False)
        net_returns = _strategy_returns_array(raw_returns, direction, c, include_costs=True)

        all_trades: list[dict[str, Any]] = []
        for row_idx, (signal_date, row) in enumerate(sample_df.sort_index().iterrows()):
            signal_ts = pd.Timestamp(signal_date)
            try:
                pos = price_index.get_loc(signal_ts)
            except KeyError:
                continue
            if not isinstance(pos, (int, np.integer)):
                continue
            entry_pos = int(pos) + int(selected_exit.entry_lag_bars)
            exit_pos = int(pos) + int(selected_exit.exit_lag_bars)
            if entry_pos < 0 or exit_pos < 0 or entry_pos >= len(price_index) or exit_pos >= len(price_index):
                continue
            entry_kind = selected_exit.entry_price_kind
            exit_kind = selected_exit.exit_price_kind
            entry_price = _evidence_float(price_frame.iloc[entry_pos][entry_kind])
            exit_price = _evidence_float(price_frame.iloc[exit_pos][exit_kind])
            entry_close_price = _evidence_float(price_frame.iloc[entry_pos]["close"])
            exit_close_price = _evidence_float(price_frame.iloc[exit_pos]["close"])
            raw = _evidence_float(row.get("fwd"))
            period_idx = _period_index_for_date(signal_ts)
            if period_idx is None:
                continue
            is_actionable = direction in {"long", "short"}
            gross = (
                float(gross_returns[row_idx])
                if is_actionable and row_idx < len(gross_returns) and np.isfinite(gross_returns[row_idx])
                else None
            )
            net = (
                float(net_returns[row_idx])
                if is_actionable and row_idx < len(net_returns) and np.isfinite(net_returns[row_idx])
                else None
            )
            trade = {
                "trade_id": f"wfo-{period_idx}-{signal_ts.date().isoformat()}-{row_idx}",
                "fold_id": periods[period_idx].get("fold_id"),
                "signal_date": signal_ts.date().isoformat(),
                "bucket": str(row.get("bucket") or bucket),
                "direction": direction,
                "score_pct": _evidence_float(row.get("score")),
                "entry_date": pd.Timestamp(price_index[entry_pos]).date().isoformat(),
                "entry_price": entry_price,
                "entry_close_price": entry_close_price,
                "entry_price_kind": entry_kind,
                "exit_date": pd.Timestamp(price_index[exit_pos]).date().isoformat(),
                "exit_price": exit_price,
                "exit_close_price": exit_close_price,
                "exit_price_kind": exit_kind,
                "exit_timing_label": str(edge.get("exit_timing_label") or selected_exit.label),
                "holding_period_bars": int(selected_exit.horizon_bars),
                "stock_return": raw,
                "action_return_gross": gross,
                "action_return_net": net,
                "is_hit": bool(gross is not None and gross > 0.0),
                "cost_bps_per_side": float(cost_bps),
            }
            all_trades.append(trade)

        raw_action_trade_count = sum(
            1
            for trade in all_trades
            if str(trade.get("direction") or "").strip().lower() in {"long", "short"}
        )
        all_trades = _apply_evidence_trade_cooldown(all_trades, price_index, cooldown_bars)
        all_trades = sorted(
            all_trades,
            key=lambda trade: (
                str(trade.get("signal_date") or ""),
                str(trade.get("entry_date") or ""),
                str(trade.get("exit_date") or ""),
                str(trade.get("trade_id") or ""),
            ),
        )
        proof_trades = all_trades if proof_limit is None else all_trades[-max(0, int(proof_limit)):]
        proof_summary = _evidence_trade_proof_summary(
            proof_trades,
            direction=direction,
            proof_limit_label=proof_limit_label,
        )
        for period in periods:
            period["trades"] = []
        if direction in {"long", "short"}:
            for trade in all_trades:
                signal_value = trade.get("signal_date")
                if not signal_value:
                    continue
                period_idx = _period_index_for_date(pd.Timestamp(signal_value))
                if period_idx is not None:
                    periods[period_idx]["trades"].append(trade)

        total_trades = 0
        for period in periods:
            trades = period["trades"]
            total_trades += len(trades)
            period["sample_n"] = len(trades)
            if not trades:
                continue
            gross_vals = [float(t["action_return_gross"]) for t in trades if t.get("action_return_gross") is not None]
            net_vals = [float(t["action_return_net"]) for t in trades if t.get("action_return_net") is not None]
            stock_vals = [float(t["stock_return"]) for t in trades if t.get("stock_return") is not None]
            period["hit_rate"] = sum(1 for t in trades if t.get("is_hit")) / len(trades)
            period["action_expected_return_gross"] = float(np.mean(gross_vals)) if gross_vals else None
            period["action_expected_return_net"] = float(np.mean(net_vals)) if net_vals else None
            period["stock_expected_return"] = float(np.mean(stock_vals)) if stock_vals else None

        chart_dates, chart_open, chart_high, chart_low, chart_close = _evidence_chart_frame(
            price_index,
            price_frame,
            windows,
            all_trades,
        )
        stitched_window_starts = [
            _evidence_iso_date(getattr(window, "start", None))
            for window in windows
            if getattr(window, "start", None) is not None
        ]
        stitched_window_ends = [
            _evidence_iso_date(getattr(window, "end", None))
            for window in windows
            if getattr(window, "end", None) is not None
        ]
        stitched = _evidence_stitched_backtest(
            dates=chart_dates,
            open_prices=chart_open,
            high=chart_high,
            low=chart_low,
            close=chart_close,
            trades=all_trades,
            bucket=bucket,
            direction=direction,
            score_mode=getattr(proof_oos_sample, "score_mode", None),
            cost_bps=float(cost_bps),
            cooldown_bars=max(0, int(cooldown_bars or 0)),
            raw_trade_count=raw_action_trade_count,
            proof_summary=proof_summary,
            stitched_window_start=min(stitched_window_starts) if stitched_window_starts else None,
            stitched_window_end=max(stitched_window_ends) if stitched_window_ends else None,
        )

        return periods, total_trades, stitched
    except Exception:
        logger.exception(
            "failed to build signal evidence OOS periods",
            extra={"symbol": symbol, "horizon": horizon, "source": source, "variant": variant},
        )
        try:
            db.rollback()
        except Exception:
            pass
        return [], 0, None


def _edge_with_stitched_evidence(edge: dict[str, Any], stitched: dict[str, Any] | None) -> dict[str, Any]:
    if not stitched:
        return edge
    metrics = stitched.get("metrics") if isinstance(stitched.get("metrics"), dict) else {}
    proof = stitched.get("proof") if isinstance(stitched.get("proof"), dict) else {}
    out = dict(edge)
    dates = stitched.get("dates") if isinstance(stitched.get("dates"), list) else []
    n_trades = int(proof.get("n_trades") if proof.get("n_trades") is not None else metrics.get("n_trades") or 0)
    direction = str(stitched.get("direction") or out.get("direction") or "").strip().lower()
    has_action = direction in {"long", "short"}
    out["stitched_window_start"] = stitched.get("stitched_window_start") or (dates[0] if dates else out.get("stitched_window_start"))
    out["stitched_window_end"] = stitched.get("stitched_window_end") or (dates[-1] if dates else out.get("stitched_window_end"))
    if proof.get("limit") is not None:
        out["proof_limit"] = proof.get("limit")
    if metrics.get("stock_expected_return") is not None:
        out["stock_expected_return"] = metrics.get("stock_expected_return")
    if not has_action:
        out["n"] = n_trades
        out["proof_n"] = n_trades
        out["proof_window_start"] = proof.get("window_start") or out.get("proof_window_start")
        out["proof_window_end"] = proof.get("window_end") or out.get("proof_window_end")
        out["proof_method"] = "no_action_current_signal"
        return out

    out["n"] = n_trades
    out["proof_n"] = n_trades
    out["proof_method"] = "all_wfo_oos_folds_exact_bucket"
    out["window_start"] = proof.get("window_start") or out.get("window_start")
    out["window_end"] = proof.get("window_end") or out.get("window_end")
    out["proof_window_start"] = proof.get("window_start") or out.get("proof_window_start")
    out["proof_window_end"] = proof.get("window_end") or out.get("proof_window_end")
    for target_key, metric_key in (
        ("action_expected_return_gross", "expected_return_gross"),
        ("expected_return_gross", "expected_return_gross"),
        ("action_expected_return_net", "expected_return_net"),
        ("expected_return_net", "expected_return_net"),
        ("action_expected_return_gross_ci_lower", "expected_return_gross_ci_lower"),
        ("action_expected_return_gross_ci_upper", "expected_return_gross_ci_upper"),
        ("expected_return_gross_ci_lower", "expected_return_gross_ci_lower"),
        ("expected_return_gross_ci_upper", "expected_return_gross_ci_upper"),
        ("action_expected_return_net_ci_lower", "expected_return_net_ci_lower"),
        ("action_expected_return_net_ci_upper", "expected_return_net_ci_upper"),
        ("expected_return_net_ci_lower", "expected_return_net_ci_lower"),
        ("expected_return_net_ci_upper", "expected_return_net_ci_upper"),
        ("stock_expected_return", "stock_expected_return"),
        ("stock_expected_return_ci_lower", "stock_expected_return_ci_lower"),
        ("stock_expected_return_ci_upper", "stock_expected_return_ci_upper"),
        ("hit_rate", "hit_rate"),
        ("hit_ci_lower", "hit_ci_lower"),
        ("hit_ci_upper", "hit_ci_upper"),
    ):
        source_metrics = proof if proof else metrics
        if source_metrics.get(metric_key) is not None:
            out[target_key] = source_metrics.get(metric_key)
    gates = dict(out.get("gates") or {}) if isinstance(out.get("gates"), dict) else {}
    if gates:
        from core.quant_core.research.edge import N_MIN, WILSON_LB_THRESHOLD

        hit_ci_lower = _evidence_float(out.get("hit_ci_lower"))
        gates["n"] = bool(n_trades >= int(N_MIN))
        gates["wilson"] = bool(hit_ci_lower is not None and float(hit_ci_lower) > WILSON_LB_THRESHOLD)
        out["gates"] = gates
        out["proven_edge_gross"] = bool(
            gates.get("mc_gross")
            and gates.get("label_shuffle_gross")
            and gates.get("wilson")
            and gates.get("n")
            and gates.get("freshness_gross")
        )
        out["proven_edge_net"] = bool(
            gates.get("mc_net")
            and gates.get("label_shuffle_net")
            and gates.get("wilson")
            and gates.get("n")
            and gates.get("freshness_net")
        )
    return out


def _sr_overlay_empty(status: str, reason: str, baseline_metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "status": status,
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
            uplift = _sr_overlay_uplift(baseline_metrics, metrics)
            total_uplift = uplift.get("total_return")
            sharpe_uplift = uplift.get("sharpe")
            dd_uplift = uplift.get("max_drawdown")
            rank_score = (
                float(total_uplift or 0.0)
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
            -float(row.get("rank_score") or 0.0),
            -float((row.get("metrics") or {}).get("total_return") or 0.0),
            str(row.get("variant_id") or ""),
        )
    )
    best = top_rows[0]
    overlay_metrics = dict(best.get("metrics") or {})
    return {
        "status": "ready",
        "reason": "computed",
        "best_variant_id": best["variant_id"],
        "best_support_method": best["support_method"],
        "best_support_line": best["support_line"],
        "best_resistance_method": best["resistance_method"],
        "best_resistance_line": best["resistance_line"],
        "baseline_metrics": baseline_metrics,
        "overlay_metrics": overlay_metrics,
        "uplift": best.get("uplift") or {},
        "top_variants": top_rows[: max(1, int(top_n))],
        "tested_count": tested_count,
        "viable_count": len(top_rows),
        "invalid_pair_count": invalid_pair_count,
        "unavailable_count": unavailable_count,
    }


@router.get("/signal/evidence", summary="Get auditable OOS evidence for today's selected signal")
def get_signal_evidence(
    symbol: str,
    horizon: CanonicalHorizon,
    source: str = Query("auto", description="auto | signal_engine | wfo"),
    variant: str | None = Query(None, description="Signal mode variant; auto by default"),
    cost_bps: float | None = Query(default=None, ge=0.0, le=500.0),
    cooldown_bars: int = Query(0, ge=0, le=252),
    proof_limit: str = Query("100", description="Proof sample size: 100, 250, 500, or all"),
    db: Session = Depends(get_db),
):
    """Return the OOS proof and signal drivers behind today's tradable signal."""
    from ..config import settings

    symbol_upper = symbol.strip().upper()
    if not symbol_upper:
        raise HTTPException(status_code=422, detail="symbol is required")

    canonical_h = _require_canonical_signal_horizon(horizon)
    requested_source = _evidence_source(source)
    cooldown = max(0, min(252, int(cooldown_bars or 0)))
    proof_n_limit, proof_limit_label = _evidence_proof_limit(proof_limit)

    selected_edge, selected_source, selected_variant, method_label = _select_signal_evidence_edge(
        db,
        symbol=symbol_upper,
        horizon=canonical_h,
        source=requested_source,
        variant=variant,
        cost_bps=float(settings.EDGE_COST_BPS_PER_SIDE if cost_bps is None else cost_bps),
    )
    current = _current_evidence_signal(
        db,
        symbol=symbol_upper,
        horizon=canonical_h,
        source=selected_source,
        variant=selected_variant,
    )
    contributors = _signal_evidence_contributors(
        db,
        symbol=symbol_upper,
        horizon=canonical_h,
        source=selected_source,
        variant=selected_variant,
    )
    oos_periods, evidence_trade_count, stitched_oos_backtest = _signal_evidence_oos_periods(
        db,
        symbol=symbol_upper,
        horizon=canonical_h,
        source=selected_source,
        variant=selected_variant,
        edge=selected_edge,
        contributors=contributors,
        cost_bps=float(settings.EDGE_COST_BPS_PER_SIDE if cost_bps is None else cost_bps),
        cooldown_bars=cooldown,
        proof_limit=proof_n_limit,
        proof_limit_label=proof_limit_label,
    )
    selected_edge = _edge_with_stitched_evidence(selected_edge, stitched_oos_backtest)
    sr_overlay = _sr_overlay_empty("unavailable", "source_not_wfo")
    if selected_source == "wfo" and isinstance(stitched_oos_backtest, dict):
        stitched_metrics = stitched_oos_backtest.get("metrics")
        baseline_metrics = dict(stitched_metrics) if isinstance(stitched_metrics, dict) else {}
        sr_overlay = _sr_overlay_for_position_series(
            db,
            symbol=symbol_upper,
            horizon=canonical_h,
            variant=selected_variant,
            dates=stitched_oos_backtest.get("dates") if isinstance(stitched_oos_backtest.get("dates"), list) else [],
            baseline_position=(
                stitched_oos_backtest.get("position_series")
                if isinstance(stitched_oos_backtest.get("position_series"), list)
                else []
            ),
            baseline_metrics=baseline_metrics,
            cost_bps=float(settings.EDGE_COST_BPS_PER_SIDE if cost_bps is None else cost_bps),
            slippage_bps=0.0,
            cooldown_bars=cooldown,
            side_policy=(
                "long_short"
                if str(stitched_oos_backtest.get("direction") or "").strip().lower() == "short"
                else "long_only"
            ),
        )
        stitched_oos_backtest["sr_overlay"] = sr_overlay

    return {
        "symbol": symbol_upper,
        "horizon": canonical_h,
        "source": selected_source,
        "variant": selected_variant,
        "method_label": method_label,
        "current_signal": {
            **current,
            "bucket": selected_edge.get("bucket"),
            "direction": selected_edge.get("direction"),
        },
        "edge": selected_edge,
        "oos": {
            "proof_window_start": selected_edge.get("proof_window_start") or selected_edge.get("window_start"),
            "proof_window_end": selected_edge.get("proof_window_end") or selected_edge.get("window_end"),
            "proof_n": selected_edge.get("proof_n") or selected_edge.get("n"),
            "proof_method": selected_edge.get("proof_method"),
            "proof_limit": selected_edge.get("proof_limit") or proof_limit_label,
            "stitched_window_start": selected_edge.get("stitched_window_start"),
            "stitched_window_end": selected_edge.get("stitched_window_end"),
            "selection_window_start": selected_edge.get("selection_window_start"),
            "selection_window_end": selected_edge.get("selection_window_end"),
            "selection_n": selected_edge.get("selection_n"),
            "selection_action_expected_return_net": selected_edge.get("selection_action_expected_return_net"),
            "selection_hit_rate": selected_edge.get("selection_hit_rate"),
        },
        "contributors": contributors,
        "contributor_count": len(contributors),
        "factor_condition_count": sum(len(item.get("factor_conditions") or []) for item in contributors),
        "oos_periods": oos_periods,
        "evidence_trade_count": evidence_trade_count,
        "stitched_oos_backtest": stitched_oos_backtest,
        "sr_overlay": sr_overlay,
    }


def _signal_backtest_direction_filter(value: str | None) -> str | None:
    token = str(value or "").strip().lower()
    if not token:
        return None
    aliases = {
        "achat": "long",
        "buy": "long",
        "long": "long",
        "vente": "short",
        "sell": "short",
        "short": "short",
        "hold": "none",
        "neutral": "none",
        "neutre": "none",
        "flat": "none",
        "none": "none",
    }
    if token not in aliases:
        raise HTTPException(status_code=422, detail="selected_direction must be long, short, or none")
    return aliases[token]


def _signal_backtest_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _signal_backtest_numeric_series(values: Any) -> list[float]:
    if not isinstance(values, list):
        return []
    out: list[float] = []
    for value in values:
        number = _signal_backtest_float(value)
        out.append(float(number) if number is not None else 0.0)
    return out


def _signal_backtest_selected_position(position: Any, selected_direction: str | None) -> list[float]:
    values = _signal_backtest_numeric_series(position)
    if selected_direction is None:
        return values
    if selected_direction == "none":
        return [0.0 for _ in values]
    if selected_direction == "long":
        return [value if value > 0.0 else 0.0 for value in values]
    if selected_direction == "short":
        return [value if value < 0.0 else 0.0 for value in values]
    return values


def _signal_backtest_global_score_by_date(db: Session, row: Any) -> dict[str, float]:
    try:
        from ..routers.analytics import _load_score_history, _resolve_score_source
        from core.quant_core.research.score_history import aggregate_subset

        source = "wfo" if str(getattr(row, "source", "")).lower() == "wfo" else "engine"
        source_spec = _resolve_score_source(source, getattr(row, "variant", None))
        series_by_cat = _load_score_history(
            db,
            symbol=str(getattr(row, "symbol", "")).upper(),
            source=source_spec.canonical_source,
            horizon=str(getattr(row, "horizon", "")),
        )
        score = aggregate_subset(series_by_cat, list(series_by_cat.keys())) if series_by_cat else None
        if score is None:
            return {}
        out: dict[str, float] = {}
        for raw_date, raw_value in score.dropna().items():
            value = _signal_backtest_float(raw_value)
            if value is None:
                continue
            out[pd.Timestamp(raw_date).date().isoformat()] = float(value)
        return out
    except Exception:
        logger.debug(
            "could not load global score series for signal backtest ledger",
            exc_info=True,
            extra={
                "symbol": getattr(row, "symbol", None),
                "horizon": getattr(row, "horizon", None),
                "source": getattr(row, "source", None),
                "variant": getattr(row, "variant", None),
            },
        )
        return {}


def _signal_backtest_score_for_date(score_by_date: dict[str, float] | None, date_value: str) -> float | None:
    if not score_by_date:
        return None
    return score_by_date.get(str(date_value)[:10])


def _signal_backtest_score_series(dates: Any, score_by_date: dict[str, float] | None) -> list[float | None]:
    if not isinstance(dates, list):
        return []
    return [_signal_backtest_score_for_date(score_by_date, str(date)) for date in dates]


def _signal_backtest_representative_lookup(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    variant: str,
    source: str,
    cache: dict[tuple[str, str, str, str], dict[str, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    key = (symbol, horizon, variant, source)
    cached = cache.get(key)
    if cached is not None:
        return cached

    from services.api.app.models import SignalEngineFamilyResult, WfoSignalSummary

    variants = signal_mode_read_names(variant)
    reps: list[dict[str, Any]] = []
    if source == "wfo":
        rows = (
            db.query(WfoSignalSummary)
            .filter(
                WfoSignalSummary.symbol == symbol,
                WfoSignalSummary.horizon == horizon,
                WfoSignalSummary.variant.in_(variants),
                WfoSignalSummary.status == "succeeded",
            )
            .all()
        )
        for row in rows:
            reps.extend(rep for rep in (row.representatives_json or []) if isinstance(rep, dict))
    else:
        rows = (
            db.query(SignalEngineFamilyResult)
            .filter(
                SignalEngineFamilyResult.symbol == symbol,
                SignalEngineFamilyResult.horizon == horizon,
                SignalEngineFamilyResult.variant.in_(variants),
                SignalEngineFamilyResult.status == "succeeded",
            )
            .all()
        )
        for row in rows:
            for raw_rep in row.representatives_json or []:
                if not isinstance(raw_rep, dict):
                    continue
                rep = dict(raw_rep)
                rep.setdefault("family", row.family)
                reps.append(rep)

    lookup: dict[str, dict[str, Any]] = {}
    for rep in reps:
        variant_id = str(rep.get("variant_id") or "").strip()
        if variant_id and variant_id not in lookup:
            lookup[variant_id] = rep
    cache[key] = lookup
    return lookup


def _signal_backtest_merge_params(current: Any, source: Any) -> dict[str, Any]:
    current_params = dict(current) if isinstance(current, dict) else {}
    source_params = source if isinstance(source, dict) else {}
    if not source_params:
        return current_params

    merged = dict(current_params)
    for key, value in source_params.items():
        if key == "components":
            if isinstance(value, list) and not merged.get("components"):
                merged[key] = value
            continue
        if key not in merged:
            merged[key] = value
    return merged


def _signal_backtest_diagnostics_with_source_reps(
    db: Session,
    row: Any,
    *,
    cache: dict[tuple[str, str, str, str], dict[str, dict[str, Any]]],
) -> dict[str, Any] | None:
    diagnostics = row.signal_diagnostics_json
    if not isinstance(diagnostics, dict):
        return diagnostics

    raw_reps = diagnostics.get("representatives")
    if not isinstance(raw_reps, list) or not raw_reps:
        return diagnostics

    lookup = _signal_backtest_representative_lookup(
        db,
        symbol=str(row.symbol),
        horizon=str(row.horizon),
        variant=str(row.variant),
        source="wfo" if str(row.source).lower() == "wfo" else "engine",
        cache=cache,
    )
    if not lookup:
        return diagnostics

    changed = False
    reps: list[Any] = []
    for raw_rep in raw_reps:
        if not isinstance(raw_rep, dict):
            reps.append(raw_rep)
            continue
        rep = dict(raw_rep)
        source_rep = lookup.get(str(rep.get("variant_id") or "").strip())
        if source_rep is None:
            reps.append(rep)
            continue

        merged_params = _signal_backtest_merge_params(rep.get("params"), source_rep.get("params"))
        if merged_params != rep.get("params"):
            rep["params"] = merged_params
            changed = True
        for key in ("family", "archetype", "description"):
            if not rep.get(key) and source_rep.get(key):
                rep[key] = source_rep[key]
                changed = True
        reps.append(rep)

    if not changed:
        return diagnostics
    enriched = dict(diagnostics)
    enriched["representatives"] = reps
    return enriched


def _signal_backtest_trade_ledger(
    row: Any,
    *,
    position_override: list[float] | None = None,
    equity_override: list[float] | None = None,
    score_by_date: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Build a per-fill accounting ledger from persisted signal backtest series."""
    dates = row.dates_json if isinstance(row.dates_json, list) else []
    close = row.close_series_json if isinstance(row.close_series_json, list) else []
    position = position_override if position_override is not None else (
        row.position_series_json if isinstance(row.position_series_json, list) else []
    )
    equity = equity_override if equity_override is not None else (
        row.equity_json if isinstance(row.equity_json, list) else []
    )
    n = min(len(dates), len(close), len(position))
    if n < 2:
        return []

    friction = (float(row.cost_bps or 0.0) + float(row.slippage_bps or 0.0)) / 10_000.0
    ledger: list[dict[str, Any]] = []
    current_position = 0.0
    cmp = 0.0
    cash = 0.0
    realized_cumulative = 0.0

    def _price(index: int) -> float:
        value = close[index]
        return float(value) if isinstance(value, (int, float)) and np.isfinite(value) else 0.0

    def _date(index: int) -> str:
        return str(dates[index])[:10] if index < len(dates) else ""

    def _cum_return(index: int) -> float | None:
        if index < len(equity) and isinstance(equity[index], (int, float)) and np.isfinite(equity[index]):
            return round(float(equity[index]) - 1.0, 10)
        return None

    def _cmp_after_open(price: float, cost: float, new_position: float) -> float:
        if new_position > 0.0:
            return price + cost
        if new_position < 0.0:
            return price - cost
        return 0.0

    def _cash_delta(price: float, prev: float, new: float) -> float:
        delta = 0.0
        if prev > 0.0:
            delta += price - (friction * price)
        elif prev < 0.0:
            delta -= price + (friction * price)
        if new > 0.0:
            delta -= price + (friction * price)
        elif new < 0.0:
            delta += price - (friction * price)
        return delta

    def _append_fill(index: int, prev: float, new: float, *, force_close: bool = False) -> None:
        nonlocal cash, cmp, current_position, realized_cumulative

        price = _price(index)
        pos_change = abs(new - prev)
        total_cost = friction * pos_change * price
        realized = 0.0
        cmp_display = cmp
        previous_cmp = cmp

        if prev == 0.0 and new != 0.0:
            cmp = _cmp_after_open(price, total_cost, new)
            cmp_display = cmp
        elif new == 0.0 and prev != 0.0:
            cmp_display = cmp
            close_cost = friction * abs(prev) * price
            realized = price - cmp - close_cost if prev > 0.0 else cmp - price - close_cost
            cmp = 0.0
            total_cost = close_cost
        elif prev != 0.0 and new != 0.0 and np.sign(prev) != np.sign(new):
            close_cost = friction * abs(prev) * price
            open_cost = friction * abs(new) * price
            realized = price - cmp - close_cost if prev > 0.0 else cmp - price - close_cost
            cmp = _cmp_after_open(price, open_cost, new)
            cmp_display = cmp
            total_cost = close_cost + open_cost
        elif prev != 0.0 and new != 0.0:
            # Defensive path for fractional/sized positions; current signal positions are usually -1/0/+1.
            open_cost = friction * max(0.0, abs(new) - abs(prev)) * price
            close_cost = friction * max(0.0, abs(prev) - abs(new)) * price
            if abs(new) > abs(prev):
                old_basis = abs(prev) * cmp
                added_basis = (abs(new) - abs(prev)) * price + open_cost
                cmp = (old_basis + added_basis) / abs(new) if abs(new) > 0.0 else 0.0
                cmp_display = cmp
            elif abs(new) < abs(prev):
                cmp_display = cmp
                realized = price - cmp - close_cost if prev > 0.0 else cmp - price - close_cost
            total_cost = open_cost + close_cost

        if prev != 0.0 and (
            new == 0.0
            or (new != 0.0 and np.sign(prev) != np.sign(new))
            or abs(new) < abs(prev)
        ):
            latent = price - previous_cmp if prev > 0.0 else previous_cmp - price
        elif new > 0.0:
            latent = price - cmp
        elif new < 0.0:
            latent = cmp - price
        else:
            latent = 0.0

        current_position = new
        cash += _cash_delta(price, prev, new)
        realized_cumulative += realized

        side = "VENTE" if new < prev else "ACHAT"
        if force_close:
            side = "VENTE" if prev > 0.0 else "ACHAT"

        ledger.append({
            "date": _date(index),
            "side": side,
            "global_score_pct": _signal_backtest_score_for_date(score_by_date, _date(index)),
            "prix_execution": round(price, 4),
            "open_t_plus_1": round(price, 4),
            "close_du_jour": round(price, 4),
            "cmp": round(cmp_display, 4),
            "position": round(current_position, 4),
            "return_cumule": _cum_return(index),
            "cash_cumulee": round(cash, 4),
            "tresorerie": round(cash, 4),
            "pnl_realise": round(realized, 4),
            "pnl_realise_cumule": round(realized_cumulative, 4),
            "pnl_latent": round(latent, 4),
            "cout": round(total_cost, 4),
        })

    for idx in range(n):
        raw_position = position[idx]
        next_position = float(raw_position) if isinstance(raw_position, (int, float)) and np.isfinite(raw_position) else 0.0
        if next_position == current_position:
            continue
        _append_fill(idx, current_position, next_position)

    if current_position != 0.0:
        _append_fill(n - 1, current_position, 0.0, force_close=True)

    return ledger


def _signal_backtest_round_trips(
    dates: list[Any],
    close: list[Any],
    position: list[float],
    *,
    friction: float,
    score_by_date: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    n = min(len(dates), len(close), len(position))
    if n < 2:
        return []

    close_values = [_signal_backtest_float(value) for value in close[:n]]
    trades: list[dict[str, Any]] = []
    in_trade = False
    trade_open_idx = 0
    trade_open_price = 0.0
    prev_pos = 0.0

    def _date(index: int) -> str:
        return str(dates[index])[:10] if index < len(dates) else ""

    def _price(index: int) -> float:
        value = close_values[index] if index < len(close_values) else None
        return float(value) if value is not None else 0.0

    def _append_trade(close_idx: int, *, terminal: bool = False) -> None:
        close_price = _price(close_idx)
        if trade_open_price == 0.0:
            pnl = 0.0
        else:
            pnl = (close_price - trade_open_price) / trade_open_price * prev_pos
            pnl -= friction if terminal else friction * 2.0
        open_date = _date(trade_open_idx)
        close_date = _date(close_idx)
        trades.append({
            "open_idx": int(trade_open_idx),
            "close_idx": int(close_idx),
            "open_date": open_date,
            "close_date": close_date,
            "open_price": float(trade_open_price),
            "close_price": float(close_price),
            "bars_held": int(close_idx - trade_open_idx),
            "pnl_return": float(pnl),
            "direction": float(prev_pos),
            "global_score_pct": _signal_backtest_score_for_date(score_by_date, open_date),
            "open_global_score_pct": _signal_backtest_score_for_date(score_by_date, open_date),
            "close_global_score_pct": _signal_backtest_score_for_date(score_by_date, close_date),
        })

    for index, raw_pos in enumerate(position[:n]):
        pos = _signal_backtest_float(raw_pos) or 0.0
        if not in_trade and pos != 0.0:
            in_trade = True
            trade_open_idx = index
            trade_open_price = _price(index)
            prev_pos = pos
        elif in_trade and (pos == 0.0 or np.sign(pos) != np.sign(prev_pos)):
            _append_trade(index)
            if pos != 0.0:
                in_trade = True
                trade_open_idx = index
                trade_open_price = _price(index)
                prev_pos = pos
            else:
                in_trade = False

    if in_trade:
        _append_trade(n - 1, terminal=True)

    return trades


def _signal_backtest_recomputed_payload(
    row: Any,
    *,
    position: list[float],
    score_by_date: dict[str, float] | None = None,
) -> dict[str, Any]:
    dates = row.dates_json if isinstance(row.dates_json, list) else []
    close = row.close_series_json if isinstance(row.close_series_json, list) else []
    n = min(len(dates), len(close), len(position))
    if n < 2:
        equity = [1.0] if n else []
        return {
            "equity": equity,
            "returns": [],
            "trades": [],
            "metrics": {
                "total_return": 0.0,
                "cagr": 0.0,
                "sharpe": 0.0,
                "max_drawdown": 0.0,
                "win_rate": 0.0,
                "n_trades": 0,
            },
            "mc": None,
        }

    close_arr = np.asarray([_signal_backtest_float(value) or 0.0 for value in close[:n]], dtype=np.float64)
    position_arr = np.asarray(position[:n], dtype=np.float64)
    friction = (float(row.cost_bps or 0.0) + float(row.slippage_bps or 0.0)) / 10_000.0
    raw_returns = np.diff(close_arr) / np.where(close_arr[:-1] == 0.0, 1.0, close_arr[:-1])
    pos_change = np.abs(np.diff(np.concatenate(([0.0], position_arr))))
    costs = pos_change[:-1] * friction
    strategy_returns = position_arr[:-1] * raw_returns - costs
    equity_arr = np.concatenate(([1.0], np.cumprod(1.0 + strategy_returns)))
    total_return = float(equity_arr[-1] - 1.0)
    years = (n - 1) / 252.0
    cagr = float((1.0 + total_return) ** (1.0 / years) - 1.0) if years > 0 and total_return > -1.0 else -1.0
    sharpe = 0.0
    if len(strategy_returns) >= 2:
        sigma = float(np.std(strategy_returns, ddof=1))
        if sigma > 0.0:
            sharpe = float(np.mean(strategy_returns) / sigma * np.sqrt(252.0))
    peak = np.maximum.accumulate(equity_arr)
    safe_peak = np.where(peak <= 0.0, 1.0, peak)
    max_drawdown = float(np.max(1.0 - equity_arr / safe_peak)) if len(equity_arr) else 0.0
    trades = _signal_backtest_round_trips(
        dates[:n],
        close[:n],
        position[:n],
        friction=friction,
        score_by_date=score_by_date,
    )
    win_rate = float(np.mean([trade["pnl_return"] > 0.0 for trade in trades])) if trades else 0.0

    mc_result = None
    try:
        method = str(row.mc_method or "block_bootstrap")
        trade_events = None
        if method == "trade_bootstrap":
            if len(trades) >= 10:
                trade_events = {
                    "pnls": [trade["pnl_return"] for trade in trades],
                    "start_indices": [trade["open_idx"] for trade in trades],
                }
            else:
                method = "block_bootstrap"
        mc_result = monte_carlo_equity_paths(
            np.asarray(strategy_returns, dtype=np.float64),
            method=method,
            n_paths=int(row.n_paths or 2000),
            block_mean=getattr(row, "block_mean", None),
            trade_events=trade_events,
            seed=42,
        )
    except Exception:
        logger.debug("could not recompute selected-direction MC payload", exc_info=True)

    return {
        "equity": equity_arr.tolist(),
        "returns": strategy_returns.tolist(),
        "trades": trades,
        "metrics": {
            "total_return": total_return,
            "cagr": cagr,
            "sharpe": sharpe,
            "max_drawdown": max_drawdown,
            "win_rate": win_rate,
            "n_trades": len(trades),
        },
        "mc": mc_result,
    }


@router.get("/backtest-mc", summary="Get persisted signal backtest + MC results for one symbol/horizon")
def get_signal_backtest_results(
    symbol: str,
    horizon: CanonicalHorizon,
    variant: str = "expanded",
    source: _Optional[str] = None,
    scope: _Optional[str] = None,
    cooldown_bars: int = Query(0, ge=0, le=252),
    selected_direction: _Optional[str] = Query(
        None,
        description="Optional action filter for returned chart/ledger: long, short, or none.",
    ),
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

    horizon = _require_canonical_signal_horizon(horizon)
    direction_filter = _signal_backtest_direction_filter(selected_direction)
    cooldown = min(252, max(0, int(cooldown_bars or 0)))
    q = db.query(SignalBacktestRun).filter_by(
        symbol=symbol,
        horizon=horizon,
        variant=variant,
        cooldown_bars=cooldown,
    )
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
    representative_lookup_cache: dict[tuple[str, str, str, str], dict[str, dict[str, Any]]] = {}
    for row in rows:
        row_data_as_of = row.data_as_of.isoformat() if row.data_as_of else None
        is_stale = (
            row_data_as_of is None
            or (market_data_as_of and row_data_as_of < market_data_as_of)
        )
        score_by_date = _signal_backtest_global_score_by_date(db, row)
        base_position = row.position_series_json if isinstance(row.position_series_json, list) else []
        response_position = _signal_backtest_selected_position(base_position, direction_filter)
        score_series = _signal_backtest_score_series(row.dates_json, score_by_date)
        if direction_filter is None:
            response_equity = row.equity_json
            response_trades = row.trades_json
            response_metrics = {
                "total_return": row.total_return,
                "cagr": row.cagr,
                "sharpe": row.sharpe,
                "max_drawdown": row.max_drawdown,
                "win_rate": row.win_rate,
                "n_trades": row.n_trades,
            }
            response_mc = {
                "method": row.mc_method,
                "n_paths": row.n_paths,
                "envelope": row.mc_envelope_json,
                "stats": row.mc_stats_json,
            }
            trade_ledger = _signal_backtest_trade_ledger(row, score_by_date=score_by_date)
        else:
            recomputed = _signal_backtest_recomputed_payload(
                row,
                position=response_position,
                score_by_date=score_by_date,
            )
            response_equity = recomputed["equity"]
            response_trades = recomputed["trades"]
            response_metrics = recomputed["metrics"]
            selected_mc = recomputed.get("mc")
            response_mc = {
                "method": (selected_mc or {}).get("method") or "block_bootstrap",
                "n_paths": int((selected_mc or {}).get("n_paths") or row.n_paths or 0),
                "envelope": (selected_mc or {}).get("envelope") if selected_mc else None,
                "stats": (selected_mc or {}).get("stats") if selected_mc else None,
            }
            trade_ledger = _signal_backtest_trade_ledger(
                row,
                position_override=response_position,
                equity_override=response_equity,
                score_by_date=score_by_date,
            )

        response_metrics_dict = dict(response_metrics or {})
        sr_overlay = _sr_overlay_empty(
            "unavailable",
            "source_not_wfo",
            response_metrics_dict,
        )
        if str(row.source or "") == "wfo":
            sr_overlay = _sr_overlay_for_position_series(
                db,
                symbol=symbol,
                horizon=horizon,
                variant=variant,
                dates=row.dates_json if isinstance(row.dates_json, list) else [],
                baseline_position=response_position,
                baseline_metrics=response_metrics_dict,
                cost_bps=float(row.cost_bps or 0.0),
                slippage_bps=float(row.slippage_bps or 0.0),
                cooldown_bars=int(getattr(row, "cooldown_bars", 0) or 0),
                side_policy=(
                    "long_short"
                    if direction_filter == "short"
                    else str(row.side_policy or "long_only")
                ),
            )

        results.append({
            "source": row.source,
            "scope": row.scope,
            "scope_key": row.scope_key,
            "status": row.status,
            "warning_code": row.warning_code,
            "side_policy": row.side_policy or "long_only",
            "cooldown_bars": int(getattr(row, "cooldown_bars", 0) or 0),
            "selected_direction": direction_filter,
            "window_start": row.window_start.isoformat() if row.window_start else None,
            "window_end": row.window_end.isoformat() if row.window_end else None,
            "n_bars": row.n_bars,
            "n_trades": response_metrics.get("n_trades"),
            "equity": response_equity,
            "dates": row.dates_json,
            "trades": response_trades,
            "trade_ledger": trade_ledger,
            "close_series": row.close_series_json,
            "position_series": response_position,
            "global_score_series": score_series,
            "signal_diagnostics": _signal_backtest_diagnostics_with_source_reps(
                db,
                row,
                cache=representative_lookup_cache,
            ),
            "metrics": response_metrics,
            "sr_overlay": sr_overlay,
            "mc": response_mc,
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
            SignalEngineBatchJob.created_at.desc(),
            SignalEngineBatchJob.started_at.desc().nullslast(),
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
    horizon: CanonicalHorizon,
    variant: str = "expanded",
    db: Session = Depends(get_db),
):
    """Return recent signal_engine batch jobs for this (symbol, horizon)."""
    horizon = _require_canonical_signal_horizon(horizon)
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
    horizon_distribution: dict[str, int] = {}
    legacy_horizon_rows = 0
    first_error_sample: str | None = None
    for row in latest_by_key.values():
        status = str(getattr(row, "status", "") or "pending").strip().lower()
        horizon_name = str(getattr(row, "horizon", "") or "").strip().lower()
        if horizon_name:
            horizon_distribution[horizon_name] = horizon_distribution.get(horizon_name, 0) + 1
        if horizon_name in LEGACY_HORIZON_ALIASES:
            legacy_horizon_rows += 1
        if first_error_sample is None:
            err = str(getattr(row, "error_message", "") or "").strip()
            if err:
                first_error_sample = err
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
        "horizon_distribution": horizon_distribution,
        "legacy_horizon_rows": legacy_horizon_rows,
        "first_error_sample": first_error_sample,
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
