from __future__ import annotations

import datetime as dt
import logging
import math
from dataclasses import dataclass
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from core.quant_core.data import BDCSessionAdapter

from .. import models


DEFAULT_MAX_AGE_SECONDS = 60
SOURCE_PROVIDER = "casablanca_bourse_live"
SOURCE_URL_TEMPLATE = "https://www.casablanca-bourse.com/fr/live-market/instruments/{symbol}?pwa=1"
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


def _upsert_quote_from_frame(db: Session, symbol: str, frame: pd.DataFrame) -> models.BourseLiveQuote | None:
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
    quote.source_provider = SOURCE_PROVIDER
    quote.source_url = SOURCE_URL_TEMPLATE.format(symbol=symbol)
    quote.raw_json = {
        "source": "BDCSessionAdapter",
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

    if stale_symbols:
        adapter = BDCSessionAdapter(timezone="UTC", use_cache=False)
        for symbol in stale_symbols:
            try:
                market_data = adapter.load(symbols=[symbol], start=None, end=None, interval="1d")
                frame = market_data.bars.get(symbol)
                quote = _upsert_quote_from_frame(db, symbol, frame) if frame is not None else None
                if quote is not None:
                    if persist_history:
                        _append_quote_history(db, quote)
                    db.commit()
                    db.refresh(quote)
                    cached_rows[symbol] = quote
            except Exception:
                logger.debug("Bourse live quote scrape failed", extra={"symbol": symbol}, exc_info=True)
                db.rollback()

    return {
        symbol: quote_to_view(cached_rows[symbol], max_age_seconds=max_age_seconds)
        for symbol in normalized
        if symbol in cached_rows
    }


def effective_price_from_quote(
    *,
    official_price: float | None,
    quote: LiveQuoteView | None,
    live_if_fresh: bool = True,
) -> tuple[float | None, str]:
    if live_if_fresh and quote is not None and quote.is_fresh and quote.last_price not in (None, 0.0):
        return quote.last_price, "live"
    return official_price, "official_close"
