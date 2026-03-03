from __future__ import annotations

import hashlib
import json
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
import pandas as pd
from sqlalchemy.orm import Session
from ..config import settings
from .. import models
from ..db import get_db
from ..storage import delete_object, presign_get, put_bytes
from core.quant_core.s3_keys import build_dataset_object_key

router = APIRouter(prefix="/datasets", tags=["datasets"])


def _is_placeholder_sheet_symbol(sym: str) -> bool:
    s = str(sym).strip().upper()
    if not s:
        return True
    if s in {"UPLOAD", "DATASET"}:
        return True
    if s.startswith("FEUIL"):
        tail = s[5:]
        if tail == "" or tail.isdigit():
            return True
    if s.startswith("FEUILLE"):
        tail = s[7:]
        if tail == "" or tail.isdigit():
            return True
    if s.startswith("SHEET"):
        tail = s[5:]
        if tail == "" or tail.isdigit():
            return True
    return False


def _default_dataset_meta(_: str) -> dict[str, Any]:
    return {
        "detected_symbols": [],
    }


def _safe_detected_symbols(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        sym = str(item).strip().upper()
        if not sym or _is_placeholder_sheet_symbol(sym) or sym in seen:
            continue
        out.append(sym)
        seen.add(sym)
    return out


def _detect_symbols_from_payload(*, filename: str, content_type: str, data: bytes) -> list[str]:
    ext = Path(filename).suffix.lower()
    if ext in {".xlsx", ".xls"}:
        try:
            with pd.ExcelFile(BytesIO(data)) as xls:
                out = [str(name).strip().upper() for name in xls.sheet_names if str(name).strip()]
                return _safe_detected_symbols(out)
        except Exception:
            return []

    if ext == ".csv" or "csv" in content_type.lower():
        try:
            frame = pd.read_csv(BytesIO(data), nrows=2500)
        except Exception:
            return []
        if frame.empty:
            return []
        candidates = {"symbol", "ticker", "code", "ric"}
        col_map = {str(c).strip().lower(): str(c) for c in frame.columns}
        selected = next((col_map[c] for c in candidates if c in col_map), None)
        if selected is None:
            return []
        out = frame[selected].dropna().astype(str).str.strip().str.upper().tolist()
        return _safe_detected_symbols(out)

    return []


def _serialize_dataset(row: models.Dataset) -> dict[str, Any]:
    meta = dict(row.meta_json or {})
    return {
        "dataset_id": str(row.id),
        "source": row.source,
        "filename": row.filename or row.symbol,
        "content_type": row.content_type or row.timeframe,
        "sha256": row.data_hash,
        "object_key": row.object_key,
        "size_bytes": int(row.size_bytes or 0),
        "meta": meta,
        "detected_symbols": list(meta.get("detected_symbols") or []),
        "created_at": row.created_at,
        "download_url": presign_get(str(row.object_key), expires_seconds=300) if row.object_key else None,
    }


@router.get("")
def list_datasets(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = (
        db.query(models.Dataset)
        .order_by(models.Dataset.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_serialize_dataset(row) for row in rows]


@router.get("/{dataset_id}")
def get_dataset(dataset_id: UUID, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.get(models.Dataset, dataset_id)
    if row is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    return _serialize_dataset(row)


@router.post("/upload")
def upload_dataset(
    file: UploadFile = File(...),
    metadata_json: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > settings.DATASET_MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Limit is {settings.DATASET_MAX_UPLOAD_BYTES} bytes.",
        )

    filename = Path(file.filename or "upload.bin").name

    ext = Path(filename).suffix.lower()
    if ext not in settings.DATASET_ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file extension: {ext or '<none>'}. Allowed: {', '.join(settings.DATASET_ALLOWED_EXTENSIONS)}",
        )
    content_type = file.content_type or "application/octet-stream"
    digest = hashlib.sha256(data).hexdigest()

    metadata: dict[str, Any] = _default_dataset_meta(filename)

    metadata["filename"] = filename
    metadata["content_type"] = content_type
    metadata["size_bytes"] = len(data)

    # 1) Server-side detection is source of truth (Excel sheet names / CSV ticker columns)
    server_symbols = _detect_symbols_from_payload(
        filename=filename,
        content_type=content_type,
        data=data,
    )
    if server_symbols:
        metadata["detected_symbols"] = server_symbols

    # 2) Merge client metadata_json (but do not override server-detected symbols)
    if metadata_json:
        if len(metadata_json.encode("utf-8")) > settings.DATASET_METADATA_MAX_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"metadata_json too large. Limit is {settings.DATASET_METADATA_MAX_BYTES} bytes.",
            )
        try:
            parsed = json.loads(metadata_json)
            if isinstance(parsed, dict):
                parsed_meta = dict(parsed)
                if server_symbols:
                    parsed_meta.pop("detected_symbols", None)
                metadata.update(parsed_meta)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="metadata_json must be valid JSON object") from exc

    # 3) Sanitize once at the end
    safe_symbols = _safe_detected_symbols(metadata.get("detected_symbols"))
    metadata["detected_symbols"] = safe_symbols
    primary_symbol = safe_symbols[0] if safe_symbols else "UPLOAD"


    existing = (
        db.query(models.Dataset)
        .filter(models.Dataset.data_hash == digest)
        .one_or_none()
    )
    if existing is not None and existing.object_key:
        object_key = str(existing.object_key)
    else:
        object_key = build_dataset_object_key(data_hash=digest, filename=filename)
        put_bytes(object_key=object_key, data=data, content_type=content_type)

    if existing is None:
        existing = models.Dataset(
            source="uploaded_file",
            symbol=primary_symbol,
            timeframe="1D",
            data_hash=digest,
            filename=filename,
            content_type=content_type,
            object_key=object_key,
            size_bytes=len(data),
            meta_json=metadata,
        )

        db.add(existing)
        db.commit()
        db.refresh(existing)
    else:
        existing.filename = existing.filename or filename
        existing.content_type = existing.content_type or content_type
        existing.object_key = existing.object_key or object_key
        existing.size_bytes = int(existing.size_bytes or len(data))
        merged_meta = dict(existing.meta_json or {})
        merged_meta.update(metadata)
        existing.meta_json = merged_meta
        # keep symbol/timeframe coherent for rows created by older code
        if safe_symbols:
            existing.symbol = primary_symbol
        if not existing.timeframe:
            existing.timeframe = "1D"
        db.add(existing)
        db.commit()
        db.refresh(existing)

    return {
        "dataset_id": str(existing.id),
        "sha256": digest,
        "filename": filename,
        "object_key": object_key,
        "meta": existing.meta_json or {},
        "download_url": presign_get(str(existing.object_key), expires_seconds=300) if existing.object_key else None,
    }


@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: UUID, db: Session = Depends(get_db)) -> None:
    row = db.get(models.Dataset, dataset_id)
    if row is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    if row.object_key:
        try:
            delete_object(str(row.object_key))
        except Exception:
            pass  # best-effort; still remove the DB record
    db.delete(row)
    db.commit()


@router.get("/{dataset_id}/download-url")
def get_dataset_download_url(
    dataset_id: UUID,
    expires_seconds: int = Query(default=300, ge=30, le=3600),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    row = db.get(models.Dataset, dataset_id)
    if row is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    if not row.object_key:
        raise HTTPException(status_code=404, detail="dataset object key not found")
    return {
        "dataset_id": str(row.id),
        "filename": row.filename,
        "object_key": row.object_key,
        "url": presign_get(str(row.object_key), expires_seconds=expires_seconds),
        "expires_seconds": int(expires_seconds),
    }
