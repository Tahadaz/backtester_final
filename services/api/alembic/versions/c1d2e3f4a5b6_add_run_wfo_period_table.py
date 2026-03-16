"""add run_wfo_period table

Revision ID: c1d2e3f4a5b6
Revises: d4e5f6a7b8c9
Create Date: 2026-03-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'run_wfo_period',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('run_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('symbol', sa.String(), nullable=False),
        sa.Column('strategy_kind', sa.String(length=128), nullable=False),
        sa.Column('horizon', sa.String(length=32), nullable=True),
        sa.Column('fold_no', sa.Integer(), nullable=False),
        sa.Column('train_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('train_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('test_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('test_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('winning_trial_id', sa.String(), nullable=False),
        sa.Column('optimal_params_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default='{}'),
        sa.Column('is_objective_name', sa.String(), nullable=True),
        sa.Column('is_objective_value', sa.Float(), nullable=True),
        sa.Column('oos_pnl', sa.Float(), nullable=True),
        sa.Column('oos_return', sa.Float(), nullable=True),
        sa.Column('oos_cagr', sa.Float(), nullable=True),
        sa.Column('oos_sharpe', sa.Float(), nullable=True),
        sa.Column('oos_max_drawdown', sa.Float(), nullable=True),
        sa.Column('oos_win_pct', sa.Float(), nullable=True),
        sa.Column('oos_n_fills', sa.Integer(), nullable=True),
        sa.Column('cumulative_oos_pnl', sa.Float(), nullable=True),
        sa.Column('is_holdout', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['run_id'], ['run.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('run_id', 'symbol', 'strategy_kind', 'horizon', 'fold_no',
                            name='uq_run_wfo_period_run_sk_horizon_fold'),
    )
    op.create_index('ix_run_wfo_period_run_id', 'run_wfo_period', ['run_id'])


def downgrade() -> None:
    op.drop_index('ix_run_wfo_period_run_id', table_name='run_wfo_period')
    op.drop_table('run_wfo_period')
