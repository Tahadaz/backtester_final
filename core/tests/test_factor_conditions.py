"""Unit tests for core/quant_core/research/factors/conditions.py

Tests every condition form with known synthetic inputs:
  - zscore: fixed z-score relative to threshold
  - momentum: N-day percentage return
  - change: absolute N-day delta
  - level: raw value comparison
  - direction: 1-day sign

All tests verify:
  - Correct True/False mask on the valid portion
  - NaN positions → False (no look-ahead from NaN data)
  - Length preserved
"""
import numpy as np
import pytest

from core.quant_core.signal_engine.domain import FactorConditionMeta
from core.quant_core.research.factors.conditions import evaluate_condition


def _meta(form: str, lookback: int, threshold: float, direction: str) -> FactorConditionMeta:
    return FactorConditionMeta(
        condition_id=f"test_{form}",
        factor_ticker="TEST",
        form=form,
        lookback=lookback,
        threshold=threshold,
        direction=direction,
    )


# ---------------------------------------------------------------------------
# zscore
# ---------------------------------------------------------------------------

class TestZscoreCondition:
    def test_constant_series_nan_propagates_false(self):
        # Constant series → std=0 → z=NaN → condition is False (NaN-safe)
        x = np.ones(50)
        mask = evaluate_condition(_meta("zscore", 20, 1.0, "below"), x)
        assert mask.dtype == bool
        assert not mask.any()

    def test_varying_series_above_threshold(self):
        # Stable baseline near 0, single spike at last bar → z well above 3
        x = np.zeros(50, dtype=float)
        x[-1] = 50.0  # spike: mean≈0, std≈(50/sqrt(19)) small → z >> 3
        mask = evaluate_condition(_meta("zscore", 20, 3.0, "above"), x)
        assert mask.dtype == bool
        assert mask[-1]  # last bar spike is z >> 3

    def test_spike_above_triggers_true(self):
        # Normal distribution centred at 0 with σ=1; spike at end
        rng = np.random.default_rng(42)
        x = rng.normal(0, 1, 200)
        x[-1] = 10.0  # z > 3.0
        mask = evaluate_condition(_meta("zscore", 20, 3.0, "above"), x)
        assert mask[-1]

    def test_nan_safe(self):
        x = np.full(50, np.nan)
        mask = evaluate_condition(_meta("zscore", 20, 0.0, "above"), x)
        assert not mask.any()

    def test_length_preserved(self):
        x = np.arange(100, dtype=float)
        mask = evaluate_condition(_meta("zscore", 20, 0.0, "above"), x)
        assert len(mask) == 100


# ---------------------------------------------------------------------------
# momentum
# ---------------------------------------------------------------------------

class TestMomentumCondition:
    def test_uptrend_above_zero(self):
        # Monotonically increasing → 10d momentum > 0 → True
        x = np.arange(1, 101, dtype=float)
        mask = evaluate_condition(_meta("momentum", 10, 0.0, "above"), x)
        assert mask[10:].all()

    def test_downtrend_below_zero(self):
        # Monotonically decreasing → 10d momentum < 0 → True
        x = np.arange(100, 0, -1, dtype=float)
        mask = evaluate_condition(_meta("momentum", 10, 0.0, "below"), x)
        assert mask[10:].all()

    def test_warmup_false(self):
        x = np.arange(1, 101, dtype=float)
        mask = evaluate_condition(_meta("momentum", 10, 0.0, "above"), x)
        assert not mask[:10].any()

    def test_exact_threshold(self):
        # returns == threshold (0.0 exactly) → above is False
        x = np.ones(50)
        mask = evaluate_condition(_meta("momentum", 5, 0.0, "above"), x)
        assert not mask.any()


# ---------------------------------------------------------------------------
# change
# ---------------------------------------------------------------------------

class TestChangeCondition:
    def test_rising_yield_shock(self):
        # Simulated 5d yield rise > 0.002 (20 bp)
        x = np.zeros(30)
        x[20:] = np.cumsum(np.full(10, 0.0005))  # 5-day change = 0.0025
        mask = evaluate_condition(_meta("change", 5, 0.002, "above"), x)
        assert mask[25:].all()

    def test_below(self):
        x = np.zeros(30)
        x[:] = -0.001  # 5-day change = -0.005
        # x is constant, so delta = 0 everywhere, not below 0.002
        mask = evaluate_condition(_meta("change", 5, 0.002, "below"), x)
        assert mask[5:].all()  # 0 < 0.002 → True

    def test_nan_safe(self):
        x = np.full(30, np.nan)
        mask = evaluate_condition(_meta("change", 5, 0.0, "above"), x)
        assert not mask.any()


# ---------------------------------------------------------------------------
# level
# ---------------------------------------------------------------------------

class TestLevelCondition:
    def test_vix_above_30(self):
        x = np.array([20.0, 25.0, 31.0, 28.0])
        mask = evaluate_condition(_meta("level", 1, 30.0, "above"), x)
        assert list(mask) == [False, False, True, False]

    def test_all_below(self):
        x = np.array([1.0, 2.0, 3.0])
        mask = evaluate_condition(_meta("level", 1, 5.0, "below"), x)
        assert mask.all()

    def test_nan_safe(self):
        x = np.array([np.nan, 5.0, np.nan])
        mask = evaluate_condition(_meta("level", 1, 3.0, "above"), x)
        assert list(mask) == [False, True, False]


# ---------------------------------------------------------------------------
# direction
# ---------------------------------------------------------------------------

class TestDirectionCondition:
    def test_upward_ticks(self):
        x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        mask = evaluate_condition(_meta("direction", 1, 0.0, "above"), x)
        # delta[0] = nan, delta[1:] > 0
        assert not mask[0]
        assert mask[1:].all()

    def test_downward_ticks(self):
        x = np.array([5.0, 4.0, 3.0, 2.0, 1.0])
        mask = evaluate_condition(_meta("direction", 1, 0.0, "below"), x)
        assert not mask[0]
        assert mask[1:].all()

    def test_flat_not_above(self):
        x = np.ones(5)
        mask = evaluate_condition(_meta("direction", 1, 0.0, "above"), x)
        # delta = 0, not > 0
        assert not mask.any()


# ---------------------------------------------------------------------------
# invalid form
# ---------------------------------------------------------------------------

def test_invalid_form_raises():
    x = np.ones(10)
    with pytest.raises(ValueError, match="Unknown condition form"):
        evaluate_condition(_meta("nonexistent", 1, 0.0, "above"), x)
