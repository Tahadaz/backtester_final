from __future__ import annotations

import datetime
from typing import Optional

from pydantic import BaseModel

# Reuse OHLCV response shapes from the stocks schemas — indices use the same wire format
from .market_data import (
    AvailabilityCalendarOut,
    MarketRefreshRunOut,
    OhlcvHistoryOut,
    OhlcvPreviewOut,
)

__all__ = [
    "IndexMasterCreate",
    "IndexMasterOut",
    "IndexCatalogRowOut",
    "OhlcvPreviewOut",
    "OhlcvHistoryOut",
    "AvailabilityCalendarOut",
    "MarketRefreshRunOut",
]


class IndexMasterCreate(BaseModel):
    symbol: str
    display_name: str
    family: Optional[str] = None
    source: str = "casablanca_bourse"
    notes: Optional[str] = None


class IndexMasterOut(BaseModel):
    symbol: str
    display_name: str
    family: Optional[str] = None
    is_active: bool
    source: str
    notes: Optional[str] = None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class IndexCatalogRowOut(BaseModel):
    """One row in the indices catalog table on the data page."""
    symbol: str
    display_name: Optional[str] = None
    family: Optional[str] = None
    is_active: Optional[bool] = None
    source: Optional[str] = None
    # From market_data_store
    start_ts: Optional[datetime.datetime] = None
    end_ts: Optional[datetime.datetime] = None
    row_count: Optional[int] = None
    source_provider: Optional[str] = None
    data_as_of: Optional[datetime.date] = None
    is_stale: bool = False
    is_tracked: bool = False
    has_canonical_data: bool = False
