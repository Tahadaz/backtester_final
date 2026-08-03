"""Pricing: accrued, clean/dirty price, YTM solver, current yield.

The heart of the build. Discounting is periodic compounding at the coupon
frequency f: a flow at time t periods from settlement has DF = (1 + y/f)^(-t).
The first flow's t is the fractional period from settlement to the next coupon
(day-count-consistent); each subsequent flow adds a whole period.
"""

from __future__ import annotations

from datetime import date

from .cashflows import BondDefinition, _add_months, _validate, generate_schedule, previous_coupon_date
from .daycount import accrual_fraction_icma, year_fraction


def _period_fraction(bond: BondDefinition, settlement: date, period_start: date, period_end: date) -> float:
    if settlement == period_end:
        return 0.0
    if bond.day_count == "ACT/ACT-ICMA":
        return accrual_fraction_icma(period_start, settlement, period_start, period_end, bond.coupon_frequency) * bond.coupon_frequency
    return min(1.0, max(0.0, year_fraction(period_start, settlement, bond.day_count) * bond.coupon_frequency))


def _cashflow_periods(bond: BondDefinition, settlement: date) -> list[tuple[float, float]]:
    flows = generate_schedule(bond, settlement)
    if not flows:
        return []
    previous = previous_coupon_date(bond, settlement)
    next_coupon = _add_months(previous, 12 // bond.coupon_frequency)
    if next_coupon <= settlement:
        next_coupon = flows[0].date
    accrued_period = _period_fraction(bond, settlement, previous, next_coupon)
    first_t = 1.0 - accrued_period
    if bond.coupon_rate == 0:
        months_after_next = (bond.maturity_date.year - next_coupon.year) * 12 + bond.maturity_date.month - next_coupon.month
        periods = first_t + months_after_next / (12 // bond.coupon_frequency)
        return [(flows[0].amount, periods)]
    return [(flow.amount, first_t + index) for index, flow in enumerate(flows)]


def _price_and_derivative(bond: BondDefinition, settlement: date, ytm: float) -> tuple[float, float]:
    frequency = bond.coupon_frequency
    base = 1.0 + ytm / frequency
    if base <= 0:
        raise ValueError("ytm is below the periodic-compounding lower bound")
    price = 0.0
    derivative = 0.0
    for amount, periods in _cashflow_periods(bond, settlement):
        price += amount * base ** (-periods)
        derivative += amount * (-periods / frequency) * base ** (-periods - 1.0)
    return price, derivative


def accrued_interest(bond: BondDefinition, settlement: date) -> float:
    """Accrued per 100 = 100 * coupon_rate / f * accrual_fraction(prev_coupon -> settlement).

    Use the bond's own day-count convention (period-aware ICMA where applicable).
    Zero on a coupon date.
    """
    _validate(bond, settlement)
    previous = previous_coupon_date(bond, settlement)
    if previous == settlement or bond.coupon_rate == 0:
        return 0.0
    next_coupon = _add_months(previous, 12 // bond.coupon_frequency)
    fraction = _period_fraction(bond, settlement, previous, next_coupon)
    return 100.0 * bond.coupon_rate / bond.coupon_frequency * fraction


def dirty_price(bond: BondDefinition, settlement: date, ytm: float) -> float:
    """Present value per 100 of all flows after settlement at flat yield ytm."""
    _validate(bond, settlement)
    return _price_and_derivative(bond, settlement, ytm)[0]


def clean_price(bond: BondDefinition, settlement: date, ytm: float) -> float:
    """clean = dirty - accrued."""
    return dirty_price(bond, settlement, ytm) - accrued_interest(bond, settlement)


def yield_to_maturity(
    bond: BondDefinition,
    settlement: date,
    clean: float | None = None,
    dirty: float | None = None,
) -> float:
    """Solve for the flat yield that reprices the bond to the given quote.

    Newton-Raphson with analytic derivative; fall back to bisection on
    [-0.99, 10.0] if Newton fails to converge within 50 iterations. Converged
    when |P(y) - P_target| < 1e-10 in dirty-price space. Raise ValueError with a
    clear message if the target is not bracketed. Exactly one of clean/dirty
    must be supplied.
    """
    _validate(bond, settlement)
    if (clean is None) == (dirty is None):
        raise ValueError("exactly one of clean or dirty must be supplied")
    quote = clean if clean is not None else dirty
    if quote is None or quote <= 0:
        raise ValueError("price quote must be positive")
    target = float(quote) + accrued_interest(bond, settlement) if clean is not None else float(quote)
    guess = max(-0.5, min(1.0, bond.coupon_rate or 0.05))
    for _ in range(50):
        price, derivative = _price_and_derivative(bond, settlement, guess)
        error = price - target
        if abs(error) < 1e-10:
            return guess
        if derivative == 0:
            break
        candidate = guess - error / derivative
        if not (-0.99 < candidate < 10.0):
            break
        guess = candidate
    lower, upper = -0.99, 10.0
    f_lower = dirty_price(bond, settlement, lower) - target
    f_upper = dirty_price(bond, settlement, upper) - target
    if f_lower * f_upper > 0:
        raise ValueError("target price is not bracketed by yields in [-0.99, 10.0]")
    for _ in range(250):
        middle = (lower + upper) / 2.0
        error = dirty_price(bond, settlement, middle) - target
        if abs(error) < 1e-10:
            return middle
        if f_lower * error > 0:
            lower, f_lower = middle, error
        else:
            upper = middle
    raise ValueError("yield solver did not converge")


def current_yield(bond: BondDefinition, clean: float) -> float:
    """Annual coupon per 100 divided by clean price."""
    if clean <= 0:
        raise ValueError("clean price must be positive")
    if bond.coupon_rate < 0:
        raise ValueError("coupon_rate cannot be negative")
    return 100.0 * bond.coupon_rate / clean
