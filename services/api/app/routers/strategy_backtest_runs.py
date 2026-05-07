from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import models
from ..config import settings
from ..db import get_db
from ..queue import get_queue
from ..schemas.strategy_backtest_runs import (
    StrategyBacktestRunCreateRequest,
    StrategyBacktestRunCreateResponse,
    StrategyBacktestRunListItemOut,
    StrategyBacktestRunOut,
    StrategyBacktestRunUpdateRequest,
    StrategyBacktestStockDetailOut,
    StrategyBacktestStockSummaryOut,
    StrategyBacktestWindowDetailOut,
)
from ..strategy_v2 import (
    build_strategy_review,
    get_basket_from_strategy_config,
    migrate_strategy_config_v2,
)

router = APIRouter(prefix="/backtest/strategy-runs", tags=["strategy-backtest-runs"])


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_number(value: object, fallback: float = 0.0, *, precision: int = 8) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = fallback
    return round(parsed, precision)


def _normalize_int(value: object, fallback: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return fallback


def _normalize_symbol(value: object) -> str:
    return str(value or "").strip().upper()


def _canonical_json(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _canonical_json(value[key]) for key in sorted(value.keys(), key=lambda item: str(item))}
    if isinstance(value, list):
        return [_canonical_json(item) for item in value]
    return value


def _resolve_code_version() -> str | None:
    env_value = str(settings.GIT_COMMIT or "").strip() if hasattr(settings, "GIT_COMMIT") else ""
    if env_value:
        return env_value

    repo_root = Path(__file__).resolve().parents[4]
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            stderr=subprocess.DEVNULL,
            timeout=2,
            text=True,
        ).strip()
        return out or None
    except Exception:
        return None


def _default_run_title(strategy_name: str, mode: str, created_at: datetime | None = None) -> str:
    stamp = (created_at or _utcnow()).strftime("%Y-%m-%d %H:%M")
    mode_label = "WFO" if str(mode).lower() == "wfo" else "Direct"
    return f"{strategy_name} • {mode_label} • {stamp}"


def _strategy_name_for_row(row: models.StrategyBacktestRun, strategy: models.SavedStrategy | None) -> str:
    if strategy is not None and strategy.name:
        return str(strategy.name)
    snapshot = row.strategy_snapshot_json or {}
    if isinstance(snapshot, dict):
        candidate = str(snapshot.get("strategy_name") or "").strip()
        if candidate:
            return candidate
    return "Unknown strategy"


def _display_run_title(row: models.StrategyBacktestRun, strategy_name: str) -> str:
    candidate = str(row.title or "").strip()
    return candidate or _default_run_title(strategy_name, row.mode, row.created_at)


def _serialize_run(
    row: models.StrategyBacktestRun,
    strategy_name: str,
    stocks: list[models.StrategyBacktestStock],
) -> StrategyBacktestRunOut:
    return StrategyBacktestRunOut(
        run_id=str(row.id),
        title=_display_run_title(row, strategy_name),
        strategy_id=str(row.strategy_id),
        strategy_name=strategy_name,
        mode=row.mode,
        status=row.status,
        horizon=row.horizon,
        strategy_snapshot=row.strategy_snapshot_json or {},
        data_snapshot=row.data_snapshot_json or {},
        request=row.request_json or {},
        summary=row.summary_json or {},
        result=row.result_json or {},
        progress=row.progress_json or {},
        stocks=[
            StrategyBacktestStockSummaryOut(
                symbol=stock.symbol,
                status=stock.status,
                summary=stock.summary_json or {},
                error_text=stock.error_text,
            )
            for stock in stocks
        ],
        error_text=row.error_text,
        created_at=_iso(row.created_at) or "",
        started_at=_iso(row.started_at),
        completed_at=_iso(row.completed_at),
    )


def _serialize_list_item(
    row: models.StrategyBacktestRun,
    strategy_name: str,
) -> StrategyBacktestRunListItemOut:
    request = row.request_json or {}
    wfo_config = request.get("wfo_config") if isinstance(request.get("wfo_config"), dict) else {}
    start_date = str(request.get("start_date") or "") or None
    end_date = str(request.get("end_date") or "") or None
    if row.mode == "wfo":
        start_date = str(wfo_config.get("test_period_start") or "") or start_date
        end_date = str(wfo_config.get("test_period_end") or "") or end_date
    snapshot = row.strategy_snapshot_json or {}
    basket = list(snapshot.get("basket") or []) if isinstance(snapshot, dict) else []
    return StrategyBacktestRunListItemOut(
        run_id=str(row.id),
        title=_display_run_title(row, strategy_name),
        strategy_id=str(row.strategy_id),
        strategy_name=strategy_name,
        mode=row.mode,
        status=row.status,
        horizon=row.horizon,
        start_date=start_date,
        end_date=end_date,
        basket_count=len(basket),
        summary=row.summary_json or {},
        created_at=_iso(row.created_at) or "",
        completed_at=_iso(row.completed_at),
    )


def _normalize_volume_gate(raw: object) -> dict[str, object]:
    gate = raw if isinstance(raw, dict) else {}
    enabled = bool(gate.get("enabled"))
    if not enabled:
        return {"enabled": False}
    kind = str(gate.get("kind") or "min_ratio_adv").strip().lower()
    out: dict[str, object] = {"enabled": True, "kind": kind}
    if kind == "min_abs":
        out["min_volume_abs"] = _normalize_int(gate.get("min_volume_abs"), 0)
    else:
        out["min_volume_ratio_adv"] = _normalize_number(gate.get("min_volume_ratio_adv"), 0.0)
        out["adv_window"] = _normalize_int(gate.get("adv_window"), 20)
    return out


def _normalize_wfo_config(raw: object, *, fallback_test_end: str | None = None) -> dict[str, object]:
    if not isinstance(raw, dict):
        return {}
    window_policy = str(raw.get("window_policy") or "strict_fold_driven").strip().lower()
    if window_policy not in {"strict_fold_driven", "legacy_ratio_scan"}:
        window_policy = "strict_fold_driven"
    ratio_input_supplied = "is_oos_ratios" in raw
    ratio_input_values = list(raw.get("is_oos_ratios") or [])
    ratios = sorted(
        {
            _normalize_number(item, 0.0, precision=6)
            for item in ratio_input_values
            if 0 < _normalize_number(item, 0.0, precision=6) < 1
        }
    )
    normalized_ratios: list[float]
    if window_policy == "legacy_ratio_scan" and ratio_input_supplied:
        normalized_ratios = ratios
    else:
        normalized_ratios = ratios or [0.25, 0.30, 0.35]
    out: dict[str, object] = {
        "window_policy": window_policy,
        "top_k_folds": max(1, min(_normalize_int(raw.get("top_k_folds"), 12), 50)),
        "strict_fallback_enabled": bool(raw.get("strict_fallback_enabled", True)),
        "strict_fallback_floor": max(1, min(_normalize_int(raw.get("strict_fallback_floor"), 1), 50)),
        "is_oos_ratios": normalized_ratios,
        "min_walk_forwards": _normalize_int(raw.get("min_walk_forwards"), 5),
    }
    test_period_start = str(raw.get("test_period_start") or "").strip()
    if test_period_start:
        out["test_period_start"] = test_period_start
    test_period_end = str(raw.get("test_period_end") or fallback_test_end or "").strip()
    if test_period_end:
        out["test_period_end"] = test_period_end
    if raw.get("n_monte_carlo_paths") is not None:
        out["n_monte_carlo_paths"] = _normalize_int(raw.get("n_monte_carlo_paths"), 1000)
    if raw.get("monte_carlo_block_length") is not None:
        out["monte_carlo_block_length"] = _normalize_int(raw.get("monte_carlo_block_length"), 0)
    return out


def _normalize_create_request(body: StrategyBacktestRunCreateRequest) -> dict[str, object]:
    payload = body.model_dump(mode="json")
    mode = str(payload.get("mode") or "direct").lower()
    normalized: dict[str, object] = {
        "mode": mode,
        "start_date": str(payload.get("start_date") or "").strip() if mode != "wfo" else "",
        "end_date": str(payload.get("end_date") or "").strip() if mode != "wfo" else "",
        "timeframe": str(payload.get("timeframe") or "1D").strip().upper(),
        "cost_model": {
            "brokerage_bps": _normalize_number(((payload.get("cost_model") or {}).get("brokerage_bps")), 0.0),
            "comm_bourse_bps": _normalize_number(((payload.get("cost_model") or {}).get("comm_bourse_bps")), 0.0),
            "reg_liv_bps": _normalize_number(((payload.get("cost_model") or {}).get("reg_liv_bps")), 0.0),
            "slippage_bps": _normalize_number(((payload.get("cost_model") or {}).get("slippage_bps")), 0.0),
            "tva_rate": _normalize_number(((payload.get("cost_model") or {}).get("tva_rate")), 0.0),
        },
        "volume_gate": _normalize_volume_gate(payload.get("volume_gate")),
        "cooldown_bars": _normalize_int(payload.get("cooldown_bars"), 0),
        "family_history_mode": str(payload.get("family_history_mode") or "static_current_reps").strip().lower(),
    }
    if mode == "wfo":
        normalized["wfo_config"] = _normalize_wfo_config(
            payload.get("wfo_config"),
            fallback_test_end=str(payload.get("end_date") or "").strip() or None,
        )
    return normalized


def _build_strategy_snapshot(strategy: models.SavedStrategy) -> tuple[dict[str, object], list[str]]:
    config = migrate_strategy_config_v2(strategy.config_json or {}, horizon=strategy.horizon)
    canonical_config = json.loads(json.dumps(config))
    basket = sorted(_normalize_symbol(symbol) for symbol in get_basket_from_strategy_config(canonical_config, horizon=strategy.horizon))
    portfolio = dict(canonical_config.get("portfolio") or {})
    universe = dict(portfolio.get("universe") or {})
    universe["basket"] = basket
    portfolio["universe"] = universe
    canonical_config["portfolio"] = portfolio
    snapshot = {
        "strategy_name": strategy.name,
        "side_policy": strategy.side_policy,
        "horizon": strategy.horizon,
        "basket": basket,
        "config_json": canonical_config,
    }
    return snapshot, basket


def _build_data_snapshot(db: Session, *, basket: list[str], timeframe: str) -> dict[str, object]:
    rows = (
        db.query(models.MarketDataStore)
        .filter(models.MarketDataStore.timeframe == timeframe)
        .filter(models.MarketDataStore.symbol.in_(basket) if basket else False)
        .all()
    )
    by_symbol = {str(row.symbol).strip().upper(): row for row in rows}
    symbols: list[dict[str, object]] = []
    for symbol in basket:
        row = by_symbol.get(symbol)
        symbols.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "present": row is not None,
                "object_key": str(row.object_key or "") if row is not None else "",
                "last_dataset_id": str(row.last_dataset_id) if row is not None and row.last_dataset_id is not None else None,
                "data_as_of": str(row.data_as_of) if row is not None and row.data_as_of is not None else None,
                "start_ts": _iso(row.start_ts) if row is not None else None,
                "end_ts": _iso(row.end_ts) if row is not None else None,
                "row_count": int(row.row_count or 0) if row is not None and row.row_count is not None else 0,
                "updated_at": _iso(row.updated_at) if row is not None else None,
            }
        )
    return {"timeframe": timeframe, "symbols": symbols}


def _compute_execution_fingerprint(
    *,
    normalized_request: dict[str, object],
    strategy_snapshot: dict[str, object],
    data_snapshot: dict[str, object],
    code_version: str | None,
) -> str:
    fingerprint_payload = {
        "request": normalized_request,
        "strategy": {
            "side_policy": strategy_snapshot.get("side_policy"),
            "horizon": strategy_snapshot.get("horizon"),
            "basket": strategy_snapshot.get("basket"),
            "config_json": strategy_snapshot.get("config_json"),
        },
        "data": data_snapshot,
        "code_version": code_version or "",
    }
    encoded = json.dumps(_canonical_json(fingerprint_payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _enqueue_strategy_backtest_job(run_id: UUID) -> str:
    job = get_queue().enqueue(
        "services.worker.tasks.strategy_backtest_runs.execute_strategy_backtest_run",
        str(run_id),
        job_timeout=int(settings.RUN_JOB_TIMEOUT_SECONDS),
        result_ttl=int(settings.RUN_JOB_RESULT_TTL_SECONDS),
        failure_ttl=int(settings.RUN_JOB_FAILURE_TTL_SECONDS),
    )
    return str(job.id)


def _rq_job_is_active(queue: object, job_id: str | None) -> bool:
    candidate = str(job_id or "").strip()
    if not candidate:
        return False
    fetch_job = getattr(queue, "fetch_job", None)
    if not callable(fetch_job):
        # If queue introspection is unavailable, preserve existing job linkage.
        return True
    try:
        job = fetch_job(candidate)
    except Exception:
        return False
    if job is None:
        return False
    get_status = getattr(job, "get_status", None)
    if not callable(get_status):
        return True
    try:
        status_text = str(get_status(refresh=False) or "").strip().lower()
    except Exception:
        return True
    return status_text in {"queued", "started", "deferred", "scheduled"}


@router.get("", response_model=list[StrategyBacktestRunListItemOut])
def list_strategy_backtest_runs(
    strategy_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    mode: str | None = None,
    q: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[StrategyBacktestRunListItemOut]:
    query = (
        db.query(models.StrategyBacktestRun, models.SavedStrategy.name.label("strategy_name"))
        .outerjoin(models.SavedStrategy, models.SavedStrategy.id == models.StrategyBacktestRun.strategy_id)
    )
    if strategy_id:
        try:
            query = query.filter(models.StrategyBacktestRun.strategy_id == UUID(str(strategy_id)))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid strategy_id filter.") from exc
    if status_filter:
        query = query.filter(models.StrategyBacktestRun.status == str(status_filter).strip().lower())
    if mode:
        query = query.filter(models.StrategyBacktestRun.mode == str(mode).strip().lower())
    if q:
        pattern = f"%{str(q).strip().lower()}%"
        query = query.filter(
            or_(
                func.lower(models.StrategyBacktestRun.title).like(pattern),
                func.lower(func.coalesce(models.SavedStrategy.name, "")).like(pattern),
            )
        )
    rows = query.order_by(models.StrategyBacktestRun.created_at.desc()).limit(limit).all()
    return [
        _serialize_list_item(row, str(strategy_name or _strategy_name_for_row(row, None)))
        for row, strategy_name in rows
    ]


@router.post("", response_model=StrategyBacktestRunCreateResponse, status_code=202)
def create_strategy_backtest_run(
    body: StrategyBacktestRunCreateRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> StrategyBacktestRunCreateResponse:
    try:
        strategy_id = UUID(body.strategy_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Strategy not found") from exc

    strategy = db.get(models.SavedStrategy, strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Strategy not found")

    normalized_request = _normalize_create_request(body)
    strategy_snapshot, basket = _build_strategy_snapshot(strategy)
    if not basket:
        raise HTTPException(status_code=422, detail="Saved strategy has an empty basket.")

    if body.mode == "direct":
        if not str(body.start_date or "").strip() or not str(body.end_date or "").strip():
            raise HTTPException(status_code=422, detail="Direct backtests require start_date and end_date.")
    if body.mode == "wfo":
        review = build_strategy_review(strategy.config_json or {}, horizon=strategy.horizon, for_wfo=True)
        if not review.get("ready"):
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "Strategy is not executable in four-page WFO mode.",
                    "blocking_issues": list(review.get("blocking_issues") or []),
                },
            )
        wfo_config = normalized_request.get("wfo_config") if isinstance(normalized_request.get("wfo_config"), dict) else {}
        window_policy = str(wfo_config.get("window_policy") or "strict_fold_driven").strip().lower()
        if window_policy == "legacy_ratio_scan":
            if isinstance(wfo_config.get("is_oos_ratios"), list):
                ratios = [float(item) for item in list(wfo_config.get("is_oos_ratios") or [])]
            else:
                ratios = [0.25, 0.30, 0.35]
            if not ratios or any(item <= 0 or item >= 1 for item in ratios):
                raise HTTPException(status_code=422, detail="WFO ratios must stay inside (0, 1).")
        test_period_start = str(wfo_config.get("test_period_start") or "").strip()
        test_period_end = str(wfo_config.get("test_period_end") or "").strip()
        if not test_period_start or not test_period_end:
            raise HTTPException(status_code=422, detail="WFO runs require test_period_start and test_period_end.")
        try:
            test_start_dt = datetime.fromisoformat(test_period_start)
            test_end_dt = datetime.fromisoformat(test_period_end)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="WFO test period dates must be valid ISO dates.") from exc
        if test_start_dt > test_end_dt:
            raise HTTPException(status_code=422, detail="WFO test_period_start must be on or before test_period_end.")

    timeframe = str(normalized_request.get("timeframe") or "1D")
    data_snapshot = _build_data_snapshot(db, basket=basket, timeframe=timeframe)
    code_version = _resolve_code_version()
    execution_fingerprint = _compute_execution_fingerprint(
        normalized_request=normalized_request,
        strategy_snapshot=strategy_snapshot,
        data_snapshot=data_snapshot,
        code_version=code_version,
    )

    existing = (
        db.query(models.StrategyBacktestRun)
        .filter(models.StrategyBacktestRun.execution_fingerprint == execution_fingerprint)
        .order_by(models.StrategyBacktestRun.created_at.desc())
        .first()
    )
    if existing is not None:
        existing_status = str(existing.status or "").strip().lower()
        if existing_status in {"failed", "canceled"}:
            existing = None
        elif existing_status == "queued":
            queue = get_queue()
            if not _rq_job_is_active(queue, existing.rq_job_id):
                try:
                    existing.rq_job_id = _enqueue_strategy_backtest_job(existing.id)
                    existing.updated_at = _utcnow()
                    progress = dict(existing.progress_json or {})
                    progress["message"] = "Re-queued in RQ"
                    existing.progress_json = progress
                    db.commit()
                except Exception as exc:
                    existing.status = "failed"
                    existing.error_text = f"re-enqueue failed: {exc}"[:8000]
                    existing.completed_at = _utcnow()
                    db.commit()
                    raise HTTPException(status_code=503, detail="failed to re-enqueue strategy backtest run") from exc
        if existing is not None:
            response.status_code = status.HTTP_200_OK
            existing_strategy = db.get(models.SavedStrategy, existing.strategy_id)
            return StrategyBacktestRunCreateResponse(
                run_id=str(existing.id),
                status=existing.status,
                mode=existing.mode,
                title=_display_run_title(existing, _strategy_name_for_row(existing, existing_strategy)),
                reused=True,
            )

    run = models.StrategyBacktestRun(
        strategy_id=strategy_id,
        title=_default_run_title(strategy.name, body.mode),
        mode=body.mode,
        status="queued",
        horizon=strategy.horizon,
        execution_fingerprint=execution_fingerprint,
        strategy_snapshot_json=strategy_snapshot,
        data_snapshot_json=data_snapshot,
        request_json=normalized_request,
        summary_json={},
        result_json={},
        progress_json={
            "completed": 0,
            "total": len(basket),
            "active_symbol": None,
            "message": "Queued in RQ",
        },
    )
    db.add(run)
    db.flush()

    for symbol in basket:
        db.add(
            models.StrategyBacktestStock(
                run_id=run.id,
                symbol=symbol,
                status="queued",
                summary_json={},
                result_json={},
            )
        )

    try:
        run.rq_job_id = _enqueue_strategy_backtest_job(run.id)
    except Exception as exc:
        run.status = "failed"
        run.error_text = f"enqueue failed: {exc}"[:8000]
        run.completed_at = _utcnow()
        db.commit()
        raise HTTPException(status_code=503, detail="failed to enqueue strategy backtest run") from exc

    db.commit()
    return StrategyBacktestRunCreateResponse(
        run_id=str(run.id),
        status=run.status,
        mode=run.mode,
        title=run.title,
        reused=False,
    )


@router.get("/{run_id}", response_model=StrategyBacktestRunOut)
def get_strategy_backtest_run(run_id: UUID, db: Session = Depends(get_db)) -> StrategyBacktestRunOut:
    row = db.get(models.StrategyBacktestRun, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Strategy backtest run not found")
    strategy = db.get(models.SavedStrategy, row.strategy_id)
    stocks = (
        db.query(models.StrategyBacktestStock)
        .filter(models.StrategyBacktestStock.run_id == run_id)
        .order_by(models.StrategyBacktestStock.symbol.asc())
        .all()
    )
    return _serialize_run(row, _strategy_name_for_row(row, strategy), stocks)


@router.post("/{run_id}/cancel", response_model=StrategyBacktestRunOut)
def cancel_strategy_backtest_run(run_id: UUID, db: Session = Depends(get_db)) -> StrategyBacktestRunOut:
    row = db.get(models.StrategyBacktestRun, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Strategy backtest run not found")

    current_status = str(row.status or "").strip().lower()
    if current_status in {"succeeded", "failed", "canceled"}:
        strategy = db.get(models.SavedStrategy, row.strategy_id)
        stocks = (
            db.query(models.StrategyBacktestStock)
            .filter(models.StrategyBacktestStock.run_id == run_id)
            .order_by(models.StrategyBacktestStock.symbol.asc())
            .all()
        )
        return _serialize_run(row, _strategy_name_for_row(row, strategy), stocks)

    rq_job_id = str(row.rq_job_id or "").strip()
    canceled_from_queue = False

    try:
        queue = get_queue()
    except Exception:
        queue = None

    queue_connection = getattr(queue, "connection", None) if queue is not None else None
    if rq_job_id and queue_connection is not None:
        try:
            queue_connection.set(f"rq:cancel:{rq_job_id}", "1", ex=24 * 3600)
        except Exception:
            pass

    if rq_job_id and queue is not None:
        fetch_job = getattr(queue, "fetch_job", None)
        if callable(fetch_job):
            try:
                job = fetch_job(rq_job_id)
            except Exception:
                job = None
            if job is not None:
                get_status = getattr(job, "get_status", None)
                status_text = ""
                if callable(get_status):
                    try:
                        status_text = str(get_status(refresh=True) or "").strip().lower()
                    except Exception:
                        status_text = ""
                if status_text in {"queued", "deferred", "scheduled"}:
                    cancel = getattr(job, "cancel", None)
                    if callable(cancel):
                        try:
                            cancel()
                            canceled_from_queue = True
                        except Exception:
                            pass

    next_status = "cancel_requested"
    if current_status == "created" or (current_status == "queued" and canceled_from_queue):
        next_status = "canceled"

    row.status = next_status
    row.updated_at = _utcnow()
    progress = dict(row.progress_json or {})
    progress["message"] = "Cancel requested by user" if next_status == "cancel_requested" else "Canceled by user"
    if next_status == "canceled":
        progress["active_symbol"] = None
        row.completed_at = _utcnow()
    row.progress_json = progress

    if next_status == "canceled":
        for stock in (
            db.query(models.StrategyBacktestStock)
            .filter(models.StrategyBacktestStock.run_id == run_id)
            .all()
        ):
            stock_status = str(stock.status or "").strip().lower()
            if stock_status in {"queued", "running", "cancel_requested"}:
                stock.status = "canceled"
                stock.error_text = stock.error_text or "Canceled by user."
                stock.updated_at = _utcnow()

    db.commit()
    db.refresh(row)
    strategy = db.get(models.SavedStrategy, row.strategy_id)
    stocks = (
        db.query(models.StrategyBacktestStock)
        .filter(models.StrategyBacktestStock.run_id == run_id)
        .order_by(models.StrategyBacktestStock.symbol.asc())
        .all()
    )
    return _serialize_run(row, _strategy_name_for_row(row, strategy), stocks)


@router.patch("/{run_id}", response_model=StrategyBacktestRunOut)
def rename_strategy_backtest_run(
    run_id: UUID,
    body: StrategyBacktestRunUpdateRequest,
    db: Session = Depends(get_db),
) -> StrategyBacktestRunOut:
    row = db.get(models.StrategyBacktestRun, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Strategy backtest run not found")
    title = str(body.title or "").strip()
    if not title:
        raise HTTPException(status_code=422, detail="Backtest title cannot be empty.")
    row.title = title[:200]
    row.updated_at = _utcnow()
    db.commit()
    db.refresh(row)
    strategy = db.get(models.SavedStrategy, row.strategy_id)
    stocks = (
        db.query(models.StrategyBacktestStock)
        .filter(models.StrategyBacktestStock.run_id == run_id)
        .order_by(models.StrategyBacktestStock.symbol.asc())
        .all()
    )
    return _serialize_run(row, _strategy_name_for_row(row, strategy), stocks)


@router.delete("/{run_id}", status_code=204)
def delete_strategy_backtest_run(run_id: UUID, db: Session = Depends(get_db)) -> Response:
    row = db.get(models.StrategyBacktestRun, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Strategy backtest run not found")
    (
        db.query(models.StrategyBacktestWindow)
        .filter(models.StrategyBacktestWindow.run_id == run_id)
        .delete(synchronize_session=False)
    )
    (
        db.query(models.StrategyBacktestStock)
        .filter(models.StrategyBacktestStock.run_id == run_id)
        .delete(synchronize_session=False)
    )
    db.delete(row)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{run_id}/stocks/{symbol}", response_model=StrategyBacktestStockDetailOut)
def get_strategy_backtest_stock_detail(run_id: UUID, symbol: str, db: Session = Depends(get_db)) -> StrategyBacktestStockDetailOut:
    row = (
        db.query(models.StrategyBacktestStock)
        .filter(models.StrategyBacktestStock.run_id == run_id)
        .filter(models.StrategyBacktestStock.symbol == str(symbol).strip().upper())
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Strategy backtest stock not found")
    return StrategyBacktestStockDetailOut(
        run_id=str(run_id),
        symbol=row.symbol,
        status=row.status,
        summary=row.summary_json or {},
        result=row.result_json or {},
        error_text=row.error_text,
    )


@router.get("/{run_id}/stocks/{symbol}/windows/{window_index}", response_model=StrategyBacktestWindowDetailOut)
def get_strategy_backtest_window_detail(
    run_id: UUID,
    symbol: str,
    window_index: int,
    db: Session = Depends(get_db),
) -> StrategyBacktestWindowDetailOut:
    row = (
        db.query(models.StrategyBacktestWindow)
        .filter(models.StrategyBacktestWindow.run_id == run_id)
        .filter(models.StrategyBacktestWindow.symbol == str(symbol).strip().upper())
        .filter(models.StrategyBacktestWindow.window_index == int(window_index))
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="No persisted window details for this run.")
    return StrategyBacktestWindowDetailOut(
        run_id=str(run_id),
        symbol=row.symbol,
        window_index=row.window_index,
        summary=row.summary_json or {},
        detail=row.detail_json or {},
    )
