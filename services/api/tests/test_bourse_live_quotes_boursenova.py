"""Casablanca live quotes now read the boursenova history API (today, then last 5 days)."""
from __future__ import annotations

import datetime as dt

import pandas as pd

from services.api.app.services import bourse_live_quotes as quotes

TODAY = dt.date(2026, 11, 17)


class _Adapter:
    """Empty for a window starting today (holiday / pre-open), data for the 5-day window."""

    calls: list = []

    def __init__(self, **kwargs):
        pass

    def load(self, symbols, start=None, end=None, interval="1d"):
        _Adapter.calls.append((start, end))
        if start == TODAY.isoformat():
            frame = pd.DataFrame()
        else:
            frame = pd.DataFrame(
                {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [10.0]},
                index=pd.DatetimeIndex(["2026-11-16"]),
            )
        return type("MD", (), {"bars": {symbols[0]: frame}})()


def test_casablanca_load_falls_back_from_today_to_last_five_days(monkeypatch):
    monkeypatch.setattr(quotes, "BoursenovaHistoryAdapter", _Adapter)
    monkeypatch.setattr(quotes, "boursenova_today", lambda: TODAY)
    _Adapter.calls = []

    frame = quotes._load_one(quotes.CASABLANCA_PROVIDER, "IAM")

    assert _Adapter.calls == [("2026-11-17", "2026-11-17"), ("2026-11-12", "2026-11-17")]
    assert frame is not None and float(frame["Close"].iloc[-1]) == 1.5


def test_casablanca_source_url_points_at_boursenova_api():
    assert "/api/boursenova/stock-historical" in quotes._provider_source_url(quotes.CASABLANCA_PROVIDER, "IAM")
    assert "casablanca-bourse.com/fr/live-market" not in quotes.SOURCE_URL_TEMPLATE
