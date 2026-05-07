"""add asset_class to market_data_store and create index_master

Revision ID: l2m3n4o5p6q7
Revises: k1m2n3p4q5r6
Create Date: 2026-04-24 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "l2m3n4o5p6q7"
down_revision: Union[str, None] = "k1m2n3p4q5r6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add asset_class discriminator to market_data_store
    #    Values: 'equity' (stocks), 'index' (Moroccan indices), 'factor' (macro, Phase 0)
    op.add_column(
        "market_data_store",
        sa.Column(
            "asset_class",
            sa.String(length=16),
            nullable=False,
            server_default="equity",
        ),
    )
    op.create_index(
        "ix_market_data_store_asset_class",
        "market_data_store",
        ["asset_class"],
        unique=False,
    )

    # 2. Create index_master table for Moroccan market indices
    op.create_table(
        "index_master",
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("family", sa.String(), nullable=True),   # all_share|blue_chip|esg|sector
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("source", sa.String(), nullable=False, server_default="casablanca_bourse"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("symbol"),
    )
    op.create_index(
        "ix_index_master_is_active",
        "index_master",
        ["is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_index_master_is_active", table_name="index_master")
    op.drop_table("index_master")
    op.drop_index("ix_market_data_store_asset_class", table_name="market_data_store")
    op.drop_column("market_data_store", "asset_class")
