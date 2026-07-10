"""add full WFO recompute metadata

Revision ID: 8c1e5b7d2f90
Revises: 6039f1ec4937
Create Date: 2026-07-10 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8c1e5b7d2f90"
down_revision: Union[str, None] = "6039f1ec4937"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("wfo_global_signal", sa.Column("full_computed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("wfo_global_signal", sa.Column("full_data_as_of", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("wfo_global_signal", "full_data_as_of")
    op.drop_column("wfo_global_signal", "full_computed_at")
