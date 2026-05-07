"""Tests for monte_carlo_equity_paths and related MC functions in core/quant_core/risk.py."""
from __future__ import annotations

import math
import numpy as np
import pytest

from core.quant_core.risk import (
    monte_carlo_equity_paths,
    stationary_block_bootstrap,
    trade_bootstrap,
)


# ---------------------------------------------------------------------------
# stationary_block_bootstrap
# ---------------------------------------------------------------------------

def test_block_bootstrap_shape():
    rng = np.random.default_rng(0)
    returns = rng.normal(0, 0.01, 100)
    paths = stationary_block_bootstrap(returns, n_paths=50, block_mean=5, seed=1)
    assert paths.shape == (50, 100)
    assert paths.dtype == np.float64


def test_block_bootstrap_short_input():
    paths = stationary_block_bootstrap(np.array([0.01, 0.02]), n_paths=10, block_mean=3, seed=1)
    assert paths.shape == (10, 2)


def test_block_bootstrap_determinism():
    rng = np.random.default_rng(7)
    returns = rng.normal(0, 0.01, 80)
    p1 = stationary_block_bootstrap(returns, n_paths=30, block_mean=4, seed=42)
    p2 = stationary_block_bootstrap(returns, n_paths=30, block_mean=4, seed=42)
    np.testing.assert_array_equal(p1, p2)


def test_block_bootstrap_different_seeds():
    rng = np.random.default_rng(3)
    returns = rng.normal(0, 0.01, 60)
    p1 = stationary_block_bootstrap(returns, n_paths=20, block_mean=4, seed=1)
    p2 = stationary_block_bootstrap(returns, n_paths=20, block_mean=4, seed=2)
    assert not np.allclose(p1, p2)


# ---------------------------------------------------------------------------
# trade_bootstrap
# ---------------------------------------------------------------------------

def test_trade_bootstrap_shape():
    pnls = np.array([0.02, -0.01, 0.03, 0.01, -0.02])
    starts = np.array([5, 20, 40, 60, 80])
    paths = trade_bootstrap(pnls, starts, T=100, n_paths=50, seed=1)
    assert paths.shape == (50, 100)
    assert paths.dtype == np.float64


def test_trade_bootstrap_zero_outside_trades():
    """All non-trade bars should have zero return contribution in the mean path."""
    pnls = np.array([0.05, 0.05, 0.05])
    starts = np.array([10, 30, 50])
    T = 100
    paths = trade_bootstrap(pnls, starts, T=T, n_paths=200, seed=0)
    # Bars that are never trade starts should have zero mean (no assignment possible)
    non_trade_mask = np.ones(T, dtype=bool)
    non_trade_mask[[10, 30, 50]] = False
    mean_non_trade = np.abs(paths[:, non_trade_mask]).mean()
    assert mean_non_trade == 0.0


def test_trade_bootstrap_no_trades():
    paths = trade_bootstrap(np.array([]), np.array([], dtype=np.intp), T=50, n_paths=10, seed=1)
    assert paths.shape == (10, 50)
    np.testing.assert_array_equal(paths, 0.0)


def test_trade_bootstrap_determinism():
    pnls = np.array([0.01, 0.02, -0.01])
    starts = np.array([0, 5, 10])
    p1 = trade_bootstrap(pnls, starts, T=20, n_paths=15, seed=99)
    p2 = trade_bootstrap(pnls, starts, T=20, n_paths=15, seed=99)
    np.testing.assert_array_equal(p1, p2)


# ---------------------------------------------------------------------------
# monte_carlo_equity_paths
# ---------------------------------------------------------------------------

def test_mc_equity_paths_shape_and_keys():
    rng = np.random.default_rng(5)
    returns = rng.normal(0.001, 0.01, 120)
    result = monte_carlo_equity_paths(returns, method="block_bootstrap", n_paths=100, seed=7)

    assert set(result["envelope"]) == {"p05", "p25", "p50", "p75", "p95"}
    for k, v in result["envelope"].items():
        assert len(v) == 120, f"envelope[{k}] length mismatch"

    stats = result["stats"]
    for k in ("total_return", "cagr", "sharpe", "max_drawdown"):
        assert set(stats[k]) == {"p05", "p50", "p95"}
    assert "var95" in stats
    assert "cvar95" in stats
    assert "prob_positive_terminal" in stats


def test_mc_envelope_monotonicity():
    """p05 <= p25 <= p50 <= p75 <= p95 at every timestep."""
    rng = np.random.default_rng(11)
    returns = rng.normal(0.0005, 0.008, 252)
    result = monte_carlo_equity_paths(returns, method="block_bootstrap", n_paths=500, seed=13)
    env = result["envelope"]
    p05 = np.array(env["p05"])
    p25 = np.array(env["p25"])
    p50 = np.array(env["p50"])
    p75 = np.array(env["p75"])
    p95 = np.array(env["p95"])

    assert np.all(p05 <= p25 + 1e-10), "p05 > p25 at some timestep"
    assert np.all(p25 <= p50 + 1e-10), "p25 > p50 at some timestep"
    assert np.all(p50 <= p75 + 1e-10), "p50 > p75 at some timestep"
    assert np.all(p75 <= p95 + 1e-10), "p75 > p95 at some timestep"


def test_mc_equity_paths_determinism():
    rng = np.random.default_rng(17)
    returns = rng.normal(0, 0.01, 100)
    r1 = monte_carlo_equity_paths(returns, method="block_bootstrap", n_paths=50, seed=42)
    r2 = monte_carlo_equity_paths(returns, method="block_bootstrap", n_paths=50, seed=42)
    np.testing.assert_allclose(r1["envelope"]["p50"], r2["envelope"]["p50"])
    assert r1["stats"]["var95"] == r2["stats"]["var95"]


def test_mc_equity_paths_auto_block_mean():
    T = 200
    rng = np.random.default_rng(19)
    returns = rng.normal(0, 0.01, T)
    result = monte_carlo_equity_paths(returns, n_paths=50, block_mean=None, seed=1)
    expected_block_mean = math.ceil(T ** (1.0 / 3.0))
    assert result["block_mean"] == expected_block_mean


def test_mc_equity_paths_short_returns():
    result = monte_carlo_equity_paths(np.array([0.01, 0.02]), n_paths=10, seed=0)
    assert result["envelope"]["p05"] == []
    assert result["stats"]["var95"] is None


def test_mc_equity_paths_trade_bootstrap():
    rng = np.random.default_rng(23)
    returns = rng.normal(0, 0.01, 100)
    trade_events = {
        "pnls": list(rng.normal(0.01, 0.02, 40)),
        "start_indices": list(range(0, 100, 2)[:40]),
    }
    result = monte_carlo_equity_paths(
        returns,
        method="trade_bootstrap",
        n_paths=50,
        trade_events=trade_events,
        seed=3,
    )
    assert len(result["envelope"]["p50"]) == 100


def test_mc_trade_bootstrap_requires_events():
    rng = np.random.default_rng(0)
    returns = rng.normal(0, 0.01, 50)
    with pytest.raises(ValueError, match="trade_events required"):
        monte_carlo_equity_paths(returns, method="trade_bootstrap", n_paths=10, seed=0)


def test_mc_prob_positive_bounded():
    rng = np.random.default_rng(29)
    returns = rng.normal(0, 0.01, 252)
    result = monte_carlo_equity_paths(returns, n_paths=200, seed=5)
    prob = result["stats"]["prob_positive_terminal"]
    assert 0.0 <= prob <= 1.0


def test_mc_positive_drift_mostly_positive_terminal():
    """Strong positive drift should yield high prob_positive_terminal."""
    returns = np.full(252, 0.003)  # +0.3% per bar → very strong drift
    result = monte_carlo_equity_paths(returns, method="block_bootstrap", n_paths=300, seed=0)
    assert result["stats"]["prob_positive_terminal"] > 0.9


def test_mc_negative_drift_low_terminal():
    """Strong negative drift should yield low prob_positive_terminal."""
    returns = np.full(252, -0.003)
    result = monte_carlo_equity_paths(returns, method="block_bootstrap", n_paths=300, seed=0)
    assert result["stats"]["prob_positive_terminal"] < 0.1
