from __future__ import annotations

import numpy as np
import pandas as pd

from core.quant_core.factor_selection import calculate_cusum_drift, detect_regime_window, select_factors_lasso
from core.quant_core.factor_selection.direct import DirectSelectionConfig, rank_direct_factors, select_direct_factors
from core.quant_core.factor_selection.screen import screen_factor_candidates, summarize_screen_results, ScreenConfig


def _make_dates(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2020-01-01", periods=n, freq="B")


def test_stage1_bh_fdr_screen_is_deterministic() -> None:
    n = 320
    rng = np.random.default_rng(7)
    dates = _make_dates(n)
    factor_a_ret = rng.normal(0, 0.01, n)
    factor_b_ret = rng.normal(0, 0.01, n)
    stock_ret = np.roll(factor_a_ret, 1) * 0.9 + rng.normal(0, 0.002, n)
    factor_a = pd.Series(100 * np.exp(np.cumsum(factor_a_ret)), index=dates)
    factor_b = pd.Series(100 * np.exp(np.cumsum(factor_b_ret)), index=dates)
    stock = pd.Series(100 * np.exp(np.cumsum(stock_ret)), index=dates)

    raw = screen_factor_candidates(
        stock,
        {"FA": factor_a, "FB": factor_b},
        config=ScreenConfig(horizon_days=5, min_obs=120, fdr_q=0.10),
    )
    summary = summarize_screen_results(raw)

    assert not summary.empty
    assert "bh_p_adj" in summary.columns
    assert summary.iloc[0]["factor_id"] == "FA"
    assert bool(summary[summary["factor_id"] == "FA"]["passed_fdr"].iloc[0]) is True


def test_low_confidence_path_skips_break_detection() -> None:
    n = 400
    prices = pd.Series(np.linspace(100.0, 150.0, n), index=_make_dates(n))
    result = detect_regime_window(prices)

    assert result.low_confidence is True
    assert result.breakpoints == []
    assert result.history_n_days == n


def test_adaptive_lasso_returns_at_most_three_ranked_factors() -> None:
    n = 280
    rng = np.random.default_rng(11)
    dates = _make_dates(n)
    f1 = rng.normal(0, 1, n)
    f2 = rng.normal(0, 1, n)
    f3 = rng.normal(0, 1, n)
    f4 = rng.normal(0, 1, n)
    y = 0.8 * f1 - 0.6 * f2 + 0.4 * f3 + rng.normal(0, 0.1, n)
    result = select_factors_lasso(
        pd.Series(y, index=dates),
        pd.DataFrame({"F1": f1, "F2": f2, "F3": f3, "F4": f4}, index=dates),
        max_selected=3,
    )

    assert len(result.coefficients) <= 3
    assert set(result.coefficients) == set(result.ranks)
    assert sorted(result.ranks.values()) == list(range(1, len(result.ranks) + 1))


def test_direct_ic_composite_selects_only_usable_factors() -> None:
    n = 340
    rng = np.random.default_rng(17)
    dates = _make_dates(n)
    factor_a_ret = rng.normal(0, 0.01, n)
    factor_b_ret = rng.normal(0, 0.01, n)
    factor_c_ret = rng.normal(0, 0.01, n)
    stock_ret = np.roll(factor_a_ret, 5) * 1.2 + np.roll(factor_b_ret, 5) * 0.8 + rng.normal(0, 0.003, n)
    stock = pd.Series(100 * np.exp(np.cumsum(stock_ret)), index=dates)
    factors = {
        "USABLE_A": pd.Series(100 * np.exp(np.cumsum(factor_a_ret)), index=dates),
        "USABLE_B": pd.Series(100 * np.exp(np.cumsum(factor_b_ret)), index=dates),
        "UNUSABLE_C": pd.Series(100 * np.exp(np.cumsum(factor_c_ret)), index=dates),
    }

    config = DirectSelectionConfig(horizon_days=5)
    ranked = rank_direct_factors(stock, factors, config=config)
    selected = select_direct_factors(
        ranked,
        usable_factor_ids={"USABLE_A", "USABLE_B"},
        config=config,
    )

    assert not selected.empty
    assert set(selected["factor_id"]).issubset({"USABLE_A", "USABLE_B"})
    assert len(selected) <= 3
    assert selected.iloc[0]["selected_reason"] in {"normal", "low_confidence"}


def test_direct_ic_composite_low_confidence_top_one_fallback() -> None:
    n = 180
    rng = np.random.default_rng(19)
    dates = _make_dates(n)
    weak_factor_ret = rng.normal(0, 0.01, n)
    stock_ret = rng.normal(0, 0.01, n)
    stock = pd.Series(100 * np.exp(np.cumsum(stock_ret)), index=dates)
    factors = {"WEAK": pd.Series(100 * np.exp(np.cumsum(weak_factor_ret)), index=dates)}

    config = DirectSelectionConfig(horizon_days=5)
    ranked = rank_direct_factors(stock, factors, config=config)
    selected = select_direct_factors(ranked, usable_factor_ids={"WEAK"}, config=config)

    assert len(selected) == 1
    assert selected.iloc[0]["selected_reason"] == "low_confidence"


def test_direct_ic_composite_no_selection_when_obs_too_low() -> None:
    n = 90
    rng = np.random.default_rng(23)
    dates = _make_dates(n)
    stock = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=dates)
    factor = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=dates)

    config = DirectSelectionConfig(horizon_days=5)
    ranked = rank_direct_factors(stock, {"F": factor}, config=config)
    selected = select_direct_factors(ranked, usable_factor_ids={"F"}, config=config)

    assert selected.empty


def test_cusum_monitor_flags_drift_without_invalidating_all_cases() -> None:
    n = 220
    rng = np.random.default_rng(13)
    dates = _make_dates(n)
    factor = pd.Series(rng.normal(0, 1, n), index=dates)
    target = pd.Series(rng.normal(0, 0.2, n), index=dates)
    target.iloc[n // 2 :] = factor.iloc[n // 2 :] * 2.5 + rng.normal(0, 0.2, n - n // 2)

    result = calculate_cusum_drift(target, factor)

    assert result["drift_score"] >= 0.0
    assert isinstance(result["alarm"], bool)
    assert len(result["cusum_path"]) > 0
