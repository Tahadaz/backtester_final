from __future__ import annotations

import datetime as dt
from typing import Any


def _date(value: Any) -> dt.date | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def normalize_yfinance_calendar(symbol: str, calendar: Any, dividends: Any = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    payload = calendar
    if hasattr(calendar, "to_dict"):
        try:
            payload = calendar.to_dict()
        except Exception:
            payload = calendar
    if isinstance(payload, dict):
        earnings_value = (
            payload.get("Earnings Date")
            or payload.get("EarningsDate")
            or payload.get("earningsDate")
            or payload.get("Earnings")
        )
        if isinstance(earnings_value, (list, tuple)):
            earnings_value = earnings_value[0] if earnings_value else None
        earnings_date = _date(earnings_value)
        if earnings_date is not None:
            rows.append(
                {
                    "symbol": symbol.upper(),
                    "event_type": "earnings",
                    "event_date": earnings_date,
                    "event_date_confidence": "estimated",
                    "impact_tier": "moderate",
                    "expected_direction": None,
                    "title": f"{symbol.upper()} earnings",
                    "notes": None,
                    "source": "yfinance",
                    "source_payload": payload,
                }
            )
    if dividends is not None:
        try:
            tail = dividends.tail(8) if hasattr(dividends, "tail") else dividends
            iterable = tail.items() if hasattr(tail, "items") else []
        except Exception:
            iterable = []
        for raw_date, amount in iterable:
            event_date = _date(raw_date)
            if event_date is None:
                continue
            rows.append(
                {
                    "symbol": symbol.upper(),
                    "event_type": "dividend",
                    "event_date": event_date,
                    "event_date_confidence": "confirmed",
                    "impact_tier": "routine",
                    "expected_direction": "neutral",
                    "title": f"{symbol.upper()} dividend",
                    "notes": f"Dividend amount: {amount}",
                    "source": "yfinance",
                    "source_payload": {"date": str(raw_date), "amount": float(amount) if amount is not None else None},
                }
            )
    return rows
