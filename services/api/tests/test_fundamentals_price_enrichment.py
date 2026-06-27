from core.quant_core.fundamentals.domain import AnnualMetricRow, FundamentalSnapshot, IntegrityCheck, IntegrityReport
from core.quant_core.fundamentals.projection import Projection

from services.api.app.services.fundamentals import _combined_status, _enrich_snapshot_with_market_data, _integrity_with_projection


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
        AnnualMetricRow(symbol="AAA", company_name="Company A", statement_year=2024, metric_name="Resultat_dexploitation", metric_value=800.0),
        AnnualMetricRow(symbol="AAA", company_name="Company A", statement_year=2024, metric_name="EBITDA", metric_value=1_000.0),
        AnnualMetricRow(symbol="AAA", company_name="Company A", statement_year=2024, metric_name="Free_Cash_Flow", metric_value=250.0),
        AnnualMetricRow(symbol="AAA", company_name="Company A", statement_year=2024, metric_name="Dividendes", metric_value=100.0),
        AnnualMetricRow(symbol="AAA", company_name="Company A", statement_year=2024, metric_name="Dettes_de_financement", metric_value=6_000.0),
        AnnualMetricRow(symbol="AAA", company_name="Company A", statement_year=2024, metric_name="Tresorerie_Actif", metric_value=1_000.0),
    ]

    enriched = _enrich_snapshot_with_market_data(
        snapshot,
        price_context={
            "current_price": 12.5,
            "price_as_of": "2026-05-22",
            "price_source": "market_data_store",
            "price_source_provider": "bourse_direct",
            "price_timeframe": "1D",
            "adv20": 750_000.0,
            "shares_outstanding": 1_000.0,
            "shares_source": "stock_master",
        },
        history=history,
    )

    assert enriched.metrics["Current_Price"] == 12.5
    assert enriched.metrics["ADV20"] == 750_000.0
    assert enriched.metrics["Shares_Outstanding"] == 1_000.0
    assert enriched.metrics["MarketCap_Calc"] == 12_500.0
    assert enriched.metrics["PER"] == 25.0
    assert enriched.metrics["Price_to_Book"] == 6.25
    assert enriched.metrics["Price_to_Sales"] == 3.125
    assert enriched.metrics["FCF_Yield"] == 2.0
    assert enriched.metrics["Dividend_Yield"] == 0.8
    assert enriched.metrics["NetDebt"] == 5_000.0
    assert enriched.metrics["EnterpriseValue"] == 17_500.0
    assert enriched.metrics["EV_to_EBITDA"] == 17.5
    assert enriched.metrics["EV_to_EBIT"] == 21.875
    assert enriched.metrics["EV_to_Sales"] == 4.375
    assert enriched.metrics["NetDebt_to_EBITDA"] == 5.0
    assert enriched.metrics["NetDebt_to_Equity"] == 2.5
    assert enriched.coverage["has_current_price"] is True
    assert enriched.coverage["has_adv20"] is True
    assert enriched.coverage["adv20"] == 750_000.0
    assert enriched.coverage["price_source"] == "market_data_store"
    assert enriched.coverage["price_as_of"] == "2026-05-22"


def test_projection_integrity_cannot_upgrade_unavailable_source_checks_to_pass() -> None:
    assert _combined_status("unavailable", "pass") == "unavailable"
    assert _combined_status("unavailable", "derived") == "unavailable"
    assert _combined_status("unavailable", "warn") == "warn"
    assert _combined_status("pass", "warn") == "warn"


def test_projection_integrity_uses_source_checks_not_prior_combined_status() -> None:
    source_report = IntegrityReport(
        symbol="AAA",
        statement_year=2024,
        checks=[
            IntegrityCheck(
                name="bs_balance",
                status="unavailable",
                delta=None,
                rel_delta=None,
                inputs={},
            )
        ],
        overall_status="pass",
        confidence_haircut=0.05,
    )
    projection = Projection(
        symbol="AAA",
        scenario="base",
        start_year=2025,
        forecast_years=1,
        as_of=None,
        statements=[],
        drivers={},
        fcff=[],
        fcfe=[],
        dividends=[],
        book_values=[],
        integrity_checks=[
            IntegrityCheck(
                name="projection_balance",
                status="pass",
                delta=0.0,
                rel_delta=0.0,
                inputs={},
            )
        ],
    )

    combined = _integrity_with_projection(report=source_report, projection=projection, symbol="AAA", statement_year=2024)

    assert combined.overall_status == "unavailable"
    assert combined.confidence_haircut == 0.05
