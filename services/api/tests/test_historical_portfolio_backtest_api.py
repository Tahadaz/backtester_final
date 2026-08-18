from __future__ import annotations

from datetime import date, datetime, timezone
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.quant_core.historical_portfolio import METHODOLOGY_VERSION
from services.api.app import models
from services.api.app.db import get_db
from services.api.app.routers import historical_portfolio_backtest as api


class _Job:
    def __init__(self, job_id: str):
        self.id = job_id


class _Queue:
    def __init__(self):
        self.calls = []
        self.connection = object()

    def enqueue(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return _Job(f"rq-test-job-{len(self.calls)}")


def _client(monkeypatch):
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.HistoricalPortfolioBacktestRun.__table__.create(engine)
    models.HistoricalOpportunityMaterializationRun.__table__.create(engine)
    models.HistoricalTradeOpportunity.__table__.create(engine)
    models.SignalScoreHistory.__table__.create(engine)
    models.MarketDataStore.__table__.create(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[get_db] = lambda: db
    queue = _Queue()
    monkeypatch.setattr(api, "get_queue", lambda: queue)
    monkeypatch.setattr(
        api,
        "_fetch_rq_job",
        lambda *_args, **_kwargs: type(
            "QueuedJob", (), {"dependency_ids": [], "get_status": lambda self, refresh=True: "queued"}
        )(),
    )
    monkeypatch.setattr(api, "list_masi_signal_universe_symbols", lambda _db: ["IAM", "ATW"])
    db.add_all([
        models.SignalScoreHistory(
            date=date(2024, 1, 1), symbol="IAM", source="wfo", category="tendance",
            horizon="weekly", score_pct=1.0, is_oos=True,
        ),
        models.SignalScoreHistory(
            date=date(2025, 1, 1), symbol="IAM", source="wfo", category="tendance",
            horizon="weekly", score_pct=1.0, is_oos=True,
        ),
        # The weekly decision grid is built from the MASI index calendar, so the resolver clamps
        # to these bounds as well as to score history.
        models.MarketDataStore(
            symbol="MASI", timeframe="1D", object_key="masi.parquet",
            start_ts=datetime(2023, 6, 2, tzinfo=timezone.utc),
            end_ts=datetime(2026, 7, 10, tzinfo=timezone.utc),
        ),
    ])
    db.commit()
    return TestClient(app), db, queue


def _seed_coverage(db) -> None:
    db.add(models.HistoricalOpportunityMaterializationRun(
        status="succeeded", methodology_version=METHODOLOGY_VERSION,
        config_json={"start_date": "2024-01-01", "end_date": "2025-01-01", "symbols": []},
        progress_json={"stage": "completed"}, coverage_json={"start": "2024-01-01", "end": "2025-01-01"},
        completed_at=datetime.now(timezone.utc),
    ))
    db.commit()


def test_create_status_and_incomplete_result_guard(monkeypatch) -> None:
    client, db, _queue = _client(monkeypatch)
    _seed_coverage(db)
    response = client.post("/strategy/signal/historical-portfolio-backtests", json={
        "start_date": "2024-01-01", "end_date": "2025-01-01",
        "horizons": ["monthly", "weekly"],
    })
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    row = db.query(models.HistoricalPortfolioBacktestRun).filter_by(id=uuid.UUID(run_id)).one()
    assert row.status == "queued"
    assert row.rq_job_id == "rq-test-job-1"
    assert row.config_json["horizons"] == ["weekly", "monthly"]
    assert client.get(f"/strategy/signal/historical-portfolio-backtests/{run_id}").json()["status"] == "queued"
    guarded = client.get(f"/strategy/signal/historical-portfolio-backtests/{run_id}/result")
    assert guarded.status_code == 409

    empty_horizons = client.post("/strategy/signal/historical-portfolio-backtests", json={
        "start_date": "2024-01-01", "end_date": "2025-01-01", "horizons": [],
    })
    assert empty_horizons.status_code == 422


def test_snapshot_returns_latest_canonical_run_or_computing_state(monkeypatch) -> None:
    """The always-shown snapshot returns the latest succeeded full-universe run instantly, or a
    computing/empty state — the mechanism behind 'results shown on load, no wait'."""

    client, db, _queue = _client(monkeypatch)
    base = "/strategy/signal/historical-portfolio-backtests/snapshot"

    empty = client.get(base)
    assert empty.status_code == 200
    assert empty.json() == {"snapshot_available": False, "computing": None, "result": None}

    # An in-flight canonical run surfaces as 'computing'.
    running = models.HistoricalPortfolioBacktestRun(
        id=uuid.uuid4(), status="running", methodology_version=METHODOLOGY_VERSION,
        config_json={"symbols": []}, provenance_json={}, diagnostics_json={"progress_pct": 40},
        opportunities_json=[], trades_json=[], equity_curves_json={}, benchmark_curves_json={},
        statistics_json={}, validation_json={}, snapshot_audit_json={}, warnings_json=[],
    )
    db.add(running)
    db.commit()
    assert client.get(base).json()["computing"]["run_id"] == str(running.id)

    # A succeeded canonical run becomes the snapshot; a symbol-filtered run never overwrites it.
    succeeded = models.HistoricalPortfolioBacktestRun(
        id=uuid.uuid4(), status="succeeded", methodology_version=METHODOLOGY_VERSION,
        config_json={"symbols": []}, provenance_json={"point_in_time": True}, diagnostics_json={
            "winner_semantics": "v5_reconstructed_dashboard_winner",
            "execution_events_v1": [
                {"horizon": "weekly", "scenario": "baseline", "symbol": "IAM"},
                {"horizon": "monthly", "scenario": "baseline", "symbol": "ATW"},
            ],
            "liquidation_diagnostics_v1": {
                "total": {"count": 2},
                "by_horizon": {"weekly": {"count": 1}, "monthly": {"count": 1}},
                "lots": [
                    {"horizon": "weekly", "symbol": "IAM"},
                    {"horizon": "monthly", "symbol": "ATW"},
                ],
            },
        },
        opportunities_json=[], trades_json=[], equity_curves_json={"0.01": {"combined": {}}},
        benchmark_curves_json={}, statistics_json={"combined": {"absolute_return": 0.1}},
        validation_json={}, snapshot_audit_json={}, warnings_json=[], completed_at=datetime.now(timezone.utc),
    )
    custom = models.HistoricalPortfolioBacktestRun(
        id=uuid.uuid4(), status="succeeded", methodology_version=METHODOLOGY_VERSION,
        config_json={"symbols": ["IAM"]}, provenance_json={}, diagnostics_json={},
        opportunities_json=[], trades_json=[], equity_curves_json={}, benchmark_curves_json={},
        statistics_json={}, validation_json={}, snapshot_audit_json={}, warnings_json=[],
        completed_at=datetime.now(timezone.utc),
    )
    db.add_all([succeeded, custom])
    db.commit()
    body = client.get(base).json()
    assert body["snapshot_available"] is True
    assert body["result"]["run_id"] == str(succeeded.id)
    assert body["result"]["statistics"]["combined"]["absolute_return"] == 0.1

    succeeded.equity_curves_json = {
        "0.01": {"sleeves": {
            "weekly": {"equity_curve": [{"date": "2024-01-01", "equity": 100.0}], "statistics": {"sharpe": 1.0}},
            "monthly": {"equity_curve": [{"date": "2024-01-01", "equity": 200.0}], "statistics": {"sharpe": 2.0}},
        }},
    }
    succeeded.trades_json = [
        {"symbol": "IAM", "horizon": "weekly"}, {"symbol": "ATW", "horizon": "monthly"},
    ]
    succeeded.statistics_json = {"sleeves": {"weekly": {"sharpe": 1.0}, "monthly": {"sharpe": 2.0}}}
    db.commit()
    projected = client.get(f"{base}?horizon=weekly").json()["result"]
    assert projected["config"]["horizons"] == ["weekly"]
    assert list(projected["equity_curves"]["0.01"]["sleeves"]) == ["weekly"]
    assert projected["equity_curves"]["0.01"]["combined"]["statistics"]["sharpe"] == 1.0
    assert [trade["horizon"] for trade in projected["trades"]] == ["weekly"]
    assert projected["diagnostics"]["execution_events_v1"] == [
        {"horizon": "weekly", "scenario": "baseline", "symbol": "IAM"},
    ]
    assert projected["diagnostics"]["liquidation_diagnostics_v1"]["lots"] == [
        {"horizon": "weekly", "symbol": "IAM"},
    ]
    assert projected["liquidation_diagnostics"]["total"]["count"] == 1
    assert projected["opportunities"] == []


def test_failed_and_succeeded_runs_are_distinguished(monkeypatch) -> None:
    client, db, _queue = _client(monkeypatch)
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
    assert "barrier_scenario" not in complete.json()
    assert set(complete.json()) >= {"equity_curves", "benchmark_curves", "statistics", "diagnostics"}


def test_window_is_clamped_to_masi_calendar(monkeypatch) -> None:
    """Dates with score history but no MASI bars yield zero decision dates, so they are clamped."""

    client, db, _queue = _client(monkeypatch)
    db.add(models.SignalScoreHistory(
        date=date(2021, 1, 4), symbol="IAM", source="wfo", category="tendance",
        horizon="weekly", score_pct=1.0, is_oos=True,
    ))
    db.commit()
    response = client.post("/strategy/signal/historical-portfolio-backtests/coverage", json={
        "start_date": "2021-01-01", "end_date": "2025-01-01",
    })
    assert response.status_code == 200
    assert response.json()["requested_start"] == "2023-06-02"


def test_window_entirely_before_masi_calendar_is_rejected(monkeypatch) -> None:
    client, db, _queue = _client(monkeypatch)
    db.add(models.SignalScoreHistory(
        date=date(2021, 1, 4), symbol="IAM", source="wfo", category="tendance",
        horizon="weekly", score_pct=1.0, is_oos=True,
    ))
    db.commit()
    response = client.post("/strategy/signal/historical-portfolio-backtests", json={
        "start_date": "2021-01-01", "end_date": "2021-06-30",
    })
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "window_outside_supported_coverage"
    assert detail["masi_calendar_start"] == "2023-06-02"


def test_universe_wide_materialization_counts_as_coverage(monkeypatch) -> None:
    """A request without symbols must be satisfied by a run that stored the universe explicitly,
    otherwise a complete store still sends every launch back to precalculation."""

    client, db, queue = _client(monkeypatch)
    db.add(models.HistoricalOpportunityMaterializationRun(
        status="succeeded", methodology_version=METHODOLOGY_VERSION,
        config_json={
            "start_date": "2024-01-01", "end_date": "2025-01-01",
            "symbols": ["ATW", "IAM"], "resolved_universe": ["ATW", "IAM"],
        },
        progress_json={"stage": "completed"}, coverage_json={},
        completed_at=datetime.now(timezone.utc),
    ))
    db.commit()
    response = client.post("/strategy/signal/historical-portfolio-backtests", json={
        "start_date": "2024-01-01", "end_date": "2025-01-01",
    })
    assert response.status_code == 202
    assert len(queue.calls) == 1
    assert queue.calls[0][0][0].endswith("execute_historical_portfolio_backtest")


def test_uncovered_launch_reports_gap_instead_of_rebuilding(monkeypatch) -> None:
    """A launch never silently starts a full rebuild: it reports the missing sub-ranges so the
    caller can precalculate exactly those and retry."""

    client, db, queue = _client(monkeypatch)
    response = client.post("/strategy/signal/historical-portfolio-backtests", json={
        "start_date": "2024-01-01", "end_date": "2025-01-01",
    })
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "pit_coverage_incomplete"
    assert detail["missing_ranges"] == [{"start": "2024-01-01", "end": "2025-01-01"}]
    assert detail["materialization_in_progress"] is None
    assert db.query(models.HistoricalOpportunityMaterializationRun).count() == 0
    assert queue.calls == []


def test_uncovered_launch_points_at_inflight_materialization(monkeypatch) -> None:
    client, db, _queue = _client(monkeypatch)
    inflight = models.HistoricalOpportunityMaterializationRun(
        status="running", methodology_version=METHODOLOGY_VERSION,
        config_json={"start_date": "2024-01-01", "end_date": "2025-01-01", "symbols": ["ATW", "IAM"]},
        progress_json={"stage": "running"}, coverage_json={}, rq_job_id="rq-inflight-job",
    )
    db.add(inflight)
    db.commit()
    response = client.post("/strategy/signal/historical-portfolio-backtests", json={
        "start_date": "2024-01-01", "end_date": "2025-01-01",
    })
    assert response.status_code == 409
    assert response.json()["detail"]["materialization_in_progress"] == str(inflight.id)


def test_materialization_covers_only_missing_ranges_in_chunks(monkeypatch) -> None:
    """The precalculation top-up must skip already-covered dates and chunk what is left."""

    client, db, queue = _client(monkeypatch)
    db.add(models.HistoricalOpportunityMaterializationRun(
        status="succeeded", methodology_version=METHODOLOGY_VERSION,
        config_json={"start_date": "2024-01-01", "end_date": "2024-06-30", "symbols": []},
        progress_json={"stage": "completed"}, coverage_json={},
        completed_at=datetime.now(timezone.utc),
    ))
    db.commit()

    response = client.post(
        "/strategy/signal/historical-portfolio-backtests/materializations",
        json={"start_date": "2024-01-01", "end_date": "2024-12-31"},
    )
    assert response.status_code == 202

    windows = [
        (row.config_json["start_date"], row.config_json["end_date"])
        for row in db.query(models.HistoricalOpportunityMaterializationRun).filter_by(status="queued").all()
    ]
    # Only 2024-07-01..2024-12-31 was missing, split into 90-day chunks.
    assert windows == [("2024-07-01", "2024-09-28"), ("2024-09-29", "2024-12-27"), ("2024-12-28", "2024-12-31")]
    assert len(queue.calls) == 3
    assert "depends_on" not in queue.calls[0][1]
    assert queue.calls[1][1]["depends_on"].id == "rq-test-job-1"
    assert queue.calls[2][1]["depends_on"].id == "rq-test-job-2"


def test_materialization_rejects_fully_covered_window(monkeypatch) -> None:
    client, db, queue = _client(monkeypatch)
    _seed_coverage(db)
    response = client.post(
        "/strategy/signal/historical-portfolio-backtests/materializations",
        json={"start_date": "2024-01-01", "end_date": "2025-01-01"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "pit_coverage_already_complete"
    assert queue.calls == []


def test_backtest_covered_fast_path_enqueues_once_without_dependency(monkeypatch) -> None:
    client, db, queue = _client(monkeypatch)
    _seed_coverage(db)
    response = client.post("/strategy/signal/historical-portfolio-backtests", json={
        "start_date": "2024-01-01", "end_date": "2025-01-01",
    })
    assert response.status_code == 202
    assert response.json()["materialization_run_id"] is None
    assert len(queue.calls) == 1
    assert "depends_on" not in queue.calls[0][1]


def test_materialization_is_persisted_and_enqueued(monkeypatch) -> None:
    client, db, _queue = _client(monkeypatch)
    response = client.post("/strategy/signal/historical-portfolio-backtests/materializations", json={
        "start_date": "2024-01-01", "end_date": "2025-01-01",
    })
    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    # An uncovered year is chunked; the response points at the first chunk.
    rows = db.query(models.HistoricalOpportunityMaterializationRun).order_by(
        models.HistoricalOpportunityMaterializationRun.created_at
    ).all()
    assert str(rows[0].id) == payload["materialization_run_id"]
    assert rows[0].rq_job_id == "rq-test-job-1"
    assert rows[0].config_json["start_date"] == "2024-01-01"
    assert rows[-1].config_json["end_date"] == "2025-01-01"
    status_response = client.get(
        f"/strategy/signal/historical-portfolio-backtests/materializations/{payload['materialization_run_id']}"
    )
    assert status_response.status_code == 200


def test_run_contract_rejects_system_and_out_of_universe_symbols(monkeypatch) -> None:
    client, _db, _queue = _client(monkeypatch)
    reserved = client.post("/strategy/signal/historical-portfolio-backtests", json={
        "start_date": "2024-01-01", "end_date": "2025-01-01", "_system": {},
    })
    assert reserved.status_code == 422
    outside = client.post("/strategy/signal/historical-portfolio-backtests", json={
        "start_date": "2024-01-01", "end_date": "2025-01-01", "symbols": ["NOPE"],
    })
    assert outside.status_code == 422
    assert outside.json()["detail"]["offenders"] == ["NOPE"]


def test_decisions_route_filters_and_versioned_winner_semantics(monkeypatch) -> None:
    client, db, _queue = _client(monkeypatch)
    materialization = models.HistoricalOpportunityMaterializationRun(
        status="succeeded", methodology_version=METHODOLOGY_VERSION,
        config_json={}, progress_json={}, coverage_json={}, completed_at=datetime.now(timezone.utc),
    )
    db.add(materialization)
    db.flush()
    decision = {
        "status": "evaluated", "signal_direction": "short", "actionable": True,
        "actionability_reasons": [], "rank": [1, 2, 3, 4],
        "category_scores": {key: 1.0 for key in ("tendance", "momentum", "oscillation", "volume")},
        "aggregate_score": -80.0, "bucket": "strong_sell",
        "computation_rejection_reasons": [], "execution_eligible": False,
        "execution_rejection_reason": "short_entry_not_supported_masi", "evidence": {"n": 30},
    }
    db.add(models.HistoricalTradeOpportunity(
        methodology_version=METHODOLOGY_VERSION, decision_date=date(2024, 2, 1), symbol="IAM",
        horizon="weekly", variant="expanded", accepted=False, status="evaluated", actionable=True,
        reconstructed_dashboard_winner=True, rank_json=[1, 2, 3, 4], decision_json=decision,
        opportunity_json={"direction": "short"}, input_hash="a" * 64,
        materialization_run_id=materialization.id,
    ))
    db.commit()
    response = client.get(
        "/strategy/signal/historical-portfolio-backtests/decisions",
        params={"winners_only": True, "signal_direction": "short", "page_size": 200},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["winner_semantics"] == "v5_reconstructed_dashboard_winner"
    assert payload["items"][0]["decision"]["signal_direction"] == "short"


def test_run_reuse_ignores_server_system_metadata_but_not_barrier_config(monkeypatch) -> None:
    client, db, _queue = _client(monkeypatch)
    _seed_coverage(db)
    first = client.post("/strategy/signal/historical-portfolio-backtests", json={
        "start_date": "2024-01-01", "end_date": "2025-01-01", "stop_loss_pct": 0.1,
    })
    row = db.query(models.HistoricalPortfolioBacktestRun).one()
    materialization_ids = [
        str(item.id) for item in db.query(models.HistoricalOpportunityMaterializationRun).all()
    ]
    row.status = "succeeded"
    row.completed_at = datetime.now(timezone.utc)
    row.provenance_json = {"opportunity_store_materialization_runs": materialization_ids}
    row.config_json = {**row.config_json, "_system": {"source_watermark_v1": "abc"}}
    db.commit()
    reused = client.post("/strategy/signal/historical-portfolio-backtests", json={
        "start_date": "2024-01-01", "end_date": "2025-01-01", "stop_loss_pct": 0.1,
    })
    assert reused.status_code == 202
    assert reused.json() == {
        "run_id": first.json()["run_id"], "status": "succeeded", "reused": True,
        "materialization_run_id": None,
    }
    changed = client.post("/strategy/signal/historical-portfolio-backtests", json={
        "start_date": "2024-01-01", "end_date": "2025-01-01", "stop_loss_pct": 0.2,
    })
    assert changed.status_code == 202
    assert changed.json()["run_id"] != first.json()["run_id"]


def test_status_poll_reconciles_terminal_rq_state(monkeypatch) -> None:
    client, db, _queue = _client(monkeypatch)
    run = models.HistoricalPortfolioBacktestRun(
        status="queued", rq_job_id="dead-job", methodology_version=METHODOLOGY_VERSION,
        config_json={}, provenance_json={}, diagnostics_json={}, opportunities_json=[], trades_json=[],
        equity_curves_json={}, benchmark_curves_json={}, statistics_json={}, validation_json={},
        snapshot_audit_json={}, warnings_json=[],
    )
    db.add(run)
    db.commit()

    class FailedJob:
        dependency_ids = []

        @staticmethod
        def get_status(refresh=True):
            return "failed"

    monkeypatch.setattr(api, "_fetch_rq_job", lambda *_args, **_kwargs: FailedJob())
    response = client.get(f"/strategy/signal/historical-portfolio-backtests/{run.id}")
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "failed" in response.json()["error_message"]


def test_rq_reconciliation_authoritative_missing_dependency_and_outage(monkeypatch) -> None:
    _client_obj, db, _queue = _client(monkeypatch)
    run = models.HistoricalPortfolioBacktestRun(
        status="queued", rq_job_id="job", methodology_version=METHODOLOGY_VERSION,
        config_json={}, provenance_json={}, diagnostics_json={}, opportunities_json=[], trades_json=[],
        equity_curves_json={}, benchmark_curves_json={}, statistics_json={}, validation_json={},
        snapshot_audit_json={}, warnings_json=[],
    )
    db.add(run)
    db.commit()

    NoSuchJobError = type("NoSuchJobError", (Exception,), {})
    monkeypatch.setattr(api, "_fetch_rq_job", lambda *_args, **_kwargs: (_ for _ in ()).throw(NoSuchJobError()))
    api._reconcile_rq_state(db, run)
    assert run.status == "failed"
    first_error = run.error_message
    api._reconcile_rq_state(db, run)
    assert run.error_message == first_error

    run.status, run.error_message, run.rq_job_id = "queued", None, "deferred-job"
    db.commit()

    class DeferredJob:
        dependency_ids = ["dependency"]

        @staticmethod
        def get_status(refresh=True):
            return "deferred"

    class FailedDependency:
        dependency_ids = []

        @staticmethod
        def get_status(refresh=True):
            return "failed"

    monkeypatch.setattr(
        api, "_fetch_rq_job",
        lambda job_id, _connection: DeferredJob() if job_id == "deferred-job" else FailedDependency(),
    )
    api._reconcile_rq_state(db, run)
    assert run.status == "failed"
    assert "dependency" in run.error_message

    run.status, run.error_message, run.rq_job_id = "queued", None, "redis-outage"
    db.commit()
    from redis.exceptions import ConnectionError as RedisConnectionError
    monkeypatch.setattr(
        api, "_fetch_rq_job",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RedisConnectionError("offline")),
    )
    api._reconcile_rq_state(db, run)
    db.refresh(run)
    assert run.status == "queued"
    assert run.error_message is None
