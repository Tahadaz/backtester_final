from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_core.engine import (  # noqa: E402
    BacktestEngine,
    DataConfig,
    EngineSpec,
    IndicatorsConfig,
    StrategyConfig,
)


def _assert_canonical(df: pd.DataFrame) -> None:
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.tz is not None
    assert str(df.index.tz) == "UTC"
    assert df.index.name == "timestamp"
    assert df.index.is_monotonic_increasing
    assert df.index.is_unique
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]


def test_synthetic_multi_symbol_backtest_smoke() -> None:
    data_cfg = DataConfig(
        source="synthetic",
        symbols=["AAA", "BBB"],
        start="2024-01-01",
        end="2024-12-31",
        synthetic={
            "seed": 42,
            "mu": 0.0003,
            "sigma": 0.01,
            "start_price": 100.0,
            "vol_min": 100_000,
            "vol_max": 300_000,
        },
    )
    spec = EngineSpec(
        data=data_cfg,
        indicators=IndicatorsConfig(),
        strategy=StrategyConfig(kind="buy_hold", params={}),
    )

    bundle = BacktestEngine(spec).run()

    assert set(bundle.md.bars.keys()) == {"AAA", "BBB"}
    for sym in ("AAA", "BBB"):
        _assert_canonical(bundle.md.bars[sym])


def test_synthetic_is_deterministic_for_same_config() -> None:
    common = dict(
        source="synthetic",
        symbols=["AAA", "BBB"],
        start="2024-01-01",
        end="2024-03-31",
        synthetic={"seed": 77},
    )
    spec1 = EngineSpec(
        data=DataConfig(**common),
        indicators=IndicatorsConfig(),
        strategy=StrategyConfig(kind="buy_hold", params={}),
    )
    spec2 = EngineSpec(
        data=DataConfig(**common),
        indicators=IndicatorsConfig(),
        strategy=StrategyConfig(kind="buy_hold", params={}),
    )

    b1 = BacktestEngine(spec1).run()
    b2 = BacktestEngine(spec2).run()

    for sym in ("AAA", "BBB"):
        pd.testing.assert_frame_equal(b1.md.bars[sym], b2.md.bars[sym])
