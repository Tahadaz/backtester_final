from __future__ import annotations

from math import isfinite
from typing import Any

from .cgnc_mapping import FINANCIAL_ARCHETYPES, FINANCIAL_SUPPRESSED_METRICS


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    try:
        result = numerator / denominator
    except ZeroDivisionError:
        return None
    return result if isfinite(result) else None


def _get(raw_by_year: dict[int, dict[str, Any]], year: int, *keys: str) -> float | None:
    """Return the first finite float found under any of *keys* for *year*."""
    row = raw_by_year.get(year, {})
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        try:
            f = float(value)
        except (TypeError, ValueError):
            continue
        if isfinite(f):
            return f
    return None


def _set(d: dict[str, float], key: str, value: float | None) -> None:
    if value is not None:
        d[key] = value


def _yoy_growth(raw_by_year: dict[int, dict[str, Any]], year: int, metric: str) -> float | None:
    latest = _get(raw_by_year, year, metric)
    previous = _get(raw_by_year, year - 1, metric)
    if latest is None or previous is None or previous == 0:
        return None
    result = (latest - previous) / abs(previous)
    return result if isfinite(result) else None


def _avg_equity(raw_by_year: dict[int, dict[str, Any]], year: int) -> float | None:
    current = _get(raw_by_year, year, "Total_Equity")
    if current is None:
        return None
    previous = _get(raw_by_year, year - 1, "Total_Equity")
    if previous is not None:
        return (current + previous) / 2.0
    return current


def _avg_assets(raw_by_year: dict[int, dict[str, Any]], year: int) -> float | None:
    current = _get(raw_by_year, year, "Total_Assets")
    if current is None:
        return None
    previous = _get(raw_by_year, year - 1, "Total_Assets")
    if previous is not None:
        return (current + previous) / 2.0
    return current


def _bank_revenue(row: dict[str, Any]) -> float | None:
    """Primary revenue proxy for banks: Revenue → PNB → Net_Interest_Income."""
    for key in ("Revenue", "PNB", "Net_Interest_Income"):
        value = row.get(key)
        if value is None:
            continue
        try:
            f = float(value)
        except (TypeError, ValueError):
            continue
        if isfinite(f) and f != 0:
            return f
    return None


# ---------------------------------------------------------------------------
# Per-archetype ratio dispatchers
# ---------------------------------------------------------------------------

def _industrial_ratios(
    raw_by_year: dict[int, dict[str, float]],
    price: float | None,
    shares: float | None,
) -> dict[int, dict[str, float]]:
    years = sorted(raw_by_year)
    latest_year = years[-1] if years else None
    out: dict[int, dict[str, float]] = {}

    for year in years:
        ratios: dict[str, float] = {}

        revenue = _get(raw_by_year, year, "Revenue")
        ebit = _get(raw_by_year, year, "EBIT")
        net_income = _get(raw_by_year, year, "NetIncome")
        total_assets = _get(raw_by_year, year, "Total_Assets")
        total_equity = _get(raw_by_year, year, "Total_Equity")
        total_debt = _get(raw_by_year, year, "Total_Debt")
        net_debt = _get(raw_by_year, year, "Net_Debt")
        cash = _get(raw_by_year, year, "Cash")
        current_assets = _get(raw_by_year, year, "Current_Assets")
        current_liabilities = _get(raw_by_year, year, "Current_Liabilities")
        operating_cf = _get(raw_by_year, year, "Operating_Cash_Flow")
        free_cf = _get(raw_by_year, year, "Free_Cash_Flow")
        ebitda = _get(raw_by_year, year, "EBITDA")
        interest_expense = _get(raw_by_year, year, "Interest_Expense")
        caf = _get(raw_by_year, year, "CAF")
        dividendes = _get(raw_by_year, year, "Dividendes")
        avg_equity = _avg_equity(raw_by_year, year)

        # margins
        _set(ratios, "Operating_Margin", _safe_div(ebit, revenue))
        _set(ratios, "Net_Margin", _safe_div(net_income, revenue))
        _set(ratios, "FCF_Margin", _safe_div(free_cf, revenue))
        _set(ratios, "Operating_CF_Margin", _safe_div(operating_cf, revenue))
        _set(ratios, "CAF_Margin", _safe_div(caf, revenue))
        # returns
        _set(ratios, "ROA", _safe_div(net_income, total_assets))
        _set(ratios, "ROE", _safe_div(net_income, avg_equity))
        # leverage / risk
        _set(ratios, "Debt_to_Equity", _safe_div(total_debt, total_equity))
        _set(ratios, "NetDebt_to_Equity", _safe_div(net_debt, total_equity))
        _set(ratios, "NetDebt_to_EBITDA", _safe_div(net_debt, ebitda))
        _set(ratios, "Equity_Multiplier", _safe_div(total_assets, total_equity))
        # health
        _set(ratios, "Current_Ratio", _safe_div(current_assets, current_liabilities))
        _set(ratios, "Cash_Ratio", _safe_div(cash, current_liabilities))
        _set(ratios, "Interest_Coverage", _safe_div(ebit, interest_expense))
        # growth (requires prior year in raw_by_year)
        _set(ratios, "Revenue_Growth", _yoy_growth(raw_by_year, year, "Revenue"))
        _set(ratios, "EBIT_Growth", _yoy_growth(raw_by_year, year, "EBIT"))
        _set(ratios, "NetIncome_Growth", _yoy_growth(raw_by_year, year, "NetIncome"))

        # price-derived — latest year only; omit entirely when price/shares absent
        if year == latest_year and price is not None and shares is not None and shares > 0:
            market_cap = price * shares
            ev = market_cap + (net_debt if net_debt is not None else 0.0)
            _set(ratios, "Market_Cap_Calc", market_cap)
            _set(ratios, "EV_Calc", ev)
            _set(ratios, "PER", _safe_div(market_cap, net_income))
            _set(ratios, "Price_to_Book", _safe_div(market_cap, total_equity))
            _set(ratios, "Price_to_Sales", _safe_div(market_cap, revenue))
            _set(ratios, "EV_to_EBITDA", _safe_div(ev, ebitda))
            _set(ratios, "FCF_Yield", _safe_div(free_cf, market_cap))
            _set(ratios, "Dividend_Yield", _safe_div(dividendes, market_cap))

        out[year] = ratios
    return out


def _bank_ratios(
    raw_by_year: dict[int, dict[str, float]],
    price: float | None,
    shares: float | None,
) -> dict[int, dict[str, float]]:
    years = sorted(raw_by_year)
    latest_year = years[-1] if years else None
    out: dict[int, dict[str, float]] = {}

    for year in years:
        ratios: dict[str, float] = {}

        net_income = _get(raw_by_year, year, "NetIncome")
        total_assets = _get(raw_by_year, year, "Total_Assets")
        total_equity = _get(raw_by_year, year, "Total_Equity")
        net_interest_income = _get(raw_by_year, year, "Net_Interest_Income")
        operating_expenses = _get(raw_by_year, year, "Operating_Expenses")
        loans_net = _get(raw_by_year, year, "Loans_Net")
        customer_deposits = _get(raw_by_year, year, "Customer_Deposits")
        provision = _get(raw_by_year, year, "Provision_for_Loan_Losses")
        dividendes = _get(raw_by_year, year, "Dividendes")
        avg_equity = _avg_equity(raw_by_year, year)
        avg_assets = _avg_assets(raw_by_year, year)
        revenue = _bank_revenue(raw_by_year.get(year, {}))

        _set(ratios, "ROE", _safe_div(net_income, avg_equity))
        _set(ratios, "ROA", _safe_div(net_income, total_assets))
        _set(ratios, "Net_Margin", _safe_div(net_income, revenue))
        _set(ratios, "Equity_Multiplier", _safe_div(total_assets, total_equity))
        _set(ratios, "Net_Interest_Margin", _safe_div(net_interest_income, avg_assets))
        _set(ratios, "Cost_to_Income", _safe_div(operating_expenses, revenue))
        _set(ratios, "Loans_to_Deposits", _safe_div(loans_net, customer_deposits))
        # Cost of risk: abs(provision) / gross loans; canonical name matches BVC lineage
        if provision is not None and loans_net is not None and loans_net > 0:
            _set(ratios, "Cout_du_risque", abs(provision) / loans_net)
        _set(ratios, "Revenue_Growth", _yoy_growth(raw_by_year, year, "Revenue"))
        _set(ratios, "NetIncome_Growth", _yoy_growth(raw_by_year, year, "NetIncome"))

        if year == latest_year and price is not None and shares is not None and shares > 0:
            market_cap = price * shares
            _set(ratios, "Market_Cap_Calc", market_cap)
            _set(ratios, "PER", _safe_div(market_cap, net_income))
            _set(ratios, "Price_to_Book", _safe_div(market_cap, total_equity))
            _set(ratios, "Dividend_Yield", _safe_div(dividendes, market_cap))

        # Safety guard: never emit FINANCIAL_SUPPRESSED_METRICS for banks
        for key in list(ratios):
            if key in FINANCIAL_SUPPRESSED_METRICS:
                del ratios[key]

        out[year] = ratios
    return out


def _financial_ratios(
    raw_by_year: dict[int, dict[str, float]],
    price: float | None,
    shares: float | None,
) -> dict[int, dict[str, float]]:
    """Insurance and uncertain-financial archetypes: ROE/ROA/margins/growth + PER/P_B/Div_Yield."""
    years = sorted(raw_by_year)
    latest_year = years[-1] if years else None
    out: dict[int, dict[str, float]] = {}

    for year in years:
        ratios: dict[str, float] = {}

        net_income = _get(raw_by_year, year, "NetIncome")
        total_assets = _get(raw_by_year, year, "Total_Assets")
        total_equity = _get(raw_by_year, year, "Total_Equity")
        dividendes = _get(raw_by_year, year, "Dividendes")
        avg_equity = _avg_equity(raw_by_year, year)
        revenue = _bank_revenue(raw_by_year.get(year, {}))  # same fallback order
        premiums_earned = _get(raw_by_year, year, "Premiums_Earned")
        policy_benefits = _get(raw_by_year, year, "Policy_Benefits")
        policy_acq_costs = _get(raw_by_year, year, "Policy_Acquisition_Costs")

        _set(ratios, "ROE", _safe_div(net_income, avg_equity))
        _set(ratios, "ROA", _safe_div(net_income, total_assets))
        _set(ratios, "Net_Margin", _safe_div(net_income, revenue))
        _set(ratios, "Equity_Multiplier", _safe_div(total_assets, total_equity))
        _set(ratios, "Revenue_Growth", _yoy_growth(raw_by_year, year, "Revenue"))
        _set(ratios, "NetIncome_Growth", _yoy_growth(raw_by_year, year, "NetIncome"))
        # Combined ratio: insurer analog of bank Cost_to_Income (lower is better)
        if premiums_earned and premiums_earned > 0 and (policy_benefits is not None or policy_acq_costs is not None):
            _set(ratios, "Combined_Ratio", ((policy_benefits or 0.0) + (policy_acq_costs or 0.0)) / premiums_earned)

        if year == latest_year and price is not None and shares is not None and shares > 0:
            market_cap = price * shares
            _set(ratios, "Market_Cap_Calc", market_cap)
            _set(ratios, "PER", _safe_div(market_cap, net_income))
            _set(ratios, "Price_to_Book", _safe_div(market_cap, total_equity))
            _set(ratios, "Dividend_Yield", _safe_div(dividendes, market_cap))

        for key in list(ratios):
            if key in FINANCIAL_SUPPRESSED_METRICS:
                del ratios[key]

        out[year] = ratios
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_ratios(
    raw_by_year: dict[int, dict[str, float]],
    *,
    archetype: str,
    price: float | None,
    shares: float | None,
) -> dict[int, dict[str, float]]:
    """Compute scorer-ready ratios from raw 3-statement data.

    Pure function — input dicts are never modified.  Returns a new dict of
    ratios keyed by year; the caller merges into raw_by_year if desired.

    Invariant: scraped ratio keys are never read or emitted.  All ratios are
    derived here from raw statement lines only.

    archetype dispatching:
      "bank"                      → bank-specific ratios (NIM, C/I, L/D, …)
      "insurance" or any other
        FINANCIAL_ARCHETYPES key  → financial ratios (ROE/ROA/margins + P/B/PER)
      anything else (incl. "unknown") → industrial ratios (full scorer set)
    """
    if not raw_by_year:
        return {}
    if archetype == "bank":
        return _bank_ratios(raw_by_year, price, shares)
    if archetype in FINANCIAL_ARCHETYPES:
        return _financial_ratios(raw_by_year, price, shares)
    return _industrial_ratios(raw_by_year, price, shares)
