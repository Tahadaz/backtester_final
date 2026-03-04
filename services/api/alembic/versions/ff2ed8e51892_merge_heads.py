"""merge heads

Revision ID: ff2ed8e51892
Revises: f1a2b3c4d5e6, 3c1a9f2d8e47
Create Date: 2026-03-03 20:35:14.437142

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ff2ed8e51892'
down_revision: Union[str, Sequence[str], None] = ('f1a2b3c4d5e6', '3c1a9f2d8e47')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
