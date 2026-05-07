"""Tests for core/quant_core/research/factors/signals.py — Phase 1.

All tests use synthetic pd.Series with a pd.date_range index.
No parquet, no DB, no network calls.
"""
import math

import numpy as np
import pandas as pd
import pytest

from quant_core.research.factors.signals import (
    REGISTERED_FACTOR_SIGNALS,
    FactorSignalSpec,
    brent_direction_signal,
    compute_all_factor_signals,
    compute_factor_signal,
    dxy_momentum_signal,
    eurusd_momentum_signal,
    is_applicable,
    sp500_vix_confirmation_signal,
    us10y_shock_signal,
    vix_zscore_signal,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_series(values, freq="B"):
    idx = pd.date_range("2020-01-01", periods=len(values), freq=freq)
    return pd.Series(values, index=idx, dtype=float)


def _const(n: int, v: float) -> pd.Series:
    return _make_series([v] * n)


# ---------------------------------------------------------------------------
# VIX z-score
# ---------------------------------------------------------------------------

def test_vix_zscore_long_regime():
    # Constant-low VIX: z-score is 0 (std=0), but in practice low VIX below mean
    # Use a series where the last value is much lower than the rolling mean
    base = [20.0] * 19 + [10.0]  # last value 2 std below mean
    vix = _make_series(base)
    sig = vix_zscore_signal(vix, window=20, z_long=-1.0, z_short=2.0)
    # After window fills (bar 20), z should be strongly negative → +1
    assert sig.iloc[-1] == 1.0


def test_vix_zscore_short_regime():
    base = [15.0] * 19 + [40.0]  # spike much above mean
    vix = _make_series(base)
    sig = vix_zscore_signal(vix, window=20, z_long=-1.0, z_short=2.0)
    assert sig.iloc[-1] == -1.0


def test_vix_zscore_neutral_band():
    # Uniform ±0.3 noise has max |z| ≈ √3 ≈ 1.73. Use extreme thresholds (-5, +5)
    # to ensure the band is never crossed — proving z=0 logic is correct.
    rng = np.random.default_rng(42)
    base = list(20.0 + rng.uniform(-0.3, 0.3, size=60))
    vix = _make_series(base)
    sig = vix_zscore_signal(vix, window=20, z_long=-5.0, z_short=5.0)
    non_nan = sig.dropna()
    assert (non_nan == 0.0).all(), f"Expected all 0, got unique values: {non_nan.unique()}"


def test_vix_zscore_short_window():
    # Series shorter than window → all NaN
    vix = _make_series([15.0] * 10)
    sig = vix_zscore_signal(vix, window=20)
    assert sig.isna().all()


# ---------------------------------------------------------------------------
# DXY momentum
# ---------------------------------------------------------------------------

def test_dxy_momentum_falling():
    # Monotone-falling DXY: 20d momentum < 0 → +1
    dxy = _make_series(list(np.linspace(105, 90, 40)))
    sig = dxy_momentum_signal(dxy, window=20)
    non_nan = sig.dropna()
    assert (non_nan == 1.0).all()


def test_dxy_momentum_rising():
    # Monotone-rising DXY: 20d momentum > 0 → -1
    dxy = _make_series(list(np.linspace(90, 105, 40)))
    sig = dxy_momentum_signal(dxy, window=20)
    non_nan = sig.dropna()
    assert (non_nan == -1.0).all()


# ---------------------------------------------------------------------------
# Brent direction
# ---------------------------------------------------------------------------

def test_brent_direction_up():
    brent = _make_series(list(np.linspace(80, 90, 20)))
    sig = brent_direction_signal(brent, window=5)
    non_nan = sig.dropna()
    assert (non_nan == 1.0).all()


# ---------------------------------------------------------------------------
# SP500 + VIX confirmation
# ---------------------------------------------------------------------------

def test_sp500_vix_both_satisfied():
    # SP500 rising, VIX low and stable → z < 1 → +1
    n = 30
    sp500 = _make_series(list(np.linspace(4000, 4200, n)))
    vix = _make_series([15.0] * n)
    sig = sp500_vix_confirmation_signal(sp500, vix, sp500_window=5, vix_window=20, vix_z_cap=1.0)
    non_nan = sig.dropna()
    assert (non_nan == 1.0).all()


def test_sp500_vix_blocked_by_vix():
    # SP500 rising but VIX spikes → z >> 1 → 0
    n = 30
    sp500 = _make_series(list(np.linspace(4000, 4200, n)))
    # Last bar VIX spikes far above the rolling mean
    vix_vals = [15.0] * (n - 1) + [80.0]
    vix = _make_series(vix_vals)
    sig = sp500_vix_confirmation_signal(sp500, vix, sp500_window=5, vix_window=20, vix_z_cap=1.0)
    assert sig.iloc[-1] == 0.0


# ---------------------------------------------------------------------------
# US10Y shock
# ---------------------------------------------------------------------------

def test_us10y_shock_triggers():
    # 5d change = +0.30 (30 bp) > threshold (20 bp) → -1
    base = [4.0] * 10 + [4.30]
    us10y = _make_series(base)
    sig = us10y_shock_signal(us10y, window=5, shock_threshold_bp=20.0)
    assert sig.iloc[-1] == -1.0


def test_us10y_no_shock():
    # 5d change = +0.10 (10 bp) < threshold (20 bp) → 0
    base = [4.0] * 10 + [4.10]
    us10y = _make_series(base)
    sig = us10y_shock_signal(us10y, window=5, shock_threshold_bp=20.0)
    assert sig.iloc[-1] == 0.0


# ---------------------------------------------------------------------------
# EUR/USD momentum
# ---------------------------------------------------------------------------

def test_eurusd_momentum_up():
    eurusd = _make_series(list(np.linspace(1.05, 1.12, 40)))
    sig = eurusd_momentum_signal(eurusd, window=20)
    non_nan = sig.dropna()
    assert (non_nan == 1.0).all()


# ---------------------------------------------------------------------------
# Channel filter
# ---------------------------------------------------------------------------

def test_channel_filter_brent_materials():
    brent_spec = next(s for s in REGISTERED_FACTOR_SIGNALS if s.signal_name == "brent_direction")
    assert is_applicable(brent_spec, "materials") is True


def test_channel_filter_brent_telecom():
    brent_spec = next(s for s in REGISTERED_FACTOR_SIGNALS if s.signal_name == "brent_direction")
    assert is_applicable(brent_spec, "telecom") is False


# ---------------------------------------------------------------------------
# compute_all_factor_signals dispatcher
# ---------------------------------------------------------------------------

def _make_aligned_factors(n: int = 50) -> dict[str, pd.Series]:
    return {
        "VIX": _const(n, 15.0),
        "DXY": _make_series(list(np.linspace(105, 90, n))),
        "BRENT": _make_series(list(np.linspace(80, 95, n))),
        "SP500": _make_series(list(np.linspace(4000, 4200, n))),
        "US10Y": _const(n, 4.0),
        "EURUSD": _make_series(list(np.linspace(1.05, 1.12, n))),
    }


def test_compute_all_sector_all_returns_six():
    aligned = _make_aligned_factors()
    result = compute_all_factor_signals(aligned, sector="all")
    assert len(result) == 6
    assert set(result.keys()) == {
        "vix_zscore", "dxy_momentum", "brent_direction",
        "sp500_vix_confirmation", "us10y_shock", "eurusd_momentum",
    }


def test_compute_all_missing_sp500_drops_combo():
    aligned = _make_aligned_factors()
    # Remove SP500 — sp500_vix_confirmation needs both SP500 and VIX
    del aligned["SP500"]
    result = compute_all_factor_signals(aligned, sector="all")
    assert "sp500_vix_confirmation" not in result
    # Other 5 signals still computable
    assert len(result) == 5
