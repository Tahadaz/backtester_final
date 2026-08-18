"""Pricing acceptance harness — textbook vectors (Fabozzi/Steiner) + round-trips.

Settlement is on a coupon anniversary (2026-07-15) so accrued = 0 and clean =
dirty for the vector cases. Make these green by hand.
"""

from datetime import date

import pytest

from core.quant_core.fixed_income import (
    BondDefinition,
    clean_price,
    dirty_price,
    accrued_interest,
    yield_to_maturity,
    current_yield,
)

SETTLE = date(2026, 7, 15)


def make_bond(coupon, freq, years, day_count="30E/360"):
    return BondDefinition(
        face_value=100.0,
        currency="USD",
        coupon_rate=coupon,
        coupon_frequency=freq,
        maturity_date=date(2026 + years, 7, 15),
        day_count=day_count,
    )


# (coupon, freq, years, ytm, expected_clean)
VECTORS = [
    (0.05, 1, 5, 0.05, 100.0000),   # par identity
    (0.06, 1, 5, 0.04, 108.9036),   # premium
    (0.04, 1, 5, 0.06, 91.5753),    # discount
    (0.08, 2, 10, 0.06, 114.8775),  # semiannual BEY
]


@pytest.mark.parametrize("coupon,freq,years,ytm,expected", VECTORS)
def test_clean_price_vectors(coupon, freq, years, ytm, expected):
    b = make_bond(coupon, freq, years)
    assert clean_price(b, SETTLE, ytm) == pytest.approx(expected, abs=1e-4)


def test_zero_coupon_price():
    z = make_bond(0.0, 1, 10)
    assert clean_price(z, SETTLE, 0.05) == pytest.approx(61.3913, abs=1e-4)


def test_accrued_zero_on_coupon_date():
    b = make_bond(0.06, 1, 5)
    assert accrued_interest(b, SETTLE) == pytest.approx(0.0, abs=1e-9)


def test_accrued_half_period_30e360():
    # 6% annual, exactly half a 30E/360 period elapsed -> accrued 3.00 per 100
    b = BondDefinition(100.0, "USD", 0.06, 1, date(2031, 7, 15), "30E/360")
    assert accrued_interest(b, date(2027, 1, 15)) == pytest.approx(3.0, abs=1e-4)


def test_dirty_equals_clean_plus_accrued():
    b = BondDefinition(100.0, "USD", 0.06, 1, date(2031, 7, 15), "30E/360")
    s = date(2027, 1, 15)
    assert dirty_price(b, s, 0.05) == pytest.approx(
        clean_price(b, s, 0.05) + accrued_interest(b, s), abs=1e-9
    )


@pytest.mark.parametrize("coupon,freq,years,ytm,_expected", VECTORS)
def test_price_yield_round_trip(coupon, freq, years, ytm, _expected):
    b = make_bond(coupon, freq, years)
    p = clean_price(b, SETTLE, ytm)
    assert yield_to_maturity(b, SETTLE, clean=p) == pytest.approx(ytm, abs=1e-8)


def test_round_trip_near_maturity():
    b = BondDefinition(100.0, "USD", 0.05, 2, date(2026, 10, 15), "30E/360")
    p = clean_price(b, SETTLE, 0.045)
    assert yield_to_maturity(b, SETTLE, clean=p) == pytest.approx(0.045, abs=1e-8)


def test_current_yield():
    b = make_bond(0.06, 1, 5)
    assert current_yield(b, 120.0) == pytest.approx(0.05, abs=1e-9)


def test_invalid_settlement_after_maturity_raises():
    b = make_bond(0.05, 1, 5)
    with pytest.raises(ValueError):
        clean_price(b, date(2032, 1, 1), 0.05)
