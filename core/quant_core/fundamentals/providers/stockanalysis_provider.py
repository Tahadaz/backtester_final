from __future__ import annotations

import re
import time
from html.parser import HTMLParser
from math import isfinite
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.quant_core.fundamentals.domain import (
    AnnualMetricRow,
    CompanyMapping,
    FundamentalQualityIssue,
    FundamentalSnapshot,
    FundamentalWorkbook,
)

from . import ProviderUnavailableError


BASE_URL = "https://stockanalysis.com/quote/cbse/{symbol}"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
MONEY_SCALE = 1_000_000.0
SUPPORTED_CURRENCY = "MAD"
CORE_STATEMENT_FIELDS = (
    "Revenue",
    "NetIncome",
    "Total_Assets",
    "Total_Equity",
    "Operating_Cash_Flow",
    "Free_Cash_Flow",
    "Total_Debt",
)


class _FirstTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._in_table = False
        self._done = False
        self._in_row = False
        self._in_cell = False
        self._current_row: list[str] = []
        self._current_cell: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._done:
            return
        if tag == "table" and not self._in_table:
            self._in_table = True
            return
        if not self._in_table:
            return
        if tag == "tr":
            self._in_row = True
            self._current_row = []
        elif tag in {"th", "td"} and self._in_row:
            self._in_cell = True
            self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        if self._done or not self._in_table:
            return
        if tag in {"th", "td"} and self._in_cell:
            text = " ".join("".join(self._current_cell).split())
            self._current_row.append(text)
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            if self._current_row:
                self.rows.append(self._current_row)
            self._in_row = False
        elif tag == "table":
            self._in_table = False
            self._done = True

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current_cell.append(data)


def _first_table_rows(html: str) -> list[list[str]]:
    parser = _FirstTableParser()
    parser.feed(html)
    return parser.rows


def _year_from_header(value: str) -> int | None:
    match = re.search(r"(?:FY\s*)?(20\d{2}|19\d{2})", value or "")
    return int(match.group(1)) if match else None


def _statement_years(rows: list[list[str]]) -> list[int | None]:
    if not rows:
        return []
    return [_year_from_header(cell) for cell in rows[0][1:]]


def _safe_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text in {"-", "--", "N/A"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.replace("MAD", "").replace("%", "").replace(",", "").replace("(", "").replace(")", "")
    try:
        out = float(text)
    except (TypeError, ValueError):
        return None
    if negative:
        out = -out
    return out if isfinite(out) else None


def _scaled_money(value: Any) -> float | None:
    out = _safe_float(value)
    return None if out is None else out * MONEY_SCALE


def _scaled_money_first(*values: Any) -> float | None:
    for value in values:
        out = _scaled_money(value)
        if out is not None:
            return out
    return None


def _first_non_null(*values: float | None) -> float | None:
    for value in values:
        if value is not None:
            return value
    return None


def _abs_money(value: float | None) -> float | None:
    return None if value is None else abs(value)


def _scaled_shares(value: Any) -> float | None:
    out = _safe_float(value)
    return None if out is None else out * MONEY_SCALE


def _currency_from_html(html: str) -> str | None:
    match = re.search(r"Financials\s+in\s+millions\s+([A-Z]{3})", html or "", flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).upper()


def _table_values_by_year(rows: list[list[str]]) -> dict[int, dict[str, float | None]]:
    years = _statement_years(rows)
    out: dict[int, dict[str, float | None]] = {}
    for row in rows[1:]:
        if len(row) < 2:
            continue
        label = row[0]
        for index, year in enumerate(years, start=1):
            if year is None or index >= len(row):
                continue
            value = _safe_float(row[index])
            out.setdefault(year, {})[label] = value
    return out


def _latest_year(annual: dict[int, dict[str, float | None]]) -> int | None:
    years = [year for year, values in annual.items() if _has_core_statement_values(values)]
    return max(years) if years else None


def _has_core_statement_values(values: dict[str, float | None]) -> bool:
    # Require at least 2 non-null core fields to reject all-null or near-empty
    # years (e.g., TTM / partial columns that would create phantom statement years).
    return sum(1 for metric in CORE_STATEMENT_FIELDS if values.get(metric) is not None) >= 2


def _dividend_history_by_fiscal_year(rows: list[list[str]]) -> dict[int, float]:
    out: dict[int, float] = {}
    if not rows:
        return out
    for row in rows[1:]:
        if len(row) < 2:
            continue
        year_match = re.search(r"(20\d{2}|19\d{2})", row[0])
        if not year_match:
            continue
        cash_amount = _safe_float(row[1])
        if cash_amount is not None:
            # StockAnalysis' dividend table is event-dated by ex-date/payment year.
            # Moroccan annual dividends are normally detached in the following
            # calendar year, while financial tables are keyed by fiscal year.
            out[int(year_match.group(1)) - 1] = cash_amount
    return out


class StockAnalysisFundamentalProvider:
    """Fetch public StockAnalysis financial tables for CBSE/MASI symbols."""

    def __init__(self, *, timeout_seconds: int = 30, retries: int = 3, sleep: Any = time.sleep):
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self._sleep = sleep

    def fetch(
        self,
        symbol: str,
        *,
        provider_symbol: str | None = None,
        display_name: str | None = None,
        market_region: str | None = "masi",
        shares_outstanding: float | None = None,
    ) -> FundamentalWorkbook:
        target_symbol = symbol.upper()
        provider = (provider_symbol or target_symbol).upper()
        last_exc: Exception | None = None
        for attempt in range(self.retries):
            try:
                return self._fetch_once(
                    target_symbol,
                    provider_symbol=provider,
                    display_name=display_name,
                    market_region=market_region,
                    shares_outstanding=shares_outstanding,
                )
            except Exception as exc:
                last_exc = exc
                if attempt < self.retries - 1:
                    self._sleep(2**attempt)
        raise ProviderUnavailableError(f"stockanalysis fundamentals unavailable for {target_symbol}: {last_exc}") from last_exc

    def _fetch_url(self, url: str) -> str:
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return response.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError, TimeoutError) as exc:
            raise ProviderUnavailableError(f"could not fetch {url}: {exc}") from exc

    def _fetch_table(self, url: str) -> list[list[str]]:
        rows, _currency = self._fetch_table_with_currency(url)
        return rows

    def _fetch_table_with_currency(self, url: str) -> tuple[list[list[str]], str | None]:
        html = self._fetch_url(url)
        rows = _first_table_rows(html)
        if not rows:
            raise ProviderUnavailableError(f"no financial table found at {url}")
        return rows, _currency_from_html(html)

    def _fetch_once(
        self,
        symbol: str,
        *,
        provider_symbol: str,
        display_name: str | None,
        market_region: str | None,
        shares_outstanding: float | None,
    ) -> FundamentalWorkbook:
        base = BASE_URL.format(symbol=provider_symbol)
        urls = {
            "income": f"{base}/financials/",
            "balance": f"{base}/financials/balance-sheet/",
            "cash_flow": f"{base}/financials/cash-flow-statement/",
            "dividends": f"{base}/dividend/",
        }
        tables: dict[str, list[list[str]]] = {}
        currencies: set[str] = set()
        for statement_name in ("income", "balance", "cash_flow"):
            try:
                rows, currency = self._fetch_table_with_currency(urls[statement_name])
            except ProviderUnavailableError:
                tables[statement_name] = []
                continue
            tables[statement_name] = rows
            if currency:
                currencies.add(currency)
        if not any(tables.values()):
            raise ProviderUnavailableError(f"no financial statement tables found for {provider_symbol}")
        currency = next(iter(currencies)) if len(currencies) == 1 else SUPPORTED_CURRENCY
        if len(currencies) > 1:
            raise ProviderUnavailableError(f"mixed StockAnalysis statement currencies for {provider_symbol}: {sorted(currencies)}")
        if currency != SUPPORTED_CURRENCY:
            raise ProviderUnavailableError(
                f"StockAnalysis reports {provider_symbol} financials in {currency}; {SUPPORTED_CURRENCY} conversion is not implemented"
            )
        for optional_name in ("dividends",):
            try:
                tables[optional_name] = self._fetch_table(urls[optional_name])
            except ProviderUnavailableError:
                tables[optional_name] = []
        annual = self._normalize_tables(tables, shares_outstanding=shares_outstanding)
        latest_year = _latest_year(annual)
        latest_metrics = dict(annual.get(latest_year, {})) if latest_year is not None else {}
        company_name = display_name or symbol
        source_urls = list(urls.values())
        annual_rows = [
            AnnualMetricRow(
                symbol=symbol,
                company_name=company_name,
                statement_year=year,
                metric_name=metric,
                metric_value=value,
                raw_metric_name=metric,
                source_sheet="stockanalysis",
                source_field=metric,
            )
            for year in sorted(annual)
            for metric, value in sorted(annual[year].items())
            if value is not None  # never write null rows — they pollute the resolver
        ]
        mapping = CompanyMapping(
            company_name=company_name,
            mapped_company_name=company_name,
            symbol=symbol,
            shares_outstanding=shares_outstanding,
            match_type="provider_symbol",
            score_note=f"stockanalysis:{provider_symbol}",
            source="stockanalysis",
            canonical_company_name=company_name,
        )
        snapshot = FundamentalSnapshot(
            symbol=symbol,
            company_name=company_name,
            latest_statement_year=latest_year,
            metrics=latest_metrics,
            coverage={
                "latest_statement_year": latest_year,
                "metric_count": sum(value is not None for value in latest_metrics.values()),
                "core_year_count": len(annual),
                "has_market_cap": latest_metrics.get("MarketCap_Calc") is not None,
                "has_current_price": latest_metrics.get("Current_Price") is not None,
                "source_urls": source_urls,
            },
            source={
                "data_source": "stockanalysis",
                "provider_symbol": provider_symbol,
                "currency": currency,
                "market_region": market_region,
                "source_urls": source_urls,
            },
        )
        return FundamentalWorkbook(
            mappings=[mapping],
            annual_metrics=annual_rows,
            latest_snapshots=[snapshot],
            summary={
                "data_source": "stockanalysis",
                "symbol": symbol,
                "provider_symbol": provider_symbol,
                "market_region": market_region,
                "source_urls": source_urls,
                "annual_year_count": len(annual),
                "annual_metric_count": len(annual_rows),
            },
            quality_issues=[
                FundamentalQualityIssue(
                    severity="info",
                    code="stockanalysis_public_web_backfill",
                    message="Public web financial tables imported from StockAnalysis CBSE pages.",
                    symbol=symbol,
                    context={"provider_symbol": provider_symbol, "source_urls": source_urls},
                )
            ],
        )

    def _normalize_tables(
        self,
        tables: dict[str, list[list[str]]],
        *,
        shares_outstanding: float | None,
    ) -> dict[int, dict[str, float | None]]:
        income = _table_values_by_year(tables.get("income", []))
        balance = _table_values_by_year(tables.get("balance", []))
        cash_flow = _table_values_by_year(tables.get("cash_flow", []))
        dividend_history = _dividend_history_by_fiscal_year(tables.get("dividends", []))
        annual: dict[int, dict[str, float | None]] = {}
        years = sorted(set(income) | set(balance) | set(cash_flow))

        for year in years:
            inc = income.get(year, {})
            bal = balance.get(year, {})
            cf = cash_flow.get(year, {})
            shares = shares_outstanding
            if shares is None:
                shares = _scaled_shares(bal.get("Total Common Shares Outstanding"))
            if shares is None:
                shares = _scaled_shares(inc.get("Diluted Shares Outstanding"))
            total_debt = _scaled_money(bal.get("Total Debt"))
            cash = _scaled_money(bal.get("Cash & Equivalents"))
            net_cash = _scaled_money(bal.get("Net Cash (Debt)"))
            net_debt = -net_cash if net_cash is not None else (total_debt - cash if total_debt is not None and cash is not None else None)
            revenue = _scaled_money_first(inc.get("Revenue"), inc.get("Total Revenue"))
            net_income = _scaled_money(inc.get("Net Income"))
            total_assets = _scaled_money(bal.get("Total Assets"))
            equity = _scaled_money(bal.get("Shareholders' Equity"))
            operating_cf = _scaled_money(cf.get("Operating Cash Flow"))
            free_cf = _scaled_money(cf.get("Free Cash Flow"))
            gross_profit = _scaled_money(inc.get("Gross Profit"))
            operating_expenses = _scaled_money_first(inc.get("Operating Expenses"), inc.get("Total Non-Interest Expense"))
            ebit = _scaled_money_first(inc.get("EBIT"), inc.get("Operating Income"))
            ebitda = _scaled_money(inc.get("EBITDA"))
            depreciation_amortization = _scaled_money_first(
                inc.get("D&A For EBITDA"),
                cf.get("Depreciation & Amortization"),
            )
            interest_expense = _abs_money(_scaled_money_first(inc.get("Interest Expense"), inc.get("Interest Paid on Deposits")))
            income_tax = _scaled_money(inc.get("Income Tax Expense"))
            current_assets = _scaled_money(bal.get("Total Current Assets"))
            current_liabilities = _scaled_money(bal.get("Total Current Liabilities"))
            accounts_receivable = _scaled_money_first(bal.get("Receivables"), bal.get("Accounts Receivable"))
            accounts_payable = _scaled_money(bal.get("Accounts Payable"))
            inventory = _scaled_money(bal.get("Inventory"))
            retained_earnings = _scaled_money(bal.get("Retained Earnings"))
            working_capital = _scaled_money(bal.get("Working Capital"))
            capital_expenditures = _scaled_money(cf.get("Capital Expenditures"))
            common_dividends_paid = _scaled_money(cf.get("Common Dividends Paid"))
            change_in_working_capital = _scaled_money(cf.get("Change in Working Capital"))
            dividend_per_share = inc.get("Dividend Per Share")
            if dividend_per_share is None:
                dividend_per_share = dividend_history.get(year)
            dividends: float | None = None
            if dividend_per_share is not None and shares is not None and shares > 0:
                raw_total = dividend_per_share * shares
                # Sanity-guard: total dividends > 5× |net_income| implies a unit
                # mismatch (DPS treated as total, or wrong-scale DPS). Discard.
                if net_income is not None and net_income != 0 and raw_total > abs(net_income) * 5.0:
                    dividend_per_share = None  # clear so Dividend_Per_Share is not written either
                else:
                    dividends = raw_total
            dividends = _first_non_null(dividends, _abs_money(common_dividends_paid))
            premiums_earned = _scaled_money(inc.get("Premiums & Annuity Revenue"))
            policy_benefits = _scaled_money(inc.get("Policy Benefits"))
            policy_acquisition_costs = _scaled_money(inc.get("Policy Acquisition & Underwriting Costs"))
            values = {
                "Has_Core_Fundamentals": 1.0,
                "Revenue": revenue,
                "Cost_of_Revenue": _scaled_money(inc.get("Cost of Revenue")),
                "Gross_Profit": gross_profit,
                "Operating_Expenses": operating_expenses,
                "Selling_General_Admin": _scaled_money(inc.get("Selling, General & Admin")),
                "Other_Operating_Expenses": _scaled_money(inc.get("Other Operating Expenses")),
                "Occupancy_Expenses": _scaled_money(inc.get("Occupancy Expenses")),
                "Other_NonInterest_Expense": _scaled_money(inc.get("Other Non-Interest Expense")),
                "EBITDA": ebitda,
                "EBIT": ebit,
                "Depreciation_Amortization": depreciation_amortization,
                "Interest_Expense": interest_expense,
                "Net_Interest_Income": _scaled_money(inc.get("Net Interest Income")),
                "Total_Interest_Income": _scaled_money(inc.get("Total Interest Income")),
                "Interest_Income_on_Loans": _scaled_money(inc.get("Interest Income on Loans")),
                "Interest_Paid_on_Deposits": _scaled_money(inc.get("Interest Paid on Deposits")),
                "Total_NonInterest_Income": _scaled_money(inc.get("Total Non-Interest Income")),
                "Revenues_Before_Loan_Losses": _scaled_money(inc.get("Revenues Before Loan Losses")),
                "Provision_for_Loan_Losses": _scaled_money(inc.get("Provision for Loan Losses")),
                "Premiums_Earned": premiums_earned,
                "Policy_Benefits": policy_benefits,
                "Policy_Acquisition_Costs": policy_acquisition_costs,
                "Pretax_Income": _scaled_money(inc.get("Pretax Income")),
                "Income_Tax_Expense": income_tax,
                "NetIncome": net_income,
                "Basic_EPS": inc.get("EPS (Basic)"),
                "Diluted_EPS": inc.get("EPS (Diluted)"),
                "Dividend_Per_Share": dividend_per_share,
                "Dividendes": dividends,
                "Common_Dividends_Paid": common_dividends_paid,
                "Total_Assets": total_assets,
                "Total_Liabilities": _scaled_money(bal.get("Total Liabilities")),
                "Total_Liabilities_And_Equity": _scaled_money(bal.get("Total Liabilities & Equity")),
                "Total_Equity": equity,
                "Total_Debt": total_debt,
                "Cash": cash,
                "Net_Debt": net_debt,
                "Loans_Net": _scaled_money(bal.get("Net Loans")),
                "Customer_Deposits": _scaled_money(bal.get("Total Deposits")),
                "Current_Assets": current_assets,
                "Current_Liabilities": current_liabilities,
                "Inventory": inventory,
                "Accounts_Receivable": accounts_receivable,
                "Accounts_Payable": accounts_payable,
                "Retained_Earnings": retained_earnings,
                "Working_Capital": working_capital,
                "Shares_Outstanding": shares,
                "Book_Value_Per_Share": bal.get("Book Value Per Share"),
                "CFS_Net_Income_Top_Of_CFS": _scaled_money(cf.get("Net Income")),
                "Operating_Cash_Flow": operating_cf,
                "CF_Investing": _scaled_money(cf.get("Investing Cash Flow")),
                "CF_Financing": _scaled_money(cf.get("Financing Cash Flow")),
                "CF_FX_Effect": _scaled_money(cf.get("Foreign Exchange Rate Adjustments")),
                "Change_in_Cash": _scaled_money(cf.get("Net Cash Flow")),
                "Change_in_Working_Capital": change_in_working_capital,
                "Free_Cash_Flow": free_cf,
                "Capital_Expenditures": capital_expenditures,
                "Capex": _abs_money(capital_expenditures),
            }
            if _has_core_statement_values(values):
                annual[year] = values

        return annual
