from __future__ import annotations

import time
from typing import Any

from core.quant_core.fundamentals.domain import (
    AnnualMetricRow,
    CompanyMapping,
    FundamentalQualityIssue,
    FundamentalSnapshot,
    FundamentalWorkbook,
)
from core.quant_core.fundamentals.normalize_yfinance import normalize_yfinance_fundamentals

from . import ProviderUnavailableError


class YfinanceFundamentalProvider:
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
        market_region: str | None = None,
    ) -> FundamentalWorkbook:
        ticker_symbol = provider_symbol or symbol
        last_exc: Exception | None = None
        for attempt in range(self.retries):
            try:
                return self._fetch_once(
                    symbol.upper(),
                    ticker_symbol=ticker_symbol,
                    display_name=display_name,
                    market_region=market_region,
                )
            except Exception as exc:  # yfinance raises broad transport/parser errors.
                last_exc = exc
                if attempt < self.retries - 1:
                    self._sleep(2**attempt)
        raise ProviderUnavailableError(f"yfinance fundamentals unavailable for {symbol}: {last_exc}") from last_exc

    def _fetch_once(
        self,
        symbol: str,
        *,
        ticker_symbol: str,
        display_name: str | None,
        market_region: str | None,
    ) -> FundamentalWorkbook:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise ProviderUnavailableError("yfinance is not installed") from exc

        ticker = yf.Ticker(ticker_symbol)
        financials = getattr(ticker, "financials", None)
        balance_sheet = getattr(ticker, "balance_sheet", None)
        cashflow = getattr(ticker, "cashflow", None)
        info = getattr(ticker, "info", {}) or {}
        normalized = normalize_yfinance_fundamentals(
            symbol=symbol,
            financials=financials,
            balance_sheet=balance_sheet,
            cashflow=cashflow,
            info=info,
        )
        company_name = display_name or normalized.company_name or symbol
        annual_rows = [
            AnnualMetricRow(
                symbol=symbol,
                company_name=company_name,
                statement_year=statement_year,
                metric_name=metric_name,
                metric_value=value,
                raw_metric_name=metric_name,
                source_sheet="yfinance",
                source_field=metric_name,
            )
            for statement_year, metric_name, value in normalized.annual_metrics
        ]
        coverage = {
            "latest_statement_year": normalized.latest_statement_year,
            "metric_count": sum(value is not None for value in normalized.latest_metrics.values()),
            "core_year_count": len({row.statement_year for row in annual_rows}),
            "has_market_cap": normalized.latest_metrics.get("MarketCap_Calc") is not None,
            "has_current_price": normalized.latest_metrics.get("Current_Price") is not None,
            "missing_metrics": normalized.missing_fields,
        }
        quality_issues = [
            FundamentalQualityIssue(
                severity="warning",
                code="yfinance_missing_metric",
                message=f"yfinance did not provide {metric}",
                symbol=symbol,
                metric_name=metric,
                context={"provider_symbol": ticker_symbol},
            )
            for metric in normalized.missing_fields
        ]
        snapshot = FundamentalSnapshot(
            symbol=symbol,
            company_name=company_name,
            latest_statement_year=normalized.latest_statement_year,
            metrics=normalized.latest_metrics,
            coverage=coverage,
            source={
                "data_source": "yfinance",
                "provider_symbol": ticker_symbol,
                "currency": normalized.currency,
                "market_region": market_region,
            },
        )
        mapping = CompanyMapping(
            company_name=company_name,
            mapped_company_name=company_name,
            symbol=symbol,
            match_type="provider_symbol",
            source="yfinance",
            canonical_company_name=company_name,
        )
        return FundamentalWorkbook(
            mappings=[mapping],
            annual_metrics=annual_rows,
            latest_snapshots=[snapshot],
            summary={
                "data_source": "yfinance",
                "symbol": symbol,
                "provider_symbol": ticker_symbol,
                "market_region": market_region,
                "quality_issue_count": len(quality_issues),
            },
            quality_issues=quality_issues,
        )
