from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from quant_core.fundamentals.cost_of_capital import (
    BetaConfig,
    estimate_beta,
    relever_beta,
    unlever_beta,
    wacc_build_up,
)
from quant_core.fundamentals.valuation import DEFAULT_ASSUMPTIONS


def _prices_from_returns(returns: list[float], *, start: float = 100.0) -> pd.Series:
    index = pd.date_range("2024-01-05", periods=len(returns) + 1, freq="W-FRI")
    values = [start]
    current = start
    for ret in returns:
        current *= 1.0 + ret
        values.append(current)
    return pd.Series(values, index=index)


def _hand_beta(y: np.ndarray, x: np.ndarray) -> float:
    x_centered = x - x.mean()
    y_centered = y - y.mean()
    return float(np.dot(x_centered, y_centered) / np.dot(x_centered, x_centered))


def test_weekly_ols_beta_matches_hand_computed_fixture() -> None:
    market_returns = np.array([0.01, -0.02, 0.03, 0.00, 0.02, -0.01, 0.04, -0.02, 0.01, 0.03])
    stock_returns = 0.004 + 1.5 * market_returns
    stock_close = _prices_from_returns(stock_returns.tolist())
    market_close = _prices_from_returns(market_returns.tolist())

    result = estimate_beta(
        symbol="AAA.CS",
        stock_close=stock_close,
        market_close=market_close,
        as_of=dt.date(2024, 3, 15),
        config=BetaConfig(min_obs=5, min_traded_periods=5, zero_return_threshold=0.90),
    )

    assert result.symbol == "AAA"
    assert result.method == "ols"
    assert result.liquidity_flag is False
    assert result.n_obs == len(market_returns)
    assert result.beta == pytest.approx(_hand_beta(stock_returns, market_returns))
    assert result.r2 == pytest.approx(1.0)
    assert result.as_of == dt.date(2024, 3, 15)


def test_thin_name_routes_to_peer_relevered_robust_path() -> None:
    market_returns = np.array([0.01, -0.02, 0.03, -0.01, 0.02, -0.03, 0.01, 0.02, -0.01, 0.03])
    stock_returns = np.array([0.0, 0.0, 0.0, 0.006, 0.0, 0.0, 0.0, 0.004, 0.0, 0.0])

    result = estimate_beta(
        symbol="THIN",
        stock_close=_prices_from_returns(stock_returns.tolist()),
        market_close=_prices_from_returns(market_returns.tolist()),
        config=BetaConfig(
            min_obs=5,
            min_traded_periods=5,
            zero_return_threshold=0.30,
            robust_min_nonzero_periods=5,
        ),
        peer_unlevered_beta=0.80,
        debt_to_equity=0.50,
        tax_rate=0.35,
    )

    assert result.liquidity_flag is True
    assert result.method == "peer_relevered"
    assert result.zero_week_frac == pytest.approx(0.80)
    assert result.beta == pytest.approx(relever_beta(0.80, 0.50, 0.35))
    assert "very_low_liquidity" in result.warnings
    assert "dimson_unstable" in result.warnings


def test_unlever_relever_round_trip() -> None:
    levered = 1.25
    unlevered = unlever_beta(levered, debt_to_equity=0.40, tax_rate=0.35)
    assert relever_beta(unlevered, debt_to_equity=0.40, tax_rate=0.35) == pytest.approx(levered)


def test_wacc_build_up_normalizes_weights() -> None:
    result = wacc_build_up(
        cost_of_equity=0.089,
        cost_of_debt=0.055,
        tax_rate=0.35,
        equity_weight=70.0,
        debt_weight=30.0,
    )

    assert result["equity_weight"] == pytest.approx(0.70)
    assert result["debt_weight"] == pytest.approx(0.30)
    assert result["wacc"] == pytest.approx(0.70 * 0.089 + 0.30 * 0.055 * (1.0 - 0.35))


def test_default_wacc_matches_after_tax_registry_build_up() -> None:
    result = wacc_build_up(
        cost_of_equity=DEFAULT_ASSUMPTIONS["cost_of_equity"],
        cost_of_debt=DEFAULT_ASSUMPTIONS["cost_of_debt"],
        tax_rate=DEFAULT_ASSUMPTIONS["tax_rate"],
        equity_weight=DEFAULT_ASSUMPTIONS["default_equity_weight"],
        debt_weight=DEFAULT_ASSUMPTIONS["default_debt_weight"],
    )

    assert DEFAULT_ASSUMPTIONS["wacc"] == pytest.approx(result["wacc"], abs=1e-4)
