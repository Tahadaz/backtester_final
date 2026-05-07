"""
Econometric factor selection pipeline.

This package exposes both the current direct IC-composite production selector
and the older research-oriented BH-FDR / Adaptive LASSO helpers.
"""

from .screen import screen_factors_fdr, screen_factor_candidates, summarize_screen_results
from .regime import detect_structural_breaks, detect_regime_window, bai_perron_sup_f_gate
from .lasso import select_factors_lasso, AdaptiveLassoResult
from .monitor import calculate_cusum_drift
from .direct import DirectSelectionConfig, direct_ic_composite_score, rank_direct_factors, select_direct_factors

__all__ = [
    "screen_factors_fdr",
    "screen_factor_candidates",
    "summarize_screen_results",
    "detect_structural_breaks",
    "detect_regime_window",
    "bai_perron_sup_f_gate",
    "select_factors_lasso",
    "AdaptiveLassoResult",
    "calculate_cusum_drift",
    "DirectSelectionConfig",
    "direct_ic_composite_score",
    "rank_direct_factors",
    "select_direct_factors",
]
