"""Layer C — Robustness scoring.

Computes a reliability_score in [0, 1] from OOS window results.
Viability gate: if fraction_positive_windows < 0.40 or n_valid < min_windows → score = 0.
"""

from __future__ import annotations

import statistics

from .domain import OOSWindowResult, VariantDef, VariantRobustnessSummary


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def score_variant_robustness(
    variant: VariantDef,
    oos_results: list[OOSWindowResult],
    *,
    min_windows: int = 3,
) -> VariantRobustnessSummary:
    """Score a variant's robustness from its OOS window results."""
    valid = [w for w in oos_results if w.is_valid]
    n_oos = len(oos_results)
    n_valid = len(valid)

    if n_valid == 0:
        return VariantRobustnessSummary(
            variant=variant,
            n_oos_windows=n_oos,
            n_valid_windows=0,
            mean_sharpe=0.0, std_sharpe=0.0, median_sharpe=0.0,
            fraction_positive_windows=0.0,
            mean_max_drawdown=0.0,
            reliability_score=0.0,
            is_viable=False,
            cagr=0.0,
            total_pnl=0.0,
        )

    sharpes = [w.sharpe for w in valid]
    drawdowns = [w.max_drawdown for w in valid]

    mean_sharpe = statistics.mean(sharpes)
    std_sharpe = statistics.pstdev(sharpes) if n_valid > 1 else 0.0
    median_sharpe = statistics.median(sharpes)
    frac_positive = sum(1 for s in sharpes if s > 0) / n_valid
    mean_mdd = statistics.mean(drawdowns)
    cagr = statistics.mean(w.cagr for w in valid)
    total_pnl = statistics.mean(w.pnl for w in valid)

    # Viability gate
    is_viable = (n_valid >= min_windows) and (frac_positive >= 0.40)

    if not is_viable:
        return VariantRobustnessSummary(
            variant=variant,
            n_oos_windows=n_oos,
            n_valid_windows=n_valid,
            mean_sharpe=mean_sharpe,
            std_sharpe=std_sharpe,
            median_sharpe=median_sharpe,
            fraction_positive_windows=frac_positive,
            mean_max_drawdown=mean_mdd,
            reliability_score=0.0,
            is_viable=False,
            cagr=cagr,
            total_pnl=total_pnl,
        )

    # Component scores — each in [0, 1]
    sharpe_score = _clamp((mean_sharpe + 0.5) / 2.0)           # maps [-0.5, 1.5] -> [0, 1]
    stability_score = frac_positive                              # already in [0, 1]
    consistency_score = _clamp(1.0 - std_sharpe / (abs(mean_sharpe) + 0.1))
    drawdown_score = _clamp(1.0 - mean_mdd / 0.30)

    reliability = _clamp(
        0.35 * sharpe_score
        + 0.30 * stability_score
        + 0.20 * consistency_score
        + 0.15 * drawdown_score
    )

    return VariantRobustnessSummary(
        variant=variant,
        n_oos_windows=n_oos,
        n_valid_windows=n_valid,
        mean_sharpe=mean_sharpe,
        std_sharpe=std_sharpe,
        median_sharpe=median_sharpe,
        fraction_positive_windows=frac_positive,
        mean_max_drawdown=mean_mdd,
        reliability_score=reliability,
        is_viable=True,
        sharpe_score=sharpe_score,
        stability_score=stability_score,
        consistency_score=consistency_score,
        drawdown_score=drawdown_score,
        cagr=cagr,
        total_pnl=total_pnl,
    )
