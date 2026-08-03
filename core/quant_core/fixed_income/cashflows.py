"""Bond definition and cash-flow schedule generation.

You implement generate_schedule() and previous_coupon_date(). The dataclasses
are given so the tests and later modules share one shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import calendar


@dataclass(frozen=True)
class BondDefinition:
    face_value: float          # per-100 quotation assumed; default 100.0
    currency: str              # ISO code, display only
    coupon_rate: float         # decimal p.a., e.g. 0.05 for 5%
    coupon_frequency: int      # 1 or 2
    maturity_date: date
    day_count: str             # "30E/360" | "ACT/ACT-ICMA" | "ACT/365F"
    redemption: float = 100.0  # per 100 face


@dataclass(frozen=True)
class CashFlow:
    date: date
    amount: float              # per 100 face
    kind: str                  # "coupon" | "redemption"


def _validate(bond: BondDefinition, settlement: date | None = None) -> None:
    if bond.face_value <= 0:
        raise ValueError("face_value must be positive")
    if bond.coupon_rate < 0:
        raise ValueError("coupon_rate cannot be negative")
    if bond.coupon_frequency not in {1, 2}:
        raise ValueError("coupon_frequency must be 1 or 2")
    if bond.day_count not in {"30E/360", "ACT/ACT-ICMA", "ACT/365F"}:
        raise ValueError(f"unsupported day_count: {bond.day_count}")
    if bond.redemption <= 0:
        raise ValueError("redemption must be positive")
    if settlement is not None and settlement >= bond.maturity_date:
        raise ValueError("settlement must be before maturity_date")


def _add_months(value: date, months: int) -> date:
    ordinal = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(ordinal, 12)
    month = month_zero + 1
    return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _coupon_dates_back_to(bond: BondDefinition, cutoff: date) -> list[date]:
    step = 12 // bond.coupon_frequency
    dates = [bond.maturity_date]
    while dates[-1] > cutoff:
        dates.append(_add_months(dates[-1], -step))
    return dates


def generate_schedule(bond: BondDefinition, settlement: date) -> list[CashFlow]:
    """Cash flows strictly after settlement, in date order.

    - Coupon dates roll BACKWARDS from maturity in 12/frequency-month steps
      (clamp day-of-month on short months; no dateutil in this package, so hand-
      roll the month arithmetic).
    - Regular coupon amount per 100 = 100 * coupon_rate / frequency. Do NOT
      recompute regular coupons via day count.
    - The final flow carries coupon + redemption (redemption kind "redemption").
    - A zero-coupon bond (coupon_rate == 0) has a single redemption flow.
    """
    _validate(bond, settlement)
    if bond.coupon_rate == 0:
        return [CashFlow(bond.maturity_date, bond.redemption, "redemption")]
    dates = sorted(item for item in _coupon_dates_back_to(bond, settlement) if item > settlement)
    coupon = 100.0 * bond.coupon_rate / bond.coupon_frequency
    return [
        CashFlow(item, coupon + bond.redemption if item == bond.maturity_date else coupon, "redemption" if item == bond.maturity_date else "coupon")
        for item in dates
    ]


def previous_coupon_date(bond: BondDefinition, settlement: date) -> date:
    """The notional coupon date <= settlement from the same backward roll.

    Used as the accrual period start for accrued_interest().
    """
    _validate(bond)
    dates = _coupon_dates_back_to(bond, settlement)
    return max(item for item in dates if item <= settlement)
