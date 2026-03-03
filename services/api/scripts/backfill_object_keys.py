#!/usr/bin/env python
"""One-time backfill: normalise dataset.object_key to canonical format.

CANONICAL FORMAT: ``datasets/{data_hash}/{filename}``

Run manually after deploying the fix/dataset-objectkey-canonical branch:

    cd services/api
    python -m scripts.backfill_object_keys [--dry-run]

What it does
------------
Finds every ``dataset`` row whose ``object_key`` does NOT equal
``datasets/{data_hash}/{filename}`` and updates it in-place.

The typical mismatch comes from the e2b7c24d9f0c migration which set:
    object_key = 'datasets/' || data_hash || '/' || symbol
for rows that existed before the ``filename`` column was added.  When
``filename`` was later populated with the real uploaded filename, the
``object_key`` still pointed at ``…/symbol`` while the S3 object lived at
``…/{filename}`` — causing NoSuchKey errors.

Safety
------
* Rows where ``data_hash`` or ``filename`` is NULL are skipped (no safe
  reconstruction is possible).
* The script prints each change before committing; use ``--dry-run`` to
  preview without writing.
* If the corrected key does not exist in S3, the row is skipped and a
  warning is printed so you can investigate manually.
"""
from __future__ import annotations

import argparse
import sys
import os

# Allow running from repo root or services/api/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import boto3
from botocore.exceptions import ClientError
from sqlalchemy import create_engine, text

from core.quant_core.s3_keys import build_dataset_object_key


def _s3_key_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return False
        raise


def backfill(db_url: str, s3_endpoint: str, s3_bucket: str, aws_key: str, aws_secret: str, dry_run: bool) -> None:
    engine = create_engine(db_url)

    s3 = boto3.client(
        "s3",
        endpoint_url=s3_endpoint or None,
        aws_access_key_id=aws_key,
        aws_secret_access_key=aws_secret,
    )

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, data_hash, filename, object_key
                FROM dataset
                WHERE data_hash IS NOT NULL
                  AND filename IS NOT NULL
                ORDER BY created_at
                """
            )
        ).mappings().all()

        updated = 0
        skipped_null = 0
        skipped_missing_s3 = 0
        already_ok = 0

        for row in rows:
            data_hash = str(row["data_hash"] or "").strip()
            filename = str(row["filename"] or "").strip()
            current_key = str(row["object_key"] or "").strip()
            dataset_id = row["id"]

            if not data_hash or not filename:
                skipped_null += 1
                continue

            canonical = build_dataset_object_key(data_hash=data_hash, filename=filename)

            if current_key == canonical:
                already_ok += 1
                continue

            # Verify the canonical key exists in S3 before switching
            if not _s3_key_exists(s3, s3_bucket, canonical):
                print(
                    f"  SKIP (S3 missing) id={dataset_id}  "
                    f"current={current_key!r}  wanted={canonical!r}"
                )
                skipped_missing_s3 += 1
                continue

            print(
                f"  {'DRY' if dry_run else 'FIX'} id={dataset_id}  "
                f"{current_key!r}  →  {canonical!r}"
            )

            if not dry_run:
                conn.execute(
                    text("UPDATE dataset SET object_key = :key WHERE id = :id"),
                    {"key": canonical, "id": dataset_id},
                )
            updated += 1

        if not dry_run:
            conn.commit()

    print(
        f"\nSummary: already_ok={already_ok}  updated={updated}  "
        f"skipped_null={skipped_null}  skipped_s3_missing={skipped_missing_s3}"
    )
    if dry_run:
        print("(dry-run — no rows were changed)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing to DB")
    parser.add_argument("--db-url", default=os.getenv("DATABASE_URL"), help="SQLAlchemy DB URL")
    parser.add_argument("--s3-endpoint", default=os.getenv("S3_ENDPOINT_URL", ""), help="S3/MinIO endpoint URL")
    parser.add_argument("--s3-bucket", default=os.getenv("S3_BUCKET", "backtester"), help="S3 bucket name")
    parser.add_argument("--aws-key", default=os.getenv("AWS_ACCESS_KEY_ID", ""), help="AWS/MinIO access key")
    parser.add_argument("--aws-secret", default=os.getenv("AWS_SECRET_ACCESS_KEY", ""), help="AWS/MinIO secret key")
    args = parser.parse_args()

    if not args.db_url:
        parser.error("--db-url or DATABASE_URL env var is required")

    backfill(
        db_url=args.db_url,
        s3_endpoint=args.s3_endpoint,
        s3_bucket=args.s3_bucket,
        aws_key=args.aws_key,
        aws_secret=args.aws_secret,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
