"""
Stage 4: factor-level CUSUM and CUSUM-SQ monitoring via RecursiveLS.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.regression.recursive_ls import RecursiveLS


def calculate_cusum_drift(
    target_returns: pd.Series,
    factor_signal: pd.Series,
    *,
    threshold: float = 1.0,
) -> dict[str, float | bool | list[float]]:
    aligned = pd.concat(
        [
            target_returns.rename("target"),
            factor_signal.rename("factor_signal"),
        ],
        axis=1,
        join="inner",
    ).dropna()
    if len(aligned) < 25:
        return {
            "drift_score": 0.0,
            "cusum_score": 0.0,
            "cusum_sq_score": 0.0,
            "alarm": False,
            "cusum_path": [],
            "cusum_sq_path": [],
        }

    X = sm.add_constant(aligned["factor_signal"].to_numpy(dtype=float))
    y = aligned["target"].to_numpy(dtype=float)
    model = RecursiveLS(y, X)
    fitted = model.fit()

    cusum = np.asarray(fitted.cusum, dtype=float)
    cusum_sq = np.asarray(fitted.cusum_squares, dtype=float)
    cusum_score = float(np.nanmax(np.abs(cusum))) if cusum.size else 0.0
    cusum_sq_score = float(np.nanmax(np.abs(cusum_sq - 1.0))) if cusum_sq.size else 0.0
    drift_score = max(cusum_score, cusum_sq_score)
    return {
        "drift_score": drift_score,
        "cusum_score": cusum_score,
        "cusum_sq_score": cusum_sq_score,
        "alarm": bool(drift_score >= threshold),
        "cusum_path": cusum.tolist(),
        "cusum_sq_path": cusum_sq.tolist(),
    }
