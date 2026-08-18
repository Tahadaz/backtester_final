"""Day-count acceptance harness. Make these green by hand."""

from datetime import date

import pytest

from core.quant_core.fixed_income import year_fraction, accrual_fraction_icma


def test_30e360_half_year():
    # 2026-07-15 -> 2027-01-15 : 6*30 / 360 = 0.5
    assert year_fraction(date(2026, 7, 15), date(2027, 1, 15), "30E/360") == pytest.approx(0.5, abs=1e-9)


def test_30e360_full_year():
    assert year_fraction(date(2026, 7, 15), date(2027, 7, 15), "30E/360") == pytest.approx(1.0, abs=1e-9)


def test_30e360_clamps_day_31():
    # 2026-01-31 -> 2026-02-28 under 30E/360: d1->30, d2 stays 28 => 28/360
    assert year_fraction(date(2026, 1, 31), date(2026, 2, 28), "30E/360") == pytest.approx(28 / 360, abs=1e-9)


def test_act365f():
    assert year_fraction(date(2026, 1, 1), date(2026, 12, 31), "ACT/365F") == pytest.approx(364 / 365, abs=1e-9)


def test_icma_fraction_in_unit_interval():
    f = accrual_fraction_icma(
        date(2026, 7, 15), date(2027, 1, 15), date(2026, 7, 15), date(2027, 7, 15), 1
    )
    assert 0.0 < f < 1.0


def test_icma_full_period_is_one_over_frequency():
    # start=period_start, end=period_end, annual -> full period = 1/frequency
    f = accrual_fraction_icma(
        date(2026, 7, 15), date(2027, 7, 15), date(2026, 7, 15), date(2027, 7, 15), 1
    )
    assert f == pytest.approx(1.0, abs=1e-9)


def test_year_fraction_rejects_icma():
    with pytest.raises(ValueError):
        year_fraction(date(2026, 7, 15), date(2027, 7, 15), "ACT/ACT-ICMA")
