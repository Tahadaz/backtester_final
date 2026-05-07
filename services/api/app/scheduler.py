"""Daily 20:00 market refresh scheduler (Africa/Casablanca timezone)."""
from __future__ import annotations

import logging
import os
from uuid import uuid4

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import text

from .db import _ensure_session_factory
from .queue import get_market_refresh_queue
from . import models

log = logging.getLogger(__name__)


def _enqueue_daily_refresh() -> None:
    """Create a MarketRefreshRun and enqueue the RQ job - same logic as POST /market-data/refresh."""
    Session = _ensure_session_factory()
    db = Session()
    try:
        active_count = db.execute(
            text("SELECT count(*) FROM stock_master WHERE is_active = true")
        ).scalar() or 0
        if active_count == 0:
            log.info("scheduler: no active stocks, skipping refresh")
            return

        run = models.MarketRefreshRun(
            id=uuid4(),
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

        q = get_market_refresh_queue()
        job = q.enqueue(
            "services.worker.tasks.refresh_market_data.refresh_all_tracked_symbols",
            str(run.id), "1D", None, False,
        )
        run.rq_job_id = job.id
        db.commit()
        log.info("scheduler: enqueued daily refresh run=%s job=%s symbols=%d", run.id, job.id, active_count)
    except Exception:
        db.rollback()
        log.exception("scheduler: failed to enqueue daily refresh")
    finally:
        db.close()


def _enqueue_factor_monitor() -> None:
    """Enqueue the nightly parameter drift monitor (Stage 4) for all active macro factors."""
    try:
        from services.api.app.queue import _get_macro_ingest_queue
        q = _get_macro_ingest_queue()
        job = q.enqueue("services.worker.tasks.factor_selection_monitor.run_factor_selection_monitor")
        log.info("scheduler: enqueued factor selection monitor job=%s", job.id)
    except Exception:
        log.exception("scheduler: failed to enqueue factor selection monitor")


def _enqueue_quarterly_recalibration() -> None:
    """Enqueue full factor selection recalibration for all active stocks."""
    try:
        from services.api.app.queue import _get_macro_ingest_queue
        q = _get_macro_ingest_queue()
        job = q.enqueue("services.worker.tasks.factor_selection_quarterly.run_quarterly_factor_recalibration")
        log.info("scheduler: enqueued quarterly factor recalibration job=%s", job.id)
    except Exception:
        log.exception("scheduler: failed to enqueue quarterly factor recalibration")


_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> None:
    global _scheduler
    if os.environ.get("MARKET_REFRESH_CRON_ENABLED", "1").strip() in ("0", "false", "False"):
        log.info("scheduler: disabled via MARKET_REFRESH_CRON_ENABLED=0")
        return
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _enqueue_daily_refresh,
        trigger=CronTrigger(hour=20, minute=0, day_of_week="mon-fri", timezone="Africa/Casablanca"),
        id="daily_market_refresh",
        replace_existing=True,
    )
    _scheduler.add_job(
        _enqueue_factor_monitor,
        trigger=CronTrigger(hour=22, minute=0, day_of_week="mon-fri", timezone="Africa/Casablanca"),
        id="daily_factor_monitor",
        replace_existing=True,
    )
    _scheduler.add_job(
        _enqueue_quarterly_recalibration,
        trigger=CronTrigger(month="1,4,7,10", day=1, hour=2, minute=0, timezone="Africa/Casablanca"),
        id="quarterly_factor_recalibration",
        replace_existing=True,
    )
    _scheduler.start()
    log.info("scheduler: started - daily refresh @20:00, factor monitor @22:00, quarterly recalib @Jan/Apr/Jul/Oct 1st")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
