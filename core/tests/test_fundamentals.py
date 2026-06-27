from __future__ import annotations

from dataclasses import replace
from io import BytesIO

import pytest
from openpyxl import Workbook

from quant_core.fundamentals import (
    DEFAULT_ASSUMPTIONS,
    compute_sensitivity,
    compute_valuation_ensemble,
    compute_symbol_valuations,
    parse_fundamental_workbook,
    score_fundamental_snapshots,
)
from quant_core.fundamentals.domain import AnnualMetricRow, FundamentalSnapshot, IntegrityCheck, IntegrityReport, ValuationResult
from quant_core.fundamentals.projection import build_projection
from quant_core.fundamentals.valuation import _discount_projected_cash_flows, _fcf_growth_input, _monte_carlo_band


def _sample_workbook() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Workbook", "Companies"])
    ws.append(["test", 4])

    ws = wb.create_sheet("Market_Map")
    ws.append(["Company in Long_Data", "Mapped market company", "Ticker", "Shares outstanding", "Match type", "Score / Note", "Source"])
    ws.append(["Company A", "Company A", "AAA", 1000, "exact", "1.00", "test"])
    ws.append(["Company A Duplicate", "Company A", "AAA", 1000, "manual", "duplicate", "test"])
    ws.append(["Company B", "Company B", "BBB", 2000, "exact", "1.00", "test"])
    ws.append(["Company C", "Company C", "CCC", 1500, "exact", "1.00", "test"])

    ws = wb.create_sheet("Factor_Summary_10Y")
    ws.append([
        "Company",
        "Statement_Year",
        "Has_Core_Fundamentals",
        "Chiffre_daffaires",
        "Resultat_net",
        "ROA",
        "Asset_Turnover",
        "Current_Ratio",
        "Debt_to_Equity",
        "PER",
        "ROE",
        "FCF_Margin",
        "Dividend_Yield",
    ])
    ws.append(["Company A", 2023, 1, 9000, 900, 0.06, 0.8, 1.1, 0.7, 10, 0.12, 0.08, 0.03])
    ws.append(["Company A", 2024, 1, 10000, 1000, 0.07, 0.9, 1.2, 0.6, 9, 0.14, 0.09, 0.04])
    ws.append(["Company B", 2024, 1, 8000, 500, 0.03, 0.5, 0.9, 1.5, 18, 0.08, -0.02, None])
    ws.append(["Company C", 2024, 1, 12000, 700, 0.04, 0.7, 1.0, 1.0, 14, 0.10, 0.04, 0.02])

    ws = wb.create_sheet("Factor_Summary_Latest")
    ws.append([
        "Company",
        "Latest Statement Year",
        "MarketCap_Calc",
        "PER",
        "Price_to_Book",
        "Price_to_Sales",
        "EnterpriseValue",
        "EV_to_EBITDA",
        "ROE",
        "ROA",
        "Asset_Turnover",
        "Equity_Multiplier",
        "Net_Margin",
        "Current_Ratio",
        "Debt_to_Equity",
        "Operating_Margin",
        "FCF_Margin",
        "Dividend_Yield",
        "Revenue_Growth",
        "NetIncome_Growth",
    ])
    ws.append(["Company A", 2024, 10000, 9, 1.2, 1.0, 11000, 6, 0.14, 0.07, 0.9, 2.2, 0.10, 1.2, 0.6, 0.16, 0.09, 0.04, 0.07, 0.08])
    ws.append(["Company A Duplicate", 2023, 9000, 10, 1.3, 1.1, 10000, 7, 0.12, 0.06, 0.8, 2.1, 0.09, 1.1, 0.7, 0.15, 0.08, 0.03, 0.05, 0.06])
    ws.append(["Company B", 2024, 20000, 18, 2.0, 2.5, 21000, 12, 0.08, 0.03, 0.5, 2.0, 0.06, 0.9, 1.5, 0.09, -0.02, None, 0.03, 0.02])
    ws.append(["Company C", 2024, 15000, 14, 1.6, 1.4, 17000, 9, 0.10, 0.04, 0.7, 2.1, 0.07, 1.0, 1.0, 0.11, 0.04, 0.02, 0.04, 0.03])

    ws = wb.create_sheet("Free_Cash_Flow")
    ws.append(["Company", 2022, 2023, 2024])
    ws.append(["Company A", 700, 800, 900])
    ws.append(["Company B", -100, -120, -150])
    ws.append(["Company C", 350, 420, 500])

    ws = wb.create_sheet("Dividendes")
    ws.append(["Company", 2023, 2024])
    ws.append(["Company A", 350, 400])
    ws.append(["Company B", None, None])
    ws.append(["Company C", 150, 180])

    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def test_parse_workbook_dedupes_latest_by_symbol() -> None:
    parsed = parse_fundamental_workbook(_sample_workbook())

    assert parsed.summary["mapped_symbol_count"] == 3
    assert parsed.summary["duplicate_symbols"] == ["AAA"]
    assert {row.symbol for row in parsed.latest_snapshots} == {"AAA", "BBB", "CCC"}
    aaa = next(row for row in parsed.latest_snapshots if row.symbol == "AAA")
    assert aaa.company_name == "Company A"
    assert aaa.latest_statement_year == 2024
    assert aaa.metrics["Current_Price"] == 10


def test_parse_workbook_prefers_statement_metrics_over_market_only_future_row() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Workbook", "Companies"])
    ws.append(["test", 1])

    ws = wb.create_sheet("Market_Map")
    ws.append(["Company in Long_Data", "Mapped market company", "Ticker", "Shares outstanding", "Match type", "Score / Note", "Source"])
    ws.append(["Company A", "Company A", "AAA", 1000, "exact", "1.00", "test"])
    ws.append(["Company A Market Row", "Company A", "AAA", 1000, "exact", "1.00", "test"])

    ws = wb.create_sheet("Factor_Summary_10Y")
    ws.append(["Company", "Statement_Year", "Has_Core_Fundamentals", "Chiffre_daffaires", "Resultat_net"])
    ws.append(["Company A", 2025, 1, 10_000, 1_000])

    ws = wb.create_sheet("Factor_Summary_Latest")
    ws.append(["Company", "Latest Statement Year", "MarketCap_Calc", "EnterpriseValue", "PER", "ROE"])
    ws.append(["Company A", 2025, 10_000, 11_000, 10, 0.14])
    ws.append(["Company A Market Row", 2026, 12_000, 12_000, None, None])

    out = BytesIO()
    wb.save(out)
    parsed = parse_fundamental_workbook(out.getvalue())

    aaa = next(row for row in parsed.latest_snapshots if row.symbol == "AAA")
    assert aaa.company_name == "Company A"
    assert aaa.latest_statement_year == 2025
    assert aaa.metrics["PER"] == 10


def test_parse_workbook_does_not_materialize_all_null_statement_years() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Workbook", "Companies"])
    ws.append(["test", 1])

    ws = wb.create_sheet("Market_Map")
    ws.append(["Company in Long_Data", "Mapped market company", "Ticker", "Shares outstanding", "Match type", "Score / Note", "Source"])
    ws.append(["Company A", "Company A", "AAA", 1000, "exact", "1.00", "test"])

    ws = wb.create_sheet("Factor_Summary_10Y")
    ws.append(["Company", "Statement_Year", "Chiffre_daffaires", "Resultat_net"])
    ws.append(["Company A", 2025, 13_700.0, 3_000.0])
    ws.append(["Company A", 2026, None, None])

    ws = wb.create_sheet("Free_Cash_Flow")
    ws.append(["Company", 2025, 2026])
    ws.append(["Company A", -470.0, None])

    ws = wb.create_sheet("Factor_Summary_Latest")
    ws.append(["Company", "Latest Statement Year", "MarketCap_Calc"])
    ws.append(["Company A", 2025, 10_000.0])

    out = BytesIO()
    wb.save(out)
    parsed = parse_fundamental_workbook(out.getvalue())

    years = {row.statement_year for row in parsed.annual_metrics if row.symbol == "AAA"}
    assert years == {2025}


def test_scoring_and_valuation_route_models_by_input_quality() -> None:
    parsed = parse_fundamental_workbook(_sample_workbook())
    snapshots = score_fundamental_snapshots(
        parsed.latest_snapshots,
        parsed.annual_metrics,
        sectors={"AAA": "Industrie", "BBB": "Industrie", "CCC": "Industrie"},
    )
    by_symbol = {row.symbol: row for row in snapshots}
    history = [row for row in parsed.annual_metrics if row.symbol == "AAA"]

    eligibility, valuations = compute_symbol_valuations(
        snapshot=by_symbol["AAA"],
        history=history,
        peer_snapshots=snapshots,
        sectors={"AAA": "Industrie", "BBB": "Industrie", "CCC": "Industrie"},
    )

    assert by_symbol["AAA"].scores["overall"] is not None
    assert by_symbol["AAA"].scores["health"] is not None
    assert "dividend" not in by_symbol["AAA"].scores
    assert by_symbol["AAA"].scores["quality_components"]["raw_percentile"] is not None
    assert by_symbol["AAA"].diagnostics["accounting_discipline"] is not None
    assert by_symbol["AAA"].diagnostics["score_scopes"]["value"] == "sector"
    assert by_symbol["AAA"].diagnostics["piotroski_lite"]["available_points"] >= 5
    assert eligibility["fcff_dcf"]["eligible"] is True
    assert eligibility["ddm"]["eligible"] is True
    assert {row.model for row in valuations} == {
        "relative_multiples",
        "reverse_dcf",
        "fcff_dcf",
        "fcfe_dcf",
        "ddm",
        "residual_income",
        "justified_multiples",
    }
    assert next(row for row in valuations if row.model == "relative_multiples").confidence in {"medium", "high"}
    ensemble = compute_valuation_ensemble("AAA", "base", valuations)
    assert ensemble.usable_model_count >= 3
    assert ensemble.fair_value_base is not None
    assert ensemble.monte_carlo_low is not None


def test_ensemble_excludes_severe_quality_rows_from_headline_weights() -> None:
    rows = [
        ValuationResult(
            symbol="AAA",
            scenario="base",
            model="fcff_dcf",
            fair_value=100_000.0,
            current_price=100.0,
            upside_pct=999.0,
            confidence="low",
            confidence_score=0.20,
            inputs={},
            outputs={},
            warnings=["fcf_model_unreliable_negative_trailing_fcf", "terminal_value_above_75pct_ev"],
        ),
        ValuationResult(
            symbol="AAA",
            scenario="base",
            model="ddm",
            fair_value=2_000.0,
            current_price=100.0,
            upside_pct=19.0,
            confidence="low",
            confidence_score=0.25,
            inputs={},
            outputs={},
            warnings=["dividend_yield_above_plausible_range"],
        ),
        ValuationResult(
            symbol="AAA",
            scenario="base",
            model="relative_multiples",
            fair_value=120.0,
            current_price=100.0,
            upside_pct=0.20,
            confidence="high",
            confidence_score=0.85,
            inputs={},
            outputs={},
            warnings=[],
            family="relative",
        ),
        ValuationResult(
            symbol="AAA",
            scenario="base",
            model="justified_multiples",
            fair_value=130.0,
            current_price=100.0,
            upside_pct=0.30,
            confidence="medium",
            confidence_score=0.60,
            inputs={},
            outputs={},
            warnings=[],
            family="relative",
        ),
    ]

    ensemble = compute_valuation_ensemble("AAA", "base", rows)

    assert "fcff_dcf" not in ensemble.model_weights
    assert "ddm" not in ensemble.model_weights
    assert set(ensemble.model_weights) == {"relative_multiples", "justified_multiples"}
    assert ensemble.fair_value_base is not None
    assert ensemble.fair_value_base < 1_000.0
    assert "fcff_dcf_severe_fcf_quality_warning" in ensemble.warnings
    assert "ddm_severe_dividend_quality_warning" in ensemble.warnings


def test_value_pillar_uses_trailing_average_for_cyclical_per() -> None:
    snapshots = []
    for symbol, per in (("CYCL", 3.0), ("P1", 8.0), ("P2", 9.0), ("P3", 11.0), ("P4", 12.0)):
        row = _valuation_snapshot(symbol)
        row.metrics = {"PER": per, "ROE": 0.12}
        snapshots.append(row)
    history = _rows("CYCL", {2022: {"PER": 10.0, "ROE": 0.12}, 2023: {"PER": 10.0, "ROE": 0.12}, 2024: {"PER": 10.0, "ROE": 0.12}})

    scored = score_fundamental_snapshots(
        snapshots,
        history,
        sectors={row.symbol: "Industrie" for row in snapshots},
    )
    cycl = next(row for row in scored if row.symbol == "CYCL")

    assert cycl.diagnostics["smoothing"]["PER"]["latest"] == pytest.approx(3.0)
    assert cycl.diagnostics["smoothing"]["PER"]["trailing_3y"] == pytest.approx(10.0)
    assert cycl.diagnostics["smoothing"]["PER"]["scoring_input"] == pytest.approx(10.0)
    assert cycl.scores["value"] == pytest.approx(50.0)


def _valuation_snapshot(symbol: str = "VAL") -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol=symbol,
        company_name=symbol,
        latest_statement_year=2024,
        metrics={
            "Current_Price": 100.0,
            "MarketCap_Calc": 1000.0,
            "Shares_Outstanding": 10.0,
            "PER": 10.0,
            "Price_to_Book": 1.25,
            "Price_to_Sales": 1.1,
            "EV_to_EBITDA": 7.0,
            "ROE": 0.16,
            "ROA": 0.08,
            "Dividend_Yield": 0.04,
            "Dividend_Payout": 0.90,
            "Revenue_Growth": 0.12,
            "NetIncome_Growth": 0.10,
            "FCF_Growth": 0.06,
            "FCF_Yield": 0.08,
            "FCF_Margin": 0.12,
            "Current_Ratio": 1.4,
            "Cash_Ratio": 0.4,
            "Debt_to_Equity": 0.8,
            "Interest_Coverage": 5.0,
        },
        source={"currency": "MAD"},
    )


def _valuation_history(symbol: str = "VAL") -> list[AnnualMetricRow]:
    values = {
        2021: {
            "Free_Cash_Flow": 50.0,
            "Total_Debt": 260.0,
            "Cash": 40.0,
            "Interest_Expense": 12.0,
            "Debt_Issuance": 30.0,
            "Debt_Repayment": 15.0,
        },
        2022: {"Free_Cash_Flow": 65.0},
        2023: {"Free_Cash_Flow": 75.0},
        2024: {
            "Free_Cash_Flow": 80.0,
            "Total_Debt": 240.0,
            "Cash": 50.0,
            "Interest_Expense": 10.0,
            "Debt_Issuance": 25.0,
            "Debt_Repayment": 5.0,
            "Dividendes": 40.0,
        },
    }
    return [
        AnnualMetricRow(symbol=symbol, company_name=symbol, statement_year=year, metric_name=metric, metric_value=value)
        for year, metrics in values.items()
        for metric, value in metrics.items()
    ]


def _rows(symbol: str, values: dict[int, dict[str, float]]) -> list[AnnualMetricRow]:
    return [
        AnnualMetricRow(symbol=symbol, company_name=symbol, statement_year=year, metric_name=metric, metric_value=value)
        for year, metrics in values.items()
        for metric, value in metrics.items()
    ]


def _ensemble_row(
    model: str,
    fair_value: float,
    *,
    confidence_score: float = 0.85,
    family: str = "intrinsic",
    warnings: list[str] | None = None,
) -> ValuationResult:
    return ValuationResult(
        symbol="ENS",
        scenario="base",
        model=model,
        fair_value=fair_value,
        current_price=100.0,
        upside_pct=fair_value / 100.0 - 1.0,
        confidence="high",
        inputs={},
        outputs={},
        warnings=warnings or [],
        family=family,
        confidence_score=confidence_score,
        data_quality_score=confidence_score * 100.0,
        currency="MAD",
    )


def test_valuation_correctness_fixes_surface_inputs_and_diagnostics() -> None:
    snapshot = _valuation_snapshot()
    history = _valuation_history()
    peers = [
        snapshot,
        _valuation_snapshot("P1"),
        _valuation_snapshot("P2"),
        _valuation_snapshot("P3"),
    ]

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=peers,
        sectors={row.symbol: "Industrie" for row in peers},
    )
    by_model = {row.model: row for row in valuations}

    fcff = by_model["fcff_dcf"]
    assert fcff.inputs["fcf_growth_source"] == "fcf_series_cagr_blended_reported_fcf_growth"
    assert fcff.inputs["net_debt"] == 190.0
    assert fcff.inputs["net_debt_source"] == "computed_from_debt_minus_cash"

    fcfe = by_model["fcfe_dcf"]
    assert fcfe.is_proxy is False
    assert fcfe.inputs["fcfe_start"] == 93.5

    ddm = by_model["ddm"]
    assert ddm.inputs["growth_source"] == "sustainable_growth_from_roe_retention"
    assert round(ddm.inputs["growth"], 4) == 0.016

    reverse = by_model["reverse_dcf"]
    assert reverse.family == "diagnostic"
    assert reverse.fair_value is None
    assert reverse.outputs["implied_perpetual_growth"] is not None


def test_relative_ev_to_ebitda_uses_net_debt_bridge() -> None:
    snapshot = _valuation_snapshot()
    history = [
        *_valuation_history(),
        AnnualMetricRow("VAL", "VAL", 2024, "EBITDA", 200.0),
    ]
    peers = [snapshot, _valuation_snapshot("P1"), _valuation_snapshot("P2"), _valuation_snapshot("P3")]

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=peers,
        sectors={row.symbol: "Industrie" for row in peers},
    )
    relative = next(row for row in valuations if row.model == "relative_multiples")

    assert relative.outputs["implied_prices"]["EV_to_EBITDA"] == pytest.approx((7.0 * 200.0 - 190.0) / 10.0)
    assert relative.outputs["implied_prices"]["EV_to_EBITDA"] != pytest.approx(snapshot.metrics["Current_Price"])


def test_relative_ev_to_ebitda_skips_when_bridge_inputs_missing() -> None:
    snapshot = _valuation_snapshot()
    peers = [snapshot, _valuation_snapshot("P1"), _valuation_snapshot("P2"), _valuation_snapshot("P3")]

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=[],
        peer_snapshots=peers,
        sectors={row.symbol: "Industrie" for row in peers},
    )
    relative = next(row for row in valuations if row.model == "relative_multiples")

    assert "EV_to_EBITDA" not in relative.outputs["implied_prices"]
    assert "ev_multiple_skipped_missing_bridge" in relative.warnings


def test_sign_flipping_fcf_growth_uses_real_driver_proxy_without_complex_cagr() -> None:
    snapshot = _valuation_snapshot("FLIP")
    for key in ("FCF_Growth", "OperatingCF_Growth", "NetIncome_Growth", "Revenue_Growth"):
        snapshot.metrics.pop(key, None)
    history = _rows(
        "FLIP",
        {
            2021: {"Free_Cash_Flow": 100.0, "Revenue": 1000.0},
            2022: {"Free_Cash_Flow": 75.0, "Revenue": 1100.0},
            2023: {"Free_Cash_Flow": -40.0, "Revenue": 1210.0},
            2024: {"Free_Cash_Flow": -20.0, "Revenue": 1331.0},
        },
    )

    growth, source, is_proxy = _fcf_growth_input(snapshot, history, DEFAULT_ASSUMPTIONS)

    assert isinstance(growth, float)
    assert growth == pytest.approx(0.10)
    assert source == "revenue_series_cagr_proxy"
    assert is_proxy is True


def test_negative_trailing_fcf_fcff_dcf_unavailable_instead_of_zero_when_equity_bridge_negative() -> None:
    snapshot = _valuation_snapshot("CAPEX")
    snapshot.metrics.update(
        {
            "Current_Price": 100.0,
            "Shares_Outstanding": 10.0,
            "MarketCap_Calc": 1_000.0,
            "Price_to_Book": 1.0,
            "ROE": 0.15,
        }
    )
    history = _rows(
        "CAPEX",
        {
            2021: {"Revenue": 1_000.0, "EBIT": 250.0, "Depreciation_Amortization": 50.0, "Capex": 700.0, "Free_Cash_Flow": -500.0},
            2022: {"Revenue": 1_100.0, "EBIT": 275.0, "Depreciation_Amortization": 55.0, "Capex": 770.0, "Free_Cash_Flow": -550.0},
            2023: {"Revenue": 1_200.0, "EBIT": 300.0, "Depreciation_Amortization": 60.0, "Capex": 840.0, "Free_Cash_Flow": -600.0},
            2024: {
                "Revenue": 1_300.0,
                "EBIT": 325.0,
                "Depreciation_Amortization": 65.0,
                "Capex": 910.0,
                "Free_Cash_Flow": -650.0,
                "Working_Capital": 130.0,
                "Total_Debt": 100_000.0,
                "Cash": 0.0,
                "Total_Equity": 1_000.0,
                "Total_Assets": 101_000.0,
                "Total_Liabilities": 100_000.0,
            },
        },
    )
    assumptions = {
        **DEFAULT_ASSUMPTIONS,
        "maintenance_capex_pct": 0.04,
        "terminal_growth": 0.02,
        "terminal_growth_firm": 0.02,
        "wacc": 0.09,
    }
    projection = build_projection(snapshot, history, assumptions, scenario="base")

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=[snapshot],
        assumptions={**assumptions, "_projection": projection},
    )
    fcff = next(row for row in valuations if row.model == "fcff_dcf")

    assert fcff.fair_value is None
    assert fcff.confidence == "unavailable"
    assert "fcf_model_unreliable_negative_trailing_fcf" in fcff.warnings
    assert "fcf_dcf_unavailable_nonpositive_equity_value" in fcff.warnings


def test_justified_pb_uses_trailing_roe_not_spot() -> None:
    snapshot = _valuation_snapshot("ROE")
    snapshot.metrics.update({"Current_Price": 100.0, "Price_to_Book": 1.0, "PER": 20.0, "ROE": 0.30, "Dividend_Payout": 0.50})
    history = _rows("ROE", {2022: {"ROE": 0.15}, 2023: {"ROE": 0.15}, 2024: {"ROE": 0.15}})

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=[snapshot],
        sectors={"ROE": "Industrie"},
        assumptions={"cost_of_equity": 0.12, "terminal_growth": 0.02, "fade_years": 5.0},
    )
    justified = next(row for row in valuations if row.model == "justified_multiples")

    growth = 0.02 + (DEFAULT_ASSUMPTIONS["fade_years"] / 2.0) * ((0.15 * 0.50) - 0.02) / DEFAULT_ASSUMPTIONS["fade_years"]
    expected_pb = (0.15 - growth) / (0.12 - growth)
    spot_growth = 0.02 + (DEFAULT_ASSUMPTIONS["fade_years"] / 2.0) * ((0.30 * 0.50) - 0.02) / DEFAULT_ASSUMPTIONS["fade_years"]
    spot_pb = (0.30 - spot_growth) / (0.12 - spot_growth)

    assert justified.inputs["roe"] == pytest.approx(0.15)
    assert justified.inputs["roe_source"] == "roe_3y_trailing"
    assert justified.outputs["justified_multiples"]["implied_pb"] == pytest.approx(expected_pb)
    assert justified.outputs["justified_multiples"]["implied_pb"] != pytest.approx(spot_pb)


def test_multiple_ratio_masks_filter_relative_and_justified_models() -> None:
    snapshot = _valuation_snapshot("MASK")
    snapshot.metrics.update({"Current_Price": 100.0, "MarketCap_Calc": 1000.0, "Shares_Outstanding": 10.0, "PER": 10.0, "Price_to_Book": 1.0, "Dividend_Payout": 0.50})
    peers = [_valuation_snapshot("P1"), _valuation_snapshot("P2"), _valuation_snapshot("P3")]
    for peer in peers:
        peer.metrics.update({"PER": 14.0, "Price_to_Book": 2.5, "Price_to_Sales": 3.0, "EV_to_EBITDA": 9.0})
    history = _rows(
        "MASK",
        {
            2022: {"NetIncome": 100.0, "ROE": 0.12},
            2023: {"NetIncome": 100.0, "ROE": 0.12},
            2024: {"NetIncome": 100.0, "ROE": 0.12, "EBITDA": 200.0, "Total_Debt": 240.0, "Cash": 50.0},
        },
    )

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=[snapshot, *peers],
        sectors={row.symbol: "Industrie" for row in [snapshot, *peers]},
        assumptions={
            "cost_of_equity": 0.12,
            "terminal_growth": 0.02,
            "relative_multiple_ratio_mask": 1.0,
            "justified_multiple_ratio_mask": 2.0,
        },
    )
    relative = next(row for row in valuations if row.model == "relative_multiples")
    justified = next(row for row in valuations if row.model == "justified_multiples")

    assert relative.inputs["selected_ratio_keys"] == ["PER"]
    assert set(relative.outputs["implied_prices"]) == {"PER"}
    assert relative.fair_value == pytest.approx(relative.outputs["implied_prices"]["PER"])
    assert justified.inputs["selected_ratio_keys"] == ["justified_pe"]
    assert set(justified.outputs["implied_prices"]) == {"justified_pe"}
    assert justified.fair_value == pytest.approx(justified.outputs["implied_prices"]["justified_pe"])


def test_relative_per_target_uses_normalized_earnings() -> None:
    snapshot = _valuation_snapshot("PER")
    snapshot.metrics.update({"Current_Price": 100.0, "MarketCap_Calc": 1000.0, "Shares_Outstanding": 10.0, "PER": 5.0})
    peers = [_valuation_snapshot("P1"), _valuation_snapshot("P2"), _valuation_snapshot("P3")]
    for peer in peers:
        peer.metrics["PER"] = 15.0
    history = _rows("PER", {2022: {"NetIncome": 100.0}, 2023: {"NetIncome": 100.0}, 2024: {"NetIncome": 100.0}})

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=[snapshot, *peers],
        sectors={row.symbol: "Industrie" for row in [snapshot, *peers]},
    )
    relative = next(row for row in valuations if row.model == "relative_multiples")

    assert relative.inputs["own_multiples"]["PER"] == pytest.approx(10.0)
    assert relative.inputs["own_multiple_basis"]["PER"] == "market_cap_over_3y_avg_net_income"
    assert relative.outputs["implied_prices"]["PER"] == pytest.approx(150.0)
    assert relative.outputs["implied_prices"]["PER"] != pytest.approx(300.0)


def test_relative_implied_prices_are_not_price_anchored() -> None:
    snapshot = _valuation_snapshot("CLAMP")
    snapshot.metrics.update({"Current_Price": 100.0, "MarketCap_Calc": 1000.0, "Shares_Outstanding": 10.0, "PER": 10.0})
    peers = [_valuation_snapshot("P1"), _valuation_snapshot("P2"), _valuation_snapshot("P3")]
    for peer in peers:
        peer.metrics["PER"] = 70.0
    history = _rows("CLAMP", {2022: {"NetIncome": 100.0}, 2023: {"NetIncome": 100.0}, 2024: {"NetIncome": 100.0}})

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=[snapshot, *peers],
        sectors={row.symbol: "Industrie" for row in [snapshot, *peers]},
    )
    relative = next(row for row in valuations if row.model == "relative_multiples")

    assert relative.outputs["implied_prices_raw"]["PER"] == pytest.approx(700.0)
    assert relative.outputs["implied_prices"]["PER"] == pytest.approx(700.0)


def test_capex_heavy_relative_multiples_use_normalized_ev_ebitda() -> None:
    snapshot = _valuation_snapshot("CAPEXREL")
    snapshot.metrics.update(
        {
            "Current_Price": 100.0,
            "MarketCap_Calc": 1000.0,
            "Shares_Outstanding": 10.0,
            "PER": 10.0,
            "Price_to_Book": 1.0,
            "Price_to_Sales": 1.0,
            "EV_to_EBITDA": 10.0,
            "EBITDA": 100.0,
        }
    )
    peers = [_valuation_snapshot("P1"), _valuation_snapshot("P2"), _valuation_snapshot("P3")]
    for peer in peers:
        peer.metrics["PER"] = 12.0
        peer.metrics["Price_to_Book"] = 1.2
        peer.metrics["Price_to_Sales"] = 1.2
        peer.metrics["EV_to_EBITDA"] = 12.0
    history = _rows(
        "CAPEXREL",
        {
            2024: {
                "Revenue": 100.0,
                "EBIT": 20.0,
                "EBITDA": 100.0,
                "Free_Cash_Flow": -10.0,
                "Capital_Expenditures": 60.0,
                "Depreciation_Amortization": 5.0,
                "Total_Debt": 100.0,
                "Cash": 0.0,
            }
        },
    )

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=[snapshot, *peers],
        sectors={row.symbol: "Materials" for row in [snapshot, *peers]},
        assumptions={"relative_multiple_ratio_mask": 15.0},
    )
    relative = next(row for row in valuations if row.model == "relative_multiples")

    assert relative.inputs["selected_ratio_keys"] == ["EV_to_EBITDA", "PER", "Price_to_Book", "Price_to_Sales"]
    assert set(relative.outputs["implied_prices"]) == {"EV_to_EBITDA", "PER", "Price_to_Book", "Price_to_Sales"}
    assert "ev_ebitda_uses_normalized_projection_ebitda" in relative.warnings


def test_justified_implied_prices_are_not_price_anchored() -> None:
    snapshot = _valuation_snapshot("JCLAMP")
    snapshot.metrics.update({"Current_Price": 100.0, "Price_to_Book": 0.20, "PER": 1.0, "ROE": 0.40, "Dividend_Payout": 0.50})
    history = _rows("JCLAMP", {2022: {"ROE": 0.40}, 2023: {"ROE": 0.40}, 2024: {"ROE": 0.40}})

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=[snapshot],
        sectors={"JCLAMP": "Industrie"},
        assumptions={"cost_of_equity": 0.12, "terminal_growth": 0.02, "fade_years": 5.0},
    )
    justified = next(row for row in valuations if row.model == "justified_multiples")

    assert justified.outputs["implied_prices_raw"]["justified_pb"] > 250.0
    assert justified.outputs["implied_prices"]["justified_pb"] == pytest.approx(
        justified.outputs["implied_prices_raw"]["justified_pb"]
    )


def test_within_band_implied_prices_are_not_clamped() -> None:
    snapshot = _valuation_snapshot("BAND")
    snapshot.metrics.update({"Current_Price": 100.0, "MarketCap_Calc": 1000.0, "Shares_Outstanding": 10.0, "PER": 10.0})
    peers = [_valuation_snapshot("P1"), _valuation_snapshot("P2"), _valuation_snapshot("P3")]
    for peer in peers:
        peer.metrics["PER"] = 12.0
    history = _rows("BAND", {2022: {"NetIncome": 100.0}, 2023: {"NetIncome": 100.0}, 2024: {"NetIncome": 100.0}})

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=[snapshot, *peers],
        sectors={row.symbol: "Industrie" for row in [snapshot, *peers]},
    )
    relative = next(row for row in valuations if row.model == "relative_multiples")

    assert relative.outputs["implied_prices"]["PER"] == pytest.approx(120.0)
    assert relative.outputs["implied_prices_raw"]["PER"] == pytest.approx(120.0)


def test_terminal_growth_paths_are_model_specific_and_capped_at_risk_free() -> None:
    snapshot = _valuation_snapshot("GT")
    snapshot.metrics.update({"ROE": 0.08, "Dividend_Payout": 0.60, "Revenue_Growth": 0.08})
    history = [
        AnnualMetricRow("GT", "GT", 2023, "Revenue", 1000.0),
        AnnualMetricRow("GT", "GT", 2023, "EBIT", 90.0),
        AnnualMetricRow("GT", "GT", 2023, "Total_Debt", 100.0),
        AnnualMetricRow("GT", "GT", 2023, "Total_Equity", 300.0),
        AnnualMetricRow("GT", "GT", 2023, "Capex", 35.0),
        AnnualMetricRow("GT", "GT", 2023, "Depreciation_Amortization", 10.0),
        AnnualMetricRow("GT", "GT", 2023, "Working_Capital", 20.0),
        AnnualMetricRow("GT", "GT", 2024, "Revenue", 1100.0),
        AnnualMetricRow("GT", "GT", 2024, "EBIT", 100.0),
        AnnualMetricRow("GT", "GT", 2024, "Total_Debt", 100.0),
        AnnualMetricRow("GT", "GT", 2024, "Total_Equity", 333.3333333333),
        AnnualMetricRow("GT", "GT", 2024, "Capex", 40.0),
        AnnualMetricRow("GT", "GT", 2024, "Depreciation_Amortization", 10.0),
        AnnualMetricRow("GT", "GT", 2024, "Working_Capital", 22.5),
        AnnualMetricRow("GT", "GT", 2024, "Free_Cash_Flow", 80.0),
        AnnualMetricRow("GT", "GT", 2024, "Dividendes", 40.0),
    ]

    eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=[snapshot],
        sectors={"GT": "Industrie"},
        assumptions={"risk_free_rate": 0.04, "wacc": 0.08, "cost_of_equity": 0.12, "tax_rate": 0.35},
    )
    by_model = {row.model: row for row in valuations}

    assert by_model["fcff_dcf"].inputs["terminal_growth"] == pytest.approx(0.04)
    assert by_model["fcff_dcf"].inputs["terminal_growth_firm"] == pytest.approx(0.04)
    assert by_model["fcfe_dcf"].inputs["terminal_growth_equity"] == pytest.approx(0.032)
    assert by_model["ddm"].inputs["terminal_growth"] == pytest.approx(0.032)
    assert by_model["fcff_dcf"].inputs["terminal_growth_basis"]["binding_constraint"] == "ceiling"
    assert by_model["fcff_dcf"].outputs["projection"]["growth_decomposition"]["terminal_growth"] == pytest.approx(0.04)
    assert eligibility["terminal_growth"]["firm"]["source"] == "reinvestment_times_roic"
    assert eligibility["terminal_growth"]["equity"]["source"] == "retention_times_roe"


def test_legacy_terminal_growth_override_wins_for_both_paths() -> None:
    snapshot = _valuation_snapshot("GOVR")

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=_valuation_history("GOVR"),
        peer_snapshots=[snapshot],
        sectors={"GOVR": "Industrie"},
        assumptions={"terminal_growth": 0.03, "risk_free_rate": 0.02, "wacc": 0.09, "cost_of_equity": 0.11},
    )
    by_model = {row.model: row for row in valuations}

    assert by_model["fcff_dcf"].inputs["terminal_growth_firm"] == pytest.approx(0.03)
    assert by_model["ddm"].inputs["terminal_growth_equity"] == pytest.approx(0.03)
    assert by_model["fcff_dcf"].inputs["terminal_growth_basis"]["source"] == "legacy_terminal_growth_override"


def test_dcf_terminal_value_defaults_to_full_year_n() -> None:
    dcf = _discount_projected_cash_flows([100.0] * 5, 0.02, 0.08, mid_year=True)
    legacy = _discount_projected_cash_flows([100.0] * 5, 0.02, 0.08, mid_year=True, mid_year_terminal=True)

    assert dcf["periods"] == [0.5, 1.5, 2.5, 3.5, 4.5]
    assert dcf["terminal_period"] == pytest.approx(5.0)
    assert legacy["terminal_period"] == pytest.approx(4.5)
    assert dcf["total_value"] < legacy["total_value"]


def test_correlated_monte_carlo_band_is_wider_than_independent_band() -> None:
    rows = []
    for index, fair_value in enumerate((90.0, 110.0, 130.0)):
        base_row = next(
            row
            for row in compute_symbol_valuations(
                snapshot=_valuation_snapshot(f"MC{index}"),
                history=_valuation_history(f"MC{index}"),
                peer_snapshots=[_valuation_snapshot(f"MC{index}")],
            )[1]
            if row.model == "relative_multiples"
        )
        rows.append((replace(base_row, fair_value=fair_value, confidence="low", confidence_score=0.35), 1.0))

    independent = _monte_carlo_band(rows, 3.0, seed="mc-test", samples=2000, shock_correlation=0.0)
    correlated = _monte_carlo_band(rows, 3.0, seed="mc-test", samples=2000, shock_correlation=0.60)

    assert independent[0] is not None and independent[2] is not None
    assert correlated[0] is not None and correlated[2] is not None
    assert correlated[2] - correlated[0] > independent[2] - independent[0]


def test_ensemble_central_estimate_uses_method_class_representatives() -> None:
    valuations = [
        _ensemble_row("fcff_dcf", 100.0),
        _ensemble_row("residual_income", 110.0),
        _ensemble_row("relative_multiples", 1000.0, family="relative"),
    ]

    ensemble = compute_valuation_ensemble("ENS", "base", valuations)

    # IC weights: fcff_dcf(0.5419) + relative_multiples(0.4581); residual_income IC=0
    # fair_base = 100*0.5419 + 1000*0.4581 = 512.29; extreme upside triggers review
    assert ensemble.fair_value_base is None
    assert ensemble.model_dispersion_base == pytest.approx(100.0 * 0.5419 + 1000.0 * 0.4581, abs=0.5)
    assert ensemble.fair_value_mean is not None
    assert ensemble.fair_value_mean == pytest.approx((100.0 + 110.0 + 1000.0) / 3.0)
    assert ensemble.model_weights["relative_multiples"] > 0.0
    assert "relative_multiples_excluded_cross_model_outlier" not in ensemble.warnings
    assert "headline_review_required_extreme_upside" in ensemble.warnings


def test_relative_family_survivors_are_equal_weighted() -> None:
    valuations = [
        _ensemble_row("fcff_dcf", 100.0),
        _ensemble_row("relative_multiples", 200.0, family="relative"),
        _ensemble_row("justified_multiples", 180.0, family="relative"),
    ]

    ensemble = compute_valuation_ensemble("ENS", "base", valuations)

    # IC weights: fcff_dcf(0.5419) + relative_multiples(0.4581); justified_multiples IC=0
    assert ensemble.model_weights["justified_multiples"] == 0.0
    assert ensemble.model_weights["fcff_dcf"] == pytest.approx(0.5419, abs=1e-4)
    assert ensemble.model_weights["relative_multiples"] == pytest.approx(0.4581, abs=1e-4)


def test_negative_fcf_excludes_fcf_without_weight_boosts() -> None:
    valuations = [
        _ensemble_row("fcff_dcf", 100.0, warnings=["fcf_model_unreliable_negative_trailing_fcf"]),
        _ensemble_row("relative_multiples", 130.0, family="relative"),
        _ensemble_row("justified_multiples", 125.0, family="relative"),
        _ensemble_row("residual_income", 120.0),
        _ensemble_row("ddm", 90.0),
    ]

    ensemble = compute_valuation_ensemble("ENS", "base", valuations)
    relative_weight = ensemble.model_weights["relative_multiples"] + ensemble.model_weights["justified_multiples"]

    # IC weights: among survivors (relative_multiples, justified_multiples, residual_income),
    # only relative_multiples has positive IC → gets full weight; others floored to 0
    assert "fcff_dcf" not in ensemble.model_weights
    assert ensemble.model_weights["ddm"] == 0.0
    assert ensemble.model_weights["relative_multiples"] == pytest.approx(1.0, abs=1e-6)
    assert ensemble.model_weights["justified_multiples"] == 0.0
    assert ensemble.model_weights["residual_income"] == 0.0
    assert relative_weight > 0.25
    assert "fcff_dcf_severe_fcf_quality_warning" in ensemble.warnings
    assert "ddm_excluded_cross_model_outlier" in ensemble.warnings


def test_ensemble_unchanged_when_models_agree() -> None:
    valuations = [
        _ensemble_row("fcff_dcf", 100.0),
        _ensemble_row("residual_income", 101.0),
        _ensemble_row("ddm", 102.0),
    ]

    ensemble = compute_valuation_ensemble("ENS", "base", valuations)

    # IC weights: only fcff_dcf has positive IC; ddm is anti-predictive (IC<0), residual_income IC=0
    assert ensemble.fair_value_base == pytest.approx(100.0)
    assert ensemble.fair_value_mean is not None
    assert abs(ensemble.fair_value_mean - ensemble.fair_value_base) < 2.0


def test_ensemble_confidence_penalized_by_dispersion() -> None:
    valuations = [
        _ensemble_row("fcff_dcf", 174.0),
        _ensemble_row("relative_multiples", 585.0, family="relative"),
    ]

    ensemble = compute_valuation_ensemble("ENS", "base", valuations)

    assert ensemble.model_dispersion_cv is not None
    assert ensemble.dispersion_factor is not None and ensemble.dispersion_factor < 1.0
    assert ensemble.dispersion_factor < 0.40
    assert ensemble.confidence_score is not None and ensemble.confidence_score < 0.60


def test_tight_cluster_confidence_unpenalized() -> None:
    valuations = [
        _ensemble_row("fcff_dcf", 99.0),
        _ensemble_row("residual_income", 100.0),
        _ensemble_row("ddm", 101.0),
    ]

    ensemble = compute_valuation_ensemble("ENS", "base", valuations)

    assert ensemble.dispersion_factor is not None and ensemble.dispersion_factor > 0.98
    assert ensemble.confidence_score == pytest.approx(0.855, abs=0.01)


def test_ddm_prefers_reported_dividend_per_share_over_percent_yield() -> None:
    snapshot = _valuation_snapshot("IAM")
    snapshot.metrics.update(
        {
            "Current_Price": 94.0,
            "MarketCap_Calc": 94.0 * 879_095_340.0,
            "Shares_Outstanding": 879_095_340.0,
            "Dividend_Yield": 1.5211479138920148,
            "Dividend_Payout": 0.1803960964408726,
        }
    )
    history = [
        AnnualMetricRow(
            symbol="IAM",
            company_name="IAM",
            statement_year=2025,
            metric_name="Dividendes",
            metric_value=1_257_000_000.0,
        )
    ]

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=[snapshot],
        sectors={"IAM": "Telecom"},
    )
    ddm = next(row for row in valuations if row.model == "ddm")
    expected_dividend_per_share = 1_257_000_000.0 / 879_095_340.0

    assert abs(ddm.inputs["dividend_per_share"] - expected_dividend_per_share) < 1e-12
    assert ddm.inputs["dividend_source"] == "reported_dividends_per_share"
    assert abs(ddm.inputs["dividend_yield"] - 0.015211479138920148) < 1e-12
    assert ddm.fair_value is not None
    assert ddm.fair_value < 50


def test_ddm_h_model_collapses_to_terminal_gordon_when_growth_equals_terminal() -> None:
    snapshot = _valuation_snapshot("DDM")
    snapshot.metrics.update({"Current_Price": 100.0, "Dividend_Yield": 0.10, "ROE": 0.06, "Dividend_Payout": 0.50})
    assumptions = {"cost_of_equity": 0.105, "terminal_growth": 0.03, "fade_years": 5.0}

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=[],
        peer_snapshots=[snapshot],
        sectors={"DDM": "Industrie"},
        assumptions=assumptions,
    )
    ddm = next(row for row in valuations if row.model == "ddm")

    expected = 10.0 * (1.0 + 0.03) / (0.105 - 0.03)
    assert ddm.fair_value == pytest.approx(expected)


def test_ddm_h_model_lies_between_two_single_stage_gordons() -> None:
    snapshot = _valuation_snapshot("DDM")
    snapshot.metrics.update({"Current_Price": 100.0, "Dividend_Yield": 0.10, "ROE": 0.12, "Dividend_Payout": 0.50})
    assumptions = {"cost_of_equity": 0.105, "terminal_growth": 0.03, "fade_years": 5.0}

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=[],
        peer_snapshots=[snapshot],
        sectors={"DDM": "Industrie"},
        assumptions=assumptions,
    )
    ddm = next(row for row in valuations if row.model == "ddm")

    gordon_terminal = 10.0 * (1.0 + 0.03) / (0.105 - 0.03)
    gordon_sustainable = 10.0 * (1.0 + 0.06) / (0.105 - 0.06)
    assert gordon_terminal < ddm.fair_value < gordon_sustainable


def test_ddm_returns_none_when_cost_le_terminal_growth() -> None:
    snapshot = _valuation_snapshot("DDM")
    snapshot.metrics.update({"Current_Price": 100.0, "Dividend_Yield": 0.10, "ROE": 0.12, "Dividend_Payout": 0.50})

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=[],
        peer_snapshots=[snapshot],
        sectors={"DDM": "Industrie"},
        assumptions={"cost_of_equity": 0.03, "terminal_growth": 0.04},
    )
    ddm = next(row for row in valuations if row.model == "ddm")

    assert ddm.fair_value is None
    assert "cost_of_equity_not_above_terminal_growth" in ddm.warnings


def test_ddm_inputs_expose_fade_years_and_h_factor() -> None:
    snapshot = _valuation_snapshot("DDM")

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=[],
        peer_snapshots=[snapshot],
        sectors={"DDM": "Industrie"},
    )
    ddm = next(row for row in valuations if row.model == "ddm")

    assert ddm.inputs["fade_years"] == int(DEFAULT_ASSUMPTIONS["fade_years"])
    assert ddm.inputs["h_factor"] == pytest.approx(DEFAULT_ASSUMPTIONS["fade_years"] / 2.0)


def test_residual_income_year1_uses_full_roe() -> None:
    snapshot = _valuation_snapshot("RI")
    snapshot.metrics.update({"Current_Price": 100.0, "Price_to_Book": 1.0, "ROE": 0.15, "Dividend_Payout": 0.50})

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=[],
        peer_snapshots=[snapshot],
        sectors={"RI": "Banque"},
        assumptions={"cost_of_equity": 0.105, "fade_years": 5.0},
    )
    ri = next(row for row in valuations if row.model == "residual_income")

    assert ri.outputs["projected_residual_income"][0]["roe"] == pytest.approx(0.15)


def test_residual_income_reaches_zero_spread_at_horizon_end() -> None:
    snapshot = _valuation_snapshot("RI")
    snapshot.metrics.update({"Current_Price": 100.0, "Price_to_Book": 1.0, "ROE": 0.15, "Dividend_Payout": 0.50})

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=[],
        peer_snapshots=[snapshot],
        sectors={"RI": "Banque"},
        assumptions={"cost_of_equity": 0.105, "fade_years": 5.0},
    )
    ri = next(row for row in valuations if row.model == "residual_income")
    last_projection = ri.outputs["projected_residual_income"][-1]

    assert last_projection["roe"] == pytest.approx(0.105)
    assert last_projection["residual_income"] == pytest.approx(0.0)


def test_residual_income_strictly_higher_than_pre_v14_for_high_roe_firms() -> None:
    snapshot = _valuation_snapshot("RI")
    snapshot.metrics.update({"Current_Price": 100.0, "Price_to_Book": 1.0, "ROE": 0.15, "Dividend_Payout": 0.50})

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=[],
        peer_snapshots=[snapshot],
        sectors={"RI": "Banque"},
        assumptions={"cost_of_equity": 0.105, "fade_years": 5.0},
    )
    ri = next(row for row in valuations if row.model == "residual_income")

    pre_v14_fade_from_year1_fair_value = 107.87870731640339
    assert ri.fair_value > pre_v14_fade_from_year1_fair_value
    assert ri.fair_value == pytest.approx(111.73720395034718)


def test_ddm_and_ri_agree_within_15pct_on_clean_inputs() -> None:
    snapshot = _valuation_snapshot("CLEAN")
    snapshot.metrics.update(
        {
            "Current_Price": 100.0,
            "MarketCap_Calc": 1000.0,
            "Shares_Outstanding": 10.0,
            "Dividend_Yield": 0.04,
            "Price_to_Book": 1.5,
            "ROE": 0.15,
            "Dividend_Payout": 0.50,
        }
    )
    history = [AnnualMetricRow("CLEAN", "CLEAN", 2024, "Dividendes", 50.0)]

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=[snapshot],
        sectors={"CLEAN": "Banque"},
        assumptions={"cost_of_equity": 0.105, "terminal_growth": 0.03, "fade_years": 5.0},
    )
    by_model = {row.model: row for row in valuations}
    ddm_fair = by_model["ddm"].fair_value
    ri_fair = by_model["residual_income"].fair_value

    assert ddm_fair is not None
    assert ri_fair is not None
    assert abs(ddm_fair - ri_fair) / max(ddm_fair, ri_fair) <= 0.15


def test_overvaluation_repro_fixture_is_contained() -> None:
    snapshot = _valuation_snapshot("OVR")
    snapshot.metrics.update(
        {
            "Current_Price": 100.0,
            "MarketCap_Calc": 1000.0,
            "Shares_Outstanding": 10.0,
            "PER": 3.0,
            "Price_to_Book": 1.2,
            "Price_to_Sales": 0.5,
            "ROE": 0.275,
            "Dividend_Payout": 0.50,
            "Dividend_Yield": 0.03,
            "FCF_Yield": 0.06,
        }
    )
    history = _rows(
        "OVR",
        {
            2022: {"ROE": 0.18, "NetIncome": 83.0, "Revenue": 2000.0, "Free_Cash_Flow": 55.0, "Total_Debt": 240.0, "Cash": 50.0},
            2023: {"ROE": 0.18, "NetIncome": 83.0, "Revenue": 2050.0, "Free_Cash_Flow": 60.0, "Total_Debt": 240.0, "Cash": 50.0},
            2024: {"ROE": 0.275, "NetIncome": 333.0, "Revenue": 2100.0, "Free_Cash_Flow": 65.0, "Total_Debt": 240.0, "Cash": 50.0},
        },
    )
    peers = [_valuation_snapshot("P1"), _valuation_snapshot("P2"), _valuation_snapshot("P3")]
    for peer in peers:
        peer.metrics.update({"PER": 15.5, "Price_to_Book": 2.0, "Price_to_Sales": 0.8, "EV_to_EBITDA": 7.0})

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=[snapshot, *peers],
        sectors={row.symbol: "Industrie" for row in [snapshot, *peers]},
        assumptions={"cost_of_equity": 0.12, "wacc": 0.10, "terminal_growth": 0.025, "fade_years": 5.0},
    )
    ensemble = compute_valuation_ensemble("OVR", "base", valuations)

    assert ensemble.fair_value_base is not None
    assert ensemble.fair_value_base <= 225.0
    assert ensemble.upside_pct is not None and ensemble.upside_pct <= 1.25
    assert ensemble.confidence_score is not None


def test_low_confidence_extreme_upside_routes_to_review_when_coverage_is_weak() -> None:
    rows = [
        _ensemble_row("fcff_dcf", 600.0, confidence_score=0.05),
        _ensemble_row("fcfe_dcf", 600.0, confidence_score=0.05),
        _ensemble_row("residual_income", 600.0, confidence_score=0.05),
    ]

    ensemble = compute_valuation_ensemble("ENS", "base", rows)

    assert ensemble.fair_value_base is None
    assert ensemble.upside_pct is None
    assert ensemble.model_dispersion_base == pytest.approx(600.0)
    assert ensemble.usable_model_count == 3
    assert "headline_review_required_extreme_upside" in ensemble.warnings
    assert "headline_review_weak_model_coverage" in ensemble.warnings


def test_confident_extreme_upside_routes_to_review_when_coverage_is_weak() -> None:
    rows = [
        _ensemble_row("fcff_dcf", 600.0, confidence_score=0.50),
        _ensemble_row("fcfe_dcf", 600.0, confidence_score=0.50),
        _ensemble_row("residual_income", 600.0, confidence_score=0.50),
    ]

    ensemble = compute_valuation_ensemble("ENS", "base", rows)

    assert ensemble.fair_value_base is None
    assert ensemble.upside_pct is None
    assert ensemble.model_dispersion_base == pytest.approx(600.0)
    assert ensemble.usable_model_count == 3
    assert "headline_review_required_extreme_upside" in ensemble.warnings
    assert "headline_review_weak_model_coverage" in ensemble.warnings


def test_failed_integrity_keeps_headline_target_with_diagnostic() -> None:
    snapshot = _valuation_snapshot("FAIL")
    report = IntegrityReport(
        symbol="FAIL",
        statement_year=2024,
        checks=[
            IntegrityCheck(
                name="balance_sheet_balance",
                status="fail",
                delta=10.0,
                rel_delta=0.10,
                inputs={"assets": 100.0, "liabilities_plus_equity": 90.0},
            )
        ],
        overall_status="fail",
        confidence_haircut=0.30,
    )

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=_valuation_history("FAIL"),
        peer_snapshots=[snapshot, _valuation_snapshot("P1"), _valuation_snapshot("P2"), _valuation_snapshot("P3")],
        sectors={"FAIL": "Industrie", "P1": "Industrie", "P2": "Industrie", "P3": "Industrie"},
        integrity=report,
    )
    ensemble = compute_valuation_ensemble("FAIL", "base", valuations)

    assert ensemble.fair_value_base is not None
    assert ensemble.upside_pct is not None
    assert "integrity_fail_diagnostic" in ensemble.warnings
    assert any("integrity_fail" in warning for row in valuations for warning in row.warnings)


def test_currency_mismatch_blocks_valuation_models() -> None:
    snapshot = _valuation_snapshot()
    snapshot.source["currency"] = "USD"
    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=_valuation_history(),
        peer_snapshots=[snapshot],
        sectors={"VAL": "Industrie"},
    )
    assert all("currency_mismatch" in row.warnings for row in valuations)
    assert compute_valuation_ensemble("VAL", "base", valuations).usable_model_count == 0


def test_sensitivity_returns_matrix() -> None:
    snapshot = _valuation_snapshot()
    history = _valuation_history()
    sensitivity = compute_sensitivity(
        snapshot=snapshot,
        history=history,
        peer_snapshots=[snapshot, _valuation_snapshot("P1"), _valuation_snapshot("P2")],
        sectors={"VAL": "Industrie", "P1": "Industrie", "P2": "Industrie"},
        steps=3,
    )
    assert sensitivity["axis_x"] == "wacc"
    assert len(sensitivity["matrix"]) == 3
    assert len(sensitivity["matrix"][0]) == 3
    assert "model_grids" in sensitivity
    assert "ddm" in sensitivity["model_grids"]
    assert len(sensitivity["model_grids"]["ddm"]["matrix"]) == 3
