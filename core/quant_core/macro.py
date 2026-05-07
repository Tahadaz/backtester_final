"""Macro factor data ingestion.

Wraps YahooFinanceDataSource for macro series.

Previously used a static list of 6 series (Phase 0/1). As of Phase 2, the
canonical source is the ``macro_factor_meta`` DB table, which is seeded with
14 series and supports user-added factors.

**Backward-compat shims** — the module-level names below still work:

    MACRO_SERIES            → get_macro_series()
    MACRO_SERIES_BY_ID      → get_macro_series_by_id()
    MACRO_SERIES_BY_SYMBOL  → get_macro_series_by_symbol()

They all call get_macro_series() which reads the DB with a 60-second
in-process cache, so existing consumer code (factor_signals.py,
ingest_macro_series.py, analytics.py) requires no changes.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from .data import YahooFinanceDataSource, _standardize_ohlcv

# ---------------------------------------------------------------------------
# Spec dataclass — kept for backward compat; populated from DB rows
# ---------------------------------------------------------------------------

@dataclass
class MacroSeriesSpec:
    """Specification for one macro factor series."""
    symbol: str           # Yahoo ticker, e.g. "^VIX"
    canonical_id: str     # Storage key / display name, e.g. "VIX"
    description: str
    timezone: str = "UTC"
    close_time_utc: str = "21:00"  # typical US close
    channel_tags: list[str] = field(default_factory=list)  # ["banks", "insurance", ...]
    source: str = "yahoo"


# ---------------------------------------------------------------------------
# Fallback static list — used when DB is unavailable (e.g. Alembic env, tests)
# ---------------------------------------------------------------------------

_STATIC_FALLBACK: list[MacroSeriesSpec] = [
    MacroSeriesSpec(
        symbol="^VIX",
        canonical_id="VIX",
        description="CBOE Volatility Index — global risk appetite",
        timezone="America/New_York",
        close_time_utc="21:00",
        channel_tags=["all"],
    ),
    MacroSeriesSpec(
        symbol="^GSPC",
        canonical_id="SP500",
        description="S&P 500 — global equity risk",
        timezone="America/New_York",
        close_time_utc="21:00",
        channel_tags=["all"],
    ),
    MacroSeriesSpec(
        symbol="BZ=F",
        canonical_id="BRENT",
        description="Brent Crude futures — oil imports / materials channel",
        timezone="UTC",
        close_time_utc="22:30",
        channel_tags=["materials", "mining"],
    ),
    MacroSeriesSpec(
        symbol="DX-Y.NYB",
        canonical_id="DXY",
        description="US Dollar Index — USD strength / EM flows",
        timezone="America/New_York",
        close_time_utc="21:00",
        channel_tags=["all"],
    ),
    MacroSeriesSpec(
        symbol="EURUSD=X",
        canonical_id="EURUSD",
        description="EUR/USD — MAD peg (~60% EUR, 40% USD), first-order for MASI",
        timezone="UTC",
        close_time_utc="21:00",
        channel_tags=["all"],
    ),
    MacroSeriesSpec(
        symbol="^TNX",
        canonical_id="US10Y",
        description="10-Year US Treasury yield — global discount rate",
        timezone="America/New_York",
        close_time_utc="21:00",
        channel_tags=["banks", "insurance"],
    ),
]

# ---------------------------------------------------------------------------
# DB-backed loader with 60-second in-process cache
# ---------------------------------------------------------------------------

_cache_series: list[MacroSeriesSpec] = []
_cache_ts: float = 0.0
_CACHE_TTL = 60.0  # seconds


def _row_to_spec(row) -> MacroSeriesSpec:
    """Convert a DB row / mapping to a MacroSeriesSpec."""
    return MacroSeriesSpec(
        symbol=row["yahoo_ticker"],
        canonical_id=row["canonical_id"],
        description=row.get("display_name") or row["canonical_id"],
        # Timezone heuristic: US equity/bond markets close at 21:00 UTC;
        # everything else is UTC. Users can override via DB notes if needed.
        timezone=(
            "America/New_York"
            if row.get("asset_type") in ("equity", "bond") and row.get("market_region") == "us"
            else "UTC"
        ),
        close_time_utc="21:00",
        channel_tags=["all"],
        source="yahoo",
    )


def get_macro_series(force_refresh: bool = False) -> list[MacroSeriesSpec]:
    """Return all active macro factor specs, reading from DB with 60s cache.

    Falls back to _STATIC_FALLBACK if the DB is unavailable (e.g. during
    Alembic env setup or unit tests without a live DB).
    """
    global _cache_series, _cache_ts
    now = time.monotonic()
    if not force_refresh and _cache_series and (now - _cache_ts) < _CACHE_TTL:
        return _cache_series

    try:
        # Import here to avoid circular-import at module load time
        from sqlalchemy import text as _text

        # Try to get a DB session from the API layer first, then the worker layer
        try:
            from services.api.app.db import _ensure_session_factory
            Session = _ensure_session_factory()
        except Exception:
            try:
                from services.worker.db import SessionLocal as Session  # type: ignore[assignment]
            except Exception:
                raise RuntimeError("No DB session available")

        db = Session()
        try:
            rows = db.execute(
                _text(
                    "SELECT canonical_id, yahoo_ticker, display_name, asset_type, market_region "
                    "FROM macro_factor_meta WHERE active = true ORDER BY canonical_id"
                )
            ).mappings().all()
            series = [_row_to_spec(r) for r in rows]
        finally:
            db.close()

        if not series:
            # Table exists but is empty — should not happen after migration seed
            series = _STATIC_FALLBACK

        _cache_series = series
        _cache_ts = now
        return series

    except Exception:
        # DB unavailable: return static fallback without poisoning the cache
        return _STATIC_FALLBACK if not _cache_series else _cache_series


def get_macro_series_by_id() -> dict[str, MacroSeriesSpec]:
    """Return {canonical_id: MacroSeriesSpec} for all active series."""
    return {s.canonical_id: s for s in get_macro_series()}


def get_macro_series_by_symbol() -> dict[str, MacroSeriesSpec]:
    """Return {yahoo_ticker: MacroSeriesSpec} for all active series."""
    return {s.symbol: s for s in get_macro_series()}


# ---------------------------------------------------------------------------
# Backward-compatible module-level names
# (existing imports of MACRO_SERIES, MACRO_SERIES_BY_ID, MACRO_SERIES_BY_SYMBOL
#  will get a live dict/list on first access via __getattr__ — but since most
#  consumers reference them at function-call time, we also expose direct aliases)
# ---------------------------------------------------------------------------

# These resolve at import time to the static fallback; once the DB is warm the
# cache kicks in for subsequent calls.  For truly dynamic behaviour, consumers
# should call get_macro_series_by_id() / get_macro_series_by_symbol() directly.

def __getattr__(name: str):
    if name == "MACRO_SERIES":
        return get_macro_series()
    if name == "MACRO_SERIES_BY_ID":
        return get_macro_series_by_id()
    if name == "MACRO_SERIES_BY_SYMBOL":
        return get_macro_series_by_symbol()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------------------------------------------------------------------------
# Fetch helpers (unchanged public API)
# ---------------------------------------------------------------------------

def fetch_macro_series(
    spec: MacroSeriesSpec,
    start: str,
    end: Optional[str] = None,
    interval: str = "1d",
) -> pd.DataFrame:
    """Fetch one macro series via YahooFinanceDataSource.

    Returns a standardized OHLCV DataFrame with canonical columns:
        Open, High, Low, Close, Volume — indexed by tz-aware DatetimeIndex.

    Args:
        spec: MacroSeriesSpec defining the Yahoo ticker and metadata.
        start: ISO date string e.g. "2010-01-01".
        end: ISO date string (None = today).
        interval: yfinance interval string (default "1d").
    """
    source = YahooFinanceDataSource(timezone=spec.timezone)
    md = source.load(
        symbols=[spec.symbol],
        start=start,
        end=end,
        interval=interval,
    )
    df = md.bars.get(spec.symbol)
    if df is None or df.empty:
        raise ValueError(f"No data returned for {spec.symbol}")

    return _standardize_ohlcv(df, tz=spec.timezone)


def fetch_all_macro_series(
    start: str,
    end: Optional[str] = None,
    interval: str = "1d",
    series: Optional[list[MacroSeriesSpec]] = None,
) -> dict[str, pd.DataFrame]:
    """Fetch all macro series (or a subset).

    Returns dict[canonical_id -> DataFrame].
    """
    if series is None:
        series = get_macro_series()

    results: dict[str, pd.DataFrame] = {}
    for spec in series:
        try:
            results[spec.canonical_id] = fetch_macro_series(spec, start=start, end=end, interval=interval)
        except Exception as exc:
            import warnings
            warnings.warn(f"Failed to fetch {spec.symbol} ({spec.canonical_id}): {exc}", stacklevel=2)

    return results
