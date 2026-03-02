from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_ADF_CRITICAL_VALUES = {
    "1%": -3.43,
    "5%": -2.86,
    "10%": -2.57,
}


def _to_array(series: Any) -> np.ndarray:
    if isinstance(series, pd.Series):
        values = series.astype(float).to_numpy()
    else:
        values = np.asarray(series, dtype=float)
    values = values[np.isfinite(values)]
    return values.astype(float, copy=False)


def _ols(y: np.ndarray, x: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    resid = y - x @ beta
    rss = float(np.dot(resid, resid))
    return beta, resid, rss


def _adf_design(y: np.ndarray, lags: int) -> tuple[np.ndarray, np.ndarray]:
    dy = np.diff(y)
    y_lag = y[:-1]
    dep = dy[lags:]
    cols = [np.ones(len(dep), dtype=float), y_lag[lags:]]
    for i in range(1, lags + 1):
        cols.append(dy[lags - i : len(dy) - i])
    return dep, np.column_stack(cols)


def _adf_pvalue_approx(stat: float, critical_values: dict[str, float]) -> float:
    cv1 = float(critical_values["1%"])
    cv5 = float(critical_values["5%"])
    cv10 = float(critical_values["10%"])

    if stat <= cv1:
        return 0.005
    if stat <= cv5:
        ratio = (stat - cv1) / (cv5 - cv1)
        return 0.01 + ratio * 0.04
    if stat <= cv10:
        ratio = (stat - cv5) / (cv10 - cv5)
        return 0.05 + ratio * 0.05

    # Very rough upper tail approximation for non-rejection region.
    z = max(0.0, stat - cv10)
    p = 0.1 + 0.9 * (1.0 - math.exp(-0.9 * z))
    return min(0.999, max(0.101, p))


def adf_test(
    series: Any,
    *,
    max_lags: int | None = None,
    autolag: bool = True,
) -> dict[str, Any]:
    y = _to_array(series)
    n = len(y)
    if n < 25:
        raise ValueError("ADF requires at least 25 finite observations.")

    if max_lags is None:
        max_lags = max(1, min(12, int(math.sqrt(n))))
    max_lags = max(0, min(max_lags, n // 4))

    best: dict[str, Any] | None = None
    for lag in range(max_lags + 1):
        try:
            dep, x = _adf_design(y, lag)
            nobs, nparams = x.shape
            if nobs <= nparams + 1:
                continue
            beta, resid, rss = _ols(dep, x)
            xtx_inv = np.linalg.inv(x.T @ x)
            sigma2 = float(np.dot(resid, resid) / (nobs - nparams))
            stderr = float(math.sqrt(max(xtx_inv[1, 1] * sigma2, 1e-18)))
            t_stat = float(beta[1] / stderr)
            aic = float(nobs * np.log(max(rss / nobs, 1e-18)) + 2 * nparams)
            candidate = {
                "lag": lag,
                "nobs": int(nobs),
                "t_stat": t_stat,
                "aic": aic,
            }
            if best is None:
                best = candidate
                continue
            if autolag and candidate["aic"] < best["aic"]:
                best = candidate
            if not autolag and lag == max_lags:
                best = candidate
        except np.linalg.LinAlgError:
            continue

    if best is None:
        raise ValueError("ADF regression could not be estimated.")

    critical_values = dict(DEFAULT_ADF_CRITICAL_VALUES)
    stat = float(best["t_stat"])
    pvalue = _adf_pvalue_approx(stat, critical_values)

    return {
        "statistic": stat,
        "pvalue": pvalue,
        "used_lags": int(best["lag"]),
        "nobs": int(best["nobs"]),
        "critical_values": critical_values,
        "is_stationary_5pct": bool(stat < critical_values["5%"]),
        "method": "adf_ols_approx",
    }


def estimate_half_life(spread: Any) -> dict[str, Any]:
    x = _to_array(spread)
    if len(x) < 25:
        raise ValueError("Half-life requires at least 25 finite observations.")

    y = np.diff(x)
    x_lag = x[:-1]
    design = np.column_stack([np.ones(len(x_lag), dtype=float), x_lag])
    beta, resid, _ = _ols(y, design)
    slope = float(beta[1])

    half_life = math.inf
    if slope < 0:
        half_life = float(-math.log(2.0) / slope)

    y_mean = float(np.mean(y))
    tss = float(np.dot(y - y_mean, y - y_mean))
    rss = float(np.dot(resid, resid))
    r2 = 1.0 - (rss / tss) if tss > 1e-18 else 0.0

    return {
        "lambda": slope,
        "half_life": half_life,
        "intercept": float(beta[0]),
        "r2": float(r2),
        "nobs": int(len(y)),
        "method": "ou_regression",
    }


def cadf_cointegration(
    y: Any,
    x: Any,
    *,
    max_lags: int | None = None,
) -> dict[str, Any]:
    y_arr = _to_array(y)
    x_arr = _to_array(x)
    n = min(len(y_arr), len(x_arr))
    if n < 50:
        raise ValueError("CADF requires at least 50 aligned finite observations.")

    y_arr = y_arr[-n:]
    x_arr = x_arr[-n:]

    design = np.column_stack([np.ones(n, dtype=float), x_arr])
    beta, _, _ = _ols(y_arr, design)
    intercept = float(beta[0])
    hedge_ratio = float(beta[1])
    spread = y_arr - (intercept + hedge_ratio * x_arr)

    adf = adf_test(spread, max_lags=max_lags, autolag=True)
    hl = estimate_half_life(spread)

    return {
        "hedge_ratio": hedge_ratio,
        "intercept": intercept,
        "adf_stat": float(adf["statistic"]),
        "pvalue": float(adf["pvalue"]),
        "used_lags": int(adf["used_lags"]),
        "critical_values": dict(adf["critical_values"]),
        "is_cointegrated_5pct": bool(adf["is_stationary_5pct"]),
        "spread_half_life": float(hl["half_life"]),
        "nobs": int(n),
        "method": "cadf_ols",
    }
