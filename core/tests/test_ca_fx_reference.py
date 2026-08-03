import pandas as pd
import pytest

from core.quant_core.cross_asset.returns import fx_excess_return
from core.quant_core.cross_asset.strategy_spec import StrategyDefinition
from services.api.app.services.cross_asset.reference_strategies import fx_reference_strategies


def test_fx_identity_and_reference_specs_are_stable_round_trips():
    index = pd.date_range("2025-01-01", periods=2)
    total = fx_excess_return(
        pd.Series([1.0, 1.1], index=index),
        pd.Series([0.06, 0.07], index=index),
        pd.Series([0.03, 0.04], index=index),
        daycount=1 / 12,
    )
    assert total.iloc[1] == pytest.approx(0.10 + (0.06 - 0.03) / 12)
    for spec in fx_reference_strategies():
        restored = StrategyDefinition.from_dict(spec.to_dict())
        assert restored == spec
        assert restored.spec_hash() == spec.spec_hash()
        assert restored.research_source.replication_fidelity == "adapted"
        assert restored.execution.rebalance == "monthly"
