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

from ...auth import rate_limit_trigger, require_admin
from ...db import get_db
from ...market_data_loader import load_close_for_symbol, load_ohlcv_for_symbol
from ...schemas.strategy import PivotPoints
from ...services.signal_engine_persistence import resolve_signal_engine_result
from ...schemas.strategy_signals import (
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
_SR_WFO_CACHE: dict[tuple, tuple[float, dict[str, Any]]] = {}
_SR_WFO_CACHE_TTL = _SR_VARIANTS_CACHE_TTL


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


def _truncate_for_horizon(ohlcv, horizon: str, *, periods_per_year: float = 252.0):
    """Keep only the last N years of OHLCV data for the given horizon."""
    max_bars = int(round(HORIZON_PARAMS[horizon]["max_years"] * periods_per_year))
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


def _safe_float(v) -> float | None:
    """Convert numpy scalar to Python float, NaN → None."""
    if v is None:
        return None
    f = float(v)
    return None if np.isnan(f) else f


def _safe_float_list(arr: np.ndarray) -> list[float | None]:
    """Convert numpy array to list of floats, NaN → None."""
    return [None if np.isnan(float(v)) else round(float(v), 4) for v in arr]


def _evidence_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return number


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


