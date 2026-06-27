from __future__ import annotations

import pytest

from core.quant_core.fundamentals.integrity import build_data_tieout_report


def _base_rows() -> dict[str, float]:
    shares = 10_000_000.0
    equity_group = 400_000_000.0
    rnpg = 48_000_000.0
    return {
        "Total_Assets": 1_000_000_000.0,
        "Total_Liabilities": 580_000_000.0,
        "Total_Liabilities_And_Equity": 1_000_000_000.0,
        "Total_Equity": 420_000_000.0,
        "Equity_Group": equity_group,
        "Shares_Outstanding": shares,
        "BVPS": equity_group / shares,
        "Resultat_net": 50_000_000.0,
        "NetIncome": 50_000_000.0,
        "Resultat_net_part_du_groupe": rnpg,
        "ROE": rnpg / equity_group,
        "Current_Price": 80.0,
    }


def test_tieout_verifies_recomputed_raw_lines_and_ignores_unavailable_cash_flow() -> None:
    report = build_data_tieout_report("OK", 2025, _base_rows(), snapshot_year=2025, period_type="annual")

    assert report.status == "verified"
    assert not report.failed_checks
    assert report.recomputed_metrics["ROE"] == pytest.approx(50_000_000.0 / 420_000_000.0)
    assert report.recomputed_metrics["t4_basis"] == "no_minority_total_equity"
    assert any(warning.startswith("t6_cash_tie_out:unavailable") for warning in report.warnings)


def test_lhm_style_bad_equity_extraction_fails_balance_and_plausibility() -> None:
    rows = _base_rows()
    rows.update(
        {
            "Total_Assets": 994_546_000.0,
            "Total_Liabilities": 7_838_247_000.0,
            "Total_Liabilities_And_Equity": 19_994_546_000.0,
            "Total_Equity": 156_299_000.0,
            "Equity_Group": 156_299_000.0,
            "Resultat_net": 2_165_873_000.0,
            "NetIncome": 2_165_873_000.0,
            "Resultat_net_part_du_groupe": 2_165_873_000.0,
            "ROE": 13.857,
        }
    )

    report = build_data_tieout_report("LHM", 2025, rows, snapshot_year=2025, period_type="annual")

    assert report.status == "data_unverified"
    assert "t1_balance_sheet" in report.failed_checks
    assert "t7_plausibility" in report.failed_checks


def test_income_label_mismatch_is_not_silently_accepted() -> None:
    rows = _base_rows()
    rows["NetIncome"] = 1_160_000_000.0
    rows["Resultat_net"] = 500_000.0

    report = build_data_tieout_report("STR", 2025, rows, snapshot_year=2025, period_type="annual")

    assert report.status == "data_unverified"
    assert "t3_income_consistency" in report.failed_checks


def test_group_basis_roe_must_match_rnpg_over_group_equity() -> None:
    rows = _base_rows()
    group_roe = 4_503_361_000.0 / 41_452_033_000.0
    rows.update(
        {
            "Total_Assets": 571_244_210_000.0,
            "Total_Liabilities": 513_288_181_000.0,
            "Total_Liabilities_And_Equity": 571_244_210_000.0,
            "Total_Equity": 57_956_029_000.0,
            "Equity_Group": 41_452_033_000.0,
            "Resultat_net": 5_621_085_000.0,
            "NetIncome": 5_621_085_000.0,
            "Resultat_net_part_du_groupe": 4_503_361_000.0,
            "ROE": 0.0782,
            "Shares_Outstanding": 203_312_473.0,
            "BVPS": 41_452_033_000.0 / 203_312_473.0,
        }
    )

    report = build_data_tieout_report("BCP", 2025, rows, snapshot_year=2025, period_type="annual")

    assert report.status == "verified"
    assert "t4_group_basis_roe" not in report.failed_checks
    assert report.recomputed_metrics["ROE"] == pytest.approx(group_roe)
    assert report.recomputed_metrics["t4_basis"] == "reported_group_basis"


def test_mixed_fiscal_year_or_non_annual_snapshot_fails_t5() -> None:
    rows = _base_rows()
    report = build_data_tieout_report(
        "MIX",
        2025,
        rows,
        snapshot_year=2025,
        metric_years={"Total_Assets": 2024, "Total_Equity": 2025},
        period_type="semiannual",
    )

    assert report.status == "data_unverified"
    assert "t5_single_annual_vintage" in report.failed_checks
