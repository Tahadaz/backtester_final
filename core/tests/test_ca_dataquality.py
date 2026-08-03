import numpy as np
import pandas as pd
import pytest

from quant_core.cross_asset.backtest import run_backtest
from quant_core.cross_asset.dataquality import data_quality_report
from quant_core.cross_asset.instruments import Instrument
from quant_core.cross_asset.strategy_spec import Identity, PositionSpec, ResearchSource, SignalSpec, StrategyDefinition, Universe


def _spec():
    return StrategyDefinition(Identity("quality"), Universe(("A",)), ResearchSource(replication_fidelity="adapted"), signal=SignalSpec(lookback_months=1), position=PositionSpec(method="unit"))


def test_duplicate_and_all_stale_data_block_driver():
    index = pd.to_datetime(["2025-01-01", "2025-01-01", "2025-01-02"])
    panel = pd.DataFrame({"A": [1.0, 1.0, 1.0]}, index=index)
    report = data_quality_report(panel, [Instrument("A", "fx", "USD", "return")])
    assert report.blocks_backtest
    with pytest.raises(ValueError, match="quality blocks"):
        run_backtest(_spec(), panel)


def test_missing_values_warn_and_are_not_filled():
    panel = pd.DataFrame({"A": [0.01, np.nan, 0.02]}, index=pd.date_range("2025-01-01", periods=3))
    report = data_quality_report(panel, [Instrument("A", "fx", "USD", "return")])
    assert report.instruments[0].missing_periods == 1
    assert "no forward-fill" in report.warnings[0]
