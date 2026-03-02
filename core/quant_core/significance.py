from __future__ import annotations

import math
from typing import Any

import numpy as np


def _to_returns(values: Any) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    return arr.astype(float, copy=False)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def sharpe_ratio(returns: Any, *, periods_per_year: int = 252) -> float:
    r = _to_returns(returns)
    if len(r) < 2:
        return float("nan")
    vol = float(np.std(r, ddof=1))
    if vol <= 0 or not math.isfinite(vol):
        return float("nan")
    mean = float(np.mean(r))
    return float(mean / vol * math.sqrt(float(periods_per_year)))


def t_stat_mean_return(returns: Any) -> dict[str, Any]:
    r = _to_returns(returns)
    n = len(r)
    if n < 2:
        return {
            "nobs": int(n),
            "mean": float(np.mean(r)) if n else None,
            "std": None,
            "t_stat": None,
            "pvalue": None,
            "method": "mean_return_t_stat_normal_approx",
        }

    mean = float(np.mean(r))
    std = float(np.std(r, ddof=1))
    if std <= 0 or not math.isfinite(std):
        t_stat = None
        pvalue = None
    else:
        t_stat = float(mean / (std / math.sqrt(float(n))))
        pvalue = float(2.0 * (1.0 - _norm_cdf(abs(t_stat))))

    return {
        "nobs": int(n),
        "mean": mean,
        "std": std,
        "t_stat": t_stat,
        "pvalue": pvalue,
        "method": "mean_return_t_stat_normal_approx",
    }


def monte_carlo_luck_test(
    returns: Any,
    *,
    metric: str = "sharpe",
    n_iter: int = 2000,
    seed: int = 42,
    periods_per_year: int = 252,
) -> dict[str, Any]:
    r = _to_returns(returns)
    n = len(r)
    if n < 3:
        return {
            "metric": metric,
            "nobs": int(n),
            "observed": None,
            "pvalue": None,
            "null_quantiles": {},
            "method": "bootstrap_centered_returns",
        }

    metric_key = str(metric).strip().lower()
    if metric_key not in {"sharpe", "total_return"}:
        raise ValueError("metric must be 'sharpe' or 'total_return'.")

    def _metric_fn(x: np.ndarray) -> float:
        if metric_key == "sharpe":
            return float(sharpe_ratio(x, periods_per_year=periods_per_year))
        return float(np.prod(1.0 + x) - 1.0)

    observed = _metric_fn(r)
    centered = r - float(np.mean(r))

    rng = np.random.default_rng(int(seed))
    null = np.empty(int(n_iter), dtype=float)
    for i in range(int(n_iter)):
        sample = centered[rng.integers(0, n, size=n)]
        null[i] = _metric_fn(sample)

    if observed >= 0:
        pvalue = float(np.mean(null >= observed))
    else:
        pvalue = float(np.mean(null <= observed))

    quantiles = {
        "q01": float(np.quantile(null, 0.01)),
        "q05": float(np.quantile(null, 0.05)),
        "q50": float(np.quantile(null, 0.50)),
        "q95": float(np.quantile(null, 0.95)),
        "q99": float(np.quantile(null, 0.99)),
    }

    return {
        "metric": metric_key,
        "nobs": int(n),
        "iterations": int(n_iter),
        "seed": int(seed),
        "observed": float(observed),
        "pvalue": pvalue,
        "null_quantiles": quantiles,
        "method": "bootstrap_centered_returns",
    }


def evaluate_significance(
    returns_by_key: dict[str, Any],
    *,
    n_iter: int = 2000,
    seed: int = 42,
    periods_per_year: int = 252,
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for key, values in sorted(dict(returns_by_key or {}).items()):
        r = _to_returns(values)
        if len(r) < 3:
            continue
        t_res = t_stat_mean_return(r)
        mc_sharpe = monte_carlo_luck_test(
            r,
            metric="sharpe",
            n_iter=n_iter,
            seed=seed,
            periods_per_year=periods_per_year,
        )
        out[str(key)] = {
            "t_test": t_res,
            "mc_sharpe": mc_sharpe,
        }
    return out
