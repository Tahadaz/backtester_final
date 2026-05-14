from __future__ import annotations

import json

from fastapi.encoders import jsonable_encoder
import numpy as np
import pandas as pd
import pytest

from core.quant_core.strategy_plan.backtest import (
    _apply_exit_rules,
    _build_cost_model,
    _bucket_target_fraction,
    _entry_target_fraction,
    _simulate_stock,
    run_strategy_plan_backtest,
)
from core.quant_core.strategy_plan.score_sources import compute_strategy_score_frame


def _sample_bars() -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=8, freq="D")
    return pd.DataFrame(
        {
            "Open": [100, 101, 102, 103, 104, 105, 106, 107],
            "High": [101, 102, 103, 104, 105, 106, 107, 108],
            "Low": [99, 100, 101, 102, 103, 104, 105, 106],
            "Close": [100.5, 101.5, 102.5, 103.5, 104.5, 105.5, 106.5, 107.5],
            "Volume": [100_000, 100_000, 101_000, 102_000, 103_000, 104_000, 105_000, 106_000],
        },
        index=idx,
    )


BET_SIZING = {
    "starter_threshold": 20,
    "starter_target_pct": 25,
    "medium_threshold": 40,
    "medium_target_pct": 50,
    "large_threshold": 60,
    "large_target_pct": 75,
    "max_threshold": 80,
    "max_target_pct": 100,
    "reduce_to_large_below": 70,
    "reduce_to_medium_below": 50,
    "reduce_to_starter_below": 30,
    "exit_below": 15,
}

EXPOSURE_LADDER = [
    {"score_low": 0.0, "score_high": 29.9999, "target_exposure_pct": 0},
    {"score_low": 30.0, "score_high": 49.9999, "target_exposure_pct": 25},
    {"score_low": 50.0, "score_high": 69.9999, "target_exposure_pct": 50},
    {"score_low": 70.0, "score_high": 84.9999, "target_exposure_pct": 75},
    {"score_low": 85.0, "score_high": 100.0, "target_exposure_pct": 100},
]


def test_bucket_target_fraction_uses_exposure_ladder() -> None:
    assert _bucket_target_fraction(19, side_policy="long_only", exposure_ladder=EXPOSURE_LADDER) == 0.0
    assert _bucket_target_fraction(30, side_policy="long_only", exposure_ladder=EXPOSURE_LADDER) == 0.25
    assert _bucket_target_fraction(69, side_policy="long_only", exposure_ladder=EXPOSURE_LADDER) == 0.5
    assert _bucket_target_fraction(85, side_policy="long_only", exposure_ladder=EXPOSURE_LADDER) == 1.0
    assert _bucket_target_fraction(-61, side_policy="long_only", exposure_ladder=EXPOSURE_LADDER) == 0.0
    assert _bucket_target_fraction(-61, side_policy="long_short", exposure_ladder=EXPOSURE_LADDER) == -0.5


def test_simulate_stock_exposes_signal_score_and_ledger() -> None:
    bars = _sample_bars()
    scores = pd.Series([85, 82, 79, 75, 60, 45, 20, 10], index=bars.index, dtype="float64")

    sim = _simulate_stock(
        symbol="AAA",
        bars=bars,
        score_series=scores,
        score_frame=None,
        allocated_capital=100_000,
        side_policy="long_only",
        exposure_ladder=EXPOSURE_LADDER,
        entry_rules=[],
        exit_rules=[],
        risk={
            "max_holding_bars": 30,
            "stop_atr_multiplier": 1.5,

            "take_profit_rr": 1.5,
            "time_stop_enabled": True,
            "trailing_stop_enabled": False,
        },
        cost_model=_build_cost_model({}),
        cooldown_bars=0,
        volume_gate={"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0, "adv_window": 20},
    )

    assert not sim.equity.empty
    assert sim.per_fill_ledger
    assert "signal_score" in sim.per_fill_ledger[0]


def test_simulate_stock_does_not_fill_on_zero_volume_execution_day() -> None:
    idx = pd.date_range("2026-04-01", periods=6, freq="D")
    bars = pd.DataFrame(
        {
            "Open": [100, 101, 102, 103, 104, 105],
            "High": [101, 102, 103, 104, 105, 106],
            "Low": [99, 100, 101, 102, 103, 104],
            "Close": [100, 101, 102, 103, 104, 105],
            "Volume": [100_000, 100_000, 100_000, 0, 100_000, 100_000],
        },
        index=idx,
    )
    scores = pd.Series([85, 85, 0, 0, 0, 0], index=idx, dtype="float64")

    sim = _simulate_stock(
        symbol="AAA",
        bars=bars,
        score_series=scores,
        score_frame=None,
        allocated_capital=100_000,
        side_policy="long_only",
        exposure_ladder=EXPOSURE_LADDER,
        entry_rules=[],
        exit_rules=[],
        risk={
            "max_holding_bars": 999,
            "stop_atr_multiplier": 1000,
            "take_profit_rr": 1000,
            "time_stop_enabled": False,
            "trailing_stop_enabled": False,
        },
        cost_model=_build_cost_model({}),
        cooldown_bars=0,
        volume_gate={"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0, "adv_window": 20},
    )

    fill_dates = [row["timestamp"][:10] for row in sim.per_fill_ledger]
    assert "2026-04-04" not in fill_dates
    assert fill_dates == ["2026-04-02", "2026-04-05"]


def test_simulate_stock_does_not_rebalance_inside_same_bucket() -> None:
    idx = pd.date_range("2026-01-01", periods=7, freq="D")
    bars = pd.DataFrame(
        {
            "Open": [100, 100, 110, 120, 130, 140, 150],
            "High": [101, 101, 111, 121, 131, 141, 151],
            "Low": [99, 99, 109, 119, 129, 139, 149],
            "Close": [100, 100, 110, 120, 130, 140, 150],
            "Volume": [100_000] * 7,
        },
        index=idx,
    )
    scores = pd.Series([71, 72, 73, 74, 75, 76, 77], index=idx, dtype="float64")

    sim = _simulate_stock(
        symbol="AAA",
        bars=bars,
        score_series=scores,
        score_frame=None,
        allocated_capital=100_000,
        side_policy="long_only",
        exposure_ladder=EXPOSURE_LADDER,
        entry_rules=[],
        exit_rules=[],
        risk={
            "max_holding_bars": 999,
            "stop_atr_multiplier": 1000,

            "take_profit_rr": 1000,
            "time_stop_enabled": False,
            "trailing_stop_enabled": False,
        },
        cost_model=_build_cost_model({}),
        cooldown_bars=0,
        volume_gate={"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0, "adv_window": 20},
    )

    assert len(sim.per_fill_ledger) == 1
    assert sim.per_fill_ledger[0]["reason"] == "signal_entry"


def test_simulate_stock_executes_entry_and_exit_rules() -> None:
    bars = _sample_bars()
    score_frame = pd.DataFrame(
        {
            "trend_score": [20, 80, 80, 80, 20, 20, 20, 20],
            "momentum_score": [0, 10, 10, 10, -10, -10, -10, -10],
            "oscillation_score": [0] * 8,
            "volume_score": [0] * 8,
            "consensus_score": [20, 80, 80, 80, 20, 20, 20, 20],
        },
        index=bars.index,
        dtype="float64",
    )
    scores = score_frame["consensus_score"]

    sim = _simulate_stock(
        symbol="AAA",
        bars=bars,
        score_series=scores,
        score_frame=score_frame,
        allocated_capital=100_000,
        side_policy="long_only",
        exposure_ladder=EXPOSURE_LADDER,
        entry_rules=[
            {
                "config_option": "A",
                "label": "Entry 1",
                "conditions": [
                    {"variable": "trend_score", "operator": ">=", "threshold": {"mode": "manual", "value": 60}}
                ],
                "sizing": {"mode": "manual", "manual_pct": 50},
            }
        ],
        exit_rules=[
            {
                "config_option": "B",
                "label": "Exit 1",
                "conditions": [
                    {"variable": "momentum_score", "operator": "<=", "threshold": {"mode": "manual", "value": -5}}
                ],
                "sizing": {"mode": "manual", "manual_pct": 100},
            }
        ],
        risk={
            "max_holding_bars": 999,
            "stop_atr_multiplier": 1000,

            "take_profit_rr": 1000,
            "time_stop_enabled": False,
            "trailing_stop_enabled": False,
            "max_position_pct": 100,
        },
        cost_model=_build_cost_model({}),
        cooldown_bars=0,
        volume_gate={"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0, "adv_window": 20},
    )

    reasons = [row["reason"] for row in sim.per_fill_ledger]
    assert any(str(reason).startswith("entry_rule:") for reason in reasons)
    assert any(str(reason).startswith("exit_rule:") for reason in reasons)
    trigger_displays = [str(row.get("trigger_display", "")) for row in sim.per_fill_ledger]
    assert any(display.startswith("Entry A (") for display in trigger_displays)
    assert any(display.startswith("Exit B (") for display in trigger_displays)


def test_entry_target_fraction_evaluates_donchian_breakout_expression() -> None:
    idx = pd.date_range("2026-01-01", periods=21, freq="D")
    bars = pd.DataFrame(
        {
            "Open": np.linspace(100, 120, 21),
            "High": [100 + i for i in range(20)] + [121],
            "Low": [98 + i for i in range(21)],
            "Close": [99 + i for i in range(20)] + [120.5],
            "Volume": [100_000] * 21,
        },
        index=idx,
    )
    rule = {
        "label": "20-bar breakout",
        "rule_expression": {
            "operator": "all",
            "children": [
                {
                    "type": "breakout",
                    "direction": "above",
                    "source": {"kind": "price", "field": "Close"},
                    "level": {"kind": "rolling", "function": "highest", "field": "High", "lookback": 20, "offset": 1},
                }
            ],
        },
        "sizing": {"mode": "manual", "manual_pct": 25},
    }

    target, matched = _entry_target_fraction(
        snapshot={"consensus_score": 0.0},
        entry_rules=[rule],
        previous_fraction=0.0,
        side_policy="long_only",
        max_fraction=1.0,
        bars=bars,
        index=20,
    )

    assert matched is rule
    assert target == pytest.approx(0.25)


def test_entry_target_fraction_evaluates_moving_average_cross_expression() -> None:
    idx = pd.date_range("2026-02-01", periods=7, freq="D")
    bars = pd.DataFrame(
        {
            "Open": [10, 10, 10, 10, 8, 8, 14],
            "High": [11, 11, 11, 11, 9, 9, 15],
            "Low": [9, 9, 9, 9, 7, 7, 13],
            "Close": [10, 10, 10, 10, 8, 8, 14],
            "Volume": [100_000] * 7,
        },
        index=idx,
    )
    rule = {
        "label": "fast over slow",
        "rule_expression": {
            "operator": "all",
            "children": [
                {
                    "type": "cross",
                    "direction": "above",
                    "left": {"kind": "indicator", "name": "sma", "window": 2},
                    "right": {"kind": "indicator", "name": "sma", "window": 3},
                }
            ],
        },
        "sizing": {"mode": "manual", "manual_pct": 40},
    }

    target, matched = _entry_target_fraction(
        snapshot={"consensus_score": 0.0},
        entry_rules=[rule],
        previous_fraction=0.0,
        side_policy="long_only",
        max_fraction=1.0,
        bars=bars,
        index=6,
    )

    assert matched is rule
    assert target == pytest.approx(0.4)


def test_simulate_stock_executes_price_expression_rules() -> None:
    idx = pd.date_range("2026-03-01", periods=24, freq="D")
    bars = pd.DataFrame(
        {
            "Open": [100 + i for i in range(24)],
            "High": [101 + i for i in range(20)] + [125, 126, 127, 128],
            "Low": [99 + i for i in range(24)],
            "Close": [100 + i for i in range(20)] + [124, 125, 126, 127],
            "Volume": [100_000] * 24,
        },
        index=idx,
    )
    scores = pd.Series([0.0] * len(bars), index=bars.index)
    score_frame = pd.DataFrame({"consensus_score": scores}, index=bars.index, dtype="float64")

    sim = _simulate_stock(
        symbol="AAA",
        bars=bars,
        score_series=scores,
        score_frame=score_frame,
        allocated_capital=100_000,
        side_policy="long_only",
        exposure_ladder=EXPOSURE_LADDER,
        entry_rules=[
            {
                "config_option": "A",
                "label": "Donchian entry",
                "rule_expression": {
                    "operator": "all",
                    "children": [
                        {
                            "type": "breakout",
                            "direction": "above",
                            "source": {"kind": "price", "field": "Close"},
                            "level": {"kind": "rolling", "function": "highest", "field": "High", "lookback": 20, "offset": 1},
                        }
                    ],
                },
                "sizing": {"mode": "manual", "manual_pct": 50},
            }
        ],
        exit_rules=[],
        risk={
            "max_holding_bars": 999,
            "stop_atr_multiplier": 1000,
            "take_profit_rr": 1000,
            "time_stop_enabled": False,
            "trailing_stop_enabled": False,
            "max_position_pct": 100,
        },
        cost_model=_build_cost_model({}),
        cooldown_bars=0,
        volume_gate={"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0, "adv_window": 20},
    )

    assert any(str(row["reason"]).startswith("entry_rule:") for row in sim.per_fill_ledger)
    assert any(row["entry_rule"] == "A - Donchian entry" for row in sim.per_fill_ledger)


def test_simulate_stock_rule_conditions_can_use_custom_score_frame_columns() -> None:
    bars = _sample_bars()
    score_frame = pd.DataFrame(
        {
            "custom_edge_score": [0, 0, 80, 80, 80, 80, 80, 80],
            "consensus_score": [0] * 8,
        },
        index=bars.index,
        dtype="float64",
    )

    sim = _simulate_stock(
        symbol="AAA",
        bars=bars,
        score_series=score_frame["consensus_score"],
        score_frame=score_frame,
        allocated_capital=100_000,
        side_policy="long_only",
        exposure_ladder=EXPOSURE_LADDER,
        entry_rules=[
            {
                "config_option": "A",
                "label": "Custom score",
                "conditions": [
                    {"variable": "custom_edge_score", "operator": ">=", "threshold": {"mode": "manual", "value": 60}}
                ],
                "sizing": {"mode": "manual", "manual_pct": 50},
            }
        ],
        exit_rules=[],
        risk={
            "max_holding_bars": 999,
            "stop_atr_multiplier": 1000,
            "take_profit_rr": 1000,
            "time_stop_enabled": False,
            "trailing_stop_enabled": False,
            "max_position_pct": 100,
        },
        cost_model=_build_cost_model({}),
        cooldown_bars=0,
        volume_gate={"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0, "adv_window": 20},
    )

    assert any(str(row["reason"]).startswith("entry_rule:") for row in sim.per_fill_ledger)


def test_entry_target_fraction_uses_direct_wfo_size_pct() -> None:
    target, matched = _entry_target_fraction(
        snapshot={"consensus_score": 80.0},
        entry_rules=[
            {
                "config_option": "A",
                "label": "Entry WFO",
                "conditions": [
                    {"variable": "consensus_score", "operator": ">=", "threshold": {"mode": "manual", "value": 60}}
                ],
                "sizing": {
                    "mode": "wfo",
                    "manual_pct": 25,
                    "size_pct": {"mode": "wfo", "value": 50},
                },
            }
        ],
        previous_fraction=0.0,
        side_policy="long_only",
        max_fraction=1.0,
    )

    assert matched is not None
    assert target == pytest.approx(0.5)


def test_apply_exit_rules_uses_direct_wfo_reduction_pct() -> None:
    target, matched = _apply_exit_rules(
        snapshot={"consensus_score": -10.0},
        exit_rules=[
            {
                "config_option": "B",
                "label": "Exit WFO",
                "conditions": [
                    {"variable": "consensus_score", "operator": "<=", "threshold": {"mode": "manual", "value": -5}}
                ],
                "sizing": {
                    "mode": "wfo",
                    "manual_pct": 100,
                    "reduction_pct": {"mode": "wfo", "value": 50},
                },
            }
        ],
        target_fraction=1.0,
    )

    assert matched is not None
    assert target == pytest.approx(0.5)


def test_entry_target_fraction_uses_execution_kelly_times_modifier() -> None:
    target, matched = _entry_target_fraction(
        snapshot={"consensus_score": 80.0},
        entry_rules=[
            {
                "config_option": "A",
                "label": "Entry Kelly",
                "conditions": [
                    {"variable": "consensus_score", "operator": ">=", "threshold": {"mode": "manual", "value": 60}}
                ],
                "sizing": {
                    "mode": "kelly_wfo",
                    "manual_pct": 25,
                    "execution_kelly_fraction": 0.4,
                    "kelly_modifier": {"mode": "manual", "value": 0.5},
                },
            }
        ],
        previous_fraction=0.0,
        side_policy="long_only",
        max_fraction=1.0,
    )

    assert matched is not None
    assert target == pytest.approx(0.2)


def test_kelly_rule_falls_back_to_manual_pct_when_execution_kelly_missing() -> None:
    target, matched = _entry_target_fraction(
        snapshot={"consensus_score": 80.0},
        entry_rules=[
            {
                "config_option": "A",
                "label": "Entry Kelly Fallback",
                "conditions": [
                    {"variable": "consensus_score", "operator": ">=", "threshold": {"mode": "manual", "value": 60}}
                ],
                "sizing": {
                    "mode": "kelly_wfo",
                    "manual_pct": 30,
                    "kelly_modifier": {"mode": "manual", "value": 0.5},
                },
            }
        ],
        previous_fraction=0.0,
        side_policy="long_only",
        max_fraction=1.0,
    )

    assert matched is not None
    assert target == pytest.approx(0.3)


def test_apply_exit_rules_uses_execution_kelly_times_modifier() -> None:
    target, matched = _apply_exit_rules(
        snapshot={"consensus_score": -10.0},
        exit_rules=[
            {
                "config_option": "B",
                "label": "Exit Kelly",
                "conditions": [
                    {"variable": "consensus_score", "operator": "<=", "threshold": {"mode": "manual", "value": -5}}
                ],
                "sizing": {
                    "mode": "kelly_wfo",
                    "manual_pct": 100,
                    "execution_kelly_fraction": 0.4,
                    "kelly_modifier": {"mode": "manual", "value": 0.5},
                },
            }
        ],
        target_fraction=1.0,
    )

    assert matched is not None
    assert target == pytest.approx(0.8)


def test_compute_strategy_score_frame_supports_multiple_indicator_rows() -> None:
    bars = _sample_bars()

    frame = compute_strategy_score_frame(
        stock_config={
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
                                "params": {"window": {"mode": "manual", "value": 2}},
                            },
                            {
                                "id": "sma_row_2",
                                "enabled": True,
                                "score_key": "trend_score_2",
                                "label": "Trend Score 2",
                                "params": {"window": {"mode": "manual", "value": 3}},
                            },
                        ],
                    },
                    "rsi": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                    "macd": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                    "obv": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                }
            }
        },
        ohlcv=bars,
        symbol="AAA",
        horizon="medium",
        timeframe="1D",
        signal_cost_bps=0.0,
        cooldown_bars=0,
    )

    assert "trend_score" in frame.columns
    assert "trend_score_2" in frame.columns
    assert "consensus_score" in frame.columns
    expected_consensus = (frame["trend_score"] + frame["trend_score_2"]) / 2.0
    pd.testing.assert_series_equal(frame["consensus_score"], expected_consensus, check_names=False)


def test_compute_strategy_score_frame_uses_family_ensemble_source(monkeypatch) -> None:
    bars = _sample_bars()

    def fake_run_family_ensemble_full(
        family_id,
        close,
        *,
        volume=None,
        symbol=None,
        horizon=None,
        timeframe=None,
        cost_bps=None,
        cooldown_bars=None,
    ):
        assert family_id == "sma"
        assert symbol == "AAA"
        return {"family": family_id, "points": len(close)}

    def fake_compute_family_score_timeseries(
        detail,
        close,
        *,
        volume=None,
        cooldown_bars=0,
        family_history_mode="static_current_reps",
        symbol=None,
        horizon=None,
        timeframe=None,
        signal_cost_bps=10.0,
    ):
        assert detail["family"] == "sma"
        assert family_history_mode == "static_current_reps"
        assert symbol == "AAA"
        assert horizon == "medium"
        assert timeframe == "1D"
        assert signal_cost_bps == 0.0
        return np.linspace(10.0, 80.0, len(close))

    monkeypatch.setattr(
        "core.quant_core.strategy_plan.score_sources.run_family_ensemble_full",
        fake_run_family_ensemble_full,
    )
    monkeypatch.setattr(
        "core.quant_core.strategy_plan.score_sources.compute_family_score_timeseries",
        fake_compute_family_score_timeseries,
    )

    frame = compute_strategy_score_frame(
        stock_config={
            "signal_construction": {
                "families": {
                    "sma": {"enabled": True, "source_mode": "family_ensemble", "rows": []},
                    "rsi": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                    "macd": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                    "obv": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                }
            }
        },
        ohlcv=bars,
        symbol="AAA",
        horizon="medium",
        timeframe="1D",
        signal_cost_bps=0.0,
        cooldown_bars=0,
    )

    assert list(frame["trend_score"]) == pytest.approx(np.linspace(10.0, 80.0, len(bars)).tolist())
    assert list(frame["consensus_score"]) == pytest.approx(list(frame["trend_score"]))


def test_compute_strategy_score_frame_forwards_dynamic_family_history_mode(monkeypatch) -> None:
    bars = _sample_bars()
    seen_modes: list[str] = []

    def fake_run_family_ensemble_full(
        family_id,
        close,
        *,
        volume=None,
        symbol=None,
        horizon=None,
        timeframe=None,
        cost_bps=None,
        cooldown_bars=None,
    ):
        return {"family": family_id, "points": len(close)}

    def fake_compute_family_score_timeseries(
        detail,
        close,
        *,
        volume=None,
        cooldown_bars=0,
        family_history_mode="static_current_reps",
        symbol=None,
        horizon=None,
        timeframe=None,
        signal_cost_bps=10.0,
    ):
        seen_modes.append(str(family_history_mode))
        return np.linspace(1.0, 2.0, len(close))

    monkeypatch.setattr(
        "core.quant_core.strategy_plan.score_sources.run_family_ensemble_full",
        fake_run_family_ensemble_full,
    )
    monkeypatch.setattr(
        "core.quant_core.strategy_plan.score_sources.compute_family_score_timeseries",
        fake_compute_family_score_timeseries,
    )

    compute_strategy_score_frame(
        stock_config={
            "signal_construction": {
                "families": {
                    "sma": {"enabled": True, "source_mode": "family_ensemble", "rows": []},
                    "rsi": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                    "macd": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                    "obv": {"enabled": False, "source_mode": "indicator_rows", "rows": []},
                }
            }
        },
        ohlcv=bars,
        symbol="AAA",
        horizon="medium",
        timeframe="1D",
        signal_cost_bps=0.0,
        cooldown_bars=0,
        family_history_mode="dynamic_point_in_time",
    )

    assert seen_modes == ["dynamic_point_in_time"]
def test_run_strategy_plan_backtest_returns_general_and_stock_sections(monkeypatch) -> None:
    bars_by_symbol = {"AAA": _sample_bars(), "BBB": _sample_bars()}

    def fake_scores(**kwargs):
        ohlcv = kwargs["ohlcv"]
        return pd.DataFrame(
            {
                "trend_score": [80.0] * len(ohlcv),
                "momentum_score": [80.0] * len(ohlcv),
                "oscillation_score": [80.0] * len(ohlcv),
                "volume_score": [80.0] * len(ohlcv),
                "consensus_score": [80.0] * len(ohlcv),
            },
            index=ohlcv.index,
            dtype="float64",
        )

    monkeypatch.setattr(
        "core.quant_core.strategy_plan.backtest._compute_score_frame",
        fake_scores,
    )

    result = run_strategy_plan_backtest(
        strategy_id="strategy-1",
        strategy_name="Desk Test",
        side_policy="long_only",
        horizon="medium",
        timeframe="1D",
        config_json={
            "capital": {"total_capital_mad": 200_000},
            "universe": {"basket": ["AAA", "BBB"]},
            "allocation": {"method": "hrp", "hrp_lookback_bars": 60, "manual_overrides_by_symbol": {}},
            "signal": {
                "enabled_families": ["sma", "rsi"],
            },
            "bet_sizing": BET_SIZING,
            "risk": {
                "max_holding_bars": 30,
                "stop_atr_multiplier": 1.5,
    
                "take_profit_rr": 1.5,
                "time_stop_enabled": True,
                "trailing_stop_enabled": False,
            },
        },
        bars_by_symbol=bars_by_symbol,
        start_date="2024-01-01",
        end_date="2024-01-08",
        cost_model_raw={"brokerage_bps": 0.2, "comm_bourse_bps": 0.1, "reg_liv_bps": 0.0, "slippage_bps": 0.0, "tva_rate": 0.1},
        volume_gate={"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0.0, "adv_window": 20},
        cooldown_bars=0,
    )

    assert "general_results" in result
    assert "stocks" in result
    assert len(result["stocks"]) == 2
    assert "cumreturn_vs_benchmark" in result["general_results"]["plots"]
    assert result["stocks"][0]["trade_ledger"]
    assert result["general_results"]["calibration"]["status"] in {"fallback", "provisional", "ok"}
    payload = jsonable_encoder(result)
    encoded = json.dumps(payload)
    assert encoded
    assert isinstance(result["general_results"]["plots"]["cumreturn_vs_benchmark"]["data"][0]["x"], list)
    assert isinstance(result["stocks"][0]["price_chart"]["data"][0]["x"], list)
    assert result["strategy"]["signal"]["enabled_families"] == ["sma", "rsi"]
    assert result["strategy"]["bet_sizing"]["mode"] == "auto_calibrated"
    assert result["strategy"]["bet_sizing"]["active_ladder"]
    assert "logic" not in result["strategy"]


def test_run_strategy_plan_backtest_accepts_legacy_logic_config(monkeypatch) -> None:
    bars = _sample_bars()
    bars_by_symbol = {"AAA": bars}

    def fake_scores(**kwargs):
        ohlcv = kwargs["ohlcv"]
        return pd.DataFrame(
            {
                "trend_score": [80.0] * len(ohlcv),
                "momentum_score": [80.0] * len(ohlcv),
                "oscillation_score": [80.0] * len(ohlcv),
                "volume_score": [80.0] * len(ohlcv),
                "consensus_score": [80.0] * len(ohlcv),
            },
            index=ohlcv.index,
            dtype="float64",
        )

    monkeypatch.setattr(
        "core.quant_core.strategy_plan.backtest._compute_score_frame",
        fake_scores,
    )

    result = run_strategy_plan_backtest(
        strategy_id="strategy-1",
        strategy_name="Desk Test",
        side_policy="long_only",
        horizon="medium",
        timeframe="1D",
        config_json={
            "capital": {"total_capital_mad": 100_000},
            "universe": {"basket": ["AAA"]},
            "allocation": {"method": "hrp", "hrp_lookback_bars": 60, "manual_overrides_by_symbol": {}},
            "logic": {
                "enabled_families": ["sma"],
                "entry_threshold": 999,
                "holding_threshold": 999,
                "exit_threshold": 999,
                "bet_sizing": BET_SIZING,
            },
            "risk": {
                "max_holding_bars": 30,
                "stop_atr_multiplier": 1.5,
    
                "take_profit_rr": 1.5,
                "time_stop_enabled": True,
                "trailing_stop_enabled": False,
            },
        },
        bars_by_symbol=bars_by_symbol,
        start_date="2024-01-01",
        end_date="2024-01-08",
        cost_model_raw={"brokerage_bps": 0.2, "comm_bourse_bps": 0.1, "reg_liv_bps": 0.0, "slippage_bps": 0.0, "tva_rate": 0.1},
        volume_gate={"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0.0, "adv_window": 20},
        cooldown_bars=0,
    )

    assert result["general_results"]["metrics"]["number_of_trades"] >= 0
    assert len(result["stocks"]) == 1
    assert result["strategy"]["enabled_families"] == ["sma"]
    assert result["strategy"]["bet_sizing"]["legacy_manual_ladder"]["exit_below"] == 15


def test_run_strategy_plan_backtest_supports_manual_per_stock_signal_and_risk(monkeypatch) -> None:
    bars_by_symbol = {"IAM": _sample_bars(), "BCP": _sample_bars()}
    calls: list[tuple[str, tuple[str, ...]]] = []

    def fake_scores(**kwargs):
        calls.append((kwargs["symbol"], tuple(kwargs["enabled_families"])))
        ohlcv = kwargs["ohlcv"]
        return pd.DataFrame(
            {
                "trend_score": [80.0] * len(ohlcv),
                "momentum_score": [80.0] * len(ohlcv),
                "oscillation_score": [80.0] * len(ohlcv),
                "volume_score": [80.0] * len(ohlcv),
                "consensus_score": [80.0] * len(ohlcv),
            },
            index=ohlcv.index,
            dtype="float64",
        )

    monkeypatch.setattr(
        "core.quant_core.strategy_plan.backtest._compute_score_frame",
        fake_scores,
    )

    result = run_strategy_plan_backtest(
        strategy_id="strategy-hetero",
        strategy_name="Manual Hetero",
        side_policy="long_only",
        horizon="medium",
        timeframe="1D",
        config_json={
            "capital": {"total_capital_mad": 200_000},
            "universe": {"basket": ["IAM", "BCP"]},
            "allocation": {"method": "hrp", "hrp_lookback_bars": 60, "manual_overrides_by_symbol": {}},
            "signal": {"enabled_families": ["sma"]},
            "bet_sizing": {
                "mode": "auto_calibrated",
                "calibration_lookback_bars": 120,
                "min_observations": 1,
                "min_bucket_observations": 1,
                "primary_metric": "avg_r_multiple",
                "bucket_count": 4,
                "exposure_levels": [0, 25, 50, 100],
                "sample_method": "event_deduped",
                "last_calibration": None,
            },
            "risk": {
                "max_holding_bars": 30,
                "stop_atr_multiplier": 1.5,
    
                "take_profit_rr": 1.5,
                "time_stop_enabled": True,
                "trailing_stop_enabled": False,
            },
            "per_stock": {
                "IAM": {
                    "signal": {"enabled_families": ["sma"]},
                    "risk": {
                        "max_holding_bars": 20,
                        "stop_atr_multiplier": 1.5,
            
                        "take_profit_rr": 1.4,
                        "time_stop_enabled": True,
                        "trailing_stop_enabled": False,
                    },
                },
                "BCP": {
                    "signal": {"enabled_families": ["rsi"]},
                    "risk": {
                        "max_holding_bars": 45,
                        "stop_atr_multiplier": 2.0,
            
                        "take_profit_rr": 2.0,
                        "time_stop_enabled": True,
                        "trailing_stop_enabled": False,
                    },
                },
            },
        },
        bars_by_symbol=bars_by_symbol,
        start_date="2024-01-01",
        end_date="2024-01-08",
        cost_model_raw={"brokerage_bps": 0.2, "comm_bourse_bps": 0.1, "reg_liv_bps": 0.0, "slippage_bps": 0.0, "tva_rate": 0.1},
        volume_gate={"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0.0, "adv_window": 20},
        cooldown_bars=0,
    )

    assert result["stocks"]
    assert ("IAM", ("sma",)) in calls
    assert ("BCP", ("rsi",)) in calls


def test_run_strategy_plan_backtest_accepts_tz_aware_bars(monkeypatch) -> None:
    bars = _sample_bars()
    bars.index = bars.index.tz_localize("UTC")
    bars_by_symbol = {"AAA": bars}

    def fake_scores(**kwargs):
        ohlcv = kwargs["ohlcv"]
        return pd.DataFrame(
            {
                "trend_score": [80.0] * len(ohlcv),
                "momentum_score": [80.0] * len(ohlcv),
                "oscillation_score": [80.0] * len(ohlcv),
                "volume_score": [80.0] * len(ohlcv),
                "consensus_score": [80.0] * len(ohlcv),
            },
            index=ohlcv.index,
            dtype="float64",
        )

    monkeypatch.setattr(
        "core.quant_core.strategy_plan.backtest._compute_score_frame",
        fake_scores,
    )

    result = run_strategy_plan_backtest(
        strategy_id="strategy-1",
        strategy_name="Desk Test",
        side_policy="long_only",
        horizon="medium",
        timeframe="1D",
        config_json={
            "capital": {"total_capital_mad": 100_000},
            "universe": {"basket": ["AAA"]},
            "allocation": {"method": "hrp", "hrp_lookback_bars": 60, "manual_overrides_by_symbol": {}},
            "signal": {"enabled_families": ["sma"]},
            "bet_sizing": BET_SIZING,
            "risk": {
                "max_holding_bars": 30,
                "stop_atr_multiplier": 1.5,
    
                "take_profit_rr": 1.5,
                "time_stop_enabled": True,
                "trailing_stop_enabled": False,
            },
        },
        bars_by_symbol=bars_by_symbol,
        start_date="2024-01-01",
        end_date="2024-01-08",
        cost_model_raw={"brokerage_bps": 0.2, "comm_bourse_bps": 0.1, "reg_liv_bps": 0.0, "slippage_bps": 0.0, "tva_rate": 0.1},
        volume_gate={"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0.0, "adv_window": 20},
        cooldown_bars=0,
    )

    assert result["general_results"]["metrics"]["number_of_trades"] >= 0
    assert len(result["stocks"]) == 1


def test_simulate_stock_short_reversal_respects_cash_for_extra_long() -> None:
    bars = pd.DataFrame(
        {
            "Open": [100, 100, 400, 410],
            "High": [101, 401, 411, 421],
            "Low": [99, 99, 399, 409],
            "Close": [100, 100, 405, 415],
            "Volume": [100_000, 100_000, 100_000, 100_000],
        },
        index=pd.date_range("2024-01-01", periods=4, freq="D"),
    )
    scores = pd.Series([-85, 85, 85, 85], index=bars.index, dtype="float64")

    sim = _simulate_stock(
        symbol="AAA",
        bars=bars,
        score_series=scores,
        score_frame=None,
        allocated_capital=100_000,
        side_policy="long_short",
        exposure_ladder=EXPOSURE_LADDER,
        entry_rules=[],
        exit_rules=[],
        risk={
            "max_holding_bars": 30,
            "stop_atr_multiplier": 1.5,

            "take_profit_rr": 1.5,
            "time_stop_enabled": True,
            "trailing_stop_enabled": False,
        },
        cost_model=_build_cost_model({}),
        cooldown_bars=0,
        volume_gate={"enabled": False, "kind": "min_ratio_adv", "min_volume_abs": 0, "min_volume_ratio_adv": 0, "adv_window": 20},
    )

    fills = sim.fills.sort_values("timestamp").reset_index(drop=True)
    assert list(fills["side"])[:2] == ["SELL", "BUY"]
    assert int(fills.loc[0, "qty"]) == -1000
    assert int(fills.loc[1, "qty"]) == 1000
