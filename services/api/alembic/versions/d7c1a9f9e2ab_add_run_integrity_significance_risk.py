"""add run integrity, fold, significance, and risk tables

Revision ID: d7c1a9f9e2ab
Revises: b3d9c4f7e821
Create Date: 2026-02-25 14:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "d7c1a9f9e2ab"
down_revision: Union[str, Sequence[str], None] = "b3d9c4f7e821"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("run", sa.Column("mode", sa.String(), nullable=False, server_default="single"))
    op.add_column("run", sa.Column("seed", sa.Integer(), nullable=True))
    op.add_column("run", sa.Column("dataset_hash", sa.String(), nullable=True))
    op.add_column("run", sa.Column("code_version", sa.String(), nullable=True))
    op.add_column("run", sa.Column("integrity_status", sa.String(), nullable=True))

    op.create_index("ix_run_mode_created_at", "run", ["mode", "created_at"], unique=False)
    op.create_index("ix_run_integrity_status", "run", ["integrity_status"], unique=False)

    op.execute(
        """
        update run
        set mode = case
          when coalesce((spec_json #>> '{optimization,walk_forward,enabled}')::boolean, false)
          then 'walk_forward'
          else 'single'
        end
        """
    )

    op.execute(
        """
        update run
        set seed = case
          when (spec_json #>> '{optimization,seed}') ~ '^-?[0-9]+$'
          then (spec_json #>> '{optimization,seed}')::int
          else null
        end
        """
    )

    op.execute(
        """
        update run r
        set dataset_hash = d.data_hash
        from dataset d
        where r.dataset_id = d.id
        """
    )

    op.execute(
        """
        update run
        set code_version = coalesce(nullif(git_commit, ''), nullif(engine_version, ''))
        """
    )

    op.create_table(
        "run_integrity_check",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("check_name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("details_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "check_name", name="uq_run_integrity_check_run_name"),
    )
    op.create_index("ix_run_integrity_check_run_id", "run_integrity_check", ["run_id"], unique=False)

    op.create_table(
        "run_fold",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("fold_index", sa.Integer(), nullable=False),
        sa.Column("train_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("train_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("test_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("test_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fold_metrics_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("fold_artifacts", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "fold_index", name="uq_run_fold_run_index"),
    )
    op.create_index("ix_run_fold_run_id", "run_fold", ["run_id"], unique=False)

    op.create_table(
        "run_significance",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("pvalue", sa.Float(), nullable=True),
        sa.Column("statistic", sa.Float(), nullable=True),
        sa.Column("mc_null_dist_ref", sa.String(), nullable=True),
        sa.Column("details_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "method", name="uq_run_significance_run_method"),
    )
    op.create_index("ix_run_significance_run_id", "run_significance", ["run_id"], unique=False)

    op.create_table(
        "run_risk",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("kelly_fraction", sa.Float(), nullable=True),
        sa.Column("half_kelly", sa.Float(), nullable=True),
        sa.Column("chosen_leverage", sa.Float(), nullable=True),
        sa.Column("mc_drawdown_pctl", sa.Float(), nullable=True),
        sa.Column("mc_var", sa.Float(), nullable=True),
        sa.Column("mc_cvar", sa.Float(), nullable=True),
        sa.Column("details_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["run_id"], ["run.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_run_risk_run_id"),
    )
    op.create_index("ix_run_risk_run_id", "run_risk", ["run_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_run_risk_run_id", table_name="run_risk")
    op.drop_table("run_risk")

    op.drop_index("ix_run_significance_run_id", table_name="run_significance")
    op.drop_table("run_significance")

    op.drop_index("ix_run_fold_run_id", table_name="run_fold")
    op.drop_table("run_fold")

    op.drop_index("ix_run_integrity_check_run_id", table_name="run_integrity_check")
    op.drop_table("run_integrity_check")

    op.drop_index("ix_run_integrity_status", table_name="run")
    op.drop_index("ix_run_mode_created_at", table_name="run")

    op.drop_column("run", "integrity_status")
    op.drop_column("run", "code_version")
    op.drop_column("run", "dataset_hash")
    op.drop_column("run", "seed")
    op.drop_column("run", "mode")
