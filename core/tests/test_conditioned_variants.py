"""Unit tests for core/quant_core/research/factors/conditioned_variants.py

Tests:
  - compose_and_signal: HOLD-on-false semantics, shape preservation
  - make_conditioned_variant: family suffix, description, unique variant_id
  - No look-ahead guarantee (composition is element-wise with aligned mask)
"""
import numpy as np
import pytest

from core.quant_core.signal_engine.domain import FactorConditionMeta, VariantDef
from core.quant_core.research.factors.conditioned_variants import (
    compose_and_signal,
    conditioned_family,
    conditioned_description,
    make_conditioned_variant,
    FACTOR_X_TA_FAMILY_SUFFIX,
)


def _condition(condition_id: str = "vix_z20_below_neg1") -> FactorConditionMeta:
    return FactorConditionMeta(
        condition_id=condition_id,
        factor_ticker="^VIX",
        form="zscore",
        lookback=20,
        threshold=-1.0,
        direction="below",
    )


def _ta_variant(family: str = "sma") -> VariantDef:
    from core.quant_core.signal_engine._hashing import compute_variant_id
    params = {"window": 20, "archetype": "price_vs_sma"}
    return VariantDef(
        variant_id=compute_variant_id(family, params),
        family=family,
        archetype="price_vs_sma",
        params={"window": 20},
        description="SMA-20 (short)",
    )


# ---------------------------------------------------------------------------
# compose_and_signal
# ---------------------------------------------------------------------------

class TestComposeAndSignal:
    def test_condition_true_passes_ta_signal(self):
        ta = np.array([1.0, -1.0, 0.0, 1.0, -1.0])
        mask = np.array([True, True, True, True, True])
        out = compose_and_signal(ta, mask)
        np.testing.assert_array_equal(out, ta)

    def test_condition_false_emits_hold(self):
        ta = np.array([1.0, -1.0, 1.0])
        mask = np.array([False, False, False])
        out = compose_and_signal(ta, mask)
        np.testing.assert_array_equal(out, [0.0, 0.0, 0.0])

    def test_mixed_gate(self):
        ta = np.array([1.0, 1.0, -1.0, -1.0])
        mask = np.array([True, False, True, False])
        out = compose_and_signal(ta, mask)
        expected = np.array([1.0, 0.0, -1.0, 0.0])
        np.testing.assert_array_equal(out, expected)

    def test_shape_preserved(self):
        n = 1000
        ta = np.ones(n)
        mask = np.ones(n, dtype=bool)
        out = compose_and_signal(ta, mask)
        assert len(out) == n

    def test_shape_mismatch_raises(self):
        ta = np.ones(10)
        mask = np.ones(9, dtype=bool)
        with pytest.raises(ValueError):
            compose_and_signal(ta, mask)

    def test_sell_signal_gated(self):
        # Ensure -1 is blocked (not inverted) when condition is False
        ta = np.array([-1.0, -1.0])
        mask = np.array([False, True])
        out = compose_and_signal(ta, mask)
        assert out[0] == 0.0  # gated → HOLD, not +1 (no inversion)
        assert out[1] == -1.0


# ---------------------------------------------------------------------------
# naming utilities
# ---------------------------------------------------------------------------

class TestNamingUtilities:
    def test_conditioned_family_suffix(self):
        assert conditioned_family("sma") == "sma@fx"
        assert conditioned_family("rsi") == "rsi@fx"
        assert FACTOR_X_TA_FAMILY_SUFFIX == "@fx"

    def test_conditioned_description(self):
        desc = conditioned_description("SMA-20 (short)", "vix_z20_below_neg1")
        assert desc == "SMA-20 (short)@vix_z20_below_neg1"


# ---------------------------------------------------------------------------
# make_conditioned_variant
# ---------------------------------------------------------------------------

class TestMakeConditionedVariant:
    def test_family_has_fx_suffix(self):
        ta = _ta_variant("sma")
        cond = _condition()
        cv = make_conditioned_variant(ta, cond)
        assert cv.family == "sma@fx"

    def test_description_contains_condition_id(self):
        ta = _ta_variant("sma")
        cond = _condition("vix_z20_below_neg1")
        cv = make_conditioned_variant(ta, cond)
        assert "vix_z20_below_neg1" in cv.description

    def test_factor_condition_populated(self):
        ta = _ta_variant("sma")
        cond = _condition()
        cv = make_conditioned_variant(ta, cond)
        assert cv.factor_condition is cond

    def test_variant_id_differs_from_ta(self):
        ta = _ta_variant("sma")
        cond = _condition()
        cv = make_conditioned_variant(ta, cond)
        assert cv.variant_id != ta.variant_id

    def test_different_conditions_give_different_ids(self):
        ta = _ta_variant("sma")
        cv1 = make_conditioned_variant(ta, _condition("cond_a"))
        cv2 = make_conditioned_variant(ta, _condition("cond_b"))
        assert cv1.variant_id != cv2.variant_id

    def test_original_ta_variant_unchanged(self):
        ta = _ta_variant("sma")
        original_id = ta.variant_id
        make_conditioned_variant(ta, _condition())
        assert ta.variant_id == original_id
        assert ta.family == "sma"
        assert ta.factor_condition is None

    def test_archetype_preserved(self):
        ta = _ta_variant("sma")
        cond = _condition()
        cv = make_conditioned_variant(ta, cond)
        assert cv.archetype == "price_vs_sma"
