from __future__ import annotations

import datetime as dt

import pytest

from core.quant_core.fundamentals.domain import AnnualMetricRow, FundamentalSnapshot
from core.quant_core.fundamentals.integrity import build_data_tieout_report
from core.quant_core.fundamentals.valuation import _group_basis_roe


def _rows(*, minority_interest: float | None = None) -> dict[str, float]:
    rows = {
        "Total_Assets": 1_000.0,
        "Total_Liabilities": 600.0,
        "Total_Liabilities_And_Equity": 1_000.0,
        "Total_Equity": 400.0,
        "Shares_Outstanding": 10.0,
        "BVPS": 40.0,
        "Resultat_net": 40.0,
        "NetIncome": 40.0,
        "Current_Price": 80.0,
    }
    if minority_interest is not None:
        rows["Minority_Interest"] = minority_interest
    return rows


def _row(metric: str, value: float, year: int = 2025) -> AnnualMetricRow:
    return AnnualMetricRow(
        symbol="NMI",
        company_name="No Minority",
        statement_year=year,
        metric_name=metric,
        metric_value=value,
        as_of_date=dt.date(year + 1, 4, 30),
    )


def test_t4_no_minority_uses_total_equity_basis() -> None:
    report = build_data_tieout_report("NMI", 2025, _rows(), snapshot_year=2025, period_type="annual")

    assert report.status == "verified"
    assert report.recomputed_metrics["ROE"] == pytest.approx(0.10)
    assert report.recomputed_metrics["t4_basis"] == "no_minority_total_equity"
    t4 = next(check for check in report.checks if check.name == "t4_group_basis_roe")
    assert t4.inputs["t4_basis"] == "no_minority_total_equity"


def test_t4_immaterial_minority_still_uses_total_equity_basis() -> None:
    report = build_data_tieout_report("NMI", 2025, _rows(minority_interest=16.0), snapshot_year=2025, period_type="annual")

    assert report.status == "verified"
    assert report.recomputed_metrics["ROE"] == pytest.approx(0.10)
    assert report.recomputed_metrics["t4_basis"] == "no_minority_total_equity"


def test_t4_material_minority_without_group_figures_is_unavailable() -> None:
    report = build_data_tieout_report("MIN", 2025, _rows(minority_interest=60.0), snapshot_year=2025, period_type="annual")

    assert report.status == "data_unverified"
    assert "t4_group_basis_roe" in report.failed_checks
    t4 = next(check for check in report.checks if check.name == "t4_group_basis_roe")
    assert t4.status == "unavailable"
    assert "needs_group_figures" in (t4.message or "")


def test_valuation_group_basis_roe_matches_t4_no_minority_logic() -> None:
    snapshot = FundamentalSnapshot(
        symbol="NMI",
        company_name="No Minority",
        latest_statement_year=2025,
        metrics={"Current_Price": 80.0},
    )
    history = [_row("Resultat_net", 40.0), _row("NetIncome", 40.0), _row("Total_Equity", 400.0)]

    roe, source = _group_basis_roe(snapshot, history)

    assert roe == pytest.approx(0.10)
    assert source == "no_minority_total_equity"
