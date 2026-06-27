from core.quant_core.fundamentals.domain import AnnualMetricRow, FundamentalSnapshot

from services.api.app.services.fundamentals import _enrich_snapshot_with_market_data


def test_fundamental_snapshot_derives_roe_payout_and_growth_from_history() -> None:
    snapshot = FundamentalSnapshot(
        symbol="MNG",
        company_name="Managem",
        latest_statement_year=2025,
        metrics={"ROE": 0.0, "Revenue_Growth": None, "NetIncome_Growth": None},
    )
    history = [
        AnnualMetricRow(symbol="MNG", company_name="Managem", statement_year=2024, metric_name="Revenue", metric_value=10_000.0),
        AnnualMetricRow(symbol="MNG", company_name="Managem", statement_year=2024, metric_name="NetIncome", metric_value=787.0),
        AnnualMetricRow(symbol="MNG", company_name="Managem", statement_year=2024, metric_name="Total_Equity", metric_value=11_000.0),
        AnnualMetricRow(symbol="MNG", company_name="Managem", statement_year=2024, metric_name="Dividendes", metric_value=500.0),
        AnnualMetricRow(symbol="MNG", company_name="Managem", statement_year=2025, metric_name="Revenue", metric_value=13_700.0),
        AnnualMetricRow(symbol="MNG", company_name="Managem", statement_year=2025, metric_name="NetIncome", metric_value=3_000.0),
        AnnualMetricRow(symbol="MNG", company_name="Managem", statement_year=2025, metric_name="Total_Equity", metric_value=11_500.0),
    ]

    enriched = _enrich_snapshot_with_market_data(snapshot, price_context={}, history=history)

    assert enriched.metrics["ROE"] == 3_000.0 / ((11_000.0 + 11_500.0) / 2.0)
    assert enriched.metrics["Revenue_Growth"] == 0.37
    assert enriched.metrics["NetIncome_Growth"] == (3_000.0 - 787.0) / 787.0
    assert enriched.metrics["Dividend_Payout"] == 500.0 / 3_000.0
    assert enriched.metrics["Dividend_Coverage"] == 3_000.0 / 500.0
