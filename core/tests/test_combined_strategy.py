from __future__ import annotations

import datetime as dt
import math

import pandas as pd
import pytest

from quant_core.fundamentals.cross_section.combined_strategy import (
    ACTION_BUY,
    ACTION_EARLY_EXIT,
    ACTION_GATE_BLOCK,
    ACTION_LATE_BUY,
    ACTION_SELL,
    CombinedConfig,
    aggregate_wfo_gate,
    apply_risk_overlays,
    build_graceful_composite_holdings,
    build_rank_composite_holdings,
    build_signal_holdings,
    build_trend_gate_series,
    compute_pit_adv_series,
    difference_test,
    evaluate_acceptance,
    pit_value,
    run_gated_vintage_backtest,
)
from quant_core.fundamentals.cross_section.live_like_strategy import (
    LiveLikeConfig,
    build_trade_ledger,
    run_vintage_backtest,
    summarize_performance,
)

SHARED_MONTHLY_COLUMNS = [
    "as_of_date",
    "n_active_vintages",
    "n_holdings",
    "gross_return",
    "turnover",
    "cost",
    "net_return",
    "stale_price_events",
]


def _monthly_dates(n: int, start: str = "2020-01-31") -> list[dt.date]:
    return [d.date() for d in pd.date_range(start, periods=n, freq="ME")]


def _flat_price_series(value: float, dates: list[dt.date]) -> pd.Series:
    return pd.Series([value] * len(dates), index=pd.DatetimeIndex(dates))


def _scenario_multi_symbol_geometric():
    """12 monthly dates, 4-symbol rotating pool -- covers warm-up (first 6
    periods) AND the first vintage's expiry (period index 6)."""
    dates = _monthly_dates(12)
    pool = ["AAA", "BBB", "CCC", "DDD"]
    holdings_by_date: dict[dt.date, dict[str, float]] = {}
    for i, d in enumerate(dates):
        chosen = [pool[(i + j) % 4] for j in range(3)]
        w = 1.0 / 3.0
        holdings_by_date[d] = {s: w for s in chosen}
    prices = {
        "AAA": pd.Series([100.0 * (1.01**i) for i in range(12)], index=pd.DatetimeIndex(dates)),
        "BBB": pd.Series([50.0 * (1.02**i) for i in range(12)], index=pd.DatetimeIndex(dates)),
        "CCC": _flat_price_series(80.0, dates),
        "DDD": pd.Series([120.0 * (0.995**i) for i in range(12)], index=pd.DatetimeIndex(dates)),
    }
    return holdings_by_date, prices


def _scenario_flat_prices():
    dates = _monthly_dates(11)
    holdings_by_date = {d: {"AAA": 0.5, "BBB": 0.5} for d in dates}
    prices = {
        "AAA": _flat_price_series(100.0, dates),
        "BBB": _flat_price_series(60.0, dates),
    }
    return holdings_by_date, prices


def _scenario_missing_and_stale():
    """10 monthly dates. GHOST has no price series at all (missing). BBB only
    has prices on every other date (forces stale-price events, same as the
    incumbent's `_pit_price` look-back behavior)."""
    dates = _monthly_dates(10)
    holdings_by_date = {d: {"AAA": 0.4, "BBB": 0.3, "GHOST": 0.3} for d in dates}
    sparse_dates = [dates[i] for i in range(0, 10, 2)]
    prices = {
        "AAA": pd.Series([90.0 * (1.015**i) for i in range(10)], index=pd.DatetimeIndex(dates)),
        "BBB": pd.Series([70.0 * (1.01**i) for i in range(len(sparse_dates))], index=pd.DatetimeIndex(sparse_dates)),
        # GHOST intentionally absent from price_by_symbol
    }
    return holdings_by_date, prices


SCENARIOS = {
    "multi_symbol_geometric": _scenario_multi_symbol_geometric,
    "flat_prices": _scenario_flat_prices,
    "missing_and_stale": _scenario_missing_and_stale,
}


@pytest.mark.parametrize("scenario_name", list(SCENARIOS))
def test_g0_parity_monthly_frame(scenario_name):
    holdings_by_date, prices = SCENARIOS[scenario_name]()
    base_config = LiveLikeConfig(cost_bps=25.0)

    incumbent = run_vintage_backtest(holdings_by_date, price_by_symbol=prices, config=base_config)
    gated_monthly, _events = run_gated_vintage_backtest(
        holdings_by_date,
        price_by_symbol=prices,
        gate_by_symbol=None,
        config=CombinedConfig(base=base_config, gate="G0"),
    )

    pd.testing.assert_frame_equal(
        incumbent[SHARED_MONTHLY_COLUMNS].reset_index(drop=True),
        gated_monthly[SHARED_MONTHLY_COLUMNS].reset_index(drop=True),
        check_dtype=False,
    )

    # Extra Phase-1 columns must be present and G0-quiescent.
    assert (gated_monthly["n_pending"] == 0).all()
    assert (gated_monthly["n_confirmed_late"] == 0).all()
    assert (gated_monthly["n_early_exits"] == 0).all()
    assert (gated_monthly["gate_blocked_weight"] == 0).all()
    assert "cash_weight" in gated_monthly.columns


@pytest.mark.parametrize("scenario_name", list(SCENARIOS))
def test_g0_parity_summary(scenario_name):
    holdings_by_date, prices = SCENARIOS[scenario_name]()
    base_config = LiveLikeConfig(cost_bps=40.0)

    incumbent = run_vintage_backtest(holdings_by_date, price_by_symbol=prices, config=base_config)
    gated_monthly, _events = run_gated_vintage_backtest(
        holdings_by_date,
        price_by_symbol=prices,
        gate_by_symbol=None,
        config=CombinedConfig(base=base_config, gate="G0"),
    )

    incumbent_summary = summarize_performance(incumbent, periods_per_year=12)
    gated_summary = summarize_performance(gated_monthly, periods_per_year=12)

    assert set(incumbent_summary) == set(gated_summary)
    for key, expected in incumbent_summary.items():
        actual = gated_summary[key]
        if isinstance(expected, float) and isinstance(actual, float):
            if math.isnan(expected):
                assert math.isnan(actual)
            else:
                assert actual == pytest.approx(expected, rel=1e-9, abs=1e-12)
        else:
            assert actual == expected


def test_g0_events_match_trade_ledger():
    holdings_by_date, prices = _scenario_multi_symbol_geometric()
    base_config = LiveLikeConfig(cost_bps=33.0)

    ledger = build_trade_ledger(holdings_by_date, config=base_config)
    _monthly, events = run_gated_vintage_backtest(
        holdings_by_date,
        price_by_symbol=prices,
        gate_by_symbol=None,
        config=CombinedConfig(base=base_config, gate="G0"),
    )

    # Compare as sorted lists of plain tuples (weight rounded for float-safe
    # equality) since row ordering between the two engines may differ.
    def _as_sorted_tuples(frame: pd.DataFrame) -> list[tuple]:
        return sorted(
            (row["date"], row["action"], row["symbol"], row["vintage_formed"], round(float(row["weight"]), 12))
            for _, row in frame.iterrows()
        )

    assert _as_sorted_tuples(ledger) == _as_sorted_tuples(events)
    # sanity: both actions appear given expiry occurs within the window
    assert set(events["action"]) == {ACTION_BUY, ACTION_SELL}


def test_cash_weight_warmup():
    dates = _monthly_dates(9)
    holdings_by_date = {d: {"AAA": 0.5, "BBB": 0.5} for d in dates}
    prices = {
        "AAA": _flat_price_series(100.0, dates),
        "BBB": _flat_price_series(60.0, dates),
    }
    monthly, _events = run_gated_vintage_backtest(
        holdings_by_date,
        price_by_symbol=prices,
        gate_by_symbol=None,
        config=CombinedConfig(base=LiveLikeConfig(), gate="G0"),
    )

    cash = monthly["cash_weight"].tolist()
    # Warm-up: i-th period (0-indexed) has i+1 active vintages (no expiry yet
    # since the pool never runs out within 6 periods here), each contributing
    # 1/6 of the fully-allocated (AAA+BBB sum to 1.0) vintage weight.
    for i in range(6):
        expected = 1.0 - (i + 1) / 6.0
        assert cash[i] == pytest.approx(expected, abs=1e-9)
    assert monthly["cash_weight"].iloc[:6].is_monotonic_decreasing
    # Fully warmed up (6 active vintages, complete holdings every period) ->
    # ~0 cash from period index 5 onward.
    for i in range(5, 9):
        assert cash[i] == pytest.approx(0.0, abs=1e-9)


def test_turnover_cost_accounting():
    dates = _monthly_dates(3)
    holdings_by_date = {
        dates[0]: {"AAA": 1.0},
        dates[1]: {"BBB": 1.0},
        dates[2]: {},
    }
    prices = {
        "AAA": _flat_price_series(100.0, dates),
        "BBB": _flat_price_series(50.0, dates),
    }
    cost_bps = 100.0
    monthly, _events = run_gated_vintage_backtest(
        holdings_by_date,
        price_by_symbol=prices,
        gate_by_symbol=None,
        config=CombinedConfig(base=LiveLikeConfig(cost_bps=cost_bps), gate="G0"),
    )

    # Period 0 (formation of AAA): turnover from {} -> {"AAA": 1/6} is 1/6
    # (previous empty branch: sum of abs diffs, not halved). Cost is forced to
    # 0.0 at i==0 regardless of turnover (matches incumbent convention).
    assert monthly["turnover"].iloc[0] == pytest.approx(1.0 / 6.0)
    assert monthly["cost"].iloc[0] == pytest.approx(0.0)

    # Period 1 (AAA ages to months_held=1, BBB forms): combined goes from
    # {"AAA": 1/6} -> {"AAA": 1/6, "BBB": 1/6}; both dicts non-empty so
    # turnover = 0.5 * sum(abs diffs) = 0.5 * (0 + 1/6) = 1/12.
    expected_turnover_1 = 1.0 / 12.0
    expected_cost_1 = (cost_bps / 10000.0) * 2.0 * expected_turnover_1
    assert monthly["turnover"].iloc[1] == pytest.approx(expected_turnover_1)
    assert monthly["cost"].iloc[1] == pytest.approx(expected_cost_1)
    assert monthly["gross_return"].iloc[1] == pytest.approx(0.0)  # flat prices
    assert monthly["net_return"].iloc[1] == pytest.approx(0.0 - expected_cost_1)

    # Period 2 (no new formation, no expiry -> combined unchanged) -> turnover 0.
    assert monthly["turnover"].iloc[2] == pytest.approx(0.0)
    assert monthly["cost"].iloc[2] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Phase 2: gating semantics
# ---------------------------------------------------------------------------


def _gate_series(values: list[float], dates: list[dt.date]) -> pd.Series:
    return pd.Series(values, index=pd.DatetimeIndex(dates), dtype=float)


def test_gate_blocks_at_formation_without_redistribution():
    dates = _monthly_dates(8)
    holdings_by_date = {d: {"AAA": 0.5, "BBB": 0.5} for d in dates}
    prices = {
        "AAA": _flat_price_series(100.0, dates),
        "BBB": _flat_price_series(60.0, dates),
    }
    gate = {
        "AAA": _gate_series([1.0] * 8, dates),
        "BBB": _gate_series([0.0] * 8, dates),  # blocked forever
    }
    monthly, events = run_gated_vintage_backtest(
        holdings_by_date,
        price_by_symbol=prices,
        gate_by_symbol=gate,
        config=CombinedConfig(base=LiveLikeConfig(), gate="G1", exit_mode="X0"),
    )

    # BBB blocked at every formation: one GATE_BLOCK per date, weight 0.5/6.
    blocks = events[events["action"] == ACTION_GATE_BLOCK]
    assert list(blocks["symbol"].unique()) == ["BBB"]
    assert len(blocks) == 8
    assert blocks["weight"].tolist() == pytest.approx([0.5 / 6.0] * 8)

    # No redistribution: AAA's BUY weight stays at its reserved 0.5/6.
    buys = events[events["action"] == ACTION_BUY]
    assert set(buys["symbol"]) == {"AAA"}
    assert buys["weight"].tolist() == pytest.approx([0.5 / 6.0] * 8)

    # Fully warmed up (period index >= 5): 6 active vintages, each holding
    # only AAA at 0.5 -> invested 0.5, blocked 0.5, cash 0.5.
    for i in range(5, 8):
        assert monthly["gate_blocked_weight"].iloc[i] == pytest.approx(0.5, abs=1e-9)
        assert monthly["cash_weight"].iloc[i] == pytest.approx(0.5, abs=1e-9)
        assert monthly["n_pending"].iloc[i] == 6
    # BBB never confirmed late (stance is explicit 0, never missing/True).
    assert (events["action"] != ACTION_LATE_BUY).all()


def test_missing_gate_policy_pass_vs_block():
    dates = _monthly_dates(3)
    holdings_by_date = {dates[0]: {"AAA": 1.0}, dates[1]: {}, dates[2]: {}}
    prices = {"AAA": _flat_price_series(100.0, dates)}
    gate: dict[str, pd.Series] = {}  # AAA has no gate series at all

    for policy, expect_confirmed in (("pass", True), ("block", False)):
        monthly, events = run_gated_vintage_backtest(
            holdings_by_date,
            price_by_symbol=prices,
            gate_by_symbol=gate,
            config=CombinedConfig(base=LiveLikeConfig(), gate="G1", missing_gate_policy=policy),
        )
        if expect_confirmed:
            assert (events["action"] == ACTION_BUY).any()
            assert monthly["n_pending"].iloc[0] == 0
        else:
            assert (events["action"] == ACTION_GATE_BLOCK).all()
            assert monthly["n_pending"].iloc[0] == 1


def test_late_confirmation_within_window():
    dates = _monthly_dates(8)
    holdings_by_date: dict[dt.date, dict[str, float]] = {dates[0]: {"AAA": 1.0}}
    for d in dates[1:]:
        holdings_by_date[d] = {}
    prices = {"AAA": pd.Series([100.0 * (1.02**i) for i in range(8)], index=pd.DatetimeIndex(dates))}
    # Blocked at formation (d0), long from d1 -> late-confirms at d1 (months_held=0 < K=2).
    gate = {"AAA": _gate_series([0.0] + [1.0] * 7, dates)}
    monthly, events = run_gated_vintage_backtest(
        holdings_by_date,
        price_by_symbol=prices,
        gate_by_symbol=gate,
        config=CombinedConfig(base=LiveLikeConfig(cost_bps=0.0), gate="G1", confirm_window_months=2),
    )

    late = events[events["action"] == ACTION_LATE_BUY]
    assert len(late) == 1
    assert late.iloc[0]["date"] == dates[1]
    assert late.iloc[0]["weight"] == pytest.approx(1.0 / 6.0)
    assert monthly["n_confirmed_late"].iloc[1] == 1

    # Return attribution: period 1 realized with pre-confirmation holdings
    # (nothing) -> 0; period 2 earns the late-entered 1/6 * 2%.
    assert monthly["gross_return"].iloc[1] == pytest.approx(0.0)
    assert monthly["gross_return"].iloc[2] == pytest.approx((1.0 / 6.0) * 0.02, rel=1e-9)
    # Late entry shows up in period-1 turnover: {} -> {"AAA": 1/6}... prev was
    # {"AAA": 0} pending only, so prev combined empty -> min(1, 1/6).
    assert monthly["turnover"].iloc[1] == pytest.approx(1.0 / 6.0)


def test_late_confirmation_window_expires():
    dates = _monthly_dates(8)
    holdings_by_date: dict[dt.date, dict[str, float]] = {dates[0]: {"AAA": 1.0}}
    for d in dates[1:]:
        holdings_by_date[d] = {}
    prices = {"AAA": _flat_price_series(100.0, dates)}
    # Gate only turns long at d3: months_held at the d3 check is 2, not < K=2
    # -> never enters.
    gate = {"AAA": _gate_series([0.0, 0.0, 0.0] + [1.0] * 5, dates)}
    monthly, events = run_gated_vintage_backtest(
        holdings_by_date,
        price_by_symbol=prices,
        gate_by_symbol=gate,
        config=CombinedConfig(base=LiveLikeConfig(), gate="G1", confirm_window_months=2),
    )

    assert (events["action"] == ACTION_GATE_BLOCK).all()  # only the block row
    assert (monthly["n_holdings"] == 0).all()
    # Pending weight visible until the vintage expires at d6, then gone.
    assert monthly["gate_blocked_weight"].iloc[5] == pytest.approx(1.0 / 6.0)
    assert monthly["gate_blocked_weight"].iloc[6] == pytest.approx(0.0)
    # A never-confirmed name is never bought, hence never sold.
    assert not (events["action"] == ACTION_SELL).any()


def test_x1_early_exit_and_x0_hold():
    dates = _monthly_dates(8)
    holdings_by_date: dict[dt.date, dict[str, float]] = {dates[0]: {"AAA": 1.0}}
    for d in dates[1:]:
        holdings_by_date[d] = {}
    prices = {"AAA": pd.Series([100.0 * (1.02**i) for i in range(8)], index=pd.DatetimeIndex(dates))}
    # Long at d0/d1, flips to 0 from d2 onward.
    gate = {"AAA": _gate_series([1.0, 1.0] + [0.0] * 6, dates)}

    monthly_x1, events_x1 = run_gated_vintage_backtest(
        holdings_by_date,
        price_by_symbol=prices,
        gate_by_symbol=gate,
        config=CombinedConfig(base=LiveLikeConfig(cost_bps=0.0), gate="G1", exit_mode="X1"),
    )
    exits = events_x1[events_x1["action"] == ACTION_EARLY_EXIT]
    assert len(exits) == 1
    assert exits.iloc[0]["date"] == dates[2]
    assert exits.iloc[0]["weight"] == pytest.approx(1.0 / 6.0)
    assert monthly_x1["n_early_exits"].iloc[2] == 1
    # Period 2's return was realized BEFORE the exit check -> still earns 2%.
    assert monthly_x1["gross_return"].iloc[2] == pytest.approx((1.0 / 6.0) * 0.02, rel=1e-9)
    # From period 3 the position is cash; no expiry SELL for an exited name.
    assert monthly_x1["gross_return"].iloc[3] == pytest.approx(0.0)
    assert not (events_x1["action"] == ACTION_SELL).any()
    # Exit turnover at d2: {"AAA": 1/6} -> {} = min(1, 1/6) via empty branch.
    assert monthly_x1["turnover"].iloc[2] == pytest.approx(1.0 / 6.0)

    monthly_x0, events_x0 = run_gated_vintage_backtest(
        holdings_by_date,
        price_by_symbol=prices,
        gate_by_symbol=gate,
        config=CombinedConfig(base=LiveLikeConfig(cost_bps=0.0), gate="G1", exit_mode="X0"),
    )
    assert not (events_x0["action"] == ACTION_EARLY_EXIT).any()
    # Held to expiry: earns every month until the d6 expiry SELL.
    assert monthly_x0["gross_return"].iloc[5] == pytest.approx((1.0 / 6.0) * 0.02, rel=1e-9)
    assert (events_x0["action"] == ACTION_SELL).sum() == 1


# ---------------------------------------------------------------------------
# Phase 2: gate builders
# ---------------------------------------------------------------------------


def test_g1_sma_gate_math_and_warmup():
    days = [d.date() for d in pd.date_range("2024-01-01", periods=6, freq="B")]
    close = pd.Series([1.0, 1.0, 1.0, 2.0, 2.0, 1.0], index=pd.DatetimeIndex(days))
    cfg = CombinedConfig(gate="G1", g1_rule="sma", g1_sma_days=3)
    gate = build_trend_gate_series({"AAA": close}, cfg)["AAA"]

    # Warm-up: SMA undefined for the first 2 bars -> NaN -> stance None.
    assert math.isnan(gate.iloc[0]) and math.isnan(gate.iloc[1])
    assert pit_value(gate, days[1]) is None
    # Bar 2: close 1.0 vs SMA(1,1,1)=1.0 -> not strictly above -> 0.
    assert gate.iloc[2] == 0.0
    # Bar 3: close 2.0 vs SMA(1,1,2)=4/3 -> 1. Bar 5: close 1.0 vs SMA(2,2,1)=5/3 -> 0.
    assert gate.iloc[3] == 1.0
    assert gate.iloc[5] == 0.0


def test_g1_momentum_gate_math():
    days = [d.date() for d in pd.date_range("2024-01-01", periods=8, freq="B")]
    rising = pd.Series([float(100 + i) for i in range(8)], index=pd.DatetimeIndex(days))
    falling = pd.Series([float(100 - i) for i in range(8)], index=pd.DatetimeIndex(days))
    cfg = CombinedConfig(gate="G1", g1_rule="momentum", g1_mom_formation_days=3, g1_mom_skip_days=1)
    gates = build_trend_gate_series({"UP": rising, "DOWN": falling}, cfg)

    # mom_t = c[t-1]/c[t-4] - 1: defined from bar index 4 onward.
    assert math.isnan(gates["UP"].iloc[3])
    assert gates["UP"].iloc[4] == 1.0
    assert gates["DOWN"].iloc[4] == 0.0


def test_g1_either_rule_or_semantics():
    days = [d.date() for d in pd.date_range("2024-01-01", periods=10, freq="B")]
    # Rising then plateau: momentum positive early, SMA warm-up longer -> the
    # "either" gate should be defined (from momentum) before SMA is defined.
    close = pd.Series([float(100 + i) for i in range(10)], index=pd.DatetimeIndex(days))
    cfg = CombinedConfig(gate="G1", g1_rule="either", g1_sma_days=8, g1_mom_formation_days=2, g1_mom_skip_days=1)
    gate = build_trend_gate_series({"AAA": close}, cfg)["AAA"]

    # Bars 0-2: both undefined -> NaN. Bar 3: momentum defined (1), SMA NaN -> 1.
    assert math.isnan(gate.iloc[2])
    assert gate.iloc[3] == 1.0
    # Bar 7+: SMA defined too; rising series -> still 1.
    assert gate.iloc[8] == 1.0


def test_g1_gate_is_point_in_time():
    days = [d.date() for d in pd.date_range("2024-01-01", periods=12, freq="B")]
    full = pd.Series([float(100 + i) for i in range(12)], index=pd.DatetimeIndex(days))
    cfg = CombinedConfig(gate="G1", g1_rule="sma", g1_sma_days=3)
    gate_full = build_trend_gate_series({"AAA": full}, cfg)["AAA"]
    gate_trunc = build_trend_gate_series({"AAA": full.iloc[:8]}, cfg)["AAA"]
    # The first 8 gate values must be identical whether or not later bars exist.
    pd.testing.assert_series_equal(gate_full.iloc[:8], gate_trunc, check_names=False)


def test_g2_aggregation_threshold_and_min_categories():
    d1, d2, d3 = (pd.Timestamp("2025-01-02"), pd.Timestamp("2025-01-03"), pd.Timestamp("2025-01-06"))
    rows = [
        # d1: all four categories, mean = 25 -> long at threshold 20.
        *[{"date": d1, "symbol": "AAA", "category": c, "score_pct": s}
          for c, s in (("tendance", 100.0), ("momentum", 0.0), ("oscillation", 0.0), ("volume", 0.0))],
        # d2: two categories, mean 0 -> flat.
        {"date": d2, "symbol": "AAA", "category": "tendance", "score_pct": 0.0},
        {"date": d2, "symbol": "AAA", "category": "momentum", "score_pct": 0.0},
        # d3: single category at 100 -> defined only if min_categories == 1.
        {"date": d3, "symbol": "AAA", "category": "tendance", "score_pct": 100.0},
    ]
    frame = pd.DataFrame(rows)

    gate1 = aggregate_wfo_gate(frame, threshold=20.0, min_categories=1)["AAA"]
    assert gate1.loc[d1] == 1.0
    assert gate1.loc[d2] == 0.0
    assert gate1.loc[d3] == 1.0

    gate2 = aggregate_wfo_gate(frame, threshold=20.0, min_categories=2)["AAA"]
    assert gate2.loc[d1] == 1.0
    assert math.isnan(gate2.loc[d3])


def test_g2_staleness_treated_as_missing():
    dates = _monthly_dates(8)
    holdings_by_date: dict[dt.date, dict[str, float]] = {dates[0]: {"AAA": 1.0}}
    for d in dates[1:]:
        holdings_by_date[d] = {}
    prices = {"AAA": _flat_price_series(100.0, dates)}
    # One ancient gate observation (explicitly False) long before formation:
    # under G2 staleness it must be treated as MISSING -> policy "pass" enters.
    old = [dt.date(2018, 1, 31)]
    gate = {"AAA": pd.Series([0.0], index=pd.DatetimeIndex(old))}
    _monthly, events = run_gated_vintage_backtest(
        holdings_by_date,
        price_by_symbol=prices,
        gate_by_symbol=gate,
        config=CombinedConfig(base=LiveLikeConfig(), gate="G2", missing_gate_policy="pass"),
    )
    assert (events["action"] == ACTION_BUY).any()
    # Same series under G1 (no staleness limit) would block.
    _monthly_g1, events_g1 = run_gated_vintage_backtest(
        holdings_by_date,
        price_by_symbol=prices,
        gate_by_symbol=gate,
        config=CombinedConfig(base=LiveLikeConfig(), gate="G1"),
    )
    assert (events_g1["action"] == ACTION_GATE_BLOCK).any()


# ---------------------------------------------------------------------------
# Phase 3: risk overlays
# ---------------------------------------------------------------------------


def test_sector_cap_redistributes():
    weights = {"A": 0.4, "B": 0.3, "C": 0.2, "D": 0.1}
    sectors = {"A": "RE", "B": "RE", "C": "FIN", "D": "FIN"}
    cfg = CombinedConfig(sector_cap=0.5, max_name_weight=None)
    out = apply_risk_overlays(weights, sector_map=sectors, config=cfg)
    # RE capped 0.7 -> 0.5 (scaled 5/7); freed 0.2 redistributed to FIN pro rata.
    assert out["A"] == pytest.approx(0.4 * 5 / 7)
    assert out["B"] == pytest.approx(0.3 * 5 / 7)
    assert out["C"] == pytest.approx(0.2 * 5 / 3)
    assert out["D"] == pytest.approx(0.1 * 5 / 3)
    assert sum(out.values()) == pytest.approx(1.0)


def test_name_cap_all_capped_leaves_cash():
    weights = {"A": 0.5, "B": 0.5}
    cfg = CombinedConfig(sector_cap=None, max_name_weight=0.3)
    out = apply_risk_overlays(weights, sector_map={}, config=cfg)
    assert out["A"] == pytest.approx(0.3)
    assert out["B"] == pytest.approx(0.3)
    assert sum(out.values()) == pytest.approx(0.6)  # residual 0.4 stays cash


def test_caps_none_is_noop():
    weights = {"A": 0.6, "B": 0.4}
    cfg = CombinedConfig(sector_cap=None, max_name_weight=None)
    assert apply_risk_overlays(weights, sector_map={}, config=cfg) == weights


def test_adv_floor_drops_and_missing_passes():
    weights = {"A": 1 / 3, "B": 1 / 3, "C": 1 / 3}
    adv = {"A": 50_000.0, "B": None, "C": 200_000.0}
    cfg = CombinedConfig(sector_cap=None, max_name_weight=None, adv_floor_mad=100_000.0)
    out = apply_risk_overlays(weights, sector_map={}, config=cfg, adv_by_symbol=adv)
    assert "A" not in out
    assert out["B"] == pytest.approx(0.5)
    assert out["C"] == pytest.approx(0.5)


def test_compute_pit_adv_series_formula():
    days = [d.date() for d in pd.date_range("2024-01-01", periods=25, freq="B")]
    frame = pd.DataFrame(
        {"Close": [10.0] * 25, "Volume": [1000.0] * 25},
        index=pd.DatetimeIndex(days),
    )
    adv = compute_pit_adv_series({"AAA": frame}, window=20, min_obs=10)["AAA"]
    # Constant 10 * 1000 = 10_000 dirham/day once min_obs reached.
    assert math.isnan(adv.iloc[8])  # fewer than 10 obs
    assert adv.iloc[9] == pytest.approx(10_000.0)
    assert adv.iloc[24] == pytest.approx(10_000.0)


# ---------------------------------------------------------------------------
# Value-momentum study: holdings builders
# ---------------------------------------------------------------------------


def test_build_signal_holdings_tercile_and_filtering():
    d1, d2 = dt.date(2020, 1, 31), dt.date(2020, 2, 29)
    rows = [
        # d1: 6 eligible+notna names (values 10..60), one ineligible with a
        # dominating value (must be excluded), one eligible-but-NaN (excluded).
        {"as_of_date": d1, "symbol": "P1", "eligible_universe": True, "sig": 10.0},
        {"as_of_date": d1, "symbol": "P2", "eligible_universe": True, "sig": 20.0},
        {"as_of_date": d1, "symbol": "P3", "eligible_universe": True, "sig": 30.0},
        {"as_of_date": d1, "symbol": "P4", "eligible_universe": True, "sig": 40.0},
        {"as_of_date": d1, "symbol": "P5", "eligible_universe": True, "sig": 50.0},
        {"as_of_date": d1, "symbol": "P6", "eligible_universe": True, "sig": 60.0},
        {"as_of_date": d1, "symbol": "PX", "eligible_universe": False, "sig": 1000.0},
        {"as_of_date": d1, "symbol": "PN", "eligible_universe": True, "sig": float("nan")},
        # d2: only 5 eligible+notna names -> below min_universe_names=6 -> {}.
        {"as_of_date": d2, "symbol": "Q1", "eligible_universe": True, "sig": 1.0},
        {"as_of_date": d2, "symbol": "Q2", "eligible_universe": True, "sig": 2.0},
        {"as_of_date": d2, "symbol": "Q3", "eligible_universe": True, "sig": 3.0},
        {"as_of_date": d2, "symbol": "Q4", "eligible_universe": True, "sig": 4.0},
        {"as_of_date": d2, "symbol": "Q5", "eligible_universe": True, "sig": 5.0},
    ]
    panel = pd.DataFrame(rows)
    config = LiveLikeConfig(min_universe_names=6)

    holdings = build_signal_holdings(panel, signal_col="sig", config=config)

    # d1: n_bucket = 6 // 3 = 2 -> top 2 by "sig" among P1..P6 only (PX/PN excluded).
    assert holdings[d1] == pytest.approx({"P6": 0.5, "P5": 0.5})
    # d2: only 5 eligible+notna rows < min_names=6 -> empty.
    assert holdings[d2] == {}


def test_build_rank_composite_holdings_hand_computable():
    d1 = dt.date(2020, 1, 31)
    # bm rank positions (ascending) 1..6 for A..F; momentum positions chosen
    # so the two rankings are NOT simply anti-correlated (composite has a
    # unique separation between the top tercile and the rest):
    #   composite*12 = bm_pos + mom_pos
    #   A: 1+3=4 -> 0.33333   B: 2+1=3 -> 0.25      C: 3+6=9 -> 0.75
    #   D: 4+2=6 -> 0.5       E: 5+5=10 -> 0.83333  F: 6+4=10 -> 0.83333
    # Top tercile (n_bucket = 6 // 3 = 2) = {E, F}, clearly above C=0.75.
    bm = {"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0, "E": 5.0, "F": 6.0}
    mom = {"A": 3.0, "B": 1.0, "C": 6.0, "D": 2.0, "E": 5.0, "F": 4.0}
    rows = [
        {"as_of_date": d1, "symbol": sym, "elig": True, "bm": bm[sym], "mom": mom[sym]}
        for sym in bm
    ]
    # Ineligible name with an attractive composite (must be excluded).
    rows.append({"as_of_date": d1, "symbol": "GX", "elig": False, "bm": 100.0, "mom": 100.0})
    # Eligible name missing one component (must be excluded by notna filter).
    rows.append({"as_of_date": d1, "symbol": "HX", "elig": True, "bm": 100.0, "mom": float("nan")})
    panel = pd.DataFrame(rows)
    config = LiveLikeConfig(min_universe_names=6)

    holdings = build_rank_composite_holdings(
        panel,
        components=[("bm", 0.5), ("mom", 0.5)],
        eligibility_cols=["elig"],
        config=config,
    )

    assert holdings[d1] == pytest.approx({"E": 0.5, "F": 0.5})


def test_build_graceful_composite_holdings_hand_computable():
    """9 names, 3 (N1/N2/N3) lack the secondary signal. Weights 0.5/0.5.
    primary_rank(N_a) = a/9 for a=1..9 (primary_raw = a). Present-secondary
    names N4..N9 get secondary_raw chosen so their secondary rank (of the 6
    present names) is b = 10-a, i.e. composite*36 = 2a + 3b = 2a + 3(10-a) =
    30 - a (present) vs 2a + 9 (missing, imputed 0.5*0.5*2=0.25 -> +9/36).
    Missing composites (N1..N3): 11,13,15 (/36). Present composites
    (N4..N9, a=4..9): 26,25,24,23,22,21 (/36). All 9 values distinct -> top-3
    (n_bucket = 9//3 = 3) = N4, N5, N6 unambiguously."""
    d1 = dt.date(2020, 1, 31)
    primary_raw = {f"N{i}": float(i) for i in range(1, 10)}
    secondary_raw = {
        "N1": float("nan"),
        "N2": float("nan"),
        "N3": float("nan"),
        "N4": 6.0,
        "N5": 5.0,
        "N6": 4.0,
        "N7": 3.0,
        "N8": 2.0,
        "N9": 1.0,
    }
    rows = [
        {"as_of_date": d1, "symbol": sym, "elig": True, "prim": primary_raw[sym], "sec": secondary_raw[sym]}
        for sym in primary_raw
    ]
    panel = pd.DataFrame(rows)
    # min_universe_names=9: this threshold can only be satisfied (non-empty
    # holdings) if the graceful universe kept all 9 names -- if the 3
    # missing-secondary names had been dropped, only 6 would remain (<9) and
    # _tercile_holdings would return {} instead. This is (i).
    config = LiveLikeConfig(min_universe_names=9)

    holdings = build_graceful_composite_holdings(
        panel,
        primary=("prim", 0.5),
        secondary=("sec", 0.5),
        eligibility_col="elig",
        config=config,
    )

    assert holdings[d1] != {}  # (i) universe kept all 9 names
    assert holdings[d1] == pytest.approx({"N4": 1 / 3, "N5": 1 / 3, "N6": 1 / 3})  # (iii)


def test_build_graceful_composite_holdings_no_secondary_coverage():
    """When NO name has the secondary signal, composite = w_p*primary_rank +
    w_s*0.5 for every name -- a constant offset, so selection ordering must
    equal pure primary-signal ranking. 6 names, top tercile (n_bucket=2)
    picks the 2 highest primary values regardless of secondary weight."""
    d1 = dt.date(2020, 1, 31)
    rows = [
        {"as_of_date": d1, "symbol": f"X{i}", "elig": True, "prim": float(i), "sec": float("nan")}
        for i in range(1, 7)
    ]
    panel = pd.DataFrame(rows)
    config = LiveLikeConfig(min_universe_names=6)

    holdings = build_graceful_composite_holdings(
        panel,
        primary=("prim", 0.3),
        secondary=("sec", 0.7),
        eligibility_col="elig",
        config=config,
    )

    assert holdings[d1] == pytest.approx({"X5": 0.5, "X6": 0.5})


def test_build_graceful_composite_holdings_missing_imputed_at_neutral_0_5():
    """Precision check that the imputed secondary rank for a missing name is
    exactly 0.5, not some other placeholder (e.g. 0 or the group mean).

    6 names, weights 0.5/0.5, primary_raw = position (1..6). 5 names have a
    real secondary signal (ranks .2/.4/.6/.8/1.0 among themselves); MISS
    (position 5) lacks it. Composites (with correct 0.5 imputation):
      TOP (pos6, sec_rank=1.0):  .5*1 + .5*1.0   = 1.0000  (clear #1)
      MISS(pos5, imputed 0.5):   .5*5/6 + .5*0.5 = 0.6667
      COMP(pos4, sec_rank=0.6):  .5*4/6 + .5*0.6 = 0.6333
      LOW1(pos1, sec_rank=0.8):  .5*1/6 + .5*0.8 = 0.4833
      LOW2(pos2, sec_rank=0.4):  .5*2/6 + .5*0.4 = 0.3667
      LOW3(pos3, sec_rank=0.2):  .5*3/6 + .5*0.2 = 0.3500
    Top-2 (n_bucket=2) = TOP, MISS -- MISS narrowly beats COMP (0.6667 vs
    0.6333) ONLY because the imputed value is 0.5: had it been imputed at
    0.4 (a plausible bug -- e.g. treating missing as "worst case"), MISS's
    composite would drop to 0.6167 < COMP's 0.6333 and COMP would take the
    #2 spot instead. This test therefore pins the imputation constant to
    0.5 within a tight, deliberately-constructed band, not just "some
    constant"."""
    d1 = dt.date(2020, 1, 31)
    primary_raw = {"LOW1": 1.0, "LOW2": 2.0, "LOW3": 3.0, "COMP": 4.0, "MISS": 5.0, "TOP": 6.0}
    secondary_raw = {"LOW3": 10.0, "LOW2": 20.0, "COMP": 30.0, "LOW1": 40.0, "TOP": 50.0, "MISS": float("nan")}
    rows = [
        {"as_of_date": d1, "symbol": sym, "elig": True, "prim": primary_raw[sym], "sec": secondary_raw[sym]}
        for sym in primary_raw
    ]
    panel = pd.DataFrame(rows)
    config = LiveLikeConfig(min_universe_names=6)

    holdings = build_graceful_composite_holdings(
        panel,
        primary=("prim", 0.5),
        secondary=("sec", 0.5),
        eligibility_col="elig",
        config=config,
    )

    assert holdings[d1] == pytest.approx({"TOP": 0.5, "MISS": 0.5})


# ---------------------------------------------------------------------------
# Phase 3: statistics
# ---------------------------------------------------------------------------


def _monthly_frame(dates: list[dt.date], returns: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"as_of_date": dates, "net_return": returns, "turnover": [0.1] * len(dates)})


def test_difference_test_identical_and_dominant():
    dates = _monthly_dates(36)
    base = [0.01 if i % 2 == 0 else -0.005 for i in range(36)]
    same = difference_test(_monthly_frame(dates, base), _monthly_frame(dates, base))
    assert same["nobs"] == 36
    assert same["mean_monthly_diff"] == pytest.approx(0.0)

    better = [r + 0.02 for r in base]
    dom = difference_test(_monthly_frame(dates, better), _monthly_frame(dates, base))
    assert dom["mean_monthly_diff"] == pytest.approx(0.02)
    # A constant +2%/month improvement has zero variance in the diff... the
    # bootstrap centers it, so observed >> null -> tiny p-value.
    assert dom["pvalue"] is not None and dom["pvalue"] <= 0.05


def test_evaluate_acceptance_verdicts():
    primary = {"sharpe": 1.0, "max_drawdown": -0.20}
    incumbent = {"sharpe": 0.8, "max_drawdown": -0.25}
    diff_sig = {"pvalue": 0.03, "mean_monthly_diff": 0.01}
    diff_weak = {"pvalue": 0.40, "mean_monthly_diff": 0.01}

    a = evaluate_acceptance(primary, incumbent, diff_sig, masi_sharpe=0.5)
    assert a["verdict"] == "A"
    b = evaluate_acceptance(primary, incumbent, diff_weak, masi_sharpe=0.5)
    assert b["verdict"] == "B"
    # Sharpe worse -> C regardless of p-value.
    c = evaluate_acceptance({"sharpe": 0.5, "max_drawdown": -0.20}, incumbent, diff_sig)
    assert c["verdict"] == "C"
    # Drawdown breach beyond tolerance -> C.
    d = evaluate_acceptance({"sharpe": 1.0, "max_drawdown": -0.30}, incumbent, diff_sig)
    assert d["verdict"] == "C"
    # A-grade blocked by MASI Sharpe -> B.
    e = evaluate_acceptance(primary, incumbent, diff_sig, masi_sharpe=1.5)
    assert e["verdict"] == "B"
    # Significant p-value but NEGATIVE mean monthly diff -> criterion (c) must
    # fail despite the low p-value (sign-blind pass was the pre-registered
    # defect); (a) and (b) still pass -> verdict B, not A.
    diff_sig_negative = {"pvalue": 0.03, "mean_monthly_diff": -0.01}
    f = evaluate_acceptance(primary, incumbent, diff_sig_negative, masi_sharpe=0.5)
    assert f["verdict"] == "B"
    assert f["criteria"]["c_difference_pvalue"]["pass"] is False
