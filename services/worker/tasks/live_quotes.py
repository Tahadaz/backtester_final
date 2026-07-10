"""Controlled background refresh for cached live market quotes."""

from __future__ import annotations

import logging

from services.api.app.services.bourse_live_quotes import refresh_live_quotes
from services.worker.db import SessionLocal

logger = logging.getLogger(__name__)


def refresh_live_quotes_job(symbols: list[str] | None = None) -> dict:
    """Refresh supplied symbols, or the active equity universe when omitted."""
    from services.api.app.market_refresh_window import is_bourse_live_session

    if not is_bourse_live_session():
        return {"status": "skipped", "reason": "market_closed", "requested": 0}
    if symbols is None:
        from services.api.app import models

        db = SessionLocal()
        try:
            symbols = [
                str(row[0]).upper()
                for row in db.query(models.StockMaster.symbol)
                .filter(models.StockMaster.is_active.is_(True))
                .all()
            ]
        finally:
            db.close()
    result = refresh_live_quotes(symbols or [], session_factory=SessionLocal, persist_history=True)
    logger.info("Live quote refresh complete: %s", result)
    return result
