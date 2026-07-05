from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from services.api.app import models
from services.api.app.services.fundamental_cross_section import recompute_and_persist_sfc, recompute_and_persist_sfc_backtest
from services.worker.db import SessionLocal


def _mark_scheduler_run(batch_id: str | None, *, status: str, meta: dict[str, Any], error: str | None = None) -> None:
    if not batch_id:
        return
    try:
        run_id = uuid.UUID(str(batch_id))
    except ValueError:
        return
    db = SessionLocal()
    try:
        row = db.get(models.SchedulerRun, run_id)
        if row is None:
            return
        row.status = status
        row.finished_at = dt.datetime.now(dt.timezone.utc)
        row.error_message = error
        row.meta_json = {**(row.meta_json or {}), **meta}
        db.commit()
    finally:
        db.close()


def recompute_fundamental_cross_section(
    *,
    as_of_date: str | None = None,
    triggered_by: str | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    db = SessionLocal()
    try:
        parsed = dt.date.fromisoformat(as_of_date) if as_of_date else dt.date.today()
        result = recompute_and_persist_sfc(db, as_of_date=parsed)
        payload = {
            **result,
            "triggered_by": triggered_by or "manual",
            "batch_id": batch_id,
            "status": "succeeded",
        }
        _mark_scheduler_run(batch_id, status="succeeded", meta=payload)
        return payload
    except Exception as exc:
        db.rollback()
        payload = {
            "status": "failed",
            "error": str(exc),
            "triggered_by": triggered_by or "manual",
            "batch_id": batch_id,
        }
        _mark_scheduler_run(batch_id, status="failed", meta=payload, error=str(exc))
        raise
    finally:
        db.close()


def recompute_sfc_portfolio_backtest(
    *,
    params: dict[str, Any] | None = None,
    triggered_by: str | None = None,
    batch_id: str | None = None,
    job_row_id: str | None = None,
) -> dict[str, Any]:
    db = SessionLocal()
    job_row = None
    try:
        if job_row_id:
            try:
                job_row = db.get(models.SignalEngineBatchJob, uuid.UUID(str(job_row_id)))
            except ValueError:
                job_row = None
            if job_row is not None:
                job_row.status = "running"
                job_row.started_at = dt.datetime.now(dt.timezone.utc)
                db.commit()
        result = recompute_and_persist_sfc_backtest(db, params=params)
        payload = {
            **result,
            "triggered_by": triggered_by or "manual",
            "batch_id": batch_id,
            "status": "succeeded",
        }
        if job_row is not None:
            job_row.status = "succeeded"
            job_row.completed_units = 1
            job_row.failed_units = 0
            job_row.finished_at = dt.datetime.now(dt.timezone.utc)
            db.commit()
        return payload
    except Exception as exc:
        db.rollback()
        if job_row_id:
            try:
                job_row = db.get(models.SignalEngineBatchJob, uuid.UUID(str(job_row_id)))
            except ValueError:
                job_row = None
            if job_row is not None:
                job_row.status = "failed"
                job_row.failed_units = 1
                job_row.error_message = str(exc)
                job_row.finished_at = dt.datetime.now(dt.timezone.utc)
                db.commit()
        raise
    finally:
        db.close()
