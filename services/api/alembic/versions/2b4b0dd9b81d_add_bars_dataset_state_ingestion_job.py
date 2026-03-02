"""add bars dataset_state ingestion_job

Revision ID: 2b4b0dd9b81d
Revises: 9f4c2d1b7a55
Create Date: 2026-03-02 14:00:16.793953

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '2b4b0dd9b81d'
down_revision: Union[str, Sequence[str], None] = '9f4c2d1b7a55'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade():
    # 1) bars
    op.create_table(
        "bars",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("instrument_id", sa.BigInteger(), sa.ForeignKey("instrument.id", ondelete="CASCADE"), nullable=False),
        sa.Column("timeframe", sa.Text(), nullable=False, server_default="1D"),
        sa.Column("source", sa.Text(), nullable=False, server_default="tradingview"),
        sa.Column("dt", sa.Date(), nullable=False),

        sa.Column("open", sa.Numeric(18, 6), nullable=True),
        sa.Column("high", sa.Numeric(18, 6), nullable=True),
        sa.Column("low", sa.Numeric(18, 6), nullable=True),
        sa.Column("close", sa.Numeric(18, 6), nullable=True),
        sa.Column("volume", sa.Numeric(24, 6), nullable=True),

        sa.Column("inserted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_index("ix_bars_instrument_dt", "bars", ["instrument_id", "dt"])
    op.create_unique_constraint(
        "uq_bars_instrument_source_tf_dt",
        "bars",
        ["instrument_id", "source", "timeframe", "dt"],
    )

    # 2) dataset_state (cache last dt)
    op.create_table(
        "dataset_state",
        sa.Column("instrument_id", sa.BigInteger(), sa.ForeignKey("instrument.id", ondelete="CASCADE"), nullable=False),
        sa.Column("timeframe", sa.Text(), nullable=False, server_default="1D"),
        sa.Column("source", sa.Text(), nullable=False, server_default="tradingview"),
        sa.Column("last_dt", sa.Date(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("instrument_id", "source", "timeframe", name="pk_dataset_state"),
    )

    # 3) ingestion_job
    op.create_table(
        "ingestion_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source", sa.Text(), nullable=False, server_default="tradingview"),
        sa.Column("timeframe", sa.Text(), nullable=False, server_default="1D"),
        sa.Column("tickers", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),  # queued/running/success/failed
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_ingestion_job_status", "ingestion_job", ["status"])

def downgrade():
    op.drop_index("ix_ingestion_job_status", table_name="ingestion_job")
    op.drop_table("ingestion_job")

    op.drop_table("dataset_state")

    op.drop_constraint("uq_bars_instrument_source_tf_dt", "bars", type_="unique")
    op.drop_index("ix_bars_instrument_dt", table_name="bars")
    op.drop_table("bars")