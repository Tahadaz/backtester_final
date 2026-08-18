"""Tests for cross-asset performance statistics."""

import numpy as np
import pandas as pd
import pytest

from quant_core.cross_asset.performance import (
    extract_trades,
    per_instrument_summary,
    performance_summary,
    period_statistics,
    trade_statistics,
)


def _index(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2020-01-01", periods=n)


# ---------------------------------------------------------------------------
# Trade extraction
# ---------------------------------------------------------------------------


def test_trades_split_on_sign_flip_not_on_resize():
    index = _index(10)
    # Long (resized mid-way), then short. Two trades, not three.
    positions = pd.Series([1.0, 1.0, 2.0, 2.0, 2.0, -1.0, -1.0, -1.0, 0.0, 0.0], index=index)
    returns = pd.Series(0.01, index=index)
    trades = extract_trades(positions, returns, "X", execution_lag=1)
    assert len(trades) == 2
    assert trades[0].direction == 1
    assert trades[1].direction == -1
    assert trades[0].bars == 5
    assert trades[1].bars == 3


def test_flat_position_produces_no_trade():
    index = _index(6)
    positions = pd.Series(0.0, index=index)
    returns = pd.Series(0.01, index=index)
    assert extract_trades(positions, returns, "X") == []


def test_trade_pnl_sums_to_total_contribution():
    """The decisive accounting check: no P&L invented, none lost."""
    rng = np.random.default_rng(4)
    index = _index(500)
    returns = pd.Series(rng.normal(0.0005, 0.01, 500), index=index)
    raw = pd.Series(rng.normal(0, 1, 500), index=index).rolling(20).mean()
    positions = np.sign(raw).fillna(0.0)

    trades = extract_trades(positions, returns, "X", execution_lag=1)
    total_contribution = (positions.shift(1) * returns).sum()
    assert sum(t.pnl for t in trades) == pytest.approx(total_contribution, rel=1e-9, abs=1e-12)


def test_trade_pnl_respects_execution_lag():
    index = _index(6)
    positions = pd.Series([0.0, 1.0, 1.0, 0.0, 0.0, 0.0], index=index)
    returns = pd.Series([0.0, 0.0, 0.10, 0.20, 0.50, 0.0], index=index)
    trades = extract_trades(positions, returns, "X", execution_lag=1)
    assert len(trades) == 1
    # Position is on for bars 1-2, so it earns bars 2 and 3 (10% + 20%),
    # and must NOT earn the 50% on bar 4 after it has flattened.
    assert trades[0].pnl == pytest.approx(0.30)


def test_open_trade_at_end_of_sample_is_still_counted():
    index = _index(5)
    positions = pd.Series([0.0, 1.0, 1.0, 1.0, 1.0], index=index)
    returns = pd.Series([0.0, 0.0, 0.01, 0.01, 0.01], index=index)
    trades = extract_trades(positions, returns, "X")
    assert len(trades) == 1
    assert trades[0].bars == 4


# ---------------------------------------------------------------------------
# Trade statistics
# ---------------------------------------------------------------------------


def test_trade_statistics_arithmetic():
    from quant_core.cross_asset.performance import Trade

    stamp = pd.Timestamp("2020-01-01")
    trades = [
        Trade("X", 1, stamp, stamp, 5, 0.10, 1.0),
        Trade("X", 1, stamp, stamp, 5, 0.20, 1.0),
        Trade("X", -1, stamp, stamp, 5, -0.05, 1.0),
        Trade("X", -1, stamp, stamp, 5, -0.05, 1.0),
    ]
    stats = trade_statistics(trades)
    assert stats["n_trades"] == 4
    assert stats["win_rate"] == pytest.approx(0.5)
    assert stats["avg_win"] == pytest.approx(0.15)
    assert stats["avg_loss"] == pytest.approx(-0.05)
    assert stats["payoff_ratio"] == pytest.approx(3.0)
    assert stats["profit_factor"] == pytest.approx(0.30 / 0.10)
    assert stats["expectancy_per_trade"] == pytest.approx(0.05)
    assert stats["n_long"] == 2 and stats["n_short"] == 2


def test_expectancy_matches_win_loss_decomposition():
    """expectancy == win_rate*avg_win + (1-win_rate)*avg_loss."""
    from quant_core.cross_asset.performance import Trade

    stamp = pd.Timestamp("2020-01-01")
    rng = np.random.default_rng(8)
    trades = [Trade("X", 1, stamp, stamp, 3, float(v), 1.0) for v in rng.normal(0.01, 0.05, 200)]
    stats = trade_statistics(trades)
    reconstructed = (
        stats["win_rate"] * stats["avg_win"] + (1 - stats["win_rate"]) * stats["avg_loss"]
    )
    assert reconstructed == pytest.approx(stats["expectancy_per_trade"], rel=1e-9)


def test_empty_trade_statistics_are_nan_not_zero():
    stats = trade_statistics([])
    assert stats["n_trades"] == 0
    assert np.isnan(stats["win_rate"])
    assert np.isnan(stats["expectancy_per_trade"])


# ---------------------------------------------------------------------------
# Period statistics
# ---------------------------------------------------------------------------


def test_period_statistics_on_a_known_series():
    index = _index(252)
    returns = pd.Series(0.001, index=index)  # constant, zero vol
    stats = period_statistics(returns)
    assert stats["expected_return_annual"] == pytest.approx(0.252)
    assert stats["hit_rate_periods"] == pytest.approx(1.0)
    assert stats["max_drawdown"] == pytest.approx(0.0)
    assert np.isnan(stats["sharpe"])  # zero volatility -> undefined, not infinite


def test_drawdown_and_recovery_are_measured():
    index = _index(10)
    returns = pd.Series([0.0, -0.10, -0.10, 0.05, 0.05, 0.05, 0.05, 0.0, 0.0, 0.0], index=index)
    stats = period_statistics(returns)
    assert stats["max_drawdown"] < -0.15
    assert stats["longest_drawdown_periods"] >= 3


def test_sharpe_and_sortino_diverge_with_asymmetry():
    rng = np.random.default_rng(2)
    index = _index(1000)
    # Many small gains, few large losses -- but a genuinely positive mean, or
    # the sign of the comparison flips and the test stops meaning anything.
    values = rng.normal(0.0020, 0.004, 1000)
    values[::50] = -0.05
    stats = period_statistics(pd.Series(values, index=index))
    assert stats["expected_return_annual"] > 0, "test premise: mean must be positive"
    assert stats["skew"] < 0
    # Negative skew inflates downside deviation relative to total, so a
    # positive-mean strategy scores worse on Sortino than on Sharpe.
    assert stats["sortino"] < stats["sharpe"]


def test_period_statistics_handle_empty_input():
    stats = period_statistics(pd.Series(dtype=float))
    assert stats["n_periods"] == 0


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------


def test_performance_summary_merges_both_views():
    rng = np.random.default_rng(6)
    index = _index(600)
    panel = pd.DataFrame(rng.normal(0.0004, 0.01, (600, 3)), index=index, columns=["A", "B", "C"])
    positions = np.sign(panel.rolling(20).mean()).fillna(0.0)
    portfolio = (positions.shift(1) * panel).sum(axis=1)

    summary = performance_summary(portfolio, positions, panel)
    assert summary["n_periods"] > 0
    assert summary["n_trades"] > 0
    assert "expected_return_annual" in summary
    assert "win_rate" in summary


def test_per_instrument_summary_is_sorted_and_complete():
    rng = np.random.default_rng(1)
    index = _index(600)
    panel = pd.DataFrame(rng.normal(0.0004, 0.01, (600, 4)), index=index, columns=list("ABCD"))
    positions = np.sign(panel.rolling(20).mean()).fillna(0.0)

    frame = per_instrument_summary(positions, panel)
    assert list(frame["instrument"]) == sorted(
        frame["instrument"], key=lambda i: -frame.set_index("instrument").loc[i, "total_pnl"]
    )
    assert len(frame) == 4
    for column in ("win_rate", "expectancy_per_trade", "sharpe", "max_drawdown", "n_trades"):
        assert column in frame.columns


def test_per_instrument_pnl_sums_to_portfolio_pnl():
    rng = np.random.default_rng(12)
    index = _index(500)
    panel = pd.DataFrame(rng.normal(0.0005, 0.01, (500, 3)), index=index, columns=list("XYZ"))
    positions = np.sign(panel.rolling(15).mean()).fillna(0.0)

    frame = per_instrument_summary(positions, panel)
    portfolio_total = (positions.shift(1) * panel).sum(axis=1).sum()
    assert frame["total_pnl"].sum() == pytest.approx(portfolio_total, rel=1e-9)
