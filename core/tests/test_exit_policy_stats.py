"""Tests for bootstrap CI and SPA/Reality Check significance tests.

Invariants:
  - Identical return series → zero mean difference, CI contains zero.
  - SPA and RC p-values are in [0, 1].
  - Clearly superior alternative → low p-value (stochastic, so uses wide margin).
  - Clearly inferior alternative → p-value close to 1.
"""
from __future__ import annotations

import numpy as np
import pytest

from core.quant_core.research.exit_policy.stats import (
    block_bootstrap_ci,
    reality_check_pvalue,
    spa_pvalue,
    summarize_policy_stats,
)


class TestBlockBootstrapCI:
    def test_identical_series_zero_diff(self):
        rng = np.random.default_rng(0)
        a = rng.normal(0, 1, 100)
        ci = block_bootstrap_ci(a, a, B=500, seed=0)
        assert abs(ci["mean_diff"]) < 1e-10
        assert ci["ci_lower"] <= 0.0 <= ci["ci_upper"]

    def test_clearly_superior_alternative(self):
        rng = np.random.default_rng(1)
        a = rng.normal(0.00, 0.01, 200)       # baseline: ~0 mean
        b = rng.normal(0.02, 0.01, 200)       # alternative: +2% mean
        ci = block_bootstrap_ci(a, b, B=1000, seed=1)
        assert ci["mean_diff"] == pytest.approx(b.mean() - a.mean(), abs=0.001)
        assert ci["ci_lower"] > 0.0, "CI should be entirely above zero"
        assert ci["p_one_sided"] < 0.10

    def test_clearly_inferior_alternative(self):
        rng = np.random.default_rng(2)
        a = rng.normal(0.01, 0.01, 200)
        b = rng.normal(-0.01, 0.01, 200)
        ci = block_bootstrap_ci(a, b, B=500, seed=2)
        assert ci["mean_diff"] < 0.0
        assert ci["p_one_sided"] > 0.5

    def test_short_series(self):
        ci = block_bootstrap_ci(np.array([0.0]), np.array([0.0]), B=100, seed=0)
        assert ci["mean_diff"] == pytest.approx(0.0)

    def test_ci_ordered(self):
        rng = np.random.default_rng(3)
        a = rng.normal(0, 1, 50)
        b = rng.normal(0.1, 1, 50)
        ci = block_bootstrap_ci(a, b, B=500, seed=3)
        assert ci["ci_lower"] <= ci["ci_upper"]


class TestRealityCheck:
    def test_p_in_unit_interval(self):
        rng = np.random.default_rng(4)
        baseline = rng.normal(0, 1, 100)
        alts = rng.normal(0, 1, (100, 5))
        p = reality_check_pvalue(baseline, alts, B=200, seed=4)
        assert 0.0 <= p <= 1.0

    def test_all_inferior_alts_high_p(self):
        rng = np.random.default_rng(5)
        baseline = rng.normal(0.03, 0.01, 300)
        alts = rng.normal(-0.02, 0.01, (300, 3))
        p = reality_check_pvalue(baseline, alts, B=500, seed=5)
        assert p > 0.20, "All inferior alts should give high p-value"

    def test_one_clearly_superior_alt_low_p(self):
        rng = np.random.default_rng(6)
        baseline = rng.normal(0.00, 0.005, 500)
        good_alt = rng.normal(0.03, 0.005, 500)
        bad_alts = rng.normal(-0.01, 0.005, (500, 4))
        alts = np.column_stack([good_alt, bad_alts])
        p = reality_check_pvalue(baseline, alts, B=1000, seed=6)
        assert p < 0.15

    def test_single_alternative(self):
        rng = np.random.default_rng(7)
        baseline = rng.normal(0, 1, 100)
        alt = rng.normal(0, 1, 100)
        p = reality_check_pvalue(baseline, alt, B=200, seed=7)
        assert 0.0 <= p <= 1.0


class TestSPA:
    def test_p_in_unit_interval(self):
        rng = np.random.default_rng(8)
        baseline = rng.normal(0, 1, 100)
        alts = rng.normal(0, 1, (100, 5))
        p = spa_pvalue(baseline, alts, B=200, seed=8)
        assert 0.0 <= p <= 1.0

    def test_spa_leq_rc_or_similar(self):
        # SPA is less conservative than RC; SPA p ≤ RC p (not guaranteed every sample but
        # holds in expectation). We just verify both are valid.
        rng = np.random.default_rng(9)
        baseline = rng.normal(0, 1, 200)
        alts = rng.normal(0.5, 1, (200, 5))
        p_rc = reality_check_pvalue(baseline, alts, B=500, seed=9)
        p_spa = spa_pvalue(baseline, alts, B=500, seed=9)
        assert 0.0 <= p_spa <= 1.0
        assert 0.0 <= p_rc <= 1.0

    def test_all_inferior_high_p(self):
        rng = np.random.default_rng(10)
        baseline = rng.normal(0.03, 0.01, 300)
        alts = rng.normal(-0.02, 0.01, (300, 3))
        p = spa_pvalue(baseline, alts, B=500, seed=10)
        assert p > 0.20

    def test_degenerate_identical_series(self):
        a = np.ones(50) * 0.01
        b = np.ones(50) * 0.01
        ci = block_bootstrap_ci(a, b, B=100, seed=0)
        assert ci["mean_diff"] == pytest.approx(0.0, abs=1e-10)


class TestSummarizePolicyStats:
    def test_returns_dict_per_policy(self):
        rng = np.random.default_rng(11)
        baseline = rng.normal(0, 0.01, 100)
        alts = {
            "B_ksl1.5_ktp1.5": rng.normal(0, 0.01, 100),
            "C_wf": rng.normal(0.005, 0.01, 100),
        }
        result = summarize_policy_stats(baseline, alts, B=200, seed=11)
        assert set(result.keys()) == set(alts.keys())
        for k, v in result.items():
            assert "mean_diff" in v
            assert "ci_lower" in v
            assert "ci_upper" in v
            assert "spa_pvalue" in v
            assert 0.0 <= v["spa_pvalue"] <= 1.0

    def test_empty_alternatives(self):
        baseline = np.ones(50)
        result = summarize_policy_stats(baseline, {}, B=100, seed=0)
        assert result == {}

    def test_spa_pvalue_shared_across_policies(self):
        # SPA is computed globally; all policies share the same SPA p-value
        rng = np.random.default_rng(12)
        baseline = rng.normal(0, 0.01, 100)
        alts = {
            "X": rng.normal(0, 0.01, 100),
            "Y": rng.normal(0, 0.01, 100),
        }
        result = summarize_policy_stats(baseline, alts, B=200, seed=12)
        assert result["X"]["spa_pvalue"] == result["Y"]["spa_pvalue"]
