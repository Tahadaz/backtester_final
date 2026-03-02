"""add defaults discovery and strategy default set tables

Revision ID: 9f4c2d1b7a55
Revises: d7c1a9f9e2ab
Create Date: 2026-02-26 16:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "9f4c2d1b7a55"
down_revision: Union[str, Sequence[str], None] = "d7c1a9f9e2ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "defaults_discovery_run",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("strategy_name", sa.String(), nullable=False, server_default="sma_price"),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("ticker", sa.String(), nullable=True),
        sa.Column("dataset_id", sa.UUID(), nullable=True),
        sa.Column("params_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("results_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("artifacts_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("rq_job_id", sa.String(), nullable=True),
        sa.Column("progress_pct", sa.Float(), nullable=True),
        sa.Column("progress_stage", sa.String(), nullable=True),
        sa.Column("progress_message", sa.Text(), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["dataset_id"], ["dataset.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_defaults_discovery_run_created_at", "defaults_discovery_run", ["created_at"], unique=False)
    op.create_index("ix_defaults_discovery_run_status_created_at", "defaults_discovery_run", ["status", "created_at"], unique=False)
    op.create_index("ix_defaults_discovery_run_strategy_created_at", "defaults_discovery_run", ["strategy_name", "created_at"], unique=False)
    op.create_index("ix_defaults_discovery_run_rq_job_id", "defaults_discovery_run", ["rq_job_id"], unique=False)

    op.create_table(
        "strategy_default_set",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("strategy_name", sa.String(), nullable=False),
        sa.Column("source_run_id", sa.UUID(), nullable=True),
        sa.Column("defaults_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["source_run_id"], ["defaults_discovery_run.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_strategy_default_set_strategy_name", "strategy_default_set", ["strategy_name"], unique=False)
    op.create_index("ix_strategy_default_set_source_run_id", "strategy_default_set", ["source_run_id"], unique=False)
    op.create_index("ix_strategy_default_set_created_at", "strategy_default_set", ["created_at"], unique=False)
    op.create_index(
        "ix_strategy_default_set_strategy_name_created_at",
        "strategy_default_set",
        ["strategy_name", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_strategy_default_set_strategy_name_created_at", table_name="strategy_default_set")
    op.drop_index("ix_strategy_default_set_created_at", table_name="strategy_default_set")
    op.drop_index("ix_strategy_default_set_source_run_id", table_name="strategy_default_set")
    op.drop_index("ix_strategy_default_set_strategy_name", table_name="strategy_default_set")
    op.drop_table("strategy_default_set")

    op.drop_index("ix_defaults_discovery_run_rq_job_id", table_name="defaults_discovery_run")
    op.drop_index("ix_defaults_discovery_run_strategy_created_at", table_name="defaults_discovery_run")
    op.drop_index("ix_defaults_discovery_run_status_created_at", table_name="defaults_discovery_run")
    op.drop_index("ix_defaults_discovery_run_created_at", table_name="defaults_discovery_run")
    op.drop_table("defaults_discovery_run")
