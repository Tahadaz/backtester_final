"""
Quarterly Factor Selection Trigger

Scheduled task that enqueues full factor re-selection
(run_factor_selection_for_symbol) for all tracked stocks.
This bypasses the CUSUM drift monitor to guarantee a fresh
re-calibration of factors every quarter.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from services.worker.db import SessionLocal
from services.api.app.queue import get_queue

logger = logging.getLogger(__name__)


def run_quarterly_factor_recalibration() -> dict[str, Any]:
    """
    Enqueues a full factor selection run for all active stocks.
    """
    logger.info("Triggering quarterly factor recalibration for all active stocks")
    db = SessionLocal()
    try:
        rows = db.execute(
            text("SELECT symbol FROM stock_master WHERE is_active = true")
        ).mappings().all()
        
        if not rows:
            logger.info("No active stocks found.")
            return {"status": "success", "enqueued": 0}
            
        q = get_queue()
        from services.worker.tasks.factor_selection_full import run_factor_selection_for_symbol

        enqueued = 0
        for row in rows:
            symbol = row["symbol"]
            q.enqueue(run_factor_selection_for_symbol, symbol, True)
            enqueued += 1
            
        return {"status": "success", "enqueued": enqueued}
        
    except Exception as e:
        logger.exception("Error triggering quarterly recalibration")
        return {"status": "error", "reason": str(e)}
    finally:
        db.close()
