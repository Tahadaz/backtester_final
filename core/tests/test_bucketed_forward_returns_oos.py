"""Unit tests for the OOS / recent_window / max_lookback_years extension of
`bucketed_forward_returns` (§4.1.c of docs/plans/edge-deploy-plan.md).

Synthetic data only — no DB. Default-call behavior MUST match the legacy
contract because non-Edge callers (frontend predictive-history endpoints,
existing analytics jobs) still pass no Edge kwargs.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.quant_core.research.score_history import bucketed_forward_returns


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _const_score_series(idx: pd.DatetimeIndex, score: float) -> pd.Series:
    """Constant-score series so every bar lands in the same bucket."""
    return pd.Series(score, index=idx, name="score")


def _is_oos_split_prices(idx: pd.DatetimeIndex, oos_dates: pd.DatetimeIndex,
                         is_growth: float, oos_growth: float) -> pd.Series:
    """Build a close series where each bar's NEXT-bar return is determined by
    the current bar's IS/OOS classification.

    Bar t classified IS  → close[t+1] = close[t] * (1 + is_growth)
    Bar t classified OOS → close[t+1] = close[t] * (1 + oos_growth)

    Used to build a synthetic where IS forward returns differ predictably from
    OOS forward returns at horizon h=1 (close-to-close).
    """
    oos_set = set(oos_dates)
    closes = np.empty(len(idx), dtype="float64")
    closes[0] = 100.0
    for i in range(len(idx) - 1):
        g = oos_growth if idx[i] in oos_set else is_growth
        closes[i + 1] = closes[i] * (1.0 + g)
    return pd.Series(closes, index=idx, name="close")


# ---------------------------------------------------------------------------
# 1. Default-call backwards compatibility
# ---------------------------------------------------------------------------

def test_oos_filter_preserves_existing_behavior_when_none():
    """oos_dates=None must not change cell counts/values vs. the legacy contract."""
    idx = pd.date_range("2024-01-01", periods=300, freq="B")
    rng = np.random.default_rng(42)
    scores = pd.Series(rng.uniform(-80, 80, size=len(idx)), index=idx, name="score")
    closes = pd.Series(100.0 * np.cumprod(1 + rng.normal(0.0005, 0.01, len(idx))),
                       index=idx, name="close")

    legacy = bucketed_forward_returns(scores, closes, [1, 5], n_bootstrap=100)
    new_default = bucketed_forward_returns(
        scores, closes, [1, 5], n_bootstrap=100,
        oos_dates=None, recent_window=None, max_lookback_years=None,
    )
    assert legacy == new_default


# ---------------------------------------------------------------------------
# 2. OOS filter excludes IS dates
# ---------------------------------------------------------------------------

def test_oos_filter_drops_is_dates():
    """IS bars have +5% next-bar growth, OOS bars 0%. With score pinned to
    strong_buy bucket, mean should be ~+5% unfiltered and ~0% with oos_dates."""
    idx = pd.date_range("2024-01-01", periods=200, freq="B")
    is_dates = idx[:100]
    oos_dates = idx[100:]
    closes = _is_oos_split_prices(idx, oos_dates, is_growth=0.05, oos_growth=0.0)
    scores = _const_score_series(idx, score=75.0)  # strong_buy

    cells_full = bucketed_forward_returns(scores, closes, [1], n_bootstrap=200)
    cells_oos = bucketed_forward_returns(scores, closes, [1], n_bootstrap=200,
                                         oos_dates=oos_dates)

    full_sb = next(c for c in cells_full if c["bucket"] == "strong_buy" and c["fwd_h"] == 1)
    oos_sb = next(c for c in cells_oos if c["bucket"] == "strong_buy" and c["fwd_h"] == 1)

    # Unfiltered mean ≈ blend of +5% (IS) and 0% (OOS) → strictly positive.
    assert full_sb["mean"] is not None and full_sb["mean"] > 0.01
    # OOS-filtered mean should be ~0%.
    assert oos_sb["mean"] is not None and abs(oos_sb["mean"]) < 1e-9
    # IS dates dropped from sample.
    assert oos_sb["n"] < full_sb["n"]


def test_oos_filter_requires_forward_exit_inside_oos_window():
    """For h>1, an OOS entry whose exit date lands after OOS must be dropped."""
    idx = pd.date_range("2024-01-01", periods=40, freq="B")
    oos_dates = idx[10:35]
    closes = pd.Series(100.0, index=idx, name="close")
    closes.iloc[35:] = 200.0
    scores = _const_score_series(idx, score=75.0)

    cells = bucketed_forward_returns(
        scores, closes, [3], n_bootstrap=100, oos_dates=oos_dates,
    )
    sb = next(c for c in cells if c["bucket"] == "strong_buy" and c["fwd_h"] == 3)

    assert sb["n"] == 22
    assert sb["mean"] == 0.0
    assert sb["window_start"] == idx[10].date().isoformat()
    assert sb["window_end"] == idx[31].date().isoformat()


# ---------------------------------------------------------------------------
# 3. max_lookback_years caps the aligned index
# ---------------------------------------------------------------------------

def test_max_lookback_years_caps_window():
    """5-year span; max_lookback_years=2 must drop the first 3 years."""
    idx = pd.date_range("2020-01-01", periods=5 * 252, freq="B")
    rng = np.random.default_rng(7)
    scores = _const_score_series(idx, score=75.0)
    closes = pd.Series(
        100.0 * np.cumprod(1 + rng.normal(0.0, 0.005, len(idx))),
        index=idx, name="close",
    )

    cells_full = bucketed_forward_returns(scores, closes, [1], n_bootstrap=100)
    cells_capped = bucketed_forward_returns(
        scores, closes, [1], n_bootstrap=100, max_lookback_years=2.0,
    )

    full_sb = next(c for c in cells_full if c["bucket"] == "strong_buy" and c["fwd_h"] == 1)
    capped_sb = next(c for c in cells_capped if c["bucket"] == "strong_buy" and c["fwd_h"] == 1)

    # ~3 of 5 years dropped → capped n is ~2/5 of full.
    assert capped_sb["n"] < full_sb["n"]
    ratio = capped_sb["n"] / full_sb["n"]
    assert 0.30 <= ratio <= 0.50


# ---------------------------------------------------------------------------
# 4. recent_window picks the most recent N per bucket
# ---------------------------------------------------------------------------

def test_recent_window_picks_last_N():
    """200 same-bucket bars; recent_window=(30,60) → cell n must be 60."""
    idx = pd.date_range("2023-01-01", periods=200, freq="B")
    rng = np.random.default_rng(11)
    scores = _const_score_series(idx, score=75.0)
    closes = pd.Series(
        100.0 * np.cumprod(1 + rng.normal(0.0, 0.005, len(idx))),
        index=idx, name="close",
    )

    cells = bucketed_forward_returns(
        scores, closes, [1], n_bootstrap=100, recent_window=(30, 60),
    )
    sb = next(c for c in cells if c["bucket"] == "strong_buy" and c["fwd_h"] == 1)
    # h=1 drops one row at the tail (NaN forward return), so the most recent
    # 60 surviving bars all land in strong_buy.
    assert sb["n"] == 60
    # Window range reflects the surviving 60 bars. After tail(60) the start
    # sits ~60 business days before the end, lookback ≈ 60.
    assert sb["window_start"] is not None and sb["window_end"] is not None
    assert sb["window_start"] < sb["window_end"]
    assert 55 <= sb["lookback_business_days"] <= 65


def test_lookback_fields_present_on_default_call():
    """Cells from a vanilla call also carry window_start/window_end/lookback."""
    idx = pd.date_range("2024-01-01", periods=200, freq="B")
    rng = np.random.default_rng(17)
    scores = pd.Series(rng.uniform(-80, 80, size=len(idx)), index=idx, name="score")
    closes = pd.Series(
        100.0 * np.cumprod(1 + rng.normal(0.0, 0.005, len(idx))),
        index=idx, name="close",
    )
    cells = bucketed_forward_returns(scores, closes, [1], n_bootstrap=100)
    populated = [c for c in cells if c["n"] >= 5]
    assert populated, "fixture should produce at least one populated cell"
    for c in populated:
        assert c["window_start"] is not None
        assert c["window_end"] is not None
        assert c["lookback_business_days"] is not None
        assert c["window_start"] <= c["window_end"]


# ---------------------------------------------------------------------------
# 5. Insufficient sample emits an empty cell with the truncated n
# ---------------------------------------------------------------------------

def test_insufficient_sample_emits_empty_cell():
    """Only ~25 same-bucket bars; recent_window=(30,60) → empty cell with n=25."""
    idx = pd.date_range("2024-01-01", periods=30, freq="B")
    rng = np.random.default_rng(13)
    scores = _const_score_series(idx, score=75.0)
    closes = pd.Series(
        100.0 * np.cumprod(1 + rng.normal(0.0, 0.005, len(idx))),
        index=idx, name="close",
    )

    cells = bucketed_forward_returns(
        scores, closes, [1], n_bootstrap=100, recent_window=(30, 60),
    )
    sb = next(c for c in cells if c["bucket"] == "strong_buy" and c["fwd_h"] == 1)
    # 30 input bars - 1 (final NaN forward return) = 29 valid bars.
    # All 29 fall in strong_buy; tail(60) keeps all 29; 29 < n_min(30) → empty.
    assert sb["mean"] is None
    assert sb["ci_lower"] is None
    assert 0 < sb["n"] < 30


# ---------------------------------------------------------------------------
# 6. OOS filter that yields too few bars early-exits cleanly
# ---------------------------------------------------------------------------

def test_oos_filter_below_threshold_returns_empty_list():
    """Aligned-index < 20 after OOS filter → function returns [] (legacy guard)."""
    idx = pd.date_range("2024-01-01", periods=100, freq="B")
    rng = np.random.default_rng(3)
    scores = pd.Series(rng.uniform(-80, 80, size=len(idx)), index=idx, name="score")
    closes = pd.Series(
        100.0 * np.cumprod(1 + rng.normal(0.0, 0.005, len(idx))),
        index=idx, name="close",
    )

    only_a_few = idx[:5]
    cells = bucketed_forward_returns(
        scores, closes, [1], n_bootstrap=100, oos_dates=only_a_few,
    )
    assert cells == []
