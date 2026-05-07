"""add wfo signal summary tables

Revision ID: a6451325b021
Revises: j0k1l2m3n4o
Create Date: 2026-04-15 09:48:29.589289

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a6451325b021'
down_revision: Union[str, Sequence[str], None] = 'j0k1l2m3n4o'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'wfo_signal_summary',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('symbol', sa.String(), nullable=False),
        sa.Column('category', sa.String(length=32), nullable=False),
        sa.Column('horizon', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('score_pct', sa.Float(), nullable=True),
        sa.Column('signal_label', sa.String(length=60), nullable=True),
        sa.Column('representatives_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('wfe_pct', sa.Float(), nullable=True),
        sa.Column('robustness_ratio', sa.Float(), nullable=True),
        sa.Column('total_folds', sa.Integer(), nullable=True),
        sa.Column('profitable_folds', sa.Integer(), nullable=True),
        sa.Column('mean_oos_sharpe', sa.Float(), nullable=True),
        sa.Column('total_oos_pnl', sa.Float(), nullable=True),
        sa.Column('worst_fold_drawdown', sa.Float(), nullable=True),
        sa.Column('composite_score', sa.Float(), nullable=True),
        sa.Column('robustness_grade', sa.String(length=2), nullable=True),
        sa.Column('computed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('data_as_of', sa.Date(), nullable=True),
        sa.Column('compute_seconds', sa.Float(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('symbol', 'category', 'horizon', name='uq_wfo_signal_summary_sym_cat_hz'),
    )
    op.create_index('ix_wfo_signal_summary_symbol_horizon', 'wfo_signal_summary', ['symbol', 'horizon'], unique=False)
    op.create_index('ix_wfo_signal_summary_status', 'wfo_signal_summary', ['status'], unique=False)

    op.create_table(
        'wfo_global_signal',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('symbol', sa.String(), nullable=False),
        sa.Column('horizon', sa.String(length=16), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('global_score_pct', sa.Float(), nullable=True),
        sa.Column('raw_score_pct', sa.Float(), nullable=True),
        sa.Column('signal_label', sa.String(length=60), nullable=True),
        sa.Column('recommendation', sa.String(length=32), nullable=True),
        sa.Column('weight_tendance', sa.Float(), nullable=True),
        sa.Column('weight_momentum', sa.Float(), nullable=True),
        sa.Column('weight_oscillation', sa.Float(), nullable=True),
        sa.Column('weight_volume', sa.Float(), nullable=True),
        sa.Column('sr_modifier', sa.Float(), nullable=True),
        sa.Column('sr_support_level', sa.Float(), nullable=True),
        sa.Column('sr_resistance_level', sa.Float(), nullable=True),
        sa.Column('sr_support_method', sa.String(length=40), nullable=True),
        sa.Column('sr_resistance_method', sa.String(length=40), nullable=True),
        sa.Column('sr_distance_support_atr', sa.Float(), nullable=True),
        sa.Column('sr_distance_resistance_atr', sa.Float(), nullable=True),
        sa.Column('best_category', sa.String(length=32), nullable=True),
        sa.Column('best_category_score', sa.Float(), nullable=True),
        sa.Column('categories_viable', sa.Integer(), nullable=True),
        sa.Column('consensus_wfe_pct', sa.Float(), nullable=True),
        sa.Column('consensus_robustness', sa.Float(), nullable=True),
        sa.Column('computed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('data_as_of', sa.Date(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('symbol', 'horizon', name='uq_wfo_global_signal_sym_hz'),
    )
    op.create_index('ix_wfo_global_signal_symbol', 'wfo_global_signal', ['symbol'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_wfo_global_signal_symbol', table_name='wfo_global_signal')
    op.drop_table('wfo_global_signal')
    op.drop_index('ix_wfo_signal_summary_status', table_name='wfo_signal_summary')
    op.drop_index('ix_wfo_signal_summary_symbol_horizon', table_name='wfo_signal_summary')
    op.drop_table('wfo_signal_summary')
