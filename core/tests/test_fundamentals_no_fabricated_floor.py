from __future__ import annotations

from pathlib import Path

from quant_core.fundamentals import DEFAULT_ASSUMPTIONS, compute_symbol_valuations
from quant_core.fundamentals.domain import AnnualMetricRow, FundamentalSnapshot
from quant_core.fundamentals.projection import Projection


def _snapshot(symbol: str = "NFLR") -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol=symbol,
        company_name=symbol,
        latest_statement_year=2024,
        metrics={
            "Current_Price": 100.0,
            "MarketCap_Calc": 1_000.0,
            "Shares_Outstanding": 10.0,
            "Price_to_Book": 1.0,
            "PER": 10.0,
            "ROE": 0.12,
            "Dividend_Yield": 0.04,
        },
        source={"currency": "MAD"},
    )


def _row(symbol: str, year: int, metric: str, value: float) -> AnnualMetricRow:
    return AnnualMetricRow(symbol=symbol, company_name=symbol, statement_year=year, metric_name=metric, metric_value=value)


def _projection(symbol: str, *, fcff: list[float], fcfe: list[float], dividends: list[float] | None = None) -> Projection:
    return Projection(
        symbol=symbol,
        scenario="base",
        start_year=2024,
        forecast_years=5,
        as_of=None,
        statements=[],
        drivers={},
        fcff=fcff,
        fcfe=fcfe,
        dividends=dividends or [4.0] * 5,
        book_values=[100.0] * 5,
        growth_decomposition={"terminal_growth": 0.02},
        warnings=[],
        fallback=False,
    )


def test_nonpositive_intrinsic_models_return_unavailable_not_zero() -> None:
    snapshot = _snapshot()
    history = [
        _row("NFLR", 2024, "Revenue", 1_000.0),
        _row("NFLR", 2024, "EBIT", 100.0),
        _row("NFLR", 2024, "Total_Debt", 1_000_000.0),
        _row("NFLR", 2024, "Cash", 0.0),
        _row("NFLR", 2024, "Free_Cash_Flow", 100.0),
    ]
    assumptions = {
        **DEFAULT_ASSUMPTIONS,
        "terminal_growth": 0.02,
        "terminal_growth_firm": 0.02,
        "terminal_growth_equity": 0.02,
        "wacc": 0.09,
        "cost_of_equity": 0.10,
        "_projection": _projection("NFLR", fcff=[100.0] * 5, fcfe=[-100.0] * 5),
    }

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=[snapshot],
        sectors={"NFLR": "Industrie"},
        assumptions=assumptions,
    )
    by_model = {row.model: row for row in valuations}

    assert by_model["fcff_dcf"].fair_value is None
    assert by_model["fcff_dcf"].confidence == "unavailable"
    assert "fcf_dcf_unavailable_nonpositive_equity_value" in by_model["fcff_dcf"].warnings
    assert by_model["fcfe_dcf"].fair_value is None
    assert by_model["fcfe_dcf"].confidence == "unavailable"
    assert "fcf_dcf_unavailable_nonpositive_equity_value" in by_model["fcfe_dcf"].warnings

    no_growth = _snapshot("DDM0")
    no_growth.metrics["ROE"] = None
    _eligibility, ddm_rows = compute_symbol_valuations(
        snapshot=no_growth,
        history=[],
        peer_snapshots=[no_growth],
        sectors={"DDM0": "Industrie"},
    )
    ddm = next(row for row in ddm_rows if row.model == "ddm")
    assert ddm.fair_value is None
    assert ddm.confidence == "unavailable"
    assert "ddm_nonpositive_value_unavailable" in ddm.warnings

    negative_ri = _snapshot("RI0")
    negative_ri.metrics.update({"ROE": -1.0, "Price_to_Book": 10.0})
    _eligibility, ri_rows = compute_symbol_valuations(
        snapshot=negative_ri,
        history=[],
        peer_snapshots=[negative_ri],
        sectors={"RI0": "Banque"},
    )
    ri = next(row for row in ri_rows if row.model == "residual_income")
    assert ri.fair_value is None
    assert ri.confidence == "unavailable"
    assert "residual_income_nonpositive_value_unavailable" in ri.warnings


def test_one_point_projection_without_peer_median_makes_dcf_unavailable() -> None:
    snapshot = _snapshot("ONEP")
    history = [
        _row("ONEP", 2024, "Revenue", 1_000.0),
        _row("ONEP", 2024, "EBIT", 100.0),
        _row("ONEP", 2024, "Total_Equity", 500.0),
        _row("ONEP", 2024, "Total_Debt", 100.0),
        _row("ONEP", 2024, "Cash", 25.0),
    ]

    eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=[snapshot],
        sectors={"ONEP": "Industrie"},
    )
    by_model = {row.model: row for row in valuations}

    assert eligibility["projection"]["fallback"] is True
    assert eligibility["projection"]["confidence_cap"] == "unavailable"
    assert "projection_driver_unavailable" in eligibility["projection"]["warnings"]
    assert by_model["fcff_dcf"].fair_value is None
    assert by_model["fcff_dcf"].confidence == "unavailable"
    assert by_model["fcfe_dcf"].fair_value is None
    assert by_model["fcfe_dcf"].confidence == "unavailable"


def test_financial_with_proxied_book_value_does_not_get_high_ri_or_ddm_confidence() -> None:
    snapshot = _snapshot("BANK")
    history = [
        _row("BANK", 2024, "Revenue", 1_000.0),
        _row("BANK", 2024, "EBIT", 100.0),
    ]

    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=[snapshot],
        sectors={"BANK": "Banque"},
    )
    by_model = {row.model: row for row in valuations}

    assert by_model["residual_income"].confidence != "high"
    assert by_model["ddm"].confidence != "high"


def test_projection_driver_magic_fallback_literals_are_removed() -> None:
    text = Path("core/quant_core/fundamentals/projection.py").read_text()
    forbidden = (
        "year1_growth = 0.03",
        "default=0.10",
        "_trailing_average(dand_a_series, default=0.0)",
        "_trailing_average(wc_series, default=0.0)",
        'assumptions.get("maintenance_capex_pct"), 0.04',
        'assumptions.get("stable_payout_ratio"), 0.55',
        "default 3.0%",
        "capex_pct_default_no_history",
        "working_capital_pct_default_no_history",
        "d_and_a_pct_default_no_history",
    )
    for needle in forbidden:
        assert needle not in text
