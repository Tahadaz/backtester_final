from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

from core.quant_core.research.score_history import _bucket_for
from core.quant_core.signal_engine.current_signal import build_current_signal
from core.quant_core.signal_engine.domain import FAMILY_SIGNAL_TYPE, VariantDef, signal_type_label
from core.quant_core.signal_engine.modes import ALL_SIGNAL_MODE_NAMES, resolve_signal_mode
from core.quant_core.signal_engine.wfo_global import compute_global_wfo_signal
from core.quant_core.signal_engine.wfo_signal import WfoCategoryResult

from .. import models
from ..market_data_loader import load_ohlcv_for_symbol
from ..market_refresh_window import bourse_session_status
from .bourse_live_quotes import (
    DEFAULT_MAX_AGE_SECONDS,
    LiveQuoteView,
    get_or_refresh_live_quotes,
    normalize_symbols,
)
from .dashboard_builder import (
    EDGE_CANDIDATE_COUNT,
    EDGE_SIGNAL_MODES,
    EXPANDED_CATEGORY_FAMILIES,
    HORIZON_ALIASES,
    HORIZONS,
    _apply_wfo_all_oos_proof_to_edge,
    _best_signal_rank,
    _bucket_to_signal_label,
    _build_best_technical_signal_payload,
    _build_classic_technical_signal_payload_from_ohlcv,
    _build_technical_signal_candidate,
    _category_scores_from_family_payload,
    _direction_from_score,
    _round,
    _score_to_label,
    _signal_method_label,
    _safe_float,
)
from .signal_engine_persistence import (
    DEFAULT_COOLDOWN_BARS,
    _expected_families,
    _family_to_category_map,
    _refresh_representatives_for_family,
    _representative_payload_is_valid,
)

logger = logging.getLogger(__name__)


def _normalize_horizon(raw: str) -> str:
    token = str(raw or "").strip().lower()
    normalized = HORIZON_ALIASES.get(token, token)
    if normalized not in HORIZONS:
        raise ValueError("Invalid horizon")
    return normalized


def _quote_payload(quote: LiveQuoteView | None) -> dict[str, Any] | None:
    if quote is None:
        return None
    return {
        "symbol": quote.symbol,
        "session_date": quote.session_date,
        "quote_timestamp": quote.quote_timestamp,
        "open_price": quote.open_price,
        "last_price": quote.last_price,
        "high_price": quote.high_price,
        "low_price": quote.low_price,
        "prev_close": quote.prev_close,
        "volume": quote.volume,
        "source_provider": quote.source_provider,
        "source_url": quote.source_url,
        "updated_at": quote.updated_at,
        "is_fresh": quote.is_fresh,
        "age_seconds": quote.age_seconds,
    }


def _variation_pct(end_price: float | None, start_price: float | None) -> float | None:
    if end_price is None or start_price in (None, 0):
        return None
    try:
        return round(((float(end_price) / float(start_price)) - 1.0) * 100.0, 2)
    except Exception:
        return None


def _period_payload(
    *,
    start_price: Any,
    end_price: Any,
    start_date: Any,
    end_date: Any,
    source: str = "live_quote",
) -> dict[str, Any]:
    return {
        "pct": _variation_pct(_safe_float(end_price), _safe_float(start_price)),
        "start_price": _safe_float(start_price),
        "end_price": _safe_float(end_price),
        "start_date": str(start_date) if start_date is not None else None,
        "end_date": str(end_date) if end_date is not None else None,
        "source": source,
    }


def _standardize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index, errors="coerce")
        out = out[out.index.notna()]

    rename_map: dict[str, str] = {}
    for target, candidates in {
        "Open": ("Open", "open"),
        "High": ("High", "high"),
        "Low": ("Low", "low"),
        "Close": ("Close", "close", "Adj Close", "AdjClose", "adj_close", "Price", "price"),
        "Volume": ("Volume", "volume", "Vol", "vol"),
    }.items():
        for candidate in candidates:
            if candidate in out.columns:
                rename_map[candidate] = target
                break
    if rename_map:
        out = out.rename(columns=rename_map)
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").replace([np.inf, -np.inf], np.nan)
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out


def _session_timestamp(frame: pd.DataFrame, quote: LiveQuoteView) -> pd.Timestamp | None:
    if quote.session_date is None:
        return None
    ts = pd.Timestamp(quote.session_date)
    tz = getattr(frame.index, "tz", None)
    if tz is not None and ts.tzinfo is None:
        ts = ts.tz_localize(tz)
    return ts


def _with_live_bar(frame: pd.DataFrame, quote: LiveQuoteView) -> tuple[pd.DataFrame | None, list[str]]:
    warnings: list[str] = []
    if quote.last_price is None or quote.last_price == 0:
        return None, ["missing_live_last_price"]

    out = _standardize_ohlcv(frame)
    if out.empty or "Close" not in out.columns:
        return None, ["missing_official_ohlcv"]

    session_ts = _session_timestamp(out, quote)
    if session_ts is None:
        return None, ["missing_live_session_date"]

    latest_ts = out.index[-1]
    latest_day = pd.Timestamp(latest_ts).date()
    if quote.session_date is not None and quote.session_date < latest_day:
        return None, ["live_quote_session_older_than_official_data"]

    base = out.iloc[-1].copy()
    same_day_mask = pd.Index([idx.date() for idx in out.index]) == quote.session_date
    if bool(same_day_mask.any()):
        base = out.loc[same_day_mask].iloc[-1].copy()

    last_price = float(quote.last_price)
    open_price = _safe_float(quote.open_price) or _safe_float(base.get("Open")) or last_price
    high_candidates = [
        _safe_float(quote.high_price),
        _safe_float(base.get("High")) if bool(same_day_mask.any()) else None,
        open_price,
        last_price,
    ]
    low_candidates = [
        _safe_float(quote.low_price),
        _safe_float(base.get("Low")) if bool(same_day_mask.any()) else None,
        open_price,
        last_price,
    ]
    high_price = max(value for value in high_candidates if value is not None)
    low_price = min(value for value in low_candidates if value is not None)
    volume = _safe_float(quote.volume)
    if volume is None:
        volume = _safe_float(base.get("Volume")) if bool(same_day_mask.any()) else 0.0

    if "Open" not in out.columns:
        out["Open"] = out["Close"]
    if "High" not in out.columns:
        out["High"] = out["Close"]
    if "Low" not in out.columns:
        out["Low"] = out["Close"]
    if "Volume" not in out.columns:
        out["Volume"] = 0.0

    if bool(same_day_mask.any()):
        replace_idx = out.loc[same_day_mask].index[-1]
        out.loc[replace_idx, ["Open", "High", "Low", "Close", "Volume"]] = [
            open_price,
            high_price,
            low_price,
            last_price,
            volume,
        ]
    else:
        out.loc[session_ts, ["Open", "High", "Low", "Close", "Volume"]] = [
            open_price,
            high_price,
            low_price,
            last_price,
            volume,
        ]
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out, warnings


def _frame_arrays(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None, np.ndarray | None]:
    close_series = pd.to_numeric(frame["Close"], errors="coerce").replace([np.inf, -np.inf], np.nan)
    valid = close_series.notna() & (close_series != 0)
    normalized = frame.loc[valid].copy()
    close = close_series.loc[valid].to_numpy(dtype=np.float64)
    if len(close) == 0:
        raise ValueError("No finite live close values")

    volume = None
    if "Volume" in normalized.columns:
        volume = (
            pd.to_numeric(normalized["Volume"], errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0.0)
            .to_numpy(dtype=np.float64)
        )

    high = None
    if "High" in normalized.columns:
        high = (
            pd.to_numeric(normalized["High"], errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
            .fillna(pd.Series(close, index=normalized.index))
            .to_numpy(dtype=np.float64)
        )

    low = None
    if "Low" in normalized.columns:
        low = (
            pd.to_numeric(normalized["Low"], errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
            .fillna(pd.Series(close, index=normalized.index))
            .to_numpy(dtype=np.float64)
        )
    return close, volume, high, low


def _factor_dependencies_from_reps(representatives: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for rep in representatives:
        raw = rep.get("factor_condition")
        if not isinstance(raw, dict):
            continue
        key = (str(raw.get("factor_ticker") or ""), str(raw.get("condition_id") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(raw))
    return out


def _aggregate_signal_engine_family_scores(
    family_payload: dict[str, dict[str, Any]],
    variant: str,
) -> tuple[float | None, dict[str, Any]]:
    per_category = _category_scores_from_family_payload(family_payload, variant)
    scores = [
        _safe_float(payload.get("score_pct"))
        for payload in per_category.values()
        if isinstance(payload, dict)
    ]
    scores = [score for score in scores if score is not None]
    if not scores:
        return None, per_category
    return round(sum(scores) / len(scores), 2), per_category


def _signal_engine_live_candidates(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    close: np.ndarray,
    volume: np.ndarray | None,
    high: np.ndarray | None,
    low: np.ndarray | None,
) -> list[dict[str, Any] | None]:
    rows = (
        db.query(models.SignalEngineFamilyResult)
        .filter(
            models.SignalEngineFamilyResult.symbol == symbol,
            models.SignalEngineFamilyResult.horizon == horizon,
            models.SignalEngineFamilyResult.variant.in_(list(ALL_SIGNAL_MODE_NAMES)),
        )
        .all()
    )
    rows_by_key = {(str(row.variant), str(row.family)): row for row in rows}
    variants = sorted({str(row.variant) for row in rows}, key=lambda item: list(sorted(ALL_SIGNAL_MODE_NAMES)).index(item) if item in ALL_SIGNAL_MODE_NAMES else 999)

    candidates: list[dict[str, Any] | None] = []
    for variant in variants:
        family_payload: dict[str, dict[str, Any]] = {}
        factor_dependencies: dict[str, list[dict[str, Any]]] = {}
        category_by_family = _family_to_category_map(variant)

        for family in _expected_families(variant):
            row = rows_by_key.get((variant, family))
            if row is None or str(row.status or "").lower() != "succeeded":
                continue
            reps_src = [
                rep
                for rep in (row.representatives_json or [])
                if _representative_payload_is_valid(rep)
            ]
            if not reps_src:
                continue
            try:
                score_pct, label, refreshed_reps = _refresh_representatives_for_family(
                    family=family,
                    reps_src=reps_src,
                    close=close,
                    volume=volume,
                    high=high,
                    low=low,
                    cooldown_bars=DEFAULT_COOLDOWN_BARS,
                )
            except Exception:
                logger.debug(
                    "live signal-engine family refresh failed",
                    extra={"symbol": symbol, "horizon": horizon, "variant": variant, "family": family},
                    exc_info=True,
                )
                continue

            family_payload[family] = {
                "score_pct": _round(score_pct),
                "family_score_pct": _round(score_pct),
                "label": label,
                "representative_count": len(refreshed_reps),
            }
            deps = _factor_dependencies_from_reps(refreshed_reps)
            category = category_by_family.get(family)
            if category and deps:
                factor_dependencies.setdefault(category, []).extend(deps)

        score, per_category = _aggregate_signal_engine_family_scores(family_payload, variant)
        if score is None:
            continue
        candidates.append(
            _build_technical_signal_candidate(
                source="signal_engine",
                variant=variant,
                score=score,
                signal_label=_score_to_label(score),
                per_family=per_category,
                factor_dependencies=factor_dependencies,
            )
        )
    return candidates


def _variant_from_wfo_rep(rep: dict[str, Any]) -> VariantDef:
    family = str(rep.get("family") or "").strip()
    variant_id = str(rep.get("variant_id") or "").strip()
    archetype = str(rep.get("archetype") or "").strip()
    if not family or not variant_id or not archetype:
        raise ValueError("Representative missing required keys: family, variant_id, archetype.")
    params = rep.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    return VariantDef(
        variant_id=variant_id,
        family=family,
        archetype=archetype,
        params=dict(params),
        description=str(rep.get("description") or ""),
    )


def _wfo_category_live_result(
    row: models.WfoSignalSummary,
    *,
    close: np.ndarray,
    volume: np.ndarray | None,
    high: np.ndarray | None,
    low: np.ndarray | None,
) -> WfoCategoryResult | None:
    reps_src = [rep for rep in (row.representatives_json or []) if isinstance(rep, dict)]
    if not reps_src:
        return None

    refreshed_reps: list[dict[str, Any]] = []
    weighted_sum = 0.0
    total_weight = 0.0
    for rep in reps_src:
        variant_def = _variant_from_wfo_rep(rep)
        weight = _safe_float(rep.get("normalized_weight") or rep.get("reliability_weight") or 1.0) or 1.0
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
        signal = float(current.signal)
        weighted_sum += weight * signal
        total_weight += weight
        refreshed = dict(rep)
        refreshed.update(
            {
                "family": variant_def.family,
                "archetype": variant_def.archetype,
                "variant_id": variant_def.variant_id,
                "params": dict(variant_def.params),
                "description": str(rep.get("description") or variant_def.description or ""),
                "signal": signal,
                "signal_label": str(current.signal_label),
                "current_close": _safe_float(current.current_close),
                "indicator_value": _safe_float(current.indicator_value),
                "explanation": str(current.explanation or ""),
            }
        )
        refreshed_reps.append(refreshed)

    if total_weight <= 0:
        return None
    for rep in refreshed_reps:
        normalized = (_safe_float(rep.get("normalized_weight") or rep.get("reliability_weight") or 1.0) or 1.0) / total_weight
        rep["normalized_weight"] = round(normalized, 4)
        rep["contribution"] = round(normalized * float(rep.get("signal") or 0.0), 4)

    score_pct = round((weighted_sum / total_weight) * 100.0, 2)
    first_family = str(refreshed_reps[0].get("family") or EXPANDED_CATEGORY_FAMILIES.get(str(row.category), [str(row.category)])[0])
    signal_label = signal_type_label(FAMILY_SIGNAL_TYPE.get(first_family, "trend"), score_pct)

    return WfoCategoryResult(
        category=str(row.category),
        symbol=str(row.symbol),
        horizon=str(row.horizon),
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
        data_as_of=str(row.data_as_of or ""),
        compute_seconds=float(row.compute_seconds or 0.0),
    )


def _wfo_live_candidates(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    close: np.ndarray,
    volume: np.ndarray | None,
    high: np.ndarray | None,
    low: np.ndarray | None,
) -> tuple[list[dict[str, Any] | None], dict[str, float]]:
    rows = (
        db.query(models.WfoSignalSummary)
        .filter(
            models.WfoSignalSummary.symbol == symbol,
            models.WfoSignalSummary.horizon == horizon,
            models.WfoSignalSummary.variant.in_(list(EDGE_SIGNAL_MODES)),
            models.WfoSignalSummary.status == "succeeded",
        )
        .all()
    )
    rows_by_variant: dict[str, list[models.WfoSignalSummary]] = {}
    for row in rows:
        rows_by_variant.setdefault(str(row.variant), []).append(row)

    candidates: list[dict[str, Any] | None] = []
    score_by_variant: dict[str, float] = {}
    for variant in EDGE_SIGNAL_MODES:
        category_results: dict[str, WfoCategoryResult] = {}
        for row in rows_by_variant.get(variant, []):
            try:
                result = _wfo_category_live_result(row, close=close, volume=volume, high=high, low=low)
            except Exception:
                logger.debug(
                    "live WFO category refresh failed",
                    extra={"symbol": symbol, "horizon": horizon, "variant": variant, "category": row.category},
                    exc_info=True,
                )
                continue
            if result is not None:
                category_results[str(row.category)] = result
        if not category_results:
            continue

        global_result = compute_global_wfo_signal(
            category_results,
            close,
            volume=volume,
            high=high,
            low=low,
        )
        if global_result.status != "succeeded":
            continue
        score = _safe_float(global_result.raw_score_pct)
        if score is None:
            score = _safe_float(global_result.global_score_pct)
        if score is None:
            continue

        try:
            canonical_variant = resolve_signal_mode(variant).name
        except ValueError:
            canonical_variant = variant
        score_by_variant[canonical_variant] = float(score)
        per_category = {
            category: {"score_pct": _round(result.score_pct), "label": result.signal_label}
            for category, result in category_results.items()
        }
        candidates.append(
            _build_technical_signal_candidate(
                source="wfo",
                variant=canonical_variant,
                score=score,
                signal_label=global_result.signal_label or _score_to_label(score),
                per_family={c: per_category[c] for c in EXPANDED_CATEGORY_FAMILIES if c in per_category},
            )
        )
    return candidates, score_by_variant


def _live_best_signal_payload(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    live_wfo_scores: dict[str, float],
) -> dict[str, Any] | None:
    if not live_wfo_scores:
        return None
    try:
        from ..config import settings
        from ..routers.analytics import _build_edge_metrics_from_db, _edge_metrics_to_out
    except Exception:
        return None

    cost_bps = float(settings.EDGE_COST_BPS_PER_SIDE)
    best: tuple[tuple[int, float, float, float], dict[str, Any]] | None = None
    for variant, score in live_wfo_scores.items():
        try:
            bucket = _bucket_for(float(score))
            metrics = _build_edge_metrics_from_db(
                symbol=symbol,
                horizon=horizon,
                source="wfo",
                variant=variant,
                cost_bps=cost_bps,
                db=db,
                multiple_testing_count=EDGE_CANDIDATE_COUNT,
                bucket_override=bucket,
            )
            if metrics is None:
                continue
            edge = json.loads(_edge_metrics_to_out(metrics).model_dump_json())
            edge = _apply_wfo_all_oos_proof_to_edge(
                db,
                symbol=symbol,
                horizon=horizon,
                variant=variant,
                edge=edge,
                cost_bps=cost_bps,
            )
        except Exception:
            logger.debug(
                "live best-signal edge build failed",
                extra={"symbol": symbol, "horizon": horizon, "variant": variant},
                exc_info=True,
            )
            try:
                db.rollback()
            except Exception:
                pass
            continue

        rank = _best_signal_rank(edge)
        if rank is None:
            continue

        payload = {
            "source": "wfo",
            "variant": variant,
            "label": _signal_method_label("wfo", variant),
            "signal_label": _bucket_to_signal_label(edge.get("bucket")),
            "triage": "proven" if bool(edge.get("proven_edge_net")) else "watch",
            "bucket": edge.get("bucket"),
            "direction": edge.get("direction"),
            "n": edge.get("n"),
            "fwd_horizon_bars": edge.get("fwd_horizon_bars"),
            "return_calc_method": edge.get("return_calc_method"),
            "entry_price_kind": edge.get("entry_price_kind"),
            "entry_lag_bars": edge.get("entry_lag_bars"),
            "exit_price_kind": edge.get("exit_price_kind"),
            "exit_lag_bars": edge.get("exit_lag_bars"),
            "exit_timing_label": edge.get("exit_timing_label"),
            "action_expected_return_net": edge.get("action_expected_return_net"),
            "action_expected_return_net_ci_lower": edge.get("action_expected_return_net_ci_lower"),
            "action_expected_return_net_ci_upper": edge.get("action_expected_return_net_ci_upper"),
            "hit_rate": edge.get("hit_rate"),
            "hit_ci_lower": edge.get("hit_ci_lower"),
            "hit_ci_upper": edge.get("hit_ci_upper"),
            "selection_n": edge.get("selection_n"),
            "selection_window_start": edge.get("selection_window_start"),
            "selection_window_end": edge.get("selection_window_end"),
            "selection_action_expected_return_net": edge.get("selection_action_expected_return_net"),
            "selection_hit_rate": edge.get("selection_hit_rate"),
            "proof_n": edge.get("proof_n"),
            "proof_window_start": edge.get("proof_window_start"),
            "proof_window_end": edge.get("proof_window_end"),
            "proof_method": edge.get("proof_method"),
            "multiple_testing_count": edge.get("multiple_testing_count"),
            "mc_luck_pvalue_net_adj": edge.get("mc_luck_pvalue_net_adj"),
            "label_shuffle_pvalue_net_adj": edge.get("label_shuffle_pvalue_net_adj"),
            "proven_edge_gross": edge.get("proven_edge_gross"),
            "proven_edge_net": edge.get("proven_edge_net"),
            "edge_score": edge.get("edge_score"),
            "edge_score_components": edge.get("edge_score_components") if isinstance(edge.get("edge_score_components"), dict) else {},
            "score": rank[2],
            "live_adjusted": True,
            "live_score_pct": _round(score),
        }
        if best is None or rank > best[0]:
            best = (rank, payload)

    return best[1] if best is not None else None


def _live_price_payload(frame: pd.DataFrame, quote: LiveQuoteView) -> dict[str, Any]:
    last_price = _safe_float(quote.last_price)
    prev_close = _safe_float(quote.prev_close)
    if prev_close is None:
        close = pd.to_numeric(frame["Close"], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if len(close) >= 2:
            prev_close = _safe_float(close.iloc[-2])
    latest_ts = frame.index[-1] if not frame.empty else quote.session_date
    open_price = _safe_float(quote.open_price)
    if open_price is None and "Open" in frame.columns and not frame.empty:
        open_price = _safe_float(frame.iloc[-1].get("Open"))
    return {
        "last_price": last_price,
        "prev_close": prev_close,
        "var1j_pct": _variation_pct(last_price, prev_close),
        "performance": {
            "one_day": _period_payload(
                start_price=prev_close,
                end_price=last_price,
                start_date=None,
                end_date=latest_ts,
            ),
            "open_to_now": _period_payload(
                start_price=open_price,
                end_price=last_price,
                start_date=latest_ts,
                end_date=latest_ts,
            ),
        },
    }


def _json_safe(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {str(key): _json_safe(value) for key, value in payload.items()}
    if isinstance(payload, list):
        return [_json_safe(value) for value in payload]
    if isinstance(payload, tuple):
        return [_json_safe(value) for value in payload]
    if hasattr(payload, "isoformat"):
        return payload.isoformat()
    if isinstance(payload, np.generic):
        return payload.item()
    if isinstance(payload, float) and not math.isfinite(payload):
        return None
    try:
        if hasattr(payload, "__dataclass_fields__"):
            return _json_safe(asdict(payload))
    except Exception:
        pass
    return payload


def _build_symbol_overlay(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    quote: LiveQuoteView | None,
) -> dict[str, Any]:
    warnings: list[str] = []
    overlay: dict[str, Any] = {
        "symbol": symbol,
        "live_quote": _quote_payload(quote),
        "warnings": warnings,
        "live_adjusted": False,
    }
    if quote is None:
        warnings.append("missing_live_quote")
        return overlay
    if not quote.is_fresh:
        warnings.append("stale_live_quote")
    if quote.last_price is None:
        warnings.append("missing_live_last_price")
        return overlay

    try:
        official_frame = load_ohlcv_for_symbol(db, symbol, timeframe="1D")
        live_frame, frame_warnings = _with_live_bar(official_frame, quote)
        warnings.extend(frame_warnings)
    except Exception as exc:
        warnings.append(f"ohlcv_load_failed:{exc}")
        return overlay

    if live_frame is None:
        return overlay

    overlay.update(_live_price_payload(live_frame, quote))
    try:
        close, volume, high, low = _frame_arrays(live_frame)
    except Exception as exc:
        warnings.append(f"live_frame_invalid:{exc}")
        return overlay

    technical_candidates: list[dict[str, Any] | None] = []
    technical_candidates.extend(
        _signal_engine_live_candidates(
            db,
            symbol=symbol,
            horizon=horizon,
            close=close,
            volume=volume,
            high=high,
            low=low,
        )
    )
    wfo_candidates, live_wfo_scores = _wfo_live_candidates(
        db,
        symbol=symbol,
        horizon=horizon,
        close=close,
        volume=volume,
        high=high,
        low=low,
    )
    technical_candidates.extend(wfo_candidates)
    best_technical = _build_best_technical_signal_payload(technical_candidates)
    if technical_candidates or best_technical is not None:
        overlay["best_technical_signal"] = best_technical
    if best_technical is not None:
        best_technical["live_adjusted"] = True
        best_technical["live_price"] = _safe_float(quote.last_price)

    classic = _build_classic_technical_signal_payload_from_ohlcv(live_frame)
    overlay["classic_technical_signal"] = classic
    if classic is not None:
        classic["live_adjusted"] = True

    best_signal = _live_best_signal_payload(
        db,
        symbol=symbol,
        horizon=horizon,
        live_wfo_scores=live_wfo_scores,
    )
    if live_wfo_scores or best_signal is not None:
        overlay["best_signal"] = best_signal

    overlay["live_adjusted"] = any(
        overlay.get(key) is not None
        for key in ("best_signal", "best_technical_signal", "classic_technical_signal")
    )
    return overlay


def build_dashboard_live_refresh(
    db: Session,
    *,
    symbols: list[str],
    horizon: str,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
    persist_history: bool = True,
    allow_when_closed: bool = False,
) -> dict[str, Any]:
    normalized = normalize_symbols(symbols)
    if not normalized:
        raise ValueError("No symbols requested")
    horizon = _normalize_horizon(horizon)
    session = bourse_session_status()
    if not bool(session.get("is_live_session")) and not allow_when_closed:
        return _json_safe(
            {
                "market_session": session,
                "horizon": horizon,
                "max_age_seconds": int(max_age_seconds),
                "persisted_history_count": 0,
                "quotes": [],
                "missing_symbols": normalized,
                "overlays": [],
                "skipped": True,
                "reason": "market_closed",
            }
        )

    quotes = get_or_refresh_live_quotes(
        db,
        normalized,
        max_age_seconds=max_age_seconds,
        force_refresh=True,
        persist_history=persist_history,
    )

    overlays = [
        _build_symbol_overlay(db, symbol=symbol, horizon=horizon, quote=quotes.get(symbol))
        for symbol in normalized
    ]
    return _json_safe(
        {
            "market_session": session,
            "horizon": horizon,
            "max_age_seconds": int(max_age_seconds),
            "persisted_history_count": len(quotes) if persist_history else 0,
            "quotes": [_quote_payload(quotes[symbol]) for symbol in normalized if symbol in quotes],
            "missing_symbols": [symbol for symbol in normalized if symbol not in quotes],
            "overlays": overlays,
        }
    )
