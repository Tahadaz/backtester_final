from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from core.quant_core.historical_portfolio import METHODOLOGY_VERSION
from .. import models


def _date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def opportunity_store_coverage(db: Session, config: dict[str, Any]) -> dict[str, Any]:
    """Return whether successful materialization intervals cover the request."""

    requested_start = _date(config["start_date"])
    requested_end = _date(config["end_date"])
    requested_symbols = set(config.get("symbols") or [])
    rows = db.query(models.HistoricalOpportunityMaterializationRun).filter_by(
        status="succeeded", methodology_version=METHODOLOGY_VERSION,
    ).order_by(models.HistoricalOpportunityMaterializationRun.completed_at.desc()).all()
    intervals: list[tuple[date, date, str]] = []
    for row in rows:
        stored = row.config_json or {}
        stored_symbols = set(stored.get("symbols") or [])
        scope_matches = (
            (not requested_symbols and not stored_symbols)
            or (bool(requested_symbols) and (not stored_symbols or requested_symbols.issubset(stored_symbols)))
        )
        if not scope_matches:
            continue
        try:
            start = _date(stored["start_date"])
            end = _date(stored["end_date"])
            if end < requested_start or start > requested_end:
                continue
            intervals.append((start, end, str(row.id)))
        except Exception:
            continue
    intervals.sort()
    merged: list[tuple[date, date]] = []
    for start, end, _run_id in intervals:
        if not merged or start > merged[-1][1] + timedelta(days=1):
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    covered = any(start <= requested_start and end >= requested_end for start, end in merged)
    return {
        "available": covered,
        "methodology_version": METHODOLOGY_VERSION,
        "requested_start": requested_start.isoformat(),
        "requested_end": requested_end.isoformat(),
        "requested_symbols": sorted(requested_symbols),
        "intervals": [{"start": start.isoformat(), "end": end.isoformat()} for start, end in merged],
        "materialization_run_ids": [run_id for _start, _end, run_id in intervals],
    }
