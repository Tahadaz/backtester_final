"""Orchestration: load WFO trades → reconstruct paths → run policies → stats → report.

The harness reads the DB read-only and does not touch production endpoints.
"""
from __future__ import annotations

import itertools
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .paths import TradePath, reconstruct_trade_paths
from .policies import (
    ExitResult, PolicyName, K_GRID, DEFAULT_K_SL, DEFAULT_K_TP,
    simulate_A, simulate_B, simulate_C, simulate_D, simulate_E,
)
from .calibrate import walk_forward_c_params
from .portfolio import run_policy_portfolio, exit_reason_histogram, _portfolio_metrics
from .stats import summarize_policy_stats

logger = logging.getLogger(__name__)


@dataclass
class HarnessConfig:
    horizon: str = "weekly"
    variant: str = "expanded"
    symbols: list[str] | None = None         # None = all qualifying
    policies: list[PolicyName] = field(default_factory=lambda: ["A", "B", "C", "D", "E"])
    k_grid: list[float] = field(default_factory=lambda: list(K_GRID))
    min_calib_trades: int = 20
    bootstrap_B: int = 10_000
    out_dir: str | None = None
    compute_sr: bool = True                   # set False to skip policy D/E S/R computation


@dataclass
class PolicyResult:
    name: str                                 # e.g. "B_ksl1.5_ktp2.0"
    policy: str                               # "A" / "B" / "C" / "D" / "E"
    params: dict[str, Any]
    metrics: dict[str, float]
    exit_reasons: dict[str, int]
    effective_returns: list[float]            # per-trade effective returns (aligned to baseline events)


@dataclass
class HarnessReport:
    config: HarnessConfig
    n_symbols: int
    n_trades_total: int
    n_paths_reconstructed: int
    baseline_metrics: dict[str, float]
    policy_results: list[PolicyResult]
    stats: dict[str, dict[str, float]]       # policy_name → CI + SPA stats
    elapsed_seconds: float
    verdict: str                              # human-readable summary sentence


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load_wfo_trades(db: Any, *, symbol: str, horizon: str, variant: str) -> list[dict[str, Any]]:
    """Load WFO OOS trades for a symbol from SignalBacktestRun."""
    from services.api.app.models import SignalBacktestRun

    rows = (
        db.query(SignalBacktestRun)
        .filter_by(
            symbol=symbol,
            horizon=horizon,
            variant=variant,
            source="wfo",
            scope="global",
            status="succeeded",
        )
        .all()
    )
    trades: list[dict[str, Any]] = []
    for row in rows:
        raw = row.trades_json
        if isinstance(raw, list):
            trades.extend(raw)
    return trades


def _load_ohlcv(db: Any, symbol: str) -> pd.DataFrame | None:
    from services.api.app.market_data_loader import load_ohlcv_for_symbol

    try:
        return load_ohlcv_for_symbol(db, symbol)
    except Exception:
        logger.warning("Could not load OHLCV for %s", symbol, exc_info=True)
        return None


def _enumerate_symbols(db: Any, *, horizon: str, variant: str) -> list[str]:
    """Return all symbols that have qualifying WFO backtest rows."""
    from services.api.app.models import SignalBacktestRun

    rows = (
        db.query(SignalBacktestRun.symbol)
        .filter_by(
            horizon=horizon,
            variant=variant,
            source="wfo",
            scope="global",
            status="succeeded",
        )
        .distinct()
        .all()
    )
    return sorted(str(r.symbol) for r in rows)


def _build_policy_variants(
    paths: list[TradePath],
    config: HarnessConfig,
) -> list[tuple[str, Any]]:
    """Build (variant_name, simulate_fn) pairs for every requested policy × k combo."""
    variants: list[tuple[str, Any]] = []

    # Pre-compute walk-forward C params once (expensive); keyed by id(path)
    c_params: dict[int, tuple[float, float]] | None = None

    for policy in config.policies:
        if policy == "A":
            variants.append(("A", simulate_A))

        elif policy == "B":
            for k_sl, k_tp in itertools.product(config.k_grid, config.k_grid):
                name = f"B_ksl{k_sl}_ktp{k_tp}"
                def make_b(ks=k_sl, kt=k_tp):
                    return lambda p: simulate_B(p, k_sl=ks, k_tp=kt)
                variants.append((name, make_b()))

        elif policy == "C":
            if c_params is None:
                sorted_paths = sorted(paths, key=lambda p: p.open_date)
                c_params_raw = walk_forward_c_params(
                    sorted_paths,
                    min_calib_trades=config.min_calib_trades,
                )
                # Key by object identity, not open_date: many signals across
                # symbols share an open_date, and a date-keyed dict would collapse
                # them onto whichever trade was written last. The same TradePath
                # objects flow through run_policy_portfolio (re-sorted, not copied),
                # so id(path) is a stable, collision-proof key.
                c_params = {id(p): kv for p, kv in zip(sorted_paths, c_params_raw)}

            def make_c(param_map=c_params):
                def sim_c(path: TradePath) -> ExitResult:
                    k_sl, k_tp = param_map.get(id(path), (DEFAULT_K_SL, DEFAULT_K_TP))
                    return simulate_C(path, k_sl=k_sl, k_tp=k_tp)
                return sim_c
            variants.append(("C_wf", make_c()))

        elif policy == "D":
            variants.append(("D", simulate_D))

        elif policy == "E":
            for k_sl, k_tp in itertools.product(config.k_grid, config.k_grid):
                name = f"E_ksl{k_sl}_ktp{k_tp}"
                def make_e(ks=k_sl, kt=k_tp):
                    return lambda p: simulate_E(p, k_sl=ks, k_tp=kt)
                variants.append((name, make_e()))

    return variants


def _run_single_variant(
    name: str,
    policy_letter: str,
    params: dict[str, Any],
    simulate_fn: Any,
    paths: list[TradePath],
) -> tuple[PolicyResult, list[float]]:
    """Run one policy variant; return (PolicyResult, list_of_effective_returns)."""
    portfolio = run_policy_portfolio(paths, simulate_fn)
    reasons = exit_reason_histogram(portfolio["trades"])
    eff_returns = [t["effective_return"] for t in portfolio["trades"]]
    result = PolicyResult(
        name=name,
        policy=policy_letter,
        params=params,
        metrics=portfolio["metrics"],
        exit_reasons=reasons,
        effective_returns=eff_returns,
    )
    return result, eff_returns


def _build_verdict(stats: dict[str, dict[str, float]], threshold: float = 0.05) -> str:
    """Build a human-readable summary of which policies beat the baseline."""
    winners = [
        k for k, v in stats.items()
        if v.get("spa_pvalue", 1.0) <= threshold and v.get("mean_diff", 0.0) > 0.0
    ]
    losers = [
        k for k, v in stats.items()
        if v.get("spa_pvalue", 1.0) > threshold
    ]
    if not stats:
        return "No policy results computed."
    if not winners:
        return (
            f"No alternative policy beats the baseline at SPA p ≤ {threshold}. "
            "Baseline (natural signal exit) is not improved by any tested TP/SL rule."
        )
    best = max(winners, key=lambda k: stats[k].get("mean_diff", 0.0))
    s = stats[best]
    verdict = (
        f"Policy {best} beats baseline on mean effective return "
        f"(Δ={s['mean_diff']:+.4f}, "
        f"95% CI [{s['ci_lower']:+.4f}, {s['ci_upper']:+.4f}], "
        f"SPA p={s['spa_pvalue']:.3f}). "
    )
    if losers:
        sample = losers[:3]
        verdict += f"Indistinguishable from baseline: {', '.join(sample)}" + (
            f" and {len(losers)-3} more." if len(losers) > 3 else "."
        )
    return verdict


# ── Public entrypoint ─────────────────────────────────────────────────────────

def run_harness(db: Any, config: HarnessConfig) -> HarnessReport:
    """Orchestrate the full exit-policy horse race.

    Args:
        db:     SQLAlchemy Session (read-only usage).
        config: HarnessConfig with horizon, variant, symbols, policies, etc.

    Returns:
        HarnessReport with per-policy metrics, bootstrap CIs, SPA p-values, verdict.
    """
    t0 = time.time()

    # Resolve logical variant aliases (e.g. "expanded" → "expanded_ta_simple") to the
    # stored variant string, matching what the production signal endpoints persist/read.
    # Without this, --variant expanded silently matches zero rows.
    try:
        from core.quant_core.signal_engine.modes import signal_mode_storage_name
        resolved = signal_mode_storage_name(config.variant)
        if resolved != config.variant:
            logger.info("Resolved variant %r → %r", config.variant, resolved)
            config.variant = resolved
    except Exception:
        logger.debug("Variant alias resolution skipped for %r", config.variant, exc_info=True)

    symbols = config.symbols or _enumerate_symbols(db, horizon=config.horizon, variant=config.variant)
    if not symbols:
        logger.warning("No qualifying symbols found for %s/%s", config.horizon, config.variant)

    # --- Aggregate trade paths across all symbols ---
    all_paths: list[TradePath] = []
    for symbol in symbols:
        trades = _load_wfo_trades(db, symbol=symbol, horizon=config.horizon, variant=config.variant)
        if not trades:
            logger.info("No WFO trades for %s — skipping", symbol)
            continue
        ohlcv = _load_ohlcv(db, symbol)
        if ohlcv is None:
            logger.info("No OHLCV for %s — skipping", symbol)
            continue
        paths = reconstruct_trade_paths(
            trades, ohlcv, symbol=symbol, compute_sr=config.compute_sr
        )
        all_paths.extend(paths)

    # Sort globally by open_date (capital recycling across symbols)
    all_paths.sort(key=lambda p: p.open_date)

    n_paths = len(all_paths)
    if n_paths == 0:
        return HarnessReport(
            config=config,
            n_symbols=len(symbols),
            n_trades_total=0,
            n_paths_reconstructed=0,
            baseline_metrics={},
            policy_results=[],
            stats={},
            elapsed_seconds=time.time() - t0,
            verdict="No trade paths reconstructed. Check that WFO runs exist with status=succeeded.",
        )

    # --- Build policy variants ---
    variants = _build_policy_variants(all_paths, config)

    # --- Run all variants ---
    policy_results: list[PolicyResult] = []
    returns_by_name: dict[str, list[float]] = {}
    baseline_returns: list[float] = []

    for variant_name, simulate_fn in variants:
        policy_letter = variant_name[0]
        # Reconstruct params from name
        params: dict[str, Any] = {}
        if "_ksl" in variant_name:
            parts = variant_name.split("_")
            for part in parts:
                if part.startswith("ksl"):
                    params["k_sl"] = float(part[3:])
                elif part.startswith("ktp"):
                    params["k_tp"] = float(part[3:])

        result, eff_returns = _run_single_variant(
            variant_name, policy_letter, params, simulate_fn, all_paths
        )
        policy_results.append(result)
        returns_by_name[variant_name] = eff_returns

        if variant_name == "A":
            baseline_returns = eff_returns

    # --- Statistics ---
    baseline_arr = np.asarray(baseline_returns, dtype=np.float64)
    alt_returns = {k: np.asarray(v, dtype=np.float64) for k, v in returns_by_name.items() if k != "A"}
    stats_result: dict[str, dict[str, float]] = {}
    if alt_returns and len(baseline_arr) >= 10:
        stats_result = summarize_policy_stats(
            baseline_arr,
            alt_returns,
            B=config.bootstrap_B,
        )

    baseline_result = next((r for r in policy_results if r.name == "A"), None)
    baseline_metrics = baseline_result.metrics if baseline_result else {}
    verdict = _build_verdict(stats_result)

    return HarnessReport(
        config=config,
        n_symbols=len(symbols),
        n_trades_total=sum(len(_load_wfo_trades(db, symbol=s, horizon=config.horizon, variant=config.variant)) for s in symbols),
        n_paths_reconstructed=n_paths,
        baseline_metrics=baseline_metrics,
        policy_results=policy_results,
        stats=stats_result,
        elapsed_seconds=time.time() - t0,
        verdict=verdict,
    )


# ── Report formatting ─────────────────────────────────────────────────────────

def format_report(report: HarnessReport) -> str:
    """Format HarnessReport as a markdown string."""
    lines: list[str] = []
    cfg = report.config

    lines.append("# Exit-Policy Horse-Race Report")
    lines.append("")
    lines.append(f"**Horizon:** {cfg.horizon}  |  **Variant:** {cfg.variant}")
    lines.append(f"**Symbols evaluated:** {report.n_symbols}  |  **OOS trades loaded:** {report.n_trades_total}")
    lines.append(f"**Trade paths reconstructed:** {report.n_paths_reconstructed}  |  **Elapsed:** {report.elapsed_seconds:.1f}s")
    lines.append("")

    # Baseline metrics
    lines.append("## Baseline (Policy A — natural signal exit)")
    bm = report.baseline_metrics
    lines.append(f"- Total return: {bm.get('total_return', 0):.2%}")
    lines.append(f"- CAGR: {bm.get('cagr', 0):.2%}")
    lines.append(f"- Sharpe: {bm.get('sharpe', 0):.3f}")
    lines.append(f"- Max DD: {bm.get('max_drawdown', 0):.2%}")
    lines.append(f"- Win rate: {bm.get('win_rate', 0):.1%}")
    lines.append(f"- Trades: {bm.get('n_trades', 0)}")
    lines.append("")

    # Ranked policy table
    lines.append("## Policy Rankings")
    lines.append("")
    lines.append("| Policy | Sharpe | Return | MaxDD | Win% | Trades | Exit reasons | Δ vs A | SPA p |")
    lines.append("|--------|--------|--------|-------|------|--------|--------------|--------|-------|")

    sorted_results = sorted(report.policy_results, key=lambda r: -r.metrics.get("sharpe", -99))
    base_sharpe = report.baseline_metrics.get("sharpe", 0.0)

    for pr in sorted_results:
        m = pr.metrics
        st = report.stats.get(pr.name, {})
        reasons_str = " ".join(f"{k}={v}" for k, v in pr.exit_reasons.items())
        delta = m.get("sharpe", 0) - base_sharpe
        spa_p = st.get("spa_pvalue", float("nan"))
        spa_str = f"{spa_p:.3f}" if not (spa_p != spa_p) else "—"
        delta_str = f"{delta:+.3f}"
        lines.append(
            f"| {pr.name} | {m.get('sharpe', 0):.3f} | {m.get('total_return', 0):.1%} | "
            f"{m.get('max_drawdown', 0):.1%} | {m.get('win_rate', 0):.0%} | "
            f"{m.get('n_trades', 0)} | {reasons_str[:40]} | {delta_str} | {spa_str} |"
        )

    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    lines.append(report.verdict)
    lines.append("")

    # Bootstrap CI table for alternatives
    if report.stats:
        lines.append("## Bootstrap CI (95%) vs Baseline")
        lines.append("")
        lines.append("| Policy | Mean Δ | CI lower | CI upper | SPA p | RC p |")
        lines.append("|--------|--------|----------|----------|-------|------|")
        for name, st in sorted(report.stats.items(), key=lambda x: -x[1].get("mean_diff", -99)):
            lines.append(
                f"| {name} | {st.get('mean_diff', 0):+.4f} | {st.get('ci_lower', 0):+.4f} | "
                f"{st.get('ci_upper', 0):+.4f} | {st.get('spa_pvalue', 1):.3f} | "
                f"{st.get('rc_pvalue', 1):.3f} |"
            )
        lines.append("")

    return "\n".join(lines)
