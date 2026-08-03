from __future__ import annotations

import numpy as np
import pandas as pd


def time_series_momentum(excess_ret: pd.Series, lookback_months: int, lag: int = 1) -> pd.Series:
    if lookback_months not in {1, 3, 6, 12}:
        raise ValueError("lookback_months must be one of 1, 3, 6, 12")
    if lag < 1:
        raise ValueError("lag must be at least one bar")
    window = 21 * lookback_months
    trailing = excess_ret.astype(float).rolling(window, min_periods=window).sum()
    return np.sign(trailing).shift(lag)


def carry_signal(carry: pd.Series, lag: int = 1) -> pd.Series:
    if lag < 1:
        raise ValueError("lag must be at least one bar")
    return np.sign(carry.astype(float)).shift(lag)


def vol_scale(
    excess_ret: pd.Series,
    target_vol_annual: float,
    halflife: int,
    lag: int = 1,
) -> pd.Series:
    if target_vol_annual <= 0 or halflife <= 0 or lag < 1:
        raise ValueError("target_vol_annual, halflife and lag must be positive")
    annual_vol = excess_ret.astype(float).ewm(halflife=halflife, min_periods=halflife, adjust=False).std() * np.sqrt(252)
    return (target_vol_annual / annual_vol.replace(0.0, np.nan)).shift(lag)
