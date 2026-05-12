"""Continue the all-mode recompute until canonical outputs are populated.

This is an operational helper for the local Docker stack. It avoids RQ registry
helpers because those helpers can perform cleanup as a side effect while long
jobs are running.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Iterable

from redis import Redis
from rq import Queue
from rq.job import Job
from sqlalchemy import and_
from sqlalchemy.orm import Session

from core.quant_core.signal_engine.modes import ALL_SIGNAL_MODE_NAMES
from services.api.app import models
from services.api.app.config import settings
from services.api.app.db import _ensure_session_factory
from services.api.app.services.market_universe import list_signal_universe_symbols


LOG_PATH = os.getenv("FULL_RECOMPUTE_MONITOR_LOG", "/repo/services/api/scripts/full_recompute_monitor.log")
POLL_SECONDS = int(os.getenv("FULL_RECOMPUTE_MONITOR_POLL_SECONDS", "300"))
JOB_TIMEOUT_SECONDS = int(os.getenv("FULL_RECOMPUTE_JOB_TIMEOUT_SECONDS", "7200"))
MAX_RETRY_PASSES = int(os.getenv("FULL_RECOMPUTE_MAX_RETRY_PASSES", "2"))

HORIZONS = ("weekly", "monthly", "quarterly")
VARIANTS = tuple(ALL_SIGNAL_MODE_NAMES)
QUEUE_NAMES = ("runs", "signal_engine", "wfo_signals", "score_history")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("full_recompute_monitor")


def _redis() -> Redis:
    return Redis.from_url(settings.REDIS_URL, decode_responses=True)


def _redis_binary() -> Redis:
    return Redis.from_url(settings.REDIS_URL, decode_responses=False)


def _count_key(r: Redis, key: str) -> int:
    typ = r.type(key)
    if typ == "list":
        return int(r.llen(key))
    if typ == "zset":
        return int(r.zcard(key))
    if typ == "set":
        return int(r.scard(key))
    return 0


def queue_counts(r: Redis) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for name in QUEUE_NAMES:
        out[name] = {
            "queued": _count_key(r, f"rq:queue:{name}"),
            "wip": _count_key(r, f"rq:wip:{name}"),
            "deferred": _count_key(r, f"rq:deferred:{name}"),
            "finished": _count_key(r, f"rq:finished:{name}"),
            "failed": _count_key(r, f"rq:failed:{name}"),
        }
    return out


def _iter_pending_job_ids(r: Redis, queue_name: str) -> Iterable[str]:
    yield from r.lrange(f"rq:queue:{queue_name}", 0, -1)
    yield from r.zrange(f"rq:deferred:{queue_name}", 0, -1)
    yield from r.zrange(f"rq:wip:{queue_name}", 0, -1)


def normalize_timeouts(r: Redis, rb: Redis) -> int:
    updated = 0
    for queue_name in ("signal_engine", "wfo_signals", "score_history"):
        for job_id in _iter_pending_job_ids(r, queue_name):
            try:
                job = Job.fetch(job_id, connection=rb)
            except Exception:
                continue
            if getattr(job, "timeout", None) != JOB_TIMEOUT_SECONDS:
                job.timeout = JOB_TIMEOUT_SECONDS
                job.save()
                updated += 1
    return updated


def repair_false_failed(r: Redis) -> int:
    repaired = 0
    for queue_name in QUEUE_NAMES:
        failed = set(r.zrange(f"rq:failed:{queue_name}", 0, -1))
        finished = set(r.zrange(f"rq:finished:{queue_name}", 0, -1))
        for job_id in sorted(failed & finished):
            key = f"rq:job:{job_id}"
            if r.hget(key, "status") == "failed" and r.hget(key, "ended_at"):
                r.hset(key, "status", "finished")
                r.zrem(f"rq:failed:{queue_name}", job_id)
                repaired += 1
    return repaired


def cancel_stale_legacy_deferred(r: Redis, rb: Redis) -> int:
    canceled = 0
    for queue_name in ("signal_engine", "wfo_signals"):
        deferred_key = f"rq:deferred:{queue_name}"
        for job_id in list(r.zrange(deferred_key, 0, -1)):
            try:
                job = Job.fetch(job_id, connection=rb)
            except Exception:
                continue
            args = job.args or ()
            horizon = args[1] if len(args) > 1 else None
            if horizon not in HORIZONS:
                r.zrem(deferred_key, job_id)
                r.hset(f"rq:job:{job_id}", "status", "canceled")
                canceled += 1
    return canceled


def queues_idle(counts: dict[str, dict[str, int]]) -> bool:
    for name in ("runs", "signal_engine", "wfo_signals"):
        item = counts[name]
        if item["queued"] or item["wip"] or item["deferred"]:
            return False
    return True


def _active_symbols(db: Session) -> list[str]:
    return list_signal_universe_symbols(db)


def _missing_signal_engine(db: Session) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for symbol in _active_symbols(db):
        for horizon in HORIZONS:
            for variant in VARIANTS:
                found = (
                    db.query(models.SignalEngineGlobalResult)
                    .filter_by(symbol=symbol, horizon=horizon, variant=variant)
                    .filter(models.SignalEngineGlobalResult.status.in_(("succeeded", "no_signal")))
                    .first()
                )
                if found is None:
                    rows.append((symbol, horizon, variant))
    return rows


def _missing_wfo(db: Session) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for symbol in _active_symbols(db):
        for horizon in HORIZONS:
            for variant in VARIANTS:
                found = (
                    db.query(models.WfoGlobalSignal)
                    .filter_by(symbol=symbol, horizon=horizon, variant=variant)
                    .filter(models.WfoGlobalSignal.status.in_(("succeeded", "no_signal")))
                    .first()
                )
                if found is None:
                    rows.append((symbol, horizon, variant))
    return rows


def enqueue_signal_retries(rb: Redis, rows: list[tuple[str, str, str]]) -> int:
    q = Queue("signal_engine", connection=rb)
    for symbol, horizon, variant in rows:
        q.enqueue(
            "services.worker.tasks.signal_engine_batch.compute_signal_engine_for_symbol",
            symbol,
            horizon,
            variant,
            job_timeout=JOB_TIMEOUT_SECONDS,
            meta={"triggered_by": "full_recompute_monitor"},
        )
    return len(rows)


def enqueue_wfo_retries(rb: Redis, rows: list[tuple[str, str, str]]) -> int:
    q = Queue("wfo_signals", connection=rb)
    for symbol, horizon, variant in rows:
        q.enqueue(
            "services.worker.tasks.wfo_signal_batch.enqueue_wfo_for_symbol_horizon",
            symbol,
            horizon,
            None,
            variant,
            job_timeout=JOB_TIMEOUT_SECONDS,
            meta={"triggered_by": "full_recompute_monitor"},
        )
    return len(rows)


def enqueue_score_history(db: Session, rb: Redis) -> int:
    q = Queue("score_history", connection=rb)
    symbols = _active_symbols(db)
    for symbol in symbols:
        row = db.query(models.ScoreHistoryJob).filter_by(symbol=symbol).first()
        if row is None:
            row = models.ScoreHistoryJob(symbol=symbol, status="pending")
            db.add(row)
        else:
            row.status = "pending"
            row.error_message = None
        job = q.enqueue(
            "services.worker.tasks.score_history_batch.enqueue_score_history_for_symbol",
            symbol,
            job_timeout=JOB_TIMEOUT_SECONDS,
            meta={"triggered_by": "full_recompute_monitor"},
        )
        row.rq_job_id = str(job.id)
    db.commit()
    return len(symbols)


def canonical_score_history_complete(db: Session) -> bool:
    rows = (
        db.query(models.SignalScoreHistory.source)
        .filter(models.SignalScoreHistory.source.like("engine:%") | models.SignalScoreHistory.source.like("wfo:%"))
        .distinct()
        .all()
    )
    sources = {source for (source,) in rows}
    expected = {f"engine:{variant}" for variant in VARIANTS} | {f"wfo:{variant}" for variant in VARIANTS}
    return expected.issubset(sources)


def main() -> int:
    log.info("full recompute monitor starting")
    r = _redis()
    rb = _redis_binary()
    SessionLocal = _ensure_session_factory()
    retry_pass = 0
    score_history_triggered = False

    while True:
        updated = normalize_timeouts(r, rb)
        repaired = repair_false_failed(r)
        canceled = cancel_stale_legacy_deferred(r, rb)
        counts = queue_counts(r)
        log.info(
            "queues=%s timeout_updates=%d repaired=%d canceled_stale=%d",
            counts,
            updated,
            repaired,
            canceled,
        )

        if not queues_idle(counts):
            time.sleep(POLL_SECONDS)
            continue

        db = SessionLocal()
        try:
            missing_engine = _missing_signal_engine(db)
            missing_wfo = _missing_wfo(db)
            if (missing_engine or missing_wfo) and retry_pass < MAX_RETRY_PASSES:
                retry_pass += 1
                engine_count = enqueue_signal_retries(rb, missing_engine)
                wfo_count = enqueue_wfo_retries(rb, missing_wfo)
                log.info(
                    "retry pass %d queued signal_engine=%d wfo=%d",
                    retry_pass,
                    engine_count,
                    wfo_count,
                )
                time.sleep(POLL_SECONDS)
                continue

            if missing_engine or missing_wfo:
                log.error(
                    "canonical recompute still incomplete after retries: signal_engine=%d wfo=%d",
                    len(missing_engine),
                    len(missing_wfo),
                )
                return 2

            if not score_history_triggered:
                triggered = enqueue_score_history(db, rb)
                score_history_triggered = True
                log.info("queued score_history jobs=%d", triggered)
                time.sleep(POLL_SECONDS)
                continue

            counts = queue_counts(r)
            if counts["score_history"]["queued"] or counts["score_history"]["wip"] or counts["score_history"]["deferred"]:
                time.sleep(POLL_SECONDS)
                continue

            if canonical_score_history_complete(db):
                log.info("full recompute monitor complete")
                return 0
            log.error("score history completed but canonical sources are missing")
            return 3
        finally:
            db.close()


if __name__ == "__main__":
    raise SystemExit(main())
