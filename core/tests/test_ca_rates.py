import pandas as pd
import pytest
import numpy as np

from core.quant_core.cross_asset.backtest import run_backtest
from core.quant_core.cross_asset.rates import bond_duration_legs, bond_duration_return
from core.quant_core.cross_asset.strategy_spec import Disclosures, Identity, PositionSpec, ResearchSource, ReturnSpec, SignalSpec, StrategyDefinition, Universe


def test_decomposition_and_convexity_sign_for_rally_and_selloff():
    index = pd.date_range("2025-01-01", periods=3)
    yields = pd.Series([0.04, 0.05, 0.04], index=index)
    legs = bond_duration_legs(yields, maturity_years=10, cash_rate=pd.Series(0.02, index=index), daycount=1 / 252)
    assert legs.loc[index[1], "total"] == pytest.approx(legs.loc[index[1], ["carry", "duration", "convexity"]].sum())
    assert legs.loc[index[1], "convexity"] > 0
    assert legs.loc[index[2], "convexity"] > 0
    assert legs.loc[index[1], "excess"] == pytest.approx(legs.loc[index[1], "total"] - 0.02 / 252)


def test_duration_is_recomputed_and_inputs_are_lagged():
    index = pd.date_range("2025-01-01", periods=5)
    yields = pd.Series([0.01, 0.02, 0.03, 0.04, 0.05], index=index)
    legs = bond_duration_legs(yields, maturity_years=5, cash_rate=pd.Series(0.01, index=index))
    assert legs["modified_duration"].dropna().nunique() > 1
    shocked = yields.copy()
    shocked.iloc[-1] = 0.50
    original = bond_duration_return(yields, maturity_years=5, cash_rate=pd.Series(0.01, index=index))
    changed = bond_duration_return(shocked, maturity_years=5, cash_rate=pd.Series(0.01, index=index))
    pd.testing.assert_series_equal(original.iloc[:-1], changed.iloc[:-1])


def test_shifting_yield_path_shifts_return_one_bar():
    index = pd.date_range("2025-01-01", periods=20)
    yields = pd.Series([0.03 + i / 10000 for i in range(20)], index=index)
    cash = pd.Series(0.01, index=index)
    expected = bond_duration_return(yields, maturity_years=2, cash_rate=cash).shift(1)
    actual = bond_duration_return(yields.shift(1), maturity_years=2, cash_rate=cash.shift(1))
    pd.testing.assert_series_equal(actual.iloc[2:], expected.iloc[2:])


def test_bond_tsm_completes_shared_engine_with_model_warning():
    index = pd.date_range("2020-01-01", periods=320, freq="B")
    yields = pd.Series(0.03 + np.sin(np.arange(len(index)) / 30) / 200, index=index)
    modeled = bond_duration_return(yields, maturity_years=10, cash_rate=pd.Series(0.01, index=index))
    spec = StrategyDefinition(
        Identity("DGS10 Bond TSM"),
        Universe(("DGS10",), "USD"),
        ResearchSource("Rates TSM", "FRED constant maturity", "adapted"),
        signal=SignalSpec("time_series_momentum", 12, 1),
        position=PositionSpec("vol_target", 0.10, 20, 1.0, 1.0),
        returns=ReturnSpec("bond_duration", 1 / 252),
        disclosures=Disclosures(warnings=("Duration-approximated from par yields; not reconstructed from traded bonds or futures.",)),
    )
    result = run_backtest(spec, pd.DataFrame({"DGS10": modeled}, index=index), seed=17)
    assert "net_return" in result.stages
    assert any("Duration-approximated" in warning for warning in result.warnings)
