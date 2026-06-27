from __future__ import annotations

import pytest

from quant_core.fundamentals import compute_valuation_ensemble
from quant_core.fundamentals.domain import ValuationResult
from quant_core.fundamentals.valuation import _dispersion_stats


def _row(model: str, fair_value: float, *, warnings: list[str] | None = None, is_proxy: bool = False) -> ValuationResult:
    return ValuationResult(
        symbol="CNF",
        scenario="base",
        model=model,
        fair_value=fair_value,
        current_price=100.0,
        upside_pct=fair_value / 100.0 - 1.0,
        confidence="high",
        confidence_score=0.85,
        inputs={"required_inputs": "observed"},
        outputs={},
        warnings=warnings or ["all_required_inputs_observed"],
        family="intrinsic",
        is_proxy=is_proxy,
        currency="MAD",
    )


def test_five_agreeing_observed_models_reach_reachable_confidence() -> None:
    valuations = [
        _row("fcff_dcf", 99.0),
        _row("fcfe_dcf", 100.0),
        _row("ddm", 101.0),
        _row("residual_income", 102.0),
        _row("justified_multiples", 100.5),
    ]

    ensemble = compute_valuation_ensemble("CNF", "base", valuations)

    assert ensemble.usable_model_count == 5
    assert ensemble.model_dispersion_cv is not None
    assert ensemble.model_dispersion_cv < 0.03
    assert ensemble.dispersion_factor is not None
    assert ensemble.dispersion_factor > 0.97
    assert ensemble.confidence_score is not None
    assert ensemble.confidence_score >= 0.6


def test_confidence_improves_with_coverage_when_agreement_and_quality_match() -> None:
    two_model = compute_valuation_ensemble(
        "CNF",
        "base",
        [_row("fcff_dcf", 100.0), _row("fcfe_dcf", 101.0)],
    )
    five_model = compute_valuation_ensemble(
        "CNF",
        "base",
        [
            _row("fcff_dcf", 100.0),
            _row("fcfe_dcf", 101.0),
            _row("ddm", 100.5),
            _row("residual_income", 99.5),
            _row("justified_multiples", 100.2),
        ],
    )

    assert two_model.confidence_score is not None
    assert five_model.confidence_score is not None
    assert five_model.confidence_score > two_model.confidence_score


def test_data_quality_penalizes_proxy_or_peer_filled_inputs() -> None:
    observed = compute_valuation_ensemble(
        "CNF",
        "base",
        [
            _row("fcff_dcf", 100.0),
            _row("fcfe_dcf", 101.0),
            _row("ddm", 100.5),
            _row("residual_income", 99.5),
            _row("justified_multiples", 100.2),
        ],
    )
    proxied = compute_valuation_ensemble(
        "CNF",
        "base",
        [
            _row("fcff_dcf", 100.0, warnings=["revenue_peer_median"], is_proxy=True),
            _row("fcfe_dcf", 101.0, warnings=["capex_proxy"], is_proxy=True),
            _row("ddm", 100.5, warnings=["payout_assumption"]),
            _row("residual_income", 99.5, warnings=["book_value_fallback"]),
            _row("justified_multiples", 100.2, warnings=["roe_peer_median"]),
        ],
    )

    assert observed.confidence_score is not None
    assert proxied.confidence_score is not None
    assert proxied.confidence_score < observed.confidence_score


def test_dispersion_agreement_has_no_legacy_floor() -> None:
    robust_cv, agreement = _dispersion_stats([100.0, 400.0, 700.0])

    assert robust_cv is not None
    assert robust_cv == pytest.approx(1.11195, rel=1e-4)
    assert agreement == 0.0
