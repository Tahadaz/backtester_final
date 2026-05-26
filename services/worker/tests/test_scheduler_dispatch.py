from __future__ import annotations

import uuid
from types import SimpleNamespace

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


def test_dispatch_fundamental_refresh_enqueues_yfinance_universe(monkeypatch) -> None:
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
        "market_regions": ["us", "european", "asian"],
        "source": "yfinance",
    }
    assert queue.calls == [
        (
            ("services.worker.tasks.refresh_yfinance_fundamentals.refresh_yfinance_universe",),
            {
                "market_regions": ["us", "european", "asian"],
                "triggered_by": "scheduled",
                "batch_id": "batch-123",
                "job_timeout": 7200,
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
