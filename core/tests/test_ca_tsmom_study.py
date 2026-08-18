"""Correctness tests for the cross-asset TSMOM sleeve.

The load-bearing tests are the look-ahead ones: if future data can reach a past
position, every metric the study reports is meaningless.
"""

import numpy as np
import pandas as pd
import pytest

from quant_core.cross_asset.tsmom_study import (
    StudyConfig,
    TRADING_DAYS,
    align_on_common_calendar,
    apply_rebalance_schedule,
    build_return_panel,
    compute_metrics,
    data_quality_report,
    inverse_vol_scale,
    price_returns,
    run_tsmom,
    tsmom_signal,
    yield_to_bond_return,
)


def _panel(n_days: int = 1500, n_instruments: int = 8, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2010-01-01", periods=n_days)
    data = rng.normal(0.0003, 0.011, size=(n_days, n_instruments))
    return pd.DataFrame(data, index=index, columns=[f"I{i}" for i in range(n_instruments)])


def _classes(panel: pd.DataFrame, asset_class: str = "fx") -> dict[str, str]:
    return {column: asset_class for column in panel.columns}


# ---------------------------------------------------------------------------
# Look-ahead
# ---------------------------------------------------------------------------


def test_future_returns_cannot_change_past_positions():
    """The decisive test: perturb the tail, the head must not move."""
    panel = _panel()
    classes = _classes(panel)
    cut = 1000

    base = run_tsmom(panel, classes)

    perturbed_panel = panel.copy()
    perturbed_panel.iloc[cut:] += 0.05  # a violent, obvious change
    perturbed = run_tsmom(perturbed_panel, classes)

    pd.testing.assert_frame_equal(
        base.positions.iloc[:cut],
        perturbed.positions.iloc[:cut],
        check_exact=False,
        atol=1e-12,
    )


def test_signal_shift_is_exactly_one_bar():
    panel = _panel(600, 3)
    signal = tsmom_signal(panel, lookback_months=6, lag=1)
    shifted_input = tsmom_signal(panel.shift(1), lookback_months=6, lag=1)
    pd.testing.assert_frame_equal(signal.shift(1), shifted_input, check_exact=False, atol=1e-12)


def test_vol_scale_is_lagged():
    panel = _panel(600, 3)
    scale = inverse_vol_scale(panel, 0.10, halflife=60, lag=1)
    # A vol explosion on the last bar must not be reflected on that bar.
    spiked = panel.copy()
    spiked.iloc[-1] *= 50.0
    spiked_scale = inverse_vol_scale(spiked, 0.10, halflife=60, lag=1)
    pd.testing.assert_frame_equal(scale.iloc[:-1], spiked_scale.iloc[:-1], check_exact=False, atol=1e-12)


def test_position_on_a_bar_never_uses_that_bars_return():
    panel = _panel(800, 6)
    classes = _classes(panel)
    base = run_tsmom(panel, classes)

    for probe in (400, 600, 799):
        bumped = panel.copy()
        bumped.iloc[probe] += 0.10
        result = run_tsmom(bumped, classes)
        pd.testing.assert_series_equal(
            base.positions.iloc[probe],
            result.positions.iloc[probe],
            check_exact=False,
            atol=1e-12,
        )


# ---------------------------------------------------------------------------
# Return construction
# ---------------------------------------------------------------------------


def test_yield_to_bond_return_carry_and_price_move():
    yields = pd.Series(
        [0.0400, 0.0400, 0.0410, 0.0390],
        index=pd.bdate_range("2020-01-01", periods=4),
    )
    out = yield_to_bond_return(yields, duration=8.0)
    assert np.isnan(out.iloc[0])
    # Flat yield -> carry only.
    assert out.iloc[1] == pytest.approx(0.04 / TRADING_DAYS)
    # +10bp on 8y duration -> -0.8% price, plus yesterday's carry.
    assert out.iloc[2] == pytest.approx(0.04 / TRADING_DAYS - 8.0 * 0.0010)
    # -20bp -> +1.6% price.
    assert out.iloc[3] == pytest.approx(0.041 / TRADING_DAYS + 8.0 * 0.0020)


def test_yield_to_bond_return_uses_yesterdays_yield_for_carry():
    yields = pd.Series([0.02, 0.02, 0.09], index=pd.bdate_range("2020-01-01", periods=3))
    out = yield_to_bond_return(yields, duration=5.0)
    # The carry term on the last bar must come from 0.02, not the new 0.09.
    assert out.iloc[2] == pytest.approx(0.02 / TRADING_DAYS - 5.0 * 0.07)


def test_yield_to_bond_return_rejects_bad_duration():
    with pytest.raises(ValueError):
        yield_to_bond_return(pd.Series([0.01, 0.02]), duration=0.0)


def test_price_returns_leave_gaps_as_gaps():
    """A hole stays a hole. Filling is explicit, disclosed, and done upstream."""
    prices = pd.Series([100.0, 110.0, np.nan, 121.0], index=pd.bdate_range("2020-01-01", periods=4))
    out = price_returns(prices)
    assert out.iloc[1] == pytest.approx(0.10)
    assert np.isnan(out.iloc[2])
    assert np.isnan(out.iloc[3])
    assert len(out) == 4  # index preserved, so the panel cannot de-align


def test_price_returns_reject_non_positive_prices():
    """WTI settled at -$37.63 on 2020-04-20; pct_change makes that -306%."""
    prices = pd.Series(
        [20.0, 18.0, -37.63, 10.0, 12.0], index=pd.bdate_range("2020-04-15", periods=5)
    )
    out = price_returns(prices)
    assert out.iloc[1] == pytest.approx(-0.10)
    assert np.isnan(out.iloc[2])  # into the negative print
    assert np.isnan(out.iloc[3])  # out of it
    assert out.iloc[4] == pytest.approx(0.20)


# ---------------------------------------------------------------------------
# Calendar alignment -- the bug that silently zeroed 30 of 39 instruments
# ---------------------------------------------------------------------------


def test_differing_holiday_calendars_do_not_kill_the_signal():
    """Regression: the union-index bug.

    Instruments trade on different calendars. On a naive union index every
    column gets NaN wherever some other market was open, a 252-day rolling
    window never fills, and the instrument silently contributes nothing while
    still appearing in the panel.
    """
    calendar = pd.bdate_range("2015-01-01", periods=900)
    rng = np.random.default_rng(11)
    series = {}
    for i in range(6):
        prices = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, 900))), index=calendar)
        # Each instrument observes a different, staggered subset of the calendar.
        series[f"I{i}"] = prices.drop(prices.index[i::17])

    unaligned = build_return_panel(series, {f"I{i}": "fx" for i in range(6)}, align=False)
    aligned = build_return_panel(series, {f"I{i}": "fx" for i in range(6)}, align=True)

    signal_unaligned = tsmom_signal(unaligned, lookback_months=12, lag=1)
    signal_aligned = tsmom_signal(aligned, lookback_months=12, lag=1)

    live_unaligned = int(signal_unaligned.notna().sum().sum())
    live_aligned = int(signal_aligned.notna().sum().sum())

    assert live_unaligned == 0, "test premise: the union index should destroy the signal"
    assert live_aligned > 0
    # Every instrument must be live, not just the one with the densest calendar.
    assert (signal_aligned.notna().sum() > 0).all()


def test_alignment_reports_filled_bars_instead_of_hiding_them():
    calendar = pd.bdate_range("2020-01-01", periods=60)
    dense = pd.Series(np.arange(60.0) + 100.0, index=calendar)
    sparse = dense.drop(calendar[10:15])
    aligned, filled = align_on_common_calendar({"D": dense, "S": sparse})
    assert filled["D"] == 0
    assert filled["S"] == 5
    # Forward-filled, so the holiday return is 0 rather than fabricated.
    assert aligned["S"].loc[calendar[12]] == pytest.approx(dense.loc[calendar[9]])


def test_alignment_never_extrapolates_beyond_an_instruments_life():
    calendar = pd.bdate_range("2020-01-01", periods=60)
    short = pd.Series(np.arange(30.0) + 1.0, index=calendar[:30])
    long_series = pd.Series(np.arange(60.0) + 1.0, index=calendar)
    aligned, _ = align_on_common_calendar({"S": short, "L": long_series})
    assert aligned["S"].iloc[:30].notna().all()
    assert aligned["S"].iloc[30:].isna().all(), "must not invent data past the last observation"


def test_data_quality_report_surfaces_non_positive_prices():
    calendar = pd.bdate_range("2020-04-01", periods=10)
    prices = pd.Series([20.0] * 9 + [-37.63], index=calendar)
    report = data_quality_report({"CL": prices}, {"CL": 0})
    assert report["CL"]["non_positive_prices"] == 1


def test_build_return_panel_routes_rates_through_duration():
    index = pd.bdate_range("2020-01-01", periods=5)
    series = {
        "TY": pd.Series([0.02, 0.021, 0.022, 0.021, 0.020], index=index),
        "CL": pd.Series([50.0, 51.0, 52.0, 51.0, 50.0], index=index),
    }
    panel = build_return_panel(series, {"TY": "rates", "CL": "commodity"})
    assert set(panel.columns) == {"TY", "CL"}
    # Rising yields must produce a negative bond return.
    assert panel["TY"].iloc[1] < 0
    assert panel["CL"].iloc[1] == pytest.approx(0.02)


def test_build_return_panel_requires_a_known_duration():
    index = pd.bdate_range("2020-01-01", periods=3)
    with pytest.raises(KeyError):
        build_return_panel({"XX": pd.Series([0.01, 0.02, 0.03], index=index)}, {"XX": "rates"})


# ---------------------------------------------------------------------------
# Rebalancing
# ---------------------------------------------------------------------------


def test_positions_are_held_between_rebalance_dates():
    index = pd.bdate_range("2021-01-04", periods=20)
    targets = pd.DataFrame({"A": np.linspace(1.0, 2.0, 20)}, index=index)
    held = apply_rebalance_schedule(targets, "W-FRI", no_trade_band=0.0)
    changes = held["A"].diff().fillna(0.0).ne(0.0).sum()
    # 20 business days ~= 4 weeks, so only a handful of changes.
    assert changes <= 5
    assert held["A"].nunique() <= 5


def test_no_trade_band_suppresses_small_adjustments():
    index = pd.bdate_range("2021-01-04", periods=40)
    targets = pd.DataFrame({"A": [1.0] * 20 + [1.02] * 20}, index=index)
    tight = apply_rebalance_schedule(targets, "W-FRI", no_trade_band=0.0)
    banded = apply_rebalance_schedule(targets, "W-FRI", no_trade_band=0.10)
    assert tight["A"].iloc[-1] == pytest.approx(1.02)
    # A 2% drift is inside a 10% band, so the position should not move.
    assert banded["A"].iloc[-1] == pytest.approx(1.0)


def test_rebalance_handles_empty_input():
    empty = pd.DataFrame(index=pd.DatetimeIndex([]), columns=["A"], dtype=float)
    assert apply_rebalance_schedule(empty, "W-FRI", 0.1).empty


# ---------------------------------------------------------------------------
# Accounting
# ---------------------------------------------------------------------------


def test_net_equals_gross_minus_costs():
    panel = _panel(900, 5)
    result = run_tsmom(panel, _classes(panel))
    recomputed = result.gross_returns - result.costs
    pd.testing.assert_series_equal(result.net_returns, recomputed, check_names=False, atol=1e-15)


def test_costs_are_non_negative_and_scale_with_the_multiplier():
    panel = _panel(900, 5)
    classes = _classes(panel)
    base = run_tsmom(panel, classes, StudyConfig())
    tripled = run_tsmom(panel, classes, StudyConfig(cost_multiplier=3.0))
    assert (base.costs.dropna() >= 0).all()
    assert tripled.costs.sum() == pytest.approx(3.0 * base.costs.sum(), rel=1e-9)
    assert tripled.net_returns.sum() < base.net_returns.sum()


def test_zero_cost_multiplier_makes_net_equal_gross():
    panel = _panel(700, 5)
    result = run_tsmom(panel, _classes(panel), StudyConfig(cost_multiplier=0.0))
    pd.testing.assert_series_equal(
        result.net_returns, result.gross_returns, check_names=False, atol=1e-15
    )


def test_run_is_deterministic():
    panel = _panel(900, 6)
    classes = _classes(panel)
    first = run_tsmom(panel, classes)
    second = run_tsmom(panel, classes)
    pd.testing.assert_series_equal(first.net_returns, second.net_returns)
    assert first.metrics == second.metrics


def test_unclassified_instrument_warns_rather_than_silently_defaulting():
    panel = _panel(700, 6)
    result = run_tsmom(panel, {"I0": "fx"})
    assert result.warnings
    assert "default 5bps" in result.warnings[0]


def test_trending_market_earns_and_choppy_market_does_not():
    """Sanity: TSMOM should make money in a trend and lose it in a chop."""
    index = pd.bdate_range("2010-01-01", periods=1500)
    trend = pd.DataFrame({f"I{i}": np.full(1500, 0.0006) for i in range(6)}, index=index)
    rng = np.random.default_rng(3)
    trend += rng.normal(0, 0.004, size=trend.shape)
    trending = run_tsmom(trend, _classes(trend))
    assert trending.metrics["net_sharpe"] > 0.5

    # A cycle a little longer than the 12-month lookback is the classic
    # whipsaw: the signal commits to the trend just as the cycle turns.
    steps = np.arange(1500)
    cycle = 100.0 * (1.0 + 0.30 * np.sin(2 * np.pi * steps / 380.0))
    cycle_returns = pd.Series(cycle, index=index).pct_change()
    chop = pd.DataFrame({f"I{i}": cycle_returns for i in range(6)}, index=index)
    choppy = run_tsmom(chop, _classes(chop))
    assert np.isfinite(choppy.metrics["net_sharpe"])
    assert choppy.metrics["net_sharpe"] < trending.metrics["net_sharpe"]


def test_config_rejects_invalid_settings():
    with pytest.raises(ValueError):
        StudyConfig(execution_lag=0)
    with pytest.raises(ValueError):
        StudyConfig(lookback_months=7)
    with pytest.raises(ValueError):
        StudyConfig(no_trade_band=1.0)
    with pytest.raises(ValueError):
        StudyConfig(portfolio_vol_target=0.0)


def test_metrics_cover_the_pre_registered_reporting_fields():
    panel = _panel(1200, 5)
    result = run_tsmom(panel, _classes(panel))
    for key in (
        "net_sharpe",
        "gross_sharpe",
        "net_cagr",
        "net_vol",
        "max_drawdown",
        "longest_drawdown_days",
        "avg_annual_turnover",
        "cost_drag_annual",
        "n_obs",
        "years",
    ):
        assert key in result.metrics


def test_compute_metrics_handles_an_empty_series():
    empty = pd.Series(dtype=float)
    out = compute_metrics(empty, empty, empty)
    assert out["n_obs"] == 0


# ---------------------------------------------------------------------------
# Deflated Sharpe -- regression for the units bug found 2026-08-17
# ---------------------------------------------------------------------------


def test_deflated_sharpe_is_not_degenerate():
    """It used to return 0.0 for every input, including brilliant strategies."""
    from quant_core.research.stats.robustness import deflated_sharpe_ratio

    rng = np.random.default_rng(0)
    excellent = rng.normal(0.003, 0.01, 5000)   # annualised Sharpe ~4.7
    worthless = rng.normal(0.0, 0.01, 5000)     # annualised Sharpe ~0

    assert deflated_sharpe_ratio(excellent, n_variants=4) > 0.99
    assert deflated_sharpe_ratio(worthless, n_variants=4) < 0.90
    # and it must discriminate between them
    assert deflated_sharpe_ratio(excellent, n_variants=4) > deflated_sharpe_ratio(worthless, n_variants=4)


def test_deflated_sharpe_penalises_more_variants():
    from quant_core.research.stats.robustness import deflated_sharpe_ratio

    rng = np.random.default_rng(5)
    returns = rng.normal(0.0004, 0.01, 4000)
    few = deflated_sharpe_ratio(returns, n_variants=2)
    many = deflated_sharpe_ratio(returns, n_variants=200)
    assert many <= few, "searching more variants must not make a result look better"


def test_deflated_sharpe_uses_supplied_variant_dispersion():
    from quant_core.research.stats.robustness import deflated_sharpe_ratio

    rng = np.random.default_rng(9)
    returns = rng.normal(0.0005, 0.01, 4000)
    tight = deflated_sharpe_ratio(returns, n_variants=4, variant_sharpes=[0.70, 0.69, 0.68, 0.67])
    wide = deflated_sharpe_ratio(returns, n_variants=4, variant_sharpes=[0.70, 0.10, -0.40, 1.30])
    # Widely dispersed trial Sharpes mean a higher bar to clear.
    assert wide < tight
