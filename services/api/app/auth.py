from __future__ import annotations

import hmac
from typing import Iterable

from fastapi import Header, HTTPException, Request

from .config import settings


def _check_jwt(authorization: str | None, *, required_scopes: Iterable[str] | None = None) -> bool:
    """Return True if the bearer token is valid and (optionally) carries one of ``required_scopes``."""
    jwt_secret = settings.INTERNAL_JWT_SECRET.strip()
    if not jwt_secret or not authorization or not authorization.startswith("Bearer "):
        return False
    token = authorization[7:]
    try:
        from jose import jwt  # type: ignore[import]
        payload = jwt.decode(token, jwt_secret, algorithms=["HS256"])
    except Exception:
        return False
    if not required_scopes:
        return True
    raw_scope = payload.get("scope") or payload.get("scopes") or ""
    if isinstance(raw_scope, str):
        scopes = {s.strip().lower() for s in raw_scope.split() if s.strip()}
    elif isinstance(raw_scope, (list, tuple, set)):
        scopes = {str(s).strip().lower() for s in raw_scope if str(s).strip()}
    else:
        scopes = set()
    return any(s.lower() in scopes for s in required_scopes)


def require_auth(
    x_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    api_key = settings.API_KEY.strip()
    jwt_secret = settings.INTERNAL_JWT_SECRET.strip()

    # Dev mode: no auth configured at all
    if not api_key and not jwt_secret:
        return

    # API-key path (used by the Next.js proxy, which injects API_KEY server-side)
    if api_key and x_api_key and hmac.compare_digest(x_api_key, api_key):
        return

    # Bearer JWT path (forward-compat: used once Auth.js session minting is wired)
    if jwt_secret and authorization and authorization.startswith("Bearer "):
        if _check_jwt(authorization):
            return
        raise HTTPException(status_code=401, detail="invalid token")

    raise HTTPException(status_code=401, detail="missing or invalid credentials")


def require_admin(
    x_api_key: str | None = Header(default=None),
    x_admin_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    """Phase 0 — gate Trigger / refresh endpoints behind an admin scope.

    Accepts:
      * ``X-Admin-Api-Key`` matching ``settings.ADMIN_API_KEY`` (dedicated admin key), or
      * a Bearer JWT carrying one of ``settings.ADMIN_SCOPES`` claims, or
      * (dev mode only — when no credentials are configured at all) anything.
    """
    api_key = settings.API_KEY.strip()
    jwt_secret = settings.INTERNAL_JWT_SECRET.strip()
    admin_key = settings.ADMIN_API_KEY.strip()

    # Dev mode: nothing configured anywhere → wide-open like require_auth.
    if not api_key and not jwt_secret and not admin_key:
        return

    # Dedicated admin API-key (preferred): doesn't grant general access, only admin.
    if admin_key and x_admin_api_key and hmac.compare_digest(x_admin_api_key, admin_key):
        return

    # JWT with admin scope.
    if jwt_secret and authorization and _check_jwt(authorization, required_scopes=settings.ADMIN_SCOPES):
        return

    # Fallback: if no dedicated admin key is set and the caller passes the
    # general API key, accept it (single-tenant deployments). This preserves
    # behaviour for installs that haven't rolled out an admin key yet.
    if not admin_key and api_key and x_api_key and hmac.compare_digest(x_api_key, api_key):
        return

    raise HTTPException(status_code=403, detail="admin scope required")


# Backward-compatible alias — existing routers use Depends(auth.require_api_key)
require_api_key = require_auth


def require_bloomberg_bridge_key(
    x_bloomberg_bridge_key: str | None = Header(default=None),
) -> None:
    """Authenticate the dedicated Bloomberg bridge ingestion surface."""
    bridge_key = settings.BLOOMBERG_BRIDGE_API_KEY.strip()
    if not bridge_key:
        raise HTTPException(status_code=503, detail="Bloomberg bridge is not configured")
    if x_bloomberg_bridge_key and hmac.compare_digest(x_bloomberg_bridge_key, bridge_key):
        return
    raise HTTPException(status_code=401, detail="missing or invalid Bloomberg bridge key")


# ---------------------------------------------------------------------------
# Phase 0 — per-IP rate limit for trigger endpoints
# ---------------------------------------------------------------------------

import time
from threading import Lock


class _InMemoryRateLimiter:
    """Process-local sliding-window counter. Used as a fallback when Redis is down."""

    def __init__(self) -> None:
        self._buckets: dict[str, list[float]] = {}
        self._lock = Lock()

    def hit(self, key: str, *, limit: int, window_seconds: int) -> bool:
        if limit <= 0 or window_seconds <= 0:
            return True
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._buckets.setdefault(key, [])
            # Drop expired timestamps; keep list bounded.
            bucket[:] = [ts for ts in bucket if ts > cutoff]
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            return True


_LIMITER = _InMemoryRateLimiter()


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _redis_rate_limit(key: str, *, limit: int, window_seconds: int) -> bool | None:
    """Try Redis-backed rate limit. Returns None if Redis is unavailable."""
    try:
        from redis import Redis  # type: ignore[import]
    except Exception:
        return None
    try:
        conn = Redis.from_url(settings.REDIS_URL, decode_responses=True, socket_timeout=0.25)
        pipe = conn.pipeline()
        pipe.incr(key, 1)
        pipe.expire(key, window_seconds)
        count, _ = pipe.execute()
        return int(count) <= limit
    except Exception:
        return None


def rate_limit_trigger(request: Request) -> None:
    """Per-IP rate limit for trigger endpoints.

    Uses Redis when available (so multiple API workers share the bucket);
    falls back to a process-local counter otherwise.
    """
    limit = settings.TRIGGER_RATE_LIMIT_PER_MIN
    window = settings.TRIGGER_RATE_LIMIT_WINDOW_SECONDS
    if limit <= 0 or window <= 0:
        return
    ip = _client_ip(request)
    bucket_key = f"ratelimit:trigger:{ip}:{request.url.path}"
    redis_decision = _redis_rate_limit(bucket_key, limit=limit, window_seconds=window)
    if redis_decision is False:
        raise HTTPException(status_code=429, detail="trigger rate limit exceeded")
    if redis_decision is None:
        if not _LIMITER.hit(bucket_key, limit=limit, window_seconds=window):
            raise HTTPException(status_code=429, detail="trigger rate limit exceeded")
