"""Risk-measure acceptance harness. Make these green by hand."""

from datetime import date

import pytest

from core.quant_core.fixed_income import (
    BondDefinition,
    risk_measures,
    dirty_price,
    clean_price,
)

SETTLE = date(2026, 7, 15)


def make_bond(coupon, freq, years, day_count="30E/360"):
    return BondDefinition(100.0, "USD", coupon, freq, date(2026 + years, 7, 15), day_count)


def test_zero_coupon_duration_identity():
    z = make_bond(0.0, 1, 10)
    rm = risk_measures(z, SETTLE, 0.05)
    assert rm.macaulay_duration == pytest.approx(10.0, abs=1e-4)   # MacDur of a zero = maturity
    assert rm.modified_duration == pytest.approx(10.0 / 1.05, abs=1e-4)  # 9.5238
    assert rm.convexity > 0


def test_dv01_matches_central_difference():
    b = make_bond(0.06, 1, 5)
    ytm = 0.04
    rm = risk_measures(b, SETTLE, ytm)
    numeric = (dirty_price(b, SETTLE, ytm - 1e-4) - dirty_price(b, SETTLE, ytm + 1e-4)) / 2.0
    assert rm.dv01_per_100 == pytest.approx(numeric, abs=1e-6)
    assert rm.dv01_per_100 > 0


def test_price_decreasing_in_yield():
    b = make_bond(0.05, 1, 5)
    assert clean_price(b, SETTLE, 0.04) > clean_price(b, SETTLE, 0.05) > clean_price(b, SETTLE, 0.06)


def test_convexity_positive_all_vectors():
    for coupon, freq, years, ytm in [(0.05, 1, 5, 0.05), (0.08, 2, 10, 0.06), (0.0, 1, 10, 0.05)]:
        assert risk_measures(make_bond(coupon, freq, years), SETTLE, ytm).convexity > 0
