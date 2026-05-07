"""False Discovery Rate control and Harvey-Liu Sharpe haircut.

References:
- Benjamini & Hochberg (1995), JRSS-B — BH procedure for FDR control.
- Harvey, Liu & Zhu (2016), RFS — Sharpe ratio haircut for data mining.
"""
from __future__ import annotations

import numpy as np


def benjamini_hochberg(
    p_values: list[float],
    q: float = 0.10,
) -> list[bool]:
    """BH procedure: control expected FDR at level q.

    Benjamini & Hochberg (1995): sort p-values p_(1) ≤ … ≤ p_(m); find the
    largest k such that p_(k) ≤ (k/m)·q; reject all H₀ for i ≤ k.

    Args:
        p_values: list of p-values (one per hypothesis)
        q: FDR level (default 0.10)

    Returns:
        list of bool — True = rejected (significant after FDR control)
    """
    m = len(p_values)
    if m == 0:
        return []

    arr = np.array(p_values, dtype=float)
    order = np.argsort(arr)
    sorted_p = arr[order]

    thresholds = np.arange(1, m + 1) / m * q
    rejected_sorted = sorted_p <= thresholds

    # Find the largest k where p_(k) <= threshold
    # All hypotheses up to and including k are rejected
    last_rejected = -1
    for k in range(m - 1, -1, -1):
        if rejected_sorted[k]:
            last_rejected = k
            break

    result_sorted = np.zeros(m, dtype=bool)
    if last_rejected >= 0:
        result_sorted[: last_rejected + 1] = True

    # Map back to original order
    result = np.zeros(m, dtype=bool)
    result[order] = result_sorted
    return result.tolist()


def bh_adjusted_pvalues(p_values: list[float]) -> list[float]:
    """Return BH-adjusted p-values (Benjamini & Hochberg 1995).

    Adjusted p-value for rank i: p_adj_(i) = min_{j≥i}(m/j · p_(j)), capped at 1.
    """
    m = len(p_values)
    if m == 0:
        return []

    arr = np.array(p_values, dtype=float)
    order = np.argsort(arr)
    sorted_p = arr[order]

    adjusted = sorted_p * m / np.arange(1, m + 1)
    # Enforce monotonicity from right: adjusted_p_(i) = min(adjusted_p_(i), adjusted_p_(i+1), …)
    for i in range(m - 2, -1, -1):
        adjusted[i] = min(adjusted[i], adjusted[i + 1])

    adjusted = np.minimum(adjusted, 1.0)

    result = np.empty(m)
    result[order] = adjusted
    return result.tolist()


def harvey_liu_sharpe_haircut(
    sr_hat: float,
    n_variants: int,
    t_obs: int,
) -> float:
    """Harvey-Liu-Zhu (2016) Sharpe ratio haircut for multiple testing.

    Computes the haircut = 1 - E[SR_max(n_variants)] / SR_hat.
    A haircut > 0.5 means more than half the observed Sharpe is likely spurious.

    sr_hat: observed per-period Sharpe (not annualized).
    Returns the haircut fraction in [0, 1].
    """
    from .robustness import harvey_liu_expected_max_sharpe

    if sr_hat <= 0 or n_variants <= 1:
        return 0.0

    sr_max = harvey_liu_expected_max_sharpe(n_variants)
    if sr_max >= sr_hat:
        return 1.0  # fully explained by selection bias
    return float(sr_max / sr_hat)
