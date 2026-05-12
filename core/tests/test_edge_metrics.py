"""Tests for `core.quant_core.research.edge` (§4.2.d + §E.7)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.quant_core.research.edge import (
    DEFAULT_COST_BPS_PER_SIDE,
    EDGE_MAX_OBSERVATIONS,
    EdgeGates,
    EdgeMetrics,
    _sample_frames,
    bootstrap_mean_ci,
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


def test_bootstrap_mean_ci_brackets_sample_mean():
    r = np.array([-0.01, 0.0, 0.01, 0.02, 0.03])
    lo, hi = bootstrap_mean_ci(r, n_iter=300, seed=7)
    assert lo is not None
    assert hi is not None
    assert lo < float(np.mean(r)) < hi


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
    assert em.gates.label_shuffle_gross is True
    assert em.proven_edge_gross is True
    # With zero cost gross and net are identical.
    assert em.proven_edge_net is True


def test_edge_selects_best_open_to_open_holding_period():
    idx = _bdays(520)
    scores = np.zeros(len(idx), dtype="float64")
    open_prices = np.full(len(idx), 100.0, dtype="float64")

    event_idx = list(range(5, 455, 10))
    for i in event_idx:
        scores[i] = 80.0
        open_prices[i + 1] = 100.0
        open_prices[i + 2] = 101.0
        open_prices[i + 3] = 102.0
        open_prices[i + 4] = 110.0
        open_prices[i + 5] = 99.0
        open_prices[i + 6] = 98.0

    score = pd.Series(scores, index=idx)
    prices = pd.DataFrame(
        {
            "Open": open_prices,
            "High": open_prices + 1.0,
            "Low": open_prices - 1.0,
            "Close": open_prices,
        },
        index=idx,
    )
    oos = _full_oos_sample(idx)

    em = build_edge_payload(
        symbol="TEST", horizon="weekly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=oos,
        today_bucket="strong_buy", fwd_horizon_bars=5,
        holding_period_candidates=(1, 2, 3, 4, 5),
        return_calc_method="open_to_open",
        cost_bps_per_side=0.0, max_lookback_years=None, mc_iter=200,
    )

    assert em.return_calc_method == "open_to_open"
    assert em.fwd_horizon_bars == 3
    assert em.holding_period_min_bars == 1
    assert em.holding_period_max_bars == 5
    assert em.holding_period_candidate_count == 5
    assert em.action_expected_return_gross == pytest.approx(0.10)


def test_exact_current_bucket_is_evaluated_without_neighbor_bucket_leakage():
    idx = _bdays(360)
    scores = np.where(np.arange(len(idx)) % 2 == 0, 80.0, 30.0)
    score = pd.Series(scores, index=idx)
    close = np.empty(len(idx), dtype="float64")
    close[0] = 100.0
    for i in range(len(idx) - 1):
        ret = 0.02 if scores[i] > 50 else -0.02
        close[i + 1] = close[i] * (1.0 + ret)
    prices = pd.Series(close, index=idx)
    oos = _full_oos_sample(idx)

    strong_buy = build_edge_payload(
        symbol="TEST", horizon="weekly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=oos,
        today_bucket="strong_buy", fwd_horizon_bars=1,
        holding_period_candidates=(1,), cost_bps_per_side=0.0, mc_iter=100,
    )
    buy = build_edge_payload(
        symbol="TEST", horizon="weekly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=oos,
        today_bucket="buy", fwd_horizon_bars=1,
        holding_period_candidates=(1,), cost_bps_per_side=0.0, mc_iter=100,
    )

    assert strong_buy.n >= 30
    assert buy.n >= 30
    assert strong_buy.action_expected_return_gross is not None
    assert buy.action_expected_return_gross is not None
    assert strong_buy.action_expected_return_gross > 0.0
    assert buy.action_expected_return_gross < 0.0


def test_exit_ladder_can_select_close_exit_after_open_entry():
    idx = _bdays(520)
    scores = np.zeros(len(idx), dtype="float64")
    open_prices = np.full(len(idx), 100.0, dtype="float64")
    close_prices = np.full(len(idx), 100.0, dtype="float64")

    for i in range(5, 455, 10):
        scores[i] = 80.0
        open_prices[i + 1] = 100.0
        close_prices[i + 1] = 101.0
        open_prices[i + 2] = 102.0
        close_prices[i + 2] = 110.0
        open_prices[i + 3] = 99.0
        close_prices[i + 3] = 98.0

    score = pd.Series(scores, index=idx)
    prices = pd.DataFrame(
        {"Open": open_prices, "High": np.maximum(open_prices, close_prices), "Low": np.minimum(open_prices, close_prices), "Close": close_prices},
        index=idx,
    )

    em = build_edge_payload(
        symbol="TEST", horizon="weekly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=_full_oos_sample(idx),
        today_bucket="strong_buy", fwd_horizon_bars=3,
        holding_period_candidates=(1, 2, 3),
        cost_bps_per_side=0.0, max_lookback_years=None, mc_iter=100,
    )

    assert em.return_calc_method == "open_to_exit_ladder"
    assert em.entry_price_kind == "open"
    assert em.entry_lag_bars == 1
    assert em.exit_price_kind == "close"
    assert em.exit_lag_bars == 2
    assert em.exit_timing_label == "J+2 Close"
    assert em.action_expected_return_gross == pytest.approx(0.10)


def test_exit_ladder_can_select_open_exit_after_open_entry():
    idx = _bdays(520)
    scores = np.zeros(len(idx), dtype="float64")
    open_prices = np.full(len(idx), 100.0, dtype="float64")
    close_prices = np.full(len(idx), 100.0, dtype="float64")

    for i in range(5, 455, 10):
        scores[i] = 80.0
        open_prices[i + 1] = 100.0
        close_prices[i + 1] = 101.0
        open_prices[i + 2] = 102.0
        close_prices[i + 2] = 103.0
        open_prices[i + 3] = 115.0
        close_prices[i + 3] = 90.0

    score = pd.Series(scores, index=idx)
    prices = pd.DataFrame(
        {"Open": open_prices, "High": np.maximum(open_prices, close_prices), "Low": np.minimum(open_prices, close_prices), "Close": close_prices},
        index=idx,
    )

    em = build_edge_payload(
        symbol="TEST", horizon="weekly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=_full_oos_sample(idx),
        today_bucket="strong_buy", fwd_horizon_bars=3,
        holding_period_candidates=(1, 2, 3),
        cost_bps_per_side=0.0, max_lookback_years=None, mc_iter=100,
    )

    assert em.exit_price_kind == "open"
    assert em.exit_lag_bars == 3
    assert em.exit_timing_label == "J+3 Open"
    assert em.action_expected_return_gross == pytest.approx(0.15)


def test_exit_ladder_respects_monthly_lower_horizon_bound():
    idx = _bdays(1400)
    scores = np.zeros(len(idx), dtype="float64")
    open_prices = np.full(len(idx), 100.0, dtype="float64")
    close_prices = np.full(len(idx), 100.0, dtype="float64")

    for i in range(5, 1200, 30):
        scores[i] = 80.0
        open_prices[i + 1] = 100.0
        close_prices[i + 2] = 150.0
        close_prices[i + 6] = 108.0

    score = pd.Series(scores, index=idx)
    prices = pd.DataFrame(
        {"Open": open_prices, "High": np.maximum(open_prices, close_prices), "Low": np.minimum(open_prices, close_prices), "Close": close_prices},
        index=idx,
    )

    em = build_edge_payload(
        symbol="TEST", horizon="monthly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=_full_oos_sample(idx),
        today_bucket="strong_buy", fwd_horizon_bars=21,
        holding_period_candidates=tuple(range(6, 22)),
        cost_bps_per_side=0.0, max_lookback_years=None, mc_iter=100,
    )

    assert em.holding_period_min_bars == 6
    assert em.exit_lag_bars is not None
    assert em.exit_lag_bars >= 6
    assert em.action_expected_return_gross == pytest.approx(0.08)


def test_strict_oos_selection_sample_picks_hold_and_proof_sample_reports_edge():
    idx = _bdays(520)
    scores = np.zeros(len(idx), dtype="float64")
    open_prices = np.full(len(idx), 100.0, dtype="float64")

    for i in range(5, 495, 5):
        scores[i] = 80.0
        open_prices[i + 1] = 100.0
        open_prices[i + 2] = 101.0
        open_prices[i + 3] = 102.0
        open_prices[i + 4] = 110.0
        open_prices[i + 5] = 99.0

    score = pd.Series(scores, index=idx)
    prices = pd.DataFrame(
        {
            "Open": open_prices,
            "High": open_prices + 1.0,
            "Low": open_prices - 1.0,
            "Close": open_prices,
        },
        index=idx,
    )
    selection_idx = idx[:320]
    proof_idx = idx[320:500]
    selection_oos = OosSample(
        source="signal_engine", horizon="weekly",
        windows=(OosWindow(fold_id=None, start=selection_idx.min(), end=selection_idx.max()),),
        dates=selection_idx,
        score_mode="terminal_holdout",
    )
    proof_oos = OosSample(
        source="signal_engine", horizon="weekly",
        windows=(OosWindow(fold_id=None, start=proof_idx.min(), end=proof_idx.max()),),
        dates=proof_idx,
        score_mode="terminal_holdout",
    )

    em = build_edge_payload(
        symbol="TEST", horizon="weekly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=proof_oos,
        selection_oos_sample=selection_oos,
        today_bucket="strong_buy", fwd_horizon_bars=5,
        holding_period_candidates=(1, 2, 3, 4, 5),
        cost_bps_per_side=0.0, mc_iter=100,
    )

    assert em.proof_method == "strict_oos_split"
    assert em.holding_period_selection_metric == "strict_oos_selection_max_net_action_expected_return_open_entry_close_open_exit_ladder"
    assert em.fwd_horizon_bars == 4
    assert em.exit_price_kind == "open"
    assert em.selection_n >= 30
    assert em.proof_n == em.n
    assert em.window_start >= proof_idx.min()
    assert em.window_end <= proof_idx.max()


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


def test_mc_gate_accepts_pvalue_below_five_percent(monkeypatch):
    score, prices, oos = _strong_buy_fixture(n_total=240, edge_size=0.02)

    def fake_mc(*args, **kwargs):
        return {"pvalue": 0.049}

    def fake_label_shuffle(*args, **kwargs):
        return {"pvalue": 0.001}

    monkeypatch.setattr("core.quant_core.research.edge.monte_carlo_luck_test", fake_mc)
    monkeypatch.setattr("core.quant_core.research.edge.monte_carlo_label_shuffle_test", fake_label_shuffle)

    em = build_edge_payload(
        symbol="TEST", horizon="weekly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=oos,
        today_bucket="strong_buy", fwd_horizon_bars=1,
        holding_period_candidates=(1,),
        cost_bps_per_side=0.0, mc_iter=100,
    )

    assert em.mc_luck_pvalue_gross_adj == pytest.approx(0.049)
    assert em.gates.mc_gross is True
    assert em.gates.mc_net is True


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


def test_proven_edge_fails_when_label_shuffle_gate_fails(monkeypatch):
    score, prices, oos = _strong_buy_fixture(n_total=240, edge_size=0.02)

    def fake_label_shuffle(*args, **kwargs):
        return {"pvalue": 0.50}

    monkeypatch.setattr(
        "core.quant_core.research.edge.monte_carlo_label_shuffle_test",
        fake_label_shuffle,
    )
    em = build_edge_payload(
        symbol="TEST", horizon="weekly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=oos,
        today_bucket="strong_buy", fwd_horizon_bars=1,
        cost_bps_per_side=0.0, mc_iter=300,
    )
    assert em.gates.mc_gross is True
    assert em.gates.label_shuffle_gross is False
    assert em.proven_edge_gross is False


def test_label_shuffle_uses_reported_edge_window(monkeypatch):
    idx = _bdays(180)
    score = pd.Series(80.0, index=idx)
    close = np.empty(len(idx), dtype="float64")
    close[0] = 100.0
    for i in range(len(idx) - 1):
        close[i + 1] = close[i] * 1.01
    prices = pd.Series(close, index=idx)
    oos = _full_oos_sample(idx)
    seen_windows: list[tuple[pd.Timestamp, pd.Timestamp]] = []

    def fake_label_shuffle(score_series, forward_returns, **kwargs):
        series = pd.Series(score_series)
        seen_windows.append((pd.Timestamp(series.index.min()), pd.Timestamp(series.index.max())))
        return {"pvalue": 0.001}

    monkeypatch.setattr(
        "core.quant_core.research.edge.monte_carlo_label_shuffle_test",
        fake_label_shuffle,
    )
    em = build_edge_payload(
        symbol="TEST", horizon="weekly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=oos,
        today_bucket="strong_buy", fwd_horizon_bars=1,
        cost_bps_per_side=0.0, n_target=30, mc_iter=100,
    )
    assert seen_windows
    assert all(start == em.window_start and end == em.window_end for start, end in seen_windows)


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


def _force_edge_significance(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_significance(*_args, **_kwargs):
        return {"pvalue": 0.001}

    monkeypatch.setattr("core.quant_core.research.edge.monte_carlo_luck_test", fake_significance)
    monkeypatch.setattr("core.quant_core.research.edge.monte_carlo_label_shuffle_test", fake_significance)


def _event_score_price_fixture(
    *,
    n_total: int,
    positive_events: list[int],
    negative_events: list[int] | None = None,
) -> tuple[pd.Series, pd.Series, OosSample]:
    idx = _bdays(n_total)
    scores = np.zeros(n_total, dtype="float64")
    positive_set = {int(i) for i in positive_events if 0 <= int(i) < n_total - 1}
    negative_set = {int(i) for i in (negative_events or []) if 0 <= int(i) < n_total - 1}
    for i in positive_set | negative_set:
        scores[i] = 80.0

    close = np.empty(n_total, dtype="float64")
    close[0] = 100.0
    for i in range(n_total - 1):
        if i in positive_set:
            ret = 0.02
        elif i in negative_set:
            ret = -0.02
        else:
            ret = 0.0
        close[i + 1] = close[i] * (1.0 + ret)

    return pd.Series(scores, index=idx, name="score"), pd.Series(close, index=idx, name="close"), _full_oos_sample(idx)


def test_edge_recency_policy_defaults_by_horizon():
    idx = _bdays(80)
    score = pd.Series(0.0, index=idx)
    prices = pd.Series(100.0, index=idx)

    expected = {
        "weekly": (1.0, 0.25),
        "monthly": (2.0, 0.5),
        "quarterly": (3.0, 1.0),
    }
    for horizon, (proof_years, freshness_years) in expected.items():
        em = build_edge_payload(
            symbol="TEST", horizon=horizon, source="signal_engine",
            score_series=score, prices=prices, oos_sample=_full_oos_sample(idx),
            today_bucket="hold", fwd_horizon_bars=1,
            holding_period_candidates=(1,), cost_bps_per_side=0.0, mc_iter=20,
        )
        assert em.proof_max_lookback_years == proof_years
        assert em.freshness_lookback_years == freshness_years
        assert em.freshness_min_n == 10


def test_default_lookback_anchor_uses_latest_oos_date_not_latest_bucket_date():
    score, prices, oos = _event_score_price_fixture(
        n_total=520,
        positive_events=list(range(10, 110)),
    )

    em = build_edge_payload(
        symbol="TEST", horizon="weekly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=oos,
        today_bucket="strong_buy", fwd_horizon_bars=1,
        holding_period_candidates=(1,), cost_bps_per_side=0.0, mc_iter=20,
    )

    assert em.proof_max_lookback_years == 1.0
    assert em.n == 0
    assert em.action_expected_return_gross is None


def test_explicit_none_disables_proof_lookback_cap():
    score, prices, oos = _event_score_price_fixture(
        n_total=520,
        positive_events=list(range(10, 110)),
    )

    em = build_edge_payload(
        symbol="TEST", horizon="weekly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=oos,
        today_bucket="strong_buy", fwd_horizon_bars=1,
        holding_period_candidates=(1,), cost_bps_per_side=0.0,
        max_lookback_years=None, mc_iter=20,
    )

    assert em.proof_max_lookback_years is None
    assert em.n == 60
    assert em.action_expected_return_gross == pytest.approx(0.02)


def test_sample_frames_caps_requested_observations_at_100():
    idx = _bdays(180)
    score = pd.Series(80.0, index=idx, name="score")
    prices = pd.Series(np.linspace(100.0, 280.0, len(idx)), index=idx, name="close")
    _, bucket_df = _sample_frames(
        score_series=score,
        prices=prices,
        oos_sample=_full_oos_sample(idx),
        today_bucket="strong_buy",
        fwd_horizon_bars=1,
        return_calc_method="close_to_close",
        max_lookback_years=None,
        n_target=10**9,
    )

    assert len(bucket_df) == EDGE_MAX_OBSERVATIONS
    assert bucket_df.index.min() == idx[-(EDGE_MAX_OBSERVATIONS + 1)]
    assert bucket_df.index.max() == idx[-2]


def test_freshness_gate_blocks_old_edge_when_recent_slice_contradicts(monkeypatch: pytest.MonkeyPatch):
    _force_edge_significance(monkeypatch)
    score, prices, oos = _event_score_price_fixture(
        n_total=260,
        positive_events=list(range(20, 182, 3))[:50],
        negative_events=list(range(230, 240)),
    )

    em = build_edge_payload(
        symbol="TEST", horizon="weekly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=oos,
        today_bucket="strong_buy", fwd_horizon_bars=1,
        holding_period_candidates=(1,), cost_bps_per_side=0.0, mc_iter=50,
    )

    assert em.n == 60
    assert em.action_expected_return_gross is not None
    assert em.action_expected_return_gross > 0.0
    assert em.gates.mc_gross is True
    assert em.gates.label_shuffle_gross is True
    assert em.gates.wilson is True
    assert em.freshness_n == 10
    assert em.freshness_action_expected_return_gross == pytest.approx(-0.02)
    assert em.gates.freshness_gross is False
    assert em.gates.freshness_net is False
    assert em.freshness_status == "failed"
    assert em.proven_edge_gross is False
    assert em.proven_edge_net is False


def test_freshness_gate_passes_when_recent_slice_confirms(monkeypatch: pytest.MonkeyPatch):
    _force_edge_significance(monkeypatch)
    score, prices, oos = _event_score_price_fixture(
        n_total=260,
        positive_events=list(range(20, 182, 3))[:50] + list(range(230, 240)),
    )

    em = build_edge_payload(
        symbol="TEST", horizon="weekly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=oos,
        today_bucket="strong_buy", fwd_horizon_bars=1,
        holding_period_candidates=(1,), cost_bps_per_side=0.0, mc_iter=50,
    )

    assert em.n == 60
    assert em.freshness_n == 10
    assert em.freshness_action_expected_return_gross == pytest.approx(0.02)
    assert em.gates.freshness_gross is True
    assert em.gates.freshness_net is True
    assert em.freshness_status == "passed"
    assert em.proven_edge_gross is True
    assert em.proven_edge_net is True


def test_freshness_gate_requires_minimum_recent_observations(monkeypatch: pytest.MonkeyPatch):
    _force_edge_significance(monkeypatch)
    score, prices, oos = _event_score_price_fixture(
        n_total=260,
        positive_events=list(range(20, 182, 3))[:51] + list(range(230, 239)),
    )

    em = build_edge_payload(
        symbol="TEST", horizon="weekly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=oos,
        today_bucket="strong_buy", fwd_horizon_bars=1,
        holding_period_candidates=(1,), cost_bps_per_side=0.0, mc_iter=50,
    )

    assert em.n == 60
    assert em.freshness_n == 9
    assert em.freshness_status == "insufficient_n"
    assert em.gates.freshness_gross is False
    assert em.gates.freshness_net is False
    assert em.proven_edge_gross is False
    assert em.proven_edge_net is False


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


def test_short_edge_treats_negative_forward_returns_as_wins():
    idx = _bdays(180)
    score = pd.Series(-80.0, index=idx)
    close = np.empty(len(idx), dtype="float64")
    close[0] = 100.0
    for i in range(len(idx) - 1):
        close[i + 1] = close[i] * 0.99
    prices = pd.Series(close, index=idx)
    oos = _full_oos_sample(idx)
    em = build_edge_payload(
        symbol="TEST", horizon="weekly", source="signal_engine",
        score_series=score, prices=prices, oos_sample=oos,
        today_bucket="strong_sell", fwd_horizon_bars=1,
        cost_bps_per_side=0.0, mc_iter=300,
    )
    assert em.direction == "short"
    assert em.n >= 30
    assert em.hit_rate == pytest.approx(1.0)
    assert em.expected_return_gross is not None
    assert em.expected_return_gross > 0
    assert em.action_expected_return_gross == pytest.approx(em.expected_return_gross)
    assert em.stock_expected_return is not None
    assert em.stock_expected_return < 0
    assert em.expected_return_gross_ci_lower is not None
    assert em.expected_return_gross_ci_lower > 0
