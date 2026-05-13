"""Recover dashboard-visible recompute outputs after a partial batch.

The script is intentionally dashboard-scoped: it targets MASI equity rows that
are visible in the dashboard, enqueues full WFO recomputes, rebuilds score
history after WFO is idle, then refreshes dashboard snapshots.

Usage from a worker/API container:
    python -m services.api.scripts.recover_dashboard_recompute --execute --wait
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from collections.abc import Iterable, Sequence
from typing import Any

from redis import Redis
from sqlalchemy.orm import Session

from core.quant_core.signal_engine.modes import ALL_SIGNAL_MODE_NAMES
from services.api.app import models
from services.api.app.config import settings
from services.api.app.db import _ensure_session_factory
from services.api.app.services.market_universe import is_masi_dashboard_member, list_signal_universe


HORIZONS: tuple[str, ...] = ("weekly", "monthly", "quarterly")
VARIANTS: tuple[str, ...] = tuple(ALL_SIGNAL_MODE_NAMES)
QUEUE_NAMES: tuple[str, ...] = ("wfo_signals", "score_history")
WFO_TERMINAL_STATUSES: tuple[str, ...] = ("succeeded", "no_signal", "insufficient_data")
JOB_TIMEOUT_SECONDS = int(os.getenv("DASHBOARD_RECOVERY_JOB_TIMEOUT_SECONDS", "7200"))
POLL_SECONDS = int(os.getenv("DASHBOARD_RECOVERY_POLL_SECONDS", "300"))

log = logging.getLogger("dashboard_recompute_recovery")


def dashboard_symbols(db: Session) -> list[str]:
    """Return data-backed dashboard members only."""
    rows = list_signal_universe(db)
    symbols = [row.symbol for row in rows if is_masi_dashboard_member(row)]
    return sorted(dict.fromkeys(symbols))


def missing_or_failed_wfo(
    db: Session,
    symbols: Sequence[str],
    *,
    scope: str = "incomplete",
) -> list[tuple[str, str, str]]:
    """Return WFO tuples that should be full-recomputed."""
    rows: list[tuple[str, str, str]] = []
    for symbol in symbols:
        for horizon in HORIZONS:
            for variant in VARIANTS:
                if scope == "all":
                    rows.append((symbol, horizon, variant))
                    continue
                found = (
                    db.query(models.WfoGlobalSignal)
                    .filter_by(symbol=symbol, horizon=horizon, variant=variant)
                    .first()
                )
                if found is None or str(found.status or "").strip().lower() not in WFO_TERMINAL_STATUSES:
                    rows.append((symbol, horizon, variant))
    return rows


def _count_key(redis: Redis, key: str) -> int:
    key_type = redis.type(key)
    if key_type == "list":
        return int(redis.llen(key))
    if key_type == "zset":
        return int(redis.zcard(key))
    if key_type == "set":
        return int(redis.scard(key))
    return 0


def queue_counts(redis: Redis) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for name in QUEUE_NAMES:
        out[name] = {
            "queued": _count_key(redis, f"rq:queue:{name}"),
            "wip": _count_key(redis, f"rq:wip:{name}"),
            "deferred": _count_key(redis, f"rq:deferred:{name}"),
            "failed": _count_key(redis, f"rq:failed:{name}"),
        }
    return out


def queues_idle(counts: dict[str, dict[str, int]], names: Iterable[str]) -> bool:
    return all(
        counts[name]["queued"] == 0 and counts[name]["wip"] == 0 and counts[name]["deferred"] == 0
        for name in names
    )


def wait_for_idle(redis: Redis, queue_names: Sequence[str], *, poll_seconds: int) -> None:
    while True:
        counts = queue_counts(redis)
        log.info("queue counts: %s", counts)
        if queues_idle(counts, queue_names):
            return
        time.sleep(poll_seconds)


def enqueue_full_wfo_jobs(
    queue: Any,
    rows: Sequence[tuple[str, str, str]],
    *,
    dry_run: bool,
) -> list[str]:
    job_ids: list[str] = []
    for symbol, horizon, variant in rows:
        if dry_run:
            continue
        job = queue.enqueue(
            "services.worker.tasks.wfo_signal_batch.enqueue_wfo_for_symbol_horizon",
            symbol,
            horizon,
            None,
            variant,
            job_timeout=JOB_TIMEOUT_SECONDS,
            meta={"triggered_by": "dashboard_recompute_recovery"},
        )
        job_ids.append(str(job.id))
    return job_ids


def enqueue_score_history_jobs(
    db: Session,
    queue: Any,
    symbols: Sequence[str],
    *,
    dry_run: bool,
) -> list[str]:
    job_ids: list[str] = []
    for symbol in symbols:
        if dry_run:
            continue
        row = db.query(models.ScoreHistoryJob).filter_by(symbol=symbol).first()
        if row is None:
            row = models.ScoreHistoryJob(symbol=symbol, status="pending")
            db.add(row)
        else:
            row.status = "pending"
            row.error_message = None
        job = queue.enqueue(
            "services.worker.tasks.score_history_batch.enqueue_score_history_for_symbol",
            symbol,
            job_timeout=JOB_TIMEOUT_SECONDS,
            meta={"triggered_by": "dashboard_recompute_recovery"},
        )
        row.rq_job_id = str(job.id)
        job_ids.append(str(job.id))
    if not dry_run:
        db.commit()
    return job_ids


def refresh_dashboard_snapshots(*, dry_run: bool) -> dict[str, bool]:
    if dry_run:
        return {horizon: False for horizon in HORIZONS}
    from services.worker.tasks.dashboard_snapshot import refresh_dashboard_snapshot

    return refresh_dashboard_snapshot()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Enqueue jobs and write DB state. Defaults to dry-run.")
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Wait between phases so score history and snapshots run in order.",
    )
    parser.add_argument(
        "--phase",
        choices=("all", "wfo", "score-history", "snapshots"),
        default="all",
        help="Recovery phase to run.",
    )
    parser.add_argument(
        "--wfo-scope",
        choices=("incomplete", "all"),
        default="incomplete",
        help="Which WFO tuples to enqueue during the WFO phase.",
    )
    parser.add_argument("--poll-seconds", type=int, default=POLL_SECONDS)
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args()
    dry_run = not args.execute

    from rq import Queue

    redis_conn = Redis.from_url(settings.REDIS_URL, decode_responses=False)
    wfo_queue = Queue("wfo_signals", connection=redis_conn)
    score_queue = Queue("score_history", connection=redis_conn)
    SessionLocal = _ensure_session_factory()

    with SessionLocal() as db:
        symbols = dashboard_symbols(db)
        log.info("dashboard symbols=%d dry_run=%s phase=%s", len(symbols), dry_run, args.phase)

        if args.phase in {"all", "wfo"}:
            rows = missing_or_failed_wfo(db, symbols, scope=args.wfo_scope)
            log.info("full WFO tuples to enqueue=%d scope=%s", len(rows), args.wfo_scope)
            job_ids = enqueue_full_wfo_jobs(wfo_queue, rows, dry_run=dry_run)
            log.info("full WFO jobs enqueued=%d", len(job_ids))
            if args.phase == "wfo":
                return 0
            if rows and not args.wait:
                log.info(
                    "WFO phase queued. Re-run with --phase score-history after "
                    "wfo_signals is idle, or use --wait."
                )
                return 0

        if args.phase == "all" and args.wait and not dry_run:
            wait_for_idle(redis_conn, ("wfo_signals",), poll_seconds=args.poll_seconds)

        if args.phase in {"all", "score-history"}:
            job_ids = enqueue_score_history_jobs(db, score_queue, symbols, dry_run=dry_run)
            log.info("score history jobs enqueued=%d", len(job_ids))
            if args.phase == "score-history":
                return 0
            if not args.wait:
                log.info(
                    "Score history phase queued. Re-run with --phase snapshots "
                    "after score_history is idle, or use --wait."
                )
                return 0

        if args.phase == "all" and args.wait and not dry_run:
            wait_for_idle(redis_conn, ("score_history",), poll_seconds=args.poll_seconds)

        if args.phase in {"all", "snapshots"}:
            results = refresh_dashboard_snapshots(dry_run=dry_run)
            log.info("snapshot refresh results=%s", results)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
