"""Point-in-time market-equity primitives for the structural-value model.

Stored accounting-workbook market-cap fields are intentionally not accepted
here: market equity at a decision date is the observable price at that date
times shares outstanding that were themselves available by that date.
"""
from __future__ import annotations

import math
from typing import Any


def _positive_finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or result <= 0:
        return None
    return result


def decision_date_market_equity(*, close: Any, shares_outstanding: Any) -> float | None:
    """Return decision-date market equity, or ``None`` when either input is unusable."""

    price = _positive_finite(close)
    shares = _positive_finite(shares_outstanding)
    if price is None or shares is None:
        return None
    market_equity = price * shares
    return market_equity if math.isfinite(market_equity) and market_equity > 0 else None


__all__ = ["decision_date_market_equity"]
