from __future__ import annotations

import pytest

from quant_core.fundamentals.cross_section.production_readiness import (
    LiveTradingNotAuthorized,
    ReadinessGate,
    assert_live_trading_authorized,
    current_repository_readiness,
    evaluate_production_readiness,
)


def test_current_repository_is_fail_closed_for_live_trading():
    report = current_repository_readiness()

    assert report.status == "RESEARCH_ONLY"
    assert report.live_trading_authorized is False
    assert report.blockers
    assert "pit_market_equity" in {gate.gate_id for gate in report.blockers}
    assert "executable_timing" in {gate.gate_id for gate in report.blockers}


def test_live_boundary_raises_with_explicit_blockers():
    with pytest.raises(LiveTradingNotAuthorized, match="pit_market_equity"):
        assert_live_trading_authorized(current_repository_readiness())


def test_all_evidence_gates_must_pass_for_authorization():
    passed = ReadinessGate("a", "required", True, "evidence", "keep current")
    failed = ReadinessGate("b", "required", False, "missing", "remediate")

    assert evaluate_production_readiness((passed,)).live_trading_authorized is True
    assert evaluate_production_readiness((passed, failed)).live_trading_authorized is False


def test_duplicate_or_missing_gates_are_rejected():
    gate = ReadinessGate("same", "required", True, "evidence", "keep current")
    with pytest.raises(ValueError, match="At least one"):
        evaluate_production_readiness(())
    with pytest.raises(ValueError, match="unique"):
        evaluate_production_readiness((gate, gate))


def test_readiness_payload_is_explicit_and_serializable():
    payload = current_repository_readiness().to_dict()

    assert payload["live_trading_authorized"] is False
    assert payload["status"] == "RESEARCH_ONLY"
    assert payload["blocker_ids"]
    assert all("evidence" in gate and "remediation" in gate for gate in payload["gates"])
