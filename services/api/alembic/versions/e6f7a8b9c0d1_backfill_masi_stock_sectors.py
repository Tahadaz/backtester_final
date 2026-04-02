"""backfill MASI stock_master sectors

Revision ID: e6f7a8b9c0d1
Revises: c1d2e3f4a5b6
Create Date: 2026-03-26 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE stock_master
        SET sector = CASE symbol
            WHEN 'ADH' THEN 'Immobilier'
            WHEN 'ADI' THEN 'Immobilier'
            WHEN 'AKT' THEN 'Santé'
            WHEN 'ATW' THEN 'Banques'
            WHEN 'BCP' THEN 'Banques'
            WHEN 'CAP' THEN 'Sociétés de financement'
            WHEN 'CDM' THEN 'Banques'
            WHEN 'CFG' THEN 'Banques'
            WHEN 'CSR' THEN 'Agroalimentaire'
            WHEN 'GTM' THEN 'BTP'
            WHEN 'IAM' THEN 'Télécommunications'
            WHEN 'JET' THEN 'BTP'
            WHEN 'LHM' THEN 'BTP'
            WHEN 'MSA' THEN 'Transport'
            WHEN 'SNA' THEN 'Distribution'
            WHEN 'TGC' THEN 'BTP'
            WHEN 'VCN' THEN 'Santé'
            ELSE sector
        END
        WHERE (sector IS NULL OR btrim(sector) = '')
          AND symbol IN (
            'ADH', 'ADI', 'AKT', 'ATW', 'BCP', 'CAP', 'CDM', 'CFG', 'CSR',
            'GTM', 'IAM', 'JET', 'LHM', 'MSA', 'SNA', 'TGC', 'VCN'
          )
        """
    )


def downgrade() -> None:
    # Data backfill only; keep enriched sector values on downgrade.
    pass
