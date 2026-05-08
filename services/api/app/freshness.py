"""Phase 0 — freshness/lineage helpers.

Endpoints stash the upstream revision tuple, the time the data was computed
and a cache-status verdict on ``request.state``; the middleware in
``main.py`` reads them off and emits ``X-Computed-At``, ``X-Upstream-Rev``
and ``X-Cache`` response headers uniformly.

Endpoints don't have to set anything — endpoints that don't will simply
have no freshness headers (legacy live-compute paths).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Literal, Mapping

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


CacheStatus = Literal["hit", "miss", "stale", "bypass", "shadow"]


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def set_freshness(
    request: Request,
    *,
    computed_at: datetime | date | str | None = None,
    upstream_rev: Mapping[str, Any] | str | None = None,
    cache: CacheStatus | None = None,
) -> None:
    """Stash freshness metadata on the request so the middleware can emit headers.

    Safe to call multiple times — last write wins.
    """
    state = request.state
    if computed_at is not None:
        state.computed_at = _to_iso(computed_at)
    if upstream_rev is not None:
        if isinstance(upstream_rev, str):
            state.upstream_rev = upstream_rev
        else:
            state.upstream_rev = json.dumps(
                dict(upstream_rev), separators=(",", ":"), sort_keys=True, default=str
            )
    if cache is not None:
        state.cache_status = cache


class FreshnessHeadersMiddleware(BaseHTTPMiddleware):
    """Copy freshness metadata from ``request.state`` onto response headers."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response: Response = await call_next(request)
        state = getattr(request, "state", None)
        if state is None:
            return response
        computed_at = getattr(state, "computed_at", None)
        if computed_at:
            response.headers["X-Computed-At"] = str(computed_at)
        upstream_rev = getattr(state, "upstream_rev", None)
        if upstream_rev:
            response.headers["X-Upstream-Rev"] = str(upstream_rev)
        cache_status = getattr(state, "cache_status", None)
        if cache_status:
            response.headers["X-Cache"] = str(cache_status)
        return response
