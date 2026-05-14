from __future__ import annotations

import logging
import os
import signal
import socket
import sys
from typing import Iterable

from redis import Redis
from rq import Queue
from rq.worker import Worker  # Worker base (ok in rq v2)
from rq.timeouts import JobTimeoutException

from services.worker.config import settings
from services.worker.redis_utils import connect_redis_with_fallback

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
    return connect_redis_with_fallback(settings.REDIS_URL, decode_responses=False, logger=log)


def _build_queues(redis: Redis, names: Iterable[str]) -> list[Queue]:
    return [Queue(name, connection=redis) for name in names]


def _register_schedules(redis: Redis) -> None:
    """Register weekly cron jobs for signal engine + backtest batch.

    Uses RQ's built-in scheduler (enabled via with_scheduler=True).
    Weekly signal jobs are conditional fallbacks: they only recompute tuples that
    are more than 7 days old if the Friday market refresh did not already catch them.
    """
    if os.getenv("LEGACY_RQ_CRON_ENABLED", "0").strip() not in ("1", "true", "True"):
        log.info("Legacy rq-scheduler cron registration disabled; dedicated scheduler owns recurring jobs.")
        return

    try:
        from rq_scheduler import Scheduler as RQScheduler
    except ImportError:
        log.warning("rq-scheduler not installed — skipping weekly schedule registration.")
        return

    try:
        sched = RQScheduler(connection=redis, queue_name="signal_engine")

        existing_ids = {str(job.id) for job in sched.get_jobs()}

        if "weekly_signal_engine_batch" not in existing_ids:
            from services.worker.tasks.signal_engine_batch import run_signal_engine_batch
            sched.cron(
                "0 22 * * 0",          # Every Sunday at 22:00 UTC
                func=run_signal_engine_batch,
                id="weekly_signal_engine_batch",
                use_local_timezone=False,
                timeout=7200,
            )
            log.info("Registered weekly cron: signal engine batch (Sun 22:00 UTC)")

        if "weekly_wfo_signal_batch" not in existing_ids:
            from services.worker.tasks.wfo_signal_batch import run_weekly_wfo_batch
            sched.cron(
                "0 21 * * 0",          # Every Sunday at 21:00 UTC
                func=run_weekly_wfo_batch,
                id="weekly_wfo_signal_batch",
                use_local_timezone=False,
                timeout=7200,
            )
            log.info("Registered weekly cron: WFO signal batch (Sun 21:00 UTC)")

        if "weekly_signal_backtest_batch" not in existing_ids:
            from services.worker.tasks.signal_backtest_batch import run_signal_backtest_batch
            sched.cron(
                "0 23 * * 0",          # Every Sunday at 23:00 UTC (after engine batch)
                func=run_signal_backtest_batch,
                id="weekly_signal_backtest_batch",
                use_local_timezone=False,
                timeout=7200,
            )
            log.info("Registered weekly cron: signal backtest batch (Sun 23:00 UTC)")

    except Exception:
        log.exception("Failed to register scheduled jobs — worker will start anyway.")


def _run_single_worker(*, worker_name: str | None = None) -> None:
    # Build fresh connections — required after os.fork() since sockets are not fork-safe.
    redis = _build_redis()
    queues = _build_queues(redis, LISTEN_QUEUES)

    with_scheduler = os.getenv("WORKER_WITH_SCHEDULER", "1").strip() not in ("0", "false", "False")

    worker = Worker(
        queues,
        connection=redis,
        name=worker_name or os.getenv("WORKER_NAME") or None,
        worker_ttl=int(os.getenv("WORKER_TTL_SECONDS", "420")),
        maintenance_interval=int(os.getenv("WORKER_MAINTENANCE_INTERVAL_SECONDS", "86400")),
        job_monitoring_interval=int(os.getenv("WORKER_JOB_MONITORING_INTERVAL", "30")),
    )

    def _handle_sig(signum, _frame):
        log.warning("Received signal %s, requesting stop...", signum)
        try:
            worker.request_stop()
        except Exception:
            pass

    signal.signal(signal.SIGTERM, _handle_sig)
    signal.signal(signal.SIGINT, _handle_sig)

    try:
        work_kwargs: dict = {
            "with_scheduler": with_scheduler,
            "logging_level": LOG_LEVEL,
        }
        worker.work(**work_kwargs)
    except JobTimeoutException:
        log.exception("Job timed out.")
        raise
    except Exception:
        log.exception("Worker crashed.")
        raise


def main() -> None:
    concurrency = int(os.getenv("WORKER_CONCURRENCY", "1"))

    log.info(
        "Starting RQ worker. queues=%s redis=%s concurrency=%d",
        LISTEN_QUEUES, settings.REDIS_URL, concurrency,
    )

    # Register legacy rq-scheduler schedules only when explicitly enabled.
    sched_redis = _build_redis()
    _register_schedules(sched_redis)
    sched_redis.close()

    if concurrency <= 1 or not hasattr(os, "fork"):
        _run_single_worker()
        return

    # Fork N child processes — each builds its own Redis connection after forking.
    # Only available on Linux (the target deployment platform for this service).
    # Use hostname (unique Docker container ID prefix) so names don't collide across containers.
    base_name = os.getenv("WORKER_NAME") or f"worker-{socket.gethostname()}-{os.getpid()}"
    pids: list[int] = []
    for i in range(concurrency):
        pid = os.fork()
        if pid == 0:
            # Child: build fresh connections (socket not fork-safe), then run.
            child_name = f"{base_name}-{i}"
            log.info("Child worker %d starting as %s", i, child_name)
            try:
                _run_single_worker(worker_name=child_name)
            except Exception:
                log.exception("Child worker %s crashed", child_name)
            finally:
                os._exit(0)
        pids.append(pid)

    # Parent: forward SIGTERM/SIGINT to all children, then wait.
    def _forward_sig(signum, _frame):
        log.warning("Parent received signal %s, forwarding to children...", signum)
        for child_pid in pids:
            try:
                os.kill(child_pid, signum)
            except ProcessLookupError:
                pass

    signal.signal(signal.SIGTERM, _forward_sig)
    signal.signal(signal.SIGINT, _forward_sig)

    for pid in pids:
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass


if __name__ == "__main__":
    main()
