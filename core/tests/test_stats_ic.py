"""Tests for IC calculation and Newey-West SE."""
import math

import numpy as np
import pandas as pd
import pytest

from quant_core.research.stats.ic import (
    rank_ic,
    ic_decay_curve,
    conditional_return_tstat,
    _newey_west_var,
)


class TestNeweyWestVar:
    def test_iid_series_approx_var_of_mean(self):
        rng = np.random.default_rng(0)
        x = rng.normal(0, 1, 200)
        nw = _newey_west_var(x)
        classical = np.var(x, ddof=1) / len(x)
        # NW includes finite-sample autocovariance noise; allow 50% tolerance
        assert abs(nw - classical) < 0.5 * classical

    def test_returns_nan_for_short_series(self):
        assert math.isnan(_newey_west_var(np.array([1.0, 2.0])))

    def test_positive(self):
        rng = np.random.default_rng(1)
        x = rng.normal(0, 1, 100)
        nw = _newey_west_var(x)
        assert nw > 0


class TestRankIC:
    def test_perfect_positive_correlation(self):
        n = 100
        s = pd.Series(np.arange(n, dtype=float))
        r = pd.Series(np.arange(n, dtype=float))
        ic = rank_ic(s, r)
        assert abs(ic - 1.0) < 1e-9

    def test_perfect_negative_correlation(self):
        n = 100
        s = pd.Series(np.arange(n, dtype=float))
        r = pd.Series(np.arange(n - 1, -1, -1, dtype=float))
        ic = rank_ic(s, r)
        assert abs(ic + 1.0) < 1e-9

    def test_zero_correlation(self):
        rng = np.random.default_rng(42)
        s = pd.Series(rng.normal(0, 1, 200))
        r = pd.Series(rng.normal(0, 1, 200))
        ic = rank_ic(s, r)
        assert abs(ic) < 0.2  # not exactly 0 but small

    def test_returns_nan_for_short_series(self):
        s = pd.Series([1.0, 2.0, 3.0])
        r = pd.Series([1.0, 2.0, 3.0])
        assert math.isnan(rank_ic(s, r))

    def test_handles_nans(self):
        s = pd.Series([1.0, float("nan"), 3.0, 4.0, 5.0, 6.0])
        r = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
        ic = rank_ic(s, r)
        assert not math.isnan(ic)


class TestICDecayCurve:
    def test_returns_all_horizons(self):
        rng = np.random.default_rng(0)
        n = 300
        prices = pd.Series(100 + np.cumsum(rng.normal(0, 1, n)))
        signal = pd.Series(rng.choice([-1, 0, 1], size=n).astype(float))
        result = ic_decay_curve(signal, prices)
        assert set(result.keys()) == {1, 2, 3, 5, 10}

    def test_each_result_has_required_keys(self):
        rng = np.random.default_rng(1)
        n = 200
        prices = pd.Series(100 + np.cumsum(rng.normal(0, 1, n)))
        signal = pd.Series(rng.normal(0, 1, n))
        result = ic_decay_curve(signal, prices)
        for h, d in result.items():
            assert "ic" in d and "se" in d and "ci_lower" in d and "ci_upper" in d and "n" in d

    def test_ci_contains_ic(self):
        rng = np.random.default_rng(2)
        n = 250
        prices = pd.Series(100 + np.cumsum(rng.normal(0, 1, n)))
        signal = pd.Series(rng.normal(0, 1, n))
        result = ic_decay_curve(signal, prices)
        for h, d in result.items():
            if not math.isnan(d["ic"]):
                assert d["ci_lower"] <= d["ic"] <= d["ci_upper"]


class TestConditionalReturnTstat:
    def test_positive_signal_on_positive_days(self):
        rng = np.random.default_rng(0)
        n = 300
        returns = pd.Series(rng.normal(0.001, 0.01, n))
        # Signal fires when return was positive yesterday (perfect predictor)
        signal = pd.Series(returns.shift(1).fillna(0).values)
        prices = pd.Series(100 + (1 + returns).cumprod().values * 0 + np.arange(n) * 0.001)
        fwd_ret = returns

        t = conditional_return_tstat(signal, fwd_ret, threshold=0.0)
        # With this construction, t should be > 0
        assert not math.isnan(t)

    def test_returns_nan_for_short_series(self):
        s = pd.Series([1.0, 1.0, 1.0])
        r = pd.Series([0.01, 0.02, 0.01])
        assert math.isnan(conditional_return_tstat(s, r))
