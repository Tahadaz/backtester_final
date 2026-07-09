"""ICT / Smart-Money-Concept support & resistance candidate detectors.

Pure module: no DB/HTTP/plotting imports. All functions are deterministic
given their numpy inputs.

Every detector returns levels tagged with a ``bar_index`` that marks the bar
at which the pattern is CONFIRMED — i.e. the earliest index at which the
level could legitimately be known using only data up to and including that
bar. Callers that build strictly-causal per-bar series MUST NOT use a level
before its ``bar_index``; this is what makes these detectors safe to drop
into a walk-forward / backtest pipeline without lookahead bias.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from core.quant_core.strategy_plan.levels import (
    _is_swing_high,
    _is_swing_low,
    compute_atr,
)

__all__ = [
    "detect_liquidity_pools",
    "detect_order_blocks",
    "detect_fair_value_gaps",
    "prior_period_extremes",
]


def _empty_level_result(current_close: float) -> dict[str, Any]:
    return {
        "supports": [],
        "resistances": [],
        "nearest_support": None,
        "nearest_resistance": None,
        "current_close": round(float(current_close), 4) if np.isfinite(current_close) else 0.0,
    }


def _cluster_pivots(pivots: list[tuple[float, int]], tolerance: float) -> list[dict[str, Any]]:
    """Cluster (price, confirm_bar_index) pivots within `tolerance` of each other.

    A cluster's confirmation bar is the LATEST confirmation among its members
    (the cluster as a whole is only knowable once every pivot forming it has
    been confirmed). A lone pivot forms its own weak (strength=1) cluster.
    """
    if not pivots:
        return []
    ordered = sorted(pivots, key=lambda item: item[0])
    clusters: list[list[tuple[float, int]]] = [[ordered[0]]]
    for price, bar_index in ordered[1:]:
        if price - clusters[-1][-1][0] <= tolerance:
            clusters[-1].append((price, bar_index))
        else:
            clusters.append([(price, bar_index)])
    out: list[dict[str, Any]] = []
    for cluster in clusters:
        prices = [p for p, _ in cluster]
        confirm_bar = max(b for _, b in cluster)
        out.append(
            {
                "price": round(float(np.mean(prices)), 4),
                "bar_index": int(confirm_bar),
                "strength": int(len(cluster)),
            }
        )
    return out


def detect_liquidity_pools(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    *,
    left_bars: int = 3,
    right_bars: int = 3,
    atr_tol_mult: float = 0.5,
    lookback: int = 250,
    max_levels: int = 8,
) -> dict[str, Any]:
    """Detect buy-side/sell-side liquidity pools ("equal highs/lows").

    A confirmed swing high/low (N-bar fractal, reusing `_is_swing_high` /
    `_is_swing_low`) at index i is only knowable at bar `i + right_bars`
    (once the right-side bars exist to confirm dominance). Equal highs
    within `atr_tol_mult * ATR` of each other cluster into a single
    buy-side-liquidity resistance level; equal lows cluster into a
    sell-side-liquidity support level. A lone (unclustered) pivot is still
    returned but with `strength=1` (weak).

    Causality guarantee: a returned level's `bar_index` is the LATEST
    confirmation bar among the pivots forming its cluster, so it is never
    knowable earlier than that bar.
    """
    n = len(close)
    current_close = float(close[-1]) if n > 0 else 0.0
    min_bars = left_bars + right_bars + 2
    if n < min_bars:
        return _empty_level_result(current_close)

    lb = min(lookback, n)
    offset = n - lb
    h = high[offset:]
    l_ = low[offset:]

    atr_abs, _ = compute_atr(high, low, close, window=14)
    tolerance = atr_tol_mult * atr_abs if atr_abs > 0 else 0.0

    raw_highs: list[tuple[float, int]] = []
    raw_lows: list[tuple[float, int]] = []
    for i in range(left_bars, len(h) - right_bars):
        abs_i = offset + i
        confirm_idx = abs_i + right_bars
        if confirm_idx >= n:
            continue
        if _is_swing_high(h, i, left_bars, right_bars):
            raw_highs.append((float(h[i]), confirm_idx))
        if _is_swing_low(l_, i, left_bars, right_bars):
            raw_lows.append((float(l_[i]), confirm_idx))

    resistance_clusters = _cluster_pivots(raw_highs, tolerance)
    support_clusters = _cluster_pivots(raw_lows, tolerance)

    supports = [s for s in support_clusters if s["price"] < current_close]
    resistances = [r for r in resistance_clusters if r["price"] > current_close]

    supports.sort(key=lambda s: (current_close - s["price"], -s["bar_index"], -s["strength"], -s["price"]))
    resistances.sort(key=lambda r: (r["price"] - current_close, -r["bar_index"], -r["strength"], r["price"]))

    supports = supports[:max_levels]
    resistances = resistances[:max_levels]

    return {
        "supports": supports,
        "resistances": resistances,
        "nearest_support": supports[0]["price"] if supports else None,
        "nearest_resistance": resistances[0]["price"] if resistances else None,
        "current_close": round(current_close, 4),
    }


def detect_order_blocks(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    *,
    displacement_atr_mult: float = 1.5,
    lookback: int = 250,
    max_displacement_bars: int = 3,
    max_levels: int = 6,
) -> dict[str, Any]:
    """Detect bullish/bearish order blocks (last opposite-close candle before a displacement).

    Bullish OB: the last DOWN-close candle (close < open) immediately before
    an up-displacement — a subsequent bar within `max_displacement_bars`
    whose range from that candle's low (`high[j] - low[i]`) exceeds
    `displacement_atr_mult * ATR` AND closes above the candle's high
    (structure break). Zone = [low[i], high[i]]; reference level (support)
    = low[i].

    Bearish OB: the last UP-close candle before a down-displacement,
    mirrored; reference level (resistance) = high[i].

    Causality guarantee: a block is only reported with `bar_index` equal to
    the displacement's confirmation bar `j` — never at the origin candle `i`
    itself, since the block is only meaningful once the displacement that
    validates it has occurred.
    """
    n = len(close)
    current_close = float(close[-1]) if n > 0 else 0.0
    if n < 5:
        return _empty_level_result(current_close)

    lb = min(lookback, n)
    offset = n - lb
    atr_abs, _ = compute_atr(high, low, close, window=14)
    if atr_abs <= 0:
        return _empty_level_result(current_close)
    threshold = displacement_atr_mult * atr_abs

    # confirm_bar -> best (most recent origin) candidate for that confirmation bar
    bullish_by_confirm: dict[int, dict[str, Any]] = {}
    bearish_by_confirm: dict[int, dict[str, Any]] = {}

    last_idx = n - 1
    for i in range(offset, last_idx):
        is_down = close[i] < open_[i]
        is_up = close[i] > open_[i]
        if not is_down and not is_up:
            continue
        window_end = min(i + max_displacement_bars, last_idx)
        for j in range(i + 1, window_end + 1):
            if is_down:
                disp_range = float(high[j] - low[i])
                if disp_range >= threshold and float(close[j]) > float(high[i]):
                    candidate = {
                        "price_low": float(low[i]),
                        "price_high": float(high[i]),
                        "bar_index": int(j),
                        "origin_bar": int(i),
                        "strength": round(disp_range / atr_abs, 2),
                    }
                    prior = bullish_by_confirm.get(j)
                    if prior is None or i > prior["origin_bar"]:
                        bullish_by_confirm[j] = candidate
                    break
            else:
                disp_range = float(high[i] - low[j])
                if disp_range >= threshold and float(close[j]) < float(low[i]):
                    candidate = {
                        "price_low": float(low[i]),
                        "price_high": float(high[i]),
                        "bar_index": int(j),
                        "origin_bar": int(i),
                        "strength": round(disp_range / atr_abs, 2),
                    }
                    prior = bearish_by_confirm.get(j)
                    if prior is None or i > prior["origin_bar"]:
                        bearish_by_confirm[j] = candidate
                    break

    supports = [
        {"price": round(c["price_low"], 4), "bar_index": c["bar_index"], "strength": c["strength"]}
        for c in bullish_by_confirm.values()
        if c["price_low"] < current_close
    ]
    resistances = [
        {"price": round(c["price_high"], 4), "bar_index": c["bar_index"], "strength": c["strength"]}
        for c in bearish_by_confirm.values()
        if c["price_high"] > current_close
    ]

    supports.sort(key=lambda s: (-s["bar_index"], -s["strength"], current_close - s["price"]))
    resistances.sort(key=lambda r: (-r["bar_index"], -r["strength"], r["price"] - current_close))

    supports = supports[:max_levels]
    resistances = resistances[:max_levels]

    return {
        "supports": supports,
        "resistances": resistances,
        "nearest_support": supports[0]["price"] if supports else None,
        "nearest_resistance": resistances[0]["price"] if resistances else None,
        "current_close": round(current_close, 4),
    }


def detect_fair_value_gaps(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    *,
    min_gap_atr_mult: float = 0.25,
    lookback: int = 250,
    max_levels: int = 6,
) -> dict[str, Any]:
    """Detect bullish/bearish 3-candle fair value gaps (FVG).

    Bullish FVG at index i: `high[i-1] < low[i+1]`, gap size
    `low[i+1] - high[i-1] >= min_gap_atr_mult * ATR`. Level = gap midpoint
    (support). Bearish FVG at index i: `low[i-1] > high[i+1]`, mirrored
    (resistance).

    Causality guarantee: the gap involves candles i-1, i, i+1 so it can only
    be known once the 3rd candle (i+1) exists; `bar_index` is reported as
    `i + 1`, never earlier.

    Each level also carries `mitigated`: whether price has already traded
    back through the midpoint within the supplied array (using only data
    already present in the array — no lookahead beyond what the caller
    passed in).
    """
    n = len(close)
    current_close = float(close[-1]) if n > 0 else 0.0
    if n < 4:
        return _empty_level_result(current_close)

    lb = min(lookback, n)
    offset = max(1, n - lb)
    atr_abs, _ = compute_atr(high, low, close, window=14)
    min_gap = min_gap_atr_mult * atr_abs if atr_abs > 0 else 0.0

    raw_supports: list[dict[str, Any]] = []
    raw_resistances: list[dict[str, Any]] = []

    for i in range(offset, n - 1):
        confirm_idx = i + 1
        if confirm_idx >= n:
            continue
        if float(high[i - 1]) < float(low[i + 1]):
            gap = float(low[i + 1] - high[i - 1])
            if gap >= min_gap:
                midpoint = (float(high[i - 1]) + float(low[i + 1])) / 2.0
                mitigated = bool(np.any(low[confirm_idx + 1:] <= midpoint)) if confirm_idx + 1 < n else False
                raw_supports.append(
                    {
                        "price": round(midpoint, 4),
                        "bar_index": int(confirm_idx),
                        "strength": round(gap / atr_abs, 2) if atr_abs > 0 else 0.0,
                        "mitigated": mitigated,
                    }
                )
        if float(low[i - 1]) > float(high[i + 1]):
            gap = float(low[i - 1] - high[i + 1])
            if gap >= min_gap:
                midpoint = (float(low[i - 1]) + float(high[i + 1])) / 2.0
                mitigated = bool(np.any(high[confirm_idx + 1:] >= midpoint)) if confirm_idx + 1 < n else False
                raw_resistances.append(
                    {
                        "price": round(midpoint, 4),
                        "bar_index": int(confirm_idx),
                        "strength": round(gap / atr_abs, 2) if atr_abs > 0 else 0.0,
                        "mitigated": mitigated,
                    }
                )

    supports = [s for s in raw_supports if s["price"] < current_close]
    resistances = [r for r in raw_resistances if r["price"] > current_close]

    # prefer unmitigated (still-live) gaps, then most recent, then largest
    supports.sort(key=lambda s: (s["mitigated"], -s["bar_index"], -s["strength"]))
    resistances.sort(key=lambda r: (r["mitigated"], -r["bar_index"], -r["strength"]))

    supports = supports[:max_levels]
    resistances = resistances[:max_levels]

    return {
        "supports": supports,
        "resistances": resistances,
        "nearest_support": supports[0]["price"] if supports else None,
        "nearest_resistance": resistances[0]["price"] if resistances else None,
        "current_close": round(current_close, 4),
    }


def prior_period_extremes(
    index: pd.DatetimeIndex,
    high: np.ndarray,
    low: np.ndarray,
    *,
    period: str,
) -> dict[str, Any]:
    """Per-bar High/Low of the most recently COMPLETED prior week/month.

    `period` is "W" or "M". For every bar, only the extreme of the period
    strictly BEFORE the bar's own period is used — the bar's own (possibly
    still-open) period is never touched, so this is causal by construction
    regardless of the bar's position within its period.

    Returns
    -------
    dict with keys:
        ``prior_high``, ``prior_low`` — np.ndarray aligned to `index`
            (NaN where no completed prior period exists yet).
        ``latest`` — {"prior_high": float|None, "prior_low": float|None}
            snapshot for the final bar, convenience for the "current" state.
    """
    if period not in {"W", "M"}:
        raise ValueError("period must be 'W' or 'M'")

    n = len(high)
    if n == 0 or len(index) != n:
        return {
            "prior_high": np.full(n, np.nan, dtype="float64"),
            "prior_low": np.full(n, np.nan, dtype="float64"),
            "latest": {"prior_high": None, "prior_low": None},
        }

    dt_index = pd.DatetimeIndex(index)
    s_high = pd.Series(np.asarray(high, dtype="float64"), index=dt_index)
    s_low = pd.Series(np.asarray(low, dtype="float64"), index=dt_index)

    resample_freq = "ME" if period == "M" else period
    period_high = s_high.resample(resample_freq).max()
    period_low = s_low.resample(resample_freq).min()
    period_high.index = period_high.index.to_period(period)
    period_low.index = period_low.index.to_period(period)

    bar_period = dt_index.to_period(period)
    prior_period = bar_period - 1

    high_map = period_high.to_dict()
    low_map = period_low.to_dict()

    prior_high = np.array(
        [high_map.get(pk, np.nan) for pk in prior_period],
        dtype="float64",
    )
    prior_low = np.array(
        [low_map.get(pk, np.nan) for pk in prior_period],
        dtype="float64",
    )

    latest_high = float(prior_high[-1]) if np.isfinite(prior_high[-1]) else None
    latest_low = float(prior_low[-1]) if np.isfinite(prior_low[-1]) else None

    return {
        "prior_high": prior_high,
        "prior_low": prior_low,
        "latest": {"prior_high": latest_high, "prior_low": latest_low},
    }
