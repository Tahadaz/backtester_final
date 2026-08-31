from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from core.quant_core.fundamentals.cross_section.live_like_strategy import (
    LiveLikeConfig,
    point_in_time_adv_mad,
    run_capacity_constrained_backtest,
)


def _frame() -> pd.DataFrame:
    index = pd.bdate_range("2025-11-01", "2026-08-31")
    volume = pd.Series(10_000.0, index=index)
    volume.loc[volume.index >= "2026-06-01"] = 1.0
    return pd.DataFrame({"Close": 100.0, "Open": 100.0, "Volume": volume}, index=index)


def test_adv_is_strictly_lagged_and_requires_full_window() -> None:
    frame = _frame()
    as_of = dt.date(2026, 1, 30)
    expected = float((frame.loc[frame.index.date < as_of, "Close"] * frame.loc[frame.index.date < as_of, "Volume"]).tail(20).mean())
    assert point_in_time_adv_mad(frame, as_of, window_days=20) == pytest.approx(expected)
    assert point_in_time_adv_mad(frame, dt.date(2025, 11, 5), window_days=20) is None


def test_capacity_caps_entries_and_exits_and_keeps_residual_position() -> None:
    dates = [dt.date(2026, month, 28) for month in range(1, 8)]
    holdings = {date: ({"AAA": 1.0} if index == 0 else {}) for index, date in enumerate(dates)}
    config = LiveLikeConfig(
        portfolio_nav_mad=10_000_000.0,
        min_order_enabled=False,
        min_adv_enabled=False,
        max_participation_rate=0.20,
        adv_window_days=20,
    )

    result, ledger, summary, final_weights = run_capacity_constrained_backtest(
        holdings,
        price_frames={"AAA": _frame()},
        config=config,
    )

    buy = ledger.iloc[0]
    sell = ledger.iloc[-1]
    assert buy["action"] == "BUY"
    assert buy["status"] == "partial_capacity"
    assert buy["filled_notional_mad"] == pytest.approx(200_000.0)
    assert sell["action"] == "SELL"
    assert sell["status"] == "partial_capacity"
    assert sell["filled_notional_mad"] == pytest.approx(20.0)
    assert final_weights["AAA"] > 0
    assert summary["unfilled_notional_mad"] > 0
    assert not result.empty
    assert result.iloc[0]["net_return"] == pytest.approx(-buy["filled_notional_mad"] * 0.0033 / 10_000_000.0)


def test_minimum_ticket_rejects_peanut_order() -> None:
    date = dt.date(2026, 1, 30)
    config = LiveLikeConfig(
        portfolio_nav_mad=600_000.0,
        min_order_mad=150_000.0,
        min_adv_enabled=False,
        max_participation_enabled=False,
    )
    _, ledger, _, final_weights = run_capacity_constrained_backtest(
        {date: {"AAA": 1.0}},
        price_frames={"AAA": _frame()},
        config=config,
    )
    assert ledger.iloc[0]["status"] == "rejected_min_order"
    assert ledger.iloc[0]["filled_notional_mad"] == 0
    assert final_weights == {}
