"""Baseline return computation shared by support/resistance backtest paths.

This module is intentionally pure: no database, HTTP, or plotting concerns.
"""
from __future__ import annotations

from typing import Any, Sequence

import numpy as np


def _safe_returns(values: Sequence[Any] | np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype="float64")
    if arr.ndim != 1:
        arr = arr.reshape(-1)
    arr = np.where(np.isfinite(arr), arr, 0.0)
    return arr


def baseline_returns_from_position(
    close: Sequence[Any] | np.ndarray,
    position: Sequence[Any] | np.ndarray,
    *,
    cost_bps: float,
    slippage_bps: float = 0.0,
) -> np.ndarray:
    """Return per-bar baseline returns for an executed position series."""
    close_arr = _safe_returns(close)
    pos = _safe_returns(position)
    n = min(len(close_arr), len(pos))
    if n < 2:
        return np.zeros(0, dtype="float64")
    close_arr = close_arr[:n]
    pos = pos[:n]
    out = np.zeros(n - 1, dtype="float64")
    friction = (float(cost_bps) + float(slippage_bps)) / 10_000.0
    prev_pos = 0.0
    for idx in range(n - 1):
        c0 = float(close_arr[idx])
        c1 = float(close_arr[idx + 1])
        ret = (c1 / c0 - 1.0) if c0 > 0.0 else 0.0
        current_pos = float(pos[idx])
        transition_cost = abs(current_pos - prev_pos) * friction
        out[idx] = current_pos * ret - transition_cost
        prev_pos = current_pos
    if n >= 2:
        out[-1] -= abs(float(pos[n - 1]) - prev_pos) * friction
    return out
