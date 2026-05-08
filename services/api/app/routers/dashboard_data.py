"""Dashboard data router — Phase 1.

GET /dashboard/data/{horizon}
  * legacy   mode: live-compute (original behaviour, D1-D5 intact)
  * shadow   mode: serve live-compute response, also query snapshot and log diffs
  * snapshot mode: SELECT payload_jsonb with ETag/If-None-Match support

POST /dashboard/snapshot/trigger         (admin) — enqueue snapshot refresh for one horizon
POST /dashboard/snapshot/backfill        (admin) — enqueue all three horizons
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..auth import rate_limit_trigger, require_admin
from ..config import settings
from ..db import get_db
from ..freshness import set_freshness
from ..services.dashboard_builder import (
    HORIZON_ALIASES,
    HORIZONS,
    build_dashboard_payload,
    derive_upstream_rev,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _normalize_horizon(raw: str) -> str:
    token = str(raw or "").strip().lower()
    normalized = HORIZON_ALIASES.get(token, token)
    if normalized not in HORIZONS:
        raise HTTPException(status_code=400, detail="Invalid horizon")
    return normalized


def _etag_for(computed_at: Any, upstream_rev: Any) -> str:
    key = f"{computed_at!s}:{json.dumps(upstream_rev, sort_keys=True, default=str)}"
    return '"' + hashlib.md5(key.encode()).hexdigest() + '"'


def _latest_snapshot(db: Session, horizon: str) -> Any:
    return db.execute(
        text("""
        SELECT payload_jsonb, upstream_rev, computed_at, as_of_date
        FROM dashboard_snapshot
        WHERE horizon = :horizon
        ORDER BY as_of_date DESC
        LIMIT 1
        """),
        {"horizon": horizon},
    ).fetchone()


@router.get("/data/{horizon}", response_model=None)
def get_dashboard_data(
    horizon: str,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    horizon = _normalize_horizon(horizon)
    mode = settings.snapshot_read_mode_for("dashboard")

    if mode == "snapshot":
        return _serve_snapshot(horizon, request, response, db)

    if mode == "shadow":
        return _serve_shadow(horizon, request, response, db)

    # legacy — original live-compute path
    payload = build_dashboard_payload(db, horizon)
    return payload


# ---------------------------------------------------------------------------
# Snapshot path
# ---------------------------------------------------------------------------

def _serve_snapshot(
    horizon: str, request: Request, response: Response, db: Session
) -> Any:
    row = _latest_snapshot(db, horizon)
    if row is None:
        raise HTTPException(
            status_code=503,
            detail=(
                f"No snapshot available for horizon '{horizon}'. "
                "Trigger a backfill via POST /dashboard/snapshot/backfill and retry."
            ),
        )

    payload_jsonb, upstream_rev, computed_at, as_of_date = row
    etag = _etag_for(computed_at, upstream_rev)

    set_freshness(
        request,
        computed_at=computed_at,
        upstream_rev=upstream_rev,
        cache="hit",
    )
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, max-age=60"

    if_none_match = request.headers.get("if-none-match", "")
    if if_none_match and etag in (t.strip() for t in if_none_match.split(",")):
        response.status_code = 304
        return Response(status_code=304, headers={"ETag": etag})

    return payload_jsonb


# ---------------------------------------------------------------------------
# Shadow path
# ---------------------------------------------------------------------------

def _serve_shadow(
    horizon: str, request: Request, response: Response, db: Session
) -> Any:
    payload = build_dashboard_payload(db, horizon)

    row = _latest_snapshot(db, horizon)
    if row is None:
        logger.debug("dashboard shadow: no snapshot row for %s — diff skipped", horizon)
        set_freshness(request, cache="miss")
    else:
        _payload, upstream_rev, computed_at, _ = row
        set_freshness(request, computed_at=computed_at, upstream_rev=upstream_rev, cache="shadow")
        # Diff: compare stock count and index aggregate as a lightweight sentinel.
        snap_stocks = len(_payload.get("stocks", []))
        live_stocks = len(payload.get("stocks", []))
        if snap_stocks != live_stocks:
            logger.warning(
                "dashboard shadow DIFF: horizon=%s snapshot_stocks=%d live_stocks=%d",
                horizon, snap_stocks, live_stocks,
            )
        snap_idx = (_payload.get("index") or {}).get("aggregate_score_pct")
        live_idx = (payload.get("index") or {}).get("aggregate_score_pct")
        if snap_idx != live_idx:
            logger.warning(
                "dashboard shadow DIFF: horizon=%s snapshot_index_score=%s live_index_score=%s",
                horizon, snap_idx, live_idx,
            )

    return payload


# ---------------------------------------------------------------------------
# Admin: snapshot trigger + backfill
# ---------------------------------------------------------------------------

class _SnapshotTriggerBody:
    pass


from pydantic import BaseModel


class SnapshotTriggerBody(BaseModel):
    horizon: str | None = None


@router.post(
    "/snapshot/trigger",
    dependencies=[Depends(require_admin), Depends(rate_limit_trigger)],
)
def trigger_dashboard_snapshot(body: SnapshotTriggerBody) -> dict:
    """Enqueue a dashboard snapshot refresh (admin only)."""
    from redis import Redis
    from rq import Queue

    horizon: str | None = None
    if body.horizon:
        horizon = _normalize_horizon(body.horizon)

    redis_conn = Redis.from_url(settings.REDIS_URL, decode_responses=False)
    q = Queue("market_refresh", connection=redis_conn)
    job = q.enqueue(
        "services.worker.tasks.dashboard_snapshot.refresh_dashboard_snapshot",
        horizon,
        job_timeout=600,
    )
    return {"job_id": str(job.id), "horizon": horizon or "all", "status": "queued"}


@router.post(
    "/snapshot/backfill",
    dependencies=[Depends(require_admin), Depends(rate_limit_trigger)],
)
def backfill_dashboard_snapshots() -> dict:
    """Enqueue snapshot refresh for all horizons (admin only).

    Call this once before flipping SNAPSHOT_READ_MODE to 'snapshot'.
    """
    from redis import Redis
    from rq import Queue

    redis_conn = Redis.from_url(settings.REDIS_URL, decode_responses=False)
    q = Queue("market_refresh", connection=redis_conn)
    job_ids: list[str] = []
    for h in ("weekly", "monthly", "quarterly"):
        job = q.enqueue(
            "services.worker.tasks.dashboard_snapshot.refresh_dashboard_snapshot",
            h,
            job_timeout=600,
        )
        job_ids.append(str(job.id))
    return {"job_ids": job_ids, "horizons": ["weekly", "monthly", "quarterly"], "status": "queued"}
