"""Direct IC-composite factor ranking for production Factor×TA selection."""

from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Literal

import numpy as np
import pandas as pd
import statsmodels.api as sm


SelectionReason = Literal["normal", "low_confidence", "not_selected", "insufficient_obs"]


@dataclass(frozen=True)
class DirectSelectionConfig:
    horizon_days: int
    min_normal_obs: int = 252
    min_fallback_obs: int = 126
    min_abs_spearman: float = 0.03
    min_abs_t_stat: float = 1.0
    min_score: float = 0.20
    max_selected: int = 3


def _nw_maxlags(n_obs: int) -> int:
    if n_obs <= 1:
        return 1
    return max(1, int(floor(4.0 * (n_obs / 100.0) ** (2.0 / 9.0))))


def _safe_corr(left: pd.Series, right: pd.Series, method: str) -> float:
    value = left.corr(right, method=method)
    return float(value) if np.isfinite(value) else 0.0


def _hac_t_stat(target: pd.Series, factor_return: pd.Series) -> float:
    if len(target) < 3:
        return 0.0
    try:
        X = sm.add_constant(factor_return)
        fit = sm.OLS(target, X).fit(
            cov_type="HAC",
            cov_kwds={"maxlags": _nw_maxlags(len(target))},
        )
        value = float(fit.tvalues.iloc[1])
    except Exception:
        return 0.0
    return value if np.isfinite(value) else 0.0


def direct_ic_composite_score(
    *,
    spearman_ic: float,
    pearson_corr: float,
    t_stat: float,
    coverage: float,
) -> float:
    return float(
        0.45 * abs(spearman_ic)
        + 0.25 * abs(pearson_corr)
        + 0.25 * min(abs(t_stat) / 3.0, 1.0)
        + 0.05 * max(0.0, min(coverage, 1.0))
    )


def evaluate_direct_factor(
    stock_close: pd.Series,
    factor_close: pd.Series,
    *,
    factor_id: str,
    config: DirectSelectionConfig,
) -> dict[str, object] | None:
    stock_forward_return = stock_close.pct_change(config.horizon_days).shift(-config.horizon_days)
    factor_return = factor_close.pct_change(config.horizon_days).shift(1)
    aligned = pd.concat(
        [
            stock_forward_return.rename("stock_forward_return"),
            factor_return.rename("factor_return"),
        ],
        axis=1,
        join="inner",
    ).replace([np.inf, -np.inf], np.nan).dropna()
    n_obs = int(len(aligned))
    if n_obs < config.min_fallback_obs:
        return {
            "factor_id": factor_id,
            "spearman_ic": 0.0,
            "pearson_corr": 0.0,
            "ic_t_stat": 0.0,
            "relevance_score": 0.0,
            "n_obs": n_obs,
            "coverage": 0.0,
            "direction": "flat",
            "selected_reason": "insufficient_obs",
            "normal_confidence": False,
        }

    denominator = max(int(stock_forward_return.replace([np.inf, -np.inf], np.nan).dropna().shape[0]), 1)
    coverage = min(float(n_obs) / float(denominator), 1.0)
    spearman_ic = _safe_corr(aligned["factor_return"], aligned["stock_forward_return"], "spearman")
    pearson_corr = _safe_corr(aligned["factor_return"], aligned["stock_forward_return"], "pearson")
    t_stat = _hac_t_stat(aligned["stock_forward_return"], aligned["factor_return"])
    score = direct_ic_composite_score(
        spearman_ic=spearman_ic,
        pearson_corr=pearson_corr,
        t_stat=t_stat,
        coverage=coverage,
    )
    normal_confidence = bool(
        n_obs >= config.min_normal_obs
        and abs(spearman_ic) >= config.min_abs_spearman
        and abs(t_stat) >= config.min_abs_t_stat
        and score >= config.min_score
    )
    direction = "positive" if spearman_ic > 0 else ("negative" if spearman_ic < 0 else "flat")
    return {
        "factor_id": factor_id,
        "spearman_ic": spearman_ic,
        "pearson_corr": pearson_corr,
        "ic_t_stat": t_stat,
        "relevance_score": score,
        "n_obs": n_obs,
        "coverage": coverage,
        "direction": direction,
        "selected_reason": "normal" if normal_confidence else "not_selected",
        "normal_confidence": normal_confidence,
    }


def rank_direct_factors(
    stock_close: pd.Series,
    factor_close_by_id: dict[str, pd.Series],
    *,
    config: DirectSelectionConfig,
) -> pd.DataFrame:
    rows = [
        row
        for factor_id, factor_close in factor_close_by_id.items()
        if (row := evaluate_direct_factor(stock_close, factor_close, factor_id=factor_id, config=config)) is not None
    ]
    if not rows:
        return pd.DataFrame(
            columns=[
                "factor_id",
                "spearman_ic",
                "pearson_corr",
                "ic_t_stat",
                "relevance_score",
                "n_obs",
                "coverage",
                "direction",
                "selected_reason",
                "normal_confidence",
            ]
        )
    frame = pd.DataFrame(rows)
    return frame.sort_values(
        by=["relevance_score", "n_obs", "factor_id"],
        ascending=[False, False, True],
    ).reset_index(drop=True)


def select_direct_factors(
    ranked: pd.DataFrame,
    *,
    usable_factor_ids: set[str],
    config: DirectSelectionConfig,
) -> pd.DataFrame:
    if ranked.empty:
        return ranked.copy()

    usable = ranked[ranked["factor_id"].isin(usable_factor_ids)].copy()
    if usable.empty:
        return usable

    normal = usable[usable["normal_confidence"].astype(bool)].copy()
    if not normal.empty:
        selected = normal.head(config.max_selected).copy()
        selected["selected_reason"] = "normal"
    else:
        fallback = usable[usable["n_obs"].astype(int) >= config.min_fallback_obs].head(1).copy()
        if fallback.empty:
            return fallback
        selected = fallback
        selected["selected_reason"] = "low_confidence"

    selected["rank"] = range(1, len(selected) + 1)
    return selected
