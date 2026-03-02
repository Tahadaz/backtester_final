from __future__ import annotations

import math

import numpy as np

from quant_core.mean_reversion import adf_test, cadf_cointegration, estimate_half_life
from quant_core.risk import build_risk_summary, kelly_fraction, monte_carlo_risk
from quant_core.significance import evaluate_significance, monte_carlo_luck_test, t_stat_mean_return


def test_adf_wrapper_detects_stationary_series() -> None:
    rng = np.random.default_rng(7)
    n = 500
    eps = rng.normal(0.0, 1.0, size=n)
    x = np.zeros(n, dtype=float)
    phi = 0.65
    for i in range(1, n):
        x[i] = phi * x[i - 1] + eps[i]

    out = adf_test(x)

    assert out["used_lags"] >= 0
    assert out["nobs"] > 100
    assert isinstance(out["critical_values"], dict)
    assert out["is_stationary_5pct"] is True


def test_half_life_estimation_returns_positive_value_for_mean_reverting_spread() -> None:
    rng = np.random.default_rng(11)
    n = 400
    eps = rng.normal(0.0, 0.3, size=n)
    spread = np.zeros(n, dtype=float)
    for i in range(1, n):
        spread[i] = 0.8 * spread[i - 1] + eps[i]

    out = estimate_half_life(spread)

    assert out["lambda"] < 0
    assert out["half_life"] > 0
    assert math.isfinite(out["half_life"])


def test_cadf_cointegration_wrapper_estimates_hedge_ratio() -> None:
    rng = np.random.default_rng(17)
    n = 700
    x = np.cumsum(rng.normal(0.0, 1.0, size=n))
    y = 1.7 * x + rng.normal(0.0, 0.6, size=n)

    out = cadf_cointegration(y, x)

    assert abs(out["hedge_ratio"] - 1.7) < 0.2
    assert out["nobs"] == n
    assert "critical_values" in out


def test_kelly_fraction_matches_mean_variance_ratio() -> None:
    r = np.array([0.01, 0.015, -0.005, 0.02, -0.01], dtype=float)

    expected = float(np.mean(r) / np.var(r, ddof=1))
    got = kelly_fraction(r)

    assert abs(got - expected) < 1e-10


def test_monte_carlo_risk_outputs_tail_metrics() -> None:
    rng = np.random.default_rng(29)
    r = rng.normal(0.0005, 0.01, size=250)

    out = monte_carlo_risk(
        r,
        n_paths=300,
        seed=13,
        chosen_leverage=1.0,
        leverage_cap=2.0,
        cost_bps=3.0,
        slippage_bps=2.0,
        avg_turnover=0.2,
    )

    assert out["mc_drawdown_pctl"] is not None
    assert out["mc_var"] is not None
    assert out["mc_cvar"] is not None
    assert out["n_paths"] == 300


def test_significance_module_returns_tstat_and_mc_pvalue() -> None:
    rng = np.random.default_rng(41)
    returns = rng.normal(0.0008, 0.012, size=300)

    t_out = t_stat_mean_return(returns)
    mc_out = monte_carlo_luck_test(returns, metric="sharpe", n_iter=300, seed=9)
    by_key = evaluate_significance({"demo": returns}, n_iter=200, seed=21)

    assert t_out["nobs"] == 300
    assert t_out["t_stat"] is not None
    assert mc_out["pvalue"] is not None
    assert "demo" in by_key


def test_build_risk_summary_contains_kelly_and_mc_details() -> None:
    rng = np.random.default_rng(55)
    r = rng.normal(0.0005, 0.01, size=240)

    out = build_risk_summary(
        r,
        seed=5,
        n_paths=200,
        leverage_cap=1.5,
        cost_bps=2.0,
        slippage_bps=1.0,
        avg_turnover=0.1,
    )

    assert "kelly_fraction" in out
    assert "half_kelly" in out
    assert "details" in out
    assert out["details"]["n_paths"] == 200
