"""Lightweight enqueue helpers for signal engine/backtest jobs.

This module intentionally avoids importing heavy compute modules so API trigger
endpoints can respond quickly.
"""
from __future__ import annotations

import logging
import uuid

from rq import Queue

from core.quant_core.signal_engine.domain import ALL_FAMILIES, VARIANT_FAMILIES
from services.api.app.models import SignalEngineBatchJob
from services.worker.config import settings
from services.worker.db import SessionLocal
from services.worker.redis_utils import connect_redis_with_fallback


logger = logging.getLogger(__name__)


def _families_for_variant(variant: str) -> list[str]:
    fams = [
        family
        for cat_families in VARIANT_FAMILIES.get(variant, VARIANT_FAMILIES["expanded"]).values()
        for family in cat_families
    ]
    return list(dict.fromkeys(fams))


def enqueue_signal_engine_for_symbol(
    symbol: str,
    horizon: str,
    variant: str = "expanded",
    triggered_by: str = "manual",
    batch_id: str | None = None,
) -> str:
    redis = connect_redis_with_fallback(settings.REDIS_URL, decode_responses=False, logger=logger)
    queue_name = settings.SIGNAL_ENGINE_QUEUE_NAME
    q = Queue(queue_name, connection=redis)
    meta = {"triggered_by": triggered_by}
    if batch_id:
        meta["batch_id"] = batch_id
    job = q.enqueue(
        "services.worker.tasks.signal_engine_batch.compute_signal_engine_for_symbol",
        symbol,
        horizon,
        variant,
        job_timeout=1800,
        meta=meta,
    )

    db = SessionLocal()
    try:
        row = SignalEngineBatchJob(
            id=uuid.uuid4(),
            symbol=symbol,
            horizon=horizon,
            variant=variant,
            job_type="signal_engine",
            status="pending",
            rq_job_id=str(job.id),
            triggered_by=triggered_by,
            batch_id=batch_id,
            total_units=len(_families_for_variant(variant)) or len(ALL_FAMILIES),
            completed_units=0,
            failed_units=0,
        )
        db.add(row)
        db.commit()
    finally:
        db.close()
    return str(job.id)


def enqueue_signal_engine_refresh_for_symbol(
    symbol: str,
    horizon: str,
    variant: str = "expanded",
    triggered_by: str = "auto_stale",
    batch_id: str | None = None,
) -> str:
    redis = connect_redis_with_fallback(settings.REDIS_URL, decode_responses=False, logger=logger)
    q = Queue(settings.SIGNAL_ENGINE_QUEUE_NAME, connection=redis)
    meta = {"triggered_by": triggered_by}
    if batch_id:
        meta["batch_id"] = batch_id
    job = q.enqueue(
        "services.worker.tasks.signal_engine_batch.refresh_signal_engine_for_symbol",
        symbol,
        horizon,
        variant,
        job_timeout=1800,
        meta=meta,
    )

    db = SessionLocal()
    try:
        row = SignalEngineBatchJob(
            id=uuid.uuid4(),
            symbol=symbol,
            horizon=horizon,
            variant=variant,
            job_type="signal_engine",
            status="pending",
            rq_job_id=str(job.id),
            triggered_by=triggered_by,
            batch_id=batch_id,
            total_units=len(_families_for_variant(variant)) or len(ALL_FAMILIES),
            completed_units=0,
            failed_units=0,
        )
        db.add(row)
        db.commit()
    finally:
        db.close()
    return str(job.id)


def enqueue_signal_backtest_for_symbol(
    symbol: str,
    horizon: str,
    variant: str = "expanded",
    window_start: str = "2026-01-01",
    window_end: str | None = None,
    mc_config: dict | None = None,
    triggered_by: str = "manual",
) -> str:
    redis = connect_redis_with_fallback(settings.REDIS_URL, decode_responses=False, logger=logger)
    queue_name = settings.SIGNAL_BACKTEST_QUEUE_NAME
    q = Queue(queue_name, connection=redis)
    rq_job_id = str(uuid.uuid4())
    job = q.enqueue(
        "services.worker.tasks.signal_backtest_batch.compute_signal_backtest_for_symbol",
        symbol,
        horizon,
        variant,
        window_start,
        window_end,
        mc_config,
        rq_job_id,
        triggered_by,
        job_id=rq_job_id,
        job_timeout=1800,
    )
    return str(job.id)
