from __future__ import annotations

import datetime as dt
import os
import uuid

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("MARKET_REFRESH_CRON_ENABLED", "0")

from services.api.app import models
from services.api.app.db import get_db
from services.api.app.routers import strategy_backtest_runs as strategy_backtest_runs_router
from core.quant_core.strategy_plan import wfo as strategy_wfo
from services.worker.tasks import strategy_backtest_runs as worker_strategy_backtest_runs


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):  # pragma: no cover - sqlite harness
    return "JSON"


@pytest.fixture()
def client_and_session(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    for table in (
        models.MarketDataStore.__table__,
        models.SavedStrategy.__table__,
        models.StrategyBacktestRun.__table__,
        models.StrategyBacktestStock.__table__,
        models.StrategyBacktestWindow.__table__,
    ):
        table.create(engine)

    app = FastAPI()
    app.include_router(strategy_backtest_runs_router.router)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    class _FakeQueue:
        def enqueue(self, *_args, **_kwargs):
            class _Job:
                id = "job-123"
            return _Job()

    monkeypatch.setattr(strategy_backtest_runs_router, "get_queue", lambda: _FakeQueue())
    monkeypatch.setattr(strategy_backtest_runs_router, "_resolve_code_version", lambda: "test-code-version")

    with TestClient(app) as client:
        yield client, SessionLocal

    app.dependency_overrides.clear()
    engine.dispose()


def _sample_strategy_config() -> dict:
    return {
        "schema_version": 3,
        "app_domain": "four_pages",
        "legacy_snapshot": None,
        "portfolio": {
            "total_capital_mad": 100_000,
            "universe": {
                "basket": ["IAM", "BCP"],
                "sector_filter": [],
                "min_abs_signal": 0,
                "min_adv20": 0,
                "sort_by": "adv20",
                "sort_dir": "desc",
            },
            "allocation": {
                "method": "hrp",
                "hrp_lookback_bars": 60,
                "manual_overrides_by_symbol": {},
            },
        },
        "stocks": {
            "IAM": {
                "strategy_type": "trend_following",
                "signal_construction": {
                    "families": {
                        "sma": {
                            "enabled": True,
                            "source_mode": "indicator_rows",
                            "rows": [
                                {
                                    "id": "sma_row_1",
                                    "enabled": True,
                                    "score_key": "trend_score",
                                    "label": "Trend Score",
                                    "params": {"window": {"mode": "manual", "value": 20}},
                                }
                            ],
                        },
                        "rsi": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                        "macd": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                        "obv": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                    },
                },
                "entry_rules": [],
                "exit_rules": [],
                "risk": {
                    "stop_loss": {"mode": "atr_based", "atr_multiplier": {"mode": "manual", "value": 1.5}},
                    "take_profit": {"mode": "rr_target", "rr_ratio": {"mode": "manual", "value": 1.5}},
                    "cooldown_bars": {"mode": "manual", "value": 0},
                    "time_stop": {"enabled": True, "bars": {"mode": "manual", "value": 30}},
                    "trailing_stop_enabled": False,
                    "max_position_pct": 20,
                    "max_sector_pct": 40,
                },
            },
            "BCP": {
                "strategy_type": "trend_following",
                "signal_construction": {
                    "families": {
                        "sma": {
                            "enabled": True,
                            "source_mode": "indicator_rows",
                            "rows": [
                                {
                                    "id": "sma_row_1",
                                    "enabled": True,
                                    "score_key": "trend_score",
                                    "label": "Trend Score",
                                    "params": {"window": {"mode": "manual", "value": 20}},
                                }
                            ],
                        },
                        "rsi": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                        "macd": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                        "obv": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                    },
                },
                "entry_rules": [],
                "exit_rules": [],
                "risk": {
                    "stop_loss": {"mode": "atr_based", "atr_multiplier": {"mode": "manual", "value": 1.5}},
                    "take_profit": {"mode": "rr_target", "rr_ratio": {"mode": "manual", "value": 1.5}},
                    "cooldown_bars": {"mode": "manual", "value": 0},
                    "time_stop": {"enabled": True, "bars": {"mode": "manual", "value": 30}},
                    "trailing_stop_enabled": False,
                    "max_position_pct": 20,
                    "max_sector_pct": 40,
                },
            },
        },
        "snapshot": None,
    }


def _sample_wfo_strategy_config() -> dict:
    config = _sample_strategy_config()
    for symbol in ("IAM", "BCP"):
        stock = config["stocks"][symbol]
        stock["entry_rules"] = [
            {
                "id": "entry_1",
                "label": "Entree 1",
                "config_option": "A",
                "conditions": [
                    {
                        "variable": "consensus_score",
                        "operator": ">=",
                        "threshold": {"mode": "wfo", "value": 1.0, "scan_min": 0.5, "scan_max": 1.5, "scan_step": 0.5},
                    }
                ],
                "sizing": {"mode": "manual", "manual_pct": 25},
            }
        ]
        stock["exit_rules"] = [
            {
                "id": "exit_1",
                "label": "Sortie 1",
                "config_option": "A",
                "conditions": [
                    {
                        "variable": "consensus_score",
                        "operator": "<=",
                        "threshold": {"mode": "manual", "value": -0.5},
                    }
                ],
                "sizing": {"mode": "manual", "manual_pct": 100},
            }
        ]
        stock["risk"]["take_profit"]["rr_ratio"] = {"mode": "wfo", "value": 1.5, "scan_min": 1.0, "scan_max": 2.0, "scan_step": 0.5}
    return config


def _sample_wfo_family_score_strategy_config() -> dict:
    config = _sample_wfo_strategy_config()
    for symbol in ("IAM", "BCP"):
        families = config["stocks"][symbol]["signal_construction"]["families"]
        families["sma"]["source_mode"] = "family_ensemble"
        families["sma"]["rows"] = []
    return config


def _direct_create_payload(strategy_id: uuid.UUID) -> dict:
    return {
        "strategy_id": str(strategy_id),
        "mode": "direct",
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "timeframe": "1D",
        "cost_model": {"brokerage_bps": 0.2, "comm_bourse_bps": 0.1, "reg_liv_bps": 0, "slippage_bps": 0, "tva_rate": 0.1},
        "volume_gate": {"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0, "adv_window": 20},
        "cooldown_bars": 0,
    }


def _seed_market_store_rows(session_factory) -> None:
    with session_factory() as db:
        now = dt.datetime(2026, 4, 5, tzinfo=dt.timezone.utc)
        db.add_all(
            [
                models.MarketDataStore(
                    symbol="IAM",
                    timeframe="1D",
                    object_key="market/iam.parquet",
                    start_ts=now - dt.timedelta(days=365),
                    end_ts=now,
                    row_count=252,
                    last_dataset_id=uuid.uuid4(),
                    source_provider="bourse_direct",
                    data_as_of=now.date(),
                    updated_at=now,
                ),
                models.MarketDataStore(
                    symbol="BCP",
                    timeframe="1D",
                    object_key="market/bcp.parquet",
                    start_ts=now - dt.timedelta(days=365),
                    end_ts=now,
                    row_count=252,
                    last_dataset_id=uuid.uuid4(),
                    source_provider="bourse_direct",
                    data_as_of=now.date(),
                    updated_at=now,
                ),
            ]
        )
        db.commit()


def test_create_strategy_backtest_run_enqueues_job(client_and_session) -> None:
    client, SessionLocal = client_and_session
    strategy_id = uuid.uuid4()
    _seed_market_store_rows(SessionLocal)

    with SessionLocal() as db:
        db.add(
            models.SavedStrategy(
                id=strategy_id,
                name="Desk Strategy",
                side_policy="long_only",
                horizon="medium",
                status="saved",
                config_json=_sample_strategy_config(),
            )
        )
        db.commit()

    response = client.post(
        "/backtest/strategy-runs",
        json=_direct_create_payload(strategy_id),
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["reused"] is False
    assert "Desk Strategy" in payload["title"]

    with SessionLocal() as db:
        run = db.get(models.StrategyBacktestRun, uuid.UUID(payload["run_id"]))
        stocks = db.query(models.StrategyBacktestStock).filter(models.StrategyBacktestStock.run_id == run.id).all()
        assert run is not None
        assert run.rq_job_id == "job-123"
        assert run.execution_fingerprint
        assert run.title
        assert dict(run.request_json or {}).get("family_history_mode") == "static_current_reps"
        assert len(stocks) == 2


def test_create_strategy_backtest_run_reuses_exact_match(client_and_session) -> None:
    client, SessionLocal = client_and_session
    _seed_market_store_rows(SessionLocal)
    first_strategy_id = uuid.uuid4()
    second_strategy_id = uuid.uuid4()

    with SessionLocal() as db:
        db.add_all(
            [
                models.SavedStrategy(
                    id=first_strategy_id,
                    name="Desk Strategy A",
                    side_policy="long_only",
                    horizon="medium",
                    status="saved",
                    config_json=_sample_strategy_config(),
                ),
                models.SavedStrategy(
                    id=second_strategy_id,
                    name="Desk Strategy B",
                    side_policy="long_only",
                    horizon="medium",
                    status="saved",
                    config_json=_sample_strategy_config(),
                ),
            ]
        )
        db.commit()

    first = client.post("/backtest/strategy-runs", json=_direct_create_payload(first_strategy_id))
    second = client.post("/backtest/strategy-runs", json=_direct_create_payload(second_strategy_id))

    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["reused"] is True
    assert second.json()["run_id"] == first.json()["run_id"]


def test_create_strategy_backtest_run_requeues_stale_queued_match(client_and_session, monkeypatch) -> None:
    client, SessionLocal = client_and_session
    _seed_market_store_rows(SessionLocal)
    strategy_id = uuid.uuid4()

    with SessionLocal() as db:
        db.add(
            models.SavedStrategy(
                id=strategy_id,
                name="Desk Strategy",
                side_policy="long_only",
                horizon="medium",
                status="saved",
                config_json=_sample_strategy_config(),
            )
        )
        db.commit()

    first = client.post("/backtest/strategy-runs", json=_direct_create_payload(strategy_id))
    assert first.status_code == 202
    run_id = uuid.UUID(first.json()["run_id"])

    class _StaleQueue:
        def enqueue(self, *_args, **_kwargs):
            class _Job:
                id = "job-456"
            return _Job()

        def fetch_job(self, _job_id):
            return None

    monkeypatch.setattr(strategy_backtest_runs_router, "get_queue", lambda: _StaleQueue())

    second = client.post("/backtest/strategy-runs", json=_direct_create_payload(strategy_id))
    assert second.status_code == 200
    assert second.json()["reused"] is True
    assert second.json()["run_id"] == str(run_id)

    with SessionLocal() as db:
        run = db.get(models.StrategyBacktestRun, run_id)
        assert run is not None
        assert run.rq_job_id == "job-456"
        assert dict(run.progress_json or {}).get("message") == "Re-queued in RQ"


def test_create_strategy_backtest_run_does_not_reuse_canceled_match(client_and_session) -> None:
    client, SessionLocal = client_and_session
    _seed_market_store_rows(SessionLocal)
    strategy_id = uuid.uuid4()

    with SessionLocal() as db:
        db.add(
            models.SavedStrategy(
                id=strategy_id,
                name="Desk Strategy",
                side_policy="long_only",
                horizon="medium",
                status="saved",
                config_json=_sample_strategy_config(),
            )
        )
        db.commit()

    first = client.post("/backtest/strategy-runs", json=_direct_create_payload(strategy_id))
    assert first.status_code == 202
    first_run_id = uuid.UUID(first.json()["run_id"])

    with SessionLocal() as db:
        run = db.get(models.StrategyBacktestRun, first_run_id)
        assert run is not None
        run.status = "canceled"
        run.completed_at = dt.datetime.now(dt.timezone.utc)
        db.commit()

    second = client.post("/backtest/strategy-runs", json=_direct_create_payload(strategy_id))
    assert second.status_code == 202
    assert second.json()["reused"] is False
    assert second.json()["run_id"] != str(first_run_id)


def test_create_strategy_backtest_run_fingerprint_changes_with_data_snapshot(client_and_session) -> None:
    client, SessionLocal = client_and_session
    strategy_id = uuid.uuid4()
    _seed_market_store_rows(SessionLocal)

    with SessionLocal() as db:
        db.add(
            models.SavedStrategy(
                id=strategy_id,
                name="Desk Strategy",
                side_policy="long_only",
                horizon="medium",
                status="saved",
                config_json=_sample_strategy_config(),
            )
        )
        db.commit()

    first = client.post("/backtest/strategy-runs", json=_direct_create_payload(strategy_id))
    assert first.status_code == 202

    with SessionLocal() as db:
        row = db.query(models.MarketDataStore).filter(models.MarketDataStore.symbol == "IAM").one()
        row.updated_at = row.updated_at + dt.timedelta(minutes=5)
        row.object_key = "market/iam-v2.parquet"
        db.commit()

    second = client.post("/backtest/strategy-runs", json=_direct_create_payload(strategy_id))
    assert second.status_code == 202
    assert second.json()["run_id"] != first.json()["run_id"]


def test_create_strategy_backtest_run_fingerprint_changes_with_family_history_mode(client_and_session) -> None:
    client, SessionLocal = client_and_session
    strategy_id = uuid.uuid4()
    _seed_market_store_rows(SessionLocal)

    with SessionLocal() as db:
        db.add(
            models.SavedStrategy(
                id=strategy_id,
                name="Desk Strategy",
                side_policy="long_only",
                horizon="medium",
                status="saved",
                config_json=_sample_strategy_config(),
            )
        )
        db.commit()

    baseline = client.post("/backtest/strategy-runs", json=_direct_create_payload(strategy_id))
    assert baseline.status_code == 202

    dynamic_payload = _direct_create_payload(strategy_id)
    dynamic_payload["family_history_mode"] = "dynamic_point_in_time"
    dynamic = client.post("/backtest/strategy-runs", json=dynamic_payload)
    assert dynamic.status_code == 202
    assert dynamic.json()["run_id"] != baseline.json()["run_id"]


def test_list_rename_and_delete_strategy_backtest_runs(client_and_session) -> None:
    client, SessionLocal = client_and_session
    strategy_id = uuid.uuid4()
    _seed_market_store_rows(SessionLocal)

    with SessionLocal() as db:
        db.add(
            models.SavedStrategy(
                id=strategy_id,
                name="Desk Strategy",
                side_policy="long_only",
                horizon="medium",
                status="saved",
                config_json=_sample_strategy_config(),
            )
        )
        db.commit()

    created = client.post("/backtest/strategy-runs", json=_direct_create_payload(strategy_id))
    run_id = created.json()["run_id"]

    listed = client.get("/backtest/strategy-runs", params={"strategy_id": str(strategy_id), "mode": "direct", "status": "queued", "q": "desk"})
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["run_id"] == run_id
    assert rows[0]["basket_count"] == 2

    renamed = client.patch(f"/backtest/strategy-runs/{run_id}", json={"title": "My Favorite Backtest"})
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "My Favorite Backtest"

    deleted = client.delete(f"/backtest/strategy-runs/{run_id}")
    assert deleted.status_code == 204

    listed_after = client.get("/backtest/strategy-runs")
    assert listed_after.status_code == 200
    assert listed_after.json() == []


def test_cancel_strategy_backtest_run_marks_queued_run_canceled(client_and_session, monkeypatch) -> None:
    client, SessionLocal = client_and_session
    strategy_id = uuid.uuid4()
    run_id = uuid.uuid4()
    _seed_market_store_rows(SessionLocal)

    with SessionLocal() as db:
        db.add(
            models.SavedStrategy(
                id=strategy_id,
                name="Desk Strategy",
                side_policy="long_only",
                horizon="medium",
                status="saved",
                config_json=_sample_strategy_config(),
            )
        )
        db.add(
            models.StrategyBacktestRun(
                id=run_id,
                strategy_id=strategy_id,
                mode="direct",
                status="queued",
                horizon="medium",
                title="Desk Strategy • Direct • 2026-04-05 10:00",
                execution_fingerprint="cancel-fingerprint",
                strategy_snapshot_json={"basket": ["IAM", "BCP"]},
                data_snapshot_json={"timeframe": "1D", "symbols": []},
                request_json=_direct_create_payload(strategy_id),
                summary_json={},
                result_json={},
                progress_json={"completed": 0, "total": 2, "message": "Queued in RQ"},
                rq_job_id="job-cancel-1",
            )
        )
        db.add(models.StrategyBacktestStock(run_id=run_id, symbol="IAM", status="queued", summary_json={}, result_json={}))
        db.add(models.StrategyBacktestStock(run_id=run_id, symbol="BCP", status="queued", summary_json={}, result_json={}))
        db.commit()

    class _FakeJob:
        def get_status(self, refresh=False):  # noqa: ARG002
            return "queued"

        def cancel(self):
            return None

    class _CancelQueue:
        connection = None

        def fetch_job(self, _job_id):
            return _FakeJob()

    monkeypatch.setattr(strategy_backtest_runs_router, "get_queue", lambda: _CancelQueue())

    response = client.post(f"/backtest/strategy-runs/{run_id}/cancel")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "canceled"

    with SessionLocal() as db:
        run = db.get(models.StrategyBacktestRun, run_id)
        stocks = (
            db.query(models.StrategyBacktestStock)
            .filter(models.StrategyBacktestStock.run_id == run_id)
            .order_by(models.StrategyBacktestStock.symbol.asc())
            .all()
        )
        assert run is not None
        assert run.status == "canceled"
        assert run.completed_at is not None
        assert all(stock.status == "canceled" for stock in stocks)


def test_worker_executes_strategy_backtest_run(monkeypatch, client_and_session) -> None:
    _client, SessionLocal = client_and_session
    strategy_id = uuid.uuid4()
    run_id = uuid.uuid4()

    with SessionLocal() as db:
        db.add(
            models.SavedStrategy(
                id=strategy_id,
                name="Desk Strategy",
                side_policy="long_only",
                horizon="medium",
                status="saved",
                config_json=_sample_strategy_config(),
            )
        )
        db.add(
            models.StrategyBacktestRun(
                id=run_id,
                strategy_id=strategy_id,
                mode="direct",
                status="queued",
                horizon="medium",
                title="Desk Strategy • Direct • 2026-04-05 10:00",
                execution_fingerprint="fingerprint",
                strategy_snapshot_json={"basket": ["IAM", "BCP"]},
                data_snapshot_json={"timeframe": "1D", "symbols": []},
                request_json={
                    "strategy_id": str(strategy_id),
                    "mode": "direct",
                    "start_date": "2024-01-01",
                    "end_date": "2024-12-31",
                    "timeframe": "1D",
                    "cost_model": {"brokerage_bps": 0.2, "comm_bourse_bps": 0.1, "reg_liv_bps": 0, "slippage_bps": 0, "tva_rate": 0.1},
                    "volume_gate": {"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0, "adv_window": 20},
                    "cooldown_bars": 0,
                },
                summary_json={},
                result_json={},
                progress_json={},
            )
        )
        db.add(models.StrategyBacktestStock(run_id=run_id, symbol="IAM", status="queued", summary_json={}, result_json={}))
        db.add(models.StrategyBacktestStock(run_id=run_id, symbol="BCP", status="queued", summary_json={}, result_json={}))
        db.commit()

    monkeypatch.setattr(worker_strategy_backtest_runs, "SessionLocal", SessionLocal)
    monkeypatch.setattr(
        worker_strategy_backtest_runs,
        "load_ohlcv_for_symbol",
        lambda *_args, **_kwargs: pd.DataFrame(
            {
                "Open": [1.0, 1.1, 1.2],
                "High": [1.1, 1.2, 1.3],
                "Low": [0.9, 1.0, 1.1],
                "Close": [1.0, 1.15, 1.25],
                "Volume": [1000, 1100, 1200],
            },
            index=pd.date_range("2024-01-01", periods=3, freq="D"),
        ),
    )
    monkeypatch.setattr(
        worker_strategy_backtest_runs,
        "run_strategy_plan_backtest",
        lambda **kwargs: {
            "general_results": {"metrics": {"net_pnl": 1234.0, "total_return": 0.12, "sharpe": 1.6, "number_of_trades": 5}, "plots": {}},
            "assumptions": {},
            "stocks": [
                {"symbol": "IAM", "allocation": {"capital_mad": 50_000, "weight_pct": 50}, "summary_metrics": {"net_pnl": 1234.0, "n_trades": 5}, "price_chart": {}, "trade_ledger": [], "trade_performance": []},
                {"symbol": "BCP", "allocation": {"capital_mad": 50_000, "weight_pct": 50}, "summary_metrics": {"net_pnl": 2345.0, "n_trades": 6}, "price_chart": {}, "trade_ledger": [], "trade_performance": []},
            ],
        },
    )

    worker_strategy_backtest_runs.execute_strategy_backtest_run(str(run_id))

    with SessionLocal() as db:
        run = db.get(models.StrategyBacktestRun, run_id)
        stocks = db.query(models.StrategyBacktestStock).filter(models.StrategyBacktestStock.run_id == run_id).order_by(models.StrategyBacktestStock.symbol.asc()).all()
        assert run.status == "succeeded"
        assert run.summary_json["succeeded"] == 2
        assert run.result_json["general_results"]["metrics"]["net_pnl"] == 1234.0
        assert all(stock.status == "succeeded" for stock in stocks)
        assert stocks[0].summary_json["net_pnl"] in {1234.0, 2345.0}


def test_worker_honors_cancel_requested_status_before_start(monkeypatch, client_and_session) -> None:
    _client, SessionLocal = client_and_session
    strategy_id = uuid.uuid4()
    run_id = uuid.uuid4()

    with SessionLocal() as db:
        db.add(
            models.SavedStrategy(
                id=strategy_id,
                name="Desk Strategy",
                side_policy="long_only",
                horizon="medium",
                status="saved",
                config_json=_sample_strategy_config(),
            )
        )
        db.add(
            models.StrategyBacktestRun(
                id=run_id,
                strategy_id=strategy_id,
                mode="direct",
                status="cancel_requested",
                horizon="medium",
                title="Desk Strategy • Direct • 2026-04-05 10:00",
                execution_fingerprint="cancel-requested-fingerprint",
                strategy_snapshot_json={"basket": ["IAM", "BCP"]},
                data_snapshot_json={"timeframe": "1D", "symbols": []},
                request_json=_direct_create_payload(strategy_id),
                summary_json={},
                result_json={},
                progress_json={},
            )
        )
        db.add(models.StrategyBacktestStock(run_id=run_id, symbol="IAM", status="queued", summary_json={}, result_json={}))
        db.add(models.StrategyBacktestStock(run_id=run_id, symbol="BCP", status="queued", summary_json={}, result_json={}))
        db.commit()

    monkeypatch.setattr(worker_strategy_backtest_runs, "SessionLocal", SessionLocal)
    worker_strategy_backtest_runs.execute_strategy_backtest_run(str(run_id))

    with SessionLocal() as db:
        run = db.get(models.StrategyBacktestRun, run_id)
        stocks = (
            db.query(models.StrategyBacktestStock)
            .filter(models.StrategyBacktestStock.run_id == run_id)
            .order_by(models.StrategyBacktestStock.symbol.asc())
            .all()
        )
        assert run is not None
        assert run.status == "canceled"
        assert run.completed_at is not None
        assert all(stock.status == "canceled" for stock in stocks)


def test_create_wfo_strategy_backtest_run_accepts_ready_strategy(client_and_session) -> None:
    client, SessionLocal = client_and_session
    strategy_id = uuid.uuid4()
    _seed_market_store_rows(SessionLocal)

    with SessionLocal() as db:
        db.add(
            models.SavedStrategy(
                id=strategy_id,
                name="Desk Strategy WFO",
                side_policy="long_only",
                horizon="medium",
                status="saved",
                config_json=_sample_wfo_strategy_config(),
            )
        )
        db.commit()

    response = client.post(
        "/backtest/strategy-runs",
        json={
            "strategy_id": str(strategy_id),
            "mode": "wfo",
            "timeframe": "1D",
            "cost_model": {"brokerage_bps": 0.2, "comm_bourse_bps": 0.1, "reg_liv_bps": 0, "slippage_bps": 0, "tva_rate": 0.1},
            "volume_gate": {"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0, "adv_window": 20},
            "cooldown_bars": 0,
            "wfo_config": {
                "is_oos_ratios": [0.25, 0.3],
                "min_walk_forwards": 3,
                "test_period_start": "2024-01-01",
                "test_period_end": "2024-12-31",
                "n_monte_carlo_paths": 200,
            },
        },
    )

    assert response.status_code == 202
    assert response.json()["mode"] == "wfo"
    run_id = uuid.UUID(response.json()["run_id"])
    with SessionLocal() as db:
        run = db.get(models.StrategyBacktestRun, run_id)
        assert run is not None
        wfo_config = dict((run.request_json or {}).get("wfo_config") or {})
        assert wfo_config["window_policy"] == "strict_fold_driven"
        assert wfo_config["top_k_folds"] == 12
        assert wfo_config["strict_fallback_enabled"] is True
        assert wfo_config["strict_fallback_floor"] == 1


def test_create_wfo_strategy_backtest_run_accepts_family_score_signal_mode(client_and_session) -> None:
    client, SessionLocal = client_and_session
    strategy_id = uuid.uuid4()
    _seed_market_store_rows(SessionLocal)

    with SessionLocal() as db:
        db.add(
            models.SavedStrategy(
                id=strategy_id,
                name="Desk Strategy WFO Family Score",
                side_policy="long_only",
                horizon="medium",
                status="saved",
                config_json=_sample_wfo_family_score_strategy_config(),
            )
        )
        db.commit()

    response = client.post(
        "/backtest/strategy-runs",
        json={
            "strategy_id": str(strategy_id),
            "mode": "wfo",
            "timeframe": "1D",
            "cost_model": {"brokerage_bps": 0.2, "comm_bourse_bps": 0.1, "reg_liv_bps": 0, "slippage_bps": 0, "tva_rate": 0.1},
            "volume_gate": {"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0, "adv_window": 20},
            "cooldown_bars": 0,
            "wfo_config": {
                "is_oos_ratios": [0.25, 0.3],
                "min_walk_forwards": 3,
                "test_period_start": "2024-01-01",
                "test_period_end": "2024-12-31",
                "n_monte_carlo_paths": 200,
            },
        },
    )

    assert response.status_code == 202
    assert response.json()["mode"] == "wfo"


def test_wfo_engine_accepts_family_score_signal_mode(monkeypatch) -> None:
    def _derive_max_lookback_guard(*_args, **kwargs):
        assert kwargs.get("strict_indicator_rows") is not True
        return 5

    monkeypatch.setattr(strategy_wfo, "derive_max_lookback", _derive_max_lookback_guard)

    bars = pd.DataFrame(
        {
            "Open": [100.0 + (0.05 * idx) for idx in range(520)],
            "High": [101.0 + (0.05 * idx) for idx in range(520)],
            "Low": [99.0 + (0.05 * idx) for idx in range(520)],
            "Close": [100.0 + (0.05 * idx) for idx in range(520)],
            "Volume": [20_000.0 for _ in range(520)],
        },
        index=pd.date_range("2023-01-01", periods=520, freq="D"),
    )

    stock_config = _sample_wfo_family_score_strategy_config()["stocks"]["IAM"]
    result = strategy_wfo.run_stock_walk_forward(
        symbol="IAM",
        strategy_id="strategy-1",
        strategy_name="Family score WFO",
        side_policy="long_only",
        horizon="medium",
        timeframe="1D",
        stock_config=stock_config,
        bars=bars,
        start_date=None,
        end_date=None,
        allocated_capital=100_000.0,
        cost_model_raw={"brokerage_bps": 0.2, "comm_bourse_bps": 0.1, "reg_liv_bps": 0.0, "slippage_bps": 0.0, "tva_rate": 0.1},
        volume_gate={"enabled": False},
        cooldown_bars=0,
        wfo_config={
            "window_policy": "strict_fold_driven",
            "top_k_folds": 1,
            "min_walk_forwards": 1,
            "test_period_start": "2024-02-01",
            "test_period_end": "2024-02-20",
            "n_monte_carlo_paths": 100,
        },
    )

    assert result["status"] in {"succeeded", "not_viable"}
    assert result["summary"]["status"] in {"succeeded", "not_viable"}
    assert int(result["summary"]["candidate_count"]) >= 2


def test_create_wfo_strategy_backtest_run_requires_explicit_test_end(client_and_session) -> None:
    client, SessionLocal = client_and_session
    strategy_id = uuid.uuid4()
    _seed_market_store_rows(SessionLocal)

    with SessionLocal() as db:
        db.add(
            models.SavedStrategy(
                id=strategy_id,
                name="Desk Strategy WFO",
                side_policy="long_only",
                horizon="medium",
                status="saved",
                config_json=_sample_wfo_strategy_config(),
            )
        )
        db.commit()

    response = client.post(
        "/backtest/strategy-runs",
        json={
            "strategy_id": str(strategy_id),
            "mode": "wfo",
            "timeframe": "1D",
            "cost_model": {"brokerage_bps": 0.2, "comm_bourse_bps": 0.1, "reg_liv_bps": 0, "slippage_bps": 0, "tva_rate": 0.1},
            "volume_gate": {"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0, "adv_window": 20},
            "cooldown_bars": 0,
            "wfo_config": {"is_oos_ratios": [0.25, 0.3], "min_walk_forwards": 3, "test_period_start": "2024-01-01"},
        },
    )

    assert response.status_code == 422
    assert "test_period_end" in response.text


def test_create_wfo_strategy_backtest_run_legacy_policy_rejects_invalid_ratios(client_and_session) -> None:
    client, SessionLocal = client_and_session
    strategy_id = uuid.uuid4()
    _seed_market_store_rows(SessionLocal)

    with SessionLocal() as db:
        db.add(
            models.SavedStrategy(
                id=strategy_id,
                name="Desk Strategy WFO",
                side_policy="long_only",
                horizon="medium",
                status="saved",
                config_json=_sample_wfo_strategy_config(),
            )
        )
        db.commit()

    response = client.post(
        "/backtest/strategy-runs",
        json={
            "strategy_id": str(strategy_id),
            "mode": "wfo",
            "timeframe": "1D",
            "cost_model": {"brokerage_bps": 0.2, "comm_bourse_bps": 0.1, "reg_liv_bps": 0, "slippage_bps": 0, "tva_rate": 0.1},
            "volume_gate": {"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0, "adv_window": 20},
            "cooldown_bars": 0,
            "wfo_config": {
                "window_policy": "legacy_ratio_scan",
                "is_oos_ratios": [1.2, -0.1],
                "min_walk_forwards": 3,
                "test_period_start": "2024-01-01",
                "test_period_end": "2024-12-31",
            },
        },
    )

    assert response.status_code == 422
    assert "ratios" in response.text.lower()
def test_worker_executes_wfo_strategy_backtest_run(monkeypatch, client_and_session) -> None:
    _client, SessionLocal = client_and_session
    strategy_id = uuid.uuid4()
    run_id = uuid.uuid4()

    with SessionLocal() as db:
        db.add(
            models.SavedStrategy(
                id=strategy_id,
                name="Desk Strategy WFO",
                side_policy="long_only",
                horizon="medium",
                status="saved",
                config_json=_sample_wfo_strategy_config(),
            )
        )
        db.add(
            models.StrategyBacktestRun(
                id=run_id,
                strategy_id=strategy_id,
                mode="wfo",
                status="queued",
                horizon="medium",
                title="Desk Strategy WFO - WFO - 2026-04-05 10:00",
                execution_fingerprint="fingerprint",
                strategy_snapshot_json={"basket": ["IAM", "BCP"]},
                data_snapshot_json={"timeframe": "1D", "symbols": []},
                request_json={
                    "strategy_id": str(strategy_id),
                    "mode": "wfo",
                    "start_date": "",
                    "end_date": "",
                    "timeframe": "1D",
                    "cost_model": {"brokerage_bps": 0.2, "comm_bourse_bps": 0.1, "reg_liv_bps": 0, "slippage_bps": 0, "tva_rate": 0.1},
                    "volume_gate": {"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0, "adv_window": 20},
                    "cooldown_bars": 0,
                    "wfo_config": {
                        "is_oos_ratios": [0.25],
                        "min_walk_forwards": 3,
                        "test_period_start": "2024-01-01",
                        "test_period_end": "2024-12-31",
                        "n_monte_carlo_paths": 200,
                    },
                },
                summary_json={},
                result_json={},
                progress_json={},
            )
        )
        db.add(models.StrategyBacktestStock(run_id=run_id, symbol="IAM", status="queued", summary_json={}, result_json={}))
        db.add(models.StrategyBacktestStock(run_id=run_id, symbol="BCP", status="queued", summary_json={}, result_json={}))
        db.commit()

    monkeypatch.setattr(worker_strategy_backtest_runs, "SessionLocal", SessionLocal)
    monkeypatch.setattr(
        worker_strategy_backtest_runs,
        "load_ohlcv_for_symbol",
        lambda *_args, **_kwargs: pd.DataFrame(
            {
                "Open": [1.0, 1.1, 1.2, 1.25],
                "High": [1.1, 1.2, 1.3, 1.35],
                "Low": [0.9, 1.0, 1.1, 1.15],
                "Close": [1.0, 1.15, 1.25, 1.3],
                "Volume": [1000, 1100, 1200, 1250],
            },
            index=pd.date_range("2020-01-01", periods=4, freq="D"),
        ),
    )
    monkeypatch.setattr(
        worker_strategy_backtest_runs,
        "compute_strategy_allocation_map",
        lambda **_kwargs: {"IAM": 50_000.0, "BCP": 50_000.0},
    )
    monkeypatch.setattr(
        worker_strategy_backtest_runs,
        "run_stock_walk_forward",
        lambda **kwargs: {
            "symbol": kwargs["symbol"],
            "status": "succeeded",
            "summary": {
                "symbol": kwargs["symbol"],
                "status": "succeeded",
                "wfe": 0.72,
                "robustness_ratio": 0.66,
                "final_test_return": 0.14,
            },
            "result": {
                "symbol": kwargs["symbol"],
                "status": "succeeded",
                "winning_config": {"wfe": 0.72},
                "windows": [
                    {
                        "window_index": 0,
                        "summary": {"window_index": 0, "profile_passes": True},
                    }
                ],
                "diagnostics": {
                    "window_policy": "strict_fold_driven",
                    "policy": {
                        "window_policy_used": "strict_fold_driven",
                        "fallback_applied": False,
                        "ignored_inputs": ["is_oos_ratios"],
                        "feasibility": {"horizon_cap_applied": True},
                    },
                },
                "test_period": {
                    "equity_curve": [
                        {"date": "2024-01-01", "value": 50000.0},
                        {"date": "2024-01-02", "value": 52000.0},
                    ]
                },
            },
            "windows": [
                {
                    "window_index": 0,
                    "summary": {"window_index": 0, "profile_passes": True},
                    "detail": {"window_index": 0, "winner_params": {"risk.take_profit.rr_ratio": 1.5}},
                }
            ],
        },
    )
    monkeypatch.setattr(
        worker_strategy_backtest_runs,
        "aggregate_portfolio_test_results",
        lambda *args, **kwargs: {"status": "succeeded", "test_period": {"metrics": {"total_return": 0.14}}, "robustness": {"enabled": False}},
    )

    worker_strategy_backtest_runs.execute_strategy_backtest_run(str(run_id))

    with SessionLocal() as db:
        run = db.get(models.StrategyBacktestRun, run_id)
        stocks = db.query(models.StrategyBacktestStock).filter(models.StrategyBacktestStock.run_id == run_id).order_by(models.StrategyBacktestStock.symbol.asc()).all()
        windows = db.query(models.StrategyBacktestWindow).filter(models.StrategyBacktestWindow.run_id == run_id).all()
        assert run.status == "succeeded"
        assert run.summary_json["succeeded"] == 2
        assert run.summary_json["portfolio"]["status"] == "succeeded"
        assert run.summary_json["strict_window_policy"]["strict_symbols"] == ["BCP", "IAM"]
        assert run.summary_json["strict_window_policy"]["ratios_ignored_symbols"] == ["BCP", "IAM"]
        assert run.summary_json["strict_window_policy"]["horizon_cap_applied_symbols"] == ["BCP", "IAM"]
        assert len(windows) == 2
        assert all(stock.status == "succeeded" for stock in stocks)
        assert stocks[0].summary_json["wfe"] == 0.72
        assert stocks[0].result_json["windows"] == [{"window_index": 0, "summary": {"window_index": 0, "profile_passes": True}}]
        assert windows[0].detail_json["winner_params"] == {"risk.take_profit.rr_ratio": 1.5}


def test_worker_marks_all_not_viable_wfo_run_as_succeeded(monkeypatch, client_and_session) -> None:
    _client, SessionLocal = client_and_session
    strategy_id = uuid.uuid4()
    run_id = uuid.uuid4()

    with SessionLocal() as db:
        db.add(
            models.SavedStrategy(
                id=strategy_id,
                name="Desk Strategy WFO",
                side_policy="long_only",
                horizon="medium",
                status="saved",
                config_json=_sample_wfo_strategy_config(),
            )
        )
        db.add(
            models.StrategyBacktestRun(
                id=run_id,
                strategy_id=strategy_id,
                mode="wfo",
                status="queued",
                horizon="medium",
                title="Desk Strategy WFO • WFO • 2026-04-05 10:00",
                execution_fingerprint="fingerprint-not-viable",
                strategy_snapshot_json={"basket": ["IAM", "BCP"]},
                data_snapshot_json={"timeframe": "1D", "symbols": []},
                request_json={
                    "strategy_id": str(strategy_id),
                    "mode": "wfo",
                    "start_date": "",
                    "end_date": "",
                    "timeframe": "1D",
                    "cost_model": {"brokerage_bps": 0.2, "comm_bourse_bps": 0.1, "reg_liv_bps": 0, "slippage_bps": 0, "tva_rate": 0.1},
                    "volume_gate": {"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0, "adv_window": 20},
                    "cooldown_bars": 0,
                    "wfo_config": {
                        "is_oos_ratios": [0.25],
                        "min_walk_forwards": 3,
                        "test_period_start": "2024-01-01",
                        "test_period_end": "2024-12-31",
                        "n_monte_carlo_paths": 200,
                    },
                },
                summary_json={},
                result_json={},
                progress_json={},
            )
        )
        db.add(models.StrategyBacktestStock(run_id=run_id, symbol="IAM", status="queued", summary_json={}, result_json={}))
        db.add(models.StrategyBacktestStock(run_id=run_id, symbol="BCP", status="queued", summary_json={}, result_json={}))
        db.commit()

    monkeypatch.setattr(worker_strategy_backtest_runs, "SessionLocal", SessionLocal)
    monkeypatch.setattr(
        worker_strategy_backtest_runs,
        "load_ohlcv_for_symbol",
        lambda *_args, **_kwargs: pd.DataFrame(
            {
                "Open": [1.0, 1.1, 1.2, 1.25],
                "High": [1.1, 1.2, 1.3, 1.35],
                "Low": [0.9, 1.0, 1.1, 1.15],
                "Close": [1.0, 1.15, 1.25, 1.3],
                "Volume": [1000, 1100, 1200, 1250],
            },
            index=pd.date_range("2020-01-01", periods=4, freq="D"),
        ),
    )
    monkeypatch.setattr(
        worker_strategy_backtest_runs,
        "compute_strategy_allocation_map",
        lambda **_kwargs: {"IAM": 50_000.0, "BCP": 50_000.0},
    )
    monkeypatch.setattr(
        worker_strategy_backtest_runs,
        "run_stock_walk_forward",
        lambda **kwargs: {
            "symbol": kwargs["symbol"],
            "status": "not_viable",
            "summary": {
                "symbol": kwargs["symbol"],
                "status": "not_viable",
                "wfe": 0.32,
                "robustness_ratio": 0.43,
                "rejection_reasons": ["WFE = 32.0% < 50% threshold"],
            },
            "result": {
                "symbol": kwargs["symbol"],
                "status": "not_viable",
                "winning_config": {"wfe": 0.32, "viable": False},
                "windows": [
                    {
                        "window_index": 0,
                        "summary": {"window_index": 0, "profile_passes": False},
                    }
                ],
                "rejection_reasons": ["WFE = 32.0% < 50% threshold"],
                "all_configs_tested": [{"train_bars": 504, "oos_bars": 126, "window_count": 1, "wfe": 0.32, "robustness_ratio": 0.43, "profile_passes": False, "viable": False}],
                "diagnostics": {
                    "window_policy": "strict_fold_driven",
                    "policy": {
                        "window_policy_used": "strict_fold_driven",
                        "fallback_applied": True,
                        "ignored_inputs": ["is_oos_ratios"],
                        "feasibility": {"horizon_cap_applied": False},
                    },
                },
            },
            "windows": [
                {
                    "window_index": 0,
                    "summary": {"window_index": 0, "profile_passes": False},
                    "detail": {"window_index": 0, "raw_proms": [{"params": {"risk.take_profit.rr_ratio": 1.5}, "prom": 0.2}]},
                }
            ],
        },
    )
    monkeypatch.setattr(
        worker_strategy_backtest_runs,
        "aggregate_portfolio_test_results",
        lambda *args, **kwargs: {"status": "failed", "test_period": None, "robustness": {}},
    )

    worker_strategy_backtest_runs.execute_strategy_backtest_run(str(run_id))

    with SessionLocal() as db:
        run = db.get(models.StrategyBacktestRun, run_id)
        stocks = db.query(models.StrategyBacktestStock).filter(models.StrategyBacktestStock.run_id == run_id).order_by(models.StrategyBacktestStock.symbol.asc()).all()
        windows = db.query(models.StrategyBacktestWindow).filter(models.StrategyBacktestWindow.run_id == run_id).all()
        assert run.status == "succeeded"
        assert run.error_text is None
        assert run.summary_json["succeeded"] == 0
        assert run.summary_json["not_viable"] == 2
        assert run.summary_json["strict_window_policy"]["strict_symbols"] == ["BCP", "IAM"]
        assert run.summary_json["strict_window_policy"]["fallback_symbols"] == ["BCP", "IAM"]
        assert len(windows) == 2
        assert all(stock.status == "not_viable" for stock in stocks)
        assert stocks[0].result_json["windows"] == [{"window_index": 0, "summary": {"window_index": 0, "profile_passes": False}}]
        assert windows[0].detail_json["raw_proms"] == [{"params": {"risk.take_profit.rr_ratio": 1.5}, "prom": 0.2}]
