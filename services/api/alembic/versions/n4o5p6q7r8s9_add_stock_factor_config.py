"""add stock_factor_config table

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-04-30 00:00:00.000000

Per-stock factor enable/disable state for Phase 2 Factor×TA cross-product
variants. Default: all 6 macro factors enabled per stock.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "n4o5p6q7r8s9"
down_revision: Union[str, None] = "m3n4o5p6q7r8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FACTOR_TICKERS = ["^VIX", "^GSPC", "BZ=F", "DX-Y.NYB", "EURUSD=X", "^TNX"]

_SEED_STOCKS = ["ATW", "BCP", "BMCE", "IAM", "CDM", "ADDH", "COSU", "WAA"]


def upgrade() -> None:
    op.create_table(
        "stock_factor_config",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stock_symbol", sa.String(20), nullable=False),
        sa.Column("factor_ticker", sa.String(20), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stock_factor_config"),
        sa.UniqueConstraint("stock_symbol", "factor_ticker", name="uq_stock_factor"),
    )
    op.create_index(
        "ix_sfc_stock_symbol",
        "stock_factor_config",
        ["stock_symbol"],
    )

    # Seed default rows: all 6 factors enabled for each seed stock
    seed_rows = [
        {"stock_symbol": stock, "factor_ticker": factor, "enabled": True}
        for stock in _SEED_STOCKS
        for factor in _FACTOR_TICKERS
    ]
    op.bulk_insert(
        sa.table(
            "stock_factor_config",
            sa.column("stock_symbol", sa.String),
            sa.column("factor_ticker", sa.String),
            sa.column("enabled", sa.Boolean),
        ),
        seed_rows,
    )


def downgrade() -> None:
    op.drop_index("ix_sfc_stock_symbol", table_name="stock_factor_config")
    op.drop_table("stock_factor_config")
