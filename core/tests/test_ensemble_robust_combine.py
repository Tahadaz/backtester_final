from __future__ import annotations

import pytest

from quant_core.fundamentals import compute_symbol_valuations, compute_valuation_ensemble
from quant_core.fundamentals.domain import AnnualMetricRow, FundamentalSnapshot, ValuationResult

# IC-shrunk ensemble weights committed in ic_ensemble_weights.json (Brief 47/48). Only
# fcff_dcf and relative_multiples carry positive IC; all other models are floored to 0
# weight and kept as diagnostics. See test_method_class_combiner for the full rationale.
IC_W_FCFF_DCF = 0.5419
IC_W_RELATIVE = 0.4581


def _row(model: str, fair_value: float | None, *, confidence: str = "high", family: str = "intrinsic") -> ValuationResult:
    return ValuationResult(
        symbol="ROB",
        scenario="base",
        model=model,
        fair_value=fair_value,
        current_price=100.0,
        upside_pct=None if fair_value is None else fair_value / 100.0 - 1.0,
        confidence=confidence,
        inputs={},
        outputs={},
        warnings=[] if fair_value is not None else ["model_unavailable_for_test"],
        family=family,
        confidence_score={"high": 0.85, "medium": 0.60, "low": 0.35, "unavailable": 0.0}[confidence],
        currency="MAD",
    )


def _snapshot(symbol: str = "BANK") -> FundamentalSnapshot:
    return FundamentalSnapshot(
        symbol=symbol,
        company_name=symbol,
        latest_statement_year=2024,
        metrics={
            "Current_Price": 100.0,
            "MarketCap_Calc": 1_000.0,
            "Shares_Outstanding": 10.0,
            "Price_to_Book": 1.2,
            "PER": 9.0,
            "ROE": 0.14,
            "Dividend_Yield": 0.04,
            "Dividend_Payout": 0.50,
            "FCF_Yield": 0.05,
        },
        source={"currency": "MAD"},
    )


def test_cross_method_market_blowup_routes_headline_to_review() -> None:
    valuations = [
        _row("fcff_dcf", 95.0),
        _row("fcfe_dcf", 100.0),
        _row("ddm", 102.0),
        _row("residual_income", 104.0),
        _row("justified_multiples", 98.0, family="relative"),
        _row("relative_multiples", 10_000.0, family="relative"),
    ]

    ensemble = compute_valuation_ensemble("ROB", "base", valuations)

    assert ensemble.fair_value_base is None
    # IC-weighted mean of the two positive-IC models (fcff_dcf=95, relative=10000).
    assert ensemble.model_dispersion_base == pytest.approx(95.0 * IC_W_FCFF_DCF + 10_000.0 * IC_W_RELATIVE)
    assert ensemble.model_weights["relative_multiples"] > 0.0
    assert "relative_multiples_excluded_cross_model_outlier" not in ensemble.warnings
    assert "headline_review_required_extreme_upside" in ensemble.warnings
    assert "headline_review_weak_method_class_agreement" in ensemble.warnings
    # IC-weighting keeps only the two positive-IC models; the other four are floored to
    # 0 weight and retained as diagnostics, so a coverage-fallback warning is emitted.
    included = {model: weight for model, weight in ensemble.model_weights.items() if weight > 0}
    assert set(included) == {"fcff_dcf", "relative_multiples"}
    assert included["fcff_dcf"] == pytest.approx(IC_W_FCFF_DCF)
    assert included["relative_multiples"] == pytest.approx(IC_W_RELATIVE)
    assert "ic_weight_fallback_for_uncovered_models" in ensemble.warnings


def test_unavailable_zero_model_never_pulls_median_to_zero() -> None:
    valuations = [
        _row("fcff_dcf", None, confidence="unavailable"),
        _row("ddm", 98.0),
        _row("residual_income", 102.0),
        _row("justified_multiples", 100.0, family="relative"),
    ]

    ensemble = compute_valuation_ensemble("ROB", "base", valuations)

    assert ensemble.fair_value_base == pytest.approx(100.0)
    assert "fcff_dcf" not in ensemble.model_weights
    assert ensemble.usable_model_count == 3


def test_financial_sector_excludes_fcff_and_fcfe_from_eligible_set() -> None:
    snapshot = _snapshot()
    history = [
        AnnualMetricRow("BANK", "BANK", 2024, "Revenue", 1_000.0),
        AnnualMetricRow("BANK", "BANK", 2024, "EBIT", 100.0),
        AnnualMetricRow("BANK", "BANK", 2024, "Free_Cash_Flow", 80.0),
        AnnualMetricRow("BANK", "BANK", 2024, "Total_Equity", 700.0),
        AnnualMetricRow("BANK", "BANK", 2024, "Dividendes", 40.0),
    ]

    eligibility, valuations = compute_symbol_valuations(
        snapshot=snapshot,
        history=history,
        peer_snapshots=[snapshot],
        sectors={"BANK": "Banque"},
    )
    ensemble = compute_valuation_ensemble("BANK", "base", valuations)

    assert eligibility["fcff_dcf"]["eligible"] is False
    assert eligibility["fcfe_dcf"]["eligible"] is False
    assert "fcff_dcf" not in ensemble.model_weights
    assert "fcfe_dcf" not in ensemble.model_weights
    assert set(ensemble.model_weights).issubset({"ddm", "residual_income", "justified_multiples", "relative_multiples"})


def test_relative_multiples_are_not_price_anchored_before_ensemble_rejection() -> None:
    valuations = [
        _row("relative_multiples", 500.0, family="relative"),
        _row("justified_multiples", 110.0, family="relative"),
        _row("ddm", 105.0),
        _row("residual_income", 100.0),
    ]

    ensemble = compute_valuation_ensemble("ROB", "base", valuations)

    assert valuations[0].fair_value == 500.0
    # relative_multiples is the only positive-IC model present, so it carries the full
    # IC weight and the (pre-rejection) base equals its un-anchored 500.0 — proving it
    # is not clamped to price before the ensemble rejects the headline.
    assert ensemble.model_dispersion_base == pytest.approx(500.0)
    assert ensemble.fair_value_base is None
    assert "relative_multiples_excluded_cross_model_outlier" not in ensemble.warnings
    assert "headline_review_required_extreme_upside" in ensemble.warnings
