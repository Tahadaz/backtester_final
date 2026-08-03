"""add cross asset instrument and strategy tables

Revision ID: c8a1f3d7e204
Revises: b4c8e2f6a913
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c8a1f3d7e204"
down_revision: Union[str, Sequence[str], None] = "b4c8e2f6a913"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cross_asset_instrument",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("asset_class", sa.String(), nullable=False),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("quote_convention", sa.String(), nullable=False),
        sa.Column("point_value", sa.Float(), server_default="1", nullable=False),
        sa.Column("expiry", sa.String(), nullable=True),
        sa.Column("roll_rule", sa.String(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol"),
    )
    op.create_table(
        "cross_asset_strategy",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("spec_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("spec_hash", sa.String(length=64), nullable=False),
        sa.Column("replication_fidelity", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_cross_asset_strategy_name_version"),
    )


def downgrade() -> None:
    op.drop_table("cross_asset_strategy")
    op.drop_table("cross_asset_instrument")
