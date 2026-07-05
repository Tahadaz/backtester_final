from __future__ import annotations

import uuid

import pytest

from services.worker.tasks import fundamental_cross_section as task_mod


class _FakeSchedulerRun:
    def __init__(self, run_id: uuid.UUID) -> None:
        self.id = run_id
        self.status = "running"
        self.finished_at = None
        self.error_message = None
        self.meta_json = {"existing": True}


class _FakeDB:
    def __init__(self, row: _FakeSchedulerRun | None = None) -> None:
        self.row = row
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def get(self, _model, run_id):
        if self.row is not None and self.row.id == run_id:
            return self.row
        return None

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_recompute_fundamental_cross_section_marks_scheduler_success(monkeypatch):
    run_id = uuid.uuid4()
    row = _FakeSchedulerRun(run_id)
    db = _FakeDB(row)

    monkeypatch.setattr(task_mod, "SessionLocal", lambda: db)
    monkeypatch.setattr(task_mod, "recompute_and_persist_sfc", lambda _db, as_of_date: {"persisted": 3, "as_of_date": as_of_date.isoformat()})

    result = task_mod.recompute_fundamental_cross_section(as_of_date="2026-07-05", triggered_by="test", batch_id=str(run_id))

    assert result["status"] == "succeeded"
    assert row.status == "succeeded"
    assert row.error_message is None
    assert row.meta_json["persisted"] == 3
    assert row.finished_at is not None


def test_recompute_fundamental_cross_section_marks_scheduler_failure_and_raises(monkeypatch):
    run_id = uuid.uuid4()
    row = _FakeSchedulerRun(run_id)
    db = _FakeDB(row)

    def _fail(_db, as_of_date):
        raise RuntimeError("tz-aware crash")

    monkeypatch.setattr(task_mod, "SessionLocal", lambda: db)
    monkeypatch.setattr(task_mod, "recompute_and_persist_sfc", _fail)

    with pytest.raises(RuntimeError, match="tz-aware crash"):
        task_mod.recompute_fundamental_cross_section(as_of_date="2026-07-05", triggered_by="test", batch_id=str(run_id))

    assert row.status == "failed"
    assert row.error_message == "tz-aware crash"
    assert row.meta_json["status"] == "failed"
    assert row.finished_at is not None


class _FakeBacktestDB:
    def __init__(self, job):
        self.job = job
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def get(self, _model, run_id):
        if self.job is not None and self.job.id == run_id:
            return self.job
        return None

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


def test_recompute_sfc_portfolio_backtest_updates_batch_job(monkeypatch):
    job_id = uuid.uuid4()
    job = type(
        "JobRow",
        (),
        {
            "id": job_id,
            "status": "pending",
            "started_at": None,
            "finished_at": None,
            "completed_units": 0,
            "failed_units": 0,
            "error_message": None,
        },
    )()
    db = _FakeBacktestDB(job)

    monkeypatch.setattr(task_mod, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        task_mod,
        "recompute_and_persist_sfc_backtest",
        lambda _db, params: {"snapshot_id": 7, "params": params},
    )

    result = task_mod.recompute_sfc_portfolio_backtest(
        params={"rebalance": "monthly", "cost_bps": 33.0},
        triggered_by="test",
        batch_id=str(job_id),
        job_row_id=str(job_id),
    )

    assert result["status"] == "succeeded"
    assert result["snapshot_id"] == 7
    assert job.status == "succeeded"
    assert job.completed_units == 1
    assert job.failed_units == 0
    assert job.started_at is not None
    assert job.finished_at is not None
