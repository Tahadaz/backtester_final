from __future__ import annotations

from quant_core.horizons import (
    DEFAULT_COST_BPS_PER_SIDE,
    HORIZON_PARAMS,
    HORIZON_SPECS,
    VALID_HORIZONS,
    canonical_horizon,
)
from quant_core.signal_engine.candidates import generate_candidates


def test_canonical_horizon_contract() -> None:
    assert VALID_HORIZONS == frozenset({"weekly", "monthly", "quarterly"})
    assert DEFAULT_COST_BPS_PER_SIDE == 33.0

    weekly = HORIZON_SPECS["weekly"]
    assert weekly.prediction_min_days == 1
    assert weekly.prediction_max_days == 5
    assert weekly.forward_grid_days == (1, 3, 5)
    assert weekly.signal_engine_holdout_bars == 60
    assert HORIZON_PARAMS["monthly"] == {"train": 504, "test": 63, "step": 63, "max_years": 10}
    assert HORIZON_SPECS["quarterly"].signal_engine_holdout_bars == 360


def test_legacy_horizons_are_only_explicit_aliases() -> None:
    assert canonical_horizon("short", allow_legacy=True) == "weekly"
    assert canonical_horizon("medium", allow_legacy=True) == "monthly"
    assert canonical_horizon("long", allow_legacy=True) == "quarterly"


def test_candidate_generation_accepts_new_horizon_names() -> None:
    assert generate_candidates("sma", "weekly")
    assert generate_candidates("rsi", "monthly")
    assert generate_candidates("macd", "quarterly")
