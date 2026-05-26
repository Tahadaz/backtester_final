from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .domain import VariantDef
from .variant_detail import compute_variant_signal_array

BUY_THRESHOLD = 15.0
SELL_THRESHOLD = -15.0
LEVEL_METHOD = "rep_inversion_v2"
LEVEL_SCAN_POINTS = 161
LEVEL_REFINE_STEPS = 20
SUPPORT_SCAN_MULTIPLIERS = (0.85, 0.7, 0.55, 0.4, 0.3, 0.2, 0.1)
RESISTANCE_SCAN_MULTIPLIERS = (1.15, 1.3, 1.5, 1.8, 2.2, 2.8, 3.5, 5.0, 7.5)
MA_SUPPORT_ARCHETYPES = frozenset({"price_vs_sma", "price_vs_ema", "slope_confirmed"})
METHOD_ORDER = (
    "ma_anchor",
    "score_inversion",
    "swing_levels",
    "pivot_points",
    "fibonacci_pivot",
    "camarilla",
    "woodie",
    "dm",
    "quantile_extrema_atr",
    "fibonacci_retracement",
)


def _to_float(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    if not np.isfinite(out):
        return None
    return out


def round_number(value: Any, digits: int = 6) -> float | None:
    out = _to_float(value)
    if out is None:
        return None
    return round(out, digits)


def collect_weighted_representatives(
    family_snapshots: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, list[tuple[VariantDef, float]]]:
    grouped: dict[str, list[tuple[VariantDef, float]]] = {}
    if not isinstance(family_snapshots, Mapping):
        return grouped

    for family, snapshot in family_snapshots.items():
        reps = snapshot.get("representatives") if isinstance(snapshot, Mapping) else None
        if not isinstance(reps, list):
            continue

        family_group: list[tuple[VariantDef, float]] = []
        for rep in reps:
            if not isinstance(rep, Mapping):
                continue
            weight = _to_float(rep.get("normalized_weight")) or 0.0
            if weight <= 0.0:
                continue

            archetype = str(rep.get("archetype") or "").strip()
            params = rep.get("params") if isinstance(rep.get("params"), Mapping) else {}
            variant_id = str(rep.get("variant_id") or "")
            if not archetype:
                continue

            family_group.append(
                (
                    VariantDef(
                        variant_id=variant_id or f"{family}:{archetype}",
                        family=str(family),
                        archetype=archetype,
                        params=dict(params),
                        description="",
                    ),
                    weight,
                )
            )
        if family_group:
            grouped[str(family)] = family_group

    return grouped


def aggregate_score_from_representatives(
    close: np.ndarray,
    volume: np.ndarray | None,
    grouped_reps: Mapping[str, list[tuple[VariantDef, float]]],
    *,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
) -> float | None:
    family_scores: list[float] = []

    for family_reps in grouped_reps.values():
        if not family_reps:
            continue

        family_weighted_signal = 0.0
        has_variant = False
        for variant, weight in family_reps:
            has_variant = True
            try:
                signal_arr = compute_variant_signal_array(
                    close,
                    variant,
                    volume=volume,
                    high=high,
                    low=low,
                    cooldown_bars=0,
                )
                signal_value = float(signal_arr[-1]) if len(signal_arr) else 0.0
            except Exception:
                signal_value = 0.0
            family_weighted_signal += weight * signal_value

        if has_variant:
            family_scores.append(100.0 * family_weighted_signal)

    if not family_scores:
        return None

    return float(sum(family_scores) / len(family_scores))


def _refine_support_trigger(
    eval_score,
    low_true: float,
    high_false: float,
    *,
    refine_steps: int = LEVEL_REFINE_STEPS,
) -> float:
    lo = min(low_true, high_false)
    hi = max(low_true, high_false)
    for _ in range(max(1, int(refine_steps))):
        mid = (lo + hi) / 2.0
        score = eval_score(mid)
        is_buy = score is not None and score >= BUY_THRESHOLD
        if is_buy:
            lo = mid
        else:
            hi = mid
    return lo


def _refine_resistance_trigger(
    eval_score,
    low_false: float,
    high_true: float,
    *,
    refine_steps: int = LEVEL_REFINE_STEPS,
) -> float:
    lo = min(low_false, high_true)
    hi = max(low_false, high_true)
    for _ in range(max(1, int(refine_steps))):
        mid = (lo + hi) / 2.0
        score = eval_score(mid)
        is_sell = score is not None and score <= SELL_THRESHOLD
        if is_sell:
            hi = mid
        else:
            lo = mid
    return hi


def find_support_trigger(
    close_used: float,
    eval_score,
    *,
    scan_points: int = LEVEL_SCAN_POINTS,
    scan_multipliers: Sequence[float] = SUPPORT_SCAN_MULTIPLIERS,
    refine_steps: int = LEVEL_REFINE_STEPS,
) -> float | None:
    points = max(10, int(scan_points))
    for mult in scan_multipliers:
        low_bound = max(0.01, close_used * mult)
        candidates = np.linspace(close_used, low_bound, points)

        prev_price: float | None = None
        prev_is_buy: bool | None = None
        for candidate in candidates:
            candidate_price = float(candidate)
            score = eval_score(candidate_price)
            is_buy = score is not None and score >= BUY_THRESHOLD

            if is_buy:
                if prev_price is not None and prev_is_buy is False and prev_price > candidate_price:
                    return _refine_support_trigger(
                        eval_score,
                        candidate_price,
                        prev_price,
                        refine_steps=refine_steps,
                    )
                return candidate_price

            prev_price = candidate_price
            prev_is_buy = is_buy

    return None


def find_resistance_trigger(
    close_used: float,
    eval_score,
    *,
    scan_points: int = LEVEL_SCAN_POINTS,
    scan_multipliers: Sequence[float] = RESISTANCE_SCAN_MULTIPLIERS,
    refine_steps: int = LEVEL_REFINE_STEPS,
) -> float | None:
    points = max(10, int(scan_points))
    for mult in scan_multipliers:
        high_bound = max(close_used + 0.01, close_used * mult)
        candidates = np.linspace(close_used, high_bound, points)

        prev_price: float | None = None
        prev_is_sell: bool | None = None
        for candidate in candidates:
            candidate_price = float(candidate)
            score = eval_score(candidate_price)
            is_sell = score is not None and score <= SELL_THRESHOLD

            if is_sell:
                if prev_price is not None and prev_is_sell is False and candidate_price > prev_price:
                    return _refine_resistance_trigger(
                        eval_score,
                        prev_price,
                        candidate_price,
                        refine_steps=refine_steps,
                    )
                return candidate_price

            prev_price = candidate_price
            prev_is_sell = is_sell

    return None


def compute_representative_ma_anchor(
    family_snapshots: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    weighted_sum = 0.0
    weight_sum = 0.0
    plain_values: list[float] = []
    used_representatives: list[dict[str, Any]] = []

    if not isinstance(family_snapshots, Mapping):
        return {
            "anchor": None,
            "representative_count": 0,
            "weight_sum": 0.0,
            "representatives": [],
        }

    for family, snapshot in family_snapshots.items():
        reps = snapshot.get("representatives") if isinstance(snapshot, Mapping) else None
        if not isinstance(reps, list):
            continue

        for rep in reps:
            if not isinstance(rep, Mapping):
                continue
            archetype = str(rep.get("archetype") or "").strip()
            if archetype not in MA_SUPPORT_ARCHETYPES:
                continue

            indicator_value = _to_float(rep.get("indicator_value"))
            if indicator_value is None:
                continue

            plain_values.append(indicator_value)
            rep_weight = _to_float(rep.get("normalized_weight")) or 0.0
            if rep_weight > 0.0:
                weighted_sum += rep_weight * indicator_value
                weight_sum += rep_weight

            used_representatives.append(
                {
                    "family": str(family),
                    "variant_id": str(rep.get("variant_id") or ""),
                    "archetype": archetype,
                    "params": dict(rep.get("params") or {}) if isinstance(rep.get("params"), Mapping) else {},
                    "label": str(rep.get("label") or ""),
                    "indicator_value": indicator_value,
                    "normalized_weight": rep_weight,
                }
            )

    anchor = None
    if weight_sum > 0.0:
        anchor = weighted_sum / weight_sum
    elif plain_values:
        anchor = float(sum(plain_values) / len(plain_values))

    return {
        "anchor": anchor,
        "representative_count": len(used_representatives),
        "weight_sum": weight_sum,
        "representatives": used_representatives,
    }


def compute_score_inversion_levels(
    close: np.ndarray,
    volume: np.ndarray | None,
    family_snapshots: Mapping[str, Mapping[str, Any]] | None,
    *,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    scan_points: int = LEVEL_SCAN_POINTS,
    refine_steps: int = LEVEL_REFINE_STEPS,
    max_evals: int | None = None,
    support_scan_multipliers: Sequence[float] = SUPPORT_SCAN_MULTIPLIERS,
    resistance_scan_multipliers: Sequence[float] = RESISTANCE_SCAN_MULTIPLIERS,
) -> dict[str, Any]:
    close_used = round_number(close[-1], 6) if len(close) > 0 else None
    ma_anchor = compute_representative_ma_anchor(family_snapshots)

    if close_used is None:
        return {
            "close_used": None,
            "support_buy_trigger": None,
            "resistance_sell_trigger": None,
            "support_reference": round_number(ma_anchor.get("anchor"), 6),
            "thresholds": {"buy": BUY_THRESHOLD, "sell": SELL_THRESHOLD},
            "method": LEVEL_METHOD,
        }

    grouped_reps = collect_weighted_representatives(family_snapshots)
    if not grouped_reps:
        return {
            "close_used": close_used,
            "support_buy_trigger": None,
            "resistance_sell_trigger": None,
            "support_reference": round_number(ma_anchor.get("anchor"), 6),
            "thresholds": {"buy": BUY_THRESHOLD, "sell": SELL_THRESHOLD},
            "method": LEVEL_METHOD,
        }

    close_base = close.astype("float64", copy=True)
    volume_base = volume.astype("float64", copy=True) if volume is not None else None
    high_base = high.astype("float64", copy=True) if high is not None else None
    low_base = low.astype("float64", copy=True) if low is not None else None
    score_cache: dict[float, float | None] = {}
    eval_count = 0
    budget_exceeded = False

    def eval_score(candidate_close: float) -> float | None:
        nonlocal eval_count, budget_exceeded
        candidate = max(float(candidate_close), 0.01)
        cache_key = round(candidate, 6)
        if cache_key in score_cache:
            return score_cache[cache_key]
        if max_evals is not None and eval_count >= max(1, int(max_evals)):
            budget_exceeded = True
            return None
        eval_count += 1

        close_candidate = close_base.copy()
        close_candidate[-1] = cache_key
        score = aggregate_score_from_representatives(
            close_candidate,
            volume_base,
            grouped_reps,
            high=high_base,
            low=low_base,
        )
        score_cache[cache_key] = score
        return score

    support = find_support_trigger(
        close_used,
        eval_score,
        scan_points=scan_points,
        scan_multipliers=support_scan_multipliers,
        refine_steps=refine_steps,
    )
    resistance = find_resistance_trigger(
        close_used,
        eval_score,
        scan_points=scan_points,
        scan_multipliers=resistance_scan_multipliers,
        refine_steps=refine_steps,
    )

    return {
        "close_used": close_used,
        "support_buy_trigger": round_number(support, 6),
        "resistance_sell_trigger": round_number(resistance, 6),
        "support_reference": round_number(ma_anchor.get("anchor"), 6),
        "thresholds": {"buy": BUY_THRESHOLD, "sell": SELL_THRESHOLD},
        "method": LEVEL_METHOD,
        "inputs": {
            "eval_count": eval_count,
            "max_evals": int(max_evals) if max_evals is not None else None,
            "budget_exceeded": budget_exceeded,
            "scan_points": int(scan_points),
            "refine_steps": int(refine_steps),
        },
    }


def build_ma_anchor_method(
    anchor_payload: Mapping[str, Any],
    *,
    trend_score_pct: float | None,
) -> dict[str, Any]:
    anchor = _to_float(anchor_payload.get("anchor"))
    rep_count = int(anchor_payload.get("representative_count") or 0)
    method = {
        "id": "ma_anchor",
        "label": "Ancre MA representatives",
        "support": None,
        "resistance": None,
        "status": "unavailable",
        "selected_for_support": False,
        "selected_for_resistance": False,
        "explanation": "Aucune moyenne mobile representative exploitable.",
        "inputs": {
            "anchor": round_number(anchor, 6),
            "representative_count": rep_count,
            "weight_sum": round_number(anchor_payload.get("weight_sum"), 6),
            "representatives": list(anchor_payload.get("representatives") or []),
        },
    }
    if anchor is None or rep_count <= 0:
        return method

    if trend_score_pct is None:
        method["status"] = "ignored"
        method["explanation"] = "Orientation indisponible: tendance non resolue."
        return method

    if trend_score_pct > BUY_THRESHOLD:
        method["support"] = round_number(anchor, 6)
        method["status"] = "available"
        method["explanation"] = "Tendance haussiere: l'ancre MA contribue comme support dynamique."
        return method

    if trend_score_pct < SELL_THRESHOLD:
        method["resistance"] = round_number(anchor, 6)
        method["status"] = "available"
        method["explanation"] = "Tendance baissiere: l'ancre MA contribue comme resistance dynamique."
        return method

    method["status"] = "ignored"
    method["explanation"] = "Tendance neutre: l'ancre MA n'est utilisee ni en support ni en resistance."
    return method


def finalize_support_resistance_methods(
    current_close: float,
    methods: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    finalized: list[dict[str, Any]] = []
    support_candidates: list[tuple[float, int, str]] = []
    resistance_candidates: list[tuple[float, int, str]] = []

    method_rank = {method_id: idx for idx, method_id in enumerate(METHOD_ORDER)}

    for raw_method in methods:
        method = dict(raw_method)
        method_id = str(method.get("id") or "")
        rank = method_rank.get(method_id, len(method_rank))
        support_raw = _to_float(method.get("support"))
        resistance_raw = _to_float(method.get("resistance"))
        support = support_raw if support_raw is not None and support_raw <= current_close else None
        resistance = resistance_raw if resistance_raw is not None and resistance_raw >= current_close else None

        notes: list[str] = []
        if support_raw is not None and support is None:
            notes.append("support > close ignore")
        if resistance_raw is not None and resistance is None:
            notes.append("resistance < close ignore")

        method["support"] = round_number(support, 6)
        method["resistance"] = round_number(resistance, 6)
        method["selected_for_support"] = False
        method["selected_for_resistance"] = False
        method["inputs"] = dict(method.get("inputs") or {})
        method["inputs"]["raw_support"] = round_number(support_raw, 6)
        method["inputs"]["raw_resistance"] = round_number(resistance_raw, 6)

        current_status = str(method.get("status") or "unavailable")
        if support is not None or resistance is not None:
            if current_status not in {"available", "ignored", "unavailable"}:
                current_status = "available"
        elif current_status == "available":
            current_status = "ignored" if notes else "unavailable"
        method["status"] = current_status

        explanation = str(method.get("explanation") or "")
        if notes:
            note_text = "; ".join(notes)
            explanation = f"{explanation} {note_text}." if explanation else f"{note_text}."
        method["explanation"] = explanation.strip()

        if support is not None:
            support_candidates.append((support, rank, method_id))
        if resistance is not None:
            resistance_candidates.append((resistance, rank, method_id))

        finalized.append(method)

    final_support = None
    selected_support_method_id = None
    if support_candidates:
        final_support, _rank, selected_support_method_id = max(
            support_candidates,
            key=lambda item: (item[0], -item[1]),
        )

    final_resistance = None
    selected_resistance_method_id = None
    if resistance_candidates:
        final_resistance, _rank, selected_resistance_method_id = min(
            resistance_candidates,
            key=lambda item: (item[0], item[1]),
        )

    for method in finalized:
        if method.get("id") == selected_support_method_id:
            method["selected_for_support"] = True
        if method.get("id") == selected_resistance_method_id:
            method["selected_for_resistance"] = True

    support_desc = (
        f"support final {round_number(final_support, 6)} via {selected_support_method_id}"
        if final_support is not None and selected_support_method_id
        else "aucun support final"
    )
    resistance_desc = (
        f"resistance finale {round_number(final_resistance, 6)} via {selected_resistance_method_id}"
        if final_resistance is not None and selected_resistance_method_id
        else "aucune resistance finale"
    )

    return {
        "methods": finalized,
        "final_support": round_number(final_support, 6),
        "final_resistance": round_number(final_resistance, 6),
        "selected_support_method_id": selected_support_method_id,
        "selected_resistance_method_id": selected_resistance_method_id,
        "summary_explanation": (
            "Selection finale: max(valid supports <= close) et min(valid resistances >= close). "
            f"{support_desc}; {resistance_desc}."
        ),
    }
