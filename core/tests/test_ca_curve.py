from datetime import date

import pandas as pd
import pytest
import numpy as np

from quant_core.cross_asset.backtest import run_backtest
from quant_core.cross_asset.curve import curve_carry, curve_snapshot, nominal_carry
from services.api.app.services.cross_asset.commodity_data import commodity_reference_strategy


def test_front_second_and_front_fourth_carry_on_hand_built_curve():
    frame = pd.DataFrame({"date": ["2025-01-02"] * 4, "contract_expiry": ["2025-02-01", "2025-03-01", "2025-04-01", "2025-05-01"], "settle": [100.0, 99.0, 98.0, 97.0], "volume": [1000, 800, 500, 300]})
    snapshot = curve_snapshot(frame, date(2025, 1, 2))
    carry = curve_carry(snapshot)
    assert carry.front_second is not None and carry.front_second > 0
    assert carry.front_fourth is not None and carry.front_fourth > 0


def test_contango_is_negative_with_explicit_annualization():
    assert nominal_carry(100, 102, 1) == pytest.approx((100 / 102 - 1) * 12)
    assert nominal_carry(100, 102, 1) < 0


def test_fixture_commodity_run_uses_shared_engine_and_is_labelled_non_tradable():
    index = pd.date_range("2024-01-01", periods=100, freq="B")
    panel = pd.DataFrame({("GC", "front"): 2600 + np.linspace(0, 80, len(index)), ("GC", "collateral_rate"): 0.04 + np.linspace(0, 0.001, len(index))}, index=index)
    result = run_backtest(commodity_reference_strategy(), panel, seed=11)
    assert "tradable_returns" in result.stages
    assert any("non-tradable" in warning for warning in result.warnings)
