"""Canonical S3 object-key helpers.

This is the single source of truth for dataset object key construction.
Both the API service and the worker import from here so the key format
can never silently diverge between writer and reader.
"""
from __future__ import annotations


def build_dataset_object_key(data_hash: str, filename: str) -> str:
    """Return the canonical S3 key for an uploaded dataset file.

    Format: ``datasets/{data_hash}/{filename}``

    Args:
        data_hash: SHA-256 hex digest of the raw file bytes (stored in
                   ``dataset.data_hash``).
        filename:  Original uploaded filename, basename only (stored in
                   ``dataset.filename``).

    This function is the fallback used when ``dataset.object_key`` is NULL
    (legacy rows).  New rows always have ``object_key`` populated at upload
    time using this same formula, so reads should always prefer the DB column.
    """
    return f"datasets/{data_hash}/{filename}"
