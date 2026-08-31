"""Audit or fill BVC publication dates by exact official-document URL match.

The default mode is read-only.  Pass ``--apply`` to fill missing dates.  A
conflicting non-null date is reported and never overwritten automatically.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess

import requests
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.quant_core.fundamentals.providers.bvc_publications import (
    BVC_ARCHIVE_DOCUMENT_TYPES,
    BVC_PUBLICATION_ARCHIVE_URL,
    canonical_official_document_filename,
    canonical_official_document_key,
    discover_bvc_publications,
)
from services.api.app import models


def _fetcher(session: requests.Session, *, verify: bool | str):
    def fetch(url: str) -> str:
        response = session.get(url, timeout=30, verify=verify)
        response.raise_for_status()
        return response.content.decode("utf-8", errors="replace")

    return fetch


def _system_curl_fetcher():
    """Use curl's native OS trust store while retaining verified HTTPS."""

    executable = shutil.which("curl.exe") or shutil.which("curl")
    if not executable:
        raise RuntimeError("curl is required for --system-curl but was not found")

    def fetch(url: str) -> str:
        result = subprocess.run(
            [
                executable,
                "--fail",
                "--silent",
                "--show-error",
                "--location",
                "--user-agent",
                "Mozilla/5.0 (compatible; BVC-publication-lineage-audit/1.0)",
                "--proto",
                "=https",
                "--tlsv1.2",
                "--connect-timeout",
                "10",
                "--max-time",
                "30",
                url,
            ],
            check=True,
            capture_output=True,
        )
        return result.stdout.decode("utf-8", errors="replace")

    return fetch


def reconcile_archive_records(db: Session, records, *, apply: bool) -> dict[str, object]:
    documents = db.execute(select(models.FundamentalSourceDocument)).scalars().all()
    by_key: dict[str, list[models.FundamentalSourceDocument]] = {}
    db_paths_by_filename: dict[str, set[str]] = {}
    documents_by_filename: dict[str, list[models.FundamentalSourceDocument]] = {}
    for document in documents:
        key = canonical_official_document_key(document.source_url)
        if key:
            by_key.setdefault(key, []).append(document)
            filename = canonical_official_document_filename(document.source_url)
            documents_by_filename.setdefault(filename, []).append(document)
            db_paths_by_filename.setdefault(filename, set()).add(key)

    archive_paths_by_filename: dict[str, set[str]] = {}
    for record in records:
        filename = canonical_official_document_filename(record.document_url)
        key = canonical_official_document_key(record.document_url)
        if filename and key:
            archive_paths_by_filename.setdefault(filename, set()).add(key)

    matched = filled = already_equal = conflicts = 0
    exact_path_matches = unique_filename_matches = ambiguous_filename_records = 0
    conflict_rows: list[dict[str, object]] = []
    for record in records:
        record_key = canonical_official_document_key(record.document_url)
        matched_documents = by_key.get(record_key, [])
        match_kind = "exact_official_path"
        if not matched_documents:
            filename = canonical_official_document_filename(record.document_url)
            archive_paths = archive_paths_by_filename.get(filename, set())
            db_paths = db_paths_by_filename.get(filename, set())
            if filename and len(archive_paths) == 1 and len(db_paths) == 1:
                matched_documents = documents_by_filename.get(filename, [])
                match_kind = "globally_unique_exact_official_filename"
            elif filename and db_paths:
                ambiguous_filename_records += 1
        for document in matched_documents:
            matched += 1
            if match_kind == "exact_official_path":
                exact_path_matches += 1
            else:
                unique_filename_matches += 1
            if document.publication_date == record.publication_date:
                already_equal += 1
                continue
            if document.publication_date is not None:
                conflicts += 1
                conflict_rows.append(
                    {
                        "source_document_id": int(document.id),
                        "stored_date": document.publication_date.isoformat(),
                        "archive_date": record.publication_date.isoformat(),
                        "source_url": document.source_url,
                    }
                )
                continue
            if apply:
                raw = dict(document.raw_json or {})
                raw["archive_publication_date"] = record.publication_date.isoformat()
                raw["archive_page_url"] = record.archive_page_url
                raw["archive_document_url"] = record.document_url
                raw["archive_source"] = BVC_PUBLICATION_ARCHIVE_URL
                raw["archive_match_kind"] = match_kind
                document.publication_date = record.publication_date
                document.raw_json = raw
                db.add(document)
            filled += 1
    if apply:
        db.commit()
    return {
        "mode": "apply" if apply else "audit",
        "archive_records": len(records),
        "matched_source_documents": matched,
        "exact_path_matches": exact_path_matches,
        "unique_filename_matches": unique_filename_matches,
        "ambiguous_filename_records_not_matched": ambiguous_filename_records,
        "fillable_missing_dates": filled,
        "already_equal": already_equal,
        "conflicts_not_overwritten": conflicts,
        "conflicts": conflict_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    tls = parser.add_mutually_exclusive_group()
    tls.add_argument("--ca-bundle", help="PEM CA bundle for the Bourse TLS chain.")
    tls.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification only when an approved local CA bundle is unavailable.",
    )
    tls.add_argument(
        "--system-curl",
        action="store_true",
        help="Fetch with curl and the operating system trust store (useful when requests lacks the local CA).",
    )
    parser.add_argument(
        "--document-type",
        action="append",
        choices=sorted(BVC_ARCHIVE_DOCUMENT_TYPES),
        help="Defaults to financial statements and annual reports.",
    )
    args = parser.parse_args()
    if args.apply and args.insecure:
        parser.error("--apply requires verified TLS; provide --ca-bundle instead of --insecure")
    type_names = args.document_type or list(BVC_ARCHIVE_DOCUMENT_TYPES)
    type_ids = tuple(BVC_ARCHIVE_DOCUMENT_TYPES[name] for name in type_names)

    if args.system_curl:
        fetch_html = _system_curl_fetcher()
    else:
        session = requests.Session()
        session.headers["User-Agent"] = "Mozilla/5.0 (compatible; BVC-publication-lineage-audit/1.0)"
        verify: bool | str = False if args.insecure else (args.ca_bundle or True)
        fetch_html = _fetcher(session, verify=verify)
    records = discover_bvc_publications(fetch_html, document_types=type_ids)
    engine = create_engine(os.environ.get("DATABASE_URL", "postgresql+psycopg2://app:app@127.0.0.1:5555/quant"))
    with Session(engine) as db:
        result = reconcile_archive_records(db, records, apply=args.apply)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
