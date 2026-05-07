"""add wfo folds_json and config_json columns

Revision ID: b7562436c132
Revises: a6451325b021
Create Date: 2026-04-15 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b7562436c132'
down_revision: Union[str, None] = 'a6451325b021'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('wfo_signal_summary', sa.Column('folds_json', postgresql.JSONB(), nullable=True))
    op.add_column('wfo_signal_summary', sa.Column('config_json', postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('wfo_signal_summary', 'config_json')
    op.drop_column('wfo_signal_summary', 'folds_json')
