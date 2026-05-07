"""add variant column to wfo_signal_summary and wfo_global_signal

Revision ID: c8673547d243
Revises: b7562436c132
Create Date: 2026-04-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c8673547d243'
down_revision: Union[str, None] = 'b7562436c132'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # wfo_signal_summary
    op.add_column(
        'wfo_signal_summary',
        sa.Column('variant', sa.String(16), nullable=False, server_default='expanded'),
    )
    op.drop_constraint('uq_wfo_signal_summary_sym_cat_hz', 'wfo_signal_summary', type_='unique')
    op.create_unique_constraint(
        'uq_wfo_signal_summary_sym_cat_hz_var',
        'wfo_signal_summary',
        ['symbol', 'category', 'horizon', 'variant'],
    )

    # wfo_global_signal
    op.add_column(
        'wfo_global_signal',
        sa.Column('variant', sa.String(16), nullable=False, server_default='expanded'),
    )
    op.drop_constraint('uq_wfo_global_signal_sym_hz', 'wfo_global_signal', type_='unique')
    op.create_unique_constraint(
        'uq_wfo_global_signal_sym_hz_var',
        'wfo_global_signal',
        ['symbol', 'horizon', 'variant'],
    )


def downgrade() -> None:
    # wfo_global_signal
    op.drop_constraint('uq_wfo_global_signal_sym_hz_var', 'wfo_global_signal', type_='unique')
    op.create_unique_constraint(
        'uq_wfo_global_signal_sym_hz', 'wfo_global_signal', ['symbol', 'horizon'],
    )
    op.drop_column('wfo_global_signal', 'variant')

    # wfo_signal_summary
    op.drop_constraint('uq_wfo_signal_summary_sym_cat_hz_var', 'wfo_signal_summary', type_='unique')
    op.create_unique_constraint(
        'uq_wfo_signal_summary_sym_cat_hz', 'wfo_signal_summary',
        ['symbol', 'category', 'horizon'],
    )
    op.drop_column('wfo_signal_summary', 'variant')
