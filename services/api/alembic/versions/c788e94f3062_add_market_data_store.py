"""add_market_data_store

Revision ID: c788e94f3062
Revises: e2b7c24d9f0c
Create Date: 2026-02-17 10:13:22.136177

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c788e94f3062'
down_revision: Union[str, Sequence[str], None] = 'e2b7c24d9f0c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_data_store",
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False, server_default="1D"),
        sa.Column("object_key", sa.String(), nullable=False),
        sa.Column("start_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.Column("last_dataset_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("dataset.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "timeframe", name="pk_market_data_store"),
    )
    op.create_index("ix_market_data_store_symbol", "market_data_store", ["symbol"])

def downgrade() -> None:
    op.drop_index("ix_market_data_store_symbol", table_name="market_data_store")
    op.drop_table("market_data_store")