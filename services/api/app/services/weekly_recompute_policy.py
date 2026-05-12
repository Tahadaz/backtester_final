from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from core.quant_core.signal_engine.modes import ALL_SIGNAL_MODE_NAMES, signal_mode_storage_name
from services.api.app.models import SignalEngineGlobalResult, WfoGlobalSignal, WfoSignalSummary

HORIZONS = ("weekly", "monthly", "quarterly")
VARIANTS = ALL_SIGNAL_MODE_NAMES
WFO_CATEGORIES = ("tendance", "momentum", "oscillation", "volume")
MARKET_REFRESH_TIMEZONE = ZoneInfo("Africa/Casablanca")
WEEKLY_RECOMPUTE_DELTA = timedelta(days=7)


def _normalize_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def needs_weekly_recompute(
    last_computed_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    normalized_last = _normalize_utc(last_computed_at)
    if normalized_last is None:
        return True
    normalized_now = _normalize_utc(now) or datetime.now(timezone.utc)
    return normalized_last <= (normalized_now - WEEKLY_RECOMPUTE_DELTA)


def is_friday_market_refresh(now: datetime | None = None) -> bool:
    normalized_now = _normalize_utc(now) or datetime.now(timezone.utc)
    return normalized_now.astimezone(MARKET_REFRESH_TIMEZONE).weekday() == 4


def get_signal_engine_last_full_compute_at(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    variant: str,
) -> datetime | None:
    row = (
        db.query(SignalEngineGlobalResult)
        .filter_by(symbol=symbol, horizon=horizon, variant=variant)
        .first()
    )
    return _normalize_utc(row.computed_at if row is not None else None)


def get_wfo_last_full_compute_at(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    variant: str,
) -> datetime | None:
    global_row = (
        db.query(WfoGlobalSignal)
        .filter_by(symbol=symbol, horizon=horizon, variant=variant)
        .first()
    )
    if global_row is not None and global_row.computed_at is not None:
        return _normalize_utc(global_row.computed_at)

    rows = (
        db.query(WfoSignalSummary)
        .filter_by(symbol=symbol, horizon=horizon, variant=variant)
        .all()
    )
    if not rows:
        return None

    by_category = {row.category: _normalize_utc(row.computed_at) for row in rows}
    category_times = [by_category.get(category) for category in WFO_CATEGORIES]
    if any(value is None for value in category_times):
        return None
    return min(value for value in category_times if value is not None)


def iter_signal_engine_weekly_stale_tuples(
    db: Session,
    *,
    symbols: Iterable[str],
    horizons: Iterable[str] = HORIZONS,
    variants: Iterable[str] = VARIANTS,
    now: datetime | None = None,
) -> list[tuple[str, str, str]]:
    normalized_now = _normalize_utc(now) or datetime.now(timezone.utc)
    stale: list[tuple[str, str, str]] = []
    for symbol in symbols:
        for horizon in horizons:
            for raw_variant in variants:
                variant = signal_mode_storage_name(raw_variant)
                last_computed_at = get_signal_engine_last_full_compute_at(
                    db,
                    symbol=symbol,
                    horizon=horizon,
                    variant=variant,
                )
                if needs_weekly_recompute(last_computed_at, normalized_now):
                    stale.append((symbol, horizon, variant))
    return stale


def iter_wfo_weekly_stale_tuples(
    db: Session,
    *,
    symbols: Iterable[str],
    horizons: Iterable[str] = HORIZONS,
    variants: Iterable[str] = VARIANTS,
    now: datetime | None = None,
) -> list[tuple[str, str, str]]:
    normalized_now = _normalize_utc(now) or datetime.now(timezone.utc)
    stale: list[tuple[str, str, str]] = []
    for symbol in symbols:
        for horizon in horizons:
            for raw_variant in variants:
                variant = signal_mode_storage_name(raw_variant)
                last_computed_at = get_wfo_last_full_compute_at(
                    db,
                    symbol=symbol,
                    horizon=horizon,
                    variant=variant,
                )
                if needs_weekly_recompute(last_computed_at, normalized_now):
                    stale.append((symbol, horizon, variant))
    return stale
