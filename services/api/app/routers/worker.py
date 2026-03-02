from __future__ import annotations
from fastapi import APIRouter
from redis import Redis
from ..config import settings

router = APIRouter(prefix="/workers", tags=["workers"])

def _redis() -> Redis:
    return Redis.from_url(settings.REDIS_URL, decode_responses=True)

@router.get("/health")
def workers_health():
    r = _redis()
    # Workers registered in redis (rq:worker:<name>)
    keys = list(r.scan_iter(match="rq:worker:*"))
    queue_names = [
        settings.RUNS_QUEUE_NAME,
        settings.DEFAULTS_DISCOVERY_QUEUE_NAME,
    ]
    queue_lengths = {
        name: int(r.llen(f"rq:queue:{name}"))
        for name in dict.fromkeys(queue_names)
    }
    # Failed jobs count (optional signal)
    failed = r.zcard("rq:failed")

    return {
        "ok": True,
        "workers_registered": len(keys),
        "worker_keys": keys[:50],  # cap
        "queue_lengths": queue_lengths,
        "queue_runs_length": int(queue_lengths.get(settings.RUNS_QUEUE_NAME, 0)),
        "failed_count": failed,
    }
