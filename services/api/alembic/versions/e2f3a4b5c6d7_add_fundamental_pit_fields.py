"""add point-in-time lineage fields to fundamentals

Revision ID: e2f3a4b5c6d7
Revises: e1f2a3b4c5d6
Create Date: 2026-06-01

The backfill is intentionally conservative: it only fills NULL PIT fields from
already persisted source-document lineage and leaves unresolved legacy rows
NULL rather than inventing a publication date.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "e2f3a4b5c6d7"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fundamental_source_document", sa.Column("document_kind", sa.String(length=20), nullable=True))
    op.create_index("ix_fundamental_source_document_kind", "fundamental_source_document", ["document_kind"])

    op.add_column("fundamental_annual_metric", sa.Column("as_of_date", sa.Date(), nullable=True))
    op.add_column("fundamental_annual_metric", sa.Column("source_document_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_fundamental_annual_metric_source_document",
        "fundamental_annual_metric",
        "fundamental_source_document",
        ["source_document_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_fundamental_annual_metric_symbol_asof",
        "fundamental_annual_metric",
        ["symbol", "as_of_date"],
    )

    op.add_column("fundamental_latest_snapshot", sa.Column("as_of_date", sa.Date(), nullable=True))
    op.add_column("fundamental_latest_snapshot", sa.Column("source_document_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_fundamental_latest_snapshot_source_document",
        "fundamental_latest_snapshot",
        "fundamental_source_document",
        ["source_document_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_fundamental_latest_snapshot_symbol_asof",
        "fundamental_latest_snapshot",
        ["symbol", "as_of_date"],
    )

    op.execute(
        sa.text(
            """
            UPDATE fundamental_source_document
            SET document_kind = CASE
                WHEN upper(coalesce(raw_json->>'Document_Kind', raw_json->>'document_kind', '')) IN ('RFA', 'CP')
                    THEN upper(coalesce(raw_json->>'Document_Kind', raw_json->>'document_kind'))
                WHEN lower(coalesce(raw_json->>'Document_Kind', raw_json->>'document_kind', '')) = 'notice'
                    THEN 'notice'
                WHEN lower(coalesce(document_title, '') || ' ' || coalesce(source_url, '')) LIKE '%rapport financier annuel%'
                    OR lower(coalesce(document_title, '') || ' ' || coalesce(source_url, '')) LIKE '%rapport annuel%'
                    OR lower(coalesce(document_title, '') || ' ' || coalesce(source_url, '')) LIKE '%/rfa%'
                    OR lower(coalesce(document_title, '') || ' ' || coalesce(source_url, '')) LIKE '%rfa%'
                    THEN 'RFA'
                WHEN lower(coalesce(document_title, '') || ' ' || coalesce(source_url, '')) LIKE '%communique%'
                    OR lower(coalesce(document_title, '') || ' ' || coalesce(source_url, '')) LIKE '%communiqu%'
                    OR lower(coalesce(document_title, '') || ' ' || coalesce(source_url, '')) LIKE '%/cp%'
                    THEN 'CP'
                WHEN lower(coalesce(document_title, '') || ' ' || coalesce(source_url, '')) LIKE '%notice%'
                    THEN 'notice'
                ELSE NULL
            END
            WHERE document_kind IS NULL
            """
        )
    )

    op.execute(
        sa.text(
            """
            WITH candidates AS (
                SELECT
                    am.id AS annual_metric_id,
                    sd.id AS source_document_id,
                    sd.publication_date AS as_of_date,
                    row_number() OVER (
                        PARTITION BY am.id
                        ORDER BY
                            CASE upper(coalesce(sd.document_kind, ''))
                                WHEN 'RFA' THEN 3
                                WHEN 'CP' THEN 2
                                WHEN 'NOTICE' THEN 1
                                ELSE 0
                            END DESC,
                            sd.extracted_field_count DESC,
                            sd.publication_date DESC NULLS LAST,
                            sd.id DESC
                    ) AS rn
                FROM fundamental_annual_metric am
                JOIN fundamental_period_metric pm
                  ON pm.import_id = am.import_id
                 AND pm.symbol = am.symbol
                 AND pm.fiscal_year = am.statement_year
                 AND pm.metric_name = am.metric_name
                JOIN fundamental_source_document sd
                  ON sd.id = pm.source_document_id
                WHERE (am.as_of_date IS NULL OR am.source_document_id IS NULL)
                  AND sd.publication_date IS NOT NULL
            )
            UPDATE fundamental_annual_metric am
            SET
                as_of_date = COALESCE(am.as_of_date, candidates.as_of_date),
                source_document_id = COALESCE(am.source_document_id, candidates.source_document_id)
            FROM candidates
            WHERE am.id = candidates.annual_metric_id
              AND candidates.rn = 1
            """
        )
    )

    op.execute(
        sa.text(
            """
            WITH candidates AS (
                SELECT
                    snap.id AS snapshot_id,
                    sd.id AS source_document_id,
                    sd.publication_date AS as_of_date,
                    row_number() OVER (
                        PARTITION BY snap.id
                        ORDER BY
                            sd.publication_date DESC NULLS LAST,
                            CASE upper(coalesce(sd.document_kind, ''))
                                WHEN 'RFA' THEN 3
                                WHEN 'CP' THEN 2
                                WHEN 'NOTICE' THEN 1
                                ELSE 0
                            END DESC,
                            sd.extracted_field_count DESC,
                            sd.id DESC
                    ) AS rn
                FROM fundamental_latest_snapshot snap
                JOIN fundamental_source_document sd
                  ON sd.import_id = snap.import_id
                 AND sd.symbol = snap.symbol
                WHERE (snap.as_of_date IS NULL OR snap.source_document_id IS NULL)
                  AND sd.publication_date IS NOT NULL
                  AND (
                      snap.latest_statement_year IS NULL
                      OR sd.fiscal_year = snap.latest_statement_year
                  )
            )
            UPDATE fundamental_latest_snapshot snap
            SET
                as_of_date = COALESCE(snap.as_of_date, candidates.as_of_date),
                source_document_id = COALESCE(snap.source_document_id, candidates.source_document_id)
            FROM candidates
            WHERE snap.id = candidates.snapshot_id
              AND candidates.rn = 1
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_fundamental_latest_snapshot_symbol_asof", table_name="fundamental_latest_snapshot")
    op.drop_constraint(
        "fk_fundamental_latest_snapshot_source_document",
        "fundamental_latest_snapshot",
        type_="foreignkey",
    )
    op.drop_column("fundamental_latest_snapshot", "source_document_id")
    op.drop_column("fundamental_latest_snapshot", "as_of_date")

    op.drop_index("ix_fundamental_annual_metric_symbol_asof", table_name="fundamental_annual_metric")
    op.drop_constraint(
        "fk_fundamental_annual_metric_source_document",
        "fundamental_annual_metric",
        type_="foreignkey",
    )
    op.drop_column("fundamental_annual_metric", "source_document_id")
    op.drop_column("fundamental_annual_metric", "as_of_date")

    op.drop_index("ix_fundamental_source_document_kind", table_name="fundamental_source_document")
    op.drop_column("fundamental_source_document", "document_kind")
