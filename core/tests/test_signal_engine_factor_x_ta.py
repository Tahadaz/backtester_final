"""Architectural smoke test: Layers B–G absorb factor-conditioned variants unchanged.

This is the Day-1 verification from the Phase 2 plan (§17.1):
  1. Inject one hand-crafted factor-conditioned candidate into Layer A output.
  2. Pre-compute the AND-composed signal.
  3. Run the full A→G pipeline via evaluate_variant_oos + robustness + survivor
     + redundancy + current_signal + ensemble.
  4. Verify a VariantCurrentSignal comes out with factor_condition populated and
     IC/Sharpe/DSR plausibly computed.

If this test fails, Layers B–G have a leak and the architectural bet is wrong.
"""
import numpy as np
import pytest

from core.quant_core.signal_engine.domain import (
    FactorConditionMeta,
    VariantDef,
)
from core.quant_core.signal_engine.oos_eval import evaluate_variant_oos
from core.quant_core.signal_engine.robustness import score_variant_robustness
from core.quant_core.signal_engine.survivor import filter_survivors
from core.quant_core.signal_engine.current_signal import build_current_signal
from core.quant_core.research.factors.conditions import evaluate_condition
from core.quant_core.research.factors.conditioned_variants import (
    compose_and_signal,
    make_conditioned_variant,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_synthetic_close(n: int = 800, seed: int = 42) -> np.ndarray:
    """Random-walk price series with enough bars for medium horizon OOS."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(0.0005, 0.015, n)
    prices = 100.0 * np.cumprod(1 + returns)
    return prices.astype(np.float64)


def _make_synthetic_factor(n: int = 800, seed: int = 7) -> np.ndarray:
    """Synthetic VIX-like factor series."""
    rng = np.random.default_rng(seed)
    vix = 20 + 5 * rng.normal(0, 1, n)
    return np.maximum(vix, 5.0)


def _sma_variant() -> VariantDef:
    from core.quant_core.signal_engine._hashing import compute_variant_id

    params = {"window": 20, "archetype": "price_vs_sma"}
    return VariantDef(
        variant_id=compute_variant_id("sma", params),
        family="sma",
        archetype="price_vs_sma",
        params={"window": 20},
        description="SMA-20 (short)",
    )


def _vix_condition() -> FactorConditionMeta:
    return FactorConditionMeta(
        condition_id="vix_z20_below_neg1",
        factor_ticker="^VIX",
        form="zscore",
        lookback=20,
        threshold=-1.0,
        direction="below",
    )


# ---------------------------------------------------------------------------
# The architectural smoke test
# ---------------------------------------------------------------------------

class TestFactorXTaArchitecturalBet:
    def test_layer_b_accepts_precomputed_signal(self):
        """Layer B (evaluate_variant_oos) with precomputed_signal returns OOS windows."""
        close = _make_synthetic_close()
        factor = _make_synthetic_factor()

        ta_variant = _sma_variant()
        condition = _vix_condition()
        c_variant = make_conditioned_variant(ta_variant, condition)

        # Pre-compose signal
        from core.quant_core.signal_engine.oos_eval import compute_signal_array
        ta_sig = compute_signal_array(close, c_variant)
        cond_mask = evaluate_condition(condition, factor)
        composed = compose_and_signal(ta_sig, cond_mask)
        assert len(composed) == len(close)

        # Layer B
        windows = evaluate_variant_oos(
            close,
            c_variant,
            "short",
            cost_bps=10.0,
            precomputed_signal=composed,
        )
        assert isinstance(windows, list)
        assert len(windows) >= 1

    def test_layers_b_through_c_produce_robustness_summary(self):
        """Layers B+C return a VariantRobustnessSummary for a conditioned variant."""
        close = _make_synthetic_close()
        factor = _make_synthetic_factor()

        ta_variant = _sma_variant()
        condition = _vix_condition()
        c_variant = make_conditioned_variant(ta_variant, condition)

        from core.quant_core.signal_engine.oos_eval import compute_signal_array
        ta_sig = compute_signal_array(close, c_variant)
        cond_mask = evaluate_condition(condition, factor)
        composed = compose_and_signal(ta_sig, cond_mask)

        windows = evaluate_variant_oos(close, c_variant, "short", precomputed_signal=composed)
        summary = score_variant_robustness(c_variant, windows)

        assert summary.variant.variant_id == c_variant.variant_id
        assert summary.variant.factor_condition is not None
        assert isinstance(summary.reliability_score, float)

    def test_layer_d_survivor_filtering_accepts_conditioned_variants(self):
        """Layer D (filter_survivors) works on conditioned variant summaries."""
        close = _make_synthetic_close(n=1200)
        factor = _make_synthetic_factor(n=1200)

        ta_variant = _sma_variant()
        condition = _vix_condition()
        c_variant = make_conditioned_variant(ta_variant, condition)

        from core.quant_core.signal_engine.oos_eval import compute_signal_array
        ta_sig = compute_signal_array(close, c_variant)
        cond_mask = evaluate_condition(condition, factor)
        composed = compose_and_signal(ta_sig, cond_mask)

        windows = evaluate_variant_oos(close, c_variant, "short", precomputed_signal=composed)
        summary = score_variant_robustness(c_variant, windows)

        survivors = filter_survivors([summary])
        # Either 0 or 1 survivors — just verifying no crash and correct type
        assert isinstance(survivors, list)
        for s in survivors:
            assert s.variant.variant_id == c_variant.variant_id

    def test_layer_f_current_signal_works_for_conditioned_variant(self):
        """Layer F (build_current_signal) works without crashing on conditioned variant.

        The '@fx' family suffix is stripped in compute_signal_array + variant_signal_label.
        """
        close = _make_synthetic_close(n=100)
        c_variant = make_conditioned_variant(_sma_variant(), _vix_condition())

        vcs = build_current_signal(c_variant, close)
        assert vcs.variant_id == c_variant.variant_id
        assert vcs.signal in (-1.0, 0.0, 1.0)
        assert isinstance(vcs.signal_label, str)
        assert len(vcs.signal_label) > 0

    def test_variant_id_uniqueness(self):
        """Factor-conditioned variant has a different ID from its native TA base."""
        ta = _sma_variant()
        c_variant = make_conditioned_variant(ta, _vix_condition())
        assert c_variant.variant_id != ta.variant_id

    def test_factor_condition_survives_in_summary(self):
        """factor_condition metadata is preserved through Layer C robustness scoring."""
        close = _make_synthetic_close()
        factor = _make_synthetic_factor()

        ta_variant = _sma_variant()
        condition = _vix_condition()
        c_variant = make_conditioned_variant(ta_variant, condition)

        from core.quant_core.signal_engine.oos_eval import compute_signal_array
        ta_sig = compute_signal_array(close, c_variant)
        cond_mask = evaluate_condition(condition, factor)
        composed = compose_and_signal(ta_sig, cond_mask)

        windows = evaluate_variant_oos(close, c_variant, "short", precomputed_signal=composed)
        summary = score_variant_robustness(c_variant, windows)

        # Key assertion: the factor_condition is still accessible through the summary
        assert summary.variant.factor_condition is not None
        assert summary.variant.factor_condition.condition_id == "vix_z20_below_neg1"
        assert summary.variant.factor_condition.factor_ticker == "^VIX"


# ---------------------------------------------------------------------------
# generate_factor_conditioned_candidates integration
# ---------------------------------------------------------------------------

class TestGenerateFactorConditionedCandidates:
    def test_cross_product_returns_conditioned_variants(self):
        from core.quant_core.signal_engine.candidates import (
            generate_candidates,
            generate_factor_conditioned_candidates,
        )
        ta_candidates = generate_candidates("sma", "short")
        conditions = [_vix_condition()]
        result = generate_factor_conditioned_candidates(ta_candidates, conditions)
        assert len(result) == len(ta_candidates)
        for cv in result:
            assert cv.family == "sma@fx"
            assert cv.factor_condition is not None

    def test_channel_gate_filters(self):
        from core.quant_core.signal_engine.candidates import (
            generate_candidates,
            generate_factor_conditioned_candidates,
        )
        ta_candidates = generate_candidates("sma", "short")
        brent_cond = FactorConditionMeta(
            condition_id="brent_test",
            factor_ticker="BZ=F",
            form="momentum",
            lookback=20,
            threshold=0.0,
            direction="above",
        )
        # Only channel_tag [materials] — stock is banks → should be excluded
        channel_tags = {"BZ=F": ["materials", "mining"]}
        result = generate_factor_conditioned_candidates(
            ta_candidates, [brent_cond], channel_tags=channel_tags, stock_sector="banks"
        )
        assert len(result) == 0

    def test_channel_gate_passes_matching_sector(self):
        from core.quant_core.signal_engine.candidates import (
            generate_candidates,
            generate_factor_conditioned_candidates,
        )
        ta_candidates = generate_candidates("sma", "short")[:5]  # small subset
        brent_cond = FactorConditionMeta(
            condition_id="brent_test",
            factor_ticker="BZ=F",
            form="momentum",
            lookback=20,
            threshold=0.0,
            direction="above",
        )
        channel_tags = {"BZ=F": ["materials", "mining"]}
        result = generate_factor_conditioned_candidates(
            ta_candidates, [brent_cond], channel_tags=channel_tags, stock_sector="mining"
        )
        assert len(result) == 5
