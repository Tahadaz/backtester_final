from __future__ import annotations

import logging
import os
from urllib.parse import SplitResult, urlsplit, urlunsplit

from redis import Redis


_DOCKER_REDIS_HOST_ALIASES = {"quant_redis", "redis"}


def _replace_url_host(redis_url: str, host: str) -> str:
    parts = urlsplit(redis_url)
    if not parts.hostname:
        return redis_url

    userinfo = ""
    if parts.username is not None:
        userinfo = parts.username
        if parts.password is not None:
            userinfo = f"{userinfo}:{parts.password}"
        userinfo = f"{userinfo}@"

    port = f":{parts.port}" if parts.port is not None else ""
    netloc = f"{userinfo}{host}{port}"
    rebuilt = SplitResult(parts.scheme, netloc, parts.path, parts.query, parts.fragment)
    return urlunsplit(rebuilt)


def _redis_url_candidates(redis_url: str) -> list[str]:
    out: list[str] = []
    hostname = (urlsplit(redis_url).hostname or "").strip().lower()
    if hostname in _DOCKER_REDIS_HOST_ALIASES:
        # In local host-mode runs, docker DNS aliases can hang on resolution.
        # Prefer loopback first so API trigger endpoints stay responsive.
        for fallback_host in ("localhost", "127.0.0.1"):
            candidate = _replace_url_host(redis_url, fallback_host)
            if candidate not in out:
                out.append(candidate)
        if _likely_in_container() and redis_url not in out:
            out.insert(0, redis_url)
        return out
    out.append(redis_url)
    return out


def _likely_in_container() -> bool:
    if os.path.exists("/.dockerenv"):
        return True
    try:
        with open("/proc/1/cgroup", "r", encoding="utf-8") as fh:
            data = fh.read()
        lowered = data.lower()
        return ("docker" in lowered) or ("containerd" in lowered) or ("kubepods" in lowered)
    except Exception:
        return False


def connect_redis_with_fallback(
    redis_url: str,
    *,
    decode_responses: bool,
    logger: logging.Logger | None = None,
    socket_connect_timeout: float = 5.0,
    socket_timeout: float = 30.0,
) -> Redis:
    """Connect to Redis using docker-friendly URL fallbacks for local runs.

    When REDIS_URL points at docker service aliases like ``quant_redis`` but the
    API/worker runs directly on the host, DNS resolution can fail. This helper
    keeps the configured URL as the first choice, then falls back to localhost
    targets only for those known docker aliases.
    """
    candidates = _redis_url_candidates(redis_url)
    last_error: Exception | None = None

    for idx, url in enumerate(candidates):
        client = Redis.from_url(
            url,
            decode_responses=decode_responses,
            socket_connect_timeout=socket_connect_timeout,
            socket_timeout=socket_timeout,
            retry_on_timeout=False,
        )
        try:
            client.ping()
            if idx > 0 and logger is not None:
                logger.warning(
                    "Redis URL fallback in use. requested_host=%s active_host=%s",
                    urlsplit(redis_url).hostname,
                    urlsplit(url).hostname,
                )
            return client
        except Exception as exc:  # pragma: no cover - exercised in integration
            last_error = exc
            try:
                client.close()
            except Exception:
                pass

    if last_error is not None:
        raise last_error
    raise RuntimeError("Unable to establish Redis connection")
