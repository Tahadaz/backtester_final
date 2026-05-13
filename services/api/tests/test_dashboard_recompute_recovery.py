from __future__ import annotations

from types import SimpleNamespace


def test_dashboard_symbols_targets_masi_equities(monkeypatch) -> None:
    from services.api.scripts import recover_dashboard_recompute as recovery

    monkeypatch.setattr(
        recovery,
        "list_signal_universe",
        lambda _db: [
            SimpleNamespace(symbol="AAA", asset_class="equity", asset_type="equity", market_region="masi"),
            SimpleNamespace(symbol="SP500", asset_class="index", asset_type="equity", market_region="us"),
            SimpleNamespace(symbol="BTC", asset_class="equity", asset_type="crypto", market_region=None),
        ],
    )

    assert recovery.dashboard_symbols(object()) == ["AAA"]


def test_missing_or_failed_wfo_selects_only_incomplete_rows(monkeypatch) -> None:
    from services.api.scripts import recover_dashboard_recompute as recovery

    monkeypatch.setattr(recovery, "HORIZONS", ("weekly",))
    monkeypatch.setattr(recovery, "VARIANTS", ("expanded_ta_simple",))

    lookup = {
        ("AAA", "weekly", "expanded_ta_simple"): SimpleNamespace(status="succeeded"),
        ("BBB", "weekly", "expanded_ta_simple"): SimpleNamespace(status="failed"),
        ("CCC", "weekly", "expanded_ta_simple"): SimpleNamespace(status="No_Signal"),
    }

    class Query:
        def __init__(self):
            self.filters = {}

        def filter_by(self, **kwargs):
            self.filters.update(kwargs)
            return self

        def first(self):
            key = (
                self.filters["symbol"],
                self.filters["horizon"],
                self.filters["variant"],
            )
            return lookup.get(key)

    class FakeDb:
        def query(self, _model):
            return Query()

    rows = recovery.missing_or_failed_wfo(FakeDb(), ["AAA", "BBB", "CCC", "DDD"])

    assert rows == [
        ("BBB", "weekly", "expanded_ta_simple"),
        ("DDD", "weekly", "expanded_ta_simple"),
    ]
    assert recovery.missing_or_failed_wfo(FakeDb(), ["AAA"], scope="all") == [
        ("AAA", "weekly", "expanded_ta_simple")
    ]


def test_enqueue_full_wfo_jobs_uses_full_entrypoint() -> None:
    from services.api.scripts import recover_dashboard_recompute as recovery

    class FakeQueue:
        def __init__(self):
            self.calls = []

        def enqueue(self, target, *args, **kwargs):
            self.calls.append((target, args, kwargs))
            return SimpleNamespace(id=f"job-{len(self.calls)}")

    queue = FakeQueue()
    job_ids = recovery.enqueue_full_wfo_jobs(
        queue,
        [("AAA", "weekly", "expanded_ta_simple")],
        dry_run=False,
    )

    assert job_ids == ["job-1"]
    target, args, kwargs = queue.calls[0]
    assert target == "services.worker.tasks.wfo_signal_batch.enqueue_wfo_for_symbol_horizon"
    assert args == ("AAA", "weekly", None, "expanded_ta_simple")
    assert "refresh_wfo_for_symbol_horizon" not in target
    assert kwargs["job_timeout"] == recovery.JOB_TIMEOUT_SECONDS
    assert kwargs["meta"] == {"triggered_by": "dashboard_recompute_recovery"}


def test_enqueue_full_wfo_jobs_dry_run_does_not_enqueue() -> None:
    from services.api.scripts import recover_dashboard_recompute as recovery

    class FakeQueue:
        def enqueue(self, *_args, **_kwargs):
            raise AssertionError("dry-run should not enqueue")

    assert recovery.enqueue_full_wfo_jobs(
        FakeQueue(),
        [("AAA", "weekly", "expanded_ta_simple")],
        dry_run=True,
    ) == []
