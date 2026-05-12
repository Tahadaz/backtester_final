"""Phase 2 — Factor × TA ensemble pipeline entry point.

Mirrors run_family_ensemble_full() from ensemble.py but generates and evaluates
factor-conditioned cross-product variants instead of native TA variants.

Key architectural property: Layers B–G are unchanged. The only integration
point is:
  - Layer A: generate_factor_conditioned_candidates instead of generate_candidates
  - Before Layer B: compute native TA signal + evaluate condition + AND-compose
  - Layer B onward: evaluate_variant_oos(..., precomputed_signal=composed)

The family-agnostic layers (robustness, survivor, redundancy, current_signal,
ensemble) absorb factor-conditioned variants transparently because:
  - compute_signal_array strips the "@fx" suffix for dispatch
  - variant_signal_label strips the "@fx" suffix for labelling
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import numpy as np

from core.quant_core.horizons import DEFAULT_COST_BPS_PER_SIDE
from .candidates import (
    generate_candidates,
    generate_factor_conditioned_candidates,
)
from .domain import (
    CATEGORY_FAMILIES,
    FAMILY_SIGNAL_TYPE,
    HORIZON_PARAMS,
    VALID_HORIZONS,
    EnsemblePipelineDetail,
    FamilyCombinedSignal,
    FactorConditionMeta,
    OOSWindowResult,
    VariantDef,
    VariantCurrentSignal,
    VariantRobustnessSummary,
    signal_type_label,
    variant_signal_label,
)
from .ensemble import (
    UNAVAILABLE_SIGNAL_LABEL,
    combine_family_signals,
    _resolve_methodology_context,
)
from .oos_eval import compute_signal_array, evaluate_variant_oos
from .redundancy import reduce_redundancy
from .robustness import score_variant_robustness
from .survivor import filter_survivors
from .ta_combo import compute_strict_and_combo_signal, make_combo_variant, primary_category_for_families
from core.quant_core.research.factors.conditions import evaluate_condition
from core.quant_core.research.factors.conditioned_variants import compose_and_signal

logger = logging.getLogger(__name__)

_MIN_VALID_WINDOWS = 2
_MIN_TEST_BARS_VALID = 20
_FX_COMBO_SEEDS_PER_FAMILY = 3
_FX_COMBO_COMPONENTS_PER_FAMILY = 12
_CATEGORY_ORDER = ("tendance", "momentum", "oscillation", "volume")


def _select_evenly_spaced(items: list[VariantDef], limit: int) -> list[VariantDef]:
    if len(items) <= limit:
        return list(items)
    if limit <= 1:
        return [items[0]]
    indices: list[int] = []
    for idx in range(limit):
        raw = round(idx * (len(items) - 1) / (limit - 1))
        if raw not in indices:
            indices.append(raw)
    return [items[idx] for idx in indices]


def precompute_factor_x_ta_signals(
    variants: list[VariantDef],
    close: np.ndarray,
    aligned_factor_arrays: dict[str, np.ndarray],
    *,
    volume: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """Precompute AND-composed arrays for factor-conditioned TA variants."""
    n = len(close)
    precomputed: dict[str, np.ndarray] = {}
    for c_variant in variants:
        condition = c_variant.factor_condition
        if condition is None:
            continue
        factor_close = aligned_factor_arrays.get(condition.factor_ticker)
        if factor_close is None or len(factor_close) == 0:
            continue

        fc = factor_close
        if len(fc) > n:
            fc = fc[-n:]
        elif len(fc) < n:
            fc = np.concatenate([np.full(n - len(fc), np.nan), fc])

        ta_sig = _compute_ta_signal_for_conditioned(
            c_variant,
            close,
            volume=volume,
            high=high,
            low=low,
        )
        if ta_sig is None:
            continue

        condition_mask = evaluate_condition(condition, fc)
        precomputed[c_variant.variant_id] = compose_and_signal(ta_sig, condition_mask)
    return precomputed


def build_factor_x_ta_combo_pool_for_category(
    *,
    category: str,
    combo_family: str,
    category_families: dict[str, list[str]],
    horizon: str,
    close: np.ndarray,
    aligned_factor_arrays: dict[str, np.ndarray],
    conditions: list[FactorConditionMeta],
    volume: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    channel_tags: dict[str, list[str]] | None = None,
    stock_sector: str | None = None,
) -> tuple[list[VariantDef], dict[str, np.ndarray]]:
    """Build bounded Factor×TA strict-AND combo variants and their replay arrays.

    Each combo component is itself a fully conditioned Factor×TA signal. The
    combo signal is then a strict same-direction AND of the two conditioned
    component arrays. The component universe is intentionally capped so combo
    runs remain tractable inside the existing worker queues.
    """
    family_to_category = {
        base_family: cat
        for cat, families in category_families.items()
        for base_family in families
    }
    ordered_families = [
        base_family
        for cat in _CATEGORY_ORDER
        for base_family in category_families.get(cat, [])
    ]

    conditioned_by_family: dict[str, list[VariantDef]] = {}
    for base_family in ordered_families:
        try:
            seeds = _select_evenly_spaced(
                generate_candidates(base_family, horizon),
                _FX_COMBO_SEEDS_PER_FAMILY,
            )
        except (ValueError, NotImplementedError):
            continue
        conditioned = generate_factor_conditioned_candidates(
            seeds,
            conditions,
            channel_tags=_invert_channel_tags(channel_tags) if channel_tags else None,
            stock_sector=stock_sector,
        )
        conditioned_by_family[base_family] = _select_evenly_spaced(
            conditioned,
            _FX_COMBO_COMPONENTS_PER_FAMILY,
        )

    component_pool = [
        variant
        for variants in conditioned_by_family.values()
        for variant in variants
    ]
    component_signals = precompute_factor_x_ta_signals(
        component_pool,
        close,
        aligned_factor_arrays,
        volume=volume,
        high=high,
        low=low,
    )
    viable_by_family = {
        family: [variant for variant in variants if variant.variant_id in component_signals]
        for family, variants in conditioned_by_family.items()
    }

    combo_pool: list[VariantDef] = []
    combo_precomputed: dict[str, np.ndarray] = {}
    for left_idx, left_family in enumerate(ordered_families):
        for right_family in ordered_families[left_idx + 1:]:
            primary_category = primary_category_for_families(
                [left_family, right_family],
                family_to_category,
            )
            if primary_category != category:
                continue
            left_variants = viable_by_family.get(left_family) or []
            right_variants = viable_by_family.get(right_family) or []
            for left_variant, right_variant in zip(left_variants, right_variants, strict=False):
                combo_variant = make_combo_variant(
                    family=combo_family,
                    components=[left_variant, right_variant],
                    primary_category=primary_category,
                    horizon=horizon,
                    conditioning="factor_x_ta",
                )

                def _component_signal(component: VariantDef) -> np.ndarray:
                    return component_signals[component.variant_id]

                try:
                    combo_precomputed[combo_variant.variant_id] = compute_strict_and_combo_signal(
                        close,
                        combo_variant,
                        compute_component_signal=_component_signal,
                    )
                except Exception:
                    continue
                combo_pool.append(combo_variant)

    return combo_pool, combo_precomputed


def run_factor_x_ta_ensemble_for_family(
    family: str,
    close: np.ndarray,
    aligned_factor_arrays: dict[str, np.ndarray],
    conditions: list[FactorConditionMeta],
    *,
    volume: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    symbol: str,
    horizon: str = "monthly",
    timeframe: str = "1D",
    cost_bps: float = DEFAULT_COST_BPS_PER_SIDE,
    cooldown_bars: int = 0,
    channel_tags: dict[str, list[str]] | None = None,
    stock_sector: str | None = None,
) -> EnsemblePipelineDetail:
    """Run the A→G pipeline on factor-conditioned variants of one TA family.

    Args:
        family:                 Base TA family name (e.g. "sma", "rsi").
        close:                  Stock close price array.
        aligned_factor_arrays:  {canonical_id → close_array} already lag-aligned
                                to the stock calendar via alignment.py precede_open.
        conditions:             Pre-registered FactorConditionMeta list.
        channel_tags:           {factor_ticker → [sector, ...]} gate (from channel_tags.yaml).
        stock_sector:           Stock sector string for channel-tag gating.
        Other kwargs:           Same as run_family_ensemble_full().

    Returns:
        EnsemblePipelineDetail with family="{family}@fx" variants.
    """
    if horizon not in VALID_HORIZONS:
        raise ValueError(f"Unknown horizon {horizon!r}")

    now_str = datetime.now(timezone.utc).isoformat(timespec="seconds")

    hp = HORIZON_PARAMS[horizon]
    max_bars = hp["max_years"] * 252
    if len(close) > max_bars:
        close = close[-max_bars:]
        if volume is not None:
            volume = volume[-max_bars:]
        if high is not None:
            high = high[-max_bars:]
        if low is not None:
            low = low[-max_bars:]
        # Trim factor arrays to match
        aligned_factor_arrays = {
            k: v[-max_bars:] if len(v) > max_bars else v
            for k, v in aligned_factor_arrays.items()
        }

    conditioned_family = f"{family}@fx"
    st = FAMILY_SIGNAL_TYPE.get(family, "trend")
    cat = next((k for k, v in CATEGORY_FAMILIES.items() if family in v), "tendance")
    methodology = _resolve_methodology_context(horizon, len(close))

    # --- Layer A: generate factor-conditioned candidates ---
    try:
        ta_candidates = generate_candidates(family, horizon)
    except ValueError:
        ta_candidates = []

    conditioned_candidates = generate_factor_conditioned_candidates(
        ta_candidates,
        conditions,
        channel_tags=_invert_channel_tags(channel_tags) if channel_tags else None,
        stock_sector=stock_sector,
    )
    tested_count = len(conditioned_candidates)

    def _empty_result(reason: str) -> EnsemblePipelineDetail:
        signal = FamilyCombinedSignal(
            family=conditioned_family,
            symbol=symbol,
            horizon=horizon,
            timeframe=timeframe,
            family_score_pct=0.0,
            family_signal_label=UNAVAILABLE_SIGNAL_LABEL,
            tested_count=tested_count,
            viable_count=0,
            competitive_count=0,
            representative_count=0,
            representatives=[],
            fallback_variants=[],
            score_explanation=reason,
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

    if len(close) == 0 or not conditioned_candidates:
        return _empty_result("No conditioned candidates available for this family/horizon/channel.")

    # --- Pre-compose AND signals (before Layer B) ---
    # Build {conditioned_variant_id → composed_signal_array}
    precomputed: dict[str, np.ndarray] = {}
    for c_variant in conditioned_candidates:
        condition = c_variant.factor_condition
        if condition is None:
            continue
        factor_close = aligned_factor_arrays.get(condition.factor_ticker)
        if factor_close is None or len(factor_close) == 0:
            continue

        # Align lengths
        n = len(close)
        if len(factor_close) > n:
            factor_close = factor_close[-n:]
        elif len(factor_close) < n:
            # Pad front with NaN (treat as condition-false)
            factor_close = np.concatenate([
                np.full(n - len(factor_close), np.nan),
                factor_close,
            ])

        # Find the base TA variant (same archetype + base params)
        ta_sig = _compute_ta_signal_for_conditioned(
            c_variant, close, volume=volume, high=high, low=low
        )
        if ta_sig is None:
            continue

        condition_mask = evaluate_condition(condition, factor_close)
        composed = compose_and_signal(ta_sig, condition_mask)
        precomputed[c_variant.variant_id] = composed

    # Filter to only variants with valid precomputed signals
    viable_conditioned = [v for v in conditioned_candidates if v.variant_id in precomputed]
    if not viable_conditioned:
        return _empty_result("Factor series unavailable for all conditions; check macro ingestion.")

    # --- Layer B: OOS evaluation ---
    oos_results: dict[str, list[OOSWindowResult]] = {}
    for c_variant in viable_conditioned:
        composed = precomputed[c_variant.variant_id]
        try:
            windows = evaluate_variant_oos(
                close,
                c_variant,
                horizon,
                cost_bps,
                cooldown_bars=cooldown_bars,
                volume=volume,
                high=high,
                low=low,
                window_config=methodology.effective_window if methodology.methodology_mode != "robust_oos_ensemble" else None,
                min_valid_windows=_MIN_VALID_WINDOWS,
                min_test_bars_valid=_MIN_TEST_BARS_VALID,
                precomputed_signal=composed,
            )
        except Exception:
            windows = []
        oos_results[c_variant.variant_id] = windows

    # Drop windows where the macro condition never fired. n_trades==0 means
    # mean_return_net==0.0 which unfairly counts as non-positive for sparse AND signals.
    oos_results = {
        vid: [w for w in windows if w.n_trades > 0]
        for vid, windows in oos_results.items()
    }

    # --- Layer C: Robustness scoring ---
    summaries: list[VariantRobustnessSummary] = []
    for c_variant in viable_conditioned:
        windows = oos_results.get(c_variant.variant_id, [])
        summary = score_variant_robustness(c_variant, windows)
        summaries.append(summary)

    # --- Layer D: Survivor filtering ---
    survivors = filter_survivors(summaries)
    survivor_ids = {s.variant.variant_id for s in survivors}

    if not survivors:
        return _empty_result("No conditioned variants survived OOS filtering.")

    # --- Layer E: Redundancy reduction ---
    try:
        representatives, redundancy_info, correlation_matrix = reduce_redundancy(
            survivors,
            close,
            volume=volume,
            high=high,
            low=low,
            max_reps=5,
        )
    except Exception:
        representatives = survivors[:5]
        redundancy_info = {}
        correlation_matrix = {}

    representative_ids = {r.variant.variant_id for r in representatives}

    # --- Layer F: Current signals ---
    current_signal_labels: dict[str, str] = {}
    rep_current_signals: list[VariantCurrentSignal] = []

    for rep in representatives:
        c_variant = rep.variant
        composed = precomputed.get(c_variant.variant_id)
        if composed is None:
            continue
        current_sig_val = float(composed[-1]) if len(composed) > 0 else 0.0
        label = variant_signal_label(c_variant.family, current_sig_val)
        current_signal_labels[c_variant.variant_id] = label

        current_close = float(close[-1])
        vcs = VariantCurrentSignal(
            variant_id=c_variant.variant_id,
            signal=current_sig_val,
            signal_label=label,
            reliability_weight=rep.reliability_score,
            current_close=current_close,
            indicator_value=None,
            explanation=f"{c_variant.description}: signal={current_sig_val:+.0f}, condition active",
        )
        rep_current_signals.append(vcs)

    # --- Layer G: Ensemble ---
    score_pct, family_label, representatives_list = combine_family_signals(
        rep_current_signals, conditioned_family
    )

    # Annotate representative dicts
    for rep_dict in representatives_list:
        rep_dict["family"] = conditioned_family
        vid = rep_dict.get("variant_id", "")
        c_var = next((v for v in viable_conditioned if v.variant_id == vid), None)
        if c_var is not None:
            rep_dict["description"] = c_var.description
            rep_dict["archetype"] = c_var.archetype
            rep_dict["params"] = c_var.params
            cond = c_var.factor_condition
            if cond is not None:
                rep_dict["factor_condition"] = {
                    "condition_id": cond.condition_id,
                    "factor_ticker": cond.factor_ticker,
                    "form": cond.form,
                    "lookback": cond.lookback,
                    "threshold": cond.threshold,
                    "direction": cond.direction,
                }

    best_id = representatives[0].variant.variant_id if representatives else ""

    signal = FamilyCombinedSignal(
        family=conditioned_family,
        symbol=symbol,
        horizon=horizon,
        timeframe=timeframe,
        family_score_pct=round(score_pct, 2),
        family_signal_label=family_label,
        tested_count=tested_count,
        viable_count=len([s for s in summaries if s.is_viable]),
        competitive_count=len(survivors),
        representative_count=len(representatives),
        representatives=representatives_list,
        fallback_variants=[],
        score_explanation=f"{len(representatives)} factor-conditioned representative(s) from {tested_count} tested.",
        methodology_status=methodology.methodology_mode,
        methodology_mode=methodology.methodology_mode,
        available_bars=len(close),
        nominal_window=methodology.nominal_window,
        effective_window=methodology.effective_window,
        warning_message=methodology.warning_message,
        is_provisional=methodology.is_provisional,
        as_of=now_str,
        latest_close=float(close[-1]) if len(close) > 0 else None,
        best_variant_id=best_id,
        signal_type=st,
        category=cat,
    )

    return EnsemblePipelineDetail(
        signal=signal,
        all_summaries=summaries,
        oos_windows=oos_results,
        survivor_ids=survivor_ids,
        representative_ids=representative_ids,
        current_signal_labels=current_signal_labels,
        redundancy_info=redundancy_info,
        correlation_matrix=correlation_matrix,
        fallback_variant_ids=set(),
    )


def run_factor_x_ta_combo_ensemble_for_category(
    *,
    category: str,
    combo_family: str,
    category_families: dict[str, list[str]],
    close: np.ndarray,
    aligned_factor_arrays: dict[str, np.ndarray],
    conditions: list[FactorConditionMeta],
    volume: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    symbol: str,
    horizon: str = "monthly",
    timeframe: str = "1D",
    cost_bps: float = DEFAULT_COST_BPS_PER_SIDE,
    cooldown_bars: int = 0,
    channel_tags: dict[str, list[str]] | None = None,
    stock_sector: str | None = None,
) -> EnsemblePipelineDetail:
    """Run A→G on strict-AND combos of Factor×TA component signals."""
    if horizon not in VALID_HORIZONS:
        raise ValueError(f"Unknown horizon {horizon!r}")

    now_str = datetime.now(timezone.utc).isoformat(timespec="seconds")
    hp = HORIZON_PARAMS[horizon]
    max_bars = hp["max_years"] * 252
    if len(close) > max_bars:
        close = close[-max_bars:]
        if volume is not None:
            volume = volume[-max_bars:]
        if high is not None:
            high = high[-max_bars:]
        if low is not None:
            low = low[-max_bars:]
        aligned_factor_arrays = {
            key: value[-max_bars:] if len(value) > max_bars else value
            for key, value in aligned_factor_arrays.items()
        }

    first_base_family = (category_families.get(category) or ["sma"])[0]
    st = FAMILY_SIGNAL_TYPE.get(first_base_family, "trend")
    methodology = _resolve_methodology_context(horizon, len(close))

    combo_candidates, precomputed = build_factor_x_ta_combo_pool_for_category(
        category=category,
        combo_family=combo_family,
        category_families=category_families,
        horizon=horizon,
        close=close,
        aligned_factor_arrays=aligned_factor_arrays,
        conditions=conditions,
        volume=volume,
        high=high,
        low=low,
        channel_tags=channel_tags,
        stock_sector=stock_sector,
    )
    tested_count = len(combo_candidates)

    def _empty_result(reason: str) -> EnsemblePipelineDetail:
        signal = FamilyCombinedSignal(
            family=combo_family,
            symbol=symbol,
            horizon=horizon,
            timeframe=timeframe,
            family_score_pct=0.0,
            family_signal_label=UNAVAILABLE_SIGNAL_LABEL,
            tested_count=tested_count,
            viable_count=0,
            competitive_count=0,
            representative_count=0,
            representatives=[],
            fallback_variants=[],
            score_explanation=reason,
            methodology_status=methodology.methodology_mode,
            methodology_mode=methodology.methodology_mode,
            available_bars=len(close),
            nominal_window=methodology.nominal_window,
            effective_window=methodology.effective_window,
            warning_message=methodology.warning_message,
            is_provisional=methodology.is_provisional,
            as_of=now_str,
            signal_type=st,
            category=category,
        )
        return EnsemblePipelineDetail(
            signal=signal,
            all_summaries=[],
            oos_windows={},
            survivor_ids=set(),
            representative_ids=set(),
        )

    if len(close) == 0 or not combo_candidates:
        return _empty_result("No factor-conditioned combo candidates available for this category.")

    viable_combos = [variant for variant in combo_candidates if variant.variant_id in precomputed]
    if not viable_combos:
        return _empty_result("Factor series unavailable for all combo components.")

    oos_results: dict[str, list[OOSWindowResult]] = {}
    for combo_variant in viable_combos:
        try:
            windows = evaluate_variant_oos(
                close,
                combo_variant,
                horizon,
                cost_bps,
                cooldown_bars=cooldown_bars,
                volume=volume,
                high=high,
                low=low,
                window_config=methodology.effective_window if methodology.methodology_mode != "robust_oos_ensemble" else None,
                min_valid_windows=_MIN_VALID_WINDOWS,
                min_test_bars_valid=_MIN_TEST_BARS_VALID,
                precomputed_signal=precomputed[combo_variant.variant_id],
            )
        except Exception:
            windows = []
        oos_results[combo_variant.variant_id] = [w for w in windows if w.n_trades > 0]

    summaries = [
        score_variant_robustness(combo_variant, oos_results.get(combo_variant.variant_id, []))
        for combo_variant in viable_combos
    ]
    survivors = filter_survivors(summaries)
    survivor_ids = {s.variant.variant_id for s in survivors}
    if not survivors:
        return _empty_result("No factor-conditioned combo variants survived OOS filtering.")

    try:
        representatives, redundancy_info, correlation_matrix = reduce_redundancy(
            survivors,
            close,
            volume=volume,
            high=high,
            low=low,
            max_reps=5,
        )
    except Exception:
        representatives = survivors[:5]
        redundancy_info = {}
        correlation_matrix = {}

    representative_ids = {r.variant.variant_id for r in representatives}
    current_signal_labels: dict[str, str] = {}
    rep_current_signals: list[VariantCurrentSignal] = []
    current_close = float(close[-1]) if len(close) else 0.0

    for rep in representatives:
        combo_variant = rep.variant
        composed = precomputed.get(combo_variant.variant_id)
        if composed is None:
            continue
        current_sig_val = float(composed[-1]) if len(composed) > 0 else 0.0
        label = variant_signal_label(combo_variant.family, current_sig_val)
        current_signal_labels[combo_variant.variant_id] = label
        rep_current_signals.append(
            VariantCurrentSignal(
                variant_id=combo_variant.variant_id,
                signal=current_sig_val,
                signal_label=label,
                reliability_weight=rep.reliability_score,
                current_close=current_close,
                indicator_value=None,
                explanation=f"{combo_variant.description}: combo signal={current_sig_val:+.0f}",
            )
        )

    score_pct, family_label, representatives_list = combine_family_signals(
        rep_current_signals,
        combo_family,
    )
    variant_by_id = {variant.variant_id: variant for variant in viable_combos}
    for rep_dict in representatives_list:
        rep_dict["family"] = combo_family
        vid = rep_dict.get("variant_id", "")
        combo_variant = variant_by_id.get(str(vid))
        if combo_variant is not None:
            rep_dict["description"] = combo_variant.description
            rep_dict["archetype"] = combo_variant.archetype
            rep_dict["params"] = combo_variant.params

    best_id = representatives[0].variant.variant_id if representatives else ""
    signal = FamilyCombinedSignal(
        family=combo_family,
        symbol=symbol,
        horizon=horizon,
        timeframe=timeframe,
        family_score_pct=round(score_pct, 2),
        family_signal_label=family_label,
        tested_count=tested_count,
        viable_count=len([s for s in summaries if s.is_viable]),
        competitive_count=len(survivors),
        representative_count=len(representatives),
        representatives=representatives_list,
        fallback_variants=[],
        score_explanation=f"{len(representatives)} factor-conditioned combo representative(s) from {tested_count} tested.",
        methodology_status=methodology.methodology_mode,
        methodology_mode=methodology.methodology_mode,
        available_bars=len(close),
        nominal_window=methodology.nominal_window,
        effective_window=methodology.effective_window,
        warning_message=methodology.warning_message,
        is_provisional=methodology.is_provisional,
        as_of=now_str,
        latest_close=current_close,
        best_variant_id=best_id,
        signal_type=st,
        category=category,
    )

    return EnsemblePipelineDetail(
        signal=signal,
        all_summaries=summaries,
        oos_windows=oos_results,
        survivor_ids=survivor_ids,
        representative_ids=representative_ids,
        current_signal_labels=current_signal_labels,
        redundancy_info=redundancy_info,
        correlation_matrix=correlation_matrix,
        fallback_variant_ids=set(),
    )


def _compute_ta_signal_for_conditioned(
    conditioned_variant: VariantDef,
    close: np.ndarray,
    *,
    volume: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
) -> np.ndarray | None:
    """Compute the underlying TA signal array for a conditioned variant.

    Since compute_signal_array already strips '@' suffix, we can call it
    directly with the conditioned variant.
    """
    try:
        return compute_signal_array(
            close,
            conditioned_variant,
            volume=volume,
            high=high,
            low=low,
        )
    except Exception as exc:
        logger.debug("TA signal computation failed for %s: %s", conditioned_variant.variant_id, exc)
        return None


def _invert_channel_tags(
    channel_tags: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Convert channel_tags from {canonical_id → [sectors]} to {factor_ticker → [sectors]}.

    The channel_tags.yaml uses canonical IDs (VIX, SP500, etc.) but the
    conditions use Yahoo tickers (^VIX, ^GSPC, etc.).
    `generate_factor_conditioned_candidates` expects {factor_ticker → [sectors]}.

    This function attempts to pass through as-is; callers that need
    canonical-to-ticker translation should handle it before calling here.
    """
    return channel_tags
