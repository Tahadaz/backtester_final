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


def test_cost_drag_arithmetic_equal_weight_mode() -> None:
    panel = pd.DataFrame(
        [
            {"symbol": "AAA", "as_of_date": "2023-08-31", "sfc": 3.0, "is_covered": True, "max_metric_availability_date": "2023-08-20"},
            {"symbol": "BBB", "as_of_date": "2023-08-31", "sfc": 2.0, "is_covered": True, "max_metric_availability_date": "2023-08-20"},
            {"symbol": "CCC", "as_of_date": "2023-08-31", "sfc": 1.0, "is_covered": True, "max_metric_availability_date": "2023-08-20"},
            {"symbol": "AAA", "as_of_date": "2023-09-30", "sfc": 3.0, "is_covered": True, "max_metric_availability_date": "2023-08-20"},
            {"symbol": "BBB", "as_of_date": "2023-09-30", "sfc": 2.0, "is_covered": True, "max_metric_availability_date": "2023-08-20"},
            {"symbol": "CCC", "as_of_date": "2023-09-30", "sfc": 1.0, "is_covered": True, "max_metric_availability_date": "2023-08-20"},
        ]
    )
    prices = {sym: _prices({"2023-08-31": 100.0, "2023-09-30": 110.0}) for sym in ("AAA", "BBB", "CCC")}

    result = run_sfc_portfolio_backtest(
        panel,
        price_by_symbol=prices,
        config=SfcPortfolioBacktestConfig(rebalance="monthly", weighting_mode="equal_top_tercile", cost_bps=33.0),
    )

    row = result["rebalance_rows"][0]
    assert row["turnover"] == pytest.approx(1.0)
    assert row["strategy_return_gross"] == pytest.approx(0.10)
    assert row["cost_drag"] == pytest.approx(0.0066)
    assert row["strategy_return_net"] == pytest.approx(0.0934)


def test_event_rebalance_uses_publication_windows() -> None:
    panel = pd.DataFrame(
        [
            {"symbol": "AAA", "as_of_date": "2023-08-31", "sfc": 3.0, "is_covered": True, "max_metric_availability_date": "2023-08-15"},
            {"symbol": "BBB", "as_of_date": "2023-08-31", "sfc": 2.0, "is_covered": True, "max_metric_availability_date": "2023-08-10"},
            {"symbol": "AAA", "as_of_date": "2023-09-30", "sfc": 3.0, "is_covered": True, "max_metric_availability_date": "2023-08-15"},
            {"symbol": "BBB", "as_of_date": "2023-09-30", "sfc": 2.0, "is_covered": True, "max_metric_availability_date": "2023-08-10"},
            {"symbol": "AAA", "as_of_date": "2023-10-31", "sfc": 3.0, "is_covered": True, "max_metric_availability_date": "2023-10-20"},
            {"symbol": "BBB", "as_of_date": "2023-10-31", "sfc": 2.0, "is_covered": True, "max_metric_availability_date": "2023-10-19"},
            {"symbol": "AAA", "as_of_date": "2023-11-30", "sfc": 3.0, "is_covered": True, "max_metric_availability_date": "2023-10-20"},
            {"symbol": "BBB", "as_of_date": "2023-11-30", "sfc": 2.0, "is_covered": True, "max_metric_availability_date": "2023-10-19"},
            {"symbol": "AAA", "as_of_date": "2023-12-31", "sfc": 3.0, "is_covered": True, "max_metric_availability_date": "2023-12-18"},
            {"symbol": "BBB", "as_of_date": "2023-12-31", "sfc": 2.0, "is_covered": True, "max_metric_availability_date": "2023-12-16"},
        ]
    )
    prices = {sym: _prices({"2023-08-31": 100.0, "2023-10-31": 110.0, "2023-12-31": 115.0}) for sym in ("AAA", "BBB")}

    result = run_sfc_portfolio_backtest(
        panel,
        price_by_symbol=prices,
        config=SfcPortfolioBacktestConfig(rebalance="event", weighting_mode="equal_top_tercile", cost_bps=0.0),
    )

    assert [row["date"] for row in result["rebalance_rows"]] == ["2023-10-31"]
    assert result["turnover_vs_monthly_baseline"] is not None


def test_benchmark_relative_weights_zero_bottom_and_bound_active() -> None:
    panel = pd.DataFrame(
        [
            {"symbol": "ATW", "as_of_date": "2023-08-31", "sfc": 9.0, "is_covered": True, "close": 500.0, "sector": "Banks", "is_financial": True, "max_metric_availability_date": "2023-08-20"},
            {"symbol": "IAM", "as_of_date": "2023-08-31", "sfc": 8.0, "is_covered": True, "close": 100.0, "sector": "Telecom", "is_financial": False, "max_metric_availability_date": "2023-08-20"},
            {"symbol": "BCP", "as_of_date": "2023-08-31", "sfc": 7.0, "is_covered": True, "close": 250.0, "sector": "Banks", "is_financial": True, "max_metric_availability_date": "2023-08-20"},
            {"symbol": "MNG", "as_of_date": "2023-08-31", "sfc": 6.0, "is_covered": True, "close": 1000.0, "sector": "Mines", "is_financial": False, "max_metric_availability_date": "2023-08-20"},
            {"symbol": "MSA", "as_of_date": "2023-08-31", "sfc": 2.0, "is_covered": True, "close": 50.0, "sector": "Transport", "is_financial": False, "max_metric_availability_date": "2023-08-20"},
            {"symbol": "LHM", "as_of_date": "2023-08-31", "sfc": 1.0, "is_covered": True, "close": 40.0, "sector": "Construction", "is_financial": False, "max_metric_availability_date": "2023-08-20"},
            {"symbol": "ATW", "as_of_date": "2023-09-30", "sfc": 9.0, "is_covered": True, "close": 510.0, "sector": "Banks", "is_financial": True, "max_metric_availability_date": "2023-08-20"},
            {"symbol": "IAM", "as_of_date": "2023-09-30", "sfc": 8.0, "is_covered": True, "close": 105.0, "sector": "Telecom", "is_financial": False, "max_metric_availability_date": "2023-08-20"},
            {"symbol": "BCP", "as_of_date": "2023-09-30", "sfc": 7.0, "is_covered": True, "close": 255.0, "sector": "Banks", "is_financial": True, "max_metric_availability_date": "2023-08-20"},
            {"symbol": "MNG", "as_of_date": "2023-09-30", "sfc": 6.0, "is_covered": True, "close": 1010.0, "sector": "Mines", "is_financial": False, "max_metric_availability_date": "2023-08-20"},
            {"symbol": "MSA", "as_of_date": "2023-09-30", "sfc": 2.0, "is_covered": True, "close": 48.0, "sector": "Transport", "is_financial": False, "max_metric_availability_date": "2023-08-20"},
            {"symbol": "LHM", "as_of_date": "2023-09-30", "sfc": 1.0, "is_covered": True, "close": 39.0, "sector": "Construction", "is_financial": False, "max_metric_availability_date": "2023-08-20"},
        ]
    )
    prices = {
        "ATW": _prices({"2023-08-31": 500.0, "2023-09-30": 510.0}),
        "IAM": _prices({"2023-08-31": 100.0, "2023-09-30": 105.0}),
        "BCP": _prices({"2023-08-31": 250.0, "2023-09-30": 255.0}),
        "MNG": _prices({"2023-08-31": 1000.0, "2023-09-30": 1010.0}),
        "MSA": _prices({"2023-08-31": 50.0, "2023-09-30": 48.0}),
        "LHM": _prices({"2023-08-31": 40.0, "2023-09-30": 39.0}),
    }

    result = run_sfc_portfolio_backtest(
        panel,
        price_by_symbol=prices,
        config=SfcPortfolioBacktestConfig(
            rebalance="monthly",
            weighting_mode="benchmark_active",
            cost_bps=0.0,
            active_weight_cap=0.03,
            sector_cap=1.0,
        ),
    )

    holdings = {row["symbol"]: row for row in result["latest_holdings"]}
    assert "MSA" not in holdings
    assert "LHM" not in holdings
    assert holdings["ATW"]["active_weight"] <= 0.03 + 1e-9
    assert holdings["IAM"]["active_weight"] <= 0.03 + 1e-9
    assert sum(row["weight"] for row in result["latest_holdings"] if row["badge"] != "out") == pytest.approx(1.0)
    exposure = result["rebalance_rows"][0]["financials_vs_non_financials_active_exposure"]
    assert set(exposure) == {"financials", "non_financials"}


def test_segment_tagging_around_split_date() -> None:
    assert segment_for_date(dt.date(2023, 7, 30)) == "selection"
    assert segment_for_date(dt.date(2023, 7, 31)) == "proof"
    assert segment_for_date(dt.date(2026, 7, 5)) == "proof"
    assert segment_for_date(dt.date(2026, 7, 6)) == "live"


def test_stale_price_count_when_rebalance_date_missing() -> None:
    panel = pd.DataFrame(
        [
            {"symbol": "AAA", "as_of_date": "2023-08-31", "sfc": 3.0, "is_covered": True, "max_metric_availability_date": "2023-08-20"},
            {"symbol": "BBB", "as_of_date": "2023-08-31", "sfc": 2.0, "is_covered": True, "max_metric_availability_date": "2023-08-20"},
            {"symbol": "CCC", "as_of_date": "2023-08-31", "sfc": 1.0, "is_covered": True, "max_metric_availability_date": "2023-08-20"},
            {"symbol": "AAA", "as_of_date": "2023-09-30", "sfc": 3.0, "is_covered": True, "max_metric_availability_date": "2023-08-20"},
            {"symbol": "BBB", "as_of_date": "2023-09-30", "sfc": 2.0, "is_covered": True, "max_metric_availability_date": "2023-08-20"},
            {"symbol": "CCC", "as_of_date": "2023-09-30", "sfc": 1.0, "is_covered": True, "max_metric_availability_date": "2023-08-20"},
        ]
    )
    prices = {
        "AAA": _prices({"2023-08-30": 100.0, "2023-09-29": 101.0}),
        "BBB": _prices({"2023-08-31": 100.0, "2023-09-30": 100.0}),
        "CCC": _prices({"2023-08-31": 100.0, "2023-09-30": 100.0}),
    }

    result = run_sfc_portfolio_backtest(
        panel,
        price_by_symbol=prices,
        config=SfcPortfolioBacktestConfig(rebalance="monthly", weighting_mode="equal_top_tercile"),
    )

    assert result["rebalance_rows"][0]["holdings"] == ["AAA"]
    assert result["rebalance_rows"][0]["stale_price_count"] >= 2
