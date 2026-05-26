from core.quant_core.fundamentals.domain import AnnualMetricRow, FundamentalSnapshot

from services.api.app.services.fundamentals import _enrich_snapshot_with_market_data


def test_fundamental_snapshot_uses_app_market_price_for_price_dependent_metrics() -> None:
    snapshot = FundamentalSnapshot(
        symbol="AAA",
        company_name="Company A",
        latest_statement_year=2024,
        metrics={},
    )
    history = [
        AnnualMetricRow(symbol="AAA", company_name="Company A", statement_year=2024, metric_name="Resultat_net", metric_value=500.0),
        AnnualMetricRow(symbol="AAA", company_name="Company A", statement_year=2024, metric_name="Total_Equity", metric_value=2_000.0),
        AnnualMetricRow(symbol="AAA", company_name="Company A", statement_year=2024, metric_name="Chiffre_daffaires", metric_value=4_000.0),
        AnnualMetricRow(symbol="AAA", company_name="Company A", statement_year=2024, metric_name="Free_Cash_Flow", metric_value=250.0),
        AnnualMetricRow(symbol="AAA", company_name="Company A", statement_year=2024, metric_name="Dividendes", metric_value=100.0),
    ]

    enriched = _enrich_snapshot_with_market_data(
        snapshot,
        price_context={
            "current_price": 12.5,
            "price_as_of": "2026-05-22",
            "price_source": "market_data_store",
            "price_source_provider": "bourse_direct",
            "price_timeframe": "1D",
            "shares_outstanding": 1_000.0,
            "shares_source": "stock_master",
        },
        history=history,
    )

    assert enriched.metrics["Current_Price"] == 12.5
    assert enriched.metrics["Shares_Outstanding"] == 1_000.0
    assert enriched.metrics["MarketCap_Calc"] == 12_500.0
    assert enriched.metrics["PER"] == 25.0
    assert enriched.metrics["Price_to_Book"] == 6.25
    assert enriched.metrics["Price_to_Sales"] == 3.125
    assert enriched.metrics["FCF_Yield"] == 2.0
    assert enriched.metrics["Dividend_Yield"] == 0.8
    assert enriched.coverage["has_current_price"] is True
    assert enriched.coverage["price_source"] == "market_data_store"
    assert enriched.coverage["price_as_of"] == "2026-05-22"
