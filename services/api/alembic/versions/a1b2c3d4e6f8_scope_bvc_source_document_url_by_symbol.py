"""scope BVC source document URL uniqueness by symbol

Revision ID: a1b2c3d4e6f8
Revises: z9y8x7w6v5u4
Create Date: 2026-06-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "a1b2c3d4e6f8"
down_revision = "z9y8x7w6v5u4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_fundamental_source_document_import_url",
        "fundamental_source_document",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_fundamental_source_document_import_url_symbol",
        "fundamental_source_document",
        ["import_id", "source_url", "symbol"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_fundamental_source_document_import_url_symbol",
        "fundamental_source_document",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_fundamental_source_document_import_url",
        "fundamental_source_document",
        ["import_id", "source_url"],
    )
