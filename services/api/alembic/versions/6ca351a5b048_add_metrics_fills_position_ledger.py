"""add metrics fills position_ledger

Revision ID: 6ca351a5b048
Revises: fddaff4e1b7a
Create Date: 2026-02-16 10:32:21.913985

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '6ca351a5b048'
down_revision: Union[str, Sequence[str], None] = 'fddaff4e1b7a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'run_metric',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.Column('symbol', sa.String(), nullable=False),
        sa.Column('metric_name', sa.String(), nullable=False),
        sa.Column('metric_value', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['run.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('run_id', 'symbol', 'metric_name', name='uq_run_metric_run_id_symbol_metric_name'),
    )

    op.create_table(
        'fill',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('symbol', sa.String(), nullable=False),
        sa.Column('side', sa.String(), nullable=False),
        sa.Column('qty', sa.Float(), nullable=False),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('fees', sa.Float(), nullable=False),
        sa.Column('notional', sa.Float(), nullable=False),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(['run_id'], ['run.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_fill_run_id_timestamp', 'fill', ['run_id', 'timestamp'], unique=False)
    op.create_index('ix_fill_run_id_symbol_timestamp', 'fill', ['run_id', 'symbol', 'timestamp'], unique=False)

    op.create_table(
        'position_ledger',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('run_id', sa.UUID(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('symbol', sa.String(), nullable=False),
        sa.Column('available_qty', sa.Float(), nullable=False),
        sa.Column('cmp', sa.Float(), nullable=False),
        sa.Column('position_value_cost', sa.Float(), nullable=False),
        sa.Column('pnl_realise', sa.Float(), nullable=False),
        sa.Column('pnl_latent', sa.Float(), nullable=False),
        sa.Column('mark_price', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['run.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_position_ledger_run_id_timestamp', 'position_ledger', ['run_id', 'timestamp'], unique=False)
    op.create_index('ix_position_ledger_run_id_symbol_timestamp', 'position_ledger', ['run_id', 'symbol', 'timestamp'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_position_ledger_run_id_symbol_timestamp', table_name='position_ledger')
    op.drop_index('ix_position_ledger_run_id_timestamp', table_name='position_ledger')
    op.drop_table('position_ledger')

    op.drop_index('ix_fill_run_id_symbol_timestamp', table_name='fill')
    op.drop_index('ix_fill_run_id_timestamp', table_name='fill')
    op.drop_table('fill')

    op.drop_table('run_metric')
