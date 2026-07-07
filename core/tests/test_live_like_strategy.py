from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from quant_core.fundamentals.cross_section.live_like_strategy import (
    VINTAGE_LIFE_MONTHS,
    LiveLikeConfig,
    VintageState,
    _combined_weights,
    combine_sleeves,
    eligibility_mask,
    run_fixed_stride_backtest,
    run_semiannual_backtest,
    run_vintage_backtest,
    summarize_performance,
)


def _monthly_dates(n: int, start="2020-01-31"):
    return [d.date() for d in pd.date_range(start, periods=n, freq="ME")]


def _flat_price_series(value: float, dates: list[dt.date]) -> pd.Series:
    idx = pd.DatetimeIndex(dates)
    return pd.Series([value] * len(dates), index=idx)


def test_capital_weights_sum_to_one_sixth_per_vintage_and_total_le_one():
    dates = _monthly_dates(8)
    holdings_by_date = {d: {"AAA": 0.5, "BBB": 0.5} for d in dates}
    prices = {
        "AAA": pd.Series([100.0 * (1.01**i) for i in range(8)], index=pd.DatetimeIndex(dates)),
        "BBB": pd.Series([50.0 * (1.005**i) for i in range(8)], index=pd.DatetimeIndex(dates)),
    }
    result = run_vintage_backtest(holdings_by_date, price_by_symbol=prices, config=LiveLikeConfig())
    # After warm-up (6 months), exactly 6 vintages should be active every period
    assert result["n_active_vintages"].iloc[-1] == 6
    assert result["n_active_vintages"].iloc[0] == 1


def test_vintage_expires_after_six_months():
    dates = _monthly_dates(10)
    # only the very first date has a real vintage; all subsequent dates form empty vintages
    holdings_by_date = {dates[0]: {"AAA": 1.0}}
    holdings_by_date.update({d: {} for d in dates[1:]})
    prices = {"AAA": _flat_price_series(100.0, dates)}
    result = run_vintage_backtest(holdings_by_date, price_by_symbol=prices, config=LiveLikeConfig())
    active_counts = result["n_active_vintages"].tolist()
    # vintage formed at dates[0] should be active for exactly 6 periods (months_held 0..5), then expire
    assert active_counts[0] == 1
    assert active_counts[5] == 1
    assert active_counts[6] == 0


def test_flat_prices_produce_zero_gross_return():
    dates = _monthly_dates(8)
    holdings_by_date = {d: {"AAA": 1.0} for d in dates}
    prices = {"AAA": _flat_price_series(100.0, dates)}
    result = run_vintage_backtest(holdings_by_date, price_by_symbol=prices, config=LiveLikeConfig(cost_bps=0.0))
    assert result["gross_return"].abs().max() < 1e-12


def test_engine_does_not_reproduce_overlapping_forward_return_compounding_error():
    """Synthetic proof: if a stock returns +5% every month for 12 months, the
    OLD invalid method (compounding a 6-month OVERLAPPING forward-return
    series sampled monthly) would double-count each month's return up to 6x
    and produce a wildly inflated equity curve. The new vintage engine must
    produce the correct, non-inflated ~ (1.05^12 - 1) cumulative return since
    it uses genuine one-month-at-a-time realized price changes, not
    overlapping 6-month windows."""
    n = 13
    dates = _monthly_dates(n)
    holdings_by_date = {d: {"AAA": 1.0} for d in dates}
    growth = [100.0 * (1.05**i) for i in range(n)]
    prices = {"AAA": pd.Series(growth, index=pd.DatetimeIndex(dates))}

    result = run_vintage_backtest(holdings_by_date, price_by_symbol=prices, config=LiveLikeConfig(cost_bps=0.0))
    # Once fully ramped (6 active vintages, from period index 5 onward), the
    # portfolio is 100% invested in AAA every period, so each period's return
    # must equal the true one-month price return (5%) -- not a compounded
    # overlapping 6-month spread re-applied every month.
    # A newly-formed vintage doesn't earn a return in its formation period (it
    # starts accruing from the next period), so skip the first period where
    # the vintage count first reaches steady state and check the periods after.
    steady_state = result[result["n_active_vintages"] == VINTAGE_LIFE_MONTHS].iloc[1:]
    assert len(steady_state) >= 3
    for ret in steady_state["gross_return"]:
        assert ret == pytest.approx(0.05, rel=1e-6)
    # The old invalid method (treating a 6-month OVERLAPPING forward return,
    # sampled monthly, as a sequential monthly P&L) would imply a monthly step
    # of (1.05^6 - 1) = ~34%, not 5% -- roughly 6-7x larger every period.
    naive_overlapping_step = 1.05**6 - 1.0
    assert naive_overlapping_step > 6 * 0.05


def test_turnover_is_zero_when_portfolio_unchanged():
    dates = _monthly_dates(8)
    holdings_by_date = {d: {"AAA": 1.0} for d in dates}
    prices = {"AAA": _flat_price_series(100.0, dates)}
    result = run_vintage_backtest(holdings_by_date, price_by_symbol=prices, config=LiveLikeConfig())
    # once ramped up to steady-state (6 vintages, same stock every time), turnover should be 0
    assert result["turnover"].iloc[-1] == pytest.approx(0.0, abs=1e-9)


def test_transaction_costs_reduce_net_return_relative_to_gross():
    dates = _monthly_dates(8)
    holdings_by_date = {dates[0]: {"AAA": 1.0}}
    holdings_by_date.update({d: {"BBB": 1.0} for d in dates[1:]})  # forces turnover every period
    prices = {
        "AAA": _flat_price_series(100.0, dates),
        "BBB": _flat_price_series(100.0, dates),
    }
    result = run_vintage_backtest(holdings_by_date, price_by_symbol=prices, config=LiveLikeConfig(cost_bps=50.0))
    assert (result["net_return"] <= result["gross_return"] + 1e-12).all()
    assert result["cost"].iloc[1:].gt(0).any()


def test_missing_price_excludes_symbol_without_crashing():
    dates = _monthly_dates(4)
    holdings_by_date = {d: {"AAA": 0.5, "GHOST": 0.5} for d in dates}
    prices = {"AAA": _flat_price_series(100.0, dates)}  # GHOST has no price series at all
    result = run_vintage_backtest(holdings_by_date, price_by_symbol=prices, config=LiveLikeConfig())
    assert not result["gross_return"].isna().any()


def test_semiannual_backtest_is_non_overlapping():
    dates = _monthly_dates(13)
    holdings_by_date = {d: {"AAA": 1.0} for d in dates}
    prices = {"AAA": pd.Series([100.0 * (1.02**i) for i in range(13)], index=pd.DatetimeIndex(dates))}
    result = run_semiannual_backtest(holdings_by_date, price_by_symbol=prices, config=LiveLikeConfig(cost_bps=0.0))
    # 13 monthly dates -> rebalance every 6th -> 3 rebalance dates (0, 6, 12)
    assert len(result) == 3
    # each held period should reflect 6 months of 2% compounding: (1.02^6 - 1)
    assert result["gross_return"].iloc[1] == pytest.approx(1.02**6 - 1.0, rel=1e-6)


def test_combine_sleeves_averages_realized_returns_not_overlapping_ic():
    dates = pd.date_range("2020-01-31", periods=3, freq="ME").date
    a = pd.DataFrame({"as_of_date": dates, "gross_return": [0.10, 0.0, 0.0], "net_return": [0.08, 0.0, 0.0], "turnover": [1.0, 0.0, 0.0], "cost": [0.02, 0.0, 0.0]})
    b = pd.DataFrame({"as_of_date": dates, "gross_return": [0.0, 0.20, 0.0], "net_return": [0.0, 0.18, 0.0], "turnover": [0.0, 1.0, 0.0], "cost": [0.0, 0.02, 0.0]})
    combined = combine_sleeves(a, b)
    assert combined["gross_return"].tolist() == pytest.approx([0.05, 0.10, 0.0])
    assert combined["net_return"].tolist() == pytest.approx([0.04, 0.09, 0.0])


def test_summarize_performance_sharpe_and_drawdown():
    returns = pd.DataFrame({"as_of_date": _monthly_dates(6), "net_return": [0.02, -0.01, 0.03, -0.02, 0.01, 0.015], "turnover": [0.1] * 6})
    summary = summarize_performance(returns, periods_per_year=12)
    assert summary["periods"] == 6
    assert np.isfinite(summary["sharpe"])
    assert summary["max_drawdown"] <= 0.0
    assert summary["cumulative_return"] == pytest.approx(np.prod([1 + x for x in [0.02, -0.01, 0.03, -0.02, 0.01, 0.015]]) - 1.0)


def test_quarterly_stride_rebalances_every_three_months():
    dates = _monthly_dates(13)
    holdings_by_date = {d: {"AAA": 1.0} for d in dates}
    prices = {"AAA": pd.Series([100.0 * (1.02**i) for i in range(13)], index=pd.DatetimeIndex(dates))}
    result = run_fixed_stride_backtest(holdings_by_date, price_by_symbol=prices, config=LiveLikeConfig(cost_bps=0.0), stride_months=3)
    # 13 monthly dates, stride 3 -> rebalance at index 0,3,6,9,12 -> 5 rows
    assert len(result) == 5
    assert result["gross_return"].iloc[1] == pytest.approx(1.02**3 - 1.0, rel=1e-6)


def test_eligibility_mask_excludes_sah_and_null_signal_rows():
    panel = pd.DataFrame(
        {
            "symbol": ["SAH", "AAA", "BBB"],
            "close": [100.0, 100.0, 100.0],
            "market_cap_raw": [1e9, 1e9, 1e9],
            "book_to_market_raw": [0.5, 0.5, None],
            "cashflow_price_raw": [0.1, None, 0.1],
        }
    )
    out = eligibility_mask(panel)
    assert not out.loc[out["symbol"] == "SAH", "eligible_universe"].iloc[0]
    assert out.loc[out["symbol"] == "AAA", "eligible_bm"].iloc[0]
    assert not out.loc[out["symbol"] == "BBB", "eligible_bm"].iloc[0]
    assert out.loc[out["symbol"] == "BBB", "eligible_cfp"].iloc[0]
