"""Signal engine persistence and trigger endpoints: persisted-summaries, regime-consensus, zone-chart, triggers, engine/result."""
from __future__ import annotations

import time
import uuid
from typing import Any

import numpy as np
import pandas as pd

from pydantic import BaseModel as _BaseModel
from typing import Optional as _Optional

from fastapi import Depends, HTTPException, Query
from redis.exceptions import RedisError
from sqlalchemy.orm import Session

from ...auth import rate_limit_trigger, require_admin
from ...db import get_db
from ...schemas.strategy_signals import (
    PersistedSignalEngineSummariesRequest,
    RegimeConsensusRequest,
    SignalZoneChartRequest,
)
from ...services.signal_engine_persistence import resolve_signal_engine_result
from core.quant_core.signal_engine.domain import (
    ALL_FAMILIES,
    CATEGORY_FAMILIES,
    EnsemblePipelineDetail,
    FAMILY_SIGNAL_TYPE,
    HORIZON_PARAMS,
    VARIANT_FAMILIES,
    VariantDef,
    label_to_signal_value,
    signal_type_label,
    variant_signal_label,
)
from core.quant_core.signal_engine.ensemble import (
    run_family_ensemble_full,
    compute_family_score_timeseries,
    family_signal_is_available,
)
from core.quant_core.signal_engine.modes import (
    ALL_SIGNAL_MODE_NAMES,
    resolve_signal_mode,
    signal_mode_read_names,
    signal_mode_storage_name,
)
from core.quant_core.signal_engine.regime import validate_regime_oos, compute_regime_consensus
from core.quant_core.signal_engine.ta_combo import factor_condition_to_dict
from core.quant_core.signal_engine.variant_detail import _compute_indicator
from core.quant_core.signal_engine.oos_eval import compute_signal_array
from core.quant_core.horizons import canonical_horizon, LEGACY_HORIZON_ALIASES
from core.quant_core.data import drop_incomplete_ohlcv_rows
from ...market_data_loader import format_ohlcv_timestamp, load_close_for_symbol, load_ohlcv_for_symbol
from ._shared import (
    logger,
    router,
    CanonicalHorizon,
    _VOLUME_DEPENDENT,
    _HIGH_LOW_DEPENDENT,
    _require_canonical_signal_horizon,
    _truncate_for_horizon,
    _clean_ohlcv,
    _validate_volume_data,
    _require_high_low,
    _variant_label,
    _get_or_compute,
    _safe_float,
    _safe_float_list,
)

@router.post("/engine/persisted-summaries", summary="Get persisted signal engine summaries for multiple symbols")
def persisted_signal_engine_summaries(
    body: PersistedSignalEngineSummariesRequest,
    db: Session = Depends(get_db),
):
    """Return sidebar-ready persisted Signal Engine summaries.

    Unlike /signal/batch-scores, this endpoint never recomputes from ALL_FAMILIES.
    It mirrors the saved signal-engine page state for the requested variant.
    """
    from ...models import MarketDataStore, SignalEngineGlobalResult

    symbols = [symbol.strip().upper() for symbol in body.symbols if symbol and symbol.strip()]
    if not symbols:
        return []

    symbol_set = set(symbols)
    global_rows = [
        row
        for row in db.query(SignalEngineGlobalResult)
        .filter_by(horizon=body.horizon, variant=body.variant)
        .all()
        if row.symbol in symbol_set
    ]
    market_rows = [
        row
        for row in db.query(MarketDataStore)
        .filter_by(timeframe=body.timeframe)
        .all()
        if row.symbol in symbol_set
    ]
    global_by_symbol = {row.symbol: row for row in global_rows}
    market_as_of_by_symbol = {row.symbol: row.data_as_of for row in market_rows}

    results: list[dict[str, Any]] = []
    for symbol in symbols:
        row = global_by_symbol.get(symbol)
        market_data_as_of = market_as_of_by_symbol.get(symbol)
        score = None
        label = None
        data_as_of = None
        computed_at = None
        is_stale = False

        if row is not None:
            score = (
                row.aggregate_score_pct
                if body.variant == "legacy"
                else row.expanded_aggregate_score_pct
            )
            label = row.signal_label
            data_as_of = row.data_as_of.isoformat() if row.data_as_of else None
            computed_at = row.computed_at.isoformat() if row.computed_at else None
            is_stale = bool(
                row.data_as_of
                and market_data_as_of
                and row.data_as_of < market_data_as_of
            )

        results.append(
            {
                "symbol": symbol,
                "aggregate_score_pct": score,
                "aggregate_signal_label": label,
                "data_as_of": data_as_of,
                "market_data_as_of": market_data_as_of.isoformat() if market_data_as_of else None,
                "computed_at": computed_at,
                "is_stale": is_stale,
            }
        )

    # Best-effort: auto-enqueue a lightweight refresh for any stale signal that has no active job.
    if any(r["is_stale"] for r in results):
        try:
            from ...models import SignalEngineBatchJob
            from services.worker.tasks.signal_enqueue import enqueue_signal_engine_refresh_for_symbol
            for r in results:
                if not r["is_stale"]:
                    continue
                already_active = (
                    db.query(SignalEngineBatchJob)
                    .filter(
                        SignalEngineBatchJob.symbol == r["symbol"],
                        SignalEngineBatchJob.horizon == body.horizon,
                        SignalEngineBatchJob.variant == body.variant,
                        SignalEngineBatchJob.job_type == "signal_engine",
                        SignalEngineBatchJob.status.in_(["queued", "running", "pending"]),
                    )
                    .first()
                )
                if not already_active:
                    enqueue_signal_engine_refresh_for_symbol(
                        r["symbol"], body.horizon, variant=body.variant, triggered_by="auto_stale"
                    )
        except Exception:
            pass

    return results


# ---------------------------------------------------------------------------
# Layer H — Regime-aware consensus
# ---------------------------------------------------------------------------

_REGIME_CACHE: dict[tuple, tuple[float, dict]] = {}
_REGIME_CACHE_TTL = 600.0  # 10 minutes
_REGIME_CONSENSUS_ENABLED = True


@router.post("/signal/regime-consensus")
def regime_consensus(body: RegimeConsensusRequest, db: Session = Depends(get_db)):
    """Return regime-aware consensus: Kaufman ER detection + OOS-validated weights.

    Layer H: runs AFTER per-family A→G pipelines.
    If regime weighting beats equal-weight OOS → regime-weighted consensus.
    Otherwise → transparent equal-weight fallback.
    """
    if not _REGIME_CONSENSUS_ENABLED:
        raise HTTPException(status_code=404, detail="Regime-aware consensus is currently disabled.")

    cache_key = (body.symbol, body.horizon, body.timeframe, body.cost_bps, body.cooldown_bars)
    now = time.monotonic()
    cached = _REGIME_CACHE.get(cache_key)
    if cached and (now - cached[0]) < _REGIME_CACHE_TTL:
        return cached[1]

    # 1. Compute all family ensembles (each individually cached at 5min TTL)
    family_scores: dict[str, float] = {}
    family_details: dict[str, EnsemblePipelineDetail] = {}
    for family in ALL_FAMILIES:
        try:
            detail = _get_or_compute(
                db, family, body.symbol, body.horizon, body.timeframe,
                body.cost_bps, body.cooldown_bars, variant=body.variant,
            )
            if not family_signal_is_available(detail.signal):
                continue
            family_scores[family] = detail.signal.family_score_pct
            family_details[family] = detail
        except HTTPException:
            pass  # skip unavailable families

    if not family_scores:
        return {
            "symbol": body.symbol,
            "final_consensus": None,
            "family_weights": {},
            "per_family": {},
            "regime_active": False,
            "regime_label": "insufficient_data",
            "er_value": None,
            "improvement": 0.0,
            "tercile_bounds": [0.33, 0.67],
            "equal_consensus": None,
            "n_families": 0,
            "window_results": [],
            "n_folds": 0,
            "folds_regime_wins": 0,
            "top_variants": {},
        }

    # 2. Load OHLCV for signal array computation
    try:
        ohlcv = load_ohlcv_for_symbol(db, body.symbol, body.timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    ohlcv = _truncate_for_horizon(ohlcv, body.horizon)
    ohlcv = _clean_ohlcv(ohlcv)
    close = ohlcv["Close"].values.astype("float64")
    volume = ohlcv["Volume"].values.astype("float64") if "Volume" in ohlcv.columns else None
    high = ohlcv["High"].values.astype("float64") if "High" in ohlcv.columns else None
    low = ohlcv["Low"].values.astype("float64") if "Low" in ohlcv.columns else None

    # 3. Extract top variant per family (highest reliability) and compute signal arrays
    family_signals: dict[str, np.ndarray] = {}
    for family, detail in family_details.items():
        if not detail.all_summaries:
            continue
        top_variant = max(detail.all_summaries, key=lambda s: s.reliability_score).variant
        try:
            sig = compute_signal_array(close, top_variant, volume=volume, high=high, low=low)
            family_signals[family] = sig
        except Exception as exc:
            logger.warning("Failed to compute signal array for %s/%s: %s", body.symbol, family, exc)

    # 4. Run OOS regime validation
    regime_result = validate_regime_oos(
        close, family_signals, body.horizon, body.cost_bps,
    )

    # 5. Compute regime consensus
    consensus = compute_regime_consensus(family_scores, regime_result)

    # 6. Enrich window_results with date strings
    idx = ohlcv.index
    enriched_windows: list[dict[str, Any]] = []
    for wr in regime_result.window_results:
        ew = dict(wr)
        ts, te = wr["test_start"], wr["test_end"]
        trs = wr["train_start"]
        if trs < len(idx):
            ew["train_start_date"] = str(idx[trs])[:10]
        if wr["train_end"] < len(idx):
            ew["train_end_date"] = str(idx[wr["train_end"] - 1])[:10]
        if ts < len(idx):
            ew["test_start_date"] = str(idx[ts])[:10]
        if te < len(idx):
            ew["test_end_date"] = str(idx[min(te, len(idx) - 1)])[:10]
        # Compute delta for easy display
        ew["delta"] = round(wr["regime_sharpe"] - wr["equal_sharpe"], 4)
        enriched_windows.append(ew)

    # 7. Equal-weight consensus for comparison
    n_avail = len(family_scores)
    equal_consensus = round(sum(family_scores.values()) / n_avail, 2) if n_avail > 0 else None

    # 8. Top variant info per family (what was used for regime validation)
    top_variants: dict[str, dict[str, Any]] = {}
    for family, detail in family_details.items():
        if not detail.all_summaries:
            continue
        top = max(detail.all_summaries, key=lambda s: s.reliability_score)
        top_variants[family] = {
            "variant_id": top.variant.variant_id,
            "archetype": top.variant.archetype,
            "params": top.variant.params,
            "reliability_score": round(top.reliability_score, 4),
            "label": _variant_label(top.variant),
        }

    # 9. Compute win rate across folds
    n_folds = len(enriched_windows)
    folds_regime_wins = sum(1 for w in enriched_windows if w.get("delta", 0) > 0)

    response = {
        "symbol": body.symbol,
        **consensus,
        "tercile_bounds": list(consensus.get("tercile_bounds", (0.33, 0.67))),
        "equal_consensus": equal_consensus,
        "n_families": regime_result.n_families,
        "window_results": enriched_windows,
        "n_folds": n_folds,
        "folds_regime_wins": folds_regime_wins,
        "top_variants": top_variants,
    }

    _REGIME_CACHE[cache_key] = (now, response)
    return response


# ---------------------------------------------------------------------------
# Signal zone chart — per-bar family consensus presentation
# ---------------------------------------------------------------------------

def _detect_macd_crossovers(macd_line: list, signal_line: list) -> list[dict]:
    """Detect MACD / signal-line crossover bar indices."""
    crossovers: list[dict] = []
    for i in range(1, len(macd_line)):
        prev_m, curr_m = macd_line[i - 1], macd_line[i]
        prev_s, curr_s = signal_line[i - 1], signal_line[i]
        if prev_m is None or curr_m is None or prev_s is None or curr_s is None:
            continue
        prev_diff = prev_m - prev_s
        curr_diff = curr_m - curr_s
        if prev_diff <= 0 < curr_diff:
            crossovers.append({"bar_index": i, "direction": "bullish"})
        elif prev_diff >= 0 > curr_diff:
            crossovers.append({"bar_index": i, "direction": "bearish"})
    return crossovers


def _compute_obv_bar_signals(obv: list, ema_vals: list) -> list[str]:
    """Per-bar accumulation / distribution / neutral classification."""
    signals: list[str] = []
    for i in range(len(obv)):
        o, e = obv[i], ema_vals[i]
        if o is None or e is None:
            signals.append("neutral")
        elif o > e:
            signals.append("accumulation")
        elif o < e:
            signals.append("distribution")
        else:
            signals.append("neutral")
    return signals


def _get_all_representative_indicators(
    detail: EnsemblePipelineDetail,
    close: np.ndarray,
    volume: np.ndarray | None,
    high: np.ndarray | None,
    low: np.ndarray | None,
) -> list[dict]:
    """Representative entries enriched with per-variant indicator data."""
    reps = [
        s for s in detail.all_summaries
        if s.variant.variant_id in detail.representative_ids
    ]
    if not reps:
        reps = [
            s for s in detail.all_summaries
            if s.variant.variant_id in detail.fallback_variant_ids
        ]

    result: list[dict] = []
    for s in reps:
        entry: dict = {
            "variant_id": s.variant.variant_id,
            "weight": round(s.reliability_score, 4),
            "label": _variant_label(s.variant),
        }

        ind = _compute_indicator(close, s.variant, volume=volume, high=high, low=low)
        if ind["type"] == "none":
            entry["indicator"] = None
        else:
            ind_serialized: dict = {"type": ind["type"], "name": ind.get("name", "")}
            for key, val in ind.items():
                if key in ("type", "name"):
                    continue
                if isinstance(val, np.ndarray):
                    ind_serialized[key] = _safe_float_list(val)
                else:
                    ind_serialized[key] = val

            if "macd_line" in ind_serialized and "signal_line" in ind_serialized:
                ind_serialized["crossovers"] = _detect_macd_crossovers(
                    ind_serialized["macd_line"], ind_serialized["signal_line"],
                )
            if "obv" in ind_serialized and "ema_values" in ind_serialized:
                ind_serialized["bar_signals"] = _compute_obv_bar_signals(
                    ind_serialized["obv"], ind_serialized["ema_values"],
                )

            entry["indicator"] = ind_serialized

        result.append(entry)
    return result


def _get_top_representative_indicator(
    detail: EnsemblePipelineDetail,
    close: np.ndarray,
    volume: np.ndarray | None,
    high: np.ndarray | None,
    low: np.ndarray | None,
) -> dict | None:
    """Indicator overlay data from the top representative variant."""
    reps = [
        s for s in detail.all_summaries
        if s.variant.variant_id in detail.representative_ids
    ]
    if not reps:
        reps = [
            s for s in detail.all_summaries
            if s.variant.variant_id in detail.fallback_variant_ids
        ]
    if not reps:
        return None

    top = max(reps, key=lambda s: s.reliability_score)
    ind = _compute_indicator(close, top.variant, volume=volume, high=high, low=low)
    if ind["type"] == "none":
        return None

    result: dict = {"type": ind["type"], "name": ind.get("name", "")}
    for key, val in ind.items():
        if key in ("type", "name"):
            continue
        if isinstance(val, np.ndarray):
            result[key] = _safe_float_list(val)
        else:
            result[key] = val
    return result


def _get_representatives_info(detail: EnsemblePipelineDetail) -> list[dict]:
    """Representative variant labels and weights."""
    reps = [
        s for s in detail.all_summaries
        if s.variant.variant_id in detail.representative_ids
    ]
    if not reps:
        reps = [
            s for s in detail.all_summaries
            if s.variant.variant_id in detail.fallback_variant_ids
        ]
    return [
        {
            "variant_id": s.variant.variant_id,
            "weight": round(s.reliability_score, 4),
            "label": _variant_label(s.variant),
        }
        for s in reps
    ]


@router.post("/signal/zone-chart")
def signal_zone_chart(body: SignalZoneChartRequest, db: Session = Depends(get_db)):
    """Per-bar family consensus with representative overlays for chart rendering."""
    try:
        ohlcv = load_ohlcv_for_symbol(db, body.symbol, body.timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    ohlcv = _truncate_for_horizon(ohlcv, body.horizon)
    ohlcv = _clean_ohlcv(ohlcv)

    if len(ohlcv) == 0:
        raise HTTPException(status_code=422, detail=f"No OHLCV data for {body.symbol}")

    close = ohlcv["Close"].values.astype("float64")
    volume = (
        ohlcv["Volume"].values.astype("float64")
        if "Volume" in ohlcv.columns
        else None
    )
    high = ohlcv["High"].values.astype("float64") if "High" in ohlcv.columns else None
    low = ohlcv["Low"].values.astype("float64") if "Low" in ohlcv.columns else None
    dates = [str(d)[:10] for d in ohlcv.index]

    # Format OHLCV bars
    bars: list[dict] = []
    has_volume = "Volume" in ohlcv.columns
    for i, d in enumerate(dates):
        bars.append({
            "date": d,
            "open": _safe_float(ohlcv["Open"].iloc[i]),
            "high": _safe_float(ohlcv["High"].iloc[i]),
            "low": _safe_float(ohlcv["Low"].iloc[i]),
            "close": _safe_float(ohlcv["Close"].iloc[i]),
            "volume": _safe_float(ohlcv["Volume"].iloc[i]) if has_volume else None,
        })

    # Per-family signal computation
    families: dict[str, dict] = {}

    for fam in body.enabled_families:
        try:
            detail = _get_or_compute(
                db, fam, body.symbol, body.horizon,
                body.timeframe, body.cost_bps, body.cooldown_bars,
                variant=body.variant,
            )
        except HTTPException:
            continue  # skip family if data insufficient (e.g. OBV without volume)

        scores = compute_family_score_timeseries(
            detail,
            close,
            volume=volume,
            high=high,
            low=low,
            cooldown_bars=body.cooldown_bars,
            family_history_mode=body.family_history_mode,
            symbol=body.symbol,
            horizon=body.horizon,
            timeframe=body.timeframe,
            signal_cost_bps=body.cost_bps,
        )

        families[fam] = {
            "scores": [round(float(s), 2) for s in scores],
            "representatives": _get_all_representative_indicators(detail, close, volume, high, low),
            "indicator": _get_top_representative_indicator(detail, close, volume, high, low),
        }

    return {
        "symbol": body.symbol,
        "horizon": body.horizon,
        "bars": bars,
        "families": families,
    }


# ---------------------------------------------------------------------------
# Signal Engine Persistence API — added 2026-04-20
# ---------------------------------------------------------------------------

from pydantic import BaseModel as _BaseModel
from typing import Optional as _Optional


class _TriggerBody(_BaseModel):
    symbol: str
    horizon: CanonicalHorizon
    variant: str = "expanded"
    triggered_by: str = "manual"


class _BacktestTriggerBody(_BaseModel):
    symbol: str
    horizon: CanonicalHorizon
    variant: str = "expanded"
    window_start: str = "2026-01-01"
    window_end: _Optional[str] = None
    cooldown_bars: _Optional[int] = None
    mc_config: _Optional[dict] = None
    triggered_by: str = "manual"


class _TriggerAllBody(_BaseModel):
    variants: list[str] = list(ALL_SIGNAL_MODE_NAMES)


@router.post(
    "/engine/trigger",
    summary="Trigger signal engine batch for one symbol/horizon",
    dependencies=[Depends(rate_limit_trigger)],
)
def trigger_signal_engine(body: _TriggerBody, db: Session = Depends(get_db)):
    """Enqueue computation of A→G engine results for (symbol, horizon).

    Returns the RQ job_id. Results are persisted to signal_engine_family_result
    and signal_engine_global_result.
    """
    from services.worker.tasks.signal_enqueue import enqueue_signal_engine_for_symbol

    try:
        horizon = _require_canonical_signal_horizon(body.horizon)
        mode = resolve_signal_mode(body.variant)
        variant = mode.name
        if mode.is_factor_x_ta:
            from services.api.app.queue import _get_macro_ingest_queue
            from services.worker.tasks.factor_x_ta_batch import enqueue_factor_x_ta_for_symbol
            from services.worker.tasks.wfo_factor_x_ta_batch import enqueue_wfo_factor_x_ta_for_symbol

            q = _get_macro_ingest_queue()
            fs_job = q.enqueue(
                "services.worker.tasks.factor_selection_full.run_factor_selection_for_symbol",
                body.symbol,
                False,
                job_timeout=3600,
            )
            engine_job_id = enqueue_factor_x_ta_for_symbol(
                body.symbol,
                horizon,
                variant=variant,
                triggered_by=body.triggered_by,
                depends_on=fs_job.id,
            )
            wfo_job_id = enqueue_wfo_factor_x_ta_for_symbol(
                body.symbol,
                horizon,
                variant=variant,
                triggered_by=body.triggered_by,
                depends_on=fs_job.id,
            )
            return {
                "job_id": engine_job_id,
                "factor_selection_job_id": fs_job.id,
                "engine_job_id": engine_job_id,
                "wfo_job_id": wfo_job_id,
                "status": "queued",
            }

        job_id = enqueue_signal_engine_for_symbol(
            body.symbol, horizon,
            variant=variant,
            triggered_by=body.triggered_by,
        )
        return {"job_id": job_id, "status": "queued"}
    except RedisError as exc:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/engine/trigger-all",
    summary="Trigger signal engine batch for all data-backed symbols/horizons",
    dependencies=[Depends(require_admin), Depends(rate_limit_trigger)],
)
def trigger_all_signal_engine(body: _TriggerAllBody, db: Session = Depends(get_db)):
    """Fan out signal-engine jobs for every data-backed symbol x horizon x variant."""
    from services.api.app.queue import _get_macro_ingest_queue
    from services.api.app.services.market_universe import list_signal_universe_symbols
    from services.worker.tasks.signal_enqueue import enqueue_signal_engine_for_symbol

    horizons: list[CanonicalHorizon] = ["weekly", "monthly", "quarterly"]
    batch_id = uuid.uuid4().hex

    variants: list[str] = []
    for raw in body.variants or list(ALL_SIGNAL_MODE_NAMES):
        value = str(raw or "").strip().lower()
        if not value:
            continue
        try:
            normalized = signal_mode_storage_name(value)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if normalized not in variants:
            variants.append(normalized)
    if not variants:
        variants = list(ALL_SIGNAL_MODE_NAMES)

    symbols = list_signal_universe_symbols(db)

    total_jobs = 0
    factor_selection_jobs: dict[str, str] = {}
    try:
        if any(resolve_signal_mode(variant).is_factor_x_ta for variant in variants):
            factor_queue = _get_macro_ingest_queue()
            for symbol in symbols:
                job = factor_queue.enqueue(
                    "services.worker.tasks.factor_selection_full.run_factor_selection_for_symbol",
                    symbol,
                    False,
                    job_timeout=3600,
                )
                factor_selection_jobs[symbol] = str(job.id)

        for symbol in symbols:
            for horizon in horizons:
                for variant in variants:
                    mode = resolve_signal_mode(variant)
                    enqueue_signal_engine_for_symbol(
                        symbol,
                        horizon,
                        variant=variant,
                        triggered_by="manual_global",
                        batch_id=batch_id,
                        depends_on=factor_selection_jobs.get(symbol) if mode.is_factor_x_ta else None,
                    )
                    total_jobs += 1
    except RedisError as exc:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "batch_id": batch_id,
        "total_jobs": total_jobs,
        "symbols": len(symbols),
        "horizons": horizons,
        "variants": variants,
        "factor_selection_jobs": len(factor_selection_jobs),
    }


@router.post(
    "/backtest-mc/trigger",
    summary="Trigger signal backtest + MC for one symbol/horizon",
    dependencies=[Depends(rate_limit_trigger)],
)
def trigger_signal_backtest(body: _BacktestTriggerBody, db: Session = Depends(get_db)):
    """Enqueue signal-based backtest + Monte Carlo computation.

    Results are persisted to signal_backtest_run. Use GET /signal/backtest-mc
    to read results once the job completes.
    """
    from services.worker.tasks.signal_enqueue import enqueue_signal_backtest_for_symbol

    try:
        horizon = _require_canonical_signal_horizon(body.horizon)
        mc_config = dict(body.mc_config or {})
        raw_cooldown = body.cooldown_bars
        if raw_cooldown is None:
            raw_cooldown = mc_config.get("cooldown_bars", 0)
        mc_config["cooldown_bars"] = min(252, max(0, int(raw_cooldown or 0)))
        job_id = enqueue_signal_backtest_for_symbol(
            body.symbol, horizon,
            variant=body.variant,
            window_start=body.window_start,
            window_end=body.window_end,
            mc_config=mc_config,
            triggered_by=body.triggered_by,
        )
        return {"job_id": job_id, "status": "queued"}
    except RedisError as exc:
        raise HTTPException(status_code=503, detail=f"Redis unavailable: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/engine/result", summary="Get persisted signal engine results for one symbol/horizon")
def get_signal_engine_result(
    symbol: str,
    horizon: CanonicalHorizon,
    variant: str = "expanded",
    cooldown_bars: int = 0,
    db: Session = Depends(get_db),
):
    """Return persisted Signal Engine state for this tuple without mutating it."""
    try:
        horizon = _require_canonical_signal_horizon(horizon)
        return resolve_signal_engine_result(
            db,
            symbol=symbol,
            horizon=horizon,
            variant=variant,
            cooldown_bars=max(0, int(cooldown_bars)),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to resolve signal engine result for %s/%s/%s", symbol, horizon, variant)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


