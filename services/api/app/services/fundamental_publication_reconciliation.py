"""Exact, fail-closed reconciliation of StockAnalysis values to BVC filings.

A Bourse publication date is attached only when issuer, fiscal year,
canonical metric, and stored numeric value all agree with a non-proxy annual
metric extracted from an official document.  There is no fuzzy title match,
numeric tolerance, inferred lag, or current-date fallback.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from core.quant_core.fundamentals.cgnc_mapping import resolve_metric_name
from core.quant_core.fundamentals.cross_section.quarterly_pit_audit import (
    OFFICIAL_BVC_PUBLICATION_HOSTS,
    is_trustworthy_publication_date,
)
from services.api.app import models


RECONCILIATION_METHOD_VERSION = "stockanalysis_bvc_exact_metric_v1_2026_08_30"


@dataclass(frozen=True)
class FilingMetricEvidence:
    source_document_id: int
    symbol: str
    fiscal_year: int
    metric_name: str
    metric_value: float
    publication_date: dt.date
    document_kind: str | None = None


def _decimal_value(value: object) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed.normalize() if parsed.is_finite() else None


def exact_metric_key(*, symbol: str, fiscal_year: int, metric_name: str, metric_value: object) -> tuple[str, int, str, Decimal] | None:
    value = _decimal_value(metric_value)
    if value is None:
        return None
    return (str(symbol).strip().upper(), int(fiscal_year), resolve_metric_name(str(metric_name)), value)


def select_exact_publication_evidence(
    *,
    symbol: str,
    fiscal_year: int,
    metric_name: str,
    metric_value: object,
    evidence: Iterable[FilingMetricEvidence],
) -> FilingMetricEvidence | None:
    target = exact_metric_key(
        symbol=symbol,
        fiscal_year=fiscal_year,
        metric_name=metric_name,
        metric_value=metric_value,
    )
    if target is None:
        return None
    matches = [
        row
        for row in evidence
        if exact_metric_key(
            symbol=row.symbol,
            fiscal_year=row.fiscal_year,
            metric_name=row.metric_name,
            metric_value=row.metric_value,
        )
        == target
    ]
    if not matches:
        return None
    kind_rank = {"RFA": 0, "CP": 1}
    return min(
        matches,
        key=lambda row: (
            row.publication_date,
            kind_rank.get(str(row.document_kind or "").upper(), 2),
            row.source_document_id,
        ),
    )


def _official_trustworthy_document(document: models.FundamentalSourceDocument) -> bool:
    host = (urlparse(document.source_url or "").hostname or "").lower()
    return host in OFFICIAL_BVC_PUBLICATION_HOSTS and is_trustworthy_publication_date(
        publication_date=document.publication_date,
        created_at=document.created_at,
        document_title=document.document_title,
        source_url=document.source_url,
        raw_json=document.raw_json,
    )


def _with_reconciliation_history(
    summary_json: object,
    reconciliation_record: dict[str, object],
) -> dict[str, object]:
    """Append audit lineage without discarding a reconciliation from an earlier run."""

    summary = dict(summary_json) if isinstance(summary_json, dict) else {}
    previous = summary.get("bvc_exact_publication_reconciliation")
    raw_history = summary.get("bvc_exact_publication_reconciliation_history")
    history = list(raw_history) if isinstance(raw_history, list) else []
    if previous and not history:
        history.append(previous)
    history.append(reconciliation_record)
    summary["bvc_exact_publication_reconciliation"] = reconciliation_record
    summary["bvc_exact_publication_reconciliation_history"] = history
    return summary


def reconcile_stockanalysis_publication_dates(
    db: Session,
    *,
    apply: bool = False,
    symbols: set[str] | None = None,
) -> dict[str, object]:
    wanted_symbols = {str(symbol).strip().upper() for symbol in symbols or set() if str(symbol).strip()}
    document_rows = db.query(models.FundamentalSourceDocument).all()
    documents = {int(row.id): row for row in document_rows if row.id is not None}
    trusted_document_ids = {doc_id for doc_id, row in documents.items() if _official_trustworthy_document(row)}

    period_query = db.query(models.FundamentalPeriodMetric).filter(
        models.FundamentalPeriodMetric.period_type == "annual",
        models.FundamentalPeriodMetric.is_proxy.is_(False),
        models.FundamentalPeriodMetric.metric_value.isnot(None),
        models.FundamentalPeriodMetric.source_document_id.in_(sorted(trusted_document_ids)),
    )
    if wanted_symbols:
        period_query = period_query.filter(models.FundamentalPeriodMetric.symbol.in_(sorted(wanted_symbols)))
    period_rows = period_query.all()

    evidence_by_key: dict[tuple[str, int, str, Decimal], list[FilingMetricEvidence]] = {}
    for row in period_rows:
        document = documents.get(int(row.source_document_id)) if row.source_document_id is not None else None
        if document is None or document.publication_date is None:
            continue
        item = FilingMetricEvidence(
            source_document_id=int(document.id),
            symbol=row.symbol,
            fiscal_year=int(row.fiscal_year),
            metric_name=row.metric_name,
            metric_value=float(row.metric_value),
            publication_date=document.publication_date,
            document_kind=document.document_kind,
        )
        key = exact_metric_key(
            symbol=item.symbol,
            fiscal_year=item.fiscal_year,
            metric_name=item.metric_name,
            metric_value=item.metric_value,
        )
        if key is not None:
            evidence_by_key.setdefault(key, []).append(item)

    annual_query = (
        db.query(models.FundamentalAnnualMetric)
        .join(models.FundamentalImport, models.FundamentalAnnualMetric.import_id == models.FundamentalImport.id)
        .filter(
            models.FundamentalImport.data_source == "stockanalysis",
            models.FundamentalAnnualMetric.metric_value.isnot(None),
            models.FundamentalAnnualMetric.is_proxy.is_(False),
        )
    )
    if wanted_symbols:
        annual_query = annual_query.filter(models.FundamentalAnnualMetric.symbol.in_(sorted(wanted_symbols)))
    annual_rows = annual_query.all()

    matched = changed = already_exact = 0
    matched_by_metric: dict[str, int] = {}
    matched_symbols: set[str] = set()
    matched_by_import: dict[object, int] = {}
    changes_by_import: dict[object, list[dict[str, object]]] = {}
    for row in annual_rows:
        key = exact_metric_key(
            symbol=row.symbol,
            fiscal_year=int(row.statement_year),
            metric_name=row.metric_name,
            metric_value=row.metric_value,
        )
        candidates = evidence_by_key.get(key, []) if key is not None else []
        selected = select_exact_publication_evidence(
            symbol=row.symbol,
            fiscal_year=int(row.statement_year),
            metric_name=row.metric_name,
            metric_value=row.metric_value,
            evidence=candidates,
        )
        if selected is None:
            continue
        matched += 1
        canonical_metric = resolve_metric_name(str(row.metric_name))
        matched_by_metric[canonical_metric] = matched_by_metric.get(canonical_metric, 0) + 1
        matched_symbols.add(str(row.symbol).strip().upper())
        if row.source_document_id == selected.source_document_id and row.as_of_date == selected.publication_date:
            already_exact += 1
            continue
        changed += 1
        matched_by_import[row.import_id] = matched_by_import.get(row.import_id, 0) + 1
        changes_by_import.setdefault(row.import_id, []).append(
            {
                "annual_metric_id": int(row.id),
                "symbol": str(row.symbol).strip().upper(),
                "statement_year": int(row.statement_year),
                "metric_name": str(row.metric_name),
                "prior_as_of_date": row.as_of_date.isoformat() if row.as_of_date else None,
                "prior_source_document_id": int(row.source_document_id) if row.source_document_id else None,
                "verified_publication_date": selected.publication_date.isoformat(),
                "verified_source_document_id": selected.source_document_id,
            }
        )
        if apply:
            row.source_document_id = selected.source_document_id
            row.as_of_date = selected.publication_date
            db.add(row)

    if apply:
        for import_id, changes in changes_by_import.items():
            import_row = db.get(models.FundamentalImport, import_id)
            if import_row is None:
                continue
            reconciliation_record = {
                "method_version": RECONCILIATION_METHOD_VERSION,
                "matching_rule": "exact_symbol_fiscal_year_canonical_metric_decimal_value",
                "changed_rows": changes,
            }
            import_row.summary_json = _with_reconciliation_history(import_row.summary_json, reconciliation_record)
            db.add(import_row)
        db.commit()
    return {
        "mode": "apply" if apply else "audit",
        "method_version": RECONCILIATION_METHOD_VERSION,
        "stockanalysis_metric_rows": len(annual_rows),
        "trusted_bvc_annual_metric_rows": len(period_rows),
        "exact_reconciled_rows": matched,
        "rows_needing_change": changed,
        "rows_already_exact": already_exact,
        "unmatched_rows": len(annual_rows) - matched,
        "matched_imports": len(matched_by_import),
        "matched_symbols": sorted(matched_symbols),
        "matched_by_canonical_metric": dict(sorted(matched_by_metric.items())),
    }


__all__ = [
    "FilingMetricEvidence",
    "_with_reconciliation_history",
    "exact_metric_key",
    "reconcile_stockanalysis_publication_dates",
    "select_exact_publication_evidence",
]
