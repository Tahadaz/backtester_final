from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Iterable, Sequence


OPTION_E_LEVEL_COUNTS = (2, 3, 4)


@dataclass(frozen=True)
class OptionEDiscoveryResult:
    level_count: int
    score: float


def ordered_level_combinations(
    values: Sequence[float],
    level_count: int,
    *,
    non_decreasing: bool = False,
) -> list[tuple[float, ...]]:
    if level_count < 2:
        raise ValueError("level_count must be at least 2")
    if non_decreasing:
        if not values:
            return []
        unique = sorted(set(values))
        return [combo for combo in combinations(unique, level_count)]
    return list(combinations(sorted(set(values)), level_count))


def select_best_level_count(scores: dict[int, float]) -> OptionEDiscoveryResult | None:
    if not scores:
        return None
    level_count, score = max(scores.items(), key=lambda item: item[1])
    return OptionEDiscoveryResult(level_count=level_count, score=score)


def requires_joint_wfo(indicator_param_modes: Iterable[str]) -> bool:
    return any(mode.lower() == "wfo" for mode in indicator_param_modes)

