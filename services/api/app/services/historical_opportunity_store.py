from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from core.quant_core.historical_portfolio import DECISION_HORIZONS, METHODOLOGY_VERSION
from .. import models


def normalized_user_config(config: dict[str, Any] | None) -> dict[str, Any]:
    """Canonical config used for run reuse; server metadata never participates."""

    value = dict(config or {})
    value.pop("_system", None)
    if "symbols" in value:
        value["symbols"] = sorted({str(item).strip().upper() for item in value["symbols"] if str(item).strip()})
    requested_horizons = set(value.get("horizons") or DECISION_HORIZONS)
    value["horizons"] = [item for item in DECISION_HORIZONS if item in requested_horizons]
    if "resolved_universe" in value:
        value["resolved_universe"] = sorted(
            {str(item).strip().upper() for item in value["resolved_universe"] if str(item).strip()}
        )
    if "required_edge_conditions" in value:
        value["required_edge_conditions"] = list(dict.fromkeys(value["required_edge_conditions"]))
    return value


def configs_equal(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    return normalized_user_config(left) == normalized_user_config(right)


def _date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def opportunity_store_coverage(db: Session, config: dict[str, Any]) -> dict[str, Any]:
    """Return whether successful materialization intervals cover the request."""

    requested_start = _date(config["start_date"])
    requested_end = _date(config["end_date"])
    # An empty symbol list means "the whole resolved universe" on both sides. Comparing the raw
    # lists would report a universe-wide materialization as not covering a universe-wide request,
    # which sends every launch back to precalculation even when the store is complete.
    requested_symbols = set(config.get("symbols") or []) or set(config.get("resolved_universe") or [])
    rows = db.query(models.HistoricalOpportunityMaterializationRun).filter_by(
        status="succeeded", methodology_version=METHODOLOGY_VERSION,
    ).order_by(models.HistoricalOpportunityMaterializationRun.completed_at.desc()).all()
    intervals: list[tuple[date, date, str]] = []
    for row in rows:
        stored = row.config_json or {}
        stored_symbols = set(stored.get("symbols") or [])
        if stored_symbols and not requested_symbols.issubset(stored_symbols):
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


def missing_coverage_ranges(
    coverage: dict[str, Any], requested_start: date, requested_end: date,
) -> list[tuple[date, date]]:
    """Sub-ranges of the requested window absent from merged, sorted coverage intervals."""

    cursor = requested_start
    missing: list[tuple[date, date]] = []
    for interval in coverage.get("intervals") or []:
        interval_start = _date(interval["start"])
        interval_end = _date(interval["end"])
        if interval_end < cursor:
            continue
        if interval_start > requested_end:
            break
        if interval_start > cursor:
            missing.append((cursor, min(requested_end, interval_start - timedelta(days=1))))
        cursor = max(cursor, interval_end + timedelta(days=1))
        if cursor > requested_end:
            break
    if cursor <= requested_end:
        missing.append((cursor, requested_end))
    return missing
