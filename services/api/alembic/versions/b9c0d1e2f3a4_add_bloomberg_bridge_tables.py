"""add bloomberg bridge ingestion tables

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-05-12
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "b9c0d1e2f3a4"
down_revision: Union[str, None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bloomberg_ingest_batch",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("bridge_id", sa.String(length=128), nullable=False),
        sa.Column("request_id", sa.String(length=160), nullable=False),
        sa.Column("bloomberg_source", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="succeeded"),
        sa.Column("raw_object_key", sa.String(), nullable=False),
        sa.Column("manifest_object_key", sa.String(), nullable=False),
        sa.Column("normalized_object_key", sa.String(), nullable=True),
        sa.Column("filename", sa.String(), nullable=True),
        sa.Column("content_type", sa.String(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("data_sha256", sa.String(length=64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("series_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "manifest_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("bridge_id", "request_id", name="uq_bloomberg_ingest_batch_bridge_request"),
    )
    op.create_index("ix_bloomberg_ingest_batch_created_at", "bloomberg_ingest_batch", ["created_at"])
    op.create_index("ix_bloomberg_ingest_batch_bridge_id", "bloomberg_ingest_batch", ["bridge_id"])
    op.create_index("ix_bloomberg_ingest_batch_kind", "bloomberg_ingest_batch", ["kind"])

    op.create_table(
        "bloomberg_series",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("series_key", sa.String(length=64), nullable=False, unique=True),
        sa.Column("last_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("security", sa.String(length=256), nullable=False),
        sa.Column("field", sa.String(length=128), nullable=False),
        sa.Column("periodicity", sa.String(length=32), nullable=True),
        sa.Column("overrides_hash", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="time_series"),
        sa.Column("object_key", sa.String(), nullable=False),
        sa.Column("start_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["last_batch_id"], ["bloomberg_ingest_batch.id"]),
    )
    op.create_index("ix_bloomberg_series_security", "bloomberg_series", ["security"])
    op.create_index("ix_bloomberg_series_field", "bloomberg_series", ["field"])
    op.create_index("ix_bloomberg_series_updated_at", "bloomberg_series", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_bloomberg_series_updated_at", table_name="bloomberg_series")
    op.drop_index("ix_bloomberg_series_field", table_name="bloomberg_series")
    op.drop_index("ix_bloomberg_series_security", table_name="bloomberg_series")
    op.drop_table("bloomberg_series")
    op.drop_index("ix_bloomberg_ingest_batch_kind", table_name="bloomberg_ingest_batch")
    op.drop_index("ix_bloomberg_ingest_batch_bridge_id", table_name="bloomberg_ingest_batch")
    op.drop_index("ix_bloomberg_ingest_batch_created_at", table_name="bloomberg_ingest_batch")
    op.drop_table("bloomberg_ingest_batch")
