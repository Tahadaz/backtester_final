"""implement the PIT portfolio Revision 5 ledger contract

Revision ID: b4c8e2f6a913
Revises: a3f7d9e1b402
"""

from __future__ import annotations

import json
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b4c8e2f6a913"
down_revision: Union[str, Sequence[str], None] = "a3f7d9e1b402"
branch_labels = None
depends_on = None

V4_FALLBACK_VERSION = "pit-dashboard-opportunity-portfolio-edge-policy-v4"
STATUSES = (
    "no_price_data",
    "no_score_data",
    "stale_score",
    "insufficient_history",
    "evidence_unavailable",
    "evaluated",
)
CATEGORIES = ("tendance", "momentum", "oscillation", "volume")


def _json_type() -> sa.types.TypeEngine[Any]:
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return dict(value) if isinstance(value, dict) else {}


def _sequence(value: Any) -> list[Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    return list(value) if isinstance(value, (list, tuple)) else []


def _legacy_decision(opportunity: Any, rank: Any) -> dict[str, Any]:
    payload = _mapping(opportunity)
    provenance = _mapping(payload.get("provenance"))
    evidence = {**provenance, "evidence_source": "legacy_provenance", "legacy_backfill": True}
    return {
        "status": "evaluated",
        "signal_direction": payload.get("direction"),
        "actionable": True,
        "actionability_reasons": [],
        "rank": _sequence(rank),
        "category_scores": {key: "unavailable" for key in CATEGORIES},
        "aggregate_score": None,
        "bucket": payload.get("bucket"),
        "computation_rejection_reasons": [],
        "execution_eligible": True,
        "execution_rejection_reason": None,
        "evidence": evidence,
    }


def upgrade() -> None:
    op.add_column("historical_trade_opportunity", sa.Column("methodology_version", sa.String(80), nullable=True))
    op.add_column("historical_trade_opportunity", sa.Column("status", sa.String(32), nullable=True))
    op.add_column(
        "historical_trade_opportunity",
        sa.Column("actionable", sa.Boolean(), nullable=True, server_default=sa.false()),
    )
    op.add_column(
        "historical_trade_opportunity",
        sa.Column("reconstructed_dashboard_winner", sa.Boolean(), nullable=True, server_default=sa.false()),
    )
    op.add_column("historical_trade_opportunity", sa.Column("decision_json", _json_type(), nullable=True))

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT o.id, o.rank_json, o.opportunity_json, r.methodology_version
            FROM historical_trade_opportunity AS o
            LEFT JOIN historical_opportunity_materialization_run AS r
              ON r.id = o.materialization_run_id
            """
        )
    ).mappings()
    update = sa.text(
        """
        UPDATE historical_trade_opportunity
        SET methodology_version=:methodology_version,
            status='evaluated', actionable=:actionable,
            reconstructed_dashboard_winner=:winner,
            decision_json=:decision_json
        WHERE id=:id
        """
    ).bindparams(sa.bindparam("decision_json", type_=_json_type()))
    for row in rows:
        connection.execute(
            update,
            {
                "id": row["id"],
                "methodology_version": row["methodology_version"] or V4_FALLBACK_VERSION,
                "actionable": True,
                "winner": False,
                "decision_json": _legacy_decision(row["opportunity_json"], row["rank_json"]),
            },
        )

    status_values = ",".join(f"'{value}'" for value in STATUSES)
    with op.batch_alter_table("historical_trade_opportunity") as batch:
        batch.drop_constraint("uq_historical_trade_opportunity_key", type_="unique")
        batch.alter_column("methodology_version", existing_type=sa.String(80), nullable=False)
        batch.alter_column("status", existing_type=sa.String(32), nullable=False)
        batch.alter_column("actionable", existing_type=sa.Boolean(), nullable=False, server_default=sa.false())
        batch.alter_column(
            "reconstructed_dashboard_winner",
            existing_type=sa.Boolean(), nullable=False, server_default=sa.false(),
        )
        batch.alter_column("decision_json", existing_type=_json_type(), nullable=False)
        batch.alter_column("opportunity_json", existing_type=_json_type(), nullable=True)
        batch.create_unique_constraint(
            "uq_historical_trade_opportunity_key",
            ["methodology_version", "decision_date", "symbol", "horizon", "variant"],
        )
        batch.create_check_constraint(
            "ck_historical_trade_opportunity_status", f"status IN ({status_values})",
        )

    op.create_index(
        "ix_historical_trade_opportunity_methodology_version",
        "historical_trade_opportunity", ["methodology_version"],
    )
    op.create_index("ix_historical_trade_opportunity_status", "historical_trade_opportunity", ["status"])
    op.create_index("ix_historical_trade_opportunity_actionable", "historical_trade_opportunity", ["actionable"])
    op.create_index(
        "ix_historical_trade_opportunity_winner_date",
        "historical_trade_opportunity", ["reconstructed_dashboard_winner", "decision_date"],
    )


def downgrade() -> None:
    # Revision 4 cannot represent grid/audit rows. Preserve the rows it can
    # deserialize, then restore its original natural key and non-null payload.
    connection = op.get_bind()
    connection.execute(sa.text("DELETE FROM historical_trade_opportunity WHERE opportunity_json IS NULL"))
    connection.execute(
        sa.text(
            """
            DELETE FROM historical_trade_opportunity
            WHERE id NOT IN (
                SELECT MIN(id) FROM historical_trade_opportunity
                GROUP BY decision_date, symbol, horizon, variant
            )
            """
        )
    )
    op.drop_index("ix_historical_trade_opportunity_winner_date", table_name="historical_trade_opportunity")
    op.drop_index("ix_historical_trade_opportunity_actionable", table_name="historical_trade_opportunity")
    op.drop_index("ix_historical_trade_opportunity_status", table_name="historical_trade_opportunity")
    op.drop_index("ix_historical_trade_opportunity_methodology_version", table_name="historical_trade_opportunity")
    with op.batch_alter_table("historical_trade_opportunity") as batch:
        batch.drop_constraint("ck_historical_trade_opportunity_status", type_="check")
        batch.drop_constraint("uq_historical_trade_opportunity_key", type_="unique")
        batch.alter_column("opportunity_json", existing_type=_json_type(), nullable=False)
        batch.create_unique_constraint(
            "uq_historical_trade_opportunity_key", ["decision_date", "symbol", "horizon", "variant"],
        )
        batch.drop_column("decision_json")
        batch.drop_column("reconstructed_dashboard_winner")
        batch.drop_column("actionable")
        batch.drop_column("status")
        batch.drop_column("methodology_version")
