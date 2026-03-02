from __future__ import annotations
from redis import Redis

def cancel_requested(redis: Redis, job_id: str) -> bool:
    return bool(redis.get(f"rq:cancel:{job_id}".encode()))
