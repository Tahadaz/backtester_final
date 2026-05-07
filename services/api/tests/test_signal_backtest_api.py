from __future__ import annotations

import datetime as dt
import sys
import types
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.app.db import get_db
from services.api.app.models import (
    MarketDataStore,
    SignalEngineBatchJob,
    SignalEngineFamilyResult,
    SignalEngineGlobalResult,
    StockMaster,
)
from services.api.app.routers import strategy_signals
from services.api.app.services import signal_engine_persistence as signal_engine_persistence_mod


class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def filter_by(self, **kwargs):
        rows = [
            row
            for row in self._rows
            if all(getattr(row, key, None) == value for key, value in kwargs.items())
        ]
        return _FakeQuery(rows)

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, count):
        return _FakeQuery(self._rows[:count])

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    def __init__(self, rows_by_model):
        self.rows_by_model = {**rows_by_model}

    def query(self, model):
        return _FakeQuery(self.rows_by_model.get(model, []))


def _app(db) -> FastAPI:
    app = FastAPI()
    app.include_router(strategy_signals.router)

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return app


def test_engine_result_returns_persisted_support_resistance_payload():
    global_row = SignalEngineGlobalResult(
        symbol="AAA",
        horizon="short",
        variant="legacy",
        status="succeeded",
        aggregate_score_pct=10.0,
        expanded_aggregate_score_pct=20.0,
        signal_label="Haussier",
        per_category_json={"tendance": {"score_pct": 20.0}},
        per_family_json={"sma": {"score_pct": 20.0}},
        technical_levels_json={"support_buy_trigger": 99.0},
        support_resistance_json={"final_support": 99.0, "final_resistance": 110.0},
        computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
        data_as_of=dt.date(2026, 4, 21),
    )
    family_rows = [
        SignalEngineFamilyResult(
            symbol="AAA",
            family="sma",
            category="tendance",
            horizon="short",
            variant="legacy",
            status="succeeded",
            family_score_pct=20.0,
            signal_label="Haussier",
            tested_count=1,
            viable_count=1,
            representative_count=1,
            is_provisional=False,
            computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
            data_as_of=dt.date(2026, 4, 21),
            representatives_json=[{"variant_id": "sma_v1", "archetype": "price_vs_sma", "params": {"window": 20}}],
        ),
        SignalEngineFamilyResult(
            symbol="AAA",
            family="macd",
            category="momentum",
            horizon="short",
            variant="legacy",
            status="succeeded",
            family_score_pct=10.0,
            signal_label="Haussier",
            tested_count=1,
            viable_count=1,
            representative_count=1,
            is_provisional=False,
            computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
            data_as_of=dt.date(2026, 4, 21),
            representatives_json=[{"variant_id": "macd_v1", "archetype": "macd_cross", "params": {"fast": 12, "slow": 26, "signal": 9}}],
        ),
        SignalEngineFamilyResult(
            symbol="AAA",
            family="rsi",
            category="oscillation",
            horizon="short",
            variant="legacy",
            status="succeeded",
            family_score_pct=5.0,
            signal_label="Neutre",
            tested_count=1,
            viable_count=1,
            representative_count=1,
            is_provisional=False,
            computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
            data_as_of=dt.date(2026, 4, 21),
            representatives_json=[{"variant_id": "rsi_v1", "archetype": "rsi_level", "params": {"period": 14, "oversold": 30, "overbought": 70}}],
        ),
        SignalEngineFamilyResult(
            symbol="AAA",
            family="obv",
            category="volume",
            horizon="short",
            variant="legacy",
            status="succeeded",
            family_score_pct=15.0,
            signal_label="Haussier",
            tested_count=1,
            viable_count=1,
            representative_count=1,
            is_provisional=False,
            computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
            data_as_of=dt.date(2026, 4, 21),
            representatives_json=[{"variant_id": "obv_v1", "archetype": "obv_trend", "params": {"ema_period": 20}}],
        ),
    ]
    market_row = MarketDataStore(symbol="AAA", timeframe="1D", data_as_of=dt.date(2026, 4, 21))
    client = TestClient(
        _app(
            _FakeDB(
                {
                    SignalEngineGlobalResult: [global_row],
                    SignalEngineFamilyResult: family_rows,
                    MarketDataStore: [market_row],
                }
            )
        )
    )

    response = client.get("/strategy/engine/result?symbol=AAA&horizon=short&variant=legacy")

    assert response.status_code == 200
    payload = response.json()
    assert payload["technical_levels"] == {"support_buy_trigger": 99.0}
    assert payload["support_resistance"] == {"final_support": 99.0, "final_resistance": 110.0}
    assert payload["resolution_mode"] == "fresh_cache"


def test_engine_result_returns_stale_cache_without_refresh_or_rebuild(monkeypatch):
    global_row = SignalEngineGlobalResult(
        symbol="AAA",
        horizon="short",
        variant="legacy",
        status="succeeded",
        aggregate_score_pct=10.0,
        expanded_aggregate_score_pct=20.0,
        signal_label="Haussier",
        per_category_json={"tendance": {"score_pct": 20.0}},
        per_family_json={"sma": {"score_pct": 20.0}},
        technical_levels_json={"support_buy_trigger": 99.0},
        support_resistance_json={"final_support": 99.0, "final_resistance": 110.0},
        computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
        data_as_of=dt.date(2026, 4, 21),
    )
    family_rows = [
        SignalEngineFamilyResult(
            symbol="AAA",
            family="sma",
            category="tendance",
            horizon="short",
            variant="legacy",
            status="succeeded",
            family_score_pct=20.0,
            signal_label="Haussier",
            tested_count=1,
            viable_count=1,
            representative_count=1,
            is_provisional=False,
            computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
            data_as_of=dt.date(2026, 4, 21),
            representatives_json=[{"variant_id": "sma_v1", "archetype": "price_vs_sma", "params": {"window": 20}}],
        ),
        SignalEngineFamilyResult(
            symbol="AAA",
            family="macd",
            category="momentum",
            horizon="short",
            variant="legacy",
            status="succeeded",
            family_score_pct=10.0,
            signal_label="Haussier",
            tested_count=1,
            viable_count=1,
            representative_count=1,
            is_provisional=False,
            computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
            data_as_of=dt.date(2026, 4, 21),
            representatives_json=[{"variant_id": "macd_v1", "archetype": "macd_cross", "params": {"fast": 12, "slow": 26, "signal": 9}}],
        ),
        SignalEngineFamilyResult(
            symbol="AAA",
            family="rsi",
            category="oscillation",
            horizon="short",
            variant="legacy",
            status="succeeded",
            family_score_pct=5.0,
            signal_label="Neutre",
            tested_count=1,
            viable_count=1,
            representative_count=1,
            is_provisional=False,
            computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
            data_as_of=dt.date(2026, 4, 21),
            representatives_json=[{"variant_id": "rsi_v1", "archetype": "rsi_level", "params": {"period": 14, "oversold": 30, "overbought": 70}}],
        ),
        SignalEngineFamilyResult(
            symbol="AAA",
            family="obv",
            category="volume",
            horizon="short",
            variant="legacy",
            status="succeeded",
            family_score_pct=15.0,
            signal_label="Haussier",
            tested_count=1,
            viable_count=1,
            representative_count=1,
            is_provisional=False,
            computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
            data_as_of=dt.date(2026, 4, 21),
            representatives_json=[{"variant_id": "obv_v1", "archetype": "obv_trend", "params": {"ema_period": 20}}],
        ),
    ]
    market_row = MarketDataStore(symbol="AAA", timeframe="1D", data_as_of=dt.date(2026, 4, 22))
    client = TestClient(
        _app(
            _FakeDB(
                {
                    SignalEngineGlobalResult: [global_row],
                    SignalEngineFamilyResult: family_rows,
                    MarketDataStore: [market_row],
                }
            )
        )
    )

    monkeypatch.setattr(
        signal_engine_persistence_mod,
        "refresh_from_persisted_reps",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("stale GET should not refresh")),
    )
    monkeypatch.setattr(
        signal_engine_persistence_mod,
        "full_rebuild_from_pipeline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("stale GET should not rebuild")),
    )

    response = client.get("/strategy/engine/result?symbol=AAA&horizon=short&variant=legacy")

    assert response.status_code == 200
    payload = response.json()
    assert payload["resolution_mode"] == "stale_cache"
    assert payload["cache_state"] == "stale"
    assert payload["is_stale"] is True
    assert payload["market_data_as_of"] == "2026-04-22"


def test_persisted_signal_engine_summaries_follow_variant_specific_persisted_scores():
    rows = [
        SignalEngineGlobalResult(
            symbol="AAA",
            horizon="short",
            variant="expanded",
            status="succeeded",
            aggregate_score_pct=10.0,
            expanded_aggregate_score_pct=44.0,
            signal_label="Achat",
            computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
            data_as_of=dt.date(2026, 4, 21),
        ),
        SignalEngineGlobalResult(
            symbol="AAA",
            horizon="short",
            variant="legacy",
            status="succeeded",
            aggregate_score_pct=10.0,
            expanded_aggregate_score_pct=44.0,
            signal_label="Achat",
            computed_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
            data_as_of=dt.date(2026, 4, 21),
        ),
    ]
    market_rows = [MarketDataStore(symbol="AAA", timeframe="1D", data_as_of=dt.date(2026, 4, 22))]
    client = TestClient(_app(_FakeDB({SignalEngineGlobalResult: rows, MarketDataStore: market_rows})))

    expanded = client.post(
        "/strategy/engine/persisted-summaries",
        json={"symbols": ["AAA", "BBB"], "horizon": "short", "variant": "expanded"},
    )
    legacy = client.post(
        "/strategy/engine/persisted-summaries",
        json={"symbols": ["AAA"], "horizon": "short", "variant": "legacy"},
    )

    assert expanded.status_code == 200
    assert legacy.status_code == 200

    expanded_payload = expanded.json()
    legacy_payload = legacy.json()

    assert expanded_payload[0]["symbol"] == "AAA"
    assert expanded_payload[0]["aggregate_score_pct"] == 44.0
    assert expanded_payload[0]["is_stale"] is True
    assert expanded_payload[1]["symbol"] == "BBB"
    assert expanded_payload[1]["aggregate_score_pct"] is None

    assert legacy_payload[0]["symbol"] == "AAA"
    assert legacy_payload[0]["aggregate_score_pct"] == 10.0


def test_batch_status_endpoints_filter_by_job_type():
    engine_job = SignalEngineBatchJob(
        id=uuid.uuid4(),
        symbol="AAA",
        horizon="short",
        variant="expanded",
        job_type="signal_engine",
        status="succeeded",
        created_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
    )
    backtest_job = SignalEngineBatchJob(
        id=uuid.uuid4(),
        symbol="AAA",
        horizon="short",
        variant="expanded",
        job_type="signal_backtest",
        status="running",
        created_at=dt.datetime(2026, 4, 21, tzinfo=dt.timezone.utc),
    )
    client = TestClient(_app(_FakeDB({SignalEngineBatchJob: [engine_job, backtest_job]})))

    engine_response = client.get("/strategy/engine/batch-status?symbol=AAA&horizon=short&variant=expanded")
    backtest_response = client.get("/strategy/backtest-mc/batch-status?symbol=AAA&horizon=short&variant=expanded")

    assert engine_response.status_code == 200
    assert backtest_response.status_code == 200
    assert [job["job_type"] for job in engine_response.json()["jobs"]] == ["signal_engine"]
    assert [job["job_type"] for job in backtest_response.json()["jobs"]] == ["signal_backtest"]


def test_trigger_all_signal_engine_enqueues_all_active_symbols_and_horizons(monkeypatch):
    calls: list[tuple[str, str, str, str, str | None]] = []

    def _fake_enqueue(
        symbol: str,
        horizon: str,
        variant: str = "expanded",
        triggered_by: str = "manual",
        batch_id: str | None = None,
    ):
        calls.append((symbol, horizon, variant, triggered_by, batch_id))
        return f"{symbol}-{horizon}-{variant}"

    fake_enqueue_module = types.ModuleType("services.worker.tasks.signal_enqueue")
    fake_enqueue_module.enqueue_signal_engine_for_symbol = _fake_enqueue
    monkeypatch.setitem(sys.modules, "services.worker.tasks.signal_enqueue", fake_enqueue_module)

    active_a = StockMaster(symbol="AAA", is_active=True)
    active_b = StockMaster(symbol="BBB", is_active=True)
    inactive = StockMaster(symbol="ZZZ", is_active=False)
    client = TestClient(_app(_FakeDB({StockMaster: [active_a, active_b, inactive]})))

    response = client.post("/strategy/engine/trigger-all", json={})

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["batch_id"], str)
    assert payload["batch_id"]
    assert payload["symbols"] == 2
    assert payload["horizons"] == ["short", "medium", "long"]
    assert payload["variants"] == ["legacy", "expanded"]
    assert payload["total_jobs"] == 12
    assert len(calls) == 12
    assert all(triggered_by == "manual_global" for *_rest, triggered_by, _batch in calls)
    assert all(batch == payload["batch_id"] for *_rest, _triggered_by, batch in calls)


def test_signal_engine_global_batch_status_dedupes_latest_rows_and_counts_partial():
    now = dt.datetime(2026, 4, 22, tzinfo=dt.timezone.utc)
    batch_id = "batch-new"
    rows = [
        SignalEngineBatchJob(
            id=uuid.uuid4(),
            symbol="AAA",
            horizon="short",
            variant="legacy",
            job_type="signal_engine",
            triggered_by="manual_global",
            batch_id=batch_id,
            status="pending",
            created_at=now - dt.timedelta(minutes=5),
        ),
        SignalEngineBatchJob(
            id=uuid.uuid4(),
            symbol="AAA",
            horizon="short",
            variant="legacy",
            job_type="signal_engine",
            triggered_by="manual_global",
            batch_id=batch_id,
            status="succeeded",
            created_at=now,
        ),
        SignalEngineBatchJob(
            id=uuid.uuid4(),
            symbol="BBB",
            horizon="medium",
            variant="expanded",
            job_type="signal_engine",
            triggered_by="manual_global",
            batch_id=batch_id,
            status="partial",
            created_at=now - dt.timedelta(minutes=1),
        ),
        SignalEngineBatchJob(
            id=uuid.uuid4(),
            symbol="CCC",
            horizon="long",
            variant="expanded",
            job_type="signal_engine",
            triggered_by="manual_global",
            batch_id=batch_id,
            status="running",
            created_at=now - dt.timedelta(minutes=2),
        ),
        SignalEngineBatchJob(
            id=uuid.uuid4(),
            symbol="ZZZ",
            horizon="short",
            variant="expanded",
            job_type="signal_engine",
            triggered_by="manual_global",
            batch_id="batch-old",
            status="failed",
            created_at=now - dt.timedelta(days=1),
        ),
        SignalEngineBatchJob(
            id=uuid.uuid4(),
            symbol="DDD",
            horizon="short",
            variant="expanded",
            job_type="signal_backtest",
            triggered_by="manual_global",
            status="failed",
            created_at=now - dt.timedelta(minutes=3),
        ),
        SignalEngineBatchJob(
            id=uuid.uuid4(),
            symbol="EEE",
            horizon="short",
            variant="expanded",
            job_type="signal_engine",
            triggered_by="manual",
            status="failed",
            created_at=now - dt.timedelta(minutes=3),
        ),
    ]
    client = TestClient(_app(_FakeDB({SignalEngineBatchJob: rows})))

    response = client.get("/strategy/engine/batch-status-global")

    assert response.status_code == 200
    payload = response.json()
    assert payload["batch_id"] == batch_id
    assert payload["total"] == 3
    assert payload["succeeded"] == 1
    assert payload["partial"] == 1
    assert payload["running"] == 1
    assert payload["pending"] == 0
    assert payload["failed"] == 0


def test_signal_engine_global_batch_status_filters_by_batch_id():
    now = dt.datetime(2026, 4, 22, tzinfo=dt.timezone.utc)
    rows = [
        SignalEngineBatchJob(
            id=uuid.uuid4(),
            symbol="AAA",
            horizon="short",
            variant="legacy",
            job_type="signal_engine",
            triggered_by="manual_global",
            batch_id="batch-a",
            status="succeeded",
            created_at=now,
        ),
        SignalEngineBatchJob(
            id=uuid.uuid4(),
            symbol="AAA",
            horizon="short",
            variant="legacy",
            job_type="signal_engine",
            triggered_by="manual_global",
            batch_id="batch-b",
            status="failed",
            created_at=now,
        ),
    ]
    client = TestClient(_app(_FakeDB({SignalEngineBatchJob: rows})))

    response = client.get("/strategy/engine/batch-status-global?batch_id=batch-a")

    assert response.status_code == 200
    payload = response.json()
    assert payload["batch_id"] == "batch-a"
    assert payload["total"] == 1
    assert payload["succeeded"] == 1
    assert payload["failed"] == 0
