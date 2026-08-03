import numpy as np
import pandas as pd

from quant_core.cross_asset.portfolio import size_positions


def test_vol_target_caps_and_short_symmetry():
    index = pd.date_range("2025-01-01", periods=50)
    signals = pd.DataFrame({"A": 1.0, "B": -1.0}, index=index)
    vols = pd.DataFrame({"A": 0.20, "B": 0.20}, index=index)
    weights = size_positions(signals, vols, method="vol_target", target_vol_annual=0.10, max_weight=0.4, max_gross=0.8)
    assert weights.abs().max().max() <= 0.4
    assert weights.abs().sum(axis=1).max() <= 0.8
    np.testing.assert_allclose(weights["A"], -weights["B"])
    implied = np.sqrt(((weights * vols) ** 2).sum(axis=1))
    np.testing.assert_allclose(implied, 0.10)
