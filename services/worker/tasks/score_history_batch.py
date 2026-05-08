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
    build_engine_category_series,
    build_wfo_category_series,
)
from core.quant_core.research.oos_index import oos_windows_from_wfo
from core.quant_core.signal_engine.variant_detail import compute_variant_signal_array
from core.quant_core.signal_engine.wfo_signal import build_category_candidate_grid
from core.quant_core.signal_engine.domain import VARIANT_FAMILIES


logger = logging.getLogger(__name__)

HORIZONS = ("weekly", "monthly", "quarterly")
ENGINE_VARIANTS = ("legacy", "expanded")


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
                     is_oos_dates_by_cat: dict[str, set[pd.Timestamp]] | None = None) -> int:
    """Upsert the per-bar series into signal_score_history. Returns row count."""
    # Wipe the existing slice for atomicity, then bulk-insert.
    db.query(models.SignalScoreHistory).filter_by(
        symbol=symbol, source=source, horizon=horizon,
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
    fam_rows = (
        db.query(models.SignalEngineFamilyResult)
        .filter_by(symbol=symbol, horizon=horizon, variant=variant, status="succeeded")
        .all()
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for r in fam_rows:
        reps = r.representatives_json or []
        if isinstance(reps, list) and reps:
            out[r.family] = reps
    return out


def _wfo_category_reps(db: Session, symbol: str, horizon: str
                       ) -> dict[str, models.WfoSignalSummary]:
    rows = (
        db.query(models.WfoSignalSummary)
        .filter_by(symbol=symbol, horizon=horizon, variant="expanded", status="succeeded")
        .all()
    )
    out: dict[str, models.WfoSignalSummary] = {}
    for r in rows:
        reps = r.representatives_json or []
        if isinstance(reps, list) and reps:
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


def run_score_history_for_symbol(db: Session, symbol: str) -> dict[str, int]:
    """Compute and persist all (source, horizon) score series for one symbol."""
    df = load_ohlcv_for_symbol(db, symbol)
    close, volume, high, low, idx = _ohlcv_arrays(df)
    if len(close) < 100:
        raise ValueError(f"Not enough bars for {symbol}: {len(close)}")

    summary = {"engine_legacy": 0, "engine_expanded": 0, "wfo": 0}

    for horizon in HORIZONS:
        # Engine legacy + expanded
        for variant in ENGINE_VARIANTS:
            family_rows = _engine_family_rows(db, symbol, horizon, variant)
            if not family_rows:
                continue
            series = build_engine_category_series(
                symbol=symbol, horizon=horizon, variant=variant,
                close=close, volume=volume, high=high, low=low,
                family_rows=family_rows, index=idx,
            )
            source = f"engine_{variant}"
            summary[source] += _replace_history(db, symbol, source, horizon, series)

        # WFO
        cat_reps = _wfo_category_reps(db, symbol, horizon)
        if cat_reps:
            category_reps = {
                category: list(row.representatives_json or [])
                for category, row in cat_reps.items()
            }
            series = build_wfo_category_series(
                symbol=symbol, horizon=horizon,
                close=close, volume=volume, high=high, low=low,
                category_reps=category_reps, index=idx,
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
            summary["wfo"] += _replace_history(
                db,
                symbol,
                "wfo",
                horizon,
                series,
                is_oos_dates_by_cat=is_oos_dates_by_cat,
            )

    return summary


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
