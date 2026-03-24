"""Layer G — Ensemble combination + full pipeline entry point.

run_family_ensemble_full() orchestrates layers A → B → C → D → E → F → G.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np

from .candidates import filter_candidates_for_history, generate_candidates, variant_min_history
from .current_signal import build_current_signal, compute_current_signals
from .domain import (
    CATEGORY_FAMILIES,
    FAMILY_SIGNAL_TYPE,
    HORIZON_PARAMS,
    MethodologyContext,
    MethodologyWindow,
    VALID_HORIZONS,
    EnsemblePipelineDetail,
    FamilyCombinedSignal,
    OOSWindowResult,
    VariantDef,
    VariantCurrentSignal,
    VariantRobustnessSummary,
    signal_type_label,
    variant_signal_label,
)
from .oos_eval import compute_signal_array, evaluate_variant_oos
from .redundancy import reduce_redundancy
from .robustness import score_variant_robustness
from .survivor import filter_survivors

_MIN_VALID_WINDOWS = 3
_MIN_TEST_BARS_VALID = 20
_PREFERRED_ADAPTIVE_TEST = 21
_TARGET_ADAPTIVE_WINDOWS = 3
_MAX_FALLBACK_VARIANTS = 5

# ---------------------------------------------------------------------------
# Layer G — Combine representative signals
# ---------------------------------------------------------------------------


def combine_family_signals(
    signals: list[VariantCurrentSignal],
    family: str | None = None,
) -> tuple[float, str, list[dict[str, Any]]]:
    """Reliability-weighted ensemble → (family_score_pct, label, per_rep)."""
    if not signals:
        return 0.0, "Neutre", []

    total_weight = sum(s.reliability_weight for s in signals)
    if total_weight <= 0:
        return 0.0, "Neutre", []

    score_raw = sum(s.signal * s.reliability_weight for s in signals) / total_weight
    score_pct = 100.0 * score_raw

    label = _score_to_label(score_pct, family)

    per_rep: list[dict[str, Any]] = []
    for s in signals:
        nw = s.reliability_weight / total_weight
        per_rep.append({
            "variant_id": s.variant_id,
            "signal": s.signal,
            "signal_label": s.signal_label,
            "reliability_weight": s.reliability_weight,
            "normalized_weight": round(nw, 4),
            "contribution": round(nw * s.signal, 4),
            "current_close": s.current_close,
            "indicator_value": s.indicator_value,
            "explanation": s.explanation,
        })

    return score_pct, label, per_rep


def _score_to_label(score_pct: float, family: str | None = None) -> str:
    """Score → label. If family given, use type-specific label; else aggregate."""
    if family:
        st = FAMILY_SIGNAL_TYPE.get(family, "trend")
        return signal_type_label(st, score_pct)
    # Aggregate label (no family context)
    return signal_type_label("aggregate", score_pct)


def _nominal_window(horizon: str) -> MethodologyWindow:
    hp = HORIZON_PARAMS[horizon]
    return MethodologyWindow(train=hp["train"], test=hp["test"], step=hp["step"])


def _build_warning_message(
    methodology_mode: str,
    available_bars: int,
    nominal_window: MethodologyWindow,
    effective_window: MethodologyWindow,
) -> str:
    if methodology_mode == "robust_oos_ensemble":
        return ""
    if methodology_mode == "adaptive_oos_ensemble":
        return (
            f"Historique limite: {available_bars} bars disponibles. "
            f"Mode adaptatif utilise au lieu du mode nominal "
            f"({nominal_window.train}/{nominal_window.test}/{nominal_window.step}) avec "
            f"fenetres reduites ({effective_window.train}/{effective_window.test}/{effective_window.step}). "
            "Le signal reste exploitable mais doit etre interprete avec prudence."
        )
    return (
        f"Historique tres limite: {available_bars} bars disponibles. "
        f"Impossible de construire 3 fenetres OOS valides avec un test >= {_MIN_TEST_BARS_VALID} bars. "
        "Signal calcule uniquement sur les donnees disponibles, sans validation OOS complete."
    )


def _resolve_methodology_context(horizon: str, available_bars: int) -> MethodologyContext:
    nominal = _nominal_window(horizon)
    nominal_min_bars = nominal.train + nominal.test + 1
    if available_bars >= nominal_min_bars:
        return MethodologyContext(
            methodology_mode="robust_oos_ensemble",
            available_bars=available_bars,
            nominal_window=nominal,
            effective_window=nominal,
        )

    preferred_test = _PREFERRED_ADAPTIVE_TEST
    if available_bars >= (1 + (_TARGET_ADAPTIVE_WINDOWS * preferred_test) + 1):
        effective = MethodologyWindow(
            train=available_bars - (_TARGET_ADAPTIVE_WINDOWS * preferred_test) - 1,
            test=preferred_test,
            step=preferred_test,
            target_windows=_TARGET_ADAPTIVE_WINDOWS,
        )
        return MethodologyContext(
            methodology_mode="adaptive_oos_ensemble",
            available_bars=available_bars,
            nominal_window=nominal,
            effective_window=effective,
            warning_message=_build_warning_message("adaptive_oos_ensemble", available_bars, nominal, effective),
            is_provisional=True,
        )

    adaptive_test = max(_MIN_TEST_BARS_VALID, (available_bars - 2) // _TARGET_ADAPTIVE_WINDOWS)
    adaptive_train = available_bars - (_TARGET_ADAPTIVE_WINDOWS * adaptive_test) - 1
    if adaptive_test >= _MIN_TEST_BARS_VALID and adaptive_train >= 1:
        effective = MethodologyWindow(
            train=adaptive_train,
            test=adaptive_test,
            step=adaptive_test,
            target_windows=_TARGET_ADAPTIVE_WINDOWS,
        )
        return MethodologyContext(
            methodology_mode="adaptive_oos_ensemble",
            available_bars=available_bars,
            nominal_window=nominal,
            effective_window=effective,
            warning_message=_build_warning_message("adaptive_oos_ensemble", available_bars, nominal, effective),
            is_provisional=True,
        )

    effective = MethodologyWindow(train=0, test=0, step=0, target_windows=_TARGET_ADAPTIVE_WINDOWS)
    return MethodologyContext(
        methodology_mode="live_signal_only",
        available_bars=available_bars,
        nominal_window=nominal,
        effective_window=effective,
        warning_message=_build_warning_message("live_signal_only", available_bars, nominal, effective),
        is_provisional=True,
    )


def _current_signal_entry(
    variant: VariantDef,
    close: np.ndarray,
    *,
    volume: np.ndarray | None = None,
    reliability_weight: float = 0.0,
    selection_status: str,
) -> tuple[VariantCurrentSignal, dict[str, Any]]:
    current = build_current_signal(
        variant,
        close,
        volume=volume,
        reliability_weight=reliability_weight,
    )
    entry = {
        "variant_id": current.variant_id,
        "signal": current.signal,
        "signal_label": current.signal_label,
        "reliability_weight": current.reliability_weight,
        "normalized_weight": 0.0,
        "contribution": 0.0,
        "current_close": current.current_close,
        "indicator_value": current.indicator_value,
        "explanation": current.explanation,
        "params": dict(variant.params),
        "archetype": variant.archetype,
        "selection_status": selection_status,
    }
    return current, entry


def _annotate_weights(entries: list[dict[str, Any]], signals: list[VariantCurrentSignal]) -> None:
    total_weight = sum(s.reliability_weight for s in signals)
    use_equal_weights = total_weight <= 0
    if use_equal_weights:
        total_weight = float(len(signals)) if signals else 0.0
    if total_weight <= 0:
        return
    for entry, signal in zip(entries, signals, strict=False):
        weight = 1.0 if use_equal_weights else max(signal.reliability_weight, 0.0)
        normalized = weight / total_weight
        entry["normalized_weight"] = round(normalized, 4)
        entry["contribution"] = round(normalized * signal.signal, 4)


def _fallback_from_summaries(
    summaries: list[VariantRobustnessSummary],
    close: np.ndarray,
    *,
    volume: np.ndarray | None = None,
    selection_status: str,
) -> tuple[list[VariantCurrentSignal], list[dict[str, Any]], set[str]]:
    ranked = sorted(
        summaries,
        key=lambda s: (s.reliability_score, s.is_viable, -variant_min_history(s.variant)),
        reverse=True,
    )[:_MAX_FALLBACK_VARIANTS]

    signals: list[VariantCurrentSignal] = []
    entries: list[dict[str, Any]] = []
    ids: set[str] = set()
    for summary in ranked:
        current, entry = _current_signal_entry(
            summary.variant,
            close,
            volume=volume,
            reliability_weight=summary.reliability_score,
            selection_status=selection_status,
        )
        signals.append(current)
        entries.append(entry)
        ids.add(summary.variant.variant_id)
    _annotate_weights(entries, signals)
    return signals, entries, ids


def _fallback_live_only(
    candidates: list[VariantDef],
    close: np.ndarray,
    *,
    volume: np.ndarray | None = None,
) -> tuple[list[VariantCurrentSignal], list[dict[str, Any]], set[str], dict[str, str], list[VariantRobustnessSummary]]:
    ranked = sorted(
        candidates,
        key=lambda c: (abs(float(compute_signal_array(close, c, volume=volume)[-1])), -variant_min_history(c), c.variant_id),
        reverse=True,
    )[:_MAX_FALLBACK_VARIANTS]

    signals: list[VariantCurrentSignal] = []
    entries: list[dict[str, Any]] = []
    ids: set[str] = set()
    labels: dict[str, str] = {}
    summaries: list[VariantRobustnessSummary] = []
    for candidate in candidates:
        sig_arr = compute_signal_array(close, candidate, volume=volume)
        labels[candidate.variant_id] = variant_signal_label(candidate.family, float(sig_arr[-1]))
        summaries.append(VariantRobustnessSummary(
            variant=candidate,
            n_oos_windows=0,
            n_valid_windows=0,
            mean_sharpe=0.0,
            std_sharpe=0.0,
            median_sharpe=0.0,
            fraction_positive_windows=0.0,
            mean_max_drawdown=0.0,
            reliability_score=0.0,
            is_viable=False,
            cagr=0.0,
            total_pnl=0.0,
        ))

    for candidate in ranked:
        current, entry = _current_signal_entry(
            candidate,
            close,
            volume=volume,
            reliability_weight=1.0,
            selection_status="live_only_fallback",
        )
        signals.append(current)
        entries.append(entry)
        ids.add(candidate.variant_id)

    _annotate_weights(entries, signals)
    return signals, entries, ids, labels, summaries


# ---------------------------------------------------------------------------
# Full pipeline entry point (family-generic)
# ---------------------------------------------------------------------------


def run_family_ensemble_full(
    family: str,
    close: np.ndarray,
    *,
    volume: np.ndarray | None = None,
    symbol: str,
    horizon: str = "medium",
    timeframe: str = "1D",
    cost_bps: float = 10.0,
    cooldown_bars: int = 0,
) -> EnsemblePipelineDetail:
    """Full A→G pipeline for any indicator family, returning all intermediate data."""
    if horizon not in VALID_HORIZONS:
        raise ValueError(f"Unknown horizon {horizon!r}")

    now_str = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Truncate to horizon-appropriate lookback period
    hp = HORIZON_PARAMS[horizon]
    max_bars = hp["max_years"] * 252
    if len(close) > max_bars:
        close = close[-max_bars:]
        if volume is not None:
            volume = volume[-max_bars:]

    st = FAMILY_SIGNAL_TYPE.get(family, "trend")
    cat = next((k for k, v in CATEGORY_FAMILIES.items() if family in v), "tendance")
    methodology = _resolve_methodology_context(horizon, len(close))

    # Layer A: candidates
    candidates = generate_candidates(family, horizon)
    if methodology.methodology_mode == "adaptive_oos_ensemble":
        candidates = filter_candidates_for_history(candidates, methodology.effective_window.train + 1)
        if not candidates:
            methodology = MethodologyContext(
                methodology_mode="live_signal_only",
                available_bars=methodology.available_bars,
                nominal_window=methodology.nominal_window,
                effective_window=MethodologyWindow(0, 0, 0, target_windows=_TARGET_ADAPTIVE_WINDOWS),
                warning_message=(
                    methodology.warning_message
                    + " Aucune variante n'a assez d'historique chauffe pour un OOS adaptatif; bascule en signal live uniquement."
                ).strip(),
                is_provisional=True,
            )
    elif methodology.methodology_mode == "live_signal_only":
        candidates = filter_candidates_for_history(candidates, len(close))
    tested_count = len(candidates)

    if len(close) == 0 or not candidates:
        signal = FamilyCombinedSignal(
            family=family,
            symbol=symbol,
            horizon=horizon,
            timeframe=timeframe,
            family_score_pct=0.0,
            family_signal_label="Neutre",
            tested_count=tested_count,
            viable_count=0,
            competitive_count=0,
            representative_count=0,
            representatives=[],
            fallback_variants=[],
            score_explanation="Aucune variante exploitable avec l'historique disponible.",
            methodology_status=methodology.methodology_mode,
            methodology_mode=methodology.methodology_mode,
            available_bars=len(close),
            nominal_window=methodology.nominal_window,
            effective_window=methodology.effective_window,
            warning_message=methodology.warning_message,
            is_provisional=methodology.is_provisional,
            as_of=now_str,
            signal_type=st,
            category=cat,
        )
        return EnsemblePipelineDetail(
            signal=signal,
            all_summaries=[],
            oos_windows={},
            survivor_ids=set(),
            representative_ids=set(),
        )

    if methodology.methodology_mode == "live_signal_only":
        fallback_signals, fallback_variants, fallback_ids, current_signal_labels, summaries = _fallback_live_only(
            candidates,
            close,
            volume=volume,
        )
        score_pct, label, _ = combine_family_signals(fallback_signals, family)
        explanation = (
            f"{len(fallback_variants)} variante(s) provisoire(s) basees uniquement sur le signal courant."
            if fallback_variants else
            "Aucune variante provisoire disponible."
        )
        best_id = fallback_variants[0]["variant_id"] if fallback_variants else ""
        signal = FamilyCombinedSignal(
            family=family,
            symbol=symbol,
            horizon=horizon,
            timeframe=timeframe,
            family_score_pct=round(score_pct, 2),
            family_signal_label=label,
            tested_count=tested_count,
            viable_count=0,
            competitive_count=0,
            representative_count=0,
            representatives=[],
            fallback_variants=fallback_variants,
            score_explanation=explanation,
            methodology_status=methodology.methodology_mode,
            methodology_mode=methodology.methodology_mode,
            available_bars=len(close),
            nominal_window=methodology.nominal_window,
            effective_window=methodology.effective_window,
            warning_message=methodology.warning_message,
            is_provisional=methodology.is_provisional,
            as_of=now_str,
            best_variant_id=best_id,
            signal_type=st,
            category=cat,
        )
        return EnsemblePipelineDetail(
            signal=signal,
            all_summaries=summaries,
            oos_windows={c.variant_id: [] for c in candidates},
            survivor_ids=set(),
            representative_ids=set(),
            current_signal_labels=current_signal_labels,
            fallback_variant_ids=fallback_ids,
        )

    # Layer B + C: OOS evaluation + robustness scoring
    summaries: list[VariantRobustnessSummary] = []
    oos_windows: dict[str, list[OOSWindowResult]] = {}
    for c in candidates:
        windows = evaluate_variant_oos(
            close,
            c,
            horizon,
            cost_bps,
            cooldown_bars=cooldown_bars,
            volume=volume,
            window_config=(
                methodology.effective_window
                if methodology.methodology_mode == "adaptive_oos_ensemble"
                else None
            ),
            min_valid_windows=_MIN_VALID_WINDOWS,
            min_test_bars_valid=_MIN_TEST_BARS_VALID,
        )
        oos_windows[c.variant_id] = windows
        summary = score_variant_robustness(c, windows)
        summaries.append(summary)

    viable_count = sum(1 for s in summaries if s.is_viable)

    # Layer D: survivor filtering
    survivors = filter_survivors(summaries)
    competitive_count = len(survivors)
    survivor_ids = {s.variant.variant_id for s in survivors}

    # Compute current signal labels for ALL candidates (type-specific)
    current_signal_labels: dict[str, str] = {}
    for c in candidates:
        sig_arr = compute_signal_array(close, c, volume=volume)
        val = float(sig_arr[-1])
        current_signal_labels[c.variant_id] = variant_signal_label(c.family, val)

    # Layer E: redundancy reduction
    if survivors:
        representatives, redundancy_info, correlation_matrix = reduce_redundancy(
            survivors, close, volume=volume,
        )
    else:
        representatives, redundancy_info, correlation_matrix = [], {}, {}
    representative_count = len(representatives)
    representative_ids = {r.variant.variant_id for r in representatives}

    # Layer F: current signals
    current_signals = compute_current_signals(representatives, close, volume=volume)

    # Layer G: ensemble combination
    score_pct, label, per_rep = combine_family_signals(current_signals, family)

    # Enrich per_rep with variant params and archetype for frontend display
    rep_lookup = {r.variant.variant_id: r.variant for r in representatives}
    for entry in per_rep:
        vdef = rep_lookup.get(entry["variant_id"])
        if vdef:
            entry["params"] = dict(vdef.params)
            entry["archetype"] = vdef.archetype
        entry["selection_status"] = "selected"

    fallback_signals: list[VariantCurrentSignal] = []
    fallback_variants: list[dict[str, Any]] = []
    fallback_variant_ids: set[str] = set()
    if methodology.methodology_mode == "adaptive_oos_ensemble" and not representatives:
        fallback_signals, fallback_variants, fallback_variant_ids = _fallback_from_summaries(
            summaries,
            close,
            volume=volume,
            selection_status="adaptive_fallback",
        )
        if fallback_signals:
            score_pct, label, _ = combine_family_signals(fallback_signals, family)

    # Score explanation
    rep_strs = [
        f"{r['explanation']}" for r in per_rep
    ]
    if representative_count > 0:
        explanation = (
            f"{representative_count} representative(s): "
            + "; ".join(rep_strs)
        )
    elif fallback_variants:
        explanation = (
            "Aucune variante n'a passe le filtrage strict en mode adaptatif. "
            f"{len(fallback_variants)} variante(s) provisoire(s) sont affichees a titre indicatif."
        )
    else:
        explanation = "Aucune variante n'a survecu au filtrage competitif."

    best_id = (
        representatives[0].variant.variant_id if representatives else
        fallback_variants[0]["variant_id"] if fallback_variants else
        max(summaries, key=lambda s: s.reliability_score).variant.variant_id if summaries else
        ""
    )
    signal = FamilyCombinedSignal(
        family=family,
        symbol=symbol,
        horizon=horizon,
        timeframe=timeframe,
        family_score_pct=round(score_pct, 2),
        family_signal_label=label,
        tested_count=tested_count,
        viable_count=viable_count,
        competitive_count=competitive_count,
        representative_count=representative_count,
        representatives=per_rep,
        fallback_variants=fallback_variants,
        score_explanation=explanation,
        methodology_status=methodology.methodology_mode,
        methodology_mode=methodology.methodology_mode,
        available_bars=len(close),
        nominal_window=methodology.nominal_window,
        effective_window=methodology.effective_window,
        warning_message=methodology.warning_message,
        is_provisional=methodology.is_provisional,
        as_of=now_str,
        best_variant_id=best_id,
        signal_type=st,
        category=cat,
    )

    return EnsemblePipelineDetail(
        signal=signal,
        all_summaries=summaries,
        oos_windows=oos_windows,
        survivor_ids=survivor_ids,
        representative_ids=representative_ids,
        current_signal_labels=current_signal_labels,
        redundancy_info=redundancy_info,
        correlation_matrix=correlation_matrix,
        fallback_variant_ids=fallback_variant_ids,
    )


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------


def run_family_ensemble(
    family: str,
    close: np.ndarray,
    *,
    volume: np.ndarray | None = None,
    symbol: str,
    horizon: str = "medium",
    timeframe: str = "1D",
    cost_bps: float = 10.0,
    cooldown_bars: int = 0,
) -> FamilyCombinedSignal:
    """Full A→G pipeline for any family (returns signal only)."""
    detail = run_family_ensemble_full(
        family, close, volume=volume, symbol=symbol, horizon=horizon,
        timeframe=timeframe, cost_bps=cost_bps, cooldown_bars=cooldown_bars,
    )
    return detail.signal


def run_sma_ensemble_full(
    close: np.ndarray,
    *,
    symbol: str,
    horizon: str = "medium",
    timeframe: str = "1D",
    cost_bps: float = 10.0,
    cooldown_bars: int = 0,
) -> EnsemblePipelineDetail:
    """Full A→G pipeline for the SMA family (backward-compat wrapper)."""
    return run_family_ensemble_full(
        "sma", close, symbol=symbol, horizon=horizon,
        timeframe=timeframe, cost_bps=cost_bps, cooldown_bars=cooldown_bars,
    )


def run_sma_ensemble(
    close: np.ndarray,
    *,
    symbol: str,
    horizon: str = "medium",
    timeframe: str = "1D",
    cost_bps: float = 10.0,
    cooldown_bars: int = 0,
) -> FamilyCombinedSignal:
    """Full A→G pipeline for the SMA family (convenience wrapper)."""
    detail = run_sma_ensemble_full(
        close, symbol=symbol, horizon=horizon,
        timeframe=timeframe, cost_bps=cost_bps, cooldown_bars=cooldown_bars,
    )
    return detail.signal
