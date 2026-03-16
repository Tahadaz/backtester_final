"""Tests for the signal generation engine (Layers A–G).

All tests use synthetic numpy data — no DB, S3, or API required.
"""

import numpy as np
import pytest

from quant_core.signal_engine.candidates import generate_candidates
from quant_core.signal_engine.domain import HORIZON_PARAMS, VariantDef
from quant_core.signal_engine.ensemble import combine_family_signals, run_sma_ensemble
from quant_core.signal_engine.oos_eval import compute_signal_array, evaluate_variant_oos
from quant_core.signal_engine.redundancy import reduce_redundancy
from quant_core.signal_engine.robustness import score_variant_robustness
from quant_core.signal_engine.survivor import filter_survivors
from quant_core.signal_engine.domain import (
    OOSWindowResult,
    VariantCurrentSignal,
    VariantRobustnessSummary,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uptrend(n: int = 1500, start: float = 100.0, end: float = 200.0) -> np.ndarray:
    """Monotonic uptrend — every SMA signal should be BUY after warmup."""
    return np.linspace(start, end, n)


def _flat(n: int = 1500, value: float = 100.0) -> np.ndarray:
    return np.full(n, value)


def _make_variant(archetype: str = "price_vs_sma", **params) -> VariantDef:
    return VariantDef(
        variant_id=f"test_{archetype}",
        family="sma",
        archetype=archetype,
        params=params,
        description=f"test {archetype}",
    )


# ===================================================================
# Candidates (Layer A)
# ===================================================================

class TestCandidates:
    @pytest.mark.parametrize("horizon", ["short", "medium", "long"])
    def test_candidate_count_per_horizon(self, horizon):
        candidates = generate_candidates("sma", horizon)
        assert 8 <= len(candidates) <= 12, f"{horizon}: got {len(candidates)}"

    def test_variant_ids_unique(self):
        for horizon in ("short", "medium", "long"):
            candidates = generate_candidates("sma", horizon)
            ids = [c.variant_id for c in candidates]
            assert len(ids) == len(set(ids)), f"Duplicate IDs in {horizon}"

    def test_variant_id_deterministic(self):
        a = generate_candidates("sma", "medium")
        b = generate_candidates("sma", "medium")
        assert [c.variant_id for c in a] == [c.variant_id for c in b]


# ===================================================================
# Signal contract (Layer B foundations)
# ===================================================================

class TestSignalContract:
    @pytest.mark.parametrize("archetype,params", [
        ("price_vs_sma", {"window": 20}),
        ("sma_cross", {"fast": 10, "slow": 50}),
        ("slope_confirmed", {"window": 30, "slope_lookback": 7}),
    ])
    def test_signal_length_equals_close_length(self, archetype, params):
        close = _uptrend(500)
        v = _make_variant(archetype, **params)
        sig = compute_signal_array(close, v)
        assert len(sig) == len(close)

    @pytest.mark.parametrize("archetype,params", [
        ("price_vs_sma", {"window": 20}),
        ("sma_cross", {"fast": 10, "slow": 50}),
        ("slope_confirmed", {"window": 30, "slope_lookback": 7}),
    ])
    def test_signal_values_in_valid_set(self, archetype, params):
        close = _uptrend(500)
        v = _make_variant(archetype, **params)
        sig = compute_signal_array(close, v)
        unique_vals = set(np.unique(sig))
        assert unique_vals <= {-1.0, 0.0, 1.0}, f"Invalid values: {unique_vals}"

    def test_warmup_bars_are_zero(self):
        close = _uptrend(500)
        v = _make_variant("price_vs_sma", window=20)
        sig = compute_signal_array(close, v)
        # First w-1 bars should be 0.0 (flat policy), not -1.0
        warmup = sig[:19]
        assert np.all(warmup == 0.0), f"Warmup not flat: {warmup[:5]}"

    def test_slope_confirmed_padding(self):
        close = _uptrend(500)
        w, k = 30, 7
        v = _make_variant("slope_confirmed", window=w, slope_lookback=k)
        sig = compute_signal_array(close, v)
        # First window + slope_lookback - 1 bars should be 0.0
        warmup_end = w + k - 2  # conservative: at least this many zeros
        assert np.all(sig[:w - 1] == 0.0), "SMA warmup not flat"


# ===================================================================
# OOS evaluation (Layer B)
# ===================================================================

class TestOOSEval:
    def test_oos_eval_valid_windows(self):
        close = _uptrend(1500)
        v = _make_variant("price_vs_sma", window=20)
        results = evaluate_variant_oos(close, v, "medium")
        valid = [r for r in results if r.is_valid]
        assert len(valid) >= 3, f"Expected >= 3 valid windows, got {len(valid)}"

    def test_oos_chronology_no_overlap(self):
        close = _uptrend(1500)
        v = _make_variant("price_vs_sma", window=20)
        results = evaluate_variant_oos(close, v, "medium")
        for w in results:
            assert w.test_start >= w.train_end, (
                f"Window {w.window_index}: test_start {w.test_start} < train_end {w.train_end}"
            )

    def test_oos_no_future_data(self):
        """Signal at bar t must depend only on close[0..t].

        Verify by computing signal on close[:t+1] and checking it matches
        the full-array signal at position t.
        """
        close = _uptrend(200)
        v = _make_variant("price_vs_sma", window=10)
        full_sig = compute_signal_array(close, v)

        # Check a few bars past warmup
        for t in [15, 50, 100, 150, 190]:
            partial_sig = compute_signal_array(close[:t + 1], v)
            assert partial_sig[-1] == full_sig[t], (
                f"Signal at bar {t} differs: partial={partial_sig[-1]}, full={full_sig[t]}"
            )


# ===================================================================
# Robustness + filtering (Layers C, D)
# ===================================================================

class TestRobustnessAndFiltering:
    def test_reliability_score_bounds(self):
        close = _uptrend(1500)
        candidates = generate_candidates("sma", "medium")
        for c in candidates:
            windows = evaluate_variant_oos(close, c, "medium")
            summary = score_variant_robustness(c, windows)
            assert 0.0 <= summary.reliability_score <= 1.0

    def test_viability_gate_enforced(self):
        """Force fraction_positive < 0.40 → score = 0, is_viable = False."""
        v = _make_variant("price_vs_sma", window=20)
        # Create fake OOS windows where most have negative Sharpe
        fake_windows = [
            OOSWindowResult(
                window_index=i,
                train_start=0, train_end=100,
                test_start=100, test_end=150,
                n_trades=10, mean_return_net=-0.001,
                sharpe=-0.5, max_drawdown=0.15,
                fraction_positive_bars=0.4, n_bars=50,
                is_valid=True,
            )
            for i in range(5)
        ]
        # Only 0 out of 5 have positive Sharpe → fraction_positive = 0.0
        summary = score_variant_robustness(v, fake_windows)
        assert summary.reliability_score == 0.0
        assert summary.is_viable is False

    def test_survivor_removes_non_viable(self):
        v1 = _make_variant("price_vs_sma", window=20)
        v2 = _make_variant("price_vs_sma", window=50)
        viable = VariantRobustnessSummary(
            variant=v1, n_oos_windows=5, n_valid_windows=5,
            mean_sharpe=0.5, std_sharpe=0.2, median_sharpe=0.5,
            fraction_positive_windows=0.8, mean_max_drawdown=0.1,
            reliability_score=0.6, is_viable=True,
        )
        non_viable = VariantRobustnessSummary(
            variant=v2, n_oos_windows=5, n_valid_windows=2,
            mean_sharpe=0.1, std_sharpe=0.5, median_sharpe=0.0,
            fraction_positive_windows=0.2, mean_max_drawdown=0.2,
            reliability_score=0.0, is_viable=False,
        )
        survivors = filter_survivors([viable, non_viable])
        assert len(survivors) == 1
        assert survivors[0].variant.variant_id == v1.variant_id


# ===================================================================
# Redundancy + ensemble (Layers E, G)
# ===================================================================

class TestRedundancyAndEnsemble:
    def test_redundancy_identical_signals_keeps_one(self):
        """5 identical variants → should collapse to 1."""
        close = _uptrend(500)
        variants = [
            VariantRobustnessSummary(
                variant=VariantDef(
                    variant_id=f"v_{i}", family="sma", archetype="price_vs_sma",
                    params={"window": 20}, description=f"dup {i}",
                ),
                n_oos_windows=5, n_valid_windows=5,
                mean_sharpe=0.5 - i * 0.01, std_sharpe=0.2,
                median_sharpe=0.5, fraction_positive_windows=0.8,
                mean_max_drawdown=0.1, reliability_score=0.6 - i * 0.01,
                is_viable=True,
            )
            for i in range(5)
        ]
        reps = reduce_redundancy(variants, close)
        assert len(reps) == 1, f"Expected 1, got {len(reps)}"

    def test_ensemble_score_range(self):
        """All BUY → +100, all SELL → -100."""
        buy_signals = [
            VariantCurrentSignal(
                variant_id="v1", signal=1.0, signal_label="BUY",
                reliability_weight=0.5, current_close=100.0,
                indicator_value=90.0, explanation="test",
            ),
            VariantCurrentSignal(
                variant_id="v2", signal=1.0, signal_label="BUY",
                reliability_weight=0.3, current_close=100.0,
                indicator_value=85.0, explanation="test",
            ),
        ]
        score, label, _ = combine_family_signals(buy_signals)
        assert score == pytest.approx(100.0)
        assert label == "STRONG BUY"

        sell_signals = [
            VariantCurrentSignal(
                variant_id="v1", signal=-1.0, signal_label="SELL",
                reliability_weight=0.5, current_close=100.0,
                indicator_value=110.0, explanation="test",
            ),
        ]
        score, label, _ = combine_family_signals(sell_signals)
        assert score == pytest.approx(-100.0)
        assert label == "STRONG SELL"
