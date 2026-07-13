from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from core.quant_core.historical_portfolio import METHODOLOGY_VERSION
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
from ..services.historical_opportunity_store import opportunity_store_coverage

router = APIRouter(prefix="/strategy/signal/historical-portfolio-backtests", tags=["historical-portfolio-backtests"])


def _row_or_404(db: Session, run_id: UUID) -> models.HistoricalPortfolioBacktestRun:
    row = db.query(models.HistoricalPortfolioBacktestRun).filter_by(id=run_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Historical portfolio backtest run not found")
    return row


@router.post("", response_model=HistoricalPortfolioRunCreated, status_code=status.HTTP_202_ACCEPTED)
def create_historical_portfolio_backtest(
    body: HistoricalPortfolioRunCreate,
    db: Session = Depends(get_db),
):
    coverage = opportunity_store_coverage(db, body.model_dump(mode="json"))
    if not coverage["available"]:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "pit_store_coverage_required",
                "message": "Materialize PIT opportunities for this period before running the backtest.",
                "coverage": coverage,
            },
        )
    normalized_config = body.model_dump(mode="json")
    recent = db.query(models.HistoricalPortfolioBacktestRun).filter_by(
        status="succeeded", methodology_version=METHODOLOGY_VERSION,
    ).order_by(models.HistoricalPortfolioBacktestRun.completed_at.desc()).limit(25).all()
    for cached in recent:
        cached_runs = (cached.provenance_json or {}).get("opportunity_store_materialization_runs") or []
        if (cached.config_json or {}) == normalized_config and cached_runs == coverage["materialization_run_ids"]:
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
    config = body.model_dump(mode="json")
    existing = db.query(models.HistoricalOpportunityMaterializationRun).filter(
        models.HistoricalOpportunityMaterializationRun.status.in_(("queued", "running")),
        models.HistoricalOpportunityMaterializationRun.methodology_version == METHODOLOGY_VERSION,
    ).order_by(models.HistoricalOpportunityMaterializationRun.created_at.desc()).first()
    if existing is not None and (existing.config_json or {}) == config:
        return _serialize_materialization(existing)
    row = models.HistoricalOpportunityMaterializationRun(
        status="queued", methodology_version=METHODOLOGY_VERSION,
        config_json=config, progress_json={"stage": "queued", "progress_pct": 0}, coverage_json={},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    try:
        job = get_queue().enqueue(
            "services.worker.tasks.historical_portfolio_backtest.materialize_historical_opportunities",
            str(row.id), job_timeout="24h",
        )
        row.rq_job_id = str(job.id)
        db.commit()
    except Exception as exc:
        row.status = "failed"
        row.error_message = f"Could not enqueue PIT materialization: {exc}"
        db.commit()
        raise HTTPException(status_code=503, detail=row.error_message) from exc
    return _serialize_materialization(row)


@router.get("/materializations/{materialization_run_id}", response_model=HistoricalOpportunityMaterializationOut)
def get_historical_opportunity_materialization(materialization_run_id: UUID, db: Session = Depends(get_db)):
    row = db.query(models.HistoricalOpportunityMaterializationRun).filter_by(id=materialization_run_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="PIT materialization run not found")
    return _serialize_materialization(row)


@router.post("/coverage")
def get_historical_opportunity_coverage(body: HistoricalPortfolioRunCreate, db: Session = Depends(get_db)):
    return opportunity_store_coverage(db, body.model_dump(mode="json"))


@router.get("/{run_id}", response_model=HistoricalPortfolioRunStatus)
def get_historical_portfolio_backtest_status(run_id: UUID, db: Session = Depends(get_db)):
    row = _row_or_404(db, run_id)
    return HistoricalPortfolioRunStatus(
        run_id=str(row.id), status=row.status, methodology_version=row.methodology_version,
        progress=row.diagnostics_json or {}, error_message=row.error_message,
        created_at=row.created_at, started_at=row.started_at, completed_at=row.completed_at,
    )


@router.get("/{run_id}/result", response_model=HistoricalPortfolioRunResult)
def get_historical_portfolio_backtest_result(run_id: UUID, db: Session = Depends(get_db)):
    row = _row_or_404(db, run_id)
    if row.status == "failed":
        raise HTTPException(status_code=422, detail={"status": "failed", "error_message": row.error_message})
    if row.status != "succeeded":
        raise HTTPException(status_code=409, detail={"status": row.status, "message": "Run is not complete"})
    return HistoricalPortfolioRunResult(
        run_id=str(row.id), status="succeeded", methodology_version=row.methodology_version,
        config=row.config_json or {}, provenance=row.provenance_json or {},
        diagnostics=row.diagnostics_json or {}, opportunities=row.opportunities_json or [],
        trades=row.trades_json or [], equity_curves=row.equity_curves_json or {},
        benchmark_curves=row.benchmark_curves_json or {}, statistics=row.statistics_json or {},
        validation=row.validation_json or {}, snapshot_audit=row.snapshot_audit_json or {},
        warnings=row.warnings_json or [],
    )
