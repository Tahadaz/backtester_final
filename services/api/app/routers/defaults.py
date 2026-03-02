from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from redis import Redis
from rq import Queue, Retry
from rq.job import Job
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import DefaultsDiscoveryRun, StrategyDefaultSet
from ..schemas.defaults import (
    DefaultsDiscoveryLaunchResponse,
    DefaultsDiscoveryRunOut,
    SmaDiscoveryRequest,
    StrategyDefaultSetOut,
)
from ..storage import presign_get, s3_client


router = APIRouter(prefix="/defaults", tags=["defaults"])


def _redis_connection() -> Redis:
    # Keep API responsive even if Redis is degraded.
    return Redis.from_url(
        settings.REDIS_URL,
        decode_responses=False,
        socket_connect_timeout=2,
        socket_timeout=2,
        retry_on_timeout=False,
    )


def _normalize_rq_status(raw: object) -> str:
    if raw is None:
        return ""
    value = getattr(raw, "value", raw)
    return str(value).strip().lower()


def _truncate_error(raw: str | None, *, limit: int = 8000) -> str | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    return text[:limit]


def _sync_discovery_run_with_rq(
    db: Session,
    row: DefaultsDiscoveryRun,
    *,
    redis_conn: Redis | None = None,
) -> DefaultsDiscoveryRun:
    current_status = str(row.status or "").strip().lower()
    rq_job_id = str(row.rq_job_id or "").strip()
    if current_status not in {"queued", "running"} or not rq_job_id:
        return row

    redis_client = redis_conn or _redis_connection()
    try:
        job = Job.fetch(rq_job_id, connection=redis_client)
        rq_status = _normalize_rq_status(job.get_status(refresh=True))
    except Exception:
        # Keep DB state unchanged if we cannot inspect RQ.
        return row

    now = datetime.now(timezone.utc)
    changed = False

    if rq_status in {"queued", "deferred", "scheduled"}:
        if current_status != "queued":
            row.status = "queued"
            changed = True
        if not str(row.progress_stage or "").strip():
            row.progress_stage = "queued"
            changed = True
    elif rq_status in {"started", "running"}:
        if current_status != "running":
            row.status = "running"
            changed = True
        if row.progress_stage != "running":
            row.progress_stage = "running"
            changed = True
    elif rq_status in {"failed"}:
        row.status = "failed"
        row.finished_at = row.finished_at or now
        row.progress_pct = 100.0
        row.progress_stage = "failed"
        row.progress_message = "failed"
        row.last_heartbeat_at = row.last_heartbeat_at or now
        error_hint = _truncate_error(str(getattr(job, "exc_info", "") or ""))
        if error_hint:
            row.error_message = error_hint
        changed = True
    elif rq_status in {"stopped", "canceled", "cancelled"}:
        row.status = "failed"
        row.finished_at = row.finished_at or now
        row.progress_pct = 100.0
        row.progress_stage = "failed"
        row.progress_message = "canceled"
        row.error_message = row.error_message or "RQ job canceled/stopped"
        row.last_heartbeat_at = row.last_heartbeat_at or now
        changed = True
    elif rq_status in {"finished"} and current_status in {"queued", "running"}:
        # If RQ says finished but run row never reached succeeded/failed, treat as stale failed state.
        row.status = "failed"
        row.finished_at = row.finished_at or now
        row.progress_pct = 100.0
        row.progress_stage = "failed"
        row.progress_message = "stale queue status"
        row.error_message = row.error_message or "RQ job finished but defaults_discovery_run state was not finalized."
        row.last_heartbeat_at = row.last_heartbeat_at or now
        changed = True

    if changed:
        db.commit()
        db.refresh(row)
    return row


def _extract_discovery_artifact_object_keys(artifacts_json: dict | None) -> list[str]:
    if not isinstance(artifacts_json, dict):
        return []
    raw_object_keys = artifacts_json.get("object_keys")
    if not isinstance(raw_object_keys, dict):
        return []

    out: list[str] = []
    seen: set[str] = set()
    for value in raw_object_keys.values():
        key = str(value or "").strip().lstrip("/")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _delete_discovery_artifact_objects(object_keys: list[str]) -> tuple[int, int]:
    if not object_keys:
        return 0, 0
    try:
        client = s3_client()
    except Exception:
        return 0, len(object_keys)

    deleted = 0
    failed = 0
    for object_key in object_keys:
        try:
            client.delete_object(Bucket=settings.S3_BUCKET, Key=object_key)
            deleted += 1
        except Exception:
            failed += 1
    return deleted, failed


def _serialize_discovery_run(row: DefaultsDiscoveryRun) -> dict:
    artifacts_json = dict(row.artifacts_json or {})
    object_keys = dict(artifacts_json.get("object_keys") or {})
    artifact_urls = {
        str(name): presign_get(str(key), expires_seconds=600)
        for name, key in object_keys.items()
        if str(key).strip()
    }
    if artifact_urls:
        artifacts_json["urls"] = artifact_urls

    return {
        "run_id": row.id,
        "strategy_name": row.strategy_name,
        "status": row.status,
        "ticker": row.ticker,
        "dataset_id": row.dataset_id,
        "created_at": row.created_at,
        "finished_at": row.finished_at,
        "params_json": dict(row.params_json or {}),
        "results_json": dict(row.results_json or {}) if isinstance(row.results_json, dict) else row.results_json,
        "artifacts_json": artifacts_json,
        "progress_pct": row.progress_pct,
        "progress_stage": row.progress_stage,
        "progress_message": row.progress_message,
        "last_heartbeat_at": row.last_heartbeat_at,
        "rq_job_id": row.rq_job_id,
        "error_message": row.error_message,
    }


@router.post("/sma/discover", response_model=DefaultsDiscoveryLaunchResponse)
def discover_sma_defaults(
    payload: SmaDiscoveryRequest,
    db: Session = Depends(get_db),
):
    if not payload.ticker and payload.dataset_id is None:
        raise HTTPException(status_code=400, detail="ticker or dataset_id is required")
    if str(payload.strategy_name or "").strip().lower() != "sma_price":
        raise HTTPException(status_code=400, detail="Only sma_price defaults discovery is currently supported")

    normalized_ticker = str(payload.ticker).strip().upper() if payload.ticker else None
    dedupe_since = datetime.now(timezone.utc) - timedelta(hours=2)
    q_existing = (
        db.query(DefaultsDiscoveryRun)
        .filter(
            DefaultsDiscoveryRun.strategy_name == "sma_price",
            DefaultsDiscoveryRun.status.in_(("queued", "running")),
            DefaultsDiscoveryRun.created_at >= dedupe_since,
        )
        .order_by(DefaultsDiscoveryRun.created_at.desc())
    )
    if payload.dataset_id is not None:
        q_existing = q_existing.filter(DefaultsDiscoveryRun.dataset_id == payload.dataset_id)
    elif normalized_ticker:
        q_existing = q_existing.filter(DefaultsDiscoveryRun.ticker == normalized_ticker)
    existing_rows = q_existing.limit(10).all()
    redis_conn: Redis | None = None
    for existing in existing_rows:
        if redis_conn is None:
            redis_conn = _redis_connection()
        existing = _sync_discovery_run_with_rq(db, existing, redis_conn=redis_conn)
        if str(existing.status).strip().lower() in {"queued", "running"}:
            return {"run_id": existing.id, "status": existing.status, "job_id": existing.rq_job_id}

    run = DefaultsDiscoveryRun(
        strategy_name="sma_price",
        status="queued",
        ticker=normalized_ticker,
        dataset_id=payload.dataset_id,
        params_json=payload.model_dump(mode="json"),
        artifacts_json={},
        progress_pct=0.0,
        progress_stage="queued",
        progress_message="Queued in RQ",
    )
    db.add(run)
    db.flush()

    retry_policy = None
    if settings.RUN_JOB_RETRY_MAX > 0:
        retry_policy = Retry(
            max=settings.RUN_JOB_RETRY_MAX,
            interval=settings.RUN_JOB_RETRY_INTERVAL_SECONDS,
        )

    q = Queue(
        settings.DEFAULTS_DISCOVERY_QUEUE_NAME,
        connection=_redis_connection(),
        default_timeout=int(settings.RUN_JOB_TIMEOUT_SECONDS),
    )
    try:
        job = q.enqueue(
            "services.worker.tasks.defaults_discovery.execute_defaults_discovery",
            str(run.id),
            job_timeout=int(settings.RUN_JOB_TIMEOUT_SECONDS),
            result_ttl=int(settings.RUN_JOB_RESULT_TTL_SECONDS),
            failure_ttl=int(settings.RUN_JOB_FAILURE_TTL_SECONDS),
            retry=retry_policy,
        )
    except Exception as exc:
        run.status = "failed"
        run.finished_at = datetime.now(timezone.utc)
        run.error_message = f"enqueue failed: {exc}"[:8000]
        db.commit()
        raise HTTPException(status_code=503, detail="failed to enqueue defaults discovery") from exc

    run.rq_job_id = str(job.id)
    db.commit()
    return {"run_id": run.id, "status": run.status, "job_id": str(job.id)}


@router.get("/runs", response_model=list[DefaultsDiscoveryRunOut])
def list_discovery_runs(
    limit: int = Query(default=20, ge=1, le=200),
    strategy_name: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    q = db.query(DefaultsDiscoveryRun)
    if strategy_name:
        q = q.filter(DefaultsDiscoveryRun.strategy_name == str(strategy_name).strip().lower())
    rows = q.order_by(DefaultsDiscoveryRun.created_at.desc()).limit(int(limit)).all()
    redis_conn: Redis | None = None
    for row in rows:
        if str(row.status or "").strip().lower() not in {"queued", "running"}:
            continue
        if redis_conn is None:
            redis_conn = _redis_connection()
        _sync_discovery_run_with_rq(db, row, redis_conn=redis_conn)
    return [_serialize_discovery_run(row) for row in rows]


@router.get("/runs/{run_id}", response_model=DefaultsDiscoveryRunOut)
def get_discovery_run(run_id: UUID, db: Session = Depends(get_db)):
    row = db.get(DefaultsDiscoveryRun, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="defaults discovery run not found")
    if str(row.status or "").strip().lower() in {"queued", "running"}:
        _sync_discovery_run_with_rq(db, row)
    return _serialize_discovery_run(row)


@router.delete("/runs/{run_id}")
def delete_discovery_run(run_id: UUID, db: Session = Depends(get_db)):
    row = db.get(DefaultsDiscoveryRun, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="defaults discovery run not found")

    current_status = str(row.status or "").strip().lower()
    if current_status == "running":
        raise HTTPException(status_code=409, detail="cannot delete a running defaults discovery run")

    rq_job_id = str(row.rq_job_id or "").strip() or None
    queued_job_canceled = False
    if rq_job_id:
        try:
            redis_conn = _redis_connection()
            job = Job.fetch(rq_job_id, connection=redis_conn)
            if job is not None:
                job_status = str(job.get_status(refresh=True) or "").strip().lower()
                if job_status == "started":
                    raise HTTPException(status_code=409, detail="cannot delete a running defaults discovery run")
                if job_status in {"queued", "deferred", "scheduled"}:
                    job.cancel()
                    queued_job_canceled = True
        except HTTPException:
            raise
        except Exception:
            # best effort: allow deletion for stale or missing jobs
            pass

    artifacts_json = row.artifacts_json if isinstance(row.artifacts_json, dict) else None
    object_keys = _extract_discovery_artifact_object_keys(artifacts_json)
    objects_deleted, object_delete_failed = _delete_discovery_artifact_objects(object_keys)

    default_sets_unlinked = (
        db.query(StrategyDefaultSet)
        .filter(StrategyDefaultSet.source_run_id == run_id)
        .update({StrategyDefaultSet.source_run_id: None}, synchronize_session=False)
    )

    db.delete(row)
    db.commit()

    return {
        "run_id": str(run_id),
        "status": "deleted",
        "previous_status": current_status,
        "job_id": rq_job_id,
        "queued_job_canceled": bool(queued_job_canceled),
        "default_sets_unlinked": int(default_sets_unlinked or 0),
        "artifact_objects_deleted": int(objects_deleted),
        "artifact_object_delete_failed": int(object_delete_failed),
    }


@router.post("/runs/{run_id}/apply", response_model=StrategyDefaultSetOut)
def apply_discovery_defaults(
    run_id: UUID,
    horizon: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    row = db.get(DefaultsDiscoveryRun, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="defaults discovery run not found")
    if str(row.status) != "succeeded":
        raise HTTPException(status_code=409, detail="defaults discovery run must be succeeded before apply")

    results = dict(row.results_json or {}) if isinstance(row.results_json, dict) else {}
    selected_horizon = str(horizon or "").strip().lower() or None
    selected_results = results
    if selected_horizon is not None:
        horizons_map = results.get("horizons") or results.get("results_by_horizon")
        if not isinstance(horizons_map, dict):
            raise HTTPException(status_code=400, detail="run results do not include multi-horizon payload")
        horizon_payload = horizons_map.get(selected_horizon)
        if not isinstance(horizon_payload, dict):
            available = ", ".join(sorted(str(k) for k in horizons_map.keys()))
            raise HTTPException(status_code=400, detail=f"invalid horizon '{selected_horizon}'. available: {available}")
        selected_results = dict(horizon_payload)

    defaults = list(selected_results.get("defaults") or [])
    if len(defaults) != 9:
        raise HTTPException(status_code=400, detail="discovery results do not contain 9 defaults")

    selected_meta = dict(selected_results.get("meta") or {}) if isinstance(selected_results.get("meta"), dict) else {}
    selected_horizon_out = (
        str(selected_meta.get("horizon") or selected_horizon or ((results.get("meta") or {}).get("horizon") if isinstance(results.get("meta"), dict) else "")).strip().lower()
        or None
    )
    selected_horizon_label = (
        str(selected_meta.get("horizon_label") or "").strip()
        or ((results.get("meta") or {}).get("horizon_label") if isinstance(results.get("meta"), dict) else None)
    )

    default_set = StrategyDefaultSet(
        strategy_name="sma_price",
        source_run_id=row.id,
        defaults_json={
            "strategy_kind": "sma_price",
            "parameter_key": "strategy.sma_window",
            "defaults": [int(x) for x in defaults],
            "source": "defaults_discovery_run",
            "horizon": selected_horizon_out,
        },
        meta_json={
            "run_id": str(row.id),
            "created_from_status": str(row.status),
            "bucket_reports": selected_results.get("bucket_reports", []),
            "horizon": selected_horizon_out,
            "horizon_label": selected_horizon_label,
        },
    )
    db.add(default_set)
    db.commit()
    db.refresh(default_set)
    return {
        "id": int(default_set.id),
        "strategy_name": default_set.strategy_name,
        "source_run_id": default_set.source_run_id,
        "defaults_json": dict(default_set.defaults_json or {}),
        "meta_json": dict(default_set.meta_json or {}),
        "created_at": default_set.created_at,
    }


@router.get("/strategy/sma/default-sets", response_model=list[StrategyDefaultSetOut])
def list_sma_default_sets(
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(StrategyDefaultSet)
        .filter(StrategyDefaultSet.strategy_name == "sma_price")
        .order_by(StrategyDefaultSet.created_at.desc())
        .limit(int(limit))
        .all()
    )
    return [
        {
            "id": int(row.id),
            "strategy_name": row.strategy_name,
            "source_run_id": row.source_run_id,
            "defaults_json": dict(row.defaults_json or {}),
            "meta_json": dict(row.meta_json or {}),
            "created_at": row.created_at,
        }
        for row in rows
    ]


@router.get("/strategy/sma/default-sets/latest", response_model=StrategyDefaultSetOut)
def get_latest_sma_default_set(db: Session = Depends(get_db)):
    row = (
        db.query(StrategyDefaultSet)
        .filter(StrategyDefaultSet.strategy_name == "sma_price")
        .order_by(StrategyDefaultSet.created_at.desc())
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="no saved defaults set found")
    return {
        "id": int(row.id),
        "strategy_name": row.strategy_name,
        "source_run_id": row.source_run_id,
        "defaults_json": dict(row.defaults_json or {}),
        "meta_json": dict(row.meta_json or {}),
        "created_at": row.created_at,
    }
