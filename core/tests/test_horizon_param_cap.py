"""Tests for A.1.d — horizon-aware parameter caps.

Verifies that no generated candidate exceeds its family's cap for the
governing warmup parameter, across all three canonical horizons.
Uses canonical horizon names (weekly/monthly/quarterly) for generate_candidates
and the short/medium/long keys (+ their aliases) for HORIZON_PARAM_CAP.
"""
from __future__ import annotations

import pytest

from core.quant_core.signal_engine.candidates import generate_candidates
from core.quant_core.signal_engine.domain import HORIZON_PARAM_CAP, cap_param_grid

# Canonical names recognised by generate_candidates / VALID_HORIZONS
HORIZONS = ("weekly", "monthly", "quarterly")


# ---------------------------------------------------------------------------
# cap_param_grid unit tests
# ---------------------------------------------------------------------------

def test_cap_param_grid_basic():
    assert cap_param_grid([5, 10, 15, 20], 15) == [5, 10, 15]


def test_cap_param_grid_all_pass():
    values = [1, 2, 3]
    assert cap_param_grid(values, 10) == values


def test_cap_param_grid_boundary_included():
    assert cap_param_grid([10, 20, 30], 20) == [10, 20]


def test_cap_param_grid_empty_raises():
    with pytest.raises(ValueError, match="cap_param_grid"):
        cap_param_grid([50, 100], 10)


def test_cap_param_grid_idempotent():
    values = [5, 10, 15]
    result = cap_param_grid(values, 20)
    assert cap_param_grid(result, 20) == result


# ---------------------------------------------------------------------------
# HORIZON_PARAM_CAP alias coverage
# ---------------------------------------------------------------------------

def test_aliases_share_base_horizon_caps():
    assert HORIZON_PARAM_CAP["weekly"] is HORIZON_PARAM_CAP["short"]
    assert HORIZON_PARAM_CAP["monthly"] is HORIZON_PARAM_CAP["medium"]
    assert HORIZON_PARAM_CAP["quarterly"] is HORIZON_PARAM_CAP["long"]


# ---------------------------------------------------------------------------
# Per-family cap enforcement across all horizons
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("horizon", HORIZONS)
def test_sma_window_within_cap(horizon: str):
    cap = HORIZON_PARAM_CAP[horizon]["sma"]
    for v in generate_candidates("sma", horizon):
        assert v.params["window"] <= cap, (
            f"sma window {v.params['window']} exceeds cap {cap} for {horizon}"
        )


@pytest.mark.parametrize("horizon", HORIZONS)
def test_ema_window_within_cap(horizon: str):
    cap = HORIZON_PARAM_CAP[horizon]["ema"]
    for v in generate_candidates("ema", horizon):
        assert v.params["window"] <= cap, (
            f"ema window {v.params['window']} exceeds cap {cap} for {horizon}"
        )


@pytest.mark.parametrize("horizon", HORIZONS)
def test_rsi_period_within_cap(horizon: str):
    cap = HORIZON_PARAM_CAP[horizon]["rsi"]
    for v in generate_candidates("rsi", horizon):
        assert v.params["period"] <= cap, (
            f"rsi period {v.params['period']} exceeds cap {cap} for {horizon}"
        )


@pytest.mark.parametrize("horizon", HORIZONS)
def test_macd_slow_within_cap(horizon: str):
    cap = HORIZON_PARAM_CAP[horizon]["macd_slow"]
    for v in generate_candidates("macd", horizon):
        assert v.params["slow"] <= cap, (
            f"macd slow {v.params['slow']} exceeds cap {cap} for {horizon}"
        )


@pytest.mark.parametrize("horizon", HORIZONS)
def test_stochastic_k_within_cap(horizon: str):
    cap = HORIZON_PARAM_CAP[horizon]["stoch"]
    for v in generate_candidates("stochastic", horizon):
        assert v.params["k_period"] <= cap, (
            f"stoch k_period {v.params['k_period']} exceeds cap {cap} for {horizon}"
        )


@pytest.mark.parametrize("horizon", HORIZONS)
def test_obv_ema_period_within_cap(horizon: str):
    cap = HORIZON_PARAM_CAP[horizon]["obv_ema"]
    for v in generate_candidates("obv", horizon):
        assert v.params["ema_period"] <= cap, (
            f"obv ema_period {v.params['ema_period']} exceeds cap {cap} for {horizon}"
        )


@pytest.mark.parametrize("horizon", HORIZONS)
def test_ichimoku_kijun_within_cap(horizon: str):
    cap = HORIZON_PARAM_CAP[horizon]["ichimoku_kijun"]
    for v in generate_candidates("ichimoku", horizon):
        assert v.params["kijun"] <= cap, (
            f"ichimoku kijun {v.params['kijun']} exceeds cap {cap} for {horizon}"
        )


# ---------------------------------------------------------------------------
# Short/weekly horizon must have smaller max windows than medium/monthly
# ---------------------------------------------------------------------------

def test_weekly_sma_max_window_below_monthly():
    weekly_max = max(v.params["window"] for v in generate_candidates("sma", "weekly"))
    monthly_max = max(v.params["window"] for v in generate_candidates("sma", "monthly"))
    assert weekly_max < monthly_max


def test_weekly_ema_max_window_below_monthly():
    weekly_max = max(v.params["window"] for v in generate_candidates("ema", "weekly"))
    monthly_max = max(v.params["window"] for v in generate_candidates("ema", "monthly"))
    assert weekly_max < monthly_max


# ---------------------------------------------------------------------------
# Each capped generator must still yield at least 1 candidate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("family,horizon", [
    (f, h)
    for f in ("sma", "ema", "rsi", "macd", "stochastic", "obv", "ichimoku")
    for h in HORIZONS
])
def test_each_family_horizon_non_empty(family: str, horizon: str):
    candidates = generate_candidates(family, horizon)
    assert len(candidates) >= 1, (
        f"generate_candidates({family!r}, {horizon!r}) returned empty list"
    )
