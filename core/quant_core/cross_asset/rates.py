from __future__ import annotations

from datetime import date
import calendar

import pandas as pd

from core.quant_core.fixed_income import BondDefinition, risk_measures


def _add_years(value: date, years: int) -> date:
    return date(value.year + years, value.month, min(value.day, calendar.monthrange(value.year + years, value.month)[1]))


def bond_duration_legs(
    par_yield: pd.Series,
    *,
    maturity_years: int,
    cash_rate: pd.Series | None = None,
    daycount: float = 1 / 252,
    coupon_frequency: int = 2,
) -> pd.DataFrame:
    if maturity_years <= 0:
        raise ValueError("maturity_years must be positive")
    if daycount <= 0:
        raise ValueError("daycount must be positive")
    yields = par_yield.astype(float)
    cash = cash_rate.astype(float).reindex(yields.index) if cash_rate is not None else pd.Series(0.0, index=yields.index)
    rows = pd.DataFrame(index=yields.index, columns=["carry", "duration", "convexity", "cash", "total", "excess", "modified_duration", "convexity_measure"], dtype=float)
    for position in range(1, len(yields)):
        previous_yield = yields.iloc[position - 1]
        current_yield = yields.iloc[position]
        previous_cash = cash.iloc[position - 1]
        if pd.isna(previous_yield) or pd.isna(current_yield) or pd.isna(previous_cash):
            continue
        settlement = pd.Timestamp(yields.index[position - 1]).date()
        bond = BondDefinition(100.0, "USD", float(previous_yield), coupon_frequency, _add_years(settlement, maturity_years), "ACT/365F")
        measures = risk_measures(bond, settlement, float(previous_yield))
        change = float(current_yield - previous_yield)
        carry_leg = float(previous_yield) * daycount
        duration_leg = -measures.modified_duration * change
        convexity_leg = 0.5 * measures.convexity * change ** 2
        cash_leg = float(previous_cash) * daycount
        total = carry_leg + duration_leg + convexity_leg
        rows.iloc[position] = [carry_leg, duration_leg, convexity_leg, cash_leg, total, total - cash_leg, measures.modified_duration, measures.convexity]
    return rows


def bond_duration_return(
    par_yield: pd.Series,
    *,
    maturity_years: int,
    cash_rate: pd.Series | None = None,
    daycount: float = 1 / 252,
    coupon_frequency: int = 2,
    excess: bool = True,
) -> pd.Series:
    legs = bond_duration_legs(par_yield, maturity_years=maturity_years, cash_rate=cash_rate, daycount=daycount, coupon_frequency=coupon_frequency)
    result = legs["excess" if excess else "total"].copy()
    result.name = par_yield.name
    return result
