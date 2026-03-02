from __future__ import annotations

import logging
import os
import signal
import sys
import inspect
from typing import Iterable

from redis import Redis
from rq import Queue
from rq.worker import Worker  # Worker base (ok in rq v2)
from rq.timeouts import JobTimeoutException

from services.worker.config import settings

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("quant.worker")


LISTEN_QUEUES = list(settings.WORKER_QUEUES)


def _build_redis() -> Redis:
    # decode_responses=False (bytes) is safest for rq internals
    return Redis.from_url(settings.REDIS_URL, decode_responses=False)


def _build_queues(redis: Redis, names: Iterable[str]) -> list[Queue]:
    return [Queue(name, connection=redis) for name in names]


def main() -> None:
    redis = _build_redis()
    queues = _build_queues(redis, LISTEN_QUEUES)

    log.info("Starting RQ worker. queues=%s redis=%s", LISTEN_QUEUES, settings.REDIS_URL)

    # Worker (not forking by default on Linux; on Windows, forking isn't available anyway)
    # If you ever need "no fork" semantics explicitly, keep jobs pure and avoid heavy global state.
    worker = Worker(
        queues,
        connection=redis,
        name=os.getenv("WORKER_NAME") or None,
        default_worker_ttl=int(os.getenv("WORKER_TTL_SECONDS", "420")),
    )

    # Graceful shutdown
    def _handle_sig(signum, _frame):
        log.warning("Received signal %s, requesting stop...", signum)
        try:
            worker.request_stop()
        except Exception:
            pass

    signal.signal(signal.SIGTERM, _handle_sig)
    signal.signal(signal.SIGINT, _handle_sig)

    # with_scheduler=True enables rq-scheduler-like behavior for scheduled jobs
    # If you don't use scheduling, set env WORKER_WITH_SCHEDULER=0
    with_scheduler = os.getenv("WORKER_WITH_SCHEDULER", "1").strip() not in ("0", "false", "False")

    try:
        work_kwargs = {
            "with_scheduler": with_scheduler,
            "logging_level": LOG_LEVEL,
        }
        if "job_monitoring_interval" in inspect.signature(worker.work).parameters:
            work_kwargs["job_monitoring_interval"] = int(
                os.getenv("WORKER_JOB_MONITORING_INTERVAL", "30")
            )
        worker.work(**work_kwargs)
    except JobTimeoutException:
        log.exception("Job timed out.")
        raise
    except Exception:
        log.exception("Worker crashed.")
        raise


if __name__ == "__main__":
    main()
