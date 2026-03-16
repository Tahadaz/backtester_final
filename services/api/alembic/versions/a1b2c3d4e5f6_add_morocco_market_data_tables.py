"""add morocco market data tables: stock_master, provider_symbol_map, market_refresh_run, market_refresh_error; extend market_data_store

Revision ID: a1b2c3d4e5f6
Revises: ff2ed8e51892
Create Date: 2026-03-07 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "ff2ed8e51892"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Extend market_data_store with provenance + freshness columns ─────────
    op.add_column(
        "market_data_store",
        sa.Column("source_provider", sa.String(), nullable=True),
    )
    op.add_column(
        "market_data_store",
        sa.Column("data_as_of", sa.Date(), nullable=True),
    )

    # ── 2. stock_master ──────────────────────────────────────────────────────────
    op.create_table(
        "stock_master",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("isin", sa.String(), nullable=True),
        sa.Column("sector", sa.String(), nullable=True),
        sa.Column("market_cap_class", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("track_source", sa.String(), nullable=False, server_default="bourse_direct"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", name="uq_stock_master_symbol"),
    )
    op.create_index("ix_stock_master_is_active", "stock_master", ["is_active"], unique=False)

    # ── 3. provider_symbol_map ───────────────────────────────────────────────────
    op.create_table(
        "provider_symbol_map",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_symbol", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["symbol"], ["stock_master.symbol"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "provider", name="uq_provider_symbol_map_symbol_provider"),
    )

    # ── 4. market_refresh_run ────────────────────────────────────────────────────
    op.create_table(
        "market_refresh_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger_source", sa.String(), nullable=False, server_default="manual"),
        sa.Column("scope", sa.String(), nullable=False, server_default="all"),
        sa.Column("symbol", sa.String(), nullable=True),
        sa.Column("timeframe", sa.String(), nullable=False, server_default="1D"),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("rq_job_id", sa.String(), nullable=True),
        sa.Column("symbols_total", sa.Integer(), nullable=True),
        sa.Column("symbols_done", sa.Integer(), nullable=True),
        sa.Column("symbols_failed", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "meta_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_market_refresh_run_status", "market_refresh_run", ["status"], unique=False)
    op.create_index(
        "ix_market_refresh_run_created_at",
        "market_refresh_run",
        ["created_at"],
        unique=False,
    )

    # ── 5. market_refresh_error ──────────────────────────────────────────────────
    op.create_table(
        "market_refresh_error",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("refresh_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False, server_default="bourse_direct"),
        sa.Column("error_type", sa.String(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("raw_response", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["refresh_run_id"],
            ["market_refresh_run.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_market_refresh_error_run",
        "market_refresh_error",
        ["refresh_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_market_refresh_error_symbol",
        "market_refresh_error",
        ["symbol"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_market_refresh_error_symbol", table_name="market_refresh_error")
    op.drop_index("ix_market_refresh_error_run", table_name="market_refresh_error")
    op.drop_table("market_refresh_error")

    op.drop_index("ix_market_refresh_run_created_at", table_name="market_refresh_run")
    op.drop_index("ix_market_refresh_run_status", table_name="market_refresh_run")
    op.drop_table("market_refresh_run")

    op.drop_table("provider_symbol_map")

    op.drop_index("ix_stock_master_is_active", table_name="stock_master")
    op.drop_table("stock_master")

    op.drop_column("market_data_store", "data_as_of")
    op.drop_column("market_data_store", "source_provider")
