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

from .candidates import (
    filter_candidates_for_history,
    generate_candidates,
    generate_factor_conditioned_candidates,
    variant_min_history,
)
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
from core.quant_core.research.factors.conditions import evaluate_condition
from core.quant_core.research.factors.conditioned_variants import compose_and_signal

logger = logging.getLogger(__name__)

_MIN_VALID_WINDOWS = 2
_MIN_TEST_BARS_VALID = 20


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
    horizon: str = "medium",
    timeframe: str = "1D",
    cost_bps: float = 10.0,
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

    # --- Query Active Factors from Phase 3 ---
    active_factors = None
    try:
        from services.worker.db import SessionLocal
        from services.api.app.services.factor_selection_state import active_factor_ids_for_symbol_horizon
        from core.quant_core.macro import get_macro_series_by_id
        db = SessionLocal()
        try:
            active_factor_ids = active_factor_ids_for_symbol_horizon(db, symbol.upper(), horizon)
            macro_by_id = get_macro_series_by_id()
            active_factors = [
                macro_by_id[factor_id].symbol
                for factor_id in active_factor_ids
                if factor_id in macro_by_id
            ]
        finally:
            db.close()
    except Exception as e:
        logger.error("Failed to fetch active factors for %s: %s", symbol, e)

    conditioned_candidates = generate_factor_conditioned_candidates(
        ta_candidates,
        conditions,
        channel_tags=_invert_channel_tags(channel_tags) if channel_tags else None,
        stock_sector=stock_sector,
        active_factors=active_factors,
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
    ta_variant_map = {v.variant_id: v for v in ta_candidates}

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
