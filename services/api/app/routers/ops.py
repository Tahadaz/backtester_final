from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from redis import Redis
from sqlalchemy import desc, tuple_
from sqlalchemy.orm import Session

from core.quant_core.signal_engine.modes import ALL_SIGNAL_MODE_NAMES, signal_mode_storage_name
from ..auth import rate_limit_trigger, require_admin
from ..config import settings
from ..db import get_db
from .. import models
from ..models import SchedulerRun, SignalEngineGlobalResult, WfoGlobalSignal
from ..services.fundamentals import (
    derive_research_overlay,
    latest_data_verification,
    latest_imports_by_symbol,
    latest_snapshot_rows_by_symbol,
    recompute_symbol_valuations_all_scenarios,
    reverify_symbol,
)
from ..services.market_universe import is_masi_dashboard_member, list_signal_universe
from ..services.scheduler_registry import QUEUE_NAMES, SCHEDULE_SPECS, get_schedule_spec
from ..services.weekly_recompute_policy import HORIZONS, needs_weekly_recompute

router = APIRouter(prefix="/ops", tags=["ops"], dependencies=[Depends(require_admin)])


def _redis() -> Redis:
    return Redis.from_url(settings.REDIS_URL, decode_responses=True)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _queue_status(redis: Redis) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for queue in QUEUE_NAMES:
        rows.append(
            {
                "name": queue,
                "queued": int(redis.llen(f"rq:queue:{queue}")),
                "workers": int(redis.scard(f"rq:workers:{queue}")),
                "failed": int(redis.zcard(f"rq:failed:{queue}")),
            }
        )
    return rows


def _scheduler_heartbeat(redis: Redis) -> dict[str, Any] | None:
    raw = redis.get("ops:scheduler:heartbeat")
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}
    return payload if isinstance(payload, dict) else {"raw": raw}


def _last_runs(db: Session) -> dict[str, SchedulerRun]:
    rows = (
        db.query(SchedulerRun)
        .order_by(SchedulerRun.schedule_id.asc(), SchedulerRun.started_at.desc())
        .all()
    )
    out: dict[str, SchedulerRun] = {}
    for row in rows:
        out.setdefault(row.schedule_id, row)
    return out


def _signal_staleness(db: Session) -> dict[str, Any]:
    instruments = list_signal_universe(db)
    symbols = [row.symbol for row in instruments]
    variants = list(dict.fromkeys(signal_mode_storage_name(v) for v in ALL_SIGNAL_MODE_NAMES))
    tuple_keys = [(symbol, horizon, variant) for symbol in symbols for horizon in HORIZONS for variant in variants]

    se_rows = (
        db.query(
            SignalEngineGlobalResult.symbol,
            SignalEngineGlobalResult.horizon,
            SignalEngineGlobalResult.variant,
            SignalEngineGlobalResult.computed_at,
        )
        .filter(tuple_(SignalEngineGlobalResult.symbol, SignalEngineGlobalResult.horizon, SignalEngineGlobalResult.variant).in_(tuple_keys))
        .all()
        if tuple_keys
        else []
    )
    wfo_rows = (
        db.query(
            WfoGlobalSignal.symbol,
            WfoGlobalSignal.horizon,
            WfoGlobalSignal.variant,
            WfoGlobalSignal.computed_at,
        )
        .filter(tuple_(WfoGlobalSignal.symbol, WfoGlobalSignal.horizon, WfoGlobalSignal.variant).in_(tuple_keys))
        .all()
        if tuple_keys
        else []
    )
    se_map = {(row.symbol, row.horizon, row.variant): row.computed_at for row in se_rows}
    wfo_map = {(row.symbol, row.horizon, row.variant): row.computed_at for row in wfo_rows}
    now = datetime.now(timezone.utc)

    se_stale: list[tuple[str, str, str]] = []
    wfo_stale: list[tuple[str, str, str]] = []
    for key in tuple_keys:
        if needs_weekly_recompute(se_map.get(key), now):
            se_stale.append(key)
        if needs_weekly_recompute(wfo_map.get(key), now):
            wfo_stale.append(key)

    non_masi_symbols = [row.symbol for row in instruments if not is_masi_dashboard_member(row)]
    masi_symbols = [row.symbol for row in instruments if is_masi_dashboard_member(row)]
    return {
        "symbols_total": len(symbols),
        "masi_symbols": len(masi_symbols),
        "non_masi_symbols": len(non_masi_symbols),
        "variants": variants,
        "horizons": list(HORIZONS),
        "expected_tuples": len(tuple_keys),
        "signal_engine_stale_tuples": len(se_stale),
        "wfo_stale_tuples": len(wfo_stale),
        "stale_symbols_sample": sorted(set([s for s, _, _ in se_stale] + [s for s, _, _ in wfo_stale]))[:40],
        "non_masi_symbols_sample": sorted(non_masi_symbols)[:40],
    }


def _legacy_entries() -> list[dict[str, Any]]:
    try:
        from services.worker.tasks.scheduler_dispatch import list_legacy_rq_scheduler_entries

        return list_legacy_rq_scheduler_entries()
    except Exception:
        return []


@router.get("/scheduler/status")
def scheduler_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    redis = _redis()
    heartbeat = _scheduler_heartbeat(redis)
    last_by_id = _last_runs(db)
    schedules = []
    for spec in SCHEDULE_SPECS:
        last = last_by_id.get(spec.id)
        schedules.append(
            {
                "id": spec.id,
                "label": spec.label,
                "kind": spec.kind,
                "queue": spec.queue,
                "cron": spec.cron,
                "timezone": spec.timezone,
                "description": spec.description,
                "next_run_at": _iso(spec.next_run_at()),
                "last_run": None
                if last is None
                else {
                    "id": str(last.id),
                    "status": last.status,
                    "trigger_source": last.trigger_source,
                    "started_at": _iso(last.started_at),
                    "finished_at": _iso(last.finished_at),
                    "enqueued_jobs": int(last.enqueued_jobs or 0),
                    "error_message": last.error_message,
                    "meta_json": last.meta_json or {},
                },
            }
        )
    return {
        "ok": True,
        "scheduler": {
            "online": heartbeat is not None,
            "heartbeat": heartbeat,
        },
        "schedules": schedules,
        "queues": _queue_status(redis),
        "legacy_rq_scheduler_entries": _legacy_entries(),
        "signal_coverage": _signal_staleness(db),
    }


@router.post("/scheduler/run/{schedule_id}", dependencies=[Depends(rate_limit_trigger)])
def run_scheduler_now(schedule_id: str) -> dict[str, Any]:
    try:
        get_schedule_spec(schedule_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    from services.worker.tasks.scheduler_dispatch import dispatch_schedule

    return dispatch_schedule(schedule_id, trigger_source="manual")


@router.post("/scheduler/backfill/signals", dependencies=[Depends(rate_limit_trigger)])
def backfill_signals() -> dict[str, Any]:
    from services.worker.tasks.scheduler_dispatch import dispatch_signal_backfill

    return dispatch_signal_backfill(trigger_source="manual_backfill")


@router.post("/sfc/recompute", dependencies=[Depends(rate_limit_trigger)])
def recompute_sfc_now() -> dict[str, Any]:
    from services.worker.tasks.scheduler_dispatch import dispatch_schedule

    return dispatch_schedule("weekly_fundamental_cross_section", trigger_source="manual_sfc_recompute")


@router.post("/fundamentals/reverify-nr", dependencies=[Depends(rate_limit_trigger)])
def reverify_fundamental_nr_symbols(db: Session = Depends(get_db)) -> dict[str, Any]:
    snapshots = latest_snapshot_rows_by_symbol(db, scope="masi")
    imports = latest_imports_by_symbol(db, scope="masi")
    nr_symbols: list[str] = []
    for symbol, snapshot in sorted(snapshots.items()):
        ensemble = (
            db.query(models.FundamentalEnsembleResult)
            .filter(
                models.FundamentalEnsembleResult.import_id == snapshot.import_id,
                models.FundamentalEnsembleResult.symbol == symbol,
                models.FundamentalEnsembleResult.scenario == "base",
            )
            .one_or_none()
        )
        overlay = derive_research_overlay(
            db,
            symbol=symbol,
            scenario="base",
            ensemble=ensemble,
            import_row=imports.get(symbol),
            current_price=(snapshot.metrics_json or {}).get("Current_Price"),
        )
        if overlay.get("recommendation") == "NR":
            nr_symbols.append(symbol)

    reverified: list[dict[str, Any]] = []
    for symbol in nr_symbols:
        row = reverify_symbol(db, symbol)
        snapshot = latest_snapshot_rows_by_symbol(db, symbols=[symbol]).get(symbol)
        if snapshot is not None:
            recompute_symbol_valuations_all_scenarios(db, import_id=snapshot.import_id, symbol=symbol)
        reverified.append(
            {
                "symbol": symbol,
                "status": row.status if row is not None else "missing_verification",
                "reason": row.reason if row is not None else "no_canonical_verification_row",
                "failed_checks": list(row.failed_checks_json or []) if row is not None else [],
            }
        )
    db.commit()

    remaining: list[dict[str, Any]] = []
    refreshed_snapshots = latest_snapshot_rows_by_symbol(db, symbols=nr_symbols, scope="masi") if nr_symbols else {}
    for symbol, snapshot in sorted(refreshed_snapshots.items()):
        row = latest_data_verification(
            db,
            import_id=snapshot.import_id,
            symbol=symbol,
            statement_year=snapshot.latest_statement_year,
        )
        if row is None or row.status != "data_unverified":
            continue
        failed_checks = list(row.failed_checks_json or [])
        remaining.append(
            {
                "symbol": symbol,
                "failed_check": failed_checks[0] if failed_checks else row.reason or "data_unverified",
                "failed_checks": failed_checks,
                "reason": row.reason,
            }
        )
    return {
        "input_nr_count": len(nr_symbols),
        "reverified_count": len(reverified),
        "remaining_nr_count": len(remaining),
        "remaining_nr": remaining,
        "reverified": reverified,
    }


@router.get("/scheduler/runs")
def scheduler_runs(limit: int = 50, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    safe_limit = min(max(int(limit or 50), 1), 200)
    rows = db.query(SchedulerRun).order_by(desc(SchedulerRun.started_at)).limit(safe_limit).all()
    return [
        {
            "id": str(row.id),
            "schedule_id": row.schedule_id,
            "trigger_source": row.trigger_source,
            "status": row.status,
            "started_at": _iso(row.started_at),
            "finished_at": _iso(row.finished_at),
            "enqueued_jobs": int(row.enqueued_jobs or 0),
            "error_message": row.error_message,
            "meta_json": row.meta_json or {},
        }
        for row in rows
    ]
