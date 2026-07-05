from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from services.api.app import models
from services.api.app.services.fundamental_cross_section import recompute_and_persist_sfc
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
