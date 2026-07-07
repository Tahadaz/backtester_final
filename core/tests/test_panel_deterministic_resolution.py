"""Tests for deterministic duplicate-metric resolution in cross_section/panel.py.

Covers the 2026-07-06 forensic-audit finding that `_latest_metric_map`'s
tie-break for competing metric rows (same availability_date, same
statement_year, different value/source) previously depended on input list
order rather than an explicit, reproducible rule.
"""
import datetime as dt
import random

from core.quant_core.fundamentals.cross_section.panel import _latest_metric_map


def _row(*, metric_name, value, availability_date, statement_year=2024, source_document_id=None, kind="publication_date"):
    return {
        "symbol": "TEST",
        "company_name": "Test Co",
        "statement_year": statement_year,
        "metric_name": metric_name,
        "metric_value": value,
        "availability_date": availability_date,
        "availability_kind": kind,
        "source_document_id": source_document_id,
    }


AS_OF = dt.date(2025, 1, 1)


def test_prefers_row_with_linked_source_document_on_exact_date_tie():
    same_date = dt.date(2024, 6, 1)
    rows = [
        _row(metric_name="Total_Equity", value=999.0, availability_date=same_date, source_document_id=None),
        _row(metric_name="Total_Equity", value=123.0, availability_date=same_date, source_document_id=42),
    ]
    metrics, _, _, _ = _latest_metric_map(rows, AS_OF)
    assert metrics["Total_Equity"] == 123.0


def test_resolution_is_independent_of_input_order():
    same_date = dt.date(2024, 6, 1)
    base_rows = [
        _row(metric_name="EBITDA", value=100.0, availability_date=same_date, source_document_id=None),
        _row(metric_name="EBITDA", value=200.0, availability_date=same_date, source_document_id=5),
        _row(metric_name="EBITDA", value=300.0, availability_date=same_date, source_document_id=9),
    ]
    results = set()
    rng = random.Random(0)
    for _ in range(20):
        shuffled = base_rows[:]
        rng.shuffle(shuffled)
        metrics, _, _, _ = _latest_metric_map(shuffled, AS_OF)
        results.add(metrics["EBITDA"])
    # Regardless of shuffle order, the row with the highest source_document_id wins.
    assert results == {300.0}


def test_later_availability_date_wins_over_source_document_presence():
    rows = [
        _row(metric_name="Cash", value=111.0, availability_date=dt.date(2024, 3, 1), source_document_id=7),
        _row(metric_name="Cash", value=222.0, availability_date=dt.date(2024, 6, 1), source_document_id=None),
    ]
    metrics, _, _, _ = _latest_metric_map(rows, AS_OF)
    assert metrics["Cash"] == 222.0


def test_does_not_leak_future_availability_rows():
    rows = [
        _row(metric_name="Revenue", value=1.0, availability_date=dt.date(2024, 1, 1)),
        _row(metric_name="Revenue", value=2.0, availability_date=dt.date(2026, 1, 1)),
    ]
    metrics, _, _, _ = _latest_metric_map(rows, AS_OF)
    assert metrics["Revenue"] == 1.0
