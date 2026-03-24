"""Daily 18:00 market refresh scheduler (Africa/Casablanca timezone)."""
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
    """Create a MarketRefreshRun and enqueue the RQ job — same logic as POST /market-data/refresh."""
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
        trigger=CronTrigger(hour=18, minute=0, day_of_week="mon-fri", timezone="Africa/Casablanca"),
        id="daily_market_refresh",
        replace_existing=True,
    )
    _scheduler.start()
    log.info("scheduler: started — daily refresh at 18:00 Africa/Casablanca Mon-Fri")


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
