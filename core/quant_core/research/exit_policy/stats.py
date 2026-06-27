"""Bootstrap CIs and data-snooping-corrected significance tests.

Implements:
  - Paired stationary block bootstrap CI for mean return difference.
  - White's Reality Check p-value (conservative).
  - Hansen's SPA p-value (consistent; zeroes out clearly inferior models).

References:
  White (2000) "A Reality Check for Data Snooping", Econometrica.
  Hansen (2005) "A Test for Superior Predictive Ability", JBES.
  Politis & Romano (1994) stationary bootstrap.
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np


def _auto_block_size(n: int) -> int:
    """Rule-of-thumb block size: ceil(n^(1/3)), min 5."""
    return max(5, math.ceil(n ** (1 / 3)))


def _stationary_bootstrap_indices(n: int, block_size: int, rng: np.random.Generator) -> np.ndarray:
    """Generate one resample of length n using the stationary bootstrap.

    Each block starts at a random position and has geometric(1/block_size) length.
    """
    indices = np.empty(n, dtype=np.intp)
    p = 1.0 / block_size
    i = 0
    while i < n:
        start = int(rng.integers(0, n))
        length = int(rng.geometric(p))
        for j in range(length):
            if i >= n:
                break
            indices[i] = (start + j) % n
            i += 1
    return indices


def block_bootstrap_ci(
    a: np.ndarray,
    b: np.ndarray,
    *,
    B: int = 10_000,
    block_size: int | None = None,
    alpha: float = 0.05,
    seed: int = 42,
) -> dict[str, float]:
    """Bootstrap 95% CI for mean(b) - mean(a) using paired stationary bootstrap.

    a: baseline returns (Policy A), one value per trade event.
    b: alternative policy returns (same events).
    Returns: {mean_diff, ci_lower, ci_upper, p_one_sided}
             p_one_sided = fraction of bootstrap samples where b* - a* <= 0
             (i.e., alternative fails to beat baseline in that resample).
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    if n < 2:
        return {"mean_diff": 0.0, "ci_lower": 0.0, "ci_upper": 0.0, "p_one_sided": 1.0}

    d = b - a
    d_bar = float(d.mean())
    bs = block_size or _auto_block_size(n)
    rng = np.random.default_rng(seed)

    boot_means = np.empty(B)
    for i in range(B):
        idx = _stationary_bootstrap_indices(n, bs, rng)
        boot_means[i] = d[idx].mean()

    # Centered bootstrap distribution for CI
    boot_centered = boot_means - d_bar
    lo = float(d_bar - np.quantile(boot_centered, 1 - alpha / 2))
    hi = float(d_bar - np.quantile(boot_centered, alpha / 2))
    p = float(np.mean(boot_means <= 0.0))

    return {
        "mean_diff": d_bar,
        "ci_lower": lo,
        "ci_upper": hi,
        "p_one_sided": p,
    }


def reality_check_pvalue(
    baseline: np.ndarray,
    alternatives: np.ndarray,
    *,
    B: int = 10_000,
    block_size: int | None = None,
    seed: int = 42,
) -> float:
    """White's Reality Check p-value for H0: no alternative beats baseline.

    baseline:     shape (n,) baseline policy returns per trade event.
    alternatives: shape (n, K) returns for K alternative policies.

    Returns the Reality Check p-value: probability that the best-looking
    alternative beats the baseline by at least the observed amount under H0.
    The snooping-corrected p is valid across all K alternatives simultaneously.
    """
    baseline = np.asarray(baseline, dtype=np.float64)
    alternatives = np.asarray(alternatives, dtype=np.float64)
    if alternatives.ndim == 1:
        alternatives = alternatives[:, None]

    n = len(baseline)
    if n < 2 or alternatives.shape[0] < 2:
        return 1.0

    # Loss differentials per event: d[t, k] = alt_k[t] - baseline[t]
    d = alternatives - baseline[:, None]  # (n, K)
    d_bar = d.mean(axis=0)              # (K,)
    T_rc = float(d_bar.max())            # test statistic: best mean differential

    bs = block_size or _auto_block_size(n)
    rng = np.random.default_rng(seed)

    exceed_count = 0
    for _ in range(B):
        idx = _stationary_bootstrap_indices(n, bs, rng)
        # Centered bootstrap means (subtract observed mean to impose H0: d_bar = 0)
        boot_d_bar = d[idx].mean(axis=0) - d_bar
        if boot_d_bar.max() >= T_rc:
            exceed_count += 1

    return float(exceed_count / B)


def spa_pvalue(
    baseline: np.ndarray,
    alternatives: np.ndarray,
    *,
    B: int = 10_000,
    block_size: int | None = None,
    seed: int = 42,
) -> float:
    """Hansen's SPA p-value (consistent; less conservative than Reality Check).

    Uses Hansen's consistent selection of the reference distribution:
    models with d_bar_k < 0 are zeroed out in the bootstrap null
    (they're clearly inferior and shouldn't inflate the max).

    Returns SPA p-value for H0: no alternative is superior to baseline.
    """
    baseline = np.asarray(baseline, dtype=np.float64)
    alternatives = np.asarray(alternatives, dtype=np.float64)
    if alternatives.ndim == 1:
        alternatives = alternatives[:, None]

    n = len(baseline)
    if n < 2 or alternatives.shape[0] < 2:
        return 1.0

    d = alternatives - baseline[:, None]  # (n, K)
    d_bar = d.mean(axis=0)               # (K,)
    T_spa = float(d_bar.max())

    # Variance of d_bar_k (for Hansen's consistent centering selector)
    omega = d.std(axis=0, ddof=1)        # (K,)
    omega_safe = np.where(omega <= 0.0, 1.0, omega)

    bs = block_size or _auto_block_size(n)
    rng = np.random.default_rng(seed)

    exceed_count = 0
    for _ in range(B):
        idx = _stationary_bootstrap_indices(n, bs, rng)
        boot_d_bar = d[idx].mean(axis=0)  # (K,) bootstrap means

        # Hansen's consistent centering: use max(d_bar_k, 0) as center
        # (sets center to 0 for clearly inferior models)
        center = np.maximum(d_bar, 0.0)
        boot_centered = boot_d_bar - center
        if boot_centered.max() >= T_spa:
            exceed_count += 1

    return float(exceed_count / B)


def summarize_policy_stats(
    baseline_returns: np.ndarray,
    policy_returns: dict[str, np.ndarray],
    *,
    B: int = 10_000,
    block_size: int | None = None,
    seed: int = 42,
) -> dict[str, dict[str, float]]:
    """Compute per-policy bootstrap CI and SPA p-value.

    Runs the SPA across all alternative policies simultaneously (correct snooping correction).

    Returns dict: {policy_name: {mean_diff, ci_lower, ci_upper, p_one_sided, spa_pvalue}}
    """
    baseline = np.asarray(baseline_returns, dtype=np.float64)
    n = len(baseline)

    keys = list(policy_returns.keys())
    if not keys:
        return {}

    alts = np.stack([np.asarray(policy_returns[k], dtype=np.float64)[:n] for k in keys], axis=1)

    # Global SPA p-value across all alternatives
    global_spa_p = spa_pvalue(baseline, alts, B=B, block_size=block_size, seed=seed)
    global_rc_p = reality_check_pvalue(baseline, alts, B=B, block_size=block_size, seed=seed + 1)

    results: dict[str, dict[str, float]] = {}
    for i, key in enumerate(keys):
        ci = block_bootstrap_ci(baseline, alts[:, i], B=B, block_size=block_size, seed=seed + 2 + i)
        results[key] = {
            "mean_diff": ci["mean_diff"],
            "ci_lower": ci["ci_lower"],
            "ci_upper": ci["ci_upper"],
            "p_one_sided": ci["p_one_sided"],
            "spa_pvalue": global_spa_p,
            "rc_pvalue": global_rc_p,
        }

    return results
