from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable

from sqlalchemy.orm import Session

from core.quant_core.signal_engine.domain import signal_type_label
from core.quant_core.signal_engine.modes import FUNDAMENTAL_SIGNAL_MODE_NAMES, resolve_signal_mode

from .. import models
from .fundamentals import latest_imports_by_symbol, latest_snapshot_rows_by_symbol


HORIZONS: tuple[str, ...] = ("weekly", "monthly", "quarterly")
PILLAR_TO_SCORE_KEY: dict[str, str] = {
    "fundamental_value": "value",
    "fundamental_quality": "quality",
    "fundamental_growth": "growth",
    "fundamental_risk": "risk",
    "fundamental_cash_flow": "cash_flow",
    "fundamental_health": "health",
}
PILLAR_TO_CATEGORY: dict[str, str] = {
    "fundamental_value": "value",
    "fundamental_quality": "quality",
    "fundamental_growth": "growth",
    "fundamental_risk": "risk",
    "fundamental_cash_flow": "cash_flow",
    "fundamental_health": "health",
}


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and out not in (float("inf"), float("-inf")) else None


def _round(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(float(value), digits)


def _mean(values: Iterable[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return sum(clean) / len(clean) if clean else None


def _score_to_engine(value: Any) -> float | None:
    score = _safe_float(value)
    if score is None:
        return None
    return max(-100.0, min(100.0, (score - 50.0) * 2.0))


def _upside_to_engine(value: Any) -> float | None:
    upside = _safe_float(value)
    if upside is None:
        return None
    return max(-100.0, min(100.0, upside * 250.0))


def _label(score: float | None) -> str | None:
    if score is None:
        return None
    return signal_type_label("aggregate", score)


def _data_as_of(import_row: models.FundamentalImport | None) -> date | None:
    if import_row is None:
        return None
    when = import_row.completed_at or import_row.imported_at or import_row.created_at
    if when is None:
        return None
    if isinstance(when, datetime):
        return when.date()
    return None


def _per_family_payload(
    scores_json: dict[str, Any],
    ensemble: models.FundamentalEnsembleResult | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    per_family: dict[str, dict[str, Any]] = {}
    per_category: dict[str, dict[str, Any]] = {}
    for family, score_key in PILLAR_TO_SCORE_KEY.items():
        score = _score_to_engine(scores_json.get(score_key))
        if score is None:
            continue
        payload = {"score_pct": _round(score), "label": _label(score)}
        per_family[family] = payload
        category = PILLAR_TO_CATEGORY[family]
        per_category[category] = {
            "score_pct": _round(score),
            "label": _label(score),
            "family_scores": {family: payload},
        }

    upside_score = _upside_to_engine(getattr(ensemble, "upside_pct", None))
    if upside_score is not None:
        payload = {"score_pct": _round(upside_score), "label": _label(upside_score)}
        per_family["fundamental_upside"] = payload
        per_category.setdefault(
            "value",
            {"score_pct": _round(upside_score), "label": _label(upside_score), "family_scores": {}},
        )["family_scores"]["fundamental_upside"] = payload
    return per_category, per_family


def _aggregate_score(
    variant: str,
    scores_json: dict[str, Any],
    ensemble: models.FundamentalEnsembleResult | None,
) -> float | None:
    mode = resolve_signal_mode(variant)
    focus = mode.fundamental_focus or "balanced"
    upside_score = _upside_to_engine(getattr(ensemble, "upside_pct", None))
    value_score = _score_to_engine(scores_json.get("value"))
    quality_score = _score_to_engine(scores_json.get("quality"))
    growth_score = _score_to_engine(scores_json.get("growth"))
    if focus == "value":
        return _mean([value_score, upside_score])
    if focus == "quality":
        return quality_score
    if focus == "growth":
        return growth_score
    return _mean(
        [
            _score_to_engine(scores_json.get("overall")),
            value_score,
            quality_score,
            growth_score,
            _score_to_engine(scores_json.get("risk")),
            _score_to_engine(scores_json.get("cash_flow")),
            _score_to_engine(scores_json.get("health")),
            upside_score,
        ]
    )


def _upsert_global_result(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    variant: str,
    status: str,
    aggregate_score_pct: float | None,
    signal_label: str | None,
    per_category_json: dict[str, Any] | None,
    per_family_json: dict[str, Any] | None,
    data_as_of: date | None,
    error_message: str | None,
) -> models.SignalEngineGlobalResult:
    row = (
        db.query(models.SignalEngineGlobalResult)
        .filter_by(symbol=symbol, horizon=horizon, variant=variant)
        .first()
    )
    if row is None:
        row = models.SignalEngineGlobalResult(symbol=symbol, horizon=horizon, variant=variant)
        db.add(row)
    row.status = status
    row.aggregate_score_pct = aggregate_score_pct
    row.expanded_aggregate_score_pct = aggregate_score_pct
    row.signal_label = signal_label
    row.per_category_json = per_category_json or {}
    row.per_family_json = per_family_json or {}
    row.technical_levels_json = {}
    row.support_resistance_json = {}
    row.computed_at = datetime.now(timezone.utc)
    row.data_as_of = data_as_of
    row.error_message = error_message
    return row


def upsert_fundamental_signal_row(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    variant: str = "fundamental_balanced_simple",
) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    mode = resolve_signal_mode(variant)
    if not mode.is_fundamental:
        raise ValueError(f"{variant!r} is not a fundamental signal mode")
    variant = mode.name
    snapshots = latest_snapshot_rows_by_symbol(db, symbols=[symbol])
    snapshot = snapshots.get(symbol)
    imports = latest_imports_by_symbol(db, symbols=[symbol])
    import_row = imports.get(symbol)
    if snapshot is None:
        _upsert_global_result(
            db,
            symbol=symbol,
            horizon=horizon,
            variant=variant,
            status="failed",
            aggregate_score_pct=None,
            signal_label="Indisponible",
            per_category_json={},
            per_family_json={},
            data_as_of=None,
            error_message="No fundamental snapshot",
        )
        return {"symbol": symbol, "horizon": horizon, "variant": variant, "status": "failed", "error": "No fundamental snapshot"}

    ensemble = (
        db.query(models.FundamentalEnsembleResult)
        .filter(
            models.FundamentalEnsembleResult.import_id == snapshot.import_id,
            models.FundamentalEnsembleResult.symbol == symbol,
            models.FundamentalEnsembleResult.scenario == "base",
        )
        .first()
    )
    scores_json = dict(snapshot.scores_json or {})
    per_category, per_family = _per_family_payload(scores_json, ensemble)
    aggregate = _aggregate_score(variant, scores_json, ensemble)
    if aggregate is None:
        status = "failed"
        label = "Indisponible"
        error = "No usable fundamental score"
    else:
        status = "succeeded"
        label = _label(aggregate)
        error = None
    _upsert_global_result(
        db,
        symbol=symbol,
        horizon=horizon,
        variant=variant,
        status=status,
        aggregate_score_pct=_round(aggregate),
        signal_label=label,
        per_category_json=per_category,
        per_family_json=per_family,
        data_as_of=_data_as_of(import_row),
        error_message=error,
    )
    return {
        "symbol": symbol,
        "horizon": horizon,
        "variant": variant,
        "status": status,
        "aggregate_score_pct": _round(aggregate),
        "signal_label": label,
        "error": error,
    }


def upsert_fundamental_signal_rows(
    db: Session,
    *,
    symbols: Iterable[str],
    horizons: Iterable[str] = HORIZONS,
    variants: Iterable[str] = FUNDAMENTAL_SIGNAL_MODE_NAMES,
) -> dict[str, int]:
    results = {"total": 0, "succeeded": 0, "failed": 0}
    for raw_symbol in symbols:
        symbol = str(raw_symbol or "").strip().upper()
        if not symbol:
            continue
        for horizon in horizons:
            for variant in variants:
                row = upsert_fundamental_signal_row(db, symbol=symbol, horizon=horizon, variant=variant)
                results["total"] += 1
                if row.get("status") == "succeeded":
                    results["succeeded"] += 1
                else:
                    results["failed"] += 1
    return results
