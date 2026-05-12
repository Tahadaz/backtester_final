"""Batch task: compute and persist signal-based backtests + Monte Carlo."""
from __future__ import annotations

import logging
import time
import uuid
from datetime import date, datetime, timezone
from itertools import combinations
from typing import Any

import numpy as np
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from core.quant_core.horizons import DEFAULT_COST_BPS_PER_SIDE
from core.quant_core.data import drop_incomplete_ohlcv_rows
from core.quant_core.risk import monte_carlo_equity_paths, shuffled_trade_analysis
from core.quant_core.signal_engine.backtest_mc import (
    all_category_subsets,
    build_category_signal_series_engine,
    build_category_signal_series_wfo,
    build_combination_signal_series,
    build_global_signal_series,
    compute_input_hash,
    run_signal_backtest,
)
from core.quant_core.signal_engine.domain import CATEGORY_FAMILIES, FactorConditionMeta, VariantDef
from core.quant_core.signal_engine.factor_x_ta import _compute_ta_signal_for_conditioned
from core.quant_core.signal_engine.modes import resolve_signal_mode, signal_mode_storage_name
from core.quant_core.signal_engine.ta_combo import compute_strict_and_combo_signal, is_combo_variant
from core.quant_core.research.factors.conditions import evaluate_condition
from core.quant_core.research.factors.conditioned_variants import compose_and_signal
from services.api.app.market_data_loader import load_ohlcv_for_symbol
from services.api.app.models import (
    SignalBacktestRun,
    SignalEngineBatchJob,
    SignalEngineFamilyResult,
    WfoGlobalSignal,
    WfoSignalSummary,
)
from services.worker.db import SessionLocal
from services.worker.redis_utils import connect_redis_with_fallback

logger = logging.getLogger(__name__)

HORIZONS = ("weekly", "monthly", "quarterly")
TIMEFRAME = "1D"
CATEGORIES = ("tendance", "momentum", "oscillation", "volume")

DEFAULT_WINDOW_START = "2026-01-01"
DEFAULT_COST_BPS = DEFAULT_COST_BPS_PER_SIDE
DEFAULT_SLIPPAGE_BPS = 5.0
DEFAULT_SIDE_POLICY = "long_only"
DEFAULT_BACKTEST_CONFIG = {
    "method": "block_bootstrap",
    "n_paths": 2000,
    "block_mean": None,
    "seed": 42,
    "cost_bps": DEFAULT_COST_BPS,
    "slippage_bps": DEFAULT_SLIPPAGE_BPS,
    "side_policy": DEFAULT_SIDE_POLICY,
    "cooldown_bars": 0,
}
MIN_TRADE_BOOTSTRAP_TRADES = 30
BACKTEST_INPUT_LOGIC_VERSION = "family-aware-rebuild-v6-trade-cooldown"
SIGNAL_BACKTEST_NATURAL_KEY_COLUMNS = {
    "symbol",
    "horizon",
    "source",
    "scope",
    "scope_key",
    "variant",
    "window_start",
    "window_end",
    "cooldown_bars",
}


def run_signal_backtest_batch() -> dict:
    """Compute signal backtests for every active symbol x horizon."""
    db: Session = SessionLocal()
    try:
        from services.api.app.models import StockMaster

        symbols = [
            row.symbol
            for row in db.query(StockMaster.symbol)
            .filter(StockMaster.is_active.is_(True))
            .all()
        ]
        logger.info("Signal backtest batch: %d symbols", len(symbols))
        results = {"total": 0, "succeeded": 0, "failed": 0}

        for symbol in symbols:
            for horizon in HORIZONS:
                try:
                    compute_signal_backtest_for_symbol(symbol, horizon, triggered_by="scheduler")
                    results["succeeded"] += 1
                except Exception:
                    logger.exception("Signal backtest batch failed: %s/%s", symbol, horizon)
                    results["failed"] += 1
                results["total"] += 1

        return results
    finally:
        db.close()


def enqueue_signal_backtest_for_symbol(
    symbol: str,
    horizon: str,
    variant: str = "expanded",
    window_start: str = DEFAULT_WINDOW_START,
    window_end: str | None = None,
    mc_config: dict | None = None,
    triggered_by: str = "manual",
) -> str:
    """Enqueue a signal-backtest job to RQ and return the RQ job id."""
    from rq import Queue

    from services.worker.config import settings

    variant = signal_mode_storage_name(variant)
    redis = connect_redis_with_fallback(settings.REDIS_URL, decode_responses=False, logger=logger)
    queue_name = settings.SIGNAL_BACKTEST_QUEUE_NAME
    q = Queue(queue_name, connection=redis)
    rq_job_id = str(uuid.uuid4())
    job = q.enqueue(
        compute_signal_backtest_for_symbol,
        symbol,
        horizon,
        variant,
        window_start,
        window_end,
        mc_config,
        rq_job_id,
        triggered_by,
        job_id=rq_job_id,
        job_timeout=1800,
    )

    db: Session = SessionLocal()
    try:
        job_row = _create_batch_job(
            db,
            symbol=symbol,
            horizon=horizon,
            variant=variant,
            rq_job_id=rq_job_id,
            triggered_by=triggered_by,
            total_units=_count_scopes(),
        )
        db.commit()
    finally:
        db.close()
    return job.id


def compute_signal_backtest_for_symbol(
    symbol: str,
    horizon: str,
    variant: str = "expanded",
    window_start: str = DEFAULT_WINDOW_START,
    window_end: str | None = None,
    mc_config: dict | None = None,
    rq_job_id: str | None = None,
    triggered_by: str | None = None,
) -> dict:
    """RQ task: compute backtests + Monte Carlo for one symbol x horizon."""
    mode = resolve_signal_mode(variant)
    variant = mode.name
    job_config = _normalize_backtest_config(mc_config)
    t0 = time.perf_counter()
    db: Session = SessionLocal()
    completed = 0
    failed = 0
    job_row: SignalEngineBatchJob | None = None

    try:
        win_start = date.fromisoformat(window_start)
        win_end = date.fromisoformat(window_end) if window_end else date.today()
        job_row = _start_batch_job(
            db,
            symbol=symbol,
            horizon=horizon,
            variant=variant,
            rq_job_id=rq_job_id,
            triggered_by=triggered_by,
            total_units=_count_scopes(),
        )
        db.commit()

        try:
            ohlcv_raw = load_ohlcv_for_symbol(db, symbol, TIMEFRAME)
            ohlcv = drop_incomplete_ohlcv_rows(ohlcv_raw)
        except Exception as exc:
            logger.warning("Signal backtest: no OHLCV for %s: %s", symbol, exc)
            _finish_batch_job(
                job_row,
                status="failed",
                error_message=f"OHLCV load failed: {exc}",
                completed_units=completed,
                failed_units=failed,
            )
            db.commit()
            return {"symbol": symbol, "horizon": horizon, "status": "failed", "error": str(exc)}

        ohlcv_window = ohlcv.loc[str(win_start):str(win_end)]
        if len(ohlcv_window) < 10:
            message = f"Insufficient bars in window ({len(ohlcv_window)})"
            _finish_batch_job(
                job_row,
                status="failed",
                error_message=message,
                completed_units=completed,
                failed_units=failed,
            )
            db.commit()
            return {"symbol": symbol, "horizon": horizon, "status": "skipped", "reason": message}

        data_as_of = ohlcv_window.index[-1].date()
        dates = [d.strftime("%Y-%m-%d") for d in ohlcv_window.index]
        close = ohlcv_window["Close"].values.astype(np.float64)
        high = ohlcv_window["High"].values.astype(np.float64) if "High" in ohlcv_window.columns else None
        low = ohlcv_window["Low"].values.astype(np.float64) if "Low" in ohlcv_window.columns else None
        volume = ohlcv_window["Volume"].values.astype(np.float64) if "Volume" in ohlcv_window.columns else None

        engine_family_rows = _load_engine_family_rows(db, symbol, horizon, variant)
        wfo_category_rows = _load_wfo_category_rows(db, symbol, horizon, variant)
        factor_x_ta_precomputed = (
            _build_factor_x_ta_precomputed_signals(
                db,
                ohlcv_window,
                close,
                volume,
                high,
                low,
                _all_representatives(engine_family_rows, wfo_category_rows),
            )
            if mode.is_factor_x_ta
            else {}
        )
        wfo_global_row = (
            db.query(WfoGlobalSignal)
            .filter_by(symbol=symbol, horizon=horizon, variant=variant)
            .filter(WfoGlobalSignal.status == "succeeded")
            .first()
        )
        wfo_global_weights = _extract_wfo_weights(wfo_global_row) if wfo_global_row else {}

        engine_cat_series: dict[str, np.ndarray] = {}
        build_failures: list[tuple[str, str, str, list[dict], str, float]] = []
        replay_kwargs = (
            {"precomputed_signals": factor_x_ta_precomputed}
            if mode.is_factor_x_ta
            else {}
        )
        for cat in CATEGORIES:
            t_scope = time.perf_counter()
            try:
                engine_cat_series[cat] = build_category_signal_series_engine(
                    close,
                    volume,
                    high,
                    low,
                    engine_family_rows,
                    cat,
                    **replay_kwargs,
                )
            except Exception as exc:
                logger.warning(
                    "Engine category series failed: %s/%s/%s: %s",
                    symbol,
                    cat,
                    horizon,
                    exc,
                )
                build_failures.append(
                    (
                        "engine",
                        "per_category",
                        cat,
                        _flatten_reps(engine_family_rows, cat),
                        f"Signal series build failed: {exc}",
                        time.perf_counter() - t_scope,
                    )
                )

        wfo_cat_series: dict[str, np.ndarray] = {}
        for cat, reps in wfo_category_rows.items():
            t_scope = time.perf_counter()
            try:
                wfo_cat_series[cat] = build_category_signal_series_wfo(
                    close,
                    volume,
                    high,
                    low,
                    reps,
                    **replay_kwargs,
                )
            except Exception as exc:
                logger.warning(
                    "WFO category series failed: %s/%s/%s: %s",
                    symbol,
                    cat,
                    horizon,
                    exc,
                )
                build_failures.append(
                    (
                        "wfo",
                        "per_category",
                        cat,
                        reps,
                        f"Signal series build failed: {exc}",
                        time.perf_counter() - t_scope,
                    )
                )

        for source, scope, scope_key, reps, error_message, elapsed_seconds in build_failures:
            _upsert_backtest_run(
                db,
                symbol,
                horizon,
                source,
                scope,
                scope_key,
                variant,
                win_start,
                win_end,
                mc_config=job_config,
                status="failed",
                error_message=error_message,
                data_as_of=data_as_of,
                compute_seconds=elapsed_seconds,
            )
            failed += 1
            _update_batch_job_progress(job_row, completed_units=completed, failed_units=failed)
            db.commit()

        engine_cat_weights = _compute_engine_category_weights(engine_family_rows)
        scopes_to_run: list[tuple[str, str, str, np.ndarray, list[dict]]] = []

        for cat in CATEGORIES:
            if cat in engine_cat_series:
                scopes_to_run.append(
                    ("engine", "per_category", cat, engine_cat_series[cat], _flatten_reps(engine_family_rows, cat))
                )
            if cat in wfo_cat_series:
                scopes_to_run.append(
                    ("wfo", "per_category", cat, wfo_cat_series[cat], wfo_category_rows.get(cat, []))
                )

        cats_with_engine = [c for c in CATEGORIES if c in engine_cat_series]
        if len(cats_with_engine) >= 2:
            all_engine_reps = [r for cat in cats_with_engine for r in _flatten_reps(engine_family_rows, cat)]
            scopes_to_run.append(
                (
                    "engine",
                    "global",
                    "global",
                    build_global_signal_series(engine_cat_series, engine_cat_weights),
                    all_engine_reps,
                )
            )

        cats_with_wfo = [c for c in CATEGORIES if c in wfo_cat_series]
        if len(cats_with_wfo) >= 2 and wfo_global_weights:
            all_wfo_reps = [r for cat in cats_with_wfo for r in wfo_category_rows.get(cat, [])]
            scopes_to_run.append(
                (
                    "wfo",
                    "global",
                    "global",
                    build_global_signal_series(wfo_cat_series, wfo_global_weights),
                    all_wfo_reps,
                )
            )

        for subset in all_category_subsets(list(CATEGORIES)):
            scope_key = "+".join(subset)
            if all(cat in engine_cat_series for cat in subset):
                scopes_to_run.append(
                    (
                        "engine",
                        "combination",
                        scope_key,
                        build_combination_signal_series(engine_cat_series, subset, engine_cat_weights),
                        [r for cat in subset for r in _flatten_reps(engine_family_rows, cat)],
                    )
                )
            if all(cat in wfo_cat_series for cat in subset):
                scopes_to_run.append(
                    (
                        "wfo",
                        "combination",
                        scope_key,
                        build_combination_signal_series(wfo_cat_series, subset, wfo_global_weights),
                        [r for cat in subset for r in wfo_category_rows.get(cat, [])],
                    )
                )

        for source, scope, scope_key, signal_series, reps in scopes_to_run:
            t_scope = time.perf_counter()
            try:
                ihash = compute_input_hash(
                    reps,
                    data_as_of,
                    job_config["cost_bps"],
                    job_config["slippage_bps"],
                    job_config["side_policy"],
                    cooldown_bars=job_config["cooldown_bars"],
                    mc_method=job_config["method"],
                    n_paths=job_config["n_paths"],
                    block_mean=job_config["block_mean"],
                    seed=job_config["seed"],
                    logic_version=BACKTEST_INPUT_LOGIC_VERSION,
                )

                existing = (
                    db.query(SignalBacktestRun)
                    .filter_by(
                        symbol=symbol,
                        horizon=horizon,
                        source=source,
                        scope=scope,
                        scope_key=scope_key,
                        variant=variant,
                        window_start=win_start,
                        window_end=win_end,
                        cooldown_bars=job_config["cooldown_bars"],
                    )
                    .first()
                )
                if existing and existing.status == "succeeded" and existing.input_hash == ihash:
                    completed += 1
                    _update_batch_job_progress(job_row, completed_units=completed, failed_units=failed)
                    db.commit()
                    continue

                bt = run_signal_backtest(
                    signal_series,
                    close,
                    dates,
                    cost_bps=job_config["cost_bps"],
                    slippage_bps=job_config["slippage_bps"],
                    side_policy=job_config["side_policy"],
                    cooldown_bars=job_config["cooldown_bars"],
                )
                diag = dict(bt.get("diagnostics") or {})
                diag_reps = _diagnostic_representatives(reps)
                diag["representatives"] = diag_reps
                diag["representative_count"] = len(diag_reps)
                diag["source"] = source
                diag["scope"] = scope
                diag["scope_key"] = scope_key
                bt["diagnostics"] = diag

                trade_events = None
                actual_mc_method = job_config["method"]
                trades = bt["trades"]
                if job_config["method"] == "trade_bootstrap":
                    if len(trades) >= MIN_TRADE_BOOTSTRAP_TRADES:
                        trade_events = {
                            "pnls": [t["pnl_return"] for t in trades],
                            "start_indices": [t["open_idx"] for t in trades],
                        }
                    else:
                        actual_mc_method = "block_bootstrap"

                mc_result = monte_carlo_equity_paths(
                    np.asarray(bt["returns"], dtype=np.float64),
                    method=actual_mc_method,
                    n_paths=job_config["n_paths"],
                    block_mean=job_config["block_mean"],
                    trade_events=trade_events,
                    seed=job_config["seed"],
                )

                shuffle_result = shuffled_trade_analysis(
                    np.asarray([t["pnl_return"] for t in trades], dtype=np.float64),
                    n_paths=min(job_config["n_paths"], 2000),
                    seed=job_config["seed"],
                )

                warning_code: str | None = None
                if diag.get("flat_executed"):
                    warning_code = "flat_signal"
                elif len(trades) < 5:
                    warning_code = "few_trades"

                persisted_config = dict(job_config)
                persisted_config["method"] = actual_mc_method
                _upsert_backtest_run(
                    db,
                    symbol,
                    horizon,
                    source,
                    scope,
                    scope_key,
                    variant,
                    win_start,
                    win_end,
                    bt=bt,
                    mc_result=mc_result,
                    shuffle_result=shuffle_result,
                    warning_code=warning_code,
                    mc_config=persisted_config,
                    input_hash=ihash,
                    data_as_of=data_as_of,
                    compute_seconds=time.perf_counter() - t_scope,
                )
                next_completed = completed + 1
                _update_batch_job_progress(job_row, completed_units=next_completed, failed_units=failed)
                db.commit()
                completed = next_completed
            except Exception as exc:
                logger.exception(
                    "Signal backtest scope failed: %s/%s/%s/%s: %s",
                    symbol,
                    horizon,
                    scope_key,
                    source,
                    exc,
                )
                db.rollback()
                _upsert_backtest_run(
                    db,
                    symbol,
                    horizon,
                    source,
                    scope,
                    scope_key,
                    variant,
                    win_start,
                    win_end,
                    mc_config=job_config,
                    status="failed",
                    error_message=str(exc),
                    data_as_of=data_as_of,
                    compute_seconds=time.perf_counter() - t_scope,
                )
                next_failed = failed + 1
                _update_batch_job_progress(job_row, completed_units=completed, failed_units=next_failed)
                db.commit()
                failed = next_failed

        final_status = "succeeded" if failed == 0 else ("partial" if completed > 0 else "failed")
        _finish_batch_job(
            job_row,
            status=final_status,
            completed_units=completed,
            failed_units=failed,
        )
        db.commit()
        return {
            "symbol": symbol,
            "horizon": horizon,
            "status": final_status,
            "completed": completed,
            "failed": failed,
            "elapsed": round(time.perf_counter() - t0, 2),
        }
    except Exception as exc:
        logger.exception("Signal backtest error: %s/%s: %s", symbol, horizon, exc)
        db.rollback()
        if job_row is not None:
            _finish_batch_job(
                job_row,
                status="failed",
                error_message=str(exc),
                completed_units=completed,
                failed_units=failed,
            )
            db.commit()
        return {"symbol": symbol, "horizon": horizon, "status": "failed", "error": str(exc)}
    finally:
        db.close()


def _load_engine_family_rows(db: Session, symbol: str, horizon: str, variant: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for row in (
        db.query(SignalEngineFamilyResult)
        .filter_by(symbol=symbol, horizon=horizon, variant=variant)
        .filter(SignalEngineFamilyResult.status == "succeeded")
        .all()
    ):
        representatives = _normalize_engine_representatives(row.representatives_json or [], row.family)
        rows[row.family] = {
            "status": "succeeded",
            "category": row.category,
            "family_score_pct": row.family_score_pct,
            "viable_count": row.viable_count or 0,
            "tested_count": row.tested_count or 1,
            "representative_count": row.representative_count or 0,
            "is_provisional": bool(row.is_provisional),
            "representatives_json": representatives,
        }
    return rows


def _normalize_engine_representatives(representatives: list[dict], family: str) -> list[dict]:
    normalized: list[dict] = []
    for rep in representatives:
        if not isinstance(rep, dict):
            continue
        entry = dict(rep)
        if not entry.get("family"):
            entry["family"] = family
        normalized.append(entry)
    return normalized


def _load_wfo_category_rows(db: Session, symbol: str, horizon: str, variant: str) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {}
    for row in (
        db.query(WfoSignalSummary)
        .filter_by(symbol=symbol, horizon=horizon, variant=variant)
        .filter(WfoSignalSummary.status == "succeeded")
        .all()
    ):
        rows[row.category] = row.representatives_json or []
    return rows


def _all_representatives(
    engine_family_rows: dict[str, dict],
    wfo_category_rows: dict[str, list[dict]],
) -> list[dict]:
    reps: list[dict] = []
    for row in engine_family_rows.values():
        reps.extend([rep for rep in row.get("representatives_json") or [] if isinstance(rep, dict)])
    for category_reps in wfo_category_rows.values():
        reps.extend([rep for rep in category_reps or [] if isinstance(rep, dict)])
    return reps


def _factor_condition_from_rep(rep: dict) -> FactorConditionMeta | None:
    payload = rep.get("factor_condition")
    if not isinstance(payload, dict):
        return None
    try:
        return FactorConditionMeta(
            condition_id=str(payload["condition_id"]),
            factor_ticker=str(payload["factor_ticker"]),
            form=str(payload["form"]),
            lookback=int(payload["lookback"]),
            threshold=float(payload["threshold"]),
            direction=str(payload["direction"]),
        )
    except Exception:
        return None


def _factor_conditions_from_rep(rep: dict) -> list[FactorConditionMeta]:
    conditions: list[FactorConditionMeta] = []
    top_level = _factor_condition_from_rep(rep)
    if top_level is not None:
        conditions.append(top_level)
    params = rep.get("params")
    if isinstance(params, dict):
        for payload in params.get("components", []):
            if not isinstance(payload, dict):
                continue
            condition = _factor_condition_from_rep(payload)
            if condition is not None:
                conditions.append(condition)
    return conditions


def _build_factor_x_ta_precomputed_signals(
    db: Session,
    ohlcv_window,
    close: np.ndarray,
    volume: np.ndarray | None,
    high: np.ndarray | None,
    low: np.ndarray | None,
    representatives: list[dict],
) -> dict[str, np.ndarray]:
    """Rebuild AND-composed Factor x TA signals for persisted representatives."""
    conditions_by_id: dict[str, FactorConditionMeta] = {}
    for rep in representatives:
        for condition in _factor_conditions_from_rep(rep):
            conditions_by_id[condition.condition_id] = condition
    if not conditions_by_id:
        return {}

    from services.worker.tasks.factor_x_ta_batch import _align_factor_arrays_for_conditions

    aligned_factor_arrays = _align_factor_arrays_for_conditions(
        db,
        ohlcv_window,
        list(conditions_by_id.values()),
    )
    if not aligned_factor_arrays:
        return {}

    precomputed: dict[str, np.ndarray] = {}
    for rep in representatives:
        condition = _factor_condition_from_rep(rep)
        params = dict(rep.get("params") or {})
        variant_id = str(rep.get("variant_id") or "").strip()
        family = str(rep.get("family") or "").strip()
        archetype = str(rep.get("archetype") or "").strip()
        if not variant_id or not family or not archetype:
            continue

        variant = VariantDef(
            variant_id=variant_id,
            family=family,
            archetype=archetype,
            params=params,
            description=str(rep.get("description") or ""),
            factor_condition=condition,
        )

        if condition is None and is_combo_variant(variant):
            def _compute_component(component: VariantDef) -> np.ndarray:
                component_condition = component.factor_condition
                if component_condition is None:
                    raise ValueError("factor combo component is missing factor_condition")
                factor_close = aligned_factor_arrays.get(component_condition.factor_ticker)
                if factor_close is None or len(factor_close) != len(close):
                    raise ValueError("aligned factor series is missing for combo component")
                ta_sig = _compute_ta_signal_for_conditioned(
                    component,
                    close,
                    volume=volume,
                    high=high,
                    low=low,
                )
                if ta_sig is None:
                    raise ValueError("TA signal computation failed for combo component")
                condition_mask = evaluate_condition(component_condition, factor_close)
                return compose_and_signal(ta_sig, condition_mask)

            try:
                precomputed[variant_id] = compute_strict_and_combo_signal(
                    close,
                    variant,
                    compute_component_signal=_compute_component,
                )
            except Exception:
                continue
            continue

        if condition is None:
            continue
        factor_close = aligned_factor_arrays.get(condition.factor_ticker)
        if factor_close is None or len(factor_close) != len(close):
            continue
        ta_sig = _compute_ta_signal_for_conditioned(
            variant,
            close,
            volume=volume,
            high=high,
            low=low,
        )
        if ta_sig is None:
            continue
        condition_mask = evaluate_condition(condition, factor_close)
        precomputed[variant_id] = compose_and_signal(ta_sig, condition_mask)
    return precomputed


def _normalize_backtest_config(mc_config: dict | None) -> dict[str, Any]:
    merged = {**DEFAULT_BACKTEST_CONFIG, **(mc_config or {})}
    return {
        "method": str(merged.get("method", DEFAULT_BACKTEST_CONFIG["method"])),
        "n_paths": int(merged.get("n_paths", DEFAULT_BACKTEST_CONFIG["n_paths"])),
        "block_mean": (
            None if merged.get("block_mean") in (None, "", 0) else int(merged.get("block_mean"))
        ),
        "seed": int(merged.get("seed", DEFAULT_BACKTEST_CONFIG["seed"])),
        "cost_bps": float(merged.get("cost_bps", DEFAULT_BACKTEST_CONFIG["cost_bps"])),
        "slippage_bps": float(merged.get("slippage_bps", DEFAULT_BACKTEST_CONFIG["slippage_bps"])),
        "side_policy": str(merged.get("side_policy", DEFAULT_BACKTEST_CONFIG["side_policy"])),
        "cooldown_bars": min(252, max(0, int(merged.get("cooldown_bars", DEFAULT_BACKTEST_CONFIG["cooldown_bars"]) or 0))),
    }


def _extract_wfo_weights(row: WfoGlobalSignal) -> dict[str, float]:
    weights: dict[str, float] = {}
    for cat in CATEGORIES:
        value = getattr(row, f"weight_{cat}", None)
        if value is not None:
            weights[cat] = float(value)
    total = sum(weights.values())
    if total > 0:
        return {key: value / total for key, value in weights.items()}
    return {cat: 0.25 for cat in CATEGORIES}


def _compute_engine_category_weights(family_rows: dict[str, dict]) -> dict[str, float]:
    """Derive category weights from family viable_count/tested_count for engine path."""
    cat_scores: dict[str, float] = {}
    for cat, families in CATEGORY_FAMILIES.items():
        scores = []
        for fam in families:
            family_row = family_rows.get(fam) or family_rows.get(f"{fam}@fx")
            if family_row and family_row.get("family_score_pct") is not None:
                scores.append(abs(float(family_row["family_score_pct"])))
        for family_key, family_row in family_rows.items():
            if family_row.get("category") != cat or family_key in families or family_key.endswith("@fx"):
                continue
            if family_row.get("family_score_pct") is not None:
                scores.append(abs(float(family_row["family_score_pct"])))
        if scores:
            cat_scores[cat] = sum(scores) / len(scores)

    total = sum(cat_scores.values())
    if total <= 0:
        return {cat: 0.25 for cat in CATEGORIES}
    return {cat: value / total for cat, value in cat_scores.items()}


def _flatten_reps(family_rows: dict[str, dict], category: str) -> list[dict]:
    reps: list[dict] = []
    for fam in CATEGORY_FAMILIES.get(category, []):
        family_row = family_rows.get(fam) or family_rows.get(f"{fam}@fx")
        if family_row:
            reps.extend(family_row.get("representatives_json") or [])
    for family_key, family_row in family_rows.items():
        if family_row.get("category") == category and not any(
            family_key == fam or family_key == f"{fam}@fx"
            for fam in CATEGORY_FAMILIES.get(category, [])
        ):
            reps.extend(family_row.get("representatives_json") or [])
    return reps


def _as_finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return number


def _numeric_params(params: Any) -> dict[str, float]:
    if not isinstance(params, dict):
        return {}
    out: dict[str, float] = {}
    for key, raw in params.items():
        val = _as_finite_float(raw)
        if val is None:
            continue
        out[str(key)] = val
    return out


def _diagnostic_factor_condition(condition: Any) -> dict[str, Any] | None:
    if not isinstance(condition, dict):
        return None
    out: dict[str, Any] = {}
    for key in ("condition_id", "factor_ticker", "form", "direction"):
        value = condition.get(key)
        if value is not None:
            out[key] = str(value)
    for key in ("lookback", "threshold"):
        value = _as_finite_float(condition.get(key))
        if value is not None:
            out[key] = value
    return out or None


def _diagnostic_component(component: Any) -> dict[str, Any] | None:
    if not isinstance(component, dict):
        return None
    family = str(component.get("family") or "").strip()
    variant_id = str(component.get("variant_id") or "").strip()
    if not family or not variant_id:
        return None
    out: dict[str, Any] = {
        "family": family,
        "archetype": str(component.get("archetype") or ""),
        "variant_id": variant_id,
        "description": str(component.get("description") or component.get("label") or variant_id).strip() or variant_id,
        "params": _numeric_params(component.get("params")),
    }
    condition = _diagnostic_factor_condition(component.get("factor_condition"))
    if condition is not None:
        out["factor_condition"] = condition
    return out


def _diagnostic_params(params: Any) -> dict[str, Any]:
    out: dict[str, Any] = _numeric_params(params)
    if not isinstance(params, dict):
        return out

    for key in ("operator", "primary_category", "conditioning"):
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()

    component_families = params.get("component_families")
    if isinstance(component_families, list):
        families = [str(item).strip() for item in component_families if str(item).strip()]
        if families:
            out["component_families"] = families

    components = [
        component
        for component in (_diagnostic_component(raw) for raw in params.get("components", []))
        if component is not None
    ]
    if components:
        out["components"] = components
    return out


def _diagnostic_representatives(reps: list[dict]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for rep in reps:
        if not isinstance(rep, dict):
            continue

        variant_id = str(rep.get("variant_id") or "").strip()
        family = str(rep.get("family") or "").strip()
        if not variant_id or not family:
            continue

        key = (family, variant_id)
        if key in seen:
            continue
        seen.add(key)

        params = _diagnostic_params(rep.get("params"))
        label = str(rep.get("description") or rep.get("label") or variant_id).strip() or variant_id
        out.append(
            {
                "family": family,
                "archetype": str(rep.get("archetype") or ""),
                "variant_id": variant_id,
                "description": label,
                "params": params,
                "normalized_weight": _as_finite_float(rep.get("normalized_weight")),
                "reliability_weight": _as_finite_float(rep.get("reliability_weight")),
                "signal_label": str(rep.get("signal_label") or ""),
                "indicator_value": _as_finite_float(rep.get("indicator_value")),
                "current_close": _as_finite_float(rep.get("current_close")),
            }
        )

    return out


def _count_scopes() -> int:
    n_combos = len(list(combinations(CATEGORIES, 2))) + len(list(combinations(CATEGORIES, 3)))
    return (len(CATEGORIES) + 1 + n_combos) * 2


def _create_batch_job(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    variant: str,
    rq_job_id: str | None,
    triggered_by: str | None,
    total_units: int,
) -> SignalEngineBatchJob:
    job_row = SignalEngineBatchJob(
        id=uuid.uuid4(),
        symbol=symbol,
        horizon=horizon,
        variant=variant,
        job_type="signal_backtest",
        status="pending",
        rq_job_id=rq_job_id,
        triggered_by=triggered_by,
        total_units=total_units,
        completed_units=0,
        failed_units=0,
    )
    db.add(job_row)
    return job_row


def _start_batch_job(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    variant: str,
    rq_job_id: str | None,
    triggered_by: str | None,
    total_units: int,
) -> SignalEngineBatchJob:
    job_row = None
    if rq_job_id:
        job_row = (
            db.query(SignalEngineBatchJob)
            .filter_by(rq_job_id=rq_job_id, job_type="signal_backtest")
            .first()
        )
    if job_row is None:
        job_row = _create_batch_job(
            db,
            symbol=symbol,
            horizon=horizon,
            variant=variant,
            rq_job_id=rq_job_id,
            triggered_by=triggered_by,
            total_units=total_units,
        )
    job_row.status = "running"
    job_row.started_at = datetime.now(timezone.utc)
    job_row.finished_at = None
    job_row.error_message = None
    job_row.total_units = total_units
    job_row.completed_units = 0
    job_row.failed_units = 0
    if triggered_by and not job_row.triggered_by:
        job_row.triggered_by = triggered_by
    return job_row


def _update_batch_job_progress(
    job_row: SignalEngineBatchJob | None,
    *,
    completed_units: int,
    failed_units: int,
) -> None:
    if job_row is None:
        return
    job_row.completed_units = completed_units
    job_row.failed_units = failed_units


def _finish_batch_job(
    job_row: SignalEngineBatchJob | None,
    *,
    status: str,
    error_message: str | None = None,
    completed_units: int | None = None,
    failed_units: int | None = None,
) -> None:
    if job_row is None:
        return
    job_row.status = status
    job_row.finished_at = datetime.now(timezone.utc)
    if completed_units is not None:
        job_row.completed_units = completed_units
    if failed_units is not None:
        job_row.failed_units = failed_units
    if error_message:
        job_row.error_message = error_message


def _upsert_backtest_run(
    db: Session,
    symbol: str,
    horizon: str,
    source: str,
    scope: str,
    scope_key: str,
    variant: str,
    window_start: date,
    window_end: date,
    *,
    bt: dict | None = None,
    mc_result: dict | None = None,
    shuffle_result: dict | None = None,
    warning_code: str | None = None,
    mc_config: dict | None = None,
    status: str = "succeeded",
    input_hash: str | None = None,
    data_as_of: Any = None,
    compute_seconds: float | None = None,
    error_message: str | None = None,
) -> SignalBacktestRun | None:
    values = _backtest_run_values(
        symbol=symbol,
        horizon=horizon,
        source=source,
        scope=scope,
        scope_key=scope_key,
        variant=variant,
        window_start=window_start,
        window_end=window_end,
        bt=bt,
        mc_result=mc_result,
        shuffle_result=shuffle_result,
        warning_code=warning_code,
        mc_config=mc_config,
        status=status,
        input_hash=input_hash,
        data_as_of=data_as_of,
        compute_seconds=compute_seconds,
        error_message=error_message,
    )

    if hasattr(db, "execute"):
        stmt = pg_insert(SignalBacktestRun).values(**values)
        update_cols = {
            key: getattr(stmt.excluded, key)
            for key in values
            if key not in SIGNAL_BACKTEST_NATURAL_KEY_COLUMNS
        }
        db.execute(
            stmt.on_conflict_do_update(
                constraint="uq_sbr_natural_key",
                set_=update_cols,
            )
        )
        return None

    return _orm_upsert_backtest_run(db, values)


def _backtest_run_values(
    *,
    symbol: str,
    horizon: str,
    source: str,
    scope: str,
    scope_key: str,
    variant: str,
    window_start: date,
    window_end: date,
    bt: dict | None = None,
    mc_result: dict | None = None,
    shuffle_result: dict | None = None,
    warning_code: str | None = None,
    mc_config: dict | None = None,
    status: str = "succeeded",
    input_hash: str | None = None,
    data_as_of: Any = None,
    compute_seconds: float | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    values: dict[str, Any] = {
        "symbol": symbol,
        "horizon": horizon,
        "source": source,
        "scope": scope,
        "scope_key": scope_key,
        "variant": variant,
        "window_start": window_start,
        "window_end": window_end,
        "cooldown_bars": int((mc_config or {}).get("cooldown_bars", DEFAULT_BACKTEST_CONFIG["cooldown_bars"]) or 0),
        "status": status,
        "error_message": error_message,
        "input_hash": input_hash,
        "data_as_of": data_as_of,
        "computed_at": now,
        "compute_seconds": compute_seconds,
        "warning_code": warning_code,
        "updated_at": now,
    }

    if mc_config:
        values.update(
            {
                "cost_bps": float(mc_config.get("cost_bps", DEFAULT_COST_BPS)),
                "slippage_bps": float(mc_config.get("slippage_bps", DEFAULT_SLIPPAGE_BPS)),
                "side_policy": str(mc_config.get("side_policy", DEFAULT_SIDE_POLICY)),
                "cooldown_bars": int(mc_config.get("cooldown_bars", DEFAULT_BACKTEST_CONFIG["cooldown_bars"]) or 0),
                "n_paths": int(mc_config.get("n_paths", DEFAULT_BACKTEST_CONFIG["n_paths"])),
                "mc_method": str(mc_config.get("method", DEFAULT_BACKTEST_CONFIG["method"])),
                "block_mean": mc_config.get("block_mean"),
            }
        )

    if bt and status == "succeeded":
        metrics = bt.get("metrics", {})
        trades = bt.get("trades", [])
        values.update(
            {
                "n_bars": len(bt.get("equity", [])) - 1,
                "n_trades": len(trades),
                "equity_json": bt.get("equity"),
                "dates_json": bt.get("dates"),
                "total_return": metrics.get("total_return"),
                "cagr": metrics.get("cagr"),
                "sharpe": metrics.get("sharpe"),
                "max_drawdown": metrics.get("max_drawdown"),
                "win_rate": metrics.get("win_rate"),
                "trades_json": trades,
                "close_series_json": bt.get("close_series"),
                "position_series_json": bt.get("position_series"),
                "signal_diagnostics_json": bt.get("diagnostics"),
            }
        )

    if mc_result and status == "succeeded":
        values.update(
            {
                "mc_envelope_json": mc_result.get("envelope"),
                "mc_stats_json": mc_result.get("stats"),
            }
        )

    if shuffle_result and status == "succeeded":
        values["shuffle_stats_json"] = shuffle_result

    return values


def _orm_upsert_backtest_run(db: Session, values: dict[str, Any]) -> SignalBacktestRun:
    row = (
        db.query(SignalBacktestRun)
        .filter_by(
            symbol=values["symbol"],
            horizon=values["horizon"],
            source=values["source"],
            scope=values["scope"],
            scope_key=values["scope_key"],
            variant=values["variant"],
            window_start=values["window_start"],
            window_end=values["window_end"],
            cooldown_bars=values["cooldown_bars"],
        )
        .first()
    )
    if row is None:
        row = SignalBacktestRun(
            symbol=values["symbol"],
            horizon=values["horizon"],
            source=values["source"],
            scope=values["scope"],
            scope_key=values["scope_key"],
            variant=values["variant"],
            window_start=values["window_start"],
            window_end=values["window_end"],
        )
        db.add(row)

    for key, value in values.items():
        setattr(row, key, value)

    return row
