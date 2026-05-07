"""Deflated Sharpe, Probabilistic Sharpe, stationary bootstrap CI, rolling CV.

References:
- Bailey & López de Prado (2014), Journal of Portfolio Management — DSR/PSR.
- Harvey, Liu & Zhu (2016), RFS — E[SR_max] formula.
- Politis & Romano (1994), JASA — stationary bootstrap.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd


def _standard_normal_cdf(x: float) -> float:
    """Standard normal CDF via complementary error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))


def _euler_mascheroni() -> float:
    return 0.5772156649015328


def harvey_liu_expected_max_sharpe(n_variants: int, sr_annualized: bool = False) -> float:
    """E[SR_max] from Harvey, Liu & Zhu (2016) RFS.

    Expected maximum Sharpe ratio from n_variants independent tests:
        E[SR_max] = (1 - γ)·Φ⁻¹(1 - 1/N) + γ·Φ⁻¹(1 - 1/(N·e))
    where γ = Euler-Mascheroni constant ≈ 0.5772.

    Result is in per-period (same units as the input Sharpe).
    n_variants=1 → E[SR_max]=0 (no multiple testing correction).
    """
    if n_variants <= 1:
        return 0.0

    gamma = _euler_mascheroni()
    e = math.e

    def norm_ppf(p: float) -> float:
        # Rational approximation (same as in hit_rate.py)
        from .hit_rate import _norm_ppf
        return _norm_ppf(p)

    p1 = 1.0 - 1.0 / n_variants
    p2 = 1.0 - 1.0 / (n_variants * e)

    # Clamp away from 0 and 1 to avoid inf
    p1 = max(1e-9, min(1.0 - 1e-9, p1))
    p2 = max(1e-9, min(1.0 - 1e-9, p2))

    return (1.0 - gamma) * norm_ppf(p1) + gamma * norm_ppf(p2)


def probabilistic_sharpe_ratio(
    returns: np.ndarray,
    sr_benchmark: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """PSR: probability that true Sharpe > sr_benchmark.

    Bailey & López de Prado (2014):
        PSR(SR*) = Φ[ √(T-1)·(ŜR - SR*) / √(1 - γ₃·ŜR + (γ₄-1)/4·ŜR²) ]

    Returns and sr_benchmark should be in the SAME units (per-period or annualized).
    This function uses per-period returns; convert sr_benchmark if annualized.
    """
    T = len(returns)
    if T < 5:
        return float("nan")

    mu = float(np.mean(returns))
    sigma = float(np.std(returns, ddof=1))
    if sigma == 0:
        return float("nan")

    sr_hat = mu / sigma  # per-period Sharpe

    gamma3 = float(np.mean(((returns - mu) / sigma) ** 3))
    gamma4 = float(np.mean(((returns - mu) / sigma) ** 4))  # kurtosis (not excess)

    # Bailey & LdP denominator (with excess kurtosis = gamma4 - 3)
    excess_kurtosis = gamma4 - 3.0
    denom_sq = 1.0 - gamma3 * sr_hat + (excess_kurtosis / 4.0) * sr_hat ** 2
    if denom_sq <= 0:
        denom_sq = 1e-9

    z = math.sqrt(T - 1) * (sr_hat - sr_benchmark) / math.sqrt(denom_sq)
    return _standard_normal_cdf(z)


def deflated_sharpe_ratio(
    returns: np.ndarray,
    n_variants: int = 1,
    periods_per_year: int = 252,
) -> float:
    """DSR: PSR with benchmark = E[SR_max(n_variants)] from Harvey-Liu-Zhu.

    Bailey & López de Prado (2014) + Harvey, Liu & Zhu (2016).
    DSR < 0.5 means the observed Sharpe is likely due to selection bias.
    """
    sr_max = harvey_liu_expected_max_sharpe(n_variants)
    return probabilistic_sharpe_ratio(returns, sr_benchmark=sr_max, periods_per_year=periods_per_year)


def stationary_bootstrap_ci(
    x: np.ndarray,
    stat_fn,
    n_bootstrap: int = 1000,
    block_prob: float = 0.05,
    alpha: float = 0.05,
    rng_seed: Optional[int] = 42,
) -> tuple[float, float]:
    """95% CI via Politis-Romano (1994) stationary bootstrap.

    block_prob = 1/expected_block_length (default: 0.05 → avg block = 20 obs).
    stat_fn: callable(array) → float (e.g., sharpe).
    Returns (lower, upper) empirical percentile CI.
    """
    T = len(x)
    if T < 10:
        return (float("nan"), float("nan"))

    rng = np.random.default_rng(rng_seed)
    stats = np.empty(n_bootstrap)

    for b in range(n_bootstrap):
        sample = np.empty(T)
        i = 0
        start = int(rng.integers(0, T))
        while i < T:
            block_len = int(rng.geometric(block_prob))
            block_len = min(block_len, T - i)
            for j in range(block_len):
                sample[i] = x[(start + j) % T]
                i += 1
                if i >= T:
                    break
            if i < T:
                start = int(rng.integers(0, T))

        try:
            stats[b] = stat_fn(sample)
        except Exception:
            stats[b] = float("nan")

    stats = stats[~np.isnan(stats)]
    if len(stats) < 10:
        return (float("nan"), float("nan"))

    lo = float(np.percentile(stats, 100 * alpha / 2))
    hi = float(np.percentile(stats, 100 * (1 - alpha / 2)))
    return (lo, hi)


def rolling_metric_cv(
    x: np.ndarray,
    window: int = 63,
    stat_fn=None,
) -> float:
    """Coefficient of variation of a rolling statistic (mean/std).

    Used for IC stability and Sharpe stability assessment.
    Default stat_fn: mean (used for IC CV).
    Returns |std / mean| of the rolling estimates, or nan if insufficient data.
    """
    if stat_fn is None:
        stat_fn = np.mean

    if len(x) < window + 5:
        return float("nan")

    rolling_vals = []
    for i in range(window, len(x) + 1):
        val = stat_fn(x[i - window:i])
        if not math.isnan(val):
            rolling_vals.append(val)

    if len(rolling_vals) < 3:
        return float("nan")

    arr = np.array(rolling_vals)
    mu = float(np.mean(arr))
    if mu == 0:
        return float("nan")
    return float(abs(np.std(arr, ddof=1) / mu))
