"""Information Coefficient and conditional-return statistics.

References:
- Grinold & Kahn, Active Portfolio Management, 2nd ed. (2000), Ch. 6 — IC definition.
- Newey & West (1987), Econometrica — HAC standard errors.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd


def _newey_west_var(x: np.ndarray, bandwidth: Optional[int] = None) -> float:
    """Newey-West HAC variance of the sample mean of x.

    Newey & West (1987): Var_NW(x̄) = γ₀/T + (2/T)·Σ_{k=1}^{L}(1-k/(L+1))·γₖ
    where γₖ = sample autocovariance at lag k.
    """
    T = len(x)
    if T < 3:
        return np.nan
    if bandwidth is None:
        bandwidth = max(1, int(4 * (T / 100) ** (2 / 9)))

    xc = x - x.mean()
    gamma0 = float(np.dot(xc, xc)) / T

    nw_var = gamma0
    for k in range(1, bandwidth + 1):
        w = 1.0 - k / (bandwidth + 1)
        gamma_k = float(np.dot(xc[k:], xc[:-k])) / T
        nw_var += 2.0 * w * gamma_k

    return nw_var / T


def _spearman_corr(a: pd.Series, b: pd.Series) -> float:
    """Spearman rank correlation via ranked Pearson (no scipy dependency).

    Uses pandas .rank() for tie-averaging then computes Pearson on ranks.
    """
    ra = a.rank()
    rb = b.rank()
    # Pearson correlation on ranks = Spearman
    n = len(ra)
    if n < 3:
        return float("nan")
    mean_ra = ra.mean()
    mean_rb = rb.mean()
    cov = ((ra - mean_ra) * (rb - mean_rb)).sum()
    std_ra = math.sqrt(((ra - mean_ra) ** 2).sum())
    std_rb = math.sqrt(((rb - mean_rb) ** 2).sum())
    if std_ra == 0 or std_rb == 0:
        return float("nan")
    return float(cov / (std_ra * std_rb))


def rank_ic(signal: pd.Series, forward_returns: pd.Series) -> float:
    """Spearman rank IC: correlation of signal vs N-day forward return.

    Grinold & Kahn (2000) Ch. 6: IC is the cross-sectional Spearman correlation
    between forecasts and outcomes. Here applied time-series (one stock).
    """
    aligned = pd.concat([signal, forward_returns], axis=1).dropna()
    if len(aligned) < 5:
        return float("nan")
    s = aligned.iloc[:, 0]
    r = aligned.iloc[:, 1]
    return _spearman_corr(s, r)


def ic_decay_curve(
    signal: pd.Series,
    prices: pd.Series,
    horizons: list[int] | None = None,
) -> dict[int, dict]:
    """IC and 95% CI at each forward-return horizon.

    CI via Fisher z-transform: SE ≈ 1/√(n-3), then transform back.
    Returns dict keyed by horizon with keys: ic, se, ci_lower, ci_upper, n.
    """
    if horizons is None:
        horizons = [1, 2, 3, 5, 10]

    results: dict[int, dict] = {}
    for h in horizons:
        fwd_ret = prices.pct_change(h).shift(-h)
        aligned = pd.concat([signal, fwd_ret], axis=1).dropna()
        n = len(aligned)

        if n < 10:
            results[h] = {"ic": float("nan"), "se": float("nan"), "ci_lower": float("nan"), "ci_upper": float("nan"), "n": n}
            continue

        ic = _spearman_corr(aligned.iloc[:, 0], aligned.iloc[:, 1])

        if math.isnan(ic):
            results[h] = {"ic": float("nan"), "se": float("nan"), "ci_lower": float("nan"), "ci_upper": float("nan"), "n": n}
            continue

        # Fisher z-transform CI (Grinold & Kahn Ch. 6 approximation)
        z = math.atanh(max(-0.9999, min(0.9999, ic)))
        se_z = 1.0 / math.sqrt(n - 3)
        ci_lower = math.tanh(z - 1.96 * se_z)
        ci_upper = math.tanh(z + 1.96 * se_z)
        # SE in correlation scale via delta method: se_r ≈ se_z * (1 - ic²)
        se_r = se_z * (1.0 - ic ** 2)

        results[h] = {"ic": ic, "se": se_r, "ci_lower": ci_lower, "ci_upper": ci_upper, "n": n}

    return results


def conditional_return_tstat(
    signal: pd.Series,
    forward_returns: pd.Series,
    threshold: float = 0.0,
    bandwidth: Optional[int] = None,
) -> float:
    """Newey-West t-stat: mean(fwd_return | signal > threshold) vs unconditional mean.

    Newey & West (1987): HAC correction for autocorrelation in daily return series.
    Returns t-statistic (positive = signal fires on above-average return days).
    """
    aligned = pd.concat([signal, forward_returns], axis=1).dropna()
    if len(aligned) < 10:
        return float("nan")

    sig = aligned.iloc[:, 0]
    ret = aligned.iloc[:, 1]

    conditional = ret[sig > threshold].values
    unconditional = ret.values

    if len(conditional) < 5:
        return float("nan")

    mean_cond = float(np.mean(conditional))
    mean_uncond = float(np.mean(unconditional))
    diff = mean_cond - mean_uncond

    # Excess return series: deviation of conditional observation from unconditional mean
    excess = conditional - mean_uncond
    nw_var = _newey_west_var(excess, bandwidth=bandwidth)

    if nw_var is None or np.isnan(nw_var) or nw_var <= 0:
        return float("nan")

    return diff / math.sqrt(nw_var)
