"""Brief 44 §4 — reliability-weighted combiner + shared-bias review gate.

The combiner must down-weight low-information results (thin comps, normalization-flagged
DCFs) rather than equal/IC-weighting them blind, and its review gate must fire when a
majority of usable models agree only because they share a flagged input — agreement that
masks a shared bias instead of confirming the number.
"""
from __future__ import annotations

import pytest

from core.quant_core.fundamentals.domain import ValuationResult
from core.quant_core.fundamentals.valuation import compute_valuation_ensemble

# Positive-IC models in the committed ic_ensemble_weights.json (Brief 47/48). With the
# config live the headline is the IC-weighted mean of these two; reliability multiplies
# into those weights without changing them when all inputs are clean.
IC_W_FCFF_DCF = 0.5419
IC_W_RELATIVE = 0.4581


def _row(
    model: str,
    fair_value: float,
    *,
    current_price: float = 100.0,
    confidence: str = "medium",
    family: str = "intrinsic",
    warnings: list[str] | None = None,
) -> ValuationResult:
    return ValuationResult(
        symbol="REL",
        scenario="base",
        model=model,
        fair_value=fair_value,
        current_price=current_price,
        upside_pct=fair_value / current_price - 1.0,
        confidence=confidence,
        inputs={},
        outputs={},
        warnings=list(warnings or []),
        family=family,
        confidence_score=0.60,
        data_quality_score=60.0,
        currency="MAD",
    )


def test_thin_comp_is_down_weighted_relative_to_clean_dcf() -> None:
    # A thin-peer comp (relative_peers_count_below_5) must take less than its pure-IC
    # share; the clean DCF picks up the slack.
    ensemble = compute_valuation_ensemble(
        "REL",
        "base",
        [
            _row("fcff_dcf", 100.0),
            _row("relative_multiples", 180.0, family="relative", warnings=["relative_peers_count_below_5"]),
        ],
    )
    assert ensemble.model_weights["relative_multiples"] < IC_W_RELATIVE
    assert ensemble.model_weights["fcff_dcf"] > IC_W_FCFF_DCF


def test_thin_comp_cannot_swing_headline_as_far() -> None:
    # Same fair values; the only difference is the thin flag. The flagged comp must pull
    # the headline less than a clean comp would.
    clean = compute_valuation_ensemble(
        "REL", "base",
        [_row("fcff_dcf", 100.0), _row("relative_multiples", 180.0, family="relative")],
    )
    thin = compute_valuation_ensemble(
        "REL", "base",
        [
            _row("fcff_dcf", 100.0),
            _row("relative_multiples", 180.0, family="relative", warnings=["relative_peers_count_below_5"]),
        ],
    )
    assert clean.fair_value_base is not None and thin.fair_value_base is not None
    # The high comp (180) is pulled toward the DCF (100) more when it is down-weighted.
    assert thin.fair_value_base < clean.fair_value_base


def test_shared_midcycle_flag_trips_review_warning() -> None:
    # A majority of usable models carry the same midcycle flag -> shared-bias warning.
    ensemble = compute_valuation_ensemble(
        "REL",
        "base",
        [
            _row("fcff_dcf", 95.0, warnings=["midcycle_ebit_margin_applied"]),
            _row("ddm", 98.0, warnings=["midcycle_ebit_margin_applied"]),
            _row("residual_income", 102.0, warnings=["midcycle_ebit_margin_applied"]),
            _row("relative_multiples", 105.0, family="relative"),
        ],
    )
    assert "headline_review_shared_input_bias" in ensemble.warnings


def test_confident_downside_on_shared_bias_routes_to_review() -> None:
    # A ~-65% headline (between the -60% confident band and the -95% extreme floor) built
    # on models sharing a flagged input must not ship as a confident SELL.
    ensemble = compute_valuation_ensemble(
        "REL",
        "base",
        [
            _row("fcff_dcf", 35.0, warnings=["midcycle_ebit_margin_applied"]),
            _row("relative_multiples", 35.0, family="relative", warnings=["midcycle_ebit_margin_applied"]),
            _row("ddm", 35.0, warnings=["midcycle_ebit_margin_applied"]),
        ],
    )
    assert ensemble.fair_value_base is None
    assert "headline_review_confident_downside_low_information" in ensemble.warnings


def test_lone_thin_comp_extreme_headline_routes_to_review() -> None:
    # WAA defect: for an insurer the only positive-IC model is relative_multiples (fcff_dcf
    # is ineligible), so IC-weighting collapses the headline onto that single comp at weight
    # 1.0. When the comp is thin (few peers), prints an EXTREME upside (here +120% vs price
    # 100), AND is far from every zero-weighted intrinsic model, the headline is one
    # low-information data point -> route to review.
    ensemble = compute_valuation_ensemble(
        "INS",
        "base",
        [
            _row("relative_multiples", 220.0, family="relative", warnings=["relative_peers_count_below_5"]),
            _row("ddm", 95.0),
            _row("residual_income", 102.0),
        ],
    )
    assert ensemble.model_weights["relative_multiples"] == pytest.approx(1.0)
    assert ensemble.fair_value_base is None
    assert "headline_review_lone_thin_comp" in ensemble.warnings


def test_lone_well_populated_comp_extreme_headline_is_not_reviewed() -> None:
    # A lone comp that is NOT thin (full peer set) is trusted enough to drive even an
    # extreme headline; only the thin-comp case is the defect, so names like SID
    # (well-populated comp) are spared. Identical to the case above but for the thin flag.
    ensemble = compute_valuation_ensemble(
        "IND",
        "base",
        [
            _row("relative_multiples", 220.0, family="relative"),
            _row("ddm", 95.0),
            _row("residual_income", 102.0),
        ],
    )
    assert ensemble.fair_value_base is not None
    assert "headline_review_lone_thin_comp" not in ensemble.warnings


def test_contained_lone_thin_comp_headline_still_ships() -> None:
    # A thin lone comp whose upside is contained (here +40%, below the lone-comp ceiling)
    # is not extreme enough to block on a single data point — it must still publish, even if
    # it diverges from the intrinsic models (cf. OVR +67% / AAA +52% repro fixtures).
    ensemble = compute_valuation_ensemble(
        "OVR",
        "base",
        [
            _row("relative_multiples", 140.0, family="relative", warnings=["relative_peers_count_below_5"]),
            _row("ddm", 60.0),
            _row("residual_income", 80.0),
        ],
    )
    assert ensemble.fair_value_base is not None
    assert "headline_review_lone_thin_comp" not in ensemble.warnings


def test_extreme_lone_thin_comp_corroborated_by_intrinsic_still_ships() -> None:
    # An extreme thin-comp headline that AGREES with a zero-weighted intrinsic model is
    # corroborated, not a lone bet — it must still publish (nearest-model gap below the
    # band, no review) even above the lone-comp upside ceiling.
    ensemble = compute_valuation_ensemble(
        "COR",
        "base",
        [
            _row("relative_multiples", 210.0, family="relative", warnings=["relative_peers_count_below_5"]),
            _row("ddm", 200.0),
            _row("residual_income", 205.0),
        ],
    )
    assert ensemble.fair_value_base is not None
    assert "headline_review_lone_thin_comp" not in ensemble.warnings


def test_clean_inputs_leave_ic_weights_unchanged() -> None:
    # Regression guard: with no low-information flags, reliability == 1 and the headline
    # weights reduce to the pure IC weights (no behavior change for clean names).
    ensemble = compute_valuation_ensemble(
        "REL", "base",
        [_row("fcff_dcf", 120.0), _row("relative_multiples", 140.0, family="relative")],
    )
    assert ensemble.model_weights["fcff_dcf"] == pytest.approx(IC_W_FCFF_DCF, abs=1e-3)
    assert ensemble.model_weights["relative_multiples"] == pytest.approx(IC_W_RELATIVE, abs=1e-3)


def test_user_defined_weights_override_auto_weighting() -> None:
    # The desk can pin the model weighting explicitly; it takes precedence over IC/reliability.
    ensemble = compute_valuation_ensemble(
        "REL",
        "base",
        [_row("fcff_dcf", 100.0), _row("relative_multiples", 200.0, family="relative")],
        weight_overrides={"fcff_dcf": 0.75, "relative_multiples": 0.25},
    )
    assert "ensemble_user_defined_weights" in ensemble.warnings
    assert ensemble.model_weights["fcff_dcf"] == pytest.approx(0.75)
    assert ensemble.model_weights["relative_multiples"] == pytest.approx(0.25)
    # Headline = 0.75*100 + 0.25*200 = 125.
    assert ensemble.fair_value_base == pytest.approx(125.0)


def test_all_default_ensemble_weights_give_none_override() -> None:
    """Phase A regression gate: all six ensemble_weight_* keys must default to 0.0 in
    DEFAULT_ASSUMPTIONS so _ensemble_weight_overrides_from_assumptions returns None,
    leaving auto (IC / reliability) weighting completely unchanged."""
    from core.quant_core.fundamentals.valuation import (
        DEFAULT_ASSUMPTIONS,
        ENSEMBLE_INTRINSIC_METHOD_MODELS,
        ENSEMBLE_MARKET_METHOD_MODELS,
        _ensemble_weight_overrides_from_assumptions,
    )
    all_models = ENSEMBLE_INTRINSIC_METHOD_MODELS | ENSEMBLE_MARKET_METHOD_MODELS
    for model in all_models:
        key = f"ensemble_weight_{model}"
        assert key in DEFAULT_ASSUMPTIONS, f"missing key: {key}"
        assert DEFAULT_ASSUMPTIONS[key] == 0.0, f"non-zero default for {key}"
    assert _ensemble_weight_overrides_from_assumptions(DEFAULT_ASSUMPTIONS) is None


def test_all_zero_weight_overrides_give_same_ensemble_as_auto() -> None:
    """Regression gate: passing an all-zero weight_overrides dict (derived from
    DEFAULT_ASSUMPTIONS) produces byte-identical output to auto weighting, because
    zero weights are filtered out before the combiner runs."""
    from core.quant_core.fundamentals.valuation import (
        ENSEMBLE_INTRINSIC_METHOD_MODELS,
        ENSEMBLE_MARKET_METHOD_MODELS,
    )
    rows = [_row("fcff_dcf", 100.0), _row("relative_multiples", 200.0, family="relative")]
    auto = compute_valuation_ensemble("REL", "base", rows)
    zero_overrides = {m: 0.0 for m in ENSEMBLE_INTRINSIC_METHOD_MODELS | ENSEMBLE_MARKET_METHOD_MODELS}
    with_zeros = compute_valuation_ensemble("REL", "base", rows, weight_overrides=zero_overrides)
    assert auto.fair_value_base == with_zeros.fair_value_base
    assert auto.model_weights == with_zeros.model_weights
    assert set(auto.warnings) == set(with_zeros.warnings)


def test_user_weights_cannot_resurrect_an_excluded_model() -> None:
    # A weight on a severely-flagged (excluded) model is ignored — overrides apply only to
    # the usable set, so data-quality gates still hold.
    ensemble = compute_valuation_ensemble(
        "REL",
        "base",
        [
            _row("fcff_dcf", 100.0, warnings=["missing_positive_fcf"]),  # severe → excluded
            _row("relative_multiples", 200.0, family="relative"),
            _row("ddm", 120.0),
        ],
        weight_overrides={"fcff_dcf": 0.9, "ddm": 0.1},
    )
    assert ensemble.model_weights.get("fcff_dcf", 0.0) == 0.0
    assert "ensemble_user_defined_weights" in ensemble.warnings
    # Only ddm carried a usable override → it drives the headline.
    assert ensemble.fair_value_base == pytest.approx(120.0)
