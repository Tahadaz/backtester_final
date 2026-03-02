from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from redis import Redis
from rq import Queue
from services.worker.config import settings

def main() -> None:
    redis = Redis.from_url(settings.REDIS_URL)
    q = Queue("runs", connection=redis)

    print("Queued:", q.count)
    print("Started:", q.started_job_registry.count)
    print("Failed:", q.failed_job_registry.count)

    # Remove stuck "started" jobs (abandoned)
    for job_id in q.started_job_registry.get_job_ids():
        q.started_job_registry.remove(job_id)
        print("Removed from started:", job_id)

    print("Done.")

if __name__ == "__main__":
    main()
