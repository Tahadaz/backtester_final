"""Canonical horizon and transaction-cost contract shared across quant services."""

from __future__ import annotations

from dataclasses import dataclass


DEFAULT_COST_BPS_PER_SIDE = 33.0


@dataclass(frozen=True)
class HorizonSpec:
    name: str
    label: str
    prediction_min_days: int
    prediction_max_days: int
    reference_forward_days: int
    forward_grid_days: tuple[int, ...]
    train_bars: int
    wfo_oos_bars: int
    wfo_step_bars: int
    max_years: int
    signal_engine_holdout_bars: int


HORIZON_SPECS: dict[str, HorizonSpec] = {
    "weekly": HorizonSpec(
        name="weekly",
        label="Weekly",
        prediction_min_days=1,
        prediction_max_days=5,
        reference_forward_days=5,
        forward_grid_days=(1, 3, 5),
        train_bars=252,
        wfo_oos_bars=21,
        wfo_step_bars=21,
        max_years=5,
        signal_engine_holdout_bars=60,
    ),
    "monthly": HorizonSpec(
        name="monthly",
        label="Monthly",
        prediction_min_days=6,
        prediction_max_days=21,
        reference_forward_days=21,
        forward_grid_days=(6, 10, 15, 21),
        train_bars=504,
        wfo_oos_bars=63,
        wfo_step_bars=63,
        max_years=10,
        signal_engine_holdout_bars=180,
    ),
    "quarterly": HorizonSpec(
        name="quarterly",
        label="Quarterly",
        prediction_min_days=22,
        prediction_max_days=63,
        reference_forward_days=63,
        forward_grid_days=(22, 42, 63),
        train_bars=756,
        wfo_oos_bars=126,
        wfo_step_bars=126,
        max_years=20,
        signal_engine_holdout_bars=360,
    ),
}


VALID_HORIZONS = frozenset(HORIZON_SPECS)

HORIZON_PARAMS: dict[str, dict[str, int]] = {
    key: {
        "train": spec.train_bars,
        "test": spec.wfo_oos_bars,
        "step": spec.wfo_step_bars,
        "max_years": spec.max_years,
    }
    for key, spec in HORIZON_SPECS.items()
}

LEGACY_HORIZON_ALIASES = {
    "short": "weekly",
    "medium": "monthly",
    "long": "quarterly",
}


def canonical_horizon(value: str, *, allow_legacy: bool = False) -> str:
    token = str(value).strip().lower()
    if token in HORIZON_SPECS:
        return token
    if allow_legacy and token in LEGACY_HORIZON_ALIASES:
        return LEGACY_HORIZON_ALIASES[token]
    raise ValueError(f"Unknown horizon {value!r}; expected one of {sorted(VALID_HORIZONS)}")
