from __future__ import annotations

HORIZON_LOOKBACK_YEARS: dict[str, int] = {
    "short": 5,
    "weekly": 5,
    "medium": 10,
    "monthly": 10,
    "long": 20,
    "quarterly": 20,
}

TRADING_BARS_PER_YEAR = 252
