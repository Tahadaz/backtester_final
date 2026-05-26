"""Tests for execution horizon policy defaults."""

from core.quant_core.strategy_plan.execution_policy import (
    build_execution_horizon_policy,
    default_execution_holding_bars,
)


def test_default_execution_holding_bars():
    assert default_execution_holding_bars("short") == 10
    assert default_execution_holding_bars("medium") == 30
    assert default_execution_holding_bars("long") == 60


def test_policy_defaults_follow_horizon():
    short = build_execution_horizon_policy("short")
    medium = build_execution_horizon_policy("medium")
    long = build_execution_horizon_policy("long")

    assert short.holding_bars == 10
    assert short.structural_lookback == 40
    assert short.swing_left_bars == 2
    assert short.max_levels == 4
    assert short.max_level_distance_atr == 4.0

    assert medium.holding_bars == 30
    assert medium.structural_lookback == 120
    assert medium.swing_left_bars == 3
    assert medium.max_levels == 6
    assert medium.max_level_distance_atr == 8.0

    assert long.holding_bars == 60
    assert long.structural_lookback == 240
    assert long.swing_left_bars == 5
    assert long.max_levels == 8
    assert long.max_level_distance_atr == 12.0


def test_policy_respects_override():
    custom = build_execution_horizon_policy("short", holding_bars=15)
    assert custom.holding_bars == 15
    assert custom.structural_lookback == 60
