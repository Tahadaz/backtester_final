from __future__ import annotations

from core.quant_core.wfo.statistical import deflated_sharpe_ratio, monte_carlo_permutation_test


def test_monte_carlo_permutation_returns_expected_shapes() -> None:
    returns = [0.05, -0.02, 0.04, -0.01, 0.03, 0.02, -0.03, 0.06]
    result = monte_carlo_permutation_test(returns, n_simulations=250, seed=7)
    assert 0.0 < result.p_value <= 1.0
    assert len(result.actual_curve) == len(returns) + 1
    assert len(result.sampled_curves) <= 200
    assert set(result.percentile_bands) == {5, 25, 50, 75, 95}


def test_deflated_sharpe_ratio_detects_strong_edge() -> None:
    returns = [0.03] * 45 + [-0.005] * 15
    result = deflated_sharpe_ratio(returns, n_variants_tested=12)
    assert result.observed_sharpe > 0
    assert result.p_value < 0.05
    assert result.significant

