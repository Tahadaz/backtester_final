"""add signal engine persistence and signal backtest tables

Revision ID: d1e2f3a4b5c6
Revises: c8673547d243
Create Date: 2026-04-20 00:00:00.000000

Adds 4 new tables:
  - signal_engine_family_result  : persisted A→G per-family results
  - signal_engine_global_result  : persisted A→G per-symbol aggregated scores
  - signal_backtest_run          : persisted signal-based backtest + Monte Carlo
  - signal_engine_batch_job      : tracks batch computation jobs
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'c8673547d243'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # signal_engine_family_result
    # One row per (symbol, family, horizon, variant).
    # Mirrors wfo_signal_summary in structure.
    # ------------------------------------------------------------------
    op.create_table(
        'signal_engine_family_result',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),

        # Natural key
        sa.Column('symbol', sa.String(), nullable=False),
        sa.Column('family', sa.String(32), nullable=False),
        sa.Column('category', sa.String(32), nullable=False),   # denormalized from CATEGORY_FAMILIES
        sa.Column('horizon', sa.String(16), nullable=False),
        sa.Column('variant', sa.String(16), nullable=False, server_default='expanded'),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),

        # Signal output
        sa.Column('family_score_pct', sa.Float(), nullable=True),
        sa.Column('signal_label', sa.String(60), nullable=True),

        # Representatives — committed variants used by backtest
        sa.Column('representatives_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default='[]'),

        # Full family snapshot — verbatim output of _build_family_snapshot(), used by export-scores.py
        sa.Column('family_detail_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        # Quality / selection counts
        sa.Column('tested_count', sa.Integer(), nullable=True),
        sa.Column('viable_count', sa.Integer(), nullable=True),
        sa.Column('competitive_count', sa.Integer(), nullable=True),
        sa.Column('representative_count', sa.Integer(), nullable=True),
        sa.Column('is_provisional', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('warning_message', sa.Text(), nullable=True),

        # Staleness
        sa.Column('input_hash', sa.String(64), nullable=True),  # SHA-256 of (data_as_of+cost_bps+cooldown_bars)

        # Metadata
        sa.Column('computed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('data_as_of', sa.Date(), nullable=True),
        sa.Column('compute_seconds', sa.Float(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),

        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('symbol', 'family', 'horizon', 'variant',
                            name='uq_sefr_sym_fam_hz_var'),
    )
    op.create_index('ix_sefr_symbol_horizon', 'signal_engine_family_result', ['symbol', 'horizon'])
    op.create_index('ix_sefr_category_horizon', 'signal_engine_family_result', ['category', 'horizon'])
    op.create_index('ix_sefr_status', 'signal_engine_family_result', ['status'])

    # ------------------------------------------------------------------
    # signal_engine_global_result
    # One row per (symbol, horizon, variant).
    # Aggregated global scores + per-category breakdown.
    # Mirrors wfo_global_signal in structure.
    # ------------------------------------------------------------------
    op.create_table(
        'signal_engine_global_result',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),

        sa.Column('symbol', sa.String(), nullable=False),
        sa.Column('horizon', sa.String(16), nullable=False),
        sa.Column('variant', sa.String(16), nullable=False, server_default='expanded'),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),

        # Aggregate scores (two variants: legacy 1-family/category, expanded up-to-5)
        sa.Column('aggregate_score_pct', sa.Float(), nullable=True),
        sa.Column('expanded_aggregate_score_pct', sa.Float(), nullable=True),
        sa.Column('signal_label', sa.String(60), nullable=True),

        # Per-category and per-family breakdowns (for DB-native API and export)
        sa.Column('per_category_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('per_family_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        # Technical levels + S/R — stored verbatim for export-scores.py compat
        sa.Column('technical_levels_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('support_resistance_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        sa.Column('computed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('data_as_of', sa.Date(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),

        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('symbol', 'horizon', 'variant', name='uq_segr_sym_hz_var'),
    )
    op.create_index('ix_segr_symbol', 'signal_engine_global_result', ['symbol'])
    op.create_index('ix_segr_horizon_status', 'signal_engine_global_result', ['horizon', 'status'])

    # ------------------------------------------------------------------
    # signal_backtest_run
    # One row per (symbol, horizon, source, scope, scope_key, variant, window_start, window_end).
    # Stores realized equity curve + Monte Carlo envelope.
    # ------------------------------------------------------------------
    op.create_table(
        'signal_backtest_run',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),

        # Natural key
        sa.Column('symbol', sa.String(), nullable=False),
        sa.Column('horizon', sa.String(16), nullable=False),
        sa.Column('source', sa.String(10), nullable=False),      # "engine" | "wfo"
        sa.Column('scope', sa.String(20), nullable=False),        # "per_category" | "global" | "combination"
        sa.Column('scope_key', sa.String(64), nullable=False),    # "tendance" | "global" | "tendance+momentum"
        sa.Column('variant', sa.String(16), nullable=False, server_default='expanded'),
        sa.Column('window_start', sa.Date(), nullable=False),
        sa.Column('window_end', sa.Date(), nullable=False),

        # Config (stored for reproducibility; not part of unique key → changes overwrite)
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('cost_bps', sa.Float(), nullable=False, server_default='5.0'),
        sa.Column('slippage_bps', sa.Float(), nullable=False, server_default='5.0'),
        sa.Column('side_policy', sa.String(16), nullable=False, server_default='long_only'),
        sa.Column('n_paths', sa.Integer(), nullable=False, server_default='2000'),
        sa.Column('mc_method', sa.String(20), nullable=False, server_default='block_bootstrap'),
        sa.Column('block_mean', sa.Integer(), nullable=True),     # null = auto

        # Realized backtest outputs
        sa.Column('n_bars', sa.Integer(), nullable=True),
        sa.Column('n_trades', sa.Integer(), nullable=True),
        sa.Column('equity_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),  # float[n_bars], start=1.0
        sa.Column('dates_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),   # "YYYY-MM-DD"[n_bars]

        # Denormalized metrics for fast filtering/sorting
        sa.Column('total_return', sa.Float(), nullable=True),
        sa.Column('cagr', sa.Float(), nullable=True),
        sa.Column('sharpe', sa.Float(), nullable=True),
        sa.Column('max_drawdown', sa.Float(), nullable=True),
        sa.Column('win_rate', sa.Float(), nullable=True),

        # Monte Carlo outputs
        # mc_envelope_json: {p05, p25, p50, p75, p95} each float[n_bars]
        sa.Column('mc_envelope_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        # mc_stats_json: {total_return/cagr/sharpe/max_drawdown: {p05,p50,p95}, var95, cvar95, prob_positive_terminal}
        sa.Column('mc_stats_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),

        # Staleness: SHA-256 of (representatives_json + data_as_of + cost_bps + slippage_bps + side_policy)
        sa.Column('input_hash', sa.String(64), nullable=True),

        sa.Column('computed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('data_as_of', sa.Date(), nullable=True),
        sa.Column('compute_seconds', sa.Float(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),

        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'symbol', 'horizon', 'source', 'scope', 'scope_key', 'variant',
            'window_start', 'window_end',
            name='uq_sbr_natural_key',
        ),
    )
    op.create_index('ix_sbr_symbol_horizon', 'signal_backtest_run', ['symbol', 'horizon'])
    op.create_index('ix_sbr_source_scope', 'signal_backtest_run', ['source', 'scope'])
    op.create_index('ix_sbr_status', 'signal_backtest_run', ['status'])
    op.create_index('ix_sbr_data_as_of', 'signal_backtest_run', ['data_as_of'])

    # ------------------------------------------------------------------
    # signal_engine_batch_job
    # Tracks batch computation jobs (signal engine or backtest) for a
    # (symbol, horizon) pair. Used for progress tracking and dedup.
    # UUID PK to match Run/StrategyBacktestRun convention.
    # ------------------------------------------------------------------
    op.create_table(
        'signal_engine_batch_job',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),

        sa.Column('symbol', sa.String(), nullable=False),
        sa.Column('horizon', sa.String(16), nullable=False),
        sa.Column('variant', sa.String(16), nullable=False, server_default='expanded'),
        sa.Column('job_type', sa.String(20), nullable=False),     # "signal_engine" | "signal_backtest"
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('rq_job_id', sa.String(), nullable=True),
        sa.Column('triggered_by', sa.String(32), nullable=True),  # "manual" | "market_refresh" | "scheduler"

        sa.Column('total_units', sa.Integer(), nullable=True),    # families (engine) or scopes (backtest)
        sa.Column('completed_units', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_units', sa.Integer(), nullable=False, server_default='0'),

        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),

        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_sebj_symbol_horizon_type', 'signal_engine_batch_job',
                    ['symbol', 'horizon', 'job_type'])
    op.create_index('ix_sebj_status', 'signal_engine_batch_job', ['status'])
    op.create_index('ix_sebj_created_at', 'signal_engine_batch_job', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_sebj_created_at', table_name='signal_engine_batch_job')
    op.drop_index('ix_sebj_status', table_name='signal_engine_batch_job')
    op.drop_index('ix_sebj_symbol_horizon_type', table_name='signal_engine_batch_job')
    op.drop_table('signal_engine_batch_job')

    op.drop_index('ix_sbr_data_as_of', table_name='signal_backtest_run')
    op.drop_index('ix_sbr_status', table_name='signal_backtest_run')
    op.drop_index('ix_sbr_source_scope', table_name='signal_backtest_run')
    op.drop_index('ix_sbr_symbol_horizon', table_name='signal_backtest_run')
    op.drop_table('signal_backtest_run')

    op.drop_index('ix_segr_horizon_status', table_name='signal_engine_global_result')
    op.drop_index('ix_segr_symbol', table_name='signal_engine_global_result')
    op.drop_table('signal_engine_global_result')

    op.drop_index('ix_sefr_status', table_name='signal_engine_family_result')
    op.drop_index('ix_sefr_category_horizon', table_name='signal_engine_family_result')
    op.drop_index('ix_sefr_symbol_horizon', table_name='signal_engine_family_result')
    op.drop_table('signal_engine_family_result')
