from __future__ import annotations

from datetime import timedelta
import subprocess
import uuid
from uuid import UUID

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from core.quant_core.cross_asset.backtest import run_backtest
from core.quant_core.cross_asset.dataquality import data_quality_report
from core.quant_core.cross_asset.instruments import Instrument
from core.quant_core.cross_asset.strategy_spec import StrategyDefinition

from .. import models
from ..config import settings
from ..db import get_db
from ..queue import get_queue
from ..schemas.cross_asset_research import CommodityCurveRequest, DataQualityRequest, RunCreate, StrategyCreate
from ..services.cross_asset.commodity_data import commodity_curve_payload
from ..services.cross_asset.orchestrator import (
    CrossAssetStrategy,
    dataset_hash,
    envelope,
    panel_from_payload,
    serialize_strategy,
    utcnow,
)

router = APIRouter(prefix="/cross-asset-research", tags=["cross-asset-research"])
DISCLAIMER = "Research output only; it does not guarantee profit and is not investment advice."


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=2).strip()
    except Exception:
        return "unknown"


@router.post("/commodity/curve")
def commodity_curve(payload: CommodityCurveRequest) -> dict:
    try:
        result = commodity_curve_payload(payload.data, as_of=pd.Timestamp(payload.as_of).date(), data_tier=payload.data_tier)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return envelope(
        inputs={"as_of": payload.as_of, "data_tier": payload.data_tier},
        methodology={"carry": "front/deferred - 1, annualized; forecast feature only"},
        warnings=result.pop("warnings"),
        results=result,
        interpretation="Raw unadjusted curve; carry is not realized P&L.",
        units={"settle": "contract price", "carry": "decimal annualized"},
        data_source=payload.data_tier,
    )


def _strategy(db: Session, strategy_id: UUID) -> CrossAssetStrategy:
    row = db.get(CrossAssetStrategy, strategy_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Cross-asset strategy not found")
    return row


def _quality(spec: StrategyDefinition, data: list[dict] | dict):
    panel = panel_from_payload(data)
    asset_class = {"fx_excess": "fx", "futures_excess": "commodity", "bond_duration": "rates"}[spec.returns.kind]
    instruments = [Instrument(symbol, asset_class, spec.universe.base_currency, "return") for symbol in spec.universe.instruments]
    return panel, data_quality_report(panel, instruments)


@router.post("/strategies", status_code=status.HTTP_201_CREATED)
def create_strategy(payload: StrategyCreate, db: Session = Depends(get_db)) -> dict:
    try:
        spec = StrategyDefinition.from_dict(payload.spec)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row = CrossAssetStrategy(
        id=uuid.uuid4(),
        name=spec.identity.name,
        version=str(spec.identity.version),
        spec_json=spec.to_dict(),
        spec_hash=spec.spec_hash(),
        replication_fidelity=spec.research_source.replication_fidelity,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return envelope(inputs={"spec": spec.to_dict()}, methodology={"operation": "versioned strategy creation"}, warnings=spec.disclosures.warnings, results=serialize_strategy(row), interpretation="The immutable strategy version was stored.", assumptions=spec.disclosures.assumptions)


@router.get("/strategies")
def list_strategies(db: Session = Depends(get_db)) -> dict:
    rows = db.query(CrossAssetStrategy).order_by(CrossAssetStrategy.created_at.desc()).all()
    return envelope(inputs={}, methodology={"operation": "strategy ledger query"}, warnings=[], results=[serialize_strategy(row) for row in rows], interpretation="Stored cross-asset strategy versions.")


@router.get("/strategies/{strategy_id}")
def get_strategy(strategy_id: UUID, db: Session = Depends(get_db)) -> dict:
    row = _strategy(db, strategy_id)
    return envelope(inputs={"strategy_id": str(strategy_id)}, methodology={"operation": "strategy ledger lookup"}, warnings=[], results=serialize_strategy(row), interpretation="Stored cross-asset strategy version.")


@router.post("/data-quality")
def check_data_quality(payload: DataQualityRequest, db: Session = Depends(get_db)) -> dict:
    if payload.spec is not None:
        spec = StrategyDefinition.from_dict(payload.spec)
    elif payload.strategy_id:
        spec = StrategyDefinition.from_dict(_strategy(db, UUID(payload.strategy_id)).spec_json)
    else:
        raise HTTPException(status_code=422, detail="spec or strategy_id is required")
    try:
        _, report = _quality(spec, payload.data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return envelope(inputs={"strategy": spec.identity.name}, methodology={"checks": "duplicates, overlap, missingness, staleness, jumps"}, warnings=report.warnings, results=report.to_dict(), interpretation="Backtest is blocked when blocks_backtest is true.", assumptions=spec.disclosures.assumptions)


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
def create_run(payload: RunCreate, db: Session = Depends(get_db)) -> dict:
    strategy = _strategy(db, UUID(payload.strategy_id))
    spec = StrategyDefinition.from_dict(strategy.spec_json)
    try:
        _, quality = _quality(spec, payload.data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if quality.blocks_backtest:
        raise HTTPException(status_code=422, detail="data quality blocks backtest")
    data_hash = payload.dataset_hash or dataset_hash(payload.data)
    run = models.Run(
        id=uuid.uuid4(),
        status="queued",
        run_type="cross_asset_strategy",
        spec_json={"strategy": spec.to_dict(), "fixture_data": payload.data},
        spec_hash=spec.spec_hash(),
        git_commit=_git_commit(),
        dataset_id=UUID(payload.dataset_id) if payload.dataset_id else None,
        dataset_hash=data_hash,
        seed=payload.seed,
        code_version="cross-asset-v1",
        mode="single",
    )
    db.add(run)
    db.flush()
    job = get_queue().enqueue(
        "services.worker.tasks.cross_asset.run_backtest.execute_cross_asset_backtest",
        str(run.id),
        job_timeout=int(settings.RUN_JOB_TIMEOUT_SECONDS),
        result_ttl=int(settings.RUN_JOB_RESULT_TTL_SECONDS),
        failure_ttl=int(settings.RUN_JOB_FAILURE_TTL_SECONDS),
    )
    run.rq_job_id = str(job.id)
    db.commit()
    return envelope(inputs={"strategy_id": payload.strategy_id, "dataset_hash": data_hash, "seed": payload.seed}, methodology={"engine": "shared cross-asset engine", "quality_gate": "passed"}, warnings=quality.warnings, results={"run_id": str(run.id), "status": run.status}, interpretation="The deterministic run was queued.", assumptions=spec.disclosures.assumptions)


def _run(db: Session, run_id: UUID) -> models.Run:
    row = db.get(models.Run, run_id)
    if row is None or row.run_type != "cross_asset_strategy":
        raise HTTPException(status_code=404, detail="Cross-asset run not found")
    return row


def _require_complete(row: models.Run) -> None:
    if row.status != "succeeded":
        raise HTTPException(status_code=409, detail="Run has not completed")


@router.get("/runs/{run_id}")
def get_run(run_id: UUID, db: Session = Depends(get_db)) -> dict:
    row = _run(db, run_id)
    metrics = db.query(models.RunMetric).filter(models.RunMetric.run_id == run_id).all() if row.status == "succeeded" else []
    spec = StrategyDefinition.from_dict(row.spec_json["strategy"])
    return envelope(inputs={"run_id": str(run_id), "spec_hash": row.spec_hash, "dataset_hash": row.dataset_hash, "git_commit": row.git_commit, "seed": row.seed}, methodology={"engine": "shared cross-asset engine"}, warnings=[], results={"status": row.status, "metrics": {item.metric_name: item.metric_value for item in metrics}, "error": row.error_message}, interpretation="Gross and net results are reported together after completion.", assumptions=spec.disclosures.assumptions)


@router.get("/runs/{run_id}/stages")
def get_stages(run_id: UUID, db: Session = Depends(get_db)) -> dict:
    row = _run(db, run_id)
    _require_complete(row)
    artifacts = db.query(models.Artifact).filter(models.Artifact.run_id == run_id).all()
    return envelope(inputs={"run_id": str(run_id)}, methodology={"artifacts": "inspectable stage outputs"}, warnings=[], results=[{"name": item.name, "object_key": item.object_key, "content_type": item.content_type} for item in artifacts], interpretation="Each backtest transformation is persisted as an artifact.")


@router.get("/runs/{run_id}/robustness")
def get_robustness(run_id: UUID, db: Session = Depends(get_db)) -> dict:
    row = _run(db, run_id)
    _require_complete(row)
    spec = StrategyDefinition.from_dict(row.spec_json["strategy"])
    metrics = db.query(models.RunMetric).filter(models.RunMetric.run_id == run_id, models.RunMetric.metric_name.in_(["deflated_sharpe", "variant_count"])).all()
    return envelope(inputs={"run_id": str(run_id)}, methodology={"multiple_testing": "deflated Sharpe when variant_count > 1"}, warnings=["Multiple-testing correction is required for variant comparisons."] if spec.validation.n_variants > 1 else [], results={item.metric_name: item.metric_value for item in metrics}, interpretation="Robustness statistics qualify, rather than prove, the result.")


@router.get("/strategies/{strategy_id}/current-signal")
def current_signal(strategy_id: UUID, db: Session = Depends(get_db)) -> dict:
    strategy = _strategy(db, strategy_id)
    run = db.query(models.Run).filter(models.Run.run_type == "cross_asset_strategy", models.Run.spec_hash == strategy.spec_hash, models.Run.status == "succeeded").order_by(models.Run.finished_at.desc()).first()
    if run is None:
        raise HTTPException(status_code=409, detail="No completed run is available")
    artifacts = db.query(models.Artifact).filter(models.Artifact.run_id == run.id, models.Artifact.name == "current_signal").all()
    result = {"latest_signal": None, "intended_position": None, "previous_position": None, "drivers": [], "data_timestamp": None, "staleness": None, "next_rebalance": None, "reversal_conditions": [], "artifact_key": artifacts[0].object_key if artifacts else None, "disclaimer": DISCLAIMER}
    return envelope(inputs={"strategy_id": str(strategy_id)}, methodology={"signal_timing": "all features lagged before execution"}, warnings=[], results=result, interpretation="Monitoring only; unavailable values remain null and profit is never guaranteed.")
