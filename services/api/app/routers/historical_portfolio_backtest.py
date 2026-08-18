from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session, load_only

from core.quant_core.historical_portfolio import CAPACITY_SCENARIOS, DECISION_HORIZONS, METHODOLOGY_VERSION
from .. import models
from ..db import get_db
from ..queue import get_queue
from ..schemas.historical_portfolio_backtest import (
    HistoricalOpportunityMaterializationCreate,
    HistoricalOpportunityMaterializationOut,
    HistoricalPortfolioRunCreate,
    HistoricalPortfolioRunCreated,
    HistoricalPortfolioRunResult,
    HistoricalPortfolioRunStatus,
)
from ..services.historical_opportunity_store import configs_equal, missing_coverage_ranges, opportunity_store_coverage
from ..services.market_universe import list_masi_signal_universe_symbols

router = APIRouter(prefix="/strategy/signal/historical-portfolio-backtests", tags=["historical-portfolio-backtests"])

MASI_CALENDAR_SYMBOL = "MASI"
MATERIALIZATION_CHUNK_DAYS = 90


def _resolve_scope(db: Session, config: dict) -> dict:
    if "_system" in config:
        raise HTTPException(status_code=422, detail="_system is reserved for server-generated metadata")
    resolved = sorted(set(list_masi_signal_universe_symbols(db)))
    if not resolved:
        raise HTTPException(status_code=422, detail="Resolved MASI universe is empty")
    requested = sorted(set(config.get("symbols") or []))
    offenders = sorted(set(requested) - set(resolved))
    if offenders:
        raise HTTPException(
            status_code=422,
            detail={"code": "symbols_outside_resolved_masi_universe", "offenders": offenders},
        )
    coverage = db.query(
        func.min(models.SignalScoreHistory.date), func.max(models.SignalScoreHistory.date),
    ).filter(models.SignalScoreHistory.is_oos.is_(True)).one()
    supported_start, supported_end = coverage
    if supported_start is None or supported_end is None:
        raise HTTPException(status_code=422, detail="No persisted OOS score-history coverage")
    # The weekly decision grid comes from the MASI index trading calendar, so a window with score
    # history but no MASI bars yields zero decision dates. Clamp to both, not just score history.
    calendar = db.query(
        models.MarketDataStore.start_ts, models.MarketDataStore.end_ts,
    ).filter_by(symbol=MASI_CALENDAR_SYMBOL, timeframe="1D").first()
    if calendar is None or calendar[0] is None or calendar[1] is None:
        raise HTTPException(
            status_code=422,
            detail={"code": "masi_calendar_unavailable", "symbol": MASI_CALENDAR_SYMBOL},
        )
    calendar_start, calendar_end = calendar[0].date(), calendar[1].date()
    supported_start = max(supported_start, calendar_start)
    supported_end = min(supported_end, calendar_end)
    requested_start = date.fromisoformat(str(config["start_date"]))
    requested_end = date.fromisoformat(str(config["end_date"]))
    clamped_start = max(requested_start, supported_start)
    clamped_end = min(requested_end, supported_end)
    if clamped_end < clamped_start or supported_end < supported_start:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "window_outside_supported_coverage",
                "supported_start": supported_start.isoformat(),
                "supported_end": supported_end.isoformat(),
                "masi_calendar_start": calendar_start.isoformat(),
                "masi_calendar_end": calendar_end.isoformat(),
            },
        )
    return {
        **config,
        "start_date": clamped_start.isoformat(),
        "end_date": clamped_end.isoformat(),
        "symbols": requested,
        "resolved_universe": resolved,
    }


def _inflight_materialization_id(db: Session) -> str | None:
    row = db.query(models.HistoricalOpportunityMaterializationRun).filter(
        models.HistoricalOpportunityMaterializationRun.status.in_(("queued", "running")),
        models.HistoricalOpportunityMaterializationRun.methodology_version == METHODOLOGY_VERSION,
    ).order_by(models.HistoricalOpportunityMaterializationRun.created_at.desc()).first()
    return str(row.id) if row is not None else None


def _chunked(ranges: list[tuple[date, date]], chunk_days: int) -> list[tuple[date, date]]:
    """Split each range so one failure costs a chunk, never the whole precalculation."""

    windows: list[tuple[date, date]] = []
    for start, end in ranges:
        cursor = start
        while cursor <= end:
            chunk_end = min(end, cursor + timedelta(days=chunk_days - 1))
            windows.append((cursor, chunk_end))
            cursor = chunk_end + timedelta(days=1)
    return windows


def _row_or_404(db: Session, run_id: UUID) -> models.HistoricalPortfolioBacktestRun:
    row = db.query(models.HistoricalPortfolioBacktestRun).filter_by(id=run_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Historical portfolio backtest run not found")
    return row


def _fetch_rq_job(job_id: str, connection):
    from rq.job import Job

    return Job.fetch(job_id, connection=connection)


def _rq_job_worker_is_dead(job, connection) -> bool:
    """True when a 'started' job's worker is no longer among RQ's live workers.

    Live workers renew a heartbeat with a TTL, so a restarted/crashed worker drops out of the set
    within that window; its in-flight job then reads as orphaned rather than perpetually running.
    Any uncertainty (no recorded worker name, RQ API differences) returns False — never fail a live
    run on a soft signal.
    """

    worker_name = getattr(job, "worker_name", None)
    if not worker_name:
        return False
    try:
        from rq.worker import Worker

        live = {w.name for w in Worker.all(connection=connection)}
    except Exception:
        return False
    return worker_name not in live


def _reconcile_rq_state(db: Session, row) -> None:
    """Reconcile only authoritative RQ terminal signals; outages are read-safe."""

    if row.status not in {"queued", "running"} or not row.rq_job_id:
        return
    try:
        from redis.exceptions import RedisError

        connection = get_queue().connection
        job = _fetch_rq_job(str(row.rq_job_id), connection)
        rq_status = str(job.get_status(refresh=True) or "").lower()
        if rq_status == "deferred":
            for dependency_id in getattr(job, "dependency_ids", ()) or ():
                dependency = _fetch_rq_job(str(dependency_id), connection)
                dependency_status = str(dependency.get_status(refresh=True) or "").lower()
                if dependency_status in {"failed", "canceled", "stopped"}:
                    row.status = "failed"
                    row.error_message = f"RQ dependency {dependency_id} ended as {dependency_status}"
                    break
        elif rq_status in {"failed", "canceled", "stopped"}:
            row.status = "failed"
            row.error_message = f"RQ job ended as {rq_status}"
        elif rq_status == "started" and _rq_job_worker_is_dead(job, connection):
            # A worker that dies mid-run leaves its job stuck "started" until registry maintenance
            # runs (up to job_timeout later). Without this, the panel polls a dead run forever.
            row.status = "failed"
            row.error_message = "RQ worker for this job is no longer alive (orphaned by worker restart)"
        if row.status == "failed":
            db.commit()
    except Exception as exc:
        if exc.__class__.__name__ == "NoSuchJobError":
            row.status = "failed"
            row.error_message = f"RQ job {row.rq_job_id} no longer exists"
            db.commit()
        elif isinstance(exc, (RedisError, ConnectionError, TimeoutError)):
            db.rollback()
        else:
            raise


@router.post("", response_model=HistoricalPortfolioRunCreated, status_code=status.HTTP_202_ACCEPTED)
def create_historical_portfolio_backtest(
    body: HistoricalPortfolioRunCreate,
    db: Session = Depends(get_db),
):
    normalized_config = _resolve_scope(db, body.model_dump(mode="json"))
    coverage = opportunity_store_coverage(db, normalized_config)
    normalized_start = date.fromisoformat(normalized_config["start_date"])
    normalized_end = date.fromisoformat(normalized_config["end_date"])
    missing = missing_coverage_ranges(coverage, normalized_start, normalized_end)
    if missing:
        # A launch never silently starts a rebuild: uncovered dates are reported so the caller can
        # precalculate exactly the missing sub-ranges (POST /materializations) and retry.
        raise HTTPException(
            status_code=409,
            detail={
                "code": "pit_coverage_incomplete",
                "missing_ranges": [
                    {"start": start.isoformat(), "end": end.isoformat()} for start, end in missing
                ],
                "covered_intervals": coverage["intervals"],
                "materialization_in_progress": _inflight_materialization_id(db),
            },
        )
    recent = db.query(models.HistoricalPortfolioBacktestRun).filter_by(
        status="succeeded", methodology_version=METHODOLOGY_VERSION,
    ).order_by(models.HistoricalPortfolioBacktestRun.completed_at.desc()).limit(25).all()
    for cached in recent:
        cached_runs = (cached.provenance_json or {}).get("opportunity_store_materialization_runs") or []
        if configs_equal(cached.config_json, normalized_config) and cached_runs == coverage["materialization_run_ids"]:
            return HistoricalPortfolioRunCreated(run_id=str(cached.id), status="succeeded", reused=True)
    row = models.HistoricalPortfolioBacktestRun(
        status="queued", methodology_version=METHODOLOGY_VERSION,
        config_json=normalized_config, provenance_json={}, diagnostics_json={},
        opportunities_json=[], trades_json=[], equity_curves_json={}, benchmark_curves_json={},
        statistics_json={}, validation_json={}, snapshot_audit_json={}, warnings_json=[],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    try:
        job = get_queue().enqueue(
            "services.worker.tasks.historical_portfolio_backtest.execute_historical_portfolio_backtest",
            str(row.id), job_timeout="12h",
        )
        row.rq_job_id = str(job.id)
        db.commit()
    except Exception as exc:
        row.status = "failed"
        row.error_message = f"Could not enqueue background job: {exc}"
        db.commit()
        raise HTTPException(status_code=503, detail=row.error_message) from exc
    return HistoricalPortfolioRunCreated(run_id=str(row.id), status="queued", reused=False)


def _serialize_materialization(row: models.HistoricalOpportunityMaterializationRun):
    return HistoricalOpportunityMaterializationOut(
        materialization_run_id=str(row.id), status=row.status,
        methodology_version=row.methodology_version, config=row.config_json or {},
        progress=row.progress_json or {}, coverage=row.coverage_json or {},
        error_message=row.error_message, created_at=row.created_at,
        started_at=row.started_at, completed_at=row.completed_at,
    )


@router.post("/materializations", response_model=HistoricalOpportunityMaterializationOut, status_code=status.HTTP_202_ACCEPTED)
def create_historical_opportunity_materialization(
    body: HistoricalOpportunityMaterializationCreate,
    db: Session = Depends(get_db),
):
    requested = body.model_dump(mode="json")
    requested["symbols"] = []
    config = _resolve_scope(db, requested)
    config["symbols"] = config["resolved_universe"]
    existing = db.query(models.HistoricalOpportunityMaterializationRun).filter(
        models.HistoricalOpportunityMaterializationRun.status.in_(("queued", "running")),
        models.HistoricalOpportunityMaterializationRun.methodology_version == METHODOLOGY_VERSION,
    ).order_by(models.HistoricalOpportunityMaterializationRun.created_at.desc()).with_for_update().first()
    if existing is not None and configs_equal(existing.config_json, config):
        return _serialize_materialization(existing)
    # Precalculate only what is actually missing, in chunks: re-running covered dates is the
    # difference between "quick top-up" and "multi-hour full rebuild".
    coverage = opportunity_store_coverage(db, config)
    windows = _chunked(
        missing_coverage_ranges(
            coverage,
            date.fromisoformat(config["start_date"]),
            date.fromisoformat(config["end_date"]),
        ),
        MATERIALIZATION_CHUNK_DAYS,
    )
    if not windows:
        raise HTTPException(
            status_code=409,
            detail={"code": "pit_coverage_already_complete", "covered_intervals": coverage["intervals"]},
        )
    queue = get_queue()
    previous_job = None
    first_row = None
    for window_start, window_end in windows:
        row = models.HistoricalOpportunityMaterializationRun(
            status="queued", methodology_version=METHODOLOGY_VERSION,
            config_json={
                **config,
                "start_date": window_start.isoformat(),
                "end_date": window_end.isoformat(),
            },
            progress_json={"stage": "queued", "progress_pct": 0}, coverage_json={},
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        first_row = first_row or row
        try:
            enqueue_kwargs: dict = {"job_timeout": "24h"}
            if previous_job is not None:
                enqueue_kwargs["depends_on"] = previous_job
            job = queue.enqueue(
                "services.worker.tasks.historical_portfolio_backtest.materialize_historical_opportunities",
                str(row.id), **enqueue_kwargs,
            )
            row.rq_job_id = str(job.id)
            db.commit()
            previous_job = job
        except Exception as exc:
            row.status = "failed"
            row.error_message = f"Could not enqueue PIT materialization: {exc}"
            db.commit()
            raise HTTPException(status_code=503, detail=row.error_message) from exc
    assert first_row is not None
    return _serialize_materialization(first_row)


@router.get("/materializations/{materialization_run_id}", response_model=HistoricalOpportunityMaterializationOut)
def get_historical_opportunity_materialization(materialization_run_id: UUID, db: Session = Depends(get_db)):
    row = db.query(models.HistoricalOpportunityMaterializationRun).filter_by(id=materialization_run_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="PIT materialization run not found")
    _reconcile_rq_state(db, row)
    return _serialize_materialization(row)


@router.post("/coverage")
def get_historical_opportunity_coverage(body: HistoricalPortfolioRunCreate, db: Session = Depends(get_db)):
    return opportunity_store_coverage(db, _resolve_scope(db, body.model_dump(mode="json")))


@router.get("/decisions")
def list_historical_portfolio_decisions(
    start_date: date | None = None,
    end_date: date | None = None,
    symbol: str | None = None,
    horizon: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    actionable: bool | None = None,
    signal_direction: str | None = None,
    winners_only: bool = False,
    methodology_version: str = METHODOLOGY_VERSION,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(models.HistoricalTradeOpportunity).filter(
        models.HistoricalTradeOpportunity.methodology_version == methodology_version,
    )
    if start_date is not None:
        query = query.filter(models.HistoricalTradeOpportunity.decision_date >= start_date)
    if end_date is not None:
        query = query.filter(models.HistoricalTradeOpportunity.decision_date <= end_date)
    if symbol:
        query = query.filter(models.HistoricalTradeOpportunity.symbol == symbol.strip().upper())
    if horizon:
        query = query.filter(models.HistoricalTradeOpportunity.horizon == horizon)
    if status_filter:
        query = query.filter(models.HistoricalTradeOpportunity.status == status_filter)
    if actionable is not None:
        query = query.filter(models.HistoricalTradeOpportunity.actionable.is_(actionable))
    if signal_direction:
        query = query.filter(
            models.HistoricalTradeOpportunity.decision_json["signal_direction"].as_string() == signal_direction,
        )
    is_v4 = methodology_version.endswith("-v4")
    winner_semantics = (
        "v4_legacy_accepted_edge_policy" if is_v4 else "v5_reconstructed_dashboard_winner"
    )
    if winners_only:
        query = query.filter(
            models.HistoricalTradeOpportunity.accepted.is_(True)
            if is_v4
            else models.HistoricalTradeOpportunity.reconstructed_dashboard_winner.is_(True)
        )
    total = query.count()
    rows = query.order_by(
        models.HistoricalTradeOpportunity.decision_date,
        models.HistoricalTradeOpportunity.symbol,
        models.HistoricalTradeOpportunity.horizon,
        models.HistoricalTradeOpportunity.variant,
    ).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [
            {
                "id": row.id,
                "methodology_version": row.methodology_version,
                "decision_date": row.decision_date.isoformat(),
                "symbol": row.symbol,
                "horizon": row.horizon,
                "variant": row.variant,
                "status": row.status,
                "actionable": row.actionable,
                "reconstructed_dashboard_winner": row.reconstructed_dashboard_winner,
                "accepted": row.accepted,
                "rank": row.rank_json,
                "decision": row.decision_json,
                "opportunity": row.opportunity_json,
                "input_hash": row.input_hash,
                "materialization_run_id": str(row.materialization_run_id),
            }
            for row in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
        "winner_semantics": winner_semantics,
    }


def _result_payload(row, *, include_opportunities: bool = True) -> HistoricalPortfolioRunResult:
    return HistoricalPortfolioRunResult(
        run_id=str(row.id), status="succeeded", methodology_version=row.methodology_version,
        config=row.config_json or {}, provenance=row.provenance_json or {},
        diagnostics=row.diagnostics_json or {},
        opportunities=(row.opportunities_json or []) if include_opportunities else [],
        trades=row.trades_json or [], equity_curves=row.equity_curves_json or {},
        benchmark_curves=row.benchmark_curves_json or {}, statistics=row.statistics_json or {},
        validation=row.validation_json or {}, snapshot_audit=row.snapshot_audit_json or {},
        warnings=row.warnings_json or [],
        winner_semantics=(row.diagnostics_json or {}).get("winner_semantics"),
        barrier_scenario=(row.equity_curves_json or {}).get("barrier_scenario"),
        liquidation_diagnostics=(row.diagnostics_json or {}).get("liquidation_diagnostics_v1"),
    )


def _snapshot_result_payload(row, horizon: str | None) -> HistoricalPortfolioRunResult:
    """Project the persisted canonical result onto the active page horizon."""

    if horizon is None:
        return _result_payload(row, include_opportunities=False)
    projected_curves: dict[str, dict] = {}
    for capacity, scenario in (row.equity_curves_json or {}).items():
        if not isinstance(scenario, dict) or capacity == "barrier_scenario":
            continue
        sleeve = (scenario.get("sleeves") or {}).get(horizon)
        if sleeve is not None:
            # The persisted sleeve also contains the complete rejected/event ledgers. Those are
            # useful for the explicit result endpoint but turn an on-load chart into a ~60 MB
            # response. The snapshot needs only the curve and diagnostics rendered by the page.
            compact = {
                "horizon": horizon,
                "equity_curve": sleeve.get("equity_curve") or [],
                "statistics": sleeve.get("statistics") or {},
                "assumptions": sleeve.get("assumptions") or {},
            }
            projected_curves[capacity] = {"sleeves": {horizon: compact}, "combined": compact}
    diagnostics = dict(row.diagnostics_json or {})
    diagnostics["execution_events_v1"] = [
        item for item in diagnostics.get("execution_events_v1", []) if item.get("horizon") == horizon
    ]
    diagnostics["liquidation_diagnostics_v1"] = _project_liquidation_diagnostics(
        diagnostics.get("liquidation_diagnostics_v1"), horizon,
    )
    sleeve_stats = ((row.statistics_json or {}).get("sleeves") or {}).get(horizon, {})
    return HistoricalPortfolioRunResult(
        run_id=str(row.id), status="succeeded", methodology_version=row.methodology_version,
        config={**dict(row.config_json or {}), "horizons": [horizon]},
        provenance=row.provenance_json or {}, diagnostics=diagnostics, opportunities=[],
        trades=[item for item in (row.trades_json or []) if item.get("horizon") == horizon],
        equity_curves=projected_curves, benchmark_curves=row.benchmark_curves_json or {},
        statistics={
            "selected_capacity_fraction": (row.statistics_json or {}).get("selected_capacity_fraction", 0.01),
            "sleeves": {horizon: sleeve_stats}, "combined": sleeve_stats,
        }, validation=row.validation_json or {}, snapshot_audit=row.snapshot_audit_json or {},
        warnings=row.warnings_json or [], winner_semantics=diagnostics.get("winner_semantics"),
        barrier_scenario=None,
        liquidation_diagnostics=diagnostics.get("liquidation_diagnostics_v1"),
    )


def _project_liquidation_diagnostics(payload: dict | None, horizon: str) -> dict:
    """Keep the selected horizon's liquidation ledger and matching aggregate only."""

    source = payload if isinstance(payload, dict) else {}
    lots = [
        item for item in (source.get("lots") or [])
        if isinstance(item, dict) and item.get("horizon") == horizon
    ]
    summary = dict((source.get("by_horizon") or {}).get(horizon) or {})
    if not summary:
        summary = {
            "count": len(lots),
            "realized_pnl": sum(float(item.get("realized_pnl") or 0.0) for item in lots),
            "liquidated_notional": sum(float(item.get("liquidated_notional") or 0.0) for item in lots),
            "exposure_reduction_pct_of_equity_at_fill": sum(
                float(item.get("exposure_reduction_pct_of_equity_at_fill") or 0.0) for item in lots
            ),
            "liquidation_policy_pnl_delta": sum(
                float(item.get("pnl_delta_return") or 0.0) * float(item.get("liquidated_notional") or 0.0)
                for item in lots
            ),
        }
    return {"total": summary, "by_horizon": {horizon: summary}, "lots": lots}


def _is_canonical_snapshot_config(config: dict | None) -> bool:
    """The always-shown snapshot tracks the default full-universe run: no symbol subset, no TP/SL,
    default capacity. A custom exploratory run never overwrites the canonical exhibit."""

    config = config or {}
    return (
        not (config.get("symbols") or [])
        and set(config.get("horizons") or DECISION_HORIZONS) == set(DECISION_HORIZONS)
        and config.get("stop_loss_pct") is None
        and config.get("take_profit_pct") is None
    )


@router.get("/snapshot")
def get_historical_portfolio_snapshot(
    horizon: str | None = Query(default=None, pattern="^(weekly|monthly|quarterly)$"),
    db: Session = Depends(get_db),
):
    """Latest persisted canonical backtest, returned instantly for on-load display (mirrors the
    fundamental value-strategy snapshot). No launch, no wait; a background recompute keeps it fresh."""

    # Select the candidate from lightweight columns first. Hydrating 25 complete JSONB result
    # payloads (four scenarios, curves and trades) made this supposedly instant endpoint take
    # tens of seconds on a populated database.
    recent = db.query(
        models.HistoricalPortfolioBacktestRun.id,
        models.HistoricalPortfolioBacktestRun.config_json,
    ).filter_by(
        status="succeeded", methodology_version=METHODOLOGY_VERSION,
    ).order_by(models.HistoricalPortfolioBacktestRun.completed_at.desc()).limit(25).all()
    candidate = next((r for r in recent if _is_canonical_snapshot_config(r.config_json)), None)
    if candidate is not None and horizon is not None and db.bind.dialect.name == "postgresql":
        model = models.HistoricalPortfolioBacktestRun
        # Extract only fields rendered by the horizon page. Pulling each complete sleeve also
        # transferred its rejected/event ledgers, only for Python to discard them afterwards.
        sleeve_columns = []
        for index, cap in enumerate(CAPACITY_SCENARIOS):
            prefix = (str(cap), "sleeves", horizon)
            sleeve_columns.extend((
                func.jsonb_extract_path(model.equity_curves_json, *prefix, "equity_curve").label(f"curve_{index}"),
                func.jsonb_extract_path(model.equity_curves_json, *prefix, "statistics").label(f"stats_{index}"),
                func.jsonb_extract_path(model.equity_curves_json, *prefix, "assumptions").label(f"assumptions_{index}"),
            ))
        execution_events = func.jsonb_path_query_array(
            func.jsonb_extract_path(model.diagnostics_json, "execution_events_v1"),
            f'$[*] ? (@.horizon == "{horizon}")',
        ).label("execution_events_v1")
        liquidation_diagnostics = func.jsonb_extract_path(
            model.diagnostics_json, "liquidation_diagnostics_v1",
        ).label("liquidation_diagnostics_v1")
        winner_semantics = func.jsonb_extract_path_text(
            model.diagnostics_json, "winner_semantics",
        ).label("winner_semantics")
        projected = db.query(
            model.id, model.status, model.methodology_version, model.config_json,
            model.provenance_json, model.trades_json, model.benchmark_curves_json,
            model.statistics_json, model.validation_json, model.snapshot_audit_json,
            model.warnings_json, model.completed_at, execution_events,
            liquidation_diagnostics, winner_semantics, *sleeve_columns,
        ).filter_by(id=candidate.id).one()
        equity_curves = {}
        for index, cap in enumerate(CAPACITY_SCENARIOS):
            curve = getattr(projected, f"curve_{index}")
            if curve is None:
                continue
            sleeve = {
                "horizon": horizon,
                "equity_curve": curve,
                "statistics": getattr(projected, f"stats_{index}") or {},
                "assumptions": getattr(projected, f"assumptions_{index}") or {},
            }
            equity_curves[str(cap)] = {"sleeves": {horizon: sleeve}}
        liquidation_payload = _project_liquidation_diagnostics(
            projected.liquidation_diagnostics_v1, horizon,
        )
        diagnostics = {
            "stage": "completed", "progress_pct": 100,
            "winner_semantics": projected.winner_semantics or "v5_reconstructed_dashboard_winner",
            "execution_events_v1": projected.execution_events_v1 or [],
            "liquidation_diagnostics_v1": liquidation_payload,
        }
        row = SimpleNamespace(
            **projected._asdict(), equity_curves_json=equity_curves,
            diagnostics_json=diagnostics,
        )
    else:
        row = (
            db.query(models.HistoricalPortfolioBacktestRun).options(load_only(
            models.HistoricalPortfolioBacktestRun.id,
            models.HistoricalPortfolioBacktestRun.status,
            models.HistoricalPortfolioBacktestRun.methodology_version,
            models.HistoricalPortfolioBacktestRun.config_json,
            models.HistoricalPortfolioBacktestRun.provenance_json,
            models.HistoricalPortfolioBacktestRun.diagnostics_json,
            models.HistoricalPortfolioBacktestRun.trades_json,
            models.HistoricalPortfolioBacktestRun.equity_curves_json,
            models.HistoricalPortfolioBacktestRun.benchmark_curves_json,
            models.HistoricalPortfolioBacktestRun.statistics_json,
            models.HistoricalPortfolioBacktestRun.validation_json,
            models.HistoricalPortfolioBacktestRun.snapshot_audit_json,
            models.HistoricalPortfolioBacktestRun.warnings_json,
            models.HistoricalPortfolioBacktestRun.completed_at,
            )).filter_by(id=candidate.id).one()
            if candidate is not None else None
        )
    inflight = db.query(models.HistoricalPortfolioBacktestRun).filter(
        models.HistoricalPortfolioBacktestRun.status.in_(("queued", "running")),
        models.HistoricalPortfolioBacktestRun.methodology_version == METHODOLOGY_VERSION,
    ).order_by(models.HistoricalPortfolioBacktestRun.created_at.desc()).first()
    computing = None
    if inflight is not None and _is_canonical_snapshot_config(inflight.config_json):
        computing = {
            "run_id": str(inflight.id), "status": inflight.status,
            "progress": inflight.diagnostics_json or {},
        }
    if row is None:
        return {"snapshot_available": False, "computing": computing, "result": None}
    return {
        "snapshot_available": True,
        "computed_at": row.completed_at.isoformat() if row.completed_at else None,
        "computing": computing,
        "result": _snapshot_result_payload(row, horizon).model_dump(mode="json", exclude_none=True),
    }


@router.get("/{run_id}", response_model=HistoricalPortfolioRunStatus)
def get_historical_portfolio_backtest_status(run_id: UUID, db: Session = Depends(get_db)):
    row = _row_or_404(db, run_id)
    _reconcile_rq_state(db, row)
    return HistoricalPortfolioRunStatus(
        run_id=str(row.id), status=row.status, methodology_version=row.methodology_version,
        progress=row.diagnostics_json or {}, error_message=row.error_message,
        created_at=row.created_at, started_at=row.started_at, completed_at=row.completed_at,
    )


@router.get(
    "/{run_id}/result", response_model=HistoricalPortfolioRunResult,
    response_model_exclude_none=True,
)
def get_historical_portfolio_backtest_result(run_id: UUID, db: Session = Depends(get_db)):
    row = _row_or_404(db, run_id)
    if row.status == "failed":
        raise HTTPException(status_code=422, detail={"status": "failed", "error_message": row.error_message})
    if row.status != "succeeded":
        raise HTTPException(status_code=409, detail={"status": row.status, "message": "Run is not complete"})
    return _result_payload(row)
