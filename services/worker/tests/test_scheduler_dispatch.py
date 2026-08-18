from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from math import ceil
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.quant_core.historical_portfolio import METHODOLOGY_VERSION
from core.quant_core.signal_engine.modes import ALL_SIGNAL_MODE_NAMES, signal_mode_storage_name
from services.api.app import models
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
        return SimpleNamespace(id=f"fundamentals-job-{len(self.calls)}")


def _pit_db():
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.HistoricalOpportunityMaterializationRun.__table__.create(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


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


def test_weekly_signal_history_dispatch_is_registered_on_score_history_queue() -> None:
    spec = get_schedule_spec("weekly_signal_history_dispatch")

    assert spec.kind == "signal_history_dispatch"
    assert spec.queue == "score_history"
    assert spec.cron == "30 23 * * sun"
    # Fires 30 minutes after weekly_signal_backtest_dispatch (23:00 UTC sun) and
    # well before weekly_signal_best_evidence_snapshot (01:30 UTC mon).
    assert spec.trigger() is not None


def test_dispatch_stale_wfo_enqueues_both_base_wfo_and_sr_independently(monkeypatch) -> None:
    monkeypatch.setattr(scheduler_dispatch, "list_signal_universe_symbols", lambda _db: ["AAA"])

    # Base WFO stale for weekly only; SR stale for monthly only — disjoint sets to
    # prove they're dispatched independently.
    monkeypatch.setattr(
        scheduler_dispatch,
        "iter_wfo_weekly_stale_tuples",
        lambda db, *, symbols: [("AAA", "weekly", "expanded_ta_simple")],
    )
    monkeypatch.setattr(
        scheduler_dispatch,
        "iter_sr_wfo_weekly_stale_tuples",
        lambda db, *, symbols: [("AAA", "monthly", "expanded_ta_simple")],
    )

    from services.worker.tasks import wfo_signal_batch

    wfo_calls: list[tuple] = []
    sr_calls: list[tuple] = []
    monkeypatch.setattr(
        wfo_signal_batch,
        "enqueue_wfo_full_for_symbol_horizon",
        lambda symbol, horizon, *, variant, triggered_by: wfo_calls.append((symbol, horizon, variant))
        or f"wfo-{symbol}-{horizon}",
    )
    monkeypatch.setattr(
        wfo_signal_batch,
        "enqueue_sr_wfo_for_symbol_horizon",
        lambda symbol, horizon, *, variant, triggered_by: sr_calls.append((symbol, horizon, variant))
        or f"sr-{symbol}-{horizon}",
    )

    result = scheduler_dispatch._dispatch_stale_wfo(object(), trigger_source="scheduled")

    assert wfo_calls == [("AAA", "weekly", "expanded_ta_simple")]
    assert sr_calls == [("AAA", "monthly", "expanded_ta_simple")]
    assert result["wfo_jobs"] == 1
    assert result["sr_jobs"] == 1
    assert result["enqueued_jobs"] == 2


def test_dispatch_pit_empty_store_seeds_three_years_in_chained_chunks(monkeypatch) -> None:
    db = _pit_db()
    queue = _CaptureQueue()
    today = date(2026, 7, 16)
    monkeypatch.setattr(scheduler_dispatch, "_now", lambda: datetime(2026, 7, 16, tzinfo=timezone.utc))
    monkeypatch.setattr(scheduler_dispatch, "_queue", lambda name: queue)
    monkeypatch.setattr(scheduler_dispatch, "_pit_resolved_universe", lambda db: ["AAA", "BBB"])

    result = scheduler_dispatch._dispatch_pit_opportunity_materialization(db)

    expected_chunks = ceil((scheduler_dispatch.PIT_SEED_LOOKBACK_DAYS + 1) / scheduler_dispatch.PIT_SEED_CHUNK_DAYS)
    assert result["mode"] == "seed_chunked"
    assert result["enqueued_jobs"] == expected_chunks
    assert result["window_start"] == (today - timedelta(days=scheduler_dispatch.PIT_SEED_LOOKBACK_DAYS)).isoformat()
    assert result["window_end"] == today.isoformat()
    rows = db.query(models.HistoricalOpportunityMaterializationRun).order_by(
        models.HistoricalOpportunityMaterializationRun.created_at.asc()
    ).all()
    windows = [(date.fromisoformat(row.config_json["start_date"]), date.fromisoformat(row.config_json["end_date"])) for row in rows]
    assert len(windows) == expected_chunks
    assert all(row.config_json["resolved_universe"] == ["AAA", "BBB"] for row in rows)
    assert windows[0][0] == today - timedelta(days=scheduler_dispatch.PIT_SEED_LOOKBACK_DAYS)
    assert windows[-1][1] == today
    for previous, current in zip(windows, windows[1:]):
        assert current[0] == previous[1] + timedelta(days=1)
    assert "depends_on" not in queue.calls[0][1]
    for index, (_args, kwargs) in enumerate(queue.calls[1:], start=1):
        assert kwargs["depends_on"].id == f"fundamentals-job-{index}"


def test_dispatch_pit_non_empty_store_extends_from_last_covered_end(monkeypatch) -> None:
    db = _pit_db()
    queue = _CaptureQueue()
    today = date(2026, 7, 16)
    covered_end = date(2026, 7, 10)
    db.add(models.HistoricalOpportunityMaterializationRun(
        status="succeeded", methodology_version=METHODOLOGY_VERSION,
        config_json={"start_date": "2025-01-01", "end_date": covered_end.isoformat(), "symbols": []},
        progress_json={"stage": "completed"}, coverage_json={}, completed_at=datetime.now(timezone.utc),
    ))
    db.commit()
    monkeypatch.setattr(scheduler_dispatch, "_now", lambda: datetime(2026, 7, 16, tzinfo=timezone.utc))
    monkeypatch.setattr(scheduler_dispatch, "_queue", lambda name: queue)
    monkeypatch.setattr(scheduler_dispatch, "_pit_resolved_universe", lambda db: ["AAA", "BBB"])

    result = scheduler_dispatch._dispatch_pit_opportunity_materialization(db)

    assert result["mode"] == "incremental"
    assert result["enqueued_jobs"] == 1
    assert result["window_start"] == "2026-07-03"
    assert result["window_end"] == today.isoformat()
    assert len(queue.calls) == 1
    assert "depends_on" not in queue.calls[0][1]
    queued = db.query(models.HistoricalOpportunityMaterializationRun).filter_by(status="queued").one()
    assert queued.config_json["start_date"] == "2026-07-03"
    assert queued.config_json["end_date"] == today.isoformat()
    assert queued.config_json["resolved_universe"] == ["AAA", "BBB"]


def test_dispatch_schedule_routes_signal_history_dispatch(monkeypatch) -> None:
    run_id = uuid.uuid4()
    fake_db = SimpleNamespace(close=lambda: None)
    finished: dict = {}
    calls: list = []

    monkeypatch.setattr(scheduler_dispatch, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(
        scheduler_dispatch,
        "_create_scheduler_run",
        lambda db, schedule_id, trigger_source: SimpleNamespace(id=run_id),
    )
    monkeypatch.setattr(
        scheduler_dispatch,
        "_dispatch_signal_history",
        lambda db: calls.append(db) or {"enqueued_jobs": 5, "triggered": 5, "job_ids": ["a", "b"]},
    )

    def record_finish(db, run, **kwargs):
        finished.update(kwargs)

    monkeypatch.setattr(scheduler_dispatch, "_finish_scheduler_run", record_finish)

    result = scheduler_dispatch.dispatch_schedule("weekly_signal_history_dispatch", trigger_source="manual")

    assert calls == [fake_db]
    assert result["status"] == "succeeded"
    assert result["schedule_id"] == "weekly_signal_history_dispatch"
    assert result["enqueued_jobs"] == 5
    assert finished["status"] == "succeeded"
    assert finished["meta_json"]["schedule_label"] == "Weekly signal history dispatch"
    assert finished["meta_json"]["queue"] == "score_history"


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
