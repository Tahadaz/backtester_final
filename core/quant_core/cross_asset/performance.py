"""Performance statistics for cross-asset strategies.

Two views of the same P&L, because they answer different questions:

* **Period statistics** treat every bar as an observation -- expected return,
  volatility, Sharpe, drawdown. This is what risk asks about.
* **Trade statistics** collapse each held position into one round-trip -- win
  rate, average win vs average loss, expectancy per trade. This is what a
  trader asks about, and a strategy can look good on one and poor on the other.

A "trade" here is a maximal run of bars over which an instrument's position keeps
the same sign. A flip from long to short closes one trade and opens the next; a
move to flat closes without opening. Position *size* may vary inside a trade
(vol targeting rescales continuously) without splitting it.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


TRADING_DAYS = 252


@dataclass(frozen=True)
class Trade:
    instrument: str
    direction: int
    entry: pd.Timestamp
    exit: pd.Timestamp
    bars: int
    pnl: float
    avg_position: float


# A "zero" standard deviation is rarely exactly 0.0 in floating point -- a
# constant series lands around 1e-19, which sails past a `> 0` guard and turns
# a Sharpe into ~1e16. Anything at or below this is treated as degenerate.
_VOL_FLOOR = 1e-12


def _safe_div(numerator: float, denominator: float) -> float:
    if not np.isfinite(denominator) or abs(denominator) <= _VOL_FLOOR:
        return float("nan")
    return float(numerator / denominator)


def extract_trades(
    positions: pd.Series,
    returns: pd.Series,
    instrument: str = "",
    execution_lag: int = 1,
) -> list[Trade]:
    """Round-trips from a continuously-sized position series.

    P&L for bar ``t`` is ``position[t - lag] * return[t]``, matching how the
    backtest books it, so trade P&L sums exactly to the instrument's total.
    """
    position = positions.fillna(0.0)
    contribution = position.shift(execution_lag) * returns
    sign = np.sign(position)

    trades: list[Trade] = []
    current_sign = 0.0
    start_index: int | None = None
    index = position.index

    for i in range(len(position)):
        this_sign = sign.iloc[i]
        if this_sign != current_sign:
            if current_sign != 0 and start_index is not None:
                trades.append(
                    _close_trade(
                        instrument, current_sign, index, start_index, i, contribution, position, execution_lag
                    )
                )
            current_sign = this_sign
            start_index = i if this_sign != 0 else None

    if current_sign != 0 and start_index is not None:
        trades.append(
            _close_trade(
                instrument, current_sign, index, start_index, len(position), contribution, position, execution_lag
            )
        )
    return trades


def _close_trade(
    instrument: str,
    direction: float,
    index: pd.Index,
    start: int,
    stop: int,
    contribution: pd.Series,
    position: pd.Series,
    execution_lag: int,
) -> Trade:
    # P&L lands `execution_lag` bars after the position is set, so the window
    # shifts with it; otherwise the last bars of a trade are booked to the next.
    pnl_slice = contribution.iloc[start + execution_lag : stop + execution_lag]
    return Trade(
        instrument=instrument,
        direction=int(direction),
        entry=index[start],
        exit=index[min(stop, len(index) - 1)],
        bars=int(stop - start),
        pnl=float(pnl_slice.sum(skipna=True)),
        avg_position=float(position.iloc[start:stop].abs().mean()),
    )


def trade_statistics(trades: list[Trade]) -> dict[str, float]:
    """Win rate, payoff, expectancy -- the trader's view."""
    if not trades:
        return {
            "n_trades": 0,
            "win_rate": float("nan"),
            "avg_win": float("nan"),
            "avg_loss": float("nan"),
            "payoff_ratio": float("nan"),
            "profit_factor": float("nan"),
            "expectancy_per_trade": float("nan"),
            "avg_bars_held": float("nan"),
            "best_trade": float("nan"),
            "worst_trade": float("nan"),
            "n_long": 0,
            "n_short": 0,
        }

    pnl = np.array([t.pnl for t in trades], dtype=float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    gross_profit = float(wins.sum())
    gross_loss = float(-losses.sum())

    return {
        "n_trades": len(trades),
        "win_rate": float(len(wins) / len(pnl)),
        "avg_win": float(wins.mean()) if wins.size else 0.0,
        "avg_loss": float(losses.mean()) if losses.size else 0.0,
        "payoff_ratio": _safe_div(float(wins.mean()) if wins.size else 0.0, abs(float(losses.mean())) if losses.size else 0.0),
        "profit_factor": _safe_div(gross_profit, gross_loss),
        "expectancy_per_trade": float(pnl.mean()),
        "avg_bars_held": float(np.mean([t.bars for t in trades])),
        "best_trade": float(pnl.max()),
        "worst_trade": float(pnl.min()),
        "n_long": int(sum(1 for t in trades if t.direction > 0)),
        "n_short": int(sum(1 for t in trades if t.direction < 0)),
    }


def period_statistics(returns: pd.Series, periods_per_year: int = TRADING_DAYS) -> dict[str, float]:
    """Expected return, risk, drawdown -- the risk view."""
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty:
        return {"n_periods": 0, "expected_return_annual": float("nan"), "sharpe": float("nan")}

    mean = float(clean.mean())
    std = float(clean.std(ddof=1))
    equity = (1.0 + clean).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    downside = clean[clean < 0]
    years = len(clean) / periods_per_year

    longest = current = 0
    for under_water in (drawdown < 0).to_numpy():
        current = current + 1 if under_water else 0
        longest = max(longest, current)

    monthly = clean.resample("ME").apply(lambda s: (1 + s).prod() - 1) if len(clean) > periods_per_year // 12 else pd.Series(dtype=float)
    max_dd = float(drawdown.min())
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 and equity.iloc[-1] > 0 else float("nan")

    return {
        "n_periods": int(len(clean)),
        "years": float(years),
        "expected_return_annual": float(mean * periods_per_year),
        "cagr": cagr,
        "volatility_annual": float(std * np.sqrt(periods_per_year)),
        "sharpe": _safe_div(mean, std) * np.sqrt(periods_per_year),
        "sortino": _safe_div(mean, float(downside.std(ddof=1)) if len(downside) > 1 else float("nan"))
        * np.sqrt(periods_per_year),
        "calmar": _safe_div(cagr, abs(max_dd)),
        "max_drawdown": max_dd,
        "longest_drawdown_periods": float(longest),
        "hit_rate_periods": float((clean > 0).mean()),
        "hit_rate_months": float((monthly > 0).mean()) if not monthly.empty else float("nan"),
        "best_month": float(monthly.max()) if not monthly.empty else float("nan"),
        "worst_month": float(monthly.min()) if not monthly.empty else float("nan"),
        "skew": float(clean.skew()),
        "excess_kurtosis": float(clean.kurtosis()),
        "t_stat": _safe_div(mean, std) * np.sqrt(len(clean)),
        "var_95": float(clean.quantile(0.05)),
        "cvar_95": float(clean[clean <= clean.quantile(0.05)].mean()) if (clean <= clean.quantile(0.05)).any() else float("nan"),
    }


def performance_summary(
    returns: pd.Series,
    positions: pd.DataFrame | None = None,
    instrument_returns: pd.DataFrame | None = None,
    execution_lag: int = 1,
    periods_per_year: int = TRADING_DAYS,
) -> dict[str, float]:
    """Period statistics, plus trade statistics when positions are supplied."""
    summary = period_statistics(returns, periods_per_year=periods_per_year)
    if positions is None or instrument_returns is None:
        return summary

    trades: list[Trade] = []
    for instrument in positions.columns:
        if instrument not in instrument_returns.columns:
            continue
        trades.extend(
            extract_trades(
                positions[instrument], instrument_returns[instrument], instrument, execution_lag=execution_lag
            )
        )
    summary.update(trade_statistics(trades))
    return summary


def per_instrument_summary(
    positions: pd.DataFrame,
    instrument_returns: pd.DataFrame,
    execution_lag: int = 1,
    periods_per_year: int = TRADING_DAYS,
) -> pd.DataFrame:
    """One row of statistics per instrument, sorted by contribution."""
    rows = []
    for instrument in positions.columns:
        if instrument not in instrument_returns.columns:
            continue
        contribution = positions[instrument].shift(execution_lag) * instrument_returns[instrument]
        trades = extract_trades(
            positions[instrument], instrument_returns[instrument], instrument, execution_lag=execution_lag
        )
        row = {"instrument": instrument, "total_pnl": float(contribution.sum(skipna=True))}
        row.update(period_statistics(contribution, periods_per_year=periods_per_year))
        row.update(trade_statistics(trades))
        rows.append(row)
    frame = pd.DataFrame(rows)
    return frame.sort_values("total_pnl", ascending=False).reset_index(drop=True) if not frame.empty else frame
