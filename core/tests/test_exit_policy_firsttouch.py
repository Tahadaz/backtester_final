"""Tests for the conservative daily first-touch rule and policy simulators A-E.

Invariants verified:
  - Gap-down through stop → fill at open, stop_loss
  - Gap-up through TP → fill at open, take_profit
  - Both barriers in range same bar → stop first
  - Single stop touch → fill at stop level
  - Single TP touch → fill at TP level
  - No touch through path → signal_exit at natural exit
  - Short positions mirror long positions correctly
"""
from __future__ import annotations

import pandas as pd
import pytest

from core.quant_core.research.exit_policy.paths import TradePath
from core.quant_core.research.exit_policy.policies import (
    simulate_A, simulate_B, simulate_C, simulate_D, simulate_E,
    _first_touch,
)


def _bars(*rows: tuple[float, float, float, float], start: str = "2024-01-01") -> pd.DataFrame:
    """Build a minimal OHLC DataFrame from (open, high, low, close) tuples."""
    dates = pd.date_range(start, periods=len(rows), freq="B")
    return pd.DataFrame(
        [{"Open": o, "High": h, "Low": l, "Close": c} for o, h, l, c in rows],
        index=dates,
    )


def _path(
    bars: pd.DataFrame,
    *,
    direction: float = 1.0,
    open_price: float = 100.0,
    close_price: float = 105.0,
    pnl_return: float = 0.05,
    atr: float = 2.0,
    support: float | None = None,
    resistance: float | None = None,
) -> TradePath:
    mae = ((bars["Low"].min() - open_price) / open_price) if direction > 0 else ((open_price - bars["High"].max()) / open_price)
    mfe = ((bars["High"].max() - open_price) / open_price) if direction > 0 else ((open_price - bars["Low"].min()) / open_price)
    return TradePath(
        symbol="TEST",
        direction=direction,
        open_date=bars.index[0],
        close_date=bars.index[-1],
        open_price=open_price,
        close_price=close_price,
        pnl_return=pnl_return,
        bars=bars,
        atr_entry=atr,
        support=support,
        resistance=resistance,
        mae=mae,
        mfe=mfe,
    )


# ── _first_touch unit tests ───────────────────────────────────────────────────

class TestFirstTouch:
    def _call(self, bars, *, direction=1.0, stop=None, tp=None, nat_date=None, nat_price=105.0):
        nat = nat_date or bars.index[-1]
        return _first_touch(
            bars,
            direction=direction,
            stop=stop,
            take_profit=tp,
            natural_exit_date=nat,
            natural_exit_price=nat_price,
        )

    def test_gap_down_stop_long(self):
        # Entry at 100; stop at 95; bar opens at 90 (gap below stop)
        bars = _bars((90.0, 92.0, 88.0, 91.0))
        ep, ed, er = self._call(bars, direction=1.0, stop=95.0, tp=110.0)
        assert er == "stop_loss"
        assert ep == pytest.approx(90.0)  # gap → fill at open

    def test_gap_up_tp_long(self):
        # Entry at 100; TP at 110; bar opens at 115 (gap above TP)
        bars = _bars((115.0, 118.0, 113.0, 116.0))
        ep, ed, er = self._call(bars, direction=1.0, stop=95.0, tp=110.0)
        assert er == "take_profit"
        assert ep == pytest.approx(115.0)

    def test_both_in_range_stop_first_long(self):
        # Bar range spans both stop and TP → stop fires first (pessimistic)
        bars = _bars((100.0, 115.0, 90.0, 102.0))
        ep, ed, er = self._call(bars, direction=1.0, stop=95.0, tp=110.0)
        assert er == "stop_loss"
        assert ep == pytest.approx(95.0)

    def test_single_stop_touch_long(self):
        bars = _bars((100.0, 104.0, 94.0, 102.0))
        ep, ed, er = self._call(bars, direction=1.0, stop=95.0, tp=110.0)
        assert er == "stop_loss"
        assert ep == pytest.approx(95.0)

    def test_single_tp_touch_long(self):
        bars = _bars((100.0, 112.0, 99.0, 110.0))
        ep, ed, er = self._call(bars, direction=1.0, stop=95.0, tp=110.0)
        assert er == "take_profit"
        assert ep == pytest.approx(110.0)

    def test_no_touch_returns_natural(self):
        bars = _bars((100.0, 108.0, 98.0, 105.0))
        nat_date = bars.index[-1]
        ep, ed, er = self._call(bars, direction=1.0, stop=90.0, tp=120.0, nat_date=nat_date, nat_price=105.0)
        assert er == "time_exit"
        assert ep == pytest.approx(105.0)

    def test_signal_exit_after_bars_exhausted(self):
        # Natural exit date is beyond all bars
        bars = _bars((100.0, 108.0, 98.0, 105.0))
        future = bars.index[-1] + pd.Timedelta(days=10)
        ep, ed, er = self._call(bars, direction=1.0, stop=90.0, tp=120.0, nat_date=future, nat_price=108.0)
        assert er == "signal_exit"
        assert ep == pytest.approx(108.0)

    # ── Short mirror tests ────────────────────────────────────────────────────

    def test_gap_up_stop_short(self):
        # Short; stop above entry; bar gaps UP through stop
        bars = _bars((115.0, 118.0, 113.0, 116.0))
        ep, ed, er = self._call(bars, direction=-1.0, stop=110.0, tp=90.0)
        assert er == "stop_loss"
        assert ep == pytest.approx(115.0)

    def test_gap_down_tp_short(self):
        # Short; TP below entry; bar gaps DOWN through TP
        bars = _bars((85.0, 87.0, 83.0, 86.0))
        ep, ed, er = self._call(bars, direction=-1.0, stop=110.0, tp=90.0)
        assert er == "take_profit"
        assert ep == pytest.approx(85.0)

    def test_both_in_range_stop_first_short(self):
        # Short; bar range spans both stop (above) and TP (below) → stop first
        bars = _bars((100.0, 115.0, 85.0, 100.0))
        ep, ed, er = self._call(bars, direction=-1.0, stop=110.0, tp=90.0)
        assert er == "stop_loss"
        assert ep == pytest.approx(110.0)

    def test_multi_bar_first_touch(self):
        # Stop not hit on first bar; hit on second bar
        bars = _bars(
            (100.0, 108.0, 97.0, 103.0),  # bar 1: low=97 > stop=95, no hit
            (100.0, 101.0, 93.0, 98.0),   # bar 2: low=93 < stop=95, hit
        )
        ep, ed, er = self._call(bars, direction=1.0, stop=95.0, tp=115.0)
        assert er == "stop_loss"
        assert ep == pytest.approx(95.0)
        assert ed == bars.index[1]


# ── Policy A ─────────────────────────────────────────────────────────────────

class TestPolicyA:
    def test_returns_stored_pnl(self):
        bars = _bars((100.0, 108.0, 98.0, 105.0))
        path = _path(bars, pnl_return=0.05)
        result = simulate_A(path)
        assert result.effective_return == pytest.approx(0.05)
        assert result.exit_reason == "signal_exit"

    def test_returns_negative_stored_pnl(self):
        bars = _bars((100.0, 102.0, 92.0, 95.0))
        path = _path(bars, pnl_return=-0.05)
        result = simulate_A(path)
        assert result.effective_return == pytest.approx(-0.05)


# ── Policy B ─────────────────────────────────────────────────────────────────

class TestPolicyB:
    def test_stop_fires_before_natural_exit(self):
        # stop=97 (100-1.5*2), tp=103 (100+1.5*2)
        # Bar 1: high=102 < tp, low=98 > stop → no touch
        # Bar 2: low=93 < stop=97 → stop_loss
        bars = _bars(
            (100.0, 102.0, 98.0, 101.0),    # bar 1: no touch
            (100.0, 101.0, 93.0, 95.0),     # bar 2: low 93 < stop 97 → stop
        )
        path = _path(bars, atr=2.0, open_price=100.0)
        result = simulate_B(path, k_sl=1.5, k_tp=1.5)
        assert result.exit_reason == "stop_loss"
        assert result.effective_return < 0.0

    def test_tp_fires(self):
        bars = _bars(
            (100.0, 104.0, 99.0, 103.0),    # bar 1: high=104 > tp=103 = 100+1.5*2
        )
        path = _path(bars, atr=2.0, open_price=100.0)
        result = simulate_B(path, k_sl=1.5, k_tp=1.5)
        assert result.exit_reason == "take_profit"
        assert result.effective_return > 0.0

    def test_zero_atr_falls_back_to_natural(self):
        bars = _bars((100.0, 105.0, 98.0, 104.0))
        path = _path(bars, atr=0.0, pnl_return=0.04)
        result = simulate_B(path)
        assert result.exit_reason == "signal_exit"
        assert result.effective_return == pytest.approx(0.04)


# ── Policy D ─────────────────────────────────────────────────────────────────

class TestPolicyD:
    def test_uses_sr_levels(self):
        # support=96, resistance=108, entry=100
        bars = _bars(
            (100.0, 107.0, 99.0, 106.0),
            (100.0, 109.0, 100.0, 108.0),  # high reaches resistance=108
        )
        path = _path(bars, support=96.0, resistance=108.0, open_price=100.0)
        result = simulate_D(path)
        assert result.exit_reason == "take_profit"
        assert result.exit_price == pytest.approx(108.0)

    def test_degenerate_sr_fallback(self):
        # support > entry → degenerate for long
        bars = _bars((100.0, 105.0, 98.0, 103.0))
        path = _path(bars, support=102.0, resistance=115.0, open_price=100.0, pnl_return=0.03)
        result = simulate_D(path)
        assert result.exit_reason == "signal_exit"

    def test_no_sr_fallback(self):
        bars = _bars((100.0, 105.0, 98.0, 103.0))
        path = _path(bars, support=None, resistance=None, pnl_return=0.03)
        result = simulate_D(path)
        assert result.exit_reason == "signal_exit"
        assert result.effective_return == pytest.approx(0.03)


# ── Policy E ─────────────────────────────────────────────────────────────────

class TestPolicyE:
    def test_snaps_tp_down_to_resistance(self):
        # ATR=2; tp_atr = 103. Resistance=101 is inside (100, 103) → snap down.
        bars = _bars(
            (100.0, 102.0, 99.0, 101.0),  # high=102 > resistance=101 → TP fires
        )
        path = _path(bars, atr=2.0, support=96.0, resistance=101.0, open_price=100.0)
        result = simulate_E(path, k_sl=1.5, k_tp=1.5)
        assert result.exit_reason == "take_profit"
        assert result.exit_price == pytest.approx(101.0)

    def test_snaps_stop_up_to_support(self):
        # ATR=2; stop_atr = 97. Support=98.5 is inside (97, 100) → snap up.
        bars = _bars(
            (100.0, 102.0, 98.0, 101.0),  # low=98 < support=98.5 → stop fires
        )
        path = _path(bars, atr=2.0, support=98.5, resistance=106.0, open_price=100.0)
        result = simulate_E(path, k_sl=1.5, k_tp=1.5)
        assert result.exit_reason == "stop_loss"
        assert result.exit_price == pytest.approx(98.5)

    def test_no_snap_when_sr_outside_bracket(self):
        # Resistance=110 > tp_atr=103; support=90 < stop_atr=97 → no snapping
        bars = _bars((100.0, 102.0, 99.0, 101.0))
        path = _path(bars, atr=2.0, support=90.0, resistance=110.0, open_price=100.0, pnl_return=0.01)
        result_b = simulate_B(path, k_sl=1.5, k_tp=1.5)
        result_e = simulate_E(path, k_sl=1.5, k_tp=1.5)
        # E should behave identically to B when S/R is outside the bracket
        assert result_b.exit_reason == result_e.exit_reason
        assert result_b.effective_return == pytest.approx(result_e.effective_return)

    def test_min_rr_floor_prevents_degenerate_snap(self):
        # Support=99.9 is very close to entry 100 — below min floor (0.5*2=1.0)
        bars = _bars((100.0, 108.0, 99.5, 106.0))
        path = _path(bars, atr=2.0, support=99.9, resistance=106.0, open_price=100.0, pnl_return=0.06)
        result = simulate_E(path, k_sl=1.5, k_tp=1.5, min_rr_atr_mult=0.5)
        # Stop should NOT snap to 99.9 (distance=0.1 < floor=1.0); use ATR stop=97.0
        # ATR stop=97.0, ATR tp=103.0; high=108 > 103 → tp fires
        assert result.exit_reason == "take_profit"
