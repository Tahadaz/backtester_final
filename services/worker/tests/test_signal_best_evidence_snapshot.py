from __future__ import annotations

from fastapi import HTTPException

from services.api.app.routers import strategy_signals
from services.worker.tasks import signal_best_evidence_snapshot as snapshot


class _FakeSession:
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


def test_missing_wfo_evidence_is_skipped_without_exception_log(monkeypatch) -> None:
    db = _FakeSession()
    unavailable: list[dict] = []
    exception_logs: list[tuple] = []

    monkeypatch.setattr(snapshot, "SessionLocal", lambda: db)
    monkeypatch.setattr(snapshot, "_select_wfo_best_variant", lambda *_args: None)
    monkeypatch.setattr(
        strategy_signals,
        "_build_signal_evidence_payload",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            HTTPException(status_code=404, detail="No WFO signal evidence for AGM/weekly.")
        ),
    )
    monkeypatch.setattr(
        snapshot,
        "_mark_snapshot_unavailable",
        lambda _db, **kwargs: unavailable.append(kwargs),
    )
    monkeypatch.setattr(snapshot.logger, "exception", lambda *args, **kwargs: exception_logs.append((args, kwargs)))

    result = snapshot.refresh_signal_best_evidence_for_symbol("agm", "weekly")

    assert result == {
        "symbol": "AGM",
        "horizon": "weekly",
        "status": "skipped",
        "reason": "No WFO signal evidence for AGM/weekly.",
    }
    assert unavailable == [
        {
            "symbol": "AGM",
            "horizon": "weekly",
            "cooldown_bars": 0,
            "reason": "No WFO signal evidence for AGM/weekly.",
        }
    ]
    assert exception_logs == []
    assert db.rollbacks == 1
    assert db.commits == 1
    assert db.closed


def test_non_404_http_error_remains_a_failure(monkeypatch) -> None:
    db = _FakeSession()
    failed: list[dict] = []
    exception_logs: list[tuple] = []

    monkeypatch.setattr(snapshot, "SessionLocal", lambda: db)
    monkeypatch.setattr(snapshot, "_select_wfo_best_variant", lambda *_args: None)
    monkeypatch.setattr(
        strategy_signals,
        "_build_signal_evidence_payload",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            HTTPException(status_code=422, detail="invalid evidence request")
        ),
    )
    monkeypatch.setattr(snapshot, "_mark_snapshot_failed", lambda _db, **kwargs: failed.append(kwargs))
    monkeypatch.setattr(snapshot.logger, "exception", lambda *args, **kwargs: exception_logs.append((args, kwargs)))

    result = snapshot.refresh_signal_best_evidence_for_symbol("AGM", "weekly")

    assert result["status"] == "failed"
    assert "invalid evidence request" in result["error"]
    assert failed[0]["symbol"] == "AGM"
    assert len(exception_logs) == 1
    assert db.rollbacks == 1
    assert db.commits == 1
    assert db.closed


def test_failure_to_persist_unavailable_status_is_a_real_failure(monkeypatch) -> None:
    db = _FakeSession()
    exception_logs: list[tuple] = []

    monkeypatch.setattr(snapshot, "SessionLocal", lambda: db)
    monkeypatch.setattr(snapshot, "_select_wfo_best_variant", lambda *_args: None)
    monkeypatch.setattr(
        strategy_signals,
        "_build_signal_evidence_payload",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            HTTPException(status_code=404, detail="No WFO signal evidence for AGM/weekly.")
        ),
    )
    monkeypatch.setattr(
        snapshot,
        "_mark_snapshot_unavailable",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("database unavailable")),
    )
    monkeypatch.setattr(snapshot.logger, "exception", lambda *args, **kwargs: exception_logs.append((args, kwargs)))

    result = snapshot.refresh_signal_best_evidence_for_symbol("AGM", "weekly")

    assert result["status"] == "failed"
    assert "database unavailable" in result["error"]
    assert len(exception_logs) == 1
    assert db.rollbacks == 2
    assert db.commits == 0
    assert db.closed


def test_batch_counts_skips_separately_from_failures(monkeypatch) -> None:
    db = _FakeSession()
    statuses = {
        "weekly": "succeeded",
        "monthly": "skipped",
        "quarterly": "failed",
    }

    monkeypatch.setattr(snapshot, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        snapshot,
        "refresh_signal_best_evidence_for_symbol",
        lambda symbol, horizon, cooldown: {
            "symbol": symbol,
            "horizon": horizon,
            "status": statuses[horizon],
        },
    )

    result = snapshot.refresh_signal_best_evidence_snapshot(symbol="AGM")

    assert result["status"] == "partial"
    assert result["total"] == 3
    assert result["succeeded"] == 1
    assert result["skipped"] == 1
    assert result["failed"] == 1


def test_all_coverage_gaps_complete_batch_successfully(monkeypatch) -> None:
    db = _FakeSession()
    monkeypatch.setattr(snapshot, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        snapshot,
        "refresh_signal_best_evidence_for_symbol",
        lambda symbol, horizon, cooldown: {
            "symbol": symbol,
            "horizon": horizon,
            "status": "skipped",
        },
    )

    result = snapshot.refresh_signal_best_evidence_snapshot(symbol="AGM")

    assert result["status"] == "succeeded"
    assert result["succeeded"] == 0
    assert result["skipped"] == 3
    assert result["failed"] == 0
