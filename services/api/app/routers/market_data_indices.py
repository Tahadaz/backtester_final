from __future__ import annotations

import datetime
import hashlib
import json
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..db import get_db
from ..market_data_loader import load_ohlcv_for_symbol
from ..market_holidays import get_holiday_info
from ..queue import get_market_refresh_queue
from ..storage import presign_get, put_bytes, s3_client
from ..schemas.market_data import (
    AvailabilityCalendarDayOut,
    AvailabilityCalendarOut,
    MarketRefreshRunOut,
    OhlcvBarOut,
    OhlcvHistoryOut,
    OhlcvPreviewOut,
)
from ..schemas.market_data_indices import (
    IndexCatalogRowOut,
    IndexMasterCreate,
    IndexMasterOut,
)

router = APIRouter(prefix="/market-data/indices", tags=["market-data-indices"])


# ── Helpers ──────────────────────────────────────────────────────────────────

def _today_utc() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date()


def _business_days_ago(d: datetime.date, n: int) -> datetime.date:
    count = 0
    current = d
    while count < n:
        current -= datetime.timedelta(days=1)
        if current.weekday() < 5:
            count += 1
    return current


def _is_stale(data_as_of: datetime.date | None) -> bool:
    if data_as_of is None:
        return True
    return data_as_of < _business_days_ago(_today_utc(), 2)


def _get_index_store_or_404(
    db: Session, symbol: str, timeframe: str = "1D"
) -> models.MarketDataStore:
    store = (
        db.query(models.MarketDataStore)
        .filter(
            models.MarketDataStore.symbol == symbol,
            models.MarketDataStore.timeframe == timeframe,
            models.MarketDataStore.asset_class == "index",
        )
        .one_or_none()
    )
    if not store:
        raise HTTPException(status_code=404, detail=f"No index data found for '{symbol}'")
    return store


def _frame_to_ohlcv_bars(frame: pd.DataFrame) -> list[OhlcvBarOut]:
    bars = []
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


def _refresh_run_to_out(run: models.MarketRefreshRun) -> MarketRefreshRunOut:
    return MarketRefreshRunOut(
        id=run.id,
        trigger_source=run.trigger_source,
        scope=run.scope,
        symbol=run.symbol,
        timeframe=run.timeframe,
        status=run.status,
        rq_job_id=run.rq_job_id,
        symbols_total=run.symbols_total,
        symbols_done=run.symbols_done,
        symbols_failed=run.symbols_failed,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        error_message=run.error_message,
    )


# ── Excel upload ──────────────────────────────────────────────────────────────

@router.post("/excel", status_code=202)
def upload_indices_excel(
    file: UploadFile = File(...),
    metadata_json: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Upload an Excel file with Moroccan index OHLCV data."""
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > settings.DATASET_MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large")

    filename = Path(file.filename or "indices_upload.xlsx").name
    if Path(filename).suffix.lower() not in {".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail="Only .xlsx/.xls files are supported")

    content_type = file.content_type or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    digest = hashlib.sha256(data).hexdigest()
    object_key = f"datasets/{digest}/{filename}"

    put_bytes(object_key=object_key, data=data, content_type=content_type)

    meta: dict[str, Any] = {
        "filename": filename,
        "content_type": content_type,
        "size_bytes": len(data),
        "upload_kind": "indices",
    }
    if metadata_json:
        try:
            parsed = json.loads(metadata_json)
            if isinstance(parsed, dict):
                meta.update(parsed)
        except Exception:
            raise HTTPException(status_code=400, detail="metadata_json must be valid JSON object")

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

    from ..queue import get_queue
    q = get_queue()
    job = q.enqueue(
        "services.worker.tasks.ingest_market_data.ingest_excel_indices_to_store",
        str(ds.id),
    )

    return {
        "dataset_id": str(ds.id),
        "job_id": job.id,
        "raw_object_key": object_key,
    }


@router.get("/uploads/{dataset_id}/status")
def get_indices_ingest_status(dataset_id: UUID) -> dict[str, Any]:
    """Poll-friendly endpoint: returns the ingest report when ready."""
    object_key = f"market_data/uploads/{dataset_id}/ingest_report.json"
    s3 = s3_client()
    try:
        obj = s3.get_object(Bucket=settings.S3_BUCKET, Key=object_key)
        report = json.loads(obj["Body"].read())
        return {"status": "done", "report": report}
    except Exception:
        return {"status": "processing"}


# ── Index master CRUD ─────────────────────────────────────────────────────────

@router.get("", response_model=list[IndexMasterOut])
def list_indices(db: Session = Depends(get_db)) -> list[IndexMasterOut]:
    """Return all index_master rows."""
    rows = (
        db.query(models.IndexMaster)
        .order_by(models.IndexMaster.symbol.asc())
        .all()
    )
    return [
        IndexMasterOut(
            symbol=r.symbol,
            display_name=r.display_name,
            family=r.family,
            is_active=r.is_active,
            source=r.source,
            notes=r.notes,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.post("", response_model=IndexMasterOut, status_code=201)
def create_index(body: IndexMasterCreate, db: Session = Depends(get_db)) -> IndexMasterOut:
    """Manually register an index (auto-created by ingestion in the normal path)."""
    symbol = body.symbol.strip().upper()
    existing = db.query(models.IndexMaster).filter(models.IndexMaster.symbol == symbol).one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"Index '{symbol}' already registered")
    idx = models.IndexMaster(
        symbol=symbol,
        display_name=body.display_name,
        family=body.family,
        source=body.source,
        notes=body.notes,
    )
    db.add(idx)
    db.commit()
    db.refresh(idx)
    return IndexMasterOut(
        symbol=idx.symbol,
        display_name=idx.display_name,
        family=idx.family,
        is_active=idx.is_active,
        source=idx.source,
        notes=idx.notes,
        created_at=idx.created_at,
        updated_at=idx.updated_at,
    )


@router.delete("/{symbol}", status_code=204)
def delete_index(symbol: str, db: Session = Depends(get_db)) -> None:
    symbol = symbol.strip().upper()
    idx = db.query(models.IndexMaster).filter(models.IndexMaster.symbol == symbol).one_or_none()
    if not idx:
        raise HTTPException(status_code=404, detail=f"Index '{symbol}' not found")
    db.delete(idx)
    db.commit()


# ── Catalog (data-page view) ──────────────────────────────────────────────────

@router.get("/catalog", response_model=list[IndexCatalogRowOut])
def get_indices_catalog(db: Session = Depends(get_db)) -> list[IndexCatalogRowOut]:
    """
    Unified view for the Indices tab on the data page.
    Full-outer-join: all symbols with data in market_data_store (asset_class='index')
    plus tracked indices in index_master with no data yet.
    """
    rows = db.execute(
        text("""
            SELECT
                mds.symbol,
                im.display_name,
                im.family,
                im.is_active,
                im.source,
                mds.start_ts,
                mds.end_ts,
                mds.row_count,
                mds.source_provider,
                mds.data_as_of,
                (im.symbol IS NOT NULL) AS is_tracked,
                TRUE AS has_canonical_data
            FROM market_data_store mds
            LEFT JOIN index_master im ON im.symbol = mds.symbol
            WHERE mds.timeframe = '1D' AND mds.asset_class = 'index'

            UNION ALL

            SELECT
                im.symbol,
                im.display_name,
                im.family,
                im.is_active,
                im.source,
                NULL AS start_ts,
                NULL AS end_ts,
                NULL AS row_count,
                NULL AS source_provider,
                NULL AS data_as_of,
                TRUE AS is_tracked,
                FALSE AS has_canonical_data
            FROM index_master im
            WHERE NOT EXISTS (
                SELECT 1 FROM market_data_store mds2
                WHERE mds2.symbol = im.symbol
                  AND mds2.timeframe = '1D'
                  AND mds2.asset_class = 'index'
            )

            ORDER BY symbol ASC
        """)
    ).mappings().all()

    result = []
    for r in rows:
        data_as_of: datetime.date | None = r["data_as_of"]
        if isinstance(data_as_of, datetime.datetime):
            data_as_of = data_as_of.date()
        result.append(
            IndexCatalogRowOut(
                symbol=r["symbol"],
                display_name=r["display_name"],
                family=r["family"],
                is_active=r["is_active"],
                source=r["source"],
                start_ts=r["start_ts"],
                end_ts=r["end_ts"],
                row_count=r["row_count"],
                source_provider=r["source_provider"],
                data_as_of=data_as_of,
                is_stale=_is_stale(data_as_of),
                is_tracked=bool(r["is_tracked"]),
                has_canonical_data=bool(r["has_canonical_data"]),
            )
        )
    return result


# ── OHLCV endpoints ───────────────────────────────────────────────────────────

@router.get("/{symbol}/ohlcv-preview", response_model=OhlcvPreviewOut)
def get_index_ohlcv_preview(
    symbol: str,
    timeframe: str = Query(default="1D"),
    limit: int = Query(default=30, ge=1, le=500),
    db: Session = Depends(get_db),
) -> OhlcvPreviewOut:
    symbol = symbol.strip().upper()
    store = _get_index_store_or_404(db, symbol, timeframe)
    try:
        frame = load_ohlcv_for_symbol(db, symbol, timeframe)
        bars = _frame_to_ohlcv_bars(frame.tail(limit))
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


@router.get("/{symbol}/ohlcv-history", response_model=OhlcvHistoryOut)
def get_index_ohlcv_history(
    symbol: str,
    timeframe: str = Query(default="1D"),
    db: Session = Depends(get_db),
) -> OhlcvHistoryOut:
    symbol = symbol.strip().upper()
    store = _get_index_store_or_404(db, symbol, timeframe)
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


@router.get("/{symbol}/availability-calendar", response_model=AvailabilityCalendarOut)
def get_index_availability_calendar(
    symbol: str,
    timeframe: str = Query(default="1D"),
    db: Session = Depends(get_db),
) -> AvailabilityCalendarOut:
    symbol = symbol.strip().upper()
    _get_index_store_or_404(db, symbol, timeframe)
    try:
        frame = load_ohlcv_for_symbol(db, symbol, timeframe).sort_index()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if frame.empty:
        raise HTTPException(status_code=404, detail=f"No data for {symbol}")

    first_date = frame.index.min().date()
    last_date = frame.index.max().date()
    present_dates = {ts.date() for ts in frame.index}

    days: list[AvailabilityCalendarDayOut] = []
    current = first_date
    while current <= last_date:
        has_data = current in present_dates
        holiday_info = get_holiday_info(current)
        if holiday_info:
            state = "holiday"
        elif current.weekday() >= 5:
            state = "weekend"
        elif has_data:
            state = "present"
        else:
            state = "missing"
        days.append(
            AvailabilityCalendarDayOut(
                date=current.isoformat(),
                state=state,
                has_data=has_data,
                holiday_name=holiday_info.get("name") if holiday_info else None,
            )
        )
        current += datetime.timedelta(days=1)

    return AvailabilityCalendarOut(symbol=symbol, timeframe=timeframe, days=days)


# ── Refresh ───────────────────────────────────────────────────────────────────

@router.post("/refresh", status_code=202)
def trigger_indices_refresh(db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Trigger a live refresh of all active indices from the Casablanca Bourse page.
    Returns a refresh_run_id to poll for status.
    """
    active_count = (
        db.query(models.IndexMaster)
        .filter(models.IndexMaster.is_active == True)  # noqa: E712
        .count()
    )

    run = models.MarketRefreshRun(
        id=uuid4(),
        trigger_source="manual",
        scope="indices",
        symbol=None,
        timeframe="1D",
        status="queued",
        symbols_total=active_count,
        symbols_done=0,
        symbols_failed=0,
        meta_json={"source": "casablanca_bourse"},
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    q = get_market_refresh_queue()
    job = q.enqueue(
        "services.worker.tasks.refresh_market_data.refresh_all_tracked_indices",
        str(run.id),
    )
    run.rq_job_id = job.id
    db.commit()

    return {
        "refresh_run_id": str(run.id),
        "status": "queued",
        "symbols_total": active_count,
        "job_id": job.id,
    }


@router.get("/refresh/{refresh_run_id}", response_model=MarketRefreshRunOut)
def get_indices_refresh_run(
    refresh_run_id: UUID, db: Session = Depends(get_db)
) -> MarketRefreshRunOut:
    run = (
        db.query(models.MarketRefreshRun)
        .filter(models.MarketRefreshRun.id == refresh_run_id)
        .one_or_none()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Refresh run not found")
    return _refresh_run_to_out(run)
