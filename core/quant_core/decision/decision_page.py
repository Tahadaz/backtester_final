from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Literal, Mapping

from pydantic import BaseModel, Field


DirectionLiteral = Literal["long", "short", "neutral"]
TradeStatusLiteral = Literal["trade", "watch", "no_trade"]


class ScoreLayerModel(BaseModel):
    score: float
    weight: float
    inputs: dict[str, Any] = Field(default_factory=dict)
    thresholds: dict[str, Any] = Field(default_factory=dict)
    explain: str = ""


class ScorePayloadModel(BaseModel):
    total: float
    layers: dict[str, ScoreLayerModel] = Field(default_factory=dict)


class DecisionLevelsModel(BaseModel):
    support: float | None = None
    resistance: float | None = None
    entry: float | None = None
    stop: float | None = None
    target: float | None = None


class DecisionRiskModel(BaseModel):
    rr: float
    risk_per_share: float | None = None
    reward_per_share: float | None = None
    score: float
    invalidation: str


class DecisionPageModel(BaseModel):
    symbol: str
    strategy_kind: str
    trial_id: str
    direction: DirectionLiteral
    status: TradeStatusLiteral
    when_to_act: list[str] = Field(default_factory=list)
    levels: DecisionLevelsModel
    invalidation: str
    risk: DecisionRiskModel
    opportunity: ScorePayloadModel
    confidence: ScorePayloadModel
    opportunity_score: float
    confidence_score: float
    explain: dict[str, Any] = Field(default_factory=dict)
    as_of_date: str | None = None
    generated_at: datetime


def _direction_label(direction: int) -> DirectionLiteral:
    if direction > 0:
        return "long"
    if direction < 0:
        return "short"
    return "neutral"


def _status_from_scores(
    direction: int,
    opp: float,
    conf: float,
    rr: float,
    *,
    levels_valid: bool = True,
) -> TradeStatusLiteral:
    if direction == 0:
        return "no_trade"
    if not levels_valid:
        return "no_trade"
    if opp >= 70.0 and conf >= 65.0 and rr >= 1.5:
        return "trade"
    if opp >= 50.0 and conf >= 45.0 and rr >= 1.0:
        return "watch"
    return "no_trade"


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    if not math.isfinite(out):
        return None
    return out


def _fmt_num(value: Any, digits: int = 2) -> str:
    out = _safe_float(value)
    if out is None:
        return "n/a"
    return f"{out:.{digits}f}"


def _normalize_as_of_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value).strip()
    return text or None


def _trigger_lines(
    *,
    direction: int,
    trigger_snapshot: Mapping[str, Any] | None,
) -> list[str]:
    snapshot = dict(trigger_snapshot or {})
    close = _safe_float(snapshot.get("close"))
    sma50 = _safe_float(snapshot.get("sma50"))
    rsi14 = _safe_float(snapshot.get("rsi14"))
    macd_hist = _safe_float(snapshot.get("macd_hist"))
    vol_ratio = _safe_float(snapshot.get("vol_ratio"))

    if direction > 0:
        lines: list[str] = []
        if rsi14 is not None:
            lines.append(f"RSI14 >= 50 (now: {_fmt_num(rsi14, 2)})")
        if macd_hist is not None:
            lines.append(f"MACD histogram >= 0 (now: {_fmt_num(macd_hist, 4)})")
        if close is not None and sma50 is not None:
            lines.append(f"Close above SMA50 (close: {_fmt_num(close, 4)}, SMA50: {_fmt_num(sma50, 4)})")
        if vol_ratio is not None and len(lines) < 3:
            lines.append(f"Volume ratio >= 1.00 (now: {_fmt_num(vol_ratio, 2)})")
        return lines[:3] or [f"Close >= entry trigger (close: {_fmt_num(close, 4)})"]

    if direction < 0:
        lines = []
        if rsi14 is not None:
            lines.append(f"RSI14 <= 50 (now: {_fmt_num(rsi14, 2)})")
        if macd_hist is not None:
            lines.append(f"MACD histogram <= 0 (now: {_fmt_num(macd_hist, 4)})")
        if close is not None and sma50 is not None:
            lines.append(f"Close below SMA50 (close: {_fmt_num(close, 4)}, SMA50: {_fmt_num(sma50, 4)})")
        if vol_ratio is not None and len(lines) < 3:
            lines.append(f"Volume ratio >= 1.00 (now: {_fmt_num(vol_ratio, 2)})")
        return lines[:3] or [f"Close <= entry trigger (close: {_fmt_num(close, 4)})"]

    return [
        "Signal direction != 0 (now: 0)",
        f"RSI14 crossing 50 can define bias (now: {_fmt_num(rsi14, 2)})",
    ]


def build_decision_page(
    *,
    symbol: str,
    strategy_kind: str,
    trial_id: str,
    strategy_direction: int,
    levels: dict[str, Any],
    risk_payload: dict[str, Any],
    opportunity: dict[str, Any],
    confidence: dict[str, Any],
    extra_explain: dict[str, Any] | None = None,
    as_of_date: str | datetime | None = None,
) -> DecisionPageModel:
    opp_total = float(opportunity.get("total") or 0.0)
    conf_total = float(confidence.get("total") or 0.0)
    rr = float(risk_payload.get("rr") or 0.0)
    levels_valid = bool(risk_payload.get("levels_valid", True))
    invalid_reason = str(risk_payload.get("invalid_reason") or "").strip() or None
    status = _status_from_scores(strategy_direction, opp_total, conf_total, rr, levels_valid=levels_valid)

    direction_label = _direction_label(strategy_direction)
    support = levels.get("support")
    resistance = levels.get("resistance")
    entry = levels.get("entry")
    stop = levels.get("stop")
    target = levels.get("target")
    trigger_snapshot = opportunity.get("trigger_snapshot") if isinstance(opportunity, dict) else {}
    trigger_snapshot = dict(trigger_snapshot) if isinstance(trigger_snapshot, Mapping) else {}

    explain = dict(extra_explain or {})
    explain.setdefault("status_rule", {"trade": "opp>=70 & conf>=65 & rr>=1.5", "watch": "opp>=50 & conf>=45 & rr>=1.0"})
    explain.setdefault("trigger_snapshot", trigger_snapshot)
    if not levels_valid:
        explain["risk_validation"] = {
            "levels_valid": False,
            "invalid_reason": invalid_reason,
            "message": "Risk/reward levels are invalid for this direction; status forced to no_trade.",
        }

    model = DecisionPageModel(
        symbol=str(symbol),
        strategy_kind=str(strategy_kind).strip().lower(),
        trial_id=str(trial_id),
        direction=direction_label,
        status=status,
        when_to_act=_trigger_lines(
            direction=strategy_direction,
            trigger_snapshot=trigger_snapshot,
        ),
        levels=DecisionLevelsModel(
            support=float(support) if support is not None else None,
            resistance=float(resistance) if resistance is not None else None,
            entry=float(entry) if entry is not None else None,
            stop=float(stop) if stop is not None else None,
            target=float(target) if target is not None else None,
        ),
        invalidation=str(risk_payload.get("invalidation") or ""),
        risk=DecisionRiskModel(
            rr=float(risk_payload.get("rr") or 0.0),
            risk_per_share=float(risk_payload.get("risk_per_share")) if risk_payload.get("risk_per_share") is not None else None,
            reward_per_share=float(risk_payload.get("reward_per_share")) if risk_payload.get("reward_per_share") is not None else None,
            score=float(risk_payload.get("score") or 0.0),
            invalidation=str(risk_payload.get("invalidation") or ""),
        ),
        opportunity=ScorePayloadModel.model_validate(opportunity),
        confidence=ScorePayloadModel.model_validate(confidence),
        opportunity_score=opp_total,
        confidence_score=conf_total,
        explain=explain,
        as_of_date=_normalize_as_of_date(as_of_date),
        generated_at=datetime.now(timezone.utc),
    )
    return model
