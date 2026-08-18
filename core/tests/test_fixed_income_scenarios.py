"""Scenario / carry acceptance harness. Make these green by hand."""

from datetime import date

import pytest

from core.quant_core.fixed_income import (
    BondDefinition,
    shock_table,
    carry,
)

SETTLE = date(2026, 7, 15)


def make_bond(coupon, freq, years, day_count="30E/360"):
    return BondDefinition(100.0, "USD", coupon, freq, date(2026 + years, 7, 15), day_count)


def test_zero_shock_zero_pnl():
    rows = shock_table(make_bond(0.06, 1, 5), SETTLE, 0.04, [0.0])
    assert rows[0].exact_pnl_per_100 == pytest.approx(0.0, abs=1e-9)


def test_shock_table_length_matches_request():
    shocks = [-100, -50, -10, 0, 10, 50, 100]
    rows = shock_table(make_bond(0.06, 1, 5), SETTLE, 0.04, shocks)
    assert len(rows) == len(shocks)


def test_convexity_term_reduces_error_on_large_shock():
    b = make_bond(0.06, 1, 5)
    ytm = 0.04
    row = {r.shock_bp: r for r in shock_table(b, SETTLE, ytm, [100.0])}[100.0]
    err_dur = abs(row.exact_pnl_per_100 - row.approx_pnl_duration)
    err_dur_cvx = abs(row.exact_pnl_per_100 - row.approx_pnl_duration_convexity)
    assert err_dur_cvx < err_dur


def test_carry_components_sum_to_total():
    c = carry(make_bond(0.06, 1, 5), SETTLE, 0.04, 180)
    assert c["coupon_income"] + c["pull_to_par"] == pytest.approx(c["total_per_100"], abs=1e-9)


def test_zero_horizon_zero_carry():
    c = carry(make_bond(0.06, 1, 5), SETTLE, 0.04, 0)
    assert c["total_per_100"] == pytest.approx(0.0, abs=1e-9)
