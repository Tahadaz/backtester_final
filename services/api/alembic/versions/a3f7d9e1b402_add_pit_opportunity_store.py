"""add reusable PIT opportunity store

Revision ID: a3f7d9e1b402
Revises: 9d2f6c8e3a01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a3f7d9e1b402"
down_revision: Union[str, Sequence[str], None] = "9d2f6c8e3a01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "historical_opportunity_materialization_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column("rq_job_id", sa.String(), nullable=True),
        sa.Column("methodology_version", sa.String(length=80), nullable=False),
        sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("progress_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("coverage_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('queued','running','succeeded','failed')", name="ck_historical_opportunity_materialization_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_historical_opportunity_materialization_status", "historical_opportunity_materialization_run", ["status"])
    op.create_index("ix_historical_opportunity_materialization_created", "historical_opportunity_materialization_run", ["created_at"])
    op.create_table(
        "historical_trade_opportunity",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("decision_date", sa.Date(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("horizon", sa.String(length=16), nullable=False),
        sa.Column("variant", sa.String(length=64), nullable=False),
        sa.Column("accepted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("rank_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("opportunity_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("materialization_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["materialization_run_id"], ["historical_opportunity_materialization_run.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("decision_date", "symbol", "horizon", "variant", name="uq_historical_trade_opportunity_key"),
    )
    op.create_index("ix_historical_trade_opportunity_accepted_date", "historical_trade_opportunity", ["accepted", "decision_date"])
    op.create_index("ix_historical_trade_opportunity_symbol_horizon", "historical_trade_opportunity", ["symbol", "horizon"])


def downgrade() -> None:
    op.drop_index("ix_historical_trade_opportunity_symbol_horizon", table_name="historical_trade_opportunity")
    op.drop_index("ix_historical_trade_opportunity_accepted_date", table_name="historical_trade_opportunity")
    op.drop_table("historical_trade_opportunity")
    op.drop_index("ix_historical_opportunity_materialization_created", table_name="historical_opportunity_materialization_run")
    op.drop_index("ix_historical_opportunity_materialization_status", table_name="historical_opportunity_materialization_run")
    op.drop_table("historical_opportunity_materialization_run")
