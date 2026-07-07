from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from quant_core.fundamentals.cross_section.characteristic_study import (
    CharacteristicStudyConfig,
    _past_return,
    add_characteristics,
)
from quant_core.fundamentals.domain import AnnualMetricRow, FundamentalSnapshot


def _row(symbol: str = "AAA") -> pd.DataFrame:
    metrics = {
        "MarketCap_Calc": 100.0,
        "Total_Equity": 50.0,
        "NetIncome": 10.0,
        "Operating_Cash_Flow": 12.0,
        "Dividendes": 4.0,
        "Revenue": 200.0,
        "EBITDA": 20.0,
        "EnterpriseValue": 80.0,
        "Total_Assets": 125.0,
        "Gross_Profit": 40.0,
        "Total_Debt": 25.0,
        "Operating_Income": 15.0,
    }
    history = [
        AnnualMetricRow(symbol, symbol, 2020, "Total_Assets", 100.0),
        AnnualMetricRow(symbol, symbol, 2021, "Total_Assets", 125.0),
        AnnualMetricRow(symbol, symbol, 2021, "NetIncome", 10.0),
        AnnualMetricRow(symbol, symbol, 2021, "Operating_Cash_Flow", 12.0),
    ]
    return pd.DataFrame(
        [
            {
                "symbol": symbol,
                "as_of_date": dt.date(2022, 12, 31),
                "metrics": metrics,
                "history": history,
                "snapshot": FundamentalSnapshot(symbol, symbol, 2021, metrics=metrics),
                "close": 10.0,
                "sector": "Industrials",
                "is_financial": False,
                "fwd_return_6m": 0.1,
            }
        ]
    )


def _prices() -> dict[str, pd.DataFrame]:
    idx = pd.date_range("2021-01-01", "2022-12-31", freq="B")
    return {"AAA": pd.DataFrame({"Close": range(1, len(idx) + 1), "Volume": 1000.0}, index=idx)}


def test_value_yield_raw_formulas_are_preserved() -> None:
    out = add_characteristics(_row(), _prices(), CharacteristicStudyConfig(beta_min_obs=10))
    assert out.loc[0, "earnings_yield_raw"] == pytest.approx(0.10)
    assert out.loc[0, "book_to_market_raw"] == pytest.approx(0.50)
    assert out.loc[0, "dividend_yield_raw"] == pytest.approx(0.04)
    assert out.loc[0, "cashflow_price_raw"] == pytest.approx(0.12)
    assert out.loc[0, "sales_price_raw"] == pytest.approx(2.0)
    assert out.loc[0, "ebitda_ev_yield_raw"] == pytest.approx(0.25)


def test_profitability_investment_and_accrual_formulas() -> None:
    out = add_characteristics(_row(), _prices(), CharacteristicStudyConfig(beta_min_obs=10))
    assert out.loc[0, "operating_profitability_raw"] == pytest.approx(15.0 / 50.0)
    assert out.loc[0, "gross_profitability_raw"] == pytest.approx(40.0 / 125.0)
    assert out.loc[0, "roe_raw"] == pytest.approx(10.0 / 50.0)
    assert out.loc[0, "roa_raw"] == pytest.approx(10.0 / 125.0)
    assert out.loc[0, "accruals_raw"] == pytest.approx(-((10.0 - 12.0) / 125.0))
    assert out.loc[0, "investment_raw"] == pytest.approx(0.25)
    assert out.loc[0, "leverage_raw"] == pytest.approx(-(25.0 / 125.0))


def test_negative_book_equity_excludes_book_to_market_not_signs_it() -> None:
    """Canonical B/M policy (bm_canonical_definition.md, 2026-07-06): negative book equity
    must be excluded (None), matching methodology_bakeoff.py and Fama-French HML convention --
    not turned into a negative ratio, which would misleadingly rank a distressed,
    negative-equity firm as "cheap"."""
    frame = _row()
    frame.at[0, "metrics"] = {**frame.at[0, "metrics"], "Total_Equity": -50.0}
    frame.at[0, "snapshot"] = FundamentalSnapshot("AAA", "AAA", 2021, metrics=frame.at[0, "metrics"])
    out = add_characteristics(frame, _prices(), CharacteristicStudyConfig(beta_min_obs=10))
    assert out.loc[0, "book_to_market_raw"] is None


def test_cashflow_price_excluded_for_financial_sector_issuers() -> None:
    """Canonical CF/P policy (cfp_canonical_definition.md, 2026-07-06): CFO/MarketCap is not
    economically meaningful for banks/insurers, so it must be excluded (None) for is_financial
    rows rather than computed uniformly."""
    frame = _row()
    frame.at[0, "is_financial"] = True
    out = add_characteristics(frame, _prices(), CharacteristicStudyConfig(beta_min_obs=10))
    assert out.loc[0, "cashflow_price_raw"] is None


def test_past_return_uses_skip_window_without_future_prices() -> None:
    idx = pd.date_range("2022-01-03", periods=300, freq="B")
    prices = pd.Series(range(100, 400), index=idx, dtype=float)
    as_of = idx[-1].date()
    ret = _past_return(prices, as_of, formation_days=252, skip_days=21)
    expected = prices.iloc[-22] / prices.iloc[-274] - 1.0
    assert ret == pytest.approx(expected)
