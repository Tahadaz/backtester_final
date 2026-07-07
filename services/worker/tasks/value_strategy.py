from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from services.api.app import models
from services.api.app.services.value_strategy_snapshot import recompute_and_persist_value_strategy
from services.worker.db import SessionLocal


def recompute_value_strategy(
    *,
    triggered_by: str | None = None,
    batch_id: str | None = None,
    job_row_id: str | None = None,
) -> dict[str, Any]:
    """Async worker task for the six-vintage B/M+CF/P strategy snapshot. Mirrors
    services.worker.tasks.fundamental_cross_section.recompute_sfc_portfolio_backtest's
    job-status-tracking pattern exactly (SignalEngineBatchJob row updated on start/success/
    failure) rather than inventing a new job-tracking mechanism."""
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
        result = recompute_and_persist_value_strategy(db, triggered_by=triggered_by, batch_id=batch_id)
        payload = {**result, "triggered_by": triggered_by or "manual", "batch_id": batch_id, "status": "succeeded"}
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
