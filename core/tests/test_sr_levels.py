from __future__ import annotations

from core.quant_core.signal_engine.sr_levels import (
    compute_pivot_family_levels,
    split_support_resistance_lines,
)


def test_classic_pivot_exposes_p_s1_s3_r1_r3() -> None:
    levels = compute_pivot_family_levels(
        "pivot_points",
        prev_high=110.0,
        prev_low=100.0,
        prev_close=105.0,
        prev_open=104.0,
    )

    assert levels == {
        "S3": 90.0,
        "S2": 95.0,
        "S1": 100.0,
        "P": 105.0,
        "R1": 110.0,
        "R2": 115.0,
        "R3": 120.0,
    }


def test_fibonacci_camarilla_woodie_and_demark_line_availability() -> None:
    fib = compute_pivot_family_levels(
        "fibonacci_pivot",
        prev_high=110.0,
        prev_low=100.0,
        prev_close=105.0,
    )
    camarilla = compute_pivot_family_levels(
        "camarilla",
        prev_high=110.0,
        prev_low=100.0,
        prev_close=105.0,
    )
    woodie = compute_pivot_family_levels(
        "woodie",
        prev_high=110.0,
        prev_low=100.0,
        prev_close=105.0,
    )
    demark = compute_pivot_family_levels(
        "dm",
        prev_high=110.0,
        prev_low=100.0,
        prev_close=105.0,
        prev_open=104.0,
    )

    assert fib["P"] == 105.0
    assert fib["S1"] == 101.18
    assert fib["R2"] == 111.18
    assert camarilla["S3"] == 102.25
    assert camarilla["R3"] == 107.75
    assert woodie["S3"] == 90.0
    assert woodie["R3"] == 120.0
    assert demark == {"S1": 102.5, "P": 106.25, "R1": 112.5}


def test_split_support_resistance_lines_treats_pivot_as_contextual() -> None:
    support, resistance = split_support_resistance_lines(
        {"S1": 99.0, "P": 100.0, "R1": 101.0},
        100.5,
    )

    assert support == {"S1": 99.0, "P": 100.0}
    assert resistance == {"R1": 101.0}
