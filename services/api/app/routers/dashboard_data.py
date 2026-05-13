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

from ..auth import AppUser, optional_app_user, rate_limit_trigger, require_admin, require_app_user, require_auth
from ..config import settings
from ..db import get_db
from ..freshness import set_freshness
from ..services.dashboard_builder import (
    DASHBOARD_PAYLOAD_VERSION,
    HORIZON_ALIASES,
    HORIZONS,
    build_dashboard_payload,
    derive_upstream_rev,
)
from ..schemas.dashboard_portfolio import (
    DashboardDailyBlotterRequest,
    DashboardDailyBlotterResponse,
    DashboardPortfolioPositionsRequest,
    DashboardPortfolioPositionsResponse,
    DashboardPortfolioTicketRequest,
    DashboardPortfolioTicketResponse,
)
from ..services.dashboard_portfolio import (
    build_dashboard_daily_blotter,
    build_dashboard_portfolio_ticket,
    list_dashboard_positions,
    replace_dashboard_positions,
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


def _compact_dashboard_payload(payload: Any) -> Any:
    """Remove fields that are too heavy for the initial dashboard table load."""
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        return payload
    for stock in payload.get("stocks") or []:
        if not isinstance(stock, dict):
            continue
        edge = stock.get("edge")
        if not isinstance(edge, dict):
            continue
        for edge_payload in edge.values():
            if isinstance(edge_payload, dict):
                edge_payload.pop("fragility_details", None)
    return payload


def _compact_dashboard_payload_json(payload: Any) -> str | None:
    try:
        compact = _compact_dashboard_payload(payload)
    except (TypeError, json.JSONDecodeError):
        return payload if isinstance(payload, str) else None
    return json.dumps(compact, separators=(",", ":"), default=str)


def _payload_dict(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def _dashboard_snapshot_has_current_shape(payload: Any) -> bool:
    """Return whether a snapshot carries the fields required by the current UI."""
    payload_dict = _payload_dict(payload)
    if payload_dict is None:
        return False
    if payload_dict.get("payload_version") != DASHBOARD_PAYLOAD_VERSION:
        return False
    stocks = payload_dict.get("stocks")
    if not isinstance(stocks, list):
        return False
    return all(
        not isinstance(stock, dict)
        or (
            "best_technical_signal" in stock
            and (
                not isinstance(stock.get("best_signal"), dict)
                or "edge_score" in stock["best_signal"]
            )
        )
        for stock in stocks
    )


def _snapshot_has_legacy_best_signal(payload_dict: dict[str, Any]) -> bool:
    stocks = payload_dict.get("stocks")
    if not isinstance(stocks, list):
        return False
    return any(
        isinstance(stock, dict)
        and isinstance(stock.get("best_signal"), dict)
        and "edge_score" not in stock["best_signal"]
        for stock in stocks
    )


def _dashboard_snapshot_can_merge_live_technical(payload: Any) -> bool:
    """Return whether a stale snapshot is usable after a lightweight technical merge."""
    payload_dict = _payload_dict(payload)
    if payload_dict is None:
        return False
    stocks = payload_dict.get("stocks")
    return isinstance(stocks, list) and not _snapshot_has_legacy_best_signal(payload_dict)


def _merge_live_technical_signals(snapshot_payload: dict[str, Any], live_payload: dict[str, Any]) -> dict[str, Any]:
    technical_by_symbol = {
        str(stock.get("symbol") or "").upper(): stock.get("best_technical_signal")
        for stock in live_payload.get("stocks") or []
        if isinstance(stock, dict)
    }
    for stock in snapshot_payload.get("stocks") or []:
        if not isinstance(stock, dict):
            continue
        symbol = str(stock.get("symbol") or "").upper()
        stock["best_technical_signal"] = technical_by_symbol.get(symbol)
    snapshot_payload.setdefault("payload_version", DASHBOARD_PAYLOAD_VERSION)
    return snapshot_payload


def _latest_snapshot(db: Session, horizon: str) -> Any:
    return db.execute(
        text("""
        SELECT payload_jsonb::text AS payload_jsonb, upstream_rev, computed_at, as_of_date
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
    payload = build_dashboard_payload(db, horizon, include_edge=True)
    return payload


@router.post("/portfolio-ticket", response_model=DashboardPortfolioTicketResponse)
def get_dashboard_portfolio_ticket(
    body: DashboardPortfolioTicketRequest,
    db: Session = Depends(get_db),
) -> DashboardPortfolioTicketResponse:
    """Build a next-session trade ticket from a manually selected dashboard basket."""
    return build_dashboard_portfolio_ticket(
        db,
        body,
        cost_bps=float(settings.EDGE_COST_BPS_PER_SIDE),
    )


@router.get("/portfolio/positions", response_model=DashboardPortfolioPositionsResponse)
def get_dashboard_portfolio_positions(
    user: AppUser = Depends(require_app_user),
    _auth: None = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DashboardPortfolioPositionsResponse:
    """Return the manually maintained desk portfolio state used by the blotter."""
    return list_dashboard_positions(db, owner_user_id=user.id)


@router.put("/portfolio/positions", response_model=DashboardPortfolioPositionsResponse)
def put_dashboard_portfolio_positions(
    body: DashboardPortfolioPositionsRequest,
    user: AppUser = Depends(require_app_user),
    _auth: None = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DashboardPortfolioPositionsResponse:
    """Replace active manual positions for portfolio follow-up."""
    return replace_dashboard_positions(db, body, owner_user_id=user.id)


@router.post("/daily-blotter", response_model=DashboardDailyBlotterResponse)
def get_dashboard_daily_blotter(
    body: DashboardDailyBlotterRequest,
    user: AppUser | None = Depends(optional_app_user),
    db: Session = Depends(get_db),
) -> DashboardDailyBlotterResponse:
    """Build the next-session desk blotter from selected symbols and positions."""
    return build_dashboard_daily_blotter(
        db,
        body,
        cost_bps=float(settings.EDGE_COST_BPS_PER_SIDE),
        owner_user_id=user.id if user is not None else None,
    )


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
    if not _dashboard_snapshot_has_current_shape(payload_jsonb):
        if not _dashboard_snapshot_can_merge_live_technical(payload_jsonb):
            logger.warning(
                "dashboard snapshot for %s has unusable stale shape; refusing live edge fallback",
                horizon,
            )
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Dashboard snapshot for horizon '{horizon}' is stale or invalid. "
                    "Trigger a backfill via POST /dashboard/snapshot/backfill and retry."
                ),
            )
        logger.warning(
            "dashboard snapshot for %s has stale shape; merging live technical signals until backfill refreshes it",
            horizon,
        )
        response.headers["Cache-Control"] = "private, max-age=30"
        set_freshness(request, cache="stale")
        snapshot_payload = _payload_dict(payload_jsonb)
        if snapshot_payload is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Dashboard snapshot for horizon '{horizon}' is invalid. "
                    "Trigger a backfill via POST /dashboard/snapshot/backfill and retry."
                ),
            )
        live_payload = build_dashboard_payload(db, horizon, include_edge=False)
        return _compact_dashboard_payload(
            _merge_live_technical_signals(snapshot_payload, live_payload)
        )

    etag = _etag_for(
        computed_at,
        {"upstream_rev": upstream_rev, "payload_shape": "dashboard-compact-v1"},
    )

    set_freshness(
        request,
        computed_at=computed_at,
        upstream_rev=upstream_rev,
        cache="hit",
    )
    headers = {
        "ETag": etag,
        "Cache-Control": "private, max-age=60",
    }
    response.headers.update(headers)

    if_none_match = request.headers.get("if-none-match", "")
    if if_none_match and etag in (t.strip() for t in if_none_match.split(",")):
        response.status_code = 304
        return Response(status_code=304, headers={"ETag": etag})

    compact_json = _compact_dashboard_payload_json(payload_jsonb)
    if compact_json is not None:
        return Response(
            content=compact_json,
            media_type="application/json",
            headers=headers,
        )

    return _compact_dashboard_payload(payload_jsonb)


# ---------------------------------------------------------------------------
# Shadow path
# ---------------------------------------------------------------------------

def _serve_shadow(
    horizon: str, request: Request, response: Response, db: Session
) -> Any:
    payload = build_dashboard_payload(db, horizon, include_edge=True)

    row = _latest_snapshot(db, horizon)
    if row is None:
        logger.debug("dashboard shadow: no snapshot row for %s — diff skipped", horizon)
        set_freshness(request, cache="miss")
    else:
        _payload, upstream_rev, computed_at, _ = row
        if isinstance(_payload, str):
            try:
                _payload = json.loads(_payload)
            except json.JSONDecodeError:
                logger.warning("dashboard shadow: snapshot JSON decode failed for %s", horizon)
                _payload = {}
        _payload = _compact_dashboard_payload(_payload)
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
