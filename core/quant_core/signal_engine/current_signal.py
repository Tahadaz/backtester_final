"""Layer F — Current signal computation for each representative variant."""

from __future__ import annotations

import numpy as np

from quant_core.optimize import sma_cumsum

from .domain import VariantCurrentSignal, VariantRobustnessSummary
from .oos_eval import compute_signal_array


def compute_current_signals(
    representatives: list[VariantRobustnessSummary],
    close: np.ndarray,
) -> list[VariantCurrentSignal]:
    """Compute the latest-bar signal for each representative."""
    results: list[VariantCurrentSignal] = []
    current_close = float(close[-1])

    for rep in representatives:
        v = rep.variant
        sig_arr = compute_signal_array(close, v)
        signal_val = float(sig_arr[-1])

        if signal_val > 0:
            label = "BUY"
        elif signal_val < 0:
            label = "SELL"
        else:
            label = "HOLD"

        indicator_val = _get_indicator_value(close, v)
        explanation = _build_explanation(current_close, indicator_val, v, label)

        results.append(VariantCurrentSignal(
            variant_id=v.variant_id,
            signal=signal_val,
            signal_label=label,
            reliability_weight=rep.reliability_score,
            current_close=current_close,
            indicator_value=indicator_val,
            explanation=explanation,
        ))

    return results


def _get_indicator_value(close: np.ndarray, variant) -> float | None:
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

    return None


def _build_explanation(
    current_close: float,
    indicator_val: float | None,
    variant,
    label: str,
) -> str:
    """Build a human-readable explanation string."""
    p = variant.params
    arch = variant.archetype
    ind_str = f"{indicator_val:.2f}" if indicator_val is not None else "N/A"

    if arch == "price_vs_sma":
        cmp = ">" if label == "BUY" else "<" if label == "SELL" else "="
        return f"Close {current_close:.2f} {cmp} SMA-{p['window']} {ind_str} -> {label}"

    if arch == "sma_cross":
        fast_sma = sma_cumsum(np.array([current_close]), int(p["fast"]))  # not ideal, but explanation is cosmetic
        return f"SMA({p['fast']},{p['slow']}) Cross -> {label}"

    if arch == "slope_confirmed":
        return f"SMA-{p['window']} Slope-Confirmed(k={p['slope_lookback']}) -> {label}"

    return f"{variant.family}:{arch} -> {label}"
