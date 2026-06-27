"""merge 2 heads into single tip

Two independent migration lines (d8e9f0a1b2c3 "update cost of equity floor for
brief 39" and g8h9i0j1k2l3 "add signal best evidence snapshot") accumulated during
parallel development on the feature/fundamental-ui-consolidation branch.  This merge
revision is schema-no-op (empty upgrade/downgrade) and exists solely to reunify the
lineage so that `alembic upgrade head` is unambiguous on a fresh database.

Revision ID: 356fb5ece35b
Revises: d8e9f0a1b2c3, g8h9i0j1k2l3
Create Date: 2026-06-23 20:07:12.598244

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '356fb5ece35b'
down_revision: Union[str, Sequence[str], None] = ('d8e9f0a1b2c3', 'g8h9i0j1k2l3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
