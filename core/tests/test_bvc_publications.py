from __future__ import annotations

import datetime as dt

from quant_core.fundamentals.providers.bvc_publications import (
    canonical_official_document_filename,
    canonical_official_document_key,
    discover_bvc_publications,
    parse_bvc_publication_archive,
)


def test_archive_parser_preserves_official_date_and_document_url() -> None:
    html = """
    <article class="pub-card">
      <span class="pub-type-badge">Etats Financiers</span>
      <span class="pub-date">2017-02-27</span>
      <h3 class="pub-title">IAM : 2016 consolidated results</h3>
      <a class="btn-download" href="/sites/default/files/pemetteur/2026-07/IAM_cc_2016_en_en.pdf">Download</a>
    </article>
    """
    rows = parse_bvc_publication_archive(html)
    assert len(rows) == 1
    assert rows[0].publication_date == dt.date(2017, 2, 27)
    assert rows[0].document_type == "Etats Financiers"
    assert rows[0].title == "IAM : 2016 consolidated results"
    assert rows[0].document_url == "https://www.casablanca-bourse.com/sites/default/files/pemetteur/2026-07/IAM_cc_2016_en_en.pdf"


def test_missing_or_invalid_date_is_not_defaulted_to_today() -> None:
    html = """
    <article class="pub-card">
      <span class="pub-date">not-a-date</span>
      <h3 class="pub-title">Unknown</h3>
      <a class="btn-download" href="/unknown.pdf">Download</a>
    </article>
    """
    assert parse_bvc_publication_archive(html) == []


def test_media_and_archive_paths_match_only_after_known_pemetteur_normalization() -> None:
    archive = "https://www.casablanca-bourse.com/sites/default/files/pemetteur/2026-07/IAM_cc_2016_en_en.pdf"
    media = "https://media.casablanca-bourse.com/sites/default/files/2026-07/IAM_cc_2016_en_en.pdf"
    assert canonical_official_document_key(archive) == canonical_official_document_key(media)
    assert canonical_official_document_filename(archive) == "iam_cc_2016_en_en.pdf"


def test_nonofficial_or_non_tls_url_cannot_produce_an_official_document_key() -> None:
    assert canonical_official_document_key("https://stockanalysis.com/sites/default/files/report.pdf") == ""
    assert canonical_official_document_key("http://media.casablanca-bourse.com/report.pdf") == ""


def test_discovery_stops_when_server_repeats_last_populated_page() -> None:
    html = """
    <article class="pub-card">
      <span class="pub-date">2017-02-27</span>
      <a class="btn-download" href="/sites/default/files/report.pdf">Download</a>
    </article>
    """
    fetched_urls: list[str] = []

    def fetch(url: str) -> str:
        fetched_urls.append(url)
        return html

    rows = discover_bvc_publications(fetch, document_types=("57",))

    assert len(rows) == 1
    assert len(fetched_urls) == 2
