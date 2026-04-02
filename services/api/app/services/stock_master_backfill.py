from __future__ import annotations

from sqlalchemy.orm import Session

from services.api.app import models
from services.api.app.masi_tickers import get_masi_info


def backfill_masi_sectors(db: Session) -> int:
    """Populate missing stock_master.sector values for tracked MASI symbols.

    The backfill is intentionally conservative:
    - only updates rows with NULL/blank sector
    - only updates symbols present in the MASI registry
    - never creates new rows
    """

    rows = (
        db.query(models.StockMaster)
        .filter(
            (models.StockMaster.sector.is_(None)) | (models.StockMaster.sector == "")
        )
        .order_by(models.StockMaster.symbol.asc())
        .all()
    )

    updated = 0
    for stock in rows:
        masi_info = get_masi_info(stock.symbol)
        if not masi_info:
            continue
        sector = (masi_info.get("sector") or "").strip()
        if not sector:
            continue
        stock.sector = sector
        updated += 1

    if updated:
        db.commit()

    return updated
