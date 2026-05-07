from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo
from .market_holidays import get_holiday_info

CASABLANCA_TZ = ZoneInfo("Africa/Casablanca")
BOURSE_SOURCE = "bourse_direct"
BOURSE_REFRESH_CUTOFF = dt.time(hour=17, minute=0)
BOURSE_REFRESH_CUTOFF_LABEL = "17:00"


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
