"""add bloomberg control-plane tables

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-05-13
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, None] = "b9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bloomberg_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("requested_by", sa.String(length=128), nullable=True),
        sa.Column("bridge_id", sa.String(length=128), nullable=True),
        sa.Column(
            "spec_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "progress_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_bloomberg_job_status_created_at", "bloomberg_job", ["status", "created_at"])
    op.create_index("ix_bloomberg_job_bridge_id", "bloomberg_job", ["bridge_id"])
    op.create_index("ix_bloomberg_job_job_type", "bloomberg_job", ["job_type"])

    op.create_table(
        "bloomberg_bridge_status",
        sa.Column("bridge_id", sa.String(length=128), primary_key=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="offline"),
        sa.Column(
            "capabilities_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "preflight_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("active_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["active_job_id"], ["bloomberg_job.id"]),
    )
    op.create_index("ix_bloomberg_bridge_status_last_seen_at", "bloomberg_bridge_status", ["last_seen_at"])
    op.create_index("ix_bloomberg_bridge_status_status", "bloomberg_bridge_status", ["status"])

    op.create_table(
        "bloomberg_job_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bridge_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["job_id"], ["bloomberg_job.id"]),
    )
    op.create_index(
        "ix_bloomberg_job_event_job_id_created_at",
        "bloomberg_job_event",
        ["job_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_bloomberg_job_event_job_id_created_at", table_name="bloomberg_job_event")
    op.drop_table("bloomberg_job_event")
    op.drop_index("ix_bloomberg_bridge_status_status", table_name="bloomberg_bridge_status")
    op.drop_index("ix_bloomberg_bridge_status_last_seen_at", table_name="bloomberg_bridge_status")
    op.drop_table("bloomberg_bridge_status")
    op.drop_index("ix_bloomberg_job_job_type", table_name="bloomberg_job")
    op.drop_index("ix_bloomberg_job_bridge_id", table_name="bloomberg_job")
    op.drop_index("ix_bloomberg_job_status_created_at", table_name="bloomberg_job")
    op.drop_table("bloomberg_job")
