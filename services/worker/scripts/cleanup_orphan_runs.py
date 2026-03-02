from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from redis import Redis
from rq import Queue
from rq.job import Job
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from services.worker.config import settings


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mark orphaned runs (stale heartbeat) as failed/canceled.",
    )
    parser.add_argument(
        "--stale-seconds",
        type=int,
        default=int(settings.RUN_ORPHAN_STALE_SECONDS),
        help="Heartbeat staleness threshold in seconds.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned updates without writing to DB.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    stale_seconds = max(1, int(args.stale_seconds))
    cutoff = _utcnow() - timedelta(seconds=stale_seconds)

    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=False)
    queue = Queue(settings.RUNS_QUEUE_NAME, connection=redis)

    query = text(
        """
        select
            id::text as run_id,
            status,
            rq_job_id,
            started_at,
            last_heartbeat_at
        from run
        where status in ('running', 'cancel_requested')
          and (
                (last_heartbeat_at is not null and last_heartbeat_at < :cutoff)
             or (last_heartbeat_at is null and started_at is not null and started_at < :cutoff)
          )
        order by started_at nulls first
        """
    )

    updated = 0
    with Session(engine) as db:
        rows = db.execute(query, {"cutoff": cutoff}).mappings().all()
        print(f"Found {len(rows)} stale run(s). cutoff={cutoff.isoformat()}")

        for row in rows:
            run_id = str(row["run_id"])
            status = str(row["status"] or "")
            job_id = row.get("rq_job_id")

            rq_status = "missing"
            if job_id:
                try:
                    job = Job.fetch(str(job_id), connection=redis)
                    rq_status = str(job.get_status(refresh=True))
                except Exception:
                    rq_status = "missing"

            cancel_flag = False
            if job_id:
                try:
                    cancel_flag = bool(redis.get(f"rq:cancel:{job_id}".encode("utf-8")))
                except Exception:
                    cancel_flag = False

            next_status = "canceled" if (status == "cancel_requested" or cancel_flag) else "failed"
            reason = (
                f"orphaned run cleanup: stale heartbeat>{stale_seconds}s; "
                f"rq_job_id={job_id or 'null'}; rq_status={rq_status}"
            )
            reason = reason[:8000]

            print(
                f"- run_id={run_id} status={status} rq_job_id={job_id} "
                f"rq_status={rq_status} -> {next_status}"
            )

            if args.dry_run:
                continue

            db.execute(
                text(
                    """
                    update run
                    set status=:status,
                        finished_at=:finished_at,
                        error_message=:error_message,
                        progress_stage=:progress_stage,
                        progress_message=:progress_message,
                        last_heartbeat_at=:last_heartbeat_at
                    where id=:id and status in ('running', 'cancel_requested')
                    """
                ),
                {
                    "id": run_id,
                    "status": next_status,
                    "finished_at": _utcnow(),
                    "error_message": reason,
                    "progress_stage": next_status,
                    "progress_message": "Finalized by orphan cleanup",
                    "last_heartbeat_at": _utcnow(),
                },
            )
            updated += 1

            if job_id:
                try:
                    queue.started_job_registry.remove(str(job_id), delete_job=False)
                except Exception:
                    pass

        if not args.dry_run:
            db.commit()

    if args.dry_run:
        print("Dry-run only, no rows updated.")
    else:
        print(f"Updated {updated} run(s).")


if __name__ == "__main__":
    main()
