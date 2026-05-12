from __future__ import annotations

import types
import sys
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.app.db import get_db
from services.api.app.models import WfoSignalSummary
from services.api.app.routers import wfo_signals as wfo_signals_router


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

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _FakeDB:
    def __init__(self, rows_by_model=None):
        self.rows_by_model = {**(rows_by_model or {})}

    def add(self, row):
        self.rows_by_model.setdefault(type(row), [])
        if row not in self.rows_by_model[type(row)]:
            self.rows_by_model[type(row)].append(row)

    def query(self, model):
        return _FakeQuery(self.rows_by_model.get(model, []))

    def execute(self, stmt):
        self.last_execute = stmt
        return None

    def commit(self):
        return None

    def rollback(self):
        return None


def _app(db) -> FastAPI:
    app = FastAPI()
    app.include_router(wfo_signals_router.router)

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    return app


def test_get_wfo_config_defaults_to_single_representative():
    payload = wfo_signals_router.get_wfo_config()
    assert payload["scoring"]["max_representatives"] == 1


def test_trigger_wfo_computation_passes_max_reps_override(monkeypatch):
    fake_db = _FakeDB({WfoSignalSummary: []})
    captured = {}

    class _FakeRedis:
        @staticmethod
        def from_url(*_args, **_kwargs):
            return object()

    class _FakeQueue:
        def __init__(self, _name, connection=None):
            self.connection = connection

        def enqueue(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

            class _Job:
                id = "job-xyz"

            return _Job()

    monkeypatch.setitem(sys.modules, "redis", types.SimpleNamespace(Redis=_FakeRedis))
    monkeypatch.setitem(sys.modules, "rq", types.SimpleNamespace(Queue=_FakeQueue))

    body = wfo_signals_router.WfoTriggerRequest(
        symbol="AAA",
        horizon="weekly",
        variant="expanded",
        max_reps=3,
    )
    response = wfo_signals_router.trigger_wfo_computation(body, db=fake_db)

    assert response.job_id == "job-xyz"
    assert len(response.triggered) == 4
    assert captured["args"][0] == "services.worker.tasks.wfo_signal_batch.enqueue_wfo_for_symbol_horizon"
    assert captured["args"][1] == "AAA"
    assert captured["args"][2] == "weekly"
    assert captured["args"][3]["max_reps"] == 3
    assert captured["args"][4] == "expanded"

    rows = fake_db.rows_by_model[WfoSignalSummary]
    assert len(rows) == 4
    assert all(row.status == "running" for row in rows)


def test_trigger_all_wfo_enqueues_data_backed_symbols(monkeypatch):
    fake_db = _FakeDB({WfoSignalSummary: []})
    enqueued: list[tuple[tuple, dict]] = []

    class _FakeRedis:
        @staticmethod
        def from_url(*_args, **_kwargs):
            return object()

    class _FakeQueue:
        def __init__(self, _name, connection=None):
            self.connection = connection

        def enqueue(self, *args, **kwargs):
            enqueued.append((args, kwargs))
            return types.SimpleNamespace(id=f"job-{len(enqueued)}")

    monkeypatch.setattr(wfo_signals_router, "list_signal_universe_symbols", lambda _db: ["AAA", "VIX"])
    monkeypatch.setitem(sys.modules, "redis", types.SimpleNamespace(Redis=_FakeRedis))
    monkeypatch.setitem(sys.modules, "rq", types.SimpleNamespace(Queue=_FakeQueue))

    body = wfo_signals_router.WfoTriggerAllRequest(variants=["expanded"])
    response = wfo_signals_router.trigger_all_wfo(body, db=fake_db)

    assert response.symbols == 2
    assert response.horizons == ["weekly", "monthly", "quarterly"]
    assert response.variants == ["expanded_ta_simple"]
    assert response.total_jobs == 6
    assert len(enqueued) == 6
    assert {call[0][1] for call in enqueued} == {"AAA", "VIX"}


def test_get_wfo_detail_honors_variant_selection():
    legacy_row = WfoSignalSummary(
        symbol="AAA",
        category="tendance",
        horizon="weekly",
        variant="legacy",
        status="succeeded",
        score_pct=12.0,
        signal_label="Legacy",
    )
    expanded_row = WfoSignalSummary(
        symbol="AAA",
        category="tendance",
        horizon="weekly",
        variant="expanded",
        status="succeeded",
        score_pct=48.0,
        signal_label="Expanded",
    )
    fake_db = _FakeDB({WfoSignalSummary: [legacy_row, expanded_row]})

    legacy = wfo_signals_router.get_wfo_detail(
        symbol="AAA",
        horizon="weekly",
        category="tendance",
        variant="legacy",
        db=fake_db,
    )
    expanded = wfo_signals_router.get_wfo_detail(
        symbol="AAA",
        horizon="weekly",
        category="tendance",
        variant="expanded",
        db=fake_db,
    )

    assert legacy.signal_label == "Legacy"
    assert legacy.score_pct == 12.0
    assert expanded.signal_label == "Expanded"
    assert expanded.score_pct == 48.0


def test_wfo_summary_rejects_legacy_horizon_query():
    client = TestClient(_app(_FakeDB({WfoSignalSummary: []})))
    response = client.get("/strategy/wfo/summary?symbol=AAA&horizon=short&variant=expanded")
    assert response.status_code == 422
