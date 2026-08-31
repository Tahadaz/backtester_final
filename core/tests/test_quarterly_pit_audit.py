from __future__ import annotations

import datetime as dt

from quant_core.fundamentals.cross_section.quarterly_pit_audit import is_trustworthy_publication_date


def test_stockanalysis_interim_title_is_untrustworthy():
    assert not is_trustworthy_publication_date(
        publication_date=dt.date(2026, 6, 4),
        created_at=dt.datetime(2026, 6, 4, 21, 15, 30),
        document_title="StockAnalysis interim financial tables - Balance",
    )


def test_h2_derived_title_is_untrustworthy():
    assert not is_trustworthy_publication_date(
        publication_date=dt.date(2026, 6, 4),
        created_at=dt.datetime(2026, 6, 4, 10, 0, 0),
        document_title="StockAnalysis H2 derived from FY minus H1",
    )


def test_publication_date_equal_to_created_at_is_untrustworthy_even_with_other_title():
    assert not is_trustworthy_publication_date(
        publication_date=dt.date(2025, 1, 1),
        created_at=dt.datetime(2025, 1, 1, 8, 0, 0),
        document_title="Some other title",
    )


def test_genuine_filing_date_is_trustworthy():
    assert is_trustworthy_publication_date(
        publication_date=dt.date(2023, 4, 28),
        created_at=dt.datetime(2023, 8, 15, 9, 0, 0),
        document_title="REB: Rapport financier annuel 2022",
    )


def test_missing_publication_date_is_untrustworthy():
    assert not is_trustworthy_publication_date(
        publication_date=None,
        created_at=dt.datetime(2023, 1, 1),
        document_title="Some title",
    )


def test_official_raw_publication_date_is_trusted_even_when_ingested_same_day():
    assert is_trustworthy_publication_date(
        publication_date=dt.date(2026, 4, 30),
        created_at=dt.datetime(2026, 4, 30, 18, 0, 0),
        document_title="AFM: 2025 financial statements",
        source_url="https://media.casablanca-bourse.com/issuer/afm-2025.pdf",
        raw_json={"Publication_Date": "2026-04-30"},
    )
