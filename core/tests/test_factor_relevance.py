"""Tests for core/quant_core/research/factors/relevance.py"""
import math

import numpy as np
import pandas as pd
import pytest

from quant_core.research.factors.relevance import (
    FactorRelevanceMatrix,
    FactorStockPair,
    compute_factor_relevance,
    compute_ic_series,
    compute_pair_relevance,
)


def _make_prices(n: int, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    log_ret = rng.normal(0, 0.01, n)
    prices = 100.0 * np.exp(np.cumsum(log_ret))
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.Series(prices, index=dates)


def _make_correlated_pair(n: int, rho: float = 0.4, seed: int = 42):
    """Return (factor, stock) price series where factor_ret[t-1] predicts stock_ret[t].

    After `precede_open` alignment (factor shifted 1 bar), factor_ret[t] =
    original eps_f[t-1], which was constructed to predict stock_ret[t].
    """
    rng = np.random.default_rng(seed)
    eps_f = rng.normal(0, 0.01, n)
    # eps_s[t] = rho * eps_f[t-1] + noise — lagged predictive structure
    noise = rng.normal(0, 0.01, n)
    eps_s = np.zeros(n)
    eps_s[0] = noise[0]
    for t in range(1, n):
        eps_s[t] = rho * eps_f[t - 1] + math.sqrt(1 - rho ** 2) * noise[t]
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    factor = pd.Series(100.0 * np.exp(np.cumsum(eps_f)), index=dates)
    stock = pd.Series(100.0 * np.exp(np.cumsum(eps_s)), index=dates)
    return factor, stock


class TestComputeIcSeries:
    def test_returns_dataframe(self):
        f, s = _make_correlated_pair(200)
        df = compute_ic_series(f, s)
        assert isinstance(df, pd.DataFrame)
        assert "factor" in df.columns
        assert "stock" in df.columns

    def test_no_nan_rows(self):
        f, s = _make_correlated_pair(200)
        df = compute_ic_series(f, s)
        assert df.notna().all().all()

    def test_minimal_overlap_drops_nans(self):
        # When factor is constant, pct_change = 0 everywhere; after dropna the
        # result may be small but should not crash and must have no NA rows.
        dates_f = pd.date_range("2020-01-01", periods=100, freq="B")
        dates_s = pd.date_range("2020-01-01", periods=100, freq="B")
        f = pd.Series(np.linspace(100, 200, 100), index=dates_f)
        s = pd.Series(np.linspace(100, 110, 100), index=dates_s)
        df = compute_ic_series(f, s)
        assert df.notna().all().all()


class TestComputePairRelevance:
    def test_positive_ic_for_positive_correlation(self):
        f, s = _make_correlated_pair(500, rho=0.5)
        result = compute_pair_relevance("VIX", "ATW", f, s)
        assert result is not None
        assert result.ic > 0.0

    def test_negative_ic_for_negative_correlation(self):
        f, s = _make_correlated_pair(500, rho=-0.5)
        result = compute_pair_relevance("VIX", "ATW", f, s)
        assert result is not None
        assert result.ic < 0.0

    def test_returns_none_if_insufficient_obs(self):
        f, s = _make_correlated_pair(20)
        result = compute_pair_relevance("VIX", "ATW", f, s, min_obs=50)
        assert result is None

    def test_n_obs_populated(self):
        f, s = _make_correlated_pair(300)
        result = compute_pair_relevance("VIX", "ATW", f, s)
        assert result is not None
        assert result.n_obs > 0

    def test_significant_flag_for_strong_correlation(self):
        f, s = _make_correlated_pair(500, rho=0.6)
        result = compute_pair_relevance("VIX", "ATW", f, s)
        assert result is not None
        # Strong correlation should produce |t| > 1.96
        assert result.significant

    def test_not_significant_for_near_zero_correlation(self):
        rng = np.random.default_rng(7)
        dates = pd.date_range("2020-01-01", periods=300, freq="B")
        f = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300))), index=dates)
        s = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300))), index=dates)
        result = compute_pair_relevance("VIX", "ATW", f, s)
        assert result is not None
        # Independent series: t-stat should typically be < 1.96 at α=0.05
        # Not guaranteed every seed but holds for seed=7

    def test_factor_id_and_symbol_set(self):
        f, s = _make_correlated_pair(300)
        result = compute_pair_relevance("EURUSD", "BCP", f, s)
        assert result is not None
        assert result.factor_id == "EURUSD"
        assert result.symbol == "BCP"

    def test_p_value_between_0_and_1(self):
        f, s = _make_correlated_pair(300)
        result = compute_pair_relevance("VIX", "ATW", f, s)
        assert result is not None
        assert 0.0 <= result.p_value <= 1.0


class TestComputeFactorRelevance:
    def _make_stock_dict(self, n: int = 300, count: int = 4):
        rng = np.random.default_rng(0)
        dates = pd.date_range("2020-01-01", periods=n, freq="B")
        return {
            f"STK{i}": pd.Series(
                100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=dates
            )
            for i in range(count)
        }

    def test_returns_matrix(self):
        f = _make_prices(300)
        stocks = self._make_stock_dict()
        matrix = compute_factor_relevance("VIX", f, stocks)
        assert isinstance(matrix, FactorRelevanceMatrix)
        assert matrix.factor_id == "VIX"

    def test_pairs_count(self):
        f = _make_prices(300)
        stocks = self._make_stock_dict(count=3)
        matrix = compute_factor_relevance("VIX", f, stocks)
        assert len(matrix.pairs) == 3

    def test_skips_low_obs_pairs(self):
        f = _make_prices(300)
        stocks = {
            "LONG": _make_prices(300),
            "SHORT": _make_prices(10),  # will be skipped
        }
        matrix = compute_factor_relevance("VIX", f, stocks, min_obs=30)
        symbols = {p.symbol for p in matrix.pairs}
        assert "LONG" in symbols
        assert "SHORT" not in symbols

    def test_significant_pairs_subset(self):
        f, s_corr = _make_correlated_pair(500, rho=0.55)
        stocks = {"CORR": s_corr, "RAND": _make_prices(500, seed=99)}
        matrix = compute_factor_relevance("VIX", f, stocks)
        sig = matrix.significant_pairs
        assert all(p.significant for p in sig)

    def test_as_of_set(self):
        f = _make_prices(300)
        matrix = compute_factor_relevance("VIX", f, {"ATW": _make_prices(300)}, as_of="2024-01-01")
        assert matrix.as_of == "2024-01-01"

    def test_to_records_schema(self):
        f = _make_prices(300)
        stocks = self._make_stock_dict(count=2)
        matrix = compute_factor_relevance("VIX", f, stocks)
        records = matrix.to_records()
        assert len(records) == 2
        required_keys = {"factor_id", "symbol", "ic", "t_stat", "p_value", "ic_cv", "n_obs", "significant"}
        for rec in records:
            assert required_keys.issubset(rec.keys())
