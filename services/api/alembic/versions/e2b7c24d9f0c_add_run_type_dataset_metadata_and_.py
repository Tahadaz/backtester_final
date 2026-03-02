"""add run type, dataset metadata and strategy leaderboard

Revision ID: e2b7c24d9f0c
Revises: 571b9673d32f
Create Date: 2026-02-16 18:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "e2b7c24d9f0c"
down_revision: Union[str, Sequence[str], None] = "571b9673d32f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- run table ---
    op.add_column("run", sa.Column("run_type", sa.String(), nullable=False, server_default="backtest"))
    op.create_index("ix_run_run_type_created_at", "run", ["run_type", "created_at"], unique=False)

    op.execute(
        """
        update run
        set run_type = case
            when coalesce(nullif(spec_json #>> '{optimization,n_trials}', '')::int, 0) > 0
              or coalesce(jsonb_array_length(coalesce(spec_json #> '{optimization,kinds}', '[]'::jsonb)), 0) > 0
            then 'optimization'
            else 'backtest'
        end
        """
    )

    # --- dataset table ---
    op.add_column("dataset", sa.Column("filename", sa.String(), nullable=True))
    op.add_column("dataset", sa.Column("content_type", sa.String(), nullable=True))
    op.add_column("dataset", sa.Column("object_key", sa.String(), nullable=True))
    op.add_column("dataset", sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column(
        "dataset",
        sa.Column("meta_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    op.execute(
        """
        update dataset
        set filename = coalesce(filename, symbol),
            content_type = coalesce(content_type, timeframe),
            object_key = coalesce(object_key, 'datasets/' || data_hash || '/' || symbol),
            size_bytes = coalesce(size_bytes, 0),
            meta_json = coalesce(meta_json, '{}'::jsonb)
        """
    )

    # --- strategy leaderboard table ---
    op.create_table(
        "strategy_leaderboard",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("strategy_kind", sa.String(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("pnl", sa.Float(), nullable=True),
        sa.Column("cagr", sa.Float(), nullable=True),
        sa.Column("efficiency", sa.Float(), nullable=True),
        sa.Column("n_fills", sa.Integer(), nullable=True),
        sa.Column("signal_label", sa.String(), nullable=True),
        sa.Column("signal_today", sa.Float(), nullable=True),
        sa.Column("signal_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("best_params_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "symbol", "strategy_kind", "rank", name="uq_strategy_leaderboard_run_symbol_kind_rank"),
    )
    op.create_index("ix_strategy_leaderboard_run_id", "strategy_leaderboard", ["run_id"], unique=False)
    op.create_index("ix_strategy_leaderboard_symbol", "strategy_leaderboard", ["symbol"], unique=False)
    op.create_index("ix_strategy_leaderboard_strategy_kind", "strategy_leaderboard", ["strategy_kind"], unique=False)
    op.create_index("ix_strategy_leaderboard_run_symbol", "strategy_leaderboard", ["run_id", "symbol"], unique=False)
    op.create_index("ix_strategy_leaderboard_symbol_created_at", "strategy_leaderboard", ["symbol", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_strategy_leaderboard_symbol_created_at", table_name="strategy_leaderboard")
    op.drop_index("ix_strategy_leaderboard_run_symbol", table_name="strategy_leaderboard")
    op.drop_index("ix_strategy_leaderboard_strategy_kind", table_name="strategy_leaderboard")
    op.drop_index("ix_strategy_leaderboard_symbol", table_name="strategy_leaderboard")
    op.drop_index("ix_strategy_leaderboard_run_id", table_name="strategy_leaderboard")
    op.drop_table("strategy_leaderboard")

    op.drop_column("dataset", "meta_json")
    op.drop_column("dataset", "size_bytes")
    op.drop_column("dataset", "object_key")
    op.drop_column("dataset", "content_type")
    op.drop_column("dataset", "filename")

    op.drop_index("ix_run_run_type_created_at", table_name="run")
    op.drop_column("run", "run_type")
