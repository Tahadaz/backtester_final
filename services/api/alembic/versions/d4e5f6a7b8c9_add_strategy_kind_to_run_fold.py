"""add strategy_kind column and swap unique constraint on run_fold

Revision ID: d4e5f6a7b8c9
Revises: b2c3d4e5f6a7
Create Date: 2026-03-09 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add strategy_kind as nullable first (safe for existing rows)
    op.add_column('run_fold', sa.Column('strategy_kind', sa.String(128), nullable=True))

    # 2. Backfill from fold_metrics_json — existing rows carry strategy_kind there
    op.execute(
        "UPDATE run_fold SET strategy_kind = COALESCE(fold_metrics_json->>'strategy_kind', '') "
        "WHERE strategy_kind IS NULL"
    )

    # 3. Set NOT NULL + default
    op.alter_column('run_fold', 'strategy_kind', nullable=False, server_default='')

    # 4. Drop old unique constraint (run_id, fold_index)
    op.drop_constraint('uq_run_fold_run_index', 'run_fold', type_='unique')

    # 5. Add new unique constraint (run_id, strategy_kind, fold_index)
    op.create_unique_constraint(
        'uq_run_fold_run_sk_index',
        'run_fold',
        ['run_id', 'strategy_kind', 'fold_index']
    )


def downgrade() -> None:
    # Reverse: drop new constraint → restore old constraint → drop column
    op.drop_constraint('uq_run_fold_run_sk_index', 'run_fold', type_='unique')

    op.create_unique_constraint(
        'uq_run_fold_run_index',
        'run_fold',
        ['run_id', 'fold_index']
    )

    op.drop_column('run_fold', 'strategy_kind')
