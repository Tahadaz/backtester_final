from __future__ import annotations

import math
from typing import Any

import pandas as pd

from .masi_float_shares import MASI_FLOAT_SHARES


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def benchmark_weights_from_panel(
    panel_slice: pd.DataFrame,
    *,
    symbol_col: str = "symbol",
    close_col: str = "close",
    free_float_factor_col: str = "free_float_factor",
) -> dict[str, float]:
    weights: dict[str, float] = {}
    total = 0.0
    if panel_slice.empty:
        return weights
    for _, row in panel_slice.iterrows():
        symbol = str(row.get(symbol_col) or "").strip().upper()
        close = _finite(row.get(close_col))
        float_shares = _finite(MASI_FLOAT_SHARES.get(symbol))
        if not symbol or close is None or close <= 0 or float_shares is None or float_shares <= 0:
            continue
        factor = _finite(row.get(free_float_factor_col))
        effective_float = float_shares * (factor if factor is not None and factor > 0 else 1.0)
        market_value = effective_float * close
        if market_value <= 0 or not math.isfinite(market_value):
            continue
        weights[symbol] = market_value
        total += market_value
    if total <= 0:
        return {}
    return {symbol: value / total for symbol, value in weights.items()}


__all__ = ["benchmark_weights_from_panel"]
