from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

import numpy as np


@dataclass(frozen=True)
class RegressionResult:
    beta: float
    r2: float | None
    n_obs: int
    intercept: float = 0.0


def _r2(y: np.ndarray, fitted: np.ndarray) -> float | None:
    total = float(np.sum((y - y.mean()) ** 2))
    if total <= 0.0:
        return None
    resid = float(np.sum((y - fitted) ** 2))
    return max(0.0, min(1.0, 1.0 - resid / total))


def ols_beta(y: np.ndarray, x: np.ndarray) -> RegressionResult:
    if len(y) != len(x) or len(y) < 2:
        raise ValueError("OLS beta requires at least two aligned observations")
    x_centered = x - x.mean()
    y_centered = y - y.mean()
    denom = float(np.dot(x_centered, x_centered))
    if denom <= 0.0:
        raise ValueError("market return variance is zero")
    beta = float(np.dot(x_centered, y_centered) / denom)
    intercept = float(y.mean() - beta * x.mean())
    fitted = intercept + beta * x
    return RegressionResult(beta=beta, intercept=intercept, r2=_r2(y, fitted), n_obs=len(y))


def _finite_pair_arrays(strat_ret: list[float | None], bench_ret: list[float | None]) -> tuple[np.ndarray, np.ndarray]:
    pairs: list[tuple[float, float]] = []
    for strat, bench in zip(strat_ret, bench_ret):
        if strat is None or bench is None:
            continue
        strat_f = float(strat)
        bench_f = float(bench)
        if isfinite(strat_f) and isfinite(bench_f):
            pairs.append((strat_f, bench_f))
    if not pairs:
        empty = np.asarray([], dtype="float64")
        return empty, empty
    strat_arr = np.asarray([pair[0] for pair in pairs], dtype="float64")
    bench_arr = np.asarray([pair[1] for pair in pairs], dtype="float64")
    return strat_arr, bench_arr


def market_model(
    strat_ret: list[float | None],
    bench_ret: list[float | None] | None,
    *,
    periods_per_year: int = 252,
    min_obs: int = 20,
) -> dict[str, Any]:
    """Return effective-book market exposure from traded path returns.

    ``strat_ret`` is the traded equity path return stream, including flat zero
    days. This measures the book's realized market exposure, not the underlying
    stock's standalone beta.
    """

    if bench_ret is None:
        return {
            "beta": None,
            "alpha_annualized": None,
            "alpha_r2": None,
            "alpha_n_obs": 0,
            "alpha_reason": "benchmark_unavailable",
        }

    strat, bench = _finite_pair_arrays(strat_ret, bench_ret)
    nonzero_strat_days = int(np.sum(np.abs(strat) > 1e-12)) if strat.size else 0
    if strat.size < int(min_obs) or nonzero_strat_days < 10:
        return {
            "beta": None,
            "alpha_annualized": None,
            "alpha_r2": None,
            "alpha_n_obs": int(strat.size),
            "alpha_reason": "insufficient_overlap",
        }

    try:
        ols = ols_beta(strat, bench)
    except ValueError:
        return {
            "beta": None,
            "alpha_annualized": None,
            "alpha_r2": None,
            "alpha_n_obs": int(strat.size),
            "alpha_reason": "insufficient_overlap",
        }

    return {
        "beta": float(ols.beta),
        "alpha_annualized": float(ols.intercept * float(periods_per_year)),
        "alpha_r2": ols.r2,
        "alpha_n_obs": int(ols.n_obs),
        "alpha_reason": "ok",
    }
