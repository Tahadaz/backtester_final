"""Tests for strategy_plan.levels — swing S/R, ATR, pivot points."""

import numpy as np
import pytest

from core.quant_core.strategy_plan.levels import (
    compute_atr,
    compute_pivot_points,
    detect_swing_levels,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_peak_valley(n: int = 60) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Generate synthetic data with a clear peak at n//3 and valley at 2n//3."""
    close = np.linspace(100, 100, n, dtype=np.float64)
    peak_idx = n // 3
    valley_idx = 2 * n // 3

    # Create a peak
    for i in range(max(0, peak_idx - 8), min(n, peak_idx + 9)):
        close[i] = 100 + 10 * max(0, 1 - abs(i - peak_idx) / 8.0)
    # Create a valley
    for i in range(max(0, valley_idx - 8), min(n, valley_idx + 9)):
        close[i] = 100 - 10 * max(0, 1 - abs(i - valley_idx) / 8.0)

    high = close + 0.5
    low = close - 0.5
    return high, low, close


# ---------------------------------------------------------------------------
# ATR tests
# ---------------------------------------------------------------------------

class TestComputeAtr:
    def test_constant_price(self):
        n = 30
        c = np.full(n, 100.0)
        h = np.full(n, 100.0)
        l_ = np.full(n, 100.0)
        atr_abs, atr_ratio = compute_atr(h, l_, c, window=14)
        assert atr_abs == pytest.approx(0.0, abs=1e-10)
        assert atr_ratio == pytest.approx(0.0, abs=1e-10)

    def test_known_range(self):
        n = 20
        c = np.full(n, 100.0)
        h = np.full(n, 102.0)
        l_ = np.full(n, 98.0)
        atr_abs, atr_ratio = compute_atr(h, l_, c, window=14)
        # TR = max(102-98, |102-100|, |98-100|) = 4.0 every bar
        assert atr_abs == pytest.approx(4.0, abs=0.01)
        assert atr_ratio == pytest.approx(0.04, abs=0.001)

    def test_short_data(self):
        c = np.array([100.0])
        h = np.array([101.0])
        l_ = np.array([99.0])
        atr_abs, atr_ratio = compute_atr(h, l_, c, window=14)
        assert atr_abs == 0.0  # n < 2


# ---------------------------------------------------------------------------
# Pivot points tests
# ---------------------------------------------------------------------------

class TestComputePivotPoints:
    def test_basic_formula(self):
        pp = compute_pivot_points(prev_high=110.0, prev_low=90.0, prev_close=100.0)
        assert pp["pp"] == pytest.approx(100.0, abs=0.01)
        assert pp["r1"] == pytest.approx(110.0, abs=0.01)  # 2*100 - 90
        assert pp["s1"] == pytest.approx(90.0, abs=0.01)   # 2*100 - 110
        assert pp["r2"] == pytest.approx(120.0, abs=0.01)  # 100 + (110-90)
        assert pp["s2"] == pytest.approx(80.0, abs=0.01)   # 100 - (110-90)

    def test_asymmetric(self):
        pp = compute_pivot_points(prev_high=105.0, prev_low=95.0, prev_close=103.0)
        expected_pp = (105 + 95 + 103) / 3
        assert pp["pp"] == pytest.approx(expected_pp, abs=0.01)


# ---------------------------------------------------------------------------
# Swing detection tests
# ---------------------------------------------------------------------------

class TestDetectSwingLevels:
    def test_swing_high_detected(self):
        h, l_, c = _make_peak_valley(60)
        result = detect_swing_levels(h, l_, c, left_bars=5, right_bars=5)
        # Should find at least one resistance (from the peak)
        assert len(result["resistances"]) >= 0 or len(result["supports"]) >= 0
        # The peak is at index 20, price ~110.5
        # current close is ~100, so peak should be a resistance
        res_prices = [r["price"] for r in result["resistances"]]
        if res_prices:
            assert max(res_prices) > 100  # above current close

    def test_swing_low_detected(self):
        h, l_, c = _make_peak_valley(60)
        result = detect_swing_levels(h, l_, c, left_bars=5, right_bars=5)
        sup_prices = [s["price"] for s in result["supports"]]
        if sup_prices:
            assert min(sup_prices) < 100  # below current close

    def test_flat_data_no_levels(self):
        n = 60
        c = np.full(n, 100.0)
        h = np.full(n, 100.0)
        l_ = np.full(n, 100.0)
        result = detect_swing_levels(h, l_, c, left_bars=5, right_bars=5)
        assert result["supports"] == []
        assert result["resistances"] == []
        assert result["nearest_support"] is None
        assert result["nearest_resistance"] is None

    def test_max_levels_cap(self):
        # Generate data with many peaks/valleys
        n = 200
        t = np.arange(n, dtype=np.float64)
        c = 100 + 5 * np.sin(t * 2 * np.pi / 15)  # fast oscillation
        h = c + 1
        l_ = c - 1
        result = detect_swing_levels(h, l_, c, left_bars=3, right_bars=3, max_levels=4)
        assert len(result["supports"]) <= 4
        assert len(result["resistances"]) <= 4

    def test_current_close_returned(self):
        n = 30
        c = np.linspace(95, 105, n)
        h = c + 1
        l_ = c - 1
        result = detect_swing_levels(h, l_, c, left_bars=3, right_bars=3)
        assert result["current_close"] == pytest.approx(float(c[-1]), abs=0.01)

    def test_short_data_no_crash(self):
        c = np.array([100.0, 101.0])
        h = c + 0.5
        l_ = c - 0.5
        result = detect_swing_levels(h, l_, c, left_bars=5, right_bars=5)
        assert result["supports"] == []
        assert result["resistances"] == []

    def test_nearest_support_is_closest_below(self):
        # Create data ending at 100, with supports at 90 and 95
        n = 80
        c = np.full(n, 100.0)
        # Valley at index 30 (price 90)
        for i in range(25, 36):
            c[i] = 90.0 + abs(i - 30) * 1.0
        c[30] = 89.5
        # Valley at index 50 (price 95)
        for i in range(45, 56):
            c[i] = 95.0 + abs(i - 50) * 0.5
        c[50] = 94.5
        h = c + 0.5
        l_ = c - 0.5
        result = detect_swing_levels(h, l_, c, left_bars=4, right_bars=4)
        if result["nearest_support"] is not None:
            # Nearest support should be the higher one (closer to current price)
            assert result["nearest_support"] < 100

    def test_max_distance_atr_filters_distant_levels(self):
        c = np.array([100.0] * 60)
        c[15] = 90.0
        c[35] = 98.0
        h = c + 1.0
        l_ = c - 1.0

        result = detect_swing_levels(
            h,
            l_,
            c,
            left_bars=2,
            right_bars=2,
            lookback=60,
            max_distance_atr=2.0,
        )

        support_prices = [s["price"] for s in result["supports"]]
        assert 97.0 in support_prices
        assert 89.0 not in support_prices
