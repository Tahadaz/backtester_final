"""Vectorized factor condition evaluation for Phase 2 cross-product variants.

Each condition takes a factor close-price array (already calendar-aligned,
lag applied upstream) and returns a boolean mask. True = condition holds on
that bar; NaN-position → False (no position taken when data is missing).

Supported forms:
  zscore    — rolling z-score vs threshold (Ilmanen 2011, Ch. 15)
  momentum  — N-day return sign vs threshold
  change    — absolute N-day change vs threshold (e.g. yield moves in bp)
  level     — raw value vs threshold
  direction — 1-day return sign (special case of momentum, lookback=1)
"""
from __future__ import annotations

import numpy as np

from core.quant_core.signal_engine.domain import FactorConditionMeta


def _rolling_mean(x: np.ndarray, window: int) -> np.ndarray:
    out = np.full_like(x, np.nan, dtype=float)
    cs = np.nancumsum(x)
    count = np.cumsum(~np.isnan(x))
    for i in range(window - 1, len(x)):
        n = count[i] - (count[i - window] if i >= window else 0)
        s = cs[i] - (cs[i - window] if i >= window else 0)
        out[i] = s / n if n >= window else np.nan
    return out


def _rolling_std(x: np.ndarray, window: int) -> np.ndarray:
    out = np.full_like(x, np.nan, dtype=float)
    for i in range(window - 1, len(x)):
        seg = x[i - window + 1 : i + 1]
        valid = seg[~np.isnan(seg)]
        out[i] = valid.std(ddof=1) if len(valid) >= window else np.nan
    return out


def _compare(values: np.ndarray, threshold: float, direction: str) -> np.ndarray:
    """Element-wise comparison; NaN → False."""
    nan_mask = np.isnan(values)
    if direction == "below":
        result = values < threshold
    elif direction == "above":
        result = values > threshold
    else:
        raise ValueError(f"direction must be 'above' or 'below', got {direction!r}")
    result[nan_mask] = False
    return result


def _zscore_condition(
    factor_close: np.ndarray,
    lookback: int,
    threshold: float,
    direction: str,
) -> np.ndarray:
    mu = _rolling_mean(factor_close, lookback)
    sigma = _rolling_std(factor_close, lookback)
    with np.errstate(invalid="ignore", divide="ignore"):
        z = np.where(sigma > 0, (factor_close - mu) / sigma, np.nan)
    return _compare(z, threshold, direction)


def _momentum_condition(
    factor_close: np.ndarray,
    lookback: int,
    threshold: float,
    direction: str,
) -> np.ndarray:
    pct = np.full_like(factor_close, np.nan, dtype=float)
    pct[lookback:] = (factor_close[lookback:] - factor_close[:-lookback]) / np.where(
        factor_close[:-lookback] != 0, factor_close[:-lookback], np.nan
    )
    return _compare(pct, threshold, direction)


def _change_condition(
    factor_close: np.ndarray,
    lookback: int,
    threshold: float,
    direction: str,
) -> np.ndarray:
    delta = np.full_like(factor_close, np.nan, dtype=float)
    delta[lookback:] = factor_close[lookback:] - factor_close[:-lookback]
    return _compare(delta, threshold, direction)


def _level_condition(
    factor_close: np.ndarray,
    threshold: float,
    direction: str,
) -> np.ndarray:
    return _compare(factor_close.astype(float), threshold, direction)


def _direction_condition(
    factor_close: np.ndarray,
    direction: str,
) -> np.ndarray:
    """1-day return sign. direction='above' → today > yesterday."""
    delta = np.full_like(factor_close, np.nan, dtype=float)
    delta[1:] = factor_close[1:] - factor_close[:-1]
    return _compare(delta, 0.0, direction)


def evaluate_condition(
    condition: FactorConditionMeta,
    factor_close: np.ndarray,
) -> np.ndarray:
    """Return a boolean (bool dtype) array aligned to factor_close.

    True  = condition holds on that bar.
    False = condition does not hold, or data is NaN.

    Args:
        condition:    FactorConditionMeta describing form, lookback, threshold, direction.
        factor_close: 1-D float array of factor closing prices (already lag-aligned
                      to the target stock's calendar by research/alignment.py).

    Returns:
        np.ndarray of dtype bool, same length as factor_close.
    """
    arr = np.asarray(factor_close, dtype=float)
    form = condition.form

    if form == "zscore":
        mask = _zscore_condition(arr, condition.lookback, condition.threshold, condition.direction)
    elif form == "momentum":
        mask = _momentum_condition(arr, condition.lookback, condition.threshold, condition.direction)
    elif form == "change":
        mask = _change_condition(arr, condition.lookback, condition.threshold, condition.direction)
    elif form == "level":
        mask = _level_condition(arr, condition.threshold, condition.direction)
    elif form == "direction":
        mask = _direction_condition(arr, condition.direction)
    else:
        raise ValueError(f"Unknown condition form: {form!r}")

    return mask.astype(bool)
