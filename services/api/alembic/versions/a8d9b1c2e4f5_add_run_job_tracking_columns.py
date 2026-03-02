"""add run job tracking columns

Revision ID: a8d9b1c2e4f5
Revises: c788e94f3062
Create Date: 2026-02-19 12:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a8d9b1c2e4f5"
down_revision: Union[str, Sequence[str], None] = "c788e94f3062"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("run", sa.Column("rq_job_id", sa.String(), nullable=True))
    op.add_column("run", sa.Column("progress_pct", sa.Float(), nullable=True))
    op.add_column("run", sa.Column("progress_stage", sa.String(), nullable=True))
    op.add_column("run", sa.Column("progress_message", sa.Text(), nullable=True))
    op.add_column("run", sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True))

    op.create_index("ix_run_rq_job_id", "run", ["rq_job_id"], unique=False)
    op.create_index("ix_run_status_last_heartbeat_at", "run", ["status", "last_heartbeat_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_run_status_last_heartbeat_at", table_name="run")
    op.drop_index("ix_run_rq_job_id", table_name="run")

    op.drop_column("run", "last_heartbeat_at")
    op.drop_column("run", "progress_message")
    op.drop_column("run", "progress_stage")
    op.drop_column("run", "progress_pct")
    op.drop_column("run", "rq_job_id")
