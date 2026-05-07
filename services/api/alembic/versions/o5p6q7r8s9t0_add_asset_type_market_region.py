"""add asset_type and market_region to stock_master

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-04-30 00:00:00.000000

Adds two classification columns to stock_master:
  asset_type    - "equity" | "commodity" | "forex" | "bond"  (NOT NULL, default "equity")
  market_region - "masi" | "us" | "european" | "asian" | NULL

Backfill runs inside upgrade() using the same detect_asset_type() logic
from asset_taxonomy.py so it matches what the API computes at runtime.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "o5p6q7r8s9t0"
down_revision: Union[str, None] = "n4o5p6q7r8s9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stock_master",
        sa.Column("asset_type", sa.String(), nullable=False, server_default="equity"),
    )
    op.add_column(
        "stock_master",
        sa.Column("market_region", sa.String(), nullable=True),
    )

    # ── Backfill using detect_asset_type ─────────────────────────────────────
    # Import here so alembic env doesn't need the full app on its path.
    try:
        from app.asset_taxonomy import detect_asset_type
        from app.masi_tickers import is_masi_ticker
    except ImportError:
        # Fallback: import relative to services/api
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from app.asset_taxonomy import detect_asset_type
        from app.masi_tickers import is_masi_ticker

    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT symbol, track_source FROM stock_master")
    ).fetchall()

    for symbol, track_source in rows:
        asset_type, market_region = detect_asset_type(
            symbol,
            track_source=track_source,
            is_masi=is_masi_ticker(symbol),
        )
        conn.execute(
            sa.text(
                "UPDATE stock_master SET asset_type = :at, market_region = :mr"
                " WHERE symbol = :sym"
            ),
            {"at": asset_type, "mr": market_region, "sym": symbol},
        )


def downgrade() -> None:
    op.drop_column("stock_master", "market_region")
    op.drop_column("stock_master", "asset_type")
