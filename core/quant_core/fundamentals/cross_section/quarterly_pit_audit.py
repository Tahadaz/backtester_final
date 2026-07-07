"""Quarterly/interim PIT-provenance audit utilities (2026-07-06 continuation).

Finding: `fundamental_source_document.publication_date` is not always a
genuine filing date. For rows scraped from stockanalysis.com
("StockAnalysis interim financial tables - *", "StockAnalysis H2 derived
from FY minus H1"), `publication_date` was defaulted to the ingestion
`created_at` timestamp when no real per-statement date was extracted --
confirmed via 402 of 3,183 source_document rows (12.6%) having
`publication_date == created_at::date`, and via a cluster of 196 rows all
sharing the identical ingestion timestamp `2026-06-04 21:15:30.640734Z`
across unrelated symbols and fiscal years.

This is NOT a look-ahead violation -- the fake dates are almost always much
LATER than the true availability (conservative direction), since most
affected periods are from 2020-2024 and the fake date clusters around the
2026 ingestion run. But it does corrupt any analysis of *when* information
genuinely became available (Phase 6's information-refresh / genuine-event
analysis), since a burst of years-old data would otherwise look like a wave
of brand-new filings landing on one day.

This module provides an opt-in, non-invasive detector so THIS task's
analysis (information refresh, event-driven rebalance) can discount these
rows, without silently changing `panel.py`'s shared `availability_date()`
logic that all previously-reported IC/strategy numbers already depend on
(that would be an unreviewed, out-of-scope change to already-reported
results -- flagged as a recommended follow-up instead, see
quarterly_pit_audit.md).
"""
from __future__ import annotations

import datetime as dt

UNTRUSTWORTHY_DOCUMENT_TITLE_PREFIXES = (
    "StockAnalysis interim financial tables",
    "StockAnalysis H2 derived from FY minus H1",
)


def is_trustworthy_publication_date(
    *,
    publication_date: dt.date | None,
    created_at: dt.datetime | dt.date | None,
    document_title: str | None,
) -> bool:
    """Returns False when `publication_date` looks like an ingestion-timestamp
    default rather than a genuine filing date: either the document title
    matches a known scrape-without-real-date pattern, or publication_date
    exactly equals the row's own created_at date (the tell-tale sign of a
    default-to-now fallback with no real date extracted)."""
    if publication_date is None:
        return False
    title = (document_title or "").strip()
    if title.startswith(UNTRUSTWORTHY_DOCUMENT_TITLE_PREFIXES):
        return False
    if created_at is not None:
        created_date = created_at.date() if isinstance(created_at, dt.datetime) else created_at
        if publication_date == created_date:
            return False
    return True
