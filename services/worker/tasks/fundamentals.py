from __future__ import annotations

from uuid import UUID

from services.api.app import models
from services.api.app.services.fundamentals import execute_import_run
from services.worker.config import settings
from services.worker.db import SessionLocal
from services.worker.storage import s3_client


def execute_fundamental_import(import_id: str) -> dict[str, object]:
    """RQ task: parse the uploaded workbook and compute v2 fundamentals."""

    db = SessionLocal()
    try:
        run_id = UUID(str(import_id))
        row = db.get(models.FundamentalImport, run_id)
        if row is None:
            raise ValueError(f"fundamental import {import_id} not found")
        if not row.object_key:
            raise ValueError(f"fundamental import {import_id} has no object key")
        payload = s3_client().get_object(Bucket=settings.S3_BUCKET, Key=row.object_key)["Body"].read()
        imported = execute_import_run(db, import_id=run_id, payload=payload)
        return {
            "import_id": str(imported.id),
            "status": imported.status,
            "symbols": int(imported.latest_snapshot_count or 0),
            "quality_issues": int(imported.quality_issue_count or 0),
        }
    finally:
        db.close()
