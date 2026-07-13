from __future__ import annotations

from datetime import datetime, timezone
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from services.api.app import models
from services.api.app.db import get_db
from services.api.app.routers import historical_portfolio_backtest as api


class _Job:
    id = "rq-test-job"


class _Queue:
    def enqueue(self, *args, **kwargs):
        return _Job()


def _client(monkeypatch):
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.HistoricalPortfolioBacktestRun.__table__.create(engine)
    models.HistoricalOpportunityMaterializationRun.__table__.create(engine)
    models.HistoricalTradeOpportunity.__table__.create(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(api, "get_queue", lambda: _Queue())
    return TestClient(app), db


def _seed_coverage(db) -> None:
    db.add(models.HistoricalOpportunityMaterializationRun(
        status="succeeded", methodology_version="pit-dashboard-opportunity-portfolio-v1",
        config_json={"start_date": "2024-01-01", "end_date": "2025-01-01", "symbols": []},
        progress_json={"stage": "completed"}, coverage_json={"start": "2024-01-01", "end": "2025-01-01"},
        completed_at=datetime.now(timezone.utc),
    ))
    db.commit()


def test_create_status_and_incomplete_result_guard(monkeypatch) -> None:
    client, db = _client(monkeypatch)
    _seed_coverage(db)
    response = client.post("/strategy/signal/historical-portfolio-backtests", json={
        "start_date": "2024-01-01", "end_date": "2025-01-01",
    })
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    row = db.query(models.HistoricalPortfolioBacktestRun).filter_by(id=uuid.UUID(run_id)).one()
    assert row.status == "queued"
    assert row.rq_job_id == "rq-test-job"
    assert client.get(f"/strategy/signal/historical-portfolio-backtests/{run_id}").json()["status"] == "queued"
    guarded = client.get(f"/strategy/signal/historical-portfolio-backtests/{run_id}/result")
    assert guarded.status_code == 409


def test_failed_and_succeeded_runs_are_distinguished(monkeypatch) -> None:
    client, db = _client(monkeypatch)
    run_id = uuid.uuid4()
    row = models.HistoricalPortfolioBacktestRun(
        id=run_id, status="failed", methodology_version="test", config_json={}, provenance_json={},
        diagnostics_json={}, opportunities_json=[], trades_json=[], equity_curves_json={},
        benchmark_curves_json={}, statistics_json={}, validation_json={}, snapshot_audit_json={},
        warnings_json=[], error_message="boom", completed_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    failed = client.get(f"/strategy/signal/historical-portfolio-backtests/{run_id}/result")
    assert failed.status_code == 422
    assert failed.json()["detail"]["status"] == "failed"

    row.status = "succeeded"
    row.error_message = None
    row.provenance_json = {"point_in_time": True}
    db.commit()
    complete = client.get(f"/strategy/signal/historical-portfolio-backtests/{run_id}/result")
    assert complete.status_code == 200
    assert complete.json()["status"] == "succeeded"
    assert complete.json()["provenance"]["point_in_time"] is True


def test_backtest_fails_fast_when_pit_store_is_missing(monkeypatch) -> None:
    client, _db = _client(monkeypatch)
    response = client.post("/strategy/signal/historical-portfolio-backtests", json={
        "start_date": "2024-01-01", "end_date": "2025-01-01",
    })
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "pit_store_coverage_required"


def test_materialization_is_persisted_and_enqueued(monkeypatch) -> None:
    client, db = _client(monkeypatch)
    response = client.post("/strategy/signal/historical-portfolio-backtests/materializations", json={
        "start_date": "2024-01-01", "end_date": "2025-01-01",
    })
    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    row = db.query(models.HistoricalOpportunityMaterializationRun).one()
    assert row.rq_job_id == "rq-test-job"
    status_response = client.get(
        f"/strategy/signal/historical-portfolio-backtests/materializations/{payload['materialization_run_id']}"
    )
    assert status_response.status_code == 200
