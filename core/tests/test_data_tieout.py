from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from core.quant_core.fundamentals.integrity import build_data_tieout_report
from services.api.app.services.fundamentals import _latest_symbol_rank


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


# ---------------------------------------------------------------------------
# Stale-cache regression (ATW/BCP/CMA/TQM pattern)
# ---------------------------------------------------------------------------

def test_t2_passes_with_bvps_within_one_pct_of_group_equity_per_share() -> None:
    """Regression: BVPS within the 1% pass threshold must not appear in failed_checks.

    ATW/BCP/CMA/TQM were cached as t2_equity_per_share failures on 2026-06-21 but the
    current _t2_equity_per_share logic passes them.  This test pins that any BVPS within
    the 1% tolerance is verified — stale verdicts that say otherwise are wrong.
    """
    rows = _base_rows()
    # Introduce a 0.5% BVPS rounding gap — well within pass_threshold=1%
    rows["BVPS"] = rows["BVPS"] * 1.005

    report = build_data_tieout_report("STALE_LIKE", 2025, rows, snapshot_year=2025, period_type="annual")

    assert "t2_equity_per_share" not in report.failed_checks
    assert report.status == "verified"


def test_t2_minority_aware_fallback_does_not_fail_on_legitimate_minority_gap() -> None:
    """Regression: when Equity_Group is absent, a plausible implied minority fraction passes t2.

    The minority-aware fallback accepts BVPS*shares < Total_Equity as long as the implied
    minority fraction is below T2_MINORITY_MAX_FRACTION (60%).  A 30% implied minority is
    legitimate — it must NOT produce a t2_equity_per_share failure.
    """
    rows = _base_rows()
    rows.pop("Equity_Group")  # force minority-aware fallback path
    total_equity = rows["Total_Equity"]
    shares = rows["Shares_Outstanding"]
    rows["BVPS"] = (total_equity * 0.70) / shares  # implies 30% minority

    report = build_data_tieout_report("STALE_MINORITY", 2025, rows, snapshot_year=2025, period_type="annual")

    assert "t2_equity_per_share" not in report.failed_checks


# ---------------------------------------------------------------------------
# CMG t6_ni_link — group/total net income basis
# ---------------------------------------------------------------------------

def test_ni_link_passes_when_is_ni_matches_corrected_cfs_no_minority() -> None:
    """CMG Correction A: IS NetIncome (244.01M) is the truth; CFS corrected to match.

    FY2021-2024 show CFS == IS with no minority gap every year; the FY2025 CFS figure of
    252.75M is an anomaly in the lone CFS scrape, not a real minority.  Two independent IS
    sources (stockanalysis + bvc) both report 244.01M.  The fix is to correct
    CFS_Net_Income_Top_Of_CFS to 244.01M, not to invent a minority interest.
    """
    rows = _base_rows()
    rows["Resultat_net"] = 244_010_000.0
    rows["NetIncome"] = 244_010_000.0
    rows.pop("Resultat_net_part_du_groupe")          # no minority / group split
    rows["CFS_Net_Income_Top_Of_CFS"] = 244_010_000.0  # corrected from anomalous 252.75M
    rows["ROE"] = 244_010_000.0 / rows["Total_Equity"]

    report = build_data_tieout_report("CMG_CORRECTED", 2025, rows, snapshot_year=2025, period_type="annual")

    assert "t6_ni_link" not in report.failed_checks


def test_ni_link_fails_when_rnpg_misclassified_as_consolidated_ni() -> None:
    """CMG root cause pinned: storing RNPG as NetIncome while CFS holds consolidated must fail t6.

    This test documents the pre-fix state so a future regression is immediately obvious.
    """
    rows = _base_rows()
    rows["Resultat_net"] = 244_010_000.0
    rows["NetIncome"] = 244_010_000.0
    rows.pop("Resultat_net_part_du_groupe")  # no group metric → only 'total' candidate
    rows["CFS_Net_Income_Top_Of_CFS"] = 252_750_000.0
    rows["ROE"] = 244_010_000.0 / rows["Equity_Group"]

    report = build_data_tieout_report("CMG_UNFIXED", 2025, rows, snapshot_year=2025, period_type="annual")

    assert "t6_ni_link" in report.failed_checks


# ---------------------------------------------------------------------------
# Canonical ranking: verified status must beat proof-rank reingestion (BCI pattern)
# ---------------------------------------------------------------------------

def _fake_snap(status: str | None, has_proof: bool = False) -> SimpleNamespace:
    coverage = {"data_verification": {"status": status}} if status else {}
    source = {"brief42_fy2025_reingestion": True} if has_proof else {}
    return SimpleNamespace(source_json=source, coverage_json=coverage, metrics_json={})


def _fake_import(ts: dt.datetime | None = None) -> SimpleNamespace:
    t = ts or dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    return SimpleNamespace(
        data_source="stockanalysis",
        source_universe=None,
        completed_at=None,
        imported_at=t,
        created_at=t,
    )


def test_verified_import_ranks_above_data_unverified_with_proof_flag() -> None:
    """Regression (BCI): a verified import must rank above data_unverified+proof_rank.

    Before the fix, proof_rank came before status_rank in the tuple, so a
    data_unverified import with brief42_fy2025_reingestion (proof_rank=1) beat a
    verified one (status_rank=2, proof_rank=0).  BCI was stuck on the stale import.
    """
    rank_verified = _latest_symbol_rank(
        _fake_snap("verified"),
        _fake_import(dt.datetime(2026, 6, 18, tzinfo=dt.timezone.utc)),
        stock=None,
        required_complete=1,
    )
    rank_unverified_proof = _latest_symbol_rank(
        _fake_snap("data_unverified", has_proof=True),
        _fake_import(dt.datetime(2026, 5, 26, tzinfo=dt.timezone.utc)),
        stock=None,
        required_complete=1,
    )

    assert rank_verified > rank_unverified_proof, (
        f"verified {rank_verified} must beat unverified+proof {rank_unverified_proof}"
    )
