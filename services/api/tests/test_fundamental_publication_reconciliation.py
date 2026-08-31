from __future__ import annotations

import datetime as dt

from services.api.app.services.fundamental_publication_reconciliation import (
    FilingMetricEvidence,
    _with_reconciliation_history,
    exact_metric_key,
    select_exact_publication_evidence,
)


def _evidence(*, doc_id: int, metric: str, value: float, date: dt.date, kind: str = "RFA") -> FilingMetricEvidence:
    return FilingMetricEvidence(
        source_document_id=doc_id,
        symbol="IAM",
        fiscal_year=2024,
        metric_name=metric,
        metric_value=value,
        publication_date=date,
        document_kind=kind,
    )


def test_cgnc_alias_and_exact_value_can_reconcile() -> None:
    evidence = [_evidence(doc_id=7, metric="Capitaux_propres", value=1000.0, date=dt.date(2025, 3, 1))]
    selected = select_exact_publication_evidence(
        symbol="iam",
        fiscal_year=2024,
        metric_name="Total_Equity",
        metric_value=1000.0,
        evidence=evidence,
    )
    assert selected is not None
    assert selected.source_document_id == 7


def test_numeric_mismatch_is_never_tolerance_matched() -> None:
    evidence = [_evidence(doc_id=7, metric="Capitaux_propres", value=1000.0001, date=dt.date(2025, 3, 1))]
    assert select_exact_publication_evidence(
        symbol="IAM",
        fiscal_year=2024,
        metric_name="Total_Equity",
        metric_value=1000.0,
        evidence=evidence,
    ) is None


def test_earliest_exact_official_disclosure_is_the_availability_event() -> None:
    evidence = [
        _evidence(doc_id=9, metric="Capitaux_propres", value=1000.0, date=dt.date(2025, 4, 30), kind="RFA"),
        _evidence(doc_id=8, metric="Capitaux_propres", value=1000.0, date=dt.date(2025, 3, 15), kind="CP"),
    ]
    selected = select_exact_publication_evidence(
        symbol="IAM",
        fiscal_year=2024,
        metric_name="Total_Equity",
        metric_value=1000.0,
        evidence=evidence,
    )
    assert selected is not None
    assert selected.source_document_id == 8


def test_metric_name_mismatch_is_never_value_only_matched() -> None:
    assert exact_metric_key(symbol="IAM", fiscal_year=2024, metric_name="Revenue", metric_value=1000.0) != exact_metric_key(
        symbol="IAM", fiscal_year=2024, metric_name="Total_Equity", metric_value=1000.0
    )


def test_reconciliation_history_preserves_prior_rollback_lineage() -> None:
    previous = {"changed_rows": [{"annual_metric_id": 1, "prior_as_of_date": None}]}
    current = {"changed_rows": [{"annual_metric_id": 2, "prior_as_of_date": "2025-01-01"}]}

    result = _with_reconciliation_history(
        {"unrelated": "preserved", "bvc_exact_publication_reconciliation": previous},
        current,
    )

    assert result["unrelated"] == "preserved"
    assert result["bvc_exact_publication_reconciliation"] == current
    assert result["bvc_exact_publication_reconciliation_history"] == [previous, current]
