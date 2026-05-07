"""Directional hit rate with Wilson confidence interval.

References:
- Wilson (1927), JASA — binomial proportion CI with continuity correction.
  https://www.econometrics.blog/post/the-wilson-confidence-interval-for-a-proportion/
- Grinold & Kahn (2000) Ch. 6 — directional accuracy as IC proxy.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _norm_ppf(p: float) -> float:
    """Approximation of standard normal quantile (Beasley-Springer-Moro).
    Accurate to ~1e-5 for p in (0, 1).
    """
    # Rational approximation from Peter Acklam's method
    a = [-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2,
         1.383577518672690e2, -3.066479806614716e1, 2.506628277459239]
    b = [-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2,
         6.680131188771972e1, -1.328068155288572e1]
    c = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838,
         -2.549732539343734, 4.374664141464968, 2.938163982698783]
    d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996, 3.754408661907416]

    p_low, p_high = 0.02425, 1.0 - 0.02425

    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
                ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)


def wilson_ci(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """Wilson (1927) binomial proportion CI.

    More accurate than normal approximation for small n or extreme p.
    Returns (lower, upper) bounds.
    """
    if n == 0:
        return (0.0, 1.0)
    z = _norm_ppf(1 - alpha / 2)
    p_hat = k / n
    denom = 1 + z ** 2 / n
    center = (p_hat + z ** 2 / (2 * n)) / denom
    half_width = z * math.sqrt(p_hat * (1 - p_hat) / n + z ** 2 / (4 * n ** 2)) / denom
    return (max(0.0, center - half_width), min(1.0, center + half_width))


def directional_hit_rate(
    signal: pd.Series,
    forward_returns: pd.Series,
    threshold: float = 0.0,
    alpha: float = 0.05,
) -> dict:
    """Directional accuracy of signal vs forward return direction.

    Counts: signal > threshold ↔ forward_return > 0 (long direction).
    Also computes asymmetric hit rates for BUY vs SELL calls separately.

    Returns dict with: hit_rate, ci_lower, ci_upper, n_buy_signals, n_sell_signals,
    buy_hit_rate, sell_hit_rate, buy_ci, sell_ci.
    """
    aligned = pd.concat([signal, forward_returns], axis=1).dropna()
    if len(aligned) < 5:
        return {
            "hit_rate": float("nan"), "ci_lower": float("nan"), "ci_upper": float("nan"),
            "n_buy_signals": 0, "n_sell_signals": 0,
            "buy_hit_rate": float("nan"), "sell_hit_rate": float("nan"),
            "buy_ci": [float("nan"), float("nan")], "sell_ci": [float("nan"), float("nan")],
        }

    sig = aligned.iloc[:, 0]
    ret = aligned.iloc[:, 1]

    # Overall directional accuracy (signal direction matches return direction)
    sig_dir = (sig > threshold).astype(int) * 2 - 1   # +1 or -1
    ret_dir = (ret > 0).astype(int) * 2 - 1

    correct = (sig_dir == ret_dir).sum()
    total = len(aligned)
    overall_hr = correct / total
    ci = wilson_ci(int(correct), total, alpha)

    # BUY calls only
    buy_mask = sig > threshold
    n_buy = int(buy_mask.sum())
    buy_correct = int((ret[buy_mask] > 0).sum()) if n_buy > 0 else 0
    buy_hr = buy_correct / n_buy if n_buy > 0 else float("nan")
    buy_ci = wilson_ci(buy_correct, n_buy, alpha) if n_buy > 0 else (float("nan"), float("nan"))

    # SELL calls only
    sell_mask = sig < -threshold
    n_sell = int(sell_mask.sum())
    sell_correct = int((ret[sell_mask] < 0).sum()) if n_sell > 0 else 0
    sell_hr = sell_correct / n_sell if n_sell > 0 else float("nan")
    sell_ci = wilson_ci(sell_correct, n_sell, alpha) if n_sell > 0 else (float("nan"), float("nan"))

    return {
        "hit_rate": overall_hr,
        "ci_lower": ci[0],
        "ci_upper": ci[1],
        "n_total": total,
        "n_buy_signals": n_buy,
        "n_sell_signals": n_sell,
        "buy_hit_rate": buy_hr,
        "sell_hit_rate": sell_hr,
        "buy_ci": list(buy_ci),
        "sell_ci": list(sell_ci),
    }
