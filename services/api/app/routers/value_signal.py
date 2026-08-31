"""Value signal router — the canonical B/M + CF/P value signal and its six-vintage
live-like strategy snapshot.

Endpoints:
  GET  /value-signal                    — current cross-section (all symbols)
  GET  /value-signal/{symbol}           — single-symbol detail
  GET  /value-strategy/snapshot         — latest persisted six-vintage strategy snapshot,
                                            with explicit freshness/failure state
  POST /value-strategy/recompute        — async recompute (admin-only), mirrors the SFC
                                            portfolio backtest's RQ job + SignalEngineBatchJob
                                            tracking pattern (analytics.py)
  GET  /value-strategy/recompute/status — recent recompute job attempts (queued/running/
                                            succeeded/failed)

This is the production entrypoint for core.quant_core.fundamentals.cross_section
.characteristic_study / .live_like_strategy (2026-07-06 research). See
services/api/app/services/value_signal.py and value_strategy_snapshot.py for the
single source of truth these endpoints wrap — no formulas are reimplemented here.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..db import get_db
from .. import models
from ..schemas.value_signal import (
    ValueSignalResponse,
    ValueSignalRow,
    ValueStrategyRecomputeResponse,
    ValueStrategyRecomputeRequest,
    ValueStrategySnapshotResponse,
    ValueStrategyStatusResponse,
)
from ..services.value_signal import compute_value_signal_frame, value_signal_row_to_dict
from ..services.value_strategy_snapshot import (
    VALUE_STRATEGY_JOB_HORIZON,
    VALUE_STRATEGY_JOB_SYMBOL,
    VALUE_STRATEGY_JOB_TYPE,
    latest_value_strategy_job,
    latest_value_strategy_snapshot,
    snapshot_freshness,
    value_strategy_desk_payload,
)

router = APIRouter(tags=["value-signal"])


@router.get("/value-signal", response_model=ValueSignalResponse)
def get_value_signal(
    as_of: Optional[dt.date] = Query(None),
    db: Session = Depends(get_db),
) -> ValueSignalResponse:
    panel, meta = compute_value_signal_frame(db, as_of_date=as_of)
    if panel.empty:
        raise HTTPException(status_code=404, detail="No value-signal data available for this date")
    rows = [ValueSignalRow(**value_signal_row_to_dict(row)) for _, row in panel.sort_values("symbol").iterrows()]
    return ValueSignalResponse(
        as_of_date=meta["as_of_date"],
        methodology_version=meta["methodology_version"],
        eligible_bm_count=meta.get("eligible_bm_count", 0),
        eligible_cfp_count=meta.get("eligible_cfp_count", 0),
        total_rows=meta["rows"],
        publication_coverage=meta.get("publication_coverage", {}),
        market_equity_formula=meta["market_equity_formula"],
        rows=rows,
    )


@router.get("/value-signal/{symbol}", response_model=ValueSignalRow)
def get_value_signal_symbol(
    symbol: str,
    as_of: Optional[dt.date] = Query(None),
    db: Session = Depends(get_db),
) -> ValueSignalRow:
    panel, _meta = compute_value_signal_frame(db, as_of_date=as_of)
    if panel.empty:
        raise HTTPException(status_code=404, detail="No value-signal data available for this date")
    matches = panel[panel["symbol"].astype(str).str.upper() == symbol.upper()]
    if matches.empty:
        raise HTTPException(status_code=404, detail=f"No value-signal row for {symbol.upper()}")
    return ValueSignalRow(**value_signal_row_to_dict(matches.iloc[0]))


@router.get("/value-strategy/snapshot", response_model=ValueStrategySnapshotResponse)
def get_value_strategy_snapshot(db: Session = Depends(get_db)) -> ValueStrategySnapshotResponse:
    from core.quant_core.fundamentals.cross_section.production_readiness import current_repository_readiness

    row = latest_value_strategy_snapshot(db)
    job = latest_value_strategy_job(db)
    freshness = snapshot_freshness(row, latest_job_status=job.status if job else None)
    readiness = current_repository_readiness()
    if row is None:
        desk = value_strategy_desk_payload({})
        # Explicit no_snapshot state rather than a bare 404 -- the UI needs to distinguish
        # "nothing has ever been computed" from a transient API error.
        return ValueStrategySnapshotResponse(
            live_trading_authorized=readiness.live_trading_authorized,
            production_readiness=readiness.to_dict(),
            research_status="RESEARCH ONLY — UNVALIDATED",
            recommended_architecture="S1_bm",
            model_version="Fundamental Value Strategy v2.1",
            methodology_version=desk["methodology_version"],
            transaction_cost_bps=desk["transaction_cost_bps"],
            transaction_cost_source=desk["transaction_cost_source"],
            research_pipeline=desk["pipeline_steps"],
            factor_research=desk["factor_research"],
            portfolio_rules=desk["portfolio_rules"],
            data_sources=desk["data_sources"],
            as_of_date=None,
            data_cutoff=None,
            universe_summary=None,
            current_holdings=[],
            strategy_metrics={},
            equity_curve=[],
            trade_ledger=[],
            liquidity_settings={},
            capacity_summary={},
            caveats=["No strategy snapshot has been computed yet. Trigger POST /value-strategy/recompute."],
            config_hash="",
            computed_at=None,
            freshness=freshness,
        )
    result = row.result_json or {}
    desk = value_strategy_desk_payload(result)
    return ValueStrategySnapshotResponse(
        # Authorization is evaluated from the current policy, never trusted from
        # a persisted research snapshot that may predate a new failed gate.
        live_trading_authorized=readiness.live_trading_authorized,
        production_readiness=readiness.to_dict(),
        research_status=result.get("research_status", "RESEARCH ONLY — UNVALIDATED"),
        recommended_architecture=result.get("recommended_architecture", "S1_bm"),
        model_version=result.get("model_version", "Fundamental Value Strategy v2.1"),
        methodology_version=desk["methodology_version"],
        transaction_cost_bps=desk["transaction_cost_bps"],
        transaction_cost_source=desk["transaction_cost_source"],
        research_pipeline=result.get("research_pipeline", desk["pipeline_steps"]),
        factor_research=result.get("factor_research", desk["factor_research"]),
        portfolio_rules=result.get("portfolio_rules", desk["portfolio_rules"]),
        data_sources=result.get("data_sources", desk["data_sources"]),
        as_of_date=result.get("as_of_date"),
        data_cutoff=result.get("data_cutoff"),
        universe_summary=result.get("universe_summary"),
        current_holdings=result.get("current_holdings", []),
        strategy_metrics=result.get("strategy_metrics", {}),
        equity_curve=result.get("equity_curve", []),
        trade_ledger=result.get("trade_ledger", []),
        liquidity_settings=result.get("liquidity_settings", {}),
        capacity_summary=result.get("capacity_summary", {}),
        caveats=result.get("caveats", []),
        config_hash=row.config_hash,
        computed_at=row.computed_at.isoformat() if row.computed_at else None,
        freshness=freshness,
    )


@router.post("/value-strategy/recompute", dependencies=[Depends(require_admin)], response_model=ValueStrategyRecomputeResponse)
def post_value_strategy_recompute(
    request: ValueStrategyRecomputeRequest | None = None,
    db: Session = Depends(get_db),
) -> ValueStrategyRecomputeResponse:
    """Enqueues an async recompute (RQ), mirroring POST /analytics/sfc-portfolio-backtest/run.
    Heavy (~minutes, full price-history load + vintage backtest) -- runs on the worker, never
    blocks this request."""
    from ..queue import get_market_refresh_queue

    job_row = models.SignalEngineBatchJob(
        symbol=VALUE_STRATEGY_JOB_SYMBOL,
        horizon=VALUE_STRATEGY_JOB_HORIZON,
        variant="six_vintage",
        job_type=VALUE_STRATEGY_JOB_TYPE,
        status="pending",
        triggered_by="manual",
        total_units=1,
        completed_units=0,
        failed_units=0,
    )
    db.add(job_row)
    db.commit()
    db.refresh(job_row)
    try:
        job = get_market_refresh_queue().enqueue(
            "services.worker.tasks.value_strategy.recompute_value_strategy",
            triggered_by="manual",
            batch_id=str(job_row.id),
            job_row_id=str(job_row.id),
            liquidity_settings=(request or ValueStrategyRecomputeRequest()).liquidity.model_dump(),
            job_timeout=1800,
        )
        job_row.rq_job_id = str(job.id)
        job_row.status = "queued"
        db.commit()
    except Exception as exc:
        job_row.status = "failed"
        job_row.error_message = str(exc)
        db.commit()
        raise HTTPException(status_code=503, detail=f"Could not enqueue value-strategy recompute: {exc}") from exc
    return ValueStrategyRecomputeResponse(job_id=str(job_row.id), rq_job_id=job_row.rq_job_id, status=job_row.status)


@router.get("/value-strategy/recompute/status", response_model=ValueStrategyStatusResponse)
def get_value_strategy_recompute_status(db: Session = Depends(get_db)) -> ValueStrategyStatusResponse:
    rows = (
        db.query(models.SignalEngineBatchJob)
        .filter_by(symbol=VALUE_STRATEGY_JOB_SYMBOL, job_type=VALUE_STRATEGY_JOB_TYPE)
        .order_by(models.SignalEngineBatchJob.created_at.desc())
        .limit(5)
        .all()
    )
    return ValueStrategyStatusResponse(
        job_type=VALUE_STRATEGY_JOB_TYPE,
        jobs=[
            {
                "id": str(job.id),
                "status": job.status,
                "rq_job_id": job.rq_job_id,
                "triggered_by": job.triggered_by,
                "error_message": job.error_message,
                "created_at": job.created_at.isoformat() if job.created_at else "",
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            }
            for job in rows
        ],
    )
