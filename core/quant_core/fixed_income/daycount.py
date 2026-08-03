"""Day-count conventions.

You implement these. Getting them wrong loses money mechanically on a real
desk, so this is the first thing to nail by hand.
"""

from __future__ import annotations

from datetime import date


def year_fraction(start: date, end: date, convention: str) -> float:
    """Year fraction between two dates under a NON-period-relative convention.

    Supported here: "30E/360", "ACT/365F".

    "ACT/ACT-ICMA" is period-relative (it needs the surrounding coupon period),
    so this function must raise ValueError for it and force callers to use
    accrual_fraction_icma() instead.

    30E/360 (Eurobond basis):
        d1 = min(d1, 30); d2 = min(d2, 30)
        ((y2 - y1) * 360 + (m2 - m1) * 30 + (d2 - d1)) / 360
    ACT/365F:
        actual calendar days between start and end, divided by 365.
    """
    if end < start:
        raise ValueError("end must be on or after start")
    if convention == "30E/360":
        d1 = min(start.day, 30)
        d2 = min(end.day, 30)
        return ((end.year - start.year) * 360 + (end.month - start.month) * 30 + d2 - d1) / 360.0
    if convention == "ACT/365F":
        return (end - start).days / 365.0
    if convention == "ACT/ACT-ICMA":
        raise ValueError("ACT/ACT-ICMA requires the surrounding coupon period")
    raise ValueError(f"unsupported day-count convention: {convention}")


def accrual_fraction_icma(
    start: date,
    end: date,
    period_start: date,
    period_end: date,
    frequency: int,
) -> float:
    """ICMA ACT/ACT accrual fraction within one coupon period.

        actual_days(start, end) / (frequency * actual_days(period_start, period_end))

    This is the Eurobond standard and the reason a bond can show different
    accrued under ICMA vs 30E/360 on the same date — write up that difference
    when you implement it.
    """
    if frequency not in {1, 2}:
        raise ValueError("frequency must be 1 or 2")
    if not (period_start <= start <= end <= period_end):
        raise ValueError("accrual dates must lie inside the coupon period")
    period_days = (period_end - period_start).days
    if period_days <= 0:
        raise ValueError("coupon period must have positive length")
    return (end - start).days / (frequency * period_days)
