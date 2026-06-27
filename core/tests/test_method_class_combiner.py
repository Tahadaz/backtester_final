from __future__ import annotations

import pytest

from quant_core.fundamentals.domain import ValuationResult
from quant_core.fundamentals.valuation import compute_valuation_ensemble

# ── IC-shrunk ensemble weights (committed in ic_ensemble_weights.json, Brief 47/48) ──
# The Phase-1 IC pilot (FY2021-FY2024) found only two models with positive information
# coefficient; every other model is floored to 0 weight and kept as a diagnostic. With
# this config live, the ensemble point estimate is the IC-weighted mean of fcff_dcf and
# relative_multiples — it no longer takes the equal-weight median of class
# representatives. These constants mirror that config so the expected values below are
# self-documenting; update them if the weights are re-estimated (pit_ic_backtest --phase2).
IC_W_FCFF_DCF = 0.5419
IC_W_RELATIVE = 0.4581


def _row(
    model: str,
    fair_value: float,
    *,
    current_price: float = 100.0,
    confidence: str = "medium",
    family: str = "intrinsic",
) -> ValuationResult:
    return ValuationResult(
        symbol="MCC",
        scenario="base",
        model=model,
        fair_value=fair_value,
        current_price=current_price,
        upside_pct=fair_value / current_price - 1.0,
        confidence=confidence,
        inputs={},
        outputs={},
        warnings=[],
        family=family,
        confidence_score=0.60,
        data_quality_score=60.0,
        currency="MAD",
    )


def test_comps_survives_tight_intrinsic_cluster() -> None:
    ensemble = compute_valuation_ensemble(
        "MCC",
        "base",
        [
            _row("fcff_dcf", 100.0),
            _row("fcfe_dcf", 102.0),
            _row("ddm", 104.0),
            _row("residual_income", 106.0),
            _row("relative_multiples", 180.0, family="relative"),
        ],
    )

    assert "relative_multiples_excluded_cross_model_outlier" not in ensemble.warnings
    assert ensemble.model_weights["relative_multiples"] > 0.0
    # IC-weighted mean of the two positive-IC models (fcff_dcf=100, relative=180).
    assert ensemble.fair_value_base == pytest.approx(100.0 * IC_W_FCFF_DCF + 180.0 * IC_W_RELATIVE)


def test_intra_class_outlier_is_still_rejected() -> None:
    ensemble = compute_valuation_ensemble(
        "MCC",
        "base",
        [
            _row("fcff_dcf", 10_000.0),
            _row("fcfe_dcf", 100.0),
            _row("ddm", 102.0),
            _row("residual_income", 104.0),
            _row("relative_multiples", 180.0, family="relative"),
        ],
    )

    assert "fcff_dcf_excluded_cross_model_outlier" in ensemble.warnings
    assert "relative_multiples_excluded_cross_model_outlier" not in ensemble.warnings
    assert ensemble.model_weights["fcff_dcf"] == 0.0
    assert ensemble.model_weights["relative_multiples"] > 0.0


def test_two_class_reconciliation_uses_ic_weights() -> None:
    ensemble = compute_valuation_ensemble(
        "MCC",
        "base",
        [
            _row("fcff_dcf", 100.0),
            _row("fcfe_dcf", 102.0),
            _row("ddm", 104.0),
            _row("residual_income", 106.0),
            _row("relative_multiples", 180.0, family="relative"),
        ],
    )

    pooled_median = 104.0

    # With IC-weighting live the point estimate is the IC-weighted mean of the two
    # positive-IC models (fcff_dcf=100, relative=180) — not the pooled median, and not
    # the equal-weight average of class representatives (which would be 141.5).
    assert ensemble.fair_value_base != pytest.approx(pooled_median)
    assert ensemble.fair_value_base == pytest.approx(100.0 * IC_W_FCFF_DCF + 180.0 * IC_W_RELATIVE)
    assert ensemble.model_dispersion_low == pytest.approx(102.0)
    assert ensemble.model_dispersion_high == pytest.approx(106.0)


def test_extreme_headline_routes_to_review_when_class_agreement_is_weak() -> None:
    ensemble = compute_valuation_ensemble(
        "MCC",
        "base",
        [
            _row("fcff_dcf", 500.0),
            _row("fcfe_dcf", 510.0),
            _row("ddm", 520.0),
            _row("relative_multiples", 40.0, family="relative"),
        ],
    )

    # IC-weighted mean of the two positive-IC models (fcff_dcf=500, relative=40);
    # the headline is still routed to review (fair_value_base is None) below.
    assert ensemble.model_dispersion_base == pytest.approx(500.0 * IC_W_FCFF_DCF + 40.0 * IC_W_RELATIVE)
    assert ensemble.fair_value_base is None
    assert ensemble.upside_pct is None
    assert "headline_review_required_extreme_upside" in ensemble.warnings
    assert "headline_review_weak_method_class_agreement" in ensemble.warnings


def test_equal_weight_fallback_uses_class_representatives(monkeypatch) -> None:
    """When no IC weights are available (config absent, or a stock with no positive-IC
    model), the ensemble falls back to the equal-weight median of class representatives.
    This pins that fallback contract independently of the committed IC config."""
    from quant_core.fundamentals import valuation as _val

    monkeypatch.setattr(_val, "_load_ic_weights", lambda: None)
    ensemble = compute_valuation_ensemble(
        "MCC",
        "base",
        [
            _row("fcff_dcf", 100.0),
            _row("fcfe_dcf", 102.0),
            _row("ddm", 104.0),
            _row("residual_income", 106.0),
            _row("relative_multiples", 180.0, family="relative"),
        ],
    )

    # Equal-weight path = median of class representatives:
    #   intrinsic rep = median(100,102,104,106) = 103 ; market rep = 180
    #   → median([103, 180]) = 141.5
    assert ensemble.fair_value_base == pytest.approx((103.0 + 180.0) / 2.0)
