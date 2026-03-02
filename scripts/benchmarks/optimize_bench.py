"""
scripts/benchmarks/optimize_bench.py
=====================================
Benchmark optimization trial throughput on a synthetic multi-symbol dataset.

Usage:
    # from repo root
    python scripts/benchmarks/optimize_bench.py

    # with profiling (prints top-30 functions by cumulative time):
    python scripts/benchmarks/optimize_bench.py --profile

    # more trials / symbols:
    python scripts/benchmarks/optimize_bench.py --n-trials 200 --symbols AAAA BBBB CCCC DDDD
"""
from __future__ import annotations

import argparse
import cProfile
import io
import pstats
import sys
import time
from pathlib import Path

# Allow running from repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "core"))

from quant_core.engine import DataConfig, EngineSpec, IndicatorsConfig, StrategyConfig
from quant_core.optimize import OptimizeConfig, ParamDef, run_optimization
from quant_core.portfolio import PortfolioConfig


# ---------------------------------------------------------------------------
# Benchmark spec helpers
# ---------------------------------------------------------------------------

def _make_spec(symbols: list[str], start: str = "2018-01-01", end: str = "2023-12-31") -> EngineSpec:
    return EngineSpec(
        data=DataConfig(
            source="synthetic",
            symbols=symbols,
            start=start,
            end=end,
            synthetic={"seed": 42},
        ),
        indicators=IndicatorsConfig(),
        strategy=StrategyConfig(
            kind="ma_cross",
            params={
                "sma_fast_window": 15,
                "sma_slow_window": 50,
                "nan_policy": "flat",
            },
        ),
        portfolio=PortfolioConfig(
            allow_short=True,
            initial_cash=100_000.0,
        ),
    )


def _make_params() -> list[ParamDef]:
    return [
        ParamDef(key="strategy.sma_fast_window", kind="choice", domain=[5, 10, 15, 20], cast=int),
        ParamDef(key="strategy.sma_slow_window", kind="choice", domain=[30, 50, 75, 100, 150], cast=int),
    ]


# ---------------------------------------------------------------------------
# Single timed run
# ---------------------------------------------------------------------------

def _run_once(
    symbols: list[str],
    n_trials: int,
    seed: int,
    profiling_enabled: bool = False,
) -> tuple[float, int, "OptimizeTiming"]:  # type: ignore[name-defined]
    spec = _make_spec(symbols)
    params = _make_params()
    cfg = OptimizeConfig(
        method="random",
        n_trials=n_trials,
        seed=seed,
        profiling_enabled=profiling_enabled,
    )
    t0 = time.perf_counter()
    _best, _top_df, _best_params, _best_spec, _ranked_df, timing = run_optimization(spec, params, cfg)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return elapsed_ms, timing.n_trials_run, timing


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Optimization benchmark")
    parser.add_argument("--symbols", nargs="+", default=["AAA", "BBB", "CCC"], metavar="SYM")
    parser.add_argument("--n-trials", type=int, default=100)
    parser.add_argument("--warmup", action="store_true", help="Run one warmup pass before timing")
    parser.add_argument("--profile", action="store_true", help="Print cProfile top-30 functions")
    args = parser.parse_args()

    symbols: list[str] = args.symbols
    n_trials: int = args.n_trials

    print(f"\n{'='*60}")
    print(f"  Optimization benchmark")
    print(f"  symbols   : {symbols}")
    print(f"  n_trials  : {n_trials}")
    print(f"{'='*60}\n")

    # Optional warmup (warms JIT / caches without counting toward timing)
    if args.warmup:
        print("  [warmup] running one pass...", end=" ", flush=True)
        _run_once(symbols, n_trials=10, seed=0)
        print("done\n")

    # Timed run
    if args.profile:
        # Use cProfile for detailed per-function breakdown
        prof = cProfile.Profile()
        prof.enable()
        elapsed_ms, n_run, timing = _run_once(symbols, n_trials, seed=42, profiling_enabled=False)
        prof.disable()

        sio = io.StringIO()
        ps = pstats.Stats(prof, stream=sio).sort_stats("cumulative")
        ps.print_stats(30)
        profile_output = sio.getvalue()
    else:
        elapsed_ms, n_run, timing = _run_once(symbols, n_trials, seed=42, profiling_enabled=False)
        profile_output = None

    # Summary
    trials_per_sec = (n_run / elapsed_ms * 1000) if elapsed_ms > 0 else 0.0
    print(f"  Total wall time   : {elapsed_ms:8.1f} ms")
    print(f"  Trials run        : {n_run}")
    print(f"  Avg trial time    : {timing.avg_trial_ms:8.2f} ms")
    print(f"  Trials/sec        : {trials_per_sec:8.1f}")
    print()
    print(f"  Breakdown (from OptimizeTiming):")
    print(f"    data load       : {timing.load_ms:8.1f} ms")
    print(f"    indicator bank  : {timing.bank_ms:8.1f} ms")
    print(f"    trial total     : {timing.trial_total_ms:8.1f} ms")
    print(f"    cache hits      : {timing.cache_hits}")
    print(f"    cache misses    : {timing.cache_misses}")
    print()

    if profile_output:
        print("=" * 60)
        print("  cProfile — top 30 by cumulative time")
        print("=" * 60)
        print(profile_output)


if __name__ == "__main__":
    main()
