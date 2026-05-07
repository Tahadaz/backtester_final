from redis import Redis
from .config import settings

def get_queue():
    from rq import Queue

    redis_conn = Redis.from_url(settings.REDIS_URL)
    return Queue(
        settings.RUNS_QUEUE_NAME,
        connection=redis_conn,
        default_timeout=int(settings.RUN_JOB_TIMEOUT_SECONDS),
    )


def get_market_refresh_queue():
    from rq import Queue

    redis_conn = Redis.from_url(settings.REDIS_URL)
    return Queue(
        settings.MARKET_REFRESH_QUEUE_NAME,
        connection=redis_conn,
        default_timeout=int(settings.MARKET_REFRESH_JOB_TIMEOUT_SECONDS),
    )


def _get_macro_ingest_queue():
    """Alias for the default runs queue, used for macro ingestion and factor selection jobs."""
    return get_queue()
