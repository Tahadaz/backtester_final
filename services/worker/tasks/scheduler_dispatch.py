"""Scheduler dispatch tasks.

These functions enqueue work onto the appropriate RQ queues and record the
dispatch attempt in ``scheduler_run``. They intentionally do not perform heavy
Signal Engine, WFO, or backtest computation inline.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.quant_core.signal_engine.modes import signal_mode_storage_name
from services.api.app import models
from services.api.app.services.market_universe import list_signal_universe_symbols
from services.api.app.services.scheduler_registry import (
    LEGACY_RQ_SCHEDULER_IDS,
    SCHEDULE_BY_ID,
    get_schedule_spec,
)
from services.api.app.services.weekly_recompute_policy import (
    iter_signal_engine_weekly_stale_tuples,
    iter_wfo_weekly_stale_tuples,
)
from services.worker.config import settings
from services.worker.db import SessionLocal
from services.worker.redis_utils import connect_redis_with_fallback

if TYPE_CHECKING:
    from rq import Queue

logger = logging.getLogger(__name__)

HORIZONS = ("weekly", "monthly", "quarterly")
SCHEDULER_HEARTBEAT_KEY = "ops:scheduler:heartbeat"
DASHBOARD_SNAPSHOT_JOB_TIMEOUT_SECONDS = 3600
FUNDAMENTAL_REFRESH_JOB_TIMEOUT_SECONDS = 14400
FUNDAMENTAL_REFRESH_NON_STOCK_SYMBOLS = ("INSTRUMENT", "MAJ", "MAJJ", "WORKSHEET")


def _redis() -> Redis:
    return connect_redis_with_fallback(settings.REDIS_URL, decode_responses=False, logger=logger)


def _queue(name: str) -> Queue:
    from rq import Queue

    return Queue(name, connection=_redis())


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _create_scheduler_run(db: Session, schedule_id: str, trigger_source: str) -> models.SchedulerRun:
    run = models.SchedulerRun(
        id=uuid.uuid4(),
        schedule_id=schedule_id,
        trigger_source=trigger_source,
        status="running",
        started_at=_now(),
        enqueued_jobs=0,
        meta_json={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _finish_scheduler_run(
    db: Session,
    run: models.SchedulerRun,
    *,
    status: str,
    enqueued_jobs: int,
    meta_json: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    run.status = status
    run.finished_at = _now()
    run.enqueued_jobs = int(enqueued_jobs)
    run.error_message = error_message
    run.meta_json = meta_json or {}
    db.commit()


def dispatch_schedule(schedule_id: str, *, trigger_source: str = "scheduled") -> dict[str, Any]:
    """Dispatch one registered schedule and persist an audit row."""
    spec = get_schedule_spec(schedule_id)
    db: Session = SessionLocal()
    run = _create_scheduler_run(db, spec.id, trigger_source)
    try:
        if spec.kind == "market_refresh":
            result = _dispatch_market_refresh(db)
        elif spec.kind == "dashboard_snapshot":
            result = _dispatch_dashboard_snapshot()
        elif spec.kind == "factor_monitor":
            result = _dispatch_factor_monitor()
        elif spec.kind == "factor_recalibration":
            result = _dispatch_factor_recalibration()
        elif spec.kind == "fundamental_refresh":
            result = _dispatch_fundamental_refresh(db, trigger_source=trigger_source, batch_id=str(run.id))
        elif spec.kind == "signal_engine_dispatch":
            result = _dispatch_stale_signal_engine(db, trigger_source=trigger_source, batch_id=str(run.id))
        elif spec.kind == "wfo_dispatch":
            result = _dispatch_stale_wfo(db, trigger_source=trigger_source)
        elif spec.kind == "signal_backtest_dispatch":
            result = _dispatch_signal_backtests(db, trigger_source=trigger_source)
        else:  # pragma: no cover - guarded by registry typing
            raise ValueError(f"Unsupported schedule kind {spec.kind!r}")

        enqueued_jobs = int(result.get("enqueued_jobs") or 0)
        _finish_scheduler_run(
            db,
            run,
            status="succeeded",
            enqueued_jobs=enqueued_jobs,
            meta_json={**result, "schedule_label": spec.label, "queue": spec.queue},
        )
        return {
            "run_id": str(run.id),
            "schedule_id": spec.id,
            "status": "succeeded",
            **result,
        }
    except Exception as exc:
        db.rollback()
        logger.exception("scheduler dispatch failed for %s", schedule_id)
        _finish_scheduler_run(
            db,
            run,
            status="failed",
            enqueued_jobs=0,
            meta_json={"schedule_label": spec.label, "queue": spec.queue},
            error_message=str(exc),
        )
        return {
            "run_id": str(run.id),
            "schedule_id": spec.id,
            "status": "failed",
            "error": str(exc),
            "enqueued_jobs": 0,
        }
    finally:
        db.close()


def dispatch_signal_backfill(*, trigger_source: str = "manual_backfill") -> dict[str, Any]:
    """Dispatch both stale Signal Engine and WFO work for the full signal universe."""
    results = [
        dispatch_schedule("weekly_signal_engine_dispatch", trigger_source=trigger_source),
        dispatch_schedule("weekly_wfo_dispatch", trigger_source=trigger_source),
    ]
    return {
        "status": "succeeded" if all(r.get("status") == "succeeded" for r in results) else "partial",
        "runs": results,
        "enqueued_jobs": sum(int(r.get("enqueued_jobs") or 0) for r in results),
    }


def _dispatch_market_refresh(db: Session) -> dict[str, Any]:
    active_count = int(
        db.execute(text("SELECT count(*) FROM stock_master WHERE is_active = true")).scalar() or 0
    )
    if active_count == 0:
        return {"enqueued_jobs": 0, "reason": "no_active_stocks", "symbols_total": 0}

    run = models.MarketRefreshRun(
        id=uuid.uuid4(),
        trigger_source="scheduled",
        scope="all",
        symbol=None,
        timeframe="1D",
        status="queued",
        symbols_total=active_count,
        symbols_done=0,
        symbols_failed=0,
        meta_json={"source_override": None, "include_unverified": False},
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    job = _queue(settings.MARKET_REFRESH_QUEUE_NAME).enqueue(
        "services.worker.tasks.refresh_market_data.refresh_all_tracked_symbols",
        str(run.id),
        "1D",
        None,
        False,
    )
    run.rq_job_id = str(job.id)
    db.commit()
    return {
        "enqueued_jobs": 1,
        "refresh_run_id": str(run.id),
        "rq_job_id": str(job.id),
        "symbols_total": active_count,
    }


def _dispatch_dashboard_snapshot() -> dict[str, Any]:
    job = _queue(settings.MARKET_REFRESH_QUEUE_NAME).enqueue(
        "services.worker.tasks.dashboard_snapshot.refresh_dashboard_snapshot",
        None,
        job_timeout=DASHBOARD_SNAPSHOT_JOB_TIMEOUT_SECONDS,
    )
    return {"enqueued_jobs": 1, "rq_job_id": str(job.id)}


def _dispatch_factor_monitor() -> dict[str, Any]:
    job = _queue(settings.MARKET_REFRESH_QUEUE_NAME).enqueue(
        "services.worker.tasks.factor_selection_monitor.run_factor_selection_monitor",
        job_timeout=3600,
    )
    return {"enqueued_jobs": 1, "rq_job_id": str(job.id)}


def _dispatch_factor_recalibration() -> dict[str, Any]:
    job = _queue(settings.MARKET_REFRESH_QUEUE_NAME).enqueue(
        "services.worker.tasks.factor_selection_quarterly.run_quarterly_factor_recalibration",
        job_timeout=7200,
    )
    return {"enqueued_jobs": 1, "rq_job_id": str(job.id)}


def _dispatch_fundamental_refresh(
    db: Session,
    *,
    trigger_source: str,
    batch_id: str,
) -> dict[str, Any]:
    active_count = int(
        db.query(models.StockMaster)
        .filter(
            models.StockMaster.is_active.is_(True),
            models.StockMaster.market_region == "masi",
            ~models.StockMaster.symbol.in_(FUNDAMENTAL_REFRESH_NON_STOCK_SYMBOLS),
        )
        .count()
        or 0
    )
    if active_count == 0:
        return {
            "enqueued_jobs": 0,
            "reason": "no_active_fundamental_symbols",
            "symbols_total": 0,
            "market_region": "masi",
            "source": "stockanalysis",
        }

    job = _queue(settings.MARKET_REFRESH_QUEUE_NAME).enqueue(
        "services.worker.tasks.refresh_stockanalysis_fundamentals.refresh_stockanalysis_universe",
        symbols=None,
        missing_only=False,
        triggered_by=trigger_source,
        batch_id=batch_id,
        job_timeout=FUNDAMENTAL_REFRESH_JOB_TIMEOUT_SECONDS,
    )
    return {
        "enqueued_jobs": 1,
        "rq_job_id": str(job.id),
        "symbols_total": active_count,
        "market_region": "masi",
        "source": "stockanalysis",
    }


def _dispatch_stale_signal_engine(
    db: Session,
    *,
    trigger_source: str,
    batch_id: str | None = None,
) -> dict[str, Any]:
    from services.worker.tasks.signal_enqueue import enqueue_signal_engine_for_symbol

    symbols = list_signal_universe_symbols(db)
    targets = iter_signal_engine_weekly_stale_tuples(db, symbols=symbols)
    job_ids: list[str] = []
    for symbol, horizon, variant in targets:
        job_ids.append(
            enqueue_signal_engine_for_symbol(
                symbol,
                horizon,
                variant=variant,
                triggered_by=trigger_source,
                batch_id=batch_id,
            )
        )
    return {
        "enqueued_jobs": len(job_ids),
        "symbols": len(symbols),
        "tuples": len(targets),
        "job_ids_sample": job_ids[:20],
    }


def _dispatch_stale_wfo(db: Session, *, trigger_source: str) -> dict[str, Any]:
    from services.worker.tasks.wfo_signal_batch import enqueue_wfo_full_for_symbol_horizon

    symbols = list_signal_universe_symbols(db)
    targets = iter_wfo_weekly_stale_tuples(db, symbols=symbols)
    job_ids: list[str] = []
    for symbol, horizon, variant in targets:
        job_ids.append(
            enqueue_wfo_full_for_symbol_horizon(
                symbol,
                horizon,
                variant=variant,
                triggered_by=trigger_source,
            )
        )
    return {
        "enqueued_jobs": len(job_ids),
        "symbols": len(symbols),
        "tuples": len(targets),
        "job_ids_sample": job_ids[:20],
    }


def _dispatch_signal_backtests(db: Session, *, trigger_source: str) -> dict[str, Any]:
    from services.worker.tasks.signal_backtest_batch import enqueue_signal_backtest_for_symbol

    symbols = list_signal_universe_symbols(db)
    variants = [signal_mode_storage_name("expanded")]
    job_ids: list[str] = []
    for symbol in symbols:
        for horizon in HORIZONS:
            for variant in variants:
                job_ids.append(
                    enqueue_signal_backtest_for_symbol(
                        symbol,
                        horizon,
                        variant=variant,
                        triggered_by=trigger_source,
                    )
                )
    return {
        "enqueued_jobs": len(job_ids),
        "symbols": len(symbols),
        "horizons": list(HORIZONS),
        "variants": variants,
        "job_ids_sample": job_ids[:20],
    }


def cleanup_legacy_rq_scheduler_entries() -> list[str]:
    """Remove stale rq-scheduler cron rows registered by older worker code."""
    removed: list[str] = []
    try:
        from rq_scheduler import Scheduler as RQScheduler
    except Exception:
        return removed

    redis = _redis()
    scheduler = RQScheduler(connection=redis, queue_name=settings.SIGNAL_ENGINE_QUEUE_NAME)
    existing_ids = {str(job.id) for job in scheduler.get_jobs()}
    for job_id in LEGACY_RQ_SCHEDULER_IDS:
        if job_id not in existing_ids:
            continue
        scheduler.cancel(job_id)
        removed.append(job_id)
    return removed


def list_legacy_rq_scheduler_entries() -> list[dict[str, Any]]:
    try:
        from rq_scheduler import Scheduler as RQScheduler
    except Exception:
        return []

    scheduler = RQScheduler(connection=_redis(), queue_name=settings.SIGNAL_ENGINE_QUEUE_NAME)
    rows: list[dict[str, Any]] = []
    for job, scheduled_at in scheduler.get_jobs(with_times=True):
        rows.append(
            {
                "id": str(job.id),
                "func_name": str(getattr(job, "func_name", "")),
                "origin": str(getattr(job, "origin", "")),
                "scheduled_at": scheduled_at.isoformat() if hasattr(scheduled_at, "isoformat") else str(scheduled_at),
            }
        )
    return rows


def known_schedule_ids() -> list[str]:
    return list(SCHEDULE_BY_ID)
