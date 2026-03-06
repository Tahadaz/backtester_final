"""add parallel optimisation tables: opt_task, opt_result, run.leaderboard_json

Revision ID: f1a2b3c4d5e6
Revises: d7c1a9f9e2ab
Create Date: 2026-03-03 14:15:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "d7c1a9f9e2ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. leaderboard_json on Run ─────────────────────────────────────────────
    op.add_column(
        "run",
        sa.Column(
            "leaderboard_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    # ── 2. opt_task ────────────────────────────────────────────────────────────
    op.create_table(
        "opt_task",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fold_id", sa.String(), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("worker_job_id", sa.String(), nullable=True),
        sa.Column("params_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("spec_hash", sa.String(), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_opt_task_run_id", "opt_task", ["run_id"], unique=False)
    op.create_index(
        "ix_opt_task_run_fold_status",
        "opt_task",
        ["run_id", "fold_id", "status"],
        unique=False,
    )
    op.create_index(
        "ix_opt_task_worker_job_id",
        "opt_task",
        ["worker_job_id"],
        unique=False,
    )

    # ── 3. opt_result ──────────────────────────────────────────────────────────
    op.create_table(
        "opt_result",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fold_id", sa.String(), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=False),
        sa.Column(
            "topk_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id", "fold_id", "chunk_id", name="uq_opt_result_run_fold_chunk"
        ),
    )
    op.create_index("ix_opt_result_run_id", "opt_result", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_opt_result_run_id", table_name="opt_result")
    op.drop_table("opt_result")

    op.drop_index("ix_opt_task_worker_job_id", table_name="opt_task")
    op.drop_index("ix_opt_task_run_fold_status", table_name="opt_task")
    op.drop_index("ix_opt_task_run_id", table_name="opt_task")
    op.drop_table("opt_task")

    op.drop_column("run", "leaderboard_json")
