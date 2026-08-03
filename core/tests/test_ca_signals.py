import numpy as np
import pandas as pd

from quant_core.cross_asset.signals import carry_signal, time_series_momentum, vol_scale


def test_signals_shift_exactly_one_bar_without_lookahead():
    index = pd.date_range("2020-01-01", periods=300)
    values = pd.Series(np.linspace(-0.01, 0.02, len(index)), index=index)
    shifted = values.shift(1)
    for fn in (
        lambda x: time_series_momentum(x, 1, lag=1),
        lambda x: carry_signal(x, lag=1),
        lambda x: vol_scale(x, 0.10, 20, lag=1),
    ):
        expected = fn(values).shift(1)
        actual = fn(shifted)
        pd.testing.assert_series_equal(actual.iloc[1:], expected.iloc[1:])
    shocked = values.copy()
    shocked.iloc[-1] = 100.0
    assert time_series_momentum(shocked, 1).iloc[-1] == time_series_momentum(values, 1).iloc[-1]
