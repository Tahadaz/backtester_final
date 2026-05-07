"""
Full econometric factor selection task.

Runs the approved three-stage pipeline independently for short / mid / long
selection horizons, persists the results, and re-enqueues Factor×TA outputs
only for horizons whose active top-3 set changed.
"""
from __future__ import annotations

import logging
from io import BytesIO
from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy import text

from core.quant_core.factor_selection import (
    DirectSelectionConfig,
    detect_regime_window,
    rank_direct_factors,
    select_direct_factors,
)
from core.quant_core.macro import fetch_macro_series, get_macro_series
from services.api.app.market_data_loader import find_latest_dataset_for_symbol, load_close_series_from_dataset
from services.api.app.models import MarketDataStore
from services.api.app.services.factor_selection_state import (
    SELECTION_HORIZONS,
    active_factor_ids_for_symbol_horizon,
    invalidate_factor_x_ta_results,
    next_forced_recalibration,
    selected_factors_changed,
    to_pipeline_horizon,
)
from services.api.app.config import settings
from services.api.app.storage import s3_client
from services.worker.db import SessionLocal

logger = logging.getLogger(__name__)

HORIZON_FORWARD_DAYS = {
    "short": 5,
    "mid": 21,
    "long": 63,
}


def _load_stock_close(symbol: str, db) -> pd.Series | None:
    store_row = (
        db.query(MarketDataStore)
        .filter(MarketDataStore.symbol == symbol, MarketDataStore.timeframe == "1D")
        .first()
    )
    if store_row:
        try:
            data = (
                s3_client()
                .get_object(Bucket=settings.S3_BUCKET, Key=str(store_row.object_key))["Body"]
                .read()
            )
            df = pd.read_parquet(BytesIO(data))
            close_col = next((c for c in ["Close", "close", "Adj Close"] if c in df.columns), None)
            if close_col:
                series = df[close_col].dropna()
                if hasattr(df.index, "tz") and df.index.tz is not None:
                    series.index = df.index.tz_convert(None)
                return series
        except Exception:
            pass

    dataset_row = find_latest_dataset_for_symbol(db=db, symbol=symbol)
    if dataset_row:
        series = load_close_series_from_dataset(dataset_row=dataset_row, symbol=symbol)
        if series is not None and hasattr(series.index, "tz") and series.index.tz is not None:
            series.index = series.index.tz_convert(None)
        return series

    return None


def _load_factor_close_series() -> dict[str, pd.Series]:
    results: dict[str, pd.Series] = {}
    for spec in get_macro_series():
        try:
            factor_df = fetch_macro_series(spec, start="2010-01-01")
        except Exception as exc:
            logger.debug("Failed to fetch factor %s: %s", spec.canonical_id, exc)
            continue
        close_col = next((c for c in ["Close", "close", "Adj Close"] if c in factor_df.columns), None)
        if close_col is None:
            continue
        series = factor_df[close_col].dropna()
        if hasattr(series.index, "tz") and series.index.tz is not None:
            series.index = series.index.tz_convert(None)
        results[spec.canonical_id] = series
    return results


def _usable_factor_ids_for_factor_x_ta() -> set[str]:
    """Return canonical factor IDs that have pre-registered Factor×TA conditions."""
    try:
        from services.worker.tasks.factor_x_ta_batch import (
            _build_conditions,
            _build_ticker_to_canonical,
            _load_pre_registration,
        )

        ticker_to_canonical = _build_ticker_to_canonical()
        conditions = _build_conditions(_load_pre_registration())
        return {
            str(ticker_to_canonical.get(condition.factor_ticker, condition.factor_ticker))
            for condition in conditions
        }
    except Exception as exc:
        logger.warning("Could not load Factor×TA usable factor universe: %s", exc)
        return set()


def _write_stage1_cache(
    db,
    *,
    symbol: str,
    horizon: str,
    diagnostic_rows: pd.DataFrame,
    regime_start: date | None,
    low_confidence: bool,
    history_n_days: int,
) -> None:
    db.execute(
        text("DELETE FROM stock_factor_stage1_cache WHERE symbol = :symbol AND horizon = :horizon"),
        {"symbol": symbol, "horizon": horizon},
    )
    if diagnostic_rows.empty:
        return

    payload = []
    for _, row in diagnostic_rows.iterrows():
        factor_canonical_id = str(row["factor_id"])
        spearman_ic = float(row["spearman_ic"])
        pearson_corr = float(row["pearson_corr"])
        ic_t_stat = float(row["ic_t_stat"])
        score = float(row["relevance_score"])
        selected_reason = str(row.get("selected_reason") or "not_selected")
        payload.append(
            {
                "symbol": symbol,
                "horizon": horizon,
                "factor_canonical_id": factor_canonical_id,
                "factor_id": factor_canonical_id,
                "ic_mean": spearman_ic,
                "spearman_ic": spearman_ic,
                "pearson_corr": pearson_corr,
                "ic_tstat": ic_t_stat,
                "relevance_score": score,
                "n_obs": int(row["n_obs"]),
                "selected_reason": selected_reason,
                "bh_p_adj": None,
                "passed_fdr": selected_reason == "normal",
                "regime_start": regime_start,
                "low_confidence": low_confidence,
                "history_n_days": history_n_days,
            }
        )
    db.execute(
        text(
            """
            INSERT INTO stock_factor_stage1_cache
                (symbol, horizon, factor_canonical_id, factor_id, ic_mean, spearman_ic, pearson_corr,
                 ic_tstat, bh_p_adj, relevance_score, n_obs, selected_reason, passed_fdr,
                 regime_start, low_confidence, history_n_days, calculated_at)
            VALUES
                (:symbol, :horizon, :factor_canonical_id, :factor_id, :ic_mean, :spearman_ic, :pearson_corr,
                 :ic_tstat, :bh_p_adj, :relevance_score, :n_obs, :selected_reason, :passed_fdr,
                 :regime_start, :low_confidence, :history_n_days, NOW())
            """
        ),
        payload,
    )


def _persist_selected_factors(
    db,
    *,
    symbol: str,
    horizon: str,
    target_rows: list[dict[str, Any]],
) -> None:
    db.execute(
        text(
            """
            UPDATE stock_factor_relevance
            SET cusum_status = 'invalidated',
                cusum_alarm = true,
                updated_at = NOW()
            WHERE symbol = :symbol AND horizon = :horizon
            """
        ),
        {"symbol": symbol, "horizon": horizon},
    )
    if not target_rows:
        return
    db.execute(
        text(
            """
            INSERT INTO stock_factor_relevance
                (symbol, horizon, factor_canonical_id, factor_id, rank, ic, spearman_ic, pearson_corr,
                 ic_t_stat, bh_p_adj, lasso_coef, relevance_score, n_obs, selected_reason,
                 last_calibrated_at, cusum_drift_score,
                 cusum_alarm, cusum_status, regime_start, low_confidence,
                 next_forced_recal, history_n_days, created_at, updated_at)
            VALUES
                (:symbol, :horizon, :factor_canonical_id, :factor_canonical_id, :rank, :ic, :spearman_ic,
                 :pearson_corr, :ic_t_stat, :bh_p_adj, :lasso_coef, :relevance_score, :n_obs,
                 :selected_reason, NOW(), 0.0,
                 false, 'valid', :regime_start, :low_confidence,
                 :next_forced_recal, :history_n_days, NOW(), NOW())
            ON CONFLICT (symbol, horizon, factor_canonical_id) DO UPDATE SET
                rank = EXCLUDED.rank,
                ic = EXCLUDED.ic,
                spearman_ic = EXCLUDED.spearman_ic,
                pearson_corr = EXCLUDED.pearson_corr,
                ic_t_stat = EXCLUDED.ic_t_stat,
                bh_p_adj = EXCLUDED.bh_p_adj,
                lasso_coef = EXCLUDED.lasso_coef,
                relevance_score = EXCLUDED.relevance_score,
                n_obs = EXCLUDED.n_obs,
                selected_reason = EXCLUDED.selected_reason,
                last_calibrated_at = NOW(),
                cusum_drift_score = 0.0,
                cusum_alarm = false,
                cusum_status = 'valid',
                regime_start = EXCLUDED.regime_start,
                low_confidence = EXCLUDED.low_confidence,
                next_forced_recal = EXCLUDED.next_forced_recal,
                history_n_days = EXCLUDED.history_n_days,
                updated_at = NOW()
            """
        ),
        target_rows,
    )


def _enqueue_factor_x_ta_refresh(symbol: str, selection_horizon: str) -> None:
    try:
        from services.worker.tasks.factor_x_ta_batch import enqueue_factor_x_ta_for_symbol
        from services.worker.tasks.wfo_factor_x_ta_batch import enqueue_wfo_factor_x_ta_for_symbol

        pipeline_horizon = to_pipeline_horizon(selection_horizon)
        enqueue_factor_x_ta_for_symbol(symbol, pipeline_horizon, triggered_by="factor_selection")
        enqueue_wfo_factor_x_ta_for_symbol(symbol, pipeline_horizon, triggered_by="factor_selection")
    except Exception as exc:
        logger.warning("Failed to enqueue Factor×TA refresh for %s/%s: %s", symbol, selection_horizon, exc)


def _run_one_horizon(
    db,
    *,
    symbol: str,
    horizon: str,
    stock_close: pd.Series,
    factor_close_by_id: dict[str, pd.Series],
    usable_factor_ids: set[str],
) -> dict[str, Any]:
    previous_active = active_factor_ids_for_symbol_horizon(db, symbol, horizon)
    regime = detect_regime_window(stock_close)
    regime_start = regime.regime_start
    sample_close = stock_close if regime_start is None else stock_close.loc[stock_close.index >= regime_start]
    if len(sample_close) < 60:
        sample_close = stock_close

    config = DirectSelectionConfig(horizon_days=HORIZON_FORWARD_DAYS[horizon])
    diagnostics = rank_direct_factors(
        sample_close,
        factor_close_by_id,
        config=config,
    )
    selected = select_direct_factors(
        diagnostics,
        usable_factor_ids=usable_factor_ids,
        config=config,
    )
    selected_ids = set(selected["factor_id"].astype(str).tolist()) if not selected.empty else set()
    if not diagnostics.empty:
        reason_by_id = {
            str(row["factor_id"]): str(row["selected_reason"])
            for _, row in selected.iterrows()
        }
        diagnostics = diagnostics.copy()
        diagnostics["selected_reason"] = diagnostics.apply(
            lambda row: reason_by_id.get(str(row["factor_id"]), str(row["selected_reason"])),
            axis=1,
        )

    _write_stage1_cache(
        db,
        symbol=symbol,
        horizon=horizon,
        diagnostic_rows=diagnostics,
        regime_start=regime_start.date() if regime_start is not None else None,
        low_confidence=regime.low_confidence,
        history_n_days=regime.history_n_days,
    )

    if selected.empty:
        _persist_selected_factors(db, symbol=symbol, horizon=horizon, target_rows=[])
        current_active: list[str] = []
    else:
        next_recal = next_forced_recalibration()
        payload = []
        selected = selected.sort_values("rank")
        current_active = selected["factor_id"].astype(str).tolist()
        for _, row in selected.iterrows():
            factor_id = str(row["factor_id"])
            selected_reason = str(row["selected_reason"])
            low_confidence = bool(regime.low_confidence or selected_reason == "low_confidence")
            score = float(row["relevance_score"])
            spearman_ic = float(row["spearman_ic"])
            payload.append(
                {
                    "symbol": symbol,
                    "horizon": horizon,
                    "factor_canonical_id": factor_id,
                    "rank": int(row["rank"]),
                    "ic": spearman_ic,
                    "spearman_ic": spearman_ic,
                    "pearson_corr": float(row["pearson_corr"]),
                    "ic_t_stat": float(row["ic_t_stat"]),
                    "bh_p_adj": None,
                    "lasso_coef": None,
                    "relevance_score": score,
                    "n_obs": int(row["n_obs"]),
                    "selected_reason": selected_reason,
                    "regime_start": regime_start.date() if regime_start is not None else None,
                    "low_confidence": low_confidence,
                    "next_forced_recal": next_recal,
                    "history_n_days": regime.history_n_days,
                }
            )
        _persist_selected_factors(db, symbol=symbol, horizon=horizon, target_rows=payload)

    changed = selected_factors_changed(previous_active, current_active)
    if changed:
        invalidate_factor_x_ta_results(db, symbol, horizon)
    return {
        "horizon": horizon,
        "previous_active": previous_active,
        "selected": current_active,
        "changed": changed,
        "regime_start": regime_start.date().isoformat() if regime_start is not None else None,
        "low_confidence": regime.low_confidence,
        "history_n_days": regime.history_n_days,
        "usable_factor_ids": sorted(usable_factor_ids),
        "selected_from_usable": sorted(selected_ids),
    }


def run_factor_selection_for_symbol(symbol: str, auto_enqueue: bool = True) -> dict[str, Any]:
    logger.info("Starting factor selection for %s", symbol)
    db = SessionLocal()
    symbol = symbol.upper()

    try:
        stock_close = _load_stock_close(symbol, db)
        if stock_close is None or len(stock_close.dropna()) < 90:
            return {"status": "skipped", "reason": "insufficient_data", "symbol": symbol}

        factor_close_by_id = _load_factor_close_series()
        if not factor_close_by_id:
            return {"status": "skipped", "reason": "factor_data_unavailable", "symbol": symbol}
        usable_factor_ids = _usable_factor_ids_for_factor_x_ta()
        if not usable_factor_ids:
            return {"status": "skipped", "reason": "factor_condition_universe_unavailable", "symbol": symbol}

        horizon_results: list[dict[str, Any]] = []
        refresh_horizons: list[str] = []
        for horizon in SELECTION_HORIZONS:
            result = _run_one_horizon(
                db,
                symbol=symbol,
                horizon=horizon,
                stock_close=stock_close,
                factor_close_by_id=factor_close_by_id,
                usable_factor_ids=usable_factor_ids,
            )
            horizon_results.append(result)
            if result["changed"]:
                refresh_horizons.append(horizon)

        db.commit()

        if auto_enqueue:
            for horizon in refresh_horizons:
                _enqueue_factor_x_ta_refresh(symbol, horizon)

        return {
            "status": "success",
            "symbol": symbol,
            "horizons": horizon_results,
            "refresh_horizons": refresh_horizons,
        }
    except Exception as exc:
        db.rollback()
        logger.exception("Error during factor selection for %s", symbol)
        return {"status": "error", "symbol": symbol, "reason": str(exc)}
    finally:
        db.close()
