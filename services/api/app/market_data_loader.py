"""Public data-loading utilities for market data.

Shared by market_data router, strategy_signals router, and any future consumer.
Extracted from services/api/app/routers/market_data.py (lines 81-211).
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from . import models
from .config import settings
from .storage import s3_client


# ---------------------------------------------------------------------------
# Low-level loaders
# ---------------------------------------------------------------------------

def load_close_series_from_store(*, object_key: str) -> pd.Series:
    """Load a Close series from a market_data_store parquet in S3."""
    payload = s3_client().get_object(Bucket=settings.S3_BUCKET, Key=object_key)["Body"].read()
    if not payload:
        raise ValueError(f"empty market-data object: {object_key}")

    frame = pd.read_parquet(BytesIO(payload))
    if not isinstance(frame.index, pd.DatetimeIndex):
        ts_col = None
        for candidate in ("timestamp", "Timestamp", "date", "Date", "datetime", "Datetime"):
            if candidate in frame.columns:
                ts_col = candidate
                break
        if ts_col is None:
            raise ValueError("parquet payload has no DatetimeIndex or timestamp column")
        frame[ts_col] = pd.to_datetime(frame[ts_col], errors="coerce")
        frame = frame.dropna(subset=[ts_col]).set_index(ts_col)

    close_col = None
    for candidate in ("Close", "close"):
        if candidate in frame.columns:
            close_col = candidate
            break
    if close_col is None:
        raise ValueError("parquet payload is missing Close column")

    close = pd.to_numeric(frame[close_col], errors="coerce").dropna()
    close = close.sort_index()
    close = close[~close.index.duplicated(keep="last")]
    if close.empty:
        raise ValueError("close series is empty after normalization")
    return close


def dataset_has_symbol(dataset_row: models.Dataset, symbol: str) -> bool:
    """Check whether *symbol* is present in the dataset's metadata."""
    target = str(symbol or "").strip().upper()
    if not target:
        return False

    if str(getattr(dataset_row, "symbol", "") or "").strip().upper() == target:
        return True

    meta = dataset_row.meta_json if isinstance(dataset_row.meta_json, dict) else {}
    detected = _normalize_symbols(list(meta.get("detected_symbols") or []))
    return target in set(detected)


def find_latest_dataset_for_symbol(*, db: Session, symbol: str) -> models.Dataset | None:
    """Find the most recent Dataset row containing *symbol*."""
    rows = (
        db.query(models.Dataset)
        .order_by(models.Dataset.created_at.desc())
        .limit(250)
        .all()
    )
    for row in rows:
        if dataset_has_symbol(row, symbol):
            return row
    return None


def dataset_object_key(dataset_row: models.Dataset) -> str:
    """Return the S3 object key for a dataset row."""
    object_key = str(dataset_row.object_key or "").strip()
    if object_key:
        return object_key

    filename = str(dataset_row.filename or "").strip()
    data_hash = str(dataset_row.data_hash or "").strip()
    if filename and data_hash:
        return f"datasets/{data_hash}/{filename}"
    raise ValueError("dataset row is missing object_key and (data_hash, filename)")


def load_close_series_from_dataset(*, dataset_row: models.Dataset, symbol: str) -> pd.Series:
    """Load a Close series from an uploaded dataset (Excel, CSV, or Parquet)."""
    object_key = dataset_object_key(dataset_row)
    payload = s3_client().get_object(Bucket=settings.S3_BUCKET, Key=object_key)["Body"].read()
    if not payload:
        raise ValueError(f"empty dataset object: {object_key}")

    filename = str(dataset_row.filename or "").strip()
    ext = Path(filename).suffix.lower()
    symbol_upper = str(symbol or "").strip().upper()

    if ext in {".xlsx", ".xls"}:
        with pd.ExcelFile(BytesIO(payload)) as xls:
            sheet_map = {str(name).strip().upper(): str(name) for name in xls.sheet_names}
            sheet_name = sheet_map.get(symbol_upper)
            if sheet_name is None and xls.sheet_names:
                sheet_name = str(xls.sheet_names[0])
            if not sheet_name:
                raise ValueError("dataset workbook has no sheets")
            frame = pd.read_excel(xls, sheet_name=sheet_name, engine="openpyxl")
    elif ext == ".csv":
        frame = pd.read_csv(BytesIO(payload))
    else:
        raise ValueError(f"unsupported dataset extension for technical study: {ext or '<none>'}")

    frame.columns = frame.columns.astype(str).str.strip()
    ts_col = None
    for candidate in ("Date", "date", "timestamp", "Timestamp", "datetime", "Datetime"):
        if candidate in frame.columns:
            ts_col = candidate
            break
    if ts_col is None:
        raise ValueError("dataset payload has no date/timestamp column")

    frame[ts_col] = pd.to_datetime(frame[ts_col], errors="coerce")
    frame = frame.dropna(subset=[ts_col]).set_index(ts_col)

    close_col = None
    for candidate in (
        "Close", "close", "Clôture", "Cloture", "CLOTURE",
        "ClÃ´ture", "Adj Close", "AdjClose", "adj_close",
    ):
        if candidate in frame.columns:
            close_col = candidate
            break
    if close_col is None:
        raise ValueError("dataset payload is missing Close column")

    close = pd.to_numeric(frame[close_col], errors="coerce").dropna()
    close = close.sort_index()
    close = close[~close.index.duplicated(keep="last")]
    if close.empty:
        raise ValueError("close series is empty after dataset normalization")
    return close


# ---------------------------------------------------------------------------
# High-level loader
# ---------------------------------------------------------------------------

def load_close_for_symbol(db: Session, symbol: str, timeframe: str = "1D") -> np.ndarray:
    """Load close prices for *symbol* as a numpy float64 array.

    Tries market_data_store first, then falls back to the latest dataset.
    Raises HTTPException-compatible ValueError on failure.
    """
    symbol_upper = symbol.strip().upper()
    timeframe_upper = timeframe.strip().upper()

    # Try market_data_store
    row = (
        db.query(models.MarketDataStore)
        .filter(
            models.MarketDataStore.symbol == symbol_upper,
            models.MarketDataStore.timeframe == timeframe_upper,
        )
        .first()
    )
    if row and row.object_key:
        series = load_close_series_from_store(object_key=row.object_key)
        return series.values.astype(np.float64)

    # Fallback to dataset
    ds = find_latest_dataset_for_symbol(db=db, symbol=symbol_upper)
    if ds is not None:
        series = load_close_series_from_dataset(dataset_row=ds, symbol=symbol_upper)
        return series.values.astype(np.float64)

    raise ValueError(f"No market data found for symbol {symbol_upper!r} (timeframe={timeframe_upper})")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_symbols(raw: list) -> list[str]:
    return [str(s).strip().upper() for s in raw if s]
