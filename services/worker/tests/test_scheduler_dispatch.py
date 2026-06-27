from __future__ import annotations

import uuid
from types import SimpleNamespace

from core.quant_core.signal_engine.modes import ALL_SIGNAL_MODE_NAMES, signal_mode_storage_name
from services.api.app.services.scheduler_registry import get_schedule_spec
from services.worker.tasks import scheduler_dispatch


class _FakeQuery:
    def __init__(self, count: int):
        self._count = count

    def filter(self, *args):
        return self

    def count(self) -> int:
        return self._count


class _FakeDB:
    def __init__(self, count: int = 0):
        self.query_count = count

    def query(self, model):
        return _FakeQuery(self.query_count)


class _CaptureQueue:
    def __init__(self):
        self.calls: list[tuple[tuple, dict]] = []

    def enqueue(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return SimpleNamespace(id="fundamentals-job-1")


def test_weekly_fundamental_refresh_is_registered_on_market_refresh_queue() -> None:
    spec = get_schedule_spec("weekly_fundamental_refresh")

    assert spec.kind == "fundamental_refresh"
    assert spec.queue == "market_refresh"
    assert spec.cron == "0 20 * * sat"


def test_weekly_best_evidence_snapshot_is_registered_on_signal_backtest_queue() -> None:
    spec = get_schedule_spec("weekly_signal_best_evidence_snapshot")

    assert spec.kind == "signal_best_evidence_snapshot"
    assert spec.queue == "signal_backtest"


def test_dispatch_signal_backtests_enqueues_all_signal_modes(monkeypatch) -> None:
    calls: list[tuple[str, str, str, str]] = []
    from services.worker.tasks import signal_backtest_batch

    monkeypatch.setattr(scheduler_dispatch, "list_signal_universe_symbols", lambda _db: ["AAA"])
    monkeypatch.setattr(
        signal_backtest_batch,
        "enqueue_signal_backtest_for_symbol",
        lambda symbol, horizon, *, variant, triggered_by: calls.append((symbol, horizon, variant, triggered_by))
        or f"{symbol}-{horizon}-{variant}",
    )

    result = scheduler_dispatch._dispatch_signal_backtests(object(), trigger_source="scheduled")

    expected_variants = [signal_mode_storage_name(variant) for variant in ALL_SIGNAL_MODE_NAMES]
    assert result["enqueued_jobs"] == 3 * len(expected_variants)
    assert {call[2] for call in calls} == set(expected_variants)
    assert {call[1] for call in calls} == {"weekly", "monthly", "quarterly"}


def test_dispatch_fundamental_refresh_enqueues_stockanalysis_missing_only(monkeypatch) -> None:
    queue = _CaptureQueue()
    monkeypatch.setattr(scheduler_dispatch, "_queue", lambda name: queue)

    result = scheduler_dispatch._dispatch_fundamental_refresh(
        _FakeDB(count=12),
        trigger_source="scheduled",
        batch_id="batch-123",
    )

    assert result == {
        "enqueued_jobs": 1,
        "rq_job_id": "fundamentals-job-1",
        "symbols_total": 12,
        "market_region": "masi",
        "source": "stockanalysis",
    }
    assert queue.calls == [
        (
            ("services.worker.tasks.refresh_stockanalysis_fundamentals.refresh_stockanalysis_universe",),
            {
                "symbols": None,
                "missing_only": True,
                "triggered_by": "scheduled",
                "batch_id": "batch-123",
                "job_timeout": 14400,
            },
        )
    ]


def test_dispatch_fundamental_refresh_skips_when_no_active_symbols(monkeypatch) -> None:
    queue = _CaptureQueue()
    monkeypatch.setattr(scheduler_dispatch, "_queue", lambda name: queue)

    result = scheduler_dispatch._dispatch_fundamental_refresh(
        _FakeDB(count=0),
        trigger_source="scheduled",
        batch_id="batch-123",
    )

    assert result["enqueued_jobs"] == 0
    assert result["reason"] == "no_active_fundamental_symbols"
    assert queue.calls == []


def test_dispatch_schedule_routes_weekly_fundamental_refresh(monkeypatch) -> None:
    run_id = uuid.uuid4()
    fake_db = SimpleNamespace(close=lambda: None)
    finished: dict = {}

    monkeypatch.setattr(scheduler_dispatch, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(
        scheduler_dispatch,
        "_create_scheduler_run",
        lambda db, schedule_id, trigger_source: SimpleNamespace(id=run_id),
    )
    monkeypatch.setattr(
        scheduler_dispatch,
        "_dispatch_fundamental_refresh",
        lambda db, *, trigger_source, batch_id: {
            "enqueued_jobs": 1,
            "rq_job_id": "fundamentals-job-1",
            "batch_id": batch_id,
            "trigger_source": trigger_source,
        },
    )

    def record_finish(db, run, **kwargs):
        finished.update(kwargs)

    monkeypatch.setattr(scheduler_dispatch, "_finish_scheduler_run", record_finish)

    result = scheduler_dispatch.dispatch_schedule("weekly_fundamental_refresh", trigger_source="manual")

    assert result["status"] == "succeeded"
    assert result["schedule_id"] == "weekly_fundamental_refresh"
    assert result["enqueued_jobs"] == 1
    assert result["batch_id"] == str(run_id)
    assert result["trigger_source"] == "manual"
    assert finished["status"] == "succeeded"
    assert finished["meta_json"]["schedule_label"] == "Weekly fundamental refresh"
    assert finished["meta_json"]["queue"] == "market_refresh"
