"""Tests for the _series / _ratio_series outlier-rejection and row-selection logic."""
from __future__ import annotations

import datetime as dt

import pytest

from quant_core.fundamentals.domain import AnnualMetricRow
from quant_core.fundamentals.projection import _ratio_series, _series


def _row(
    symbol: str,
    year: int,
    metric: str,
    value: float | None,
    *,
    is_proxy: bool = False,
    as_of_date: dt.date | None = None,
    source_doc_id: int | None = None,
) -> AnnualMetricRow:
    return AnnualMetricRow(
        symbol=symbol,
        company_name=symbol,
        statement_year=year,
        metric_name=metric,
        metric_value=value,
        is_proxy=is_proxy,
        as_of_date=as_of_date,
        source_document_id=source_doc_id,
    )


# ---------------------------------------------------------------------------
# Core outlier-rejection test (the Managem D&A case from codex_plan_phase2.5b)
# ---------------------------------------------------------------------------

def test_series_rejects_unit_outlier_keeps_correct_value() -> None:
    """Year 2023: [1.397e9, 370.32, None, 1.397e9×5] → picks 1.397e9."""
    rows = [
        _row("MNG", 2023, "Depreciation_Amortization", 1.397e9),
        _row("MNG", 2023, "Depreciation_Amortization", 370.32),        # mis-scaled outlier
        _row("MNG", 2023, "Depreciation_Amortization", None),          # null — must be dropped
        _row("MNG", 2023, "Depreciation_Amortization", 1.397e9, source_doc_id=2),
        _row("MNG", 2023, "Depreciation_Amortization", 1.397e9, source_doc_id=3),
        _row("MNG", 2023, "Depreciation_Amortization", 1.397e9, source_doc_id=4),
        _row("MNG", 2023, "Depreciation_Amortization", 1.397e9, source_doc_id=5),
        _row("MNG", 2023, "Depreciation_Amortization", 1.397e9, source_doc_id=6),
    ]
    result = _series(rows, ("Depreciation_Amortization", "DandA"))

    assert len(result) == 1
    year, value = result[0]
    assert year == 2023
    assert value == pytest.approx(1.397e9)


def test_series_none_only_year_returns_empty() -> None:
    rows = [_row("AAA", 2023, "Revenue", None)]
    assert _series(rows, ("Revenue",)) == []


def test_series_single_correct_value_unchanged() -> None:
    rows = [_row("AAA", 2022, "Revenue", 1_000_000.0), _row("AAA", 2023, "Revenue", 1_100_000.0)]
    result = _series(rows, ("Revenue",))
    assert len(result) == 2
    assert result[0] == (2022, pytest.approx(1_000_000.0))
    assert result[1] == (2023, pytest.approx(1_100_000.0))


def test_series_prefers_non_proxy_over_proxy() -> None:
    rows = [
        _row("AAA", 2023, "EBIT", 500.0, is_proxy=True),
        _row("AAA", 2023, "EBIT", 480.0, is_proxy=False),
    ]
    result = _series(rows, ("EBIT",))
    assert len(result) == 1
    assert result[0][1] == pytest.approx(480.0)


def test_series_prefers_most_recent_source_doc_among_identical_values() -> None:
    rows = [
        _row("AAA", 2023, "Revenue", 1_000.0, source_doc_id=10),
        _row("AAA", 2023, "Revenue", 1_000.0, source_doc_id=7),
        _row("AAA", 2023, "Revenue", 1_000.0, source_doc_id=3),
    ]
    # All same value and same proxy-status — highest source_doc_id wins
    result = _series(rows, ("Revenue",))
    assert len(result) == 1
    assert result[0][1] == pytest.approx(1_000.0)


def test_series_multi_year_dedup_per_year() -> None:
    """Five rows for 2023, two for 2024 — one result per year."""
    rows = [
        _row("AAA", 2023, "Revenue", 1_000.0, source_doc_id=1),
        _row("AAA", 2023, "Revenue", 1_000.0, source_doc_id=2),
        _row("AAA", 2023, "Revenue", 1_000.0, source_doc_id=3),
        _row("AAA", 2023, "Revenue", 1_000.0, source_doc_id=4),
        _row("AAA", 2023, "Revenue", 1_000.0, source_doc_id=5),
        _row("AAA", 2024, "Revenue", 1_100.0, source_doc_id=1),
        _row("AAA", 2024, "Revenue", 1_100.0, source_doc_id=2),
    ]
    result = _series(rows, ("Revenue",))
    assert len(result) == 2
    assert result[0][1] == pytest.approx(1_000.0)
    assert result[1][1] == pytest.approx(1_100.0)


# ---------------------------------------------------------------------------
# ratio_series — D&A / Revenue ≈ 0.12 despite polluted D&A rows
# ---------------------------------------------------------------------------

def test_ratio_series_danda_over_revenue_robust_to_outlier() -> None:
    """D&A/Revenue must resolve to ~0.12, not ~0, even with a mis-scaled twin."""
    revenue = 11_670_000_000.0
    danda_correct = 1_397_000_000.0

    rows = [
        _row("MNG", 2023, "Revenue", revenue),
        _row("MNG", 2023, "Depreciation_Amortization", danda_correct),
        _row("MNG", 2023, "Depreciation_Amortization", 370.32),   # outlier
        _row("MNG", 2023, "Depreciation_Amortization", None),     # null
        _row("MNG", 2023, "Depreciation_Amortization", danda_correct, source_doc_id=2),
        _row("MNG", 2023, "Depreciation_Amortization", danda_correct, source_doc_id=3),
    ]

    result = _ratio_series(rows, ("Depreciation_Amortization", "DandA"), ("Revenue",))

    assert len(result) == 1
    year, ratio = result[0]
    assert year == 2023
    assert ratio == pytest.approx(danda_correct / revenue, rel=0.01)
    # Must be ~0.12, not the ~0 produced by the mis-scaled 370.32 value
    assert ratio > 0.10


def test_ratio_series_aliases_match_any_name() -> None:
    """Revenue can match via either CGNC alias."""
    rows = [
        _row("AAA", 2023, "Chiffre_daffaires", 1_000.0),  # CGNC alias for Revenue
        _row("AAA", 2023, "EBIT", 150.0),
    ]
    result = _ratio_series(rows, ("EBIT",), ("Revenue", "Chiffre_daffaires"))
    assert len(result) == 1
    assert result[0][1] == pytest.approx(0.15)


def test_ratio_series_zero_denominator_skipped() -> None:
    rows = [
        _row("AAA", 2023, "Revenue", 0.0),
        _row("AAA", 2023, "EBIT", 100.0),
    ]
    result = _ratio_series(rows, ("EBIT",), ("Revenue",))
    assert result == []
