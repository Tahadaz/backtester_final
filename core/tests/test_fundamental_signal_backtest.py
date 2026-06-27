from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from core.quant_core.fundamentals.signal_backtest import (
    PITSignalSnapshot,
    SignalBacktestConfig,
    assign_quintiles,
    latest_snapshot_as_of,
    run_signal_backtest,
)


def _prices(symbol_index: int, monthly_returns: list[float]) -> pd.Series:
    dates = pd.date_range("2024-01-31", periods=len(monthly_returns) + 1, freq="ME")
    price = 100.0 + symbol_index
    values = [price]
    for ret in monthly_returns:
        price *= 1.0 + ret
        values.append(price)
    return pd.Series(values, index=dates)


def test_future_dated_snapshot_is_excluded_by_lookahead_guard() -> None:
    snapshots = [
        PITSignalSnapshot(symbol="AAA", as_of_date=dt.date(2024, 1, 15), upside_pct=0.05),
        PITSignalSnapshot(symbol="AAA", as_of_date=dt.date(2024, 3, 15), upside_pct=0.50),
    ]

    selected = latest_snapshot_as_of(snapshots, dt.date(2024, 2, 29))

    assert selected is not None
    assert selected.upside_pct == 0.05


def test_quintile_assignment_is_deterministic() -> None:
    assigned = assign_quintiles({"EEE": 0.5, "AAA": 0.1, "DDD": 0.4, "CCC": 0.3, "BBB": 0.2}, n=5)

    assert assigned == {"AAA": 1, "BBB": 2, "CCC": 3, "DDD": 4, "EEE": 5}


def test_rank_ic_positive_for_constructed_monotone_signal() -> None:
    symbols = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    price_history = {symbol: _prices(index, [0.01 * (index + 1), 0.01 * (index + 1)]) for index, symbol in enumerate(symbols)}
    snapshots = {
        symbol: [PITSignalSnapshot(symbol=symbol, as_of_date=dt.date(2024, 1, 1), upside_pct=0.10 * (index + 1))]
        for index, symbol in enumerate(symbols)
    }

    result = run_signal_backtest(
        price_history=price_history,
        snapshots_by_symbol=snapshots,
        config=SignalBacktestConfig(start=dt.date(2024, 1, 1), end=dt.date(2024, 3, 31), transaction_cost_bps=0.0),
        run_id="test",
    )

    assert result.ic["rank_ic"] == pytest.approx(1.0)
    assert result.quintile_returns[-1]["quintile"] == 5
    assert result.quintile_returns[-1]["mean_forward_return"] > result.quintile_returns[0]["mean_forward_return"]


def test_transaction_costs_reduce_net_return() -> None:
    symbols = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    price_history = {symbol: _prices(index, [0.02, 0.02]) for index, symbol in enumerate(symbols)}
    snapshots = {
        symbol: [PITSignalSnapshot(symbol=symbol, as_of_date=dt.date(2024, 1, 1), upside_pct=0.10 * (index + 1))]
        for index, symbol in enumerate(symbols)
    }

    gross = run_signal_backtest(
        price_history=price_history,
        snapshots_by_symbol=snapshots,
        config=SignalBacktestConfig(start=dt.date(2024, 1, 1), end=dt.date(2024, 3, 31), transaction_cost_bps=0.0),
        run_id="gross",
    )
    net = run_signal_backtest(
        price_history=price_history,
        snapshots_by_symbol=snapshots,
        config=SignalBacktestConfig(start=dt.date(2024, 1, 1), end=dt.date(2024, 3, 31), transaction_cost_bps=50.0),
        run_id="net",
    )

    assert net.equity_curve[-1]["equity"] < gross.equity_curve[-1]["equity"]


def test_timezone_aware_price_history_is_normalized() -> None:
    symbols = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    price_history = {}
    for index, symbol in enumerate(symbols):
        series = _prices(index, [0.01 * (index + 1), 0.01 * (index + 1)])
        series.index = series.index.tz_localize("UTC")
        price_history[symbol] = series
    snapshots = {
        symbol: [PITSignalSnapshot(symbol=symbol, as_of_date=dt.date(2024, 1, 1), upside_pct=0.10 * (index + 1))]
        for index, symbol in enumerate(symbols)
    }

    result = run_signal_backtest(
        price_history=price_history,
        snapshots_by_symbol=snapshots,
        config=SignalBacktestConfig(start=dt.date(2024, 1, 1), end=dt.date(2024, 3, 31), transaction_cost_bps=0.0),
        run_id="tz-aware",
    )

    assert result.warnings == []
    assert result.ic["rank_ic"] == pytest.approx(1.0)
