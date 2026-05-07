"""Portfolio-level performance statistics.

Metrics: Sharpe, Sortino, MaxDD, Calmar, turnover, hit rate, profit factor.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd


def _sharpe(returns: np.ndarray, periods_per_year: int = 252) -> float:
    if len(returns) < 5:
        return float("nan")
    mu = float(np.mean(returns))
    sigma = float(np.std(returns, ddof=1))
    if sigma == 0:
        return float("nan")
    return mu / sigma * math.sqrt(periods_per_year)


def _sortino(returns: np.ndarray, periods_per_year: int = 252) -> float:
    if len(returns) < 5:
        return float("nan")
    mu = float(np.mean(returns))
    downside = returns[returns < 0]
    if len(downside) == 0:
        return float("inf")
    semi_std = float(np.std(downside, ddof=1))
    if semi_std == 0:
        return float("nan")
    return mu / semi_std * math.sqrt(periods_per_year)


def _max_drawdown(cumulative: np.ndarray) -> float:
    if len(cumulative) == 0:
        return 0.0
    peak = np.maximum.accumulate(cumulative)
    drawdown = (cumulative - peak) / np.where(peak == 0, 1, peak)
    return float(np.min(drawdown))


def compute_portfolio_stats(
    signal: pd.Series,
    prices: pd.Series,
    spread_bps: float = 15.0,
    commission_bps: float = 10.0,
    periods_per_year: int = 252,
    signal_threshold: float = 0.0,
    forward_returns: Optional[pd.Series] = None,
) -> dict:
    """Compute portfolio-level stats for a long/flat/short strategy driven by signal.

    signal > threshold → long; signal < -threshold → short; else flat.
    Returns dict with all portfolio metrics.

    Args:
        forward_returns: pre-computed return series. When provided, used instead of
            prices.pct_change().shift(-1). Allows open_to_open, open_to_close, etc.
    """
    if forward_returns is not None:
        aligned = pd.concat([signal, forward_returns], axis=1).dropna()
    else:
        aligned = pd.concat([signal, prices], axis=1).dropna()
    if len(aligned) < 10:
        nan = float("nan")
        return {
            "sharpe": nan, "sortino": nan, "max_drawdown": nan, "calmar": nan,
            "turnover": nan, "hit_rate": nan, "profit_factor": nan,
            "avg_win": nan, "avg_loss": nan, "after_cost_sharpe": nan,
            "n_trades": 0, "total_return": nan,
        }

    sig = aligned.iloc[:, 0]
    px = aligned.iloc[:, 1]

    # Position: +1, -1, or 0
    pos = pd.Series(0, index=sig.index, dtype=float)
    pos[sig > signal_threshold] = 1.0
    pos[sig < -signal_threshold] = -1.0

    # Daily returns — use pre-computed if provided, else close-to-close
    if forward_returns is not None:
        daily_ret = px  # already the return series from aligned
    else:
        daily_ret = px.pct_change().shift(-1)

    # Strategy returns (before cost)
    strat_ret = pos * daily_ret
    strat_ret = strat_ret.dropna()

    if len(strat_ret) < 5:
        nan = float("nan")
        return {
            "sharpe": nan, "sortino": nan, "max_drawdown": nan, "calmar": nan,
            "turnover": nan, "hit_rate": nan, "profit_factor": nan,
            "avg_win": nan, "avg_loss": nan, "after_cost_sharpe": nan,
            "n_trades": 0, "total_return": nan,
        }

    arr = strat_ret.values

    # Turnover
    pos_chg = pos.diff().abs()
    n_trades = int((pos_chg > 0).sum())
    avg_turnover = float(pos_chg.mean()) if len(pos_chg) > 0 else 0.0

    # After-cost returns
    total_cost_bps = (spread_bps + commission_bps) / 10_000
    cost_per_bar = total_cost_bps * pos_chg.reindex(strat_ret.index).fillna(0.0)
    after_cost_ret = strat_ret - cost_per_bar

    # Basic stats
    sharpe = _sharpe(arr, periods_per_year)
    sortino = _sortino(arr, periods_per_year)

    cumulative = (1 + strat_ret).cumprod().values
    mdd = _max_drawdown(cumulative)
    ann_return = float(np.mean(arr)) * periods_per_year
    calmar = ann_return / abs(mdd) if mdd != 0 else float("nan")

    total_return = float(cumulative[-1] - 1.0) if len(cumulative) > 0 else float("nan")

    # Hit rate and profit factor
    winning = arr[arr > 0]
    losing = arr[arr < 0]
    hit_rate = len(winning) / len(arr) if len(arr) > 0 else float("nan")
    avg_win = float(np.mean(winning)) if len(winning) > 0 else 0.0
    avg_loss = float(np.mean(losing)) if len(losing) > 0 else 0.0
    gross_profit = float(np.sum(winning)) if len(winning) > 0 else 0.0
    gross_loss = float(abs(np.sum(losing))) if len(losing) > 0 else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("nan")

    after_cost_sharpe = _sharpe(after_cost_ret.values, periods_per_year)

    return {
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": mdd,
        "calmar": calmar,
        "turnover": avg_turnover,
        "hit_rate": hit_rate,
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "after_cost_sharpe": after_cost_sharpe,
        "n_trades": n_trades,
        "total_return": total_return,
    }
