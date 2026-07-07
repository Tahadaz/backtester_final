"""One-off seed script: computes and persists the first fundamental_value_strategy_snapshot
row so the new /value-strategy/snapshot endpoint has real data to serve immediately."""
import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://app:app@127.0.0.1:5555/quant")
os.environ.setdefault("S3_ENDPOINT_URL", "http://127.0.0.1:9000")
os.environ.setdefault("AWS_ACCESS_KEY_ID", os.environ.get("S3_ACCESS_KEY", "minio"))
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", os.environ.get("S3_SECRET_KEY", "minio12345"))
os.environ.setdefault("S3_BUCKET", "quant-artifacts")

from services.api.app.db import _ensure_session_factory
from services.api.app.services.value_strategy_snapshot import recompute_and_persist_value_strategy

if __name__ == "__main__":
    db = _ensure_session_factory()()
    try:
        result = recompute_and_persist_value_strategy(db)
        print(result)
    finally:
        db.close()
