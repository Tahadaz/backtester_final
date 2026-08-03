"""Risk measures: Macaulay/modified duration, convexity, DV01.

Verify your Set-A drill approximations against these exact numbers — that
cross-check is the whole point of Build 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .cashflows import BondDefinition, _validate
from .pricing import _cashflow_periods, dirty_price


@dataclass(frozen=True)
class RiskMeasures:
    macaulay_duration: float   # years
    modified_duration: float   # years, MacDur / (1 + y/f)
    convexity: float           # years^2, standard second-derivative convexity
    dv01_per_100: float        # price change per 100 face for 1bp, positive


def risk_measures(bond: BondDefinition, settlement: date, ytm: float) -> RiskMeasures:
    """Analytic risk measures at flat yield ytm.

    - Macaulay: cash-flow-PV-weighted average time in years (period times / f).
    - Modified: MacDur / (1 + y/f).
    - Convexity: standard second-derivative convexity in years^2.
    - DV01 per 100: modified_duration * dirty_price * 0.0001, reported positive.
      (The test checks it against central-difference repricing.)
    """
    _validate(bond, settlement)
    frequency = bond.coupon_frequency
    base = 1.0 + ytm / frequency
    if base <= 0:
        raise ValueError("ytm is below the periodic-compounding lower bound")
    price = dirty_price(bond, settlement, ytm)
    weighted_time = 0.0
    second_derivative = 0.0
    for amount, periods in _cashflow_periods(bond, settlement):
        pv = amount * base ** (-periods)
        weighted_time += (periods / frequency) * pv
        second_derivative += amount * periods * (periods + 1.0) / (frequency ** 2) * base ** (-periods - 2.0)
    macaulay = weighted_time / price
    modified = macaulay / base
    convexity = second_derivative / price
    return RiskMeasures(macaulay, modified, convexity, modified * price * 0.0001)
