from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _clamp_0_100(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _safe_last(series: pd.Series) -> float | None:
    if series is None or series.empty:
        return None
    value = pd.to_numeric(series, errors="coerce").dropna()
    if value.empty:
        return None
    out = float(value.iloc[-1])
    return out if np.isfinite(out) else None


def classify_regime(
    bars: pd.DataFrame,
    *,
    adx_series: pd.Series | None = None,
) -> dict[str, Any]:
    """
    Classify trend regime from price vs SMA200 and SMA200 slope.
    Returns score in [0, 100], directional bias, and explain inputs.
    """
    close = pd.to_numeric(bars.get("Close"), errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if close.empty:
        return {
            "label": "unknown",
            "bias": 0,
            "score": 50.0,
            "inputs": {},
            "thresholds": {"sma_window": 200, "slope_lookback": 20},
            "explain": "Missing close series; neutral default.",
        }

    sma200 = close.rolling(200, min_periods=200).mean()
    sma_now = _safe_last(sma200)
    price_now = float(close.iloc[-1])
    sma_prev = _safe_last(sma200.shift(20))
    n_bars = int(len(close))

    if n_bars < 200 or sma_now is None or sma_prev is None:
        return {
            "label": "insufficient_history",
            "bias": 0,
            "score": 50.0,
            "inputs": {
                "price": price_now,
                "sma200": sma_now,
                "sma200_slope_pct_20": None,
                "adx": _safe_last(adx_series) if adx_series is not None else None,
                "n_bars": n_bars,
            },
            "thresholds": {"sma_window": 200, "slope_lookback": 20},
            "explain": "insufficient_history: SMA200/slope unavailable; using neutral regime defaults.",
        }

    slope_pct = None
    if sma_now is not None and sma_prev not in (None, 0.0):
        slope_pct = (float(sma_now) - float(sma_prev)) / abs(float(sma_prev))

    label = "neutral"
    bias = 0
    score = 50.0

    if sma_now is not None and slope_pct is not None:
        if price_now > sma_now and slope_pct > 0:
            label = "bullish_trend"
            bias = 1
            score = 85.0
        elif price_now < sma_now and slope_pct < 0:
            label = "bearish_trend"
            bias = -1
            score = 20.0
        else:
            label = "sideways_transition"
            bias = 0
            score = 55.0

    adx_now = _safe_last(adx_series) if adx_series is not None else None
    if adx_now is not None:
        if adx_now >= 25.0:
            score += 5.0 if bias != 0 else -5.0
        elif adx_now < 15.0:
            score -= 5.0

    score = _clamp_0_100(score)

    return {
        "label": label,
        "bias": int(bias),
        "score": float(score),
        "inputs": {
            "price": price_now,
            "sma200": sma_now,
            "sma200_slope_pct_20": slope_pct,
            "adx": adx_now,
        },
        "thresholds": {
            "sma_window": 200,
            "slope_lookback": 20,
            "adx_trend": 25.0,
            "adx_weak": 15.0,
        },
        "explain": (
            "Price above rising SMA200 implies bullish regime; "
            "price below falling SMA200 implies bearish regime."
        ),
    }
