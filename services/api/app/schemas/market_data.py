from __future__ import annotations

import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Stock Master ─────────────────────────────────────────────────────────────

class StockMasterCreate(BaseModel):
    symbol: str
    display_name: Optional[str] = None
    isin: Optional[str] = None
    sector: Optional[str] = None
    market_cap_class: Optional[str] = None
    track_source: str = "bourse_direct"
    bourse_url: Optional[str] = None
    notes: Optional[str] = None


class StockMasterUpdate(BaseModel):
    isin: Optional[str] = None
    sector: Optional[str] = None
    market_cap_class: Optional[str] = None
    is_active: Optional[bool] = None
    track_source: Optional[str] = None
    bourse_url: Optional[str] = None
    notes: Optional[str] = None


class StockMasterOut(BaseModel):
    symbol: str
    display_name: Optional[str] = None
    isin: Optional[str] = None
    sector: Optional[str] = None
    market_cap_class: Optional[str] = None
    is_active: bool
    track_source: str
    bourse_url: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime.datetime] = None
    updated_at: Optional[datetime.datetime] = None
    # Freshness fields (joined from market_data_store)
    start_ts: Optional[datetime.datetime] = None
    end_ts: Optional[datetime.datetime] = None
    row_count: Optional[int] = None
    store_updated_at: Optional[datetime.datetime] = None
    source_provider: Optional[str] = None
    data_as_of: Optional[datetime.date] = None
    is_stale: bool = False

    class Config:
        from_attributes = True


class BourseStockLookupOut(BaseModel):
    symbol: str
    bourse_url: str
    display_name: Optional[str] = None
    sector: Optional[str] = None
    isin: Optional[str] = None
    found: bool = True


# ── Provider Symbol Map ──────────────────────────────────────────────────────

class ProviderSymbolMapOut(BaseModel):
    id: int
    symbol: str
    provider: str
    provider_symbol: str
    confidence: float
    is_verified: bool
    override_reason: Optional[str] = None
    created_at: Optional[datetime.datetime] = None

    class Config:
        from_attributes = True


class ProviderSymbolMapUpdate(BaseModel):
    provider_symbol: str
    is_verified: bool = True
    override_reason: Optional[str] = None


# ── Market Refresh Run ───────────────────────────────────────────────────────

class MarketRefreshTriggerRequest(BaseModel):
    timeframe: str = Field(default="1D")
    source_override: Optional[str] = None
    include_unverified: bool = False


class MarketRefreshRunOut(BaseModel):
    id: UUID
    trigger_source: str
    scope: str
    symbol: Optional[str] = None
    timeframe: str
    status: str
    rq_job_id: Optional[str] = None
    symbols_total: Optional[int] = None
    symbols_done: Optional[int] = None
    symbols_failed: Optional[int] = None
    started_at: Optional[datetime.datetime] = None
    finished_at: Optional[datetime.datetime] = None
    created_at: datetime.datetime
    error_message: Optional[str] = None
    meta_json: dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


# ── Market Health ─────────────────────────────────────────────────────────────

class MarketHealthOut(BaseModel):
    total_tracked: int
    up_to_date: int
    stale: int
    very_stale: int
    never_ingested: int
    last_refresh_run: Optional[MarketRefreshRunOut] = None
    last_successful_refresh: Optional[datetime.datetime] = None


# ── Market Catalog (unified /data-page view) ──────────────────────────────────

class MarketCatalogRowOut(BaseModel):
    """
    One row per symbol in the canonical market universe.
    Combines market_data_store (canonical data) with stock_master (registry metadata).
    Arm 1: all symbols with data in market_data_store (even if not tracked).
    Arm 2: tracked symbols in stock_master with no data yet.
    """
    symbol: str
    # From stock_master (null when symbol is in market_data_store but not in stock_master)
    display_name: Optional[str] = None
    isin: Optional[str] = None
    sector: Optional[str] = None
    is_active: Optional[bool] = None
    track_source: Optional[str] = None
    bourse_url: Optional[str] = None
    notes: Optional[str] = None
    # From market_data_store (null when tracked but not yet ingested)
    start_ts: Optional[datetime.datetime] = None
    end_ts: Optional[datetime.datetime] = None
    row_count: Optional[int] = None
    source_provider: Optional[str] = None
    data_as_of: Optional[datetime.date] = None
    is_stale: bool = False
    # Derived flags
    is_tracked: bool = False
    has_canonical_data: bool = False
    market: str = "masi"          # kept for backward compat; derived from asset_type/market_region
    asset_type: str = "equity"    # "equity" | "commodity" | "forex" | "bond" | "crypto"
    market_region: Optional[str] = None  # "masi" | "us" | "european" | "asian" | null
    asset_class: str = "equity"   # "equity" | "index" | "factor"


class AssetCategoryPatchIn(BaseModel):
    asset_type: str    # "equity" | "commodity" | "forex" | "bond" | "crypto"
    market_region: Optional[str] = None  # "masi" | "us" | "european" | "asian" | null


# ── OHLCV Preview ─────────────────────────────────────────────────────────────

class OhlcvBarOut(BaseModel):
    date: str
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None


class OhlcvPreviewOut(BaseModel):
    symbol: str
    timeframe: str
    bars: list[OhlcvBarOut]
    source_provider: Optional[str] = None
    data_as_of: Optional[datetime.date] = None
    row_count: Optional[int] = None


class UploadFormatFieldAliasOut(BaseModel):
    input_column: str
    matched_alias: str


class UploadFormatDefinitionOut(BaseModel):
    format_id: str
    label: str
    aliases: dict[str, list[str]]
    numeric_examples: list[str]
    volume_suffixes: list[str]
    notes: list[str] = Field(default_factory=list)


class UploadValidationSummaryOut(BaseModel):
    required_fields: list[str]
    note: str


class UploadFormatReferenceOut(BaseModel):
    canonical_fields: list[str]
    formats: list[UploadFormatDefinitionOut]
    validation: UploadValidationSummaryOut


class OhlcvHistoryOut(BaseModel):
    symbol: str
    timeframe: str
    bars: list[OhlcvBarOut]
    source_provider: Optional[str] = None
    data_as_of: Optional[datetime.date] = None
    row_count: Optional[int] = None


class AvailabilityCalendarDayOut(BaseModel):
    date: str
    state: str
    has_data: bool = False
    holiday_name: Optional[str] = None
    holiday_certainty: Optional[str] = None
    missing_fields: list[str] = Field(default_factory=list)


# ── OHLCV Row Mutations ──────────────────────────────────────────────────────

class OhlcvRowUpsert(BaseModel):
    """Upsert a single OHLCV row. Only non-None fields are written."""
    date: str = Field(..., description="ISO date YYYY-MM-DD")
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None


class OhlcvRowDeleteRequest(BaseModel):
    """Delete one or more rows by date."""
    dates: list[str] = Field(..., description="List of ISO dates YYYY-MM-DD")


class OhlcvMutationResult(BaseModel):
    symbol: str
    timeframe: str
    action: str  # "upserted" | "deleted"
    affected_dates: list[str]
    new_row_count: int


class AvailabilityCalendarOut(BaseModel):
    symbol: str
    timeframe: str
    first_date: Optional[str] = None
    last_date: Optional[str] = None
    default_month: Optional[str] = None
    days: list[AvailabilityCalendarDayOut]
    present_days: int = 0
    missing_expected_days: int = 0
    weekend_days: int = 0
    market_holiday_days: int = 0
    tentative_market_holiday_days: int = 0
    no_trading_days: int = 0
    partial_days: int = 0
