"""add batch_id to signal_engine_batch_job

Revision ID: k1m2n3p4q5r6
Revises: e3f4a5b6c7d8
Create Date: 2026-04-22 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "k1m2n3p4q5r6"
down_revision: Union[str, None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("signal_engine_batch_job", sa.Column("batch_id", sa.String(length=64), nullable=True))
    op.create_index("ix_sebj_batch_id", "signal_engine_batch_job", ["batch_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_sebj_batch_id", table_name="signal_engine_batch_job")
    op.drop_column("signal_engine_batch_job", "batch_id")

