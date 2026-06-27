"""Capital-recycling portfolio re-simulation for a given exit policy.

Trades are sorted by open_date and compounded sequentially.
Kelly fraction is recalibrated from expanding window of bracketed returns per policy,
keeping TP/SL, Kelly, and the portfolio sim coupled as one system.
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd

from .paths import TradePath
from .policies import ExitResult
from .calibrate import walk_forward_kelly, compute_half_kelly

_INITIAL_KELLY = 0.10
_MIN_KELLY_TRADES = 3


def _portfolio_metrics(
    equity: list[float],
    trade_returns: list[float],
    periods_per_year: float = 252.0,
) -> dict[str, float]:
    if len(equity) < 2 or not trade_returns:
        return {
            "total_return": 0.0,
            "cagr": 0.0,
            "sharpe": 0.0,
            "max_drawdown": 0.0,
            "win_rate": 0.0,
            "expectancy": 0.0,
            "payoff_ratio": 0.0,
            "n_trades": 0,
        }

    arr = np.asarray(trade_returns, dtype=np.float64)
    eq = np.asarray(equity, dtype=np.float64)

    total_return = float(eq[-1] - 1.0)
    n_trades = len(arr)

    # CAGR: approximate via trade count (not calendar days — WFO periods vary)
    # Use eq[-1]^(periods_per_year/n_trades) - 1 only when n_trades >= 2
    try:
        cagr = float(eq[-1] ** (periods_per_year / n_trades) - 1.0) if n_trades >= 2 else total_return
    except (ValueError, ZeroDivisionError):
        cagr = total_return

    # Sharpe on bracketed trade returns (annualised)
    sigma = float(np.std(arr, ddof=1)) if len(arr) >= 2 else 0.0
    sharpe = float(np.mean(arr) / sigma * np.sqrt(periods_per_year)) if sigma > 0.0 else 0.0

    # Max drawdown
    peak = np.maximum.accumulate(eq)
    peak_safe = np.where(peak <= 0.0, 1.0, peak)
    max_dd = float(np.max(1.0 - eq / peak_safe))

    wins = arr[arr > 0.0]
    losses = arr[arr < 0.0]
    win_rate = float(len(wins) / n_trades)
    expectancy = float(np.mean(arr))
    payoff_ratio = float(wins.mean() / abs(losses.mean())) if len(wins) and len(losses) else 0.0

    return {
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "win_rate": win_rate,
        "expectancy": expectancy,
        "payoff_ratio": payoff_ratio,
        "n_trades": n_trades,
    }


def run_policy_portfolio(
    paths: list[TradePath],
    simulate_fn: Callable[[TradePath], ExitResult],
    *,
    initial_kelly: float = _INITIAL_KELLY,
    min_kelly_trades: int = _MIN_KELLY_TRADES,
) -> dict[str, Any]:
    """Run capital-recycling portfolio sim for one exit policy.

    Args:
        paths:        Trade paths sorted by open_date (the function re-sorts).
        simulate_fn:  Policy simulator: (TradePath) → ExitResult.
        initial_kelly: Kelly fraction before enough trades to estimate.
        min_kelly_trades: Minimum trades before adaptive Kelly kicks in.

    Returns:
        {
          "equity": list[float],        # normalized equity per trade (starts at 1.0)
          "metrics": dict[str, float],  # total_return, cagr, sharpe, max_dd, win_rate, …
          "trades": list[dict],         # per-trade record with exit details
        }
    """
    sorted_paths = sorted(paths, key=lambda p: p.open_date)

    equity = 1.0
    equity_curve: list[float] = [1.0]
    past_returns: list[float] = []
    trade_records: list[dict[str, Any]] = []

    for path in sorted_paths:
        result = simulate_fn(path)

        # Kelly fraction from past bracketed returns
        if len(past_returns) >= min_kelly_trades:
            kelly_f = compute_half_kelly(past_returns)
        else:
            kelly_f = initial_kelly

        # Compound equity
        equity *= 1.0 + kelly_f * result.effective_return
        equity_curve.append(equity)
        past_returns.append(result.effective_return)

        trade_records.append({
            "symbol": path.symbol,
            "open_date": path.open_date.date().isoformat(),
            "close_date": path.close_date.date().isoformat(),
            "actual_exit_date": result.exit_date.date().isoformat(),
            "direction": path.direction,
            "open_price": path.open_price,
            "exit_price": result.exit_price,
            "exit_reason": result.exit_reason,
            "effective_return": result.effective_return,
            "kelly_fraction": kelly_f,
            "mae": path.mae,
            "mfe": path.mfe,
            "equity_after": equity,
        })

    metrics = _portfolio_metrics(equity_curve, past_returns)
    return {
        "equity": equity_curve,
        "metrics": metrics,
        "trades": trade_records,
    }


def exit_reason_histogram(trade_records: list[dict[str, Any]]) -> dict[str, int]:
    """Count exit reasons across a trade list."""
    counts: dict[str, int] = {}
    for t in trade_records:
        reason = str(t.get("exit_reason") or "unknown")
        counts[reason] = counts.get(reason, 0) + 1
    return counts
