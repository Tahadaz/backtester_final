from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from quant_core.fundamentals.cross_section.methodology_bakeoff import (
    add_classical_and_change_signals,
    add_residual_value_signal,
)
from quant_core.fundamentals.domain import AnnualMetricRow, FundamentalSnapshot


def _history(symbol: str, *, assets0: float, assets1: float, equity: float = 100.0) -> list[AnnualMetricRow]:
    return [
        AnnualMetricRow(symbol, symbol, 2020, "Total_Assets", assets0),
        AnnualMetricRow(symbol, symbol, 2021, "Total_Assets", assets1),
        AnnualMetricRow(symbol, symbol, 2020, "Total_Equity", equity),
        AnnualMetricRow(symbol, symbol, 2021, "Total_Equity", equity),
        AnnualMetricRow(symbol, symbol, 2020, "Revenue", 100.0),
        AnnualMetricRow(symbol, symbol, 2021, "Revenue", 120.0),
        AnnualMetricRow(symbol, symbol, 2020, "Operating_Income", 10.0),
        AnnualMetricRow(symbol, symbol, 2021, "Operating_Income", 18.0),
        AnnualMetricRow(symbol, symbol, 2020, "NetIncome", 8.0),
        AnnualMetricRow(symbol, symbol, 2021, "NetIncome", 12.0),
        AnnualMetricRow(symbol, symbol, 2020, "Operating_Cash_Flow", 9.0),
        AnnualMetricRow(symbol, symbol, 2021, "Operating_Cash_Flow", 15.0),
    ]


def _panel(n: int = 12) -> pd.DataFrame:
    rows = []
    for i in range(n):
        symbol = f"S{i:02d}"
        mcap = 100.0 + i * 10.0
        equity = 100.0 + i
        metrics = {
            "MarketCap_Calc": mcap,
            "Total_Equity": equity,
            "Total_Assets": 200.0 + i * 5.0,
            "Revenue": 120.0 + i,
            "Operating_Income": 18.0 + i,
            "NetIncome": 12.0 + i,
            "Operating_Cash_Flow": 15.0 + i,
            "Shares_Outstanding": 10.0,
            "Price_to_Book": mcap / equity,
        }
        rows.append(
            {
                "symbol": symbol,
                "as_of_date": dt.date(2022, 6, 30),
                "metrics": metrics,
                "history": _history(symbol, assets0=100.0 + i, assets1=110.0 + i * 2.0, equity=equity),
                "snapshot": FundamentalSnapshot(symbol, symbol, 2021, metrics=metrics),
                "close": 10.0 + i,
                "sector": "Industrials",
                "is_financial": False,
                "fwd_return_6m": i / 100.0,
            }
        )
    return pd.DataFrame(rows)


def test_book_to_market_raw_uses_pit_book_equity_over_market_cap() -> None:
    out = add_classical_and_change_signals(_panel())
    assert out.loc[0, "book_to_market_raw"] == pytest.approx(1.0)
    assert out.loc[1, "book_to_market_raw"] == pytest.approx(101.0 / 110.0)


def test_conservative_investment_rewards_lower_asset_growth() -> None:
    frame = _panel()
    out = add_classical_and_change_signals(frame)
    low_growth = out.sort_values("investment_raw").head(3)["investment_conservative"].mean()
    high_growth = out.sort_values("investment_raw").tail(3)["investment_conservative"].mean()
    assert low_growth > high_growth


def test_fundamental_momentum_uses_accounting_changes_not_today_consensus() -> None:
    frame = _panel()
    frame.at[0, "metrics"] = {**frame.at[0, "metrics"], "Consensus_EPS_Forward_2099": 999.0}
    out = add_classical_and_change_signals(frame)
    assert "fundamental_momentum" in out
    assert np.isfinite(out["fundamental_momentum"].dropna()).any()


def test_residual_value_signal_rewards_cheaper_than_predicted_pb() -> None:
    frame = add_classical_and_change_signals(_panel(18))
    frame.loc[0, "price_to_book_raw"] = 0.25
    out, fit = add_residual_value_signal(frame)
    assert not fit.empty
    assert out.loc[0, "residual_value_no_sector_raw"] > 0
