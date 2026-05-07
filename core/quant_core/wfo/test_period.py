# core/quant_core/wfo/test_period.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class TestPeriodPartition:
    wfo_data: Sequence[T]
    test_data: Sequence[T]
    test_start_index: int


@dataclass(frozen=True)
class TestPeriodAssessment:
    has_test_period: bool
    is_short: bool
    warning: str | None


def partition_test_period(data: Sequence[T], last_oos_end_index: int) -> TestPeriodPartition:
    clamped = max(0, min(len(data), last_oos_end_index))
    return TestPeriodPartition(
        wfo_data=data[:clamped],
        test_data=data[clamped:],
        test_start_index=clamped,
    )


def assess_test_period_length(n_bars: int, *, min_test_bars: int = 126) -> TestPeriodAssessment:
    if n_bars <= 0:
        return TestPeriodAssessment(
            has_test_period=False,
            is_short=False,
            warning="No data available after the WFO period.",
        )
    if n_bars < min_test_bars:
        years = n_bars / 252
        return TestPeriodAssessment(
            has_test_period=True,
            is_short=True,
            warning=(
                f"Test period is only {n_bars} bars (~{years:.1f} years). "
                "Results are displayed but have low statistical power."
            ),
        )
    return TestPeriodAssessment(has_test_period=True, is_short=False, warning=None)

