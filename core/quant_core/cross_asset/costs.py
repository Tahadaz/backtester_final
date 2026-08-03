from __future__ import annotations

import pandas as pd


def _bps_frame(weights: pd.DataFrame, value: dict[str, float] | float) -> pd.DataFrame:
    if isinstance(value, dict):
        missing = [str(column) for column in weights.columns if str(column) not in value]
        if missing:
            raise KeyError(f"missing cost assumptions for: {missing}")
        row = pd.Series({column: float(value[str(column)]) for column in weights.columns})
        return pd.DataFrame([row.to_dict()] * len(weights), index=weights.index)
    return pd.DataFrame(float(value), index=weights.index, columns=weights.columns)


def apply_costs(
    weights: pd.DataFrame,
    half_spread_bps: dict[str, float] | float,
    slippage_bps: dict[str, float] | float,
    commission_bps: dict[str, float] | float,
) -> tuple[pd.Series, pd.Series]:
    changes = weights.astype(float).diff()
    for column in weights.columns:
        first_valid = weights[column].first_valid_index()
        if first_valid is not None:
            changes.loc[first_valid, column] = weights.loc[first_valid, column]
    per_instrument_turnover = changes.abs()
    turnover = per_instrument_turnover.sum(axis=1, min_count=1)
    total_bps = (
        _bps_frame(weights, half_spread_bps)
        + _bps_frame(weights, slippage_bps)
        + _bps_frame(weights, commission_bps)
    )
    costs = (per_instrument_turnover * total_bps / 10_000.0).sum(axis=1, min_count=1)
    turnover.name = "turnover"
    costs.name = "costs"
    return turnover, costs
