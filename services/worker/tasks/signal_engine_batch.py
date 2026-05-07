"""Batch task: compute and persist Signal Engine results."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from core.quant_core.signal_engine.domain import ALL_FAMILIES, VARIANT_FAMILIES
from services.api.app.models import SignalEngineBatchJob
from services.api.app.services.weekly_recompute_policy import iter_signal_engine_weekly_stale_tuples
from services.api.app.services.signal_engine_persistence import (
    DEFAULT_COOLDOWN_BARS,
    DEFAULT_COST_BPS,
    DEFAULT_TIMEFRAME,
    full_rebuild_from_pipeline,
    refresh_from_persisted_reps,
)
from services.worker.config import settings
from services.worker.db import SessionLocal
from services.worker.redis_utils import connect_redis_with_fallback

logger = logging.getLogger(__name__)

HORIZONS = ("short", "medium", "long")


def _active_symbols(db: Session) -> list[str]:
    from services.api.app.models import StockMaster

    return [row.symbol for row in db.query(StockMaster).filter_by(is_active=True).all()]


def _resolve_rq_meta_value(key: str) -> str | None:
    try:
        from rq import get_current_job

        job = get_current_job()
        if job is None:
            return None
        meta = job.meta if isinstance(job.meta, dict) else {}
        value = str(meta.get(key) or "").strip()
        return value or None
    except Exception:
        return None


def _resolve_triggered_by_from_rq_meta() -> str | None:
    return _resolve_rq_meta_value("triggered_by")


def _resolve_batch_id_from_rq_meta() -> str | None:
    return _resolve_rq_meta_value("batch_id")


def _families_for_variant(variant: str) -> list[str]:
    fams = [
        family
        for cat_families in VARIANT_FAMILIES.get(variant, VARIANT_FAMILIES["expanded"]).values()
        for family in cat_families
    ]
    return list(dict.fromkeys(fams))


def run_signal_engine_batch(*, now: datetime | None = None) -> dict:
    """Compute full signal-engine persisted rows only for weekly-stale tuples."""
    db: Session = SessionLocal()
    try:
        targets = iter_signal_engine_weekly_stale_tuples(
            db,
            symbols=_active_symbols(db),
            now=now,
        )
    finally:
        db.close()

    results = {"total": 0, "succeeded": 0, "failed": 0}
    for symbol, horizon, variant in targets:
        result = compute_signal_engine_for_symbol(symbol, horizon, variant=variant)
        if str(result.get("status") or "").lower() in {"succeeded", "partial", "no_signal"}:
            results["succeeded"] += 1
        else:
            results["failed"] += 1
        results["total"] += 1
    return results


def enqueue_signal_engine_for_symbol(
    symbol: str,
    horizon: str,
    variant: str = "expanded",
    triggered_by: str = "manual",
    batch_id: str | None = None,
) -> str:
    """Enqueue a full signal-engine compute for one tuple and persist a pending row."""
    from rq import Queue

    redis = connect_redis_with_fallback(settings.REDIS_URL, decode_responses=False, logger=logger)
    q = Queue(settings.SIGNAL_ENGINE_QUEUE_NAME, connection=redis)
    meta = {"triggered_by": triggered_by}
    if batch_id:
        meta["batch_id"] = batch_id
    job = q.enqueue(
        compute_signal_engine_for_symbol,
        symbol,
        horizon,
        variant,
        job_timeout=1800,
        meta=meta,
    )

    db: Session = SessionLocal()
    try:
        _upsert_batch_job(
            db,
            symbol,
            horizon,
            variant,
            job_type="signal_engine",
            status="pending",
            rq_job_id=str(job.id),
            triggered_by=triggered_by,
            batch_id=batch_id,
            total_units=len(_families_for_variant(variant)) or len(ALL_FAMILIES),
        )
        db.commit()
    finally:
        db.close()

    return str(job.id)


def enqueue_signal_engine_refresh_for_symbol(
    symbol: str,
    horizon: str,
    variant: str = "expanded",
    triggered_by: str = "market_refresh",
    batch_id: str | None = None,
) -> str:
    """Enqueue representative-only refresh for one tuple and persist a pending row."""
    from rq import Queue

    redis = connect_redis_with_fallback(settings.REDIS_URL, decode_responses=False, logger=logger)
    q = Queue(settings.SIGNAL_ENGINE_QUEUE_NAME, connection=redis)
    meta = {"triggered_by": triggered_by}
    if batch_id:
        meta["batch_id"] = batch_id
    job = q.enqueue(
        refresh_signal_engine_for_symbol,
        symbol,
        horizon,
        variant,
        job_timeout=1800,
        meta=meta,
    )

    db: Session = SessionLocal()
    try:
        _upsert_batch_job(
            db,
            symbol,
            horizon,
            variant,
            job_type="signal_engine",
            status="pending",
            rq_job_id=str(job.id),
            triggered_by=triggered_by,
            batch_id=batch_id,
            total_units=len(_families_for_variant(variant)) or len(ALL_FAMILIES),
        )
        db.commit()
    finally:
        db.close()

    return str(job.id)


def compute_signal_engine_for_symbol(
    symbol: str,
    horizon: str,
    variant: str = "expanded",
) -> dict:
    """RQ task wrapper around full persisted rebuild."""
    if str(variant or "").strip().lower() == "factor_x_ta":
        from services.worker.tasks.factor_x_ta_batch import compute_factor_x_ta_for_symbol

        result = compute_factor_x_ta_for_symbol(symbol, horizon)
        result["variant"] = "factor_x_ta"
        result["mode"] = "factor_x_ta_dedicated"
        return result

    db: Session = SessionLocal()
    started = time.perf_counter()
    job_row: SignalEngineBatchJob | None = None
    try:
        triggered_by = _resolve_triggered_by_from_rq_meta()
        batch_id = _resolve_batch_id_from_rq_meta()
        job_row = _upsert_batch_job(
            db,
            symbol,
            horizon,
            variant,
            job_type="signal_engine",
            status="running",
            triggered_by=triggered_by,
            batch_id=batch_id,
            total_units=len(_families_for_variant(variant)) or len(ALL_FAMILIES),
        )
        db.commit()

        result = full_rebuild_from_pipeline(
            db,
            symbol=symbol,
            horizon=horizon,
            variant=variant,
            timeframe=DEFAULT_TIMEFRAME,
            cost_bps=DEFAULT_COST_BPS,
            cooldown_bars=DEFAULT_COOLDOWN_BARS,
        )
        db.commit()

        _status = str(result.get("status") or "failed")
        _first_error = result.get("first_error") or (
            f"failed: completed={result.get('completed')} failed={result.get('failed')} (no per-family detail)"
            if _status == "failed"
            else None
        )
        _finish_job(
            db,
            job_row,
            status=_status,
            error_message=_first_error,
            completed_units=int(result.get("completed") or 0),
            failed_units=int(result.get("failed") or 0),
        )
        db.commit()

        return {
            "symbol": symbol,
            "horizon": horizon,
            "variant": variant,
            "status": _status,
            "completed": int(result.get("completed") or 0),
            "failed": int(result.get("failed") or 0),
            "elapsed": round(time.perf_counter() - started, 2),
            "mode": str(result.get("mode") or "full_rebuild"),
            "error": _first_error,
        }
    except Exception as exc:
        logger.exception("Signal engine full rebuild failed for %s/%s/%s: %s", symbol, horizon, variant, exc)
        db.rollback()
        if job_row is not None:
            _finish_job(db, job_row, "failed", error_message=str(exc), completed_units=0, failed_units=1)
            db.commit()
        return {
            "symbol": symbol,
            "horizon": horizon,
            "variant": variant,
            "status": "failed",
            "error": str(exc),
            "elapsed": round(time.perf_counter() - started, 2),
            "mode": "full_rebuild",
        }
    finally:
        db.close()


def refresh_signal_engine_for_symbol(
    symbol: str,
    horizon: str,
    variant: str = "expanded",
) -> dict:
    """RQ task wrapper around representative-only refresh (with full fallback)."""
    if str(variant or "").strip().lower() == "factor_x_ta":
        from services.worker.tasks.factor_x_ta_batch import compute_factor_x_ta_for_symbol

        result = compute_factor_x_ta_for_symbol(symbol, horizon)
        result["variant"] = "factor_x_ta"
        result["mode"] = "factor_x_ta_dedicated"
        return result

    db: Session = SessionLocal()
    started = time.perf_counter()
    job_row: SignalEngineBatchJob | None = None
    try:
        triggered_by = _resolve_triggered_by_from_rq_meta()
        batch_id = _resolve_batch_id_from_rq_meta()
        job_row = _upsert_batch_job(
            db,
            symbol,
            horizon,
            variant,
            job_type="signal_engine",
            status="running",
            triggered_by=triggered_by,
            batch_id=batch_id,
            total_units=len(_families_for_variant(variant)) or len(ALL_FAMILIES),
        )
        db.commit()

        result = refresh_from_persisted_reps(
            db,
            symbol=symbol,
            horizon=horizon,
            variant=variant,
            timeframe=DEFAULT_TIMEFRAME,
            cost_bps=DEFAULT_COST_BPS,
            cooldown_bars=DEFAULT_COOLDOWN_BARS,
            fallback_to_full_rebuild=True,
        )
        db.commit()

        _status = str(result.get("status") or "failed")
        _first_error = result.get("first_error") or (
            f"failed: completed={result.get('completed')} failed={result.get('failed')} (no per-family detail)"
            if _status == "failed"
            else None
        )
        _finish_job(
            db,
            job_row,
            status=_status,
            error_message=_first_error,
            completed_units=int(result.get("completed") or 0),
            failed_units=int(result.get("failed") or 0),
        )
        db.commit()

        return {
            "symbol": symbol,
            "horizon": horizon,
            "variant": variant,
            "status": _status,
            "completed": int(result.get("completed") or 0),
            "failed": int(result.get("failed") or 0),
            "elapsed": round(time.perf_counter() - started, 2),
            "mode": str(result.get("mode") or "refresh_from_reps"),
            "error": _first_error,
        }
    except Exception as exc:
        logger.exception("Signal engine refresh failed for %s/%s/%s: %s", symbol, horizon, variant, exc)
        db.rollback()
        if job_row is not None:
            _finish_job(db, job_row, "failed", error_message=str(exc), completed_units=0, failed_units=1)
            db.commit()
        return {
            "symbol": symbol,
            "horizon": horizon,
            "variant": variant,
            "status": "failed",
            "error": str(exc),
            "elapsed": round(time.perf_counter() - started, 2),
            "mode": "refresh_from_reps",
        }
    finally:
        db.close()


def _upsert_batch_job(
    db: Session,
    symbol: str,
    horizon: str,
    variant: str,
    *,
    job_type: str,
    status: str,
    rq_job_id: str | None = None,
    triggered_by: str | None = None,
    batch_id: str | None = None,
    total_units: int | None = None,
    completed_units: int = 0,
    failed_units: int = 0,
) -> SignalEngineBatchJob:
    row = SignalEngineBatchJob(
        id=uuid.uuid4(),
        symbol=symbol,
        horizon=horizon,
        variant=variant,
        job_type=job_type,
        status=status,
        rq_job_id=rq_job_id,
        triggered_by=triggered_by,
        batch_id=batch_id,
        total_units=total_units,
        completed_units=completed_units,
        failed_units=failed_units,
        started_at=datetime.now(timezone.utc) if status == "running" else None,
    )
    db.add(row)
    return row


def _finish_job(
    db: Session,
    job_row: SignalEngineBatchJob,
    status: str,
    error_message: str | None = None,
    completed_units: int | None = None,
    failed_units: int | None = None,
) -> None:
    del db  # kept for signature compatibility
    job_row.status = status
    job_row.finished_at = datetime.now(timezone.utc)
    if error_message:
        job_row.error_message = error_message
    if completed_units is not None:
        job_row.completed_units = completed_units
    if failed_units is not None:
        job_row.failed_units = failed_units
