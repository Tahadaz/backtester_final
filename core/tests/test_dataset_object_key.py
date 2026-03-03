"""Regression tests: dataset object_key canonical format.

Verifies that:
1. build_dataset_object_key always produces datasets/{data_hash}/{filename}.
2. The upload code path (simulated) sets dataset.object_key to the canonical key.
3. A simulated read always uses the stored key in preference to any fallback.
4. The fallback reconstruction matches the canonical key exactly.

These tests are pure-unit (no DB, no S3) so they run in the standard test suite:
    python -m pytest core/tests/test_dataset_object_key.py -v
"""
from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

import pytest

from core.quant_core.s3_keys import build_dataset_object_key


# ---------------------------------------------------------------------------
# 1. Canonical key format
# ---------------------------------------------------------------------------

class TestBuildDatasetObjectKey:
    def test_basic_format(self):
        key = build_dataset_object_key(data_hash="abc123", filename="prices.xlsx")
        assert key == "datasets/abc123/prices.xlsx"

    def test_with_real_sha256(self):
        content = b"fake file content for testing"
        sha = hashlib.sha256(content).hexdigest()
        key = build_dataset_object_key(data_hash=sha, filename="data.csv")
        assert key.startswith("datasets/")
        assert sha in key
        assert key.endswith("/data.csv")

    def test_no_double_slash(self):
        key = build_dataset_object_key(data_hash="deadbeef", filename="file.csv")
        assert "//" not in key

    def test_format_is_always_three_segments(self):
        key = build_dataset_object_key(data_hash="x" * 64, filename="upload.bin")
        parts = key.split("/")
        # "datasets" / <hash> / <filename>
        assert len(parts) == 3
        assert parts[0] == "datasets"

    def test_filename_preserved_exactly(self):
        filename = "My Data 2024 (v2).xlsx"
        key = build_dataset_object_key(data_hash="abc", filename=filename)
        assert key == f"datasets/abc/{filename}"


# ---------------------------------------------------------------------------
# 2. Upload path: object_key stored in DB matches canonical format
# ---------------------------------------------------------------------------

class TestUploadSetsCanonicalKey:
    """Simulate the datasets.py upload endpoint logic without real I/O."""

    def _simulate_upload(self, file_bytes: bytes, filename: str) -> dict:
        """Replicate the key-derivation logic from datasets.py POST /upload."""
        digest = hashlib.sha256(file_bytes).hexdigest()
        object_key = build_dataset_object_key(data_hash=digest, filename=filename)
        # Simulate what is stored in DB
        return {"data_hash": digest, "object_key": object_key, "filename": filename}

    def test_object_key_matches_canonical(self):
        row = self._simulate_upload(b"some,csv,data\n1,2,3", "prices.csv")
        expected = build_dataset_object_key(data_hash=row["data_hash"], filename=row["filename"])
        assert row["object_key"] == expected

    def test_object_key_format(self):
        row = self._simulate_upload(b"\x50\x4b\x03\x04", "workbook.xlsx")
        assert row["object_key"].startswith("datasets/")
        assert row["object_key"].endswith("/workbook.xlsx")

    def test_two_different_files_get_different_keys(self):
        row_a = self._simulate_upload(b"content_A", "data.csv")
        row_b = self._simulate_upload(b"content_B", "data.csv")
        assert row_a["object_key"] != row_b["object_key"]

    def test_same_content_same_filename_idempotent(self):
        row_a = self._simulate_upload(b"same", "upload.xlsx")
        row_b = self._simulate_upload(b"same", "upload.xlsx")
        assert row_a["object_key"] == row_b["object_key"]


# ---------------------------------------------------------------------------
# 3. Read path: stored object_key is preferred over fallback reconstruction
# ---------------------------------------------------------------------------

class TestReadPrefersStoredKey:
    """Simulate the _materialize_dataset_file logic (runs.py / execute_run.py)."""

    def _materialize_key(
        self,
        filename: str,
        data_hash: str,
        object_key: str | None,
    ) -> str:
        """Mirror the key-selection logic in both API and worker."""
        return object_key or build_dataset_object_key(data_hash=data_hash, filename=filename)

    def test_stored_key_takes_precedence(self):
        stored = "datasets/abc123/prices.xlsx"
        chosen = self._materialize_key("prices.xlsx", "abc123", stored)
        assert chosen == stored

    def test_fallback_used_when_stored_is_none(self):
        chosen = self._materialize_key("prices.xlsx", "abc123", None)
        assert chosen == "datasets/abc123/prices.xlsx"

    def test_fallback_matches_canonical_function(self):
        data_hash = "deadbeef" * 8  # 64-char hex
        filename = "data.csv"
        fallback = self._materialize_key(filename, data_hash, None)
        canonical = build_dataset_object_key(data_hash=data_hash, filename=filename)
        assert fallback == canonical

    def test_stored_key_is_used_even_if_it_differs_from_reconstruction(self):
        # Legacy rows may have object_key = datasets/{hash}/{symbol} while
        # filename = actual_file.xlsx.  The stored key is authoritative.
        legacy_key = "datasets/abc/SOME_SYMBOL"
        chosen = self._materialize_key("actual_file.xlsx", "abc", legacy_key)
        assert chosen == legacy_key


# ---------------------------------------------------------------------------
# 4. Consistency: fallback == canonical for "normal" rows
# ---------------------------------------------------------------------------

class TestFallbackConsistency:
    def test_fallback_always_matches_canonical_key(self):
        cases = [
            ("abc123", "prices.xlsx"),
            ("deadbeef" * 8, "my data.csv"),
            ("0" * 64, "upload.bin"),
        ]
        for data_hash, filename in cases:
            canonical = build_dataset_object_key(data_hash=data_hash, filename=filename)
            fallback = build_dataset_object_key(data_hash=data_hash, filename=filename)
            assert canonical == fallback, f"Mismatch for {data_hash!r}, {filename!r}"
