from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.quant_core.signal_engine.sr_ict import (
    detect_fair_value_gaps,
    detect_liquidity_pools,
    detect_order_blocks,
    prior_period_extremes,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _flat_ohlcv(n: int, base: float = 100.0):
    close = np.full(n, base, dtype="float64")
    high = close + 1.0
    low = close - 1.0
    open_ = close.copy()
    return open_, high, low, close


# ---------------------------------------------------------------------------
# 1. liquidity pools (equal highs / equal lows)
# ---------------------------------------------------------------------------


def test_liquidity_pools_detects_equal_highs_cluster():
    n = 60
    open_, high, low, close = _flat_ohlcv(n)
    # plant two swing highs at nearly the same price (equal highs -> BSL)
    for center, price in ((15, 110.0), (35, 110.2)):
        high[center] = price
        low[center] = price - 2.0
        close[center] = price - 0.5
        for off in range(1, 4):
            high[center - off] = 105.0
            high[center + off] = 105.0

    result = detect_liquidity_pools(high, low, close, left_bars=3, right_bars=3, atr_tol_mult=2.0, lookback=60)
    assert result["resistances"], "expected at least one clustered resistance"
    top = result["resistances"][0]
    assert top["strength"] >= 2
    assert 109.0 <= top["price"] <= 111.0


def test_liquidity_pools_confirmation_bar_not_before_right_bars():
    n = 40
    open_, high, low, close = _flat_ohlcv(n)
    pivot_idx = 20
    high[pivot_idx] = 120.0
    low[pivot_idx] = 118.0
    for off in range(1, 4):
        high[pivot_idx - off] = 105.0
        high[pivot_idx + off] = 105.0

    result = detect_liquidity_pools(high, low, close, left_bars=3, right_bars=3, atr_tol_mult=0.0, lookback=40)
    assert result["resistances"]
    entry = result["resistances"][0]
    # the pivot at index 20 can only be confirmed once the right_bars=3 window exists,
    # i.e. at bar_index >= 20 + 3 = 23. A leaking implementation would report 20.
    assert entry["bar_index"] >= pivot_idx + 3


def test_liquidity_pools_no_lookahead_future_mutation_does_not_change_past_result():
    n = 60
    open_, high, low, close = _flat_ohlcv(n)
    high[15] = 110.0
    low[15] = 108.0
    for off in range(1, 4):
        high[15 - off] = 105.0
        high[15 + off] = 105.0

    causal_slice = slice(0, 25)
    result_before = detect_liquidity_pools(
        high[causal_slice], low[causal_slice], close[causal_slice], left_bars=3, right_bars=3, lookback=60
    )

    # mutate data far in the future (beyond the causal slice) and recompute on the
    # same causal slice: result must be identical.
    high_mut = high.copy()
    high_mut[50:] = 999.0
    result_after = detect_liquidity_pools(
        high_mut[causal_slice], low[causal_slice], close[causal_slice], left_bars=3, right_bars=3, lookback=60
    )
    assert result_before["resistances"] == result_after["resistances"]
    assert result_before["supports"] == result_after["supports"]


# ---------------------------------------------------------------------------
# 2. order blocks
# ---------------------------------------------------------------------------


def test_bullish_order_block_detected_after_displacement():
    n = 40
    open_, high, low, close = _flat_ohlcv(n, base=100.0)
    ob_idx = 20
    # down-close candle: origin of the bullish order block
    open_[ob_idx] = 101.0
    close[ob_idx] = 99.0
    high[ob_idx] = 101.5
    low[ob_idx] = 98.5
    # strong up displacement over the next 2 bars, breaking structure above high[ob_idx]
    open_[ob_idx + 1] = 99.0
    close[ob_idx + 1] = 108.0
    high[ob_idx + 1] = 108.5
    low[ob_idx + 1] = 99.0

    result = detect_order_blocks(open_, high, low, close, displacement_atr_mult=1.5, lookback=40)
    assert result["supports"], "expected a bullish order block support level"
    top = result["supports"][0]
    assert top["price"] == pytest.approx(low[ob_idx], abs=0.01)
    # causality: must be confirmed at the displacement bar, never at the origin candle itself
    assert top["bar_index"] == ob_idx + 1
    assert top["bar_index"] > ob_idx


def test_bearish_order_block_detected_after_displacement():
    n = 40
    open_, high, low, close = _flat_ohlcv(n, base=100.0)
    ob_idx = 20
    open_[ob_idx] = 99.0
    close[ob_idx] = 101.0
    high[ob_idx] = 101.5
    low[ob_idx] = 98.5
    open_[ob_idx + 1] = 101.0
    close[ob_idx + 1] = 92.0
    high[ob_idx + 1] = 101.0
    low[ob_idx + 1] = 91.5

    result = detect_order_blocks(open_, high, low, close, displacement_atr_mult=1.5, lookback=40)
    assert result["resistances"], "expected a bearish order block resistance level"
    top = result["resistances"][0]
    assert top["price"] == pytest.approx(high[ob_idx], abs=0.01)
    assert top["bar_index"] == ob_idx + 1


def test_order_block_not_reported_without_sufficient_displacement():
    n = 40
    open_, high, low, close = _flat_ohlcv(n, base=100.0)
    ob_idx = 20
    open_[ob_idx] = 100.5
    close[ob_idx] = 99.5
    high[ob_idx] = 100.7
    low[ob_idx] = 99.3
    # only a tiny up-move afterwards -> should not qualify as displacement
    open_[ob_idx + 1] = 99.5
    close[ob_idx + 1] = 100.0
    high[ob_idx + 1] = 100.2
    low[ob_idx + 1] = 99.4

    result = detect_order_blocks(open_, high, low, close, displacement_atr_mult=1.5, lookback=40)
    assert not any(s["bar_index"] == ob_idx + 1 for s in result["supports"])


# ---------------------------------------------------------------------------
# 3. fair value gaps
# ---------------------------------------------------------------------------


def test_bullish_fvg_detected_with_correct_midpoint_and_confirmation_bar():
    n = 30
    open_, high, low, close = _flat_ohlcv(n, base=100.0)
    i = 15
    high[i - 1] = 100.5
    low[i + 1] = 106.0  # gap between high[i-1] and low[i+1]
    high[i + 1] = 106.5
    low[i - 1] = 99.5
    close[-1] = 110.0  # current close above the gap midpoint so it qualifies as support

    result = detect_fair_value_gaps(high, low, close, min_gap_atr_mult=0.1, lookback=30)
    assert result["supports"], "expected a bullish FVG support level"
    top = result["supports"][0]
    expected_mid = (high[i - 1] + low[i + 1]) / 2.0
    assert top["price"] == pytest.approx(expected_mid, abs=0.01)
    # confirmed only once the 3rd candle (i+1) exists
    assert top["bar_index"] == i + 1


def test_bearish_fvg_detected():
    n = 30
    open_, high, low, close = _flat_ohlcv(n, base=100.0)
    i = 15
    low[i - 1] = 106.0
    high[i + 1] = 100.5
    high[i - 1] = 106.5
    low[i + 1] = 99.5

    result = detect_fair_value_gaps(high, low, close, min_gap_atr_mult=0.1, lookback=30)
    assert result["resistances"], "expected a bearish FVG resistance level"
    top = result["resistances"][0]
    expected_mid = (low[i - 1] + high[i + 1]) / 2.0
    assert top["price"] == pytest.approx(expected_mid, abs=0.01)
    assert top["bar_index"] == i + 1


def test_fvg_below_min_gap_atr_mult_is_ignored():
    n = 30
    open_, high, low, close = _flat_ohlcv(n, base=100.0)
    i = 15
    # tiny gap, far below the ATR-scaled threshold
    high[i - 1] = 100.05
    low[i + 1] = 100.10

    result = detect_fair_value_gaps(high, low, close, min_gap_atr_mult=5.0, lookback=30)
    assert not any(s["bar_index"] == i + 1 for s in result["supports"])


# ---------------------------------------------------------------------------
# 4. prior period extremes
# ---------------------------------------------------------------------------


def test_prior_period_extremes_monthly_uses_only_completed_prior_month():
    dates = pd.date_range("2024-01-01", periods=70, freq="D")
    high = np.linspace(100.0, 170.0, len(dates))
    low = high - 2.0

    result = prior_period_extremes(dates, high, low, period="M")
    prior_high = result["prior_high"]
    prior_low = result["prior_low"]

    jan_high_actual = float(np.max(high[dates.month == 1]))
    jan_low_actual = float(np.min(low[dates.month == 1]))

    feb_mask = dates.month == 2
    # every bar in February must see January's fully-completed extreme
    assert np.all(prior_high[feb_mask] == pytest.approx(jan_high_actual))
    assert np.all(prior_low[feb_mask] == pytest.approx(jan_low_actual))

    # January bars have no completed prior month -> NaN
    jan_mask = dates.month == 1
    assert np.all(np.isnan(prior_high[jan_mask]))


def test_prior_period_extremes_no_lookahead_future_mutation_does_not_change_past():
    dates = pd.date_range("2024-01-01", periods=70, freq="D")
    high = np.linspace(100.0, 170.0, len(dates))
    low = high - 2.0

    result_before = prior_period_extremes(dates, high, low, period="M")

    high_mut = high.copy()
    # mutate March (should not affect February's "prior period" value, which is January)
    march_mask = dates.month == 3
    high_mut[march_mask] = 9999.0

    result_after = prior_period_extremes(dates, high_mut, low, period="M")
    feb_mask = dates.month == 2
    assert np.allclose(
        result_before["prior_high"][feb_mask],
        result_after["prior_high"][feb_mask],
        equal_nan=True,
    )


def test_prior_period_extremes_weekly_period():
    dates = pd.date_range("2024-01-01", periods=21, freq="D")
    high = np.linspace(50.0, 70.0, len(dates))
    low = high - 1.0

    result = prior_period_extremes(dates, high, low, period="W")
    assert result["prior_high"].shape == (21,)
    # last bar's "latest" snapshot should be finite once at least one full week has passed
    assert result["latest"]["prior_high"] is not None
