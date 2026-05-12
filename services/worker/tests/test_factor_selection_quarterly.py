from __future__ import annotations

from services.worker.tasks import factor_selection_quarterly as quarterly_mod


class _FakeDB:
    def close(self):
        return None


def test_quarterly_factor_recalibration_uses_data_backed_universe(monkeypatch):
    fake_db = _FakeDB()
    enqueued: list[tuple[str, bool]] = []

    class _FakeQueue:
        def enqueue(self, fn, symbol: str, auto_enqueue: bool):
            enqueued.append((symbol, auto_enqueue))
            assert callable(fn)

    monkeypatch.setattr(quarterly_mod, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(quarterly_mod, "list_signal_universe_symbols", lambda _db: ["AAA", "VIX"])
    monkeypatch.setattr(quarterly_mod, "get_queue", lambda: _FakeQueue())

    result = quarterly_mod.run_quarterly_factor_recalibration()

    assert result == {"status": "success", "enqueued": 2}
    assert enqueued == [("AAA", True), ("VIX", True)]
