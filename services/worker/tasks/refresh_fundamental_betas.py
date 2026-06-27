from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from services.api.app.services.fundamental_beta import recompute_universe_betas
from services.api.app.services.fundamentals import (
    latest_snapshot_rows_by_symbol,
    make_bulk_overrides_loader,
    recompute_symbol_valuations_all_scenarios,
)
from services.worker.db import SessionLocal


logger = logging.getLogger(__name__)


def refresh_fundamental_betas(
    *,
    as_of: str | None = None,
    window_years: float = 2.0,
    frequency: str = "weekly",
    proxy_symbol: str = "MASI",
    recompute_valuations: bool = True,
    triggered_by: str | None = None,
    batch_id: str | None = None,
) -> dict[str, Any]:
    db = SessionLocal()
    started = time.perf_counter()
    batch_id = batch_id or str(uuid.uuid4())
    parsed_as_of = None
    if as_of:
        import datetime as dt

        parsed_as_of = dt.date.fromisoformat(str(as_of)[:10])
    try:
        beta_summary = recompute_universe_betas(
            db,
            as_of=parsed_as_of,
            window_years=window_years,
            frequency=frequency,
            proxy_symbol=proxy_symbol,
        )
        db.commit()

        valuation_symbols = 0
        valuation_count = 0
        computed_symbols = [str(symbol).upper() for symbol in beta_summary.get("computed_symbols", [])]
        if recompute_valuations and computed_symbols:
            snapshots = latest_snapshot_rows_by_symbol(db, symbols=computed_symbols)
            overrides_loader = make_bulk_overrides_loader(db, list(snapshots))
            for symbol, snapshot in snapshots.items():
                valuation_count += len(
                    recompute_symbol_valuations_all_scenarios(
                        db,
                        import_id=snapshot.import_id,
                        symbol=symbol,
                        overrides_loader=overrides_loader,
                    )
                )
                valuation_symbols += 1
            db.commit()

        return {
            "batch_id": batch_id,
            "status": "succeeded",
            "triggered_by": triggered_by,
            "beta_summary": beta_summary,
            "valuation_symbols": valuation_symbols,
            "valuation_count": valuation_count,
            "elapsed_seconds": round(time.perf_counter() - started, 2),
        }
    except Exception:
        db.rollback()
        logger.exception("fundamental beta refresh failed")
        raise
    finally:
        db.close()
