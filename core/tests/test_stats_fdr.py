"""Tests for Benjamini-Hochberg FDR control and Harvey-Liu haircut."""
import pytest
import numpy as np

from quant_core.research.stats.fdr import (
    benjamini_hochberg,
    bh_adjusted_pvalues,
    harvey_liu_sharpe_haircut,
)


class TestBenjaminiHochberg:
    def test_all_null_pvalues_no_rejections(self):
        # Uniform p-values from null distribution → expected FDR ≤ q, so some rejections
        # but with q=0.10 on 20 uniform p-values, most will not be rejected
        rng = np.random.default_rng(0)
        p_vals = list(rng.uniform(0.1, 1.0, 20))
        rejected = benjamini_hochberg(p_vals, q=0.10)
        # None should be rejected since all p-values > 0.10
        assert not any(rejected)

    def test_clear_signals_rejected(self):
        # Mix of very small (signal) and large (null) p-values
        p_vals = [0.001, 0.002, 0.003, 0.5, 0.6, 0.7, 0.8, 0.9]
        rejected = benjamini_hochberg(p_vals, q=0.10)
        assert rejected[0] and rejected[1] and rejected[2]
        assert not rejected[4] and not rejected[5]

    def test_empty_list(self):
        assert benjamini_hochberg([], q=0.10) == []

    def test_single_significant(self):
        rejected = benjamini_hochberg([0.001], q=0.10)
        assert len(rejected) == 1 and rejected[0]

    def test_single_not_significant(self):
        rejected = benjamini_hochberg([0.5], q=0.10)
        assert len(rejected) == 1 and not rejected[0]

    def test_inject_known_nulls(self):
        # 20 known nulls + 5 strong signals; BH should catch signals and miss nulls
        rng = np.random.default_rng(42)
        null_p = list(rng.uniform(0.3, 1.0, 20))
        signal_p = [1e-5, 2e-5, 3e-5, 4e-5, 5e-5]
        all_p = null_p + signal_p
        rejected = benjamini_hochberg(all_p, q=0.10)
        # All 5 signals should be rejected
        assert all(rejected[20:])
        # At most 10% of nulls should be rejected (FDR control)
        null_rejections = sum(rejected[:20])
        assert null_rejections <= 2

    def test_output_length_matches_input(self):
        p_vals = [0.01, 0.05, 0.10, 0.20]
        result = benjamini_hochberg(p_vals, q=0.10)
        assert len(result) == 4


class TestBHAdjustedPvalues:
    def test_adjusted_geq_original(self):
        p_vals = [0.001, 0.01, 0.05, 0.1, 0.5]
        adjusted = bh_adjusted_pvalues(p_vals)
        for orig, adj in zip(p_vals, adjusted):
            assert adj >= orig

    def test_all_adjusted_leq_one(self):
        p_vals = [0.4, 0.6, 0.8, 0.9]
        adjusted = bh_adjusted_pvalues(p_vals)
        assert all(a <= 1.0 for a in adjusted)

    def test_empty(self):
        assert bh_adjusted_pvalues([]) == []


class TestHarveyLiuHaircut:
    def test_single_variant_no_haircut(self):
        assert harvey_liu_sharpe_haircut(0.5, n_variants=1, t_obs=252) == 0.0

    def test_negative_sharpe_no_haircut(self):
        assert harvey_liu_sharpe_haircut(-0.5, n_variants=10, t_obs=252) == 0.0

    def test_more_variants_higher_haircut(self):
        # Use sr_hat=3.0 so E[SR_max] < sr_hat for both N (avoids clamping to 1.0)
        h10 = harvey_liu_sharpe_haircut(3.0, n_variants=10, t_obs=252)
        h100 = harvey_liu_sharpe_haircut(3.0, n_variants=100, t_obs=252)
        assert h100 > h10

    def test_haircut_in_0_1(self):
        h = harvey_liu_sharpe_haircut(0.5, n_variants=20, t_obs=252)
        assert 0.0 <= h <= 1.0
