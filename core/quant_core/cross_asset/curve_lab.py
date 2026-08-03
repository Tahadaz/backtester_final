from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping

import pandas as pd

from core.quant_core.fixed_income import BondDefinition, risk_measures


def curve_spreads(yields: pd.DataFrame) -> pd.DataFrame:
    aliases = {
        2: next((key for key in (2, "2", "DGS2") if key in yields), None),
        5: next((key for key in (5, "5", "DGS5") if key in yields), None),
        10: next((key for key in (10, "10", "DGS10") if key in yields), None),
        30: next((key for key in (30, "30", "DGS30") if key in yields), None),
    }
    missing = [str(maturity) for maturity, column in aliases.items() if column is None]
    if missing:
        raise ValueError(f"curve missing maturities: {', '.join(missing)}")
    return pd.DataFrame({"2s10s": yields[aliases[10]] - yields[aliases[2]], "5s30s": yields[aliases[30]] - yields[aliases[5]]}, index=yields.index)


def classify_regime(short_yield_change: float, long_yield_change: float) -> str:
    level_change = (short_yield_change + long_yield_change) / 2.0
    slope_change = long_yield_change - short_yield_change
    if level_change == 0 or slope_change == 0:
        return "unchanged"
    direction = "bull" if level_change < 0 else "bear"
    shape = "steepener" if slope_change > 0 else "flattener"
    return f"{direction}_{shape}"


def regime_history(short_yield: pd.Series, long_yield: pd.Series) -> pd.Series:
    short_change = short_yield.astype(float).diff()
    long_change = long_yield.astype(float).diff()
    return pd.Series(
        [None if pd.isna(short_change.iloc[index]) or pd.isna(long_change.iloc[index]) else classify_regime(float(short_change.iloc[index]), float(long_change.iloc[index])) for index in range(len(short_change))],
        index=short_yield.index,
        name="regime",
        dtype=object,
    )


def roll_down_return(
    curve: Mapping[float, float],
    *,
    maturity_years: float,
    horizon_years: float,
    modified_duration: float,
) -> float:
    if horizon_years < 0 or horizon_years >= maturity_years:
        raise ValueError("horizon_years must be non-negative and shorter than maturity")
    target = maturity_years - horizon_years
    points = sorted((float(key), float(value)) for key, value in curve.items())
    if target < points[0][0] or maturity_years > points[-1][0]:
        raise ValueError("curve does not bracket roll-down maturities")

    def interpolate(maturity: float) -> float:
        for left, right in zip(points, points[1:]):
            if left[0] <= maturity <= right[0]:
                weight = (maturity - left[0]) / (right[0] - left[0])
                return left[1] + weight * (right[1] - left[1])
        return points[-1][1]

    yield_change = interpolate(target) - interpolate(maturity_years)
    return -modified_duration * yield_change


@dataclass(frozen=True)
class CurveTradeResult:
    long_notional: float
    short_notional: float
    long_dv01: float
    short_dv01: float
    residual_dv01: float
    long_pnl: float
    short_pnl: float
    total_pnl: float


def dv01_neutral_curve_trade(
    long_bond: BondDefinition,
    short_bond: BondDefinition,
    *,
    settlement: date,
    long_ytm: float,
    short_ytm: float,
    long_notional: float,
    long_yield_change_bp: float = 0.0,
    short_yield_change_bp: float = 0.0,
) -> CurveTradeResult:
    if long_notional <= 0:
        raise ValueError("long_notional must be positive")
    long_per_100 = risk_measures(long_bond, settlement, long_ytm).dv01_per_100
    short_per_100 = risk_measures(short_bond, settlement, short_ytm).dv01_per_100
    if short_per_100 <= 0:
        raise ValueError("short-leg DV01 must be positive")
    long_dv01 = long_per_100 * long_notional / 100.0
    short_notional = long_dv01 / short_per_100 * 100.0
    short_dv01 = -short_per_100 * short_notional / 100.0
    residual = long_dv01 + short_dv01
    long_pnl = -long_dv01 * long_yield_change_bp
    short_pnl = -short_dv01 * short_yield_change_bp
    return CurveTradeResult(long_notional, short_notional, long_dv01, short_dv01, residual, long_pnl, short_pnl, long_pnl + short_pnl)
