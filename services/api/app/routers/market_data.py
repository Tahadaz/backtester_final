from __future__ import annotations

import datetime
import json
from io import BytesIO
from pathlib import Path
from typing import Any, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Query
import pandas as pd
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text

from .. import models
from ..config import settings
from ..db import get_db
from ..market_data_formats import build_upload_format_reference
from ..market_holidays import get_holiday_info
from ..masi_tickers import is_masi_ticker, get_masi_info, all_masi_tickers
from ..queue import get_queue, get_market_refresh_queue
from ..storage import delete_object, put_bytes, presign_get, s3_client
from ..schemas.market_data import (
    AvailabilityCalendarDayOut,
    AvailabilityCalendarOut,
    BourseStockLookupOut,
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
    sector = stock.sector or (masi_info.get("sector") if masi_info else None)

    return StockMasterOut(
        symbol=stock.symbol,
        display_name=stock.display_name,
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


def _frame_to_ohlcv_bars(frame: pd.DataFrame) -> list[OhlcvBarOut]:
    bars: list[OhlcvBarOut] = []
    for ts, row in frame.iterrows():
        bars.append(
            OhlcvBarOut(
                date=ts.strftime("%Y-%m-%d"),
                open=float(row["Open"]) if "Open" in row and pd.notna(row["Open"]) else None,
                high=float(row["High"]) if "High" in row and pd.notna(row["High"]) else None,
                low=float(row["Low"]) if "Low" in row and pd.notna(row["Low"]) else None,
                close=float(row["Close"]) if "Close" in row and pd.notna(row["Close"]) else None,
                volume=float(row["Volume"]) if "Volume" in row and pd.notna(row["Volume"]) else None,
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
    display_name = masi_info["display_name"] if masi_info else body.display_name
    sector = body.sector or (masi_info["sector"] if masi_info else None)

    stock = models.StockMaster(
        symbol=symbol,
        display_name=display_name,
        isin=body.isin,
        sector=sector,
        market_cap_class=body.market_cap_class,
        is_active=True,
        track_source=body.track_source or "bourse_direct",
        bourse_url=body.bourse_url,
        notes=body.notes,
    )
    db.add(stock)
    db.flush()  # persist stock_master row so FK constraint is satisfied before inserting provider maps

    # Auto-create Yahoo provider mapping at confidence=0.9
    yahoo_map = models.ProviderSymbolMap(
        symbol=symbol,
        provider="yahoo",
        provider_symbol=f"{symbol}.CS",
        confidence=0.9,
        is_verified=False,
    )
    db.add(yahoo_map)

    # Auto-create bourse_direct mapping at confidence=1.0
    bourse_map = models.ProviderSymbolMap(
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
    import re as _re
    try:
        import requests as _requests
    except ImportError:
        raise HTTPException(status_code=500, detail="requests package not installed")

    import os as _os
    # The Bourse de Casablanca uses `valeur` parameter for ticker lookup.
    # URL template is configurable via BOURSE_STOCK_PAGE_URL env var.
    url_template = _os.environ.get(
        "BOURSE_STOCK_PAGE_URL",
        "https://www.casablanca-bourse.com/bourseweb/Detail-Valeur.aspx?Cat=3&valeur={symbol}",
    )
    bourse_url = url_template.format(symbol=symbol)

    display_name: Optional[str] = None
    sector: Optional[str] = None
    isin: Optional[str] = None

    try:
        resp = _requests.get(
            bourse_url,
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0 (compatible; QuantBot/1.0)"},
            allow_redirects=True,
        )
        if resp.status_code == 200:
            html = resp.text
            # Try to extract company name (typically in <title> or a heading element)
            title_match = _re.search(r"<title[^>]*>([^<]+)</title>", html, _re.IGNORECASE)
            if title_match:
                raw_title = title_match.group(1).strip()
                # Strip site name suffix like " - Bourse de Casablanca"
                name_part = _re.sub(r"\s*[-|–]\s*Bourse.*$", "", raw_title, flags=_re.IGNORECASE).strip()
                if name_part and name_part.upper() != symbol:
                    display_name = name_part

            # Try to extract ISIN (12-char alphanumeric starting with MA)
            isin_match = _re.search(r"\b(MA[A-Z0-9]{10})\b", html)
            if isin_match:
                isin = isin_match.group(1)

            # Try to extract sector from common patterns
            sector_match = _re.search(
                r"[Ss]ecteur[^:]*:\s*<[^>]+>([^<]+)<", html
            ) or _re.search(r"[Ss]ecteur[^:]*:\s*([^<\n]{3,50})", html)
            if sector_match:
                sector = sector_match.group(1).strip()

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
def bourse_lookup_stock(symbol: str) -> BourseStockLookupOut:
    """
    Look up a stock on the Bourse de Casablanca website by ticker symbol.
    Returns the direct page URL and any metadata that can be scraped (name, sector, ISIN).
    Also persists the URL into stock_master if the stock is already tracked.
    """
    symbol = symbol.strip().upper()
    result = _bourse_lookup(symbol)
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

    # Build per-date missing-fields lookup for partial data detection
    ohlcv_cols = ["Open", "High", "Low", "Close", "Volume"]
    available_cols = [c for c in ohlcv_cols if c in frame.columns]
    missing_fields_by_date: dict[datetime.date, list[str]] = {}
    if available_cols:
        for ts, row_data in frame[available_cols].iterrows():
            missing = [c for c in available_cols if pd.isna(row_data[c])]
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
        if state in counts:
            counts[state] += 1

        day_missing: list[str] = []
        if cursor in present_dates:
            day_missing = missing_fields_by_date.get(cursor, []) + absent_cols
            if day_missing:
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
        partial_days=partial_count,
    )


# ── OHLCV Row Mutation Endpoints ──────────────────────────────────────────────


def _update_store_metadata(db: Session, store: models.MarketDataStore, frame: pd.DataFrame) -> None:
    """Sync market_data_store row with the current state of the parquet frame."""
    store.row_count = int(len(frame))
    store.start_ts = frame.index.min().to_pydatetime() if not frame.empty else None
    store.end_ts = frame.index.max().to_pydatetime() if not frame.empty else None
    store.updated_at = datetime.datetime.now(datetime.timezone.utc)
    db.commit()


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

    source = body.source_override or stock.track_source
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

    Returns every symbol that has canonical data in market_data_store (timeframe=1D),
    plus any tracked symbols in stock_master that have no market_data_store row yet.

    Full-outer-join semantics expressed as two UNION arms:
      Arm 1: market_data_store LEFT JOIN stock_master  — all symbols with data
      Arm 2: stock_master WHERE NOT EXISTS market_data_store row — tracked, no data yet
    """
    rows = db.execute(
        text("""
            SELECT
                mds.symbol,
                sm.display_name,
                sm.isin,
                sm.sector,
                sm.is_active,
                sm.track_source,
                sm.bourse_url,
                sm.notes,
                mds.start_ts,
                mds.end_ts,
                mds.row_count,
                mds.source_provider,
                mds.data_as_of,
                (sm.symbol IS NOT NULL) AS is_tracked,
                TRUE               AS has_canonical_data
            FROM market_data_store mds
            LEFT JOIN stock_master sm ON sm.symbol = mds.symbol
            WHERE mds.timeframe = '1D'

            UNION ALL

            SELECT
                sm.symbol,
                sm.display_name,
                sm.isin,
                sm.sector,
                sm.is_active,
                sm.track_source,
                sm.bourse_url,
                sm.notes,
                NULL AS start_ts,
                NULL AS end_ts,
                NULL AS row_count,
                NULL AS source_provider,
                NULL AS data_as_of,
                TRUE AS is_tracked,
                FALSE AS has_canonical_data
            FROM stock_master sm
            WHERE NOT EXISTS (
                SELECT 1 FROM market_data_store mds2
                WHERE mds2.symbol = sm.symbol AND mds2.timeframe = '1D'
            )

            ORDER BY symbol ASC
        """)
    ).mappings().all()

    result = []
    for r in rows:
        data_as_of: datetime.date | None = r["data_as_of"]
        if isinstance(data_as_of, datetime.datetime):
            data_as_of = data_as_of.date()
        masi_info = get_masi_info(r["symbol"])
        sector = r["sector"] or (masi_info.get("sector") if masi_info else None)
        result.append(
            MarketCatalogRowOut(
                symbol=r["symbol"],
                display_name=r["display_name"],
                isin=r["isin"],
                sector=sector,
                is_active=r["is_active"],
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
                market="masi" if is_masi_ticker(r["symbol"]) else "other",
            )
        )
    return result


@router.get("/masi-tickers")
def list_masi_tickers() -> list[dict[str, str]]:
    """Return the canonical MASI ticker registry for frontend autocomplete."""
    return all_masi_tickers()


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
