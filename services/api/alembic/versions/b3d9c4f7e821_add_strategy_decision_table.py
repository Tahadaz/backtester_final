"""add strategy decision table

Revision ID: b3d9c4f7e821
Revises: a8d9b1c2e4f5
Create Date: 2026-02-25 11:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b3d9c4f7e821"
down_revision: Union[str, Sequence[str], None] = "a8d9b1c2e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strategy_decision",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("strategy_kind", sa.String(), nullable=False),
        sa.Column("trial_id", sa.String(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("params_hash", sa.String(), nullable=False),
        sa.Column("params_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("opportunity_score", sa.Float(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("opportunity_subscores", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("confidence_subscores", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("decision_page_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("explain_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'watch'")),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "symbol", "strategy_kind", "trial_id", name="uq_strategy_decision_run_symbol_kind_trial"),
    )
    op.create_index("ix_strategy_decision_run_symbol", "strategy_decision", ["run_id", "symbol"], unique=False)
    op.create_index(
        "ix_strategy_decision_run_symbol_kind_rank",
        "strategy_decision",
        ["run_id", "symbol", "strategy_kind", "rank"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_strategy_decision_run_symbol_kind_rank", table_name="strategy_decision")
    op.drop_index("ix_strategy_decision_run_symbol", table_name="strategy_decision")
    op.drop_table("strategy_decision")
