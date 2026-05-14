"""Dedicated recurring-operations scheduler process."""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import sys
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from services.api.app.services.scheduler_registry import SCHEDULE_SPECS
from services.worker.config import settings
from services.worker.redis_utils import connect_redis_with_fallback
from services.worker.tasks.scheduler_dispatch import (
    SCHEDULER_HEARTBEAT_KEY,
    cleanup_legacy_rq_scheduler_entries,
    dispatch_schedule,
)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("quant.scheduler")


def _scheduler_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _write_heartbeat(scheduler: BlockingScheduler, *, started_at: str) -> None:
    redis = connect_redis_with_fallback(settings.REDIS_URL, decode_responses=True, logger=log)
    jobs = []
    for job in scheduler.get_jobs():
        next_run_time = getattr(job, "next_run_time", None)
        jobs.append(
            {
                "id": str(job.id),
                "next_run_at": next_run_time.isoformat() if next_run_time else None,
            }
        )
    redis.setex(
        SCHEDULER_HEARTBEAT_KEY,
        120,
        json.dumps(
            {
                "scheduler_id": _scheduler_identity(),
                "started_at": started_at,
                "heartbeat_at": datetime.now(timezone.utc).isoformat(),
                "jobs": jobs,
            },
            sort_keys=True,
        ),
    )


def _add_registered_jobs(scheduler: BlockingScheduler) -> None:
    for spec in SCHEDULE_SPECS:
        scheduler.add_job(
            dispatch_schedule,
            trigger=spec.trigger(),
            id=spec.id,
            kwargs={"schedule_id": spec.id, "trigger_source": "scheduled"},
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )


def main() -> None:
    started_at = datetime.now(timezone.utc).isoformat()
    removed = cleanup_legacy_rq_scheduler_entries()
    if removed:
        log.info("Removed legacy rq-scheduler entries: %s", ", ".join(removed))

    scheduler = BlockingScheduler(timezone=timezone.utc)
    _add_registered_jobs(scheduler)
    scheduler.add_job(
        _write_heartbeat,
        trigger=IntervalTrigger(seconds=30),
        id="scheduler_heartbeat",
        kwargs={"scheduler": scheduler, "started_at": started_at},
        replace_existing=True,
        max_instances=1,
    )

    def _handle_sig(signum, _frame):
        log.warning("Received signal %s, shutting down scheduler...", signum)
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGTERM, _handle_sig)
    signal.signal(signal.SIGINT, _handle_sig)

    log.info(
        "Starting dedicated scheduler. jobs=%s redis=%s",
        [spec.id for spec in SCHEDULE_SPECS],
        settings.REDIS_URL,
    )
    _write_heartbeat(scheduler, started_at=started_at)
    scheduler.start()


if __name__ == "__main__":
    main()
