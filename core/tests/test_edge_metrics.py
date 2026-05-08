"""Tests for `core.quant_core.research.edge` (§4.2.d + §E.7)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.quant_core.research.edge import (
    DEFAULT_COST_BPS_PER_SIDE,
    EdgeGates,
    EdgeMetrics,
    build_edge_payload,
    compute_canonical_expectancy,
    compute_edge_ratio,
    compute_profit_factor,
    direction_for_bucket,
    strategy_return,
)
from core.quant_core.research.oos_index import OosSample, OosWindow


def _bdays(n: int, start: str = "2020-01-01") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="B")


def _full_oos_sample(idx: pd.DatetimeIndex) -> OosSample:
    return OosSample(
        source="signal_engine",
        horizon="weekly",
        windows=(OosWindow(fold_id=None, start=idx.min(), end=idx.max()),),
        dates=idx,
        score_mode="terminal_holdout",
    )


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def test_canonical_expectancy_matches_arithmetic_within_1e9():
    rng = np.random.default_rng(0)
    r = rng.normal(0.001, 0.02, size=200)
    decomp = compute_canonical_expectancy(r)
    assert abs(decomp.expectancy - float(np.mean(r))) < 1e-9


def test_canonical_expectancy_short_signal_inverts_sign():
    raw = np.array([-0.02, -0.01, -0.03, -0.005])
    short_strategy = np.array([+0.02, +0.01, +0.03, +0.005])
    decomp = compute_canonical_expectancy(short_strategy)
    assert decomp.p_win == 1.0
    assert decomp.expectancy > 0
    assert abs(decomp.expectancy - float(np.mean(short_strategy))) < 1e-12
    # Sanity: raw sign was negative → flipped to positive on short.
    assert float(np.mean(short_strategy)) == -float(np.mean(raw))


def test_profit_factor_no_losses_returns_none():
    assert compute_profit_factor(np.array([0.01, 0.02, 0.03])) is None


def test_profit_factor_no_wins_returns_zero():
    pf = compute_profit_factor(np.array([-0.01, -0.02, -0.03]))
    assert pf == 0.0


def test_profit_factor_known_value():
    # [+1,+2,-1,-2]: pos_sum=3, neg_sum=3 → 1.0
    pf = compute_profit_factor(np.array([1.0, 2.0, -1.0, -2.0]))
    assert pf == pytest.approx(1.0)


def test_edge_ratio_zero_std_returns_none():
    assert compute_edge_ratio(np.array([0.01, 0.01, 0.01])) is None


# ---------------------------------------------------------------------------
# strategy_return — Amendment E.1
# ---------------------------------------------------------------------------

def test_strategy_return_long_subtracts_round_trip_cost():
    c = 0.0033
    assert strategy_return(0.05, "long", c, include_costs=False) == pytest.approx(0.05)
    assert strategy_return(0.05, "long", c, include_costs=True) == pytest.approx(0.05 - 2 * c)


def test_strategy_return_short_subtracts_round_trip_cost_after_sign_flip():
    c = 0.0033
    # Short of a -2% move = +2% gross, then minus round-trip.
    assert strategy_return(-0.02, "short", c, include_costs=False) == pytest.approx(0.02)
    assert strategy_return(-0.02, "short", c, include_costs=True) == pytest.approx(0.02 - 2 * c)


def test_hold_bucket_strategy_return_is_zero():
    assert strategy_return(0.05, "none", 0.0033, include_costs=False) == 0.0
    assert strategy_return(0.05, "none", 0.0033, include_costs=True) == 0.0


def test_edge_ratio_net_equals_gross_minus_cost_over_std():
    rng = np.random.default_rng(2)
    r_gross = rng.normal(0.005, 0.02, size=500)
    c = 0.0033
    r_net = r_gross - 2 * c
    er_gross = compute_edge_ratio(r_gross)
    er_net = compute_edge_ratio(r_net)
    std = float(np.std(r_gross, ddof=1))
    assert er_net == pytest.approx(er_gross - (2 * c) / std, rel=1e-9, abs=1e-9)


def test_profit_factor_net_lower_than_gross_when_costs_nonzero():
    rng = np.random.default_rng(4)
    r_gross = rng.normal(0.003, 0.015, size=300)
    c = 0.0033
    r_net = r_gross - 2 * c
    assert compute_profit_factor(r_net) < compute_profit_factor(r_gross)


# ---------------------------------------------------------------------------
# direction_for_bucket
# ---------------------------------------------------------------------------

def test_direction_for_bucket():
    assert direction_for_bucket("strong_buy") == "long"
    assert direction_for_bucket("buy") == "long"
    assert direction_for_bucket("strong_sell") == "short"
    assert direction_for_bucket("sell") == "short"
    assert direction_for_bucket("hold") == "none"


# ---------------------------------------------------------------------------
# Orchestrator — happy path & gate failure modes
# ---------------------------------------------------------------------------

def _strong_buy_fixture(n_total: int = 200, edge_size: float = 0.02, noise: float = 0.001, seed: int = 1):
    """Build (score_series, prices, oos_sample, today_bucket).

    `n_total` business days; ~half score in `strong_buy` (>50). On those days,
    the next-day return is `edge_size` plus small noise; on others, ~0.
    Returns at horizon 1 (close-to-close).
    """
    idx = _bdays(n_total)
    rng = np.random.default_rng(seed)
    # Alternate scores: strong_buy on odd indices, strong_sell on even.
    scores = np.where(np.arange(n_total) % 2 == 0, -80.0, 80.0)
    score = pd.Series(scores, index=idx, name="score")

    # Build price series so that close-to-close pct change matches the desired
    # forward return on strong_buy days.
    close = np.empty(n_total, dtype="float64")
    close[0] = 100.0
    rets = np.zeros(n_total - 1, dtype="float64")
    for i in range(n_total - 1):
        if scores[i] > 50:  # strong_buy day → next-day return is +edge_size
            rets[i] = edge_size + rng.normal(0.0, noise)
        else:
            rets[i] = rng.normal(0.0, noise)
        close[i + 1] = close[i] * (1.0 + rets[i])
    prices = pd.Series(close, index=idx, name="close")

    oos_sample = _full_oos_sample(idx)
    return score, prices, oos_sample


def test_proven_edge_all_gates_pass():
    score, prices, oos = _strong_buy_fixture(n_total=240, edge_size=0.02)
    em = build_edge_payload(
        symbol="TEST", horizon="weekly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=oos,
        today_bucket="strong_buy", fwd_horizon_bars=1,
        cost_bps_per_side=0.0, mc_iter=300,
    )
    assert em.gates.n is True
    assert em.gates.wilson is True
    assert em.gates.mc_gross is True
    assert em.proven_edge_gross is True
    # With zero cost gross and net are identical.
    assert em.proven_edge_net is True


def test_proven_edge_fails_when_n_below_30():
    score, prices, oos = _strong_buy_fixture(n_total=240, edge_size=0.02)
    # Trim OOS sample to fewer than 30 strong_buy bars.
    short_idx = score.index[:50]  # ~25 strong_buy days
    oos_short = OosSample(
        source="signal_engine", horizon="weekly",
        windows=(OosWindow(fold_id=None, start=short_idx.min(), end=short_idx.max()),),
        dates=short_idx,
        score_mode="terminal_holdout",
    )
    em = build_edge_payload(
        symbol="TEST", horizon="weekly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=oos_short,
        today_bucket="strong_buy", fwd_horizon_bars=1,
        cost_bps_per_side=0.0, mc_iter=200,
    )
    assert em.n < 30
    assert em.gates.n is False
    assert em.proven_edge_gross is False


def test_proven_edge_fails_when_mc_pvalue_above_threshold():
    rng = np.random.default_rng(5)
    n = 240
    idx = _bdays(n)
    scores = np.where(np.arange(n) % 2 == 0, -80.0, 80.0)
    score = pd.Series(scores, index=idx)
    # No edge — pure noise.
    close = 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.005, size=n))
    prices = pd.Series(close, index=idx)
    oos = _full_oos_sample(idx)
    em = build_edge_payload(
        symbol="TEST", horizon="weekly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=oos,
        today_bucket="strong_buy", fwd_horizon_bars=1,
        cost_bps_per_side=0.0, mc_iter=300,
    )
    assert em.gates.mc_gross is False
    assert em.proven_edge_gross is False


def test_proven_edge_fails_when_wilson_lower_below_half():
    # 50/50 hit rate → wilson_lb < 0.5 → wilson gate fails.
    rng = np.random.default_rng(6)
    n = 240
    idx = _bdays(n)
    scores = np.where(np.arange(n) % 2 == 0, -80.0, 80.0)
    close = np.empty(n, dtype="float64"); close[0] = 100.0
    for i in range(n - 1):
        sign = +1 if rng.random() < 0.5 else -1
        close[i + 1] = close[i] * (1.0 + sign * 0.01)
    score = pd.Series(scores, index=idx)
    prices = pd.Series(close, index=idx)
    oos = _full_oos_sample(idx)
    em = build_edge_payload(
        symbol="TEST", horizon="weekly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=oos,
        today_bucket="strong_buy", fwd_horizon_bars=1,
        cost_bps_per_side=0.0, mc_iter=300,
    )
    assert em.gates.wilson is False
    assert em.proven_edge_gross is False


def test_proven_edge_invariant_to_cost_when_cost_is_zero():
    score, prices, oos = _strong_buy_fixture(n_total=240, edge_size=0.02)
    em = build_edge_payload(
        symbol="TEST", horizon="weekly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=oos,
        today_bucket="strong_buy", fwd_horizon_bars=1,
        cost_bps_per_side=0.0, mc_iter=300,
    )
    assert em.proven_edge_gross == em.proven_edge_net
    assert em.expected_return_gross == pytest.approx(em.expected_return_net)
    assert em.edge_ratio_gross == pytest.approx(em.edge_ratio_net)


def test_proven_edge_gross_true_net_false_when_cost_kills_mc():
    # Tiny edge — gross MC passes, but a 200 bps/side cost flips it.
    score, prices, oos = _strong_buy_fixture(
        n_total=300, edge_size=0.004, noise=0.001, seed=8,
    )
    em = build_edge_payload(
        symbol="TEST", horizon="weekly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=oos,
        today_bucket="strong_buy", fwd_horizon_bars=1,
        cost_bps_per_side=200.0, mc_iter=400,
    )
    assert em.proven_edge_gross is True
    assert em.proven_edge_net is False
    # Cost reduces ER by exactly 2c (2 * 0.02 = 0.04).
    assert em.expected_return_net == pytest.approx(em.expected_return_gross - 0.04, abs=1e-12)


def test_oos_filter_excludes_is_dates_end_to_end():
    # Build a series where IS dates have huge +5% returns; OOS dates ≈ 0.
    n = 240
    idx = _bdays(n)
    scores = np.full(n, 80.0)  # everything strong_buy
    score = pd.Series(scores, index=idx)
    rets = np.where(np.arange(n) < 100, 0.05, 0.0)  # IS = first 100, big returns
    close = 100.0 * np.cumprod(1.0 + rets)
    prices = pd.Series(close, index=idx)
    # OOS is only the last 140 days.
    oos_idx = idx[100:]
    oos_sample = OosSample(
        source="signal_engine", horizon="weekly",
        windows=(OosWindow(fold_id=None, start=oos_idx.min(), end=oos_idx.max()),),
        dates=oos_idx,
        score_mode="terminal_holdout",
    )
    em = build_edge_payload(
        symbol="TEST", horizon="weekly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=oos_sample,
        today_bucket="strong_buy", fwd_horizon_bars=1,
        cost_bps_per_side=0.0, mc_iter=200,
    )
    # Window must be inside the OOS region.
    assert em.window_start >= oos_idx.min()
    assert em.window_end <= oos_idx.max()
    # Mean ≈ 0 (IS bars excluded).
    assert abs(em.expected_return_gross) < 1e-9


def test_hold_bucket_short_circuits_to_none_metrics():
    score, prices, oos = _strong_buy_fixture(n_total=120)
    em = build_edge_payload(
        symbol="TEST", horizon="weekly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=oos,
        today_bucket="hold", fwd_horizon_bars=1,
        cost_bps_per_side=DEFAULT_COST_BPS_PER_SIDE, mc_iter=100,
    )
    assert em.direction == "none"
    assert em.n == 0
    assert em.expected_return_gross is None
    assert em.expected_return_net is None
    assert em.expectancy_gross is None
    assert em.proven_edge_gross is False
    assert em.proven_edge_net is False
    assert em.gates.mc_gross is False
    assert em.gates.wilson is False
