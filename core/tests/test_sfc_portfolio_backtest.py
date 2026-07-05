from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from quant_core.fundamentals.cross_section.portfolio_backtest import (
    SfcPortfolioBacktestConfig,
    one_way_turnover,
    run_sfc_portfolio_backtest,
    segment_for_date,
)


def _prices(values: dict[str, float]) -> pd.Series:
    return pd.Series(values, dtype=float).rename_axis("date")


def test_turnover_math_full_replacement_and_no_change() -> None:
    assert one_way_turnover({"AAA": 0.5, "BBB": 0.5}, {"AAA": 0.5, "BBB": 0.5}) == pytest.approx(0.0)
    assert one_way_turnover({"AAA": 0.5, "BBB": 0.5}, {"CCC": 0.5, "DDD": 0.5}) == pytest.approx(1.0)


def test_cost_drag_arithmetic() -> None:
    panel = pd.DataFrame(
        [
            {"symbol": "AAA", "as_of_date": "2023-08-31", "sfc": 3.0, "is_covered": True},
            {"symbol": "BBB", "as_of_date": "2023-08-31", "sfc": 2.0, "is_covered": True},
            {"symbol": "CCC", "as_of_date": "2023-08-31", "sfc": 1.0, "is_covered": True},
            {"symbol": "AAA", "as_of_date": "2023-09-30", "sfc": 3.0, "is_covered": True},
            {"symbol": "BBB", "as_of_date": "2023-09-30", "sfc": 2.0, "is_covered": True},
            {"symbol": "CCC", "as_of_date": "2023-09-30", "sfc": 1.0, "is_covered": True},
        ]
    )
    prices = {sym: _prices({"2023-08-31": 100.0, "2023-09-30": 110.0}) for sym in ("AAA", "BBB", "CCC")}

    result = run_sfc_portfolio_backtest(
        panel,
        price_by_symbol=prices,
        config=SfcPortfolioBacktestConfig(cost_bps=33.0),
    )

    row = result["rebalance_rows"][0]
    assert row["turnover"] == pytest.approx(1.0)
    assert row["strategy_return_gross"] == pytest.approx(0.10)
    assert row["cost_drag"] == pytest.approx(0.0066)
    assert row["strategy_return_net"] == pytest.approx(0.0934)


def test_rigged_panel_top_tercile_wins() -> None:
    dates = ["2023-08-31", "2023-09-30", "2023-10-31"]
    rows = []
    prices = {}
    for idx, sym in enumerate(["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]):
        score = 10.0 - idx
        for date in dates:
            rows.append({"symbol": sym, "as_of_date": date, "sfc": score, "is_covered": True})
        growth = 1.20 if sym in {"AAA", "BBB"} else 0.95
        prices[sym] = _prices({"2023-08-31": 100.0, "2023-09-30": 100.0 * growth, "2023-10-31": 100.0 * growth * growth})

    result = run_sfc_portfolio_backtest(
        pd.DataFrame(rows),
        price_by_symbol=prices,
        config=SfcPortfolioBacktestConfig(cost_bps=0.0),
    )

    first = result["rebalance_rows"][0]
    assert first["holdings"] == ["AAA", "BBB"]
    assert first["strategy_return_net"] > first["universe_return"]
    assert result["summary"][0]["mean_active_return"] is not None


def test_segment_tagging_around_split_date() -> None:
    assert segment_for_date(dt.date(2023, 7, 30)) == "selection"
    assert segment_for_date(dt.date(2023, 7, 31)) == "proof"
    assert segment_for_date(dt.date(2026, 7, 5)) == "proof"
    assert segment_for_date(dt.date(2026, 7, 6)) == "live"


def test_stale_price_count_when_rebalance_date_missing() -> None:
    panel = pd.DataFrame(
        [
            {"symbol": "AAA", "as_of_date": "2023-08-31", "sfc": 3.0, "is_covered": True},
            {"symbol": "BBB", "as_of_date": "2023-08-31", "sfc": 2.0, "is_covered": True},
            {"symbol": "CCC", "as_of_date": "2023-08-31", "sfc": 1.0, "is_covered": True},
            {"symbol": "AAA", "as_of_date": "2023-09-30", "sfc": 3.0, "is_covered": True},
            {"symbol": "BBB", "as_of_date": "2023-09-30", "sfc": 2.0, "is_covered": True},
            {"symbol": "CCC", "as_of_date": "2023-09-30", "sfc": 1.0, "is_covered": True},
        ]
    )
    prices = {
        "AAA": _prices({"2023-08-30": 100.0, "2023-09-29": 101.0}),
        "BBB": _prices({"2023-08-31": 100.0, "2023-09-30": 100.0}),
        "CCC": _prices({"2023-08-31": 100.0, "2023-09-30": 100.0}),
    }

    result = run_sfc_portfolio_backtest(panel, price_by_symbol=prices)

    assert result["rebalance_rows"][0]["holdings"] == ["AAA"]
    assert result["rebalance_rows"][0]["stale_price_count"] >= 2
