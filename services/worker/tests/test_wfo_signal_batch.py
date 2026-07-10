from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import numpy as np
import pandas as pd

from services.api.app.models import WfoGlobalSignal, WfoSignalSummary
from services.worker.tasks import wfo_signal_batch as wfo_batch_mod
from core.quant_core.signal_engine.domain import VariantDef
from core.quant_core.signal_engine.modes import ALL_SIGNAL_MODE_NAMES


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
    dates = pd.date_range("2026-01-01", periods=30, freq="D")
    close = np.linspace(100.0, 120.0, len(dates))
    return pd.DataFrame(
        {
            "Open": close,
            "High": close + 1.0,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.linspace(1000.0, 1200.0, len(dates)),
        },
        index=dates,
    )


def _summary_row(symbol: str, category: str, horizon: str, variant: str, family: str) -> WfoSignalSummary:
    return WfoSignalSummary(
        symbol=symbol,
        category=category,
        horizon=horizon,
        variant=variant,
        status="succeeded",
        representatives_json=[
            {
                "family": family,
                "archetype": "price_vs_sma",
                "variant_id": f"{family}_v1",
                "params": {"window": 10},
                "description": f"{family} rep",
                "normalized_weight": 1.0,
                "signal": 0.0,
                "signal_label": "Neutre",
            }
        ],
    )


def test_build_config_json_defaults_max_reps_to_one():
    payload = wfo_batch_mod._build_config_json(
        horizon="weekly",
        category="tendance",
        close_len=500,
        pool_size=10,
        overrides={},
    )
    assert payload["max_reps"] == 1
    assert payload["cost_bps"] == 33.0


def test_build_folds_json_persists_indices_and_dates():
    dates = pd.date_range("2026-01-01", periods=10, freq="D")
    pool = [SimpleNamespace(variant_id="sma-5", description="SMA-5")]
    result = SimpleNamespace(
        engine_result=SimpleNamespace(
            windows=[
                SimpleNamespace(
                    winner_key=0,
                    window=SimpleNamespace(
                        index=1,
                        train_start=0,
                        train_end=5,
                        oos_start=5,
                        oos_end=8,
                    ),
                    is_return=0.0123456,
                    oos_return=0.0234567,
                    oos_sharpe=1.23456,
                    winner_prom=0.0345678,
                    profile=SimpleNamespace(
                        passes=True,
                        reason="ok",
                        pct_profitable=0.75,
                    ),
                )
            ]
        )
    )

    folds = wfo_batch_mod._build_folds_json(result, pool, dates)

    assert folds is not None
    fold = folds[0]
    assert fold["train_start_idx"] == 0
    assert fold["train_end_idx"] == 5
    assert fold["oos_start_idx"] == 5
    assert fold["oos_end_idx"] == 8
    assert fold["train_start_abs_idx"] == 0
    assert fold["train_end_abs_idx"] == 5
    assert fold["oos_start_abs_idx"] == 5
    assert fold["oos_end_abs_idx"] == 8
    assert fold["train_start_date"] == "2026-01-01"
    assert fold["train_end_date"] == "2026-01-05"
    assert fold["oos_start_date"] == "2026-01-06"
    assert fold["oos_end_date"] == "2026-01-08"
    assert fold["winner_variant_id"] == "sma-5"
    assert fold["winner_params"] == {}


def test_build_folds_json_resolves_dates_with_horizon_cap_offset():
    dates = pd.date_range("2026-01-01", periods=20, freq="D")
    pool = [SimpleNamespace(variant_id="sma-5", description="SMA-5")]
    result = SimpleNamespace(
        window_diagnostics={"horizon_cap_start_offset": 10},
        engine_result=SimpleNamespace(
            windows=[
                SimpleNamespace(
                    winner_key=0,
                    window=SimpleNamespace(
                        index=0,
                        train_start=0,
                        train_end=5,
                        oos_start=5,
                        oos_end=8,
                    ),
                    is_return=0.01,
                    oos_return=0.02,
                    oos_sharpe=1.2,
                    winner_prom=0.03,
                    profile=SimpleNamespace(
                        passes=True,
                        reason="ok",
                        pct_profitable=0.75,
                    ),
                )
            ]
        ),
    )

    folds = wfo_batch_mod._build_folds_json(result, pool, dates)

    assert folds is not None
    fold = folds[0]
    assert fold["train_start_idx"] == 0
    assert fold["oos_end_idx"] == 8
    assert fold["train_start_abs_idx"] == 10
    assert fold["train_end_abs_idx"] == 15
    assert fold["oos_start_abs_idx"] == 15
    assert fold["oos_end_abs_idx"] == 18
    assert fold["train_start_date"] == "2026-01-11"
    assert fold["train_end_date"] == "2026-01-15"
    assert fold["oos_start_date"] == "2026-01-16"
    assert fold["oos_end_date"] == "2026-01-18"


def test_build_config_json_includes_fold_coverage_metadata():
    dates = pd.date_range("2026-01-01", periods=20, freq="D")
    folds_json = [
        {
            "oos_start_date": "2026-01-16",
            "oos_end_date": "2026-01-18",
            "oos_end_abs_idx": 18,
        }
    ]

    payload = wfo_batch_mod._build_config_json(
        horizon="weekly",
        category="tendance",
        close_len=20,
        pool_size=1,
        overrides={},
        folds_json=folds_json,
        index=dates,
        data_as_of=dt.date(2026, 1, 20),
    )

    assert payload["last_oos_start_date"] == "2026-01-16"
    assert payload["last_oos_end_date"] == "2026-01-18"
    assert payload["last_oos_end_abs_idx"] == 18
    assert payload["unused_tail_bars"] == 2
    assert payload["data_as_of"] == "2026-01-20"


def test_fragility_classifies_stable_and_aggregate_no_severe():
    klass, ci_lo, ci_hi = wfo_batch_mod._fragility_class(0.4, [0.3, 0.35, 0.4, 0.45])

    assert klass == "stable"
    assert ci_lo > 0
    assert ci_hi > 0
    assert wfo_batch_mod._aggregate_fragility(
        [{"class": "stable"}, {"class": "stable"}, {"class": "mixed"}]
    ) == "mixed_local_sensitivity"


def test_local_neighbors_uses_ten_percent_window_and_caps():
    winner = VariantDef("sma-14", "sma", "price_vs_sma", {"window": 14})
    pool = [
        VariantDef(f"sma-{i}", "sma", "price_vs_sma", {"window": i})
        for i in range(1, 40)
    ]

    neighbors = wfo_batch_mod._local_neighbors(pool, winner)

    assert [item.params["window"] for item in neighbors] == [14, 13, 15, 12, 16]


def test_refresh_wfo_uses_persisted_representatives_without_reselection(monkeypatch):
    full_run_at = dt.datetime(2026, 1, 10, tzinfo=dt.timezone.utc)
    rows = [
        _summary_row("AAA", "tendance", "weekly", "expanded", "sma"),
        _summary_row("AAA", "momentum", "weekly", "expanded", "macd"),
        _summary_row("AAA", "oscillation", "weekly", "expanded", "rsi"),
        _summary_row("AAA", "volume", "weekly", "expanded", "obv"),
    ]
    global_row = WfoGlobalSignal(
        symbol="AAA",
        horizon="weekly",
        variant="expanded",
        full_computed_at=full_run_at,
    )
    fake_db = _FakeDB({WfoSignalSummary: rows, WfoGlobalSignal: [global_row]})

    monkeypatch.setattr(wfo_batch_mod, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(wfo_batch_mod, "load_ohlcv_for_symbol", lambda *_a, **_k: _ohlcv_frame())
    monkeypatch.setattr(wfo_batch_mod, "drop_incomplete_ohlcv_rows", lambda df: df)
    monkeypatch.setattr(
        wfo_batch_mod,
        "build_current_signal",
        lambda variant, close, **kwargs: SimpleNamespace(
            signal=1.0,
            signal_label="HAUSSIER",
            current_close=float(close[-1]),
            indicator_value=None,
            explanation="refreshed",
            reliability_weight=float(kwargs.get("reliability_weight", 1.0)),
        ),
    )
    monkeypatch.setattr(
        wfo_batch_mod,
        "_get_sr_levels",
        lambda close, high, low, volume, horizon: (None, None, None, None, 0.0),
    )
    monkeypatch.setattr(
        wfo_batch_mod,
        "compute_global_wfo_signal",
        lambda *args, **kwargs: SimpleNamespace(
            status="succeeded",
            global_score_pct=50.0,
            raw_score_pct=50.0,
            signal_label="Achat",
            recommendation="achat",
            weights={"tendance": 0.25, "momentum": 0.25, "oscillation": 0.25, "volume": 0.25},
            sr_modifier=1.0,
            sr_support=None,
            sr_resistance=None,
            sr_support_method=None,
            sr_resistance_method=None,
            best_category="tendance",
            best_category_score=50.0,
            categories_viable=4,
            consensus_wfe_pct=60.0,
            consensus_robustness=0.7,
        ),
    )

    def _unexpected_full_compute(*_args, **_kwargs):
        raise AssertionError("refresh path should not trigger full WFO recompute")

    monkeypatch.setattr(wfo_batch_mod, "run_wfo_for_symbol_horizon", _unexpected_full_compute)

    result = wfo_batch_mod.refresh_wfo_for_symbol_horizon("AAA", "weekly", "expanded")

    assert result["status"] == "succeeded"
    assert result["mode"] == "representatives_refresh"
    assert result["refreshed_categories"] == 4
    assert result["failed_categories"] == 0
    assert global_row.full_computed_at == full_run_at

    expected_close = float(_ohlcv_frame()["Close"].iloc[-1])
    for row in fake_db.rows_by_model[WfoSignalSummary]:
        assert row.status == "succeeded"
        assert len(row.representatives_json) == 1
        rep = row.representatives_json[0]
        assert rep["signal"] == 1.0
        assert rep["current_close"] == expected_close


def test_run_weekly_wfo_batch_only_processes_weekly_stale_data_backed_tuples(monkeypatch):
    now = dt.datetime(2026, 4, 25, 19, 0, tzinfo=dt.timezone.utc)
    fake_db = _FakeDB(
        {
            WfoGlobalSignal: [
                WfoGlobalSignal(
                    symbol="AAA",
                    horizon=horizon,
                    variant=variant,
                    computed_at=now - dt.timedelta(
                        days=8 if (horizon, variant) == ("weekly", "legacy_ta_simple") else 2
                    ),
                    full_computed_at=now - dt.timedelta(
                        days=8 if (horizon, variant) == ("weekly", "legacy_ta_simple") else 2
                    ),
                )
                for horizon in ("weekly", "monthly", "quarterly")
                for variant in ALL_SIGNAL_MODE_NAMES
            ],
        }
    )
    calls: list[tuple[str, str, str]] = []

    monkeypatch.setattr(wfo_batch_mod, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(wfo_batch_mod, "list_signal_universe_symbols", lambda _db: ["AAA"])
    monkeypatch.setattr(
        wfo_batch_mod,
        "run_wfo_for_symbol_horizon",
        lambda db, symbol, horizon, *, overrides=None, variant="expanded": calls.append(
            (symbol, horizon, variant)
        ),
    )

    result = wfo_batch_mod.run_weekly_wfo_batch(now=now)

    assert result == {"total": 1, "succeeded": 1, "failed": 0}
    assert calls == [("AAA", "weekly", "legacy_ta_simple")]


def _sr_wfo_payload(as_of: str = "2026-04-20") -> dict:
    return {
        "response": {
            "as_of": as_of,
            "wfo": {
                "as_of": as_of,
                "status": "ok",
                "decision": "actionable",
                "procedure_oos": {"sharpe": 1.0, "hit_rate": 0.6, "n_trades": 10, "total_return": 0.1},
                "baselines": {"in_sample_best": {"sharpe": 1.5}},
                "stability": {"selection_stability": 0.7},
                "windows": [{"test_metrics": {"total_return": 0.05, "max_drawdown": -0.02}}],
                "params_echo": {"foo": "bar"},
                "live_recommendation": {"support_level": 100.0, "resistance_level": 110.0, "pair_meta": {}},
            },
        }
    }


def test_run_sr_wfo_for_symbol_horizon_success_writes_succeeded_row(monkeypatch):
    fake_db = _FakeDB({WfoSignalSummary: []})
    monkeypatch.setattr(wfo_batch_mod, "SessionLocal", lambda: fake_db)

    import services.api.app.routers.strategy_signals._support_resistance as sr_mod

    monkeypatch.setattr(sr_mod, "_sr_get_or_compute_wfo", lambda **kwargs: _sr_wfo_payload())

    wfo_batch_mod.run_sr_wfo_for_symbol_horizon(fake_db, "AAA", "weekly", variant="expanded")

    rows = fake_db.rows_by_model[WfoSignalSummary]
    assert len(rows) == 1
    row = rows[0]
    assert row.category == "support_resistance"
    assert row.status == "succeeded"
    assert row.folds_json == _sr_wfo_payload()["response"]["wfo"]["windows"]
    assert row.config_json["foo"] == "bar"
    assert row.fragility_json == {"selection_stability": 0.7}
    assert row.data_as_of == dt.date(2026, 4, 20)


def test_run_sr_wfo_for_symbol_horizon_exception_writes_failed_row(monkeypatch):
    fake_db = _FakeDB({WfoSignalSummary: []})
    monkeypatch.setattr(wfo_batch_mod, "SessionLocal", lambda: fake_db)

    import services.api.app.routers.strategy_signals._support_resistance as sr_mod

    def _boom(**kwargs):
        raise RuntimeError("sr compute exploded")

    monkeypatch.setattr(sr_mod, "_sr_get_or_compute_wfo", _boom)

    wfo_batch_mod.run_sr_wfo_for_symbol_horizon(fake_db, "AAA", "weekly", variant="expanded")

    rows = fake_db.rows_by_model[WfoSignalSummary]
    assert len(rows) == 1
    row = rows[0]
    assert row.category == "support_resistance"
    assert row.status == "failed"
    assert "sr compute exploded" in row.error_message


def test_run_wfo_for_symbol_horizon_no_longer_computes_sr_inline(monkeypatch):
    """run_wfo_for_symbol_horizon should only compute the 4 base categories +
    global consensus; S/R is dispatched separately via run_sr_wfo_for_symbol_horizon."""
    fake_db = _FakeDB({WfoSignalSummary: [], WfoGlobalSignal: []})
    monkeypatch.setattr(wfo_batch_mod, "SessionLocal", lambda: fake_db)
    monkeypatch.setattr(wfo_batch_mod, "load_ohlcv_for_symbol", lambda *_a, **_k: _ohlcv_frame())
    monkeypatch.setattr(wfo_batch_mod, "drop_incomplete_ohlcv_rows", lambda df: df)

    def _unexpected_sr_call(*_args, **_kwargs):
        raise AssertionError("run_wfo_for_symbol_horizon must not compute S/R inline anymore")

    import services.api.app.routers.strategy_signals._support_resistance as sr_mod

    monkeypatch.setattr(sr_mod, "_sr_get_or_compute_wfo", _unexpected_sr_call)

    def _fake_category(category, horizon, close, *, volume=None, high=None, low=None, families=None, **kwargs):
        return SimpleNamespace(
            category=category,
            symbol=None,
            horizon=horizon,
            status="succeeded",
            score_pct=0.0,
            signal_label="Neutre",
            representatives=[],
            wfe_pct=0.0,
            robustness_ratio=0.0,
            total_folds=0,
            profitable_folds=0,
            mean_oos_sharpe=0.0,
            total_oos_pnl=0.0,
            worst_fold_drawdown=0.0,
            composite_score=0.0,
            robustness_grade="F",
            config_used={},
            data_as_of="",
            compute_seconds=0.0,
            engine_result=None,
            error_message=None,
        )

    monkeypatch.setattr(wfo_batch_mod, "run_wfo_category_signal", _fake_category)
    monkeypatch.setattr(
        wfo_batch_mod,
        "_get_sr_levels",
        lambda close, high, low, volume, horizon: (None, None, None, None, 0.0),
    )
    monkeypatch.setattr(
        wfo_batch_mod,
        "compute_global_wfo_signal",
        lambda *args, **kwargs: SimpleNamespace(
            status="succeeded",
            global_score_pct=0.0,
            raw_score_pct=0.0,
            signal_label="Neutre",
            recommendation="conserver",
            weights={"tendance": 0.25, "momentum": 0.25, "oscillation": 0.25, "volume": 0.25},
            sr_modifier=1.0,
            sr_support=None,
            sr_resistance=None,
            sr_support_method=None,
            sr_resistance_method=None,
            best_category="tendance",
            best_category_score=0.0,
            categories_viable=4,
            consensus_wfe_pct=0.0,
            consensus_robustness=0.0,
        ),
    )

    wfo_batch_mod.run_wfo_for_symbol_horizon(fake_db, "AAA", "weekly", variant="expanded")

    categories = {row.category for row in fake_db.rows_by_model[WfoSignalSummary]}
    assert "support_resistance" not in categories
    assert categories == {"tendance", "momentum", "oscillation", "volume"}
    assert fake_db.rows_by_model[WfoGlobalSignal][0].full_computed_at is not None
