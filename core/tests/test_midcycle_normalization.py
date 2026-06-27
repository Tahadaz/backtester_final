from __future__ import annotations

import datetime as dt

import pytest

from quant_core.fundamentals import compute_symbol_valuations, default_assumptions_for_scenario
from quant_core.fundamentals.domain import AnnualMetricRow, FundamentalSnapshot
from quant_core.fundamentals.projection import build_projection


def _row(symbol: str, year: int, metric: str, value: float) -> AnnualMetricRow:
    return AnnualMetricRow(
        symbol=symbol,
        company_name=symbol,
        statement_year=year,
        metric_name=metric,
        metric_value=value,
        as_of_date=dt.date(year + 1, 4, 30),
    )


def _snapshot(symbol: str = "MINE") -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol=symbol,
        company_name=symbol,
        latest_statement_year=2024,
        metrics={
            "Current_Price": 100.0,
            "Shares_Outstanding": 10.0,
            "MarketCap_Calc": 1000.0,
            "EnterpriseValue": 1000.0,
            "EV_to_EBITDA": 10.0,
            "PER": 50.0,
            "Price_to_Book": 1.0,
            "ROE": 0.02,
            "Dividend_Payout": 0.30,
            "Dividend_Yield": 0.02,
        },
        as_of_date=dt.date(2025, 4, 30),
    )


def _peer(symbol: str, ev_to_ebitda: float = 8.0) -> FundamentalSnapshot:
    peer = _snapshot(symbol)
    peer.metrics.update({"EV_to_EBITDA": ev_to_ebitda, "PER": 12.0, "Price_to_Book": 1.4})
    return peer


def _history(symbol: str = "MINE", years: tuple[int, ...] = (2020, 2021, 2022, 2023, 2024)) -> list[AnnualMetricRow]:
    ebit_margins = {2020: 0.22, 2021: 0.20, 2022: 0.18, 2023: 0.16, 2024: 0.02}
    ebitda_margins = {2020: 0.30, 2021: 0.28, 2022: 0.26, 2023: 0.24, 2024: 0.10}
    roe = {2020: 0.16, 2021: 0.15, 2022: 0.14, 2023: 0.13, 2024: 0.02}
    rows: list[AnnualMetricRow] = []
    for year in years:
        revenue = 1000.0
        equity = 1000.0
        rows.extend(
            [
                _row(symbol, year, "Revenue", revenue),
                _row(symbol, year, "EBIT", revenue * ebit_margins[year]),
                _row(symbol, year, "EBITDA", revenue * ebitda_margins[year]),
                _row(symbol, year, "Depreciation_Amortization", revenue * (ebitda_margins[year] - ebit_margins[year])),
                _row(symbol, year, "Capex", revenue * 0.07),
                _row(symbol, year, "Working_Capital", revenue * 0.15),
                _row(symbol, year, "NetIncome", equity * roe[year]),
                _row(symbol, year, "ROE", roe[year]),
                _row(symbol, year, "Dividends_Paid", equity * roe[year] * 0.30),
                _row(symbol, year, "Total_Equity", equity),
                _row(symbol, year, "Total_Debt", 0.0),
                _row(symbol, year, "Cash", 0.0),
                _row(symbol, year, "Total_Assets", equity),
                _row(symbol, year, "Total_Liabilities", 0.0),
                _row(symbol, year, "Operating_Cash_Flow", revenue * 0.15),
                _row(symbol, year, "CF_Investing", -revenue * 0.07),
                _row(symbol, year, "Free_Cash_Flow", revenue * 0.08),
            ]
        )
    return rows


def _relative_value(sector: str, *, history: list[AnnualMetricRow]) -> tuple[dict, float, list[str], dict]:
    snapshot = _snapshot()
    peers = [_peer("P1"), _peer("P2")]
    sectors = {row.symbol: sector for row in [snapshot, *peers]}
    eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=[snapshot, *peers],
        sectors=sectors,
        assumptions={"relative_multiple_ratio_mask": 8.0, "peer_min_count": 1.0},
    )
    relative = next(row for row in valuations if row.model == "relative_multiples")
    assert relative.fair_value is not None
    return eligibility, relative.fair_value, relative.warnings, relative.outputs


def test_cyclical_miner_uses_midcycle_earnings_and_capex() -> None:
    history = _history()

    cyclical_eligibility, cyclical_value, cyclical_warnings, outputs = _relative_value("Mines", history=history)
    noncyclical_eligibility, noncyclical_value, noncyclical_warnings, _outputs = _relative_value("Industrie", history=history)

    basis = outputs["normalized_earnings_basis"]
    assert basis["status"] == "available"
    assert basis["window"]["count"] == 5
    assert basis["median_margin"] == pytest.approx(0.18)
    assert basis["median_roe"] == pytest.approx(0.14)
    assert basis["normalized_ebitda"] == pytest.approx(260.0)
    assert "ev_ebitda_uses_midcycle_ebitda" in cyclical_warnings
    assert "ev_ebitda_uses_midcycle_ebitda" not in noncyclical_warnings
    assert cyclical_value > noncyclical_value * 2.0

    projection = build_projection(
        _snapshot(),
        history,
        default_assumptions_for_scenario("base"),
        scenario="base",
        cyclical=True,
    )
    capex_driver = projection.drivers["capex_pct"]
    assert capex_driver.inputs["midcycle_maintenance_capex_pct"] == pytest.approx(0.07)
    assert capex_driver.warning == "midcycle_maintenance_capex_applied"

    projection = cyclical_eligibility["projection"]
    assert projection["available"] is True
    assert cyclical_eligibility["cyclical_commodity"]["eligible"] is True


def test_thin_cyclical_history_normalizes_with_thin_flag() -> None:
    # Brief 44 §3.3: 3 cycle years is enough to normalize, but the result is flagged
    # thin so the combiner can down-weight it and the review gate can see a shared
    # thin-history input. (<3 years routes to cyclical_trough_unnormalized instead.)
    history = _history(years=(2022, 2023, 2024))

    eligibility, value, warnings, outputs = _relative_value("Mines", history=history)

    basis = outputs["normalized_earnings_basis"]
    assert basis["status"] == "available"
    assert basis["thin_history"] is True
    assert basis["window"]["count"] == 3
    assert "midcycle_normalization_thin_history" in warnings
    assert value == pytest.approx(80.0)
    assert eligibility["cyclical_commodity"]["normalized_earnings_basis"]["status"] == "available"

    projection = build_projection(
        _snapshot(),
        history,
        default_assumptions_for_scenario("base"),
        scenario="base",
        cyclical=True,
    )
    # Capex normalizes on a 3-year median too (no longer registry-assumption fallback).
    assert projection.drivers["capex_pct"].inputs["midcycle_maintenance_capex_pct"] == pytest.approx(0.07)
    assert projection.drivers["capex_pct"].warning == "midcycle_maintenance_capex_applied"


def test_non_cyclical_name_does_not_apply_midcycle_normalization() -> None:
    history = _history()

    eligibility, _value, warnings, outputs = _relative_value("Industrie", history=history)

    assert eligibility["cyclical_commodity"]["eligible"] is False
    assert outputs["normalized_earnings_basis"] is None
    assert all(not warning.startswith("midcycle_") for warning in warnings)
