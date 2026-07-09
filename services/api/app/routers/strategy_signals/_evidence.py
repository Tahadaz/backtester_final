"""Signal evidence endpoints: /signal/evidence."""
from __future__ import annotations

import json
import time
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from fastapi import Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...db import get_db
from ...schemas.strategy_signals import SupportResistanceVariantRequest
from core.quant_core.signal_engine.domain import (
    EnsemblePipelineDetail,
    HORIZON_PARAMS,
    OOSWindowResult,
    VariantRobustnessSummary,
    label_to_signal_value,
    signal_type_label,
    variant_signal_label,
)
from core.quant_core.signal_engine.ensemble import (
    run_family_ensemble_full,
    compute_family_score_timeseries,
    family_signal_is_available,
    _score_to_label,
)
from core.quant_core.signal_engine.modes import (
    ALL_SIGNAL_MODE_NAMES,
    resolve_signal_mode,
    signal_mode_read_names,
    signal_mode_storage_name,
)
from core.quant_core.signal_engine.oos_eval import compute_signal_array
from core.quant_core.signal_engine.ta_combo import factor_condition_to_dict
from core.quant_core.horizons import canonical_horizon, LEGACY_HORIZON_ALIASES
from core.quant_core.significance import sharpe_ratio
from core.quant_core.risk import monte_carlo_equity_paths
from core.quant_core.data import drop_incomplete_ohlcv_rows
from core.quant_core.research.stats.regression import market_model
from ...market_data_loader import load_ohlcv_for_symbol, load_close_for_symbol
from ._shared import (
    logger,
    router,
    CanonicalHorizon,
    _require_canonical_signal_horizon,
    _truncate_for_horizon,
    _clean_ohlcv,
    _get_or_compute,
    _safe_float,
    _safe_float_list,
    _evidence_max_drawdown,
    _evidence_float,
)
EVIDENCE_BENCHMARK_SYMBOL = "MASI"
EVIDENCE_BENCHMARK_SYMBOL_CANDIDATES = (EVIDENCE_BENCHMARK_SYMBOL, "MASI.CS", "MASI.MA")

def _evidence_source(value: str | None) -> str:
    token = str(value or "auto").strip().lower()
    if token in {"", "auto", "best"}:
        return "auto"
    if token in {"engine", "signal_engine"}:
        return "signal_engine"
    if token == "wfo":
        return "wfo"
    raise HTTPException(status_code=422, detail="source must be auto, signal_engine, or wfo")


def _evidence_proof_limit(value: str | int | None) -> tuple[int | None, str]:
    token = str(value if value is not None else "100").strip().lower()
    if token == "all":
        return None, "all"
    try:
        limit = int(token)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="proof_limit must be one of 100, 250, 500, or all")
    if limit not in {100, 250, 500}:
        raise HTTPException(status_code=422, detail="proof_limit must be one of 100, 250, 500, or all")
    return limit, str(limit)




def _evidence_db_horizons(horizon: str) -> list[str]:
    canonical = canonical_horizon(horizon, allow_legacy=True)
    return [
        canonical,
        *[
            legacy
            for legacy, mapped in LEGACY_HORIZON_ALIASES.items()
            if mapped == canonical
        ],
    ]


def _edge_payload_for_evidence(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    source: str,
    variant: str,
    cost_bps: float,
    multiple_testing_count: int,
) -> dict[str, Any] | None:
    from ..analytics import _build_edge_metrics_from_db, _edge_metrics_to_out

    metrics = _build_edge_metrics_from_db(
        symbol=symbol,
        horizon=horizon,
        source=source,
        variant=variant,
        cost_bps=cost_bps,
        db=db,
        multiple_testing_count=multiple_testing_count,
    )
    if metrics is None:
        return None
    return json.loads(_edge_metrics_to_out(metrics).model_dump_json())


def _select_signal_evidence_edge(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    source: str,
    variant: str | None,
    cost_bps: float,
) -> tuple[dict[str, Any], str, str, str]:
    """Return (edge, source, variant, method_label) for evidence.

    Requests without an explicit variant are WFO-first for the evidence page.
    The dashboard best-signal rank intentionally rejects weak signals; evidence
    must still be auditable when the current WFO signal has too few samples or
    fails proof gates.  Explicit variant requests keep their requested
    source/variant behavior.
    """
    from ...services.dashboard_builder import (
        EDGE_CANDIDATE_COUNT,
        _apply_wfo_all_oos_proof_to_edge,
        _best_signal_rank,
        _is_actionable_edge_bucket,
        _signal_method_label,
    )

    if variant is not None:
        try:
            variants = [resolve_signal_mode(variant).name]
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    else:
        variants = list(ALL_SIGNAL_MODE_NAMES)

    prefer_relaxed_wfo = variant is None
    if prefer_relaxed_wfo:
        candidate_sources = ["wfo"]
    elif source == "auto":
        candidate_sources = ["signal_engine", "wfo"]
    else:
        candidate_sources = [source]
        if variant is None and source != "wfo":
            variants = [resolve_signal_mode("expanded").name]

    best: tuple[tuple[int, float, float, float], dict[str, Any], str, str] | None = None
    relaxed_best: tuple[tuple[int, int, float, float, float], dict[str, Any], str, str] | None = None
    first_payload: tuple[dict[str, Any], str, str] | None = None
    for candidate_source in candidate_sources:
        for candidate_variant in variants:
            try:
                edge = _edge_payload_for_evidence(
                    db,
                    symbol=symbol,
                    horizon=horizon,
                    source=candidate_source,
                    variant=candidate_variant,
                    cost_bps=cost_bps,
                    multiple_testing_count=EDGE_CANDIDATE_COUNT,
                )
            except Exception:
                logger.exception(
                    "signal evidence edge build failed",
                    extra={
                        "symbol": symbol,
                        "horizon": horizon,
                        "source": candidate_source,
                        "variant": candidate_variant,
                    },
                )
                try:
                    db.rollback()
                except Exception:
                    pass
                continue
            if edge is None:
                continue
            if candidate_source == "wfo":
                edge = _apply_wfo_all_oos_proof_to_edge(
                    db,
                    symbol=symbol,
                    horizon=horizon,
                    variant=candidate_variant,
                    edge=edge,
                    cost_bps=cost_bps,
                )
            first_payload = first_payload or (edge, candidate_source, candidate_variant)
            if prefer_relaxed_wfo:
                direction = str(edge.get("direction") or "none").strip().lower()
                actionable = 1 if _is_actionable_edge_bucket(edge.get("bucket"), direction) else 0
                proven = 1 if bool(edge.get("proven_edge_net")) else 0
                edge_score = _evidence_float(edge.get("edge_score"))
                expected = _evidence_float(edge.get("action_expected_return_net"))
                if expected is None:
                    expected = _evidence_float(edge.get("expected_return_net"))
                n = _evidence_float(edge.get("n")) or 0.0
                relaxed_rank = (
                    actionable,
                    proven,
                    edge_score if edge_score is not None else -1.0,
                    expected if expected is not None else -1e12,
                    n,
                )
                if relaxed_best is None or relaxed_rank > relaxed_best[0]:
                    relaxed_best = (relaxed_rank, edge, candidate_source, candidate_variant)
            else:
                rank = _best_signal_rank(edge)
                if rank is None:
                    continue
                if best is None or rank > best[0]:
                    best = (rank, edge, candidate_source, candidate_variant)

    if prefer_relaxed_wfo:
        if relaxed_best is None:
            if first_payload is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No WFO signal evidence for {symbol}/{horizon}.",
                )
            edge, selected_source, selected_variant = first_payload
        else:
            _rank, edge, selected_source, selected_variant = relaxed_best
    elif source == "auto":
        if best is None:
            if first_payload is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No actionable signal evidence for {symbol}/{horizon}.",
                )
            edge, selected_source, selected_variant = first_payload
        else:
            _rank, edge, selected_source, selected_variant = best
    else:
        if first_payload is None:
            raise HTTPException(
                status_code=404,
                detail=f"No signal evidence for {symbol}/{horizon}/{source}/{variants[0]}.",
            )
        edge, selected_source, selected_variant = first_payload

    return edge, selected_source, selected_variant, _signal_method_label(selected_source, selected_variant)


def _current_evidence_signal(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    source: str,
    variant: str,
) -> dict[str, Any]:
    from services.api.app import models

    horizons = _evidence_db_horizons(horizon)
    variants = signal_mode_read_names(variant)
    mode = resolve_signal_mode(variant)

    if source == "wfo":
        row = (
            db.query(models.WfoGlobalSignal)
            .filter(
                models.WfoGlobalSignal.symbol == symbol,
                models.WfoGlobalSignal.horizon.in_(horizons),
                models.WfoGlobalSignal.variant.in_(variants),
                models.WfoGlobalSignal.status == "succeeded",
            )
            .order_by(models.WfoGlobalSignal.updated_at.desc())
            .first()
        )
        if row is None:
            return {}
        return {
            "score_pct": _evidence_float(row.global_score_pct),
            "raw_score_pct": _evidence_float(row.raw_score_pct),
            "signal_label": row.signal_label or row.recommendation,
            "recommendation": row.recommendation,
            "best_category": row.best_category,
            "best_category_score": _evidence_float(row.best_category_score),
            "data_as_of": row.data_as_of.isoformat() if row.data_as_of else None,
            "computed_at": row.computed_at.isoformat() if row.computed_at else None,
        }

    row = (
        db.query(models.SignalEngineGlobalResult)
        .filter(
            models.SignalEngineGlobalResult.symbol == symbol,
            models.SignalEngineGlobalResult.horizon.in_(horizons),
            models.SignalEngineGlobalResult.variant.in_(variants),
            models.SignalEngineGlobalResult.status == "succeeded",
        )
        .order_by(models.SignalEngineGlobalResult.updated_at.desc())
        .first()
    )
    if row is None:
        return {}
    preferred = row.aggregate_score_pct if mode.is_legacy else row.expanded_aggregate_score_pct
    fallback = row.expanded_aggregate_score_pct if mode.is_legacy else row.aggregate_score_pct
    return {
        "score_pct": _evidence_float(preferred if preferred is not None else fallback),
        "raw_score_pct": None,
        "signal_label": row.signal_label,
        "recommendation": row.signal_label,
        "best_category": None,
        "best_category_score": None,
        "data_as_of": row.data_as_of.isoformat() if row.data_as_of else None,
        "computed_at": row.computed_at.isoformat() if row.computed_at else None,
    }


def _factor_condition_payload(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    condition = raw.get("factor_condition") if isinstance(raw.get("factor_condition"), dict) else raw
    if not isinstance(condition, dict):
        return None
    if not condition.get("condition_id") and not condition.get("factor_ticker"):
        return None
    return {
        "condition_id": str(condition.get("condition_id") or ""),
        "factor_ticker": str(condition.get("factor_ticker") or ""),
        "form": str(condition.get("form") or ""),
        "lookback": _evidence_float(condition.get("lookback")),
        "threshold": _evidence_float(condition.get("threshold")),
        "direction": str(condition.get("direction") or ""),
    }


def _factor_conditions_from_rep(rep: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    top_level = _factor_condition_payload(rep.get("factor_condition"))
    if top_level is not None:
        key = (top_level["condition_id"], top_level["factor_ticker"])
        seen.add(key)
        out.append(top_level)

    params = rep.get("params")
    if isinstance(params, dict):
        for component in params.get("components", []):
            payload = _factor_condition_payload(component)
            if payload is None:
                continue
            key = (payload["condition_id"], payload["factor_ticker"])
            if key in seen:
                continue
            seen.add(key)
            out.append(payload)
    return out


def _normalise_evidence_rep(
    rep: Any,
    *,
    category: str,
    family: str | None = None,
    category_score_pct: float | None = None,
    category_signal_label: str | None = None,
) -> dict[str, Any] | None:
    if not isinstance(rep, dict):
        return None
    params = rep.get("params") if isinstance(rep.get("params"), dict) else {}
    variant_id = str(rep.get("variant_id") or "").strip()
    rep_family = str(rep.get("family") or family or "").strip()
    if not variant_id and not rep_family:
        return None
    description = (
        str(rep.get("description") or "").strip()
        or str(rep.get("label") or "").strip()
        or variant_id
        or rep_family
    )
    factor_conditions = _factor_conditions_from_rep(rep)
    return {
        "category": category,
        "category_score_pct": category_score_pct,
        "category_signal_label": category_signal_label,
        "family": rep_family,
        "archetype": str(rep.get("archetype") or ""),
        "variant_id": variant_id,
        "description": description,
        "params": params,
        "normalized_weight": _evidence_float(rep.get("normalized_weight")),
        "reliability_weight": _evidence_float(rep.get("reliability_weight")),
        "signal_label": str(rep.get("signal_label") or ""),
        "indicator_value": _evidence_float(rep.get("indicator_value")),
        "current_close": _evidence_float(rep.get("current_close")),
        "factor_conditions": factor_conditions,
        "is_factor_conditioned": bool(factor_conditions or rep_family.endswith("@fx")),
    }


def _signal_evidence_contributors(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    source: str,
    variant: str,
) -> list[dict[str, Any]]:
    from services.api.app import models

    horizons = _evidence_db_horizons(horizon)
    variants = signal_mode_read_names(variant)
    contributors: list[dict[str, Any]] = []

    if source == "wfo":
        rows = (
            db.query(models.WfoSignalSummary)
            .filter(
                models.WfoSignalSummary.symbol == symbol,
                models.WfoSignalSummary.horizon.in_(horizons),
                models.WfoSignalSummary.variant.in_(variants),
                models.WfoSignalSummary.status == "succeeded",
            )
            .order_by(models.WfoSignalSummary.category.asc())
            .all()
        )
        for row in rows:
            for rep in row.representatives_json or []:
                normalized = _normalise_evidence_rep(
                    rep,
                    category=str(row.category or ""),
                    category_score_pct=_evidence_float(row.score_pct),
                    category_signal_label=row.signal_label,
                )
                if normalized is not None:
                    contributors.append(normalized)
    else:
        rows = (
            db.query(models.SignalEngineFamilyResult)
            .filter(
                models.SignalEngineFamilyResult.symbol == symbol,
                models.SignalEngineFamilyResult.horizon.in_(horizons),
                models.SignalEngineFamilyResult.variant.in_(variants),
                models.SignalEngineFamilyResult.status == "succeeded",
            )
            .order_by(models.SignalEngineFamilyResult.category.asc(), models.SignalEngineFamilyResult.family.asc())
            .all()
        )
        for row in rows:
            for rep in row.representatives_json or []:
                normalized = _normalise_evidence_rep(
                    rep,
                    category=str(row.category or ""),
                    family=str(row.family or ""),
                    category_score_pct=_evidence_float(row.family_score_pct),
                    category_signal_label=row.signal_label,
                )
                if normalized is not None:
                    contributors.append(normalized)

    contributors.sort(
        key=lambda item: (
            -(item.get("normalized_weight") or item.get("reliability_weight") or 0.0),
            str(item.get("category") or ""),
            str(item.get("family") or ""),
            str(item.get("variant_id") or ""),
        )
    )
    return contributors


def _evidence_iso_date(value: Any) -> str | None:
    if value is None:
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return str(value)[:10] if str(value) else None
    if pd.isna(ts):
        return None
    return ts.date().isoformat()


def _period_contributors_for_evidence(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    source: str,
    variant: str,
    windows: list[Any],
    fallback_contributors: list[dict[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    if source != "wfo":
        return {idx: list(fallback_contributors) for idx, _window in enumerate(windows)}

    from services.api.app import models

    horizons = _evidence_db_horizons(horizon)
    variants = signal_mode_read_names(variant)
    rows = (
        db.query(models.WfoSignalSummary)
        .filter(
            models.WfoSignalSummary.symbol == symbol,
            models.WfoSignalSummary.horizon.in_(horizons),
            models.WfoSignalSummary.variant.in_(variants),
            models.WfoSignalSummary.status == "succeeded",
        )
        .order_by(models.WfoSignalSummary.category.asc())
        .all()
    )

    by_fold_id: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        reps = [rep for rep in (row.representatives_json or []) if isinstance(rep, dict)]
        reps_by_id = {str(rep.get("variant_id") or ""): rep for rep in reps}
        for fold in row.folds_json or []:
            if not isinstance(fold, dict):
                continue
            fold_id = str(fold.get("index") if fold.get("index") is not None else "")
            if not fold_id:
                continue
            winner_id = str(fold.get("winner_variant_id") or "").strip()
            if not winner_id:
                continue
            rep = dict(reps_by_id.get(winner_id) or {})
            rep.setdefault("variant_id", winner_id)
            rep.setdefault("description", str(fold.get("winner_description") or winner_id))
            rep.setdefault("params", fold.get("winner_params") if isinstance(fold.get("winner_params"), dict) else {})
            normalized = _normalise_evidence_rep(
                rep,
                category=str(row.category or ""),
                category_score_pct=_evidence_float(row.score_pct),
                category_signal_label=row.signal_label,
            )
            if normalized is not None:
                by_fold_id.setdefault(fold_id, []).append(normalized)

    out: dict[int, list[dict[str, Any]]] = {}
    for idx, window in enumerate(windows):
        fold_id = str(getattr(window, "fold_id", "") if getattr(window, "fold_id", None) is not None else "")
        items = by_fold_id.get(fold_id, [])
        if not items:
            items = fallback_contributors
        seen: set[tuple[str, str, str]] = set()
        deduped: list[dict[str, Any]] = []
        for item in items:
            key = (
                str(item.get("category") or ""),
                str(item.get("family") or ""),
                str(item.get("variant_id") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        out[idx] = deduped
    return out


EVIDENCE_MIN_SAMPLE_N = 30


def _evidence_mean(values: list[float]) -> float | None:
    finite = [float(value) for value in values if np.isfinite(value)]
    return float(np.mean(finite)) if finite else None


def _evidence_finite_array(values: list[float]) -> np.ndarray:
    finite = [float(value) for value in values if np.isfinite(value)]
    return np.asarray(finite, dtype="float64")


def _evidence_path_returns(equity: list[float]) -> np.ndarray:
    arr = _evidence_finite_array(equity)
    if arr.size < 2:
        return np.asarray([], dtype="float64")
    prev = arr[:-1]
    curr = arr[1:]
    valid = prev > 0.0
    if not bool(np.any(valid)):
        return np.asarray([], dtype="float64")
    return curr[valid] / prev[valid] - 1.0


def _evidence_path_returns_with_first_flat(equity: list[float]) -> list[float | None]:
    arr = [float(value) for value in equity if np.isfinite(value)]
    if not arr:
        return []
    returns: list[float | None] = [0.0]
    for idx in range(1, len(arr)):
        prev = arr[idx - 1]
        curr = arr[idx]
        returns.append(float(curr / prev - 1.0) if prev > 0.0 else None)
    return returns


def _evidence_trade_sharpe(net_returns: list[float], dates: list[str]) -> float | None:
    returns = _evidence_finite_array(net_returns)
    if returns.size < 2:
        return None
    sigma = float(np.std(returns, ddof=1))
    if sigma <= 0.0:
        return None
    years = max(len(dates), 1) / 252.0
    trades_per_year = float(returns.size) / years
    return float(np.mean(returns) / sigma * np.sqrt(trades_per_year))


def _evidence_path_sharpe(returns: np.ndarray, periods_per_year: int = 252) -> float | None:
    if returns.size < 2:
        return None
    sigma = float(np.std(returns, ddof=1))
    if sigma <= 0.0:
        return None
    return float(np.mean(returns) / sigma * np.sqrt(float(periods_per_year)))


def _evidence_sortino(returns: np.ndarray, periods_per_year: int = 252) -> float | None:
    if returns.size < 2:
        return None
    downside = returns[returns < 0.0]
    if downside.size < 2:
        return None
    semi_std = float(np.std(downside, ddof=1))
    if semi_std <= 0.0:
        return None
    return float(np.mean(returns) / semi_std * np.sqrt(float(periods_per_year)))


def _evidence_volatility(returns: np.ndarray, periods_per_year: int = 252) -> float | None:
    if returns.size < 2:
        return None
    sigma = float(np.std(returns, ddof=1))
    return float(sigma * np.sqrt(float(periods_per_year))) if sigma >= 0.0 else None


def _evidence_downside_volatility(returns: np.ndarray, periods_per_year: int = 252) -> float | None:
    downside = returns[returns < 0.0]
    if downside.size < 2:
        return None
    sigma = float(np.std(downside, ddof=1))
    return float(sigma * np.sqrt(float(periods_per_year))) if sigma >= 0.0 else None


def _evidence_benchmark_returns(
    db: Session,
    dates: list[str],
    *,
    symbol: str = EVIDENCE_BENCHMARK_SYMBOL,
) -> tuple[list[float | None] | None, str | None]:
    if not dates:
        return [], symbol
    last_error: Exception | None = None
    for candidate in (symbol, *[item for item in EVIDENCE_BENCHMARK_SYMBOL_CANDIDATES if item != symbol]):
        try:
            # Verify the exact key through the close loader; it raises when absent.
            loaded = load_close_for_symbol(db, candidate)
            if len(loaded) == 0:
                raise ValueError(f"empty benchmark close series for {candidate}")
            frame = load_ohlcv_for_symbol(db, candidate)
            close = pd.to_numeric(frame["Close"] if "Close" in frame.columns else frame["close"], errors="coerce")
            close.index = pd.to_datetime(close.index, errors="coerce")
            if getattr(close.index, "tz", None) is not None:
                close.index = close.index.tz_convert(None)
            close.index = close.index.normalize()
            close = close.dropna().sort_index()
            close = close[~close.index.duplicated(keep="last")]
            target = pd.DatetimeIndex(pd.to_datetime(dates, errors="coerce")).tz_localize(None).normalize()
            aligned = close.reindex(target, method="ffill", limit=3)
            returns: list[float | None] = [None]
            for idx in range(1, len(aligned)):
                prev = _evidence_float(aligned.iloc[idx - 1])
                curr = _evidence_float(aligned.iloc[idx])
                if prev is None or curr is None or prev <= 0.0 or curr <= 0.0:
                    returns.append(None)
                else:
                    returns.append(float(curr / prev - 1.0))
            return returns, candidate
        except Exception as exc:
            last_error = exc
            continue
    logger.info("signal evidence benchmark unavailable", extra={"symbol": symbol, "error": str(last_error)})
    return None, symbol


def _evidence_trade_distribution_metrics(
    net_returns: list[float],
    equity: list[float],
    *,
    dates: list[str],
    benchmark_returns: list[float | None] | None = None,
    benchmark_symbol: str | None = None,
    min_sample_n: int = EVIDENCE_MIN_SAMPLE_N,
) -> dict[str, Any]:
    returns = _evidence_finite_array(net_returns)
    wins = returns[returns > 0.0]
    losses = returns[returns < 0.0]
    gross_profit = float(np.sum(wins)) if wins.size else 0.0
    gross_loss = float(abs(np.sum(losses))) if losses.size else 0.0
    avg_win = float(np.mean(wins)) if wins.size else None
    avg_loss = float(np.mean(losses)) if losses.size else None
    payoff_ratio = (
        float(avg_win / abs(avg_loss))
        if avg_win is not None and avg_loss is not None and avg_loss != 0.0
        else None
    )
    profit_factor = (
        float(gross_profit / gross_loss)
        if gross_loss > 0.0
        else None
    )
    path_returns = _evidence_path_returns(equity)
    max_dd = _evidence_max_drawdown(equity)
    total_return = float(equity[-1] - 1.0) if equity else 0.0
    years = max(len(dates), 1) / 252.0
    cagr = float((1.0 + total_return) ** (1.0 / years) - 1.0) if total_return > -1.0 else -1.0
    calmar = float(cagr / abs(max_dd)) if max_dd and max_dd != 0.0 else None
    strategy_returns = _evidence_path_returns_with_first_flat(equity)
    alpha = market_model(strategy_returns, benchmark_returns, min_obs=20)

    return {
        "profit_factor_net": profit_factor,
        "avg_win_net": avg_win,
        "avg_loss_net": avg_loss,
        "payoff_ratio_net": payoff_ratio,
        "median_return_net": float(np.median(returns)) if returns.size else None,
        "p05_return_net": float(np.percentile(returns, 5)) if returns.size else None,
        "p95_return_net": float(np.percentile(returns, 95)) if returns.size else None,
        "sortino": _evidence_sortino(path_returns),
        "sharpe_path": _evidence_path_sharpe(path_returns),
        "calmar": calmar,
        "annualized_volatility": _evidence_volatility(path_returns),
        "downside_volatility": _evidence_downside_volatility(path_returns),
        "beta": alpha["beta"],
        "alpha_annualized": alpha["alpha_annualized"],
        "alpha_r2": alpha["alpha_r2"],
        "alpha_n_obs": alpha["alpha_n_obs"],
        "alpha_reason": alpha["alpha_reason"],
        "benchmark_symbol": benchmark_symbol,
        "sample_start": dates[0] if dates else None,
        "sample_end": dates[-1] if dates else None,
        "sample_days": len(dates),
        "min_sample_pass": bool(returns.size >= int(min_sample_n)),
        "metric_basis": "stitched_wfo_oos",
    }


def _evidence_trade_proof_summary(
    trades: list[dict[str, Any]],
    *,
    direction: str,
    proof_limit_label: str,
) -> dict[str, Any]:
    action_trades = [
        trade
        for trade in trades
        if str(trade.get("direction") or "").strip().lower() in {"long", "short"}
    ]
    proof_trades = action_trades if action_trades else list(trades)
    signal_dates = [
        str(trade.get("signal_date") or "")[:10]
        for trade in proof_trades
        if str(trade.get("signal_date") or "")[:10]
    ]
    gross_values = [
        float(value)
        for trade in proof_trades
        for value in [_evidence_float(trade.get("action_return_gross"))]
        if value is not None
    ]
    net_values = [
        float(value)
        for trade in proof_trades
        for value in [_evidence_float(trade.get("action_return_net"))]
        if value is not None
    ]
    stock_values = [
        float(value)
        for trade in proof_trades
        for value in [_evidence_float(trade.get("stock_return"))]
        if value is not None
    ]

    hit_ci_lower = None
    hit_ci_upper = None
    hit_rate = None
    if gross_values:
        from core.quant_core.research.stats.hit_rate import wilson_ci

        hits = int(np.sum(np.asarray(gross_values, dtype="float64") > 0.0))
        hit_rate = float(hits / len(gross_values))
        hit_ci_lower, hit_ci_upper = wilson_ci(hits, len(gross_values))

    from core.quant_core.research.edge import bootstrap_mean_ci

    gross_ci = bootstrap_mean_ci(np.asarray(gross_values, dtype="float64"), n_iter=1000, seed=6101)
    net_ci = bootstrap_mean_ci(np.asarray(net_values, dtype="float64"), n_iter=1000, seed=6102)
    stock_ci = bootstrap_mean_ci(np.asarray(stock_values, dtype="float64"), n_iter=1000, seed=6103)

    has_action = str(direction or "").strip().lower() in {"long", "short"}
    n = len(action_trades) if has_action else len(stock_values)
    return {
        "limit": proof_limit_label,
        "n_trades": n,
        "window_start": min(signal_dates) if signal_dates else None,
        "window_end": max(signal_dates) if signal_dates else None,
        "expected_return_gross": _evidence_mean(gross_values),
        "expected_return_gross_ci_lower": gross_ci[0],
        "expected_return_gross_ci_upper": gross_ci[1],
        "expected_return_net": _evidence_mean(net_values),
        "expected_return_net_ci_lower": net_ci[0],
        "expected_return_net_ci_upper": net_ci[1],
        "stock_expected_return": _evidence_mean(stock_values),
        "stock_expected_return_ci_lower": stock_ci[0],
        "stock_expected_return_ci_upper": stock_ci[1],
        "hit_rate": hit_rate,
        "hit_ci_lower": float(hit_ci_lower) if hit_ci_lower is not None else None,
        "hit_ci_upper": float(hit_ci_upper) if hit_ci_upper is not None else None,
    }

def _evidence_tail_risk(values: list[float], *, min_n: int = 5) -> tuple[float | None, float | None]:
    finite = np.asarray([float(value) for value in values if np.isfinite(value)], dtype=np.float64)
    if finite.size < min_n:
        return None, None
    var95 = float(np.quantile(finite, 0.05))
    tail = finite[finite <= var95]
    cvar95 = float(np.mean(tail)) if tail.size else var95
    return var95, cvar95


def _evidence_chart_frame(
    price_index: pd.DatetimeIndex,
    price_frame: pd.DataFrame,
    windows: list[Any],
    trades: list[dict[str, Any]],
) -> tuple[list[str], list[float], list[float], list[float], list[float]]:
    starts = [
        pd.Timestamp(getattr(window, "start", None))
        for window in windows
        if getattr(window, "start", None) is not None
    ]
    ends = [
        pd.Timestamp(getattr(window, "end", None))
        for window in windows
        if getattr(window, "end", None) is not None
    ]
    for trade in trades:
        for key in ("signal_date", "entry_date", "exit_date"):
            value = trade.get(key)
            if value:
                starts.append(pd.Timestamp(value))
                ends.append(pd.Timestamp(value))
    if not starts or not ends:
        return [], [], [], [], []

    start = min(starts)
    end = max(ends)
    start_pos = int(price_index.searchsorted(start, side="left"))
    end_pos = int(price_index.searchsorted(end, side="right")) - 1
    if len(price_index) == 0 or start_pos >= len(price_index) or end_pos < 0:
        return [], [], [], [], []
    start_pos = max(0, min(start_pos, len(price_index) - 1))
    end_pos = max(0, min(end_pos, len(price_index) - 1))
    if end_pos < start_pos:
        start_pos, end_pos = end_pos, start_pos
    if end_pos - start_pos + 1 < 2 and len(price_index) > 1:
        start_pos = max(0, start_pos - 1)
        end_pos = min(len(price_index) - 1, end_pos + 1)
    chart_index = pd.DatetimeIndex(price_index[start_pos:end_pos + 1])
    rows: list[tuple[str, float | None, float | None, float | None, float]] = []
    for ts in chart_index:
        if ts not in price_frame.index:
            continue
        close_value = _evidence_float(price_frame.loc[ts, "close"])
        if close_value is None:
            continue
        open_value = _evidence_float(price_frame.loc[ts, "open"]) if "open" in price_frame.columns else close_value
        high_value = _evidence_float(price_frame.loc[ts, "high"]) if "high" in price_frame.columns else None
        low_value = _evidence_float(price_frame.loc[ts, "low"]) if "low" in price_frame.columns else None
        rows.append((
            pd.Timestamp(ts).date().isoformat(),
            open_value,
            high_value,
            low_value,
            float(close_value),
        ))

    dates = [row[0] for row in rows]
    close = [row[4] for row in rows]
    has_complete_ohlc = all(row[1] is not None and row[2] is not None and row[3] is not None for row in rows)
    if not has_complete_ohlc:
        return dates, [], [], [], close
    return (
        dates,
        [float(row[1]) for row in rows if row[1] is not None],
        [float(row[2]) for row in rows if row[2] is not None],
        [float(row[3]) for row in rows if row[3] is not None],
        close,
    )


def _apply_evidence_trade_cooldown(
    trades: list[dict[str, Any]],
    price_index: pd.DatetimeIndex,
    cooldown_bars: int,
) -> list[dict[str, Any]]:
    cooldown = max(0, int(cooldown_bars or 0))
    action_trades = [
        trade
        for trade in trades
        if str(trade.get("direction") or "").strip().lower() in {"long", "short"}
    ]
    if cooldown <= 0 or not action_trades:
        return list(trades)

    date_to_pos = {
        pd.Timestamp(ts).date().isoformat(): idx
        for idx, ts in enumerate(pd.DatetimeIndex(price_index))
    }

    def _bar_pos(value: Any) -> int | None:
        if value is None:
            return None
        try:
            key = pd.Timestamp(value).date().isoformat()
        except Exception:
            return None
        return date_to_pos.get(key)

    ordered = sorted(
        trades,
        key=lambda trade: (
            _bar_pos(trade.get("entry_date")) if _bar_pos(trade.get("entry_date")) is not None else 10**12,
            _bar_pos(trade.get("exit_date")) if _bar_pos(trade.get("exit_date")) is not None else 10**12,
            str(trade.get("signal_date") or ""),
            str(trade.get("trade_id") or ""),
        ),
    )
    kept: list[dict[str, Any]] = []
    cooldown_until = -1
    for trade in ordered:
        direction = str(trade.get("direction") or "").strip().lower()
        if direction not in {"long", "short"}:
            kept.append(trade)
            continue
        entry_pos = _bar_pos(trade.get("entry_date"))
        exit_pos = _bar_pos(trade.get("exit_date"))
        if entry_pos is None or exit_pos is None:
            kept.append(trade)
            continue
        if entry_pos <= cooldown_until:
            continue
        kept.append(trade)
        cooldown_until = max(cooldown_until, exit_pos + cooldown)
    return kept


def _evidence_trade_ledger(
    trades: list[dict[str, Any]],
    *,
    cost_bps: float,
) -> list[dict[str, Any]]:
    def _price_kind_rank(value: Any, event_type: str) -> int:
        token = str(value or "").strip().lower()
        if token == "open":
            return 0
        if token == "close":
            return 1
        return 0 if event_type == "entry" else 1

    def _trade_quantity(trade: dict[str, Any]) -> float:
        for key in ("quantity", "qty", "shares", "units"):
            value = _evidence_float(trade.get(key))
            if value is not None and value > 0.0:
                return float(value)
        return 1.0

    friction = float(cost_bps) * 1e-4
    ordered = sorted(
        trades,
        key=lambda item: (
            str(item.get("entry_date") or item.get("signal_date") or ""),
            str(item.get("exit_date") or ""),
            str(item.get("trade_id") or ""),
        ),
    )
    events: list[dict[str, Any]] = []

    sequence = 0
    for trade in ordered:
        direction = str(trade.get("direction") or "").lower()
        if direction not in {"long", "short"}:
            continue
        sequence += 1
        is_short = direction == "short"
        entry_side = "VENTE" if is_short else "ACHAT"
        exit_side = "ACHAT" if is_short else "VENTE"
        entry_label = f"{'Short' if is_short else 'Buy'} {sequence}"
        exit_label = f"{'Cover' if is_short else 'Sell'} {sequence}"
        entry_price = _evidence_float(trade.get("entry_price")) or 0.0
        exit_price = _evidence_float(trade.get("exit_price")) or 0.0
        entry_close_price = _evidence_float(trade.get("entry_close_price"))
        exit_close_price = _evidence_float(trade.get("exit_close_price"))
        quantity = _trade_quantity(trade)
        entry_cost = entry_price * friction * quantity
        exit_cost = exit_price * friction * quantity
        net_return = _evidence_float(trade.get("action_return_net"))
        trade_id = str(trade.get("trade_id") or f"evidence-{sequence}")
        score = _evidence_float(trade.get("score_pct"))
        entry_price_kind = str(trade.get("entry_price_kind") or "open").strip().lower() or "open"
        exit_price_kind = str(trade.get("exit_price_kind") or "close").strip().lower() or "close"

        events.append({
            "date": trade.get("entry_date"),
            "side": entry_side,
            "marker_label": entry_label,
            "event_type": "entry",
            "trade_sequence": sequence,
            "trade_id": trade_id,
            "price_kind": entry_price_kind,
            "signal_date": trade.get("signal_date"),
            "bucket": trade.get("bucket"),
            "global_score_pct": score,
            "prix_execution": round(entry_price, 4),
            "open_t_plus_1": round(entry_price, 4),
            "close_du_jour": round(entry_close_price if entry_close_price is not None else entry_price, 4),
            "cmp": round(entry_price, 4),
            "quantity": round(quantity, 4),
            "position_delta": -quantity if is_short else quantity,
            "return_cumule": None,
            "cash_cumulee": None,
            "tresorerie": None,
            "pnl_realise": 0.0,
            "pnl_realise_cumule": None,
            "pnl_latent": 0.0,
            "cout": round(entry_cost, 4),
            "notional_ouvert": round(entry_price * quantity, 4),
        })

        events.append({
            "date": trade.get("exit_date"),
            "side": exit_side,
            "marker_label": exit_label,
            "event_type": "exit",
            "trade_sequence": sequence,
            "trade_id": trade_id,
            "price_kind": exit_price_kind,
            "signal_date": trade.get("signal_date"),
            "bucket": trade.get("bucket"),
            "global_score_pct": score,
            "prix_execution": round(exit_price, 4),
            "open_t_plus_1": round(exit_price, 4),
            "close_du_jour": round(exit_close_price if exit_close_price is not None else exit_price, 4),
            "cmp": round(entry_price, 4),
            "quantity": round(quantity, 4),
            "position_delta": quantity if is_short else -quantity,
            "return_cumule": None,
            "cash_cumulee": None,
            "tresorerie": None,
            "pnl_realise": 0.0,
            "pnl_realise_cumule": None,
            "pnl_latent": 0.0,
            "cout": round(exit_cost, 4),
            "pnl_return_net": net_return,
            "notional_ouvert": 0.0,
        })

    events.sort(
        key=lambda item: (
            str(item.get("date") or "")[:10],
            _price_kind_rank(item.get("price_kind"), str(item.get("event_type") or "")),
            int(item.get("trade_sequence") or 0),
            0 if item.get("event_type") == "entry" else 1,
        )
    )

    ledger: list[dict[str, Any]] = []
    current_position = 0.0
    cmp = 0.0
    cash = 0.0
    realized_cumulative = 0.0
    opened_notional = 0.0

    def _apply_delta(exec_price: float, mark_price: float, delta: float) -> tuple[float, float, float]:
        nonlocal cash, cmp, current_position, opened_notional

        remaining = abs(delta)
        direction = 1.0 if delta > 0.0 else -1.0
        cost_per_unit = friction * exec_price
        realized = 0.0

        while remaining > 1e-12:
            if current_position == 0.0 or np.sign(current_position) == direction:
                qty = remaining
                previous_abs = abs(current_position)
                current_position += direction * qty
                opened_notional += exec_price * qty
                if direction > 0.0:
                    basis = exec_price + cost_per_unit
                    cash -= basis * qty
                else:
                    basis = exec_price - cost_per_unit
                    cash += basis * qty
                cmp = (
                    (previous_abs * cmp + qty * basis) / abs(current_position)
                    if abs(current_position) > 0.0
                    else 0.0
                )
                remaining = 0.0
                continue

            closing_qty = min(remaining, abs(current_position))
            if current_position > 0.0:
                realized += (exec_price - cmp - cost_per_unit) * closing_qty
                cash += (exec_price - cost_per_unit) * closing_qty
            else:
                realized += (cmp - exec_price - cost_per_unit) * closing_qty
                cash -= (exec_price + cost_per_unit) * closing_qty

            current_position += direction * closing_qty
            if abs(current_position) <= 1e-12:
                current_position = 0.0
                cmp = 0.0
            remaining -= closing_qty

        latent = 0.0
        if current_position > 0.0:
            latent = (mark_price - cmp) * abs(current_position)
        elif current_position < 0.0:
            latent = (cmp - mark_price) * abs(current_position)
        return realized, cash, latent

    for transaction_index, event in enumerate(events, start=1):
        delta = float(event.pop("position_delta", 0.0) or 0.0)
        price = _evidence_float(event.get("prix_execution")) or 0.0
        mark_price = _evidence_float(event.get("close_du_jour"))
        if mark_price is None:
            mark_price = price
        previous_position = current_position
        previous_cmp = cmp
        realized, cash_value, latent = _apply_delta(price, float(mark_price), delta)
        realized_cumulative += realized
        is_reducing = previous_position != 0.0 and (
            np.sign(previous_position) != np.sign(delta) or abs(current_position) < abs(previous_position)
        )
        event["transaction_index"] = transaction_index
        event["cmp"] = round(previous_cmp if is_reducing else cmp, 4)
        event["position"] = round(current_position, 4)
        event["cash_cumulee"] = round(cash_value, 4)
        event["tresorerie"] = round(cash_value, 4)
        event["pnl_realise"] = round(realized, 4)
        event["pnl_realise_cumule"] = round(realized_cumulative, 4)
        event["pnl_latent"] = round(latent, 4)
        event["return_cumule"] = round(realized_cumulative / opened_notional, 10) if opened_notional > 0.0 else 0.0
        ledger.append(event)

    return ledger


def _evidence_stitched_backtest(
    *,
    dates: list[str],
    close: list[float],
    open_prices: list[float] | None = None,
    high: list[float] | None = None,
    low: list[float] | None = None,
    trades: list[dict[str, Any]],
    bucket: str,
    direction: str,
    score_mode: str | None,
    cost_bps: float,
    cooldown_bars: int = 0,
    raw_trade_count: int | None = None,
    proof_summary: dict[str, Any] | None = None,
    stitched_window_start: str | None = None,
    stitched_window_end: str | None = None,
    benchmark_returns: list[float | None] | None = None,
    benchmark_symbol: str | None = None,
) -> dict[str, Any]:
    action_trades = [
        trade
        for trade in trades
        if str(trade.get("direction") or "").strip().lower() in {"long", "short"}
    ]
    ledger = _evidence_trade_ledger(action_trades, cost_bps=cost_bps)
    net_returns = [
        float(value)
        for trade in action_trades
        for value in [_evidence_float(trade.get("action_return_net"))]
        if value is not None
    ]
    gross_returns = [
        float(value)
        for trade in action_trades
        for value in [_evidence_float(trade.get("action_return_gross"))]
        if value is not None
    ]
    stock_returns = [
        float(value)
        for trade in trades
        for value in [_evidence_float(trade.get("stock_return"))]
        if value is not None
    ]
    opened_notional = sum(
        float(value)
        for event in ledger
        for value in [_evidence_float(event.get("notional_ouvert"))]
        if value is not None and value > 0.0
    )
    pnl_by_date: dict[str, float] = {}
    for event in ledger:
        event_date = str(event.get("date") or "")[:10]
        realized = _evidence_float(event.get("pnl_realise"))
        if event_date and realized is not None:
            pnl_by_date[event_date] = pnl_by_date.get(event_date, 0.0) + float(realized)

    equity: list[float] = []
    realized_cumulative = 0.0
    for date in dates:
        realized_cumulative += pnl_by_date.get(str(date)[:10], 0.0)
        current_equity = 1.0
        if opened_notional > 0.0:
            current_equity += realized_cumulative / opened_notional
        equity.append(float(current_equity))

    ledger_by_date: dict[str, list[dict[str, Any]]] = {}
    for event in ledger:
        event_date = str(event.get("date") or "")[:10]
        if event_date:
            ledger_by_date.setdefault(event_date, []).append(event)

    position_series: list[float] = []
    current_position = 0.0
    for date in dates:
        for event in ledger_by_date.get(str(date)[:10], []):
            event_position = _evidence_float(event.get("position"))
            if event_position is not None:
                current_position = float(event_position)
        position_series.append(round(current_position, 4))

    total_realized = sum(
        float(value)
        for event in ledger
        for value in [_evidence_float(event.get("pnl_realise"))]
        if value is not None
    )
    total_return = float(total_realized / opened_notional) if opened_notional > 0.0 else 0.0
    years = max(len(dates), 1) / 252.0
    cagr = float((1.0 + total_return) ** (1.0 / years) - 1.0) if total_return > -1.0 else -1.0
    hit_rate = float(np.mean([value > 0.0 for value in gross_returns])) if gross_returns else None
    var95, cvar95 = _evidence_tail_risk(net_returns)
    distribution_metrics = _evidence_trade_distribution_metrics(
        net_returns,
        equity,
        dates=dates,
        benchmark_returns=benchmark_returns,
        benchmark_symbol=benchmark_symbol,
        min_sample_n=EVIDENCE_MIN_SAMPLE_N,
    )

    warning_sample_n = len(action_trades) if direction in {"long", "short"} else len(stock_returns)
    warnings: list[str] = []
    if warning_sample_n < EVIDENCE_MIN_SAMPLE_N:
        sample_label = "OOS trades" if direction in {"long", "short"} else "neutral OOS samples"
        warnings.append(
            f"Too few {sample_label}: n={warning_sample_n}, minimum={EVIDENCE_MIN_SAMPLE_N}. "
            "Shown for audit only; do not treat as a proven edge."
        )

    has_candles = (
        open_prices is not None
        and high is not None
        and low is not None
        and len(open_prices) == len(dates)
        and len(high) == len(dates)
        and len(low) == len(dates)
        and len(close) == len(dates)
    )

    return {
        "status": "succeeded",
        "source": "wfo",
        "score_mode": score_mode or "fold_scoped_winner",
        "match_mode": "exact_bucket",
        "bucket": bucket,
        "direction": direction,
        "cooldown_bars": max(0, int(cooldown_bars or 0)),
        "stitched_window_start": stitched_window_start or (dates[0] if dates else None),
        "stitched_window_end": stitched_window_end or (dates[-1] if dates else None),
        "proof": proof_summary or {},
        "dates": dates,
        "open_series": open_prices if has_candles else [],
        "high_series": high if has_candles else [],
        "low_series": low if has_candles else [],
        "close_series": close,
        "position_series": position_series,
        "benchmark_returns": benchmark_returns if benchmark_returns is not None else [],
        "benchmark_symbol": benchmark_symbol,
        "benchmark_status": "available" if benchmark_returns is not None else "unavailable",
        "equity": equity,
        "trades": trades,
        "trade_ledger": ledger,
        "warnings": warnings,
        "metrics": {
            "total_return": total_return,
            "cagr": cagr,
            "sharpe": _evidence_trade_sharpe(net_returns, dates) if net_returns else None,
            "max_drawdown": _evidence_max_drawdown(equity),
            "win_rate": hit_rate,
            "hit_rate": hit_rate,
            "n_trades": len(action_trades),
            "cooldown_bars": max(0, int(cooldown_bars or 0)),
            "cooldown_filtered_trades": max(0, int(raw_trade_count or len(action_trades)) - len(action_trades)),
            "expected_return_gross": _evidence_mean(gross_returns),
            "expected_return_net": _evidence_mean(net_returns),
            "stock_expected_return": _evidence_mean(stock_returns),
            "var95": var95,
            "cvar95": cvar95,
            **distribution_metrics,
        },
    }


def _signal_evidence_oos_periods(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    source: str,
    variant: str,
    edge: dict[str, Any],
    contributors: list[dict[str, Any]],
    cost_bps: float,
    cooldown_bars: int = 0,
    proof_limit: int | None = 100,
    proof_limit_label: str = "100",
) -> tuple[list[dict[str, Any]], int, dict[str, Any] | None]:
    """Rebuild the exact OOS sample behind edge E[R] and hit-rate metrics."""
    try:
        from services.api.app import models
        from ..analytics import (
            _edge_db_horizons,
            _load_pricing_data,
            _load_score_history,
            _resolve_score_source,
        )
        from core.quant_core.horizons import HORIZON_SPECS
        from core.quant_core.research.edge import (
            ExitCandidate,
            _normalized_price_frame,
            _sample_frames,
            _strategy_returns_array,
        )
        from core.quant_core.research.oos_index import oos_sample_for
        from core.quant_core.research.score_history import aggregate_subset, _bucket_for
    except Exception:
        logger.exception("signal evidence imports failed")
        return [], 0, None

    try:
        source_spec = _resolve_score_source(source, variant)
        canonical_h = canonical_horizon(horizon, allow_legacy=True)
        spec = HORIZON_SPECS[canonical_h]
        public_source = "wfo" if source_spec.axis == "wfo" else "signal_engine"
        if public_source != "wfo":
            return [], 0, None
        db_sources = source_spec.read_sources
        variants = signal_mode_read_names(source_spec.variant)
        db_horizons = _edge_db_horizons(canonical_h)

        series_by_cat = _load_score_history(
            db,
            symbol=symbol,
            source=source_spec.canonical_source,
            horizon=canonical_h,
        )
        score = aggregate_subset(series_by_cat, list(series_by_cat.keys())) if series_by_cat else None
        if score is None or score.dropna().empty:
            return [], 0, None

        prices = _load_pricing_data(db, symbol)
        price_frame = _normalized_price_frame(prices)
        price_index = pd.DatetimeIndex(price_frame.index)

        def wfo_loader(sym: str, _h: str) -> dict[str, Any]:
            from ...services.wfo_folds import normalize_wfo_folds_json

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
                    return {
                        "folds_json": normalize_wfo_folds_json(
                            summary.folds_json,
                            config_json=summary.config_json,
                            ohlcv_index=price_index,
                        )
                    }
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
            wfo_loader=wfo_loader,
            score_history_loader=None,
            ohlcv_index_loader=lambda _sym: price_index,
            holdout_bars=spec.signal_engine_holdout_bars,
        )
        proof_oos_sample = oos_sample

        bucket = str(edge.get("bucket") or "").strip()
        if not bucket:
            live_score = float(score.dropna().iloc[-1])
            bucket = _bucket_for(live_score)
        direction = str(edge.get("direction") or "").strip().lower()
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
            oos_sample=proof_oos_sample,
            today_bucket=bucket,
            fwd_horizon_bars=fwd_horizon,
            return_calc_method=return_calc_method,
            max_lookback_years=None,
            n_target=None,
            exit_candidate=selected_exit,
        )

        windows = list(proof_oos_sample.windows or [])
        if not windows and not sample_df.empty:
            from core.quant_core.research.oos_index import OosWindow

            windows = [
                OosWindow(
                    fold_id=None,
                    start=pd.Timestamp(sample_df.index.min()),
                    end=pd.Timestamp(sample_df.index.max()),
                )
            ]

        period_contributors = _period_contributors_for_evidence(
            db,
            symbol=symbol,
            horizon=canonical_h,
            source=public_source,
            variant=source_spec.variant,
            windows=windows,
            fallback_contributors=contributors,
        )

        periods: list[dict[str, Any]] = []
        for idx, window in enumerate(windows):
            periods.append({
                "window_index": idx,
                "fold_id": getattr(window, "fold_id", None),
                "start_date": _evidence_iso_date(getattr(window, "start", None)),
                "end_date": _evidence_iso_date(getattr(window, "end", None)),
                "score_mode": getattr(proof_oos_sample, "score_mode", None),
                "sample_n": 0,
                "hit_rate": None,
                "action_expected_return_gross": None,
                "action_expected_return_net": None,
                "stock_expected_return": None,
                "indicator_count": len(period_contributors.get(idx, [])),
                "contributors": period_contributors.get(idx, []),
                "trades": [],
            })

        def _period_index_for_date(ts: pd.Timestamp) -> int | None:
            for idx, window in enumerate(windows):
                start = pd.Timestamp(getattr(window, "start", None))
                end = pd.Timestamp(getattr(window, "end", None))
                if start <= ts <= end:
                    return idx
            return None

        c = float(cost_bps) * 1e-4
        sample_df = sample_df.sort_index()
        raw_returns = sample_df["fwd"].to_numpy(dtype="float64") if not sample_df.empty else np.array([], dtype="float64")
        gross_returns = _strategy_returns_array(raw_returns, direction, c, include_costs=False)
        net_returns = _strategy_returns_array(raw_returns, direction, c, include_costs=True)

        all_trades: list[dict[str, Any]] = []
        for row_idx, (signal_date, row) in enumerate(sample_df.sort_index().iterrows()):
            signal_ts = pd.Timestamp(signal_date)
            try:
                pos = price_index.get_loc(signal_ts)
            except KeyError:
                continue
            if not isinstance(pos, (int, np.integer)):
                continue
            entry_pos = int(pos) + int(selected_exit.entry_lag_bars)
            exit_pos = int(pos) + int(selected_exit.exit_lag_bars)
            if entry_pos < 0 or exit_pos < 0 or entry_pos >= len(price_index) or exit_pos >= len(price_index):
                continue
            entry_kind = selected_exit.entry_price_kind
            exit_kind = selected_exit.exit_price_kind
            entry_price = _evidence_float(price_frame.iloc[entry_pos][entry_kind])
            exit_price = _evidence_float(price_frame.iloc[exit_pos][exit_kind])
            entry_close_price = _evidence_float(price_frame.iloc[entry_pos]["close"])
            exit_close_price = _evidence_float(price_frame.iloc[exit_pos]["close"])
            raw = _evidence_float(row.get("fwd"))
            period_idx = _period_index_for_date(signal_ts)
            if period_idx is None:
                continue
            is_actionable = direction in {"long", "short"}
            gross = (
                float(gross_returns[row_idx])
                if is_actionable and row_idx < len(gross_returns) and np.isfinite(gross_returns[row_idx])
                else None
            )
            net = (
                float(net_returns[row_idx])
                if is_actionable and row_idx < len(net_returns) and np.isfinite(net_returns[row_idx])
                else None
            )
            trade = {
                "trade_id": f"wfo-{period_idx}-{signal_ts.date().isoformat()}-{row_idx}",
                "fold_id": periods[period_idx].get("fold_id"),
                "signal_date": signal_ts.date().isoformat(),
                "bucket": str(row.get("bucket") or bucket),
                "direction": direction,
                "score_pct": _evidence_float(row.get("score")),
                "entry_date": pd.Timestamp(price_index[entry_pos]).date().isoformat(),
                "entry_price": entry_price,
                "entry_close_price": entry_close_price,
                "entry_price_kind": entry_kind,
                "exit_date": pd.Timestamp(price_index[exit_pos]).date().isoformat(),
                "exit_price": exit_price,
                "exit_close_price": exit_close_price,
                "exit_price_kind": exit_kind,
                "exit_timing_label": str(edge.get("exit_timing_label") or selected_exit.label),
                "holding_period_bars": int(selected_exit.horizon_bars),
                "stock_return": raw,
                "action_return_gross": gross,
                "action_return_net": net,
                "is_hit": bool(gross is not None and gross > 0.0),
                "cost_bps_per_side": float(cost_bps),
            }
            all_trades.append(trade)

        raw_action_trade_count = sum(
            1
            for trade in all_trades
            if str(trade.get("direction") or "").strip().lower() in {"long", "short"}
        )
        all_trades = _apply_evidence_trade_cooldown(all_trades, price_index, cooldown_bars)
        all_trades = sorted(
            all_trades,
            key=lambda trade: (
                str(trade.get("signal_date") or ""),
                str(trade.get("entry_date") or ""),
                str(trade.get("exit_date") or ""),
                str(trade.get("trade_id") or ""),
            ),
        )
        proof_trades = all_trades if proof_limit is None else all_trades[-max(0, int(proof_limit)):]
        proof_summary = _evidence_trade_proof_summary(
            proof_trades,
            direction=direction,
            proof_limit_label=proof_limit_label,
        )
        for period in periods:
            period["trades"] = []
        if direction in {"long", "short"}:
            for trade in all_trades:
                signal_value = trade.get("signal_date")
                if not signal_value:
                    continue
                period_idx = _period_index_for_date(pd.Timestamp(signal_value))
                if period_idx is not None:
                    periods[period_idx]["trades"].append(trade)

        total_trades = 0
        for period in periods:
            trades = period["trades"]
            total_trades += len(trades)
            period["sample_n"] = len(trades)
            if not trades:
                continue
            gross_vals = [float(t["action_return_gross"]) for t in trades if t.get("action_return_gross") is not None]
            net_vals = [float(t["action_return_net"]) for t in trades if t.get("action_return_net") is not None]
            stock_vals = [float(t["stock_return"]) for t in trades if t.get("stock_return") is not None]
            period["hit_rate"] = sum(1 for t in trades if t.get("is_hit")) / len(trades)
            period["action_expected_return_gross"] = float(np.mean(gross_vals)) if gross_vals else None
            period["action_expected_return_net"] = float(np.mean(net_vals)) if net_vals else None
            period["stock_expected_return"] = float(np.mean(stock_vals)) if stock_vals else None

        chart_dates, chart_open, chart_high, chart_low, chart_close = _evidence_chart_frame(
            price_index,
            price_frame,
            windows,
            all_trades,
        )
        stitched_window_starts = [
            _evidence_iso_date(getattr(window, "start", None))
            for window in windows
            if getattr(window, "start", None) is not None
        ]
        stitched_window_ends = [
            _evidence_iso_date(getattr(window, "end", None))
            for window in windows
            if getattr(window, "end", None) is not None
        ]
        benchmark_returns, benchmark_symbol = _evidence_benchmark_returns(db, chart_dates)
        stitched = _evidence_stitched_backtest(
            dates=chart_dates,
            open_prices=chart_open,
            high=chart_high,
            low=chart_low,
            close=chart_close,
            trades=all_trades,
            bucket=bucket,
            direction=direction,
            score_mode=getattr(proof_oos_sample, "score_mode", None),
            cost_bps=float(cost_bps),
            cooldown_bars=max(0, int(cooldown_bars or 0)),
            raw_trade_count=raw_action_trade_count,
            proof_summary=proof_summary,
            stitched_window_start=min(stitched_window_starts) if stitched_window_starts else None,
            stitched_window_end=max(stitched_window_ends) if stitched_window_ends else None,
            benchmark_returns=benchmark_returns,
            benchmark_symbol=benchmark_symbol,
        )

        return periods, total_trades, stitched
    except Exception:
        logger.exception(
            "failed to build signal evidence OOS periods",
            extra={"symbol": symbol, "horizon": horizon, "source": source, "variant": variant},
        )
        try:
            db.rollback()
        except Exception:
            pass
        return [], 0, None


def _edge_with_stitched_evidence(edge: dict[str, Any], stitched: dict[str, Any] | None) -> dict[str, Any]:
    if not stitched:
        return edge
    metrics = stitched.get("metrics") if isinstance(stitched.get("metrics"), dict) else {}
    proof = stitched.get("proof") if isinstance(stitched.get("proof"), dict) else {}
    out = dict(edge)
    dates = stitched.get("dates") if isinstance(stitched.get("dates"), list) else []
    n_trades = int(proof.get("n_trades") if proof.get("n_trades") is not None else metrics.get("n_trades") or 0)
    direction = str(stitched.get("direction") or out.get("direction") or "").strip().lower()
    has_action = direction in {"long", "short"}
    out["stitched_window_start"] = stitched.get("stitched_window_start") or (dates[0] if dates else out.get("stitched_window_start"))
    out["stitched_window_end"] = stitched.get("stitched_window_end") or (dates[-1] if dates else out.get("stitched_window_end"))
    if proof.get("limit") is not None:
        out["proof_limit"] = proof.get("limit")
    if metrics.get("stock_expected_return") is not None:
        out["stock_expected_return"] = metrics.get("stock_expected_return")
    if not has_action:
        out["n"] = n_trades
        out["proof_n"] = n_trades
        out["proof_window_start"] = proof.get("window_start") or out.get("proof_window_start")
        out["proof_window_end"] = proof.get("window_end") or out.get("proof_window_end")
        out["proof_method"] = "no_action_current_signal"
        return out

    out["n"] = n_trades
    out["proof_n"] = n_trades
    out["proof_method"] = "all_wfo_oos_folds_exact_bucket"
    out["window_start"] = proof.get("window_start") or out.get("window_start")
    out["window_end"] = proof.get("window_end") or out.get("window_end")
    out["proof_window_start"] = proof.get("window_start") or out.get("proof_window_start")
    out["proof_window_end"] = proof.get("window_end") or out.get("proof_window_end")
    for target_key, metric_key in (
        ("action_expected_return_gross", "expected_return_gross"),
        ("expected_return_gross", "expected_return_gross"),
        ("action_expected_return_net", "expected_return_net"),
        ("expected_return_net", "expected_return_net"),
        ("action_expected_return_gross_ci_lower", "expected_return_gross_ci_lower"),
        ("action_expected_return_gross_ci_upper", "expected_return_gross_ci_upper"),
        ("expected_return_gross_ci_lower", "expected_return_gross_ci_lower"),
        ("expected_return_gross_ci_upper", "expected_return_gross_ci_upper"),
        ("action_expected_return_net_ci_lower", "expected_return_net_ci_lower"),
        ("action_expected_return_net_ci_upper", "expected_return_net_ci_upper"),
        ("expected_return_net_ci_lower", "expected_return_net_ci_lower"),
        ("expected_return_net_ci_upper", "expected_return_net_ci_upper"),
        ("stock_expected_return", "stock_expected_return"),
        ("stock_expected_return_ci_lower", "stock_expected_return_ci_lower"),
        ("stock_expected_return_ci_upper", "stock_expected_return_ci_upper"),
        ("hit_rate", "hit_rate"),
        ("hit_ci_lower", "hit_ci_lower"),
        ("hit_ci_upper", "hit_ci_upper"),
    ):
        source_metrics = proof if proof else metrics
        if source_metrics.get(metric_key) is not None:
            out[target_key] = source_metrics.get(metric_key)
    gates = dict(out.get("gates") or {}) if isinstance(out.get("gates"), dict) else {}
    if gates:
        from core.quant_core.research.edge import N_MIN, WILSON_LB_THRESHOLD

        hit_ci_lower = _evidence_float(out.get("hit_ci_lower"))
        gates["n"] = bool(n_trades >= int(N_MIN))
        gates["wilson"] = bool(hit_ci_lower is not None and float(hit_ci_lower) > WILSON_LB_THRESHOLD)
        out["gates"] = gates
        out["proven_edge_gross"] = bool(
            gates.get("mc_gross")
            and gates.get("label_shuffle_gross")
            and gates.get("wilson")
            and gates.get("n")
            and gates.get("freshness_gross")
        )
        out["proven_edge_net"] = bool(
            gates.get("mc_net")
            and gates.get("label_shuffle_net")
            and gates.get("wilson")
            and gates.get("n")
            and gates.get("freshness_net")
        )
    return out


def _build_signal_evidence_payload(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    source: str = "auto",
    variant: str | None = None,
    cost_bps: float | None = None,
    cooldown_bars: int = 0,
    proof_limit: str = "100",
) -> dict[str, Any]:
    """Build the full signal-evidence payload for one symbol/horizon.

    Shared by the live ``/signal/evidence`` endpoint and the worker that
    persists the best-WFO evidence snapshot.  Building this is expensive, so the
    worker materializes it weekly and the signal page reads the stored row via
    ``/signal/best-evidence``.
    """
    from ...config import settings

    symbol_upper = symbol.strip().upper()
    if not symbol_upper:
        raise HTTPException(status_code=422, detail="symbol is required")

    canonical_h = _require_canonical_signal_horizon(horizon)
    requested_source = _evidence_source(source)
    cooldown = max(0, min(252, int(cooldown_bars or 0)))
    proof_n_limit, proof_limit_label = _evidence_proof_limit(proof_limit)
    resolved_cost_bps = float(settings.EDGE_COST_BPS_PER_SIDE if cost_bps is None else cost_bps)

    selected_edge, selected_source, selected_variant, method_label = _select_signal_evidence_edge(
        db,
        symbol=symbol_upper,
        horizon=canonical_h,
        source=requested_source,
        variant=variant,
        cost_bps=resolved_cost_bps,
    )
    current = _current_evidence_signal(
        db,
        symbol=symbol_upper,
        horizon=canonical_h,
        source=selected_source,
        variant=selected_variant,
    )
    contributors = _signal_evidence_contributors(
        db,
        symbol=symbol_upper,
        horizon=canonical_h,
        source=selected_source,
        variant=selected_variant,
    )
    oos_periods, evidence_trade_count, stitched_oos_backtest = _signal_evidence_oos_periods(
        db,
        symbol=symbol_upper,
        horizon=canonical_h,
        source=selected_source,
        variant=selected_variant,
        edge=selected_edge,
        contributors=contributors,
        cost_bps=resolved_cost_bps,
        cooldown_bars=cooldown,
        proof_limit=proof_n_limit,
        proof_limit_label=proof_limit_label,
    )
    selected_edge = _edge_with_stitched_evidence(selected_edge, stitched_oos_backtest)

    return {
        "symbol": symbol_upper,
        "horizon": canonical_h,
        "source": selected_source,
        "variant": selected_variant,
        "method_label": method_label,
        "current_signal": {
            **current,
            "bucket": selected_edge.get("bucket"),
            "direction": selected_edge.get("direction"),
        },
        "edge": selected_edge,
        "oos": {
            "proof_window_start": selected_edge.get("proof_window_start") or selected_edge.get("window_start"),
            "proof_window_end": selected_edge.get("proof_window_end") or selected_edge.get("window_end"),
            "proof_n": selected_edge.get("proof_n") or selected_edge.get("n"),
            "proof_method": selected_edge.get("proof_method"),
            "proof_limit": selected_edge.get("proof_limit") or proof_limit_label,
            "stitched_window_start": selected_edge.get("stitched_window_start"),
            "stitched_window_end": selected_edge.get("stitched_window_end"),
            "selection_window_start": selected_edge.get("selection_window_start"),
            "selection_window_end": selected_edge.get("selection_window_end"),
            "selection_n": selected_edge.get("selection_n"),
            "selection_action_expected_return_net": selected_edge.get("selection_action_expected_return_net"),
            "selection_hit_rate": selected_edge.get("selection_hit_rate"),
        },
        "contributors": contributors,
        "contributor_count": len(contributors),
        "factor_condition_count": sum(len(item.get("factor_conditions") or []) for item in contributors),
        "oos_periods": oos_periods,
        "evidence_trade_count": evidence_trade_count,
        "stitched_oos_backtest": stitched_oos_backtest,
    }


def _read_best_evidence_snapshot(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    cooldown_bars: int,
):
    """Load the stored best-evidence snapshot row without any live rebuild.

    Raises 404 when no successful snapshot exists and 409 when the stored
    payload predates the latest market data (the weekly refresh has not caught
    up yet).
    """
    from services.api.app import models

    canonical_h = _require_canonical_signal_horizon(horizon)
    cooldown = max(0, min(252, int(cooldown_bars or 0)))
    row = (
        db.query(models.SignalBestEvidenceSnapshot)
        .filter_by(symbol=symbol, horizon=canonical_h, cooldown_bars=cooldown)
        .first()
    )
    if row is None or str(getattr(row, "status", "") or "") != "succeeded":
        raise HTTPException(
            status_code=404,
            detail=f"No stored best signal evidence for {symbol}/{canonical_h}.",
        )
    market_row = (
        db.query(models.MarketDataStore)
        .filter_by(symbol=symbol, timeframe="1D")
        .first()
    )
    market_as_of = getattr(market_row, "data_as_of", None) if market_row is not None else None
    snapshot_as_of = row.market_data_as_of or row.data_as_of
    if market_as_of is not None and snapshot_as_of is not None and market_as_of > snapshot_as_of:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Stored best signal evidence for {symbol}/{canonical_h} is stale "
                f"(built for {snapshot_as_of.isoformat()}, latest market data is {market_as_of.isoformat()})."
            ),
        )
    return row


@router.get("/signal/evidence", summary="Get auditable OOS evidence for today's selected signal")
def get_signal_evidence(
    symbol: str,
    horizon: CanonicalHorizon,
    source: str = Query("auto", description="auto | signal_engine | wfo"),
    variant: str | None = Query(None, description="Signal mode variant; auto by default"),
    cost_bps: float | None = Query(default=None, ge=0.0, le=500.0),
    cooldown_bars: int = Query(0, ge=0, le=252),
    proof_limit: str = Query("100", description="Proof sample size: 100, 250, 500, or all"),
    db: Session = Depends(get_db),
):
    """Return the OOS proof and signal drivers behind today's tradable signal."""
    return _build_signal_evidence_payload(
        db,
        symbol=symbol,
        horizon=horizon,
        source=source,
        variant=variant,
        cost_bps=cost_bps,
        cooldown_bars=cooldown_bars,
        proof_limit=proof_limit,
    )


@router.get("/signal/best-evidence", summary="Read the stored best-WFO signal evidence snapshot")
def get_signal_best_evidence(
    symbol: str,
    horizon: CanonicalHorizon,
    cooldown_bars: int = Query(0, ge=0, le=252),
    db: Session = Depends(get_db),
):
    """Serve the weekly-materialized best-evidence payload for the signal page.

    Never triggers a live rebuild: returns the stored row, 404 when it has not
    been built, or 409 when it is stale relative to fresh market data.
    """
    symbol_upper = symbol.strip().upper()
    if not symbol_upper:
        raise HTTPException(status_code=422, detail="symbol is required")
    canonical_h = _require_canonical_signal_horizon(horizon)
    row = _read_best_evidence_snapshot(
        db,
        symbol=symbol_upper,
        horizon=canonical_h,
        cooldown_bars=cooldown_bars,
    )
    payload = row.evidence_payload_jsonb
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=404,
            detail=f"Stored best signal evidence for {symbol_upper}/{canonical_h} has no payload.",
        )
    return payload


def _signal_backtest_direction_filter(value: str | None) -> str | None:
    token = str(value or "").strip().lower()
    if not token:
        return None
    aliases = {
        "achat": "long",
        "buy": "long",
        "long": "long",
        "vente": "short",
        "sell": "short",
        "short": "short",
        "hold": "none",
        "neutral": "none",
        "neutre": "none",
        "flat": "none",
        "none": "none",
    }
    if token not in aliases:
        raise HTTPException(status_code=422, detail="selected_direction must be long, short, or none")
    return aliases[token]


def _signal_backtest_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _signal_backtest_numeric_series(values: Any) -> list[float]:
    if not isinstance(values, list):
        return []
    out: list[float] = []
    for value in values:
        number = _signal_backtest_float(value)
        out.append(float(number) if number is not None else 0.0)
    return out


def _signal_backtest_selected_position(position: Any, selected_direction: str | None) -> list[float]:
    values = _signal_backtest_numeric_series(position)
    if selected_direction is None:
        return values
    if selected_direction == "none":
        return [0.0 for _ in values]
    if selected_direction == "long":
        return [value if value > 0.0 else 0.0 for value in values]
    if selected_direction == "short":
        return [value if value < 0.0 else 0.0 for value in values]
    return values


def _signal_backtest_global_score_by_date(db: Session, row: Any) -> dict[str, float]:
    try:
        from ..analytics import _load_score_history, _resolve_score_source
        from core.quant_core.research.score_history import aggregate_subset

        source = "wfo" if str(getattr(row, "source", "")).lower() == "wfo" else "engine"
        source_spec = _resolve_score_source(source, getattr(row, "variant", None))
        series_by_cat = _load_score_history(
            db,
            symbol=str(getattr(row, "symbol", "")).upper(),
            source=source_spec.canonical_source,
            horizon=str(getattr(row, "horizon", "")),
        )
        score = aggregate_subset(series_by_cat, list(series_by_cat.keys())) if series_by_cat else None
        if score is None:
            return {}
        out: dict[str, float] = {}
        for raw_date, raw_value in score.dropna().items():
            value = _signal_backtest_float(raw_value)
            if value is None:
                continue
            out[pd.Timestamp(raw_date).date().isoformat()] = float(value)
        return out
    except Exception:
        logger.debug(
            "could not load global score series for signal backtest ledger",
            exc_info=True,
            extra={
                "symbol": getattr(row, "symbol", None),
                "horizon": getattr(row, "horizon", None),
                "source": getattr(row, "source", None),
                "variant": getattr(row, "variant", None),
            },
        )
        return {}


def _signal_backtest_scope_score_by_date(
    db: Session,
    row: Any,
) -> tuple[dict[str, float], str, str]:
    """Return (score_by_date, score_scope, score_scope_key) for a backtest row.

    Per-category rows aggregate only their scope_key category; combination rows
    average the categories listed in scope_key; global rows blend all categories.
    """
    scope = str(getattr(row, "scope", None) or "global").strip().lower()
    scope_key = str(getattr(row, "scope_key", None) or "global").strip()
    try:
        from ..analytics import _load_score_history, _resolve_score_source
        from core.quant_core.research.score_history import aggregate_subset

        source = "wfo" if str(getattr(row, "source", "")).lower() == "wfo" else "engine"
        source_spec = _resolve_score_source(source, getattr(row, "variant", None))
        series_by_cat = _load_score_history(
            db,
            symbol=str(getattr(row, "symbol", "")).upper(),
            source=source_spec.canonical_source,
            horizon=str(getattr(row, "horizon", "")),
        )
        if not series_by_cat:
            return {}, scope, scope_key

        if scope == "per_category":
            categories = [scope_key]
        elif scope == "combination":
            categories = [c.strip() for c in scope_key.split("+") if c.strip()]
        else:
            categories = list(series_by_cat.keys())

        score = aggregate_subset(series_by_cat, categories)
        if score is None:
            return {}, scope, scope_key

        out: dict[str, float] = {}
        for raw_date, raw_value in score.dropna().items():
            value = _signal_backtest_float(raw_value)
            if value is None:
                continue
            out[pd.Timestamp(raw_date).date().isoformat()] = float(value)
        return out, scope, scope_key
    except Exception:
        logger.debug(
            "could not load scope score series for signal backtest ledger",
            exc_info=True,
            extra={
                "symbol": getattr(row, "symbol", None),
                "horizon": getattr(row, "horizon", None),
                "source": getattr(row, "source", None),
                "variant": getattr(row, "variant", None),
                "scope": scope,
                "scope_key": scope_key,
            },
        )
        return {}, scope, scope_key


def _signal_backtest_score_for_date(score_by_date: dict[str, float] | None, date_value: str) -> float | None:
    if not score_by_date:
        return None
    return score_by_date.get(str(date_value)[:10])


def _signal_backtest_score_series(dates: Any, score_by_date: dict[str, float] | None) -> list[float | None]:
    if not isinstance(dates, list):
        return []
    return [_signal_backtest_score_for_date(score_by_date, str(date)) for date in dates]


def _signal_backtest_representative_lookup(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    variant: str,
    source: str,
    cache: dict[tuple[str, str, str, str], dict[str, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    key = (symbol, horizon, variant, source)
    cached = cache.get(key)
    if cached is not None:
        return cached

    from services.api.app.models import SignalEngineFamilyResult, WfoSignalSummary

    variants = signal_mode_read_names(variant)
    reps: list[dict[str, Any]] = []
    if source == "wfo":
        rows = (
            db.query(WfoSignalSummary)
            .filter(
                WfoSignalSummary.symbol == symbol,
                WfoSignalSummary.horizon == horizon,
                WfoSignalSummary.variant.in_(variants),
                WfoSignalSummary.status == "succeeded",
            )
            .all()
        )
        for row in rows:
            reps.extend(rep for rep in (row.representatives_json or []) if isinstance(rep, dict))
    else:
        rows = (
            db.query(SignalEngineFamilyResult)
            .filter(
                SignalEngineFamilyResult.symbol == symbol,
                SignalEngineFamilyResult.horizon == horizon,
                SignalEngineFamilyResult.variant.in_(variants),
                SignalEngineFamilyResult.status == "succeeded",
            )
            .all()
        )
        for row in rows:
            for raw_rep in row.representatives_json or []:
                if not isinstance(raw_rep, dict):
                    continue
                rep = dict(raw_rep)
                rep.setdefault("family", row.family)
                reps.append(rep)

    lookup: dict[str, dict[str, Any]] = {}
    for rep in reps:
        variant_id = str(rep.get("variant_id") or "").strip()
        if variant_id and variant_id not in lookup:
            lookup[variant_id] = rep
    cache[key] = lookup
    return lookup


def _signal_backtest_merge_params(current: Any, source: Any) -> dict[str, Any]:
    current_params = dict(current) if isinstance(current, dict) else {}
    source_params = source if isinstance(source, dict) else {}
    if not source_params:
        return current_params

    merged = dict(current_params)
    for key, value in source_params.items():
        if key == "components":
            if isinstance(value, list) and not merged.get("components"):
                merged[key] = value
            continue
        if key not in merged:
            merged[key] = value
    return merged


def _signal_backtest_diagnostics_with_source_reps(
    db: Session,
    row: Any,
    *,
    cache: dict[tuple[str, str, str, str], dict[str, dict[str, Any]]],
) -> dict[str, Any] | None:
    diagnostics = row.signal_diagnostics_json
    if not isinstance(diagnostics, dict):
        return diagnostics

    raw_reps = diagnostics.get("representatives")
    if not isinstance(raw_reps, list) or not raw_reps:
        return diagnostics

    lookup = _signal_backtest_representative_lookup(
        db,
        symbol=str(row.symbol),
        horizon=str(row.horizon),
        variant=str(row.variant),
        source="wfo" if str(row.source).lower() == "wfo" else "engine",
        cache=cache,
    )
    if not lookup:
        return diagnostics

    changed = False
    reps: list[Any] = []
    for raw_rep in raw_reps:
        if not isinstance(raw_rep, dict):
            reps.append(raw_rep)
            continue
        rep = dict(raw_rep)
        source_rep = lookup.get(str(rep.get("variant_id") or "").strip())
        if source_rep is None:
            reps.append(rep)
            continue

        merged_params = _signal_backtest_merge_params(rep.get("params"), source_rep.get("params"))
        if merged_params != rep.get("params"):
            rep["params"] = merged_params
            changed = True
        for key in ("family", "archetype", "description"):
            if not rep.get(key) and source_rep.get(key):
                rep[key] = source_rep[key]
                changed = True
        reps.append(rep)

    if not changed:
        return diagnostics
    enriched = dict(diagnostics)
    enriched["representatives"] = reps
    return enriched


def _signal_backtest_trade_ledger(
    row: Any,
    *,
    position_override: list[float] | None = None,
    equity_override: list[float] | None = None,
    score_by_date: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Build a per-fill accounting ledger from persisted signal backtest series."""
    dates = row.dates_json if isinstance(row.dates_json, list) else []
    close = row.close_series_json if isinstance(row.close_series_json, list) else []
    position = position_override if position_override is not None else (
        row.position_series_json if isinstance(row.position_series_json, list) else []
    )
    equity = equity_override if equity_override is not None else (
        row.equity_json if isinstance(row.equity_json, list) else []
    )
    n = min(len(dates), len(close), len(position))
    if n < 2:
        return []

    friction = (float(row.cost_bps or 0.0) + float(row.slippage_bps or 0.0)) / 10_000.0
    ledger: list[dict[str, Any]] = []
    current_position = 0.0
    cmp = 0.0
    cash = 0.0
    realized_cumulative = 0.0

    def _price(index: int) -> float:
        value = close[index]
        return float(value) if isinstance(value, (int, float)) and np.isfinite(value) else 0.0

    def _date(index: int) -> str:
        return str(dates[index])[:10] if index < len(dates) else ""

    def _cum_return(index: int) -> float | None:
        if index < len(equity) and isinstance(equity[index], (int, float)) and np.isfinite(equity[index]):
            return round(float(equity[index]) - 1.0, 10)
        return None

    def _cmp_after_open(price: float, cost: float, new_position: float) -> float:
        if new_position > 0.0:
            return price + cost
        if new_position < 0.0:
            return price - cost
        return 0.0

    def _cash_delta(price: float, prev: float, new: float) -> float:
        delta = 0.0
        if prev > 0.0:
            delta += price - (friction * price)
        elif prev < 0.0:
            delta -= price + (friction * price)
        if new > 0.0:
            delta -= price + (friction * price)
        elif new < 0.0:
            delta += price - (friction * price)
        return delta

    def _append_fill(index: int, prev: float, new: float, *, force_close: bool = False) -> None:
        nonlocal cash, cmp, current_position, realized_cumulative

        price = _price(index)
        pos_change = abs(new - prev)
        total_cost = friction * pos_change * price
        realized = 0.0
        cmp_display = cmp
        previous_cmp = cmp

        if prev == 0.0 and new != 0.0:
            cmp = _cmp_after_open(price, total_cost, new)
            cmp_display = cmp
        elif new == 0.0 and prev != 0.0:
            cmp_display = cmp
            close_cost = friction * abs(prev) * price
            realized = price - cmp - close_cost if prev > 0.0 else cmp - price - close_cost
            cmp = 0.0
            total_cost = close_cost
        elif prev != 0.0 and new != 0.0 and np.sign(prev) != np.sign(new):
            close_cost = friction * abs(prev) * price
            open_cost = friction * abs(new) * price
            realized = price - cmp - close_cost if prev > 0.0 else cmp - price - close_cost
            cmp = _cmp_after_open(price, open_cost, new)
            cmp_display = cmp
            total_cost = close_cost + open_cost
        elif prev != 0.0 and new != 0.0:
            # Defensive path for fractional/sized positions; current signal positions are usually -1/0/+1.
            open_cost = friction * max(0.0, abs(new) - abs(prev)) * price
            close_cost = friction * max(0.0, abs(prev) - abs(new)) * price
            if abs(new) > abs(prev):
                old_basis = abs(prev) * cmp
                added_basis = (abs(new) - abs(prev)) * price + open_cost
                cmp = (old_basis + added_basis) / abs(new) if abs(new) > 0.0 else 0.0
                cmp_display = cmp
            elif abs(new) < abs(prev):
                cmp_display = cmp
                realized = price - cmp - close_cost if prev > 0.0 else cmp - price - close_cost
            total_cost = open_cost + close_cost

        if prev != 0.0 and (
            new == 0.0
            or (new != 0.0 and np.sign(prev) != np.sign(new))
            or abs(new) < abs(prev)
        ):
            latent = price - previous_cmp if prev > 0.0 else previous_cmp - price
        elif new > 0.0:
            latent = price - cmp
        elif new < 0.0:
            latent = cmp - price
        else:
            latent = 0.0

        current_position = new
        cash += _cash_delta(price, prev, new)
        realized_cumulative += realized

        side = "VENTE" if new < prev else "ACHAT"
        if force_close:
            side = "VENTE" if prev > 0.0 else "ACHAT"

        ledger.append({
            "date": _date(index),
            "side": side,
            "global_score_pct": _signal_backtest_score_for_date(score_by_date, _date(index)),
            "prix_execution": round(price, 4),
            "open_t_plus_1": round(price, 4),
            "close_du_jour": round(price, 4),
            "cmp": round(cmp_display, 4),
            "position": round(current_position, 4),
            "return_cumule": _cum_return(index),
            "cash_cumulee": round(cash, 4),
            "tresorerie": round(cash, 4),
            "pnl_realise": round(realized, 4),
            "pnl_realise_cumule": round(realized_cumulative, 4),
            "pnl_latent": round(latent, 4),
            "cout": round(total_cost, 4),
        })

    for idx in range(n):
        raw_position = position[idx]
        next_position = float(raw_position) if isinstance(raw_position, (int, float)) and np.isfinite(raw_position) else 0.0
        if next_position == current_position:
            continue
        _append_fill(idx, current_position, next_position)

    if current_position != 0.0:
        _append_fill(n - 1, current_position, 0.0, force_close=True)

    return ledger


def _signal_backtest_round_trips(
    dates: list[Any],
    close: list[Any],
    position: list[float],
    *,
    friction: float,
    score_by_date: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    n = min(len(dates), len(close), len(position))
    if n < 2:
        return []

    close_values = [_signal_backtest_float(value) for value in close[:n]]
    trades: list[dict[str, Any]] = []
    in_trade = False
    trade_open_idx = 0
    trade_open_price = 0.0
    prev_pos = 0.0

    def _date(index: int) -> str:
        return str(dates[index])[:10] if index < len(dates) else ""

    def _price(index: int) -> float:
        value = close_values[index] if index < len(close_values) else None
        return float(value) if value is not None else 0.0

    def _append_trade(close_idx: int, *, terminal: bool = False) -> None:
        close_price = _price(close_idx)
        if trade_open_price == 0.0:
            pnl = 0.0
        else:
            pnl = (close_price - trade_open_price) / trade_open_price * prev_pos
            pnl -= friction if terminal else friction * 2.0
        open_date = _date(trade_open_idx)
        close_date = _date(close_idx)
        trades.append({
            "open_idx": int(trade_open_idx),
            "close_idx": int(close_idx),
            "open_date": open_date,
            "close_date": close_date,
            "open_price": float(trade_open_price),
            "close_price": float(close_price),
            "bars_held": int(close_idx - trade_open_idx),
            "pnl_return": float(pnl),
            "direction": float(prev_pos),
            "global_score_pct": _signal_backtest_score_for_date(score_by_date, open_date),
            "open_global_score_pct": _signal_backtest_score_for_date(score_by_date, open_date),
            "close_global_score_pct": _signal_backtest_score_for_date(score_by_date, close_date),
        })

    for index, raw_pos in enumerate(position[:n]):
        pos = _signal_backtest_float(raw_pos) or 0.0
        if not in_trade and pos != 0.0:
            in_trade = True
            trade_open_idx = index
            trade_open_price = _price(index)
            prev_pos = pos
        elif in_trade and (pos == 0.0 or np.sign(pos) != np.sign(prev_pos)):
            _append_trade(index)
            if pos != 0.0:
                in_trade = True
                trade_open_idx = index
                trade_open_price = _price(index)
                prev_pos = pos
            else:
                in_trade = False

    if in_trade:
        _append_trade(n - 1, terminal=True)

    return trades


def _signal_backtest_recomputed_payload(
    row: Any,
    *,
    position: list[float],
    score_by_date: dict[str, float] | None = None,
) -> dict[str, Any]:
    dates = row.dates_json if isinstance(row.dates_json, list) else []
    close = row.close_series_json if isinstance(row.close_series_json, list) else []
    n = min(len(dates), len(close), len(position))
    if n < 2:
        equity = [1.0] if n else []
        return {
            "equity": equity,
            "returns": [],
            "trades": [],
            "metrics": {
                "total_return": 0.0,
                "cagr": 0.0,
                "sharpe": 0.0,
                "max_drawdown": 0.0,
                "win_rate": 0.0,
                "n_trades": 0,
            },
            "mc": None,
        }

    close_arr = np.asarray([_signal_backtest_float(value) or 0.0 for value in close[:n]], dtype=np.float64)
    position_arr = np.asarray(position[:n], dtype=np.float64)
    friction = (float(row.cost_bps or 0.0) + float(row.slippage_bps or 0.0)) / 10_000.0
    raw_returns = np.diff(close_arr) / np.where(close_arr[:-1] == 0.0, 1.0, close_arr[:-1])
    pos_change = np.abs(np.diff(np.concatenate(([0.0], position_arr))))
    costs = pos_change[:-1] * friction
    strategy_returns = position_arr[:-1] * raw_returns - costs
    equity_arr = np.concatenate(([1.0], np.cumprod(1.0 + strategy_returns)))
    total_return = float(equity_arr[-1] - 1.0)
    years = (n - 1) / 252.0
    cagr = float((1.0 + total_return) ** (1.0 / years) - 1.0) if years > 0 and total_return > -1.0 else -1.0
    sharpe = 0.0
    if len(strategy_returns) >= 2:
        sigma = float(np.std(strategy_returns, ddof=1))
        if sigma > 0.0:
            sharpe = float(np.mean(strategy_returns) / sigma * np.sqrt(252.0))
    peak = np.maximum.accumulate(equity_arr)
    safe_peak = np.where(peak <= 0.0, 1.0, peak)
    max_drawdown = float(np.max(1.0 - equity_arr / safe_peak)) if len(equity_arr) else 0.0
    trades = _signal_backtest_round_trips(
        dates[:n],
        close[:n],
        position[:n],
        friction=friction,
        score_by_date=score_by_date,
    )
    win_rate = float(np.mean([trade["pnl_return"] > 0.0 for trade in trades])) if trades else 0.0

    mc_result = None
    try:
        method = str(row.mc_method or "block_bootstrap")
        trade_events = None
        if method == "trade_bootstrap":
            if len(trades) >= 10:
                trade_events = {
                    "pnls": [trade["pnl_return"] for trade in trades],
                    "start_indices": [trade["open_idx"] for trade in trades],
                }
            else:
                method = "block_bootstrap"
        mc_result = monte_carlo_equity_paths(
            np.asarray(strategy_returns, dtype=np.float64),
            method=method,
            n_paths=int(row.n_paths or 2000),
            block_mean=getattr(row, "block_mean", None),
            trade_events=trade_events,
            seed=42,
        )
    except Exception:
        logger.debug("could not recompute selected-direction MC payload", exc_info=True)

    return {
        "equity": equity_arr.tolist(),
        "returns": strategy_returns.tolist(),
        "trades": trades,
        "metrics": {
            "total_return": total_return,
            "cagr": cagr,
            "sharpe": sharpe,
            "max_drawdown": max_drawdown,
            "win_rate": win_rate,
            "n_trades": len(trades),
        },
        "mc": mc_result,
    }


