from __future__ import annotations

import datetime as dt

from services.api.app import market_refresh_window as refresh_window


def test_latest_completed_bourse_session_date_on_monday_morning_is_previous_friday(monkeypatch) -> None:
    monkeypatch.setattr(refresh_window, "get_holiday_info", lambda *_args, **_kwargs: None)

    result = refresh_window.latest_completed_bourse_session_date(
        dt.datetime(2026, 4, 13, 8, 30, tzinfo=refresh_window.CASABLANCA_TZ)
    )

    assert result == dt.date(2026, 4, 10)


def test_latest_completed_bourse_session_date_before_cutoff_uses_previous_trading_day(monkeypatch) -> None:
    monkeypatch.setattr(refresh_window, "get_holiday_info", lambda *_args, **_kwargs: None)

    result = refresh_window.latest_completed_bourse_session_date(
        dt.datetime(2026, 4, 15, 9, 0, tzinfo=refresh_window.CASABLANCA_TZ)
    )

    assert result == dt.date(2026, 4, 14)


def test_latest_completed_bourse_session_date_skips_holidays(monkeypatch) -> None:
    holiday = dt.date(2026, 4, 14)
    monkeypatch.setattr(
        refresh_window,
        "get_holiday_info",
        lambda day, symbol=None: {"name": "Holiday"} if day == holiday else None,
    )

    result = refresh_window.latest_completed_bourse_session_date(
        dt.datetime(2026, 4, 15, 9, 0, tzinfo=refresh_window.CASABLANCA_TZ)
    )

    assert result == dt.date(2026, 4, 13)


def test_latest_completed_bourse_session_date_after_cutoff_uses_same_day(monkeypatch) -> None:
    monkeypatch.setattr(refresh_window, "get_holiday_info", lambda *_args, **_kwargs: None)

    result = refresh_window.latest_completed_bourse_session_date(
        dt.datetime(2026, 4, 15, 17, 30, tzinfo=refresh_window.CASABLANCA_TZ)
    )

    assert result == dt.date(2026, 4, 15)
