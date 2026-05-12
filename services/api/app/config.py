from __future__ import annotations

import json
import os
from typing import Literal

from pydantic import BaseModel


SnapshotReadMode = Literal["legacy", "shadow", "snapshot"]
_VALID_SNAPSHOT_READ_MODES: tuple[SnapshotReadMode, ...] = ("legacy", "shadow", "snapshot")


def _parse_snapshot_read_mode(value: str | None, default: SnapshotReadMode = "legacy") -> SnapshotReadMode:
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in _VALID_SNAPSHOT_READ_MODES:
        return normalized  # type: ignore[return-value]
    return default


def _parse_snapshot_read_mode_overrides(raw: str | None) -> dict[str, SnapshotReadMode]:
    """Parse ``SNAPSHOT_READ_MODE_OVERRIDES`` env var.

    Accepts either JSON (``{"dashboard": "shadow"}``) or
    comma-separated ``key=value`` pairs (``dashboard=shadow,analytics=snapshot``).
    """
    if not raw:
        return {}
    raw = raw.strip()
    if not raw:
        return {}
    out: dict[str, SnapshotReadMode] = {}
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(data, dict):
            for k, v in data.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    continue
                if v.strip().lower() in _VALID_SNAPSHOT_READ_MODES:
                    out[k.strip().lower()] = v.strip().lower()  # type: ignore[assignment]
        return out
    for chunk in raw.split(","):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        if value.strip().lower() in _VALID_SNAPSHOT_READ_MODES:
            out[key.strip().lower()] = value.strip().lower()  # type: ignore[assignment]
    return out

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
    EDGE_COST_BPS_PER_SIDE: float = float(os.getenv("EDGE_COST_BPS_PER_SIDE", "33"))
    EDGE_INLINE_LIMIT_MS: int = int(os.getenv("EDGE_INLINE_LIMIT_MS", "200"))
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

    INTERNAL_JWT_SECRET: str = os.getenv("INTERNAL_JWT_SECRET", "").strip()
    BLOOMBERG_BRIDGE_API_KEY: str = os.getenv("BLOOMBERG_BRIDGE_API_KEY", "").strip()
    BLOOMBERG_BRIDGE_MAX_UPLOAD_BYTES: int = int(
        os.getenv("BLOOMBERG_BRIDGE_MAX_UPLOAD_BYTES", "268435456")
    )

    # Phase 0 — snapshot-cutover scaffolding.
    # ``legacy`` keeps the live-compute path; ``shadow`` serves legacy AND queries
    # the snapshot row to diff (Phase 1+ endpoints emit a metric on mismatch);
    # ``snapshot`` serves snapshot tables only.
    SNAPSHOT_READ_MODE: SnapshotReadMode = _parse_snapshot_read_mode(
        os.getenv("SNAPSHOT_READ_MODE"), default="legacy"
    )
    # Per-endpoint override map, e.g. ``{"dashboard": "snapshot"}``. Overrides
    # the global mode for a single logical surface (dashboard, signals, analytics).
    SNAPSHOT_READ_MODE_OVERRIDES: dict[str, SnapshotReadMode] = _parse_snapshot_read_mode_overrides(
        os.getenv("SNAPSHOT_READ_MODE_OVERRIDES")
    )

    # Phase 0 — admin scope + per-IP rate limit on trigger endpoints.
    ADMIN_API_KEY: str = os.getenv("ADMIN_API_KEY", "").strip()
    # Comma-separated list of JWT scope claims that grant admin (default: ``admin``).
    ADMIN_SCOPES: tuple[str, ...] = tuple(
        s.strip() for s in os.getenv("ADMIN_SCOPES", "admin").split(",") if s.strip()
    ) or ("admin",)
    # Trigger endpoints: per-IP rate limit (calls per window).
    TRIGGER_RATE_LIMIT_PER_MIN: int = int(os.getenv("TRIGGER_RATE_LIMIT_PER_MIN", "10"))
    TRIGGER_RATE_LIMIT_WINDOW_SECONDS: int = int(
        os.getenv("TRIGGER_RATE_LIMIT_WINDOW_SECONDS", "60")
    )

    def snapshot_read_mode_for(self, surface: str) -> SnapshotReadMode:
        """Return the effective read mode for a logical surface (e.g. "dashboard")."""
        return self.SNAPSHOT_READ_MODE_OVERRIDES.get(surface.strip().lower(), self.SNAPSHOT_READ_MODE)


settings = Settings()

if not settings.DATABASE_URL.strip():
    raise RuntimeError(
        "DATABASE_URL is empty. Set DATABASE_URL, for example "
        "postgresql+psycopg2://app:app@127.0.0.1:5555/quant"
    )
