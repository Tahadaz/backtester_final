"""Shared RSI semantics for the active signal-engine stack."""

from __future__ import annotations

import numpy as np

from core.quant_core.optimize import rsi_wilder

from .domain import VariantDef, variant_signal_label
from .oos_eval import apply_cooldown, _actions_to_positions


def is_rsi_level_variant(variant: VariantDef) -> bool:
    """Return True when *variant* uses RSI level-action semantics."""
    return variant.family == "rsi" and variant.archetype == "rsi_level"


def compute_rsi_level_actions(close: np.ndarray, variant: VariantDef) -> np.ndarray:
    """Return the raw RSI action stream for an RSI level variant."""
    if not is_rsi_level_variant(variant):
        raise ValueError(f"Variant {variant.variant_id!r} is not an RSI level variant")

    params = variant.params
    period = int(params["period"])
    oversold = float(params["oversold"])
    overbought = float(params["overbought"])
    rsi_vals = rsi_wilder(close, period)
    return np.where(rsi_vals < oversold, 1.0, np.where(rsi_vals > overbought, -1.0, 0.0))


def alternate_rsi_actions(actions: np.ndarray) -> np.ndarray:
    """Suppress repeated same-side RSI actions until the opposite side appears."""
    out = np.zeros_like(actions)
    last_nonzero = 0.0

    for i, value in enumerate(actions):
        if value == 0.0:
            continue
        if value != last_nonzero:
            out[i] = value
            last_nonzero = value

    return out


def actions_to_positions(actions: np.ndarray) -> np.ndarray:
    """Convert RSI action signals to long-only carried positions."""
    return _actions_to_positions(actions)


def compute_rsi_variant_actions(
    close: np.ndarray,
    variant: VariantDef,
    *,
    cooldown_bars: int = 0,
) -> np.ndarray:
    """Return the RSI variant action series after alternation and cooldown."""
    actions = compute_rsi_level_actions(close, variant)
    actions = alternate_rsi_actions(actions)
    return apply_cooldown(actions, cooldown_bars)


def compute_rsi_variant_positions(
    close: np.ndarray,
    variant: VariantDef,
    *,
    cooldown_bars: int = 0,
) -> np.ndarray:
    """Return the carried RSI position series derived from variant actions."""
    return actions_to_positions(
        compute_rsi_variant_actions(close, variant, cooldown_bars=cooldown_bars)
    )


def latest_rsi_variant_signal(
    close: np.ndarray,
    variant: VariantDef,
    *,
    cooldown_bars: int = 0,
) -> tuple[float, str]:
    """Return the latest RSI variant action value and its type-specific label."""
    actions = compute_rsi_variant_actions(close, variant, cooldown_bars=cooldown_bars)
    signal_val = float(actions[-1]) if len(actions) else 0.0
    return signal_val, variant_signal_label(variant.family, signal_val)


def transition_marker_indices(
    signal: np.ndarray,
    *,
    start: int = 0,
    end: int | None = None,
) -> tuple[list[int], list[int]]:
    """Return BUY/SELL marker indices using full-series transition context."""
    if end is None:
        end = len(signal) - 1

    buy_idx: list[int] = []
    sell_idx: list[int] = []
    if start > end or end < 0:
        return buy_idx, sell_idx

    for i in range(max(start, 0), min(end, len(signal) - 1) + 1):
        prev = signal[i - 1] if i > 0 else 0.0
        if signal[i] == 1.0 and prev <= 0.0:
            buy_idx.append(i)
        elif signal[i] == -1.0 and prev >= 0.0:
            sell_idx.append(i)

    return buy_idx, sell_idx


def rsi_window_marker_indices(
    action_signal: np.ndarray,
    position_signal: np.ndarray,
    *,
    start: int,
    end: int,
) -> tuple[list[int], list[int]]:
    """Return RSI window markers with a carry-in marker when a position is already open."""
    buy_idx, sell_idx = transition_marker_indices(action_signal, start=start, end=end)

    if start <= end and 0 <= start < len(position_signal):
        has_marker_at_start = start in buy_idx or start in sell_idx
        if not has_marker_at_start and action_signal[start] == 0.0:
            if position_signal[start] > 0.0:
                buy_idx.insert(0, start)

    return buy_idx, sell_idx
