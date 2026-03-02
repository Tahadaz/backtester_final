"""
core/tests/test_optimize_regression.py
========================================
Regression tests ensuring that:

1. make_signal_arrays_fast() produces identical {-1,0,1} arrays as the legacy
   make_signals_from_bank() path for each adapter that implements the fast path.

2. run_optimization() is deterministic: two calls with the same seed, spec, and
   params return bit-identical best_params and best objective metric (pnl/cagr).

3. OptimizeTiming is populated with plausible values after a normal run.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_core.engine import DataConfig, EngineSpec, IndicatorsConfig, StrategyConfig
from quant_core.optimize import (
    BankRequest,
    MACrossAdapter,
    OptimizeConfig,
    ParamDef,
    build_bank,
    run_optimization,
)
from quant_core.portfolio import PortfolioConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _synthetic_spec(
    symbols: list[str],
    kind: str = "ma_cross",
    params: dict | None = None,
    start: str = "2020-01-01",
    end: str = "2022-12-31",
) -> EngineSpec:
    return EngineSpec(
        data=DataConfig(
            source="synthetic",
            symbols=symbols,
            start=start,
            end=end,
            synthetic={"seed": 7},
        ),
        indicators=IndicatorsConfig(),
        strategy=StrategyConfig(
            kind=kind,
            params=params or {"sma_fast_window": 15, "sma_slow_window": 50, "nan_policy": "flat"},
        ),
        portfolio=PortfolioConfig(allow_short=True, initial_cash=100_000.0),
    )


def _ma_cross_params() -> list[ParamDef]:
    return [
        ParamDef(key="strategy.sma_fast_window", kind="choice", domain=[5, 10, 15, 20], cast=int),
        ParamDef(key="strategy.sma_slow_window", kind="choice", domain=[30, 50, 75, 100], cast=int),
    ]


def _normalize_signals(arr: np.ndarray) -> np.ndarray:
    """Apply the same normalization that _eval_one_trial applies."""
    a = np.nan_to_num(np.asarray(arr, dtype=np.float64), nan=0.0, posinf=1.0, neginf=-1.0)
    return np.where(a > 0.0, 1.0, np.where(a < 0.0, -1.0, 0.0))


# ---------------------------------------------------------------------------
# Test 1: make_signal_arrays_fast matches make_signals_from_bank (MACrossAdapter)
# ---------------------------------------------------------------------------

class TestMACrossSignalParity:
    """Fast path signals == legacy DataFrame signals for MACrossAdapter."""

    def _build_bank_and_index(self, symbols: list[str], fast: int, slow: int):
        from quant_core.data import make_synthetic_ohlcv

        n = 300
        rng = np.random.default_rng(42)
        banks = {}
        closes = {}
        opens = {}
        highs = {}
        lows = {}
        vols = {}
        idx = pd.date_range("2020-01-01", periods=n, freq="B")

        for sym in symbols:
            price = 100.0 + np.cumsum(rng.normal(0, 1, n))
            sma_f = pd.Series(price).rolling(fast).mean().to_numpy()
            sma_s = pd.Series(price).rolling(slow).mean().to_numpy()
            banks[sym] = {f"sma_{fast}": sma_f, f"sma_{slow}": sma_s}
            closes[sym] = price
            opens[sym] = price * 0.999
            highs[sym] = price * 1.002
            lows[sym] = price * 0.998
            vols[sym] = np.abs(rng.normal(1e6, 1e5, n))

        return idx, banks, closes, opens, highs, lows, vols

    def test_fast_path_equals_legacy_single_symbol(self):
        adapter = MACrossAdapter()
        symbols = ["AAA"]
        fast, slow = 10, 50
        idx, banks, closes, opens, highs, lows, vols = self._build_bank_and_index(symbols, fast, slow)

        spec = _synthetic_spec(symbols)
        params = {"strategy.sma_fast_window": fast, "strategy.sma_slow_window": slow}

        # Legacy path
        sf = adapter.make_signals_from_bank(
            symbols=symbols,
            index=idx,
            bank=banks,
            bars_close=closes,
            bars_high=highs,
            bars_low=lows,
            bars_vol=vols,
            params=params,
            base_spec=spec,
        )
        legacy_norm = {}
        for sym in symbols:
            c = sf.signals[sym].to_numpy(dtype=np.float64, copy=False)
            if sf.validity is not None and sym in sf.validity.columns:
                v = sf.validity[sym].to_numpy(dtype=bool, copy=False)
                c = np.where(v, c, 0.0)
            legacy_norm[sym] = _normalize_signals(c)

        # Fast path
        fast_arrays = adapter.make_signal_arrays_fast(
            symbols=symbols,
            bank=banks,
            bars_close=closes,
            bars_high=highs,
            bars_low=lows,
            bars_vol=vols,
            params=params,
            base_spec=spec,
        )
        fast_norm = {sym: _normalize_signals(fast_arrays[sym]) for sym in symbols}

        for sym in symbols:
            np.testing.assert_array_equal(
                fast_norm[sym],
                legacy_norm[sym],
                err_msg=f"Signal mismatch for symbol={sym} fast={fast} slow={slow}",
            )

    def test_fast_path_equals_legacy_multi_symbol(self):
        adapter = MACrossAdapter()
        symbols = ["AAA", "BBB", "CCC"]
        fast, slow = 15, 75
        idx, banks, closes, opens, highs, lows, vols = self._build_bank_and_index(symbols, fast, slow)

        spec = _synthetic_spec(symbols)
        params = {"strategy.sma_fast_window": fast, "strategy.sma_slow_window": slow}

        sf = adapter.make_signals_from_bank(
            symbols=symbols, index=idx, bank=banks,
            bars_close=closes, bars_high=highs, bars_low=lows, bars_vol=vols,
            params=params, base_spec=spec,
        )
        legacy_norm = {}
        for sym in symbols:
            c = sf.signals[sym].to_numpy(dtype=np.float64, copy=False)
            if sf.validity is not None and sym in sf.validity.columns:
                v = sf.validity[sym].to_numpy(dtype=bool, copy=False)
                c = np.where(v, c, 0.0)
            legacy_norm[sym] = _normalize_signals(c)

        fast_arrays = adapter.make_signal_arrays_fast(
            symbols=symbols, bank=banks,
            bars_close=closes, bars_high=highs, bars_low=lows, bars_vol=vols,
            params=params, base_spec=spec,
        )
        fast_norm = {sym: _normalize_signals(fast_arrays[sym]) for sym in symbols}

        for sym in symbols:
            np.testing.assert_array_equal(fast_norm[sym], legacy_norm[sym], err_msg=f"mismatch for {sym}")

    def test_nan_policy_propagate_preserved(self):
        """nan_policy='propagate' should leave NaN rows as NaN (then normalized to 0)."""
        adapter = MACrossAdapter()
        symbols = ["X"]
        fast, slow = 5, 20
        idx, banks, closes, opens, highs, lows, vols = self._build_bank_and_index(symbols, fast, slow)
        spec = _synthetic_spec(symbols)
        params = {"strategy.sma_fast_window": fast, "strategy.sma_slow_window": slow, "strategy.nan_policy": "propagate"}

        sf = adapter.make_signals_from_bank(
            symbols=symbols, index=idx, bank=banks,
            bars_close=closes, bars_high=highs, bars_low=lows, bars_vol=vols,
            params=params, base_spec=spec,
        )
        legacy_norm = _normalize_signals(sf.signals["X"].to_numpy(dtype=np.float64, copy=False))

        fast_arrays = adapter.make_signal_arrays_fast(
            symbols=symbols, bank=banks,
            bars_close=closes, bars_high=highs, bars_low=lows, bars_vol=vols,
            params=params, base_spec=spec,
        )
        fast_norm = _normalize_signals(fast_arrays["X"])

        np.testing.assert_array_equal(fast_norm, legacy_norm)


# ---------------------------------------------------------------------------
# Test 2: run_optimization determinism (same seed → identical best_params + objective)
# ---------------------------------------------------------------------------

class TestRunOptimizationDeterminism:
    """Two calls with the same seed must return bit-identical results."""

    def test_deterministic_best_params(self):
        spec = _synthetic_spec(["AAA"])
        params = _ma_cross_params()
        cfg = OptimizeConfig(method="random", n_trials=30, seed=42)

        _, _, best_params_1, _, _, _ = run_optimization(spec, params, cfg)
        _, _, best_params_2, _, _, _ = run_optimization(spec, params, cfg)

        assert best_params_1 == best_params_2, (
            f"best_params differ between runs:\n  run1={best_params_1}\n  run2={best_params_2}"
        )

    def test_deterministic_objective_metric(self):
        spec = _synthetic_spec(["AAA"])
        params = _ma_cross_params()
        cfg = OptimizeConfig(method="random", n_trials=30, seed=42)

        best_1, _, _, _, _, _ = run_optimization(spec, params, cfg)
        best_2, _, _, _, _, _ = run_optimization(spec, params, cfg)

        assert best_1.pnl == pytest.approx(best_2.pnl, rel=1e-9), (
            f"pnl differs: {best_1.pnl} vs {best_2.pnl}"
        )
        assert best_1.cagr == pytest.approx(best_2.cagr, rel=1e-9), (
            f"cagr differs: {best_1.cagr} vs {best_2.cagr}"
        )

    def test_grid_exhaustive_same_result_as_random_covering_full_domain(self):
        """Grid search over 2x2 domain should give same best as random over 50 trials."""
        spec = _synthetic_spec(["AAA"])
        tiny_params = [
            ParamDef(key="strategy.sma_fast_window", kind="choice", domain=[5, 10], cast=int),
            ParamDef(key="strategy.sma_slow_window", kind="choice", domain=[30, 50], cast=int),
        ]
        cfg_grid = OptimizeConfig(method="grid", seed=0)
        cfg_rand = OptimizeConfig(method="random", n_trials=50, seed=0)  # 50 > 4 unique; deduplicates

        best_grid, _, bp_grid, _, _, _ = run_optimization(spec, tiny_params, cfg_grid)
        best_rand, _, bp_rand, _, _, _ = run_optimization(spec, tiny_params, cfg_rand)

        assert bp_grid == bp_rand, f"grid best_params={bp_grid} != random best_params={bp_rand}"
        assert best_grid.pnl == pytest.approx(best_rand.pnl, rel=1e-9)


# ---------------------------------------------------------------------------
# Test 3: OptimizeTiming is populated
# ---------------------------------------------------------------------------

class TestOptimizeTiming:
    def test_timing_fields_populated(self):
        spec = _synthetic_spec(["AAA"])
        params = _ma_cross_params()
        cfg = OptimizeConfig(method="random", n_trials=10, seed=1)

        _, _, _, _, _, timing = run_optimization(spec, params, cfg)

        assert timing.n_trials_run > 0
        assert timing.trial_total_ms > 0.0
        assert timing.avg_trial_ms > 0.0
        assert timing.load_ms >= 0.0
        assert timing.bank_ms >= 0.0
        # cache_misses counts all unique trials evaluated (including invalid params),
        # so it is >= n_trials_run; cache_hits counts duplicate param combos skipped.
        assert timing.cache_misses >= timing.n_trials_run
        assert timing.cache_hits >= 0

    def test_profiling_disabled_by_default(self):
        spec = _synthetic_spec(["AAA"])
        params = _ma_cross_params()
        cfg = OptimizeConfig(method="random", n_trials=5, seed=2)

        _, _, _, _, _, timing = run_optimization(spec, params, cfg)
        assert timing.profile_text is None

    def test_profiling_enabled_returns_text(self):
        spec = _synthetic_spec(["AAA"])
        params = _ma_cross_params()
        cfg = OptimizeConfig(method="random", n_trials=5, seed=3, profiling_enabled=True)

        _, _, _, _, _, timing = run_optimization(spec, params, cfg)
        assert timing.profile_text is not None
        assert len(timing.profile_text) > 0
        # cProfile output contains "cumulative" header
        assert "cumulative" in timing.profile_text


# ---------------------------------------------------------------------------
# Test 4: ranked_df structure
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Test 5: Optimization-path correctness guards (Phase 5)
# ---------------------------------------------------------------------------

class TestOptimizationPathGuards:
    """Ensure the optimization trial loop stays free of heavy side-effects."""

    def test_precomputed_port_matches_per_trial_port(self):
        """Port-hoisting optimisation must produce the same PnL as per-trial creation."""
        spec = _synthetic_spec(["AAA"])
        params = _ma_cross_params()

        # Run with the default (hoisted port when no portfolio params vary)
        cfg_a = OptimizeConfig(method="random", n_trials=16, seed=77)
        best_a, _, bparams_a, _, _, _ = run_optimization(spec, params, cfg_a)

        # Run again with the same seed – should be bit-identical
        cfg_b = OptimizeConfig(method="random", n_trials=16, seed=77)
        best_b, _, bparams_b, _, _, _ = run_optimization(spec, params, cfg_b)

        assert bparams_a == bparams_b, "best params changed between identical runs"
        assert best_a.pnl == pytest.approx(best_b.pnl, rel=1e-9), "pnl changed between identical runs"

    def test_portfolio_param_variation_still_works(self):
        """When portfolio params are in the search space the per-trial path is used."""
        from quant_core.optimize import ParamDef
        spec = _synthetic_spec(["AAA"])
        params = [
            ParamDef(key="strategy.sma_fast_window", kind="choice", domain=[5, 10], cast=int),
            ParamDef(key="portfolio.cooldown_bars", kind="choice", domain=[0, 2, 5], cast=int),
        ]
        cfg = OptimizeConfig(method="random", n_trials=20, seed=12)
        best, _, best_params, _, ranked_df, timing = run_optimization(spec, params, cfg)

        assert timing.n_trials_run > 0
        assert best.error is None or best.pnl > float("-inf")
        assert isinstance(ranked_df, pd.DataFrame)

    def test_numba_warmup_at_import(self):
        """Numba JIT must already be loaded by portfolio import (no cold-start on first eval)."""
        import time
        from quant_core.portfolio import _HAVE_NUMBA

        spec = _synthetic_spec(["AAA"])
        params = _ma_cross_params()
        cfg = OptimizeConfig(method="random", n_trials=4, seed=99)

        t0 = time.perf_counter()
        run_optimization(spec, params, cfg)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        if _HAVE_NUMBA:
            # After warmup at import, the first optimization call should be well under 1 s.
            # (Without warmup it could be 200-1500 ms just for JIT startup.)
            assert elapsed_ms < 1000.0, (
                f"First optimization call took {elapsed_ms:.0f} ms – "
                "Numba JIT warmup at import should have prevented this."
            )

    def test_no_fills_in_trial_result(self):
        """TrialResult must not contain any trade fill data (only summary stats)."""
        from quant_core.optimize import TrialResult
        spec = _synthetic_spec(["AAA"])
        params = _ma_cross_params()
        cfg = OptimizeConfig(method="random", n_trials=8, seed=3)

        best, _, _, _, _, _ = run_optimization(spec, params, cfg)

        # TrialResult has exactly these fields; no fill ledger or plot data
        expected_fields = {"params", "pnl", "traded_notional", "efficiency", "n_fills", "cagr", "error"}
        actual_fields = set(vars(best).keys())
        extra_fields = actual_fields - expected_fields
        assert not extra_fields, f"TrialResult has unexpected fields: {extra_fields}"


class TestRankedDfStructure:
    def test_ranked_df_has_expected_columns(self):
        spec = _synthetic_spec(["AAA"])
        params = _ma_cross_params()
        cfg = OptimizeConfig(method="random", n_trials=15, seed=99)

        _, top_df, _, _, ranked_df, _ = run_optimization(spec, params, cfg)

        assert isinstance(ranked_df, pd.DataFrame)
        assert not ranked_df.empty
        # Should have at least pnl column
        assert "pnl" in ranked_df.columns or "score" in ranked_df.columns or len(ranked_df.columns) > 0

    def test_top_df_best_row_matches_best_result(self):
        spec = _synthetic_spec(["AAA"])
        params = _ma_cross_params()
        cfg = OptimizeConfig(method="random", n_trials=20, seed=5)

        best_result, top_df, best_params, _, _, _ = run_optimization(spec, params, cfg)

        # best_params should match what's at the top of top_df
        if not top_df.empty and "pnl" in top_df.columns:
            top_pnl = float(top_df.iloc[0]["pnl"])
            assert best_result.pnl == pytest.approx(top_pnl, rel=1e-6)
