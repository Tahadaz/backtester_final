"""Tests for Layer H — Regime detection via Kaufman Efficiency Ratio."""

import numpy as np
import pytest

import core.quant_core.signal_engine.regime as regime_module
from core.quant_core.signal_engine.regime import (
    kaufman_er,
    validate_regime_oos,
    compute_regime_consensus,
    _regime_weights_from_sharpes,
)
from core.quant_core.signal_engine.domain import RegimeResult


# ---------------------------------------------------------------------------
# kaufman_er tests
# ---------------------------------------------------------------------------

class TestKaufmanER:
    def test_trending_uptrend(self):
        """Perfect uptrend → ER ≈ 1.0."""
        close = np.linspace(100, 200, 100)  # monotonic up
        er = kaufman_er(close, window=20)
        # After warmup, all values should be ~1.0
        valid = er[20:]
        assert np.all(~np.isnan(valid))
        assert np.all(valid > 0.95)

    def test_ranging_oscillation(self):
        """High-frequency oscillation → ER near 0."""
        # Alternating up/down creates maximum noise vs direction
        close = np.array([100 + (i % 2) * 2 for i in range(200)], dtype=float)
        er = kaufman_er(close, window=20)
        valid = er[20:]
        assert np.all(~np.isnan(valid))
        # ER should be low for oscillating series
        assert np.mean(valid) < 0.15

    def test_output_length_and_warmup(self):
        """Output length == input length, first window values are NaN."""
        close = np.random.default_rng(42).normal(100, 5, 50)
        close = np.cumsum(np.abs(close))  # ensure positive
        er = kaufman_er(close, window=20)
        assert len(er) == len(close)
        assert np.all(np.isnan(er[:20]))
        assert not np.any(np.isnan(er[20:]))

    def test_weekly_series(self):
        """Series weeklyer than window → all NaN."""
        close = np.array([100.0, 101.0, 102.0])
        er = kaufman_er(close, window=20)
        assert len(er) == 3
        assert np.all(np.isnan(er))


# ---------------------------------------------------------------------------
# Regime weight formula tests
# ---------------------------------------------------------------------------

class TestRegimeWeights:
    def test_positive_sharpes(self):
        """Weights proportional to positive Sharpes."""
        sharpes = {"sma": 2.0, "rsi": 1.0, "macd": 1.0, "obv": 0.0}
        w = _regime_weights_from_sharpes(sharpes)
        assert abs(w["sma"] - 0.5) < 1e-6
        assert abs(w["rsi"] - 0.25) < 1e-6
        assert abs(w["macd"] - 0.25) < 1e-6
        assert abs(w["obv"] - 0.0) < 1e-6

    def test_all_negative_fallback(self):
        """All negative Sharpes → equal weight."""
        sharpes = {"sma": -1.0, "rsi": -0.5, "macd": -2.0}
        w = _regime_weights_from_sharpes(sharpes)
        for v in w.values():
            assert abs(v - 1.0 / 3) < 1e-6

    def test_single_family(self):
        """Single family → weight = 1.0."""
        w = _regime_weights_from_sharpes({"sma": 1.5})
        assert abs(w["sma"] - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# validate_regime_oos tests
# ---------------------------------------------------------------------------

class TestValidateRegimeOOS:
    def _make_trending_data(self, n: int = 1200) -> np.ndarray:
        """Synthetic uptrend with minor noise."""
        rng = np.random.default_rng(42)
        return 100.0 + np.cumsum(0.5 + rng.normal(0, 0.1, n))

    def _make_family_signals(self, n: int = 1200) -> dict[str, np.ndarray]:
        """Dummy signals: sma/macd = +1 (trend followers), rsi = alternating."""
        sma_sig = np.ones(n)
        macd_sig = np.ones(n)
        rsi_sig = np.array([1.0 if i % 4 < 2 else -1.0 for i in range(n)])
        obv_sig = np.ones(n)
        return {"sma": sma_sig, "macd": macd_sig, "rsi": rsi_sig, "obv": obv_sig}

    def test_insufficient_data(self):
        """weekly series → regime_active=False, label=insufficient_data."""
        close = np.linspace(100, 110, 50)
        signals = {"sma": np.ones(50), "rsi": np.ones(50)}
        result = validate_regime_oos(close, signals, "medium", cost_bps=10.0)
        assert not result.regime_active
        assert result.regime_label == "insufficient_data"

    def test_no_families(self):
        """Empty family dict → inactive."""
        close = np.linspace(100, 200, 1000)
        result = validate_regime_oos(close, {}, "weekly", cost_bps=10.0)
        assert not result.regime_active
        assert result.n_families == 0

    def test_single_family_inactive(self):
        """Single family â†’ regime remains inactive."""
        close = self._make_trending_data(1200)
        signals = {"sma": np.ones(1200)}
        result = validate_regime_oos(close, signals, "weekly", cost_bps=10.0)
        assert not result.regime_active
        assert result.regime_label == "single_family"
        assert result.n_families == 1

    def test_returns_regime_result(self):
        """With enough data, returns a RegimeResult with window_results."""
        close = self._make_trending_data(1200)
        signals = self._make_family_signals(1200)
        result = validate_regime_oos(close, signals, "weekly", cost_bps=10.0)
        assert isinstance(result, RegimeResult)
        assert result.n_families == 4
        assert len(result.window_results) > 0
        assert result.er_value is not None

    def test_regime_label_values(self):
        """Regime label is one of expected values."""
        close = self._make_trending_data(1200)
        signals = self._make_family_signals(1200)
        result = validate_regime_oos(close, signals, "weekly", cost_bps=10.0)
        assert result.regime_label in {
            "trending", "ranging", "mixed", "inactive", "insufficient_data"
        }

    def test_window_return_count(self, monkeypatch: pytest.MonkeyPatch):
        """Each fold processes test_end - test_start return bars."""
        close = self._make_trending_data(80)
        signals = self._make_family_signals(80)

        monkeypatch.setitem(
            regime_module.HORIZON_PARAMS,
            "weekly",
            {"train": 30, "test": 5, "step": 5, "max_years": 1},
        )
        monkeypatch.setattr(regime_module, "_sharpe", lambda arr: float(len(arr)))

        result = validate_regime_oos(close, signals, "weekly", cost_bps=10.0)

        assert len(result.window_results) > 0
        for wr in result.window_results:
            expected_bars = wr["test_end"] - wr["test_start"]
            assert wr["regime_sharpe"] == expected_bars
            assert wr["equal_sharpe"] == expected_bars


# ---------------------------------------------------------------------------
# compute_regime_consensus tests
# ---------------------------------------------------------------------------

class TestRegimeConsensus:
    def test_applies_regime_weights(self):
        """When regime active, consensus uses regime weights."""
        regime = RegimeResult(
            regime_active=True,
            regime_label="trending",
            regime_weights={"sma": 0.6, "rsi": 0.1, "macd": 0.2, "obv": 0.1},
            er_value=0.85,
            improvement=0.15,
            tercile_bounds=(0.3, 0.7),
            window_results=[],
            n_families=4,
        )
        scores = {"sma": 50.0, "rsi": -20.0, "macd": 30.0, "obv": 10.0}
        out = compute_regime_consensus(scores, regime)
        # Manual: 0.6*50 + 0.1*(-20) + 0.2*30 + 0.1*10 = 30+(-2)+6+1 = 35.0
        assert abs(out["final_consensus"] - 35.0) < 0.1
        assert out["regime_active"] is True

    def test_equal_weight_fallback(self):
        """When regime inactive, equal-weight consensus."""
        regime = RegimeResult(
            regime_active=False,
            regime_label="inactive",
            regime_weights={},
            er_value=0.5,
            improvement=-0.05,
            tercile_bounds=(0.3, 0.7),
            window_results=[],
            n_families=4,
        )
        scores = {"sma": 40.0, "rsi": 20.0, "macd": 0.0, "obv": -20.0}
        out = compute_regime_consensus(scores, regime)
        # Equal weight: (40+20+0-20)/4 = 10.0
        assert abs(out["final_consensus"] - 10.0) < 0.1
        assert out["regime_active"] is False

    def test_empty_scores(self):
        """No scores → None consensus."""
        regime = RegimeResult(
            regime_active=False, regime_label="inactive",
            regime_weights={}, er_value=None, improvement=0.0,
            tercile_bounds=(0.33, 0.67), window_results=[], n_families=0,
        )
        out = compute_regime_consensus({}, regime)
        assert out["final_consensus"] is None
