"""Portfolio-level performance statistics and shared cross-sectional helpers.

Metrics: Sharpe, Sortino, MaxDD, Calmar, turnover, hit rate, profit factor.
Shared helpers: assign_quintiles, forward_return, rebalance_dates, quintile_return_summary,
equity_curve_with_stats — used by both signal_backtest.py and cross_sectional.py.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional

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


# ── Shared cross-sectional helpers ────────────────────────────────────────────
# Used by both fundamentals/signal_backtest.py and research/cross_sectional.py.
# Logic is identical to the private functions extracted from signal_backtest.py;
# both modules import from here instead of duplicating.

def _finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _mean_finite(values: Any) -> float:
    clean = [float(v) for v in values if _finite(v)]
    return float(np.mean(clean)) if clean else 0.0


def assign_quintiles(signals: Mapping[str, float], *, n: int = 5) -> dict[str, int]:
    """Assign ranks 1 (lowest) … n (highest) to a {symbol: score} mapping.

    Ties broken alphabetically so output is deterministic.
    """
    clean = [(sym.upper(), float(v)) for sym, v in signals.items() if _finite(v)]
    if not clean:
        return {}
    ordered = sorted(clean, key=lambda item: (item[1], item[0]))
    count = len(ordered)
    out: dict[str, int] = {}
    for index, (sym, _v) in enumerate(ordered):
        bucket = int(math.floor(index * n / count)) + 1
        out[sym] = max(1, min(n, bucket))
    return out


def _tz_naive(ts: pd.Timestamp) -> pd.Timestamp:
    """Return a tz-naive Timestamp, converting from UTC if necessary."""
    return ts.tz_localize(None) if ts.tzinfo is None else ts.tz_convert("UTC").tz_localize(None)


def _normalize_index(series: pd.Series) -> pd.Series:
    """Return the series with a tz-naive DatetimeIndex (strip UTC if present)."""
    if getattr(series.index, "tz", None) is not None:
        return series.tz_localize(None) if series.index.tz is None else series.tz_convert("UTC").tz_localize(None)
    return series


def price_at_or_before(series: pd.Series, date: pd.Timestamp) -> float | None:
    s = _normalize_index(series)
    d = _tz_naive(date)
    eligible = s[s.index <= d]
    if eligible.empty:
        return None
    value = float(eligible.iloc[-1])
    return value if _finite(value) else None


def forward_return(series: pd.Series, entry: pd.Timestamp, exit_: pd.Timestamp) -> float | None:
    """Close-to-close return from entry to exit_ using the last available price on each date."""
    p_entry = price_at_or_before(series, entry)
    p_exit = price_at_or_before(series, exit_)
    if p_entry is None or p_exit is None or p_entry <= 0:
        return None
    return float(p_exit / p_entry - 1.0)


def forward_return_horizon(series: pd.Series, entry: pd.Timestamp, horizon: int) -> float | None:
    """Return over the next `horizon` trading days strictly after `entry`."""
    s = _normalize_index(series)
    e = _tz_naive(entry)
    future = s.index[s.index > e]
    if len(future) < horizon:
        return None
    return forward_return(s, e, pd.Timestamp(future[horizon - 1]))


def rebalance_dates(
    price_history: Mapping[str, pd.Series],
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> list[pd.Timestamp]:
    """Last available trading date per calendar month in [start, end]."""
    # Normalise start/end to tz-naive so they can compare against any series index
    start_n = _tz_naive(start)
    end_n = _tz_naive(end)
    all_dates = sorted({
        _tz_naive(pd.Timestamp(idx))
        for series in price_history.values()
        for idx in series.index
        if start_n <= _tz_naive(pd.Timestamp(idx)) <= end_n
    })
    if not all_dates:
        return []
    by_month: dict[tuple[int, int], pd.Timestamp] = {}
    for d in all_dates:
        by_month[(d.year, d.month)] = d
    return [by_month[k] for k in sorted(by_month)]


def quintile_return_summary(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate forward returns by quintile bucket.

    Each record must have 'quintile' (int) and 'forward_return' (float) keys.
    """
    out: list[dict[str, Any]] = []
    for q in sorted({int(row["quintile"]) for row in records}):
        rets = [float(row["forward_return"]) for row in records if int(row["quintile"]) == q]
        out.append({
            "quintile": q,
            "mean_forward_return": _mean_finite(rets),
            "median_forward_return": float(np.median(rets)) if rets else None,
            "hit_rate": float(np.mean([v > 0 for v in rets])) if rets else None,
            "count": len(rets),
        })
    return out


def equity_curve_with_stats(
    rows: list[dict[str, Any]],
    *,
    periods_per_year: int = 12,
) -> list[dict[str, Any]]:
    """Attach drawdown and annualised Sharpe to each equity-curve row.

    Each row must have 'net_return' (float) and 'equity' (float) keys.
    Sharpe uses monthly periods by default (periods_per_year=12).
    """
    if not rows:
        return []
    returns = np.array([float(row["net_return"]) for row in rows], dtype=float)
    equity = np.array([float(row["equity"]) for row in rows], dtype=float)
    peak = np.maximum.accumulate(equity)
    drawdown = equity / np.where(peak <= 0.0, 1.0, peak) - 1.0
    sr = _sharpe(returns, periods_per_year)
    out: list[dict[str, Any]] = []
    for row, dd in zip(rows, drawdown):
        out.append({**row, "drawdown": float(dd), "sharpe_to_date": sr})
    return out
