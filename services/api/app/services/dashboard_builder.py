"""Shared dashboard payload builder.

Called by both the live-compute API path (legacy/shadow mode) and the
background worker that persists snapshots to ``dashboard_snapshot``.
Keeps the aggregation logic in exactly one place.
"""
from __future__ import annotations

import json
import hashlib
import logging
import math
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.quant_core.signal_engine.domain import signal_type_label as _core_signal_type_label
from core.quant_core.signal_engine.modes import ALL_SIGNAL_MODE_NAMES, resolve_signal_mode
from .market_universe import (
    dashboard_group_label,
    is_masi_dashboard_member,
    list_signal_universe,
)


# ---------------------------------------------------------------------------
# Lookup tables (duplicated from dashboard_data.py; authoritative copy here)
# ---------------------------------------------------------------------------

HORIZON_ALIASES: dict[str, str] = {
    "short": "weekly",
    "medium": "monthly",
    "long": "quarterly",
}

HORIZONS: dict[str, str] = {
    "weekly": "Hebdomadaire",
    "monthly": "Mensuel",
    "quarterly": "Trimestriel",
}

DASHBOARD_PAYLOAD_VERSION = "2026-05-12-wfo-trade-opportunities-v1"

EDGE_SIGNAL_MODES: tuple[str, ...] = ALL_SIGNAL_MODE_NAMES
EDGE_CANDIDATE_COUNT = len(EDGE_SIGNAL_MODES)

EDGE_SCORE_HISTORY_SOURCES: tuple[str, ...] = tuple(dict.fromkeys((
    *(f"engine:{mode}" for mode in EDGE_SIGNAL_MODES),
    *(f"wfo:{mode}" for mode in EDGE_SIGNAL_MODES),
    "engine_expanded",
    "engine_legacy",
    "factor_x_ta",
    "wfo",
)))

logger = logging.getLogger(__name__)

FAMILY_SIGNAL_TYPE: dict[str, str] = {
    "sma": "trend", "ema": "trend", "ema_cross": "trend",
    "ichimoku": "trend", "psar": "trend",
    "macd": "strength", "roc": "strength", "trix": "strength",
    "adx": "strength", "tsi": "strength",
    "rsi": "oscillator", "stochastic": "oscillator", "cci": "oscillator",
    "mfi": "oscillator", "uo": "oscillator",
    "obv": "volume", "cmf": "volume", "ad": "volume",
    "vwap": "volume", "fi": "volume",
}

LEGACY_CATEGORY_FAMILIES: dict[str, list[str]] = {
    "tendance": ["sma"],
    "momentum": ["macd"],
    "oscillation": ["rsi"],
    "volume": ["obv"],
}
EXPANDED_CATEGORY_FAMILIES: dict[str, list[str]] = {
    "tendance": ["sma", "ema", "ema_cross", "ichimoku", "psar"],
    "momentum": ["macd", "roc", "trix", "adx", "tsi"],
    "oscillation": ["rsi", "stochastic", "cci", "mfi", "uo"],
    "volume": ["obv", "cmf", "ad", "vwap", "fi"],
}

SIGNAL_MODE_CATEGORY_FAMILIES: dict[str, dict[str, list[str]]] = {
    "legacy_ta_simple": LEGACY_CATEGORY_FAMILIES,
    "expanded_ta_simple": EXPANDED_CATEGORY_FAMILIES,
    "legacy_factor_x_ta_simple": {
        category: [f"{family}@fx" for family in families]
        for category, families in LEGACY_CATEGORY_FAMILIES.items()
    },
    "expanded_factor_x_ta_simple": {
        category: [f"{family}@fx" for family in families]
        for category, families in EXPANDED_CATEGORY_FAMILIES.items()
    },
    "legacy_ta_combo": {
        category: [f"legacy_ta_combo_{category}"]
        for category in EXPANDED_CATEGORY_FAMILIES
    },
    "expanded_ta_combo": {
        category: [f"expanded_ta_combo_{category}"]
        for category in EXPANDED_CATEGORY_FAMILIES
    },
    "legacy_factor_x_ta_combo": {
        category: [f"legacy_fx_combo_{category}"]
        for category in EXPANDED_CATEGORY_FAMILIES
    },
    "expanded_factor_x_ta_combo": {
        category: [f"expanded_fx_combo_{category}"]
        for category in EXPANDED_CATEGORY_FAMILIES
    },
}

FACTOR_X_TA_SIMPLE_VARIANTS: tuple[str, ...] = ("expanded_factor_x_ta_simple", "factor_x_ta")
FACTOR_X_TA_SIMPLE_VARIANT_SQL = "'expanded_factor_x_ta_simple', 'factor_x_ta'"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _round(val: Any) -> Any:
    if val is None:
        return None
    try:
        if math.isnan(val):
            return None
        return round(float(val), 2)
    except Exception:
        return val


def _score_to_label(score_pct: float | None) -> str:
    if score_pct is None:
        return "Indisponible"
    return _core_signal_type_label("aggregate", float(score_pct))


def _bucket_to_signal_label(bucket: Any) -> str:
    return {
        "strong_buy": "Achat fort",
        "buy": "Achat",
        "hold": "Neutre",
        "sell": "Vente",
        "strong_sell": "Vente forte",
    }.get(str(bucket or "").strip().lower(), "Indisponible")


def _is_actionable_edge_bucket(bucket: Any, direction: Any) -> bool:
    bucket_key = str(bucket or "").strip().lower()
    direction_key = str(direction or "").strip().lower()
    if bucket_key in {"hold", "unavailable", "indisponible", ""}:
        return False
    return (bucket_key in {"buy", "strong_buy"} and direction_key == "long") or (
        bucket_key in {"sell", "strong_sell"} and direction_key == "short"
    )


def _signal_type_label(signal_type: str, score_pct: float) -> str:
    if signal_type == "trend":
        if score_pct > 50: return "Très haussier"
        if score_pct > 15: return "Haussier"
        if score_pct >= -15: return "Neutre"
        if score_pct >= -50: return "Baissier"
        return "Très baissier"
    if signal_type == "strength":
        if score_pct > 50: return "Fort momentum haussier"
        if score_pct > 15: return "Momentum haussier"
        if score_pct >= -15: return "Pas de momentum"
        if score_pct >= -50: return "Momentum baissier"
        return "Fort momentum baissier"
    if signal_type == "oscillator":
        if score_pct > 50: return "Très survendu"
        if score_pct > 15: return "Survendu"
        if score_pct >= -15: return "Normal"
        if score_pct >= -50: return "Suracheté"
        return "Très suracheté"
    if signal_type == "volume":
        if score_pct > 50: return "Forte accumulation"
        if score_pct > 15: return "Accumulation"
        if score_pct >= -15: return "Neutre"
        if score_pct >= -50: return "Distribution"
        return "Forte distribution"
    return "Neutre"


def _family_score_value(payload: dict[str, Any], family: str) -> float | None:
    raw = payload.get(family)
    if not isinstance(raw, dict):
        return None
    value = raw.get("family_score_pct", raw.get("score_pct"))
    safe = _safe_float(value)
    return safe


def _category_signal_type(category: str, first_family: str) -> str:
    if category == "tendance":
        return "trend"
    if category == "momentum":
        return "strength"
    if category == "oscillation":
        return "oscillator"
    if category == "volume":
        return "volume"
    return FAMILY_SIGNAL_TYPE.get(first_family, "trend")


def _avg_cats(
    cat_dict: dict[str, list[float]],
    family_map: dict[str, list[str]],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for cat, vals in cat_dict.items():
        if not vals:
            continue
        avg = sum(vals) / len(vals)
        sig = _category_signal_type(cat, family_map[cat][0])
        out[cat] = {"score_pct": _round(avg), "label": _signal_type_label(sig, avg)}
    return out


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        out = float(val)
    except Exception:
        return None
    if not math.isfinite(out):
        return None
    return out


def _variation_pct(close_last: Any, prev_close: Any) -> float | None:
    close = _safe_float(close_last)
    prev = _safe_float(prev_close)
    if close is None or prev in (None, 0.0):
        return None
    return round(((close - prev) / prev) * 100.0, 2)


def _factor_specs_by_ticker() -> dict[str, Any]:
    try:
        from core.quant_core.macro import get_macro_series_by_symbol
        return get_macro_series_by_symbol()
    except Exception:
        return {}


def _factor_condition_rule(condition: dict[str, Any]) -> str:
    direction = str(condition.get("direction") or "")
    sym = "<" if direction == "below" else ">"
    form = str(condition.get("form") or "")
    lookback = condition.get("lookback")
    threshold = _safe_float(condition.get("threshold"))
    threshold_text = "--" if threshold is None else f"{threshold:g}"
    if form == "zscore":
        return f"z{lookback} {sym} {threshold_text}"
    if form == "momentum":
        pct = threshold * 100.0 if threshold is not None else None
        return f"mom{lookback} {sym} {pct:.1f}%" if pct is not None else f"mom{lookback} {sym} --"
    if form == "change":
        return f"change({lookback}) {sym} {threshold_text}"
    if form == "level":
        return f"level {sym} {threshold_text}"
    if form == "direction":
        return f"dir {sym} 0"
    return f"{form}({lookback}) {sym} {threshold_text}"


def _normalise_factor_condition(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    condition = raw.get("factor_condition") if isinstance(raw.get("factor_condition"), dict) else raw
    if not isinstance(condition, dict):
        return None
    condition_id = str(condition.get("condition_id") or "")
    ticker = str(condition.get("factor_ticker") or "")
    if not condition_id or not ticker:
        return None
    return {
        "condition_id": condition_id,
        "factor_ticker": ticker,
        "form": str(condition.get("form") or ""),
        "lookback": condition.get("lookback"),
        "threshold": condition.get("threshold"),
        "direction": str(condition.get("direction") or ""),
    }


def _factor_dependencies_from_reps(reps: Any) -> list[dict[str, Any]]:
    if not isinstance(reps, list):
        return []
    specs = _factor_specs_by_ticker()
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add_condition(raw: Any) -> None:
        condition = _normalise_factor_condition(raw)
        if condition is None:
            return
        ticker = condition["factor_ticker"]
        key = (ticker, condition["condition_id"])
        if key in seen:
            return
        seen.add(key)
        spec = specs.get(ticker)
        canonical_id = getattr(spec, "canonical_id", None) or ticker
        out.append({
            "condition_id": condition["condition_id"],
            "factor_ticker": ticker,
            "canonical_id": canonical_id,
            "label": canonical_id,
            "rule": _factor_condition_rule(condition),
        })

    for rep in reps:
        if not isinstance(rep, dict):
            continue
        add_condition(rep.get("factor_condition"))
        params = rep.get("params")
        if isinstance(params, dict):
            for component in params.get("components", []):
                add_condition(component)
                if isinstance(component, dict):
                    add_condition(component.get("factor_condition"))

    return out


def _representatives_from_family_row(row: Any) -> list[dict[str, Any]]:
    reps = row[5] if len(row) > 5 else None
    if isinstance(reps, list) and reps:
        return reps
    detail = row[6] if len(row) > 6 else None
    if isinstance(detail, dict):
        detail_reps = detail.get("representatives")
        if isinstance(detail_reps, list):
            return detail_reps
    return []


def _factor_family_payload(rows: list[Any]) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    cat_scores: dict[str, list[float]] = defaultdict(list)
    dependencies: dict[str, list[dict[str, Any]]] = defaultdict(list)
    dep_keys: dict[str, set[tuple[str, str]]] = defaultdict(set)

    for row in rows:
        category = str(row[2] or "")
        score = _safe_float(row[3])
        if category and score is not None:
            cat_scores[category].append(score)

        for dep in _factor_dependencies_from_reps(_representatives_from_family_row(row)):
            key = (str(dep.get("factor_ticker") or ""), str(dep.get("condition_id") or ""))
            if not category or key in dep_keys[category]:
                continue
            dep_keys[category].add(key)
            dependencies[category].append(dep)

    return _avg_cats(dict(cat_scores), EXPANDED_CATEGORY_FAMILIES), dict(dependencies)


def _category_scores_from_family_payload(
    per_family_json: dict[str, Any] | None,
    variant: str,
) -> dict[str, Any]:
    try:
        mode = resolve_signal_mode(variant)
    except ValueError:
        mode = resolve_signal_mode("expanded_ta_simple")
    family_map = SIGNAL_MODE_CATEGORY_FAMILIES.get(
        mode.name,
        LEGACY_CATEGORY_FAMILIES if mode.is_legacy else EXPANDED_CATEGORY_FAMILIES,
    )
    out: dict[str, Any] = {}
    payload = per_family_json or {}
    for category, families in family_map.items():
        scores = [
            score
            for family in families
            for score in [_family_score_value(payload, family)]
            if score is not None
        ]
        if not scores:
            continue
        avg = sum(scores) / len(scores)
        sig = _category_signal_type(category, families[0])
        out[category] = {"score_pct": _round(avg), "label": _signal_type_label(sig, avg)}
    return out


def _direction_from_score(score: float | None) -> str:
    if score is None:
        return "none"
    if score > 15:
        return "long"
    if score < -15:
        return "short"
    return "none"


def _technical_variant_priority(variant: str) -> tuple[int, int, int, int]:
    try:
        mode = resolve_signal_mode(variant)
    except ValueError:
        return (0, 0, 0, 0)
    sorted_names = sorted(ALL_SIGNAL_MODE_NAMES)
    name_index = sorted_names.index(mode.name) if mode.name in sorted_names else len(sorted_names)
    return (
        1 if mode.is_expanded else 0,
        1 if mode.is_factor_x_ta else 0,
        1 if mode.is_combo else 0,
        -name_index,
    )


def _technical_signal_rank(candidate: dict[str, Any]) -> tuple[float, int, int, int, int, int, str]:
    variant = str(candidate.get("variant") or "")
    source = str(candidate.get("source") or "")
    abs_score = _safe_float(candidate.get("abs_score_pct")) or 0.0
    variant_priority = _technical_variant_priority(variant)
    return (
        abs_score,
        1 if source == "wfo" else 0,
        *variant_priority,
        str(candidate.get("label") or ""),
    )


def _build_technical_signal_candidate(
    *,
    source: str,
    variant: str,
    score: float | None,
    signal_label: str | None,
    per_family: dict[str, Any] | None,
    factor_dependencies: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any] | None:
    if score is None:
        return None
    try:
        canonical_variant = resolve_signal_mode(variant).name
    except ValueError:
        canonical_variant = str(variant or "expanded")
    rounded_score = _round(score)
    return {
        "source": "wfo" if source == "wfo" else "signal_engine",
        "variant": canonical_variant,
        "label": _signal_method_label(source, canonical_variant),
        "signal_label": signal_label or _score_to_label(score),
        "direction": _direction_from_score(score),
        "score_pct": rounded_score,
        "abs_score_pct": _round(abs(float(score))),
        "per_family": per_family or {},
        "factor_dependencies": factor_dependencies or {},
    }


def _build_best_technical_signal_payload(candidates: list[dict[str, Any] | None]) -> dict[str, Any] | None:
    usable = [candidate for candidate in candidates if candidate is not None]
    if not usable:
        return None
    return max(usable, key=_technical_signal_rank)


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _revision_horizon_keys(horizon: str) -> tuple[str, ...]:
    canonical = HORIZON_ALIASES.get(str(horizon or "").strip().lower(), horizon)
    aliases = [
        legacy
        for legacy, mapped in HORIZON_ALIASES.items()
        if mapped == canonical
    ]
    return tuple(dict.fromkeys((canonical, *aliases)))


def _score_history_revision(db: Session, horizon: str) -> dict[str, Any]:
    """Fingerprint score-history inputs consumed by dashboard Edge metrics."""
    horizon_keys = _revision_horizon_keys(horizon)
    rows = db.execute(
        text("""
        SELECT source,
               horizon,
               COUNT(*) AS row_count,
               COUNT(DISTINCT symbol) AS symbol_count,
               MIN(date) AS min_date,
               MAX(date) AS max_date,
               SUM(CASE WHEN is_oos THEN 1 ELSE 0 END) AS oos_row_count
        FROM signal_score_history
        WHERE horizon = ANY(:horizons)
          AND source = ANY(:sources)
        GROUP BY source, horizon
        ORDER BY source, horizon
        """),
        {"horizons": list(horizon_keys), "sources": list(EDGE_SCORE_HISTORY_SOURCES)},
    ).mappings().all()
    source_rows = [
        {
            "source": str(row["source"]),
            "horizon": str(row["horizon"]),
            "row_count": int(row["row_count"] or 0),
            "symbol_count": int(row["symbol_count"] or 0),
            "min_date": _iso_or_none(row["min_date"]),
            "max_date": _iso_or_none(row["max_date"]),
            "oos_row_count": int(row["oos_row_count"] or 0),
        }
        for row in rows
    ]

    job_rows = db.execute(
        text("""
        SELECT status, COUNT(*) AS job_count, MAX(updated_at) AS updated_at
        FROM score_history_job
        GROUP BY status
        ORDER BY status
        """)
    ).mappings().all()
    jobs = [
        {
            "status": str(row["status"]),
            "job_count": int(row["job_count"] or 0),
            "updated_at": _iso_or_none(row["updated_at"]),
        }
        for row in job_rows
    ]
    jobs_updated = max((j["updated_at"] for j in jobs if j["updated_at"]), default=None)

    fingerprint_payload = {
        "horizons": list(horizon_keys),
        "sources": source_rows,
        "jobs": jobs,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "horizons": list(horizon_keys),
        "total_rows": sum(row["row_count"] for row in source_rows),
        "sources": source_rows,
        "jobs": jobs,
        "jobs_updated_at": jobs_updated,
        "fingerprint": fingerprint,
    }


def _build_stock_edge_payload(db: Session, symbol: str, horizon: str) -> dict[str, Any]:
    """Materialize edge metrics into the dashboard payload.

    This bypasses Redis intentionally: dashboard snapshots should contain the
    current values needed by the stock table even when the edge cache is cold.
    """
    try:
        from ..routers.analytics import _build_edge_metrics_from_db, _edge_metrics_to_out
        from ..config import settings
    except Exception:
        return {"signal_engine": None, "wfo": None}

    out: dict[str, Any] = {}
    cost_bps = float(settings.EDGE_COST_BPS_PER_SIDE)
    for source in ("signal_engine", "wfo"):
        try:
            metrics = _build_edge_metrics_from_db(
                symbol=symbol,
                horizon=horizon,
                source=source,
                cost_bps=cost_bps,
                db=db,
                multiple_testing_count=EDGE_CANDIDATE_COUNT,
            )
            if metrics is None:
                out[source] = None
                continue
            payload = json.loads(_edge_metrics_to_out(metrics).model_dump_json())
            # Keep dashboard snapshots light; the full proof panel loads details on demand.
            payload.pop("fragility_details", None)
            if source == "wfo":
                payload = _apply_wfo_all_oos_proof_to_edge(
                    db,
                    symbol=symbol,
                    horizon=horizon,
                    variant=payload.get("variant"),
                    edge=payload,
                    cost_bps=cost_bps,
                )
            out[source] = payload
        except Exception:
            out[source] = None
    return out


def _iso_date(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return pd.Timestamp(value).date().isoformat()
    except Exception:
        return None


def _apply_wfo_all_oos_proof_to_edge(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    variant: Any,
    edge: dict[str, Any],
    cost_bps: float,
) -> dict[str, Any]:
    """Replace WFO proof metrics with all available OOS folds for the same bucket.

    The Edge builder still uses a strict selection/proof split for choosing the
    exit timing. The dashboard proof values should match the Signal Evidence
    panel, which reports all WFO OOS trades in the selected bucket after that
    timing has been chosen.
    """
    try:
        import numpy as np

        from core.quant_core.horizons import HORIZON_SPECS, canonical_horizon
        from core.quant_core.research.edge import (
            EDGE_MAX_OBSERVATIONS,
            N_MIN,
            WILSON_LB_THRESHOLD,
            ExitCandidate,
            _sample_frames,
            _freshness_summary,
            _strategy_returns_array,
            bootstrap_mean_ci,
            edge_recency_policy,
        )
        from core.quant_core.research.oos_index import oos_sample_for
        from core.quant_core.research.score_history import aggregate_subset, _bucket_for
        from core.quant_core.research.stats.hit_rate import wilson_ci
        from core.quant_core.signal_engine.modes import signal_mode_read_names
        from .. import models
        from ..routers.analytics import (
            _edge_db_horizons,
            _load_pricing_data,
            _load_score_history,
            _resolve_score_source,
        )
    except Exception:
        return edge

    symbol_upper = str(symbol or "").strip().upper()
    if not symbol_upper:
        return edge

    try:
        source_spec = _resolve_score_source("wfo", str(variant or "expanded_ta_simple"))
        canonical_h = canonical_horizon(horizon, allow_legacy=True)
        spec = HORIZON_SPECS[canonical_h]
        recency_policy = edge_recency_policy(canonical_h)
        proof_max_lookback_years = edge.get("proof_max_lookback_years")
        if proof_max_lookback_years is None:
            proof_max_lookback_years = recency_policy.proof_max_lookback_years
        db_horizons = _edge_db_horizons(canonical_h)
        variants = signal_mode_read_names(source_spec.variant)

        series_by_cat = _load_score_history(
            db,
            symbol=symbol_upper,
            source=source_spec.canonical_source,
            horizon=canonical_h,
        )
        score = aggregate_subset(series_by_cat, list(series_by_cat.keys())) if series_by_cat else None
        if score is None or score.dropna().empty:
            return edge

        prices = _load_pricing_data(db, symbol_upper)
        price_index = pd.DatetimeIndex(prices.index)

        def wfo_loader(sym: str, _h: str) -> dict[str, Any]:
            for db_h in db_horizons:
                summary = (
                    db.query(models.WfoSignalSummary)
                    .filter(
                        models.WfoSignalSummary.symbol == sym,
                        models.WfoSignalSummary.horizon == db_h,
                        models.WfoSignalSummary.variant.in_(variants),
                        models.WfoSignalSummary.status == "succeeded",
                        models.WfoSignalSummary.folds_json.isnot(None),
                    )
                    .order_by(models.WfoSignalSummary.updated_at.desc())
                    .first()
                )
                if summary is not None and summary.folds_json:
                    return {"folds_json": summary.folds_json}
            return {}

        oos_sample = oos_sample_for(
            symbol=symbol_upper,
            horizon=canonical_h,
            source="wfo",
            wfo_loader=wfo_loader,
            score_history_loader=None,
            ohlcv_index_loader=lambda _sym: price_index,
            holdout_bars=spec.signal_engine_holdout_bars,
        )
        if len(pd.DatetimeIndex(oos_sample.dates)) == 0:
            return edge

        bucket = str(edge.get("bucket") or "").strip()
        if not bucket:
            bucket = _bucket_for(float(score.dropna().iloc[-1]))
        direction = str(edge.get("direction") or "").strip().lower()
        if direction not in {"long", "short", "none"}:
            return edge

        fwd_horizon = int(edge.get("fwd_horizon_bars") or spec.reference_forward_days)
        return_calc_method = str(edge.get("return_calc_method") or "open_to_exit_ladder")
        exit_price_kind = str(edge.get("exit_price_kind") or "close").strip().lower()
        if exit_price_kind not in {"open", "close"}:
            exit_price_kind = "close"
        selected_exit = ExitCandidate(
            horizon_bars=fwd_horizon,
            exit_price_kind=exit_price_kind,  # type: ignore[arg-type]
            return_calc_method=return_calc_method,
        )

        _full_oos_df, sample_df = _sample_frames(
            score_series=score,
            prices=prices,
            oos_sample=oos_sample,
            today_bucket=bucket,
            fwd_horizon_bars=fwd_horizon,
            return_calc_method=return_calc_method,
            max_lookback_years=float(proof_max_lookback_years) if proof_max_lookback_years is not None else None,
            n_target=EDGE_MAX_OBSERVATIONS,
            exit_candidate=selected_exit,
        )
        if sample_df.empty:
            return edge

        sample_df = sample_df.sort_index()
        raw_returns = sample_df["fwd"].to_numpy(dtype="float64")
        c = float(cost_bps) * 1e-4
        gross_returns = _strategy_returns_array(raw_returns, direction, c, include_costs=False)
        net_returns = _strategy_returns_array(raw_returns, direction, c, include_costs=True)
        n = int(len(sample_df))
        hits = int(np.sum(gross_returns > 0.0))
        hit_ci_lower, hit_ci_upper = wilson_ci(hits, n)
        _full_freshness_df, freshness_df = _sample_frames(
            score_series=score,
            prices=prices,
            oos_sample=oos_sample,
            today_bucket=bucket,
            fwd_horizon_bars=fwd_horizon,
            return_calc_method=return_calc_method,
            max_lookback_years=recency_policy.freshness_lookback_years,
            n_target=EDGE_MAX_OBSERVATIONS,
            exit_candidate=selected_exit,
        )
        freshness = _freshness_summary(
            freshness_df,
            direction=direction,  # type: ignore[arg-type]
            cost_bps_per_side=cost_bps,
            min_n=recency_policy.freshness_min_n,
        )

        gross_ci = bootstrap_mean_ci(gross_returns, n_iter=1000, seed=5101)
        net_ci = bootstrap_mean_ci(net_returns, n_iter=1000, seed=5102)
        stock_ci = bootstrap_mean_ci(raw_returns, n_iter=1000, seed=5103)

        out = dict(edge)
        window_start = _iso_date(sample_df.index.min())
        window_end = _iso_date(sample_df.index.max())
        gross_mean = float(np.mean(gross_returns))
        net_mean = float(np.mean(net_returns))
        stock_mean = float(np.mean(raw_returns))
        out.update({
            "n": n,
            "window_start": window_start,
            "window_end": window_end,
            "proof_n": n,
            "proof_window_start": window_start,
            "proof_window_end": window_end,
            "proof_method": "all_wfo_oos_folds_exact_bucket",
            "action_expected_return_gross": gross_mean,
            "expected_return_gross": gross_mean,
            "action_expected_return_net": net_mean,
            "expected_return_net": net_mean,
            "stock_expected_return": stock_mean,
            "action_expected_return_gross_ci_lower": gross_ci[0],
            "action_expected_return_gross_ci_upper": gross_ci[1],
            "expected_return_gross_ci_lower": gross_ci[0],
            "expected_return_gross_ci_upper": gross_ci[1],
            "action_expected_return_net_ci_lower": net_ci[0],
            "action_expected_return_net_ci_upper": net_ci[1],
            "expected_return_net_ci_lower": net_ci[0],
            "expected_return_net_ci_upper": net_ci[1],
            "stock_expected_return_ci_lower": stock_ci[0],
            "stock_expected_return_ci_upper": stock_ci[1],
            "hit_rate": float(hits / n) if n else None,
            "hit_ci_lower": float(hit_ci_lower) if hit_ci_lower is not None else None,
            "hit_ci_upper": float(hit_ci_upper) if hit_ci_upper is not None else None,
            "proof_max_lookback_years": proof_max_lookback_years,
            "freshness_lookback_years": recency_policy.freshness_lookback_years,
            "freshness_min_n": recency_policy.freshness_min_n,
            "freshness_n": int(freshness["n"] or 0),
            "freshness_window_start": _iso_date(freshness["window_start"]),
            "freshness_window_end": _iso_date(freshness["window_end"]),
            "freshness_action_expected_return_gross": freshness["gross"],
            "freshness_action_expected_return_net": freshness["net"],
            "freshness_hit_rate": freshness["hit_rate"],
            "freshness_status": freshness["status"],
        })

        gates = dict(out.get("gates") or {}) if isinstance(out.get("gates"), dict) else {}
        if gates:
            gates["n"] = bool(n >= int(N_MIN))
            gates["wilson"] = bool(hit_ci_lower is not None and float(hit_ci_lower) > WILSON_LB_THRESHOLD)
            gates["freshness_gross"] = bool(freshness["gross_pass"])
            gates["freshness_net"] = bool(freshness["net_pass"])
            out["gates"] = gates
            if not gates["n"] or not gates["wilson"]:
                out["proven_edge_gross"] = False
                out["proven_edge_net"] = False
            if not gates["freshness_gross"]:
                out["proven_edge_gross"] = False
            if not gates["freshness_net"]:
                out["proven_edge_net"] = False
        return out
    except Exception:
        logger.exception(
            "dashboard WFO all-OOS proof build failed",
            extra={"symbol": symbol_upper, "horizon": horizon, "variant": variant},
        )
        try:
            db.rollback()
        except Exception:
            pass
        return edge


def _signal_method_label(source: str, variant: str) -> str:
    try:
        mode = resolve_signal_mode(variant)
    except ValueError:
        return f"{source} - {variant}"
    axis = "WFO" if source == "wfo" else "Signal Engine"
    universe = "Legacy" if mode.is_legacy else "Expanded"
    conditioning = "Factor x TA" if mode.is_factor_x_ta else "TA"
    complexity = "Combo" if mode.is_combo else "Simple"
    return f"{axis} - {universe} {conditioning} {complexity}"


def _best_signal_rank(edge: dict[str, Any]) -> tuple[int, float, float] | None:
    direction = str(edge.get("direction") or "none")
    if not _is_actionable_edge_bucket(edge.get("bucket"), direction):
        return None
    n = _safe_float(edge.get("n")) or 0.0
    if n < 30:
        return None
    gates = edge.get("gates") if isinstance(edge.get("gates"), dict) else {}
    if gates and not bool(gates.get("n", False)):
        return None

    expected = _safe_float(edge.get("action_expected_return_net"))
    if expected is None:
        expected = _safe_float(edge.get("expected_return_net"))
    if expected is None or expected <= 0:
        return None

    lower = _safe_float(edge.get("action_expected_return_net_ci_lower"))
    if lower is None:
        lower = _safe_float(edge.get("expected_return_net_ci_lower"))
    penalized = lower if lower is not None else expected * 0.5
    proven = bool(edge.get("proven_edge_net"))
    return (2 if proven else 1, penalized, expected)


def _build_best_signal_payload(db: Session, symbol: str, horizon: str) -> dict[str, Any] | None:
    """Pick the best currently tradable WFO method by net penalized edge."""
    try:
        from ..routers.analytics import _build_edge_metrics_from_db, _edge_metrics_to_out
        from ..config import settings
    except Exception:
        return None

    cost_bps = float(settings.EDGE_COST_BPS_PER_SIDE)
    best: tuple[tuple[int, float, float], dict[str, Any]] | None = None
    for source in ("wfo",):
        for variant in EDGE_SIGNAL_MODES:
            try:
                metrics = _build_edge_metrics_from_db(
                    symbol=symbol,
                    horizon=horizon,
                    source=source,
                    variant=variant,
                    cost_bps=cost_bps,
                    db=db,
                    multiple_testing_count=EDGE_CANDIDATE_COUNT,
                )
                if metrics is None:
                    continue
                edge = json.loads(_edge_metrics_to_out(metrics).model_dump_json())
                if source == "wfo":
                    edge = _apply_wfo_all_oos_proof_to_edge(
                        db,
                        symbol=symbol,
                        horizon=horizon,
                        variant=variant,
                        edge=edge,
                        cost_bps=cost_bps,
                    )
            except Exception:
                logger.exception(
                    "best-signal edge build failed",
                    extra={"symbol": symbol, "horizon": horizon, "source": source, "variant": variant},
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
                "source": source,
                "variant": variant,
                "label": _signal_method_label(source, variant),
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
                "score": rank[1],
            }
            if best is None or rank > best[0]:
                best = (rank, payload)

    return best[1] if best is not None else None


def _portfolio_edge_member_from_stock(
    db: Session,
    horizon: str,
    stock: dict[str, Any],
    member_cache: dict[tuple[str, str, str, str, str], Any],
) -> Any | None:
    best_signal = stock.get("best_signal")
    if not isinstance(best_signal, dict):
        return None

    symbol = str(stock.get("symbol") or "").strip().upper()
    source = str(best_signal.get("source") or "").strip()
    variant = str(best_signal.get("variant") or "").strip()
    bucket = str(best_signal.get("bucket") or "").strip().lower()
    direction = str(best_signal.get("direction") or "").strip().lower()
    if not symbol or not source or not variant:
        return None
    if not _is_actionable_edge_bucket(bucket, direction):
        return None

    cache_key = (symbol, source, variant, bucket, direction)
    if cache_key in member_cache:
        return member_cache[cache_key]

    try:
        from core.quant_core.horizons import HORIZON_SPECS, canonical_horizon
        from core.quant_core.research.oos_index import oos_sample_for
        from core.quant_core.research.portfolio_edge import PortfolioEdgeMember
        from core.quant_core.research.score_history import aggregate_subset
        from core.quant_core.signal_engine.modes import signal_mode_read_names
        from .. import models
        from ..routers.analytics import (
            _edge_db_horizons,
            _load_pricing_data,
            _load_score_history,
            _resolve_score_source,
            _signal_engine_selection_sample,
            _split_wfo_oos_for_edge,
        )
    except Exception:
        member_cache[cache_key] = None
        return None

    try:
        canonical_h = canonical_horizon(horizon, allow_legacy=True)
        spec = HORIZON_SPECS[canonical_h]
        source_spec = _resolve_score_source(source, variant)
        public_source = "wfo" if source_spec.axis == "wfo" else "signal_engine"
        db_sources = source_spec.read_sources
        db_horizons = _edge_db_horizons(canonical_h)
        variants = signal_mode_read_names(source_spec.variant)

        series_by_cat = _load_score_history(
            db,
            symbol=symbol,
            source=source_spec.canonical_source,
            horizon=canonical_h,
        )
        if not series_by_cat:
            member_cache[cache_key] = None
            return None
        score = aggregate_subset(series_by_cat, list(series_by_cat.keys()))
        if score is None or score.dropna().empty:
            member_cache[cache_key] = None
            return None

        prices = _load_pricing_data(db, symbol)
        ohlcv_idx = pd.DatetimeIndex(prices.index)

        def wfo_loader(sym: str, _h: str) -> dict[str, Any]:
            for db_h in db_horizons:
                summary = (
                    db.query(models.WfoSignalSummary)
                    .filter(
                        models.WfoSignalSummary.symbol == sym,
                        models.WfoSignalSummary.horizon == db_h,
                        models.WfoSignalSummary.variant.in_(variants),
                        models.WfoSignalSummary.status == "succeeded",
                        models.WfoSignalSummary.folds_json.isnot(None),
                    )
                    .order_by(models.WfoSignalSummary.updated_at.desc())
                    .first()
                )
                if summary is not None and summary.folds_json:
                    return {"folds_json": summary.folds_json}
            return {}

        def score_history_loader(sym: str, _h: str) -> list[dict[str, Any]]:
            rows = (
                db.query(models.SignalScoreHistory)
                .filter(
                    models.SignalScoreHistory.symbol == sym,
                    models.SignalScoreHistory.source.in_(db_sources),
                    models.SignalScoreHistory.horizon.in_(db_horizons),
                )
                .order_by(models.SignalScoreHistory.date.asc())
                .all()
            )
            return [
                {"date": row.date, "is_oos": bool(getattr(row, "is_oos", False))}
                for row in rows
            ]

        oos_sample = oos_sample_for(
            symbol=symbol,
            horizon=canonical_h,
            source=public_source,
            wfo_loader=wfo_loader if public_source == "wfo" else None,
            score_history_loader=score_history_loader if public_source == "signal_engine" else None,
            ohlcv_index_loader=lambda _sym: ohlcv_idx,
            holdout_bars=spec.signal_engine_holdout_bars,
        )
        if public_source == "wfo":
            selection_oos_sample, _strict_proof_oos_sample = _split_wfo_oos_for_edge(oos_sample)
            proof_oos_sample = oos_sample
        else:
            selection_oos_sample = _signal_engine_selection_sample(
                oos_sample,
                score_index=pd.DatetimeIndex(score.dropna().index),
                holdout_bars=spec.signal_engine_holdout_bars,
            )
            proof_oos_sample = oos_sample

        member = PortfolioEdgeMember(
            symbol=symbol,
            bucket=bucket,
            direction=direction,  # type: ignore[arg-type]
            score_series=score,
            prices=prices,
            selection_oos_dates=pd.DatetimeIndex(selection_oos_sample.dates),
            proof_oos_dates=pd.DatetimeIndex(proof_oos_sample.dates),
        )
        member_cache[cache_key] = member
        return member
    except Exception:
        logger.exception("portfolio-edge member build failed", extra={"symbol": symbol, "horizon": horizon})
        try:
            db.rollback()
        except Exception:
            pass
        member_cache[cache_key] = None
        return None


def _build_portfolio_edge_payload_for_stocks(
    db: Session,
    horizon: str,
    stocks: list[dict[str, Any]],
    *,
    total_count: int | None = None,
    member_cache: dict[tuple[str, str, str, str, str], Any] | None = None,
) -> dict[str, Any] | None:
    try:
        from core.quant_core.horizons import HORIZON_SPECS, canonical_horizon
        from core.quant_core.research.portfolio_edge import build_portfolio_edge_payload
        from ..config import settings
    except Exception:
        return None

    try:
        canonical_h = canonical_horizon(horizon, allow_legacy=True)
    except ValueError:
        return None

    spec = HORIZON_SPECS[canonical_h]
    cache = member_cache if member_cache is not None else {}
    members = [
        member
        for stock in stocks
        for member in [_portfolio_edge_member_from_stock(db, canonical_h, stock, cache)]
        if member is not None
    ]
    return build_portfolio_edge_payload(
        members=members,
        horizon=canonical_h,
        total_count=int(total_count if total_count is not None else len(stocks)),
        fwd_horizon_bars=spec.reference_forward_days,
        holding_period_candidates=tuple(range(spec.prediction_min_days, spec.prediction_max_days + 1)),
        cost_bps_per_side=float(settings.EDGE_COST_BPS_PER_SIDE),
    )


def build_dashboard_portfolio_edge_for_symbols(
    db: Session,
    horizon: str,
    symbols: list[str],
    *,
    best_signal_cache: dict[str, dict[str, Any] | None] | None = None,
    member_cache: dict[tuple[str, str, str, str, str], Any] | None = None,
) -> dict[str, Any] | None:
    """Build the same portfolio Edge metric for custom dashboard indices."""
    seen: set[str] = set()
    normalized: list[str] = []
    for raw in symbols:
        symbol = str(raw or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        normalized.append(symbol)

    signal_cache = best_signal_cache if best_signal_cache is not None else {}
    stock_payloads: list[dict[str, Any]] = []
    for symbol in normalized:
        if symbol not in signal_cache:
            signal_cache[symbol] = _build_best_signal_payload(db, symbol, horizon)
        stock_payloads.append({"symbol": symbol, "best_signal": signal_cache.get(symbol)})

    return _build_portfolio_edge_payload_for_stocks(
        db,
        horizon,
        stock_payloads,
        total_count=len(normalized),
        member_cache=member_cache,
    )


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def _load_dashboard_market_stats(db: Session, symbols: list[str]) -> dict[str, dict[str, Any]]:
    if not symbols:
        return {}
    try:
        rows = db.execute(
            text("""
            SELECT DISTINCT ON (symbol)
                   symbol, close_last, prev_close, adv_20d
            FROM market_data_store
            WHERE lower(timeframe) = '1d'
              AND symbol = ANY(:symbols)
            ORDER BY symbol,
                     data_as_of DESC NULLS LAST,
                     updated_at DESC NULLS LAST,
                     CASE WHEN timeframe = '1D' THEN 0 ELSE 1 END
            """),
            {"symbols": symbols},
        ).mappings().all()
        return {str(row["symbol"]): dict(row) for row in rows}
    except Exception:
        db.rollback()
        return {}

def build_dashboard_payload(db: Session, horizon: str, *, include_edge: bool = False) -> dict[str, Any]:
    """Compute the full dashboard payload for *horizon* using *db*.

    ``horizon`` must already be normalized (weekly/monthly/quarterly).
    This is the single source of truth for dashboard aggregation; both the
    live-compute API path and the snapshot worker call this function.
    """
    stocks_info = list_signal_universe(db)
    stock_dict = {s.symbol: s for s in stocks_info}
    symbols = list(stock_dict.keys())

    market_stats_by_symbol = _load_dashboard_market_stats(db, symbols)

    se_rows = db.execute(
        text("""
        SELECT symbol, aggregate_score_pct, expanded_aggregate_score_pct, signal_label,
               per_family_json, technical_levels_json, support_resistance_json
        FROM signal_engine_global_result
        WHERE horizon = :horizon AND variant = 'expanded' AND status = 'succeeded'
        """),
        {"horizon": horizon},
    ).fetchall()
    se_by_symbol = {row[0]: row for row in se_rows}

    fx_global_rows = db.execute(
        text(f"""
        SELECT symbol, aggregate_score_pct, expanded_aggregate_score_pct, signal_label, per_family_json, variant
        FROM signal_engine_global_result
        WHERE horizon = :horizon
          AND variant IN ({FACTOR_X_TA_SIMPLE_VARIANT_SQL})
          AND status = 'succeeded'
        ORDER BY CASE WHEN variant = 'expanded_factor_x_ta_simple' THEN 0 ELSE 1 END
        """),
        {"horizon": horizon},
    ).fetchall()
    fx_global_by_symbol: dict[str, Any] = {}
    for row in fx_global_rows:
        fx_global_by_symbol.setdefault(row[0], row)

    fx_family_rows = db.execute(
        text(f"""
        SELECT symbol, family, category, family_score_pct, signal_label,
               representatives_json, family_detail_json, variant
        FROM signal_engine_family_result
        WHERE horizon = :horizon
          AND variant IN ({FACTOR_X_TA_SIMPLE_VARIANT_SQL})
          AND status IN ('succeeded', 'no_signal')
        ORDER BY CASE WHEN variant = 'expanded_factor_x_ta_simple' THEN 0 ELSE 1 END
        """),
        {"horizon": horizon},
    ).fetchall()
    fx_family_by_symbol: dict[str, list[Any]] = defaultdict(list)
    seen_fx_family: set[tuple[str, str]] = set()
    for row in fx_family_rows:
        key = (str(row[0]), str(row[1]))
        if key in seen_fx_family:
            continue
        seen_fx_family.add(key)
        fx_family_by_symbol[str(row[0])].append(row)

    wfo_rows = db.execute(
        text("""
        SELECT symbol, status, global_score_pct, signal_label,
               weight_tendance, weight_momentum, weight_oscillation, weight_volume,
               sr_support_level, sr_resistance_level,
               sr_support_method, sr_resistance_method,
               best_category, consensus_wfe_pct, consensus_robustness
        FROM wfo_global_signal
        WHERE horizon = :horizon AND variant = 'expanded'
        """),
        {"horizon": horizon},
    ).fetchall()
    wfo_global_by_symbol = {row[0]: row for row in wfo_rows}

    wfo_summary_rows = db.execute(
        text("""
        SELECT symbol, category, score_pct, signal_label
        FROM wfo_signal_summary
        WHERE horizon = :horizon AND variant = 'expanded' AND status = 'succeeded'
        """),
        {"horizon": horizon},
    ).fetchall()
    wfo_summary_by_symbol: dict[str, dict[str, Any]] = {}
    for row in wfo_summary_rows:
        sym, cat, score, label = row
        wfo_summary_by_symbol.setdefault(sym, {})[cat] = {
            "score_pct": _round(score), "label": label
        }

    technical_se_rows = db.execute(
        text("""
        SELECT symbol, variant, aggregate_score_pct, expanded_aggregate_score_pct,
               signal_label, per_family_json
        FROM signal_engine_global_result
        WHERE horizon = :horizon AND status = 'succeeded'
        """),
        {"horizon": horizon},
    ).fetchall()
    technical_se_by_symbol: dict[str, list[Any]] = defaultdict(list)
    for row in technical_se_rows:
        technical_se_by_symbol[str(row[0])].append(row)

    technical_se_family_rows = db.execute(
        text("""
        SELECT symbol, family, category, family_score_pct, signal_label,
               representatives_json, family_detail_json, variant
        FROM signal_engine_family_result
        WHERE horizon = :horizon AND status IN ('succeeded', 'no_signal')
        """),
        {"horizon": horizon},
    ).fetchall()
    technical_se_family_by_symbol_variant: dict[tuple[str, str], list[Any]] = defaultdict(list)
    seen_technical_family: set[tuple[str, str, str]] = set()
    for row in technical_se_family_rows:
        try:
            canonical_variant = resolve_signal_mode(str(row[7] or "")).name
        except ValueError:
            canonical_variant = str(row[7] or "")
        key = (str(row[0]), canonical_variant, str(row[1]))
        if key in seen_technical_family:
            continue
        seen_technical_family.add(key)
        technical_se_family_by_symbol_variant[(str(row[0]), canonical_variant)].append(row)

    technical_wfo_rows = db.execute(
        text("""
        SELECT symbol, variant, status, global_score_pct, raw_score_pct, signal_label
        FROM wfo_global_signal
        WHERE horizon = :horizon
        """),
        {"horizon": horizon},
    ).fetchall()
    technical_wfo_by_symbol: dict[str, list[Any]] = defaultdict(list)
    for row in technical_wfo_rows:
        technical_wfo_by_symbol[str(row[0])].append(row)

    technical_wfo_summary_rows = db.execute(
        text("""
        SELECT symbol, variant, category, score_pct, signal_label
        FROM wfo_signal_summary
        WHERE horizon = :horizon AND status = 'succeeded'
        """),
        {"horizon": horizon},
    ).fetchall()
    technical_wfo_summary_by_symbol_variant: dict[tuple[str, str], dict[str, Any]] = defaultdict(dict)
    for row in technical_wfo_summary_rows:
        try:
            canonical_variant = resolve_signal_mode(str(row[1] or "")).name
        except ValueError:
            canonical_variant = str(row[1] or "")
        sym, _variant, category, score, label = row
        technical_wfo_summary_by_symbol_variant[(str(sym), canonical_variant)][str(category)] = {
            "score_pct": _round(score),
            "label": label,
        }

    stocks_out: list[dict[str, Any]] = []

    for symbol, stock in stock_dict.items():
        sector = dashboard_group_label(stock)

        se_row = se_by_symbol.get(symbol)
        se_scores_obj: dict[str, Any] = {
            "variant": "expanded",
            "aggregate_score_pct": None,
            "aggregate_signal_label": "Indisponible",
            "expanded_aggregate_score_pct": None,
            "expanded_aggregate_signal_label": "Indisponible",
            "factor_x_ta_aggregate_score_pct": None,
            "factor_x_ta_aggregate_signal_label": "Indisponible",
            "per_family": {},
            "expanded_per_family": {},
            "factor_x_ta_per_family": {},
            "factor_dependencies": {},
            "technical_levels": None,
            "support_resistance": None,
        }

        if se_row:
            se_scores_obj["aggregate_score_pct"] = _round(se_row[1])
            se_scores_obj["expanded_aggregate_score_pct"] = _round(se_row[2])
            se_scores_obj["aggregate_signal_label"] = se_row[3] or "Indisponible"
            se_scores_obj["expanded_aggregate_signal_label"] = _score_to_label(se_row[2])

            per_family_json: dict[str, Any] = se_row[4] or {}

            per_family: dict[str, Any] = {}
            for cat, fams in LEGACY_CATEGORY_FAMILIES.items():
                scores = [
                    score
                    for f in fams
                    for score in [_family_score_value(per_family_json, f)]
                    if score is not None
                ]
                if scores:
                    avg = sum(scores) / len(scores)
                    sig = _category_signal_type(cat, fams[0])
                    per_family[cat] = {"score_pct": _round(avg), "label": _signal_type_label(sig, avg)}
            se_scores_obj["per_family"] = per_family

            exp_per_family: dict[str, Any] = {}
            for cat, fams in EXPANDED_CATEGORY_FAMILIES.items():
                scores = [
                    score
                    for f in fams
                    for score in [_family_score_value(per_family_json, f)]
                    if score is not None
                ]
                if scores:
                    avg = sum(scores) / len(scores)
                    sig = _category_signal_type(cat, fams[0])
                    exp_per_family[cat] = {"score_pct": _round(avg), "label": _signal_type_label(sig, avg)}
            se_scores_obj["expanded_per_family"] = exp_per_family
            se_scores_obj["technical_levels"] = se_row[5]
            se_scores_obj["support_resistance"] = se_row[6]

        fx_global_row = fx_global_by_symbol.get(symbol)
        fx_family_rows_for_symbol = fx_family_by_symbol.get(symbol, [])
        if fx_global_row or fx_family_rows_for_symbol:
            fx_per_family, fx_dependencies = _factor_family_payload(fx_family_rows_for_symbol)
            fx_score = None
            fx_label = "Indisponible"
            if fx_global_row:
                fx_score = _safe_float(fx_global_row[2])
                if fx_score is None:
                    fx_score = _safe_float(fx_global_row[1])
                fx_label = fx_global_row[3] or _score_to_label(fx_score)
            elif fx_per_family:
                scores = [
                    _safe_float(item.get("score_pct"))
                    for item in fx_per_family.values()
                    if isinstance(item, dict)
                ]
                numeric_scores = [score for score in scores if score is not None]
                fx_score = sum(numeric_scores) / len(numeric_scores) if numeric_scores else None
                fx_label = _score_to_label(fx_score)
            se_scores_obj["factor_x_ta_aggregate_score_pct"] = _round(fx_score)
            se_scores_obj["factor_x_ta_aggregate_signal_label"] = fx_label
            se_scores_obj["factor_x_ta_per_family"] = fx_per_family
            se_scores_obj["factor_dependencies"] = fx_dependencies

        wfo_row = wfo_global_by_symbol.get(symbol)
        wfo_scores_obj: dict[str, Any] | None = None
        if wfo_row and wfo_row[1] == "succeeded":
            w_cat = wfo_summary_by_symbol.get(symbol, {})
            per_fam = {c: w_cat[c] for c in EXPANDED_CATEGORY_FAMILIES if c in w_cat}
            wfo_scores_obj = {
                "variant": "expanded",
                "aggregate_score_pct": _round(wfo_row[2]),
                "aggregate_signal_label": wfo_row[3],
                "per_family": per_fam,
                "best_category": wfo_row[12],
                "consensus_wfe_pct": _round(wfo_row[13]),
                "consensus_robustness": _round(wfo_row[14]),
                "status": "succeeded",
                "technical_levels": {
                    "support_buy_trigger": _round(wfo_row[8]),
                    "resistance_sell_trigger": _round(wfo_row[9]),
                    "support_reference": _round(wfo_row[8]),
                    "support_method": wfo_row[10] or "",
                    "resistance_method": wfo_row[11] or "",
                    "method": "wfo_sr",
                },
            }

        market_stats = market_stats_by_symbol.get(symbol, {})
        last_price = _safe_float(market_stats.get("close_last"))
        prev_close = _safe_float(market_stats.get("prev_close"))
        adv_20d = _safe_float(market_stats.get("adv_20d"))

        technical_candidates: list[dict[str, Any] | None] = []
        for row in technical_se_by_symbol.get(symbol, []):
            variant = str(row[1] or "")
            try:
                mode = resolve_signal_mode(variant)
                canonical_variant = mode.name
            except ValueError:
                mode = resolve_signal_mode("expanded_ta_simple")
                canonical_variant = variant
            aggregate_score = _safe_float(row[2])
            expanded_score = _safe_float(row[3])
            score = aggregate_score if mode.is_legacy and aggregate_score is not None else expanded_score
            if score is None:
                score = aggregate_score
            family_rows = technical_se_family_by_symbol_variant.get((symbol, mode.name), [])
            factor_per_family: dict[str, Any] = {}
            factor_dependencies: dict[str, list[dict[str, Any]]] = {}
            if mode.is_factor_x_ta and family_rows:
                factor_per_family, factor_dependencies = _factor_family_payload(family_rows)
            technical_candidates.append(_build_technical_signal_candidate(
                source="signal_engine",
                variant=canonical_variant,
                score=score,
                signal_label=row[4] or _score_to_label(score),
                per_family=factor_per_family or _category_scores_from_family_payload(row[5] or {}, canonical_variant),
                factor_dependencies=factor_dependencies,
            ))

        for row in technical_wfo_by_symbol.get(symbol, []):
            if row[2] != "succeeded":
                continue
            variant = str(row[1] or "")
            try:
                canonical_variant = resolve_signal_mode(variant).name
            except ValueError:
                canonical_variant = variant
            score = _safe_float(row[3])
            if score is None:
                score = _safe_float(row[4])
            wfo_per_family = technical_wfo_summary_by_symbol_variant.get((symbol, canonical_variant), {})
            technical_candidates.append(_build_technical_signal_candidate(
                source="wfo",
                variant=canonical_variant,
                score=score,
                signal_label=row[5] or _score_to_label(score),
                per_family={c: wfo_per_family[c] for c in EXPANDED_CATEGORY_FAMILIES if c in wfo_per_family},
            ))

        stock_obj: dict[str, Any] = {
            "symbol": symbol,
            "display_name": stock.display_name,
            "sector": sector,
            "asset_type": stock.asset_type,
            "market_region": stock.market_region,
            "asset_class": stock.asset_class,
            "last_price": last_price,
            "prev_close": prev_close,
            "var1j_pct": _variation_pct(last_price, prev_close),
            "adv": adv_20d,
            "edge": _build_stock_edge_payload(db, symbol, horizon) if include_edge else {},
            "best_signal": _build_best_signal_payload(db, symbol, horizon) if include_edge else None,
            "best_technical_signal": _build_best_technical_signal_payload(technical_candidates),
            "scores": {"signal_engine": se_scores_obj, "wfo": wfo_scores_obj},
            # flat backwards-compat fields
            "aggregate_score_pct": se_scores_obj["aggregate_score_pct"],
            "aggregate_signal_label": se_scores_obj["aggregate_signal_label"],
            "expanded_aggregate_score_pct": se_scores_obj["expanded_aggregate_score_pct"],
            "expanded_aggregate_signal_label": se_scores_obj["expanded_aggregate_signal_label"],
            "factor_x_ta_aggregate_score_pct": se_scores_obj["factor_x_ta_aggregate_score_pct"],
            "factor_x_ta_aggregate_signal_label": se_scores_obj["factor_x_ta_aggregate_signal_label"],
            "per_family": se_scores_obj["per_family"],
            "expanded_per_family": se_scores_obj["expanded_per_family"],
            "factor_x_ta_per_family": se_scores_obj["factor_x_ta_per_family"],
        }
        stocks_out.append(stock_obj)

    # ------------------------------------------------------------------
    # Sector aggregation
    # ------------------------------------------------------------------
    portfolio_member_cache: dict[tuple[str, str, str, str, str], Any] = {}
    by_sector: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in stocks_out:
        by_sector[s["sector"]].append(s)

    sectors_out: list[dict[str, Any]] = []
    for sector_name, sector_stocks in sorted(by_sector.items()):
        se_aggs: list[float] = []
        se_exp_aggs: list[float] = []
        se_fx_aggs: list[float] = []
        wfo_aggs: list[float] = []
        se_cats: dict[str, list[float]] = defaultdict(list)
        se_exp_cats: dict[str, list[float]] = defaultdict(list)
        se_fx_cats: dict[str, list[float]] = defaultdict(list)
        wfo_cats: dict[str, list[float]] = defaultdict(list)

        for st in sector_stocks:
            se = st["scores"]["signal_engine"]
            if se["aggregate_score_pct"] is not None:
                se_aggs.append(se["aggregate_score_pct"])
            if se.get("expanded_aggregate_score_pct") is not None:
                se_exp_aggs.append(se["expanded_aggregate_score_pct"])
            if se.get("factor_x_ta_aggregate_score_pct") is not None:
                se_fx_aggs.append(se["factor_x_ta_aggregate_score_pct"])
            for c, d in se.get("per_family", {}).items():
                se_cats[c].append(d["score_pct"])
            for c, d in se.get("expanded_per_family", {}).items():
                se_exp_cats[c].append(d["score_pct"])
            for c, d in se.get("factor_x_ta_per_family", {}).items():
                se_fx_cats[c].append(d["score_pct"])
            wfo = st["scores"].get("wfo")
            if wfo:
                if wfo["aggregate_score_pct"] is not None:
                    wfo_aggs.append(wfo["aggregate_score_pct"])
                for c, d in wfo.get("per_family", {}).items():
                    wfo_cats[c].append(d["score_pct"])

        se_per_fam = _avg_cats(dict(se_cats), LEGACY_CATEGORY_FAMILIES)
        se_exp_per_fam = _avg_cats(dict(se_exp_cats), EXPANDED_CATEGORY_FAMILIES)
        se_fx_per_fam = _avg_cats(dict(se_fx_cats), EXPANDED_CATEGORY_FAMILIES)
        wfo_per_fam = _avg_cats(dict(wfo_cats), EXPANDED_CATEGORY_FAMILIES)
        se_agg_avg = sum(se_aggs) / len(se_aggs) if se_aggs else None
        se_exp_agg_avg = sum(se_exp_aggs) / len(se_exp_aggs) if se_exp_aggs else None
        se_fx_agg_avg = sum(se_fx_aggs) / len(se_fx_aggs) if se_fx_aggs else None
        wfo_agg_avg = sum(wfo_aggs) / len(wfo_aggs) if wfo_aggs else None

        se_obj: dict[str, Any] = {
            "variant": "expanded",
            "aggregate_score_pct": _round(se_agg_avg),
            "aggregate_signal_label": _score_to_label(se_agg_avg),
            "expanded_aggregate_score_pct": _round(se_exp_agg_avg),
            "expanded_aggregate_signal_label": _score_to_label(se_exp_agg_avg),
            "factor_x_ta_aggregate_score_pct": _round(se_fx_agg_avg),
            "factor_x_ta_aggregate_signal_label": _score_to_label(se_fx_agg_avg),
            "per_family": se_per_fam,
            "expanded_per_family": se_exp_per_fam,
            "factor_x_ta_per_family": se_fx_per_fam,
            "factor_dependencies": {},
        }
        wfo_obj: dict[str, Any] | None = None
        if wfo_aggs:
            wfo_obj = {
                "variant": "expanded",
                "aggregate_score_pct": _round(wfo_agg_avg),
                "aggregate_signal_label": _score_to_label(wfo_agg_avg),
                "per_family": wfo_per_fam,
            }

        sectors_out.append({
            "sector": sector_name,
            "stock_count": len(sector_stocks),
            "scores": {"signal_engine": se_obj, "wfo": wfo_obj},
            "portfolio_edge": _build_portfolio_edge_payload_for_stocks(
                db,
                horizon,
                sector_stocks,
                member_cache=portfolio_member_cache,
            ) if include_edge else None,
            "aggregate_score_pct": se_obj["aggregate_score_pct"],
            "aggregate_signal_label": se_obj["aggregate_signal_label"],
            "expanded_aggregate_score_pct": se_obj["expanded_aggregate_score_pct"],
            "expanded_aggregate_signal_label": se_obj["expanded_aggregate_signal_label"],
            "factor_x_ta_aggregate_score_pct": se_obj["factor_x_ta_aggregate_score_pct"],
            "factor_x_ta_aggregate_signal_label": se_obj["factor_x_ta_aggregate_signal_label"],
            "per_family": se_per_fam,
            "expanded_per_family": se_exp_per_fam,
            "factor_x_ta_per_family": se_fx_per_fam,
        })

    # ------------------------------------------------------------------
    # Index (MASI) aggregation
    # ------------------------------------------------------------------
    se_aggs = []
    se_exp_aggs = []
    se_fx_aggs = []
    wfo_aggs = []
    se_cats_idx: dict[str, list[float]] = defaultdict(list)
    se_exp_cats_idx: dict[str, list[float]] = defaultdict(list)
    se_fx_cats_idx: dict[str, list[float]] = defaultdict(list)
    wfo_cats_idx: dict[str, list[float]] = defaultdict(list)
    se_breadth: dict[str, int] = {"achat": 0, "neutre": 0, "vente": 0, "indisponible": 0}
    wfo_breadth: dict[str, int] = {"achat": 0, "neutre": 0, "vente": 0, "indisponible": 0}
    masi_index_stocks = [st for st in stocks_out if is_masi_dashboard_member(st)]

    for st in masi_index_stocks:
        se = st["scores"]["signal_engine"]
        score = se["aggregate_score_pct"]
        if score is not None:
            se_aggs.append(score)
            if score >= 66.6: se_breadth["achat"] += 1
            elif score <= 33.3: se_breadth["vente"] += 1
            else: se_breadth["neutre"] += 1
        else:
            se_breadth["indisponible"] += 1
        if se.get("expanded_aggregate_score_pct") is not None:
            se_exp_aggs.append(se["expanded_aggregate_score_pct"])
        if se.get("factor_x_ta_aggregate_score_pct") is not None:
            se_fx_aggs.append(se["factor_x_ta_aggregate_score_pct"])
        for c, d in se.get("per_family", {}).items():
            se_cats_idx[c].append(d["score_pct"])
        for c, d in se.get("expanded_per_family", {}).items():
            se_exp_cats_idx[c].append(d["score_pct"])
        for c, d in se.get("factor_x_ta_per_family", {}).items():
            se_fx_cats_idx[c].append(d["score_pct"])

        wfo = st["scores"].get("wfo")
        if wfo:
            score = wfo["aggregate_score_pct"]
            if score is not None:
                wfo_aggs.append(score)
                if score >= 66.6: wfo_breadth["achat"] += 1
                elif score <= 33.3: wfo_breadth["vente"] += 1
                else: wfo_breadth["neutre"] += 1
            else:
                wfo_breadth["indisponible"] += 1
        else:
            wfo_breadth["indisponible"] += 1

    se_per_fam_idx = _avg_cats(dict(se_cats_idx), LEGACY_CATEGORY_FAMILIES)
    se_exp_per_fam_idx = _avg_cats(dict(se_exp_cats_idx), EXPANDED_CATEGORY_FAMILIES)
    se_fx_per_fam_idx = _avg_cats(dict(se_fx_cats_idx), EXPANDED_CATEGORY_FAMILIES)
    wfo_per_fam_idx = _avg_cats(dict(wfo_cats_idx), EXPANDED_CATEGORY_FAMILIES)
    se_agg_avg = sum(se_aggs) / len(se_aggs) if se_aggs else None
    se_exp_agg_avg = sum(se_exp_aggs) / len(se_exp_aggs) if se_exp_aggs else None
    se_fx_agg_avg = sum(se_fx_aggs) / len(se_fx_aggs) if se_fx_aggs else None
    wfo_agg_avg = sum(wfo_aggs) / len(wfo_aggs) if wfo_aggs else None

    se_obj_idx: dict[str, Any] = {
        "variant": "expanded",
        "aggregate_score_pct": _round(se_agg_avg),
        "aggregate_signal_label": _score_to_label(se_agg_avg),
        "expanded_aggregate_score_pct": _round(se_exp_agg_avg),
        "expanded_aggregate_signal_label": _score_to_label(se_exp_agg_avg),
        "factor_x_ta_aggregate_score_pct": _round(se_fx_agg_avg),
        "factor_x_ta_aggregate_signal_label": _score_to_label(se_fx_agg_avg),
        "per_family": se_per_fam_idx,
        "expanded_per_family": se_exp_per_fam_idx,
        "factor_x_ta_per_family": se_fx_per_fam_idx,
        "factor_dependencies": {},
        "breadth": se_breadth,
    }
    wfo_obj_idx: dict[str, Any] | None = None
    if wfo_aggs:
        wfo_obj_idx = {
            "variant": "expanded",
            "aggregate_score_pct": _round(wfo_agg_avg),
            "aggregate_signal_label": _score_to_label(wfo_agg_avg),
            "per_family": wfo_per_fam_idx,
            "breadth": wfo_breadth,
        }

    generated_at = datetime.now(tz=timezone.utc).isoformat()

    return {
        "payload_version": DASHBOARD_PAYLOAD_VERSION,
        "generated_at": generated_at,
        "horizon": horizon,
        "horizon_label": HORIZONS[horizon],
        "stocks": stocks_out,
        "sectors": sectors_out,
        "index": {
            "name": "MASI",
            "stock_count": len(masi_index_stocks),
            "scores": {"signal_engine": se_obj_idx, "wfo": wfo_obj_idx},
            "portfolio_edge": _build_portfolio_edge_payload_for_stocks(
                db,
                horizon,
                masi_index_stocks,
                member_cache=portfolio_member_cache,
            ) if include_edge else None,
            "aggregate_score_pct": se_obj_idx["aggregate_score_pct"],
            "aggregate_signal_label": se_obj_idx["aggregate_signal_label"],
            "expanded_aggregate_score_pct": se_obj_idx["expanded_aggregate_score_pct"],
            "expanded_aggregate_signal_label": se_obj_idx["expanded_aggregate_signal_label"],
            "factor_x_ta_aggregate_score_pct": se_obj_idx["factor_x_ta_aggregate_score_pct"],
            "factor_x_ta_aggregate_signal_label": se_obj_idx["factor_x_ta_aggregate_signal_label"],
            "per_family": se_per_fam_idx,
            "expanded_per_family": se_exp_per_fam_idx,
            "factor_x_ta_per_family": se_fx_per_fam_idx,
        },
        "custom_index_definitions": [],
    }


def derive_upstream_rev(db: Session, horizon: str) -> dict[str, Any]:
    """Return the upstream revision tuple consumed to build a snapshot.

    Used to populate ``dashboard_snapshot.upstream_rev`` so a CAS upsert
    can guard against stale overwrites.
    """
    data_as_of_row = db.execute(
        text("SELECT MAX(data_as_of) FROM market_data_store WHERE lower(timeframe) = '1d'")
    ).scalar()
    engine_run_row = db.execute(
        text("""
        SELECT MAX(batch_id) FROM signal_engine_batch_job
        WHERE horizon = :horizon AND status = 'succeeded'
        """),
        {"horizon": horizon},
    ).scalar()
    engine_updated_at = db.execute(
        text("""
        SELECT MAX(updated_at) FROM signal_engine_global_result
        WHERE horizon = :horizon AND status = 'succeeded'
        """),
        {"horizon": horizon},
    ).scalar()
    wfo_run_row = db.execute(
        text("""
        SELECT MAX(id::text)
        FROM wfo_global_signal
        WHERE horizon = :horizon AND variant = 'expanded'
        """),
        {"horizon": horizon},
    ).scalar()
    wfo_updated_at = db.execute(
        text("""
        SELECT MAX(updated_at) FROM wfo_global_signal
        WHERE horizon = :horizon
        """),
        {"horizon": horizon},
    ).scalar()

    try:
        from core.quant_core.research.edge import METHODOLOGY_VERSION
        from ..config import settings

        edge_rev = {
            "methodology_version": METHODOLOGY_VERSION,
            "cost_bps_per_side": float(settings.EDGE_COST_BPS_PER_SIDE),
        }
    except Exception:
        edge_rev = {"methodology_version": None, "cost_bps_per_side": None}

    score_history_rev = _score_history_revision(db, horizon)
    revision_key = max(
        (
            value
            for value in (
                _iso_or_none(data_as_of_row),
                _iso_or_none(engine_updated_at),
                _iso_or_none(wfo_updated_at),
                score_history_rev.get("jobs_updated_at"),
            )
            if value
        ),
        default=None,
    )

    return {
        "revision_key": revision_key,
        "dashboard_payload_version": DASHBOARD_PAYLOAD_VERSION,
        "data_as_of": str(data_as_of_row) if data_as_of_row else None,
        "engine_batch_id": str(engine_run_row) if engine_run_row else None,
        "engine_updated_at": _iso_or_none(engine_updated_at),
        "wfo_run_id": str(wfo_run_row) if wfo_run_row else None,
        "wfo_updated_at": _iso_or_none(wfo_updated_at),
        "score_history": score_history_rev,
        "edge": edge_rev,
    }
