from __future__ import annotations

import uuid

import numpy as np
import pandas as pd

from services.api.app.models import SignalBacktestRun, SignalEngineBatchJob, SignalEngineFamilyResult
from services.worker.tasks import signal_backtest_batch as backtest_mod


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

    def filter(self, condition):
        key = getattr(getattr(condition, "left", None), "key", None)
        value = getattr(getattr(condition, "right", None), "value", None)
        if key is None:
            return self
        rows = [row for row in self._rows if getattr(row, key, None) == value]
        return _FakeQuery(rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _FakeDB:
    def __init__(self, rows_by_model=None):
        self.rows_by_model = {**(rows_by_model or {})}

    def add(self, row):
        self.rows_by_model.setdefault(type(row), [])
        if row not in self.rows_by_model[type(row)]:
            self.rows_by_model[type(row)].append(row)

    def query(self, model):
        return _FakeQuery(self.rows_by_model.get(model, []))

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None


def _ohlcv_frame() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=20, freq="D")
    close = np.linspace(100.0, 110.0, len(dates))
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.linspace(1000.0, 2000.0, len(dates)),
        },
        index=dates,
    )


def test_run_signal_backtest_batch_uses_data_backed_signal_universe(monkeypatch):
    fake_db = _FakeDB()
    calls: list[tuple[str, str, str | None]] = []

    monkeypatch.setattr(backtest_mod, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(backtest_mod, "list_signal_universe_symbols", lambda _db: ["AAA", "XAUUSD"])

    def _fake_compute(symbol, horizon, variant="expanded", **kwargs):
        calls.append((symbol, horizon, kwargs.get("triggered_by")))
        return {"status": "succeeded"}

    monkeypatch.setattr(backtest_mod, "compute_signal_backtest_for_symbol", _fake_compute)

    result = backtest_mod.run_signal_backtest_batch()

    assert result == {"total": 6, "succeeded": 6, "failed": 0}
    assert calls == [
        ("AAA", "weekly", "scheduler"),
        ("AAA", "monthly", "scheduler"),
        ("AAA", "quarterly", "scheduler"),
        ("XAUUSD", "weekly", "scheduler"),
        ("XAUUSD", "monthly", "scheduler"),
        ("XAUUSD", "quarterly", "scheduler"),
    ]
    assert fake_db.rows_by_model == {}


def test_compute_signal_backtest_uses_requested_config_and_updates_job(monkeypatch):
    pending_job = SignalEngineBatchJob(
        id=uuid.uuid4(),
        symbol="AAA",
        horizon="weekly",
        variant="expanded",
        job_type="signal_backtest",
        status="pending",
        rq_job_id="rq-1",
        total_units=30,
        completed_units=0,
        failed_units=0,
    )
    family_row = SignalEngineFamilyResult(
        symbol="AAA",
        family="sma",
        category="tendance",
        horizon="weekly",
        variant="expanded",
        status="succeeded",
        representatives_json=[{"variant_id": "v1", "archetype": "sma_cross", "params": {}, "normalized_weight": 1.0}],
    )
    fake_db = _FakeDB(
        {
            SignalEngineBatchJob: [pending_job],
            SignalEngineFamilyResult: [family_row],
            SignalBacktestRun: [],
        }
    )

    monkeypatch.setattr(backtest_mod, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(backtest_mod, "load_ohlcv_for_symbol", lambda *_args, **_kwargs: _ohlcv_frame())

    def _engine_series(close, volume, high, low, family_results, category):
        if category != "tendance":
            return np.zeros(len(close), dtype=np.float64)
        return np.ones(len(close), dtype=np.float64)

    monkeypatch.setattr(backtest_mod, "build_category_signal_series_engine", _engine_series)

    bt_calls: list[dict] = []
    mc_calls: list[dict] = []
    input_hash_calls: list[dict] = []

    def _fake_backtest(signal_series, close, dates, **kwargs):
        bt_calls.append(dict(kwargs))
        return {
            "equity": [1.0] * len(close),
            "returns": [0.0] * (len(close) - 1),
            "dates": list(dates),
            "trades": [],
            "metrics": {
                "total_return": 0.0,
                "cagr": 0.0,
                "sharpe": 0.0,
                "max_drawdown": 0.0,
                "win_rate": 0.0,
                "n_trades": 0,
            },
        }

    def _fake_mc(returns, **kwargs):
        mc_calls.append(dict(kwargs))
        return {
            "envelope": {"p05": [], "p25": [], "p50": [], "p75": [], "p95": []},
            "stats": {},
        }

    def _fake_input_hash(*args, **kwargs):
        input_hash_calls.append(dict(kwargs))
        return "hash-1"

    monkeypatch.setattr(backtest_mod, "run_signal_backtest", _fake_backtest)
    monkeypatch.setattr(backtest_mod, "monte_carlo_equity_paths", _fake_mc)
    monkeypatch.setattr(backtest_mod, "compute_input_hash", _fake_input_hash)

    result = backtest_mod.compute_signal_backtest_for_symbol(
        "AAA",
        "weekly",
        window_start="2024-01-01",
        window_end="2024-01-20",
        mc_config={
            "cost_bps": 12.0,
            "slippage_bps": 7.0,
            "side_policy": "long_short",
            "cooldown_bars": 4,
            "method": "trade_bootstrap",
            "n_paths": 123,
            "seed": 9,
        },
        rq_job_id="rq-1",
        triggered_by="manual",
    )

    assert result["status"] == "succeeded"
    assert bt_calls
    assert all(call["cost_bps"] == 12.0 for call in bt_calls)
    assert all(call["slippage_bps"] == 7.0 for call in bt_calls)
    assert all(call["side_policy"] == "long_short" for call in bt_calls)
    assert all(call["cooldown_bars"] == 4 for call in bt_calls)
    assert mc_calls
    assert all(call["method"] == "block_bootstrap" for call in mc_calls)
    assert all(call["n_paths"] == 123 for call in mc_calls)
    assert input_hash_calls
    assert all(call["cooldown_bars"] == 4 for call in input_hash_calls)
    assert all(call["logic_version"] == backtest_mod.BACKTEST_INPUT_LOGIC_VERSION for call in input_hash_calls)
    saved_rows = fake_db.rows_by_model[SignalBacktestRun]
    assert saved_rows
    assert all(row.cost_bps == 12.0 for row in saved_rows)
    assert all(row.slippage_bps == 7.0 for row in saved_rows)
    assert all(row.side_policy == "long_short" for row in saved_rows)
    assert all(row.cooldown_bars == 4 for row in saved_rows)
    assert all(row.n_paths == 123 for row in saved_rows)
    assert all(row.mc_method == "block_bootstrap" for row in saved_rows)
    assert pending_job.status == "succeeded"
    assert pending_job.started_at is not None
    assert pending_job.finished_at is not None
    assert pending_job.completed_units == len(saved_rows)
    assert pending_job.completed_units > 0
    assert pending_job.failed_units == 0


def test_load_engine_family_rows_backfills_missing_family():
    family_row = SignalEngineFamilyResult(
        symbol="AAA",
        family="sma",
        category="tendance",
        horizon="weekly",
        variant="expanded",
        status="succeeded",
        representatives_json=[{"variant_id": "v1", "archetype": "price_vs_sma", "params": {"window": 3}}],
    )
    fake_db = _FakeDB({SignalEngineFamilyResult: [family_row]})

    rows = backtest_mod._load_engine_family_rows(fake_db, "AAA", "weekly", "expanded")

    assert rows["sma"]["representatives_json"][0]["family"] == "sma"
    assert "family" not in family_row.representatives_json[0]


def test_compute_signal_backtest_persists_failed_scope_when_series_build_fails(monkeypatch):
    pending_job = SignalEngineBatchJob(
        id=uuid.uuid4(),
        symbol="AAA",
        horizon="weekly",
        variant="expanded",
        job_type="signal_backtest",
        status="pending",
        rq_job_id="rq-2",
        total_units=30,
        completed_units=0,
        failed_units=0,
    )
    family_row = SignalEngineFamilyResult(
        symbol="AAA",
        family="sma",
        category="tendance",
        horizon="weekly",
        variant="expanded",
        status="succeeded",
        representatives_json=[{"variant_id": "v1", "archetype": "price_vs_sma", "params": {"window": 3}}],
    )
    fake_db = _FakeDB(
        {
            SignalEngineBatchJob: [pending_job],
            SignalEngineFamilyResult: [family_row],
            SignalBacktestRun: [],
        }
    )

    monkeypatch.setattr(backtest_mod, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(backtest_mod, "load_ohlcv_for_symbol", lambda *_args, **_kwargs: _ohlcv_frame())

    def _engine_series(close, volume, high, low, family_results, category):
        if category == "tendance":
            raise ValueError("broken reps")
        return np.zeros(len(close), dtype=np.float64)

    monkeypatch.setattr(backtest_mod, "build_category_signal_series_engine", _engine_series)
    monkeypatch.setattr(
        backtest_mod,
        "run_signal_backtest",
        lambda signal_series, close, dates, **kwargs: {
            "equity": [1.0] * len(close),
            "returns": [0.0] * (len(close) - 1),
            "dates": list(dates),
            "trades": [],
            "metrics": {
                "total_return": 0.0,
                "cagr": 0.0,
                "sharpe": 0.0,
                "max_drawdown": 0.0,
                "win_rate": 0.0,
                "n_trades": 0,
            },
        },
    )
    monkeypatch.setattr(
        backtest_mod,
        "monte_carlo_equity_paths",
        lambda returns, **kwargs: {"envelope": {"p05": [], "p25": [], "p50": [], "p75": [], "p95": []}, "stats": {}},
    )

    result = backtest_mod.compute_signal_backtest_for_symbol(
        "AAA",
        "weekly",
        window_start="2024-01-01",
        window_end="2024-01-20",
        rq_job_id="rq-2",
        triggered_by="manual",
    )

    assert result["status"] == "partial"
    failed_rows = [
        row
        for row in fake_db.rows_by_model[SignalBacktestRun]
        if row.source == "engine" and row.scope == "per_category" and row.scope_key == "tendance"
    ]
    assert failed_rows
    assert failed_rows[0].status == "failed"
    assert "broken reps" in (failed_rows[0].error_message or "")
    assert pending_job.failed_units >= 1


def test_diagnostic_representatives_preserve_combo_components():
    reps = [
        {
            "family": "expanded_ta_combo_momentum",
            "archetype": "strict_and_pair",
            "variant_id": "combo-1",
            "description": "TRIX AND CMF",
            "params": {
                "operator": "strict_and",
                "primary_category": "momentum",
                "conditioning": "factor_x_ta",
                "component_families": ["trix@fx", "cmf@fx"],
                "components": [
                    {
                        "family": "trix@fx",
                        "archetype": "trix_zero",
                        "variant_id": "trix-1",
                        "description": "TRIX-31",
                        "params": {"period": 31, "ignored": "x"},
                        "factor_condition": {
                            "condition_id": "vix-z",
                            "factor_ticker": "^VIX",
                            "form": "zscore",
                            "lookback": 63,
                            "threshold": 1.5,
                            "direction": "above",
                        },
                    },
                    {
                        "family": "cmf@fx",
                        "archetype": "cmf_flow",
                        "variant_id": "cmf-1",
                        "description": "CMF-34",
                        "params": {"period": 34},
                    },
                ],
            },
        }
    ]

    out = backtest_mod._diagnostic_representatives(reps)

    params = out[0]["params"]
    assert params["operator"] == "strict_and"
    assert params["primary_category"] == "momentum"
    assert params["component_families"] == ["trix@fx", "cmf@fx"]
    assert params["components"][0]["family"] == "trix@fx"
    assert params["components"][0]["params"] == {"period": 31.0}
    assert params["components"][0]["factor_condition"]["factor_ticker"] == "^VIX"
    assert params["components"][1]["family"] == "cmf@fx"
    assert params["components"][1]["params"] == {"period": 34.0}
