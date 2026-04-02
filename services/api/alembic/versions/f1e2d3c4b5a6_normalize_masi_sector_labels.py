"""normalize MASI sector labels to concise UI names

Revision ID: f1e2d3c4b5a6
Revises: e6f7a8b9c0d1
Create Date: 2026-03-26 13:20:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "f1e2d3c4b5a6"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE stock_master
        SET sector = CASE sector
            WHEN 'Participation et promotion immobilières' THEN 'Immobilier'
            WHEN 'Sociétés de financement et Autres Activités Financières' THEN 'Sociétés de financement'
            WHEN 'Agroalimentaire et Production' THEN 'Agroalimentaire'
            WHEN 'Bâtiment et Matériaux de Construction' THEN 'BTP'
            WHEN 'Services de transport' THEN 'Transport'
            WHEN 'Distributeurs' THEN 'Distribution'
            WHEN 'Logiciels et Services Informatiques' THEN 'Informatique'
            WHEN 'Ingénieries et Biens d''Équipement Industriels' THEN 'Industrie'
            WHEN 'Pétrole et Gaz' THEN 'Énergie'
            WHEN 'Services aux collectivités' THEN 'Services publics'
            WHEN 'Loisirs et Hôtels' THEN 'Loisirs & Hôtels'
            ELSE sector
        END
        WHERE sector IN (
            'Participation et promotion immobilières',
            'Sociétés de financement et Autres Activités Financières',
            'Agroalimentaire et Production',
            'Bâtiment et Matériaux de Construction',
            'Services de transport',
            'Distributeurs',
            'Logiciels et Services Informatiques',
            'Ingénieries et Biens d''Équipement Industriels',
            'Pétrole et Gaz',
            'Services aux collectivités',
            'Loisirs et Hôtels'
        )
        """
    )


def downgrade() -> None:
    # Keep concise labels on downgrade.
    pass
