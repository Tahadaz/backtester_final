"""add scheduler run audit table

Revision ID: dd4ee5ff6aa7
Revises: cc3dd4ee5ff6
Create Date: 2026-05-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "dd4ee5ff6aa7"
down_revision = "cc3dd4ee5ff6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduler_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schedule_id", sa.String(64), nullable=False),
        sa.Column("trigger_source", sa.String(32), nullable=False, server_default="scheduled"),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enqueued_jobs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "meta_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scheduler_run_schedule_started", "scheduler_run", ["schedule_id", "started_at"])
    op.create_index("ix_scheduler_run_status", "scheduler_run", ["status"])


def downgrade() -> None:
    op.drop_index("ix_scheduler_run_status", table_name="scheduler_run")
    op.drop_index("ix_scheduler_run_schedule_started", table_name="scheduler_run")
    op.drop_table("scheduler_run")
