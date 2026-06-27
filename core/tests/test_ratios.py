"""Tests for core/quant_core/fundamentals/ratios.py.

Every expected value is expressed as the formula, not a pre-computed decimal,
so the formula is the source of truth.  All fixture values are exact integers;
floating-point arithmetic is deterministic at this scale.
"""
from __future__ import annotations

import copy

import pytest

from core.quant_core.fundamentals.ratios import compute_ratios


# ---------------------------------------------------------------------------
# Industrial fixture — two years so growth and avg-equity are non-trivial
# ---------------------------------------------------------------------------

_IND_2023: dict[str, float] = {
    "Revenue": 4_000_000_000.0,
    "EBIT": 650_000_000.0,
    "NetIncome": 320_000_000.0,
    "Total_Assets": 7_500_000_000.0,
    "Total_Equity": 2_300_000_000.0,
    "Total_Debt": 1_000_000_000.0,
    "Net_Debt": 600_000_000.0,
    "Cash": 400_000_000.0,
    "Current_Assets": 1_500_000_000.0,
    "Current_Liabilities": 900_000_000.0,
    "Operating_Cash_Flow": 480_000_000.0,
    "Free_Cash_Flow": 260_000_000.0,
    "EBITDA": 850_000_000.0,
    "Interest_Expense": 80_000_000.0,
    "CAF": 400_000_000.0,
    "Dividendes": 160_000_000.0,
}

_IND_2024: dict[str, float] = {
    "Revenue": 4_200_000_000.0,
    "EBIT": 700_000_000.0,
    "NetIncome": 350_000_000.0,
    "Total_Assets": 8_000_000_000.0,
    "Total_Equity": 2_500_000_000.0,
    "Total_Debt": 1_000_000_000.0,
    "Net_Debt": 600_000_000.0,
    "Cash": 400_000_000.0,
    "Current_Assets": 1_500_000_000.0,
    "Current_Liabilities": 900_000_000.0,
    "Operating_Cash_Flow": 500_000_000.0,
    "Free_Cash_Flow": 280_000_000.0,
    "EBITDA": 900_000_000.0,
    "Interest_Expense": 80_000_000.0,
    "CAF": 420_000_000.0,
    "Dividendes": 175_000_000.0,
}

_IND_RAW = {2023: _IND_2023, 2024: _IND_2024}
_IND_PRICE = 420.0
_IND_SHARES = 10_000_000.0


# --- Industrial: non-price ratios for latest year ---

def test_industrial_margins_2024() -> None:
    r = compute_ratios(_IND_RAW, archetype="industrial", price=_IND_PRICE, shares=_IND_SHARES)[2024]
    assert r["Operating_Margin"] == pytest.approx(700_000_000 / 4_200_000_000)
    assert r["Net_Margin"] == pytest.approx(350_000_000 / 4_200_000_000)
    assert r["FCF_Margin"] == pytest.approx(280_000_000 / 4_200_000_000)
    assert r["Operating_CF_Margin"] == pytest.approx(500_000_000 / 4_200_000_000)
    assert r["CAF_Margin"] == pytest.approx(420_000_000 / 4_200_000_000)


def test_industrial_returns_2024() -> None:
    r = compute_ratios(_IND_RAW, archetype="industrial", price=_IND_PRICE, shares=_IND_SHARES)[2024]
    avg_eq = (2_300_000_000 + 2_500_000_000) / 2
    assert r["ROA"] == pytest.approx(350_000_000 / 8_000_000_000)
    assert r["ROE"] == pytest.approx(350_000_000 / avg_eq)


def test_industrial_leverage_health_2024() -> None:
    r = compute_ratios(_IND_RAW, archetype="industrial", price=_IND_PRICE, shares=_IND_SHARES)[2024]
    assert r["Debt_to_Equity"] == pytest.approx(1_000_000_000 / 2_500_000_000)
    assert r["NetDebt_to_Equity"] == pytest.approx(600_000_000 / 2_500_000_000)
    assert r["NetDebt_to_EBITDA"] == pytest.approx(600_000_000 / 900_000_000)
    assert r["Equity_Multiplier"] == pytest.approx(8_000_000_000 / 2_500_000_000)
    assert r["Current_Ratio"] == pytest.approx(1_500_000_000 / 900_000_000)
    assert r["Cash_Ratio"] == pytest.approx(400_000_000 / 900_000_000)
    assert r["Interest_Coverage"] == pytest.approx(700_000_000 / 80_000_000)


def test_industrial_growth_2024() -> None:
    r = compute_ratios(_IND_RAW, archetype="industrial", price=_IND_PRICE, shares=_IND_SHARES)[2024]
    assert r["Revenue_Growth"] == pytest.approx((4_200_000_000 - 4_000_000_000) / 4_000_000_000)
    assert r["EBIT_Growth"] == pytest.approx((700_000_000 - 650_000_000) / 650_000_000)
    assert r["NetIncome_Growth"] == pytest.approx((350_000_000 - 320_000_000) / 320_000_000)


# --- Industrial: price-derived ratios ---

def test_industrial_price_ratios_2024() -> None:
    r = compute_ratios(_IND_RAW, archetype="industrial", price=_IND_PRICE, shares=_IND_SHARES)[2024]
    market_cap = _IND_PRICE * _IND_SHARES  # 4_200_000_000
    net_debt = 600_000_000.0
    ev = market_cap + net_debt             # 4_800_000_000
    assert r["Market_Cap_Calc"] == pytest.approx(market_cap)
    assert r["EV_Calc"] == pytest.approx(ev)
    assert r["PER"] == pytest.approx(market_cap / 350_000_000)
    assert r["Price_to_Book"] == pytest.approx(market_cap / 2_500_000_000)
    assert r["Price_to_Sales"] == pytest.approx(market_cap / 4_200_000_000)
    assert r["EV_to_EBITDA"] == pytest.approx(ev / 900_000_000)
    assert r["FCF_Yield"] == pytest.approx(280_000_000 / market_cap)
    assert r["Dividend_Yield"] == pytest.approx(175_000_000 / market_cap)


def test_industrial_price_ratios_absent_when_price_none() -> None:
    r = compute_ratios(_IND_RAW, archetype="industrial", price=None, shares=_IND_SHARES)[2024]
    for key in ("PER", "Price_to_Book", "Price_to_Sales", "EV_to_EBITDA",
                "FCF_Yield", "Dividend_Yield", "Market_Cap_Calc", "EV_Calc"):
        assert key not in r, f"{key} must be absent when price is None"


def test_industrial_price_ratios_absent_when_shares_none() -> None:
    r = compute_ratios(_IND_RAW, archetype="industrial", price=_IND_PRICE, shares=None)[2024]
    for key in ("PER", "Price_to_Book", "Market_Cap_Calc", "EV_Calc"):
        assert key not in r, f"{key} must be absent when shares is None"


def test_industrial_price_ratios_only_in_latest_year() -> None:
    result = compute_ratios(_IND_RAW, archetype="industrial", price=_IND_PRICE, shares=_IND_SHARES)
    r2023 = result[2023]
    for key in ("PER", "Price_to_Book", "Price_to_Sales", "EV_to_EBITDA",
                "FCF_Yield", "Dividend_Yield", "Market_Cap_Calc", "EV_Calc"):
        assert key not in r2023, f"{key} must not appear in non-latest year 2023"


# --- Industrial: growth absent for earliest year (no prior year in dict) ---

def test_industrial_growth_absent_for_earliest_year() -> None:
    result = compute_ratios(_IND_RAW, archetype="industrial", price=_IND_PRICE, shares=_IND_SHARES)
    r2023 = result[2023]
    for key in ("Revenue_Growth", "EBIT_Growth", "NetIncome_Growth"):
        assert key not in r2023, f"{key} must be absent for 2023 (no 2022 data)"


# --- Industrial: single-year ROE falls back to spot equity ---

def test_industrial_roe_uses_spot_equity_when_no_prior_year() -> None:
    result = compute_ratios({2024: _IND_2024}, archetype="industrial", price=None, shares=None)
    r = result[2024]
    # no 2023 in dict → avg_equity = Total_Equity[2024] alone
    assert r["ROE"] == pytest.approx(350_000_000 / 2_500_000_000)


# --- "unknown" archetype routes to industrial path ---

def test_unknown_archetype_routes_to_industrial() -> None:
    # StockAnalysis English industrial → infer_statement_archetype returns "unknown".
    # compute_ratios must treat that as industrial, not suppress ratios.
    result = compute_ratios({2024: _IND_2024}, archetype="unknown", price=None, shares=None)
    r = result[2024]
    assert "Operating_Margin" in r
    assert "Current_Ratio" in r
    assert "Interest_Coverage" in r


# --- Purity: input dicts must not be modified ---

def test_industrial_purity() -> None:
    raw: dict[int, dict[str, float]] = {2023: dict(_IND_2023), 2024: dict(_IND_2024)}
    snapshot = copy.deepcopy(raw)
    compute_ratios(raw, archetype="industrial", price=_IND_PRICE, shares=_IND_SHARES)
    assert raw == snapshot, "compute_ratios must not mutate its input"


# --- Empty input ---

def test_empty_raw_returns_empty() -> None:
    assert compute_ratios({}, archetype="industrial", price=420.0, shares=10_000_000.0) == {}


# ===========================================================================
# Bank fixture
# ===========================================================================

_BANK_2023: dict[str, float] = {
    "NetIncome": 1_300_000_000.0,
    "Total_Assets": 160_000_000_000.0,
    "Total_Equity": 13_500_000_000.0,
    "Net_Interest_Income": 4_200_000_000.0,
    "Operating_Expenses": 1_900_000_000.0,
    "Revenue": 5_500_000_000.0,
    "Loans_Net": 90_000_000_000.0,
    "Customer_Deposits": 110_000_000_000.0,
    "Provision_for_Loan_Losses": 500_000_000.0,
    "Dividendes": 650_000_000.0,
}

_BANK_2024: dict[str, float] = {
    "NetIncome": 1_500_000_000.0,
    "Total_Assets": 180_000_000_000.0,
    "Total_Equity": 15_000_000_000.0,
    "Net_Interest_Income": 4_800_000_000.0,
    "Operating_Expenses": 2_100_000_000.0,
    "Revenue": 6_000_000_000.0,
    "Loans_Net": 100_000_000_000.0,
    "Customer_Deposits": 120_000_000_000.0,
    "Provision_for_Loan_Losses": 600_000_000.0,
    "Dividendes": 750_000_000.0,
}

_BANK_RAW = {2023: _BANK_2023, 2024: _BANK_2024}
_BANK_PRICE = 5_200.0
_BANK_SHARES = 15_000_000.0


def test_bank_core_ratios_2024() -> None:
    r = compute_ratios(_BANK_RAW, archetype="bank", price=_BANK_PRICE, shares=_BANK_SHARES)[2024]
    avg_eq = (13_500_000_000 + 15_000_000_000) / 2   # 14_250_000_000
    avg_as = (160_000_000_000 + 180_000_000_000) / 2  # 170_000_000_000

    assert r["ROE"] == pytest.approx(1_500_000_000 / avg_eq)
    assert r["ROA"] == pytest.approx(1_500_000_000 / 180_000_000_000)
    assert r["Net_Margin"] == pytest.approx(1_500_000_000 / 6_000_000_000)
    assert r["Equity_Multiplier"] == pytest.approx(180_000_000_000 / 15_000_000_000)
    assert r["Net_Interest_Margin"] == pytest.approx(4_800_000_000 / avg_as)
    assert r["Cost_to_Income"] == pytest.approx(2_100_000_000 / 6_000_000_000)
    assert r["Loans_to_Deposits"] == pytest.approx(100_000_000_000 / 120_000_000_000)
    assert r["Cout_du_risque"] == pytest.approx(600_000_000 / 100_000_000_000)


def test_bank_growth_2024() -> None:
    r = compute_ratios(_BANK_RAW, archetype="bank", price=_BANK_PRICE, shares=_BANK_SHARES)[2024]
    assert r["Revenue_Growth"] == pytest.approx((6_000_000_000 - 5_500_000_000) / 5_500_000_000)
    assert r["NetIncome_Growth"] == pytest.approx((1_500_000_000 - 1_300_000_000) / 1_300_000_000)


def test_bank_price_ratios_2024() -> None:
    r = compute_ratios(_BANK_RAW, archetype="bank", price=_BANK_PRICE, shares=_BANK_SHARES)[2024]
    market_cap = _BANK_PRICE * _BANK_SHARES  # 78_000_000_000
    assert r["Market_Cap_Calc"] == pytest.approx(market_cap)
    assert r["PER"] == pytest.approx(market_cap / 1_500_000_000)
    assert r["Price_to_Book"] == pytest.approx(market_cap / 15_000_000_000)
    assert r["Dividend_Yield"] == pytest.approx(750_000_000 / market_cap)


# Industrial-only ratios that must be absent for every bank year
_BANK_FORBIDDEN: tuple[str, ...] = (
    "Operating_Margin",
    "FCF_Margin",
    "CAF_Margin",
    "Operating_CF_Margin",
    "Debt_to_Equity",
    "NetDebt_to_Equity",
    "NetDebt_to_EBITDA",
    "Current_Ratio",
    "Cash_Ratio",
    "Interest_Coverage",
    "EBIT_Growth",
    # from FINANCIAL_SUPPRESSED_METRICS
    "EV_to_EBITDA",
    "FCF_Yield",
    "Price_to_Sales",
    "Free_Cash_Flow",
    "Net_Debt",
    "EBITDA",
)


def test_bank_industrial_ratios_absent_all_years() -> None:
    result = compute_ratios(_BANK_RAW, archetype="bank", price=_BANK_PRICE, shares=_BANK_SHARES)
    for year in (2023, 2024):
        r = result[year]
        for key in _BANK_FORBIDDEN:
            assert key not in r, f"bank year {year}: {key!r} must not appear in bank output"


def test_bank_purity() -> None:
    raw: dict[int, dict[str, float]] = {2023: dict(_BANK_2023), 2024: dict(_BANK_2024)}
    snapshot = copy.deepcopy(raw)
    compute_ratios(raw, archetype="bank", price=_BANK_PRICE, shares=_BANK_SHARES)
    assert raw == snapshot, "compute_ratios must not mutate its input"


def test_bank_nim_uses_single_year_assets_when_no_prior() -> None:
    # Only 2024 in fixture — avg_assets falls back to spot Total_Assets
    result = compute_ratios({2024: _BANK_2024}, archetype="bank", price=None, shares=None)
    r = result[2024]
    assert r["Net_Interest_Margin"] == pytest.approx(4_800_000_000 / 180_000_000_000)
