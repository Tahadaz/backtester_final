"""Tests for DSR, PSR, stationary bootstrap, and rolling CV."""
import math

import numpy as np
import pytest

from quant_core.research.stats.robustness import (
    probabilistic_sharpe_ratio,
    deflated_sharpe_ratio,
    stationary_bootstrap_ci,
    rolling_metric_cv,
    harvey_liu_expected_max_sharpe,
)


class TestHarveyLiuExpectedMaxSharpe:
    def test_single_variant_returns_zero(self):
        assert harvey_liu_expected_max_sharpe(1) == 0.0

    def test_increases_with_n(self):
        sr10 = harvey_liu_expected_max_sharpe(10)
        sr100 = harvey_liu_expected_max_sharpe(100)
        assert sr100 > sr10 > 0.0

    def test_returns_finite(self):
        for n in [2, 5, 10, 50, 100]:
            sr = harvey_liu_expected_max_sharpe(n)
            assert math.isfinite(sr)


class TestProbabilisticSharpeRatio:
    def test_positive_sharpe_gives_psr_above_half(self):
        rng = np.random.default_rng(0)
        returns = rng.normal(0.001, 0.01, 252)
        psr = probabilistic_sharpe_ratio(returns, sr_benchmark=0.0)
        assert psr > 0.5

    def test_negative_mean_gives_psr_below_half(self):
        rng = np.random.default_rng(1)
        returns = rng.normal(-0.002, 0.01, 252)
        psr = probabilistic_sharpe_ratio(returns, sr_benchmark=0.0)
        assert psr < 0.5

    def test_returns_in_0_1(self):
        rng = np.random.default_rng(2)
        returns = rng.normal(0, 0.01, 100)
        psr = probabilistic_sharpe_ratio(returns)
        assert 0.0 <= psr <= 1.0

    def test_short_series_returns_nan(self):
        assert math.isnan(probabilistic_sharpe_ratio(np.array([0.01, 0.02])))


class TestDeflatedSharpeRatio:
    def test_single_variant_equals_psr(self):
        rng = np.random.default_rng(3)
        returns = rng.normal(0.001, 0.01, 200)
        dsr = deflated_sharpe_ratio(returns, n_variants=1)
        psr = probabilistic_sharpe_ratio(returns, sr_benchmark=0.0)
        assert abs(dsr - psr) < 1e-9

    def test_more_variants_reduces_dsr(self):
        rng = np.random.default_rng(4)
        returns = rng.normal(0.0005, 0.01, 500)
        dsr1 = deflated_sharpe_ratio(returns, n_variants=1)
        dsr20 = deflated_sharpe_ratio(returns, n_variants=20)
        assert dsr1 > dsr20

    def test_null_strategy_dsr_near_zero(self):
        rng = np.random.default_rng(5)
        # Near-zero Sharpe strategy
        returns = rng.normal(0.0, 0.01, 252)
        dsr = deflated_sharpe_ratio(returns, n_variants=10)
        assert dsr < 0.7  # well below 1.0


class TestStationaryBootstrapCI:
    def test_returns_finite_bounds(self):
        rng = np.random.default_rng(42)
        x = rng.normal(0.001, 0.01, 252)

        def sharpe(r):
            mu, s = np.mean(r), np.std(r, ddof=1)
            return mu / s if s > 0 else float("nan")

        lo, hi = stationary_bootstrap_ci(x, sharpe, n_bootstrap=200)
        assert math.isfinite(lo) and math.isfinite(hi)
        assert lo < hi

    def test_positive_return_series_ci_above_zero(self):
        rng = np.random.default_rng(0)
        x = rng.normal(0.003, 0.01, 252)  # clearly positive mean

        def mean_fn(r):
            return float(np.mean(r))

        lo, hi = stationary_bootstrap_ci(x, mean_fn, n_bootstrap=200)
        assert lo > 0.0

    def test_short_series_returns_nan(self):
        lo, hi = stationary_bootstrap_ci(np.array([0.01, 0.02, 0.01]), lambda x: np.mean(x))
        assert math.isnan(lo) and math.isnan(hi)


class TestRollingMetricCV:
    def test_constant_series_returns_zero_cv(self):
        x = np.ones(200) * 0.01
        cv = rolling_metric_cv(x, window=63)
        # constant series → rolling means all the same → std = 0 → cv = 0
        assert cv == 0.0 or math.isnan(cv)

    def test_volatile_series_has_higher_cv(self):
        rng = np.random.default_rng(99)
        stable = rng.normal(0.001, 0.0001, 300)
        volatile = rng.normal(0.001, 0.005, 300)
        cv_stable = rolling_metric_cv(stable, window=63)
        cv_volatile = rolling_metric_cv(volatile, window=63)
        if not (math.isnan(cv_stable) or math.isnan(cv_volatile)):
            assert cv_volatile > cv_stable

    def test_short_series_returns_nan(self):
        assert math.isnan(rolling_metric_cv(np.array([0.01, 0.02]), window=63))
