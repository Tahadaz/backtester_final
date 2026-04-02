"""Tests for the signal generation engine (Layers A–G).

All tests use synthetic numpy data — no DB, S3, or API required.
"""

import numpy as np
import pytest

from quant_core.signal_engine.candidates import generate_candidates
from quant_core.signal_engine.domain import HORIZON_PARAMS, VariantDef
from quant_core.signal_engine.ensemble import combine_family_signals, run_sma_ensemble, run_family_ensemble_full
from quant_core.signal_engine.oos_eval import apply_cooldown, compute_signal_array, evaluate_variant_oos
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


def _make_volume(n: int) -> np.ndarray:
    """Synthetic volume data for OBV tests."""
    rng = np.random.default_rng(42)
    return rng.uniform(1e5, 1e7, size=n)


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
        assert len(candidates) == 30, f"{horizon}: got {len(candidates)}"

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
    def test_signal_length_equals_close_length(self):
        close = _uptrend(500)
        v = _make_variant("price_vs_sma", window=20)
        sig = compute_signal_array(close, v)
        assert len(sig) == len(close)

    def test_signal_values_in_valid_set(self):
        close = _uptrend(500)
        v = _make_variant("price_vs_sma", window=20)
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
        reps, redundancy_info, corr_matrix = reduce_redundancy(variants, close)
        assert len(reps) == 1, f"Expected 1, got {len(reps)}"
        # 4 eliminated variants should have redundancy info
        assert len(redundancy_info) == 4
        # Correlation matrix should have 5 entries
        assert len(corr_matrix) == 5

    def test_ensemble_score_range(self):
        """All BUY → +100, all SELL → -100."""
        buy_signals = [
            VariantCurrentSignal(
                variant_id="v1", signal=1.0, signal_label="HAUSSIER",
                reliability_weight=0.5, current_close=100.0,
                indicator_value=90.0, explanation="test",
            ),
            VariantCurrentSignal(
                variant_id="v2", signal=1.0, signal_label="HAUSSIER",
                reliability_weight=0.3, current_close=100.0,
                indicator_value=85.0, explanation="test",
            ),
        ]
        # Without family → aggregate labels
        score, label, _ = combine_family_signals(buy_signals)
        assert score == pytest.approx(100.0)
        assert label == "Achat fort"

        sell_signals = [
            VariantCurrentSignal(
                variant_id="v1", signal=-1.0, signal_label="BAISSIER",
                reliability_weight=0.5, current_close=100.0,
                indicator_value=110.0, explanation="test",
            ),
        ]
        score, label, _ = combine_family_signals(sell_signals)
        assert score == pytest.approx(-100.0)
        assert label == "Vente forte"

    def test_ensemble_family_specific_labels(self):
        """With family context, labels are type-specific."""
        signals = [
            VariantCurrentSignal(
                variant_id="v1", signal=1.0, signal_label="HAUSSIER",
                reliability_weight=0.5, current_close=100.0,
                indicator_value=90.0, explanation="test",
            ),
        ]
        _, label, _ = combine_family_signals(signals, family="sma")
        assert label == "Très haussier"

        _, label, _ = combine_family_signals(signals, family="rsi")
        assert label == "Très survendu"

        _, label, _ = combine_family_signals(signals, family="obv")
        assert label == "Forte accumulation"


# ===================================================================
# OOS return metrics (total_return, cagr, pnl)
# ===================================================================

class TestOOSReturnMetrics:
    def test_oos_window_has_return_metrics(self):
        close = _uptrend(1500)
        v = _make_variant("price_vs_sma", window=20)
        results = evaluate_variant_oos(close, v, "medium")
        valid = [r for r in results if r.is_valid]
        assert len(valid) >= 3
        for w in valid:
            assert hasattr(w, 'total_return')
            assert hasattr(w, 'cagr')
            assert hasattr(w, 'pnl')
            # In uptrend, returns should generally be positive
            assert w.pnl == pytest.approx(100_000.0 * w.total_return)

    def test_robustness_summary_has_cagr_pnl(self):
        close = _uptrend(1500)
        v = _make_variant("price_vs_sma", window=20)
        windows = evaluate_variant_oos(close, v, "medium")
        summary = score_variant_robustness(v, windows)
        assert hasattr(summary, 'cagr')
        assert hasattr(summary, 'total_pnl')


# ===================================================================
# Multi-family candidates (RSI, MACD, OBV)
# ===================================================================

class TestMultiFamilyCandidates:
    @pytest.mark.parametrize("family", ["rsi", "macd", "obv"])
    @pytest.mark.parametrize("horizon", ["short", "medium", "long"])
    def test_candidate_count(self, family, horizon):
        candidates = generate_candidates(family, horizon)
        assert len(candidates) == 30, f"{family}/{horizon}: got {len(candidates)}"

    @pytest.mark.parametrize("family", ["rsi", "macd", "obv"])
    def test_variant_ids_unique(self, family):
        for horizon in ("short", "medium", "long"):
            candidates = generate_candidates(family, horizon)
            ids = [c.variant_id for c in candidates]
            assert len(ids) == len(set(ids)), f"Duplicate IDs in {family}/{horizon}"

    @pytest.mark.parametrize("family", ["rsi", "macd", "obv"])
    def test_variant_id_deterministic(self, family):
        a = generate_candidates(family, "medium")
        b = generate_candidates(family, "medium")
        assert [c.variant_id for c in a] == [c.variant_id for c in b]


# ===================================================================
# Multi-family signal contract
# ===================================================================

class TestMultiFamilySignalContract:
    @pytest.mark.parametrize("family", ["rsi", "macd", "obv"])
    def test_signal_contract(self, family):
        close = _uptrend(800)
        volume = _make_volume(800)
        candidates = generate_candidates(family, "medium")
        for c in candidates[:5]:
            sig = compute_signal_array(close, c, volume=volume)
            assert len(sig) == len(close)
            unique_vals = set(np.unique(sig))
            assert unique_vals <= {-1.0, 0.0, 1.0}, f"Invalid values for {c.variant_id}: {unique_vals}"

    def test_obv_with_real_volume(self):
        """OBV signals should vary with volume data."""
        close = _uptrend(500)
        volume = _make_volume(500)
        v = VariantDef(
            variant_id="test_obv", family="obv", archetype="obv_trend",
            params={"ema_period": 20}, description="OBV test",
        )
        sig = compute_signal_array(close, v, volume=volume)
        assert len(sig) == len(close)
        # With real volume + uptrend, OBV should be mostly increasing → BUY signals
        assert np.sum(sig == 1.0) > 0

    def test_rsi_oversold_overbought(self):
        """RSI on uptrend should not show BUY (not oversold) in later bars."""
        close = _uptrend(500)
        v = VariantDef(
            variant_id="test_rsi", family="rsi", archetype="rsi_level",
            params={"period": 14, "oversold": 30, "overbought": 70}, description="RSI test",
        )
        sig = compute_signal_array(close, v)
        assert len(sig) == len(close)
        # In a steady uptrend, RSI will be high → expect SELL (-1) or HOLD (0)
        # Not many BUY signals expected in late bars
        late_buys = np.sum(sig[200:] == 1.0)
        late_sells = np.sum(sig[200:] == -1.0)
        # RSI should be above 70 in a strong uptrend
        assert late_sells >= late_buys


# ===================================================================
# Multi-family ensemble end-to-end
# ===================================================================

class TestMultiFamilyEnsemble:
    @pytest.mark.parametrize("family", ["rsi", "macd", "obv"])
    def test_ensemble_end_to_end(self, family):
        close = _uptrend(1500)
        volume = _make_volume(1500)
        detail = run_family_ensemble_full(
            family, close, volume=volume, symbol="TEST", horizon="medium",
        )
        assert detail.signal.family == family
        assert detail.signal.tested_count == 30
        assert detail.signal.viable_count >= 0
        assert -100 <= detail.signal.family_score_pct <= 100


class TestLowDataModes:
    def test_adaptive_oos_mode_uses_reduced_windows(self):
        close = _uptrend(72)
        detail = run_family_ensemble_full(
            "sma", close, symbol="TEST", horizon="short",
        )
        assert detail.signal.methodology_mode == "adaptive_oos_ensemble"
        assert detail.signal.is_provisional is True
        assert detail.signal.effective_window.train == 8
        assert detail.signal.effective_window.test == 21
        assert detail.signal.effective_window.step == 21
        assert detail.signal.tested_count == 30
        assert detail.signal.warning_message

    def test_live_signal_only_mode_returns_fallback_variants(self):
        close = _uptrend(50)
        detail = run_family_ensemble_full(
            "sma", close, symbol="TEST", horizon="short",
        )
        assert detail.signal.methodology_mode == "live_signal_only"
        assert detail.signal.is_provisional is True
        assert detail.signal.representative_count == 0
        assert len(detail.signal.fallback_variants) > 0
        assert set(v["variant_id"] for v in detail.signal.fallback_variants).isdisjoint(detail.representative_ids)

    def test_robust_mode_stays_unchanged_when_history_is_sufficient(self):
        close = _uptrend(500)
        detail = run_family_ensemble_full(
            "sma", close, symbol="TEST", horizon="short",
        )
        assert detail.signal.methodology_mode == "robust_oos_ensemble"
        assert detail.signal.is_provisional is False
        assert detail.signal.effective_window.train == HORIZON_PARAMS["short"]["train"]
        assert detail.signal.effective_window.test == HORIZON_PARAMS["short"]["test"]


# ===================================================================
# Horizon max_years configuration
# ===================================================================

class TestHorizonMaxYears:
    def test_max_years_present_and_correct(self):
        expected = {"short": 5, "medium": 10, "long": 20}
        for h, years in expected.items():
            assert "max_years" in HORIZON_PARAMS[h], f"{h} missing max_years"
            assert HORIZON_PARAMS[h]["max_years"] == years, f"{h}: expected {years}"

    def test_max_bars_exceeds_min_bars(self):
        """max_years * 252 must be larger than train + test + 1 for each horizon."""
        for h, hp in HORIZON_PARAMS.items():
            max_bars = hp["max_years"] * 252
            min_bars = hp["train"] + hp["test"] + 1
            assert max_bars > min_bars, (
                f"{h}: max_bars={max_bars} <= min_bars={min_bars}"
            )

    def test_engine_truncates_close_to_max_years(self):
        """Passing 40 years of data with short horizon should produce same
        result as passing only 5 years, because the engine truncates."""
        n_full = 10000  # ~40 years
        n_short = HORIZON_PARAMS["short"]["max_years"] * 252  # 1260
        close_full = _uptrend(n_full)
        close_short = close_full[-n_short:]

        detail_full = run_family_ensemble_full(
            "sma", close_full, symbol="TEST", horizon="short",
        )
        detail_short = run_family_ensemble_full(
            "sma", close_short, symbol="TEST", horizon="short",
        )

        # Same number of OOS windows
        for vid in detail_full.oos_windows:
            if vid in detail_short.oos_windows:
                assert len(detail_full.oos_windows[vid]) == len(detail_short.oos_windows[vid]), (
                    f"{vid}: full={len(detail_full.oos_windows[vid])} != short={len(detail_short.oos_windows[vid])}"
                )

        # Same signal output
        assert detail_full.signal.family_score_pct == detail_short.signal.family_score_pct
        assert detail_full.signal.family_signal_label == detail_short.signal.family_signal_label


# ===================================================================
# Cooldown parameter
# ===================================================================

class TestCooldown:
    def test_cooldown_zero_no_change(self):
        """cooldown_bars=0 must produce the same signal as no cooldown."""
        sig = np.array([0, 1, -1, 1, -1, 0, 1, 1, -1, 0], dtype=float)
        result = apply_cooldown(sig, 0)
        np.testing.assert_array_equal(result, sig)

    def test_cooldown_suppresses_rapid_flips(self):
        """With cooldown=3, a flip at bar 1 holds through bar 4."""
        sig = np.array([0, 1, -1, -1, 0, 1, -1, 1, 0, 0], dtype=float)
        result = apply_cooldown(sig, 3)
        # bar 0→1: change from 0→1 at bar 1, hold 1 for bars 2,3,4
        assert result[1] == 1.0
        assert result[2] == 1.0  # was -1, now held as 1
        assert result[3] == 1.0  # was -1, now held as 1
        assert result[4] == 1.0  # was 0, now held as 1

    def test_cooldown_returns_copy(self):
        """apply_cooldown must not mutate the input."""
        sig = np.array([0, 1, -1, 1], dtype=float)
        original = sig.copy()
        apply_cooldown(sig, 2)
        np.testing.assert_array_equal(sig, original)

    def test_cooldown_oos_fewer_trades(self):
        """OOS eval with cooldown should produce fewer trades."""
        close = _uptrend(1500)
        v = _make_variant("price_vs_sma", window=20)
        results_0 = evaluate_variant_oos(close, v, "medium", cooldown_bars=0)
        results_5 = evaluate_variant_oos(close, v, "medium", cooldown_bars=5)
        # Both should produce valid windows
        assert len(results_0) > 0
        assert len(results_5) > 0
        # Cooldown should result in <= trades
        trades_0 = sum(w.n_trades for w in results_0)
        trades_5 = sum(w.n_trades for w in results_5)
        assert trades_5 <= trades_0


# ===================================================================
# Cost model — position-change basis (Chan 2008)
# ===================================================================

class _LegacyCostModel:
    def test_double_buy_no_double_cost(self):
        """RSI firing buy twice should not charge cost twice if position unchanged."""
        from quant_core.signal_engine.oos_eval import _actions_to_positions
        actions = np.array([0, 0, 1, 0, 0, 1, 0, 0, -1, 0], dtype=float)
        positions = _actions_to_positions(actions)
        sig_change = np.abs(np.diff(positions, prepend=0.0))
        # 0→+1: cost charged
        assert sig_change[2] == 1.0
        # +1→+1: NO cost (double buy, position unchanged)
        assert sig_change[5] == 0.0
        # +1→-1: cost charged (full reversal = 2.0)
        assert sig_change[8] == 2.0

    def test_position_signal_cost_unchanged(self):
        """SMA/MACD position signals: cost = |diff(position)|, same as before."""
        positions = np.array([0, 1, 1, 1, -1, -1, 0, 1], dtype=float)
        sig_change = np.abs(np.diff(positions, prepend=0.0))
        assert sig_change[1] == 1.0   # 0→+1
        assert sig_change[2] == 0.0   # +1→+1 (held)
        assert sig_change[4] == 2.0   # +1→-1
        assert sig_change[6] == 1.0   # -1→0
        assert sig_change[7] == 1.0   # 0→+1


# ===================================================================
# Signal type taxonomy labels (Murphy 1999, Elder 1993)
# ===================================================================

class TestCostModel:
    def test_double_buy_no_double_cost(self):
        """Repeated buys keep the same long and do not recharge cost."""
        from quant_core.signal_engine.oos_eval import _actions_to_positions

        actions = np.array([0, 0, 1, 0, 0, 1, 0, 0, -1, 0], dtype=float)
        positions = _actions_to_positions(actions)
        sig_change = np.abs(np.diff(positions, prepend=0.0))

        assert sig_change[2] == 1.0
        assert sig_change[5] == 0.0
        assert sig_change[8] == 1.0

    def test_position_signal_cost_uses_long_only_transitions(self):
        positions = np.array([0, 1, 1, 1, 0, 0, 0, 1], dtype=float)
        sig_change = np.abs(np.diff(positions, prepend=0.0))

        assert sig_change[1] == 1.0
        assert sig_change[2] == 0.0
        assert sig_change[4] == 1.0
        assert sig_change[6] == 0.0
        assert sig_change[7] == 1.0

    def test_state_signals_clamp_negative_values_to_flat(self):
        from quant_core.signal_engine.oos_eval import signal_to_long_only_positions

        variant = _make_variant("price_vs_sma", window=20)
        sig = np.array([0.0, 1.0, 1.0, -1.0, -1.0, 0.0, 1.0], dtype=float)

        positions = signal_to_long_only_positions(sig, variant)

        np.testing.assert_array_equal(
            positions,
            np.array([0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0], dtype=float),
        )

    def test_event_signals_treat_minus_one_as_close_not_short(self):
        from quant_core.signal_engine.oos_eval import signal_to_long_only_positions

        variant = VariantDef(
            variant_id="test_macd_cross",
            family="macd",
            archetype="macd_cross",
            params={"fast": 12, "slow": 26, "signal": 9},
            description="MACD event test",
        )
        sig = np.array([0.0, 1.0, 0.0, 0.0, -1.0, 0.0], dtype=float)

        positions = signal_to_long_only_positions(sig, variant)

        np.testing.assert_array_equal(
            positions,
            np.array([0.0, 1.0, 1.0, 1.0, 0.0, 0.0], dtype=float),
        )


class TestSignalTypeLabels:
    def test_trend_labels(self):
        from quant_core.signal_engine.domain import signal_type_label
        assert signal_type_label("trend", 60) == "Très haussier"
        assert signal_type_label("trend", 30) == "Haussier"
        assert signal_type_label("trend", 0) == "Neutre"
        assert signal_type_label("trend", -30) == "Baissier"
        assert signal_type_label("trend", -60) == "Très baissier"

    def test_oscillator_labels(self):
        from quant_core.signal_engine.domain import signal_type_label
        assert signal_type_label("oscillator", 60) == "Très survendu"
        assert signal_type_label("oscillator", 0) == "Normal"
        assert signal_type_label("oscillator", -60) == "Très suracheté"

    def test_volume_labels(self):
        from quant_core.signal_engine.domain import signal_type_label
        assert signal_type_label("volume", 60) == "Forte accumulation"
        assert signal_type_label("volume", 0) == "Neutre"
        assert signal_type_label("volume", -60) == "Forte distribution"

    def test_aggregate_labels(self):
        from quant_core.signal_engine.domain import signal_type_label
        assert signal_type_label("aggregate", 60) == "Achat fort"
        assert signal_type_label("aggregate", 0) == "Neutre"
        assert signal_type_label("aggregate", -60) == "Vente forte"

    def test_variant_signal_label(self):
        from quant_core.signal_engine.domain import variant_signal_label
        assert variant_signal_label("sma", 1.0) == "HAUSSIER"
        assert variant_signal_label("sma", -1.0) == "BAISSIER"
        assert variant_signal_label("sma", 0.0) == "NEUTRE"
        assert variant_signal_label("rsi", 1.0) == "SURVENDU"
        assert variant_signal_label("rsi", -1.0) == "SURACHETÉ"
        assert variant_signal_label("rsi", 0.0) == "NORMAL"
        assert variant_signal_label("obv", 1.0) == "ACCUMULATION"
        assert variant_signal_label("obv", -1.0) == "DISTRIBUTION"
        assert variant_signal_label("macd", 1.0) == "HAUSSIER"
