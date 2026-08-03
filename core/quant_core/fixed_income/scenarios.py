"""Yield-shock scenarios and unchanged-yield carry.

Exact repricing vs the duration and duration+convexity approximations, per
shock — this is where you SEE convexity earn its keep on large moves.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .cashflows import BondDefinition, generate_schedule
from .pricing import clean_price, dirty_price
from .riskmeasures import risk_measures


@dataclass(frozen=True)
class ShockResult:
    shock_bp: float
    exact_clean: float
    exact_pnl_per_100: float               # vs base dirty price, exact repricing
    approx_pnl_duration: float             # -ModDur * P * dy
    approx_pnl_duration_convexity: float   # + 0.5 * C * P * dy^2
    approx_error: float                    # exact - duration+convexity


def shock_table(
    bond: BondDefinition,
    settlement: date,
    base_ytm: float,
    shocks_bp: list[float],
) -> list[ShockResult]:
    """One ShockResult per shock. Shock 0 must produce exactly zero P&L.

    P&L is measured on the dirty price (a parallel yield move revalues the whole
    dirty PV); report exact repricing alongside the two approximations so the
    approximation error is visible per shock.
    """
    base_dirty = dirty_price(bond, settlement, base_ytm)
    risk = risk_measures(bond, settlement, base_ytm)
    output: list[ShockResult] = []
    for shock in shocks_bp:
        change = float(shock) / 10_000.0
        exact_clean = clean_price(bond, settlement, base_ytm + change)
        exact_pnl = dirty_price(bond, settlement, base_ytm + change) - base_dirty
        duration_pnl = -risk.modified_duration * base_dirty * change
        duration_convexity = duration_pnl + 0.5 * risk.convexity * base_dirty * change ** 2
        if change == 0:
            exact_pnl = duration_pnl = duration_convexity = 0.0
        output.append(ShockResult(float(shock), exact_clean, exact_pnl, duration_pnl, duration_convexity, exact_pnl - duration_convexity))
    return output


def carry(
    bond: BondDefinition,
    settlement: date,
    base_ytm: float,
    horizon_days: int,
) -> dict:
    """Unchanged-yield carry over horizon_days. Returns keys:

        coupon_income   -- coupons received within the horizon, per 100
        pull_to_par     -- (dirty price at horizon, same yield) - starting dirty
        total_per_100   -- coupon_income + pull_to_par

    Excludes roll-down (needs a curve; later phase). Zero horizon -> zero carry.
    """
    if horizon_days < 0:
        raise ValueError("horizon_days cannot be negative")
    if horizon_days == 0:
        return {"coupon_income": 0.0, "pull_to_par": 0.0, "total_per_100": 0.0}
    horizon = settlement + timedelta(days=horizon_days)
    if horizon >= bond.maturity_date:
        raise ValueError("carry horizon must end before maturity")
    start_price = dirty_price(bond, settlement, base_ytm)
    end_price = dirty_price(bond, horizon, base_ytm)
    coupon_income = 0.0
    for flow in generate_schedule(bond, settlement):
        if flow.date > horizon:
            continue
        coupon_income += flow.amount - (bond.redemption if flow.kind == "redemption" else 0.0)
    pull_to_par = end_price - start_price
    return {"coupon_income": coupon_income, "pull_to_par": pull_to_par, "total_per_100": coupon_income + pull_to_par}
