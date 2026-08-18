from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import re
import secrets
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse
from sqlalchemy.orm import Session

from core.quant_core.cross_asset.security_master import bloomberg_candidates
from core.quant_core.cross_asset.universes import is_global_universe, resolve as resolve_universe

from .. import auth, models
from ..bloomberg_connector import (
    bridge_source,
    powershell_one_liner,
    python_one_liner,
    render_powershell_connector,
    render_python_connector,
)
from ..config import settings
from ..db import get_db
from ..masi_tickers import all_masi_tickers
from ..schemas.bloomberg import (
    BloombergBatchCreateOut,
    BloombergBatchOut,
    BloombergBridgeStatusOut,
    BloombergBridgeManifest,
    BloombergConnectorInstructions,
    BloombergCredentialOut,
    DEFAULT_BLOOMBERG_OHLCV_FIELDS,
    BloombergEnrollIn,
    BloombergEnrollOut,
    BloombergEnrollmentCreateIn,
    BloombergEnrollmentCreateOut,
    BloombergEnrollmentOut,
    BloombergHeartbeatIn,
    BloombergJobClaimOut,
    BloombergJobCreateIn,
    BloombergJobEventOut,
    BloombergJobOut,
    BloombergJobUpdateIn,
    BloombergSeriesOut,
    BloombergSeriesPreviewOut,
)
from ..storage import put_bytes, s3_client


APP_NAME = "Moroccan Market Signal Backtester"


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def require_bridge_credential(
    x_bloomberg_bridge_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> None:
    """Accept either the shared bridge key or a per-terminal enrolled credential."""
    if auth.matches_static_bloomberg_bridge_key(x_bloomberg_bridge_key):
        return
    if x_bloomberg_bridge_key:
        credential = (
            db.query(models.BloombergBridgeCredential)
            .filter(
                models.BloombergBridgeCredential.key_hash == _hash_secret(x_bloomberg_bridge_key),
                models.BloombergBridgeCredential.revoked_at.is_(None),
            )
            .one_or_none()
        )
        if credential is not None:
            credential.last_used_at = _utcnow()
            db.commit()
            return
    raise HTTPException(status_code=401, detail="missing or invalid Bloomberg bridge key")


bridge_router = APIRouter(
    prefix="/bridge/bloomberg",
    tags=["bloomberg-bridge"],
    dependencies=[Depends(require_bridge_credential)],
)
app_router = APIRouter(prefix="/bloomberg", tags=["bloomberg"])
# Reached directly from the Bloomberg computer (outside the browser session), so
# it carries no app API key. Every route authenticates on the enrollment token.
connect_router = APIRouter(prefix="/bridge/bloomberg", tags=["bloomberg-bridge"])

_DATE_COLUMNS = ("date", "datetime", "timestamp", "time")
_SECURITY_COLUMNS = ("security", "ticker", "symbol", "instrument")
_FIELD_COLUMNS = ("field", "mnemonic", "bbg_field")
_VALUE_COLUMNS = ("value", "px", "price", "last", "close")
_BRIDGE_STALE_AFTER_SECONDS = 90
_JOB_LEASE_SECONDS = 300
_ACTIVE_JOB_STATUSES = {"queued", "leased", "running"}
_TERMINAL_JOB_STATUSES = {"succeeded", "failed", "cancelled", "expired"}


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _coerce_aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value


def _is_stale(last_seen_at: dt.datetime | None) -> bool:
    seen = _coerce_aware(last_seen_at)
    if seen is None:
        return True
    return (_utcnow() - seen).total_seconds() > _BRIDGE_STALE_AFTER_SECONDS


def _job_out(row: models.BloombergJob) -> BloombergJobOut:
    return BloombergJobOut.model_validate(row)


def _event_out(row: models.BloombergJobEvent) -> BloombergJobEventOut:
    return BloombergJobEventOut.model_validate(row)


def _bridge_status_out(row: models.BloombergBridgeStatus) -> BloombergBridgeStatusOut:
    return BloombergBridgeStatusOut(
        bridge_id=row.bridge_id,
        status=row.status,
        capabilities_json=row.capabilities_json or {},
        preflight_json=row.preflight_json or {},
        active_job_id=row.active_job_id,
        error_message=row.error_message,
        last_seen_at=row.last_seen_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        is_stale=_is_stale(row.last_seen_at),
    )


def _append_job_event(
    db: Session,
    *,
    job_id: UUID,
    bridge_id: str | None,
    status: str | None,
    message: str | None,
    payload: dict[str, Any] | None = None,
) -> None:
    db.add(
        models.BloombergJobEvent(
            id=uuid4(),
            job_id=job_id,
            bridge_id=bridge_id,
            status=status,
            message=message,
            payload_json=payload or {},
        )
    )


def _symbol_to_bloomberg_candidates(symbol: str, universe: str = "masi") -> list[str]:
    """Ordered Bloomberg tickers to probe for one symbol.

    Global universes resolve through the security master; Moroccan and ad-hoc
    universes keep the historical ``MA``/``MC`` suffix guess. Resolution is
    universe-scoped rather than registry-first so that MASI job specs stay
    byte-identical -- several canonical ids (``C``, ``S``, ``W``, ``G``, ``Z``)
    are short enough to collide with an equity ticker.
    """
    clean = symbol.strip().upper()
    if not clean:
        return []
    if is_global_universe(universe):
        return bloomberg_candidates(clean)
    return [f"{clean} MA Equity", f"{clean} MC Equity"]


def _build_job_spec(body: BloombergJobCreateIn) -> dict[str, Any]:
    symbols = list(body.symbols)
    if body.universe == "masi" and not symbols:
        symbols = [str(row.get("symbol") or "").strip().upper() for row in all_masi_tickers()]
        symbols = [symbol for symbol in symbols if symbol]
    elif is_global_universe(body.universe) and not symbols:
        symbols = list(resolve_universe(body.universe))

    security_candidates = [
        {"symbol": symbol, "candidates": _symbol_to_bloomberg_candidates(symbol, body.universe)}
        for symbol in symbols
        if symbol
    ]
    securities = list(body.securities)
    if not securities:
        securities = [item["candidates"][0] for item in security_candidates if item["candidates"]]

    fields = body.fields or DEFAULT_BLOOMBERG_OHLCV_FIELDS.copy()
    options = {
        "daily_chunk_days": 365,
        "hourly_chunk_days": 5,
        "minute_chunk_days": 1,
        "probe_days": 5,
        **(body.options or {}),
    }
    return {
        "schema_version": 1,
        "job_type": body.job_type,
        "universe": body.universe,
        "mode": body.mode,
        "frequency": body.frequency,
        "symbols": symbols,
        "securities": securities,
        "security_candidates": security_candidates,
        "fields": fields,
        "start_date": body.start_date,
        "end_date": body.end_date,
        "apply_to_market_data": body.apply_to_market_data,
        "options": options,
        "created_at": _utcnow().isoformat(),
    }


def _merge_json(existing: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing or {})
    merged.update(incoming or {})
    return merged


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


def _delete_objects_best_effort(object_keys: list[str | None]) -> tuple[int, int]:
    keys = [str(key).strip() for key in object_keys if str(key or "").strip()]
    if not keys:
        return 0, 0
    deleted = 0
    failed = 0
    try:
        client = s3_client()
    except Exception:
        return 0, len(keys)
    for key in keys:
        try:
            client.delete_object(Bucket=settings.S3_BUCKET, Key=key)
            deleted += 1
        except Exception:
            failed += 1
    return deleted, failed


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


@bridge_router.post("/heartbeat", response_model=BloombergBridgeStatusOut)
def bridge_heartbeat(body: BloombergHeartbeatIn, db: Session = Depends(get_db)) -> BloombergBridgeStatusOut:
    now = _utcnow()
    row = (
        db.query(models.BloombergBridgeStatus)
        .filter(models.BloombergBridgeStatus.bridge_id == body.bridge_id)
        .one_or_none()
    )
    if row is None:
        row = models.BloombergBridgeStatus(
            bridge_id=body.bridge_id,
            status=body.status,
            capabilities_json=body.capabilities,
            preflight_json=body.preflight,
            active_job_id=body.active_job_id,
            error_message=body.error_message,
            last_seen_at=now,
        )
        db.add(row)
    else:
        row.status = body.status
        row.capabilities_json = body.capabilities
        row.preflight_json = body.preflight
        row.active_job_id = body.active_job_id
        row.error_message = body.error_message
        row.last_seen_at = now
    db.commit()
    db.refresh(row)
    return _bridge_status_out(row)


def _release_expired_job_leases(db: Session, now: dt.datetime) -> None:
    expired = (
        db.query(models.BloombergJob)
        .filter(
            models.BloombergJob.status.in_(["leased", "running"]),
            models.BloombergJob.lease_expires_at.isnot(None),
            models.BloombergJob.lease_expires_at < now,
        )
        .all()
    )
    for job in expired:
        _append_job_event(
            db,
            job_id=job.id,
            bridge_id=job.bridge_id,
            status="expired",
            message="Bridge lease expired; job returned to queue",
            payload={"previous_status": job.status},
        )
        job.status = "queued"
        job.bridge_id = None
        job.lease_expires_at = None


@bridge_router.get("/jobs/next", response_model=BloombergJobClaimOut)
def claim_next_bloomberg_job(
    bridge_id: str = Query(..., min_length=1, max_length=128),
    lease_seconds: int = Query(default=_JOB_LEASE_SECONDS, ge=30, le=3600),
    db: Session = Depends(get_db),
) -> BloombergJobClaimOut:
    now = _utcnow()
    _release_expired_job_leases(db, now)
    job = (
        db.query(models.BloombergJob)
        .filter(models.BloombergJob.status == "queued")
        .order_by(models.BloombergJob.created_at.asc())
        .first()
    )
    if job is None:
        status = (
            db.query(models.BloombergBridgeStatus)
            .filter(models.BloombergBridgeStatus.bridge_id == bridge_id)
            .one_or_none()
        )
        if status is not None:
            status.status = "online"
            status.active_job_id = None
            status.last_seen_at = now
            db.commit()
        return BloombergJobClaimOut(job=None, server_time=now)

    job.status = "leased"
    job.bridge_id = bridge_id
    job.lease_expires_at = now + dt.timedelta(seconds=lease_seconds)
    job.progress_json = _merge_json(job.progress_json, {"claimed_at": now.isoformat()})
    _append_job_event(
        db,
        job_id=job.id,
        bridge_id=bridge_id,
        status="leased",
        message="Job claimed by Bloomberg bridge",
        payload={"lease_seconds": lease_seconds},
    )
    status = (
        db.query(models.BloombergBridgeStatus)
        .filter(models.BloombergBridgeStatus.bridge_id == bridge_id)
        .one_or_none()
    )
    if status is None:
        status = models.BloombergBridgeStatus(
            bridge_id=bridge_id,
            status="busy",
            active_job_id=job.id,
            last_seen_at=now,
        )
        db.add(status)
    else:
        status.status = "busy"
        status.active_job_id = job.id
        status.last_seen_at = now
    db.commit()
    db.refresh(job)
    return BloombergJobClaimOut(job=_job_out(job), server_time=now)


@bridge_router.post("/jobs/{job_id}/status", response_model=BloombergJobOut)
def update_bloomberg_job_status(
    job_id: UUID,
    body: BloombergJobUpdateIn,
    x_bloomberg_bridge_id: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> BloombergJobOut:
    now = _utcnow()
    job = db.query(models.BloombergJob).filter(models.BloombergJob.id == job_id).one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Bloomberg job not found")
    bridge_id = x_bloomberg_bridge_id or job.bridge_id
    if job.bridge_id and bridge_id and job.bridge_id != bridge_id:
        raise HTTPException(status_code=403, detail="Bloomberg job is leased to another bridge")

    if bridge_id:
        job.bridge_id = bridge_id
    if body.status:
        job.status = body.status
    if body.progress:
        job.progress_json = _merge_json(job.progress_json, body.progress)
    if body.result:
        job.result_json = _merge_json(job.result_json, body.result)
    if body.error_message:
        job.error_message = body.error_message
    if job.status == "running" and job.started_at is None:
        job.started_at = now
    if job.status == "running":
        job.lease_expires_at = now + dt.timedelta(seconds=_JOB_LEASE_SECONDS)
    if job.status in _TERMINAL_JOB_STATUSES:
        job.completed_at = now
        job.lease_expires_at = None

    _append_job_event(
        db,
        job_id=job.id,
        bridge_id=bridge_id,
        status=body.status,
        message=body.message,
        payload={"progress": body.progress, "result": body.result},
    )
    if bridge_id:
        bridge = (
            db.query(models.BloombergBridgeStatus)
            .filter(models.BloombergBridgeStatus.bridge_id == bridge_id)
            .one_or_none()
        )
        if bridge is not None:
            bridge.last_seen_at = now
            bridge.active_job_id = None if job.status in _TERMINAL_JOB_STATUSES else job.id
            bridge.status = "online" if job.status in _TERMINAL_JOB_STATUSES else "busy"
            if body.error_message:
                bridge.error_message = body.error_message

    db.commit()
    db.refresh(job)
    return _job_out(job)


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


@app_router.get("/bridges", response_model=list[BloombergBridgeStatusOut])
def list_bloomberg_bridges(
    limit: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[BloombergBridgeStatusOut]:
    rows = (
        db.query(models.BloombergBridgeStatus)
        .order_by(models.BloombergBridgeStatus.last_seen_at.desc())
        .limit(limit)
        .all()
    )
    return [_bridge_status_out(row) for row in rows]


@app_router.post(
    "/jobs",
    response_model=BloombergJobOut,
    status_code=201,
    dependencies=[Depends(auth.rate_limit_trigger)],
)
def create_bloomberg_job(
    body: BloombergJobCreateIn,
    x_requested_by: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> BloombergJobOut:
    spec = _build_job_spec(body)
    job = models.BloombergJob(
        id=uuid4(),
        job_type=body.job_type,
        status="queued",
        requested_by=(body.requested_by or x_requested_by or "app")[:128],
        spec_json=spec,
        progress_json={"queued_at": _utcnow().isoformat()},
        result_json={},
    )
    db.add(job)
    db.flush()
    _append_job_event(
        db,
        job_id=job.id,
        bridge_id=None,
        status="queued",
        message="Bloomberg job queued from app",
        payload={"spec": spec},
    )
    db.commit()
    db.refresh(job)
    return _job_out(job)


@app_router.get("/jobs", response_model=list[BloombergJobOut])
def list_bloomberg_jobs(
    status: str | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[BloombergJobOut]:
    query = db.query(models.BloombergJob)
    if status:
        query = query.filter(models.BloombergJob.status == status)
    rows = (
        query.order_by(models.BloombergJob.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_job_out(row) for row in rows]


@app_router.get("/jobs/{job_id}", response_model=BloombergJobOut)
def get_bloomberg_job(job_id: UUID, db: Session = Depends(get_db)) -> BloombergJobOut:
    row = db.query(models.BloombergJob).filter(models.BloombergJob.id == job_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Bloomberg job not found")
    return _job_out(row)


@app_router.get("/jobs/{job_id}/events", response_model=list[BloombergJobEventOut])
def list_bloomberg_job_events(
    job_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[BloombergJobEventOut]:
    exists = db.query(models.BloombergJob.id).filter(models.BloombergJob.id == job_id).one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="Bloomberg job not found")
    rows = (
        db.query(models.BloombergJobEvent)
        .filter(models.BloombergJobEvent.job_id == job_id)
        .order_by(models.BloombergJobEvent.created_at.asc())
        .limit(limit)
        .all()
    )
    return [_event_out(row) for row in rows]


@app_router.post(
    "/jobs/{job_id}/cancel",
    response_model=BloombergJobOut,
    dependencies=[Depends(auth.rate_limit_trigger)],
)
def cancel_bloomberg_job(job_id: UUID, db: Session = Depends(get_db)) -> BloombergJobOut:
    job = db.query(models.BloombergJob).filter(models.BloombergJob.id == job_id).one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Bloomberg job not found")
    if job.status in _TERMINAL_JOB_STATUSES:
        return _job_out(job)
    job.status = "cancelled"
    job.completed_at = _utcnow()
    job.lease_expires_at = None
    _append_job_event(
        db,
        job_id=job.id,
        bridge_id=job.bridge_id,
        status="cancelled",
        message="Bloomberg job cancelled from app",
    )
    db.commit()
    db.refresh(job)
    return _job_out(job)


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


@app_router.delete("/batches/{batch_id}", dependencies=[Depends(auth.rate_limit_trigger)])
def delete_bloomberg_batch(batch_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.query(models.BloombergIngestBatch).filter(models.BloombergIngestBatch.id == batch_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Bloomberg batch not found")

    referenced = (
        db.query(models.BloombergSeries.id)
        .filter(models.BloombergSeries.last_batch_id == batch_id)
        .limit(1)
        .first()
    )
    if referenced is not None:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete Bloomberg batch while indexed series reference it. Delete indexed series first.",
        )

    objects_deleted, object_delete_failed = _delete_objects_best_effort(
        [row.raw_object_key, row.manifest_object_key, row.normalized_object_key]
    )
    db.delete(row)
    db.commit()
    return {
        "status": "deleted",
        "batch_id": str(batch_id),
        "objects_deleted": objects_deleted,
        "object_delete_failed": object_delete_failed,
    }


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


@app_router.delete("/series/{series_id}", dependencies=[Depends(auth.rate_limit_trigger)])
def delete_bloomberg_series(series_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.query(models.BloombergSeries).filter(models.BloombergSeries.id == series_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Bloomberg series not found")

    batch_id = row.last_batch_id
    objects_deleted, object_delete_failed = _delete_objects_best_effort([row.object_key])
    batch = db.query(models.BloombergIngestBatch).filter(models.BloombergIngestBatch.id == batch_id).one_or_none()
    if batch is not None and batch.series_count:
        batch.series_count = max(0, int(batch.series_count) - 1)
    db.delete(row)
    db.commit()
    return {
        "status": "deleted",
        "series_id": str(series_id),
        "last_batch_id": str(batch_id),
        "objects_deleted": objects_deleted,
        "object_delete_failed": object_delete_failed,
    }


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


# ---------------------------------------------------------------------------
# Self-service terminal enrollment
#
# The whole point of this block: an operator sitting at the Bloomberg computer
# opens the deployed app in a browser, clicks once, and gets a pasteable command
# that already contains this app's URL, a single-use token and the terminal name.
# Nothing is transported by hand.
# ---------------------------------------------------------------------------


_BRIDGE_ID_SAFE = re.compile(r"[^a-z0-9-]+")


def _slugify_bridge_id(value: str) -> str:
    slug = _BRIDGE_ID_SAFE.sub("-", value.strip().lower()).strip("-")
    return slug[:96] or "bloomberg-terminal"


def _public_endpoint(request: Request) -> str:
    configured = settings.PUBLIC_APP_URL
    if configured:
        return configured
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "https").split(",")[0].strip()
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.url.netloc
    ).split(",")[0].strip()
    return f"{proto}://{host}".rstrip("/")


def _enrollment_status(row: models.BloombergBridgeEnrollment, now: dt.datetime) -> str:
    if row.revoked_at is not None:
        return "revoked"
    if row.consumed_at is not None:
        return "connected"
    if _coerce_aware(row.expires_at) is not None and _coerce_aware(row.expires_at) < now:
        return "expired"
    return "pending"


def _enrollment_out(row: models.BloombergBridgeEnrollment) -> BloombergEnrollmentOut:
    out = BloombergEnrollmentOut.model_validate(row)
    out.status = _enrollment_status(row, _utcnow())
    return out


def _unique_bridge_id(db: Session, base: str) -> str:
    candidate = base
    suffix = 2
    while (
        db.query(models.BloombergBridgeCredential.id)
        .filter(
            models.BloombergBridgeCredential.bridge_id == candidate,
            models.BloombergBridgeCredential.revoked_at.is_(None),
        )
        .first()
        is not None
    ):
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


def _instructions(
    *, endpoint: str, token: str, bridge_id: str, expires_at: dt.datetime
) -> BloombergConnectorInstructions:
    return BloombergConnectorInstructions(
        endpoint=endpoint,
        bridge_id=bridge_id,
        expires_at=expires_at,
        powershell_command=powershell_one_liner(endpoint=endpoint, token=token),
        jupyter_command=python_one_liner(endpoint=endpoint, token=token),
        powershell_download_url=f"{endpoint}/bridge/bloomberg/connect.ps1?token={token}&download=1",
        python_download_url=f"{endpoint}/bridge/bloomberg/connect.py?token={token}&download=1",
    )


@app_router.post(
    "/enrollments",
    response_model=BloombergEnrollmentCreateOut,
    status_code=201,
    dependencies=[Depends(auth.rate_limit_trigger)],
)
def create_bloomberg_enrollment(
    body: BloombergEnrollmentCreateIn,
    request: Request,
    x_app_user_email: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> BloombergEnrollmentCreateOut:
    now = _utcnow()
    base_id = _slugify_bridge_id(body.bridge_id or body.label or "bloomberg-terminal")
    bridge_id = _unique_bridge_id(db, base_id)
    token = f"bbe_{secrets.token_urlsafe(32)}"
    expires_at = now + dt.timedelta(minutes=body.ttl_minutes)

    row = models.BloombergBridgeEnrollment(
        id=uuid4(),
        bridge_id=bridge_id,
        label=(body.label or None),
        token_prefix=token[:12],
        token_hash=_hash_secret(token),
        created_by=(x_app_user_email or "app")[:200],
        expires_at=expires_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    endpoint = _public_endpoint(request)
    return BloombergEnrollmentCreateOut(
        enrollment=_enrollment_out(row),
        enroll_token=token,
        instructions=_instructions(
            endpoint=endpoint, token=token, bridge_id=bridge_id, expires_at=expires_at
        ),
    )


@app_router.get("/enrollments", response_model=list[BloombergEnrollmentOut])
def list_bloomberg_enrollments(
    limit: int = Query(default=25, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[BloombergEnrollmentOut]:
    rows = (
        db.query(models.BloombergBridgeEnrollment)
        .order_by(models.BloombergBridgeEnrollment.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_enrollment_out(row) for row in rows]


@app_router.post("/enrollments/{enrollment_id}/revoke", response_model=BloombergEnrollmentOut)
def revoke_bloomberg_enrollment(
    enrollment_id: UUID, db: Session = Depends(get_db)
) -> BloombergEnrollmentOut:
    row = (
        db.query(models.BloombergBridgeEnrollment)
        .filter(models.BloombergBridgeEnrollment.id == enrollment_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Bloomberg enrollment not found")
    if row.revoked_at is None:
        row.revoked_at = _utcnow()
        db.commit()
        db.refresh(row)
    return _enrollment_out(row)


@app_router.get("/credentials", response_model=list[BloombergCredentialOut])
def list_bloomberg_credentials(
    include_revoked: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> list[BloombergCredentialOut]:
    query = db.query(models.BloombergBridgeCredential)
    if not include_revoked:
        query = query.filter(models.BloombergBridgeCredential.revoked_at.is_(None))
    rows = query.order_by(models.BloombergBridgeCredential.created_at.desc()).all()
    return [BloombergCredentialOut.model_validate(row) for row in rows]


@app_router.post("/credentials/{credential_id}/revoke", response_model=BloombergCredentialOut)
def revoke_bloomberg_credential(
    credential_id: UUID, db: Session = Depends(get_db)
) -> BloombergCredentialOut:
    row = (
        db.query(models.BloombergBridgeCredential)
        .filter(models.BloombergBridgeCredential.id == credential_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Bloomberg credential not found")
    if row.revoked_at is None:
        row.revoked_at = _utcnow()
        db.commit()
        db.refresh(row)
    return BloombergCredentialOut.model_validate(row)


# --- Routes the Bloomberg computer calls directly (enrollment-token auth) ----


def _resolve_enrollment(db: Session, token: str | None) -> models.BloombergBridgeEnrollment:
    if not token or not token.strip():
        raise HTTPException(status_code=401, detail="Enrollment token is required")
    row = (
        db.query(models.BloombergBridgeEnrollment)
        .filter(models.BloombergBridgeEnrollment.token_hash == _hash_secret(token))
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=401, detail="Unknown enrollment token")
    if row.revoked_at is not None:
        raise HTTPException(status_code=403, detail="Enrollment token was revoked")
    expires_at = _coerce_aware(row.expires_at)
    if expires_at is not None and expires_at < _utcnow():
        raise HTTPException(
            status_code=403,
            detail="Enrollment token has expired. Generate a new connection code in the app.",
        )
    return row


def _script_response(body: str, *, filename: str, download: bool) -> PlainTextResponse:
    headers = {"Cache-Control": "no-store"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return PlainTextResponse(body, media_type="text/plain; charset=utf-8", headers=headers)


@connect_router.get("/connect.ps1", response_class=PlainTextResponse)
def bloomberg_connect_powershell(
    request: Request,
    token: str = Query(...),
    download: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    enrollment = _resolve_enrollment(db, token)
    body = render_powershell_connector(
        endpoint=_public_endpoint(request),
        token=token,
        bridge_id=enrollment.bridge_id,
        app_name=APP_NAME,
    )
    return _script_response(body, filename="connect-bloomberg.ps1", download=download)


@connect_router.get("/connect.py", response_class=PlainTextResponse)
def bloomberg_connect_python(
    request: Request,
    token: str = Query(...),
    download: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    enrollment = _resolve_enrollment(db, token)
    body = render_python_connector(
        endpoint=_public_endpoint(request),
        token=token,
        bridge_id=enrollment.bridge_id,
        app_name=APP_NAME,
    )
    return _script_response(body, filename="connect_bloomberg.py", download=download)


@connect_router.get("/connector/bridge.py", response_class=PlainTextResponse)
def bloomberg_connector_source(
    token: str = Query(...),
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    _resolve_enrollment(db, token)
    try:
        body = bridge_source()
    except OSError as exc:  # pragma: no cover - only if the image is built wrong
        raise HTTPException(status_code=500, detail="Bridge listener source is unavailable") from exc
    return _script_response(body, filename="bridge.py", download=False)


@connect_router.post("/enroll", response_model=BloombergEnrollOut)
def enroll_bloomberg_bridge(
    body: BloombergEnrollIn,
    request: Request,
    db: Session = Depends(get_db),
) -> BloombergEnrollOut:
    """Exchange a single-use enrollment token for a long-lived terminal key."""
    enrollment = _resolve_enrollment(db, body.token)
    now = _utcnow()

    # A re-run of the connector within the token's validity window rotates the key
    # rather than failing, so an interrupted first attempt is recoverable.
    if enrollment.credential_id is not None:
        previous = (
            db.query(models.BloombergBridgeCredential)
            .filter(models.BloombergBridgeCredential.id == enrollment.credential_id)
            .one_or_none()
        )
        if previous is not None and previous.revoked_at is None:
            previous.revoked_at = now

    bridge_key = f"bbk_{secrets.token_urlsafe(36)}"
    label_bits = [part for part in (enrollment.label, body.hostname) if part]
    credential = models.BloombergBridgeCredential(
        id=uuid4(),
        bridge_id=enrollment.bridge_id,
        label=(" / ".join(label_bits) or None),
        key_prefix=bridge_key[:12],
        key_hash=_hash_secret(bridge_key),
        created_by=enrollment.created_by,
    )
    db.add(credential)
    db.flush()

    enrollment.consumed_at = enrollment.consumed_at or now
    enrollment.credential_id = credential.id

    status_row = (
        db.query(models.BloombergBridgeStatus)
        .filter(models.BloombergBridgeStatus.bridge_id == enrollment.bridge_id)
        .one_or_none()
    )
    if status_row is None:
        db.add(
            models.BloombergBridgeStatus(
                bridge_id=enrollment.bridge_id,
                status="online",
                capabilities_json={},
                preflight_json={},
                last_seen_at=now,
            )
        )
    else:
        status_row.status = "online"
        status_row.last_seen_at = now
        status_row.error_message = None

    db.commit()
    return BloombergEnrollOut(
        bridge_id=enrollment.bridge_id,
        bridge_key=bridge_key,
        endpoint_hint=_public_endpoint(request),
    )
