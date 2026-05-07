"""Tests for core/quant_core/research/universe.py"""
import numpy as np
import pandas as pd
import pytest

from quant_core.research.universe import (
    ActiveUniverse,
    compute_adv,
    get_active_universe,
    is_tradeable,
)


def _make_ohlcv(n: int, close: float = 100.0, volume: float = 10_000.0) -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )


def _make_no_volume(n: int, close: float = 100.0) -> pd.DataFrame:
    df = _make_ohlcv(n, close=close, volume=0.0)
    df = df.drop(columns=["volume"])
    return df


class TestComputeAdv:
    def test_basic(self):
        df = _make_ohlcv(100, close=50.0, volume=20_000.0)
        adv = compute_adv(df, window=63)
        assert abs(adv - 50.0 * 20_000.0) < 1.0

    def test_empty_df(self):
        df = pd.DataFrame()
        assert np.isnan(compute_adv(df))

    def test_no_volume_col_returns_nan(self):
        df = _make_no_volume(100)
        assert np.isnan(compute_adv(df))

    def test_all_zero_volume_returns_nan(self):
        df = _make_ohlcv(100, volume=0.0)
        assert np.isnan(compute_adv(df))

    def test_partial_volume_averages_over_traded_days(self):
        df = _make_ohlcv(10, close=10.0, volume=100.0)
        df.iloc[::2, df.columns.get_loc("volume")] = 0.0  # zero every other day
        adv = compute_adv(df, window=10)
        assert adv == pytest.approx(10.0 * 100.0, rel=1e-3)

    def test_window_respected(self):
        df = _make_ohlcv(200, close=10.0, volume=500.0)
        # Last 20 bars have volume=1000
        df.iloc[-20:, df.columns.get_loc("volume")] = 1000.0
        adv_full = compute_adv(df, window=200)
        adv_recent = compute_adv(df, window=20)
        assert adv_recent > adv_full  # recent window has higher ADV


class TestIsTradeable:
    def test_enough_history_passes(self):
        df = _make_ohlcv(300)
        ok, reason = is_tradeable(df, min_bars=252)
        assert ok
        assert reason is None

    def test_insufficient_history_fails(self):
        df = _make_ohlcv(100)
        ok, reason = is_tradeable(df, min_bars=252)
        assert not ok
        assert "insufficient_history" in reason

    def test_none_df_fails(self):
        ok, reason = is_tradeable(None)
        assert not ok
        assert reason == "no_data"

    def test_empty_df_fails(self):
        ok, reason = is_tradeable(pd.DataFrame())
        assert not ok
        assert reason == "no_data"

    def test_price_below_min_fails(self):
        df = _make_ohlcv(300, close=3.0)
        ok, reason = is_tradeable(df, min_price=5.0)
        assert not ok
        assert "price_too_low" in reason

    def test_adv_below_min_fails(self):
        df = _make_ohlcv(300, close=10.0, volume=100.0)  # ADV=1000
        ok, reason = is_tradeable(df, min_adv_mad=5_000.0)
        assert not ok
        assert "adv_too_low" in reason

    def test_no_volume_col_does_not_exclude(self):
        df = _make_no_volume(300, close=20.0)
        ok, reason = is_tradeable(df, min_adv_mad=1_000_000.0)
        assert ok  # volume data absent → don't exclude

    def test_no_close_col_fails(self):
        df = pd.DataFrame({"open": [1, 2, 3] * 100})
        ok, reason = is_tradeable(df, min_bars=10)
        assert not ok
        assert reason == "no_close_column"


class TestGetActiveUniverse:
    def _make_universe(self):
        return {
            "ATW": _make_ohlcv(300, close=50.0, volume=100_000.0),
            "CIH": _make_ohlcv(300, close=20.0, volume=50.0),   # low ADV
            "NEW": _make_ohlcv(50, close=30.0),                  # insufficient history
            "BCP": _make_ohlcv(300, close=2.0),                  # price too low
        }

    def test_returns_active_universe(self):
        universe = get_active_universe(self._make_universe(), min_bars=252, min_price=5.0)
        assert isinstance(universe, ActiveUniverse)

    def test_tradeable_passes_all_filters(self):
        universe = get_active_universe(self._make_universe(), min_bars=252, min_price=5.0)
        assert "ATW" in universe.tradeable

    def test_insufficient_history_excluded(self):
        universe = get_active_universe(self._make_universe(), min_bars=252, min_price=5.0)
        assert "NEW" not in universe.tradeable

    def test_low_price_excluded(self):
        universe = get_active_universe(self._make_universe(), min_bars=252, min_price=5.0)
        assert "BCP" not in universe.tradeable

    def test_as_of_defaults_to_today(self):
        import datetime
        universe = get_active_universe({"ATW": _make_ohlcv(300)}, min_bars=252)
        assert universe.as_of == datetime.date.today().isoformat()

    def test_custom_as_of(self):
        universe = get_active_universe({"ATW": _make_ohlcv(300)}, as_of="2024-06-01")
        assert universe.as_of == "2024-06-01"

    def test_n_tradeable_count(self):
        universe = get_active_universe(self._make_universe(), min_bars=252, min_price=5.0)
        assert universe.n_tradeable == len(universe.tradeable)

    def test_rows_complete(self):
        universe = get_active_universe(self._make_universe(), min_bars=252, min_price=5.0)
        symbols_in_rows = {r.symbol for r in universe.rows}
        assert symbols_in_rows == {"ATW", "CIH", "NEW", "BCP"}

    def test_empty_input(self):
        universe = get_active_universe({})
        assert universe.tradeable == []
        assert universe.rows == []

    def test_tradeable_symbols_sorted(self):
        prices = {
            "ZZZ": _make_ohlcv(300),
            "AAA": _make_ohlcv(300),
            "MMM": _make_ohlcv(300),
        }
        universe = get_active_universe(prices, min_bars=252)
        assert universe.tradeable == sorted(universe.tradeable)
