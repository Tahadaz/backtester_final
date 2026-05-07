from __future__ import annotations

from core.quant_core.wfo.wfe import ReturnWindow, compute_robustness_ratio, compute_single_window_dominance, compute_wfe


def test_compute_wfe_uses_annualized_oos_over_is() -> None:
    windows = [
        ReturnWindow(is_return=0.18, oos_return=0.03, is_bars=252, oos_bars=126),
        ReturnWindow(is_return=0.16, oos_return=0.02, is_bars=252, oos_bars=126),
    ]
    result = compute_wfe(windows)
    assert 0.0 < result < 1.0


def test_compute_robustness_ratio_counts_profitable_oos_windows() -> None:
    assert compute_robustness_ratio([0.02, -0.01, 0.03, 0.0]) == 0.5


def test_compute_single_window_dominance_flags_concentration() -> None:
    dominance = compute_single_window_dominance([0.02, 0.01, 0.20])
    assert round(dominance, 2) == 0.87
