"""Tests for walk-forward calibration and Kelly sizing.

Critical invariant: calibration at trade i uses ONLY trades 0..i-1.
The peek detector verifies this by shuffling future trades and asserting output is unchanged.
"""
from __future__ import annotations

import random

import numpy as np
import pandas as pd
import pytest

from core.quant_core.research.exit_policy.paths import TradePath
from core.quant_core.research.exit_policy.calibrate import (
    walk_forward_c_params,
    compute_half_kelly,
    walk_forward_kelly,
    _MIN_CALIB_TRADES,
)


def _make_path(
    open_date: str,
    *,
    pnl_return: float = 0.02,
    mae: float = -0.01,
    mfe: float = 0.04,
    atr: float = 2.0,
    open_price: float = 100.0,
) -> TradePath:
    ts = pd.Timestamp(open_date)
    bars = pd.DataFrame(
        [{"Open": open_price, "High": open_price * (1 + mfe), "Low": open_price * (1 + mae), "Close": open_price * (1 + pnl_return)}],
        index=[ts],
    )
    return TradePath(
        symbol="TEST",
        direction=1.0,
        open_date=ts,
        close_date=ts + pd.Timedelta(days=5),
        open_price=open_price,
        close_price=open_price * (1 + pnl_return),
        pnl_return=pnl_return,
        bars=bars,
        atr_entry=atr,
        support=None,
        resistance=None,
        mae=mae,
        mfe=mfe,
    )


def _make_paths(n: int) -> list[TradePath]:
    """Generate n paths with alternating wins/losses, sorted by date."""
    paths = []
    for i in range(n):
        date = f"2023-01-{i+1:02d}" if i < 28 else f"2023-02-{i-27:02d}"
        pnl = 0.03 if i % 2 == 0 else -0.015
        mae = -0.012 if pnl > 0 else -0.025
        mfe = 0.035 if pnl > 0 else 0.010
        paths.append(_make_path(date, pnl_return=pnl, mae=mae, mfe=mfe))
    return sorted(paths, key=lambda p: p.open_date)


class TestWalkForwardCParams:
    def test_returns_defaults_for_early_trades(self):
        paths = _make_paths(30)
        k_values = walk_forward_c_params(paths, min_calib_trades=20)
        assert len(k_values) == 30
        # First 20 trades should use defaults
        from core.quant_core.research.exit_policy.calibrate import DEFAULT_K_SL, DEFAULT_K_TP
        for k_sl, k_tp in k_values[:20]:
            assert k_sl == DEFAULT_K_SL
            assert k_tp == DEFAULT_K_TP

    def test_calibration_kicks_in_after_min_trades(self):
        paths = _make_paths(40)
        k_values = walk_forward_c_params(paths, min_calib_trades=20)
        # After 20 trades, k values may differ from defaults
        assert all(0.5 <= k_sl <= 5.0 and 0.5 <= k_tp <= 5.0 for k_sl, k_tp in k_values)

    def test_peek_detector_future_shuffle_invariance(self):
        """Core no-look-ahead test: shuffling future trades must not change k[i].

        For each trade i, k[i] depends only on trades 0..i-1.
        After computing the canonical k_values, we shuffle trades i+1..n-1
        and recompute — k[i] must be identical.
        """
        paths = _make_paths(40)
        canonical = walk_forward_c_params(paths, min_calib_trades=15)

        rng = random.Random(42)
        for pivot in [15, 20, 30]:
            future_shuffled = list(paths[pivot:])
            rng.shuffle(future_shuffled)
            shuffled_paths = paths[:pivot] + future_shuffled
            shuffled_k = walk_forward_c_params(shuffled_paths, min_calib_trades=15)
            # k values at indices 0..pivot-1 must be identical
            for i in range(pivot):
                assert canonical[i] == shuffled_k[i], (
                    f"Peek detected at pivot={pivot} trade={i}: "
                    f"canonical={canonical[i]} shuffled={shuffled_k[i]}"
                )

    def test_min_sample_fallback(self):
        paths = _make_paths(5)
        k_values = walk_forward_c_params(paths, min_calib_trades=20)
        from core.quant_core.research.exit_policy.calibrate import DEFAULT_K_SL, DEFAULT_K_TP
        for k_sl, k_tp in k_values:
            assert k_sl == DEFAULT_K_SL
            assert k_tp == DEFAULT_K_TP

    def test_output_length_matches_input(self):
        for n in [0, 1, 10, 25]:
            paths = _make_paths(n)
            k_values = walk_forward_c_params(paths, min_calib_trades=5)
            assert len(k_values) == n


class TestHalfKelly:
    def test_zero_returns(self):
        f = compute_half_kelly([0.0] * 10)
        assert f == pytest.approx(0.01)  # all zeros → no wins, clamped to min

    def test_all_winners(self):
        f = compute_half_kelly([0.05] * 20)
        assert f == pytest.approx(0.01)  # no losses → clamped to min (no losses → can't compute b)

    def test_all_losers(self):
        f = compute_half_kelly([-0.02] * 20)
        assert f == pytest.approx(0.01)

    def test_mixed_returns_positive_edge(self):
        # Win rate=0.6, avg_win=0.04, avg_loss=0.02 → b=2; Kelly=(0.6*3-1)/2=0.4; half=0.2
        returns = [0.04] * 6 + [-0.02] * 4
        f = compute_half_kelly(returns)
        assert 0.01 <= f <= 0.5

    def test_clamped_max(self):
        # Very high edge → should clamp at 0.5
        returns = [0.10] * 10 + [-0.001] * 1
        f = compute_half_kelly(returns)
        assert f <= 0.5

    def test_empty_returns(self):
        f = compute_half_kelly([])
        assert f == pytest.approx(0.1)  # default initial


class TestWalkForwardKelly:
    def test_uses_initial_before_min_trades(self):
        returns = [0.02, -0.01, 0.03]
        fracs = walk_forward_kelly(returns, min_trades=5, initial=0.15)
        assert all(f == pytest.approx(0.15) for f in fracs)

    def test_adaptive_after_min_trades(self):
        returns = [0.02, -0.01, 0.03, 0.04, -0.02, 0.05, -0.01, 0.03]
        fracs = walk_forward_kelly(returns, min_trades=3, initial=0.1)
        assert len(fracs) == len(returns)
        # After index 3, fractions are computed adaptively
        for f in fracs[3:]:
            assert 0.01 <= f <= 0.5

    def test_length_matches_input(self):
        returns = list(range(20))
        fracs = walk_forward_kelly(returns)
        assert len(fracs) == 20
