"""Weekly batch task: compute WFO signals for all tracked symbols.

Entry point: run_weekly_wfo_batch()
Per-symbol:  run_wfo_for_symbol_horizon(db, symbol, horizon)
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from services.worker.db import SessionLocal
from services.worker.redis_utils import connect_redis_with_fallback
from services.api.app.models import (
    WfoGlobalSignal,
    WfoSignalSummary,
)
from services.api.app.services.market_universe import list_signal_universe_symbols
from services.api.app.services.weekly_recompute_policy import iter_wfo_weekly_stale_tuples
from services.api.app.market_data_loader import load_ohlcv_for_symbol
from core.quant_core.horizons import DEFAULT_COST_BPS_PER_SIDE, HORIZON_SPECS
from core.quant_core.data import drop_incomplete_ohlcv_rows
from core.quant_core.signal_engine.current_signal import build_current_signal
from core.quant_core.signal_engine.domain import (
    CATEGORY_FAMILIES,
    FAMILY_SIGNAL_TYPE,
    HORIZON_PARAMS,
    VARIANT_FAMILIES,
    VariantDef,
    signal_type_label,
)
from core.quant_core.signal_engine.modes import resolve_signal_mode, signal_mode_read_names, signal_mode_storage_name
from core.quant_core.signal_engine.wfo_signal import WfoCategoryResult, run_wfo_category_signal
from core.quant_core.signal_engine.variant_detail import compute_variant_signal_array
from core.quant_core.signal_engine.wfo_global import compute_global_wfo_signal

logger = logging.getLogger(__name__)

HORIZONS = ("weekly", "monthly", "quarterly")
CATEGORIES = ("tendance", "momentum", "oscillation", "volume")


# ---------------------------------------------------------------------------
# Top-level entry points
# ---------------------------------------------------------------------------

def _active_symbols(db: Session) -> list[str]:
    return list_signal_universe_symbols(db)


def run_weekly_wfo_batch(*, now: datetime | None = None) -> dict:
    """Compute WFO signals only for weekly-stale data-backed tuples.

    Called by RQ scheduler or cron. Returns a summary dict.
    """
    db: Session = SessionLocal()
    try:
        targets = iter_wfo_weekly_stale_tuples(
            db,
            symbols=_active_symbols(db),
            now=now,
        )
        logger.info("WFO batch: %d stale tuples to process", len(targets))

        results = {"total": 0, "succeeded": 0, "failed": 0}

        for symbol, horizon, variant in targets:
            try:
                run_wfo_for_symbol_horizon(db, symbol, horizon, variant=variant)
                results["succeeded"] += 1
            except Exception:
                logger.exception("WFO batch failed: %s/%s/%s", symbol, horizon, variant)
                results["failed"] += 1
            results["total"] += 1

        return results
    finally:
        db.close()


def enqueue_wfo_for_symbol_horizon(
    symbol: str,
    horizon: str,
    overrides: dict | None = None,
    variant: str = "expanded",
) -> None:
    """RQ entry point: creates its own DB session and delegates."""
    mode = resolve_signal_mode(variant)
    variant = mode.name
    if mode.is_factor_x_ta:
        from services.worker.tasks.wfo_factor_x_ta_batch import compute_wfo_factor_x_ta_for_symbol

        compute_wfo_factor_x_ta_for_symbol(symbol, horizon, variant=variant)
        return
    db: Session = SessionLocal()
    try:
        run_wfo_for_symbol_horizon(db, symbol, horizon, overrides=overrides or {}, variant=variant)
    finally:
        db.close()


def enqueue_wfo_refresh_for_symbol_horizon(
    symbol: str,
    horizon: str,
    variant: str = "expanded",
    triggered_by: str = "market_refresh",
) -> str:
    """Enqueue lightweight representative-only WFO refresh on the wfo_signals queue."""
    from rq import Queue
    from services.worker.config import settings

    redis = connect_redis_with_fallback(settings.REDIS_URL, decode_responses=False, logger=logger)
    q = Queue("wfo_signals", connection=redis)
    job = q.enqueue(
        refresh_wfo_for_symbol_horizon,
        symbol,
        horizon,
        variant,
        job_timeout=1200,
        meta={"triggered_by": triggered_by},
    )
    return str(job.id)


def enqueue_wfo_full_for_symbol_horizon(
    symbol: str,
    horizon: str,
    *,
    variant: str = "expanded",
    overrides: dict | None = None,
    triggered_by: str = "manual",
    depends_on: str | None = None,
) -> str:
    """Enqueue a full WFO compute for one tuple on the wfo_signals queue."""
    from rq import Queue
    from services.worker.config import settings

    variant = signal_mode_storage_name(variant)
    redis = connect_redis_with_fallback(settings.REDIS_URL, decode_responses=False, logger=logger)
    q = Queue("wfo_signals", connection=redis)
    job = q.enqueue(
        "services.worker.tasks.wfo_signal_batch.enqueue_wfo_for_symbol_horizon",
        symbol,
        horizon,
        overrides if overrides else None,
        variant,
        job_timeout=7200,
        meta={"triggered_by": triggered_by},
        depends_on=depends_on,
    )
    return str(job.id)


def _result_index_offset(result: Any) -> int:
    diagnostics = getattr(result, "window_diagnostics", {}) or {}
    try:
        return max(0, int(diagnostics.get("horizon_cap_start_offset") or 0))
    except Exception:
        return 0


def _window_date(
    index: Any,
    position: int,
    *,
    end_exclusive: bool = False,
    position_offset: int = 0,
) -> str | None:
    if index is None:
        return None
    try:
        loc = int(position_offset) + int(position) - (1 if end_exclusive else 0)
        if loc < 0 or loc >= len(index):
            return None
        value = index[loc]
        if hasattr(value, "date"):
            return value.date().isoformat()
        return str(value)
    except Exception:
        return None


def _build_folds_json(result, pool: list | None = None, index: Any = None) -> list[dict] | None:
    """Extract per-fold details from a WfoCategoryResult's engine_result."""
    er = result.engine_result
    if er is None or not er.windows:
        return None
    index_offset = _result_index_offset(result)
    folds = []
    for w in er.windows:
        winner_id = ""
        winner_desc = ""
        winner_params = {}
        if pool is not None and isinstance(w.winner_key, int) and w.winner_key < len(pool):
            winner_id = pool[w.winner_key].variant_id
            winner_desc = pool[w.winner_key].description
            winner_params = dict(getattr(pool[w.winner_key], "params", {}) or {})
        train_start_idx = int(w.window.train_start)
        train_end_idx = int(w.window.train_end)
        oos_start_idx = int(w.window.oos_start)
        oos_end_idx = int(w.window.oos_end)
        train_start_abs_idx = index_offset + train_start_idx
        train_end_abs_idx = index_offset + train_end_idx
        oos_start_abs_idx = index_offset + oos_start_idx
        oos_end_abs_idx = index_offset + oos_end_idx
        folds.append({
            "index": w.window.index,
            "train_start": train_start_idx,
            "train_end": train_end_idx,
            "oos_start": oos_start_idx,
            "oos_end": oos_end_idx,
            "train_start_idx": train_start_idx,
            "train_end_idx": train_end_idx,
            "oos_start_idx": oos_start_idx,
            "oos_end_idx": oos_end_idx,
            "train_start_abs_idx": train_start_abs_idx,
            "train_end_abs_idx": train_end_abs_idx,
            "oos_start_abs_idx": oos_start_abs_idx,
            "oos_end_abs_idx": oos_end_abs_idx,
            "train_start_date": _window_date(index, train_start_idx, position_offset=index_offset),
            "train_end_date": _window_date(index, train_end_idx, end_exclusive=True, position_offset=index_offset),
            "oos_start_date": _window_date(index, oos_start_idx, position_offset=index_offset),
            "oos_end_date": _window_date(index, oos_end_idx, end_exclusive=True, position_offset=index_offset),
            "is_return": round(w.is_return, 6),
            "oos_return": round(w.oos_return, 6),
            "oos_sharpe": round(getattr(w, 'oos_sharpe', 0.0), 4),
            "winner_variant_id": winner_id,
            "winner_description": winner_desc,
            "winner_params": winner_params,
            "winner_prom": round(w.winner_prom, 6),
            "profile_passes": w.profile.passes,
            "profile_reason": w.profile.reason,
            "profile_pct_profitable": round(w.profile.pct_profitable, 4),
            "oos_profitable": w.oos_return > 0,
        })
    return folds


def _numeric_param_distance(candidate: VariantDef, winner: VariantDef) -> float | None:
    if candidate.family != winner.family or candidate.archetype != winner.archetype:
        return None
    distance = 0.0
    numeric_seen = False
    for key, winner_value in winner.params.items():
        candidate_value = candidate.params.get(key)
        if isinstance(winner_value, (int, float)) and isinstance(candidate_value, (int, float)):
            numeric_seen = True
            radius = max(0, int(math.ceil(abs(float(winner_value)) * 0.10)))
            if abs(float(candidate_value) - float(winner_value)) > radius:
                return None
            distance += abs(float(candidate_value) - float(winner_value))
        elif candidate_value != winner_value:
            return None
    return distance if numeric_seen else (0.0 if candidate.variant_id == winner.variant_id else None)


def _local_neighbors(pool: list[VariantDef], winner: VariantDef, *, max_neighbors: int = 25) -> list[VariantDef]:
    rows: list[tuple[float, str, VariantDef]] = []
    for candidate in pool:
        dist = _numeric_param_distance(candidate, winner)
        if dist is not None:
            rows.append((dist, candidate.variant_id, candidate))
    rows.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in rows[:max_neighbors]]


def _variant_oos_edge_ratio(
    *,
    variant: VariantDef,
    close: np.ndarray,
    volume: np.ndarray | None,
    high: np.ndarray | None,
    low: np.ndarray | None,
    start: int,
    end: int,
    horizon_bars: int,
) -> float | None:
    sig = compute_variant_signal_array(close, variant, volume=volume, high=high, low=low)
    prices = np.asarray(close, dtype="float64")
    if len(sig) != len(prices) or len(prices) <= horizon_bars or end <= start:
        return None
    fwd = (np.roll(prices, -int(horizon_bars)) / prices) - 1.0
    fwd[-int(horizon_bars):] = np.nan
    lo = max(0, int(start))
    hi = min(int(end), len(prices))
    signal_slice = sig[lo:hi]
    returns_slice = fwd[lo:hi]
    mask = np.isfinite(returns_slice) & (signal_slice != 0)
    strategy_returns = signal_slice[mask].astype("float64") * returns_slice[mask].astype("float64")
    if len(strategy_returns) < 3:
        return None
    std = float(np.std(strategy_returns, ddof=1))
    if std <= 0.0 or not np.isfinite(std):
        return None
    return float(np.mean(strategy_returns) / std)


def _fragility_class(metric_winner: float, metrics: list[float]) -> tuple[str, float, float]:
    vals = np.asarray([v for v in metrics if np.isfinite(v)], dtype="float64")
    if len(vals) == 0 or not np.isfinite(metric_winner):
        return "unavailable", float("nan"), float("nan")
    rng = np.random.default_rng(20260507)
    boot = np.empty(1000, dtype="float64")
    for i in range(len(boot)):
        sample = vals[rng.integers(0, len(vals), size=len(vals))]
        boot[i] = float(np.mean(sample))
    ci_lo = float(np.percentile(boot, 2.5))
    ci_hi = float(np.percentile(boot, 97.5))
    winner_positive = metric_winner >= 0.0
    opposite_sign = (ci_hi < 0.0 and winner_positive) or (ci_lo > 0.0 and not winner_positive)
    negative_share = float(np.mean(vals < 0.0))
    if opposite_sign or negative_share > 0.50:
        return "severe", ci_lo, ci_hi
    if (ci_lo <= 0.0 <= ci_hi) or not (ci_lo <= metric_winner <= ci_hi):
        return "mixed", ci_lo, ci_hi
    return "stable", ci_lo, ci_hi


def _aggregate_fragility(details: list[dict[str, Any]]) -> str:
    classified = [d for d in details if d.get("class") in {"stable", "mixed", "severe"}]
    if not classified:
        return "unavailable"
    n = len(classified)
    severe_share = sum(1 for d in classified if d.get("class") == "severe") / n
    mixed_or_severe_share = sum(1 for d in classified if d.get("class") in {"mixed", "severe"}) / n
    if severe_share >= 0.60 or mixed_or_severe_share >= 0.60:
        return "fragility_in_most_folds"
    if severe_share >= 0.30 or mixed_or_severe_share >= 0.30:
        return "mixed_local_sensitivity"
    return "no_severe_fragility"


def _build_fragility_json(
    *,
    result: WfoCategoryResult,
    pool: list[VariantDef],
    close: np.ndarray,
    volume: np.ndarray | None,
    high: np.ndarray | None,
    low: np.ndarray | None,
    index: Any,
) -> dict[str, Any] | None:
    er = result.engine_result
    if er is None or not er.windows or not pool:
        return None
    index_offset = _result_index_offset(result)
    horizon_bars = int(HORIZON_SPECS[result.horizon].reference_forward_days)
    details: list[dict[str, Any]] = []
    for w in er.windows:
        winner = pool[w.winner_key] if isinstance(w.winner_key, int) and w.winner_key < len(pool) else None
        if winner is None:
            details.append({"fold_id": w.window.index, "class": "unavailable", "reason": "winner_missing"})
            continue
        oos_start_abs_idx = index_offset + int(w.window.oos_start)
        oos_end_abs_idx = index_offset + int(w.window.oos_end)
        metrics: list[float] = []
        metric_winner: float | None = None
        for neighbor in _local_neighbors(pool, winner):
            metric = _variant_oos_edge_ratio(
                variant=neighbor,
                close=close,
                volume=volume,
                high=high,
                low=low,
                start=oos_start_abs_idx,
                end=oos_end_abs_idx,
                horizon_bars=horizon_bars,
            )
            if metric is None:
                continue
            metrics.append(metric)
            if neighbor.variant_id == winner.variant_id:
                metric_winner = metric
        if metric_winner is None:
            details.append({"fold_id": w.window.index, "class": "unavailable", "reason": "winner_metric_unavailable"})
            continue
        klass, ci_lo, ci_hi = _fragility_class(metric_winner, metrics)
        details.append(
            {
                "fold_id": w.window.index,
                "winner_variant_id": winner.variant_id,
                "winner_params": dict(winner.params),
                "neighbor_count": len(metrics),
                "metric_winner": round(float(metric_winner), 6),
                "ci_lower": round(float(ci_lo), 6) if np.isfinite(ci_lo) else None,
                "ci_upper": round(float(ci_hi), 6) if np.isfinite(ci_hi) else None,
                "class": klass,
                "oos_start_abs_idx": oos_start_abs_idx,
                "oos_end_abs_idx": oos_end_abs_idx,
                "oos_start_date": _window_date(index, int(w.window.oos_start), position_offset=index_offset),
                "oos_end_date": _window_date(
                    index,
                    int(w.window.oos_end),
                    end_exclusive=True,
                    position_offset=index_offset,
                ),
            }
        )
    return {
        "label": _aggregate_fragility(details),
        "fold_count": len([d for d in details if d.get("class") in {"stable", "mixed", "severe"}]),
        "details": details,
    }


def _iso_date_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if hasattr(value, "isoformat"):
            return str(value.isoformat())[:10]
        return str(value)[:10]
    except Exception:
        return None


def _fold_coverage_metadata(
    *,
    folds_json: list[dict] | None,
    index: Any,
    data_as_of: Any,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    data_as_of_text = _iso_date_text(data_as_of)
    if data_as_of_text:
        metadata["data_as_of"] = data_as_of_text
    if not folds_json:
        return metadata

    last_fold = folds_json[-1]
    last_oos_end_abs_idx = last_fold.get("oos_end_abs_idx")
    if isinstance(last_oos_end_abs_idx, int):
        metadata["last_oos_end_abs_idx"] = last_oos_end_abs_idx
        if index is not None:
            metadata["unused_tail_bars"] = max(0, len(index) - last_oos_end_abs_idx)

    if last_fold.get("oos_end_date") is not None:
        metadata["last_oos_end_date"] = last_fold.get("oos_end_date")
    if last_fold.get("oos_start_date") is not None:
        metadata["last_oos_start_date"] = last_fold.get("oos_start_date")
    return metadata


def _build_config_json(
    horizon: str,
    category: str,
    close_len: int,
    pool_size: int,
    overrides: dict,
    result=None,
    families: list[str] | None = None,
    folds_json: list[dict] | None = None,
    index: Any = None,
    data_as_of: Any = None,
) -> dict:
    """Build the config context dict for storage."""
    from core.quant_core.signal_engine.domain import HORIZON_PARAMS, CATEGORY_FAMILIES

    hp = HORIZON_PARAMS[horizon]
    config_used = getattr(result, "config_used", {}) or {}
    diagnostics = getattr(result, "window_diagnostics", {}) or {}
    train = config_used.get("train_bars") or overrides.get("train_bars") or hp["train"]
    oos = config_used.get("oos_bars") or overrides.get("oos_bars") or hp["test"]
    step = config_used.get("step_bars") or overrides.get("step_bars") or hp["step"]
    payload = {
        "train_bars": train,
        "oos_bars": oos,
        "step_bars": step,
        "data_bars": close_len,
        "min_bars_needed": config_used.get("min_bars_needed", train + oos),
        "grid_size": pool_size,
        "cost_bps": overrides.get("cost_bps", DEFAULT_COST_BPS_PER_SIDE),
        "max_reps": overrides.get("max_reps", 1),
        "max_corr": overrides.get("max_corr", 0.85),
        "families": families if families is not None else CATEGORY_FAMILIES.get(category, []),
    }
    payload.update(diagnostics)
    if config_used:
        payload.update(config_used)
    payload.update(_fold_coverage_metadata(folds_json=folds_json, index=index, data_as_of=data_as_of))
    return payload


def run_wfo_for_symbol_horizon(
    db: Session,
    symbol: str,
    horizon: str,
    *,
    overrides: dict | None = None,
    variant: str = "expanded",
) -> None:
    """Run WFO for all 4 categories + global consensus for one symbol × horizon × variant.

    1. Load OHLCV data
    2. For each category: run_wfo_category_signal() with families resolved from variant
    3. Compute global consensus + S/R modulation
    4. Upsert results into DB
    """
    overrides = overrides or {}
    variant = signal_mode_storage_name(variant)
    families_map = VARIANT_FAMILIES.get(variant, VARIANT_FAMILIES["expanded"])
    logger.info("WFO signal: %s / %s / %s (overrides=%s)", symbol, horizon, variant, overrides)

    # --- Load data ---
    ohlcv_raw = load_ohlcv_for_symbol(db, symbol)
    ohlcv = drop_incomplete_ohlcv_rows(ohlcv_raw)

    if ohlcv.empty:
        logger.warning("WFO signal: no OHLCV data for %s", symbol)
        return

    # Normalise column names (market_data_loader may return Title case)
    col_map = {c.lower(): c for c in ohlcv.columns}

    def _col(name: str) -> "np.ndarray | None":
        import numpy as np
        key = col_map.get(name)
        return ohlcv[key].values.astype(float) if key else None

    import numpy as np
    close  = _col("close")
    if close is None:
        # Try "Close" directly
        close = ohlcv["Close"].values.astype(float) if "Close" in ohlcv.columns else None
    if close is None:
        logger.warning("WFO signal: no close column for %s", symbol)
        return

    volume = _col("volume")
    high   = _col("high")
    low    = _col("low")
    data_as_of = ohlcv.index[-1].date() if len(ohlcv) > 0 else None

    # --- Per-category WFO ---
    category_results: dict[str, Any] = {}

    # Build override kwargs for run_wfo_category_signal
    wfo_kwargs: dict[str, Any] = {}
    for key in (
        "cost_bps",
        "max_reps",
        "max_corr",
        "train_bars",
        "oos_bars",
        "step_bars",
        "window_policy",
        "top_k_folds",
        "min_walk_forwards",
        "strict_fallback_enabled",
        "strict_fallback_floor",
    ):
        if key in overrides and overrides[key] is not None:
            wfo_kwargs[key] = overrides[key]

    for category in CATEGORIES:
        _upsert_summary(db, symbol, category, horizon, variant=variant, status="running")
        db.commit()

        # Build candidate grid for fold context
        from core.quant_core.signal_engine.wfo_signal import build_category_candidate_grid
        cat_families = families_map.get(category)
        try:
            pool = build_category_candidate_grid(category, horizon, families=cat_families)
        except Exception:
            pool = []

        config_json = _build_config_json(
            horizon, category, len(close), len(pool), overrides,
            families=cat_families,
        )

        try:
            result = run_wfo_category_signal(
                category, horizon, close,
                volume=volume, high=high, low=low,
                families=cat_families,
                **wfo_kwargs,
            )
            result.symbol = symbol
            result.data_as_of = str(data_as_of) if data_as_of else ""
            category_results[category] = result

            folds_json = _build_folds_json(result, pool, ohlcv.index)
            fragility_json = _build_fragility_json(
                result=result,
                pool=pool,
                close=close,
                volume=volume,
                high=high,
                low=low,
                index=ohlcv.index,
            )
            config_json = _build_config_json(
                horizon,
                category,
                len(close),
                len(pool),
                overrides,
                result=result,
                families=cat_families,
                folds_json=folds_json,
                index=ohlcv.index,
                data_as_of=data_as_of,
            )

            _upsert_summary(
                db, symbol, category, horizon,
                variant=variant,
                status=result.status, result=result, data_as_of=data_as_of,
                folds_json=folds_json, config_json=config_json,
                fragility_json=fragility_json,
                error_message=result.error_message or None,
            )
        except Exception as exc:
            logger.exception("WFO category failed: %s/%s/%s/%s", symbol, category, horizon, variant)
            _upsert_summary(
                db, symbol, category, horizon,
                variant=variant,
                status="failed", error_message=str(exc),
                config_json=config_json,
            )

        db.commit()

    # --- Global consensus ---
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
        _upsert_global(db, symbol, horizon, global_result, data_as_of, variant=variant)
    except Exception:
        logger.exception("WFO global failed: %s/%s", symbol, horizon)

    db.commit()


def refresh_wfo_for_symbol_horizon(
    symbol: str,
    horizon: str,
    variant: str = "expanded",
) -> dict[str, Any]:
    """Refresh WFO current signals from persisted representatives only."""
    mode = resolve_signal_mode(variant)
    variant = mode.name
    if mode.is_factor_x_ta:
        from services.worker.tasks.wfo_factor_x_ta_batch import compute_wfo_factor_x_ta_for_symbol

        result = compute_wfo_factor_x_ta_for_symbol(symbol, horizon, variant=variant)
        result["mode"] = "factor_x_ta_dedicated"
        return result
    db: Session = SessionLocal()
    started = time.monotonic()
    refreshed = 0
    failed = 0

    try:
        families_map = VARIANT_FAMILIES.get(variant, VARIANT_FAMILIES["expanded"])

        ohlcv_raw = load_ohlcv_for_symbol(db, symbol)
        ohlcv = drop_incomplete_ohlcv_rows(ohlcv_raw)
        if ohlcv.empty:
            return {"symbol": symbol, "horizon": horizon, "variant": variant, "status": "failed", "error": "No OHLCV data"}

        max_bars = HORIZON_PARAMS[horizon]["max_years"] * 252
        if len(ohlcv) > max_bars:
            ohlcv = ohlcv.iloc[-max_bars:]

        col_map = {c.lower(): c for c in ohlcv.columns}

        def _col(name: str) -> "np.ndarray | None":
            import numpy as np
            key = col_map.get(name)
            return ohlcv[key].values.astype(float) if key else None

        import numpy as np
        close = _col("close")
        if close is None:
            close = ohlcv["Close"].values.astype(float) if "Close" in ohlcv.columns else None
        if close is None:
            return {
                "symbol": symbol,
                "horizon": horizon,
                "variant": variant,
                "status": "failed",
                "error": "No close column",
            }

        volume = _col("volume")
        high = _col("high")
        low = _col("low")
        data_as_of = ohlcv.index[-1].date() if len(ohlcv) > 0 else None

        rows = []
        for read_variant in signal_mode_read_names(variant):
            rows.extend(
                db.query(WfoSignalSummary)
                .filter_by(symbol=symbol, horizon=horizon, variant=read_variant)
                .all()
            )
        if not rows:
            logger.info(
                "WFO refresh: no persisted categories for %s/%s/%s, falling back to full compute",
                symbol,
                horizon,
                variant,
            )
            run_wfo_for_symbol_horizon(db, symbol, horizon, overrides={}, variant=variant)
            return {
                "symbol": symbol,
                "horizon": horizon,
                "variant": variant,
                "status": "succeeded",
                "mode": "fallback_full_compute",
            }

        row_by_category = {row.category: row for row in rows}
        category_results: dict[str, WfoCategoryResult] = {}

        for category in CATEGORIES:
            row = row_by_category.get(category)
            if row is None:
                failed += 1
                continue

            t_cat = time.monotonic()
            try:
                reps_src = [rep for rep in (row.representatives_json or []) if isinstance(rep, dict)]
                if not reps_src:
                    row.status = "failed"
                    row.error_message = "No persisted representatives to refresh."
                    row.computed_at = datetime.now(timezone.utc)
                    row.data_as_of = data_as_of
                    row.compute_seconds = round(time.monotonic() - t_cat, 2)
                    failed += 1
                    db.commit()
                    continue

                refreshed_reps = []
                weighted_sum = 0.0
                total_weight = 0.0

                for rep in reps_src:
                    variant_def = _variant_from_rep(rep)
                    weight = float(rep.get("normalized_weight") or rep.get("reliability_weight") or 1.0)
                    if weight <= 0:
                        weight = 1.0
                    current = build_current_signal(
                        variant_def,
                        close,
                        volume=volume,
                        high=high,
                        low=low,
                        reliability_weight=weight,
                    )
                    weighted_sum += weight * float(current.signal)
                    total_weight += weight
                    refreshed_rep = dict(rep)
                    refreshed_rep.update(
                        {
                            "family": variant_def.family,
                            "archetype": variant_def.archetype,
                            "variant_id": variant_def.variant_id,
                            "params": dict(variant_def.params),
                            "description": str(rep.get("description") or variant_def.description or ""),
                            "signal": float(current.signal),
                            "signal_label": str(current.signal_label),
                            "current_close": float(current.current_close),
                            "indicator_value": (
                                float(current.indicator_value)
                                if current.indicator_value is not None
                                else None
                            ),
                            "explanation": str(current.explanation or ""),
                        }
                    )
                    refreshed_reps.append(refreshed_rep)

                if total_weight <= 0:
                    raise ValueError("All representative weights are zero.")

                for rep in refreshed_reps:
                    normalized = float(rep.get("normalized_weight") or rep.get("reliability_weight") or 1.0) / total_weight
                    rep["normalized_weight"] = round(normalized, 4)
                    rep["contribution"] = round(normalized * float(rep.get("signal") or 0.0), 4)

                score_pct = round((weighted_sum / total_weight) * 100.0, 2)
                first_family = str(refreshed_reps[0].get("family") or families_map.get(category, [category])[0])
                signal_type = FAMILY_SIGNAL_TYPE.get(first_family, "trend")
                signal_label = signal_type_label(signal_type, score_pct)

                row.status = "succeeded"
                row.error_message = None
                row.score_pct = score_pct
                row.signal_label = signal_label
                row.representatives_json = refreshed_reps
                row.computed_at = datetime.now(timezone.utc)
                row.data_as_of = data_as_of
                row.compute_seconds = round(time.monotonic() - t_cat, 2)
                db.commit()

                category_results[category] = WfoCategoryResult(
                    category=category,
                    symbol=symbol,
                    horizon=horizon,
                    status="succeeded",
                    score_pct=float(score_pct),
                    signal_label=str(signal_label),
                    representatives=refreshed_reps,
                    wfe_pct=float(row.wfe_pct or 0.0),
                    robustness_ratio=float(row.robustness_ratio or 0.0),
                    total_folds=int(row.total_folds or 0),
                    profitable_folds=int(row.profitable_folds or 0),
                    mean_oos_sharpe=float(row.mean_oos_sharpe or 0.0),
                    total_oos_pnl=float(row.total_oos_pnl or 0.0),
                    worst_fold_drawdown=float(row.worst_fold_drawdown or 0.0),
                    composite_score=float(row.composite_score or 0.0),
                    robustness_grade=str(row.robustness_grade or "F"),
                    config_used=dict(row.config_json or {}),
                    data_as_of=str(data_as_of) if data_as_of else "",
                    compute_seconds=float(row.compute_seconds or 0.0),
                )
                refreshed += 1
            except Exception as exc:
                logger.exception("WFO refresh failed: %s/%s/%s/%s", symbol, category, horizon, variant)
                row.status = "failed"
                row.error_message = str(exc)
                row.computed_at = datetime.now(timezone.utc)
                row.data_as_of = data_as_of
                row.compute_seconds = round(time.monotonic() - t_cat, 2)
                db.commit()
                failed += 1

        support, resistance, support_method, resistance_method, atr = _get_sr_levels(
            close, high, low, volume, horizon
        )
        global_result = compute_global_wfo_signal(
            category_results,
            close,
            support=support,
            resistance=resistance,
            support_method=support_method,
            resistance_method=resistance_method,
            atr=atr,
            volume=volume,
            high=high,
            low=low,
        )
        global_result.symbol = symbol
        global_result.horizon = horizon
        _upsert_global(db, symbol, horizon, global_result, data_as_of, variant=variant)
        db.commit()

        final_status = "succeeded" if failed == 0 else ("partial" if refreshed > 0 else "failed")
        return {
            "symbol": symbol,
            "horizon": horizon,
            "variant": variant,
            "status": final_status,
            "refreshed_categories": refreshed,
            "failed_categories": failed,
            "elapsed": round(time.monotonic() - started, 2),
            "mode": "representatives_refresh",
        }
    except Exception as exc:
        logger.exception("WFO refresh error: %s/%s/%s: %s", symbol, horizon, variant, exc)
        return {
            "symbol": symbol,
            "horizon": horizon,
            "variant": variant,
            "status": "failed",
            "error": str(exc),
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _upsert_summary(
    db: Session,
    symbol: str,
    category: str,
    horizon: str,
    *,
    variant: str = "expanded",
    status: str,
    result=None,
    data_as_of=None,
    error_message: str | None = None,
    folds_json: list[dict] | None = None,
    config_json: dict | None = None,
    fragility_json: dict | None = None,
) -> None:
    row = (
        db.query(WfoSignalSummary)
        .filter_by(symbol=symbol, category=category, horizon=horizon, variant=variant)
        .first()
    )
    if row is None:
        row = WfoSignalSummary(symbol=symbol, category=category, horizon=horizon, variant=variant)
        db.add(row)

    row.status        = status
    row.error_message = error_message
    row.config_json   = config_json

    if result is not None and status == "succeeded":
        row.score_pct           = result.score_pct
        row.signal_label        = result.signal_label
        row.representatives_json = result.representatives
        row.folds_json          = folds_json
        row.fragility_json      = fragility_json
        row.wfe_pct             = result.wfe_pct
        row.robustness_ratio    = result.robustness_ratio
        row.total_folds         = result.total_folds
        row.profitable_folds    = result.profitable_folds
        row.mean_oos_sharpe     = result.mean_oos_sharpe
        row.total_oos_pnl       = result.total_oos_pnl
        row.worst_fold_drawdown = result.worst_fold_drawdown
        row.composite_score     = result.composite_score
        row.robustness_grade    = result.robustness_grade
        row.computed_at         = datetime.now(timezone.utc)
        row.data_as_of          = data_as_of
        row.compute_seconds     = result.compute_seconds


def _variant_from_rep(rep: dict[str, Any]) -> VariantDef:
    family = str(rep.get("family") or "").strip()
    variant_id = str(rep.get("variant_id") or "").strip()
    archetype = str(rep.get("archetype") or "").strip()
    if not family or not variant_id or not archetype:
        raise ValueError("Representative missing required keys: family, variant_id, archetype.")
    return VariantDef(
        variant_id=variant_id,
        family=family,
        archetype=archetype,
        params=dict(rep.get("params") or {}),
        description=str(rep.get("description") or ""),
    )


def _upsert_global(
    db: Session,
    symbol: str,
    horizon: str,
    result,
    data_as_of,
    *,
    variant: str = "expanded",
) -> None:
    row = (
        db.query(WfoGlobalSignal)
        .filter_by(symbol=symbol, horizon=horizon, variant=variant)
        .first()
    )
    if row is None:
        row = WfoGlobalSignal(symbol=symbol, horizon=horizon, variant=variant)
        db.add(row)

    row.status               = result.status
    row.global_score_pct     = result.global_score_pct
    row.raw_score_pct        = result.raw_score_pct
    row.signal_label         = result.signal_label
    row.recommendation       = result.recommendation
    row.weight_tendance      = result.weights.get("tendance",    0.0)
    row.weight_momentum      = result.weights.get("momentum",    0.0)
    row.weight_oscillation   = result.weights.get("oscillation", 0.0)
    row.weight_volume        = result.weights.get("volume",      0.0)
    row.sr_modifier          = result.sr_modifier
    row.sr_support_level     = result.sr_support
    row.sr_resistance_level  = result.sr_resistance
    row.sr_support_method    = result.sr_support_method
    row.sr_resistance_method = result.sr_resistance_method
    row.best_category        = result.best_category
    row.best_category_score  = result.best_category_score
    row.categories_viable    = result.categories_viable
    row.consensus_wfe_pct    = result.consensus_wfe_pct
    row.consensus_robustness = result.consensus_robustness
    row.computed_at          = datetime.now(timezone.utc)
    row.data_as_of           = data_as_of


# ---------------------------------------------------------------------------
# S/R level extraction
# ---------------------------------------------------------------------------

def _get_sr_levels(close, high, low, volume, horizon):
    """Get S/R levels from the existing detection system.

    Returns (support, resistance, support_method, resistance_method, atr).
    """
    from core.quant_core.strategy_plan.levels import (
        compute_atr,
        detect_swing_levels,
        compute_pivot_points,
    )

    atr_arr = compute_atr(high, low, close, window=20) if (high is not None and low is not None) else None
    atr = float(atr_arr[-1]) if (atr_arr is not None and len(atr_arr) > 0) else 0.0

    # Primary: swing levels
    if high is not None and low is not None:
        try:
            swing = detect_swing_levels(close, high, low, lookback=120, left_bars=3, right_bars=3)
            support    = swing.get("support")
            resistance = swing.get("resistance")
            if support is not None or resistance is not None:
                return support, resistance, "swing_levels", "swing_levels", atr
        except Exception:
            pass

    # Fallback: pivot points
    if high is not None and low is not None:
        try:
            pivots = compute_pivot_points(high, low, close)
            return pivots.get("s1"), pivots.get("r1"), "pivot_points", "pivot_points", atr
        except Exception:
            pass

    return None, None, None, None, atr
