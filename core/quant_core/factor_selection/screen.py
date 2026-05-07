"""
Stage 1: BH-FDR-controlled Newey-West IC screen.

This module evaluates a small menu of lagged factor transforms against
forward stock returns, applies a loose pre-gate, then controls multiple
testing with Benjamini-Hochberg FDR.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import floor

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.multitest import multipletests

TRANSFORM_NAMES: tuple[str, ...] = (
    "momentum_5d",
    "momentum_20d",
    "momentum_60d",
    "zscore_20d",
    "zscore_60d",
    "change_1d",
)


@dataclass(frozen=True)
class ScreenConfig:
    horizon_days: int
    min_obs: int = 60
    fdr_q: float = 0.10
    min_abs_ic: float = 0.02
    min_abs_t_stat: float = 1.5


def _nw_maxlags(n_obs: int) -> int:
    if n_obs <= 1:
        return 1
    return max(1, int(floor(4.0 * (n_obs / 100.0) ** (2.0 / 9.0))))


def _safe_zscore(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window).mean()
    std = series.rolling(window).std(ddof=0)
    return ((series - mean) / std.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)


def compute_factor_transform(series: pd.Series, name: str) -> pd.Series:
    if name == "momentum_5d":
        return series.pct_change(5)
    if name == "momentum_20d":
        return series.pct_change(20)
    if name == "momentum_60d":
        return series.pct_change(60)
    if name == "zscore_20d":
        return _safe_zscore(series, 20)
    if name == "zscore_60d":
        return _safe_zscore(series, 60)
    if name == "change_1d":
        return series.pct_change(1)
    raise ValueError(f"Unknown transform {name!r}")


def _build_forward_returns(close: pd.Series, horizon_days: int) -> pd.Series:
    return (close.shift(-horizon_days) - close) / close


def _evaluate_one_transform(
    stock_close: pd.Series,
    factor_close: pd.Series,
    transform_name: str,
    horizon_days: int,
    min_obs: int,
) -> dict[str, float | int | str | bool] | None:
    forward_return = _build_forward_returns(stock_close, horizon_days)
    factor_signal = compute_factor_transform(factor_close, transform_name).shift(1)
    aligned = pd.concat(
        [
            forward_return.rename("forward_return"),
            factor_signal.rename("factor_signal"),
        ],
        axis=1,
        join="inner",
    ).dropna()
    if len(aligned) < min_obs:
        return None

    ic = aligned["factor_signal"].corr(aligned["forward_return"], method="spearman")
    if not np.isfinite(ic):
        return None

    X = sm.add_constant(aligned["factor_signal"])
    model = sm.OLS(aligned["forward_return"], X).fit(
        cov_type="HAC",
        cov_kwds={"maxlags": _nw_maxlags(len(aligned))},
    )
    t_stat = float(model.tvalues.iloc[1])
    p_value = float(model.pvalues.iloc[1])
    if not np.isfinite(t_stat) or not np.isfinite(p_value):
        return None

    return {
        "transform": transform_name,
        "ic_mean": float(ic),
        "ic_tstat": t_stat,
        "p_value": p_value,
        "n_obs": int(len(aligned)),
        "passed_pre_gate": bool(abs(ic) >= 0.02 and abs(t_stat) >= 1.5),
    }


def screen_factor_candidates(
    stock_close: pd.Series,
    factor_close_by_id: dict[str, pd.Series],
    *,
    config: ScreenConfig,
) -> pd.DataFrame:
    rows: list[dict[str, float | int | str | bool]] = []
    for factor_id, factor_close in factor_close_by_id.items():
        for transform_name in TRANSFORM_NAMES:
            result = _evaluate_one_transform(
                stock_close,
                factor_close,
                transform_name,
                config.horizon_days,
                config.min_obs,
            )
            if result is None:
                continue
            rows.append({"factor_id": factor_id, **result})

    if not rows:
        return pd.DataFrame(
            columns=[
                "factor_id",
                "transform",
                "ic_mean",
                "ic_tstat",
                "p_value",
                "bh_p_adj",
                "passed_pre_gate",
                "passed_fdr",
                "n_obs",
            ]
        )

    frame = pd.DataFrame(rows)
    tested = frame["passed_pre_gate"].fillna(False).astype(bool)
    frame["bh_p_adj"] = np.nan
    frame["passed_fdr"] = False
    if tested.any():
        reject, pvals_corrected, _, _ = multipletests(
            frame.loc[tested, "p_value"],
            alpha=config.fdr_q,
            method="fdr_bh",
        )
        frame.loc[tested, "bh_p_adj"] = pvals_corrected
        frame.loc[tested, "passed_fdr"] = reject

    frame = frame.sort_values(
        by=["passed_fdr", "ic_tstat", "ic_mean", "factor_id", "transform"],
        ascending=[False, False, False, True, True],
        key=lambda col: col.abs() if col.name in {"ic_tstat", "ic_mean"} else col,
    ).reset_index(drop=True)
    return frame


def summarize_screen_results(screen_df: pd.DataFrame) -> pd.DataFrame:
    if screen_df.empty:
        return pd.DataFrame(
            columns=["factor_id", "transform", "ic_mean", "ic_tstat", "p_value", "bh_p_adj", "passed_pre_gate", "passed_fdr", "n_obs"]
        )

    ranked = screen_df.copy()
    # Rank by raw gate first (not BH) — BH kept as a diagnostic column only.
    ranked["score"] = ranked["passed_pre_gate"].astype(int) * 10_000 + ranked["ic_tstat"].abs() * 100 + ranked["ic_mean"].abs()
    ranked = ranked.sort_values(
        by=["score", "factor_id", "transform"],
        ascending=[False, True, True],
    )
    deduped = ranked.groupby("factor_id", as_index=False).first()
    return deduped[
        ["factor_id", "transform", "ic_mean", "ic_tstat", "p_value", "bh_p_adj", "passed_pre_gate", "passed_fdr", "n_obs"]
    ].reset_index(drop=True)


def screen_factors_fdr(
    stock_close: pd.Series,
    factor_close_by_id: dict[str, pd.Series],
    *,
    horizon_days: int,
    min_obs: int = 60,
    fdr_q: float = 0.10,
) -> pd.DataFrame:
    raw = screen_factor_candidates(
        stock_close,
        factor_close_by_id,
        config=ScreenConfig(horizon_days=horizon_days, min_obs=min_obs, fdr_q=fdr_q),
    )
    return summarize_screen_results(raw)
