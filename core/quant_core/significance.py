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
    block_mean: int | None = None,
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
    block = int(block_mean) if block_mean is not None else 0
    use_blocks = block > 1
    for i in range(int(n_iter)):
        if use_blocks:
            sample = _stationary_block_sample(centered, rng=rng, block_mean=block)
        else:
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
        "method": "stationary_block_bootstrap_centered_returns" if use_blocks else "bootstrap_centered_returns",
        "block_mean": block if use_blocks else None,
    }


def _stationary_block_sample(values: np.ndarray, *, rng: np.random.Generator, block_mean: int) -> np.ndarray:
    """Politis-Romano style stationary block sample with circular wrapping."""
    x = np.asarray(values, dtype=float)
    n = len(x)
    if n == 0:
        return x.copy()
    p = 1.0 / max(float(block_mean), 1.0)
    out = np.empty(n, dtype=float)
    pos = int(rng.integers(0, n))
    for i in range(n):
        if i == 0 or rng.random() < p:
            pos = int(rng.integers(0, n))
        else:
            pos = (pos + 1) % n
        out[i] = x[pos]
    return out


def _block_permutation(values: np.ndarray, *, rng: np.random.Generator, block_len: int) -> np.ndarray:
    """Shuffle contiguous non-overlapping blocks while preserving within-block order."""
    x = np.asarray(values)
    n = len(x)
    if n == 0:
        return x.copy()
    b = max(1, int(block_len))
    starts = list(range(0, n, b))
    order = rng.permutation(len(starts))
    parts = [x[starts[i]: min(starts[i] + b, n)] for i in order]
    return np.concatenate(parts)[:n]


def monte_carlo_label_shuffle_test(
    score_series: Any,
    forward_returns: Any,
    *,
    bucket: str,
    n_iter: int = 2000,
    seed: int = 42,
    block_mean: int | None = None,
) -> dict[str, Any]:
    """Test whether a bucket label is informative.

    H0: bucket assignment is uninformative — i.e., shuffling the score-to-date
    mapping produces a distribution of bucket-mean forward returns equivalent
    to the observed bucket mean. Returns the same shape as
    `monte_carlo_luck_test`. The 'observed' field is the actual bucket mean;
    the null is built by shuffling `score_series`'s index labels (preserving
    the marginal score distribution) and recomputing the bucket mean.

    Inputs are aligned by date (intersection of indices). `bucket` must be one
    of the canonical bucket names (e.g. 'strong_buy'). The test uses the same
    `_bucket_for` thresholds as the rest of the score-history pipeline.
    """
    import pandas as pd  # local to avoid hard dep at import time
    from .research.score_history import _bucket_for  # noqa: WPS433

    score = pd.Series(score_series).dropna()
    fwd = pd.Series(forward_returns).dropna()
    aligned = pd.concat([score.rename("score"), fwd.rename("fwd")], axis=1).dropna()
    if aligned.empty:
        return {
            "metric": "bucket_mean",
            "bucket": str(bucket),
            "nobs": 0,
            "observed": None,
            "pvalue": None,
            "null_quantiles": {},
            "method": "bucket_label_shuffle",
        }

    scores_arr = aligned["score"].to_numpy(dtype="float64")
    fwd_arr = aligned["fwd"].to_numpy(dtype="float64")
    buckets_arr = np.array([_bucket_for(float(s)) for s in scores_arr])

    mask_obs = buckets_arr == str(bucket)
    n_obs = int(mask_obs.sum())
    if n_obs < 3:
        return {
            "metric": "bucket_mean",
            "bucket": str(bucket),
            "nobs": n_obs,
            "observed": float(np.mean(fwd_arr[mask_obs])) if n_obs else None,
            "pvalue": None,
            "null_quantiles": {},
            "method": "bucket_label_shuffle",
        }

    observed = float(np.mean(fwd_arr[mask_obs]))

    rng = np.random.default_rng(int(seed))
    n_total = len(scores_arr)
    null = np.empty(int(n_iter), dtype=float)
    block = int(block_mean) if block_mean is not None else 0
    use_blocks = block > 1
    for i in range(int(n_iter)):
        permuted_buckets = (
            _block_permutation(buckets_arr, rng=rng, block_len=block)
            if use_blocks
            else buckets_arr[rng.permutation(n_total)]
        )
        sub = fwd_arr[permuted_buckets == str(bucket)]
        null[i] = float(np.mean(sub)) if len(sub) else float("nan")

    null_finite = null[np.isfinite(null)]
    if len(null_finite) == 0:
        pvalue = None
        quantiles: dict[str, float] = {}
    else:
        if observed >= 0:
            pvalue = float(np.mean(null_finite >= observed))
        else:
            pvalue = float(np.mean(null_finite <= observed))
        quantiles = {
            "q01": float(np.quantile(null_finite, 0.01)),
            "q05": float(np.quantile(null_finite, 0.05)),
            "q50": float(np.quantile(null_finite, 0.50)),
            "q95": float(np.quantile(null_finite, 0.95)),
            "q99": float(np.quantile(null_finite, 0.99)),
        }

    return {
        "metric": "bucket_mean",
        "bucket": str(bucket),
        "nobs": n_obs,
        "iterations": int(n_iter),
        "seed": int(seed),
        "observed": observed,
        "pvalue": pvalue,
        "null_quantiles": quantiles,
        "method": "bucket_label_block_shuffle" if use_blocks else "bucket_label_shuffle",
        "block_mean": block if use_blocks else None,
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
