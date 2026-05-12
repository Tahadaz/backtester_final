from __future__ import annotations

import datetime as dt

from services.api.app.models import SignalEngineGlobalResult, StockMaster
from core.quant_core.signal_engine.modes import ALL_SIGNAL_MODE_NAMES
from services.worker.tasks import signal_engine_batch as signal_engine_batch_mod


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

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeDB:
    def __init__(self, rows_by_model=None):
        self.rows_by_model = {**(rows_by_model or {})}

    def query(self, model):
        return _FakeQuery(self.rows_by_model.get(model, []))

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None


def test_compute_signal_engine_propagates_triggered_by_from_rq_meta(monkeypatch):
    fake_db = _FakeDB()
    captured: dict[str, str | None] = {}

    class _JobRow:
        pass

    def _fake_upsert_batch_job(
        _db,
        _symbol,
        _horizon,
        _variant,
        *,
        job_type,
        status,
        rq_job_id=None,
        triggered_by=None,
        batch_id=None,
        total_units=None,
        completed_units=0,
        failed_units=0,
    ):
        captured["triggered_by"] = triggered_by
        captured["batch_id"] = batch_id
        row = _JobRow()
        row.job_type = job_type
        row.status = status
        row.rq_job_id = rq_job_id
        row.total_units = total_units
        row.completed_units = completed_units
        row.failed_units = failed_units
        return row

    def _fake_full_rebuild(*_args, **_kwargs):
        return {
            "mode": "full_rebuild",
            "status": "failed",
            "completed": 0,
            "failed": 1,
            "first_error": "No OHLCV data",
        }

    monkeypatch.setattr(signal_engine_batch_mod, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(signal_engine_batch_mod, "_resolve_triggered_by_from_rq_meta", lambda: "manual_global")
    monkeypatch.setattr(signal_engine_batch_mod, "_resolve_batch_id_from_rq_meta", lambda: "batch-123")
    monkeypatch.setattr(signal_engine_batch_mod, "_upsert_batch_job", _fake_upsert_batch_job)
    monkeypatch.setattr(signal_engine_batch_mod, "full_rebuild_from_pipeline", _fake_full_rebuild)

    result = signal_engine_batch_mod.compute_signal_engine_for_symbol("AAA", "weekly", "expanded")

    assert result["status"] == "failed"
    assert captured["triggered_by"] == "manual_global"
    assert captured["batch_id"] == "batch-123"


def test_run_signal_engine_batch_only_processes_weekly_stale_tuples(monkeypatch):
    now = dt.datetime(2026, 4, 25, 19, 0, tzinfo=dt.timezone.utc)
    fake_db = _FakeDB(
        {
            StockMaster: [StockMaster(symbol="AAA", is_active=True)],
            SignalEngineGlobalResult: [
                SignalEngineGlobalResult(
                    symbol="AAA",
                    horizon=horizon,
                    variant=variant,
                    computed_at=now - dt.timedelta(
                        days=8 if (horizon, variant) == ("weekly", "legacy_ta_simple") else 2
                    ),
                )
                for horizon in ("weekly", "monthly", "quarterly")
                for variant in ALL_SIGNAL_MODE_NAMES
            ],
        }
    )
    calls: list[tuple[str, str, str]] = []

    monkeypatch.setattr(signal_engine_batch_mod, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(
        signal_engine_batch_mod,
        "compute_signal_engine_for_symbol",
        lambda symbol, horizon, variant="expanded": calls.append((symbol, horizon, variant)) or {
            "status": "succeeded"
        },
    )

    result = signal_engine_batch_mod.run_signal_engine_batch(now=now)

    assert result == {"total": 1, "succeeded": 1, "failed": 0}
    assert calls == [("AAA", "weekly", "legacy_ta_simple")]


def test_compute_signal_engine_rejects_legacy_horizon_with_clear_error():
    result = signal_engine_batch_mod.compute_signal_engine_for_symbol("AAA", "short", "expanded")

    assert result["status"] == "failed"
    assert "canonical horizon" in str(result["error"])
    assert result["horizon"] == "short"
