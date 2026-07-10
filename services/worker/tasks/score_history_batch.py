"""Populate `signal_score_history` for one symbol.

For each (source ∈ {engine_legacy, engine_expanded, wfo}, horizon ∈ {weekly,
monthly, quarterly}, category ∈ {tendance, momentum, oscillation, volume}) we
reconstruct a per-bar score series from the persisted representatives and
upsert it into `signal_score_history`.

Triggered by the analytics router's predictive-history endpoints.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from services.worker.db import SessionLocal
from services.api.app.market_data_loader import load_ohlcv_for_symbol
from services.api.app import models
from core.quant_core.data import drop_incomplete_ohlcv_rows
from core.quant_core.research.score_history import (
    _variant_from_rep,
    build_engine_category_series,
    build_wfo_category_series,
)
from core.quant_core.research.oos_index import oos_windows_from_wfo
from core.quant_core.signal_engine.factor_x_ta import precompute_factor_x_ta_signals
from core.quant_core.signal_engine.modes import (
    ALL_SIGNAL_MODE_NAMES,
    resolve_signal_mode,
    signal_mode_read_names,
    signal_mode_storage_name,
)
from core.quant_core.signal_engine.ta_combo import compute_strict_and_combo_signal, is_combo_variant, variant_from_component
from core.quant_core.signal_engine.variant_detail import compute_variant_signal_array
from core.quant_core.signal_engine.wfo_signal import build_category_candidate_grid
from core.quant_core.signal_engine.domain import VARIANT_FAMILIES


logger = logging.getLogger(__name__)

HORIZONS = ("weekly", "monthly", "quarterly")
ENGINE_VARIANTS = ALL_SIGNAL_MODE_NAMES
WFO_VARIANTS = ALL_SIGNAL_MODE_NAMES


def _score_source(kind: str, variant: str) -> str:
    return f"{kind}:{signal_mode_storage_name(variant)}"


def _compat_sources(kind: str, variant: str) -> tuple[str, ...]:
    variant = signal_mode_storage_name(variant)
    aliases: list[str] = []
    if kind == "engine":
        if variant == "legacy_ta_simple":
            aliases.append("engine_legacy")
        elif variant == "expanded_ta_simple":
            aliases.append("engine_expanded")
        elif variant == "expanded_factor_x_ta_simple":
            aliases.append("factor_x_ta")
    elif kind == "wfo" and variant == "expanded_ta_simple":
        aliases.append("wfo")
    return tuple(aliases)


def _upsert_job(db: Session, symbol: str, status: str, error: str | None = None) -> None:
    now = datetime.now(timezone.utc)
    row = db.query(models.ScoreHistoryJob).filter_by(symbol=symbol).first()
    if row is None:
        row = models.ScoreHistoryJob(symbol=symbol, status=status,
                                     started_at=now if status == "running" else None,
                                     error_message=error)
        db.add(row)
    else:
        row.status = status
        row.error_message = error
        if status == "running":
            row.started_at = now
        if status in ("succeeded", "failed"):
            row.finished_at = now
    db.commit()


def _ohlcv_arrays(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray | None,
                                             np.ndarray | None, np.ndarray | None,
                                             pd.DatetimeIndex]:
    df = drop_incomplete_ohlcv_rows(df).copy()
    df = df.sort_index()

    def _pick(names: list[str]) -> np.ndarray | None:
        for n in names:
            if n in df.columns:
                return df[n].to_numpy(dtype="float64")
        return None

    close_arr = _pick(["Close", "close", "Adj Close"])
    if close_arr is None:
        raise ValueError("OHLCV frame has no Close column")
    close = close_arr
    volume = _pick(["Volume", "volume"])
    high = _pick(["High", "high"])
    low = _pick(["Low", "low"])
    idx = pd.DatetimeIndex(df.index)
    return close, volume, high, low, idx


def _replace_history(db: Session, symbol: str, source: str, horizon: str,
                     series_by_cat: dict[str, pd.Series],
                     *,
                     delete_sources: tuple[str, ...] = (),
                     is_oos_dates_by_cat: dict[str, set[pd.Timestamp]] | None = None) -> int:
    """Upsert the per-bar series into signal_score_history. Returns row count."""
    # Wipe the existing slice for atomicity, then bulk-insert.
    sources_to_delete = tuple(dict.fromkeys((source, *delete_sources)))
    db.query(models.SignalScoreHistory).filter(
        models.SignalScoreHistory.symbol == symbol,
        models.SignalScoreHistory.horizon == horizon,
        models.SignalScoreHistory.source.in_(sources_to_delete),
    ).delete(synchronize_session=False)

    rows: list[dict[str, Any]] = []
    for category, series in series_by_cat.items():
        s = series.dropna()
        if s.empty:
            continue
        oos_dates = (is_oos_dates_by_cat or {}).get(category, set())
        for ts, val in s.items():
            try:
                d = pd.Timestamp(ts).date()
            except Exception:
                continue
            try:
                v = float(val)
                if not np.isfinite(v):
                    continue
            except (TypeError, ValueError):
                continue
            rows.append({
                "date": d,
                "symbol": symbol,
                "source": source,
                "category": category,
                "horizon": horizon,
                "score_pct": v,
                "is_oos": pd.Timestamp(ts) in oos_dates,
            })

    if rows:
        # Insert in chunks to avoid huge single-statement payloads.
        chunk = 5000
        for i in range(0, len(rows), chunk):
            db.execute(pg_insert(models.SignalScoreHistory), rows[i:i + chunk])
        db.commit()
    return len(rows)


def _engine_family_rows(db: Session, symbol: str, horizon: str, variant: str
                        ) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for read_variant in signal_mode_read_names(variant):
        fam_rows = (
            db.query(models.SignalEngineFamilyResult)
            .filter_by(symbol=symbol, horizon=horizon, variant=read_variant, status="succeeded")
            .all()
        )
        for r in fam_rows:
            reps = r.representatives_json or []
            if isinstance(reps, list) and reps and r.family not in out:
                out[r.family] = reps
    return out


def _wfo_category_reps(db: Session, symbol: str, horizon: str, variant: str
                       ) -> dict[str, models.WfoSignalSummary]:
    out: dict[str, models.WfoSignalSummary] = {}
    for read_variant in signal_mode_read_names(variant):
        rows = (
            db.query(models.WfoSignalSummary)
            .filter_by(symbol=symbol, horizon=horizon, variant=read_variant, status="succeeded")
            .all()
        )
        for r in rows:
            reps = r.representatives_json or []
            if isinstance(reps, list) and reps and r.category not in out:
                out[r.category] = r
    return out


def _candidate_pool_for(row: models.WfoSignalSummary) -> list:
    families = VARIANT_FAMILIES.get(row.variant or "expanded", VARIANT_FAMILIES["expanded"]).get(row.category)
    try:
        return build_category_candidate_grid(row.category, row.horizon, families=families)
    except Exception:
        return []


def _fold_scoped_wfo_series(
    *,
    row: models.WfoSignalSummary,
    base_series: pd.Series,
    close: np.ndarray,
    volume: np.ndarray | None,
    high: np.ndarray | None,
    low: np.ndarray | None,
    index: pd.DatetimeIndex,
) -> pd.Series:
    """Override WFO OOS bars with the winner variant selected for each fold."""
    out = base_series.copy()
    windows = oos_windows_from_wfo(row.folds_json, ohlcv_index=index)
    if not windows:
        return out

    pool = _candidate_pool_for(row)
    by_id = {str(v.variant_id): v for v in pool}
    signal_cache: dict[str, pd.Series] = {}

    for window in windows:
        winner_id = str(window.winner_variant_id or "").strip()
        variant = by_id.get(winner_id)
        if variant is None:
            continue
        if winner_id not in signal_cache:
            sig = compute_variant_signal_array(
                close,
                variant,
                volume=volume,
                high=high,
                low=low,
            )
            signal_cache[winner_id] = pd.Series(sig * 100.0, index=index, name=row.category)
        mask = (index >= window.start) & (index <= window.end)
        out.loc[index[mask]] = signal_cache[winner_id].loc[index[mask]]

    return out


def _dates_for_windows(
    index: pd.DatetimeIndex,
    folds_json: Any,
) -> set[pd.Timestamp]:
    windows = oos_windows_from_wfo(folds_json, ohlcv_index=index)
    if not windows:
        return set()
    out: set[pd.Timestamp] = set()
    for window in windows:
        mask = (index >= window.start) & (index <= window.end)
        out.update(pd.Timestamp(ts) for ts in index[mask])
    return out


def _reps_from_family_rows(family_rows: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    return [rep for reps in family_rows.values() for rep in reps if isinstance(rep, dict)]


def _reps_from_wfo_rows(cat_rows: dict[str, models.WfoSignalSummary]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in cat_rows.values():
        out.extend(rep for rep in (row.representatives_json or []) if isinstance(rep, dict))
    return out


def _factor_conditions_from_variant(variant) -> list:
    conditions = []
    condition = getattr(variant, "factor_condition", None)
    if condition is not None:
        conditions.append(condition)
    if is_combo_variant(variant):
        for payload in variant.params.get("components", []):
            if not isinstance(payload, dict):
                continue
            try:
                component = variant_from_component(payload)
            except Exception:
                continue
            component_condition = getattr(component, "factor_condition", None)
            if component_condition is not None:
                conditions.append(component_condition)
    return conditions


def _factor_precomputed_signals(
    db: Session,
    ohlcv: pd.DataFrame,
    reps: list[dict[str, Any]],
    *,
    close: np.ndarray,
    volume: np.ndarray | None,
    high: np.ndarray | None,
    low: np.ndarray | None,
) -> dict[str, np.ndarray]:
    variants = [v for rep in reps if (v := _variant_from_rep(rep)) is not None]
    conditions = []
    for variant in variants:
        conditions.extend(_factor_conditions_from_variant(variant))
    if not conditions:
        return {}

    from services.worker.tasks.factor_x_ta_batch import _align_factor_arrays_for_conditions

    aligned_factor_arrays = _align_factor_arrays_for_conditions(db, ohlcv, conditions)
    if not aligned_factor_arrays:
        return {}

    component_variants = []
    for variant in variants:
        if getattr(variant, "factor_condition", None) is not None:
            component_variants.append(variant)
        if is_combo_variant(variant):
            for payload in variant.params.get("components", []):
                if isinstance(payload, dict):
                    try:
                        component_variants.append(variant_from_component(payload))
                    except Exception:
                        continue

    precomputed = precompute_factor_x_ta_signals(
        component_variants,
        close,
        aligned_factor_arrays,
        volume=volume,
        high=high,
        low=low,
    )

    for variant in variants:
        if not is_combo_variant(variant) or variant.variant_id in precomputed:
            continue

        def _compute_component(component) -> np.ndarray:
            if component.variant_id in precomputed:
                return precomputed[component.variant_id]
            return compute_variant_signal_array(
                close,
                component,
                volume=volume,
                high=high,
                low=low,
            )

        try:
            precomputed[variant.variant_id] = compute_strict_and_combo_signal(
                close,
                variant,
                compute_component_signal=_compute_component,
            )
        except Exception:
            continue

    return precomputed


def run_score_history_for_symbol(db: Session, symbol: str) -> dict[str, int]:
    """Compute and persist all (source, horizon) score series for one symbol."""
    df = drop_incomplete_ohlcv_rows(load_ohlcv_for_symbol(db, symbol)).copy().sort_index()
    close, volume, high, low, idx = _ohlcv_arrays(df)
    if len(close) < 100:
        raise ValueError(f"Not enough bars for {symbol}: {len(close)}")

    summary = {
        **{_score_source("engine", variant): 0 for variant in ENGINE_VARIANTS},
        **{_score_source("wfo", variant): 0 for variant in WFO_VARIANTS},
    }

    for horizon in HORIZONS:
        for variant in ENGINE_VARIANTS:
            family_rows = _engine_family_rows(db, symbol, horizon, variant)
            if not family_rows:
                continue
            precomputed = (
                _factor_precomputed_signals(
                    db,
                    df,
                    _reps_from_family_rows(family_rows),
                    close=close,
                    volume=volume,
                    high=high,
                    low=low,
                )
                if resolve_signal_mode(variant).is_factor_x_ta
                else {}
            )
            series = build_engine_category_series(
                symbol=symbol, horizon=horizon, variant=variant,
                close=close, volume=volume, high=high, low=low,
                family_rows=family_rows, index=idx,
                precomputed_signals=precomputed,
            )
            source = _score_source("engine", variant)
            summary[source] += _replace_history(
                db,
                symbol,
                source,
                horizon,
                series,
                delete_sources=_compat_sources("engine", variant),
            )

        for variant in WFO_VARIANTS:
            cat_reps = _wfo_category_reps(db, symbol, horizon, variant)
            if not cat_reps:
                continue
            precomputed = (
                _factor_precomputed_signals(
                    db,
                    df,
                    _reps_from_wfo_rows(cat_reps),
                    close=close,
                    volume=volume,
                    high=high,
                    low=low,
                )
                if resolve_signal_mode(variant).is_factor_x_ta
                else {}
            )
            category_reps = {
                category: list(row.representatives_json or [])
                for category, row in cat_reps.items()
            }
            series = build_wfo_category_series(
                symbol=symbol, horizon=horizon,
                close=close, volume=volume, high=high, low=low,
                category_reps=category_reps, index=idx,
                precomputed_signals=precomputed,
            )
            for category, row in cat_reps.items():
                if category in series:
                    series[category] = _fold_scoped_wfo_series(
                        row=row,
                        base_series=series[category],
                        close=close,
                        volume=volume,
                        high=high,
                        low=low,
                        index=idx,
                    )
            is_oos_dates_by_cat = {
                category: _dates_for_windows(idx, row.folds_json)
                for category, row in cat_reps.items()
            }
            source = _score_source("wfo", variant)
            summary[source] += _replace_history(
                db,
                symbol,
                source,
                horizon,
                series,
                delete_sources=_compat_sources("wfo", variant),
                is_oos_dates_by_cat=is_oos_dates_by_cat,
            )

    return summary


def dispatch_score_history_for_all_symbols(db: Session) -> dict[str, Any]:
    """Collect every WFO/Signal-Engine symbol, upsert a pending ScoreHistoryJob row,
    and enqueue a score_history job for each on the ``score_history`` RQ queue.

    Shared core used by both the admin HTTP endpoint
    (``analytics.trigger_all_predictive_history``) and the scheduled weekly
    dispatcher (``scheduler_dispatch._dispatch_signal_history``).
    """
    from redis import Redis
    from rq import Queue
    from services.api.app.config import settings
    from services.api.app.routers.analytics import _invalidate_leaderboard_cache

    wfo_syms = {s for (s,) in db.query(models.WfoSignalSummary.symbol).distinct().all()}
    eng_syms = {s for (s,) in db.query(models.SignalEngineGlobalResult.symbol).distinct().all()}
    symbols = list(wfo_syms | eng_syms)
    if not symbols:
        return {"enqueued_jobs": 0, "triggered": 0, "job_ids": [], "job_ids_sample": []}

    redis_conn = Redis.from_url(settings.REDIS_URL, decode_responses=False)
    q = Queue("score_history", connection=redis_conn)

    job_ids: list[str] = []
    for sym in symbols:
        row = db.query(models.ScoreHistoryJob).filter_by(symbol=sym).first()
        if row is None:
            row = models.ScoreHistoryJob(symbol=sym, status="pending")
            db.add(row)
        else:
            row.status = "pending"
            row.error_message = None
        job = q.enqueue(
            "services.worker.tasks.score_history_batch.enqueue_score_history_for_symbol",
            sym,
            job_timeout=7200,
        )
        row.rq_job_id = str(job.id)
        job_ids.append(str(job.id))
    db.commit()
    _invalidate_leaderboard_cache()
    return {
        "enqueued_jobs": len(job_ids),
        "triggered": len(symbols),
        "symbols": len(symbols),
        "job_ids": job_ids,
        "job_ids_sample": job_ids[:20],
    }


def enqueue_score_history_for_symbol(symbol: str) -> dict[str, int] | None:
    """RQ entry point — runs in the worker process."""
    db: Session = SessionLocal()
    try:
        _upsert_job(db, symbol, "running")
        try:
            summary = run_score_history_for_symbol(db, symbol)
            _upsert_job(db, symbol, "succeeded")
            return summary
        except Exception as exc:
            logger.exception("score_history failed: %s", symbol)
            _upsert_job(db, symbol, "failed", error=str(exc)[:500])
            raise
    finally:
        db.close()
