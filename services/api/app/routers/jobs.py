from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from redis import Redis
try:
    from rq import Queue
    from rq.job import Job
except ValueError:  # pragma: no cover - Windows test environments lack fork context
    Queue = Job = None  # type: ignore[assignment]

from ..config import settings
from .. import auth

router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(auth.require_api_key)])


def _redis() -> Redis:
    return Redis.from_url(settings.REDIS_URL, decode_responses=False)


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str):
    r = _redis()

    # 1) set cancel flag (soft cancel)
    r.set(f"rq:cancel:{job_id}".encode(), b"1", ex=3600)

    # 2) If job is queued, remove it from the queue now
    try:
        job = Job.fetch(job_id, connection=r)
    except Exception:
        raise HTTPException(status_code=404, detail="Job not found")

    # If not started: remove from queue + mark canceled
    if job.get_status(refresh=True) in ("queued", "deferred", "scheduled"):
        q = Queue(job.origin, connection=r)
        try:
            q.remove(job)  # removes job id from queue list
        except Exception:
            pass
        job.cancel()  # sets status canceled (RQ)
        return {"ok": True, "job_id": job_id, "mode": "queued_removed"}

    # Running: rely on cooperative checks
    return {"ok": True, "job_id": job_id, "mode": "soft_cancel_requested", "status": job.get_status()}
