from __future__ import annotations

import os
from pydantic import BaseModel

DEFAULT_LOCAL_DATABASE_URL = "postgresql+psycopg2://app:app@127.0.0.1:5555/quant"


def _getenv_any(*names: str, default: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value != "":
            return value
    return default


class Settings(BaseModel):
    DATABASE_URL: str = os.getenv("DATABASE_URL", DEFAULT_LOCAL_DATABASE_URL)
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    DATASET_MAX_UPLOAD_BYTES: int = int(os.getenv("DATASET_MAX_UPLOAD_BYTES", "104857600"))
    DATASET_ALLOWED_EXTENSIONS: tuple[str, ...] = (".csv", ".xlsx", ".xls")
    DATASET_METADATA_MAX_BYTES: int = int(os.getenv("DATASET_METADATA_MAX_BYTES", "32768"))
    API_KEY: str = os.getenv("API_KEY", "").strip()
    RUN_JOB_TIMEOUT_SECONDS: int = int(os.getenv("RUN_JOB_TIMEOUT_SECONDS", "21600"))
    RUN_JOB_RESULT_TTL_SECONDS: int = int(os.getenv("RUN_JOB_RESULT_TTL_SECONDS", "86400"))
    RUN_JOB_FAILURE_TTL_SECONDS: int = int(os.getenv("RUN_JOB_FAILURE_TTL_SECONDS", "604800"))
    RUN_JOB_RETRY_MAX: int = int(os.getenv("RUN_JOB_RETRY_MAX", "0"))
    RUN_JOB_RETRY_INTERVAL_SECONDS: int = int(os.getenv("RUN_JOB_RETRY_INTERVAL_SECONDS", "60"))
    RUNS_QUEUE_NAME: str = os.getenv("RUNS_QUEUE_NAME", "runs").strip() or "runs"
    DEFAULTS_DISCOVERY_QUEUE_NAME: str = (
        os.getenv("DEFAULTS_DISCOVERY_QUEUE_NAME", "defaults_discovery").strip() or "defaults_discovery"
    )
    MARKET_REFRESH_QUEUE_NAME: str = (
        os.getenv("MARKET_REFRESH_QUEUE_NAME", "market_refresh").strip() or "market_refresh"
    )
    MARKET_REFRESH_JOB_TIMEOUT_SECONDS: int = int(os.getenv("MARKET_REFRESH_JOB_TIMEOUT_SECONDS", "3600"))

    # Support both *_URL/_ID naming and docker-compose short names.
    S3_ENDPOINT_URL: str = _getenv_any("S3_ENDPOINT_URL", "S3_ENDPOINT", default="http://localhost:9000")
    S3_PRESIGN_ENDPOINT_URL: str = _getenv_any(
        "S3_PRESIGN_ENDPOINT_URL",
        "S3_PUBLIC_ENDPOINT",
        default=_getenv_any("S3_ENDPOINT_URL", "S3_ENDPOINT", default="http://localhost:9000"),
    )
    S3_ACCESS_KEY_ID: str = _getenv_any("S3_ACCESS_KEY_ID", "S3_ACCESS_KEY", default="minio")
    S3_SECRET_ACCESS_KEY: str = _getenv_any("S3_SECRET_ACCESS_KEY", "S3_SECRET_KEY", default="minio12345")
    S3_BUCKET: str = os.getenv("S3_BUCKET", "quant-artifacts")
    S3_REGION: str = os.getenv("S3_REGION", "us-east-1")
    S3_USE_SSL: bool = _getenv_any("S3_USE_SSL", "S3_SECURE", default="false").lower() == "true"


settings = Settings()

if not settings.DATABASE_URL.strip():
    raise RuntimeError(
        "DATABASE_URL is empty. Set DATABASE_URL, for example "
        "postgresql+psycopg2://app:app@127.0.0.1:5555/quant"
    )
