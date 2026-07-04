"""Tests for the triangulated fair-value reference band."""
from __future__ import annotations

from core.quant_core.fundamentals.triangulation import (
    ANCHOR_BROKER,
    ANCHOR_INTRINSIC,
    ANCHOR_MARKET,
    VERDICT_ABOVE,
    VERDICT_BELOW,
    VERDICT_INSUFFICIENT,
    VERDICT_LOWER,
    VERDICT_NO_PRICE,
    VERDICT_UPPER,
    compute_triangulation,
)


def _row(model: str, family: str, fair_value):
    return {"model": model, "family": family, "fair_value": fair_value}


# family labels deliberately mimic the drifted DB vintages ("valuation",
# "relative", ...) — classification must key on model names, not family.
FULL_SET = [
    _row("fcff_dcf", "valuation", 80.0),
    _row("ddm", "intrinsic", 100.0),
    _row("residual_income", "valuation", 120.0),
    _row("justified_multiples", "relative", 160.0),  # intrinsic method class
    _row("relative_multiples", "valuation", 140.0),  # market method class
    _row("reverse_dcf", "intrinsic", 999.0),  # diagnostic → must be ignored
]


class TestAnchors:
    def test_three_anchor_classes(self):
        result = compute_triangulation(FULL_SET, 130.0, broker_target=180.0)
        names = [a.name for a in result.anchors]
        assert names == [ANCHOR_INTRINSIC, ANCHOR_MARKET, ANCHOR_BROKER]

    def test_intrinsic_anchor_is_median_by_model_class(self):
        result = compute_triangulation(FULL_SET, 130.0, broker_target=180.0)
        intrinsic = result.anchors[0]
        # justified_multiples belongs to the intrinsic method class despite
        # its "relative" family label: median(80, 100, 120, 160) = 110
        assert intrinsic.value == 110.0
        assert intrinsic.n_models == 4
        assert "justified_multiples" in intrinsic.models

    def test_market_anchor_is_relative_multiples_only(self):
        result = compute_triangulation(FULL_SET, 130.0, broker_target=180.0)
        market = result.anchors[1]
        assert market.value == 140.0
        assert market.models == ("relative_multiples",)

    def test_reverse_dcf_excluded_despite_intrinsic_family_label(self):
        result = compute_triangulation(FULL_SET, 130.0, broker_target=180.0)
        assert result.band_high == 180.0  # broker, not reverse_dcf's 999
        for anchor in result.anchors:
            assert "reverse_dcf" not in anchor.models

    def test_non_positive_and_missing_values_ignored(self):
        rows = [
            _row("fcff_dcf", "intrinsic", None),
            _row("ddm", "intrinsic", -5.0),
            _row("relative_multiples", "market", 100.0),
        ]
        result = compute_triangulation(rows, 90.0, broker_target=110.0)
        assert "no_intrinsic_anchor" in result.warnings
        assert [a.name for a in result.anchors] == [ANCHOR_MARKET, ANCHOR_BROKER]


class TestBandAndVerdict:
    def test_band_bounds(self):
        result = compute_triangulation(FULL_SET, 130.0, broker_target=180.0)
        assert result.band_low == 110.0   # intrinsic median
        assert result.band_high == 180.0  # broker
        assert result.band_mid == 140.0   # median(110, 140, 180)

    def test_price_below_band(self):
        result = compute_triangulation(FULL_SET, 50.0, broker_target=180.0)
        assert result.verdict == VERDICT_BELOW
        assert result.price_position == 0.0

    def test_price_above_band(self):
        result = compute_triangulation(FULL_SET, 500.0, broker_target=180.0)
        assert result.verdict == VERDICT_ABOVE
        assert result.price_position == 1.0

    def test_price_in_lower_half(self):
        result = compute_triangulation(FULL_SET, 120.0, broker_target=180.0)
        assert result.verdict == VERDICT_LOWER
        assert 0.0 < result.price_position <= 0.5

    def test_price_in_upper_half(self):
        result = compute_triangulation(FULL_SET, 170.0, broker_target=180.0)
        assert result.verdict == VERDICT_UPPER
        assert 0.5 < result.price_position < 1.0

    def test_no_price(self):
        result = compute_triangulation(FULL_SET, None, broker_target=180.0)
        assert result.verdict == VERDICT_NO_PRICE
        assert result.price_position is None
        assert result.band_low is not None


class TestDegradedInputs:
    def test_single_anchor_is_insufficient(self):
        rows = [_row("relative_multiples", "market", 100.0)]
        result = compute_triangulation(rows, 90.0)
        assert result.verdict == VERDICT_INSUFFICIENT
        assert result.band_low is None
        assert len(result.anchors) == 1

    def test_two_anchors_publish_band(self):
        rows = [
            _row("ddm", "intrinsic", 80.0),
            _row("relative_multiples", "market", 120.0),
        ]
        result = compute_triangulation(rows, 100.0)
        assert result.verdict == VERDICT_LOWER
        assert result.band_low == 80.0
        assert result.band_high == 120.0
        assert "no_broker_anchor" in result.warnings

    def test_single_model_intrinsic_warning(self):
        rows = [
            _row("ddm", "intrinsic", 80.0),
            _row("relative_multiples", "market", 120.0),
        ]
        result = compute_triangulation(rows, 100.0)
        assert "single_model_intrinsic_anchor" in result.warnings

    def test_zero_broker_target_rejected(self):
        rows = [
            _row("ddm", "intrinsic", 80.0),
            _row("relative_multiples", "market", 120.0),
        ]
        result = compute_triangulation(rows, 100.0, broker_target=0.0)
        assert "no_broker_anchor" in result.warnings

    def test_unknown_model_uses_family_fallback(self):
        rows = [
            _row("some_future_model", "relative", 90.0),
            _row("ddm", "intrinsic", 80.0),
        ]
        result = compute_triangulation(rows, 85.0)
        names = [a.name for a in result.anchors]
        assert ANCHOR_MARKET in names  # classified via family fallback


class TestAgreement:
    def test_identical_anchors_full_agreement(self):
        rows = [
            _row("ddm", "intrinsic", 100.0),
            _row("relative_multiples", "market", 100.0),
        ]
        result = compute_triangulation(rows, 100.0, broker_target=100.0)
        assert result.agreement == 1.0

    def test_dispersed_anchors_lower_agreement(self):
        tight = compute_triangulation(
            [_row("ddm", "intrinsic", 95.0), _row("relative_multiples", "market", 105.0)],
            100.0,
        )
        wide = compute_triangulation(
            [_row("ddm", "intrinsic", 40.0), _row("relative_multiples", "market", 160.0)],
            100.0,
        )
        assert tight.agreement > wide.agreement
        assert 0.0 <= wide.agreement <= 1.0


class TestSerialization:
    def test_to_dict_round_trip_shape(self):
        result = compute_triangulation(FULL_SET, 130.0, broker_target=180.0)
        payload = result.to_dict()
        assert payload["verdict"] == result.verdict
        assert len(payload["anchors"]) == 3
        assert payload["anchors"][0]["name"] == ANCHOR_INTRINSIC
        assert isinstance(payload["warnings"], list)
