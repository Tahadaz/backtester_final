from redis import Redis
from rq import Queue
from .config import settings

def get_queue() -> Queue:
    redis_conn = Redis.from_url(settings.REDIS_URL)
    return Queue(
        settings.RUNS_QUEUE_NAME,
        connection=redis_conn,
        default_timeout=int(settings.RUN_JOB_TIMEOUT_SECONDS),
    )
