"""
Stage 3: Adaptive LASSO with simple purged time-series cross-validation.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import Lasso, Ridge
from sklearn.preprocessing import StandardScaler


@dataclass(frozen=True)
class AdaptiveLassoResult:
    coefficients: dict[str, float]
    ranks: dict[str, int]


def _purged_time_series_splits(n_obs: int, n_splits: int, purge_size: int) -> list[tuple[np.ndarray, np.ndarray]]:
    if n_obs < max(30, n_splits * 10):
        return []
    fold_edges = np.linspace(0, n_obs, n_splits + 1, dtype=int)
    splits: list[tuple[np.ndarray, np.ndarray]] = []
    for i in range(1, len(fold_edges)):
        test_start = fold_edges[i - 1]
        test_end = fold_edges[i]
        train_end = max(0, test_start - purge_size)
        if train_end < 20 or test_end - test_start < 5:
            continue
        train_idx = np.arange(0, train_end)
        test_idx = np.arange(test_start, test_end)
        splits.append((train_idx, test_idx))
    return splits


def _fit_initial_weights(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    ridge = Ridge(alpha=1.0)
    ridge.fit(X, y)
    return 1.0 / np.maximum(np.abs(ridge.coef_), 1e-4)


def _fit_adaptive_lasso_for_alpha(X: np.ndarray, y: np.ndarray, weights: np.ndarray, alpha: float) -> Lasso:
    X_weighted = X / weights
    model = Lasso(alpha=alpha, fit_intercept=True, max_iter=20_000)
    model.fit(X_weighted, y)
    model.coef_ = model.coef_ / weights
    return model


def select_factors_lasso(
    target_returns: pd.Series,
    factor_features: pd.DataFrame,
    *,
    max_selected: int = 3,
    cv_folds: int = 5,
    purge_size: int = 5,
) -> AdaptiveLassoResult:
    aligned = pd.concat([target_returns.rename("target"), factor_features], axis=1, join="inner").dropna()
    if aligned.empty or len(aligned) < 30:
        return AdaptiveLassoResult(coefficients={}, ranks={})

    y = aligned["target"].to_numpy(dtype=float)
    X = aligned.drop(columns=["target"])
    factor_ids = list(X.columns)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X.to_numpy(dtype=float))
    weights = _fit_initial_weights(X_scaled, y)

    alphas = np.logspace(-4, 0, 20)
    splits = _purged_time_series_splits(len(aligned), cv_folds, purge_size)
    best_alpha = None
    best_score = float("inf")

    for alpha in alphas:
        fold_errors: list[float] = []
        for train_idx, test_idx in splits:
            model = _fit_adaptive_lasso_for_alpha(X_scaled[train_idx], y[train_idx], weights, alpha)
            preds = model.predict(X_scaled[test_idx] / weights)
            fold_errors.append(float(np.mean((y[test_idx] - preds) ** 2)))
        if not fold_errors:
            continue
        score = float(np.mean(fold_errors))
        if score < best_score:
            best_score = score
            best_alpha = alpha

    if best_alpha is None:
        best_alpha = 0.01

    final_model = _fit_adaptive_lasso_for_alpha(X_scaled, y, weights, best_alpha)
    raw_coefs = final_model.coef_ / np.where(scaler.scale_ == 0, 1.0, scaler.scale_)
    ranked = [
        (factor_ids[idx], float(coef))
        for idx, coef in enumerate(raw_coefs)
        if abs(float(coef)) > 1e-8
    ]
    ranked.sort(key=lambda item: (-abs(item[1]), item[0]))
    ranked = ranked[:max_selected]

    coefficients = {factor_id: coef for factor_id, coef in ranked}
    ranks = {factor_id: idx + 1 for idx, (factor_id, _) in enumerate(ranked)}
    return AdaptiveLassoResult(coefficients=coefficients, ranks=ranks)
