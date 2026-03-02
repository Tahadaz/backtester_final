from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        out = float(value)
    except Exception:
        return default
    if not np.isfinite(out):
        return default
    return out


def _atr_ratio(bars: pd.DataFrame, window: int = 20) -> float:
    high = pd.to_numeric(bars.get("High"), errors="coerce")
    low = pd.to_numeric(bars.get("Low"), errors="coerce")
    close = pd.to_numeric(bars.get("Close"), errors="coerce")
    if high is None or low is None or close is None:
        return 0.02

    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = pd.to_numeric(tr, errors="coerce").rolling(window, min_periods=5).mean()
    atr_now = _to_float(atr.iloc[-1], default=0.0)
    close_now = _to_float(close.iloc[-1], default=1.0) or 1.0
    if close_now == 0:
        return 0.02
    return max(0.005, min(0.15, float(atr_now / close_now)))


def compute_levels_support_resistance(
    bars: pd.DataFrame,
    *,
    direction: int,
    lookback: int = 120,
    min_stop_atr_mult: float = 1.0,
    min_target_atr_mult: float = 1.6,
) -> dict[str, Any]:
    """
    Heuristic support/resistance plus entry-stop-target anchors.
    """
    frame = bars.copy()
    close = pd.to_numeric(frame.get("Close"), errors="coerce").dropna()
    high = pd.to_numeric(frame.get("High"), errors="coerce").dropna()
    low = pd.to_numeric(frame.get("Low"), errors="coerce").dropna()

    if close.empty:
        return {
            "support": None,
            "resistance": None,
            "entry": None,
            "stop": None,
            "target": None,
            "inputs": {},
            "thresholds": {"lookback": lookback},
            "explain": "Missing OHLC data.",
        }

    lb = int(max(30, min(lookback, len(close))))
    close_tail = close.tail(lb)
    high_tail = high.tail(lb) if not high.empty else close_tail
    low_tail = low.tail(lb) if not low.empty else close_tail
    close_now = float(close_tail.iloc[-1])

    support_q = float(low_tail.quantile(0.2))
    resistance_q = float(high_tail.quantile(0.8))
    support_recent = float(low_tail.tail(min(20, len(low_tail))).min())
    resistance_recent = float(high_tail.tail(min(20, len(high_tail))).max())

    support = min(close_now, support_q, support_recent)
    resistance = max(close_now, resistance_q, resistance_recent)

    atr_ratio = _atr_ratio(frame.tail(max(30, lb)))
    atr_abs = close_now * atr_ratio if np.isfinite(close_now * atr_ratio) else None
    stop_buffer = max(0.015, atr_ratio * 1.2)
    target_buffer = max(0.03, atr_ratio * 2.4)
    min_stop_dist = None
    min_target_dist = None
    constraints_flags: list[str] = []

    enough_history = len(close_tail) >= 20
    low_vol = atr_abs is None or atr_abs <= max(abs(close_now) * 0.0005, 1e-8)
    constraints_ready = bool(enough_history and not low_vol)
    if constraints_ready:
        min_stop_dist = max(0.0, float(min_stop_atr_mult) * float(atr_abs))
        min_target_dist = max(0.0, float(min_target_atr_mult) * float(atr_abs))
    else:
        if not enough_history:
            constraints_flags.append("insufficient_history_for_atr_constraints")
        if low_vol:
            constraints_flags.append("low_volatility_atr_constraints_unavailable")

    if direction > 0:
        entry = close_now
        stop = min(support, close_now * (1.0 - stop_buffer))
        target = max(resistance, close_now * (1.0 + target_buffer))
        if constraints_ready:
            if min_stop_dist is not None and (entry - stop) < min_stop_dist:
                stop = entry - min_stop_dist
                constraints_flags.append("long_stop_adjusted_min_atr")
            if min_target_dist is not None and (target - entry) < min_target_dist:
                target = entry + min_target_dist
                constraints_flags.append("long_target_adjusted_min_atr")
        else:
            conservative_stop = max(abs(close_now) * 0.01, 0.01)
            conservative_target = max(abs(close_now) * 0.015, conservative_stop * 1.5)
            stop = entry - conservative_stop
            target = entry + conservative_target
            constraints_flags.append("conservative_levels_applied")
    elif direction < 0:
        entry = close_now
        stop = max(resistance, close_now * (1.0 + stop_buffer))
        target = min(support, close_now * (1.0 - target_buffer))
        if constraints_ready:
            if min_stop_dist is not None and (stop - entry) < min_stop_dist:
                stop = entry + min_stop_dist
                constraints_flags.append("short_stop_adjusted_min_atr")
            if min_target_dist is not None and (entry - target) < min_target_dist:
                target = entry - min_target_dist
                constraints_flags.append("short_target_adjusted_min_atr")
        else:
            conservative_stop = max(abs(close_now) * 0.01, 0.01)
            conservative_target = max(abs(close_now) * 0.015, conservative_stop * 1.5)
            stop = entry + conservative_stop
            target = entry - conservative_target
            constraints_flags.append("conservative_levels_applied")
    else:
        entry = close_now
        if constraints_ready and min_stop_dist is not None and min_target_dist is not None:
            stop = close_now - min_stop_dist
            target = close_now + min_target_dist
        else:
            conservative_stop = max(abs(close_now) * 0.01, 0.01)
            conservative_target = max(abs(close_now) * 0.015, conservative_stop * 1.5)
            stop = close_now - conservative_stop
            target = close_now + conservative_target
            constraints_flags.append("conservative_levels_applied")

    return {
        "support": float(support),
        "resistance": float(resistance),
        "entry": float(entry),
        "stop": float(stop),
        "target": float(target),
        "inputs": {
            "close": close_now,
            "support_q20": support_q,
            "support_recent_20d": support_recent,
            "resistance_q80": resistance_q,
            "resistance_recent_20d": resistance_recent,
            "atr_ratio_20": atr_ratio,
            "atr_abs_20": atr_abs,
            "min_stop_dist": min_stop_dist,
            "min_target_dist": min_target_dist,
            "constraints_ready": constraints_ready,
            "constraints_flags": constraints_flags,
        },
        "thresholds": {
            "lookback": lb,
            "support_quantile": 0.2,
            "resistance_quantile": 0.8,
            "stop_buffer_min": 0.015,
            "target_buffer_min": 0.03,
            "min_stop_atr_mult": float(min_stop_atr_mult),
            "min_target_atr_mult": float(min_target_atr_mult),
        },
        "explain": (
            "Support/resistance from recent quantiles and local extremes with ATR-sized buffers. "
            + (
                f"Constraint flags: {', '.join(constraints_flags)}."
                if constraints_flags
                else "ATR distance constraints satisfied."
            )
        ),
    }
