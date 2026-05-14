from __future__ import annotations

import importlib
import datetime as dt
from types import SimpleNamespace

from services.api.app.models import SignalEngineGlobalResult, WfoGlobalSignal
from core.quant_core.signal_engine.modes import ALL_SIGNAL_MODE_NAMES
from services.worker.tasks import signal_engine_batch as signal_engine_batch_mod
from services.worker.tasks import wfo_signal_batch as wfo_signal_batch_mod

refresh_market_data_mod = importlib.import_module("services.worker.tasks.refresh_market_data")


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

    def query(self, model):
        return _FakeQuery(self.rows_by_model.get(model, []))


class _CaptureDB:
    def __init__(self):
        self.executed = []
        self.commits = 0

    def execute(self, statement, params=None):
        self.executed.append((str(statement), params or {}))

    def commit(self):
        self.commits += 1


def _engine_global_rows(symbol: str, *, stale_target: tuple[str, str] | None = None):
    now = dt.datetime(2026, 4, 24, 19, 0, tzinfo=dt.timezone.utc)
    rows = []
    for horizon in ("weekly", "monthly", "quarterly"):
        for variant in ALL_SIGNAL_MODE_NAMES:
            computed_at = now - dt.timedelta(days=8 if stale_target == (horizon, variant) else 2)
            rows.append(
                SignalEngineGlobalResult(
                    symbol=symbol,
                    horizon=horizon,
                    variant=variant,
                    computed_at=computed_at,
                )
            )
    return rows


def _wfo_global_rows(symbol: str, *, stale_target: tuple[str, str] | None = None):
    now = dt.datetime(2026, 4, 24, 19, 0, tzinfo=dt.timezone.utc)
    rows = []
    for horizon in ("weekly", "monthly", "quarterly"):
        for variant in ALL_SIGNAL_MODE_NAMES:
            computed_at = now - dt.timedelta(days=8 if stale_target == (horizon, variant) else 2)
            rows.append(
                WfoGlobalSignal(
                    symbol=symbol,
                    horizon=horizon,
                    variant=variant,
                    computed_at=computed_at,
                )
            )
    return rows


def test_enqueue_signal_layers_after_refresh_enqueues_engine_and_wfo_for_all_horizons_and_variants(monkeypatch):
    engine_calls: list[tuple[str, str, str, str]] = []
    wfo_calls: list[tuple[str, str, str, str]] = []

    def record_engine(symbol, horizon, *, variant, triggered_by):
        engine_calls.append((symbol, horizon, variant, triggered_by))
        return f"engine-{len(engine_calls)}"

    def record_wfo(symbol, horizon, *, variant, triggered_by):
        wfo_calls.append((symbol, horizon, variant, triggered_by))
        return f"wfo-{len(wfo_calls)}"

    monkeypatch.setattr(refresh_market_data_mod, "_SIGNAL_ENGINE_REFRESH_ON_MARKET_REFRESH", True)
    monkeypatch.setattr(
        signal_engine_batch_mod,
        "enqueue_signal_engine_refresh_for_symbol",
        record_engine,
    )
    monkeypatch.setattr(
        wfo_signal_batch_mod,
        "enqueue_wfo_refresh_for_symbol_horizon",
        record_wfo,
    )

    job_ids = refresh_market_data_mod._enqueue_signal_layers_after_refresh("IAM")

    expected = {
        ("IAM", horizon, variant, "market_refresh")
        for horizon in ("weekly", "monthly", "quarterly")
        for variant in ALL_SIGNAL_MODE_NAMES
    }
    assert set(engine_calls) == expected
    assert set(wfo_calls) == expected
    assert len(job_ids) == len(engine_calls) + len(wfo_calls)
    assert job_ids[:2] == ["engine-1", "wfo-1"]


def test_enqueue_signal_layers_after_refresh_friday_enqueues_full_recompute_only_for_weekly_stale(monkeypatch):
    engine_refresh_calls: list[tuple[str, str, str, str]] = []
    wfo_refresh_calls: list[tuple[str, str, str, str]] = []
    engine_full_calls: list[tuple[str, str, str, str]] = []
    wfo_full_calls: list[tuple[str, str, str, str]] = []
    fake_db = _FakeDB(
        {
            SignalEngineGlobalResult: _engine_global_rows("IAM", stale_target=("weekly", "legacy_ta_simple")),
            WfoGlobalSignal: _wfo_global_rows("IAM", stale_target=("monthly", "expanded_ta_simple")),
        }
    )

    monkeypatch.setattr(refresh_market_data_mod, "_SIGNAL_ENGINE_REFRESH_ON_MARKET_REFRESH", True)
    monkeypatch.setattr(
        signal_engine_batch_mod,
        "enqueue_signal_engine_refresh_for_symbol",
        lambda symbol, horizon, *, variant, triggered_by: (
            engine_refresh_calls.append((symbol, horizon, variant, triggered_by))
            or f"engine-refresh-{len(engine_refresh_calls)}"
        ),
    )
    monkeypatch.setattr(
        signal_engine_batch_mod,
        "enqueue_signal_engine_for_symbol",
        lambda symbol, horizon, variant="expanded", triggered_by="manual", batch_id=None: (
            engine_full_calls.append((symbol, horizon, variant, triggered_by))
            or f"engine-full-{len(engine_full_calls)}"
        ),
    )
    monkeypatch.setattr(
        wfo_signal_batch_mod,
        "enqueue_wfo_refresh_for_symbol_horizon",
        lambda symbol, horizon, *, variant, triggered_by: (
            wfo_refresh_calls.append((symbol, horizon, variant, triggered_by))
            or f"wfo-refresh-{len(wfo_refresh_calls)}"
        ),
    )
    monkeypatch.setattr(
        wfo_signal_batch_mod,
        "enqueue_wfo_full_for_symbol_horizon",
        lambda symbol, horizon, *, variant="expanded", overrides=None, triggered_by="manual": (
            wfo_full_calls.append((symbol, horizon, variant, triggered_by))
            or f"wfo-full-{len(wfo_full_calls)}"
        ),
    )

    job_ids = refresh_market_data_mod._enqueue_signal_layers_after_refresh(
        "IAM",
        db=fake_db,
        now=dt.datetime(2026, 4, 24, 19, 0, tzinfo=dt.timezone.utc),
    )

    assert len(engine_refresh_calls) == 24
    assert len(wfo_refresh_calls) == 24
    assert engine_full_calls == [("IAM", "weekly", "legacy_ta_simple", "weekly_market_refresh")]
    assert wfo_full_calls == [("IAM", "monthly", "expanded_ta_simple", "weekly_market_refresh")]
    assert len(job_ids) == 50


def test_enqueue_signal_layers_after_refresh_non_friday_skips_weekly_full_recompute(monkeypatch):
    engine_full_calls: list[tuple[str, str, str, str]] = []
    wfo_full_calls: list[tuple[str, str, str, str]] = []
    fake_db = _FakeDB(
        {
            SignalEngineGlobalResult: _engine_global_rows("IAM", stale_target=("weekly", "legacy_ta_simple")),
            WfoGlobalSignal: _wfo_global_rows("IAM", stale_target=("monthly", "expanded_ta_simple")),
        }
    )

    monkeypatch.setattr(refresh_market_data_mod, "_SIGNAL_ENGINE_REFRESH_ON_MARKET_REFRESH", False)
    monkeypatch.setattr(
        wfo_signal_batch_mod,
        "enqueue_wfo_refresh_for_symbol_horizon",
        lambda symbol, horizon, *, variant, triggered_by: f"wfo-refresh-{symbol}-{horizon}-{variant}",
    )
    monkeypatch.setattr(
        signal_engine_batch_mod,
        "enqueue_signal_engine_for_symbol",
        lambda symbol, horizon, variant="expanded", triggered_by="manual", batch_id=None: engine_full_calls.append(
            (symbol, horizon, variant, triggered_by)
        ),
    )
    monkeypatch.setattr(
        wfo_signal_batch_mod,
        "enqueue_wfo_full_for_symbol_horizon",
        lambda symbol, horizon, *, variant="expanded", overrides=None, triggered_by="manual": wfo_full_calls.append(
            (symbol, horizon, variant, triggered_by)
        ),
    )

    refresh_market_data_mod._enqueue_signal_layers_after_refresh(
        "IAM",
        db=fake_db,
        now=dt.datetime(2026, 4, 23, 19, 0, tzinfo=dt.timezone.utc),
    )

    assert engine_full_calls == []
    assert wfo_full_calls == []


def test_upsert_market_data_store_persists_dashboard_stats():
    db = _CaptureDB()

    refresh_market_data_mod._upsert_market_data_store(
        db=db,
        symbol="IAM",
        timeframe="1D",
        object_key="market/IAM/1D.parquet",
        start_ts=dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc),
        end_ts=dt.datetime(2026, 5, 8, tzinfo=dt.timezone.utc),
        row_count=6,
        source_provider="bourse_direct",
        data_as_of=dt.date(2026, 5, 8),
        close_last=105.0,
        prev_close=100.0,
        adv_20d=12345.0,
    )

    assert db.commits == 1
    sql, params = db.executed[0]
    assert "close_last" in sql
    assert "prev_close" in sql
    assert "adv_20d" in sql
    assert params["close_last"] == 105.0
    assert params["prev_close"] == 100.0
    assert params["adv_20d"] == 12345.0


def test_enqueue_dashboard_snapshot_after_signal_jobs_uses_allow_failure_dependency(monkeypatch):
    captured: dict = {}

    class FakeQueue:
        def enqueue(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return SimpleNamespace(id="snapshot-job")

    monkeypatch.setattr(refresh_market_data_mod, "_market_refresh_queue", lambda: FakeQueue())
    monkeypatch.setattr(
        refresh_market_data_mod,
        "_dashboard_snapshot_dependency",
        lambda job_ids: {"jobs": tuple(job_ids), "allow_failure": True},
    )

    job_id = refresh_market_data_mod._enqueue_dashboard_snapshot_after_signal_jobs(
        ["engine-1", "wfo-1", "engine-1"],
        symbols=["IAM", "ATW"],
        triggered_by="market_refresh_all",
    )

    assert job_id == "snapshot-job"
    assert captured["args"] == (
        "services.worker.tasks.dashboard_snapshot.refresh_dashboard_snapshot",
        None,
    )
    assert captured["kwargs"]["depends_on"] == {
        "jobs": ("engine-1", "wfo-1"),
        "allow_failure": True,
    }
    assert captured["kwargs"]["job_timeout"] == 600
    assert captured["kwargs"]["meta"]["updated_symbols_count"] == 2
    assert captured["kwargs"]["meta"]["signal_dependency_count"] == 2
