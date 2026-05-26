from __future__ import annotations

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
from quant_core.fundamentals.domain import AnnualMetricRow, FundamentalSnapshot


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
    assert fcff.inputs["fcf_growth_source"] == "reported_fcf_growth"
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
