from __future__ import annotations

import logging
import math
import os
import uuid
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
from redis import Redis
from rq import Queue
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from core.quant_core.data import drop_incomplete_ohlcv_rows
from core.quant_core.horizons import canonical_horizon
from core.quant_core.stat_arb import StatArbConfig, StatArbPairResult, scan_pairs
from services.api.app import models
from services.api.app.market_data_loader import load_ohlcv_for_symbol
from services.worker.config import settings
from services.worker.db import SessionLocal


logger = logging.getLogger(__name__)


def enqueue_stat_arb_recompute(
    horizon: str = "short",
    config: dict[str, Any] | None = None,
    *,
    queue_name: str | None = None,
) -> str:
    job_id = str(uuid.uuid4())
    redis_conn = Redis.from_url(settings.REDIS_URL, decode_responses=False)
    queue = Queue(queue_name or os.getenv("STAT_ARB_QUEUE_NAME", "score_history"), connection=redis_conn)
    job = queue.enqueue(
        "services.worker.tasks.stat_arb.compute_stat_arb_for_horizon",
        horizon,
        config or {},
        job_id,
        job_id=job_id,
        job_timeout=7200,
    )

    db: Session = SessionLocal()
    try:
        canonical = canonical_horizon(horizon, allow_legacy=True)
        row = models.StatArbBatchJob(
            id=uuid.UUID(job_id),
            horizon=canonical,
            status="pending",
            rq_job_id=str(job.id),
        )
        db.merge(row)
        db.commit()
    finally:
        db.close()
    return str(job.id)


def compute_stat_arb_for_horizon(
    horizon: str = "short",
    config: dict[str, Any] | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    db: Session = SessionLocal()
    started = datetime.now(timezone.utc)
    canonical = canonical_horizon(horizon, allow_legacy=True)
    cfg = _build_config(canonical, config or {})
    job_row = _start_job(db, canonical, job_id, started)
    try:
        close_by_symbol = _load_active_masi_closes(db)
        if len(close_by_symbol) < 2:
            raise ValueError("Need at least two active MASI symbols with OHLCV history.")

        results = scan_pairs(close_by_symbol, horizon=canonical, config=cfg)
        _replace_pair_rows(db, canonical, results)
        failed = sum(1 for row in results if row.status == "failed")
        _finish_job(
            job_row,
            status="succeeded",
            total_pairs=len(results),
            completed_pairs=len(results) - failed,
            failed_pairs=failed,
        )
        db.commit()
        return {
            "horizon": canonical,
            "status": "succeeded",
            "symbols": len(close_by_symbol),
            "pairs": len(results),
            "actionable": sum(1 for row in results if row.status == "actionable"),
            "watch": sum(1 for row in results if row.status == "watch"),
            "failed": failed,
        }
    except Exception as exc:
        logger.exception("Stat-arb recompute failed for horizon=%s", canonical)
        _finish_job(job_row, status="failed", error_message=str(exc))
        db.commit()
        return {"horizon": canonical, "status": "failed", "error": str(exc)}
    finally:
        db.close()


def _build_config(horizon: str, raw: dict[str, Any]) -> StatArbConfig:
    allowed = {
        "min_obs",
        "entry_z",
        "exit_z",
        "lag_bars",
        "fdr_q",
        "min_folds",
        "min_profitable_fold_ratio",
        "max_drawdown_floor",
        "cost_bps_per_side",
        "slippage_bps_per_side",
        "borrow_bps_annual",
        "train_bars",
        "oos_bars",
        "step_bars",
        "max_chart_points",
    }
    cleaned = {k: v for k, v in (raw or {}).items() if k in allowed}
    return StatArbConfig(horizon=horizon, **cleaned)


def _start_job(db: Session, horizon: str, job_id: str | None, started: datetime) -> models.StatArbBatchJob:
    row: models.StatArbBatchJob | None = None
    if job_id:
        try:
            row = db.get(models.StatArbBatchJob, uuid.UUID(str(job_id)))
        except Exception:
            row = None
    if row is None:
        row = models.StatArbBatchJob(horizon=horizon)
        db.add(row)
        db.flush()
    row.horizon = horizon
    row.status = "running"
    row.started_at = started
    row.finished_at = None
    row.error_message = None
    row.total_pairs = 0
    row.completed_pairs = 0
    row.failed_pairs = 0
    db.commit()
    return row


def _finish_job(
    row: models.StatArbBatchJob,
    *,
    status: str,
    total_pairs: int | None = None,
    completed_pairs: int | None = None,
    failed_pairs: int | None = None,
    error_message: str | None = None,
) -> None:
    row.status = status
    if total_pairs is not None:
        row.total_pairs = int(total_pairs)
    if completed_pairs is not None:
        row.completed_pairs = int(completed_pairs)
    if failed_pairs is not None:
        row.failed_pairs = int(failed_pairs)
    row.error_message = error_message
    row.finished_at = datetime.now(timezone.utc)


def _load_active_masi_closes(db: Session) -> dict[str, pd.Series]:
    rows = (
        db.query(models.StockMaster.symbol)
        .filter(models.StockMaster.is_active.is_(True))
        .filter(models.StockMaster.asset_type == "equity")
        .all()
    )
    close_by_symbol: dict[str, pd.Series] = {}
    for (symbol,) in rows:
        sym = str(symbol or "").strip().upper()
        if not sym:
            continue
        try:
            ohlcv = drop_incomplete_ohlcv_rows(load_ohlcv_for_symbol(db, sym, "1D"))
        except Exception:
            logger.info("Stat-arb skipped %s: no OHLCV", sym)
            continue
        if ohlcv.empty or "Close" not in ohlcv.columns:
            continue
        close = pd.to_numeric(ohlcv["Close"], errors="coerce").dropna()
        if len(close) >= 252:
            close_by_symbol[sym] = close
    return close_by_symbol


def _replace_pair_rows(db: Session, horizon: str, results: list[StatArbPairResult]) -> None:
    db.query(models.StatArbPairSignal).filter(
        models.StatArbPairSignal.horizon == horizon
    ).delete(synchronize_session=False)

    now = datetime.now(timezone.utc)
    rows = [_result_to_row(result, now) for result in results]
    if rows:
        chunk = 1000
        for i in range(0, len(rows), chunk):
            db.execute(pg_insert(models.StatArbPairSignal), rows[i:i + chunk])
    db.commit()


def _result_to_row(result: StatArbPairResult, now: datetime) -> dict[str, Any]:
    return {
        "pair_id": result.pair_id,
        "symbol_y": result.symbol_y,
        "symbol_x": result.symbol_x,
        "horizon": result.horizon,
        "archetype": result.archetype,
        "lag_bars": int(result.lag_bars),
        "action_type": result.action_type,
        "current_signal": result.current_signal,
        "direction": result.direction,
        "validation_status": result.validation_status,
        "status": result.status,
        "n_obs": int(result.n_obs),
        "n_folds": int(result.n_folds),
        "hedge_ratio": _finite_or_none(result.hedge_ratio),
        "intercept": _finite_or_none(result.intercept),
        "zscore": _finite_or_none(result.zscore),
        "half_life": _finite_or_none(result.half_life),
        "adf_pvalue": _finite_or_none(result.adf_pvalue),
        "raw_pvalue": _finite_or_none(result.raw_pvalue),
        "fdr_qvalue": _finite_or_none(result.fdr_qvalue),
        "oos_sharpe": _finite_or_none(result.oos_sharpe),
        "oos_return": _finite_or_none(result.oos_return),
        "max_drawdown": _finite_or_none(result.max_drawdown),
        "profitable_fold_ratio": _finite_or_none(result.profitable_fold_ratio),
        "data_as_of": date.fromisoformat(result.data_as_of) if result.data_as_of else None,
        "cost_bps_per_side": float(result.cost_bps_per_side),
        "slippage_bps_per_side": float(result.slippage_bps_per_side),
        "borrow_bps_annual": float(result.borrow_bps_annual),
        "metrics_json": _json_safe(result.metrics),
        "chart_json": _json_safe(result.chart),
        "warnings_json": _json_safe(result.warnings),
        "computed_at": now,
        "updated_at": now,
    }


def _finite_or_none(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value
