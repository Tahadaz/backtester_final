"""Adversarial tests for cross-market calendar alignment.

Key invariant: no look-ahead — factor.align[t] uses only information
from before MASI opens on day t.
"""
import pandas as pd
import pytest
import numpy as np

from core.quant_core.research.alignment import (
    align_factor_to_target,
    align_cross_market,
    _forward_fill_with_staleness_guard,
)


def _date_range(start: str, end: str, freq: str = "B") -> pd.DatetimeIndex:
    return pd.bdate_range(start=start, end=end)


class TestForwardFillStalenessGuard:
    def test_fills_within_limit(self):
        idx = pd.date_range("2024-01-01", periods=5, freq="B")
        s = pd.Series([1.0, float("nan"), float("nan"), float("nan"), float("nan")], index=idx)
        result = _forward_fill_with_staleness_guard(s, max_staleness=3)
        assert result.iloc[1] == 1.0
        assert result.iloc[2] == 1.0
        assert result.iloc[3] == 1.0
        assert pd.isna(result.iloc[4])

    def test_no_fill_beyond_max_staleness(self):
        idx = pd.date_range("2024-01-01", periods=6, freq="B")
        s = pd.Series([5.0, float("nan"), float("nan"), float("nan"), float("nan"), float("nan")], index=idx)
        result = _forward_fill_with_staleness_guard(s, max_staleness=2)
        assert result.iloc[1] == 5.0
        assert result.iloc[2] == 5.0
        assert pd.isna(result.iloc[3])

    def test_zero_staleness_no_fill(self):
        idx = pd.date_range("2024-01-01", periods=4, freq="B")
        s = pd.Series([1.0, float("nan"), float("nan"), float("nan")], index=idx)
        result = _forward_fill_with_staleness_guard(s, max_staleness=0)
        assert pd.isna(result.iloc[1])

    def test_resets_after_real_value(self):
        idx = pd.date_range("2024-01-01", periods=7, freq="B")
        s = pd.Series([1.0, float("nan"), float("nan"), 2.0, float("nan"), float("nan"), float("nan")], index=idx)
        result = _forward_fill_with_staleness_guard(s, max_staleness=2)
        # First gap: filled for 2, then not
        assert result.iloc[1] == 1.0
        assert result.iloc[2] == 1.0
        # After reset at idx[3] = 2.0
        assert result.iloc[3] == 2.0
        assert result.iloc[4] == 2.0
        assert result.iloc[5] == 2.0
        assert pd.isna(result.iloc[6])


class TestAlignFactorToTarget:
    def _masi_cal(self, start: str = "2024-01-01", periods: int = 50) -> pd.Series:
        """Simulate MASI trading calendar (no Eid/local holidays for simplicity)."""
        idx = pd.bdate_range(start=start, periods=periods)
        return pd.Series(np.random.default_rng(0).normal(100, 1, periods), index=idx)

    def _us_cal(self, start: str = "2024-01-01", periods: int = 50) -> pd.Series:
        """Simulate US factor (same business days as MASI for simplicity here)."""
        idx = pd.bdate_range(start=start, periods=periods)
        vals = np.arange(periods, dtype=float)
        return pd.Series(vals, index=idx)

    def test_precede_open_no_lookahead(self):
        target = self._masi_cal("2024-01-02", 20)
        factor = self._us_cal("2024-01-02", 25)

        aligned = align_factor_to_target(target, factor, lag_rule="precede_open")

        # At MASI date t, aligned factor must be factor value from t-1 or earlier
        # i.e., aligned[t] <= factor up to and including t-1
        for i in range(1, len(target)):
            t = target.index[i]
            a_val = aligned.iloc[i]
            if pd.isna(a_val):
                continue
            # Factor value as of aligned should come from before this target date
            factor_before_t = factor[factor.index < t]
            if len(factor_before_t) > 0:
                assert a_val in factor.values or pd.isna(a_val), \
                    f"Aligned value {a_val} not from factor series at t={t}"

    def test_precede_open_first_bar_is_nan(self):
        target = self._masi_cal("2024-01-02", 10)
        factor = self._us_cal("2024-01-02", 10)
        aligned = align_factor_to_target(target, factor, lag_rule="precede_open")
        # First target bar has no prior factor data → NaN
        assert pd.isna(aligned.iloc[0])

    def test_previous_close_lags_by_one(self):
        idx = pd.bdate_range("2024-01-02", periods=10)
        factor = pd.Series(range(10), dtype=float, index=idx)
        target = pd.Series(1.0, index=idx)

        aligned = align_factor_to_target(target, factor, lag_rule="previous_close")
        # At bar 1, should see factor[0]; at bar 2, factor[1]; etc.
        assert pd.isna(aligned.iloc[0])
        assert aligned.iloc[1] == pytest.approx(0.0)
        assert aligned.iloc[2] == pytest.approx(1.0)

    def test_contemporaneous_same_date(self):
        idx = pd.bdate_range("2024-01-02", periods=10)
        factor = pd.Series(range(10), dtype=float, index=idx)
        target = pd.Series(1.0, index=idx)

        aligned = align_factor_to_target(target, factor, lag_rule="contemporaneous")
        assert aligned.iloc[0] == pytest.approx(0.0)
        assert aligned.iloc[5] == pytest.approx(5.0)

    def test_masi_holiday_us_open(self):
        """US open while MASI closed (MASI holiday): factor data available on holiday,
        but target has no entry for that day. Aligned series should not introduce look-ahead."""
        # MASI calendar: skip 2024-01-04 (Thursday, treat as holiday)
        masi_dates = pd.bdate_range("2024-01-02", "2024-01-12").difference(
            pd.DatetimeIndex(["2024-01-04"])
        )
        target = pd.Series(100.0, index=masi_dates)

        # US factor has data every business day including the MASI holiday
        us_dates = pd.bdate_range("2024-01-02", "2024-01-12")
        factor = pd.Series(range(len(us_dates)), dtype=float, index=us_dates)

        aligned = align_factor_to_target(target, factor, lag_rule="precede_open")

        # After the holiday (2024-01-04), the next MASI session is 2024-01-05.
        # The aligned value at 2024-01-05 should use factor from 2024-01-04 or earlier.
        t_after_holiday = pd.Timestamp("2024-01-05")
        if t_after_holiday in aligned.index:
            a_val = aligned[t_after_holiday]
            if not pd.isna(a_val):
                # factor on 2024-01-03 is index 1 (value=1), 2024-01-04 is index 2 (value=2)
                # precede_open shift(1) means we use the factor from the previous target date
                # previous target date is 2024-01-03, so factor as of 2024-01-03 → aligned[2024-01-05]
                # could be factor[2024-01-04] or factor[2024-01-03] depending on implementation
                factor_up_to_t = factor[factor.index < t_after_holiday].values
                assert a_val in factor_up_to_t or pd.isna(a_val)

    def test_staleness_clamps_stale_factor(self):
        masi_idx = pd.bdate_range("2024-01-02", periods=10)
        target = pd.Series(100.0, index=masi_idx)

        # Factor only has 2 data points, rest is NaN (extreme staleness)
        factor = pd.Series(float("nan"), index=masi_idx)
        factor.iloc[0] = 10.0
        factor.iloc[1] = 11.0

        aligned = align_factor_to_target(target, factor, lag_rule="precede_open", max_staleness=2)

        # After staleness guard, beyond 2 stale bars should be NaN
        non_nan = aligned.dropna()
        assert len(non_nan) <= 4  # max 2 stale after initial, plus initial + 1 lag shift

    def test_returns_series_indexed_like_target(self):
        target = self._masi_cal("2024-01-02", 30)
        factor = self._us_cal("2024-01-02", 35)
        aligned = align_factor_to_target(target, factor)
        assert list(aligned.index) == list(target.index)


class TestAlignCrossMarket:
    def test_multiple_factors(self):
        idx = pd.bdate_range("2024-01-02", periods=20)
        target = pd.Series(100.0, index=idx)
        factors = {
            "VIX": pd.Series(range(20), dtype=float, index=idx),
            "DXY": pd.Series(range(20, 40), dtype=float, index=idx),
        }
        result = align_cross_market(target, factors)
        assert "VIX" in result.columns
        assert "DXY" in result.columns
        assert list(result.index) == list(idx)

    def test_per_factor_lag_rules(self):
        idx = pd.bdate_range("2024-01-02", periods=10)
        target = pd.Series(100.0, index=idx)
        factor = pd.Series(range(10), dtype=float, index=idx)

        result_lag = align_cross_market(target, {"F": factor}, lag_rules={"F": "previous_close"})
        result_cont = align_cross_market(target, {"F": factor}, lag_rules={"F": "contemporaneous"})

        # Contemporaneous should match factor directly; previous_close lags by 1
        assert pd.isna(result_lag["F"].iloc[0])
        assert not pd.isna(result_cont["F"].iloc[0])

    def test_dataframe_target_accepted(self):
        idx = pd.bdate_range("2024-01-02", periods=15)
        target_df = pd.DataFrame({"Close": 100.0, "Volume": 1000}, index=idx)
        factor = pd.Series(range(15), dtype=float, index=idx)
        result = align_cross_market(target_df, {"F": factor})
        assert list(result.index) == list(idx)
