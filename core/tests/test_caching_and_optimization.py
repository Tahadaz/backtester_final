from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.quant_core.engine import DataConfig, _MARKET_DATA_CACHE, load_marketdata  # noqa: E402
from core.quant_core.optimize import ParamDef, _iter_random, _trial_params_key  # noqa: E402


def test_iter_random_deduplicates_trials() -> None:
    params = [
        ParamDef(key="strategy.sma_fast_window", kind="choice", domain=[5, 10], cast=int),
        ParamDef(key="strategy.sma_slow_window", kind="choice", domain=[20, 30], cast=int),
    ]

    trials = list(_iter_random(params, n_trials=50, seed=7))
    keys = {_trial_params_key(t) for t in trials}

    # 2x2 domain => at most 4 unique combos.
    assert len(trials) == 4
    assert len(keys) == len(trials)


def test_load_marketdata_uses_in_memory_cache() -> None:
    _MARKET_DATA_CACHE.clear()

    cfg = DataConfig(
        source="synthetic",
        symbols=["AAA"],
        start="2024-01-01",
        end="2024-02-01",
        synthetic={"seed": 42},
    )

    md1 = load_marketdata(cfg)
    md2 = load_marketdata(cfg)

    assert md1 is md2
    assert len(_MARKET_DATA_CACHE) == 1
