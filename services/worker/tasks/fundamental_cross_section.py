from __future__ import annotations

import datetime as dt
from typing import Any

from services.api.app.services.fundamental_cross_section import recompute_and_persist_sfc
from services.worker.db import SessionLocal


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
        return {
            **result,
            "triggered_by": triggered_by or "manual",
            "batch_id": batch_id,
            "status": "succeeded",
        }
    except Exception as exc:
        db.rollback()
        return {
            "status": "failed",
            "error": str(exc),
            "triggered_by": triggered_by or "manual",
            "batch_id": batch_id,
        }
    finally:
        db.close()
