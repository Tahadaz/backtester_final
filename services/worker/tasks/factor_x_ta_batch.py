"""Worker task: compute and persist Factor×TA cross-product signal engine results.

Entry point: compute_factor_x_ta_for_symbol(symbol, horizon, variant='factor_x_ta')

Runs the Phase 2 cross-product pipeline (Layer A with factor-conditioned
candidates → unchanged Layers B–G) and persists results to
SignalEngineFamilyResult with variant='factor_x_ta'.

Conditions are loaded from docs/research/phase2_pre_registration.yaml (frozen
pre-registration file). Factor series are loaded from the macro S3 store via
the same market_data_loader used by the analytics API.

Per-stock factor enables are read from the stock_factor_config DB table.
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import yaml
from pathlib import Path
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from core.quant_core.horizons import DEFAULT_COST_BPS_PER_SIDE
from core.quant_core.data import drop_incomplete_ohlcv_rows
from core.quant_core.signal_engine.domain import (
    ALL_FAMILIES,
    CATEGORY_FAMILIES,
    FAMILY_SIGNAL_TYPE,
    FactorConditionMeta,
)
from core.quant_core.signal_engine.factor_x_ta import run_factor_x_ta_ensemble_for_family
from services.api.app.market_data_loader import load_ohlcv_for_symbol
from services.api.app.models import SignalEngineBatchJob, SignalEngineFamilyResult
from services.api.app.services.signal_engine_persistence import _compute_and_upsert_global
from services.worker.db import SessionLocal
from services.worker.redis_utils import connect_redis_with_fallback

logger = logging.getLogger(__name__)

HORIZONS = ("weekly", "monthly", "quarterly")
DEFAULT_TIMEFRAME = "1D"
DEFAULT_COST_BPS = DEFAULT_COST_BPS_PER_SIDE
DEFAULT_COOLDOWN_BARS = 0
VARIANT = "factor_x_ta"

_PREREGISTRATION_PATH = (
    Path(__file__).parents[1]
    /"research" / "phase2_pre_registration.yaml"
)
_CHANNEL_TAGS_PATH = (
    Path(__file__).parents[1]
    /"research" / "channel_tags.yaml"
)


def _current_rq_job_id() -> str | None:
    try:
        from rq import get_current_job

        job = get_current_job()
        return str(job.id) if job is not None else None
    except Exception:
        return None


def _current_rq_meta_value(key: str) -> str | None:
    try:
        from rq import get_current_job

        job = get_current_job()
        meta = job.meta if job is not None and isinstance(job.meta, dict) else {}
        value = str(meta.get(key) or "").strip()
        return value or None
    except Exception:
        return None


def _upsert_batch_job(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    status: str,
    rq_job_id: str | None,
    triggered_by: str | None,
    completed_units: int = 0,
    failed_units: int = 0,
    error_message: str | None = None,
    finish: bool = False,
) -> SignalEngineBatchJob:
    row = None
    if rq_job_id:
        row = (
            db.query(SignalEngineBatchJob)
            .filter_by(rq_job_id=rq_job_id, job_type="signal_engine")
            .first()
        )
    if row is None and not rq_job_id:
        row = (
            db.query(SignalEngineBatchJob)
            .filter_by(
                symbol=symbol,
                horizon=horizon,
                variant=VARIANT,
                job_type="signal_engine",
                status="pending",
            )
            .order_by(SignalEngineBatchJob.created_at.desc())
            .first()
        )
    if row is None:
        row = SignalEngineBatchJob(
            id=uuid.uuid4(),
            symbol=symbol,
            horizon=horizon,
            variant=VARIANT,
            job_type="signal_engine",
            rq_job_id=rq_job_id,
            triggered_by=triggered_by,
            total_units=len(ALL_FAMILIES),
        )
        db.add(row)

    row.status = status
    row.variant = VARIANT
    row.rq_job_id = rq_job_id or row.rq_job_id
    row.triggered_by = triggered_by or row.triggered_by
    row.total_units = len(ALL_FAMILIES)
    row.completed_units = int(completed_units)
    row.failed_units = int(failed_units)
    row.error_message = error_message
    if status == "running" and row.started_at is None:
        row.started_at = datetime.now(timezone.utc)
    if finish:
        row.finished_at = datetime.now(timezone.utc)
    return row


def _load_pre_registration() -> dict:
    with open(_PREREGISTRATION_PATH) as f:
        return yaml.safe_load(f)


def _load_channel_tags() -> dict:
    with open(_CHANNEL_TAGS_PATH) as f:
        return yaml.safe_load(f)


def _build_conditions(pre_reg: dict) -> list[FactorConditionMeta]:
    """Parse pre-registration YAML → list of FactorConditionMeta."""
    conditions: list[FactorConditionMeta] = []
    for cid, spec in pre_reg.get("factor_conditions", {}).items():
        conditions.append(
            FactorConditionMeta(
                condition_id=cid,
                factor_ticker=spec["factor_ticker"],
                form=spec["form"],
                lookback=int(spec.get("lookback", 1)),
                threshold=float(spec.get("threshold", 0.0)),
                direction=spec["direction"],
            )
        )
    return conditions


def _get_enabled_factor_tickers(db: Session, symbol: str) -> set[str]:
    """Return set of factor tickers enabled for this stock in stock_factor_config."""
    try:
        from sqlalchemy import text

        rows = db.execute(
            text(
                "SELECT factor_ticker FROM stock_factor_config "
                "WHERE stock_symbol = :sym AND enabled = true"
            ),
            {"sym": symbol},
        ).fetchall()
        return {r[0] for r in rows}
    except Exception:
        # Table may not exist yet; fall back to all enabled
        return set()


def _load_factor_series_from_store(db: Session, canonical_id: str) -> np.ndarray | None:
    """Load factor close series from the parquet store (same path as analytics API)."""
    try:
        prices = load_ohlcv_for_symbol(db, canonical_id, timeframe="1D")
    except Exception:
        return None
    if prices is None or prices.empty:
        return None
    close_col = next((c for c in ["Close", "close", "Adj Close"] if c in prices.columns), None)
    if close_col is None:
        return None
    return prices[close_col].dropna().values.astype(np.float64)


def _build_ticker_to_canonical() -> dict[str, str]:
    """Map Yahoo tickers to canonical IDs (as registered in macro store)."""
    try:
        from core.quant_core.macro import MACRO_SERIES_BY_ID
        return {spec.symbol: cid for cid, spec in MACRO_SERIES_BY_ID.items()}
    except Exception:
        return {}


def _build_channel_tag_gate(
    channel_tags_yaml: dict,
    enabled_tickers: set[str],
) -> dict[str, list[str]]:
    """Build {factor_ticker → [sectors]} gate from channel_tags.yaml.

    Only includes factors whose ticker is in enabled_tickers.
    Factors with tags=[all] are represented as empty list → unrestricted.
    """
    ticker_to_canonical = _build_ticker_to_canonical()
    canonical_to_ticker = {v: k for k, v in ticker_to_canonical.items()}

    gate: dict[str, list[str]] = {}
    for canonical_id, spec in channel_tags_yaml.get("factors", {}).items():
        ticker = canonical_to_ticker.get(canonical_id) or canonical_id
        if enabled_tickers and ticker not in enabled_tickers:
            continue
        tags = spec.get("tags", ["all"])
        if "all" in tags:
            gate[ticker] = []  # empty = unrestricted
        else:
            gate[ticker] = [t.lower() for t in tags]
    return gate


def _get_stock_sector(db: Session, symbol: str) -> str | None:
    """Look up the stock's sector from StockMaster."""
    try:
        from services.api.app.models import StockMaster

        row = db.query(StockMaster.sector).filter_by(symbol=symbol).first()
        if row and row.sector:
            return str(row.sector).lower()
    except Exception:
        pass
    return None


def _get_selected_factor_tickers(db: Session, symbol: str, horizon: str) -> set[str]:
    """Return Yahoo tickers for statistically selected factors for this stock/horizon."""
    try:
        from services.api.app.services.factor_selection_state import active_factor_ids_for_symbol_horizon

        selected_ids = set(active_factor_ids_for_symbol_horizon(db, symbol, horizon))
        if not selected_ids:
            return set()
        try:
            from core.quant_core.macro import get_macro_series_by_id
            by_id = get_macro_series_by_id()
        except Exception:
            by_id = {}
        return {by_id[fid].symbol for fid in selected_ids if fid in by_id}
    except Exception:
        return set()


def _upsert_family_result(
    db: Session,
    *,
    symbol: str,
    family: str,
    category: str,
    horizon: str,
    status: str,
    representatives_json: list[dict],
    family_detail_json: dict,
    data_as_of: date | None,
    compute_seconds: float,
    error_message: str | None = None,
) -> None:
    now = datetime.now(timezone.utc)
    values = {
        "symbol": symbol,
        "family": family,
        "horizon": horizon,
        "variant": VARIANT,
        "category": category,
        "status": status,
        "error_message": error_message,
        "data_as_of": data_as_of,
        "computed_at": now,
        "compute_seconds": compute_seconds,
        "representatives_json": representatives_json,
        "family_detail_json": family_detail_json or {},
        "family_score_pct": family_detail_json.get("family_score_pct") if family_detail_json else None,
        "signal_label": family_detail_json.get("family_signal_label") if family_detail_json else None,
        "viable_count": family_detail_json.get("viable_count") if family_detail_json else None,
        "tested_count": family_detail_json.get("tested_count") if family_detail_json else None,
        "representative_count": family_detail_json.get("representative_count") if family_detail_json else len(representatives_json),
        "is_provisional": bool(family_detail_json.get("is_provisional")) if family_detail_json else False,
    }
    stmt = pg_insert(SignalEngineFamilyResult).values(**values)
    update_cols = {
        key: getattr(stmt.excluded, key)
        for key in values
        if key not in {"symbol", "family", "horizon", "variant"}
    }
    db.execute(
        stmt.on_conflict_do_update(
            constraint="uq_sefr_sym_fam_hz_var",
            set_=update_cols,
        )
    )


def compute_factor_x_ta_for_symbol(
    symbol: str,
    horizon: str,
    cost_bps: float = DEFAULT_COST_BPS,
    cooldown_bars: int = DEFAULT_COOLDOWN_BARS,
) -> dict:
    """RQ task: run Factor×TA cross-product pipeline for one symbol × horizon.

    Persists results to SignalEngineFamilyResult with variant='factor_x_ta'.
    """
    t0 = time.perf_counter()
    db: Session = SessionLocal()
    rq_job_id = _current_rq_job_id()
    triggered_by = _current_rq_meta_value("triggered_by")
    batch_row: SignalEngineBatchJob | None = None

    try:
        batch_row = _upsert_batch_job(
            db,
            symbol=symbol,
            horizon=horizon,
            status="running",
            rq_job_id=rq_job_id,
            triggered_by=triggered_by,
        )
        db.commit()

        # Load pre-registration + channel tags
        pre_reg = _load_pre_registration()
        channel_tags_yaml = _load_channel_tags()
        all_conditions = _build_conditions(pre_reg)

        # Load OHLCV
        try:
            ohlcv_raw = load_ohlcv_for_symbol(db, symbol, DEFAULT_TIMEFRAME)
            ohlcv = drop_incomplete_ohlcv_rows(ohlcv_raw)
        except Exception as exc:
            logger.warning("Factor×TA: no OHLCV for %s: %s", symbol, exc)
            _upsert_batch_job(
                db,
                symbol=symbol,
                horizon=horizon,
                status="failed",
                rq_job_id=rq_job_id,
                triggered_by=triggered_by,
                failed_units=len(ALL_FAMILIES),
                error_message=str(exc),
                finish=True,
            )
            db.commit()
            return {"symbol": symbol, "horizon": horizon, "status": "failed", "error": str(exc)}

        if len(ohlcv) < 10:
            _upsert_batch_job(
                db,
                symbol=symbol,
                horizon=horizon,
                status="failed",
                rq_job_id=rq_job_id,
                triggered_by=triggered_by,
                error_message="insufficient bars",
                finish=True,
            )
            db.commit()
            return {"symbol": symbol, "horizon": horizon, "status": "skipped", "reason": "insufficient bars"}

        data_as_of = ohlcv.index[-1].date()
        close = ohlcv["Close"].values.astype(np.float64)
        high = ohlcv["High"].values.astype(np.float64) if "High" in ohlcv.columns else None
        low = ohlcv["Low"].values.astype(np.float64) if "Low" in ohlcv.columns else None
        volume = ohlcv["Volume"].values.astype(np.float64) if "Volume" in ohlcv.columns else None

        selected_tickers = _get_selected_factor_tickers(db, symbol, horizon)

        # Per-stock factor enable config (empty set = all enabled)
        enabled_tickers = _get_enabled_factor_tickers(db, symbol)
        if not enabled_tickers:
            # No rows = all enabled by default
            enabled_tickers = {c.factor_ticker for c in all_conditions}
        if selected_tickers:
            enabled_tickers &= selected_tickers

        stock_sector = _get_stock_sector(db, symbol)
        channel_gate = _build_channel_tag_gate(channel_tags_yaml, enabled_tickers)

        # Filter conditions to enabled tickers
        active_conditions = [c for c in all_conditions if c.factor_ticker in enabled_tickers]

        if not active_conditions:
            _upsert_batch_job(
                db,
                symbol=symbol,
                horizon=horizon,
                status="failed",
                rq_job_id=rq_job_id,
                triggered_by=triggered_by,
                error_message="no active conditions",
                finish=True,
            )
            db.commit()
            return {"symbol": symbol, "horizon": horizon, "status": "skipped", "reason": "no active conditions"}

        # Load factor series (aligned to OHLCV length by caller)
        aligned_factor_arrays: dict[str, np.ndarray] = {}
        ticker_to_canonical = _build_ticker_to_canonical()
        for condition in active_conditions:
            ticker = condition.factor_ticker
            if ticker in aligned_factor_arrays:
                continue
            canonical_id = ticker_to_canonical.get(ticker, ticker)
            arr = _load_factor_series_from_store(db, canonical_id)
            if arr is not None:
                aligned_factor_arrays[ticker] = arr

        if not aligned_factor_arrays:
            _upsert_batch_job(
                db,
                symbol=symbol,
                horizon=horizon,
                status="failed",
                rq_job_id=rq_job_id,
                triggered_by=triggered_by,
                error_message="factor series not ingested",
                finish=True,
            )
            db.commit()
            return {"symbol": symbol, "horizon": horizon, "status": "skipped", "reason": "factor series not ingested"}

        # Run per-family
        completed = 0
        failed = 0
        family_scores: dict[str, float] = {}
        family_statuses: dict[str, str] = {}
        family_representatives: dict[str, list[dict[str, Any]]] = {}

        for cat, families in CATEGORY_FAMILIES.items():
            for family in families:
                t_fam = time.perf_counter()
                family_fx = f"{family}@fx"
                try:
                    detail = run_factor_x_ta_ensemble_for_family(
                        family,
                        close,
                        aligned_factor_arrays,
                        active_conditions,
                        volume=volume,
                        high=high,
                        low=low,
                        symbol=symbol,
                        horizon=horizon,
                        timeframe=DEFAULT_TIMEFRAME,
                        cost_bps=cost_bps,
                        cooldown_bars=cooldown_bars,
                        channel_tags=channel_gate,
                        stock_sector=stock_sector,
                    )
                    sig = detail.signal
                    reps = sig.representatives or []
                    family_detail: dict[str, Any] = {
                        "family": sig.family,
                        "symbol": sig.symbol,
                        "horizon": sig.horizon,
                        "family_score_pct": sig.family_score_pct,
                        "family_signal_label": sig.family_signal_label,
                        "tested_count": sig.tested_count,
                        "viable_count": sig.viable_count,
                        "competitive_count": sig.competitive_count,
                        "representative_count": sig.representative_count,
                        "is_provisional": sig.is_provisional,
                        "methodology_mode": sig.methodology_mode,
                    }
                    _upsert_family_result(
                        db,
                        symbol=symbol,
                        family=sig.family,
                        category=cat,
                        horizon=horizon,
                        status="succeeded" if reps else "no_signal",
                        representatives_json=reps,
                        family_detail_json=family_detail,
                        data_as_of=data_as_of,
                        compute_seconds=time.perf_counter() - t_fam,
                    )
                    
                    family_statuses[family_fx] = "succeeded" if reps else "no_signal"
                    family_representatives[family_fx] = reps
                    if reps:
                        family_scores[family_fx] = float(sig.family_score_pct)
                    
                    completed += 1
                except Exception as exc:
                    logger.exception("Factor×TA family failed: %s/%s/%s: %s", symbol, family, horizon, exc)
                    _upsert_family_result(
                        db,
                        symbol=symbol,
                        family=f"{family}@fx",
                        category=cat,
                        horizon=horizon,
                        status="failed",
                        representatives_json=[],
                        family_detail_json={},
                        data_as_of=data_as_of,
                        compute_seconds=time.perf_counter() - t_fam,
                        error_message=str(exc),
                    )
                    
                    family_statuses[family_fx] = "failed"
                    family_representatives[family_fx] = []
                    
                    failed += 1
                db.commit()

        # Phase 5: compute and upsert the global Factor×TA engine result
        cat_map_fx = {
            cat: [f"{f}@fx" for f in fams] 
            for cat, fams in CATEGORY_FAMILIES.items()
        }
        global_status = _compute_and_upsert_global(
            db,
            symbol=symbol,
            horizon=horizon,
            variant=VARIANT,
            cat_map=cat_map_fx,
            family_scores=family_scores,
            family_statuses=family_statuses,
            family_representatives=family_representatives,
            data_as_of=data_as_of,
            first_error=None,
            timeframe=DEFAULT_TIMEFRAME,
            cost_bps=cost_bps,
            cooldown_bars=cooldown_bars,
        )
        first_error = None
        if failed:
            failed_row = (
                db.query(SignalEngineFamilyResult.error_message)
                .filter_by(symbol=symbol, horizon=horizon, variant=VARIANT, status="failed")
                .filter(SignalEngineFamilyResult.error_message.isnot(None))
                .first()
            )
            first_error = failed_row.error_message if failed_row else None
        _upsert_batch_job(
            db,
            symbol=symbol,
            horizon=horizon,
            status=global_status,
            rq_job_id=rq_job_id,
            triggered_by=triggered_by,
            completed_units=completed,
            failed_units=failed,
            error_message=first_error,
            finish=True,
        )
        db.commit()

        return {
            "symbol": symbol,
            "horizon": horizon,
            "status": global_status,
            "completed": completed,
            "failed": failed,
            "elapsed": round(time.perf_counter() - t0, 2),
        }
    except Exception as exc:
        logger.exception("Factor×TA batch failed: %s/%s: %s", symbol, horizon, exc)
        db.rollback()
        if batch_row is not None:
            _upsert_batch_job(
                db,
                symbol=symbol,
                horizon=horizon,
                status="failed",
                rq_job_id=rq_job_id,
                triggered_by=triggered_by,
                failed_units=len(ALL_FAMILIES),
                error_message=str(exc),
                finish=True,
            )
            db.commit()
        return {"symbol": symbol, "horizon": horizon, "status": "failed", "error": str(exc)}
    finally:
        db.close()


def enqueue_factor_x_ta_for_symbol(
    symbol: str,
    horizon: str,
    triggered_by: str = "manual",
    depends_on: str | None = None,
) -> str:
    """Enqueue a Factor×TA pipeline job to RQ and return the job id."""
    from rq import Queue

    from services.worker.config import settings

    redis = connect_redis_with_fallback(settings.REDIS_URL, decode_responses=False, logger=logger)
    q = Queue(settings.SIGNAL_ENGINE_QUEUE_NAME, connection=redis)
    job = q.enqueue(
        compute_factor_x_ta_for_symbol,
        symbol,
        horizon,
        job_timeout=1800,
        depends_on=depends_on,
        meta={"triggered_by": triggered_by},
    )
    db = SessionLocal()
    try:
        _upsert_batch_job(
            db,
            symbol=symbol,
            horizon=horizon,
            status="pending",
            rq_job_id=str(job.id),
            triggered_by=triggered_by,
        )
        db.commit()
    finally:
        db.close()
    return str(job.id)
