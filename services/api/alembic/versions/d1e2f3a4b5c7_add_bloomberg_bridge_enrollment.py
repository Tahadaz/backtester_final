"""add bloomberg bridge self-enrollment tables

Lets a Bloomberg computer provision itself from the deployed app: the app mints a
single-use enrollment token, the downloaded connector exchanges it for a
long-lived per-terminal credential.

Revision ID: d1e2f3a4b5c7
Revises: c8a1f3d7e204
Create Date: 2026-08-17
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "d1e2f3a4b5c7"
down_revision: Union[str, None] = "c8a1f3d7e204"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bloomberg_bridge_credential",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("bridge_id", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("key_prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("created_by", sa.String(length=200), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_bloomberg_bridge_credential_bridge_id",
        "bloomberg_bridge_credential",
        ["bridge_id"],
    )

    op.create_table(
        "bloomberg_bridge_enrollment",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("bridge_id", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("token_prefix", sa.String(length=16), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("created_by", sa.String(length=200), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("credential_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["credential_id"], ["bloomberg_bridge_credential.id"]),
    )
    op.create_index(
        "ix_bloomberg_bridge_enrollment_expires_at",
        "bloomberg_bridge_enrollment",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_bloomberg_bridge_enrollment_expires_at",
        table_name="bloomberg_bridge_enrollment",
    )
    op.drop_table("bloomberg_bridge_enrollment")
    op.drop_index(
        "ix_bloomberg_bridge_credential_bridge_id",
        table_name="bloomberg_bridge_credential",
    )
    op.drop_table("bloomberg_bridge_credential")
