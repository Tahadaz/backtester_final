"""Warm the analytics edge cache from the worker."""
from __future__ import annotations

from services.worker.db import SessionLocal
from services.api.app.config import settings
from services.api.app.routers.analytics import _warm_edge_cache_entries


def warm_edge_cache(
    symbols: list[str] | None = None,
    horizons: list[str] | None = None,
    sources: list[str] | None = None,
    *,
    cost_bps: float | None = None,
) -> dict[str, int]:
    db = SessionLocal()
    try:
        return _warm_edge_cache_entries(
            db=db,
            symbols=symbols,
            horizons=horizons,
            sources=sources,
            cost_bps=float(settings.EDGE_COST_BPS_PER_SIDE if cost_bps is None else cost_bps),
        )
    finally:
        db.close()
