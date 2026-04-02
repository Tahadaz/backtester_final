"""add saved_strategy table

Revision ID: g7h8i9j0k1l2
Revises: f1e2d3c4b5a6
Create Date: 2026-03-26 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


# revision identifiers, used by Alembic.
revision = "g7h8i9j0k1l2"
down_revision = "f1e2d3c4b5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_strategy",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("side_policy", sa.String(20), nullable=False, server_default="long_only"),
        sa.Column("horizon", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("config_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_saved_strategy_status", "saved_strategy", ["status"])
    op.create_index("ix_saved_strategy_updated_at", "saved_strategy", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_saved_strategy_updated_at", table_name="saved_strategy")
    op.drop_index("ix_saved_strategy_status", table_name="saved_strategy")
    op.drop_table("saved_strategy")
