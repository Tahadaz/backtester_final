"""Add canonical snapshot flag.

Revision ID: b6c7d8e9f0a1
Revises: a1b2c3d4e6f8
Create Date: 2026-06-05
"""

from alembic import op
import sqlalchemy as sa


revision = "b6c7d8e9f0a1"
down_revision = "a1b2c3d4e6f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "fundamental_latest_snapshot",
        sa.Column("is_canonical", sa.Boolean(), server_default=sa.text("false"), nullable=True),
    )
    op.create_index(
        "ix_fundamental_latest_snapshot_symbol_canonical",
        "fundamental_latest_snapshot",
        ["symbol", "is_canonical"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_fundamental_latest_snapshot_symbol_canonical", table_name="fundamental_latest_snapshot")
    op.drop_column("fundamental_latest_snapshot", "is_canonical")
