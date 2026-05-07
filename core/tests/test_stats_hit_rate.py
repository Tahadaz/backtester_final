"""Tests for directional hit rate and Wilson CI."""
import math

import numpy as np
import pandas as pd
import pytest

from quant_core.research.stats.hit_rate import wilson_ci, directional_hit_rate, _norm_ppf


class TestNormPpf:
    def test_median_is_zero(self):
        assert abs(_norm_ppf(0.5)) < 1e-6

    def test_97_5_percentile(self):
        assert abs(_norm_ppf(0.975) - 1.96) < 0.01

    def test_2_5_percentile(self):
        assert abs(_norm_ppf(0.025) + 1.96) < 0.01


class TestWilsonCI:
    def test_zero_successes(self):
        lo, hi = wilson_ci(0, 100)
        assert lo >= 0.0
        assert hi < 0.1  # tight bound near zero

    def test_all_successes(self):
        lo, hi = wilson_ci(100, 100)
        assert lo > 0.9
        assert hi <= 1.0

    def test_half_successes(self):
        lo, hi = wilson_ci(50, 100)
        assert lo < 0.5 < hi

    def test_zero_n(self):
        lo, hi = wilson_ci(0, 0)
        assert lo == 0.0 and hi == 1.0

    def test_ci_width_shrinks_with_n(self):
        lo1, hi1 = wilson_ci(10, 20)
        lo2, hi2 = wilson_ci(100, 200)
        assert (hi1 - lo1) > (hi2 - lo2)

    @pytest.mark.parametrize("k,n", [(5, 10), (1, 20), (19, 20)])
    def test_bounds_in_0_1(self, k, n):
        lo, hi = wilson_ci(k, n)
        assert 0.0 <= lo <= hi <= 1.0


class TestDirectionalHitRate:
    def test_perfect_signal(self):
        n = 100
        sig = pd.Series(np.ones(n))  # always long
        ret = pd.Series(np.ones(n) * 0.001)  # always positive
        result = directional_hit_rate(sig, ret, threshold=0.0)
        assert result["hit_rate"] == 1.0
        assert result["ci_lower"] > 0.9

    def test_random_signal_near_50pct(self):
        rng = np.random.default_rng(42)
        n = 500
        sig = pd.Series(rng.choice([-1.0, 1.0], size=n))
        ret = pd.Series(rng.normal(0, 0.01, n))
        result = directional_hit_rate(sig, ret, threshold=0.0)
        assert abs(result["hit_rate"] - 0.5) < 0.15

    def test_returns_nan_for_short_series(self):
        sig = pd.Series([1.0, 2.0])
        ret = pd.Series([0.01, 0.02])
        result = directional_hit_rate(sig, ret)
        assert math.isnan(result["hit_rate"])

    def test_result_keys_present(self):
        sig = pd.Series(np.ones(50))
        ret = pd.Series(np.random.default_rng(0).normal(0, 0.01, 50))
        result = directional_hit_rate(sig, ret)
        for key in ["hit_rate", "ci_lower", "ci_upper", "n_buy_signals", "n_sell_signals"]:
            assert key in result

    def test_asymmetric_buy_sell(self):
        rng = np.random.default_rng(10)
        n = 200
        sig = pd.Series(rng.choice([-1.0, 0.0, 1.0], size=n))
        ret = pd.Series(rng.normal(0, 0.01, n))
        result = directional_hit_rate(sig, ret)
        assert "buy_hit_rate" in result
        assert "sell_hit_rate" in result
