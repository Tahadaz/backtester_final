"""add dashboard custom index table

Revision ID: j0k1l2m3n4o
Revises: i9j0k1l2m3n4
Create Date: 2026-04-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision = "j0k1l2m3n4o"
down_revision = "i9j0k1l2m3n4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dashboard_custom_index",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("symbols", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_index(
        "ix_dashboard_custom_index_updated_at",
        "dashboard_custom_index",
        ["updated_at"],
        unique=False,
    )
    op.create_index(
        "uq_dashboard_custom_index_name_ci",
        "dashboard_custom_index",
        [sa.text("lower(name)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_dashboard_custom_index_name_ci", table_name="dashboard_custom_index")
    op.drop_index("ix_dashboard_custom_index_updated_at", table_name="dashboard_custom_index")
    op.drop_table("dashboard_custom_index")

