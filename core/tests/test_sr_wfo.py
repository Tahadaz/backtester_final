from __future__ import annotations

import numpy as np
import pytest

from core.quant_core.signal_engine.sr_wfo import (
    line_touch_stats,
    run_sr_wfo,
    simulate_touch_pair,
    sr_window_plan,
)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _oscillator_fixture(n_bars: int = 800, period: float = 10.0, amplitude: float = 12.0):
    t = np.arange(n_bars, dtype="float64")
    price = 100.0 + amplitude * np.sin(2.0 * np.pi * t / period)
    close = price.copy()
    high = price + 1.0
    low = price - 1.0
    open_ = np.empty(n_bars, dtype="float64")
    open_[0] = close[0]
    open_[1:] = close[:-1]
    return close, high, low, open_


@pytest.fixture()
def oscillator():
    close, high, low, open_ = _oscillator_fixture()
    n = len(close)
    support_a = np.full(n, 90.0, dtype="float64")
    resistance_a = np.full(n, 110.0, dtype="float64")
    support_b = np.full(n, 50.0, dtype="float64")
    resistance_b = np.full(n, 200.0, dtype="float64")
    pair_series = {
        "A": (support_a, resistance_a),
        "B": (support_b, resistance_b),
    }
    pair_meta = {
        "A": {
            "support_method_id": "manual_a",
            "support_line_id": "S1",
            "resistance_method_id": "manual_a",
            "resistance_line_id": "R1",
        },
        "B": {
            "support_method_id": "manual_b",
            "support_line_id": "S1",
            "resistance_method_id": "manual_b",
            "resistance_line_id": "R1",
        },
    }
    return close, high, low, open_, pair_series, pair_meta


HORIZON_WEEKLY = {"train": 252, "test": 21, "step": 21}


# ---------------------------------------------------------------------------
# 1. oscillator: procedure selects pair A every selectable window
# ---------------------------------------------------------------------------


def test_oscillator_selects_pair_a_and_shows_positive_edge(oscillator):
    close, high, low, open_, pair_series, pair_meta = oscillator
    result = run_sr_wfo(
        close=close,
        high=high,
        low=low,
        open_=open_,
        pair_series=pair_series,
        pair_meta=pair_meta,
        train=HORIZON_WEEKLY["train"],
        test=HORIZON_WEEKLY["test"],
        step=HORIZON_WEEKLY["step"],
        cost_bps=33.0,
        cooldown_bars=1,
        min_train_trades=3,
        bootstrap_iter=200,
        seed=7,
    )
    assert result["status"] == "ok"
    selectable_windows = [w for w in result["windows"] if w["selected_pair_id"] is not None]
    assert selectable_windows, "expected at least one selectable window"
    for window in selectable_windows:
        assert window["selected_pair_id"] == "A"

    assert result["procedure_oos"]["total_return"] > 0.0
    assert result["decision"] != "no_edge"

    # pair B never accumulates trades over the full continuous history
    stability = result["stability"]
    assert stability["pair_win_counts"].get("B", 0) == 0


# ---------------------------------------------------------------------------
# 2. gap fill: entry fill == open, not the level
# ---------------------------------------------------------------------------


def test_gap_down_entry_fills_at_open_not_level():
    n = 6
    close = np.array([100.0, 100.0, 100.0, 100.0, 100.0, 100.0])
    high = np.array([100.5, 100.5, 100.5, 100.5, 100.5, 100.5])
    low = np.array([100.5, 100.5, 90.0, 99.5, 99.5, 99.5])
    open_ = np.array([100.0, 100.0, 95.0, 100.0, 100.0, 100.0])
    support = np.full(n, 100.0, dtype="float64")
    resistance = np.full(n, 120.0, dtype="float64")

    sim = simulate_touch_pair(
        close=close,
        high=high,
        low=low,
        open_=open_,
        support_series=support,
        resistance_series=resistance,
        start=0,
        end=n - 1,
        cost_bps=0.0,
        cooldown_bars=0,
    )
    entry_trades = [t for t in sim["trades"] if t["entry_bar"] == 2]
    # entry recorded either as a closed trade later or still open; find the fill via bar 2 return
    entry_bar_return = sim["returns"][2 - 1]
    fill = 95.0  # open[2] since open < support(100)
    expected_return = close[2] / fill - 1.0
    assert entry_bar_return == pytest.approx(expected_return)
    assert fill < 100.0


def test_touch_bar_fills_same_bar_at_level_not_next_bar_open():
    # bar 1 touches support(100) intrabar (low<=100) with no gap (open==prev close),
    # and closes flat; the fill must be recorded on bar 1 itself at the level
    # price (100.0), never deferred to bar 2's open (which is deliberately set
    # far away to prove it is NOT used as the fill).
    n = 4
    close = np.array([100.0, 100.0, 100.0, 100.0])
    high = np.array([100.5, 100.5, 100.5, 100.5])
    low = np.array([99.5, 98.0, 99.5, 99.5])
    open_ = np.array([100.0, 100.0, 250.0, 100.0])  # bar2 open is a decoy far from the level
    support = np.full(n, 100.0, dtype="float64")
    resistance = np.full(n, 300.0, dtype="float64")

    sim = simulate_touch_pair(
        close=close,
        high=high,
        low=low,
        open_=open_,
        support_series=support,
        resistance_series=resistance,
        start=0,
        end=n - 1,
        cost_bps=0.0,
        cooldown_bars=0,
    )
    # entry-bar (bar 1) return must reflect a fill at the level (100.0), i.e. zero
    # since close[1] == support == 100.0, and must NOT use bar 2's decoy open.
    entry_bar_return = sim["returns"][1 - 1]
    assert entry_bar_return == pytest.approx(0.0)


def test_support_above_market_never_triggers_entries():
    # A support series that sits ABOVE all prices satisfies `low <= support`
    # trivially on every bar; without the `support <= prev_close` touch guard
    # it would degenerate into quasi buy-and-hold. It must produce zero trades
    # and all-zero returns.
    close, high, low, open_ = _oscillator_fixture(n_bars=300)
    n = len(close)
    support = (high * 1.1).astype("float64")  # always above the market
    resistance = np.full(n, 500.0, dtype="float64")

    sim = simulate_touch_pair(
        close=close,
        high=high,
        low=low,
        open_=open_,
        support_series=support,
        resistance_series=resistance,
        start=0,
        end=n - 1,
        cost_bps=33.0,
        cooldown_bars=0,
    )
    assert sim["n_trades"] == 0
    assert sim["trades"] == []
    assert np.all(sim["returns"] == 0.0)


# ---------------------------------------------------------------------------
# 3. no same-bar round trip
# ---------------------------------------------------------------------------


def test_no_same_bar_round_trip():
    n = 5
    close = np.array([100.0, 100.0, 100.0, 100.0, 100.0])
    # bar 1: low touches support(90) AND high touches resistance(110) while flat
    high = np.array([100.5, 111.0, 111.0, 111.0, 100.5])
    low = np.array([99.5, 85.0, 99.5, 99.5, 99.5])
    open_ = np.array([100.0, 100.0, 100.0, 100.0, 100.0])
    support = np.full(n, 90.0, dtype="float64")
    resistance = np.full(n, 110.0, dtype="float64")

    sim = simulate_touch_pair(
        close=close,
        high=high,
        low=low,
        open_=open_,
        support_series=support,
        resistance_series=resistance,
        start=0,
        end=n - 1,
        cost_bps=0.0,
        cooldown_bars=0,
    )
    exits_on_bar1 = [t for t in sim["trades"] if t.get("exit_bar") == 1]
    assert not exits_on_bar1, "no exit should be recorded on the entry bar"
    exits_on_bar2 = [t for t in sim["trades"] if t.get("exit_bar") == 2]
    assert exits_on_bar2, "exit should be allowed on the following bar"
    assert exits_on_bar2[0]["entry_bar"] == 1


# ---------------------------------------------------------------------------
# 4. fill-aware entry-bar loss
# ---------------------------------------------------------------------------


def test_entry_bar_loss_is_fill_aware_not_zero():
    n = 3
    support_level = 100.0
    close_after_touch = 95.0  # closes 5% below support level
    close = np.array([100.0, close_after_touch, close_after_touch])
    high = np.array([100.5, close_after_touch + 0.5, close_after_touch + 0.5])
    low = np.array([99.5, 99.0, close_after_touch - 0.5])
    open_ = np.array([100.0, 100.0, close_after_touch])
    support = np.full(n, support_level, dtype="float64")
    resistance = np.full(n, 200.0, dtype="float64")

    cost_bps = 33.0
    sim = simulate_touch_pair(
        close=close,
        high=high,
        low=low,
        open_=open_,
        support_series=support,
        resistance_series=resistance,
        start=0,
        end=n - 1,
        cost_bps=cost_bps,
        cooldown_bars=0,
    )
    entry_bar_return = sim["returns"][0]
    cost_frac = cost_bps / 10_000.0
    expected = (close_after_touch / support_level - 1.0) - cost_frac
    assert entry_bar_return == pytest.approx(expected)
    assert entry_bar_return < 0.0


# ---------------------------------------------------------------------------
# 5. no lookahead
# ---------------------------------------------------------------------------


def test_no_lookahead_earlier_windows_unchanged(oscillator):
    close, high, low, open_, pair_series, pair_meta = oscillator
    train, test, step = 100, 20, 20

    result_1 = run_sr_wfo(
        close=close,
        high=high,
        low=low,
        open_=open_,
        pair_series=pair_series,
        pair_meta=pair_meta,
        train=train,
        test=test,
        step=step,
        cost_bps=33.0,
        cooldown_bars=1,
        min_train_trades=3,
        bootstrap_iter=100,
        seed=11,
    )

    close2 = close.copy()
    high2 = high.copy()
    low2 = low.copy()
    open2 = open_.copy()
    last_window = result_1["windows"][-1]
    mutate_start = last_window["test_start"]
    close2[mutate_start:] *= 3.0
    high2[mutate_start:] *= 3.0
    low2[mutate_start:] *= 3.0
    open2[mutate_start:] *= 3.0

    result_2 = run_sr_wfo(
        close=close2,
        high=high2,
        low=low2,
        open_=open2,
        pair_series=pair_series,
        pair_meta=pair_meta,
        train=train,
        test=test,
        step=step,
        cost_bps=33.0,
        cooldown_bars=1,
        min_train_trades=3,
        bootstrap_iter=100,
        seed=11,
    )

    assert len(result_1["windows"]) == len(result_2["windows"])
    for w1, w2 in zip(result_1["windows"][:-1], result_2["windows"][:-1]):
        assert w1["selected_pair_id"] == w2["selected_pair_id"]
        assert w1["train_objective"] == pytest.approx(w2["train_objective"]) if w1["train_objective"] is not None else w2["train_objective"] is None


# ---------------------------------------------------------------------------
# 6. insufficient history
# ---------------------------------------------------------------------------


def test_insufficient_history_returns_status(oscillator):
    close, high, low, open_, pair_series, pair_meta = oscillator
    n = 50
    result = run_sr_wfo(
        close=close[:n],
        high=high[:n],
        low=low[:n],
        open_=open_[:n],
        pair_series=pair_series,
        pair_meta=pair_meta,
        train=252,
        test=21,
        step=21,
        cost_bps=33.0,
        cooldown_bars=1,
    )
    assert result["status"] == "insufficient_history"
    assert result["windows"] == []


def test_sr_window_plan_empty_when_too_short():
    assert sr_window_plan(train=252, test=21, step=21, n_bars=50) == []
    plan = sr_window_plan(train=100, test=20, step=20, n_bars=800)
    assert plan
    for window_index, train_start, train_end, test_start, test_end in plan:
        assert train_end - train_start == 100
        assert test_start == train_end
        assert test_end - test_start >= 2


# ---------------------------------------------------------------------------
# 7. forced liquidation
# ---------------------------------------------------------------------------


def test_forced_liquidation_at_slice_end():
    n = 4
    close = np.array([100.0, 100.0, 101.0, 102.0])
    high = np.array([100.5, 100.5, 101.5, 102.5])
    low = np.array([99.5, 95.0, 100.5, 101.5])
    open_ = np.array([100.0, 100.0, 100.5, 101.5])
    support = np.full(n, 96.0, dtype="float64")
    resistance = np.full(n, 500.0, dtype="float64")  # never touched -> forced liquidation

    cost_bps = 33.0
    sim = simulate_touch_pair(
        close=close,
        high=high,
        low=low,
        open_=open_,
        support_series=support,
        resistance_series=resistance,
        start=0,
        end=n - 1,
        cost_bps=cost_bps,
        cooldown_bars=0,
    )
    forced_trades = [t for t in sim["trades"] if t["exit_reason"] == "forced"]
    assert len(forced_trades) == 1
    assert forced_trades[0]["exit_bar"] == n - 1
    # last bar return must include the forced-liquidation cost
    cost_frac = cost_bps / 10_000.0
    last_return = sim["returns"][-1]
    holding_return_only = close[-1] / close[-2] - 1.0
    assert last_return == pytest.approx(holding_return_only - cost_frac)


# ---------------------------------------------------------------------------
# 8. line_touch_stats
# ---------------------------------------------------------------------------


def test_line_touch_stats_exact_counts():
    # support touches at bars 2 and 5; bounce only at bar 2 (forward close above level)
    close = np.array([100.0, 100.0, 100.0, 96.0, 98.0, 100.0, 96.0, 90.0])
    high = close + 1.0
    low = close - 1.0
    low[2] = 89.0   # touch at bar 2 (prev close=100 > level=90)
    low[5] = 89.0   # touch at bar 5 (prev close=100 > level=90)
    level = np.full(len(close), 90.0, dtype="float64")

    stats = line_touch_stats(
        close=close,
        high=high,
        low=low,
        level_series=level,
        side="support",
        forward_bars=1,
    )
    assert stats["n_touches"] == 2
    # forward close(bar3)=96 > 90 -> bounce; forward close(bar6)=96 > 90 -> bounce
    assert stats["n_bounces"] == 2
    assert stats["bounce_rate"] == pytest.approx(1.0)
