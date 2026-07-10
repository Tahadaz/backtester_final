"""Worker task: WFO Walk-Forward Analysis for Factor×TA cross-product signals.

Entry point: compute_wfo_factor_x_ta_for_symbol(symbol, horizon)

Mirrors wfo_signal_batch.py but:
  - Generates factor-conditioned (AND-composed) candidates instead of native TA candidates
  - Uses precomputed AND signals for WFO IS/OOS evaluation
  - Persists to wfo_signal_summary with variant='factor_x_ta'

Phase 3 of the Factor×TA expansion plan.
"""
from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from core.quant_core.horizons import DEFAULT_COST_BPS_PER_SIDE
from core.quant_core.data import drop_incomplete_ohlcv_rows
from core.quant_core.signal_engine.candidates import (
    generate_candidates,
    generate_factor_conditioned_candidates,
)
from core.quant_core.signal_engine.domain import (
    CATEGORY_FAMILIES,
    FAMILY_SIGNAL_TYPE,
    HORIZON_PARAMS,
    FactorConditionMeta,
    LEGACY_CATEGORY_FAMILIES,
    VariantDef,
    signal_type_label,
    variant_signal_label,
)
from core.quant_core.signal_engine.modes import resolve_signal_mode, signal_mode_storage_name
from core.quant_core.signal_engine.factor_x_ta import (
    _compute_ta_signal_for_conditioned,
    build_factor_x_ta_combo_pool_for_category,
)
from core.quant_core.research.factors.conditions import evaluate_condition
from core.quant_core.research.factors.conditioned_variants import compose_and_signal
from core.quant_core.signal_engine.redundancy import _pearson_corr
from core.quant_core.signal_engine.wfo_signal import (
    WfoCategoryResult,
    _apply_horizon_cap,
    _config_to_dict,
    _fail_result,
    _evaluate_variant_pnl,
    _evaluate_variant_returns_and_pnl,
    _extract_trades,
    _strict_window_candidates,
    _variant_min_history,
    compute_composite_score,
    compute_robustness_grade,
    DEFAULT_MIN_WALK_FORWARDS,
    DEFAULT_TOP_K_FOLDS,
)
from core.quant_core.wfo.engine import run_wfo_engine, WindowScoreResult
from core.quant_core.wfo.prom import compute_prom
from core.quant_core.significance import sharpe_ratio
from core.quant_core.signal_engine.wfo_global import compute_global_wfo_signal
from services.api.app.market_data_loader import load_ohlcv_for_symbol
from services.api.app.models import WfoSignalSummary
from services.worker.db import SessionLocal
from services.worker.redis_utils import connect_redis_with_fallback
from services.worker.tasks.wfo_signal_batch import _build_folds_json, _get_sr_levels, _upsert_global

# Re-use shared helpers from the engine ×fx batch
from services.worker.tasks.factor_x_ta_batch import (
    _build_runtime_inputs,
    _build_conditions,
    _load_channel_tags,
    _load_pre_registration,
    DEFAULT_COST_BPS,
    DEFAULT_TIMEFRAME,
    DEFAULT_COOLDOWN_BARS,
)

logger = logging.getLogger(__name__)
VARIANT = "factor_x_ta"


def _category_families_for_variant(variant: str) -> dict[str, list[str]]:
    mode = resolve_signal_mode(variant)
    return LEGACY_CATEGORY_FAMILIES if mode.universe == "legacy" else CATEGORY_FAMILIES
CATEGORIES = ("tendance", "momentum", "oscillation", "volume")


# ---------------------------------------------------------------------------
# Prom computation from precomputed signal
# ---------------------------------------------------------------------------

def _compute_prom_fx(
    close_is: np.ndarray,
    close_oos: np.ndarray,
    sig_full: np.ndarray,
    start_is: int,
    start_oos: int,
    cost_bps: float = DEFAULT_COST_BPS_PER_SIDE,
) -> tuple[float, float, float, float]:
    """Compute (prom, is_return, oos_return, oos_sharpe) from a precomputed AND signal."""
    sig_is = sig_full[start_is:start_is + len(close_is)]
    sig_oos = sig_full[start_oos:start_oos + len(close_oos)]

    is_return = _evaluate_variant_pnl(sig_is, close_is, cost_bps)
    oos_return, oos_daily = _evaluate_variant_returns_and_pnl(sig_oos, close_oos, cost_bps)

    oos_sharpe_val = float(sharpe_ratio(oos_daily))
    if math.isnan(oos_sharpe_val):
        oos_sharpe_val = 0.0

    trades = _extract_trades(sig_is, close_is)
    prom = compute_prom(trades, 1.0) if len(trades) >= 2 else is_return

    return prom, is_return, oos_return, oos_sharpe_val


# ---------------------------------------------------------------------------
# WFO ×fx per-category runner
# ---------------------------------------------------------------------------

def run_wfo_fx_for_category(
    category: str,
    horizon: str,
    close: np.ndarray,
    conditioned_pool: list[VariantDef],
    precomputed: dict[str, np.ndarray],
    *,
    volume: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    cost_bps: float = DEFAULT_COST_BPS_PER_SIDE,
    max_reps: int = 2,
    max_corr: float = 0.85,
    top_k_folds: int = DEFAULT_TOP_K_FOLDS,
    min_walk_forwards: int = DEFAULT_MIN_WALK_FORWARDS,
) -> WfoCategoryResult:
    """Run WFO for factor-conditioned variants of one category.

    Uses precomputed AND signals instead of compute_signal_array so that
    the factor gate is respected during IS/OOS evaluation.
    """
    t0 = time.monotonic()

    pool = [v for v in conditioned_pool if v.variant_id in precomputed]
    if not pool:
        return _fail_result(
            category=category, horizon=horizon, started_at=t0,
            reason="No conditioned candidates with precomputed signals",
        )

    # Cap data to horizon window (mirrors run_wfo_category_signal behaviour)
    close_c, vol_c, high_c, low_c, cap_len, _ = _apply_horizon_cap(
        horizon=horizon, close=close, volume=volume, high=high, low=low,
    )

    # Align precomputed signals to the capped close length
    precomputed_c: dict[str, np.ndarray] = {}
    for vid, sig in precomputed.items():
        if len(sig) > cap_len:
            precomputed_c[vid] = sig[-cap_len:]
        elif len(sig) < cap_len:
            precomputed_c[vid] = np.concatenate(
                [np.zeros(cap_len - len(sig), dtype=sig.dtype), sig]
            )
        else:
            precomputed_c[vid] = sig

    max_lookback = max(_variant_min_history(v) for v in pool)

    configs, diagnostics = _strict_window_candidates(
        horizon=horizon,
        data_length=cap_len,
        max_lookback=max_lookback,
        requested_min_walk_forwards=min_walk_forwards,
        top_k_folds=top_k_folds,
    )
    if not configs:
        return _fail_result(
            category=category, horizon=horizon, started_at=t0,
            reason="No valid WFO window config for data length",
            diagnostics=diagnostics,
        )

    config = configs[0]
    min_bars = config.train_bars + config.oos_bars + max_lookback
    if cap_len < min_bars:
        return _fail_result(
            category=category, horizon=horizon, started_at=t0,
            reason=f"Need {min_bars} bars, have {cap_len}",
            status="insufficient_data",
            config_used=_config_to_dict(config),
            diagnostics=diagnostics,
        )

    def evaluate_window(window) -> WindowScoreResult:
        raw_scores: dict[int, float] = {}
        is_returns: dict[int, float] = {}
        oos_returns: dict[int, float] = {}
        oos_sharpes: dict[int, float] = {}

        close_is = close_c[window.train_start:window.train_end]
        close_oos = close_c[window.oos_start:window.oos_end]

        for i, variant in enumerate(pool):
            sig_full = precomputed_c.get(variant.variant_id)
            if sig_full is None:
                raw_scores[i] = 0.0
                is_returns[i] = 0.0
                oos_returns[i] = 0.0
                oos_sharpes[i] = 0.0
                continue
            try:
                prom, is_ret, oos_ret, oos_sharpe = _compute_prom_fx(
                    close_is, close_oos,
                    sig_full, window.train_start, window.oos_start,
                    cost_bps=cost_bps,
                )
            except Exception:
                prom, is_ret, oos_ret, oos_sharpe = 0.0, 0.0, 0.0, 0.0
            raw_scores[i] = prom
            is_returns[i] = is_ret
            oos_returns[i] = oos_ret
            oos_sharpes[i] = oos_sharpe

        return WindowScoreResult(
            raw_scores=raw_scores,
            is_returns=is_returns,
            oos_returns=oos_returns,
            oos_sharpes=oos_sharpes,
        )

    engine_result = run_wfo_engine(
        data_length=cap_len,
        config=config,
        evaluate_window=evaluate_window,
        max_lookback=max_lookback,
    )

    if not engine_result.windows:
        return _fail_result(
            category=category, horizon=horizon, started_at=t0,
            reason="No WFO windows produced",
            engine_result=engine_result,
            diagnostics=diagnostics,
        )

    # Select representatives by WFO smoothed score, decorrelated
    last_window = engine_result.windows[-1]
    smoothed = last_window.smoothed_scores
    ranked_indices = sorted(smoothed.keys(), key=lambda idx: smoothed[idx], reverse=True)

    recent_n = min(252, cap_len)
    sig_arrays: list[np.ndarray] = []
    selected: list[tuple[int, VariantDef, float]] = []

    for idx in ranked_indices:
        if len(selected) >= max_reps:
            break
        variant = pool[idx]
        sig_full = precomputed_c.get(variant.variant_id)
        if sig_full is None:
            continue
        sig = sig_full[-recent_n:]
        is_redundant = any(
            abs(_pearson_corr(sig, existing)) > max_corr for existing in sig_arrays
        )
        if not is_redundant:
            selected.append((idx, variant, smoothed[idx]))
            sig_arrays.append(sig)

    if selected:
        total_prom = sum(max(0.01, item[2]) for item in selected)
        weights = [max(0.01, item[2]) / total_prom for item in selected]
    else:
        weights = []

    reps_list: list[dict[str, Any]] = []
    score_pct_accum = 0.0
    total_weight_accum = 0.0

    for (_, variant, prom_val), weight in zip(selected, weights):
        sig_full = precomputed_c.get(variant.variant_id)
        if sig_full is None:
            continue
        current_sig = float(sig_full[-1]) if len(sig_full) > 0 else 0.0
        label = variant_signal_label(variant.family, current_sig)
        score_pct_accum += weight * current_sig
        total_weight_accum += weight

        rep: dict[str, Any] = {
            "family": variant.family,
            "archetype": variant.archetype,
            "variant_id": variant.variant_id,
            "params": dict(variant.params),
            "description": variant.description,
            "signal": current_sig,
            "signal_label": label,
            "normalized_weight": round(weight, 4),
            "contribution": round(weight * current_sig, 4),
            "wfo_prom": round(prom_val, 6),
        }
        cond = variant.factor_condition
        if cond is not None:
            rep["factor_condition"] = {
                "condition_id": cond.condition_id,
                "factor_ticker": cond.factor_ticker,
                "form": cond.form,
                "lookback": cond.lookback,
                "threshold": cond.threshold,
                "direction": cond.direction,
            }
        reps_list.append(rep)

    score_pct = (
        round((score_pct_accum / total_weight_accum) * 100.0, 2)
        if total_weight_accum > 0
        else 0.0
    )
    first_family = (CATEGORY_FAMILIES.get(category) or [category])[0]
    signal_type = FAMILY_SIGNAL_TYPE.get(first_family, "trend")
    signal_lbl = signal_type_label(signal_type, score_pct)

    oos_rets = [w.oos_return for w in engine_result.windows]
    profitable_folds = sum(1 for v in oos_rets if v > 0)
    mean_sharpe = float(np.mean(oos_rets)) if oos_rets else 0.0
    total_pnl = float(sum(oos_rets))
    worst_dd = float(min(oos_rets)) if oos_rets else 0.0

    composite = compute_composite_score(
        engine_result.wfe, engine_result.robustness_ratio, mean_sharpe, worst_dd,
    )
    grade = compute_robustness_grade(engine_result.wfe, engine_result.robustness_ratio)

    config_used = {
        **_config_to_dict(config),
        "min_bars_needed": min_bars,
        "max_lookback": max_lookback,
        "cap_len": cap_len,
    }

    return WfoCategoryResult(
        category=category,
        symbol="",
        horizon=horizon,
        status="succeeded",
        score_pct=score_pct,
        signal_label=signal_lbl,
        representatives=reps_list,
        wfe_pct=round(engine_result.wfe * 100, 2),
        robustness_ratio=round(engine_result.robustness_ratio, 4),
        total_folds=len(engine_result.windows),
        profitable_folds=profitable_folds,
        mean_oos_sharpe=round(mean_sharpe, 4),
        total_oos_pnl=round(total_pnl, 4),
        worst_fold_drawdown=round(worst_dd, 4),
        composite_score=round(composite, 2),
        robustness_grade=grade,
        engine_result=engine_result,
        config_used=config_used,
        window_diagnostics=diagnostics or {},
        data_as_of="",
        compute_seconds=round(time.monotonic() - t0, 2),
    )


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _upsert_wfo_fx_summary(
    db: Session,
    symbol: str,
    category: str,
    horizon: str,
    *,
    variant: str,
    status: str,
    result: WfoCategoryResult | None = None,
    data_as_of=None,
    error_message: str | None = None,
    folds_json: list[dict] | None = None,
) -> None:
    row = (
        db.query(WfoSignalSummary)
        .filter_by(symbol=symbol, category=category, horizon=horizon, variant=variant)
        .first()
    )
    if row is None:
        row = WfoSignalSummary(
            symbol=symbol, category=category, horizon=horizon, variant=variant,
        )
        db.add(row)

    row.status = status
    row.error_message = error_message
    row.computed_at = datetime.now(timezone.utc)
    row.data_as_of = data_as_of

    if result is not None and status == "succeeded":
        row.score_pct = result.score_pct
        row.signal_label = result.signal_label
        row.representatives_json = result.representatives
        row.folds_json = folds_json
        row.wfe_pct = result.wfe_pct
        row.robustness_ratio = result.robustness_ratio
        row.total_folds = result.total_folds
        row.profitable_folds = result.profitable_folds
        row.mean_oos_sharpe = result.mean_oos_sharpe
        row.total_oos_pnl = result.total_oos_pnl
        row.worst_fold_drawdown = result.worst_fold_drawdown
        row.composite_score = result.composite_score
        row.robustness_grade = result.robustness_grade
        row.config_json = result.config_used
        row.compute_seconds = result.compute_seconds
    else:
        row.score_pct = None
        row.signal_label = None
        row.representatives_json = []
        row.folds_json = folds_json
        row.wfe_pct = None
        row.robustness_ratio = None
        row.total_folds = None
        row.profitable_folds = None
        row.mean_oos_sharpe = None
        row.total_oos_pnl = None
        row.worst_fold_drawdown = None
        row.composite_score = None
        row.robustness_grade = None
        row.config_json = result.config_used if result is not None else None
        row.compute_seconds = result.compute_seconds if result is not None else None

# ---------------------------------------------------------------------------
# Top-level RQ task
# ---------------------------------------------------------------------------

def compute_wfo_factor_x_ta_for_symbol(
    symbol: str,
    horizon: str,
    variant: str = VARIANT,
    cost_bps: float = DEFAULT_COST_BPS,
    cooldown_bars: int = DEFAULT_COOLDOWN_BARS,
) -> dict:
    """RQ task: run WFO ×fx pipeline for one symbol × horizon.

    Persists results to wfo_signal_summary with variant='factor_x_ta'.
    """
    t0 = time.perf_counter()
    db: Session = SessionLocal()
    mode = resolve_signal_mode(variant)
    variant = mode.name
    category_families = _category_families_for_variant(variant)

    try:
        pre_reg = _load_pre_registration()
        channel_tags_yaml = _load_channel_tags()
        all_conditions = _build_conditions(pre_reg)

        try:
            ohlcv_raw = load_ohlcv_for_symbol(db, symbol, DEFAULT_TIMEFRAME)
            ohlcv = drop_incomplete_ohlcv_rows(ohlcv_raw)
        except Exception as exc:
            logger.warning("WFO×fx: no OHLCV for %s: %s", symbol, exc)
            return {"symbol": symbol, "horizon": horizon, "status": "failed", "error": str(exc)}

        if len(ohlcv) < 10:
            return {"symbol": symbol, "horizon": horizon, "status": "skipped", "reason": "insufficient bars"}

        data_as_of = ohlcv.index[-1].date()
        close = ohlcv["Close"].values.astype(np.float64)
        high = ohlcv["High"].values.astype(np.float64) if "High" in ohlcv.columns else None
        low = ohlcv["Low"].values.astype(np.float64) if "Low" in ohlcv.columns else None
        volume = ohlcv["Volume"].values.astype(np.float64) if "Volume" in ohlcv.columns else None

        runtime = _build_runtime_inputs(
            db,
            symbol=symbol,
            horizon=horizon,
            ohlcv=ohlcv,
            all_conditions=all_conditions,
            channel_tags_yaml=channel_tags_yaml,
        )
        if runtime.selection_warning:
            logger.warning(
                "WFO×fx: factor selection unavailable for %s/%s; using stock_factor_config fallback: %s",
                symbol,
                horizon,
                runtime.selection_warning,
            )

        if not runtime.conditions:
            for category in category_families:
                _upsert_wfo_fx_summary(
                    db,
                    symbol,
                    category,
                    horizon,
                    variant=variant,
                    status="no_signal",
                    data_as_of=data_as_of,
                    error_message="no active factor conditions",
                )
            db.commit()
            return {"symbol": symbol, "horizon": horizon, "status": "skipped", "reason": "no active conditions"}

        if not runtime.aligned_factor_arrays:
            for category in category_families:
                _upsert_wfo_fx_summary(
                    db,
                    symbol,
                    category,
                    horizon,
                    variant=variant,
                    status="no_signal",
                    data_as_of=data_as_of,
                    error_message="factor series not ingested or not alignable",
                )
            db.commit()
            return {"symbol": symbol, "horizon": horizon, "status": "skipped", "reason": "factor series not ingested"}

        n = len(close)
        completed = 0
        failed = 0
        category_results: dict[str, Any] = {}

        for category, families in category_families.items():
            _upsert_wfo_fx_summary(db, symbol, category, horizon, variant=variant, status="running")
            db.commit()

            t_cat = time.perf_counter()
            try:
                if mode.is_combo:
                    combo_prefix = "legacy_fx_combo" if mode.universe == "legacy" else "expanded_fx_combo"
                    conditioned_pool, precomputed = build_factor_x_ta_combo_pool_for_category(
                        category=category,
                        combo_family=f"{combo_prefix}_{category}",
                        category_families=category_families,
                        horizon=horizon,
                        close=close,
                        aligned_factor_arrays=runtime.aligned_factor_arrays,
                        conditions=runtime.conditions,
                        volume=volume,
                        high=high,
                        low=low,
                        channel_tags=runtime.channel_gate,
                        stock_sector=runtime.stock_sector,
                    )
                else:
                    # Generate factor-conditioned candidates for all families in this category
                    conditioned_pool = []
                    for family in families:
                        try:
                            ta_candidates = generate_candidates(family, horizon)
                        except (ValueError, NotImplementedError):
                            ta_candidates = []
                        conditioned = generate_factor_conditioned_candidates(
                            ta_candidates,
                            runtime.conditions,
                            channel_tags=runtime.channel_gate or None,
                            stock_sector=runtime.stock_sector,
                        )
                        conditioned_pool.extend(conditioned)

                    # Precompute AND signals for the full close array
                    precomputed = {}
                    for c_variant in conditioned_pool:
                        cond = c_variant.factor_condition
                        if cond is None:
                            continue
                        factor_close = runtime.aligned_factor_arrays.get(cond.factor_ticker)
                        if factor_close is None or len(factor_close) == 0:
                            continue

                        # Align factor to stock length
                        fc = factor_close
                        if len(fc) > n:
                            fc = fc[-n:]
                        elif len(fc) < n:
                            fc = np.concatenate([np.full(n - len(fc), np.nan), fc])

                        ta_sig = _compute_ta_signal_for_conditioned(
                            c_variant, close, volume=volume, high=high, low=low,
                        )
                        if ta_sig is None:
                            continue

                        condition_mask = evaluate_condition(cond, fc)
                        composed = compose_and_signal(ta_sig, condition_mask)
                        precomputed[c_variant.variant_id] = composed

                if not precomputed:
                    _upsert_wfo_fx_summary(
                        db, symbol, category, horizon,
                        variant=variant,
                        status="no_signal",
                        error_message="No precomputed signals for category",
                    )
                    db.commit()
                    continue

                result = run_wfo_fx_for_category(
                    category=category,
                    horizon=horizon,
                    close=close,
                    conditioned_pool=conditioned_pool,
                    precomputed=precomputed,
                    volume=volume,
                    high=high,
                    low=low,
                    cost_bps=cost_bps,
                )
                result.symbol = symbol
                result.data_as_of = str(data_as_of)
                result.compute_seconds = round(time.perf_counter() - t_cat, 2)

                cap_len = int((result.config_used or {}).get("cap_len") or len(ohlcv.index))
                fold_index = ohlcv.index[-cap_len:] if cap_len > 0 else ohlcv.index
                folds_json = _build_folds_json(result, conditioned_pool, fold_index)
                _upsert_wfo_fx_summary(
                    db, symbol, category, horizon,
                    variant=variant,
                    status=result.status if result.representatives else "no_signal",
                    result=result,
                    data_as_of=data_as_of,
                    error_message=result.error_message or None,
                    folds_json=folds_json,
                )
                if result.status == "succeeded":
                    completed += 1
                    category_results[category] = result
                else:
                    failed += 1
            except Exception as exc:
                logger.exception("WFO×fx category failed: %s/%s/%s/%s", symbol, category, horizon, exc)
                _upsert_wfo_fx_summary(
                    db, symbol, category, horizon,
                    variant=variant,
                    status="failed",
                    error_message=str(exc),
                )
                failed += 1

            db.commit()

        # Phase 5: Global Consensus and S/R
        support, resistance, support_method, resistance_method, atr = _get_sr_levels(
            close, high, low, volume, horizon
        )
        try:
            global_result = compute_global_wfo_signal(
                category_results, close,
                support=support, resistance=resistance,
                support_method=support_method,
                resistance_method=resistance_method,
                atr=atr, volume=volume, high=high, low=low,
            )
            global_result.symbol = symbol
            global_result.horizon = horizon
            _upsert_global(
                db,
                symbol,
                horizon,
                global_result,
                data_as_of,
                variant=variant,
                is_full_recompute=True,
            )
        except Exception:
            logger.exception("WFO×fx global failed: %s/%s", symbol, horizon)
        db.commit()

        overall_status = (
            "succeeded"
            if completed > 0 and failed == 0
            else ("partial" if completed > 0 else ("no_signal" if failed == 0 else "failed"))
        )
        return {
            "symbol": symbol,
            "horizon": horizon,
            "status": overall_status,
            "completed": completed,
            "failed": failed,
            "elapsed": round(time.perf_counter() - t0, 2),
        }
    except Exception as exc:
        logger.exception("WFO×fx batch failed: %s/%s: %s", symbol, horizon, exc)
        db.rollback()
        return {"symbol": symbol, "horizon": horizon, "status": "failed", "error": str(exc)}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Enqueue helper
# ---------------------------------------------------------------------------

def enqueue_wfo_factor_x_ta_for_symbol(
    symbol: str,
    horizon: str,
    variant: str = VARIANT,
    triggered_by: str = "manual",
    depends_on: str | None = None,
) -> str:
    """Enqueue a WFO ×fx job on the signal_engine queue and return the job id."""
    from rq import Queue
    from services.worker.config import settings

    variant = signal_mode_storage_name(variant)
    redis = connect_redis_with_fallback(settings.REDIS_URL, decode_responses=False, logger=logger)
    q = Queue(settings.SIGNAL_ENGINE_QUEUE_NAME, connection=redis)
    job = q.enqueue(
        compute_wfo_factor_x_ta_for_symbol,
        symbol,
        horizon,
        variant,
        job_timeout=7200,
        depends_on=depends_on,
        meta={"triggered_by": triggered_by},
    )
    return str(job.id)
