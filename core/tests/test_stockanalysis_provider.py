from __future__ import annotations

import pytest

from quant_core.fundamentals.providers import ProviderUnavailableError
from quant_core.fundamentals.providers.stockanalysis_provider import StockAnalysisFundamentalProvider


def _table(rows: list[list[str]]) -> str:
    body = "\n".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"<html><body><table>{body}</table></body></html>"


def _currency_table(currency: str, rows: list[list[str]]) -> str:
    return f"<html><body><p>Financials in millions {currency}.</p>{_table(rows)}</body></html>"


class _FixtureStockAnalysisProvider(StockAnalysisFundamentalProvider):
    def __init__(self) -> None:
        super().__init__(retries=1, sleep=lambda _seconds: None)

    def _fetch_url(self, url: str) -> str:
        if url.endswith("/financials/"):
            return _table(
                [
                    ["Fiscal Year", "FY 2026", "FY 2025", "FY 2024"],
                    ["Revenue", "-", "17,051", "15,556"],
                    ["Net Income", "-", "3,814", "3,427"],
                    ["Diluted Shares Outstanding", "-", "220", "220"],
                    ["Dividend Per Share", "-", "-", "-"],
                ]
            )
        if url.endswith("/financials/balance-sheet/"):
            return _table(
                [
                    ["Fiscal Year", "FY 2026", "FY 2025", "FY 2024"],
                    ["Cash & Equivalents", "-", "5,957", "6,730"],
                    ["Total Assets", "-", "437,678", "423,279"],
                    ["Total Liabilities", "-", "397,251", "386,464"],
                    ["Shareholders' Equity", "-", "40,426", "36,815"],
                    ["Total Debt", "-", "87,654", "97,592"],
                    ["Net Cash (Debt)", "-", "6,380", "879.69"],
                    ["Total Common Shares Outstanding", "-", "220.28", "220.28"],
                    ["Book Value Per Share", "-", "144.33", "132.24"],
                ]
            )
        if url.endswith("/financials/cash-flow-statement/"):
            return _table(
                [
                    ["Fiscal Year", "FY 2026", "FY 2025", "FY 2024"],
                    ["Operating Cash Flow", "-", "-94.88", "7,009"],
                    ["Investing Cash Flow", "-", "-2,086", "-1,063"],
                    ["Financing Cash Flow", "-", "-3,591", "-555.39"],
                    ["Free Cash Flow", "-", "-2,325", "6,007"],
                ]
            )
        if url.endswith("/dividend/"):
            return _table(
                [
                    ["Ex-Dividend Date", "Cash Amount", "Record Date", "Pay Date"],
                    ["Jul 10, 2025", "4.89795 MAD", "Jul 9, 2025", "Jul 21, 2025"],
                ]
            )
        raise AssertionError(url)


class _ForeignCurrencyStockAnalysisProvider(StockAnalysisFundamentalProvider):
    def __init__(self) -> None:
        super().__init__(retries=1, sleep=lambda _seconds: None)

    def _fetch_url(self, url: str) -> str:
        if url.endswith("/financials/"):
            return _currency_table(
                "TND",
                [
                    ["Fiscal Year", "FY 2024"],
                    ["Revenue", "678.16"],
                    ["Net Income", "47.3"],
                ],
            )
        raise ProviderUnavailableError("missing fixture page")


def test_stockanalysis_provider_normalizes_cbse_tables() -> None:
    workbook = _FixtureStockAnalysisProvider().fetch(
        "BOA",
        display_name="Bank of Africa",
        shares_outstanding=220_281_881,
    )
    snapshot = workbook.latest_snapshots[0]

    assert snapshot.symbol == "BOA"
    assert snapshot.latest_statement_year == 2025
    assert snapshot.metrics["Revenue"] == 17_051_000_000
    assert snapshot.metrics["NetIncome"] == 3_814_000_000
    assert snapshot.metrics["Total_Assets"] == 437_678_000_000
    assert snapshot.metrics["Total_Equity"] == 40_426_000_000
    assert snapshot.metrics["Dividend_Per_Share"] is None
    assert snapshot.metrics["Dividendes"] is None
    assert snapshot.metrics["Shares_Outstanding"] == 220_281_881
    # canonical key; alias NetDebt must be absent
    assert snapshot.metrics["Net_Debt"] == -6_380_000_000
    assert snapshot.latest_statement_year == 2025
    assert len({row.statement_year for row in workbook.annual_metrics}) == 2

    # provider emits raw statement lines only — no inline ratios
    _ABSENT_INLINE_RATIOS = (
        "ROE", "ROA", "Net_Margin", "FCF_Margin", "Operating_CF_Margin",
        "Asset_Turnover", "Debt_to_Equity", "NetDebt_to_Equity", "NetDebt_to_EBITDA",
        "Dividend_Payout", "Dividend_Coverage",
        "Revenue_Growth", "NetIncome_Growth", "OperatingCF_Growth", "FCF_Growth",
    )
    for key in _ABSENT_INLINE_RATIOS:
        assert key not in snapshot.metrics, f"inline ratio {key!r} must not be in provider output"

    # aliases must be absent — provider writes canonical keys only
    _ABSENT_ALIASES = (
        "Chiffre_daffaires", "Clean_Chiffre_daffaires",
        "Resultat_net", "Net_Income", "Clean_Resultat_net",
        "Marge_Brute", "Excedent_brut_dexploitation", "Resultat_dexploitation",
        "DandA", "Dotations_dexploitation", "Charges_Interets",
        "Impots_sur_les_resultats",
        "Clean_Dividendes", "Dividends_Paid",
        "Total_Actif", "Capitaux_propres", "Clean_Capitaux_propres", "Equity",
        "Debt_Total", "Dettes_de_financement",
        "Cash_and_Equivalents", "Tresorerie_Actif",
        "NetDebt",
        "Actif_circulant", "Passif_circulant",
        "Stocks", "Creances_de_lactif_circulant", "Dettes_du_passif_circulant", "Reserves",
        "CF_Operating", "Variation_du_besoin_de_financement_global",
    )
    for key in _ABSENT_ALIASES:
        assert key not in snapshot.metrics, f"alias {key!r} must not be in provider output"

    annual_by_key = {(row.statement_year, row.metric_name): row.metric_value for row in workbook.annual_metrics}
    assert annual_by_key[(2024, "Dividend_Per_Share")] == 4.89795
    assert annual_by_key[(2024, "Dividendes")] == 4.89795 * 220_281_881
    # Null DPS rows are no longer written — the key must not exist
    assert (2025, "Dividend_Per_Share") not in annual_by_key


def test_stockanalysis_provider_rejects_non_mad_statement_currency() -> None:
    with pytest.raises(ProviderUnavailableError, match="TND"):
        _ForeignCurrencyStockAnalysisProvider().fetch("NKL", display_name="Ennakl Automobiles")
