"""Deterministic parser for the official Casablanca Bourse issuer archive.

The archive is server-rendered.  This module deliberately separates parsing
from transport so callers can use an approved HTTP/browser session and tests
can use saved HTML without network access.  Missing dates remain missing; no
"today" fallback exists.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse, urlunparse


BVC_PUBLICATION_ARCHIVE_URL = "https://www.casablanca-bourse.com/apropos/publications/emetteurs"
BVC_OFFICIAL_DOCUMENT_HOSTS = frozenset(
    {
        "casablanca-bourse.com",
        "www.casablanca-bourse.com",
        "media.casablanca-bourse.com",
    }
)

# Values are taken from the archive's own publication-type form.
BVC_ARCHIVE_DOCUMENT_TYPES = {
    "financial_statements": "57",
    "annual_reports": "58",
}


@dataclass(frozen=True)
class BvcPublication:
    publication_date: dt.date
    document_type: str
    title: str
    document_url: str
    archive_page_url: str


def canonical_official_document_key(url: str) -> str:
    """Canonical official asset path used for exact archive/document matching."""

    parsed = urlparse(str(url or "").strip())
    if parsed.scheme.lower() != "https" or (parsed.hostname or "").lower() not in BVC_OFFICIAL_DOCUMENT_HOSTS:
        return ""
    path = parsed.path.replace("/sites/default/files/pemetteur/", "/sites/default/files/")
    while "//" in path:
        path = path.replace("//", "/")
    return path.rstrip("/").lower()


def canonical_official_document_filename(url: str) -> str:
    """Return an exact filename key for a verified BVC URL, or an empty key."""

    key = canonical_official_document_key(url)
    return unquote(key.rsplit("/", 1)[-1]) if key else ""


class _ArchiveParser(HTMLParser):
    def __init__(self, page_url: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.records: list[BvcPublication] = []
        self.next_page_urls: set[str] = set()
        self._article: dict[str, str] | None = None
        self._capture: str | None = None
        self._capture_tag: str | None = None

    @staticmethod
    def _classes(attrs: dict[str, str]) -> set[str]:
        return set((attrs.get("class") or "").split())

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {key: value or "" for key, value in attrs_list}
        classes = self._classes(attrs)
        if tag == "article" and "pub-card" in classes:
            self._article = {"document_type": "", "publication_date": "", "title": "", "document_url": ""}
            return
        if self._article is not None:
            field = None
            if "pub-type-badge" in classes:
                field = "document_type"
            elif "pub-date" in classes:
                field = "publication_date"
            elif "pub-title" in classes:
                field = "title"
            if field is not None:
                self._capture = field
                self._capture_tag = tag
            if tag == "a" and "btn-download" in classes and attrs.get("href"):
                self._article["document_url"] = urljoin(self.page_url, attrs["href"])
        if tag == "a" and attrs.get("href"):
            href = urljoin(self.page_url, attrs["href"])
            query = parse_qs(urlparse(href).query)
            if "page" in query:
                self.next_page_urls.add(href)

    def handle_data(self, data: str) -> None:
        if self._article is not None and self._capture:
            self._article[self._capture] += data

    def handle_endtag(self, tag: str) -> None:
        if self._capture_tag == tag:
            self._capture = None
            self._capture_tag = None
        if tag != "article" or self._article is None:
            return
        row = {key: " ".join(value.split()) for key, value in self._article.items()}
        self._article = None
        try:
            publication_date = dt.date.fromisoformat(row["publication_date"])
        except ValueError:
            return
        if not row["document_url"]:
            return
        self.records.append(
            BvcPublication(
                publication_date=publication_date,
                document_type=row["document_type"],
                title=row["title"],
                document_url=row["document_url"],
                archive_page_url=self.page_url,
            )
        )


def parse_bvc_publication_archive(html: str, *, page_url: str = BVC_PUBLICATION_ARCHIVE_URL) -> list[BvcPublication]:
    parser = _ArchiveParser(page_url)
    parser.feed(html)
    parser.close()
    return parser.records


def archive_page_url(*, document_type: str, page: int) -> str:
    parsed = urlparse(BVC_PUBLICATION_ARCHIVE_URL)
    query = urlencode({"type": str(document_type), "page": int(page)})
    return urlunparse(parsed._replace(query=query))


def discover_bvc_publications(
    fetch_html,
    *,
    document_types: tuple[str, ...] = tuple(BVC_ARCHIVE_DOCUMENT_TYPES.values()),
) -> list[BvcPublication]:
    """Fetch archive pages until empty/repeated, deduplicating by official asset path.

    Drupal may return its final populated page for an out-of-range ``page``
    value.  Stopping when a page contributes no new official document keys
    prevents an unbounded crawl without relying on an arbitrary page limit.
    """

    by_document: dict[str, BvcPublication] = {}
    for document_type in document_types:
        page = 0
        seen_type_keys: set[str] = set()
        while True:
            page_url = archive_page_url(document_type=document_type, page=page)
            records = parse_bvc_publication_archive(fetch_html(page_url), page_url=page_url)
            if not records:
                break
            page_keys = {
                canonical_official_document_key(record.document_url)
                for record in records
                if canonical_official_document_key(record.document_url)
            }
            if not page_keys.difference(seen_type_keys):
                break
            seen_type_keys.update(page_keys)
            for record in records:
                key = canonical_official_document_key(record.document_url)
                current = by_document.get(key)
                if current is None or record.publication_date < current.publication_date:
                    by_document[key] = record
            page += 1
    return sorted(by_document.values(), key=lambda row: (row.publication_date, row.document_url))


__all__ = [
    "BVC_ARCHIVE_DOCUMENT_TYPES",
    "BVC_OFFICIAL_DOCUMENT_HOSTS",
    "BVC_PUBLICATION_ARCHIVE_URL",
    "BvcPublication",
    "archive_page_url",
    "canonical_official_document_key",
    "canonical_official_document_filename",
    "discover_bvc_publications",
    "parse_bvc_publication_archive",
]
