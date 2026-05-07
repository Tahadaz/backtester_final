"""Signal evaluation harness.

Single entry point used by (a) existing TA signals from the signal engine,
(b) Phase 1 factor signals. Produces a SignalEvaluationReport with the full
statistical battery described in docs/factor-layer/05-statistical-battery.md.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .domain import ICCurve, PortfolioStats, RobustnessReport, SignalEvaluationReport
from .stats.ic import ic_decay_curve, conditional_return_tstat, _spearman_corr
from .stats.hit_rate import directional_hit_rate
from .stats.robustness import (
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
    stationary_bootstrap_ci,
    rolling_metric_cv,
)
from .stats.portfolio_stats import compute_portfolio_stats


_DEFAULT_HORIZONS = [1, 2, 3, 5, 10]
_DEFAULT_COSTS = {"spread_bps": 15.0, "commission_bps": 10.0}


def evaluate_signal(
    signal: pd.Series,
    prices: pd.Series,
    signal_id: str = "signal",
    symbol: str = "unknown",
    horizons: list[int] | None = None,
    costs: dict | None = None,
    n_variants: int = 1,
    periods_per_year: int = 252,
    signal_threshold: float = 0.0,
    bootstrap_samples: int = 500,
    forward_returns: pd.Series | None = None,
    ic_prices: pd.Series | None = None,
) -> SignalEvaluationReport:
    """Evaluate a signal series against prices.

    Args:
        signal: pd.Series (date index, values in {-1,0,1} or continuous).
                Values > signal_threshold → long; < -signal_threshold → short.
        prices: pd.Series (date index, close prices).
        signal_id: identifier for the report.
        symbol: stock ticker for the report.
        horizons: forward-return horizons in days (default [1,2,3,5,10]).
        costs: dict with spread_bps and commission_bps (default 15+10 bps).
        n_variants: number of variants tested (for DSR; default 1 = no correction).
        periods_per_year: annualization factor (default 252 for daily).
        signal_threshold: abs threshold above which signal fires (default 0).
        bootstrap_samples: stationary bootstrap replications (default 500).
        forward_returns: pre-computed 1-day forward return series. When provided,
            used instead of prices.pct_change(1).shift(-1) for hit rate, cond
            t-stat, portfolio sim, and DSR. Allows open_to_open / open_to_close.
        ic_prices: price series to use for the multi-horizon IC decay curve.
            When provided, replaces `prices` in ic_decay_curve. Pass
            open_prices.shift(-1) for open_to_open IC.

    Returns:
        SignalEvaluationReport with all metrics populated.
    """
    if horizons is None:
        horizons = _DEFAULT_HORIZONS
    if costs is None:
        costs = _DEFAULT_COSTS

    aligned = pd.concat([signal, prices], axis=1).dropna()
    n_obs = len(aligned)

    sig = aligned.iloc[:, 0]
    px = aligned.iloc[:, 1]

    # --- IC decay curve ---
    ic_px = ic_prices if ic_prices is not None else px
    ic_results = ic_decay_curve(sig, ic_px, horizons=horizons)

    ic_curve = ICCurve(
        horizons=horizons,
        ic_values=[ic_results[h]["ic"] for h in horizons],
        ic_se=[ic_results[h]["se"] for h in horizons],
        ic_ci_lower=[ic_results[h]["ci_lower"] for h in horizons],
        ic_ci_upper=[ic_results[h]["ci_upper"] for h in horizons],
        n_obs=[ic_results[h]["n"] for h in horizons],
    )

    # --- Directional hit rate at horizon 1 ---
    fwd_h1 = forward_returns if forward_returns is not None else px.pct_change(1).shift(-1)
    hit_result = directional_hit_rate(sig, fwd_h1, threshold=signal_threshold)

    # --- Conditional return t-stat at horizon 1 ---
    cond_tstat = conditional_return_tstat(sig, fwd_h1, threshold=signal_threshold)

    # --- Portfolio stats ---
    port_dict = compute_portfolio_stats(
        sig, px,
        spread_bps=costs.get("spread_bps", 15.0),
        commission_bps=costs.get("commission_bps", 10.0),
        periods_per_year=periods_per_year,
        signal_threshold=signal_threshold,
        forward_returns=forward_returns,
    )

    portfolio = PortfolioStats(
        sharpe=port_dict["sharpe"],
        sortino=port_dict["sortino"],
        max_drawdown=port_dict["max_drawdown"],
        calmar=port_dict["calmar"],
        turnover=port_dict["turnover"],
        hit_rate=port_dict["hit_rate"],
        profit_factor=port_dict["profit_factor"],
        avg_win=port_dict["avg_win"],
        avg_loss=port_dict["avg_loss"],
        after_cost_sharpe=port_dict["after_cost_sharpe"],
        n_trades=port_dict["n_trades"],
        total_return=port_dict["total_return"],
    )

    # --- Robustness ---
    # Strategy returns for DSR/PSR
    pos = pd.Series(0.0, index=sig.index)
    pos[sig > signal_threshold] = 1.0
    pos[sig < -signal_threshold] = -1.0
    daily_ret = forward_returns if forward_returns is not None else px.pct_change().shift(-1)
    strat_ret = (pos * daily_ret).dropna().values

    if len(strat_ret) >= 10:
        psr = probabilistic_sharpe_ratio(strat_ret, sr_benchmark=0.0)
        dsr = deflated_sharpe_ratio(strat_ret, n_variants=n_variants)

        def _sharpe_fn(r: np.ndarray) -> float:
            if len(r) < 5:
                return float("nan")
            mu, sigma = np.mean(r), np.std(r, ddof=1)
            return float(mu / sigma) if sigma > 0 else float("nan")

        sharpe_ci = stationary_bootstrap_ci(strat_ret, _sharpe_fn, n_bootstrap=bootstrap_samples)

        # IC bootstrap at horizon 1
        ic_vals = []
        fwd_h1_arr = fwd_h1.reindex(sig.index).dropna()
        sig_aligned = sig.reindex(fwd_h1_arr.index).dropna()
        fwd_aligned = fwd_h1_arr.reindex(sig_aligned.index)
        if len(sig_aligned) >= 10:
            def _ic_fn(idx: np.ndarray) -> float:
                s = pd.Series(sig_aligned.values[idx.astype(int)])
                r = pd.Series(fwd_aligned.values[idx.astype(int)])
                return float(s.corr(r, method="spearman"))

            rng = np.random.default_rng(42)
            for _ in range(bootstrap_samples):
                idx = rng.integers(0, len(sig_aligned), size=len(sig_aligned))
                try:
                    ic_vals.append(_spearman_corr(sig_aligned.iloc[idx], fwd_aligned.iloc[idx]))
                except Exception:
                    pass

        if len(ic_vals) >= 10:
            ic_ci = (float(np.percentile(ic_vals, 2.5)), float(np.percentile(ic_vals, 97.5)))
        else:
            ic_ci = (float("nan"), float("nan"))

        # Rolling CV
        ic_series = [ic_results[1]["ic"]] * max(1, len(strat_ret) // 63)  # placeholder
        ic_cv = rolling_metric_cv(strat_ret, window=min(63, len(strat_ret) // 3))
        sharpe_cv = rolling_metric_cv(strat_ret, window=min(63, len(strat_ret) // 3), stat_fn=_sharpe_fn)
    else:
        nan = float("nan")
        psr, dsr = nan, nan
        sharpe_ci = (nan, nan)
        ic_ci = (nan, nan)
        ic_cv, sharpe_cv = nan, nan

    robustness = RobustnessReport(
        dsr=dsr,
        psr=psr,
        sharpe_bootstrap_ci_lower=sharpe_ci[0],
        sharpe_bootstrap_ci_upper=sharpe_ci[1],
        ic_bootstrap_ci_lower=ic_ci[0],
        ic_bootstrap_ci_upper=ic_ci[1],
        ic_cv=ic_cv,
        sharpe_cv=sharpe_cv,
        n_variants=n_variants,
    )

    return SignalEvaluationReport(
        signal_id=signal_id,
        symbol=symbol,
        n_obs=n_obs,
        ic_curve=ic_curve,
        hit_rate_h1=hit_result["hit_rate"],
        hit_rate_ci_lower=hit_result["ci_lower"],
        hit_rate_ci_upper=hit_result["ci_upper"],
        conditional_return_tstat=cond_tstat,
        portfolio=portfolio,
        robustness=robustness,
        horizons=horizons,
    )
