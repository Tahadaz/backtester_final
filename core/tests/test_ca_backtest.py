import numpy as np
import pandas as pd

from quant_core.cross_asset.backtest import STAGE_KEYS, run_backtest
from quant_core.cross_asset.strategy_spec import Disclosures, ExecutionSpec, Identity, PositionSpec, ResearchSource, SignalSpec, StrategyDefinition, Universe


def _spec():
    return StrategyDefinition(
        Identity("deterministic"),
        Universe(("A", "B")),
        ResearchSource(replication_fidelity="adapted"),
        signal=SignalSpec(lookback_months=1, lag=1),
        position=PositionSpec(method="unit", max_weight=0.5, max_gross=1.0),
        execution=ExecutionSpec(lag=1, half_spread_bps=1.0),
        disclosures=Disclosures(warnings=("fixture returns are non-tradable",)),
    )


def test_backtest_is_deterministic_complete_and_net_equals_gross_minus_costs():
    rng = np.random.default_rng(9)
    panel = pd.DataFrame(rng.normal(0, 0.01, (300, 2)), index=pd.date_range("2020-01-01", periods=300), columns=["A", "B"])
    first = run_backtest(_spec(), panel, seed=7)
    second = run_backtest(_spec(), panel, seed=7)
    assert tuple(first.stages) == STAGE_KEYS
    assert first.metrics == second.metrics
    pd.testing.assert_series_equal(first.stages["net_return"], first.stages["gross_return"] - first.stages["costs"], check_names=False)
    assert first.spec_hash == _spec().spec_hash()
    assert any("non-tradable" in warning for warning in first.warnings)
