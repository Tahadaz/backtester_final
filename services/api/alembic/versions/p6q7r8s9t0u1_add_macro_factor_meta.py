"""add macro_factor_meta table + index_master.market_region

Revision ID: p6q7r8s9t0u1
Revises: o5p6q7r8s9t0
Create Date: 2026-05-05 12:00:00.000000

Changes:
  1. CREATE TABLE macro_factor_meta (14-row seed: VIX, SP500, NDX, N225, CAC,
     FTSE, BRENT, GOLD, SILVER, DXY, EURUSD, AED, US10Y, BTC).
  2. ADD COLUMN index_master.market_region TEXT NULL;
     BACKFILL all existing rows to 'masi' (all current indices are Moroccan).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "p6q7r8s9t0u1"
down_revision: Union[str, None] = "o5p6q7r8s9t0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ---------------------------------------------------------------------------
# Seed data — reconciled with core/quant_core/macro.py canonical_id values
# ---------------------------------------------------------------------------
_SEED_FACTORS = [
    # canonical_id   yahoo_ticker     display_name                         asset_type    market_region
    ("VIX",    "^VIX",      "CBOE Volatility Index",                      "equity",     "us"),
    ("SP500",  "^GSPC",     "S&P 500",                                    "equity",     "us"),
    ("NDX",    "^NDX",      "NASDAQ-100",                                  "equity",     "us"),
    ("N225",   "^N225",     "Nikkei 225",                                  "equity",     "asian"),
    ("CAC",    "^FCHI",     "CAC 40",                                      "equity",     "european"),
    ("FTSE",   "^FTSE",     "FTSE 100",                                    "equity",     "european"),
    ("BRENT",  "BZ=F",      "Brent Crude (futures)",                       "commodity",  None),
    ("GOLD",   "GC=F",      "Gold (futures)",                              "commodity",  None),
    ("SILVER", "SI=F",      "Silver (futures)",                            "commodity",  None),
    ("DXY",    "DX-Y.NYB",  "US Dollar Index",                             "forex",      None),
    ("EURUSD", "EURUSD=X",  "EUR/USD",                                     "forex",      None),
    ("AED",    "AED=X",     "AED/USD (MAD peg proxy)",                     "forex",      None),
    ("US10Y",  "^TNX",      "10-Year US Treasury Yield",                   "bond",       None),
    ("BTC",    "BTC-USD",   "Bitcoin",                                     "crypto",     None),
]


def upgrade() -> None:
    # ── 1. Create macro_factor_meta ──────────────────────────────────────────
    op.create_table(
        "macro_factor_meta",
        sa.Column("canonical_id",  sa.String(),  primary_key=True),
        sa.Column("yahoo_ticker",  sa.String(),  nullable=False, unique=True),
        sa.Column("display_name",  sa.String(),  nullable=False),
        sa.Column("asset_type",    sa.String(),  nullable=False),
        sa.Column("market_region", sa.String(),  nullable=True),
        sa.Column("active",        sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("added_via",     sa.String(),  nullable=False, server_default="system"),
        sa.Column("created_at",    sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("notes",         sa.Text(),    nullable=True),
    )
    op.create_index("ix_macro_factor_meta_active",     "macro_factor_meta", ["active"])
    op.create_index("ix_macro_factor_meta_asset_type", "macro_factor_meta", ["asset_type"])

    # ── 2. Seed 14 rows ──────────────────────────────────────────────────────
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "INSERT INTO macro_factor_meta "
            "(canonical_id, yahoo_ticker, display_name, asset_type, market_region, active, added_via) "
            "VALUES (:cid, :ticker, :name, :at, :mr, true, 'system') "
            "ON CONFLICT (canonical_id) DO NOTHING"
        ),
        [
            {"cid": cid, "ticker": ticker, "name": name, "at": at, "mr": mr}
            for cid, ticker, name, at, mr in _SEED_FACTORS
        ],
    )

    # ── 3. Add market_region to index_master ─────────────────────────────────
    op.add_column(
        "index_master",
        sa.Column("market_region", sa.String(), nullable=True),
    )
    # All current tracked indices are Moroccan
    conn.execute(
        sa.text("UPDATE index_master SET market_region = 'masi' WHERE market_region IS NULL")
    )


def downgrade() -> None:
    op.drop_column("index_master", "market_region")
    op.drop_index("ix_macro_factor_meta_asset_type", table_name="macro_factor_meta")
    op.drop_index("ix_macro_factor_meta_active",     table_name="macro_factor_meta")
    op.drop_table("macro_factor_meta")
