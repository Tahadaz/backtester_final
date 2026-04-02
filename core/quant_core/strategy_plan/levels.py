"""Support/Resistance detection via swing highs/lows, ATR, and pivot points."""

from __future__ import annotations

from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------

def compute_atr(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    window: int = 14,
) -> tuple[float, float]:
    """Compute ATR (Average True Range) for the last bar.

    Returns ``(atr_absolute, atr_ratio)`` where *atr_ratio* =
    atr_absolute / current_close.  True Range follows Wilder (1978):
    ``TR = max(H-L, |H-Cprev|, |L-Cprev|)``.
    """
    n = len(close)
    if n < 2:
        return (0.0, 0.0)

    prev_close = np.empty(n, dtype=np.float64)
    prev_close[0] = close[0]
    prev_close[1:] = close[:-1]

    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)),
    )

    # Simple rolling mean for ATR (Wilder originally used EMA; SMA is standard)
    eff_window = min(window, n)
    atr_abs = float(np.nanmean(tr[-eff_window:]))
    close_now = float(close[-1])
    atr_ratio = atr_abs / close_now if close_now != 0 else 0.0
    return (atr_abs, atr_ratio)


# ---------------------------------------------------------------------------
# Pivot points
# ---------------------------------------------------------------------------

def compute_pivot_points(
    prev_high: float,
    prev_low: float,
    prev_close: float,
) -> dict[str, float]:
    """Classic floor pivot points from previous session.

    PP = (H + L + C) / 3
    S1 = 2·PP - H,  R1 = 2·PP - L
    S2 = PP - (H - L),  R2 = PP + (H - L)
    """
    pp = (prev_high + prev_low + prev_close) / 3.0
    rng = prev_high - prev_low
    return {
        "pp": round(pp, 4),
        "s1": round(2.0 * pp - prev_high, 4),
        "s2": round(pp - rng, 4),
        "r1": round(2.0 * pp - prev_low, 4),
        "r2": round(pp + rng, 4),
    }


# ---------------------------------------------------------------------------
# Swing high / low detection
# ---------------------------------------------------------------------------

def _is_swing_high(high: np.ndarray, i: int, left: int, right: int) -> bool:
    """True if high[i] is strictly greater than all neighbours."""
    start = max(0, i - left)
    end = min(len(high), i + right + 1)
    for j in range(start, end):
        if j == i:
            continue
        if high[j] >= high[i]:
            return False
    return True


def _is_swing_low(low: np.ndarray, i: int, left: int, right: int) -> bool:
    """True if low[i] is strictly less than all neighbours."""
    start = max(0, i - left)
    end = min(len(low), i + right + 1)
    for j in range(start, end):
        if j == i:
            continue
        if low[j] <= low[i]:
            return False
    return True


def _count_touches(
    prices: np.ndarray,
    level: float,
    tolerance: float,
    start_idx: int,
) -> int:
    """Count bars where *prices* comes within *tolerance* of *level*."""
    if tolerance <= 0:
        return 0
    mask = np.abs(prices[start_idx:] - level) <= tolerance
    return int(np.sum(mask))


def detect_swing_levels(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    *,
    left_bars: int = 5,
    right_bars: int = 5,
    max_levels: int = 8,
    lookback: int = 120,
    max_distance_atr: float | None = None,
) -> dict[str, Any]:
    """Detect support/resistance via N-bar swing highs and lows.

    Parameters
    ----------
    high, low, close : np.ndarray
        OHLCV price arrays (same length).
    left_bars, right_bars : int
        Number of bars on each side that the pivot must dominate.
    max_levels : int
        Maximum supports and resistances to return (each capped independently).
    lookback : int
        Only consider the last *lookback* bars for pivot detection.

    Returns
    -------
    dict with keys:
        ``supports``, ``resistances`` — lists of ``{price, bar_index, strength}``
        ``nearest_support``, ``nearest_resistance`` — float | None
        ``current_close`` — float
    """
    n = len(close)
    if n < 3:
        return {
            "supports": [],
            "resistances": [],
            "nearest_support": None,
            "nearest_resistance": None,
            "current_close": float(close[-1]) if n > 0 else 0.0,
        }

    lb = min(lookback, n)
    offset = n - lb  # absolute index offset
    h = high[offset:]
    l_ = low[offset:]
    c = close[offset:]

    atr_abs, _ = compute_atr(high, low, close, window=14)
    touch_tol = atr_abs / 2.0 if atr_abs > 0 else 0.0

    current_close = float(close[-1])

    raw_resistances: list[dict[str, Any]] = []
    raw_supports: list[dict[str, Any]] = []

    # Scan for pivots (skip first left_bars and last right_bars)
    for i in range(left_bars, len(h) - right_bars):
        abs_i = offset + i

        if _is_swing_high(h, i, left_bars, right_bars):
            price = float(h[i])
            touches = _count_touches(close, price, touch_tol, abs_i)
            raw_resistances.append({
                "price": round(price, 4),
                "bar_index": abs_i,
                "strength": touches,
            })

        if _is_swing_low(l_, i, left_bars, right_bars):
            price = float(l_[i])
            touches = _count_touches(close, price, touch_tol, abs_i)
            raw_supports.append({
                "price": round(price, 4),
                "bar_index": abs_i,
                "strength": touches,
            })

    max_distance_abs = None
    if max_distance_atr is not None and atr_abs > 0:
        max_distance_abs = atr_abs * max_distance_atr

    supports = [s for s in raw_supports if s["price"] < current_close]
    resistances = [r for r in raw_resistances if r["price"] > current_close]

    if max_distance_abs is not None:
        supports = [
            s for s in supports
            if (current_close - s["price"]) <= max_distance_abs
        ]
        resistances = [
            r for r in resistances
            if (r["price"] - current_close) <= max_distance_abs
        ]

    # Rank by practical relevance: closest first, then more recent, then stronger.
    supports.sort(key=lambda s: (
        current_close - s["price"],
        (n - 1) - s["bar_index"],
        -s["strength"],
        -s["price"],
    ))
    resistances.sort(key=lambda r: (
        r["price"] - current_close,
        (n - 1) - r["bar_index"],
        -r["strength"],
        r["price"],
    ))

    supports = supports[:max_levels]
    resistances = resistances[:max_levels]

    nearest_support = supports[0]["price"] if supports else None
    nearest_resistance = resistances[0]["price"] if resistances else None

    return {
        "supports": supports,
        "resistances": resistances,
        "nearest_support": nearest_support,
        "nearest_resistance": nearest_resistance,
        "current_close": round(current_close, 4),
    }
