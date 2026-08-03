from datetime import date

import numpy as np
import pandas as pd
import pytest

from quant_core.cross_asset.returns import back_adjusted_series, build_return, futures_excess_return, fx_excess_return, to_base_ccy


def test_fx_excess_return_identity_and_lagged_carry():
    index = pd.date_range("2025-01-01", periods=3)
    spot = pd.Series([1.0, 1.1, 1.21], index=index)
    base = pd.Series([0.06, 0.09, 0.12], index=index)
    quote = pd.Series([0.0, 0.0, 0.0], index=index)
    actual = fx_excess_return(spot, base, quote, daycount=1 / 12)
    assert actual.iloc[1] == pytest.approx(0.105)


def test_futures_roll_reconstructs_back_adjusted_return_minus_collateral():
    index = pd.date_range("2025-01-01", periods=4)
    front = pd.Series([100.0, 101.0, 99.0, 100.0], index=index)
    collateral = pd.Series(0.05, index=index)
    rolls = [date(2025, 1, 3)]
    next_prices = {date(2025, 1, 3): 102.0}
    actual = futures_excess_return(front, rolls, next_prices, collateral)
    display = back_adjusted_series(front, rolls, next_prices).pct_change()
    np.testing.assert_allclose(actual.iloc[1:] - collateral.shift(1).iloc[1:] / 252, display.iloc[1:])


def test_base_ccy_conversion_and_bond_dispatch():
    index = pd.date_range("2025-01-01", periods=2)
    result = to_base_ccy(pd.Series([np.nan, 0.10], index=index), "EUR", "USD", {"EURUSD": pd.Series([1.0, 1.1], index=index)})
    assert result.iloc[1] == pytest.approx(0.21)
    with pytest.raises(NotImplementedError, match="Brief 4"):
        build_return("bond_duration")
