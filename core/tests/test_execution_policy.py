"""Tests for execution horizon policy defaults."""

from core.quant_core.strategy_plan.execution_policy import (
    build_execution_horizon_policy,
    default_execution_holding_bars,
)


def test_default_execution_holding_bars():
    assert default_execution_holding_bars("weekly") == 10
    assert default_execution_holding_bars("monthly") == 30
    assert default_execution_holding_bars("quarterly") == 60


def test_policy_defaults_follow_horizon():
    weekly = build_execution_horizon_policy("weekly")
    monthly = build_execution_horizon_policy("monthly")
    quarterly = build_execution_horizon_policy("quarterly")

    assert weekly.holding_bars == 10
    assert weekly.structural_lookback == 40
    assert weekly.swing_left_bars == 2
    assert weekly.max_levels == 4
    assert weekly.max_level_distance_atr == 4.0

    assert monthly.holding_bars == 30
    assert monthly.structural_lookback == 120
    assert monthly.swing_left_bars == 3
    assert monthly.max_levels == 6
    assert monthly.max_level_distance_atr == 8.0

    assert quarterly.holding_bars == 60
    assert quarterly.structural_lookback == 240
    assert quarterly.swing_left_bars == 5
    assert quarterly.max_levels == 8
    assert quarterly.max_level_distance_atr == 12.0


def test_policy_respects_override():
    custom = build_execution_horizon_policy("weekly", holding_bars=15)
    assert custom.holding_bars == 15
    assert custom.structural_lookback == 60
