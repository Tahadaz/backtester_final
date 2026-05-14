"""Shared market-universe helpers for catalog, dashboard, and compute batches."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from ..asset_taxonomy import detect_asset_type
from ..masi_tickers import get_masi_info, is_masi_ticker

DATA_PAGE_EXCLUDED_STOCKS = {"MAJ", "MAJJ", "WORKSHEET", "INSTRUMENT"}


@dataclass(frozen=True)
class MarketUniverseInstrument:
    symbol: str
    display_name: str | None
    isin: str | None
    sector: str | None
    is_active: bool | None
    track_source: str | None
    bourse_url: str | None
    shares_outstanding: int | None
    shares_as_of: dt.date | None
    shares_source: str | None
    shares_updated_at: dt.datetime | None
    notes: str | None
    asset_type: str
    market_region: str | None
    asset_class: str
    start_ts: Any = None
    end_ts: Any = None
    row_count: int | None = None
    source_provider: str | None = None
    data_as_of: dt.date | None = None
    is_tracked: bool = False
    has_canonical_data: bool = False
    market: str = "other"
    is_stale: bool = False


def _has_table(db: Session, table_name: str) -> bool:
    try:
        return inspect(db.get_bind()).has_table(table_name)
    except Exception:
        return False


def _normalize_stock_identity(value: str | None) -> str:
    return "".join(ch for ch in str(value or "").strip().upper() if ch.isalnum())


def is_data_page_excluded_stock(*, symbol: str | None = None, display_name: str | None = None) -> bool:
    normalized_symbol = _normalize_stock_identity(symbol)
    normalized_name = _normalize_stock_identity(display_name)
    return (
        normalized_symbol in DATA_PAGE_EXCLUDED_STOCKS
        or normalized_name in DATA_PAGE_EXCLUDED_STOCKS
    )


def _today_utc() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def _business_days_ago(d: dt.date, n: int) -> dt.date:
    count = 0
    current = d
    while count < n:
        current -= dt.timedelta(days=1)
        if current.weekday() < 5:
            count += 1
    return current


def is_stale_data_as_of(data_as_of: dt.date | None) -> bool:
    if data_as_of is None:
        return True
    return data_as_of < _business_days_ago(_today_utc(), 2)


def _ensure_optional_catalog_tables(db: Session) -> None:
    if not _has_table(db, "index_master"):
        db.execute(
            text(
                """
                CREATE TEMPORARY TABLE IF NOT EXISTS index_master (
                    symbol TEXT,
                    display_name TEXT,
                    market_region TEXT
                )
                """
            )
        )
    if not _has_table(db, "macro_factor_meta"):
        db.execute(
            text(
                """
                CREATE TEMPORARY TABLE IF NOT EXISTS macro_factor_meta (
                    canonical_id TEXT,
                    display_name TEXT,
                    notes TEXT,
                    asset_type TEXT,
                    market_region TEXT,
                    active BOOLEAN
                )
                """
            )
        )


def list_market_catalog(
    db: Session,
    *,
    include_without_data: bool = True,
) -> list[MarketUniverseInstrument]:
    """Return the same canonical market universe used by the Data page.

    When ``include_without_data`` is false, only instruments with canonical 1D
    data in ``market_data_store`` are returned. This is the universe used by
    dashboard Complete mode and by full Signal Engine/WFO batch fan-out.
    """
    _ensure_optional_catalog_tables(db)
    rows = db.execute(
        text(
            """
            SELECT
                mds.symbol,
                sm.display_name,
                sm.isin,
                sm.sector,
                sm.is_active,
                sm.track_source,
                sm.bourse_url,
                sm.shares_outstanding,
                sm.shares_as_of,
                sm.shares_source,
                sm.shares_updated_at,
                sm.notes,
                COALESCE(sm.asset_type, 'equity') AS asset_type,
                sm.market_region,
                mds.start_ts,
                mds.end_ts,
                mds.row_count,
                mds.source_provider,
                mds.data_as_of,
                (sm.symbol IS NOT NULL) AS is_tracked,
                TRUE AS has_canonical_data,
                COALESCE(mds.asset_class, 'equity') AS asset_class
            FROM market_data_store mds
            LEFT JOIN stock_master sm ON sm.symbol = mds.symbol
            WHERE lower(mds.timeframe) = '1d'
              AND COALESCE(mds.asset_class, 'equity') NOT IN ('index', 'factor')

            UNION ALL

            SELECT
                sm.symbol,
                sm.display_name,
                sm.isin,
                sm.sector,
                sm.is_active,
                sm.track_source,
                sm.bourse_url,
                sm.shares_outstanding,
                sm.shares_as_of,
                sm.shares_source,
                sm.shares_updated_at,
                sm.notes,
                COALESCE(sm.asset_type, 'equity') AS asset_type,
                sm.market_region,
                NULL AS start_ts,
                NULL AS end_ts,
                NULL AS row_count,
                NULL AS source_provider,
                NULL AS data_as_of,
                TRUE AS is_tracked,
                FALSE AS has_canonical_data,
                'equity' AS asset_class
            FROM stock_master sm
            WHERE NOT EXISTS (
                SELECT 1 FROM market_data_store mds2
                WHERE mds2.symbol = sm.symbol AND lower(mds2.timeframe) = '1d'
            )

            UNION ALL

            SELECT
                mds.symbol,
                COALESCE(im.display_name, mds.symbol) AS display_name,
                NULL AS isin,
                NULL AS sector,
                TRUE AS is_active,
                'casablanca_bourse' AS track_source,
                NULL AS bourse_url,
                NULL AS shares_outstanding,
                NULL AS shares_as_of,
                NULL AS shares_source,
                NULL AS shares_updated_at,
                NULL AS notes,
                'equity' AS asset_type,
                COALESCE(im.market_region, 'masi') AS market_region,
                mds.start_ts,
                mds.end_ts,
                mds.row_count,
                mds.source_provider,
                mds.data_as_of,
                TRUE AS is_tracked,
                TRUE AS has_canonical_data,
                'index' AS asset_class
            FROM market_data_store mds
            LEFT JOIN index_master im ON im.symbol = mds.symbol
            WHERE lower(mds.timeframe) = '1d'
              AND mds.asset_class = 'index'

            UNION ALL

            SELECT
                mds.symbol,
                COALESCE(mfm.display_name, mds.symbol) AS display_name,
                NULL AS isin,
                NULL AS sector,
                TRUE AS is_active,
                'yahoo' AS track_source,
                NULL AS bourse_url,
                NULL AS shares_outstanding,
                NULL AS shares_as_of,
                NULL AS shares_source,
                NULL AS shares_updated_at,
                mfm.notes AS notes,
                mfm.asset_type,
                mfm.market_region,
                mds.start_ts,
                mds.end_ts,
                mds.row_count,
                'yahoo' AS source_provider,
                mds.data_as_of,
                TRUE AS is_tracked,
                TRUE AS has_canonical_data,
                'factor' AS asset_class
            FROM market_data_store mds
            JOIN macro_factor_meta mfm ON mfm.canonical_id = mds.symbol
            WHERE lower(mds.timeframe) = '1d'
              AND mds.asset_class = 'factor'
              AND mfm.active = true

            UNION ALL

            SELECT
                mfm.canonical_id AS symbol,
                mfm.display_name,
                NULL AS isin,
                NULL AS sector,
                TRUE AS is_active,
                'yahoo' AS track_source,
                NULL AS bourse_url,
                NULL AS shares_outstanding,
                NULL AS shares_as_of,
                NULL AS shares_source,
                NULL AS shares_updated_at,
                mfm.notes,
                mfm.asset_type,
                mfm.market_region,
                NULL AS start_ts,
                NULL AS end_ts,
                NULL AS row_count,
                'yahoo' AS source_provider,
                NULL AS data_as_of,
                TRUE AS is_tracked,
                FALSE AS has_canonical_data,
                'factor' AS asset_class
            FROM macro_factor_meta mfm
            WHERE mfm.active = true
              AND NOT EXISTS (
                SELECT 1 FROM market_data_store mds2
                WHERE mds2.symbol = mfm.canonical_id AND lower(mds2.timeframe) = '1d'
              )

            ORDER BY symbol ASC
            """
        )
    ).mappings().all()

    result: list[MarketUniverseInstrument] = []
    for row in rows:
        symbol = str(row["symbol"] or "").strip().upper()
        if not symbol:
            continue
        display_name = row["display_name"]
        if is_data_page_excluded_stock(symbol=symbol, display_name=display_name):
            continue
        has_canonical_data = bool(row["has_canonical_data"])
        if not include_without_data and not has_canonical_data:
            continue

        data_as_of = row["data_as_of"]
        if isinstance(data_as_of, dt.datetime):
            data_as_of = data_as_of.date()
        masi_info = get_masi_info(symbol)
        if masi_info and (not display_name or str(display_name).strip().upper() == symbol):
            display_name = masi_info.get("display_name")
        sector = row["sector"] or (masi_info.get("sector") if masi_info else None)

        asset_type = row["asset_type"] or None
        market_region = row["market_region"]
        if asset_type is None:
            asset_type, market_region = detect_asset_type(
                symbol,
                track_source=row["track_source"],
                is_masi=is_masi_ticker(symbol),
            )
        elif market_region is None and is_masi_ticker(symbol):
            market_region = "masi"

        if market_region == "masi":
            market = "masi"
        elif asset_type == "equity":
            market = "other"
        else:
            market = str(asset_type)

        result.append(
            MarketUniverseInstrument(
                symbol=symbol,
                display_name=display_name,
                isin=row["isin"],
                sector=sector,
                is_active=bool(row["is_active"]) if row["is_active"] is not None else True,
                track_source=row["track_source"],
                bourse_url=row["bourse_url"],
                shares_outstanding=row["shares_outstanding"],
                shares_as_of=row["shares_as_of"],
                shares_source=row["shares_source"],
                shares_updated_at=row["shares_updated_at"],
                notes=row["notes"],
                asset_type=str(asset_type or "equity"),
                market_region=market_region,
                asset_class=str(row["asset_class"] or "equity"),
                start_ts=row["start_ts"],
                end_ts=row["end_ts"],
                row_count=row["row_count"],
                source_provider=row["source_provider"],
                data_as_of=data_as_of,
                is_tracked=bool(row["is_tracked"]),
                has_canonical_data=has_canonical_data,
                market=market,
                is_stale=is_stale_data_as_of(data_as_of),
            )
        )
    return result


def list_signal_universe(db: Session) -> list[MarketUniverseInstrument]:
    return list_market_catalog(db, include_without_data=False)


def list_signal_universe_symbols(db: Session) -> list[str]:
    return [row.symbol for row in list_signal_universe(db)]


def dashboard_group_label(row: MarketUniverseInstrument) -> str:
    if row.sector:
        return row.sector
    if row.asset_class == "index":
        return "Index"
    asset_type = (row.asset_type or "equity").strip().lower()
    market_region = (row.market_region or "").strip().lower()
    if asset_type == "equity":
        if market_region == "us":
            return "US Equity"
        if market_region == "european":
            return "European Equity"
        if market_region == "asian":
            return "Asian Equity"
        if market_region == "masi":
            return "MASI Equity"
        return "Other Equity"
    return {
        "commodity": "Commodity",
        "forex": "Forex",
        "bond": "Bond",
        "crypto": "Crypto",
    }.get(asset_type, asset_type.title() if asset_type else "Other")


def is_masi_dashboard_member(row: MarketUniverseInstrument | dict[str, Any]) -> bool:
    if isinstance(row, dict):
        asset_type = row.get("asset_type") or "equity"
        market_region = row.get("market_region")
        asset_class = row.get("asset_class") or "equity"
    else:
        asset_type = row.asset_type or "equity"
        market_region = row.market_region
        asset_class = row.asset_class or "equity"
    return asset_class == "equity" and asset_type == "equity" and market_region == "masi"
