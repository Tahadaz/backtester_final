from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Query
import pandas as pd
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..db import get_db
from ..queue import get_queue
from ..storage import put_bytes, presign_get, s3_client

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


def _load_close_series_from_store(*, object_key: str) -> pd.Series:
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


def _dataset_has_symbol(dataset_row: models.Dataset, symbol: str) -> bool:
    target = str(symbol or "").strip().upper()
    if not target:
        return False

    if str(getattr(dataset_row, "symbol", "") or "").strip().upper() == target:
        return True

    meta = dataset_row.meta_json if isinstance(dataset_row.meta_json, dict) else {}
    detected = _normalize_symbols(list(meta.get("detected_symbols") or []))
    return target in set(detected)


def _find_latest_dataset_for_symbol(*, db: Session, symbol: str) -> models.Dataset | None:
    rows = (
        db.query(models.Dataset)
        .order_by(models.Dataset.created_at.desc())
        .limit(250)
        .all()
    )
    for row in rows:
        if _dataset_has_symbol(row, symbol):
            return row
    return None


def _dataset_object_key(dataset_row: models.Dataset) -> str:
    object_key = str(dataset_row.object_key or "").strip()
    if object_key:
        return object_key

    filename = str(dataset_row.filename or "").strip()
    data_hash = str(dataset_row.data_hash or "").strip()
    if filename and data_hash:
        return f"datasets/{data_hash}/{filename}"
    raise ValueError("dataset row is missing object_key and (data_hash, filename)")


def _load_close_series_from_dataset(*, dataset_row: models.Dataset, symbol: str) -> pd.Series:
    object_key = _dataset_object_key(dataset_row)
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
        "Close",
        "close",
        "Clôture",
        "Cloture",
        "CLOTURE",
        "ClÃ´ture",
        "Adj Close",
        "AdjClose",
        "adj_close",
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

    meta: dict[str, Any] = {"filename": filename, "content_type": content_type, "size_bytes": len(data)}
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
