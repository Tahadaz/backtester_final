from __future__ import annotations

import os
from pydantic import BaseModel


def _getenv_any(*names: str, default: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value is not None and value != "":
            return value
    return default


def _parse_queue_list(raw: str | None, *, default: tuple[str, ...]) -> tuple[str, ...]:
    if not raw:
        return default
    out: list[str] = []
    seen: set[str] = set()
    for item in str(raw).split(","):
        name = item.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return tuple(out) if out else default


def _default_worker_queues() -> tuple[str, ...]:
    runs = os.getenv("RUNS_QUEUE_NAME", "runs").strip() or "runs"
    defaults = os.getenv("DEFAULTS_DISCOVERY_QUEUE_NAME", "defaults_discovery").strip() or "defaults_discovery"
    market_refresh = os.getenv("MARKET_REFRESH_QUEUE_NAME", "market_refresh").strip() or "market_refresh"
    signal_engine = os.getenv("SIGNAL_ENGINE_QUEUE_NAME", "signal_engine").strip() or "signal_engine"
    signal_backtest = os.getenv("SIGNAL_BACKTEST_QUEUE_NAME", "signal_backtest").strip() or "signal_backtest"
    # Use dict.fromkeys to preserve order and deduplicate
    wfo_signals = "wfo_signals"
    score_history = "score_history"
    return tuple(dict.fromkeys([runs, defaults, market_refresh, signal_engine, signal_backtest, wfo_signals, score_history]))


class Settings(BaseModel):
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://app:app@127.0.0.1:5555/quant",
    )
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    S3_ENDPOINT_URL: str = _getenv_any("S3_ENDPOINT_URL", "S3_ENDPOINT", default="http://localhost:9000")
    S3_ACCESS_KEY_ID: str = _getenv_any("S3_ACCESS_KEY_ID", "S3_ACCESS_KEY", default="minio")
    S3_SECRET_ACCESS_KEY: str = _getenv_any("S3_SECRET_ACCESS_KEY", "S3_SECRET_KEY", default="minio12345")
    S3_BUCKET: str = os.getenv("S3_BUCKET", "quant-artifacts")
    S3_REGION: str = os.getenv("S3_REGION", "us-east-1")
    S3_USE_SSL: bool = _getenv_any("S3_USE_SSL", "S3_SECURE", default="false").lower() == "true"
    RUNS_QUEUE_NAME: str = os.getenv("RUNS_QUEUE_NAME", "runs").strip() or "runs"
    DEFAULTS_DISCOVERY_QUEUE_NAME: str = (
        os.getenv("DEFAULTS_DISCOVERY_QUEUE_NAME", "defaults_discovery").strip() or "defaults_discovery"
    )
    MARKET_REFRESH_QUEUE_NAME: str = (
        os.getenv("MARKET_REFRESH_QUEUE_NAME", "market_refresh").strip() or "market_refresh"
    )
    SIGNAL_ENGINE_QUEUE_NAME: str = os.getenv("SIGNAL_ENGINE_QUEUE_NAME", "signal_engine").strip() or "signal_engine"
    SIGNAL_BACKTEST_QUEUE_NAME: str = (
        os.getenv("SIGNAL_BACKTEST_QUEUE_NAME", "signal_backtest").strip() or "signal_backtest"
    )
    WORKER_QUEUES: tuple[str, ...] = _parse_queue_list(
        os.getenv("WORKER_QUEUES"),
        default=_default_worker_queues(),
    )
    RUN_HEARTBEAT_INTERVAL_SECONDS: int = int(os.getenv("RUN_HEARTBEAT_INTERVAL_SECONDS", "15"))
    RUN_ORPHAN_STALE_SECONDS: int = int(os.getenv("RUN_ORPHAN_STALE_SECONDS", "600"))
    TOP_K_DECISIONS: int = int(os.getenv("TOP_K_DECISIONS", "5"))
    WFO_TRAIN_MONTHS: int = int(os.getenv("WFO_TRAIN_MONTHS", "24"))
    WFO_TEST_MONTHS: int = int(os.getenv("WFO_TEST_MONTHS", "6"))
    WFO_ROLL_MONTHS: int = int(os.getenv("WFO_ROLL_MONTHS", "1"))
    MC_NUM_PATHS: int = int(os.getenv("MC_NUM_PATHS", "200"))


settings = Settings()
