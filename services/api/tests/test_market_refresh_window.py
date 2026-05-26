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


def test_bourse_session_status_is_live_during_continuous_session(monkeypatch) -> None:
    monkeypatch.setattr(refresh_window, "get_holiday_info", lambda *_args, **_kwargs: None)

    status = refresh_window.bourse_session_status(
        dt.datetime(2026, 4, 15, 10, 0, tzinfo=refresh_window.CASABLANCA_TZ)
    )

    assert status["phase"] == "continuous"
    assert status["is_live_session"] is True
    assert status["next_state_at"] == dt.datetime(2026, 4, 15, 15, 20, tzinfo=refresh_window.CASABLANCA_TZ)


def test_bourse_session_status_is_live_during_closing_auction(monkeypatch) -> None:
    monkeypatch.setattr(refresh_window, "get_holiday_info", lambda *_args, **_kwargs: None)

    status = refresh_window.bourse_session_status(
        dt.datetime(2026, 4, 15, 15, 25, tzinfo=refresh_window.CASABLANCA_TZ)
    )

    assert status["phase"] == "closing_auction"
    assert status["is_live_session"] is True


def test_bourse_session_status_is_closed_after_live_close(monkeypatch) -> None:
    monkeypatch.setattr(refresh_window, "get_holiday_info", lambda *_args, **_kwargs: None)

    status = refresh_window.bourse_session_status(
        dt.datetime(2026, 4, 15, 16, 0, tzinfo=refresh_window.CASABLANCA_TZ)
    )

    assert status["phase"] == "post_close"
    assert status["is_live_session"] is False
    assert status["next_state_at"] == dt.datetime(2026, 4, 16, 9, 30, tzinfo=refresh_window.CASABLANCA_TZ)


def test_bourse_session_status_holiday_is_closed(monkeypatch) -> None:
    holiday = dt.date(2026, 4, 15)
    monkeypatch.setattr(
        refresh_window,
        "get_holiday_info",
        lambda day, symbol=None: {"name": "Holiday", "certainty": "confirmed"} if day == holiday else None,
    )

    status = refresh_window.bourse_session_status(
        dt.datetime(2026, 4, 15, 10, 0, tzinfo=refresh_window.CASABLANCA_TZ)
    )

    assert status["phase"] == "closed"
    assert status["is_live_session"] is False
    assert status["holiday_name"] == "Holiday"
    assert status["next_state_at"] == dt.datetime(2026, 4, 16, 9, 30, tzinfo=refresh_window.CASABLANCA_TZ)
