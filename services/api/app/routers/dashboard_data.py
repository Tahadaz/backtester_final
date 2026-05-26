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
from fastapi import status
from pydantic import BaseModel, Field
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
from ..services.dashboard_live import build_dashboard_live_refresh
from ..schemas.dashboard_portfolio import (
    DashboardDailyBlotterRequest,
    DashboardDailyBlotterResponse,
    DashboardPortfolioBacktestRunResponse,
    DashboardPortfolioCreate,
    DashboardPortfolioFromHistoryRequest,
    DashboardPortfolioListResponse,
    DashboardPortfolioOut,
    DashboardPortfolioPositionsRequest,
    DashboardPortfolioPositionsResponse,
    DashboardPortfolioReplayRequest,
    DashboardPortfolioReplayResponse,
    DashboardPortfolioSummaryOut,
    DashboardPortfolioTicketRequest,
    DashboardPortfolioTicketResponse,
    DashboardPortfolioTradeIn,
    DashboardPortfolioTradeOut,
    DashboardPortfolioUpdate,
)
from ..services.dashboard_portfolio import (
    build_dashboard_portfolio_summary,
    build_dashboard_daily_blotter,
    build_dashboard_portfolio_ticket,
    create_dashboard_portfolio,
    create_dashboard_portfolio_backtest_run,
    create_dashboard_portfolio_from_history,
    delete_dashboard_portfolio,
    get_dashboard_portfolio_out,
    list_dashboard_positions,
    list_dashboard_portfolios,
    record_dashboard_portfolio_trade,
    replay_dashboard_portfolio,
    replace_dashboard_positions,
    update_dashboard_portfolio,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard", tags=["dashboard"])
DASHBOARD_SNAPSHOT_JOB_TIMEOUT_SECONDS = 3600


class DashboardLiveRefreshBody(BaseModel):
    symbols: list[str] = Field(default_factory=list)
    horizon: str = "monthly"
    max_age_seconds: int = Field(default=60, ge=0, le=3600)
    persist_history: bool = True
    allow_when_closed: bool = False


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
            and "classic_technical_signal" in stock
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
        str(stock.get("symbol") or "").upper(): (
            stock.get("best_technical_signal"),
            stock.get("classic_technical_signal"),
        )
        for stock in live_payload.get("stocks") or []
        if isinstance(stock, dict)
    }
    for stock in snapshot_payload.get("stocks") or []:
        if not isinstance(stock, dict):
            continue
        symbol = str(stock.get("symbol") or "").upper()
        best_technical, classic_technical = technical_by_symbol.get(symbol, (None, None))
        stock["best_technical_signal"] = best_technical
        stock["classic_technical_signal"] = classic_technical
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


def _serve_live_dashboard_fallback(
    horizon: str,
    request: Request,
    response: Response,
    db: Session,
    *,
    reason: str,
) -> Any:
    logger.warning(
        "dashboard snapshot for %s %s; serving live dashboard fallback",
        horizon,
        reason,
    )
    response.headers["Cache-Control"] = "private, max-age=30"
    set_freshness(request, cache="bypass")
    return _compact_dashboard_payload(build_dashboard_payload(db, horizon, include_edge=True))


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


@router.post("/live-refresh", dependencies=[Depends(rate_limit_trigger)], response_model=None)
def post_dashboard_live_refresh(
    body: DashboardLiveRefreshBody,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    symbols = [str(symbol or "").strip().upper() for symbol in body.symbols if str(symbol or "").strip()]
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        raise HTTPException(status_code=400, detail="No symbols requested")
    if len(symbols) > 80:
        raise HTTPException(status_code=400, detail="Too many symbols requested")
    try:
        return build_dashboard_live_refresh(
            db,
            symbols=symbols,
            horizon=body.horizon,
            max_age_seconds=body.max_age_seconds,
            persist_history=body.persist_history,
            allow_when_closed=body.allow_when_closed,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("dashboard live refresh failed")
        raise HTTPException(status_code=502, detail=f"Dashboard live refresh failed: {exc}") from exc


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


@router.get("/portfolios", response_model=DashboardPortfolioListResponse)
def get_dashboard_portfolios(
    user: AppUser = Depends(require_app_user),
    _auth: None = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DashboardPortfolioListResponse:
    return list_dashboard_portfolios(db, owner_user_id=user.id, include_summary=True)


@router.post("/portfolios", response_model=DashboardPortfolioOut, status_code=status.HTTP_201_CREATED)
def post_dashboard_portfolio(
    body: DashboardPortfolioCreate,
    user: AppUser = Depends(require_app_user),
    _auth: None = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DashboardPortfolioOut:
    try:
        return create_dashboard_portfolio(db, body, owner_user_id=user.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/portfolios/from-history", response_model=DashboardPortfolioReplayResponse, status_code=status.HTTP_201_CREATED)
def post_dashboard_portfolio_from_history(
    body: DashboardPortfolioFromHistoryRequest,
    user: AppUser = Depends(require_app_user),
    _auth: None = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DashboardPortfolioReplayResponse:
    try:
        return create_dashboard_portfolio_from_history(db, body, owner_user_id=user.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/portfolios/{portfolio_id}", response_model=DashboardPortfolioOut)
def get_dashboard_portfolio(
    portfolio_id: str,
    user: AppUser = Depends(require_app_user),
    _auth: None = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DashboardPortfolioOut:
    try:
        return get_dashboard_portfolio_out(db, portfolio_id, owner_user_id=user.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/portfolios/{portfolio_id}", response_model=DashboardPortfolioOut)
def patch_dashboard_portfolio(
    portfolio_id: str,
    body: DashboardPortfolioUpdate,
    user: AppUser = Depends(require_app_user),
    _auth: None = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DashboardPortfolioOut:
    try:
        return update_dashboard_portfolio(db, portfolio_id, body, owner_user_id=user.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/portfolios/{portfolio_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dashboard_portfolio_endpoint(
    portfolio_id: str,
    user: AppUser = Depends(require_app_user),
    _auth: None = Depends(require_auth),
    db: Session = Depends(get_db),
) -> Response:
    try:
        delete_dashboard_portfolio(db, portfolio_id, owner_user_id=user.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/portfolios/{portfolio_id}/positions", response_model=DashboardPortfolioPositionsResponse)
def get_dashboard_named_portfolio_positions(
    portfolio_id: str,
    user: AppUser = Depends(require_app_user),
    _auth: None = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DashboardPortfolioPositionsResponse:
    try:
        return list_dashboard_positions(db, owner_user_id=user.id, portfolio_id=portfolio_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/portfolios/{portfolio_id}/positions", response_model=DashboardPortfolioPositionsResponse)
def put_dashboard_named_portfolio_positions(
    portfolio_id: str,
    body: DashboardPortfolioPositionsRequest,
    user: AppUser = Depends(require_app_user),
    _auth: None = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DashboardPortfolioPositionsResponse:
    try:
        return replace_dashboard_positions(db, body, owner_user_id=user.id, portfolio_id=portfolio_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/portfolios/{portfolio_id}/summary", response_model=DashboardPortfolioSummaryOut)
def get_dashboard_named_portfolio_summary(
    portfolio_id: str,
    price_source: str = "live_if_fresh",
    max_live_quote_age_seconds: int = 60,
    user: AppUser = Depends(require_app_user),
    _auth: None = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DashboardPortfolioSummaryOut:
    try:
        return build_dashboard_portfolio_summary(
            db,
            owner_user_id=user.id,
            portfolio_id=portfolio_id,
            price_source=price_source,
            max_live_quote_age_seconds=max_live_quote_age_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/portfolios/{portfolio_id}/trades", response_model=DashboardPortfolioTradeOut)
def post_dashboard_named_portfolio_trade(
    portfolio_id: str,
    body: DashboardPortfolioTradeIn,
    user: AppUser = Depends(require_app_user),
    _auth: None = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DashboardPortfolioTradeOut:
    try:
        return record_dashboard_portfolio_trade(db, body, owner_user_id=user.id, portfolio_id=portfolio_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/portfolios/{portfolio_id}/generate-history", response_model=DashboardPortfolioReplayResponse)
def post_dashboard_named_portfolio_replay(
    portfolio_id: str,
    body: DashboardPortfolioReplayRequest,
    user: AppUser = Depends(require_app_user),
    _auth: None = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DashboardPortfolioReplayResponse:
    try:
        return replay_dashboard_portfolio(db, portfolio_id, body, owner_user_id=user.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/portfolios/{portfolio_id}/backtest-run", response_model=DashboardPortfolioBacktestRunResponse)
def post_dashboard_named_portfolio_backtest_run(
    portfolio_id: str,
    user: AppUser = Depends(require_app_user),
    _auth: None = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DashboardPortfolioBacktestRunResponse:
    try:
        return create_dashboard_portfolio_backtest_run(db, portfolio_id, owner_user_id=user.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@router.get("/portfolio/summary", response_model=DashboardPortfolioSummaryOut)
def get_dashboard_portfolio_summary(
    price_source: str = "live_if_fresh",
    max_live_quote_age_seconds: int = 60,
    user: AppUser = Depends(require_app_user),
    _auth: None = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DashboardPortfolioSummaryOut:
    return build_dashboard_portfolio_summary(
        db,
        owner_user_id=user.id,
        price_source=price_source,
        max_live_quote_age_seconds=max_live_quote_age_seconds,
    )


@router.post("/portfolio/trades", response_model=DashboardPortfolioTradeOut)
def post_dashboard_portfolio_trade(
    body: DashboardPortfolioTradeIn,
    user: AppUser = Depends(require_app_user),
    _auth: None = Depends(require_auth),
    db: Session = Depends(get_db),
) -> DashboardPortfolioTradeOut:
    try:
        return record_dashboard_portfolio_trade(db, body, owner_user_id=user.id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
        return _serve_live_dashboard_fallback(
            horizon,
            request,
            response,
            db,
            reason="is missing",
        )

    payload_jsonb, upstream_rev, computed_at, as_of_date = row
    if not _dashboard_snapshot_has_current_shape(payload_jsonb):
        if not _dashboard_snapshot_can_merge_live_technical(payload_jsonb):
            return _serve_live_dashboard_fallback(
                horizon,
                request,
                response,
                db,
                reason="has unusable stale shape",
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
        job_timeout=DASHBOARD_SNAPSHOT_JOB_TIMEOUT_SECONDS,
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
            job_timeout=DASHBOARD_SNAPSHOT_JOB_TIMEOUT_SECONDS,
        )
        job_ids.append(str(job.id))
    return {"job_ids": job_ids, "horizons": ["weekly", "monthly", "quarterly"], "status": "queued"}
