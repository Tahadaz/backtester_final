"""Canonical signal-mode resolution.

Signal mode describes the indicator universe, factor conditioning, and
candidate complexity. Signal Engine vs WFO remains a separate source axis.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


SignalUniverse = Literal["legacy", "expanded"]
SignalConditioning = Literal["ta", "factor_x_ta"]
SignalComplexity = Literal["simple", "combo"]


@dataclass(frozen=True)
class SignalMode:
    name: str
    universe: SignalUniverse
    conditioning: SignalConditioning
    complexity: SignalComplexity

    @property
    def is_factor_x_ta(self) -> bool:
        return self.conditioning == "factor_x_ta"

    @property
    def is_combo(self) -> bool:
        return self.complexity == "combo"

    @property
    def is_legacy(self) -> bool:
        return self.universe == "legacy"

    @property
    def is_expanded(self) -> bool:
        return self.universe == "expanded"


SIGNAL_MODES: dict[str, SignalMode] = {
    "legacy_ta_simple": SignalMode("legacy_ta_simple", "legacy", "ta", "simple"),
    "expanded_ta_simple": SignalMode("expanded_ta_simple", "expanded", "ta", "simple"),
    "legacy_factor_x_ta_simple": SignalMode(
        "legacy_factor_x_ta_simple", "legacy", "factor_x_ta", "simple"
    ),
    "expanded_factor_x_ta_simple": SignalMode(
        "expanded_factor_x_ta_simple", "expanded", "factor_x_ta", "simple"
    ),
    "legacy_ta_combo": SignalMode("legacy_ta_combo", "legacy", "ta", "combo"),
    "expanded_ta_combo": SignalMode("expanded_ta_combo", "expanded", "ta", "combo"),
    "legacy_factor_x_ta_combo": SignalMode(
        "legacy_factor_x_ta_combo", "legacy", "factor_x_ta", "combo"
    ),
    "expanded_factor_x_ta_combo": SignalMode(
        "expanded_factor_x_ta_combo", "expanded", "factor_x_ta", "combo"
    ),
}

ALL_SIGNAL_MODE_NAMES: tuple[str, ...] = tuple(SIGNAL_MODES)


SIGNAL_MODE_ALIASES: dict[str, str] = {
    "legacy": "legacy_ta_simple",
    "expanded": "expanded_ta_simple",
    "factor_x_ta": "expanded_factor_x_ta_simple",
}


def resolve_signal_mode(value: str | None) -> SignalMode:
    token = str(value or "expanded").strip().lower()
    token = SIGNAL_MODE_ALIASES.get(token, token)
    try:
        return SIGNAL_MODES[token]
    except KeyError as exc:
        allowed = sorted([*SIGNAL_MODES, *SIGNAL_MODE_ALIASES])
        raise ValueError(f"Unknown signal mode {value!r}; expected one of {allowed}") from exc


def canonical_signal_mode_name(value: str | None) -> str:
    return resolve_signal_mode(value).name


def signal_mode_storage_name(value: str | None) -> str:
    """Return the canonical value used for new persisted rows."""
    return canonical_signal_mode_name(value)


def signal_mode_read_names(value: str | None) -> tuple[str, ...]:
    """Return canonical storage name plus legacy aliases that may exist in old rows."""
    mode = resolve_signal_mode(value)
    names = [mode.name]
    names.extend(
        alias
        for alias, canonical in SIGNAL_MODE_ALIASES.items()
        if canonical == mode.name and alias not in names
    )
    return tuple(names)


def accepted_signal_mode_pattern() -> str:
    names = sorted([*SIGNAL_MODES, *SIGNAL_MODE_ALIASES])
    return "^(" + "|".join(names) + ")$"
