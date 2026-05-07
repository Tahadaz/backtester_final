from __future__ import annotations

from dataclasses import dataclass, field
from math import inf
from statistics import mean, pstdev
from typing import Hashable, Mapping, Sequence


@dataclass(frozen=True)
class ProfileResult:
    passes: bool
    reason: str
    detail: str
    pct_profitable: float
    mean_profitable: float | None
    std_profitable: float | None
    winner_smoothed_prom: float | None
    neighborhood_cv: float | None
    warnings: list[str] = field(default_factory=list)


def evaluate_optimization_profile(
    raw_proms: Mapping[Hashable, float],
    smoothed_proms: Mapping[Hashable, float],
    winner_key: Hashable,
    *,
    neighbor_values: Sequence[float] | None = None,
) -> ProfileResult:
    if winner_key not in smoothed_proms:
        raise KeyError("winner_key must exist in smoothed_proms")

    all_proms = list(raw_proms.values())
    profitable_proms = [value for value in all_proms if value > 0]
    pct_profitable = (len(profitable_proms) / len(all_proms)) if all_proms else 0.0
    winner_smoothed = smoothed_proms[winner_key]
    warnings: list[str] = []

    if pct_profitable < 0.05:
        return ProfileResult(
            passes=False,
            reason="catastrophic",
            detail=f"Only {pct_profitable:.0%} profitable (< 5%)",
            pct_profitable=pct_profitable,
            mean_profitable=None,
            std_profitable=None,
            winner_smoothed_prom=winner_smoothed,
            neighborhood_cv=None,
            warnings=warnings,
        )
    if pct_profitable < 0.20:
        return ProfileResult(
            passes=False,
            reason="insufficient",
            detail=f"Only {pct_profitable:.0%} profitable (< 20%)",
            pct_profitable=pct_profitable,
            mean_profitable=None,
            std_profitable=None,
            winner_smoothed_prom=winner_smoothed,
            neighborhood_cv=None,
            warnings=warnings,
        )

    mean_profitable = mean(profitable_proms)
    std_profitable = pstdev(profitable_proms) if len(profitable_proms) > 1 else 0.0
    if winner_smoothed > mean_profitable + std_profitable:
        return ProfileResult(
            passes=False,
            reason="outlier",
            detail=(
                f"Winner PROM {winner_smoothed:.4f} > "
                f"mean+1std {(mean_profitable + std_profitable):.4f}"
            ),
            pct_profitable=pct_profitable,
            mean_profitable=mean_profitable,
            std_profitable=std_profitable,
            winner_smoothed_prom=winner_smoothed,
            neighborhood_cv=None,
            warnings=warnings,
        )

    neighborhood_cv: float | None = None
    if neighbor_values:
        center = mean(neighbor_values)
        neighborhood_cv = inf if center == 0 else pstdev(neighbor_values) / abs(center)
        if neighborhood_cv > 1.5:
            warnings.append(f"high_volatility_landscape:{neighborhood_cv:.2f}")

    return ProfileResult(
        passes=True,
        reason="ok",
        detail="Optimization profile passed",
        pct_profitable=pct_profitable,
        mean_profitable=mean_profitable,
        std_profitable=std_profitable,
        winner_smoothed_prom=winner_smoothed,
        neighborhood_cv=neighborhood_cv,
        warnings=warnings,
    )
