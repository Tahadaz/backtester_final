"""Tests for HRP allocation preview helpers."""

import pandas as pd

from core.quant_core.strategy_plan.allocation import compute_hrp_weights, compute_strategy_allocation


def _series(values: list[float]) -> pd.Series:
    return pd.Series(values, index=pd.date_range("2025-01-01", periods=len(values), freq="D"))


def test_hrp_weights_sum_to_one():
    history = {
        "AAA": _series([100, 101, 103, 104, 105, 107, 108, 110, 111, 113, 114, 116]),
        "BBB": _series([50, 49, 50, 51, 52, 53, 54, 54, 55, 56, 57, 58]),
        "CCC": _series([200, 201, 200, 202, 204, 203, 205, 206, 208, 207, 209, 210]),
    }
    weights = compute_hrp_weights(history, ["AAA", "BBB", "CCC"], lookback_bars=10)
    assert set(weights) == {"AAA", "BBB", "CCC"}
    assert abs(sum(weights.values()) - 1.0) < 1e-9
    assert all(weight >= 0 for weight in weights.values())


def test_strategy_allocation_respects_manual_override():
    history = {
        "AAA": _series([100, 101, 103, 104, 105, 107, 108, 110, 111, 113, 114, 116]),
        "BBB": _series([50, 49, 50, 51, 52, 53, 54, 54, 55, 56, 57, 58]),
        "CCC": _series([200, 201, 200, 202, 204, 203, 205, 206, 208, 207, 209, 210]),
    }
    result = compute_strategy_allocation(
        symbols=["AAA", "BBB", "CCC"],
        total_capital_mad=1_000_000,
        price_history=history,
        manual_overrides_by_symbol={"BBB": 400_000},
        lookback_bars=10,
    )
    rows = {row["symbol"]: row for row in result["rows"]}
    assert rows["BBB"]["source"] == "manual"
    assert rows["BBB"]["capital_mad"] == 400_000
    assert abs(result["allocated_capital_mad"] - 1_000_000) < 1e-6
    assert result["remaining_capital_mad"] >= 0


def test_strategy_allocation_scales_manual_overallocation():
    result = compute_strategy_allocation(
        symbols=["AAA", "BBB"],
        total_capital_mad=100_000,
        price_history={},
        manual_overrides_by_symbol={"AAA": 80_000, "BBB": 80_000},
        lookback_bars=252,
    )
    rows = {row["symbol"]: row for row in result["rows"]}
    assert rows["AAA"]["source"] == "manual"
    assert rows["BBB"]["source"] == "manual"
    assert rows["AAA"]["capital_mad"] == 50_000
    assert rows["BBB"]["capital_mad"] == 50_000
    assert result["remaining_capital_mad"] == 0
