from __future__ import annotations

import datetime as dt
import logging
import math
import os
from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd
from redis import Redis
from sqlalchemy.orm import Session

from core.quant_core.data import BDCSessionAdapter, BMCECapitalLiveAdapter

from .. import models


DEFAULT_MAX_AGE_SECONDS = 60
CASABLANCA_PROVIDER = "casablanca_bourse_live"
BKB_PROVIDER = "bmce_capital_bourse_live"
SOURCE_PROVIDER = CASABLANCA_PROVIDER
SOURCE_URL_TEMPLATE = "https://www.casablanca-bourse.com/fr/live-market/instruments/{symbol}?pwa=1"
BKB_SOURCE_URL_TEMPLATE = "https://www.bmcecapitalbourse.com/bkbbourse/details/{listing_id}"
PROVIDER_COOLDOWN_SECONDS = int(os.getenv("LIVE_QUOTE_PROVIDER_COOLDOWN_SECONDS", "3600"))
REFRESH_LOCK_SECONDS = int(os.getenv("LIVE_QUOTE_REFRESH_LOCK_SECONDS", "120"))
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LiveQuoteView:
    symbol: str
    session_date: dt.date | None
    quote_timestamp: dt.datetime | None
    open_price: float | None
    last_price: float | None
    high_price: float | None
    low_price: float | None
    prev_close: float | None
    volume: float | None
    source_provider: str
    source_url: str | None
    updated_at: dt.datetime | None
    is_fresh: bool
    age_seconds: float | None


def normalize_symbols(raw_symbols: list[str] | tuple[str, ...] | set[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in raw_symbols:
        symbol = str(raw or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return out


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _as_aware_utc(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def _quote_age_seconds(row: models.BourseLiveQuote, now: dt.datetime | None = None) -> float | None:
    updated_at = _as_aware_utc(row.updated_at)
    if updated_at is None:
        return None
    current = _as_aware_utc(now) or _utcnow()
    return max(0.0, (current - updated_at).total_seconds())


def is_quote_fresh(
    row: models.BourseLiveQuote,
    *,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    now: dt.datetime | None = None,
) -> bool:
    age = _quote_age_seconds(row, now=now)
    return age is not None and age <= max(0, int(max_age_seconds))


def quote_to_view(
    row: models.BourseLiveQuote,
    *,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    now: dt.datetime | None = None,
) -> LiveQuoteView:
    age = _quote_age_seconds(row, now=now)
    return LiveQuoteView(
        symbol=str(row.symbol or "").upper(),
        session_date=row.session_date,
        quote_timestamp=row.quote_timestamp,
        open_price=_safe_float(row.open_price),
        last_price=_safe_float(row.last_price),
        high_price=_safe_float(row.high_price),
        low_price=_safe_float(row.low_price),
        prev_close=_safe_float(row.prev_close),
        volume=_safe_float(row.volume),
        source_provider=row.source_provider or SOURCE_PROVIDER,
        source_url=row.source_url,
        updated_at=row.updated_at,
        is_fresh=age is not None and age <= max(0, int(max_age_seconds)),
        age_seconds=round(age, 3) if age is not None else None,
    )


def _prev_close_for_quote(db: Session, symbol: str, session_date: dt.date | None) -> float | None:
    store = (
        db.query(models.MarketDataStore)
        .filter(models.MarketDataStore.symbol == symbol)
        .filter(models.MarketDataStore.timeframe.in_(["1D", "1d"]))
        .order_by(models.MarketDataStore.data_as_of.desc().nullslast(), models.MarketDataStore.updated_at.desc().nullslast())
        .first()
    )
    if store is None:
        return None
    if session_date is not None and store.data_as_of is not None and session_date > store.data_as_of:
        return _safe_float(getattr(store, "close_last", None))
    return _safe_float(getattr(store, "prev_close", None))


def _upsert_quote_from_frame(
    db: Session,
    symbol: str,
    frame: pd.DataFrame,
    *,
    provider: str,
    source_url: str,
) -> models.BourseLiveQuote | None:
    if frame is None or frame.empty:
        return None
    row_data = frame.sort_index().iloc[-1]
    ts = frame.sort_index().index[-1]
    session_date = ts.date() if hasattr(ts, "date") else None
    now = _utcnow()
    quote = db.get(models.BourseLiveQuote, symbol)
    if quote is None:
        quote = models.BourseLiveQuote(symbol=symbol)
        db.add(quote)

    quote.session_date = session_date
    quote.quote_timestamp = now
    quote.open_price = _safe_float(row_data.get("Open"))
    quote.last_price = _safe_float(row_data.get("Close"))
    quote.high_price = _safe_float(row_data.get("High"))
    quote.low_price = _safe_float(row_data.get("Low"))
    quote.prev_close = _prev_close_for_quote(db, symbol, session_date)
    quote.volume = _safe_float(row_data.get("Volume"))
    quote.source_provider = provider
    quote.source_url = source_url
    quote.raw_json = {
        "source": provider,
        "columns": {str(key): _safe_float(value) for key, value in row_data.items()},
    }
    quote.updated_at = now
    return quote


def _append_quote_history(db: Session, quote: models.BourseLiveQuote) -> models.BourseLiveQuoteHistory:
    observed_at = _as_aware_utc(quote.updated_at) or _utcnow()
    history = models.BourseLiveQuoteHistory(
        symbol=str(quote.symbol or "").upper(),
        session_date=quote.session_date,
        observed_at=observed_at,
        quote_timestamp=quote.quote_timestamp,
        open_price=_safe_float(quote.open_price),
        last_price=_safe_float(quote.last_price),
        high_price=_safe_float(quote.high_price),
        low_price=_safe_float(quote.low_price),
        prev_close=_safe_float(quote.prev_close),
        volume=_safe_float(quote.volume),
        source_provider=quote.source_provider or SOURCE_PROVIDER,
        source_url=quote.source_url,
        raw_json=dict(quote.raw_json or {}),
    )
    db.add(history)
    return history


def get_cached_live_quotes(
    db: Session,
    symbols: list[str],
    *,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
) -> dict[str, LiveQuoteView]:
    normalized = normalize_symbols(symbols)
    if not normalized:
        return {}
    rows = (
        db.query(models.BourseLiveQuote)
        .filter(models.BourseLiveQuote.symbol.in_(normalized))
        .all()
    )
    return {
        row.symbol: quote_to_view(row, max_age_seconds=max_age_seconds)
        for row in rows
    }


def get_or_refresh_live_quotes(
    db: Session,
    symbols: list[str],
    *,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    force_refresh: bool = False,
    persist_history: bool = False,
) -> dict[str, LiveQuoteView]:
    normalized = normalize_symbols(symbols)
    if not normalized:
        return {}

    cached_rows = {
        row.symbol: row
        for row in db.query(models.BourseLiveQuote)
        .filter(models.BourseLiveQuote.symbol.in_(normalized))
        .all()
    }
    stale_symbols = [
        symbol
        for symbol in normalized
        if force_refresh or symbol not in cached_rows or not is_quote_fresh(cached_rows[symbol], max_age_seconds=max_age_seconds)
    ]

    # This compatibility helper deliberately became cache-only.  Performing an
    # exchange request while a request-scoped SQLAlchemy session is checked out
    # caused the production pool exhaustion incident.  Refreshes are exclusively
    # performed by ``services.worker.tasks.live_quotes``.
    if stale_symbols:
        enqueue_live_quote_refresh(stale_symbols)
    return {
        symbol: quote_to_view(cached_rows[symbol], max_age_seconds=max_age_seconds)
        for symbol in normalized
        if symbol in cached_rows
    }


def _redis() -> Redis:
    return Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)


def _provider_key(provider: str) -> str:
    return f"live_quotes:provider_cooldown:{provider}"


def _symbol_key(provider: str, symbol: str) -> str:
    return f"live_quotes:symbol_cooldown:{provider}:{symbol}"


def _provider_available(redis: Redis, provider: str) -> bool:
    return not bool(redis.get(_provider_key(provider)))


def _symbol_available(redis: Redis, provider: str, symbol: str) -> bool:
    return not bool(redis.get(_symbol_key(provider, symbol)))


def _open_provider_cooldown(redis: Redis, provider: str, reason: str) -> None:
    redis.setex(_provider_key(provider), PROVIDER_COOLDOWN_SECONDS, reason[:240])


def _open_symbol_cooldown(redis: Redis, provider: str, symbol: str, reason: str) -> None:
    redis.setex(_symbol_key(provider, symbol), PROVIDER_COOLDOWN_SECONDS, reason[:240])


def _provider_source_url(provider: str, symbol: str) -> str:
    if provider == BKB_PROVIDER:
        listing_id = BMCECapitalLiveAdapter.listing_id_for(symbol)
        return BKB_SOURCE_URL_TEMPLATE.format(listing_id=listing_id) if listing_id else ""
    return SOURCE_URL_TEMPLATE.format(symbol=symbol)


def _load_one(provider: str, symbol: str) -> pd.DataFrame | None:
    if provider == BKB_PROVIDER:
        adapter = BMCECapitalLiveAdapter(timezone="UTC", use_cache=False)
    else:
        adapter = BDCSessionAdapter(timezone="UTC", use_cache=False)
    market_data = adapter.load(symbols=[symbol], start=None, end=None, interval="1d")
    frame = market_data.bars.get(symbol)
    return frame if frame is not None and not frame.empty else None


def refresh_live_quotes(
    symbols: list[str],
    *,
    session_factory: Callable[[], Session],
    persist_history: bool = True,
) -> dict[str, Any]:
    """Refresh quotes in a worker without holding DB connections during HTTP.

    A provider-wide network failure opens a one-hour Redis circuit breaker. The
    next provider is attempted immediately; subsequent jobs use the fallback
    until the cooldown expires.  Empty/unmapped results are cooled down per
    symbol, so one suspended instrument cannot disable the entire provider.
    """
    normalized = normalize_symbols(symbols)
    redis = _redis()
    refreshed: list[str] = []
    failures: dict[str, str] = {}
    providers_used: dict[str, str] = {}
    try:
        for symbol in normalized:
            frame: pd.DataFrame | None = None
            selected_provider: str | None = None
            for provider in (CASABLANCA_PROVIDER, BKB_PROVIDER):
                if not _provider_available(redis, provider) or not _symbol_available(redis, provider, symbol):
                    continue
                if provider == BKB_PROVIDER and BMCECapitalLiveAdapter.listing_id_for(symbol) is None:
                    _open_symbol_cooldown(redis, provider, symbol, "no_listing_id")
                    continue
                try:
                    candidate = _load_one(provider, symbol)
                except Exception as exc:
                    _open_provider_cooldown(redis, provider, f"{type(exc).__name__}: {exc}")
                    logger.warning("Live quote provider failed; opening cooldown", extra={"provider": provider, "symbol": symbol})
                    continue
                if candidate is None:
                    # BDCSessionAdapter converts connection failures into an
                    # empty frame. Treat that as a provider failure so the
                    # next symbol does not immediately repeat the same 30s
                    # timeout. BKB's empty response can legitimately mean an
                    # untraded symbol, so that one is scoped to the symbol.
                    if provider == CASABLANCA_PROVIDER:
                        _open_provider_cooldown(redis, provider, "empty_provider_response")
                    else:
                        _open_symbol_cooldown(redis, provider, symbol, "empty_or_untraded_response")
                    continue
                frame = candidate
                selected_provider = provider
                redis.delete(_provider_key(provider))
                break

            if frame is None or selected_provider is None:
                failures[symbol] = "all_providers_unavailable_or_cooled_down"
                continue

            # Open a DB session only after external I/O has completed.
            db = session_factory()
            try:
                quote = _upsert_quote_from_frame(
                    db,
                    symbol,
                    frame,
                    provider=selected_provider,
                    source_url=_provider_source_url(selected_provider, symbol),
                )
                if quote is None:
                    db.rollback()
                    failures[symbol] = "invalid_quote_frame"
                    continue
                if persist_history:
                    _append_quote_history(db, quote)
                db.commit()
                refreshed.append(symbol)
                providers_used[symbol] = selected_provider
            except Exception as exc:
                db.rollback()
                failures[symbol] = f"persistence_failed:{type(exc).__name__}"
                logger.exception("Live quote persistence failed", extra={"symbol": symbol})
            finally:
                db.close()
    finally:
        redis.close()
    return {"requested": len(normalized), "refreshed": refreshed, "failures": failures, "providers": providers_used}


def enqueue_live_quote_refresh(symbols: list[str]) -> bool:
    """Best-effort, coalesced enqueue used by request paths; never blocks on a provider."""
    normalized = normalize_symbols(symbols)
    if not normalized:
        return False
    redis = _redis()
    try:
        lock_key = "live_quotes:refresh_enqueued"
        if not redis.set(lock_key, "1", nx=True, ex=REFRESH_LOCK_SECONDS):
            return False
        from rq import Queue

        queue_name = os.getenv("MARKET_REFRESH_QUEUE_NAME", "market_refresh")
        Queue(queue_name, connection=redis).enqueue(
            "services.worker.tasks.live_quotes.refresh_live_quotes_job",
            normalized,
            job_timeout=1800,
        )
        return True
    except Exception:
        logger.warning("Unable to enqueue live quote refresh", exc_info=True)
        return False
    finally:
        redis.close()


def effective_price_from_quote(
    *,
    official_price: float | None,
    quote: LiveQuoteView | None,
    live_if_fresh: bool = True,
) -> tuple[float | None, str]:
    if live_if_fresh and quote is not None and quote.is_fresh and quote.last_price not in (None, 0.0):
        return quote.last_price, "live"
    return official_price, "official_close"
