"""Merge SFC and ValueStrat heads

Revision ID: 6039f1ec4937
Revises: sfc20260706, valuestrat20260706
Create Date: 2026-07-07 11:44:12.930511

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6039f1ec4937'
down_revision: Union[str, Sequence[str], None] = ('sfc20260706', 'valuestrat20260706')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
