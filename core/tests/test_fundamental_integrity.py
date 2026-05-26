from __future__ import annotations

import pytest

from quant_core.fundamentals.domain import AnnualMetricRow
from quant_core.fundamentals.integrity import build_integrity_report
from quant_core.fundamentals.valuation import compute_symbol_valuations

from test_fundamentals import _valuation_history, _valuation_snapshot


def test_bs_balance_pass_at_zero_delta() -> None:
    report = build_integrity_report("AAA", 2024, {"Total_Assets": 100.0, "Total_Liabilities": 60.0, "Total_Equity": 40.0})
    check = next(item for item in report.checks if item.name == "bs_balance")
    assert check.status == "pass"
    assert check.rel_delta == 0


def test_bs_balance_warn_at_1pct() -> None:
    report = build_integrity_report("AAA", 2024, {"Total_Assets": 100.0, "Total_Liabilities": 59.0, "Total_Equity": 40.0})
    assert next(item for item in report.checks if item.name == "bs_balance").status == "warn"
    assert report.overall_status == "warn"


def test_bs_balance_fail_at_5pct() -> None:
    report = build_integrity_report("AAA", 2024, {"Total_Assets": 100.0, "Total_Liabilities": 55.0, "Total_Equity": 40.0})
    assert next(item for item in report.checks if item.name == "bs_balance").status == "fail"
    assert report.confidence_haircut == pytest.approx(0.30)


def test_cash_tie_out_derived_path() -> None:
    report = build_integrity_report(
        "AAA",
        2024,
        {
            "Cash_and_Equivalents": 120.0,
            "CFS_Beginning_Cash": 100.0,
            "CF_Operating": 50.0,
            "CF_Investing": -20.0,
            "CF_Financing": -10.0,
            "CF_FX_Effect": 0.0,
        },
    )
    check = next(item for item in report.checks if item.name == "cash_tie_out")
    assert check.status == "derived"
    assert "derived" in (check.message or "")


def test_ni_link_unavailable_when_top_of_cfs_missing() -> None:
    report = build_integrity_report("AAA", 2024, {"Resultat_net": 10.0})
    check = next(item for item in report.checks if item.name == "ni_link")
    assert check.status == "unavailable"
    assert "ni_link_unavailable" in (check.message or "")


def test_haircut_applied_to_valuation_confidence_and_proxy_flag() -> None:
    snapshot = _valuation_snapshot()
    history = _valuation_history()
    peers = [snapshot, _valuation_snapshot("P1"), _valuation_snapshot("P2")]
    _base_eligibility, base = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=peers,
        sectors={row.symbol: "Industrie" for row in peers},
    )
    fail_report = build_integrity_report(
        "VAL",
        2024,
        {"Total_Assets": 100.0, "Total_Liabilities": 50.0, "Total_Equity": 40.0},
    )
    _bad_eligibility, bad = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=peers,
        sectors={row.symbol: "Industrie" for row in peers},
        integrity=fail_report,
    )
    base_by_model = {row.model: row for row in base}
    for row in bad:
        if base_by_model[row.model].confidence_score is not None:
            assert row.confidence_score == pytest.approx(base_by_model[row.model].confidence_score * 0.70)
        assert row.is_proxy is True


def test_integrity_does_not_mutate_history() -> None:
    rows = [AnnualMetricRow("AAA", "AAA", 2024, "Total_Assets", 100.0)]
    before = list(rows)
    build_integrity_report("AAA", 2024, {row.metric_name: row.metric_value for row in rows})
    assert rows == before
