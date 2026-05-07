"""
Nightly factor-selection monitor.

Evaluates CUSUM and CUSUM-SQ independently for each active
(symbol, horizon, factor) tuple. When a factor invalidates, the task first
attempts a partial replacement from cached Stage-1 survivors.
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from sqlalchemy import text

from core.quant_core.factor_selection import calculate_cusum_drift
from core.quant_core.factor_selection.screen import compute_factor_transform
from core.quant_core.macro import fetch_macro_series, get_macro_series_by_id
from services.api.app.services.factor_selection_state import (
    invalidate_factor_x_ta_results,
    next_forced_recalibration,
    to_pipeline_horizon,
)
from services.worker.db import SessionLocal
from services.worker.tasks.factor_selection_full import HORIZON_FORWARD_DAYS, _load_stock_close

logger = logging.getLogger(__name__)


def _load_factor_signal(factor_id: str, transform_name: str) -> pd.Series | None:
    catalog = get_macro_series_by_id()
    spec = catalog.get(factor_id)
    if spec is None:
        return None
    try:
        factor_df = fetch_macro_series(spec, start="2010-01-01")
    except Exception:
        return None
    close_col = next((c for c in ["Close", "close", "Adj Close"] if c in factor_df.columns), None)
    if close_col is None:
        return None
    series = factor_df[close_col].dropna()
    if hasattr(series.index, "tz") and series.index.tz is not None:
        series.index = series.index.tz_convert(None)
    return compute_factor_transform(series, transform_name).shift(1)


def _lookup_stage1_candidate(db, symbol: str, horizon: str, excluded_factor_ids: set[str]) -> dict[str, Any] | None:
    rows = db.execute(
        text(
            """
            SELECT factor_canonical_id, ic_mean, ic_tstat, bh_p_adj
            FROM stock_factor_stage1_cache
            WHERE symbol = :symbol
              AND horizon = :horizon
              AND passed_fdr = true
            ORDER BY COALESCE(bh_p_adj, 1.0) ASC, ABS(ic_tstat) DESC, factor_canonical_id ASC
            """
        ),
        {"symbol": symbol, "horizon": horizon},
    ).mappings().all()
    for row in rows:
        factor_id = str(row["factor_canonical_id"])
        if factor_id not in excluded_factor_ids:
            return dict(row)
    return None


def _promote_replacement(
    db,
    *,
    symbol: str,
    horizon: str,
    candidate: dict[str, Any],
) -> None:
    db.execute(
        text(
            """
            INSERT INTO stock_factor_relevance
                (symbol, horizon, factor_canonical_id, rank, ic, ic_t_stat, bh_p_adj, lasso_coef,
                 relevance_score, last_calibrated_at, cusum_drift_score, cusum_alarm, cusum_status,
                 regime_start, low_confidence, next_forced_recal, history_n_days, created_at, updated_at)
            SELECT
                :symbol, :horizon, :factor_canonical_id,
                COALESCE(MAX(rank), 0) + 1,
                :ic, :ic_t_stat, :bh_p_adj, 0.0,
                0.0, NOW(), 0.0, false, 'valid',
                MAX(regime_start), MAX(low_confidence), :next_forced_recal, MAX(history_n_days), NOW(), NOW()
            FROM stock_factor_relevance
            WHERE symbol = :symbol AND horizon = :horizon
            ON CONFLICT (symbol, horizon, factor_canonical_id) DO UPDATE SET
                cusum_status = 'valid',
                cusum_alarm = false,
                updated_at = NOW(),
                next_forced_recal = EXCLUDED.next_forced_recal
            """
        ),
        {
            "symbol": symbol,
            "horizon": horizon,
            "factor_canonical_id": str(candidate["factor_canonical_id"]),
            "ic": float(candidate["ic_mean"]),
            "ic_t_stat": float(candidate["ic_tstat"]),
            "bh_p_adj": float(candidate["bh_p_adj"]) if candidate["bh_p_adj"] is not None else None,
            "next_forced_recal": next_forced_recalibration(),
        },
    )


def _resequence_ranks(db, symbol: str, horizon: str) -> None:
    rows = db.execute(
        text(
            """
            SELECT factor_canonical_id
            FROM stock_factor_relevance
            WHERE symbol = :symbol AND horizon = :horizon AND cusum_status = 'valid'
            ORDER BY ABS(COALESCE(lasso_coef, relevance_score)) DESC, factor_canonical_id ASC
            """
        ),
        {"symbol": symbol, "horizon": horizon},
    ).fetchall()
    for idx, row in enumerate(rows, start=1):
        db.execute(
            text(
                """
                UPDATE stock_factor_relevance
                SET rank = :rank, updated_at = NOW()
                WHERE symbol = :symbol AND horizon = :horizon AND factor_canonical_id = :factor_id
                """
            ),
            {"rank": idx, "symbol": symbol, "horizon": horizon, "factor_id": str(row[0])},
        )


def run_factor_selection_monitor() -> dict[str, Any]:
    logger.info("Starting nightly factor-selection monitor")
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT symbol, horizon, factor_canonical_id, ic, ic_t_stat, bh_p_adj, rank
                FROM stock_factor_relevance
                WHERE cusum_status = 'valid'
                ORDER BY symbol, horizon,
                         CASE WHEN rank IS NULL THEN 1 ELSE 0 END,
                         rank ASC,
                         factor_canonical_id
                """
            )
        ).mappings().all()
        if not rows:
            return {"status": "success", "monitored": 0, "alarms": 0, "replacements": 0}

        monitored = 0
        alarms = 0
        replacements = 0
        changed_pairs: set[tuple[str, str]] = set()
        for row in rows:
            symbol = str(row["symbol"])
            horizon = str(row["horizon"])
            factor_id = str(row["factor_canonical_id"])
            stock_close = _load_stock_close(symbol, db)
            if stock_close is None:
                continue

            signal = _load_factor_signal(factor_id, "change_1d")
            if signal is None:
                continue

            target_returns = stock_close.pct_change(HORIZON_FORWARD_DAYS[horizon]).shift(-HORIZON_FORWARD_DAYS[horizon])
            drift = calculate_cusum_drift(target_returns, signal)
            monitored += 1

            db.execute(
                text(
                    """
                    UPDATE stock_factor_relevance
                    SET cusum_drift_score = :score,
                        cusum_alarm = :alarm,
                        updated_at = NOW()
                    WHERE symbol = :symbol AND horizon = :horizon AND factor_canonical_id = :factor_id
                    """
                ),
                {
                    "score": float(drift["drift_score"]),
                    "alarm": bool(drift["alarm"]),
                    "symbol": symbol,
                    "horizon": horizon,
                    "factor_id": factor_id,
                },
            )

            if not bool(drift["alarm"]):
                continue

            alarms += 1
            db.execute(
                text(
                    """
                    UPDATE stock_factor_relevance
                    SET cusum_status = 'invalidated',
                        cusum_alarm = true,
                        updated_at = NOW()
                    WHERE symbol = :symbol AND horizon = :horizon AND factor_canonical_id = :factor_id
                    """
                ),
                {"symbol": symbol, "horizon": horizon, "factor_id": factor_id},
            )
            excluded = {
                str(r[0])
                for r in db.execute(
                    text(
                        "SELECT factor_canonical_id FROM stock_factor_relevance WHERE symbol = :symbol AND horizon = :horizon AND cusum_status = 'valid'"
                    ),
                    {"symbol": symbol, "horizon": horizon},
                ).fetchall()
            }
            excluded.add(factor_id)
            replacement = _lookup_stage1_candidate(db, symbol, horizon, excluded)
            if replacement is not None:
                _promote_replacement(db, symbol=symbol, horizon=horizon, candidate=replacement)
                _resequence_ranks(db, symbol, horizon)
                replacements += 1
            else:
                _resequence_ranks(db, symbol, horizon)

            invalidate_factor_x_ta_results(db, symbol, horizon)
            changed_pairs.add((symbol, horizon))

        db.commit()

        if changed_pairs:
            from services.worker.tasks.factor_x_ta_batch import enqueue_factor_x_ta_for_symbol
            from services.worker.tasks.wfo_factor_x_ta_batch import enqueue_wfo_factor_x_ta_for_symbol

            for symbol, horizon in sorted(changed_pairs):
                enqueue_factor_x_ta_for_symbol(symbol, to_pipeline_horizon(horizon), triggered_by="factor_monitor")
                enqueue_wfo_factor_x_ta_for_symbol(symbol, to_pipeline_horizon(horizon), triggered_by="factor_monitor")

        return {
            "status": "success",
            "monitored": monitored,
            "alarms": alarms,
            "replacements": replacements,
        }
    except Exception as exc:
        db.rollback()
        logger.exception("Error in factor selection monitor")
        return {"status": "error", "reason": str(exc)}
    finally:
        db.close()
