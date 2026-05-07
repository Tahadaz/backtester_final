from __future__ import annotations

import importlib
import datetime as dt

from services.api.app.models import SignalEngineGlobalResult, WfoGlobalSignal
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


def _engine_global_rows(symbol: str, *, stale_target: tuple[str, str] | None = None):
    now = dt.datetime(2026, 4, 24, 19, 0, tzinfo=dt.timezone.utc)
    rows = []
    for horizon in ("short", "medium", "long"):
        for variant in ("legacy", "expanded"):
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
    for horizon in ("short", "medium", "long"):
        for variant in ("legacy", "expanded"):
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

    monkeypatch.setattr(refresh_market_data_mod, "_SIGNAL_ENGINE_REFRESH_ON_MARKET_REFRESH", True)
    monkeypatch.setattr(
        signal_engine_batch_mod,
        "enqueue_signal_engine_refresh_for_symbol",
        lambda symbol, horizon, *, variant, triggered_by: engine_calls.append(
            (symbol, horizon, variant, triggered_by)
        ),
    )
    monkeypatch.setattr(
        wfo_signal_batch_mod,
        "enqueue_wfo_refresh_for_symbol_horizon",
        lambda symbol, horizon, *, variant, triggered_by: wfo_calls.append(
            (symbol, horizon, variant, triggered_by)
        ),
    )

    refresh_market_data_mod._enqueue_signal_layers_after_refresh("IAM")

    expected = {
        ("IAM", "short", "legacy", "market_refresh"),
        ("IAM", "short", "expanded", "market_refresh"),
        ("IAM", "medium", "legacy", "market_refresh"),
        ("IAM", "medium", "expanded", "market_refresh"),
        ("IAM", "long", "legacy", "market_refresh"),
        ("IAM", "long", "expanded", "market_refresh"),
    }
    assert set(engine_calls) == expected
    assert set(wfo_calls) == expected


def test_enqueue_signal_layers_after_refresh_friday_enqueues_full_recompute_only_for_weekly_stale(monkeypatch):
    engine_refresh_calls: list[tuple[str, str, str, str]] = []
    wfo_refresh_calls: list[tuple[str, str, str, str]] = []
    engine_full_calls: list[tuple[str, str, str, str]] = []
    wfo_full_calls: list[tuple[str, str, str, str]] = []
    fake_db = _FakeDB(
        {
            SignalEngineGlobalResult: _engine_global_rows("IAM", stale_target=("short", "legacy")),
            WfoGlobalSignal: _wfo_global_rows("IAM", stale_target=("medium", "expanded")),
        }
    )

    monkeypatch.setattr(refresh_market_data_mod, "_SIGNAL_ENGINE_REFRESH_ON_MARKET_REFRESH", True)
    monkeypatch.setattr(
        signal_engine_batch_mod,
        "enqueue_signal_engine_refresh_for_symbol",
        lambda symbol, horizon, *, variant, triggered_by: engine_refresh_calls.append(
            (symbol, horizon, variant, triggered_by)
        ),
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
        "enqueue_wfo_refresh_for_symbol_horizon",
        lambda symbol, horizon, *, variant, triggered_by: wfo_refresh_calls.append(
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
        now=dt.datetime(2026, 4, 24, 19, 0, tzinfo=dt.timezone.utc),
    )

    assert len(engine_refresh_calls) == 6
    assert len(wfo_refresh_calls) == 6
    assert engine_full_calls == [("IAM", "short", "legacy", "weekly_market_refresh")]
    assert wfo_full_calls == [("IAM", "medium", "expanded", "weekly_market_refresh")]


def test_enqueue_signal_layers_after_refresh_non_friday_skips_weekly_full_recompute(monkeypatch):
    engine_full_calls: list[tuple[str, str, str, str]] = []
    wfo_full_calls: list[tuple[str, str, str, str]] = []
    fake_db = _FakeDB(
        {
            SignalEngineGlobalResult: _engine_global_rows("IAM", stale_target=("short", "legacy")),
            WfoGlobalSignal: _wfo_global_rows("IAM", stale_target=("medium", "expanded")),
        }
    )

    monkeypatch.setattr(refresh_market_data_mod, "_SIGNAL_ENGINE_REFRESH_ON_MARKET_REFRESH", False)
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
