from __future__ import annotations

import numpy as np
import pandas as pd


def size_positions(
    signals: pd.DataFrame,
    vols: pd.DataFrame,
    *,
    method: str,
    target_vol_annual: float | None,
    max_weight: float,
    max_gross: float,
) -> pd.DataFrame:
    if method not in {"unit", "inverse_vol", "vol_target"}:
        raise ValueError(f"unsupported sizing method: {method}")
    if max_weight <= 0 or max_gross <= 0:
        raise ValueError("caps must be positive")
    signals, vols = signals.astype(float).align(vols.astype(float), join="left")
    active = signals.notna().sum(axis=1).replace(0, np.nan)
    if method == "unit":
        weights = signals
    elif method == "inverse_vol":
        raw = signals / vols.replace(0.0, np.nan)
        weights = raw.div(raw.abs().sum(axis=1).replace(0.0, np.nan), axis=0)
    else:
        if target_vol_annual is None or target_vol_annual <= 0:
            raise ValueError("vol_target requires a positive target_vol_annual")
        weights = signals * target_vol_annual / vols.replace(0.0, np.nan)
        weights = weights.div(np.sqrt(active), axis=0)
    weights = weights.clip(-max_weight, max_weight)
    gross = weights.abs().sum(axis=1)
    scale = (max_gross / gross).clip(upper=1.0).replace([np.inf, -np.inf], 1.0)
    return weights.mul(scale, axis=0)
