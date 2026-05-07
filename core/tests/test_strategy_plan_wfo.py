from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from core.quant_core.strategy_plan.score_frame import derive_max_lookback
from core.quant_core.strategy_plan import wfo as wfo_module
from core.quant_core.strategy_plan.wfo import _apply_execution_kelly, _candidate_dimensions, _parse_param_path
from core.quant_core.wfo.config import WalkForwardConfig
from core.quant_core.wfo.sizing import compute_kelly_fraction, compute_trade_stats
from core.quant_core.wfo.window import build_walk_forward_windows


def test_candidate_dimensions_include_leaf_rule_sizing_params_only() -> None:
    stock_config = {
        "signal_construction": {"families": {}},
        "entry_rules": [
            {
                "id": "e1",
                "sizing": {
                    "mode": "wfo",
                    "manual_pct": 25,
                    "size_pct": {"mode": "wfo", "value": 25, "scan_min": 25, "scan_max": 75, "scan_step": 25},
                },
            }
        ],
        "exit_rules": [
            {
                "id": "x1",
                "sizing": {
                    "mode": "kelly_wfo",
                    "manual_pct": 100,
                    "kelly_modifier": {"mode": "wfo", "value": 0.5, "scan_min": 0.25, "scan_max": 1.0, "scan_step": 0.25},
                },
            }
        ],
        "risk": {},
    }

    dimensions = _candidate_dimensions(stock_config)
    paths = {dimension.path for dimension in dimensions}

    assert "entry_rules[0].sizing" not in paths
    assert "exit_rules[0].sizing" not in paths
    assert "entry_rules[0].sizing.size_pct" in paths
    assert "exit_rules[0].sizing.kelly_modifier" in paths


def test_apply_execution_kelly_injects_fraction_for_kelly_rules() -> None:
    stock_config = {
        "entry_rules": [{"id": "e1", "label": "Entry", "sizing": {"mode": "kelly_wfo", "manual_pct": 25}}],
        "exit_rules": [{"id": "x1", "label": "Exit", "sizing": {"mode": "kelly_wfo", "manual_pct": 100}}],
    }
    kelly = compute_kelly_fraction(compute_trade_stats([200, 180, 150, -100, -120, 220, 160, -90] * 5))

    resolved, warnings = _apply_execution_kelly(stock_config, kelly=kelly, context_label="IAM window 0 IS")

    assert warnings == []
    assert resolved["entry_rules"][0]["sizing"]["execution_kelly_fraction"] == kelly.fraction
    assert resolved["exit_rules"][0]["sizing"]["execution_kelly_fraction"] == kelly.fraction


def test_apply_execution_kelly_warns_and_falls_back_when_estimate_is_not_safe() -> None:
    stock_config = {
        "entry_rules": [{"id": "e1", "label": "Entry", "sizing": {"mode": "kelly_wfo", "manual_pct": 25}}],
        "exit_rules": [{"id": "x1", "label": "Exit", "sizing": {"mode": "kelly_wfo", "manual_pct": 100}}],
    }
    kelly = compute_kelly_fraction(compute_trade_stats([120, -90, 110, -80, 100]))

    resolved, warnings = _apply_execution_kelly(stock_config, kelly=kelly, context_label="IAM window 0 IS")

    assert resolved["entry_rules"][0]["sizing"]["execution_kelly_fraction"] is None
    assert resolved["exit_rules"][0]["sizing"]["execution_kelly_fraction"] is None
    assert len(warnings) == 2
    assert all("fell back to manual_pct" in warning for warning in warnings)


def test_parse_param_path_handles_nested_lists() -> None:
    assert _parse_param_path("signal_construction.families.sma.rows[0].params.window") == [
        "signal_construction",
        "families",
        "sma",
        "rows",
        0,
        "params",
        "window",
    ]


def test_derive_max_lookback_uses_scan_max_for_strategy_wfo() -> None:
    stock_config = {
        "signal_construction": {
            "families": {
                "sma": {
                    "enabled": True,
                    "source_mode": "indicator_rows",
                    "rows": [
                        {
                            "id": "sma_row_1",
                            "enabled": True,
                            "params": {
                                "window": {"mode": "wfo", "value": 20, "scan_min": 10, "scan_max": 40, "scan_step": 5}
                            },
                        }
                    ],
                }
            }
        }
    }

    assert derive_max_lookback(stock_config, horizon="short", strict_indicator_rows=True) == 40


def test_derive_max_lookback_rejects_family_ensemble_for_strategy_wfo() -> None:
    stock_config = {
        "signal_construction": {
            "families": {
                "sma": {
                    "enabled": True,
                    "source_mode": "family_ensemble",
                    "rows": [],
                }
            }
        }
    }

    with pytest.raises(ValueError, match="indicator_rows"):
        derive_max_lookback(stock_config, strict_indicator_rows=True)


def test_derive_max_lookback_without_active_rows_uses_minimum_one() -> None:
    stock_config = {
        "signal_construction": {
            "families": {
                "sma": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                "rsi": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                "macd": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                "obv": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
            }
        }
    }

    assert derive_max_lookback(stock_config, horizon="short", strict_indicator_rows=True) == 1


def test_strict_fold_driven_configs_returns_walk_forward_configs() -> None:
    configs, meta = wfo_module._strict_fold_driven_configs(
        data_length=504,
        max_lookback=7,
        requested_min_walk_forwards=5,
        top_k_folds=12,
        fallback_enabled=True,
        fallback_floor=1,
    )

    assert configs
    assert len(configs) <= 12
    assert all(isinstance(config, WalkForwardConfig) for config in configs)
    assert meta["status"] == "strict"
    for config in configs:
        ratio = config.oos_bars / config.train_bars
        assert 0.25 <= ratio <= 0.35
        assert len(build_walk_forward_windows(504, config, max_lookback=7)) >= meta["effective_min_walk_forwards"]


def test_strict_fold_driven_configs_can_fallback_and_mark_metadata() -> None:
    configs, meta = wfo_module._strict_fold_driven_configs(
        data_length=200,
        max_lookback=7,
        requested_min_walk_forwards=50,
        top_k_folds=12,
        fallback_enabled=True,
        fallback_floor=1,
    )

    assert configs
    assert meta["fallback_applied"] is True
    assert meta["status"] == "strict_fallback"
    assert meta["effective_min_walk_forwards"] < meta["requested_min_walk_forwards"]


def test_strict_fold_driven_configs_reports_infeasible_at_floor() -> None:
    configs, meta = wfo_module._strict_fold_driven_configs(
        data_length=120,
        max_lookback=40,
        requested_min_walk_forwards=5,
        top_k_folds=12,
        fallback_enabled=True,
        fallback_floor=1,
    )

    assert configs == []
    assert meta["status"] == "infeasible"
    assert meta["max_feasible_folds_before_fallback"] == 0


def test_apply_candidate_guardrail_downsamples_large_grids_and_preserves_edges() -> None:
    dimensions = [
        wfo_module._ParamDimension(path="a", values=tuple(range(1, 101)), integer_like=True),
        wfo_module._ParamDimension(path="b", values=tuple(range(1, 101)), integer_like=True),
        wfo_module._ParamDimension(path="c", values=tuple(range(1, 51)), integer_like=True),
    ]

    capped, diagnostics = wfo_module._apply_candidate_guardrail(dimensions, max_candidate_tuples=100_000)

    assert diagnostics["applied"] is True
    assert diagnostics["raw_candidate_count"] == 500_000
    assert diagnostics["effective_candidate_count"] <= 100_000
    assert wfo_module._candidate_count(capped) == diagnostics["effective_candidate_count"]
    assert capped[0].values[0] == 1
    assert capped[0].values[-1] == 100
    assert capped[1].values[0] == 1
    assert capped[1].values[-1] == 100
    assert capped[2].values[0] == 1
    assert capped[2].values[-1] == 50
    assert diagnostics["reduced_dimensions"]
    assert "downsampled" in str(diagnostics.get("warning") or "").lower()


def _build_ohlcv_bars(*, periods: int, start: str = "2020-01-01") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(periods)],
            "High": [101.0 + i for i in range(periods)],
            "Low": [99.0 + i for i in range(periods)],
            "Close": [100.0 + i for i in range(periods)],
            "Volume": [1_000.0] * periods,
        },
        index=pd.date_range(start, periods=periods, freq="D"),
    )


def _build_full_family_score_stock_config() -> dict:
    return {
        "signal_construction": {
            "families": {
                "sma": {"enabled": True, "source_mode": "family_ensemble", "rows": []},
                "rsi": {"enabled": True, "source_mode": "family_ensemble", "rows": []},
                "macd": {"enabled": True, "source_mode": "family_ensemble", "rows": []},
                "obv": {"enabled": True, "source_mode": "family_ensemble", "rows": []},
            }
        },
        "entry_rules": [
            {
                "id": "entry_1",
                "label": "Entry 1",
                "conditions": [{"variable": "consensus_score", "operator": ">=", "threshold": {"mode": "manual", "value": 0.5}}],
                "sizing": {"mode": "manual", "manual_pct": 25},
            }
        ],
        "exit_rules": [
            {
                "id": "exit_1",
                "label": "Exit 1",
                "conditions": [{"variable": "consensus_score", "operator": "<=", "threshold": {"mode": "manual", "value": -0.5}}],
                "sizing": {"mode": "manual", "manual_pct": 100},
            }
        ],
        "risk": {
            "stop_loss": {"mode": "atr_based", "atr_multiplier": {"mode": "manual", "value": 1.5}},
            "take_profit": {"mode": "rr_target", "rr_ratio": {"mode": "manual", "value": 1.5}},
            "cooldown_bars": {"mode": "manual", "value": 0},
            "time_stop": {"enabled": True, "bars": {"mode": "manual", "value": 30}},
            "trailing_stop_enabled": False,
            "max_position_pct": 20,
        },
    }


def _build_mixed_family_score_stock_config() -> dict:
    return {
        "signal_construction": {
            "families": {
                "sma": {"enabled": True, "source_mode": "family_ensemble", "rows": []},
                "rsi": {
                    "enabled": True,
                    "source_mode": "indicator_rows",
                    "rows": [
                        {
                            "id": "rsi_row_1",
                            "enabled": True,
                            "score_key": "oscillation_score",
                            "label": "Oscillation Score",
                            "params": {"period": {"mode": "manual", "value": 14}},
                        }
                    ],
                },
                "macd": {"enabled": False, "source_mode": "family_ensemble", "rows": []},
                "obv": {"enabled": False, "source_mode": "family_ensemble", "rows": []},
            }
        },
        "entry_rules": [
            {
                "id": "entry_1",
                "label": "Entry 1",
                "conditions": [{"variable": "consensus_score", "operator": ">=", "threshold": {"mode": "manual", "value": 0.5}}],
                "sizing": {"mode": "manual", "manual_pct": 25},
            }
        ],
        "exit_rules": [
            {
                "id": "exit_1",
                "label": "Exit 1",
                "conditions": [{"variable": "consensus_score", "operator": "<=", "threshold": {"mode": "manual", "value": -0.5}}],
                "sizing": {"mode": "manual", "manual_pct": 100},
            }
        ],
        "risk": {
            "stop_loss": {"mode": "atr_based", "atr_multiplier": {"mode": "manual", "value": 1.5}},
            "take_profit": {"mode": "rr_target", "rr_ratio": {"mode": "manual", "value": 1.5}},
            "cooldown_bars": {"mode": "manual", "value": 0},
            "time_stop": {"enabled": True, "bars": {"mode": "manual", "value": 30}},
            "trailing_stop_enabled": False,
            "max_position_pct": 20,
        },
    }


def _build_wfo_short_cap_test_bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(900)],
            "High": [101.0 + i for i in range(900)],
            "Low": [99.0 + i for i in range(900)],
            "Close": [100.0 + i for i in range(900)],
            "Volume": [1_000.0] * 900,
        },
        index=pd.date_range("2020-01-01", periods=900, freq="D"),
    )


def _build_wfo_short_cap_test_stock_config() -> dict:
    return {
        "signal_construction": {
            "families": {
                "sma": {
                    "enabled": True,
                    "source_mode": "indicator_rows",
                    "rows": [
                        {
                            "id": "sma_row_1",
                            "enabled": True,
                            "score_key": "trend_score",
                            "label": "Trend Score",
                            "params": {
                                "window": {"mode": "wfo", "value": 20, "scan_min": 20, "scan_max": 20, "scan_step": 1}
                            },
                        }
                    ],
                },
                "rsi": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                "macd": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                "obv": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
            }
        },
        "entry_rules": [
            {
                "id": "entry_1",
                "label": "Entry 1",
                "conditions": [{"variable": "consensus_score", "operator": ">=", "threshold": {"mode": "manual", "value": 0.5}}],
                "sizing": {"mode": "manual", "manual_pct": 25},
            }
        ],
        "exit_rules": [
            {
                "id": "exit_1",
                "label": "Exit 1",
                "conditions": [{"variable": "consensus_score", "operator": "<=", "threshold": {"mode": "manual", "value": -0.5}}],
                "sizing": {"mode": "manual", "manual_pct": 100},
            }
        ],
        "risk": {
            "stop_loss": {"mode": "atr_based", "atr_multiplier": {"mode": "manual", "value": 1.5}},
            "take_profit": {"mode": "rr_target", "rr_ratio": {"mode": "manual", "value": 1.5}},
            "cooldown_bars": {"mode": "manual", "value": 0},
            "time_stop": {"enabled": True, "bars": {"mode": "manual", "value": 30}},
            "trailing_stop_enabled": False,
            "max_position_pct": 20,
        },
    }


def _patch_minimal_wfo_not_viable_runtime(monkeypatch) -> None:
    fake_sim = SimpleNamespace(
        summary_metrics={"total_return": 0.05},
        equity=pd.Series([100_000.0, 100_500.0, 101_000.0], index=pd.date_range("2022-01-01", periods=3, freq="D")),
        fills=pd.DataFrame(),
    )
    fake_profile = SimpleNamespace(
        passes=True,
        reason="ok",
        detail="ok",
        pct_profitable=0.5,
        winner_smoothed_prom=1.0,
        neighborhood_cv=0.1,
        warnings=[],
    )

    monkeypatch.setattr(wfo_module, "_build_cost_model", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(wfo_module, "_signal_cost_bps", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(wfo_module, "_valid_candidate", lambda *_args, **_kwargs: (True, None))
    monkeypatch.setattr(wfo_module, "_simulate_candidate_with_execution_kelly", lambda **_kwargs: (fake_sim, _kwargs["stock_config"], None, []))
    monkeypatch.setattr(wfo_module, "_simulate_candidate", lambda **_kwargs: fake_sim)
    monkeypatch.setattr(wfo_module, "_trade_ledger", lambda *_args, **_kwargs: pd.DataFrame([{"net_pnl": 1.0}]))
    monkeypatch.setattr(wfo_module, "compute_prom", lambda *_args, **_kwargs: 1.0)
    monkeypatch.setattr(wfo_module, "evaluate_optimization_profile", lambda *_args, **_kwargs: fake_profile)
    monkeypatch.setattr(wfo_module, "compute_wfe", lambda *_args, **_kwargs: 0.4)
    monkeypatch.setattr(wfo_module, "compute_robustness_ratio", lambda *_args, **_kwargs: 0.4)
    monkeypatch.setattr(wfo_module, "compute_single_window_dominance", lambda *_args, **_kwargs: 0.2)


def _strict_meta_for_tests() -> dict[str, int | bool | str]:
    return {
        "requested_min_walk_forwards": 1,
        "effective_min_walk_forwards": 1,
        "fallback_applied": False,
        "fallback_floor": 1,
        "top_k_folds_used": 12,
        "max_feasible_folds_before_fallback": 6,
        "status": "strict",
    }


@pytest.mark.parametrize(
    ("horizon", "expected_train", "expected_oos", "expected_step"),
    [
        ("short", 126, 21, 21),
        ("medium", 252, 63, 63),
        ("long", 504, 126, 126),
    ],
)
def test_run_stock_walk_forward_full_family_score_uses_fixed_windows_per_horizon(
    monkeypatch,
    horizon: str,
    expected_train: int,
    expected_oos: int,
    expected_step: int,
) -> None:
    bars = _build_ohlcv_bars(periods=5000, start="2010-01-01")
    stock_config = _build_full_family_score_stock_config()
    _patch_minimal_wfo_not_viable_runtime(monkeypatch)

    def _forbidden_builder(**_kwargs):
        raise AssertionError("strict/legacy window builders must be bypassed in full family-score fixed mode")

    monkeypatch.setattr(wfo_module, "_strict_fold_driven_configs", _forbidden_builder)
    monkeypatch.setattr(wfo_module, "_window_configs", _forbidden_builder)

    result = wfo_module.run_stock_walk_forward(
        symbol="IAM",
        strategy_id="strategy-1",
        strategy_name="All Consensus",
        side_policy="long_only",
        horizon=horizon,
        timeframe="1D",
        stock_config=stock_config,
        bars=bars,
        start_date=None,
        end_date=None,
        allocated_capital=100_000.0,
        cost_model_raw={},
        volume_gate={},
        cooldown_bars=0,
        wfo_config={
            "window_policy": "strict_fold_driven",
            "min_walk_forwards": 1,
            "test_period_start": "2022-01-01",
            "test_period_end": "2022-06-30",
        },
    )

    assert result["status"] == "not_viable"
    winning = result["result"]["winning_config"]
    assert winning["train_bars"] == expected_train
    assert winning["oos_bars"] == expected_oos
    diagnostics = result["result"]["diagnostics"]
    assert diagnostics["window_policy"] == "family_score_fixed"
    assert diagnostics["policy"]["window_policy_used"] == "family_score_fixed"
    fixed_meta = diagnostics["policy"]["family_score_fixed"]
    assert fixed_meta["horizon"] == horizon
    assert fixed_meta["train_bars"] == expected_train
    assert fixed_meta["oos_bars"] == expected_oos
    assert fixed_meta["step_bars"] == expected_step


def test_run_stock_walk_forward_full_family_score_overrides_legacy_policy_inputs(monkeypatch) -> None:
    bars = _build_ohlcv_bars(periods=5000, start="2010-01-01")
    stock_config = _build_full_family_score_stock_config()
    _patch_minimal_wfo_not_viable_runtime(monkeypatch)

    def _forbidden_builder(**_kwargs):
        raise AssertionError("strict/legacy window builders must be bypassed in full family-score fixed mode")

    monkeypatch.setattr(wfo_module, "_strict_fold_driven_configs", _forbidden_builder)
    monkeypatch.setattr(wfo_module, "_window_configs", _forbidden_builder)

    result = wfo_module.run_stock_walk_forward(
        symbol="IAM",
        strategy_id="strategy-1",
        strategy_name="All Consensus",
        side_policy="long_only",
        horizon="short",
        timeframe="1D",
        stock_config=stock_config,
        bars=bars,
        start_date=None,
        end_date=None,
        allocated_capital=100_000.0,
        cost_model_raw={},
        volume_gate={},
        cooldown_bars=0,
        wfo_config={
            "window_policy": "legacy_ratio_scan",
            "is_oos_ratios": [],
            "top_k_folds": 17,
            "strict_fallback_enabled": True,
            "strict_fallback_floor": 2,
            "min_walk_forwards": 1,
            "test_period_start": "2022-01-01",
            "test_period_end": "2022-06-30",
        },
    )

    assert result["status"] == "not_viable"
    diagnostics = result["result"]["diagnostics"]
    assert diagnostics["window_policy"] == "family_score_fixed"
    policy = diagnostics["policy"]
    assert policy["window_policy_used"] == "family_score_fixed"
    assert policy["ignored_inputs"] == [
        "window_policy",
        "is_oos_ratios",
        "top_k_folds",
        "strict_fallback_enabled",
        "strict_fallback_floor",
    ]
    assert policy["family_score_fixed"]["requested_window_policy"] == "legacy_ratio_scan"
    assert policy["family_score_fixed"]["requested_is_oos_ratios"] == [0.25, 0.3, 0.35]


def test_run_stock_walk_forward_mixed_family_mode_keeps_strict_window_builder(monkeypatch) -> None:
    bars = _build_ohlcv_bars(periods=1800, start="2018-01-01")
    stock_config = _build_mixed_family_score_stock_config()
    _patch_minimal_wfo_not_viable_runtime(monkeypatch)

    strict_config = WalkForwardConfig(train_bars=210, oos_bars=63, step_bars=63, min_walk_forwards=1)
    monkeypatch.setattr(wfo_module, "_strict_fold_driven_configs", lambda **_kwargs: ([strict_config], _strict_meta_for_tests()))
    monkeypatch.setattr(wfo_module, "_window_configs", lambda **_kwargs: (_ for _ in ()).throw(AssertionError("legacy builder should not run")))

    result = wfo_module.run_stock_walk_forward(
        symbol="IAM",
        strategy_id="strategy-1",
        strategy_name="Mixed Mode",
        side_policy="long_only",
        horizon="short",
        timeframe="1D",
        stock_config=stock_config,
        bars=bars,
        start_date=None,
        end_date=None,
        allocated_capital=100_000.0,
        cost_model_raw={},
        volume_gate={},
        cooldown_bars=0,
        wfo_config={
            "window_policy": "strict_fold_driven",
            "min_walk_forwards": 1,
            "test_period_start": "2021-12-01",
            "test_period_end": "2022-02-01",
        },
    )

    assert result["status"] == "not_viable"
    diagnostics = result["result"]["diagnostics"]
    assert diagnostics["window_policy"] == "strict_fold_driven"
    assert diagnostics["policy"]["window_policy_used"] == "strict_fold_driven"
    assert result["result"]["winning_config"]["train_bars"] == 210
    assert result["result"]["winning_config"]["oos_bars"] == 63


def test_run_stock_walk_forward_full_family_score_feasibility_error_is_mode_specific() -> None:
    bars = _build_ohlcv_bars(periods=560, start="2020-01-01")
    stock_config = _build_full_family_score_stock_config()

    with pytest.raises(ValueError, match="fixed-window family-score WFO configuration"):
        wfo_module.run_stock_walk_forward(
            symbol="IAM",
            strategy_id="strategy-1",
            strategy_name="All Consensus",
            side_policy="long_only",
            horizon="short",
            timeframe="1D",
            stock_config=stock_config,
            bars=bars,
            start_date=None,
            end_date=None,
            allocated_capital=100_000.0,
            cost_model_raw={},
            volume_gate={},
            cooldown_bars=0,
            wfo_config={
                "window_policy": "strict_fold_driven",
                "min_walk_forwards": 5,
                "test_period_start": "2021-06-01",
                "test_period_end": "2021-07-01",
            },
        )


def test_run_stock_walk_forward_full_family_score_short_pretest_1260_regression(monkeypatch) -> None:
    bars = _build_ohlcv_bars(periods=1800, start="2018-01-01")
    stock_config = _build_full_family_score_stock_config()
    _patch_minimal_wfo_not_viable_runtime(monkeypatch)

    def _forbidden_builder(**_kwargs):
        raise AssertionError("strict/legacy window builders must be bypassed in full family-score fixed mode")

    monkeypatch.setattr(wfo_module, "_strict_fold_driven_configs", _forbidden_builder)
    monkeypatch.setattr(wfo_module, "_window_configs", _forbidden_builder)

    test_period_start = pd.Timestamp(bars.index[1260]).date().isoformat()
    test_period_end = pd.Timestamp(bars.index[1320]).date().isoformat()
    result = wfo_module.run_stock_walk_forward(
        symbol="IAM",
        strategy_id="strategy-1",
        strategy_name="All Consensus",
        side_policy="long_only",
        horizon="short",
        timeframe="1D",
        stock_config=stock_config,
        bars=bars,
        start_date=None,
        end_date=None,
        allocated_capital=100_000.0,
        cost_model_raw={},
        volume_gate={},
        cooldown_bars=0,
        wfo_config={
            "window_policy": "strict_fold_driven",
            "min_walk_forwards": 5,
            "test_period_start": test_period_start,
            "test_period_end": test_period_end,
        },
    )

    assert result["status"] in {"succeeded", "not_viable"}
    assert result["result"]["diagnostics"]["window_policy"] == "family_score_fixed"
    assert result["result"]["diagnostics"]["policy"]["window_policy_used"] == "family_score_fixed"


def test_run_stock_walk_forward_short_strict_applies_oos_cap_before_eval(monkeypatch) -> None:
    bars = _build_wfo_short_cap_test_bars()
    stock_config = _build_wfo_short_cap_test_stock_config()
    _patch_minimal_wfo_not_viable_runtime(monkeypatch)

    mixed_configs = [
        WalkForwardConfig(train_bars=200, oos_bars=60, step_bars=60, min_walk_forwards=1),
        WalkForwardConfig(train_bars=220, oos_bars=80, step_bars=80, min_walk_forwards=1),
    ]
    monkeypatch.setattr(wfo_module, "_strict_fold_driven_configs", lambda **_kwargs: (mixed_configs, _strict_meta_for_tests()))

    result = wfo_module.run_stock_walk_forward(
        symbol="IAM",
        strategy_id="strategy-1",
        strategy_name="Desk Strategy",
        side_policy="long_only",
        horizon="short",
        timeframe="1D",
        stock_config=stock_config,
        bars=bars,
        start_date=None,
        end_date=None,
        allocated_capital=100_000.0,
        cost_model_raw={},
        volume_gate={},
        cooldown_bars=0,
        wfo_config={
            "window_policy": "strict_fold_driven",
            "min_walk_forwards": 1,
            "test_period_start": "2021-06-01",
            "test_period_end": "2021-12-31",
        },
    )

    tested = list(((result.get("result") or {}).get("all_configs_tested") or []))
    assert tested
    assert all(int(item["oos_bars"]) < 70 for item in tested)
    diagnostics = dict(((result.get("result") or {}).get("diagnostics") or {}))
    assert diagnostics["short_oos_cap_max_exclusive"] == 70
    assert diagnostics["short_oos_cap_applied"] is True
    assert diagnostics["short_oos_cap_fallback_used"] is False
    assert diagnostics["short_oos_cap_filtered_count"] == 1


def test_run_stock_walk_forward_short_legacy_applies_oos_cap_before_eval(monkeypatch) -> None:
    bars = _build_wfo_short_cap_test_bars()
    stock_config = _build_wfo_short_cap_test_stock_config()
    _patch_minimal_wfo_not_viable_runtime(monkeypatch)

    mixed_configs = [
        WalkForwardConfig(train_bars=210, oos_bars=65, step_bars=65, min_walk_forwards=1),
        WalkForwardConfig(train_bars=240, oos_bars=90, step_bars=90, min_walk_forwards=1),
    ]
    monkeypatch.setattr(wfo_module, "_window_configs", lambda **_kwargs: mixed_configs)

    result = wfo_module.run_stock_walk_forward(
        symbol="IAM",
        strategy_id="strategy-1",
        strategy_name="Desk Strategy",
        side_policy="long_only",
        horizon="short",
        timeframe="1D",
        stock_config=stock_config,
        bars=bars,
        start_date=None,
        end_date=None,
        allocated_capital=100_000.0,
        cost_model_raw={},
        volume_gate={},
        cooldown_bars=0,
        wfo_config={
            "window_policy": "legacy_ratio_scan",
            "is_oos_ratios": [0.25],
            "min_walk_forwards": 1,
            "test_period_start": "2021-06-01",
            "test_period_end": "2021-12-31",
        },
    )

    tested = list(((result.get("result") or {}).get("all_configs_tested") or []))
    assert tested
    assert all(int(item["oos_bars"]) < 70 for item in tested)
    diagnostics = dict(((result.get("result") or {}).get("diagnostics") or {}))
    assert diagnostics["short_oos_cap_max_exclusive"] == 70
    assert diagnostics["short_oos_cap_applied"] is True
    assert diagnostics["short_oos_cap_fallback_used"] is False
    assert diagnostics["short_oos_cap_filtered_count"] == 1


def test_run_stock_walk_forward_short_oos_cap_fallback_keeps_uncapped_configs(monkeypatch) -> None:
    bars = _build_wfo_short_cap_test_bars()
    stock_config = _build_wfo_short_cap_test_stock_config()
    _patch_minimal_wfo_not_viable_runtime(monkeypatch)

    uncapped_only_configs = [
        WalkForwardConfig(train_bars=220, oos_bars=80, step_bars=80, min_walk_forwards=1),
        WalkForwardConfig(train_bars=260, oos_bars=90, step_bars=90, min_walk_forwards=1),
    ]
    monkeypatch.setattr(wfo_module, "_strict_fold_driven_configs", lambda **_kwargs: (uncapped_only_configs, _strict_meta_for_tests()))

    result = wfo_module.run_stock_walk_forward(
        symbol="IAM",
        strategy_id="strategy-1",
        strategy_name="Desk Strategy",
        side_policy="long_only",
        horizon="short",
        timeframe="1D",
        stock_config=stock_config,
        bars=bars,
        start_date=None,
        end_date=None,
        allocated_capital=100_000.0,
        cost_model_raw={},
        volume_gate={},
        cooldown_bars=0,
        wfo_config={
            "window_policy": "strict_fold_driven",
            "min_walk_forwards": 1,
            "test_period_start": "2021-06-01",
            "test_period_end": "2021-12-31",
        },
    )

    tested = list(((result.get("result") or {}).get("all_configs_tested") or []))
    assert tested
    assert any(int(item["oos_bars"]) >= 70 for item in tested)
    diagnostics = dict(((result.get("result") or {}).get("diagnostics") or {}))
    assert diagnostics["short_oos_cap_max_exclusive"] == 70
    assert diagnostics["short_oos_cap_applied"] is False
    assert diagnostics["short_oos_cap_fallback_used"] is True
    assert diagnostics["short_oos_cap_filtered_count"] == 0
    warning_messages = list(diagnostics.get("warnings") or [])
    assert warning_messages
    assert "Short-horizon OOS cap (<70 bars) was not feasible" in warning_messages[0]


def test_run_stock_walk_forward_non_short_does_not_apply_oos_cap(monkeypatch) -> None:
    bars = _build_wfo_short_cap_test_bars()
    stock_config = _build_wfo_short_cap_test_stock_config()
    _patch_minimal_wfo_not_viable_runtime(monkeypatch)

    mixed_configs = [
        WalkForwardConfig(train_bars=200, oos_bars=60, step_bars=60, min_walk_forwards=1),
        WalkForwardConfig(train_bars=220, oos_bars=80, step_bars=80, min_walk_forwards=1),
    ]
    monkeypatch.setattr(wfo_module, "_strict_fold_driven_configs", lambda **_kwargs: (mixed_configs, _strict_meta_for_tests()))

    result = wfo_module.run_stock_walk_forward(
        symbol="IAM",
        strategy_id="strategy-1",
        strategy_name="Desk Strategy",
        side_policy="long_only",
        horizon="medium",
        timeframe="1D",
        stock_config=stock_config,
        bars=bars,
        start_date=None,
        end_date=None,
        allocated_capital=100_000.0,
        cost_model_raw={},
        volume_gate={},
        cooldown_bars=0,
        wfo_config={
            "window_policy": "strict_fold_driven",
            "min_walk_forwards": 1,
            "test_period_start": "2021-06-01",
            "test_period_end": "2021-12-31",
        },
    )

    tested = list(((result.get("result") or {}).get("all_configs_tested") or []))
    assert tested
    assert any(int(item["oos_bars"]) >= 70 for item in tested)
    diagnostics = dict(((result.get("result") or {}).get("diagnostics") or {}))
    assert diagnostics["short_oos_cap_max_exclusive"] == 70
    assert diagnostics["short_oos_cap_applied"] is False
    assert diagnostics["short_oos_cap_fallback_used"] is False
    assert diagnostics["short_oos_cap_filtered_count"] == 0


def test_run_stock_walk_forward_downsamples_candidates_instead_of_raising(monkeypatch) -> None:
    bars = _build_wfo_short_cap_test_bars()
    _patch_minimal_wfo_not_viable_runtime(monkeypatch)

    stock_config = {
        "signal_construction": {
            "families": {
                "sma": {
                    "enabled": True,
                    "source_mode": "indicator_rows",
                    "rows": [
                        {
                            "id": "sma_row_1",
                            "enabled": True,
                            "score_key": "trend_score",
                            "label": "Trend Score",
                            "params": {
                                "window": {"mode": "wfo", "value": 10, "scan_min": 10, "scan_max": 13, "scan_step": 1}
                            },
                        }
                    ],
                },
                "rsi": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                "macd": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                "obv": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
            }
        },
        "entry_rules": [
            {
                "id": "entry_1",
                "label": "Entry 1",
                "conditions": [{"variable": "consensus_score", "operator": ">=", "threshold": {"mode": "manual", "value": 0.5}}],
                "sizing": {"mode": "manual", "manual_pct": 25},
            }
        ],
        "exit_rules": [
            {
                "id": "exit_1",
                "label": "Exit 1",
                "conditions": [{"variable": "consensus_score", "operator": "<=", "threshold": {"mode": "manual", "value": -0.5}}],
                "sizing": {"mode": "manual", "manual_pct": 100},
            }
        ],
        "risk": {
            "stop_loss": {"mode": "atr_based", "atr_multiplier": {"mode": "wfo", "value": 1, "scan_min": 1, "scan_max": 4, "scan_step": 1}},
            "take_profit": {"mode": "rr_target", "rr_ratio": {"mode": "wfo", "value": 1, "scan_min": 1, "scan_max": 4, "scan_step": 1}},
            "cooldown_bars": {"mode": "manual", "value": 0},
            "time_stop": {"enabled": True, "bars": {"mode": "manual", "value": 30}},
            "trailing_stop_enabled": False,
            "max_position_pct": 20,
        },
    }

    monkeypatch.setattr(wfo_module, "_MAX_CANDIDATE_TUPLES", 16)
    monkeypatch.setattr(
        wfo_module,
        "_strict_fold_driven_configs",
        lambda **_kwargs: ([WalkForwardConfig(train_bars=200, oos_bars=60, step_bars=60, min_walk_forwards=1)], _strict_meta_for_tests()),
    )

    result = wfo_module.run_stock_walk_forward(
        symbol="ADH",
        strategy_id="strategy-1",
        strategy_name="Desk Strategy",
        side_policy="long_only",
        horizon="short",
        timeframe="1D",
        stock_config=stock_config,
        bars=bars,
        start_date=None,
        end_date=None,
        allocated_capital=100_000.0,
        cost_model_raw={},
        volume_gate={},
        cooldown_bars=0,
        wfo_config={
            "window_policy": "strict_fold_driven",
            "min_walk_forwards": 1,
            "test_period_start": "2021-06-01",
            "test_period_end": "2021-12-31",
        },
    )

    assert result["status"] == "not_viable"
    assert result["summary"]["candidate_count_raw"] == 64
    assert result["summary"]["candidate_count"] == 16
    guardrail = ((result.get("result") or {}).get("diagnostics") or {}).get("candidate_guardrail") or {}
    assert guardrail.get("applied") is True
    assert guardrail.get("raw_candidate_count") == 64
    assert guardrail.get("effective_candidate_count") == 16
    warning_messages = list((((result.get("result") or {}).get("diagnostics") or {}).get("warnings") or []))
    assert any("downsampled from 64 to 16" in message for message in warning_messages)


def test_run_stock_walk_forward_accepts_single_param_and_uses_explicit_test_window(monkeypatch) -> None:
    bars = pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(900)],
            "High": [101.0 + i for i in range(900)],
            "Low": [99.0 + i for i in range(900)],
            "Close": [100.0 + i for i in range(900)],
            "Volume": [1_000.0] * 900,
        },
        index=pd.date_range("2020-01-01", periods=900, freq="D"),
    )
    stock_config = {
        "signal_construction": {
            "families": {
                "sma": {
                    "enabled": True,
                    "source_mode": "indicator_rows",
                    "rows": [
                        {
                            "id": "sma_row_1",
                            "enabled": True,
                            "score_key": "trend_score",
                            "label": "Trend Score",
                            "params": {
                                "window": {"mode": "wfo", "value": 20, "scan_min": 20, "scan_max": 40, "scan_step": 20}
                            },
                        }
                    ],
                },
                "rsi": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                "macd": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                "obv": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
            }
        },
        "entry_rules": [
            {
                "id": "entry_1",
                "label": "Entry 1",
                "conditions": [
                    {
                        "variable": "consensus_score",
                        "operator": ">=",
                        "threshold": {"mode": "manual", "value": 0.5},
                    }
                ],
                "sizing": {"mode": "manual", "manual_pct": 25},
            }
        ],
        "exit_rules": [
            {
                "id": "exit_1",
                "label": "Exit 1",
                "conditions": [
                    {
                        "variable": "consensus_score",
                        "operator": "<=",
                        "threshold": {"mode": "manual", "value": -0.5},
                    }
                ],
                "sizing": {"mode": "manual", "manual_pct": 100},
            }
        ],
        "risk": {
            "stop_loss": {"mode": "atr_based", "atr_multiplier": {"mode": "manual", "value": 1.5}},
            "take_profit": {"mode": "rr_target", "rr_ratio": {"mode": "manual", "value": 1.5}},
            "cooldown_bars": {"mode": "manual", "value": 0},
            "time_stop": {"enabled": True, "bars": {"mode": "manual", "value": 30}},
            "trailing_stop_enabled": False,
            "max_position_pct": 20,
        },
    }

    fake_sim = SimpleNamespace(
        summary_metrics={"total_return": 0.1},
        equity=pd.Series([100_000.0, 101_000.0, 102_000.0], index=pd.date_range("2022-01-01", periods=3, freq="D")),
        fills=pd.DataFrame(),
    )
    fake_dsr = SimpleNamespace(
        observed_sharpe=1.0,
        benchmark_sharpe=0.5,
        dsr_statistic=1.2,
        p_value=0.1,
        skewness=0.0,
        kurtosis=3.0,
        n_trades=10,
        n_variants=2,
        significant=False,
    )
    fake_kelly = SimpleNamespace(
        fraction=0.2,
        half_kelly=0.1,
        win_rate=0.55,
        wl_ratio=1.4,
        n_trades=40,
        reason=None,
        warning=None,
    )

    monkeypatch.setattr(wfo_module, "_build_cost_model", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(wfo_module, "_signal_cost_bps", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(wfo_module, "_valid_candidate", lambda *_args, **_kwargs: (True, None))
    monkeypatch.setattr(wfo_module, "_simulate_candidate_with_execution_kelly", lambda **_kwargs: (fake_sim, _kwargs["stock_config"], None, []))
    monkeypatch.setattr(wfo_module, "_simulate_candidate", lambda **_kwargs: fake_sim)
    monkeypatch.setattr(wfo_module, "_trade_ledger", lambda *_args, **_kwargs: pd.DataFrame([{"r_multiple": 1.0}]))
    monkeypatch.setattr(wfo_module, "compute_prom", lambda *_args, **_kwargs: 1.0)
    monkeypatch.setattr(wfo_module, "compute_wfe", lambda *_args, **_kwargs: 0.8)
    monkeypatch.setattr(wfo_module, "compute_robustness_ratio", lambda *_args, **_kwargs: 0.7)
    monkeypatch.setattr(wfo_module, "compute_single_window_dominance", lambda *_args, **_kwargs: 0.2)
    monkeypatch.setattr(wfo_module, "_simulation_returns", lambda *_args, **_kwargs: [0.01] * 40)
    monkeypatch.setattr(wfo_module, "compute_trade_stats", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(wfo_module, "compute_kelly_fraction", lambda *_args, **_kwargs: fake_kelly)
    monkeypatch.setattr(wfo_module, "deflated_sharpe_ratio", lambda *_args, **_kwargs: fake_dsr)
    monkeypatch.setattr(
        wfo_module,
        "_bootstrap_payload",
        lambda **_kwargs: {"enabled": False, "warning": None, "method": "circular_block_bootstrap", "n_paths": 1000, "block_length": None},
    )

    result = wfo_module.run_stock_walk_forward(
        symbol="IAM",
        strategy_id="strategy-1",
        strategy_name="Desk Strategy",
        side_policy="long_only",
        horizon="short",
        timeframe="1D",
        stock_config=stock_config,
        bars=bars,
        start_date=None,
        end_date=None,
        allocated_capital=100_000.0,
        cost_model_raw={},
        volume_gate={},
        cooldown_bars=0,
        wfo_config={
            "is_oos_ratios": [0.25],
            "min_walk_forwards": 1,
            "test_period_start": "2022-01-01",
            "test_period_end": "2022-01-31",
        },
    )

    assert result["status"] == "succeeded"
    assert result["result"]["test_period"]["start_date"] == "2022-01-01"
    assert result["result"]["test_period"]["end_date"] == "2022-01-31"
    assert result["result"]["available_wfo_bars"] == len(bars.loc[bars.index < pd.Timestamp("2022-01-01")])
    assert result["result"]["windows"]
    assert "detail" not in result["result"]["windows"][0]
    assert result["result"]["windows"][0]["summary"]["window_index"] == result["result"]["windows"][0]["window_index"]
    assert "detail" in result["windows"][0]
    diagnostics = result["result"]["diagnostics"]
    assert diagnostics["window_policy"] == "strict_fold_driven"
    assert diagnostics["policy"]["ignored_inputs"] == ["is_oos_ratios"]


def test_run_stock_walk_forward_not_viable_keeps_summary_windows_in_result(monkeypatch) -> None:
    bars = pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(900)],
            "High": [101.0 + i for i in range(900)],
            "Low": [99.0 + i for i in range(900)],
            "Close": [100.0 + i for i in range(900)],
            "Volume": [1_000.0] * 900,
        },
        index=pd.date_range("2020-01-01", periods=900, freq="D"),
    )
    stock_config = {
        "signal_construction": {
            "families": {
                "sma": {
                    "enabled": True,
                    "source_mode": "indicator_rows",
                    "rows": [
                        {
                            "id": "sma_row_1",
                            "enabled": True,
                            "score_key": "trend_score",
                            "label": "Trend Score",
                            "params": {
                                "window": {"mode": "wfo", "value": 20, "scan_min": 20, "scan_max": 40, "scan_step": 20}
                            },
                        }
                    ],
                },
                "rsi": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                "macd": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                "obv": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
            }
        },
        "entry_rules": [
            {
                "id": "entry_1",
                "label": "Entry 1",
                "conditions": [
                    {
                        "variable": "consensus_score",
                        "operator": ">=",
                        "threshold": {"mode": "manual", "value": 0.5},
                    }
                ],
                "sizing": {"mode": "manual", "manual_pct": 25},
            }
        ],
        "exit_rules": [
            {
                "id": "exit_1",
                "label": "Exit 1",
                "conditions": [
                    {
                        "variable": "consensus_score",
                        "operator": "<=",
                        "threshold": {"mode": "manual", "value": -0.5},
                    }
                ],
                "sizing": {"mode": "manual", "manual_pct": 100},
            }
        ],
        "risk": {
            "stop_loss": {"mode": "atr_based", "atr_multiplier": {"mode": "manual", "value": 1.5}},
            "take_profit": {"mode": "rr_target", "rr_ratio": {"mode": "manual", "value": 1.5}},
            "cooldown_bars": {"mode": "manual", "value": 0},
            "time_stop": {"enabled": True, "bars": {"mode": "manual", "value": 30}},
            "trailing_stop_enabled": False,
            "max_position_pct": 20,
        },
    }

    fake_sim = SimpleNamespace(
        summary_metrics={"total_return": 0.05},
        equity=pd.Series([100_000.0, 100_500.0, 101_000.0], index=pd.date_range("2022-01-01", periods=3, freq="D")),
        fills=pd.DataFrame(),
    )
    fake_profile = SimpleNamespace(
        passes=True,
        reason="stable neighborhood",
        detail="Profile stayed smooth.",
        pct_profitable=0.5,
        winner_smoothed_prom=1.0,
        neighborhood_cv=0.1,
        warnings=[],
    )

    monkeypatch.setattr(wfo_module, "_build_cost_model", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(wfo_module, "_signal_cost_bps", lambda *_args, **_kwargs: 0.0)
    monkeypatch.setattr(wfo_module, "_valid_candidate", lambda *_args, **_kwargs: (True, None))
    monkeypatch.setattr(wfo_module, "_simulate_candidate_with_execution_kelly", lambda **_kwargs: (fake_sim, _kwargs["stock_config"], None, []))
    monkeypatch.setattr(wfo_module, "_simulate_candidate", lambda **_kwargs: fake_sim)
    monkeypatch.setattr(wfo_module, "_trade_ledger", lambda *_args, **_kwargs: pd.DataFrame([{"r_multiple": 1.0}]))
    monkeypatch.setattr(wfo_module, "compute_prom", lambda *_args, **_kwargs: 1.0)
    monkeypatch.setattr(wfo_module, "evaluate_optimization_profile", lambda *_args, **_kwargs: fake_profile)
    monkeypatch.setattr(wfo_module, "compute_wfe", lambda *_args, **_kwargs: 0.4)
    monkeypatch.setattr(wfo_module, "compute_robustness_ratio", lambda *_args, **_kwargs: 0.4)
    monkeypatch.setattr(wfo_module, "compute_single_window_dominance", lambda *_args, **_kwargs: 0.2)

    result = wfo_module.run_stock_walk_forward(
        symbol="IAM",
        strategy_id="strategy-1",
        strategy_name="Desk Strategy",
        side_policy="long_only",
        horizon="short",
        timeframe="1D",
        stock_config=stock_config,
        bars=bars,
        start_date=None,
        end_date=None,
        allocated_capital=100_000.0,
        cost_model_raw={},
        volume_gate={},
        cooldown_bars=0,
        wfo_config={
            "is_oos_ratios": [0.25],
            "min_walk_forwards": 1,
            "test_period_start": "2022-01-01",
            "test_period_end": "2022-01-31",
        },
    )

    assert result["status"] == "not_viable"
    assert result["summary"]["rejection_reasons"]
    assert result["result"]["winning_config"]["viable"] is False
    assert result["result"]["final_params"]
    assert result["result"]["windows"]
    assert "detail" not in result["result"]["windows"][0]
    assert result["result"]["windows"][0]["summary"]["window_index"] == result["result"]["windows"][0]["window_index"]
    assert "detail" in result["windows"][0]
    diagnostics = result["result"]["diagnostics"]
    assert diagnostics["window_policy"] == "strict_fold_driven"
    assert diagnostics["policy"]["ignored_inputs"] == ["is_oos_ratios"]
