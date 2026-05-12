from __future__ import annotations

import datetime
import json
from io import BytesIO
from pathlib import Path
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Query
from fastapi.responses import StreamingResponse
import pandas as pd
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text

from .. import models
from ..config import settings
from ..db import get_db
from ..market_data_formats import build_upload_format_reference
from ..market_refresh_window import (
    BOURSE_REFRESH_CUTOFF_LABEL,
    needs_bourse_refresh,
    is_before_bourse_refresh_cutoff,
    is_bourse_source,
)
from ..market_holidays import get_holiday_info
from ..masi_tickers import is_masi_ticker, get_masi_info, all_masi_tickers
from ..asset_taxonomy import detect_asset_type as _detect_asset_type
from ..queue import get_queue, get_market_refresh_queue
from ..services.market_universe import list_market_catalog
from ..storage import delete_object, put_bytes, presign_get, s3_client
from ..schemas.market_data import (
    AvailabilityCalendarDayOut,
    AvailabilityCalendarOut,
    BourseStockLookupOut,
    AssetCategoryPatchIn,
    MarketCatalogRowOut,
    MarketHealthOut,
    OhlcvBarOut,
    OhlcvHistoryOut,
    OhlcvMutationResult,
    OhlcvPreviewOut,
    OhlcvRowDeleteRequest,
    OhlcvRowUpsert,
    MarketRefreshTriggerRequest,
    MarketRefreshRunOut,
    ProviderSymbolMapOut,
    ProviderSymbolMapUpdate,
    StockMasterCreate,
    StockMasterOut,
    StockMasterUpdate,
    UploadFormatReferenceOut,
)

router = APIRouter(prefix="/market-data", tags=["market-data"])
_DEFAULT_SMA_WINDOWS = [5, 10, 14, 20, 30, 50, 100, 200]
_DATA_PAGE_EXCLUDED_STOCKS = {"MAJ", "MAJJ","WORKSHEET","INSTRUMENT"}


class SmaTechnicalStudyRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list, min_length=1)
    windows: list[int] = Field(default_factory=lambda: list(_DEFAULT_SMA_WINDOWS), min_length=1)
    timeframe: str = Field(default="1D", min_length=1)


def _signal_label(value: int) -> str:
    if value > 0:
        return "BUY"
    if value < 0:
        return "SELL"
    return "HOLD"


def _normalize_symbols(raw_symbols: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in list(raw_symbols or []):
        sym = str(item or "").strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return out


def _has_table(db: Session, table_name: str) -> bool:
    try:
        return inspect(db.get_bind()).has_table(table_name)
    except Exception:
        return False


def _next_sqlite_provider_map_id(db: Session) -> int | None:
    try:
        bind = db.get_bind()
        if bind.dialect.name != "sqlite":
            return None
        value = db.execute(text("SELECT COALESCE(MAX(id), 0) + 1 FROM provider_symbol_map")).scalar()
        return int(value or 1)
    except Exception:
        return None


def _normalize_windows(raw_windows: list[int]) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for item in list(raw_windows or []):
        try:
            w = int(item)
        except Exception:
            continue
        if w <= 0 or w in seen:
            continue
        seen.add(w)
        out.append(w)
    return sorted(out)


def _normalize_stock_identity(value: str | None) -> str:
    return "".join(ch for ch in str(value or "").strip().upper() if ch.isalnum())


def _is_data_page_excluded_stock(*, symbol: str | None = None, display_name: str | None = None) -> bool:
    normalized_symbol = _normalize_stock_identity(symbol)
    normalized_name = _normalize_stock_identity(display_name)
    return (
        normalized_symbol in _DATA_PAGE_EXCLUDED_STOCKS
        or normalized_name in _DATA_PAGE_EXCLUDED_STOCKS
    )


# Data-loading helpers — delegated to market_data_loader (shared public module)
from ..market_data_loader import (
    load_modify_save_ohlcv,
    load_ohlcv_for_symbol,
    load_close_series_from_store as _load_close_series_from_store,
    dataset_has_symbol as _dataset_has_symbol,
    find_latest_dataset_for_symbol as _find_latest_dataset_for_symbol,
    dataset_object_key as _dataset_object_key,
    load_close_series_from_dataset as _load_close_series_from_dataset,
)


@router.post("/technical-study/sma")
def sma_technical_study(
    payload: SmaTechnicalStudyRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    symbols = _normalize_symbols(payload.symbols)
    if not symbols:
        raise HTTPException(status_code=400, detail="symbols must include at least one valid symbol")

    windows = _normalize_windows(payload.windows)
    if not windows:
        raise HTTPException(status_code=400, detail="windows must include at least one positive integer")

    timeframe = str(payload.timeframe or "1D").strip().upper()
    if not timeframe:
        timeframe = "1D"

    results: list[dict[str, Any]] = []
    for symbol in symbols:
        try:
            close: pd.Series | None = None
            data_source = "market_data_store"
            store_row = (
                db.query(models.MarketDataStore)
                .filter(models.MarketDataStore.symbol == symbol)
                .filter(models.MarketDataStore.timeframe == timeframe)
                .one_or_none()
            )
            if store_row is not None:
                close = _load_close_series_from_store(object_key=str(store_row.object_key))
            elif timeframe == "1D":
                dataset_row = _find_latest_dataset_for_symbol(db=db, symbol=symbol)
                if dataset_row is not None:
                    close = _load_close_series_from_dataset(dataset_row=dataset_row, symbol=symbol)
                    data_source = "uploaded_dataset"

            if close is None:
                results.append(
                    {
                        "symbol": symbol,
                        "status": "error",
                        "error": f"symbol not found in market_data_store for timeframe={timeframe}",
                        "timeframe": timeframe,
                        "windows": windows,
                        "as_of": None,
                        "latest_close": None,
                        "consensus_signal": "HOLD",
                        "consensus_value": 0,
                        "score_pct": 0.0,
                        "agreement_count": 0,
                        "directional_windows": 0,
                        "buy_count": 0,
                        "sell_count": 0,
                        "hold_count": len(windows),
                        "skipped_windows": len(windows),
                        "variations": [],
                    }
                )
                continue

            latest_close = float(close.iloc[-1])
            as_of = close.index[-1]
            as_of_iso = as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of)

            variations: list[dict[str, Any]] = []
            buy_count = 0
            sell_count = 0
            hold_count = 0
            skipped_windows = 0

            for window in windows:
                sma_series = close.rolling(window=window, min_periods=window).mean()
                sma_latest = sma_series.iloc[-1] if len(sma_series) > 0 else None

                if sma_latest is None or pd.isna(sma_latest):
                    signal = 0
                    hold_count += 1
                    skipped_windows += 1
                    variations.append(
                        {
                            "window": int(window),
                            "sma_value": None,
                            "close_value": latest_close,
                            "signal_value": signal,
                            "signal": _signal_label(signal),
                            "sufficient_data": False,
                        }
                    )
                    continue

                sma_value = float(sma_latest)
                if latest_close > sma_value:
                    signal = 1
                    buy_count += 1
                elif latest_close < sma_value:
                    signal = -1
                    sell_count += 1
                else:
                    signal = 0
                    hold_count += 1

                variations.append(
                    {
                        "window": int(window),
                        "sma_value": sma_value,
                        "close_value": latest_close,
                        "signal_value": signal,
                        "signal": _signal_label(signal),
                        "sufficient_data": True,
                    }
                )

            directional_windows = buy_count + sell_count
            agreement_count = max(buy_count, sell_count)
            if directional_windows == 0:
                consensus_value = 0
            elif buy_count > sell_count:
                consensus_value = 1
            elif sell_count > buy_count:
                consensus_value = -1
            else:
                consensus_value = 0

            score_pct = (
                (agreement_count / directional_windows) * 100.0
                if directional_windows > 0
                else 0.0
            )

            results.append(
                {
                    "symbol": symbol,
                    "status": "ok",
                    "error": None,
                    "data_source": data_source,
                    "timeframe": timeframe,
                    "windows": windows,
                    "as_of": as_of_iso,
                    "latest_close": latest_close,
                    "consensus_signal": _signal_label(consensus_value),
                    "consensus_value": consensus_value,
                    "score_pct": score_pct,
                    "agreement_count": agreement_count,
                    "directional_windows": directional_windows,
                    "buy_count": buy_count,
                    "sell_count": sell_count,
                    "hold_count": hold_count,
                    "skipped_windows": skipped_windows,
                    "variations": variations,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "symbol": symbol,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "timeframe": timeframe,
                    "windows": windows,
                    "as_of": None,
                    "latest_close": None,
                    "consensus_signal": "HOLD",
                    "consensus_value": 0,
                    "score_pct": 0.0,
                    "agreement_count": 0,
                    "directional_windows": 0,
                    "buy_count": 0,
                    "sell_count": 0,
                    "hold_count": len(windows),
                    "skipped_windows": len(windows),
                    "variations": [],
                }
            )

    return {
        "strategy_kind": "sma_price",
        "timeframe": timeframe,
        "windows": windows,
        "score_basis": "agreement_count / directional_windows, where directional windows are BUY or SELL",
        "results": results,
    }


@router.post("/excel")
def upload_excel_and_ingest(
    file: UploadFile = File(...),
    metadata_json: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > settings.DATASET_MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large")

    filename = Path(file.filename or "upload.xlsx").name
    ext = Path(filename).suffix.lower()
    if ext not in {".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail="Only .xlsx/.xls supported for market-data ingestion")

    content_type = file.content_type or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    # Reuse your existing dataset storage pattern: datasets/{sha}/{filename}
    import hashlib
    digest = hashlib.sha256(data).hexdigest()
    object_key = f"datasets/{digest}/{filename}"

    # Store raw upload (preserve forever)
    put_bytes(object_key=object_key, data=data, content_type=content_type)

    # Detect symbols from sheet names, filtering out generic names
    _GENERIC_SHEETS = {"FEUIL1", "FEUIL2", "FEUIL3", "SHEET1", "SHEET2", "SHEET3", "DONNÉES", "DATA"}
    try:
        with pd.ExcelFile(BytesIO(data)) as xls:
            raw_sheets = xls.sheet_names
        detected_symbols = [
            s.strip().upper()
            for s in raw_sheets
            if s.strip() and s.strip().upper() not in _GENERIC_SHEETS
        ]
    except Exception:
        raw_sheets = []
        detected_symbols = []

    meta: dict[str, Any] = {
        "filename": filename,
        "content_type": content_type,
        "size_bytes": len(data),
        "sheet_names": raw_sheets,
        "detected_symbols": detected_symbols,
    }
    if metadata_json:
        try:
            parsed = json.loads(metadata_json)
            if isinstance(parsed, dict):
                meta.update(parsed)
        except Exception:
            raise HTTPException(status_code=400, detail="metadata_json must be valid JSON object")

    # Create Dataset row (source uploaded_file, symbol=filename like your existing endpoint)
    ds = models.Dataset(
        source="uploaded_file",
        symbol=filename,
        timeframe="1D",
        data_hash=digest,
        filename=filename,
        content_type=content_type,
        object_key=object_key,
        size_bytes=len(data),
        meta_json=meta,
    )
    db.add(ds)
    db.commit()
    db.refresh(ds)

    # Enqueue ingestion worker task
    q = get_queue()
    job = q.enqueue("services.worker.tasks.ingest_market_data.ingest_excel_to_store", str(ds.id))

    return {
        "dataset_id": str(ds.id),
        "job_id": job.id,
        "raw_object_key": object_key,
    }


@router.get("/symbols")
def list_symbols(
    timeframe: str = Query(default="1D"),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = (
        db.query(models.MarketDataStore)
        .filter(models.MarketDataStore.timeframe == timeframe)
        .order_by(models.MarketDataStore.symbol.asc())
        .all()
    )
    return [
        {
            "symbol": r.symbol,
            "timeframe": r.timeframe,
            "object_key": r.object_key,
            "start_ts": r.start_ts,
            "end_ts": r.end_ts,
            "row_count": r.row_count,
            "updated_at": r.updated_at,
            "source_provider": r.source_provider,
        }
        for r in rows
    ]


@router.get("/uploads/{dataset_id}/report-url")
def get_ingest_report_url(
    dataset_id: UUID,
    expires_seconds: int = Query(default=300, ge=30, le=3600),
) -> dict[str, Any]:
    object_key = f"market_data/uploads/{dataset_id}/ingest_report.json"
    return {
        "dataset_id": str(dataset_id),
        "object_key": object_key,
        "url": presign_get(object_key, expires_seconds=expires_seconds),
        "expires_seconds": int(expires_seconds),
    }


@router.get("/uploads/{dataset_id}/status")
def get_ingest_status(dataset_id: UUID) -> dict[str, Any]:
    """Poll-friendly endpoint: returns the ingest report inline if ready, else {"status": "processing"}."""
    object_key = f"market_data/uploads/{dataset_id}/ingest_report.json"
    s3 = s3_client()
    try:
        obj = s3.get_object(Bucket=settings.S3_BUCKET, Key=object_key)
        report = json.loads(obj["Body"].read())
        return {"status": "done", "report": report}
    except s3.exceptions.NoSuchKey:
        return {"status": "processing"}
    except Exception:
        # Bucket/auth issues — treat as still processing to avoid false errors
        return {"status": "processing"}


# ── Helpers ──────────────────────────────────────────────────────────────────

@router.get("/upload-format-reference")
def get_upload_format_reference() -> UploadFormatReferenceOut:
    return UploadFormatReferenceOut.model_validate(build_upload_format_reference())


def _today_utc() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date()


def _business_days_ago(d: datetime.date, n: int) -> datetime.date:
    """Return the date n business days before d (Mon–Fri only)."""
    count = 0
    current = d
    while count < n:
        current -= datetime.timedelta(days=1)
        if current.weekday() < 5:  # Monday=0, Friday=4
            count += 1
    return current


def _is_stale(data_as_of: datetime.date | None) -> bool:
    if data_as_of is None:
        return True
    return data_as_of < _business_days_ago(_today_utc(), 2)


def _stock_to_out(
    stock: models.StockMaster,
    store: models.MarketDataStore | None,
) -> StockMasterOut:
    masi_info = get_masi_info(stock.symbol)
    display_name = masi_info.get("display_name") if masi_info else stock.display_name
    sector = stock.sector or (masi_info.get("sector") if masi_info else None)

    return StockMasterOut(
        symbol=stock.symbol,
        display_name=display_name,
        isin=stock.isin,
        sector=sector,
        market_cap_class=stock.market_cap_class,
        is_active=stock.is_active,
        track_source=stock.track_source,
        bourse_url=stock.bourse_url,
        notes=stock.notes,
        created_at=stock.created_at,
        updated_at=stock.updated_at,
        start_ts=store.start_ts if store else None,
        end_ts=store.end_ts if store else None,
        row_count=store.row_count if store else None,
        store_updated_at=store.updated_at if store else None,
        source_provider=store.source_provider if store else None,
        data_as_of=store.data_as_of if store else None,
        is_stale=_is_stale(store.data_as_of if store else None),
    )


def _refresh_run_to_out(run: models.MarketRefreshRun) -> MarketRefreshRunOut:
    return MarketRefreshRunOut.model_validate(run)


def _get_market_store_or_404(db: Session, symbol: str, timeframe: str) -> models.MarketDataStore:
    store = (
        db.query(models.MarketDataStore)
        .filter(
            models.MarketDataStore.symbol == symbol,
            models.MarketDataStore.timeframe == timeframe,
        )
        .one_or_none()
    )
    if not store:
        raise HTTPException(status_code=404, detail=f"No market data for {symbol}/{timeframe}")
    return store


def _safe_optional_float(value: Any, *, zero_as_none: bool = False) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    if not pd.notna(out):
        return None
    if zero_as_none and out == 0.0:
        return None
    return out


def _frame_to_ohlcv_bars(frame: pd.DataFrame) -> list[OhlcvBarOut]:
    bars: list[OhlcvBarOut] = []
    for ts, row in frame.iterrows():
        bars.append(
            OhlcvBarOut(
                date=ts.strftime("%Y-%m-%d"),
                open=_safe_optional_float(row.get("Open"), zero_as_none=True),
                high=_safe_optional_float(row.get("High"), zero_as_none=True),
                low=_safe_optional_float(row.get("Low"), zero_as_none=True),
                close=_safe_optional_float(row.get("Close"), zero_as_none=True),
                volume=_safe_optional_float(row.get("Volume")),
            )
        )
    return bars


def _calendar_day_state(
    day: datetime.date,
    *,
    symbol: str,
    first_date: datetime.date,
    last_date: datetime.date,
    present_dates: set[datetime.date],
) -> tuple[str, dict[str, Any] | None]:
    if day in present_dates:
        return "present_data", get_holiday_info(day, symbol=symbol)
    if day < first_date or day > last_date:
        return "outside_series_range", None
    if day.weekday() >= 5:
        return "weekend", None

    holiday = get_holiday_info(day, symbol=symbol)
    if holiday:
        certainty = str(holiday.get("certainty") or "tentative")
        if certainty == "confirmed":
            return "market_holiday", holiday
        return "tentative_market_holiday", holiday

    return "missing_expected_day", None


def _safe_positive_bar_value(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    if not pd.notna(out) or out <= 0.0:
        return None
    return out


def _is_no_trading_row(row: pd.Series) -> bool:
    close = _safe_positive_bar_value(row.get("Close"))
    if close is None:
        return False

    volume = _safe_positive_bar_value(row.get("Volume"))
    if volume is None:
        return True

    ohl_values = [_safe_positive_bar_value(row.get(col)) for col in ("Open", "High", "Low")]
    return all(value is None for value in ohl_values)


# ── Stock Registry Endpoints ─────────────────────────────────────────────────

@router.get("/stocks")
def list_tracked_stocks(
    is_active: bool = Query(default=True),
    db: Session = Depends(get_db),
) -> list[StockMasterOut]:
    stocks = (
        db.query(models.StockMaster)
        .filter(models.StockMaster.is_active == is_active)
        .order_by(models.StockMaster.symbol.asc())
        .all()
    )
    result = []
    for stock in stocks:
        store = (
            db.query(models.MarketDataStore)
            .filter(
                models.MarketDataStore.symbol == stock.symbol,
                models.MarketDataStore.timeframe == "1D",
            )
            .one_or_none()
        )
        result.append(_stock_to_out(stock, store))
    return result


@router.post("/stocks", status_code=201)
def add_tracked_stock(
    body: StockMasterCreate,
    db: Session = Depends(get_db),
) -> StockMasterOut:
    symbol = str(body.symbol or "").strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required")

    existing = db.query(models.StockMaster).filter(models.StockMaster.symbol == symbol).one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"Stock '{symbol}' already tracked")

    # MASI symbols use registry-owned names; other symbols may still provide a display name.
    masi_info = get_masi_info(symbol)
    lookup = _bourse_lookup(symbol)
    display_name = masi_info["display_name"] if masi_info else (body.display_name or lookup.display_name)
    sector = body.sector or (masi_info["sector"] if masi_info else lookup.sector)

    stock = models.StockMaster(
        symbol=symbol,
        display_name=display_name,
        isin=body.isin or lookup.isin,
        sector=sector,
        market_cap_class=body.market_cap_class,
        is_active=True,
        track_source=body.track_source or "bourse_direct",
        bourse_url=body.bourse_url or lookup.bourse_url,
        notes=body.notes,
    )
    db.add(stock)
    db.flush()  # persist stock_master row so FK constraint is satisfied before inserting provider maps

    sqlite_next_id = _next_sqlite_provider_map_id(db)
    yahoo_map_kwargs = {"id": sqlite_next_id} if sqlite_next_id is not None else {}
    bourse_map_kwargs = {"id": sqlite_next_id + 1} if sqlite_next_id is not None else {}

    # Auto-create Yahoo provider mapping at confidence=0.9
    yahoo_map = models.ProviderSymbolMap(
        **yahoo_map_kwargs,
        symbol=symbol,
        provider="yahoo",
        provider_symbol=f"{symbol}.CS",
        confidence=0.9,
        is_verified=False,
    )
    db.add(yahoo_map)

    # Auto-create bourse_direct mapping at confidence=1.0
    bourse_map = models.ProviderSymbolMap(
        **bourse_map_kwargs,
        symbol=symbol,
        provider="bourse_direct",
        provider_symbol=symbol,
        confidence=1.0,
        is_verified=False,
    )
    db.add(bourse_map)

    db.commit()
    db.refresh(stock)
    return _stock_to_out(stock, None)


@router.patch("/stocks/{symbol}")
def update_tracked_stock(
    symbol: str,
    body: StockMasterUpdate,
    db: Session = Depends(get_db),
) -> StockMasterOut:
    symbol = symbol.strip().upper()
    stock = db.query(models.StockMaster).filter(models.StockMaster.symbol == symbol).one_or_none()
    if not stock:
        raise HTTPException(status_code=404, detail=f"Stock '{symbol}' not found")

    if body.isin is not None:
        stock.isin = body.isin
    if body.sector is not None:
        stock.sector = body.sector
    if body.market_cap_class is not None:
        stock.market_cap_class = body.market_cap_class
    if body.is_active is not None:
        stock.is_active = body.is_active
    if body.track_source is not None:
        stock.track_source = body.track_source
    if body.bourse_url is not None:
        stock.bourse_url = body.bourse_url
    if body.notes is not None:
        stock.notes = body.notes

    db.commit()
    db.refresh(stock)
    store = (
        db.query(models.MarketDataStore)
        .filter(
            models.MarketDataStore.symbol == symbol,
            models.MarketDataStore.timeframe == "1D",
        )
        .one_or_none()
    )
    return _stock_to_out(stock, store)


@router.delete("/symbols/{symbol}")
def delete_market_symbol(
    symbol: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=400, detail="symbol is required")

    store = (
        db.query(models.MarketDataStore)
        .filter(
            models.MarketDataStore.symbol == symbol,
            models.MarketDataStore.timeframe == "1D",
        )
        .one_or_none()
    )
    stock = db.query(models.StockMaster).filter(models.StockMaster.symbol == symbol).one_or_none()

    if store is None and stock is None:
        raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found")

    deleted_object_key = str(store.object_key) if store and store.object_key else None
    deleted_canonical_data = store is not None
    deleted_tracked_stock = stock is not None

    try:
        if store is not None:
            db.delete(store)

        db.query(models.ProviderSymbolMap).filter(
            models.ProviderSymbolMap.symbol == symbol
        ).delete(synchronize_session=False)

        if stock is not None:
            db.delete(stock)

        db.commit()
    except Exception:
        db.rollback()
        raise

    if deleted_object_key:
        try:
            delete_object(deleted_object_key)
        except Exception:
            # The catalog row is already deleted from Postgres. S3 cleanup is best-effort.
            pass

    return {
        "symbol": symbol,
        "deleted_tracked_stock": deleted_tracked_stock,
        "deleted_canonical_data": deleted_canonical_data,
        "deleted_object_key": deleted_object_key,
    }


# ── Symbol Mapping Endpoints ──────────────────────────────────────────────────

@router.get("/stocks/{symbol}/mappings")
def list_stock_mappings(
    symbol: str,
    db: Session = Depends(get_db),
) -> list[ProviderSymbolMapOut]:
    symbol = symbol.strip().upper()
    rows = (
        db.query(models.ProviderSymbolMap)
        .filter(models.ProviderSymbolMap.symbol == symbol)
        .order_by(models.ProviderSymbolMap.provider.asc())
        .all()
    )
    return [ProviderSymbolMapOut.model_validate(r) for r in rows]


@router.patch("/stocks/{symbol}/mappings/{provider}")
def update_stock_mapping(
    symbol: str,
    provider: str,
    body: ProviderSymbolMapUpdate,
    db: Session = Depends(get_db),
) -> ProviderSymbolMapOut:
    symbol = symbol.strip().upper()
    provider = provider.strip().lower()
    row = (
        db.query(models.ProviderSymbolMap)
        .filter(
            models.ProviderSymbolMap.symbol == symbol,
            models.ProviderSymbolMap.provider == provider,
        )
        .one_or_none()
    )
    if not row:
        raise HTTPException(status_code=404, detail=f"Mapping for {symbol}/{provider} not found")

    row.provider_symbol = body.provider_symbol
    row.is_verified = body.is_verified
    if body.override_reason is not None:
        row.override_reason = body.override_reason
    row.confidence = 1.0 if body.is_verified else row.confidence

    db.commit()
    db.refresh(row)
    return ProviderSymbolMapOut.model_validate(row)


# ── Bourse de Casablanca Lookup ───────────────────────────────────────────────

def _bourse_lookup(symbol: str) -> BourseStockLookupOut:
    """
    Attempt to find a stock on the Bourse de Casablanca website by ticker.
    Constructs the instrument page URL and scrapes basic metadata (name, sector, ISIN).
    Returns whatever it can find; always returns a URL even if scraping fails.
    """
    import html as _html
    import re as _re
    try:
        import requests as _requests
    except ImportError:
        raise HTTPException(status_code=500, detail="requests package not installed")

    import os as _os
    # URL template is configurable via BOURSE_STOCK_PAGE_URL env var.
    url_template = _os.environ.get(
        "BOURSE_STOCK_PAGE_URL",
        "https://www.casablanca-bourse.com/fr/live-market/instruments/{symbol}?pwa=1",
    )
    bourse_url = url_template.format(symbol=symbol)

    display_name: Optional[str] = None
    sector: Optional[str] = None
    isin: Optional[str] = None

    try:
        resp = _requests.get(
            bourse_url,
            timeout=10,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            },
            allow_redirects=True,
            verify=False,
        )
        if resp.status_code == 200:
            html = resp.text
            name_match = _re.search(
                rf'href=["\']/fr/live-market/instruments/{_re.escape(symbol)}\?pwa[^"\']*["\'][^>]*>([^<]+)<',
                html,
                _re.IGNORECASE,
            )
            if name_match:
                name_part = _html.unescape(name_match.group(1)).strip()
                if name_part and name_part.upper() != symbol:
                    display_name = name_part

            # Try to extract ISIN (12-char alphanumeric starting with MA)
            isin_match = _re.search(r"\b(MA[A-Z0-9]{10})\b", html)
            if isin_match:
                isin = isin_match.group(1)

            sector_match = _re.search(
                r"<th[^>]*>\s*Secteur\s*</th>\s*<td[^>]*>(?:<[^>]+>)*([^<]+)",
                html,
                _re.IGNORECASE | _re.DOTALL,
            ) or _re.search(r"[Ss]ecteur[^:]*:\s*([^<\n]{3,50})", html)
            if sector_match:
                sector = _html.unescape(sector_match.group(1)).strip()

    except Exception:
        pass  # URL is still valid; return it even if scraping failed

    return BourseStockLookupOut(
        symbol=symbol,
        bourse_url=bourse_url,
        display_name=display_name or None,
        sector=sector or None,
        isin=isin or None,
        found=True,
    )


@router.get("/stocks/{symbol}/bourse-lookup")
def bourse_lookup_stock(symbol: str, db: Session = Depends(get_db)) -> BourseStockLookupOut:
    """
    Look up a stock on the Bourse de Casablanca website by ticker symbol.
    Returns the direct page URL and any metadata that can be scraped (name, sector, ISIN).
    Also persists the URL into stock_master if the stock is already tracked.
    """
    symbol = symbol.strip().upper()
    result = _bourse_lookup(symbol)
    stock = db.query(models.StockMaster).filter(models.StockMaster.symbol == symbol).one_or_none()
    if stock:
        changed = False
        if result.bourse_url and not stock.bourse_url:
            stock.bourse_url = result.bourse_url
            changed = True
        if result.isin and not stock.isin:
            stock.isin = result.isin
            changed = True
        if result.sector and not stock.sector:
            stock.sector = result.sector
            changed = True
        if result.display_name and not stock.display_name:
            stock.display_name = result.display_name
            changed = True
        if changed:
            db.commit()
    return result


# ── OHLCV Preview ─────────────────────────────────────────────────────────────

@router.get("/stocks/{symbol}/ohlcv-preview")
def get_stock_ohlcv_preview(
    symbol: str,
    timeframe: str = Query(default="1D"),
    limit: int = Query(default=30, ge=1, le=500),
    db: Session = Depends(get_db),
) -> OhlcvPreviewOut:
    symbol = symbol.strip().upper()
    store = _get_market_store_or_404(db, symbol, timeframe)

    try:
        frame = load_ohlcv_for_symbol(db, symbol, timeframe)
        tail = frame.tail(limit)
        bars = _frame_to_ohlcv_bars(tail)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load OHLCV: {exc}") from exc

    return OhlcvPreviewOut(
        symbol=symbol,
        timeframe=timeframe,
        bars=bars,
        source_provider=store.source_provider,
        data_as_of=store.data_as_of,
        row_count=store.row_count,
    )


@router.get("/stocks/{symbol}/ohlcv-history")
def get_stock_ohlcv_history(
    symbol: str,
    timeframe: str = Query(default="1D"),
    db: Session = Depends(get_db),
) -> OhlcvHistoryOut:
    symbol = symbol.strip().upper()
    store = _get_market_store_or_404(db, symbol, timeframe)

    try:
        frame = load_ohlcv_for_symbol(db, symbol, timeframe)
        bars = _frame_to_ohlcv_bars(frame)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load OHLCV history: {exc}") from exc

    return OhlcvHistoryOut(
        symbol=symbol,
        timeframe=timeframe,
        bars=bars,
        source_provider=store.source_provider,
        data_as_of=store.data_as_of,
        row_count=store.row_count,
    )


@router.get("/stocks/{symbol}/availability-calendar")
def get_stock_availability_calendar(
    symbol: str,
    timeframe: str = Query(default="1D"),
    db: Session = Depends(get_db),
) -> AvailabilityCalendarOut:
    symbol = symbol.strip().upper()
    _store = _get_market_store_or_404(db, symbol, timeframe)

    try:
        frame = load_ohlcv_for_symbol(db, symbol, timeframe).sort_index()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load availability calendar: {exc}") from exc

    if frame.empty:
        raise HTTPException(status_code=404, detail=f"No market data for {symbol}/{timeframe}")

    first_date = frame.index.min().date()
    last_date = frame.index.max().date()
    present_dates = {ts.date() for ts in frame.index}
    no_trading_dates = {
        ts.date()
        for ts, row_data in frame.iterrows()
        if _is_no_trading_row(row_data)
    }

    # Build per-date missing-fields lookup for partial data detection
    ohlcv_cols = ["Open", "High", "Low", "Close", "Volume"]
    available_cols = [c for c in ohlcv_cols if c in frame.columns]
    missing_fields_by_date: dict[datetime.date, list[str]] = {}
    if available_cols:
        for ts, row_data in frame[available_cols].iterrows():
            missing = [
                c
                for c in available_cols
                if pd.isna(row_data[c])
                or (c in {"Open", "High", "Low", "Close"} and _safe_positive_bar_value(row_data[c]) is None)
            ]
            if missing:
                missing_fields_by_date[ts.date()] = [c.lower() for c in missing]
    # Also flag columns entirely absent from the frame
    absent_cols = [c.lower() for c in ohlcv_cols if c not in frame.columns]

    days: list[AvailabilityCalendarDayOut] = []
    counts = {
        "present_data": 0,
        "missing_expected_day": 0,
        "weekend": 0,
        "market_holiday": 0,
        "tentative_market_holiday": 0,
        "no_trading_day": 0,
    }
    partial_count = 0

    cursor = first_date
    while cursor <= last_date:
        state, holiday = _calendar_day_state(
            cursor,
            symbol=symbol,
            first_date=first_date,
            last_date=last_date,
            present_dates=present_dates,
        )
        if state == "present_data" and cursor in no_trading_dates:
            state = "no_trading_day"
        if state in counts:
            counts[state] += 1

        day_missing: list[str] = []
        if cursor in present_dates:
            day_missing = missing_fields_by_date.get(cursor, []) + absent_cols
            if day_missing and state != "no_trading_day":
                partial_count += 1

        days.append(
            AvailabilityCalendarDayOut(
                date=cursor.isoformat(),
                state=state,
                has_data=cursor in present_dates,
                holiday_name=str(holiday.get("name")) if holiday else None,
                holiday_certainty=str(holiday.get("certainty")) if holiday else None,
                missing_fields=day_missing,
            )
        )
        cursor += datetime.timedelta(days=1)

    default_month_anchor = last_date - datetime.timedelta(days=365)
    default_month = max(default_month_anchor, first_date).replace(day=1)

    return AvailabilityCalendarOut(
        symbol=symbol,
        timeframe=timeframe,
        first_date=first_date.isoformat(),
        last_date=last_date.isoformat(),
        default_month=default_month.isoformat(),
        days=days,
        present_days=counts["present_data"],
        missing_expected_days=counts["missing_expected_day"],
        weekend_days=counts["weekend"],
        market_holiday_days=counts["market_holiday"],
        tentative_market_holiday_days=counts["tentative_market_holiday"],
        no_trading_days=counts["no_trading_day"],
        partial_days=partial_count,
    )


# ── OHLCV Row Mutation Endpoints ──────────────────────────────────────────────


def _update_store_metadata(db: Session, store: models.MarketDataStore, frame: pd.DataFrame) -> None:
    """Sync market_data_store row with the current state of the parquet frame."""
    start_ts = frame.index.min().to_pydatetime() if not frame.empty else None
    end_ts = frame.index.max().to_pydatetime() if not frame.empty else None
    store.row_count = int(len(frame))
    store.start_ts = start_ts
    store.end_ts = end_ts
    store.data_as_of = end_ts.date() if end_ts is not None else None
    store.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()


def _raise_preclose_bourse_refresh_block() -> None:
    raise HTTPException(
        status_code=409,
        detail=(
            "Latest completed Bourse session is already loaded. "
            f"Next intraday Bourse refresh is available after {BOURSE_REFRESH_CUTOFF_LABEL} "
            "Africa/Casablanca."
        ),
    )


def _normalize_data_as_of(value: datetime.date | datetime.datetime | None) -> datetime.date | None:
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.date.fromisoformat(value)
        except ValueError:
            return None
    return value


def _symbol_needs_bourse_refresh(
    db: Session,
    *,
    symbol: str,
    timeframe: str,
) -> bool:
    row = (
        db.query(models.MarketDataStore.data_as_of)
        .filter(
            models.MarketDataStore.symbol == symbol,
            models.MarketDataStore.timeframe == timeframe,
        )
        .one_or_none()
    )
    data_as_of = _normalize_data_as_of(row[0] if row else None)
    return needs_bourse_refresh(data_as_of)


def _bourse_refresh_candidate_state(
    db: Session,
    *,
    timeframe: str,
    use_all_active: bool,
) -> tuple[bool, bool]:
    query = db.execute(
        text(
            """
            SELECT sm.symbol, sm.track_source, mds.data_as_of
            FROM stock_master sm
            LEFT JOIN market_data_store mds
              ON mds.symbol = sm.symbol
             AND mds.timeframe = :timeframe
            WHERE sm.is_active = true
            """
        ),
        {"timeframe": timeframe},
    ).mappings()

    has_eligible = False
    for row in query:
        if not use_all_active and str(row["track_source"] or "").strip().lower() != "bourse_direct":
            continue
        has_eligible = True
        data_as_of = _normalize_data_as_of(row["data_as_of"])
        if needs_bourse_refresh(data_as_of):
            return has_eligible, True
    return has_eligible, False


@router.patch("/stocks/{symbol}/ohlcv-rows", response_model=OhlcvMutationResult)
def upsert_ohlcv_row(
    symbol: str,
    body: OhlcvRowUpsert,
    db: Session = Depends(get_db),
    timeframe: str = Query("1D"),
) -> OhlcvMutationResult:
    """Insert or update a single OHLCV row. Only non-None fields are written."""
    store = _get_market_store_or_404(db, symbol, timeframe)
    ts = pd.Timestamp(body.date, tz="UTC")

    def _apply(frame: pd.DataFrame) -> pd.DataFrame:
        if ts not in frame.index:
            # Insert new row with NaNs, then fill provided fields
            frame.loc[ts] = [float("nan")] * len(frame.columns)
        for field, value in [
            ("Open", body.open), ("High", body.high), ("Low", body.low),
            ("Close", body.close), ("Volume", body.volume),
        ]:
            if value is not None and field in frame.columns:
                frame.at[ts, field] = value
        return frame.sort_index()

    modified = load_modify_save_ohlcv(store.object_key, _apply)
    _update_store_metadata(db, store, modified)

    return OhlcvMutationResult(
        symbol=symbol,
        timeframe=timeframe,
        action="upserted",
        affected_dates=[body.date],
        new_row_count=int(len(modified)),
    )


@router.delete("/stocks/{symbol}/ohlcv-rows", response_model=OhlcvMutationResult)
def delete_ohlcv_rows(
    symbol: str,
    body: OhlcvRowDeleteRequest,
    db: Session = Depends(get_db),
    timeframe: str = Query("1D"),
) -> OhlcvMutationResult:
    """Delete one or more OHLCV rows by date."""
    store = _get_market_store_or_404(db, symbol, timeframe)
    timestamps = [pd.Timestamp(d, tz="UTC") for d in body.dates]

    def _apply(frame: pd.DataFrame) -> pd.DataFrame:
        to_drop = frame.index.intersection(pd.DatetimeIndex(timestamps))
        return frame.drop(to_drop).sort_index()

    modified = load_modify_save_ohlcv(store.object_key, _apply)
    _update_store_metadata(db, store, modified)

    return OhlcvMutationResult(
        symbol=symbol,
        timeframe=timeframe,
        action="deleted",
        affected_dates=body.dates,
        new_row_count=int(len(modified)),
    )


# ── Refresh Trigger Endpoints ─────────────────────────────────────────────────

@router.post("/refresh", status_code=202)
def trigger_refresh_all(
    body: MarketRefreshTriggerRequest = MarketRefreshTriggerRequest(),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    source_override = str(body.source_override or "").strip().lower() or None
    if is_before_bourse_refresh_cutoff():
        if is_bourse_source(source_override):
            has_eligible, has_pending = _bourse_refresh_candidate_state(
                db,
                timeframe=body.timeframe,
                use_all_active=True,
            )
            if has_eligible and not has_pending:
                _raise_preclose_bourse_refresh_block()
        if source_override is None:
            has_eligible, has_pending = _bourse_refresh_candidate_state(
                db,
                timeframe=body.timeframe,
                use_all_active=False,
            )
            if has_eligible and not has_pending:
                _raise_preclose_bourse_refresh_block()

    active_count = db.query(models.StockMaster).filter(models.StockMaster.is_active == True).count()

    run = models.MarketRefreshRun(
        id=uuid4(),
        trigger_source="manual",
        scope="all",
        symbol=None,
        timeframe=body.timeframe,
        status="queued",
        symbols_total=active_count,
        symbols_done=0,
        symbols_failed=0,
        meta_json={"source_override": body.source_override, "include_unverified": body.include_unverified},
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    q = get_market_refresh_queue()
    job = q.enqueue(
        "services.worker.tasks.refresh_market_data.refresh_all_tracked_symbols",
        str(run.id),
        body.timeframe,
        body.source_override,
        body.include_unverified,
    )
    run.rq_job_id = job.id
    db.commit()

    return {
        "refresh_run_id": str(run.id),
        "status": "queued",
        "symbols_total": active_count,
        "job_id": job.id,
    }


@router.post("/stocks/{symbol}/refresh", status_code=202)
def trigger_refresh_single(
    symbol: str,
    body: MarketRefreshTriggerRequest = MarketRefreshTriggerRequest(),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    stock = db.query(models.StockMaster).filter(models.StockMaster.symbol == symbol).one_or_none()
    if not stock:
        raise HTTPException(status_code=404, detail=f"Stock '{symbol}' not tracked")

    source = body.source_override or stock.track_source
    if is_bourse_source(source) and is_before_bourse_refresh_cutoff():
        if not _symbol_needs_bourse_refresh(db, symbol=symbol, timeframe=body.timeframe):
            _raise_preclose_bourse_refresh_block()

    run = models.MarketRefreshRun(
        id=uuid4(),
        trigger_source="manual",
        scope="single",
        symbol=symbol,
        timeframe=body.timeframe,
        status="queued",
        symbols_total=1,
        symbols_done=0,
        symbols_failed=0,
        meta_json={"source_override": body.source_override},
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    q = get_market_refresh_queue()
    job = q.enqueue(
        "services.worker.tasks.refresh_market_data.refresh_single_symbol",
        str(run.id),
        symbol,
        body.timeframe,
        source,
    )
    run.rq_job_id = job.id
    db.commit()

    return {
        "refresh_run_id": str(run.id),
        "status": "queued",
        "job_id": job.id,
    }


# ── Refresh Run Status Endpoints ──────────────────────────────────────────────

@router.get("/refresh")
def list_refresh_runs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[MarketRefreshRunOut]:
    runs = (
        db.query(models.MarketRefreshRun)
        .order_by(models.MarketRefreshRun.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_refresh_run_to_out(r) for r in runs]


@router.get("/refresh/{refresh_run_id}")
def get_refresh_run(
    refresh_run_id: UUID,
    db: Session = Depends(get_db),
) -> MarketRefreshRunOut:
    run = db.query(models.MarketRefreshRun).filter(models.MarketRefreshRun.id == refresh_run_id).one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Refresh run not found")
    return _refresh_run_to_out(run)


# ── Market Health ─────────────────────────────────────────────────────────────

@router.get("/catalog")
def get_market_catalog(db: Session = Depends(get_db)) -> list[MarketCatalogRowOut]:
    """
    Unified canonical market universe for the /data page.

    UNION of three sources:
      A. Equities: market_data_store (asset_class='equity') ↔ stock_master
         + stock_master rows without a market_data_store entry yet.
      B. Indices: market_data_store (asset_class='index') ↔ index_master.
      C. Factors: market_data_store (asset_class='factor') ↔ macro_factor_meta.
         + macro_factor_meta rows without a market_data_store entry yet.
    """
    return [
        MarketCatalogRowOut(
            symbol=row.symbol,
            display_name=row.display_name,
            isin=row.isin,
            sector=row.sector,
            is_active=row.is_active,
            track_source=row.track_source,
            bourse_url=row.bourse_url,
            notes=row.notes,
            start_ts=row.start_ts,
            end_ts=row.end_ts,
            row_count=row.row_count,
            source_provider=row.source_provider,
            data_as_of=row.data_as_of,
            is_stale=row.is_stale,
            is_tracked=row.is_tracked,
            has_canonical_data=row.has_canonical_data,
            market=row.market,
            asset_type=row.asset_type,
            market_region=row.market_region,
            asset_class=row.asset_class,
        )
        for row in list_market_catalog(db, include_without_data=True)
    ]
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
    rows = db.execute(
        text("""
            -- ── ARM 1: equities/unknown with data ───────────────────────────
            SELECT
                mds.symbol,
                sm.display_name,
                sm.isin,
                sm.sector,
                sm.is_active,
                sm.track_source,
                sm.bourse_url,
                sm.notes,
                COALESCE(sm.asset_type, 'equity')  AS asset_type,
                sm.market_region,
                mds.start_ts,
                mds.end_ts,
                mds.row_count,
                mds.source_provider,
                mds.data_as_of,
                (sm.symbol IS NOT NULL)             AS is_tracked,
                TRUE                                AS has_canonical_data
            FROM market_data_store mds
            LEFT JOIN stock_master sm ON sm.symbol = mds.symbol
            WHERE mds.timeframe = '1D'
              AND mds.asset_class NOT IN ('index', 'factor')

            UNION ALL

            -- ── ARM 2: tracked stocks with no data yet ────────────────────
            SELECT
                sm.symbol,
                sm.display_name,
                sm.isin,
                sm.sector,
                sm.is_active,
                sm.track_source,
                sm.bourse_url,
                sm.notes,
                COALESCE(sm.asset_type, 'equity')   AS asset_type,
                sm.market_region,
                NULL  AS start_ts,
                NULL  AS end_ts,
                NULL  AS row_count,
                NULL  AS source_provider,
                NULL  AS data_as_of,
                TRUE  AS is_tracked,
                FALSE AS has_canonical_data
            FROM stock_master sm
            WHERE NOT EXISTS (
                SELECT 1 FROM market_data_store mds2
                WHERE mds2.symbol = sm.symbol AND mds2.timeframe = '1D'
            )

            UNION ALL

            -- ── ARM 3: indices with data ─────────────────────────────────
            SELECT
                mds.symbol,
                COALESCE(im.display_name, mds.symbol) AS display_name,
                NULL          AS isin,
                NULL          AS sector,
                TRUE          AS is_active,
                'casablanca_bourse' AS track_source,
                NULL          AS bourse_url,
                NULL          AS notes,
                'equity'      AS asset_type,
                COALESCE(im.market_region, 'masi') AS market_region,
                mds.start_ts,
                mds.end_ts,
                mds.row_count,
                mds.source_provider,
                mds.data_as_of,
                TRUE          AS is_tracked,
                TRUE          AS has_canonical_data
            FROM market_data_store mds
            LEFT JOIN index_master im ON im.symbol = mds.symbol
            WHERE mds.timeframe = '1D'
              AND mds.asset_class = 'index'

            UNION ALL

            -- ── ARM 4: macro factors with data ───────────────────────────
            SELECT
                mds.symbol,
                COALESCE(mfm.display_name, mds.symbol) AS display_name,
                NULL          AS isin,
                NULL          AS sector,
                TRUE          AS is_active,
                'yahoo'       AS track_source,
                NULL          AS bourse_url,
                mfm.notes     AS notes,
                mfm.asset_type,
                mfm.market_region,
                mds.start_ts,
                mds.end_ts,
                mds.row_count,
                'yahoo'       AS source_provider,
                mds.data_as_of,
                TRUE          AS is_tracked,
                TRUE          AS has_canonical_data
            FROM market_data_store mds
            JOIN macro_factor_meta mfm ON mfm.canonical_id = mds.symbol
            WHERE mds.timeframe = '1D'
              AND mds.asset_class = 'factor'
              AND mfm.active = true

            UNION ALL

            -- ── ARM 5: macro factors registered but not yet ingested ─────
            SELECT
                mfm.canonical_id   AS symbol,
                mfm.display_name,
                NULL  AS isin,
                NULL  AS sector,
                TRUE  AS is_active,
                'yahoo'  AS track_source,
                NULL  AS bourse_url,
                mfm.notes,
                mfm.asset_type,
                mfm.market_region,
                NULL  AS start_ts,
                NULL  AS end_ts,
                NULL  AS row_count,
                'yahoo'  AS source_provider,
                NULL  AS data_as_of,
                TRUE  AS is_tracked,
                FALSE AS has_canonical_data
            FROM macro_factor_meta mfm
            WHERE mfm.active = true
              AND NOT EXISTS (
                SELECT 1 FROM market_data_store mds2
                WHERE mds2.symbol = mfm.canonical_id AND mds2.timeframe = '1D'
              )

            ORDER BY symbol ASC
        """)
    ).mappings().all()

    result = []
    for r in rows:
        if _is_data_page_excluded_stock(symbol=r["symbol"], display_name=r["display_name"]):
            continue
        data_as_of: datetime.date | None = r["data_as_of"]
        if isinstance(data_as_of, datetime.datetime):
            data_as_of = data_as_of.date()
        masi_info = get_masi_info(r["symbol"])
        display_name = r["display_name"]
        if masi_info and (not display_name or str(display_name).strip().upper() == str(r["symbol"]).strip().upper()):
            display_name = masi_info.get("display_name")
        sector = r["sector"] or (masi_info.get("sector") if masi_info else None)
        asset_type = r["asset_type"] or None
        market_region = r["market_region"]
        if asset_type is None:
            asset_type, market_region = _detect_asset_type(
                r["symbol"],
                track_source=r["track_source"],
                is_masi=is_masi_ticker(r["symbol"]),
            )
        if market_region == "masi":
            market = "masi"
        elif asset_type == "equity":
            market = "other"
        else:
            market = asset_type
        result.append(
            MarketCatalogRowOut(
                symbol=r["symbol"],
                display_name=display_name,
                isin=r["isin"],
                sector=sector,
                is_active=bool(r["is_active"]) if r["is_active"] is not None else True,
                track_source=r["track_source"],
                bourse_url=r["bourse_url"],
                notes=r["notes"],
                start_ts=r["start_ts"],
                end_ts=r["end_ts"],
                row_count=r["row_count"],
                source_provider=r["source_provider"],
                data_as_of=data_as_of,
                is_stale=_is_stale(data_as_of),
                is_tracked=bool(r["is_tracked"]),
                has_canonical_data=bool(r["has_canonical_data"]),
                market=market,
                asset_type=asset_type,
                market_region=market_region,
            )
        )
    return result


# ── Macro factor management endpoints ───────────────────────────────────────

class MacroFactorCreateIn(BaseModel):
    canonical_id: str
    yahoo_ticker: str
    display_name: str
    asset_type: str   # 'equity'|'commodity'|'forex'|'bond'|'crypto'
    market_region: Optional[str] = None
    notes: Optional[str] = None


class MacroFactorPatchIn(BaseModel):
    active: Optional[bool] = None
    display_name: Optional[str] = None
    notes: Optional[str] = None


class MacroFactorOut(BaseModel):
    canonical_id: str
    yahoo_ticker: str
    display_name: str
    asset_type: str
    market_region: Optional[str]
    active: bool
    added_via: str


@router.post("/factors", response_model=MacroFactorOut, status_code=201)
def add_macro_factor(
    body: MacroFactorCreateIn,
    db: Session = Depends(get_db),
) -> MacroFactorOut:
    """Register a new macro factor series.

    Validates the Yahoo ticker via yfinance probe, inserts into macro_factor_meta,
    and enqueues an initial ingest job.
    """
    valid_types = {"equity", "commodity", "forex", "bond", "crypto"}
    if body.asset_type not in valid_types:
        raise HTTPException(status_code=422, detail=f"asset_type must be one of {valid_types}")

    # Collision check
    existing = db.execute(
        text("SELECT canonical_id FROM macro_factor_meta WHERE canonical_id = :cid"),
        {"cid": body.canonical_id.upper()},
    ).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail=f"canonical_id '{body.canonical_id}' already exists")

    # yfinance probe — verify ticker returns data
    try:
        import yfinance as yf
        info = yf.Ticker(body.yahoo_ticker).fast_info
        if not hasattr(info, "last_price"):
            raise ValueError("no last_price")
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Could not verify yahoo_ticker '{body.yahoo_ticker}' via yfinance: {exc}",
        ) from exc

    db.execute(
        text(
            "INSERT INTO macro_factor_meta "
            "(canonical_id, yahoo_ticker, display_name, asset_type, market_region, active, added_via, notes) "
            "VALUES (:cid, :ticker, :name, :at, :mr, true, 'user', :notes)"
        ),
        {
            "cid":    body.canonical_id.upper(),
            "ticker": body.yahoo_ticker,
            "name":   body.display_name,
            "at":     body.asset_type,
            "mr":     body.market_region,
            "notes":  body.notes,
        },
    )
    db.commit()

    # Enqueue ingest job
    try:
        from ..queue import _get_macro_ingest_queue
        q = _get_macro_ingest_queue()
        q.enqueue(
            "services.worker.tasks.ingest_macro_series.ingest_macro_series",
            body.canonical_id.upper(),
            "2010-01-01",
        )
    except Exception:
        pass  # non-fatal — user can manually trigger ingest

    # Invalidate macro.py cache so next call picks up new factor
    try:
        from core.quant_core.macro import get_macro_series
        get_macro_series(force_refresh=True)
    except Exception:
        pass

    return MacroFactorOut(
        canonical_id=body.canonical_id.upper(),
        yahoo_ticker=body.yahoo_ticker,
        display_name=body.display_name,
        asset_type=body.asset_type,
        market_region=body.market_region,
        active=True,
        added_via="user",
    )


@router.patch("/factors/{canonical_id}", response_model=MacroFactorOut)
def patch_macro_factor(
    canonical_id: str,
    body: MacroFactorPatchIn,
    db: Session = Depends(get_db),
) -> MacroFactorOut:
    """Toggle active / update display fields for a macro factor."""
    row = db.execute(
        text(
            "SELECT canonical_id, yahoo_ticker, display_name, asset_type, market_region, active, added_via "
            "FROM macro_factor_meta WHERE canonical_id = :cid"
        ),
        {"cid": canonical_id.upper()},
    ).mappings().fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"Factor '{canonical_id}' not found")

    updates: dict[str, Any] = {"cid": canonical_id.upper()}
    clauses: list[str] = []
    if body.active is not None:
        clauses.append("active = :active")
        updates["active"] = body.active
    if body.display_name is not None:
        clauses.append("display_name = :display_name")
        updates["display_name"] = body.display_name
    if body.notes is not None:
        clauses.append("notes = :notes")
        updates["notes"] = body.notes

    if clauses:
        db.execute(
            text(f"UPDATE macro_factor_meta SET {', '.join(clauses)} WHERE canonical_id = :cid"),
            updates,
        )
        db.commit()

    # Invalidate macro.py cache
    try:
        from core.quant_core.macro import get_macro_series
        get_macro_series(force_refresh=True)
    except Exception:
        pass

    updated_row = db.execute(
        text(
            "SELECT canonical_id, yahoo_ticker, display_name, asset_type, market_region, active, added_via "
            "FROM macro_factor_meta WHERE canonical_id = :cid"
        ),
        {"cid": canonical_id.upper()},
    ).mappings().fetchone()
    return MacroFactorOut(**dict(updated_row))


@router.patch("/stocks/{symbol}/category", response_model=MarketCatalogRowOut)
def patch_asset_category(
    symbol: str,
    body: AssetCategoryPatchIn,
    db: Session = Depends(get_db),
) -> MarketCatalogRowOut:
    """Manually override asset_type and market_region for a symbol."""
    valid_types = {"equity", "commodity", "forex", "bond", "crypto"}
    valid_regions = {"masi", "us", "european", "asian"}
    if body.asset_type not in valid_types:
        raise HTTPException(status_code=422, detail=f"asset_type must be one of {valid_types}")
    if body.market_region is not None and body.market_region not in valid_regions:
        raise HTTPException(status_code=422, detail=f"market_region must be one of {valid_regions} or null")

    row = db.query(models.StockMaster).filter(models.StockMaster.symbol == symbol).first()
    if row is None:
        # Create a minimal tracked entry so the field is persisted
        row = models.StockMaster(symbol=symbol, track_source="manual")
        db.add(row)
    row.asset_type = body.asset_type
    row.market_region = body.market_region
    db.commit()
    db.refresh(row)

    # Build a minimal MarketCatalogRowOut from the updated row
    market_region = row.market_region
    asset_type = row.asset_type
    if market_region == "masi":
        market = "masi"
    elif asset_type == "equity":
        market = "other"
    else:
        market = asset_type
    return MarketCatalogRowOut(
        symbol=row.symbol,
        display_name=row.display_name,
        isin=row.isin,
        sector=row.sector,
        is_active=row.is_active,
        track_source=row.track_source,
        bourse_url=row.bourse_url,
        notes=row.notes,
        is_tracked=True,
        has_canonical_data=False,
        market=market,
        asset_type=asset_type,
        market_region=market_region,
    )


@router.get("/download-excel")
def download_all_market_data_excel(
    db: Session = Depends(get_db),
    asset_type: str | None = Query(default=None),
    market_region: str | None = Query(default=None),
    symbols: list[str] | None = Query(default=None),
    preset: str | None = Query(default=None),
):
    """Download 1D OHLCV data as a multi-sheet Excel file.

    Optional filters: symbols (repeatable or comma-separated explicit tickers),
                      asset_type ("equity"|"commodity"|"forex"|"bond"|"crypto")
                      market_region ("masi"|"us"|"european"|"asian")
    Without filters, returns all symbols.
    """
    requested_symbols: list[str] = []
    for raw in symbols or []:
        requested_symbols.extend(part.strip().upper() for part in str(raw).split(","))
    requested_symbols = list(dict.fromkeys(sym for sym in requested_symbols if sym))

    if requested_symbols:
        rows = db.execute(
            text("SELECT symbol FROM market_data_store WHERE timeframe = '1D'")
        ).scalars().all()
        available = {str(symbol) for symbol in rows}
        symbols = [symbol for symbol in requested_symbols if symbol in available]
        if not symbols:
            raise HTTPException(status_code=404, detail="No downloadable 1D data found for selected symbols")
        filename = "masi20-data.xlsx" if preset == "masi20" else "selected-data.xlsx"
    elif asset_type or market_region:
        # Need to join with stock_master to filter by category
        conditions = ["mds.timeframe = '1D'"]
        params: dict = {}
        if asset_type:
            conditions.append("sm.asset_type = :asset_type")
            params["asset_type"] = asset_type
        if market_region:
            conditions.append("sm.market_region = :market_region")
            params["market_region"] = market_region
        where = " AND ".join(conditions)
        symbols = db.execute(
            text(
                f"SELECT mds.symbol FROM market_data_store mds"
                f" JOIN stock_master sm ON sm.symbol = mds.symbol"
                f" WHERE {where} ORDER BY mds.symbol ASC"
            ),
            params,
        ).scalars().all()
        # Build a descriptive filename
        parts = [asset_type or "all", market_region or "all"]
        filename = f"{'-'.join(p for p in parts if p != 'all') or 'all'}-data.xlsx"
    else:
        symbols = db.execute(
            text("SELECT symbol FROM market_data_store WHERE timeframe = '1D' ORDER BY symbol ASC")
        ).scalars().all()
        filename = "masi app data.xlsx"

    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for symbol in symbols:
            try:
                frame = load_ohlcv_for_symbol(db, symbol, "1D")
            except Exception:
                continue
            if hasattr(frame.index, "tz") and frame.index.tz is not None:
                frame.index = frame.index.tz_localize(None)
            frame = frame.reset_index()
            frame.columns = [str(c) for c in frame.columns]
            if frame.columns[0] not in ("Date", "date"):
                frame = frame.rename(columns={frame.columns[0]: "Date"})
            frame.to_excel(writer, sheet_name=symbol[:31], index=False)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/masi-tickers")
def list_masi_tickers() -> list[dict[str, str]]:
    """Return the canonical MASI ticker registry for frontend autocomplete."""
    return [
        ticker
        for ticker in all_masi_tickers()
        if not _is_data_page_excluded_stock(
            symbol=ticker.get("symbol"),
            display_name=ticker.get("display_name"),
        )
    ]


@router.get("/health")
def get_market_health(db: Session = Depends(get_db)) -> MarketHealthOut:
    today = _today_utc()
    threshold_stale = _business_days_ago(today, 2)         # older than 2 biz days
    threshold_very_stale = today - datetime.timedelta(days=7)

    stocks = db.query(models.StockMaster).filter(models.StockMaster.is_active == True).all()
    total_tracked = len(stocks)
    up_to_date = 0
    stale = 0
    very_stale = 0
    never_ingested = 0

    for stock in stocks:
        store = (
            db.query(models.MarketDataStore)
            .filter(
                models.MarketDataStore.symbol == stock.symbol,
                models.MarketDataStore.timeframe == "1D",
            )
            .one_or_none()
        )
        if store is None or store.data_as_of is None:
            never_ingested += 1
        elif store.data_as_of < threshold_very_stale:
            very_stale += 1
        elif store.data_as_of < threshold_stale:
            stale += 1
        else:
            up_to_date += 1

    last_run = (
        db.query(models.MarketRefreshRun)
        .order_by(models.MarketRefreshRun.created_at.desc())
        .first()
    )
    last_successful = (
        db.query(models.MarketRefreshRun)
        .filter(models.MarketRefreshRun.status.in_(["succeeded", "partial"]))
        .order_by(models.MarketRefreshRun.finished_at.desc())
        .first()
    )

    return MarketHealthOut(
        total_tracked=total_tracked,
        up_to_date=up_to_date,
        stale=stale,
        very_stale=very_stale,
        never_ingested=never_ingested,
        last_refresh_run=_refresh_run_to_out(last_run) if last_run else None,
        last_successful_refresh=last_successful.finished_at if last_successful else None,
    )
