"""Brief 44 §3.1–§3.3 — through-cycle normalization direction + reclassification.

Covers the dominant downward-bias mechanism (RC-A): a cyclical in a trough year must
be valued on *recovery up to* mid-cycle, not pinned to a trough-dragged flat median;
an elevated cyclical must fade *down* to mid-cycle. Capex must not be double-penalized
via max(D&A%, capex%). Regulated/contracted names must not be classified cyclical.
"""
from __future__ import annotations

import datetime as dt

import pytest

from core.quant_core.fundamentals.domain import AnnualMetricRow, FundamentalSnapshot
from core.quant_core.fundamentals.projection import build_projection
from core.quant_core.fundamentals.valuation import (
    _midcycle_earnings_basis,
    _midcycle_model_warning,
    default_assumptions_for_scenario,
    is_cyclical_or_commodity,
)


def _row(year: int, metric: str, value: float) -> AnnualMetricRow:
    return AnnualMetricRow(
        symbol="CYC",
        company_name="Cyclical Co",
        statement_year=year,
        metric_name=metric,
        metric_value=value,
        as_of_date=dt.date(year + 1, 4, 30),
    )


def _history(margins: dict[int, float], *, da_pct: float = 0.03, capex_pct: float = 0.05) -> list[AnnualMetricRow]:
    """Build a 4-year history with a fixed revenue and per-year EBIT margins."""
    revenue = 100.0
    rows: list[AnnualMetricRow] = []
    for year, margin in margins.items():
        rows.extend(
            [
                _row(year, "Revenue", revenue),
                _row(year, "EBIT", revenue * margin),
                _row(year, "Depreciation_Amortization", revenue * da_pct),
                _row(year, "Capex", revenue * capex_pct),
                _row(year, "Working_Capital", revenue * 0.18),
                _row(year, "NetIncome", revenue * margin * 0.6),
                _row(year, "Dividends_Paid", revenue * 0.02),
                _row(year, "Total_Equity", 200.0),
                _row(year, "Total_Debt", 80.0),
                _row(year, "Cash", 25.0),
                _row(year, "Total_Assets", 330.0),
                _row(year, "Total_Liabilities", 130.0),
                _row(year, "Operating_Cash_Flow", revenue * 0.09),
                _row(year, "Free_Cash_Flow", revenue * 0.04),
            ]
        )
    return rows


def _snapshot() -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol="CYC",
        company_name="Cyclical Co",
        latest_statement_year=2024,
        metrics={"Current_Price": 100.0, "Shares_Outstanding": 10.0, "MarketCap_Calc": 1000.0},
        source={"currency": "MAD"},
        as_of_date=dt.date(2025, 4, 30),
    )


def _ebit_driver(margins: dict[int, float], **kw):
    projection = build_projection(
        _snapshot(), _history(margins, **kw), default_assumptions_for_scenario("base"),
        scenario="base", cyclical=True,
    )
    return projection.drivers["ebit_margin"], projection.drivers["capex_pct"]


def test_trough_cyclical_recovers_up_to_midcycle() -> None:
    # latest margin 6% sits below the 16% mid-cycle median -> recover UP.
    margins = {2021: 0.20, 2022: 0.18, 2023: 0.14, 2024: 0.06}
    driver, _ = _ebit_driver(margins)
    years = sorted(driver.projected_by_year)
    basis = driver.inputs["normalized_earnings_basis"]

    assert basis["recovery_or_fade"] == "recovery"
    assert basis["median_margin"] == pytest.approx(0.16)
    assert basis["latest_margin"] == pytest.approx(0.06)
    # Year 1 starts at the trough, not clipped up to the median...
    assert driver.projected_by_year[years[0]] == pytest.approx(0.06)
    # ...and the path recovers monotonically up toward the mid-cycle anchor.
    assert driver.projected_by_year[years[-1]] == pytest.approx(0.16)
    assert driver.projected_by_year[years[-1]] > driver.projected_by_year[years[0]]


def test_elevated_cyclical_fades_down_to_midcycle() -> None:
    # latest margin 24% sits above the 14% mid-cycle median -> fade DOWN.
    margins = {2021: 0.10, 2022: 0.12, 2023: 0.16, 2024: 0.24}
    driver, _ = _ebit_driver(margins)
    years = sorted(driver.projected_by_year)
    basis = driver.inputs["normalized_earnings_basis"]

    assert basis["recovery_or_fade"] == "fade"
    assert basis["median_margin"] == pytest.approx(0.14)
    assert driver.projected_by_year[years[0]] == pytest.approx(0.24)
    assert driver.projected_by_year[years[-1]] == pytest.approx(0.14)
    assert driver.projected_by_year[years[-1]] < driver.projected_by_year[years[0]]


def test_cyclical_capex_not_double_penalized() -> None:
    # D&A% (10%) exceeds mid-cycle capex% (4%). The old max(D&A, capex) inflated
    # maintenance capex to 10%; the fix must use the mid-cycle median capex (4%).
    margins = {2021: 0.20, 2022: 0.18, 2023: 0.14, 2024: 0.06}
    _, capex = _ebit_driver(margins, da_pct=0.10, capex_pct=0.04)
    assert capex.inputs["maintenance_capex_pct"] == pytest.approx(0.04)
    assert capex.inputs["maintenance_capex_pct"] < capex.inputs["d_and_a_pct"]


def test_regulated_and_contracted_names_are_not_cyclical() -> None:
    # brief 44 §3.1: contracted IPP / regulated distributors must be declassified.
    assert is_cyclical_or_commodity("TQM", "Electricite") is False
    assert is_cyclical_or_commodity("TMA", "Energie") is False
    assert is_cyclical_or_commodity("GAZ", "Gaz") is False
    # The broad energy/oil/gas sector tokens no longer sweep names cyclical.
    assert is_cyclical_or_commodity("XYZ", "Production et distribution d'electricite") is False


def _basis(margins: dict[int, float]):
    return _midcycle_earnings_basis(_snapshot(), _history(margins), sector="Mines", current_price=100.0)


def test_three_year_cyclical_normalizes_but_flags_thin_history() -> None:
    basis = _basis({2022: 0.20, 2023: 0.14, 2024: 0.06})
    assert basis is not None and basis["status"] == "available"
    assert basis["thin_history"] is True
    warning = _midcycle_model_warning({"_cyclical_commodity": True, "_midcycle_earnings_basis": basis})
    assert warning == "midcycle_normalization_thin_history"


def test_two_year_cyclical_is_trough_unnormalized() -> None:
    basis = _basis({2023: 0.14, 2024: 0.06})
    assert basis is not None and basis["status"] == "unavailable"
    assert basis["reason"] == "cyclical_trough_unnormalized"
    warning = _midcycle_model_warning({"_cyclical_commodity": True, "_midcycle_earnings_basis": basis})
    assert warning == "cyclical_trough_unnormalized"


def test_genuine_producers_remain_cyclical() -> None:
    assert is_cyclical_or_commodity("MNG", None) is True   # mining, registry
    assert is_cyclical_or_commodity("LHM", None) is True   # cement, registry
    assert is_cyclical_or_commodity("SID", None) is True   # steel, registry
    assert is_cyclical_or_commodity("ZZZ", "Mines et metaux") is True  # mining sector token
