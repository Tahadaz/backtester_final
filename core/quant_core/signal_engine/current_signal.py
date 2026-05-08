"""Layer F - Current signal computation for each representative variant."""

from __future__ import annotations

import numpy as np

from core.quant_core.optimize import obv_array

from .domain import VariantCurrentSignal, VariantRobustnessSummary, variant_signal_label
from .indicator_series import (
    compute_ad_series,
    compute_adx_series,
    compute_cci_series,
    compute_cmf_series,
    compute_ema_cross_series,
    compute_ema_series,
    compute_force_index_series,
    compute_ichimoku_series,
    compute_macd_pack_series,
    compute_mfi_series,
    compute_obv_deviation,
    compute_psar_series,
    compute_roc_series,
    compute_rsi_series,
    compute_sma_series,
    compute_stochastic_series,
    compute_trix_series,
    compute_tsi_series,
    compute_uo_series,
    compute_vwap_series,
)
from .oos_eval import compute_signal_array
from .rsi_semantics import is_rsi_level_variant, latest_rsi_variant_signal


def build_current_signal(
    variant,
    close: np.ndarray,
    *,
    volume: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    reliability_weight: float = 0.0,
    cooldown_bars: int = 0,
) -> VariantCurrentSignal:
    """Compute the latest-bar signal for a single variant."""
    current_close = float(close[-1])
    if is_rsi_level_variant(variant):
        signal_val, label = latest_rsi_variant_signal(close, variant, cooldown_bars=cooldown_bars)
    else:
        sig_arr = compute_signal_array(close, variant, volume=volume, high=high, low=low)
        signal_val = float(sig_arr[-1])
        label = variant_signal_label(variant.family, signal_val)
    indicator_val = _get_indicator_value(close, variant, volume=volume, high=high, low=low)
    explanation = _build_explanation(current_close, indicator_val, variant, label, signal_val, volume=volume, high=high, low=low)
    return VariantCurrentSignal(
        variant_id=variant.variant_id,
        signal=signal_val,
        signal_label=label,
        reliability_weight=reliability_weight,
        current_close=current_close,
        indicator_value=indicator_val,
        explanation=explanation,
    )


def compute_current_signals(
    representatives: list[VariantRobustnessSummary],
    close: np.ndarray,
    *,
    volume: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    cooldown_bars: int = 0,
) -> list[VariantCurrentSignal]:
    """Compute the latest-bar signal for each representative."""
    return [
        build_current_signal(
            rep.variant,
            close,
            volume=volume,
            high=high,
            low=low,
            reliability_weight=rep.reliability_score,
            cooldown_bars=cooldown_bars,
        )
        for rep in representatives
    ]


def _get_indicator_value(close: np.ndarray, variant, *, volume=None, high=None, low=None) -> float | None:
    """Return the primary indicator value at the last bar."""
    p = variant.params
    arch = variant.archetype
    value: float | None = None

    if arch == "price_vs_sma":
        arr = compute_sma_series(close, int(p["window"]))
        value = float(arr[-1]) if np.isfinite(arr[-1]) else None
    elif arch == "sma_cross":
        arr = compute_sma_series(close, int(p["slow"]))
        value = float(arr[-1]) if np.isfinite(arr[-1]) else None
    elif arch == "slope_confirmed":
        arr = compute_sma_series(close, int(p["window"]))
        value = float(arr[-1]) if np.isfinite(arr[-1]) else None
    elif arch == "price_vs_ema":
        arr = compute_ema_series(close, int(p["window"]))
        value = float(arr[-1]) if np.isfinite(arr[-1]) else None
    elif arch == "ema_cross":
        _fast, slow = compute_ema_cross_series(close, int(p["fast"]), int(p["slow"]))
        value = float(slow[-1]) if np.isfinite(slow[-1]) else None
    elif arch == "ichi_cloud" and high is not None and low is not None:
        ichi = compute_ichimoku_series(high, low, close, int(p["tenkan"]), int(p["kijun"]), int(p["senkou_b"]))
        value = float(ichi["tenkan_sen"][-1]) if np.isfinite(ichi["tenkan_sen"][-1]) else None
    elif arch == "psar_trend" and high is not None and low is not None:
        arr = compute_psar_series(high, low, close, float(p["af_step"]), float(p["af_max"]))
        value = float(arr[-1]) if np.isfinite(arr[-1]) else None
    elif arch == "rsi_level":
        arr = compute_rsi_series(close, int(p["period"]))
        value = float(arr[-1]) if np.isfinite(arr[-1]) else None
    elif arch == "macd_cross":
        macd_line, _signal, _hist = compute_macd_pack_series(close, int(p["fast"]), int(p["slow"]), int(p["signal"]))
        value = float(macd_line[-1]) if np.isfinite(macd_line[-1]) else None
    elif arch == "roc_zero":
        arr = compute_roc_series(close, int(p["period"]))
        value = float(arr[-1]) if np.isfinite(arr[-1]) else None
    elif arch == "trix_zero":
        arr = compute_trix_series(close, int(p["period"]))
        value = float(arr[-1]) if np.isfinite(arr[-1]) else None
    elif arch == "adx_trend" and high is not None and low is not None:
        _plus, _minus, arr = compute_adx_series(high, low, close, int(p["period"]))
        value = float(arr[-1]) if np.isfinite(arr[-1]) else None
    elif arch == "tsi_zero":
        long_period = int(p.get("long_period", p["quarterly_period"]))
        short_period = int(p.get("short_period", p["weekly_period"]))
        arr = compute_tsi_series(close, long_period, short_period)
        value = float(arr[-1]) if np.isfinite(arr[-1]) else None
    elif arch == "stoch_level" and high is not None and low is not None:
        k_vals, _d_vals = compute_stochastic_series(high, low, close, int(p["k_period"]), int(p["d_period"]))
        value = float(k_vals[-1]) if np.isfinite(k_vals[-1]) else None
    elif arch == "cci_level" and high is not None and low is not None:
        arr = compute_cci_series(high, low, close, int(p["period"]))
        value = float(arr[-1]) if np.isfinite(arr[-1]) else None
    elif arch == "mfi_level" and volume is not None and high is not None and low is not None:
        arr = compute_mfi_series(high, low, close, volume, int(p["period"]))
        value = float(arr[-1]) if np.isfinite(arr[-1]) else None
    elif arch == "uo_level" and high is not None and low is not None:
        arr = compute_uo_series(high, low, close, int(p["period_1"]), int(p["period_2"]), int(p["period_3"]))
        value = float(arr[-1]) if np.isfinite(arr[-1]) else None
    elif arch == "obv_trend" and volume is not None:
        obv = obv_array(close, volume)
        value = float(obv[-1]) if np.isfinite(obv[-1]) else None
    elif arch == "cmf_flow" and volume is not None and high is not None and low is not None:
        arr = compute_cmf_series(high, low, close, volume, int(p["period"]))
        value = float(arr[-1]) if np.isfinite(arr[-1]) else None
    elif arch == "ad_trend" and volume is not None and high is not None and low is not None:
        arr = compute_ad_series(high, low, close, volume)
        value = float(arr[-1]) if np.isfinite(arr[-1]) else None
    elif arch == "vwap_dev" and volume is not None:
        arr = compute_vwap_series(close, volume, int(p["period"]))
        value = float(arr[-1]) if np.isfinite(arr[-1]) else None
    elif arch == "fi_trend" and volume is not None:
        arr = compute_force_index_series(close, volume, int(p["period"]))
        value = float(arr[-1]) if np.isfinite(arr[-1]) else None
    return value


def _fmt(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "N/A"


def _build_explanation(current_close: float, indicator_val: float | None, variant, label: str, signal_val: float, *, volume=None, high=None, low=None) -> str:
    """Build a human-readable explanation string."""
    p = variant.params
    arch = variant.archetype
    if arch == "price_vs_sma":
        cmp = ">" if signal_val > 0 else "<" if signal_val < 0 else "="
        return f"Close {current_close:.2f} {cmp} SMA-{p['window']} {_fmt(indicator_val)} -> {label}"
    if arch == "price_vs_ema":
        cmp = ">" if signal_val > 0 else "<" if signal_val < 0 else "="
        return f"Close {current_close:.2f} {cmp} EMA-{p['window']} {_fmt(indicator_val)} -> {label}"
    if arch == "ema_cross":
        return f"EMA({p['fast']},{p['slow']}) -> {label}"
    if arch == "ichi_cloud":
        return f"Ichimoku({p['tenkan']},{p['kijun']},{p['senkou_b']}) tenkan={_fmt(indicator_val)} -> {label}"
    if arch == "psar_trend":
        return f"PSAR(step={p['af_step']}, max={p['af_max']}) SAR={_fmt(indicator_val)} -> {label}"
    if arch == "rsi_level":
        threshold = p["oversold"] if signal_val > 0 else p["overbought"] if signal_val < 0 else "neutral"
        cmp = "<" if signal_val > 0 else ">" if signal_val < 0 else "~"
        return f"RSI({p['period']})={_fmt(indicator_val)} {cmp} {threshold} -> {label}"
    if arch == "macd_cross":
        return f"MACD({p['fast']},{p['slow']},{p['signal']})={_fmt(indicator_val)} -> {label}"
    if arch == "roc_zero":
        return f"ROC({p['period']})={_fmt(indicator_val)} -> {label}"
    if arch == "trix_zero":
        return f"TRIX({p['period']})={_fmt(indicator_val)} -> {label}"
    if arch == "adx_trend":
        return f"ADX({p['period']}) threshold={p['adx_threshold']} value={_fmt(indicator_val)} -> {label}"
    if arch == "tsi_zero":
        long_period = int(p.get("long_period", p["quarterly_period"]))
        short_period = int(p.get("short_period", p["weekly_period"]))
        return f"TSI({long_period},{short_period})={_fmt(indicator_val)} -> {label}"
    if arch == "stoch_level":
        return f"Stochastic({p['k_period']},{p['d_period']}) %K={_fmt(indicator_val)} -> {label}"
    if arch == "cci_level":
        return f"CCI({p['period']})={_fmt(indicator_val)} -> {label}"
    if arch == "mfi_level":
        return f"MFI({p['period']})={_fmt(indicator_val)} -> {label}"
    if arch == "uo_level":
        return f"UO({p['period_1']},{p['period_2']},{p['period_3']})={_fmt(indicator_val)} -> {label}"
    if arch == "obv_trend":
        return f"OBV vs EMA({p['ema_period']}) -> {label}"
    if arch == "cmf_flow":
        return f"CMF({p['period']})={_fmt(indicator_val)} -> {label}"
    if arch == "ad_trend":
        return f"A/D vs EMA({p['ema_period']}) value={_fmt(indicator_val)} -> {label}"
    if arch == "vwap_dev":
        return f"VWAP({p['period']})={_fmt(indicator_val)} threshold={p['threshold_pct']}% -> {label}"
    if arch == "fi_trend":
        return f"Force Index EMA({p['period']})={_fmt(indicator_val)} -> {label}"
    if arch == "sma_cross":
        return f"SMA({p['fast']},{p['slow']}) Cross -> {label}"
    if arch == "slope_confirmed":
        return f"SMA-{p['window']} Slope-Confirmed(k={p['slope_lookback']}) -> {label}"
    return f"{variant.family}:{arch} -> {label}"
