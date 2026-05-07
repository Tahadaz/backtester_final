from __future__ import annotations

from core.quant_core.wfo.test_period import assess_test_period_length, partition_test_period


def test_partition_test_period_splits_after_last_oos_index() -> None:
    partition = partition_test_period(list(range(10)), 7)
    assert list(partition.wfo_data) == list(range(7))
    assert list(partition.test_data) == [7, 8, 9]


def test_assess_test_period_length_warns_for_short_period() -> None:
    assessment = assess_test_period_length(90)
    assert assessment.has_test_period
    assert assessment.is_short
    assert assessment.warning is not None


def test_assess_test_period_length_handles_empty_period() -> None:
    assessment = assess_test_period_length(0)
    assert not assessment.has_test_period
    assert assessment.warning is not None

