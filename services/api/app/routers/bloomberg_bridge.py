from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from .. import auth, models
from ..config import settings
from ..db import get_db
from ..schemas.bloomberg import (
    BloombergBatchCreateOut,
    BloombergBatchOut,
    BloombergBridgeManifest,
    BloombergSeriesOut,
    BloombergSeriesPreviewOut,
)
from ..storage import put_bytes, s3_client


bridge_router = APIRouter(
    prefix="/bridge/bloomberg",
    tags=["bloomberg-bridge"],
    dependencies=[Depends(auth.require_bloomberg_bridge_key)],
)
app_router = APIRouter(prefix="/bloomberg", tags=["bloomberg"])

_DATE_COLUMNS = ("date", "datetime", "timestamp", "time")
_SECURITY_COLUMNS = ("security", "ticker", "symbol", "instrument")
_FIELD_COLUMNS = ("field", "mnemonic", "bbg_field")
_VALUE_COLUMNS = ("value", "px", "price", "last", "close")


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")


def _safe_filename(filename: str | None) -> str:
    name = Path(filename or "bloomberg_payload.parquet").name
    return name or "bloomberg_payload.parquet"


def _lower_map(columns: list[str]) -> dict[str, str]:
    return {str(column).strip().lower(): str(column) for column in columns}


def _find_column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    columns = _lower_map([str(column) for column in frame.columns])
    for candidate in candidates:
        if candidate in columns:
            return columns[candidate]
    return None


def _parse_payload_to_frame(data: bytes, filename: str, manifest: BloombergBridgeManifest) -> pd.DataFrame:
    suffixes = [part.lower() for part in Path(filename).suffixes]
    if suffixes[-1:] == [".parquet"]:
        return pd.read_parquet(BytesIO(data))
    if suffixes[-2:] == [".jsonl", ".gz"] or suffixes[-2:] == [".ndjson", ".gz"]:
        with gzip.GzipFile(fileobj=BytesIO(data), mode="rb") as handle:
            return pd.read_json(handle, lines=True)
    if suffixes[-1:] in ([".jsonl"], [".ndjson"]):
        return pd.read_json(BytesIO(data), lines=True)
    raise HTTPException(
        status_code=415,
        detail="Bloomberg bridge uploads must be .parquet, .jsonl, .ndjson, .jsonl.gz, or .ndjson.gz",
    )


def _frame_to_parquet_bytes(frame: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    frame.to_parquet(buffer, index=True)
    return buffer.getvalue()


def _normalize_datetime_index(frame: pd.DataFrame, date_col: str) -> pd.DataFrame:
    out = frame.copy()
    out[date_col] = pd.to_datetime(out[date_col], utc=True, errors="coerce")
    out = out.dropna(subset=[date_col])
    out = out.set_index(date_col).sort_index()
    out.index.name = "timestamp"
    return out


def _overrides_hash(overrides: dict[str, Any]) -> str:
    payload = json.dumps(overrides or {}, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _series_key(security: str, field: str, periodicity: str | None, overrides_hash: str) -> str:
    payload = "|".join([security.strip().upper(), field.strip().upper(), periodicity or "", overrides_hash])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _try_load_parquet(object_key: str) -> pd.DataFrame | None:
    try:
        obj = s3_client().get_object(Bucket=settings.S3_BUCKET, Key=object_key)
        data = obj["Body"].read()
        if not data:
            return None
        return pd.read_parquet(BytesIO(data))
    except Exception:
        return None


def _stream_object(object_key: str, filename: str, media_type: str = "application/octet-stream") -> StreamingResponse:
    try:
        obj = s3_client().get_object(Bucket=settings.S3_BUCKET, Key=object_key)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Object not found: {object_key}") from exc
    payload = obj["Body"].read()
    return StreamingResponse(
        iter([payload]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _merge_series_frame(old: pd.DataFrame | None, incoming: pd.DataFrame) -> pd.DataFrame:
    if old is None or old.empty:
        merged = incoming.copy()
    else:
        merged = pd.concat([old, incoming], axis=0)
    merged = merged.sort_index()
    merged = merged[~merged.index.duplicated(keep="last")]
    return merged


def _jsonable(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _preview_rows(frame: pd.DataFrame, limit: int) -> list[dict[str, Any]]:
    tail = frame.tail(limit)
    rows: list[dict[str, Any]] = []
    for idx, row in tail.reset_index().iterrows():
        _ = idx
        rows.append({str(column): _jsonable(value) for column, value in row.items()})
    return rows


def _batch_out(row: models.BloombergIngestBatch) -> BloombergBatchOut:
    return BloombergBatchOut.model_validate(row)


def _series_out(row: models.BloombergSeries) -> BloombergSeriesOut:
    return BloombergSeriesOut.model_validate(row)


def _iter_time_series_frames(
    frame: pd.DataFrame,
    manifest: BloombergBridgeManifest,
) -> list[tuple[str, str, pd.DataFrame]]:
    if manifest.kind != "time_series" or frame.empty:
        return []

    date_col = _find_column(frame, _DATE_COLUMNS)
    if date_col is None:
        return []

    security_col = _find_column(frame, _SECURITY_COLUMNS)
    field_col = _find_column(frame, _FIELD_COLUMNS)
    value_col = _find_column(frame, _VALUE_COLUMNS)

    work = frame.copy()
    if security_col is None and len(manifest.securities) == 1:
        security_col = "__security"
        work[security_col] = manifest.securities[0]

    out: list[tuple[str, str, pd.DataFrame]] = []
    if security_col and field_col and value_col:
        for (security, field), group in work.groupby([security_col, field_col], dropna=True):
            series_frame = _normalize_datetime_index(group[[date_col, value_col]].copy(), date_col)
            if series_frame.empty:
                continue
            series_frame = series_frame.rename(columns={value_col: "Value"})
            out.append((str(security), str(field), series_frame[["Value"]]))
        return out

    if security_col:
        field_names = [field for field in manifest.fields if field in work.columns]
        if not field_names and value_col and len(manifest.fields) == 1:
            field_names = [value_col]

        for security, group in work.groupby(security_col, dropna=True):
            for field_name in field_names:
                if field_name not in group.columns:
                    continue
                series_frame = _normalize_datetime_index(group[[date_col, field_name]].copy(), date_col)
                if series_frame.empty:
                    continue
                series_frame = series_frame.rename(columns={field_name: "Value"})
                output_field = manifest.fields[0] if field_name == value_col and len(manifest.fields) == 1 else field_name
                out.append((str(security), str(output_field), series_frame[["Value"]]))
        return out

    if len(manifest.securities) == 1:
        field_names = [field for field in manifest.fields if field in work.columns]
        if not field_names and value_col and len(manifest.fields) == 1:
            field_names = [value_col]
        for field_name in field_names:
            series_frame = _normalize_datetime_index(work[[date_col, field_name]].copy(), date_col)
            if series_frame.empty:
                continue
            series_frame = series_frame.rename(columns={field_name: "Value"})
            output_field = manifest.fields[0] if field_name == value_col and len(manifest.fields) == 1 else field_name
            out.append((manifest.securities[0], str(output_field), series_frame[["Value"]]))

    return out


def _index_time_series(
    db: Session,
    *,
    batch_id: UUID,
    frame: pd.DataFrame,
    manifest: BloombergBridgeManifest,
) -> list[UUID]:
    indexed: list[UUID] = []
    overrides_hash = _overrides_hash(manifest.overrides)
    periodicity = manifest.periodicity

    for security, field, incoming in _iter_time_series_frames(frame, manifest):
        key = _series_key(security, field, periodicity, overrides_hash)
        series = db.query(models.BloombergSeries).filter(models.BloombergSeries.series_key == key).one_or_none()
        object_key = series.object_key if series else f"bloomberg/series/{key}.parquet"
        existing = _try_load_parquet(object_key) if series else None
        merged = _merge_series_frame(existing, incoming)
        put_bytes(object_key, _frame_to_parquet_bytes(merged), "application/octet-stream")

        metadata = {
            "last_batch_id": str(batch_id),
            "bloomberg_source": manifest.bloomberg_source,
            "securities": manifest.securities,
            "fields": manifest.fields,
            "overrides": manifest.overrides,
        }
        if series is None:
            series = models.BloombergSeries(
                id=uuid4(),
                series_key=key,
                last_batch_id=batch_id,
                security=security,
                field=field,
                periodicity=periodicity,
                overrides_hash=overrides_hash,
                kind=manifest.kind,
                object_key=object_key,
                metadata_json=metadata,
            )
            db.add(series)
        else:
            series.last_batch_id = batch_id
            series.metadata_json = metadata

        series.start_ts = merged.index.min().to_pydatetime() if not merged.empty else None
        series.end_ts = merged.index.max().to_pydatetime() if not merged.empty else None
        series.row_count = int(len(merged))
        indexed.append(series.id)

    return indexed


@bridge_router.get("/health")
def bridge_health(
    x_bloomberg_bridge_id: str | None = Header(default=None),
) -> dict[str, Any]:
    return {
        "ok": True,
        "bridge_id": x_bloomberg_bridge_id,
        "server_time": _utcnow().isoformat(),
        "accepted_formats": ["parquet", "jsonl", "ndjson", "jsonl.gz", "ndjson.gz"],
    }


@bridge_router.post("/batches", response_model=BloombergBatchCreateOut, status_code=201)
def create_bloomberg_batch(
    manifest_json: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> BloombergBatchCreateOut:
    try:
        raw_manifest = json.loads(manifest_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"manifest_json is not valid JSON: {exc}") from exc
    manifest = BloombergBridgeManifest.model_validate(raw_manifest)
    if manifest.schema_version != 1:
        raise HTTPException(status_code=422, detail="Only Bloomberg bridge manifest schema_version=1 is supported")

    payload = file.file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Empty Bloomberg bridge payload")
    if len(payload) > settings.BLOOMBERG_BRIDGE_MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Bloomberg bridge payload is too large")

    digest = hashlib.sha256(payload).hexdigest()
    if manifest.data_sha256 and manifest.data_sha256.lower() != digest:
        raise HTTPException(status_code=422, detail="Payload SHA256 does not match manifest data_sha256")

    existing = (
        db.query(models.BloombergIngestBatch)
        .filter(
            models.BloombergIngestBatch.bridge_id == manifest.bridge_id,
            models.BloombergIngestBatch.request_id == manifest.request_id,
        )
        .one_or_none()
    )
    if existing is not None:
        if existing.data_sha256 == digest:
            existing_series = (
                db.query(models.BloombergSeries.id)
                .filter(models.BloombergSeries.last_batch_id == existing.id)
                .all()
            )
            return BloombergBatchCreateOut(
                batch=_batch_out(existing),
                duplicate=True,
                indexed_series=[row[0] for row in existing_series],
            )
        raise HTTPException(
            status_code=409,
            detail="request_id already exists for this bridge_id with a different payload hash",
        )

    filename = _safe_filename(file.filename)
    frame = _parse_payload_to_frame(payload, filename, manifest)
    if manifest.row_count is not None and int(manifest.row_count) != int(len(frame)):
        raise HTTPException(status_code=422, detail="Payload row count does not match manifest row_count")

    batch_id = uuid4()
    raw_object_key = f"bloomberg/raw/{batch_id}/{filename}"
    manifest_object_key = f"bloomberg/raw/{batch_id}/manifest.json"
    normalized_object_key = f"bloomberg/normalized/{batch_id}.parquet"

    put_bytes(raw_object_key, payload, file.content_type or "application/octet-stream")
    put_bytes(manifest_object_key, _json_bytes(raw_manifest), "application/json")
    put_bytes(normalized_object_key, _frame_to_parquet_bytes(frame), "application/octet-stream")

    batch = models.BloombergIngestBatch(
        id=batch_id,
        bridge_id=manifest.bridge_id,
        request_id=manifest.request_id,
        bloomberg_source=manifest.bloomberg_source,
        kind=manifest.kind,
        status="succeeded",
        raw_object_key=raw_object_key,
        manifest_object_key=manifest_object_key,
        normalized_object_key=normalized_object_key,
        filename=filename,
        content_type=file.content_type,
        size_bytes=len(payload),
        data_sha256=digest,
        row_count=int(len(frame)),
        series_count=0,
        manifest_json=manifest.model_dump(mode="json"),
    )
    db.add(batch)
    db.flush()

    indexed_series = _index_time_series(db, batch_id=batch_id, frame=frame, manifest=manifest)
    batch.series_count = len(indexed_series)
    db.commit()
    db.refresh(batch)

    return BloombergBatchCreateOut(batch=_batch_out(batch), duplicate=False, indexed_series=indexed_series)


@app_router.get("/health")
def app_bloomberg_health() -> dict[str, Any]:
    return {"ok": True, "server_time": _utcnow().isoformat()}


@app_router.get("/batches", response_model=list[BloombergBatchOut])
def list_bloomberg_batches(
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[BloombergBatchOut]:
    rows = (
        db.query(models.BloombergIngestBatch)
        .order_by(models.BloombergIngestBatch.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_batch_out(row) for row in rows]


@app_router.get("/batches/{batch_id}", response_model=BloombergBatchOut)
def get_bloomberg_batch(batch_id: UUID, db: Session = Depends(get_db)) -> BloombergBatchOut:
    row = db.query(models.BloombergIngestBatch).filter(models.BloombergIngestBatch.id == batch_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Bloomberg batch not found")
    return _batch_out(row)


@app_router.get("/batches/{batch_id}/raw")
def download_bloomberg_batch_raw(batch_id: UUID, db: Session = Depends(get_db)) -> StreamingResponse:
    row = db.query(models.BloombergIngestBatch).filter(models.BloombergIngestBatch.id == batch_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Bloomberg batch not found")
    return _stream_object(
        row.raw_object_key,
        row.filename or f"bloomberg-{batch_id}.parquet",
        row.content_type or "application/octet-stream",
    )


@app_router.get("/batches/{batch_id}/normalized")
def download_bloomberg_batch_normalized(batch_id: UUID, db: Session = Depends(get_db)) -> StreamingResponse:
    row = db.query(models.BloombergIngestBatch).filter(models.BloombergIngestBatch.id == batch_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Bloomberg batch not found")
    if not row.normalized_object_key:
        raise HTTPException(status_code=404, detail="Bloomberg normalized object not found")
    return _stream_object(row.normalized_object_key, f"bloomberg-normalized-{batch_id}.parquet")


@app_router.get("/series", response_model=list[BloombergSeriesOut])
def list_bloomberg_series(
    security: str | None = Query(default=None),
    field: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[BloombergSeriesOut]:
    query = db.query(models.BloombergSeries)
    if security:
        query = query.filter(models.BloombergSeries.security.ilike(f"%{security.strip()}%"))
    if field:
        query = query.filter(models.BloombergSeries.field.ilike(f"%{field.strip()}%"))
    rows = (
        query.order_by(models.BloombergSeries.updated_at.desc(), models.BloombergSeries.security.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_series_out(row) for row in rows]


@app_router.get("/series/{series_id}/preview", response_model=BloombergSeriesPreviewOut)
def preview_bloomberg_series(
    series_id: UUID,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> BloombergSeriesPreviewOut:
    row = db.query(models.BloombergSeries).filter(models.BloombergSeries.id == series_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Bloomberg series not found")
    frame = _try_load_parquet(row.object_key)
    if frame is None:
        raise HTTPException(status_code=404, detail="Bloomberg series object not found")
    preview = _preview_rows(frame, limit)
    return BloombergSeriesPreviewOut(
        series=_series_out(row),
        columns=[str(column) for column in frame.reset_index().columns],
        rows=preview,
    )


@app_router.get("/series/{series_id}/download")
def download_bloomberg_series(series_id: UUID, db: Session = Depends(get_db)) -> StreamingResponse:
    row = db.query(models.BloombergSeries).filter(models.BloombergSeries.id == series_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Bloomberg series not found")
    safe_security = "".join(ch if ch.isalnum() else "_" for ch in row.security).strip("_")
    safe_field = "".join(ch if ch.isalnum() else "_" for ch in row.field).strip("_")
    filename = f"bloomberg-series-{safe_security}-{safe_field}.parquet"
    return _stream_object(row.object_key, filename)
