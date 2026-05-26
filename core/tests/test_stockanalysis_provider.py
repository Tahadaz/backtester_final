from __future__ import annotations

from quant_core.fundamentals.providers.stockanalysis_provider import StockAnalysisFundamentalProvider


def _table(rows: list[list[str]]) -> str:
    body = "\n".join(
        "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"<html><body><table>{body}</table></body></html>"


class _FixtureStockAnalysisProvider(StockAnalysisFundamentalProvider):
    def __init__(self) -> None:
        super().__init__(retries=1, sleep=lambda _seconds: None)

    def _fetch_url(self, url: str) -> str:
        if url.endswith("/financials/"):
            return _table(
                [
                    ["Fiscal Year", "FY 2025", "FY 2024"],
                    ["Revenue", "17,051", "15,556"],
                    ["Net Income", "3,814", "3,427"],
                    ["Diluted Shares Outstanding", "220", "220"],
                    ["Dividend Per Share", "-", "4.898"],
                ]
            )
        if url.endswith("/financials/balance-sheet/"):
            return _table(
                [
                    ["Fiscal Year", "FY 2025", "FY 2024"],
                    ["Cash & Equivalents", "5,957", "6,730"],
                    ["Total Assets", "437,678", "423,279"],
                    ["Total Liabilities", "397,251", "386,464"],
                    ["Shareholders' Equity", "40,426", "36,815"],
                    ["Total Debt", "87,654", "97,592"],
                    ["Net Cash (Debt)", "6,380", "879.69"],
                    ["Total Common Shares Outstanding", "220.28", "220.28"],
                    ["Book Value Per Share", "144.33", "132.24"],
                ]
            )
        if url.endswith("/financials/cash-flow-statement/"):
            return _table(
                [
                    ["Fiscal Year", "FY 2025", "FY 2024"],
                    ["Operating Cash Flow", "-94.88", "7,009"],
                    ["Investing Cash Flow", "-2,086", "-1,063"],
                    ["Financing Cash Flow", "-3,591", "-555.39"],
                    ["Free Cash Flow", "-2,325", "6,007"],
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
    assert snapshot.metrics["Dividend_Per_Share"] == 4.89795
    assert snapshot.metrics["Dividendes"] == 4.89795 * 220_281_881
    assert snapshot.metrics["Shares_Outstanding"] == 220_281_881
    assert snapshot.metrics["NetDebt"] == -6_380_000_000
    assert snapshot.metrics["ROE"] == 3_814_000_000 / 40_426_000_000
    assert "PER" not in snapshot.metrics or snapshot.metrics["PER"] is None
    assert "MarketCap_Calc" not in snapshot.metrics or snapshot.metrics["MarketCap_Calc"] is None
    assert len({row.statement_year for row in workbook.annual_metrics}) == 2
