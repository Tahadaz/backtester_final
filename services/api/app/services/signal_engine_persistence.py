"""Shared persisted Signal Engine compute/read service.

This module is intentionally reusable from both API request handlers (sync path)
and worker tasks (async batch path).
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

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
from core.quant_core.signal_engine.ensemble import (
    _score_to_label,
    combine_family_signals,
    family_signal_is_available,
    run_family_ensemble_full,
)
from core.quant_core.signal_engine.support_resistance import round_number
from services.api.app.market_data_loader import load_ohlcv_for_symbol
from services.api.app.models import (
    MarketDataStore,
    SignalEngineFamilyResult,
    SignalEngineGlobalResult,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEFRAME = "1D"
DEFAULT_COST_BPS = 10.0
DEFAULT_COOLDOWN_BARS = 0

_VOLUME_FAMILIES = frozenset(CATEGORY_FAMILIES.get("volume", []))


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        fv = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(fv):
        return None
    return fv


def _to_plain_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if is_dataclass(value):
        converted = asdict(value)
        return converted if isinstance(converted, dict) else {}
    return {}


def _input_hash(data_as_of: Any, cost_bps: float, cooldown_bars: int) -> str:
    raw = f"{data_as_of}|{float(cost_bps):.6f}|{int(cooldown_bars)}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _variant_family_map(variant: str) -> dict[str, list[str]]:
    normalized = str(variant or "expanded").strip().lower()
    return VARIANT_FAMILIES.get(normalized, VARIANT_FAMILIES["expanded"])


def _expected_families(variant: str) -> list[str]:
    fams = [
        fam
        for cat_families in _variant_family_map(variant).values()
        for fam in cat_families
    ]
    # Keep deterministic order while removing duplicates.
    return list(dict.fromkeys(fams))


def _family_to_category_map(variant: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for category, families in _variant_family_map(variant).items():
        for family in families:
            out[family] = category
    return out


def _check_volume(volume: np.ndarray | None) -> bool:
    if volume is None:
        return False
    finite = volume[np.isfinite(volume)]
    if len(finite) == 0:
        return False
    return bool((finite != 0).mean() >= 0.01)


def _serialize_representatives(sig: Any) -> list[dict[str, Any]]:
    reps: list[dict[str, Any]] = []
    for rep in (getattr(sig, "representatives", None) or []):
        if isinstance(rep, dict):
            entry = dict(rep)
            for numeric_key in (
                "signal",
                "reliability_weight",
                "normalized_weight",
                "contribution",
                "current_close",
                "indicator_value",
            ):
                if numeric_key in entry:
                    entry[numeric_key] = _safe_float(entry.get(numeric_key))
            reps.append(entry)
            continue

        reps.append(
            {
                "variant_id": str(getattr(rep, "variant_id", "")),
                "archetype": str(getattr(rep, "archetype", "")),
                "family": str(getattr(rep, "family", "")),
                "signal": _safe_float(getattr(rep, "signal", None)),
                "signal_label": str(getattr(rep, "signal_label", "")),
                "reliability_weight": _safe_float(getattr(rep, "reliability_weight", None)),
                "normalized_weight": _safe_float(getattr(rep, "normalized_weight", None)),
                "contribution": _safe_float(getattr(rep, "contribution", None)),
                "current_close": _safe_float(getattr(rep, "current_close", None)),
                "indicator_value": _safe_float(getattr(rep, "indicator_value", None)),
                "params": dict(getattr(rep, "params", {}) or {}),
                "selection_status": str(getattr(rep, "selection_status", "")),
                "explanation": str(getattr(rep, "explanation", "")),
                "description": str(getattr(rep, "description", "")),
            }
        )
    return reps


def _build_family_detail_json(
    *,
    family: str,
    symbol: str,
    horizon: str,
    timeframe: str,
    sig: Any,
) -> dict[str, Any]:
    reps = _serialize_representatives(sig)
    fallback_variants = []
    for rep in (getattr(sig, "fallback_variants", []) or []):
        if isinstance(rep, dict):
            fallback_variants.append(dict(rep))
    methodology_status = str(getattr(sig, "methodology_status", "robust_oos_ensemble") or "robust_oos_ensemble")
    methodology_mode = str(getattr(sig, "methodology_mode", methodology_status) or methodology_status)
    return {
        "family": family,
        "symbol": symbol,
        "horizon": horizon,
        "timeframe": timeframe,
        "family_score_pct": round(float(getattr(sig, "family_score_pct", 0.0)), 2),
        "family_signal_label": str(getattr(sig, "family_signal_label", "Pas disponible")),
        "tested_count": int(getattr(sig, "tested_count", 0) or 0),
        "viable_count": int(getattr(sig, "viable_count", 0) or 0),
        "competitive_count": int(getattr(sig, "competitive_count", 0) or 0),
        "representative_count": int(getattr(sig, "representative_count", len(reps)) or 0),
        "representatives": reps,
        "fallback_variants": fallback_variants,
        "score_explanation": str(getattr(sig, "score_explanation", "")),
        "methodology_status": methodology_status,
        "methodology_mode": methodology_mode,
        "available_bars": int(getattr(sig, "available_bars", 0) or 0),
        "nominal_window": _to_plain_dict(getattr(sig, "nominal_window", {})),
        "effective_window": _to_plain_dict(getattr(sig, "effective_window", {})),
        "warning_message": str(getattr(sig, "warning_message", "") or ""),
        "is_provisional": bool(getattr(sig, "is_provisional", False)),
        "as_of": str(getattr(sig, "as_of", "") or ""),
        "latest_close": _safe_float(getattr(sig, "latest_close", None)),
        "best_variant_id": str(getattr(sig, "best_variant_id", "") or ""),
    }


def _representative_payload_is_valid(rep: Any) -> bool:
    if not isinstance(rep, dict):
        return False
    if not str(rep.get("variant_id") or "").strip():
        return False
    if not str(rep.get("archetype") or "").strip():
        return False
    params = rep.get("params")
    if params is None:
        return True
    return isinstance(params, dict)


def _family_row_refreshable(row: SignalEngineFamilyResult | None) -> bool:
    if row is None:
        return False
    status = str(row.status or "").strip().lower()
    if status == "no_signal":
        return True
    if status != "succeeded":
        return False
    reps = row.representatives_json or []
    if not isinstance(reps, list) or len(reps) == 0:
        return False
    return all(_representative_payload_is_valid(rep) for rep in reps)


def _variant_from_rep(rep: dict[str, Any], *, fallback_family: str) -> VariantDef:
    family = str(rep.get("family") or fallback_family or "").strip()
    if not family:
        raise ValueError(f"Representative {rep.get('variant_id', '<missing>')} has no family")
    variant_id = str(rep.get("variant_id") or "").strip()
    archetype = str(rep.get("archetype") or "").strip()
    if not variant_id or not archetype:
        raise ValueError("Representative must include variant_id and archetype")
    params = rep.get("params") or {}
    if not isinstance(params, dict):
        raise ValueError(f"Representative {variant_id} has non-dict params")
    return VariantDef(
        variant_id=variant_id,
        family=family,
        archetype=archetype,
        params=dict(params),
        description=str(rep.get("description") or ""),
    )


def _upsert_family_result(
    db: Session,
    *,
    symbol: str,
    family: str,
    category: str,
    horizon: str,
    variant: str,
    status: str,
    family_score_pct: float | None = None,
    signal_label: str | None = None,
    representatives_json: list[dict[str, Any]] | None = None,
    family_detail_json: dict[str, Any] | None = None,
    tested_count: int | None = None,
    viable_count: int | None = None,
    competitive_count: int | None = None,
    representative_count: int | None = None,
    is_provisional: bool = False,
    warning_message: str | None = None,
    input_hash: str | None = None,
    computed_at: datetime | None = None,
    data_as_of: date | None = None,
    compute_seconds: float | None = None,
    error_message: str | None = None,
) -> SignalEngineFamilyResult:
    row = (
        db.query(SignalEngineFamilyResult)
        .filter_by(symbol=symbol, family=family, horizon=horizon, variant=variant)
        .first()
    )
    if row is None:
        row = SignalEngineFamilyResult(
            symbol=symbol,
            family=family,
            category=category,
            horizon=horizon,
            variant=variant,
        )
        db.add(row)

    row.category = category
    row.status = status
    row.family_score_pct = family_score_pct
    row.signal_label = signal_label
    row.representatives_json = representatives_json or []
    row.family_detail_json = family_detail_json
    row.tested_count = tested_count
    row.viable_count = viable_count
    row.competitive_count = competitive_count
    row.representative_count = representative_count
    row.is_provisional = bool(is_provisional)
    row.warning_message = warning_message
    row.input_hash = input_hash
    row.computed_at = computed_at
    row.data_as_of = data_as_of
    row.compute_seconds = compute_seconds
    row.error_message = error_message
    return row


def _build_support_resistance_payload(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    timeframe: str,
    cost_bps: float,
    cooldown_bars: int,
    fallback_close: float | None,
    fallback_as_of: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    warning_message = ""
    response: dict[str, Any] = {}
    try:
        from services.api.app.routers.strategy_signals import _sr_get_or_compute_variants

        payload = _sr_get_or_compute_variants(
            db,
            symbol=symbol,
            horizon=horizon,
            timeframe=timeframe,
            cost_bps=cost_bps,
            cooldown_bars=cooldown_bars,
        )
        response = dict(payload.get("response") or {})
    except Exception as exc:
        warning_message = f"SR variants failed: {exc}"
        logger.debug("Signal engine SR failed for %s/%s: %s", symbol, horizon, exc)

    final_support_raw = response.get("final_support")
    final_resistance_raw = response.get("final_resistance")
    selected_support_method_id = response.get("selected_support_method_id")
    selected_resistance_method_id = response.get("selected_resistance_method_id")
    optimal_status = response.get("optimal_status", "unavailable")

    if optimal_status != "ready" or final_support_raw is None or final_resistance_raw is None:
        if not warning_message:
            warning_message = "Aucun couple S/R optimal disponible."
        final_support = None
        final_resistance = None
        selected_support_method_id = None
        selected_resistance_method_id = None
    else:
        final_support = round_number(final_support_raw, 6)
        final_resistance = round_number(final_resistance_raw, 6)

    support_method_id = str(selected_support_method_id) if selected_support_method_id else None
    resistance_method_id = str(selected_resistance_method_id) if selected_resistance_method_id else None
    current_close = round_number(response.get("current_close") or fallback_close, 6)
    as_of = str(response.get("as_of") or fallback_as_of)

    methods_raw = response.get("methods") or []
    methods_by_id = {
        str(method.get("id")): method
        for method in methods_raw
        if isinstance(method, dict) and method.get("id")
    }
    used_methods = [
        {
            "id": str(method.get("id") or ""),
            "label": str(method.get("label") or ""),
            "support": round_number(method.get("support"), 6),
            "resistance": round_number(method.get("resistance"), 6),
            "status": str(method.get("status") or ""),
            "selected_for_support": bool(method.get("selected_for_support")),
            "selected_for_resistance": bool(method.get("selected_for_resistance")),
            "explanation": str(method.get("explanation") or ""),
        }
        for method in methods_raw
        if isinstance(method, dict)
        and (bool(method.get("selected_for_support")) or bool(method.get("selected_for_resistance")))
    ]

    used_variant = None
    if support_method_id and resistance_method_id:
        support_label = str(methods_by_id.get(support_method_id, {}).get("label") or support_method_id)
        resistance_label = str(methods_by_id.get(resistance_method_id, {}).get("label") or resistance_method_id)
        used_variant = {
            "variant_id": f"sr:{support_method_id}__{resistance_method_id}",
            "support_method_id": support_method_id,
            "resistance_method_id": resistance_method_id,
            "description": f"Support {support_label} / Resistance {resistance_label}",
        }

    summary_explanation = str(
        response.get("score_explanation")
        or response.get("summary_explanation")
        or "Support/resistance indisponible pour ce symbole."
    )
    technical_levels = {
        "close_used": current_close,
        "support_buy_trigger": final_support,
        "resistance_sell_trigger": final_resistance,
        "support_reference": final_support,
        "method": "sr_multi_method_v1",
        "selected_support_method_id": support_method_id,
        "selected_resistance_method_id": resistance_method_id,
    }
    support_resistance = {
        "final_support": final_support,
        "final_resistance": final_resistance,
        "selected_support_method_id": support_method_id,
        "selected_resistance_method_id": resistance_method_id,
        "summary_explanation": summary_explanation,
        "trend_score_pct": round_number(response.get("trend_score_pct"), 2),
        "trend_label": str(response.get("trend_label") or ""),
        "as_of": as_of,
        "used_methods": used_methods,
        "used_variant": used_variant,
        "warning_message": warning_message,
    }
    return technical_levels, support_resistance


def _upsert_global_result(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    variant: str,
    status: str,
    aggregate_score_pct: float | None,
    expanded_aggregate_score_pct: float | None,
    signal_label: str | None,
    per_category_json: dict[str, Any] | None,
    per_family_json: dict[str, Any] | None,
    technical_levels_json: dict[str, Any] | None,
    support_resistance_json: dict[str, Any] | None,
    data_as_of: date | None,
    error_message: str | None,
) -> SignalEngineGlobalResult:
    row = (
        db.query(SignalEngineGlobalResult)
        .filter_by(symbol=symbol, horizon=horizon, variant=variant)
        .first()
    )
    if row is None:
        row = SignalEngineGlobalResult(symbol=symbol, horizon=horizon, variant=variant)
        db.add(row)

    row.status = status
    row.aggregate_score_pct = aggregate_score_pct
    row.expanded_aggregate_score_pct = expanded_aggregate_score_pct
    row.signal_label = signal_label
    row.per_category_json = per_category_json or {}
    row.per_family_json = per_family_json or {}
    row.technical_levels_json = technical_levels_json or {}
    row.support_resistance_json = support_resistance_json or {}
    row.computed_at = datetime.now(timezone.utc)
    row.data_as_of = data_as_of
    row.error_message = error_message
    return row


def _load_prices(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    timeframe: str,
) -> tuple[np.ndarray, np.ndarray | None, np.ndarray | None, np.ndarray | None, date]:
    ohlcv_raw = load_ohlcv_for_symbol(db, symbol, timeframe)
    ohlcv = drop_incomplete_ohlcv_rows(ohlcv_raw)
    if ohlcv.empty or len(ohlcv) < 50:
        raise ValueError(f"Insufficient OHLCV bars ({len(ohlcv)})")

    max_bars = HORIZON_PARAMS[horizon]["max_years"] * 252
    if len(ohlcv) > max_bars:
        ohlcv = ohlcv.iloc[-max_bars:]

    close = ohlcv["Close"].values.astype(np.float64)
    high = ohlcv["High"].values.astype(np.float64) if "High" in ohlcv.columns else None
    low = ohlcv["Low"].values.astype(np.float64) if "Low" in ohlcv.columns else None
    volume = ohlcv["Volume"].values.astype(np.float64) if "Volume" in ohlcv.columns else None
    data_as_of = ohlcv.index[-1].date()
    return close, volume, high, low, data_as_of


def _compute_and_upsert_global(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    variant: str,
    cat_map: dict[str, list[str]],
    family_scores: dict[str, float],
    family_statuses: dict[str, str],
    family_representatives: dict[str, list[dict[str, Any]]],
    data_as_of: date | None,
    first_error: str | None,
    timeframe: str,
    cost_bps: float,
    cooldown_bars: int,
) -> str:
    legacy_cat_families = {
        "tendance": ["sma"],
        "momentum": ["macd"],
        "oscillation": ["rsi"],
        "volume": ["obv"],
    }

    per_category: dict[str, dict[str, Any]] = {}
    per_family: dict[str, dict[str, Any]] = {}
    legacy_scores: list[float] = []
    expanded_scores: list[float] = []

    for category, families in cat_map.items():
        category_scores: list[float] = []
        category_family_breakdown: dict[str, Any] = {}
        for family in families:
            score = family_scores.get(family)
            if score is None:
                continue
            category_scores.append(float(score))
            base_family = family.split("@")[0] if "@" in family else family
            sig_type = FAMILY_SIGNAL_TYPE.get(base_family, "trend")
            family_payload = {
                "score_pct": round(float(score), 2),
                "label": signal_type_label(sig_type, float(score)),
            }
            per_family[family] = family_payload
            category_family_breakdown[family] = family_payload

        if category_scores:
            category_avg = sum(category_scores) / len(category_scores)
            base_first_family = families[0].split("@")[0] if "@" in families[0] else families[0]
            sig_type = FAMILY_SIGNAL_TYPE.get(base_first_family, "trend")
            per_category[category] = {
                "score_pct": round(category_avg, 2),
                "label": signal_type_label(sig_type, category_avg),
                "family_scores": category_family_breakdown,
            }
            expanded_scores.append(category_avg)

            legacy_family_candidates = legacy_cat_families.get(category, [])
            if legacy_family_candidates:
                legacy_family = legacy_family_candidates[0]
                base_legacy_family = legacy_family.split("@")[0] if "@" in legacy_family else legacy_family
                legacy_fx = f"{base_legacy_family}@fx" if "@fx" in families[0] else base_legacy_family
                if legacy_family in family_scores:
                    legacy_scores.append(float(family_scores[legacy_family]))
                elif legacy_fx in family_scores:
                    legacy_scores.append(float(family_scores[legacy_fx]))

    agg_legacy = round(sum(legacy_scores) / len(legacy_scores), 2) if legacy_scores else None
    agg_expanded = round(sum(expanded_scores) / len(expanded_scores), 2) if expanded_scores else None

    succeeded_count = sum(1 for status in family_statuses.values() if status == "succeeded")
    failed_count = sum(1 for status in family_statuses.values() if status == "failed")
    if succeeded_count == 0 and failed_count == 0:
        # All families ran but none produced a signal — valid terminal state, not an error
        global_status = "no_signal"
    elif succeeded_count == 0:
        global_status = "failed"
    elif failed_count > 0:
        global_status = "partial"
    else:
        global_status = "succeeded"

    signal_label = _score_to_label(agg_expanded) if agg_expanded is not None else None
    fallback_close = None
    for reps in family_representatives.values():
        if not reps:
            continue
        fallback_close = round_number(reps[0].get("current_close"), 6)
        if fallback_close is not None:
            break

    technical_levels, support_resistance = _build_support_resistance_payload(
        db,
        symbol=symbol,
        horizon=horizon,
        timeframe=timeframe,
        cost_bps=cost_bps,
        cooldown_bars=cooldown_bars,
        fallback_close=fallback_close,
        fallback_as_of=str(data_as_of or ""),
    )

    error_message = first_error if global_status in {"failed", "partial"} else None
    _upsert_global_result(
        db,
        symbol=symbol,
        horizon=horizon,
        variant=variant,
        status=global_status,
        aggregate_score_pct=agg_legacy,
        expanded_aggregate_score_pct=agg_expanded,
        signal_label=signal_label,
        per_category_json=per_category,
        per_family_json=per_family,
        technical_levels_json=technical_levels,
        support_resistance_json=support_resistance,
        data_as_of=data_as_of,
        error_message=error_message,
    )
    return global_status


def full_rebuild_from_pipeline(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    variant: str = "expanded",
    timeframe: str = DEFAULT_TIMEFRAME,
    cost_bps: float = DEFAULT_COST_BPS,
    cooldown_bars: int = DEFAULT_COOLDOWN_BARS,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    first_error: str | None = None
    completed = 0
    failed = 0

    cat_map = _variant_family_map(variant)
    families = _expected_families(variant)
    family_to_category = _family_to_category_map(variant)
    family_scores: dict[str, float] = {}
    family_statuses: dict[str, str] = {}
    family_representatives: dict[str, list[dict[str, Any]]] = {}
    data_as_of: date | None = None

    try:
        close, volume, high, low, data_as_of = _load_prices(
            db,
            symbol=symbol,
            horizon=horizon,
            timeframe=timeframe,
        )
    except Exception as exc:
        message = str(exc)
        _upsert_global_result(
            db,
            symbol=symbol,
            horizon=horizon,
            variant=variant,
            status="failed",
            aggregate_score_pct=None,
            expanded_aggregate_score_pct=None,
            signal_label=None,
            per_category_json={},
            per_family_json={},
            technical_levels_json={},
            support_resistance_json={},
            data_as_of=None,
            error_message=message,
        )
        return {
            "mode": "full_rebuild",
            "status": "failed",
            "completed": 0,
            "failed": len(families),
            "first_error": message,
            "elapsed": round(time.perf_counter() - started_at, 2),
        }

    has_valid_volume = _check_volume(volume)
    current_hash = _input_hash(data_as_of, cost_bps, cooldown_bars)

    for family in families:
        category = family_to_category.get(family, "unknown")
        t_family = time.perf_counter()
        try:
            if family in _VOLUME_FAMILIES and not has_valid_volume:
                family_statuses[family] = "no_signal"
                family_representatives[family] = []
                _upsert_family_result(
                    db,
                    symbol=symbol,
                    family=family,
                    category=category,
                    horizon=horizon,
                    variant=variant,
                    status="no_signal",
                    representatives_json=[],
                    family_detail_json={
                        "family": family,
                        "symbol": symbol,
                        "horizon": horizon,
                        "timeframe": timeframe,
                        "family_score_pct": 0.0,
                        "family_signal_label": "Pas disponible",
                        "tested_count": 0,
                        "viable_count": 0,
                        "competitive_count": 0,
                        "representative_count": 0,
                        "representatives": [],
                        "fallback_variants": [],
                        "score_explanation": "",
                        "methodology_status": "robust_oos_ensemble",
                        "methodology_mode": "robust_oos_ensemble",
                        "available_bars": int(len(close)),
                        "nominal_window": {},
                        "effective_window": {},
                        "warning_message": "Volume indisponible.",
                        "is_provisional": False,
                        "as_of": str(data_as_of),
                        "latest_close": _safe_float(close[-1]) if len(close) else None,
                        "best_variant_id": "",
                    },
                    tested_count=0,
                    viable_count=0,
                    competitive_count=0,
                    representative_count=0,
                    is_provisional=False,
                    warning_message="Volume indisponible.",
                    input_hash=current_hash,
                    computed_at=datetime.now(timezone.utc),
                    data_as_of=data_as_of,
                    compute_seconds=time.perf_counter() - t_family,
                    error_message=None,
                )
                completed += 1
                continue

            detail = run_family_ensemble_full(
                family,
                close,
                volume=volume,
                high=high,
                low=low,
                symbol=symbol,
                horizon=horizon,
                timeframe=timeframe,
                cost_bps=cost_bps,
                cooldown_bars=cooldown_bars,
            )
            sig = detail.signal
            reps_json = _serialize_representatives(sig)
            detail_json = _build_family_detail_json(
                family=family,
                symbol=symbol,
                horizon=horizon,
                timeframe=timeframe,
                sig=sig,
            )
            available = family_signal_is_available(sig)
            family_status = "succeeded" if available else "no_signal"
            family_statuses[family] = family_status
            family_representatives[family] = reps_json

            _upsert_family_result(
                db,
                symbol=symbol,
                family=family,
                category=category,
                horizon=horizon,
                variant=variant,
                status=family_status,
                family_score_pct=float(sig.family_score_pct) if available else None,
                signal_label=str(sig.family_signal_label) if available else "Pas disponible",
                representatives_json=reps_json,
                family_detail_json=detail_json,
                tested_count=int(sig.tested_count),
                viable_count=int(sig.viable_count),
                competitive_count=int(sig.competitive_count),
                representative_count=int(sig.representative_count),
                is_provisional=bool(sig.is_provisional),
                warning_message=str(sig.warning_message or ""),
                input_hash=current_hash,
                computed_at=datetime.now(timezone.utc),
                data_as_of=data_as_of,
                compute_seconds=time.perf_counter() - t_family,
                error_message=None,
            )

            if available:
                family_scores[family] = float(sig.family_score_pct)
            completed += 1
        except Exception as exc:
            failed += 1
            message = str(exc)
            if first_error is None:
                first_error = message
            family_statuses[family] = "failed"
            family_representatives[family] = []
            _upsert_family_result(
                db,
                symbol=symbol,
                family=family,
                category=category,
                horizon=horizon,
                variant=variant,
                status="failed",
                family_score_pct=None,
                signal_label=None,
                representatives_json=[],
                family_detail_json=None,
                tested_count=None,
                viable_count=None,
                competitive_count=None,
                representative_count=None,
                is_provisional=False,
                warning_message=None,
                input_hash=current_hash,
                computed_at=datetime.now(timezone.utc),
                data_as_of=data_as_of,
                compute_seconds=time.perf_counter() - t_family,
                error_message=message,
            )

    global_status = _compute_and_upsert_global(
        db,
        symbol=symbol,
        horizon=horizon,
        variant=variant,
        cat_map=cat_map,
        family_scores=family_scores,
        family_statuses=family_statuses,
        family_representatives=family_representatives,
        data_as_of=data_as_of,
        first_error=first_error,
        timeframe=timeframe,
        cost_bps=cost_bps,
        cooldown_bars=cooldown_bars,
    )

    failed_count = sum(1 for status in family_statuses.values() if status == "failed")
    succeeded_or_nosignal = sum(
        1 for status in family_statuses.values() if status in {"succeeded", "no_signal"}
    )
    return {
        "mode": "full_rebuild",
        "status": global_status,
        "completed": succeeded_or_nosignal,
        "failed": failed_count,
        "first_error": first_error,
        "data_as_of": str(data_as_of) if data_as_of else None,
        "elapsed": round(time.perf_counter() - started_at, 2),
    }


def refresh_from_persisted_reps(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    variant: str = "expanded",
    timeframe: str = DEFAULT_TIMEFRAME,
    cost_bps: float = DEFAULT_COST_BPS,
    cooldown_bars: int = DEFAULT_COOLDOWN_BARS,
    fallback_to_full_rebuild: bool = False,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    cat_map = _variant_family_map(variant)
    families = _expected_families(variant)
    family_to_category = _family_to_category_map(variant)

    rows = (
        db.query(SignalEngineFamilyResult)
        .filter_by(symbol=symbol, horizon=horizon, variant=variant)
        .all()
    )
    rows_by_family = {row.family: row for row in rows}
    missing_or_invalid = [
        family
        for family in families
        if not _family_row_refreshable(rows_by_family.get(family))
    ]
    if missing_or_invalid and fallback_to_full_rebuild:
        logger.info(
            "Signal engine refresh fallback to full rebuild for %s/%s/%s (families=%s)",
            symbol,
            horizon,
            variant,
            ",".join(missing_or_invalid),
        )
        return full_rebuild_from_pipeline(
            db,
            symbol=symbol,
            horizon=horizon,
            variant=variant,
            timeframe=timeframe,
            cost_bps=cost_bps,
            cooldown_bars=cooldown_bars,
        )

    first_error: str | None = None
    family_scores: dict[str, float] = {}
    family_statuses: dict[str, str] = {}
    family_representatives: dict[str, list[dict[str, Any]]] = {}

    try:
        close, volume, high, low, data_as_of = _load_prices(
            db,
            symbol=symbol,
            horizon=horizon,
            timeframe=timeframe,
        )
    except Exception as exc:
        message = str(exc)
        _upsert_global_result(
            db,
            symbol=symbol,
            horizon=horizon,
            variant=variant,
            status="failed",
            aggregate_score_pct=None,
            expanded_aggregate_score_pct=None,
            signal_label=None,
            per_category_json={},
            per_family_json={},
            technical_levels_json={},
            support_resistance_json={},
            data_as_of=None,
            error_message=message,
        )
        return {
            "mode": "refresh_from_reps",
            "status": "failed",
            "completed": 0,
            "failed": len(families),
            "first_error": message,
            "elapsed": round(time.perf_counter() - started_at, 2),
        }

    current_hash = _input_hash(data_as_of, cost_bps, cooldown_bars)
    has_valid_volume = _check_volume(volume)

    for family in families:
        category = family_to_category.get(family, "unknown")
        row = rows_by_family.get(family)
        t_family = time.perf_counter()
        try:
            if row is None:
                raise ValueError(f"Missing persisted family row for {family}")

            if family in _VOLUME_FAMILIES and not has_valid_volume:
                family_statuses[family] = "no_signal"
                family_representatives[family] = []
                _upsert_family_result(
                    db,
                    symbol=symbol,
                    family=family,
                    category=category,
                    horizon=horizon,
                    variant=variant,
                    status="no_signal",
                    family_score_pct=None,
                    signal_label="Pas disponible",
                    representatives_json=row.representatives_json or [],
                    family_detail_json=row.family_detail_json or {},
                    tested_count=row.tested_count,
                    viable_count=row.viable_count,
                    competitive_count=row.competitive_count,
                    representative_count=0,
                    is_provisional=bool(row.is_provisional),
                    warning_message=row.warning_message or "Volume indisponible.",
                    input_hash=current_hash,
                    computed_at=datetime.now(timezone.utc),
                    data_as_of=data_as_of,
                    compute_seconds=time.perf_counter() - t_family,
                    error_message=None,
                )
                continue

            reps_src = [
                rep
                for rep in (row.representatives_json or [])
                if _representative_payload_is_valid(rep)
            ]
            status = str(row.status or "").strip().lower()
            if status == "no_signal":
                family_statuses[family] = "no_signal"
                family_representatives[family] = []
                _upsert_family_result(
                    db,
                    symbol=symbol,
                    family=family,
                    category=category,
                    horizon=horizon,
                    variant=variant,
                    status="no_signal",
                    family_score_pct=None,
                    signal_label="Pas disponible",
                    representatives_json=[],
                    family_detail_json=row.family_detail_json or {},
                    tested_count=row.tested_count,
                    viable_count=row.viable_count,
                    competitive_count=row.competitive_count,
                    representative_count=0,
                    is_provisional=bool(row.is_provisional),
                    warning_message=row.warning_message,
                    input_hash=current_hash,
                    computed_at=datetime.now(timezone.utc),
                    data_as_of=data_as_of,
                    compute_seconds=time.perf_counter() - t_family,
                    error_message=None,
                )
                continue
            if not reps_src:
                raise ValueError(f"No valid representatives persisted for {family}")

            current_signals = []
            refreshed_reps: list[dict[str, Any]] = []
            for rep in reps_src:
                variant_def = _variant_from_rep(rep, fallback_family=family)
                rep_weight = _safe_float(
                    rep.get("reliability_weight") or rep.get("normalized_weight") or 1.0
                ) or 1.0
                current = build_current_signal(
                    variant_def,
                    close,
                    volume=volume,
                    high=high,
                    low=low,
                    reliability_weight=rep_weight,
                    cooldown_bars=cooldown_bars,
                )
                current_signals.append(current)
                refreshed = dict(rep)
                refreshed.update(
                    {
                        "variant_id": variant_def.variant_id,
                        "family": variant_def.family,
                        "archetype": variant_def.archetype,
                        "params": dict(variant_def.params),
                        "description": str(rep.get("description") or variant_def.description or ""),
                        "signal": _safe_float(current.signal),
                        "signal_label": str(current.signal_label),
                        "reliability_weight": _safe_float(current.reliability_weight),
                        "current_close": _safe_float(current.current_close),
                        "indicator_value": _safe_float(current.indicator_value),
                        "explanation": str(current.explanation or ""),
                        "selection_status": str(rep.get("selection_status") or "selected"),
                    }
                )
                refreshed_reps.append(refreshed)

            score_pct, label, weighted_reps = combine_family_signals(current_signals, family)
            weighted_by_id = {
                str(rep.get("variant_id")): rep
                for rep in weighted_reps
                if isinstance(rep, dict) and rep.get("variant_id")
            }
            for refreshed in refreshed_reps:
                weighted = weighted_by_id.get(str(refreshed.get("variant_id")), {})
                refreshed["normalized_weight"] = _safe_float(
                    weighted.get("normalized_weight", refreshed.get("normalized_weight"))
                )
                refreshed["contribution"] = _safe_float(
                    weighted.get("contribution", refreshed.get("contribution"))
                )

            detail_json = dict(row.family_detail_json or {})
            detail_json.update(
                {
                    "family": family,
                    "symbol": symbol,
                    "horizon": horizon,
                    "timeframe": timeframe,
                    "family_score_pct": round(float(score_pct), 2),
                    "family_signal_label": str(label),
                    "tested_count": int(row.tested_count or 0),
                    "viable_count": int(row.viable_count or 0),
                    "competitive_count": int(row.competitive_count or 0),
                    "representative_count": len(refreshed_reps),
                    "representatives": refreshed_reps,
                    "fallback_variants": detail_json.get("fallback_variants") or [],
                    "as_of": str(data_as_of),
                    "latest_close": _safe_float(close[-1]) if len(close) else None,
                    "is_provisional": bool(row.is_provisional),
                    "warning_message": str(row.warning_message or ""),
                    "score_explanation": detail_json.get("score_explanation")
                    or "Signal rafraichi a partir des representants persistes.",
                    "methodology_status": detail_json.get("methodology_status")
                    or ("adaptive_oos_ensemble" if bool(row.is_provisional) else "robust_oos_ensemble"),
                }
            )
            detail_json["methodology_mode"] = detail_json.get("methodology_mode") or detail_json["methodology_status"]
            detail_json["available_bars"] = int(detail_json.get("available_bars") or len(close))
            detail_json["nominal_window"] = detail_json.get("nominal_window") or {
                "train": int(HORIZON_PARAMS[horizon]["train"]),
                "test": int(HORIZON_PARAMS[horizon]["test"]),
                "step": int(HORIZON_PARAMS[horizon]["step"]),
                "target_windows": 0,
            }
            detail_json["effective_window"] = detail_json.get("effective_window") or detail_json["nominal_window"]
            detail_json["best_variant_id"] = detail_json.get("best_variant_id") or str(
                refreshed_reps[0]["variant_id"] if refreshed_reps else ""
            )

            _upsert_family_result(
                db,
                symbol=symbol,
                family=family,
                category=category,
                horizon=horizon,
                variant=variant,
                status="succeeded",
                family_score_pct=float(score_pct),
                signal_label=str(label),
                representatives_json=refreshed_reps,
                family_detail_json=detail_json,
                tested_count=row.tested_count,
                viable_count=row.viable_count,
                competitive_count=row.competitive_count,
                representative_count=len(refreshed_reps),
                is_provisional=bool(row.is_provisional),
                warning_message=row.warning_message,
                input_hash=current_hash,
                computed_at=datetime.now(timezone.utc),
                data_as_of=data_as_of,
                compute_seconds=time.perf_counter() - t_family,
                error_message=None,
            )

            family_statuses[family] = "succeeded"
            family_scores[family] = float(score_pct)
            family_representatives[family] = refreshed_reps
        except Exception as exc:
            message = str(exc)
            if first_error is None:
                first_error = message
            family_statuses[family] = "failed"
            family_representatives[family] = []
            _upsert_family_result(
                db,
                symbol=symbol,
                family=family,
                category=category,
                horizon=horizon,
                variant=variant,
                status="failed",
                family_score_pct=None,
                signal_label=None,
                representatives_json=[],
                family_detail_json=row.family_detail_json if row is not None else None,
                tested_count=row.tested_count if row is not None else None,
                viable_count=row.viable_count if row is not None else None,
                competitive_count=row.competitive_count if row is not None else None,
                representative_count=row.representative_count if row is not None else None,
                is_provisional=bool(row.is_provisional) if row is not None else False,
                warning_message=row.warning_message if row is not None else None,
                input_hash=current_hash,
                computed_at=datetime.now(timezone.utc),
                data_as_of=data_as_of,
                compute_seconds=time.perf_counter() - t_family,
                error_message=message,
            )

    global_status = _compute_and_upsert_global(
        db,
        symbol=symbol,
        horizon=horizon,
        variant=variant,
        cat_map=cat_map,
        family_scores=family_scores,
        family_statuses=family_statuses,
        family_representatives=family_representatives,
        data_as_of=data_as_of,
        first_error=first_error,
        timeframe=timeframe,
        cost_bps=cost_bps,
        cooldown_bars=cooldown_bars,
    )
    failed_count = sum(1 for status in family_statuses.values() if status == "failed")
    completed_count = sum(
        1 for status in family_statuses.values() if status in {"succeeded", "no_signal"}
    )
    return {
        "mode": "refresh_from_reps",
        "status": global_status,
        "completed": completed_count,
        "failed": failed_count,
        "first_error": first_error,
        "data_as_of": str(data_as_of) if data_as_of else None,
        "elapsed": round(time.perf_counter() - started_at, 2),
    }


def _market_data_as_of(db: Session, *, symbol: str, timeframe: str) -> date | None:
    row = db.query(MarketDataStore).filter_by(symbol=symbol, timeframe=timeframe).first()
    if row is None:
        return None
    return row.data_as_of


def _classify_cache_state(
    *,
    expected_families: list[str],
    global_row: SignalEngineGlobalResult | None,
    family_rows_by_family: dict[str, SignalEngineFamilyResult],
    market_data_as_of: date | None,
) -> str:
    families_present = all(family in family_rows_by_family for family in expected_families)
    families_refreshable = families_present and all(
        _family_row_refreshable(family_rows_by_family[family]) for family in expected_families
    )

    if global_row is None:
        return "stale" if families_refreshable else "missing"
    for family in expected_families:
        if family not in family_rows_by_family:
            return "missing"

    if str(global_row.status or "").strip().lower() not in {"succeeded", "partial", "no_signal"}:
        return "stale" if families_refreshable else "invalid"

    for family in expected_families:
        row = family_rows_by_family[family]
        if not _family_row_refreshable(row):
            return "invalid"

    if market_data_as_of is not None:
        if global_row.data_as_of != market_data_as_of:
            return "stale"
        for family in expected_families:
            if family_rows_by_family[family].data_as_of != market_data_as_of:
                return "stale"

    return "fresh"


def _serialize_engine_payload(
    *,
    symbol: str,
    horizon: str,
    variant: str,
    global_row: SignalEngineGlobalResult,
    family_rows: list[SignalEngineFamilyResult],
    market_data_as_of: date | None,
    resolution_mode: str,
    cache_state: str,
) -> dict[str, Any]:
    families: dict[str, dict[str, Any]] = {}
    for row in family_rows:
        reps_json = row.representatives_json or []
        detail = dict(row.family_detail_json or {})
        if not detail:
            detail = {
                "family": row.family,
                "symbol": symbol,
                "horizon": horizon,
                "timeframe": DEFAULT_TIMEFRAME,
                "family_score_pct": row.family_score_pct,
                "family_signal_label": row.signal_label or "Pas disponible",
                "tested_count": int(row.tested_count or 0),
                "viable_count": int(row.viable_count or 0),
                "competitive_count": int(row.competitive_count or 0),
                "representative_count": int(row.representative_count or 0),
                "representatives": reps_json,
                "fallback_variants": [],
                "score_explanation": "",
                "methodology_status": "adaptive_oos_ensemble" if bool(row.is_provisional) else "robust_oos_ensemble",
                "methodology_mode": "adaptive_oos_ensemble" if bool(row.is_provisional) else "robust_oos_ensemble",
                "available_bars": 0,
                "nominal_window": {"train": 0, "test": 0, "step": 0, "target_windows": 0},
                "effective_window": {"train": 0, "test": 0, "step": 0, "target_windows": 0},
                "warning_message": str(row.warning_message or ""),
                "is_provisional": bool(row.is_provisional),
                "as_of": row.data_as_of.isoformat() if row.data_as_of else "",
                "latest_close": None,
                "best_variant_id": str(reps_json[0].get("variant_id") if reps_json else ""),
            }
        else:
            detail.setdefault("family", row.family)
            detail.setdefault("symbol", symbol)
            detail.setdefault("horizon", horizon)
            detail.setdefault("timeframe", DEFAULT_TIMEFRAME)
            detail.setdefault("family_score_pct", row.family_score_pct)
            detail.setdefault("family_signal_label", row.signal_label or "Pas disponible")
            detail.setdefault("tested_count", int(row.tested_count or 0))
            detail.setdefault("viable_count", int(row.viable_count or 0))
            detail.setdefault("competitive_count", int(row.competitive_count or 0))
            detail.setdefault("representative_count", int(row.representative_count or 0))
            detail.setdefault("fallback_variants", [])
            detail.setdefault("score_explanation", "")
            detail.setdefault("methodology_status", "adaptive_oos_ensemble" if bool(row.is_provisional) else "robust_oos_ensemble")
            detail.setdefault("methodology_mode", detail.get("methodology_status"))
            detail.setdefault("available_bars", 0)
            detail.setdefault("nominal_window", {"train": 0, "test": 0, "step": 0, "target_windows": 0})
            detail.setdefault("effective_window", {"train": 0, "test": 0, "step": 0, "target_windows": 0})
            detail.setdefault("warning_message", str(row.warning_message or ""))
            detail.setdefault("is_provisional", bool(row.is_provisional))
            detail.setdefault("as_of", row.data_as_of.isoformat() if row.data_as_of else "")
            detail.setdefault("latest_close", None)
            detail.setdefault("best_variant_id", str(reps_json[0].get("variant_id") if reps_json else ""))
            detail["representatives"] = detail.get("representatives") or reps_json

        families[row.family] = {
            "status": row.status,
            "category": row.category,
            "family_score_pct": row.family_score_pct,
            "signal_label": row.signal_label,
            "tested_count": row.tested_count,
            "viable_count": row.viable_count,
            "competitive_count": row.competitive_count,
            "representative_count": row.representative_count,
            "is_provisional": row.is_provisional,
            "warning_message": row.warning_message,
            "error_message": row.error_message,
            "representatives": reps_json,
            "family_detail": detail,
            "computed_at": row.computed_at.isoformat() if row.computed_at else None,
            "data_as_of": row.data_as_of.isoformat() if row.data_as_of else None,
        }

    market_data_as_of_str = market_data_as_of.isoformat() if market_data_as_of else None
    is_stale = cache_state == "stale"
    return {
        "symbol": symbol,
        "horizon": horizon,
        "variant": variant,
        "status": global_row.status,
        "aggregate_score_pct": global_row.aggregate_score_pct,
        "expanded_aggregate_score_pct": global_row.expanded_aggregate_score_pct,
        "signal_label": global_row.signal_label,
        "per_category": global_row.per_category_json,
        "per_family": global_row.per_family_json,
        "technical_levels": global_row.technical_levels_json,
        "support_resistance": global_row.support_resistance_json,
        "computed_at": global_row.computed_at.isoformat() if global_row.computed_at else None,
        "data_as_of": global_row.data_as_of.isoformat() if global_row.data_as_of else None,
        "is_stale": is_stale,
        "market_data_as_of": market_data_as_of_str,
        "families": families,
        "resolution_mode": resolution_mode,
        "cache_state": cache_state,
    }


def resolve_signal_engine_result(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    variant: str = "expanded",
    timeframe: str = DEFAULT_TIMEFRAME,
    cost_bps: float = DEFAULT_COST_BPS,
    cooldown_bars: int = DEFAULT_COOLDOWN_BARS,
) -> dict[str, Any]:
    expected_families = _expected_families(variant)
    market_data_as_of = _market_data_as_of(db, symbol=symbol, timeframe=timeframe)
    global_row = (
        db.query(SignalEngineGlobalResult)
        .filter_by(symbol=symbol, horizon=horizon, variant=variant)
        .first()
    )
    family_rows = (
        db.query(SignalEngineFamilyResult)
        .filter_by(symbol=symbol, horizon=horizon, variant=variant)
        .all()
    )
    family_map = {row.family: row for row in family_rows}
    cache_state = _classify_cache_state(
        expected_families=expected_families,
        global_row=global_row,
        family_rows_by_family=family_map,
        market_data_as_of=market_data_as_of,
    )

    if cache_state == "missing" or global_row is None:
        raise LookupError(f"No persisted signal engine result for {symbol}/{horizon}/{variant}")

    if cache_state == "invalid":
        raise ValueError(
            f"Persisted signal engine result is invalid for {symbol}/{horizon}/{variant}; "
            "trigger a rebuild."
        )

    resolution_mode = "fresh_cache" if cache_state == "fresh" else "stale_cache"

    if cache_state == "stale":
        try:
            from services.api.app.models import SignalEngineBatchJob
            from services.worker.tasks.signal_enqueue import enqueue_signal_engine_refresh_for_symbol

            already_active = (
                db.query(SignalEngineBatchJob)
                .filter(
                    SignalEngineBatchJob.symbol == symbol,
                    SignalEngineBatchJob.horizon == horizon,
                    SignalEngineBatchJob.variant == variant,
                    SignalEngineBatchJob.job_type == "signal_engine",
                    SignalEngineBatchJob.status.in_(["queued", "running", "pending"]),
                )
                .first()
            )
            if not already_active:
                enqueue_signal_engine_refresh_for_symbol(
                    symbol, horizon, variant=variant, triggered_by="auto_stale"
                )
        except Exception:
            logger.exception("auto_stale enqueue failed for %s/%s/%s", symbol, horizon, variant)

    return _serialize_engine_payload(
        symbol=symbol,
        horizon=horizon,
        variant=variant,
        global_row=global_row,
        family_rows=family_rows,
        market_data_as_of=market_data_as_of,
        resolution_mode=resolution_mode,
        cache_state=cache_state,
    )


def compute_result_status_totals(statuses: list[str]) -> tuple[int, int, int]:
    """Helper kept public for tests: returns succeeded/no_signal/failed counts."""
    succeeded = sum(1 for status in statuses if status == "succeeded")
    no_signal = sum(1 for status in statuses if status == "no_signal")
    failed = sum(1 for status in statuses if status == "failed")
    return succeeded, no_signal, failed
