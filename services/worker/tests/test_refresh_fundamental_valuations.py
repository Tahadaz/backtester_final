from __future__ import annotations

import uuid

import services.worker.tasks.refresh_fundamental_valuations as task_mod


class _FakeDB:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


def test_worker_refreshes_stale_symbol_and_commits(monkeypatch) -> None:
    db = _FakeDB()
    import_id = uuid.uuid4()
    snapshot = type("Snapshot", (), {"import_id": import_id})()
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(task_mod, "SessionLocal", lambda: db)
    monkeypatch.setattr(task_mod, "latest_snapshot_rows_by_symbol", lambda _db, symbols: {symbols[0]: snapshot})
    monkeypatch.setattr(task_mod, "make_bulk_overrides_loader", lambda _db, symbols: (lambda _symbol, _scenario: None))

    def fake_recompute(_db, **kwargs):
        calls.append(kwargs)
        return [object(), object(), object()]

    monkeypatch.setattr(task_mod, "recompute_symbol_valuations_all_scenarios", fake_recompute)

    result = task_mod.refresh_fundamental_valuations(["aaa", "AAA"])

    assert result["refreshed"] == ["AAA"]
    assert result["valuation_count"] == 3
    assert result["failures"] == []
    assert db.commits == 1
    assert db.rollbacks == 0
    assert db.closed is True
    assert len(calls) == 1
    assert calls[0]["import_id"] == import_id
    assert calls[0]["symbol"] == "AAA"
    assert calls[0]["scenarios"] == task_mod.VALUATION_SCENARIOS
    assert callable(calls[0]["overrides_loader"])
    assert "include_sensitivity_grids" not in calls[0]
