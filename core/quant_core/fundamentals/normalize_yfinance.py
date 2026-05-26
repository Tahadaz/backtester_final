from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from math import isfinite
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class YfinanceNormalizedFundamentals:
    company_name: str
    currency: str | None
    latest_statement_year: int | None
    latest_metrics: dict[str, float | None]
    annual_metrics: list[tuple[int, str, float | None]]
    missing_fields: list[str]


_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("Total Revenue", "TotalRevenue", "Revenue"),
    "ebit": ("EBIT", "Operating Income", "OperatingIncome"),
    "ebitda": ("EBITDA", "Normalized EBITDA"),
    "net_income": ("Net Income", "NetIncome", "Net Income Common Stockholders"),
    "total_assets": ("Total Assets", "TotalAssets"),
    "total_liabilities": ("Total Liabilities Net Minority Interest", "Total Liab", "Total Liabilities"),
    "total_equity": ("Stockholders Equity", "Total Equity Gross Minority Interest", "Total Stockholder Equity"),
    "total_debt": ("Total Debt", "TotalDebt"),
    "cash": ("Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments", "Cash"),
    "current_assets": ("Current Assets", "Total Current Assets"),
    "current_liabilities": ("Current Liabilities", "Total Current Liabilities"),
    "operating_cash_flow": ("Operating Cash Flow", "Total Cash From Operating Activities"),
    "investing_cash_flow": ("Investing Cash Flow", "Total Cashflows From Investing Activities"),
    "financing_cash_flow": ("Financing Cash Flow", "Total Cash From Financing Activities"),
    "fx_effect": ("Effect Of Exchange Rate Changes", "Changes In Cash"),
    "beginning_cash": ("Beginning Cash Position", "Beginning Cash"),
    "ending_cash": ("End Cash Position", "Ending Cash"),
    "cfs_net_income": ("Net Income From Continuing Operations", "Net Income", "NetIncome"),
    "free_cash_flow": ("Free Cash Flow", "FreeCashFlow"),
    "capex": ("Capital Expenditure", "Capital Expenditures"),
    "dividends_paid": ("Cash Dividends Paid", "Dividends Paid", "Common Stock Dividend Paid"),
    "interest_expense": ("Interest Expense", "InterestExpense", "Interest Paid Supplemental Data"),
    "debt_issuance": ("Issuance Of Debt", "Debt Issuance", "Long Term Debt Issuance"),
    "debt_repayment": ("Repayment Of Debt", "Debt Repayment", "Long Term Debt Payments"),
}


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _as_percent(value: float | None) -> float | None:
    return None if value is None else value * 100.0


def _normalize_index(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _series_value(frame: pd.DataFrame | None, column: Any, key: str) -> float | None:
    if frame is None or frame.empty or column not in frame.columns:
        return None
    lookup = {_normalize_index(index): index for index in frame.index}
    for alias in _FIELD_ALIASES[key]:
        index = lookup.get(_normalize_index(alias))
        if index is not None:
            return _safe_float(frame.at[index, column])
    return None


def _ordered_columns(*frames: pd.DataFrame | None, limit: int = 5) -> list[Any]:
    columns: dict[Any, Any] = {}
    for frame in frames:
        if frame is None or frame.empty:
            continue
        for column in frame.columns:
            columns[column] = column
    def sort_key(column: Any) -> dt.datetime:
        try:
            return pd.Timestamp(column).to_pydatetime()
        except Exception:
            return dt.datetime.min
    return sorted(columns, key=sort_key, reverse=True)[:limit]


def _year(column: Any) -> int | None:
    try:
        return int(pd.Timestamp(column).year)
    except Exception:
        return None


def _info_float(info: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _safe_float(info.get(key))
        if value is not None:
            return value
    return None


def normalize_yfinance_fundamentals(
    *,
    symbol: str,
    financials: pd.DataFrame | None,
    balance_sheet: pd.DataFrame | None,
    cashflow: pd.DataFrame | None,
    info: dict[str, Any] | None,
) -> YfinanceNormalizedFundamentals:
    info = dict(info or {})
    company_name = str(info.get("shortName") or info.get("longName") or symbol)
    currency = info.get("financialCurrency") or info.get("currency")
    columns = _ordered_columns(financials, balance_sheet, cashflow)
    latest_column = columns[0] if columns else None
    latest_year = _year(latest_column) if latest_column is not None else None

    annual_by_year: dict[int, dict[str, float | None]] = {}
    for column in columns:
        statement_year = _year(column)
        if statement_year is None:
            continue
        revenue = _series_value(financials, column, "revenue")
        ebit = _series_value(financials, column, "ebit")
        ebitda = _series_value(financials, column, "ebitda")
        net_income = _series_value(financials, column, "net_income")
        total_assets = _series_value(balance_sheet, column, "total_assets")
        total_liabilities = _series_value(balance_sheet, column, "total_liabilities")
        equity = _series_value(balance_sheet, column, "total_equity")
        total_debt = _series_value(balance_sheet, column, "total_debt")
        cash = _series_value(balance_sheet, column, "cash")
        current_assets = _series_value(balance_sheet, column, "current_assets")
        current_liabilities = _series_value(balance_sheet, column, "current_liabilities")
        operating_cf = _series_value(cashflow, column, "operating_cash_flow")
        investing_cf = _series_value(cashflow, column, "investing_cash_flow")
        financing_cf = _series_value(cashflow, column, "financing_cash_flow")
        fx_effect = _series_value(cashflow, column, "fx_effect")
        beginning_cash = _series_value(cashflow, column, "beginning_cash")
        ending_cash = _series_value(cashflow, column, "ending_cash")
        cfs_net_income = _series_value(cashflow, column, "cfs_net_income")
        free_cf = _series_value(cashflow, column, "free_cash_flow")
        capex = _series_value(cashflow, column, "capex")
        if free_cf is None and operating_cf is not None and capex is not None:
            free_cf = operating_cf + capex
        dividends_paid = _series_value(cashflow, column, "dividends_paid")
        interest_expense = _series_value(financials, column, "interest_expense")
        debt_issuance = _series_value(cashflow, column, "debt_issuance")
        debt_repayment = _series_value(cashflow, column, "debt_repayment")
        net_debt = total_debt - cash if total_debt is not None and cash is not None else None
        metrics = {
            "Chiffre_daffaires": revenue,
            "Revenue": revenue,
            "EBIT": ebit,
            "EBITDA": ebitda,
            "Resultat_net": net_income,
            "NetIncome": net_income,
            "Total_Assets": total_assets,
            "Total_Liabilities": total_liabilities,
            "Total_Equity": equity,
            "Total_Debt": total_debt,
            "Cash": cash,
            "Cash_and_Equivalents": cash,
            "NetDebt": net_debt,
            "Current_Assets": current_assets,
            "Current_Liabilities": current_liabilities,
            "Operating_Cash_Flow": operating_cf,
            "CF_Operating": operating_cf,
            "CF_Investing": investing_cf,
            "CF_Financing": financing_cf,
            "CF_FX_Effect": fx_effect,
            "CFS_Beginning_Cash": beginning_cash,
            "CFS_Ending_Cash": ending_cash,
            "CFS_Net_Income_Top_Of_CFS": cfs_net_income,
            "Free_Cash_Flow": free_cf,
            "Dividends_Paid": abs(dividends_paid) if dividends_paid is not None else None,
            "Interest_Expense": abs(interest_expense) if interest_expense is not None else None,
            "Debt_Issuance": abs(debt_issuance) if debt_issuance is not None and debt_issuance > 0 else None,
            "Debt_Repayment": abs(debt_repayment) if debt_repayment is not None else None,
            "ROE": _as_percent(_safe_ratio(net_income, equity)),
            "ROA": _as_percent(_safe_ratio(net_income, total_assets)),
            "Debt_to_Equity": _safe_ratio(total_debt, equity),
            "Current_Ratio": _safe_ratio(current_assets, current_liabilities),
            "Cash_Ratio": _safe_ratio(cash, current_liabilities),
            "Interest_Coverage": _safe_ratio(ebit, abs(interest_expense) if interest_expense is not None else None),
            "Operating_Margin": _as_percent(_safe_ratio(ebit, revenue)),
            "Net_Margin": _as_percent(_safe_ratio(net_income, revenue)),
            "FCF_Margin": _as_percent(_safe_ratio(free_cf, revenue)),
            "Operating_CF_Margin": _as_percent(_safe_ratio(operating_cf, revenue)),
            "Asset_Turnover": _safe_ratio(revenue, total_assets),
        }
        annual_by_year[statement_year] = metrics

    sorted_years = sorted(annual_by_year)
    latest_metrics: dict[str, float | None] = {}
    if latest_year in annual_by_year:
        latest_metrics.update(annual_by_year[latest_year])
    elif sorted_years:
        latest_year = sorted_years[-1]
        latest_metrics.update(annual_by_year[latest_year])

    def growth(metric: str) -> float | None:
        if len(sorted_years) < 2:
            return None
        latest = annual_by_year[sorted_years[-1]].get(metric)
        previous = annual_by_year[sorted_years[-2]].get(metric)
        if latest is None or previous in (None, 0):
            return None
        return ((latest - previous) / abs(previous)) * 100.0

    market_cap = _info_float(info, "marketCap")
    current_price = _info_float(info, "currentPrice", "regularMarketPrice", "previousClose")
    shares = _info_float(info, "sharesOutstanding")
    total_debt = latest_metrics.get("Total_Debt") or _info_float(info, "totalDebt")
    cash = latest_metrics.get("Cash") or _info_float(info, "totalCash")
    net_debt = total_debt - cash if total_debt is not None and cash is not None else None
    ebitda = latest_metrics.get("EBITDA")
    revenue = latest_metrics.get("Revenue") or latest_metrics.get("Chiffre_daffaires")
    net_income = latest_metrics.get("NetIncome") or latest_metrics.get("Resultat_net")
    free_cf = latest_metrics.get("Free_Cash_Flow")
    dividends_paid = latest_metrics.get("Dividends_Paid")
    latest_metrics.update({
        "Shares_Outstanding": shares,
        "Current_Price": current_price,
        "MarketCap_Calc": market_cap,
        "PER": _info_float(info, "trailingPE", "forwardPE") or _safe_ratio(market_cap, net_income),
        "Price_to_Book": _info_float(info, "priceToBook") or _safe_ratio(market_cap, latest_metrics.get("Total_Equity")),
        "Price_to_Sales": _safe_ratio(market_cap, revenue),
        "EV_to_EBITDA": _info_float(info, "enterpriseToEbitda"),
        "Dividend_Yield": _as_percent(_info_float(info, "dividendYield")),
        "Dividend_Payout": _as_percent(_safe_ratio(dividends_paid, net_income)),
        "Dividend_Coverage": _safe_ratio(net_income, dividends_paid),
        "FCF_Yield": _as_percent(_safe_ratio(free_cf, market_cap)),
        "NetDebt_to_EBITDA": _safe_ratio(net_debt, ebitda),
        "Revenue_Growth": growth("Revenue"),
        "EBIT_Growth": growth("EBIT"),
        "NetIncome_Growth": growth("NetIncome"),
        "OperatingCF_Growth": growth("Operating_Cash_Flow"),
        "FCF_Growth": growth("Free_Cash_Flow"),
    })

    annual_metrics = [
        (statement_year, metric_name, value)
        for statement_year in sorted_years
        for metric_name, value in annual_by_year[statement_year].items()
    ]
    missing = [
        name
        for name in ("Current_Price", "PER", "Price_to_Book", "ROE", "Debt_to_Equity", "FCF_Yield")
        if latest_metrics.get(name) is None
    ]
    return YfinanceNormalizedFundamentals(
        company_name=company_name,
        currency=str(currency) if currency else None,
        latest_statement_year=latest_year,
        latest_metrics=latest_metrics,
        annual_metrics=annual_metrics,
        missing_fields=missing,
    )
