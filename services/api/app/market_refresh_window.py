from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo
from .market_holidays import get_holiday_info

CASABLANCA_TZ = ZoneInfo("Africa/Casablanca")
BOURSE_SOURCE = "bourse_direct"
BOURSE_REFRESH_CUTOFF = dt.time(hour=17, minute=0)
BOURSE_REFRESH_CUTOFF_LABEL = "17:00"
BOURSE_PRE_OPEN = dt.time(hour=9, minute=30)
BOURSE_CONTINUOUS_CLOSE = dt.time(hour=15, minute=20)
BOURSE_LIVE_CLOSE = dt.time(hour=15, minute=30)
LIVE_SESSION_PHASES = {"continuous", "closing_auction"}


def now_casablanca() -> dt.datetime:
    return dt.datetime.now(CASABLANCA_TZ)


def _coerce_casablanca(now: dt.datetime | None = None) -> dt.datetime:
    local_now = now or now_casablanca()
    if local_now.tzinfo is None:
        return local_now.replace(tzinfo=CASABLANCA_TZ)
    return local_now.astimezone(CASABLANCA_TZ)


def is_bourse_source(source: str | None) -> bool:
    return str(source or "").strip().lower() == BOURSE_SOURCE


def is_before_bourse_refresh_cutoff(now: dt.datetime | None = None) -> bool:
    local_now = _coerce_casablanca(now)
    return local_now.timetz().replace(tzinfo=None) < BOURSE_REFRESH_CUTOFF


def is_casablanca_trading_day(day: dt.date) -> bool:
    return day.weekday() < 5 and get_holiday_info(day) is None


def _combine_local(day: dt.date, time_value: dt.time) -> dt.datetime:
    return dt.datetime.combine(day, time_value, tzinfo=CASABLANCA_TZ)


def _next_trading_day(after_day: dt.date) -> dt.date:
    candidate = after_day + dt.timedelta(days=1)
    while not is_casablanca_trading_day(candidate):
        candidate += dt.timedelta(days=1)
    return candidate


def bourse_session_status(now: dt.datetime | None = None) -> dict[str, object]:
    """Return the current Casablanca equity-market live session state."""
    local_now = _coerce_casablanca(now)
    day = local_now.date()
    time_value = local_now.timetz().replace(tzinfo=None)
    holiday = get_holiday_info(day)

    if day.weekday() >= 5 or holiday is not None:
        holiday_name = holiday.get("name") if isinstance(holiday, dict) else None
        holiday_certainty = holiday.get("certainty") if isinstance(holiday, dict) else None
        next_day = day
        while not is_casablanca_trading_day(next_day):
            next_day += dt.timedelta(days=1)
        return {
            "timezone": CASABLANCA_TZ.key,
            "local_time": local_now,
            "session_date": day,
            "phase": "closed",
            "is_live_session": False,
            "next_state_at": _combine_local(next_day, BOURSE_PRE_OPEN),
            "holiday_name": holiday_name,
            "holiday_certainty": holiday_certainty,
        }

    if time_value < BOURSE_PRE_OPEN:
        phase = "pre_open"
        next_state_at = _combine_local(day, BOURSE_PRE_OPEN)
    elif time_value < BOURSE_CONTINUOUS_CLOSE:
        phase = "continuous"
        next_state_at = _combine_local(day, BOURSE_CONTINUOUS_CLOSE)
    elif time_value < BOURSE_LIVE_CLOSE:
        phase = "closing_auction"
        next_state_at = _combine_local(day, BOURSE_LIVE_CLOSE)
    else:
        phase = "post_close"
        next_state_at = _combine_local(_next_trading_day(day), BOURSE_PRE_OPEN)

    return {
        "timezone": CASABLANCA_TZ.key,
        "local_time": local_now,
        "session_date": day,
        "phase": phase,
        "is_live_session": phase in LIVE_SESSION_PHASES,
        "next_state_at": next_state_at,
        "holiday_name": None,
        "holiday_certainty": None,
    }


def is_bourse_live_session(now: dt.datetime | None = None) -> bool:
    return bool(bourse_session_status(now).get("is_live_session"))


def latest_completed_bourse_session_date(now: dt.datetime | None = None) -> dt.date:
    local_now = _coerce_casablanca(now)
    candidate = local_now.date()
    if local_now.timetz().replace(tzinfo=None) < BOURSE_REFRESH_CUTOFF:
        candidate -= dt.timedelta(days=1)
    while not is_casablanca_trading_day(candidate):
        candidate -= dt.timedelta(days=1)
    return candidate


def is_bourse_data_current(data_as_of: dt.date | None, now: dt.datetime | None = None) -> bool:
    if data_as_of is None:
        return False
    return data_as_of >= latest_completed_bourse_session_date(now)


def needs_bourse_refresh(data_as_of: dt.date | None, now: dt.datetime | None = None) -> bool:
    return not is_bourse_data_current(data_as_of, now)
