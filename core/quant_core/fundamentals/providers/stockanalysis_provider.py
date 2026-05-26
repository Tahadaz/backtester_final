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


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _scaled_money(value: Any) -> float | None:
    out = _safe_float(value)
    return None if out is None else out * MONEY_SCALE


def _scaled_shares(value: Any) -> float | None:
    out = _safe_float(value)
    return None if out is None else out * MONEY_SCALE


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
    years = [year for year, values in annual.items() if any(value is not None for value in values.values())]
    return max(years) if years else None


def _growth(annual: dict[int, dict[str, float | None]], metric: str, latest_year: int) -> float | None:
    previous_year = latest_year - 1
    latest = annual.get(latest_year, {}).get(metric)
    previous = annual.get(previous_year, {}).get(metric)
    if latest is None or previous in (None, 0):
        return None
    return (latest - previous) / abs(previous)


def _dividend_history_by_year(rows: list[list[str]]) -> dict[int, float]:
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
            out[int(year_match.group(1))] = cash_amount
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
        rows = _first_table_rows(self._fetch_url(url))
        if not rows:
            raise ProviderUnavailableError(f"no financial table found at {url}")
        return rows

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
        tables = {
            "income": self._fetch_table(urls["income"]),
            "balance": self._fetch_table(urls["balance"]),
        }
        for optional_name in ("cash_flow", "dividends"):
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
                "currency": "MAD",
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
        income = _table_values_by_year(tables["income"])
        balance = _table_values_by_year(tables["balance"])
        cash_flow = _table_values_by_year(tables["cash_flow"])
        dividend_history = _dividend_history_by_year(tables.get("dividends", []))
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
            revenue = _scaled_money(inc.get("Revenue"))
            net_income = _scaled_money(inc.get("Net Income"))
            total_assets = _scaled_money(bal.get("Total Assets"))
            equity = _scaled_money(bal.get("Shareholders' Equity"))
            operating_cf = _scaled_money(cf.get("Operating Cash Flow"))
            free_cf = _scaled_money(cf.get("Free Cash Flow"))
            dividend_per_share = inc.get("Dividend Per Share")
            if dividend_per_share is None:
                dividend_per_share = dividend_history.get(year)
            dividends = dividend_per_share * shares if dividend_per_share is not None and shares else None
            annual[year] = {
                "Has_Core_Fundamentals": 1.0,
                "Chiffre_daffaires": revenue,
                "Revenue": revenue,
                "Net_Interest_Income": _scaled_money(inc.get("Net Interest Income")),
                "Provision_for_Loan_Losses": _scaled_money(inc.get("Provision for Loan Losses")),
                "Pretax_Income": _scaled_money(inc.get("Pretax Income")),
                "Resultat_net": net_income,
                "NetIncome": net_income,
                "Basic_EPS": inc.get("EPS (Basic)"),
                "Diluted_EPS": inc.get("EPS (Diluted)"),
                "Dividend_Per_Share": dividend_per_share,
                "Dividendes": dividends,
                "Clean_Dividendes": dividends,
                "Total_Actif": total_assets,
                "Total_Assets": total_assets,
                "Total_Liabilities": _scaled_money(bal.get("Total Liabilities")),
                "Capitaux_propres": equity,
                "Clean_Capitaux_propres": equity,
                "Total_Equity": equity,
                "Total_Debt": total_debt,
                "Cash": cash,
                "Cash_and_Equivalents": cash,
                "NetDebt": net_debt,
                "Loans_Net": _scaled_money(bal.get("Net Loans")),
                "Customer_Deposits": _scaled_money(bal.get("Total Deposits")),
                "Shares_Outstanding": shares,
                "Book_Value_Per_Share": bal.get("Book Value Per Share"),
                "Operating_Cash_Flow": operating_cf,
                "CF_Operating": operating_cf,
                "CF_Investing": _scaled_money(cf.get("Investing Cash Flow")),
                "CF_Financing": _scaled_money(cf.get("Financing Cash Flow")),
                "CF_FX_Effect": _scaled_money(cf.get("Foreign Exchange Rate Adjustments")),
                "Free_Cash_Flow": free_cf,
                "Capital_Expenditures": _scaled_money(cf.get("Capital Expenditures")),
                "Net_Margin": _safe_ratio(net_income, revenue),
                "FCF_Margin": _safe_ratio(free_cf, revenue),
                "Operating_CF_Margin": _safe_ratio(operating_cf, revenue),
                "Asset_Turnover": _safe_ratio(revenue, total_assets),
                "Debt_to_Equity": _safe_ratio(total_debt, equity),
                "NetDebt_to_Equity": _safe_ratio(net_debt, equity),
                "ROE": _safe_ratio(net_income, equity),
                "ROA": _safe_ratio(net_income, total_assets),
                "Dividend_Payout": _safe_ratio(dividends, net_income),
                "Dividend_Coverage": _safe_ratio(net_income, dividends),
            }

        for year in years:
            values = annual[year]
            values["Revenue_Growth"] = _growth(annual, "Revenue", year)
            values["NetIncome_Growth"] = _growth(annual, "NetIncome", year)
            values["OperatingCF_Growth"] = _growth(annual, "Operating_Cash_Flow", year)
            values["FCF_Growth"] = _growth(annual, "Free_Cash_Flow", year)

        return annual
