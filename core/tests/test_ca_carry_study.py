"""Tests for the carry sleeve.

The look-ahead surface here is different from TSMOM's: carry is driven by
*monthly, revised, lag-published* rate series, so the tests concentrate on the
publication lag and on never interpolating a rate forward in time.
"""

import numpy as np
import pandas as pd
import pytest

from quant_core.cross_asset.carry_study import (
    CURVE_TENORS,
    RATE_PUBLICATION_LAG_MONTHS,
    carry_signal_ranked,
    carry_signal_sign,
    carry_signal_smoothed,
    fx_carry,
    interpolate_curve,
    lag_monthly_rates,
    rates_curve_carry,
    to_daily_rate,
)


def _monthly(values, start="2020-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="MS"), dtype=float)


# ---------------------------------------------------------------------------
# Publication lag -- the carry-specific look-ahead risk
# ---------------------------------------------------------------------------


def test_monthly_rates_are_lagged_by_the_publication_delay():
    rates = _monthly([0.01, 0.02, 0.03])
    lagged = lag_monthly_rates(rates, months=2)
    # January's observation must not be usable until March.
    assert lagged.index[0] == pd.Timestamp("2020-03-01")
    assert lagged.iloc[0] == pytest.approx(0.01)


def test_default_lag_matches_the_preregistered_value():
    assert RATE_PUBLICATION_LAG_MONTHS == 2


def test_lag_rejects_negative_values():
    with pytest.raises(ValueError):
        lag_monthly_rates(_monthly([0.01]), months=-1)


def test_daily_rate_is_stepped_forward_never_interpolated():
    rates = _monthly([0.01, 0.05])
    calendar = pd.bdate_range("2020-01-01", "2020-02-10")
    daily = to_daily_rate(rates, calendar)
    january = daily.loc["2020-01-15"]
    assert january == pytest.approx(0.01), "must hold January's value, not drift toward February's"
    assert daily.loc["2020-02-05"] == pytest.approx(0.05)
    # Nothing between the two observations may take an intermediate value.
    assert set(np.round(daily.dropna().unique(), 10)) <= {0.01, 0.05}


def test_daily_rate_before_first_observation_is_missing_not_backfilled():
    rates = _monthly([0.03], start="2020-06-01")
    calendar = pd.bdate_range("2020-01-01", "2020-07-01")
    daily = to_daily_rate(rates, calendar)
    assert daily.loc["2020-03-02"] != daily.loc["2020-03-02"]  # NaN
    assert daily.loc["2020-06-15"] == pytest.approx(0.03)


def test_empty_rate_series_yields_all_missing():
    daily = to_daily_rate(pd.Series(dtype=float), pd.bdate_range("2020-01-01", periods=5))
    assert daily.isna().all()


# ---------------------------------------------------------------------------
# FX carry
# ---------------------------------------------------------------------------


def test_fx_carry_is_base_minus_quote():
    calendar = pd.bdate_range("2020-01-01", periods=20)
    rates = {"EUR": _monthly([0.00]), "USD": _monthly([0.02]), "JPY": _monthly([-0.001])}
    carry = fx_carry(rates, {"EURUSD": ("EUR", "USD"), "USDJPY": ("USD", "JPY")}, calendar)
    # Long EURUSD owns EUR (0%) funded in USD (2%) -> negative carry.
    assert carry["EURUSD"].iloc[-1] == pytest.approx(-0.02)
    # Long USDJPY owns USD (2%) funded in JPY (-0.1%) -> positive carry.
    assert carry["USDJPY"].iloc[-1] == pytest.approx(0.021)


def test_fx_carry_skips_pairs_with_a_missing_currency():
    calendar = pd.bdate_range("2020-01-01", periods=5)
    carry = fx_carry({"EUR": _monthly([0.0])}, {"EURUSD": ("EUR", "USD")}, calendar)
    assert "EURUSD" not in carry.columns


# ---------------------------------------------------------------------------
# Curve interpolation and rates carry
# ---------------------------------------------------------------------------


def test_interpolate_curve_hits_known_points_exactly():
    index = pd.bdate_range("2020-01-01", periods=3)
    curve = pd.DataFrame(
        {"DGS3MO": [0.01] * 3, "DGS2": [0.02] * 3, "DGS10": [0.03] * 3}, index=index
    )
    assert interpolate_curve(curve, 2.0).iloc[0] == pytest.approx(0.02)
    assert interpolate_curve(curve, 10.0).iloc[0] == pytest.approx(0.03)
    # Halfway between 2y (2%) and 10y (3%) in tenor space.
    assert interpolate_curve(curve, 6.0).iloc[0] == pytest.approx(0.025)


def test_interpolate_curve_needs_two_live_points():
    index = pd.bdate_range("2020-01-01", periods=2)
    curve = pd.DataFrame({"DGS2": [0.02, np.nan], "DGS10": [np.nan, np.nan]}, index=index)
    out = interpolate_curve(curve, 5.0)
    assert out.isna().all()


def test_rates_carry_is_positive_on_an_upward_sloping_curve():
    index = pd.bdate_range("2020-01-01", periods=3)
    curve = pd.DataFrame(
        {
            "DGS3MO": [0.01] * 3,
            "DGS1": [0.012] * 3,
            "DGS2": [0.015] * 3,
            "DGS5": [0.020] * 3,
            "DGS10": [0.025] * 3,
            "DGS30": [0.030] * 3,
        },
        index=index,
    )
    carry = rates_curve_carry(curve)
    # Upward slope: every tenor yields above 3m funding and rolls down.
    assert (carry.iloc[-1] > 0).all()
    # The long end has the most duration, so the most roll-down.
    assert carry["US"].iloc[-1] > carry["TU"].iloc[-1]


def test_rates_carry_is_negative_on_an_inverted_curve():
    index = pd.bdate_range("2020-01-01", periods=2)
    curve = pd.DataFrame(
        {
            "DGS3MO": [0.055] * 2,
            "DGS1": [0.052] * 2,
            "DGS2": [0.048] * 2,
            "DGS5": [0.042] * 2,
            "DGS10": [0.040] * 2,
            "DGS30": [0.039] * 2,
        },
        index=index,
    )
    carry = rates_curve_carry(curve)
    assert (carry.iloc[-1] < 0).all(), "inverted curve must produce negative carry everywhere"


def test_rates_carry_requires_the_financing_column():
    index = pd.bdate_range("2020-01-01", periods=2)
    curve = pd.DataFrame({"DGS2": [0.02] * 2, "DGS10": [0.03] * 2}, index=index)
    with pytest.raises(KeyError):
        rates_curve_carry(curve)


def test_curve_tenors_cover_the_rates_universe():
    from quant_core.cross_asset.carry_study import RATES_TENOR

    assert set(RATES_TENOR) == {"TU", "FV", "TY", "US"}
    assert max(CURVE_TENORS.values()) >= max(t for t, _ in RATES_TENOR.values())


# ---------------------------------------------------------------------------
# Signal variants
# ---------------------------------------------------------------------------


def _carry_frame(n=100):
    index = pd.bdate_range("2020-01-01", periods=n)
    return pd.DataFrame(
        {"A": np.linspace(-0.02, 0.02, n), "B": np.full(n, 0.01), "C": np.full(n, -0.005)},
        index=index,
    )


@pytest.mark.parametrize("fn", [carry_signal_sign, carry_signal_smoothed, carry_signal_ranked])
def test_all_variants_are_lagged_by_one_bar(fn):
    carry = _carry_frame()
    signal = fn(carry)
    # The first bar can never carry a signal, since it would need same-bar data.
    assert signal.iloc[0].isna().all()
    with pytest.raises(ValueError):
        fn(carry, lag=0)


def test_sign_variant_follows_the_sign_of_carry():
    carry = _carry_frame()
    signal = carry_signal_sign(carry)
    assert signal["B"].iloc[-1] == 1.0
    assert signal["C"].iloc[-1] == -1.0


def test_ranked_variant_is_cross_sectionally_demeaned():
    carry = _carry_frame()
    signal = carry_signal_ranked(carry)
    last = signal.iloc[-1]
    # B (+1%) is above the cross-sectional mean, C (-0.5%) below.
    assert last["B"] == 1.0
    assert last["C"] == -1.0
    # A level shift applied to every instrument must not change the signal.
    shifted = carry_signal_ranked(carry + 0.05)
    pd.testing.assert_series_equal(signal.iloc[-1], shifted.iloc[-1])


def test_smoothed_variant_damps_a_one_day_spike():
    """A plausible rate jump, not an absurd one.

    The smoother is a 21-bar mean, so it damps a spike proportional to the
    signal's own scale (carry is single-digit percent). It is deliberately not
    outlier-proof -- a carry print of 500% is a data defect, and catching those
    is the data-quality layer's job, not the signal's.
    """
    carry = _carry_frame()
    spiked = carry.copy()
    spiked.iloc[-2, spiked.columns.get_loc("C")] = 0.05  # +5% carry for one bar
    plain = carry_signal_sign(spiked).iloc[-1]["C"]
    smooth = carry_signal_smoothed(spiked).iloc[-1]["C"]
    assert plain == 1.0, "raw sign flips on the spike"
    assert smooth == -1.0, "the 21-bar mean should outvote a single bar"


def test_variants_registry_matches_the_preregistered_count():
    from quant_core.cross_asset.carry_study import CARRY_VARIANTS

    assert len(CARRY_VARIANTS) == 3, "the pre-registration declares exactly three variants"
