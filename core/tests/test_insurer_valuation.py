"""Brief 44 §3.7 — insurer equity-side path: normalized ROE + no-embedded-value flag.

Insurers are valued equity-side (P/B-ROE, P/E, DDM). A one-off spike year (e.g. realized
investment gains) must not inflate the justified P/B; ROE is normalized to the through-cycle
median. The headline carries `insurer_no_embedded_value` so it is read as a book-and-earnings
proxy, not a life embedded-value valuation.
"""
from __future__ import annotations

import datetime as dt

import pytest

from core.quant_core.fundamentals.domain import AnnualMetricRow, FundamentalSnapshot
from core.quant_core.fundamentals.valuation import _roe_basis, compute_symbol_valuations


def _row(symbol: str, year: int, metric: str, value: float) -> AnnualMetricRow:
    return AnnualMetricRow(
        symbol=symbol, company_name=symbol, statement_year=year,
        metric_name=metric, metric_value=value, as_of_date=dt.date(year + 1, 4, 30),
    )


def _snapshot(symbol: str = "WAA") -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol=symbol, company_name=symbol, latest_statement_year=2024,
        metrics={
            "Current_Price": 100.0, "Shares_Outstanding": 10.0, "MarketCap_Calc": 1000.0,
            "Price_to_Book": 1.0, "PER": 12.0, "ROE": 0.30, "Dividend_Payout": 0.30,
        },
        as_of_date=dt.date(2025, 4, 30),
    )


def _history(symbol: str = "WAA") -> list[AnnualMetricRow]:
    # 2024 is a spike year (ROE 30%) vs an ~11% through-cycle median.
    net_income = {2021: 100.0, 2022: 120.0, 2023: 110.0, 2024: 300.0}
    rows: list[AnnualMetricRow] = []
    for year, ni in net_income.items():
        equity = 1000.0
        rows.extend([
            _row(symbol, year, "Revenue", 1500.0),
            _row(symbol, year, "NetIncome", ni),
            _row(symbol, year, "ROE", ni / equity),
            _row(symbol, year, "Total_Equity", equity),
            _row(symbol, year, "Total_Assets", equity),
            _row(symbol, year, "Total_Liabilities", 0.0),
            _row(symbol, year, "Dividends_Paid", ni * 0.30),
        ])
    return rows


def test_insurer_roe_normalized_to_median_caps_spike() -> None:
    history = _history()
    # Without the insurance archetype, the latest group-basis ROE (the 30% spike) is used.
    spot, spot_source = _roe_basis(_snapshot(), history, {})
    assert spot == pytest.approx(0.30)
    # With the insurance archetype, ROE is normalized to the through-cycle median (~11.5%),
    # capping the spike so the justified P/B cannot overshoot.
    normalized, source = _roe_basis(_snapshot(), history, {"_financial_archetype": "insurance"})
    assert source == "insurer_normalized_median_roe"
    assert normalized == pytest.approx(0.115)
    assert normalized < spot


def test_insurer_results_carry_no_embedded_value_flag() -> None:
    snapshot = _snapshot()
    sectors = {"WAA": "Assurance", "P1": "Assurance", "P2": "Assurance"}
    peers = [_snapshot("P1"), _snapshot("P2")]
    _eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=_history(),
        peer_snapshots=[snapshot, *peers],
        sectors=sectors,
        assumptions={"peer_min_count": 1.0},
    )
    equity_side = [
        row for row in valuations
        if row.model in {"justified_multiples", "residual_income", "ddm", "relative_multiples"}
        and row.fair_value is not None
    ]
    assert equity_side, "expected at least one equity-side insurer model to value"
    assert all("insurer_no_embedded_value" in row.warnings for row in equity_side)
    # Insurers must not be valued on EV/EBITDA — the relative model uses P/B + P/E.
    relative = next((row for row in valuations if row.model == "relative_multiples"), None)
    if relative is not None and relative.fair_value is not None:
        assert "EV_to_EBITDA" not in (relative.outputs.get("selected_ratios") or [])
