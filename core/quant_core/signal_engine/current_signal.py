"""Layer F — Current signal computation for each representative variant."""

from __future__ import annotations

import numpy as np

from core.quant_core.optimize import sma_cumsum, rsi_wilder, ema, macd_pack, obv_array

from .domain import VariantCurrentSignal, VariantRobustnessSummary, variant_signal_label
from .oos_eval import compute_signal_array


def build_current_signal(
    variant,
    close: np.ndarray,
    *,
    volume: np.ndarray | None = None,
    reliability_weight: float = 0.0,
) -> VariantCurrentSignal:
    """Compute the latest-bar signal for a single variant."""
    current_close = float(close[-1])
    sig_arr = compute_signal_array(close, variant, volume=volume)
    signal_val = float(sig_arr[-1])
    label = variant_signal_label(variant.family, signal_val)
    indicator_val = _get_indicator_value(close, variant, volume=volume)
    explanation = _build_explanation(current_close, indicator_val, variant, label, signal_val)

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
) -> list[VariantCurrentSignal]:
    """Compute the latest-bar signal for each representative."""
    results: list[VariantCurrentSignal] = []

    for rep in representatives:
        results.append(
            build_current_signal(
                rep.variant,
                close,
                volume=volume,
                reliability_weight=rep.reliability_score,
            )
        )

    return results


def _get_indicator_value(
    close: np.ndarray, variant, *, volume: np.ndarray | None = None,
) -> float | None:
    """Return the primary indicator value at the last bar."""
    p = variant.params
    arch = variant.archetype

    if arch == "price_vs_sma":
        sma = sma_cumsum(close, int(p["window"]))
        return float(sma[-1]) if not np.isnan(sma[-1]) else None

    if arch == "sma_cross":
        slow = sma_cumsum(close, int(p["slow"]))
        return float(slow[-1]) if not np.isnan(slow[-1]) else None

    if arch == "slope_confirmed":
        sma = sma_cumsum(close, int(p["window"]))
        return float(sma[-1]) if not np.isnan(sma[-1]) else None

    if arch == "rsi_level":
        rsi = rsi_wilder(close, int(p["period"]))
        return float(rsi[-1]) if not np.isnan(rsi[-1]) else None

    if arch == "macd_cross":
        macd_line, _, _ = macd_pack(close, int(p["fast"]), int(p["slow"]), int(p["signal"]))
        return float(macd_line[-1]) if not np.isnan(macd_line[-1]) else None

    if arch == "obv_trend":
        if volume is not None:
            obv = obv_array(close, volume)
            return float(obv[-1]) if not np.isnan(obv[-1]) else None
        return None

    return None


def _build_explanation(
    current_close: float,
    indicator_val: float | None,
    variant,
    label: str,
    signal_val: float,
) -> str:
    """Build a human-readable explanation string."""
    p = variant.params
    arch = variant.archetype
    ind_str = f"{indicator_val:.2f}" if indicator_val is not None else "N/A"

    if arch == "price_vs_sma":
        cmp = ">" if signal_val > 0 else "<" if signal_val < 0 else "="
        return f"Close {current_close:.2f} {cmp} SMA-{p['window']} {ind_str} -> {label}"

    if arch == "sma_cross":
        return f"SMA({p['fast']},{p['slow']}) Cross -> {label}"

    if arch == "slope_confirmed":
        return f"SMA-{p['window']} Slope-Confirmed(k={p['slope_lookback']}) -> {label}"

    if arch == "rsi_level":
        cmp = "<" if signal_val > 0 else ">" if signal_val < 0 else "~"
        threshold = p["oversold"] if signal_val > 0 else p["overbought"]
        return f"RSI({p['period']})={ind_str} {cmp} {threshold} -> {label}"

    if arch == "macd_cross":
        return f"MACD({p['fast']},{p['slow']},{p['signal']})={ind_str} -> {label}"

    if arch == "obv_trend":
        return f"OBV vs EMA({p['ema_period']}) -> {label}"

    return f"{variant.family}:{arch} -> {label}"
