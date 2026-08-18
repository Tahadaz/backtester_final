"""Run the pre-registered cross-asset TSMOM study and grade it against the gates.

    python tools/global_desk/run_tsmom_study.py

Reads the cache written by ingest_free_panel.py, evaluates the eight gates in
docs/global-desk/02-tsmom-preregistration.md §4, and writes a report plus a
metrics JSON to research-out/global-desk-tsmom/<date>/.

The gate thresholds live in PRE_REGISTERED_GATES below and must match the
pre-registration document exactly.
"""

from __future__ import annotations

import json
import pathlib
import sys
from datetime import date

import numpy as np
import pandas as pd


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "core"))

from quant_core.cross_asset.security_master import REGISTRY, get as sm_get  # noqa: E402
from quant_core.cross_asset.tsmom_study import (  # noqa: E402
    StudyConfig,
    TRADING_DAYS,
    align_on_common_calendar,
    build_return_panel,
    compute_metrics,
    data_quality_report,
    run_tsmom,
    tsmom_signal,
)
from quant_core.cross_asset.performance import (  # noqa: E402
    per_instrument_summary,
    performance_summary,
)
from quant_core.research.stats.robustness import (  # noqa: E402
    deflated_sharpe_ratio,
    stationary_bootstrap_ci,
)

CACHE_DIR = REPO_ROOT / "data" / "global_desk" / "raw"
OUT_DIR = REPO_ROOT / "research-out" / "global-desk-tsmom" / date.today().isoformat()

LOOKBACK_GRID = [1, 3, 6, 12]
PRIMARY_LOOKBACK = 12
START = "2000-01-01"

PRE_REGISTERED_GATES = {
    "G-1": "Net Sharpe (full sample, pessimistic costs) > 0.30",
    "G-2": "Deflated Sharpe Ratio > 0.95",
    "G-3": "WFO OOS net return > 0 and OOS Sharpe > 0 in >= 60% of windows",
    "G-4": "Net Sharpe > 0 at 3x declared costs",
    "G-5": "Leave-one-instrument-out: net Sharpe > 0.20 for every exclusion",
    "G-6": "Positive net return in >= 55% of calendar years",
    "G-7": "95% stationary-bootstrap lower bound on mean net return > 0",
    "G-8": "Net Sharpe < 1.5 (sanity ceiling)",
}


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------


def load_series() -> tuple[dict[str, pd.Series], dict[str, str], list[str]]:
    series: dict[str, pd.Series] = {}
    classes: dict[str, str] = {}
    dropped: list[str] = []

    for entry in REGISTRY:
        path = CACHE_DIR / f"{entry.canonical_id}.parquet"
        if not path.exists():
            dropped.append(f"{entry.canonical_id}: no cached data ({entry.free_proxy_note or 'not fetched'})")
            continue
        frame = pd.read_parquet(path)
        values = frame["value"].astype(float).dropna()
        values.index = pd.to_datetime(values.index)
        if values.size < 3 * TRADING_DAYS:
            dropped.append(f"{entry.canonical_id}: only {values.size} rows, needs 3y minimum")
            continue
        series[entry.canonical_id] = values
        classes[entry.canonical_id] = entry.asset_class
    return series, classes, dropped


def quality_filter(panel: pd.DataFrame, dropped: list[str]) -> pd.DataFrame:
    """Drop instruments whose return series is unusable, naming each one."""
    keep = []
    for column in panel.columns:
        column_series = panel[column].dropna()
        if column_series.empty:
            dropped.append(f"{column}: empty return series")
            continue
        if column_series.std() == 0:
            dropped.append(f"{column}: zero variance")
            continue
        extreme = (column_series.abs() > 1.0).sum()
        if extreme > 5:
            dropped.append(f"{column}: {extreme} daily moves >100%, likely a data defect")
            continue
        keep.append(column)
    return panel[keep]


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------


def walk_forward_by_slicing(
    net_by_lookback: dict[int, pd.Series], train_days: int, oos_days: int
) -> dict:
    """In-sample pick the best lookback, measure it out-of-sample.

    Positions are causal, so slicing an already-computed return series is
    equivalent to re-running on the window and avoids per-window warm-up bias.
    """
    reference = net_by_lookback[PRIMARY_LOOKBACK].dropna()
    index = reference.index
    windows = []
    start = 0
    while start + train_days + oos_days <= len(index):
        train_slice = slice(start, start + train_days)
        oos_slice = slice(start + train_days, start + train_days + oos_days)

        scores = {}
        for lookback, series in net_by_lookback.items():
            aligned = series.reindex(index)
            train_returns = aligned.iloc[train_slice].dropna()
            scores[lookback] = (
                float(train_returns.mean() / train_returns.std(ddof=1) * np.sqrt(TRADING_DAYS))
                if len(train_returns) > 30 and train_returns.std(ddof=1) > 0
                else -np.inf
            )
        winner = max(scores, key=scores.get)
        oos_returns = net_by_lookback[winner].reindex(index).iloc[oos_slice].dropna()
        if len(oos_returns) > 30:
            windows.append(
                {
                    "start": str(index[start].date()),
                    "oos_start": str(index[start + train_days].date()),
                    "winner_lookback": winner,
                    "oos_total_return": float((1 + oos_returns).prod() - 1),
                    "oos_sharpe": float(
                        oos_returns.mean() / oos_returns.std(ddof=1) * np.sqrt(TRADING_DAYS)
                    )
                    if oos_returns.std(ddof=1) > 0
                    else 0.0,
                }
            )
        start += oos_days

    positive = [w for w in windows if w["oos_sharpe"] > 0]
    return {
        "windows": windows,
        "n_windows": len(windows),
        "total_oos_return": float(np.prod([1 + w["oos_total_return"] for w in windows]) - 1)
        if windows
        else float("nan"),
        "share_positive_sharpe": len(positive) / len(windows) if windows else float("nan"),
    }


def _fmt(value, kind="num"):
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "n/a"
    if kind == "pct":
        return f"{value:.2%}"
    if kind == "int":
        return f"{int(value)}"
    return f"{value:.3f}"


def _table(rows, label):
    header = (
        f"| {label} | Expected return p.a. | Sharpe | Sortino | Max DD | Win rate (trades) | "
        "Payoff | Profit factor | Expectancy/trade | Trades | Avg bars | Hit rate (days) | t-stat |"
    )
    sep = "|" + "---|" * 13
    lines = [header, sep]
    for row in rows:
        lines.append(
            f"| {row['strategy']} | {_fmt(row.get('expected_return_annual'), 'pct')} | "
            f"{_fmt(row.get('sharpe'))} | {_fmt(row.get('sortino'))} | "
            f"{_fmt(row.get('max_drawdown'), 'pct')} | {_fmt(row.get('win_rate'), 'pct')} | "
            f"{_fmt(row.get('payoff_ratio'))} | {_fmt(row.get('profit_factor'))} | "
            f"{_fmt(row.get('expectancy_per_trade'))} | {_fmt(row.get('n_trades'), 'int')} | "
            f"{_fmt(row.get('avg_bars_held'))} | {_fmt(row.get('hit_rate_periods'), 'pct')} | "
            f"{_fmt(row.get('t_stat'))} |"
        )
    return lines


def _write_tables(strategy_rows, sleeve_rows, instrument_frame, metrics, classes):
    lines = [
        "# TSMOM — Per-Strategy and Per-Instrument Results",
        "",
        f"Generated {date.today().isoformat()}. Companion to `report.md`.",
        "",
        "Two views of the same P&L: **period statistics** treat each bar as an",
        "observation (what risk asks); **trade statistics** collapse each held position",
        "into one round-trip (what a trader asks). A strategy can look different on each.",
        "",
        "A trade is a maximal run of bars holding the same sign. Vol targeting resizes",
        "within a trade without splitting it. P&L is booked one bar after the position",
        "is set, and per-instrument P&L sums exactly to the portfolio total.",
        "",
        "## By strategy variant (whole portfolio)",
        "",
    ]
    lines += _table(strategy_rows, "Strategy")
    lines += ["", "## By asset-class sleeve (12m lookback)", ""]
    lines += _table(sleeve_rows, "Sleeve")
    lines += [
        "",
        "## By instrument (12m lookback, primary specification)",
        "",
        "Sorted by total P&L contribution.",
        "",
        "| Instrument | Class | Total P&L | Expected return p.a. | Sharpe | Max DD | "
        "Win rate | Payoff | Profit factor | Expectancy/trade | Trades | Avg bars |",
        "|" + "---|" * 12,
    ]
    for row in instrument_frame.to_dict(orient="records"):
        lines.append(
            f"| `{row['instrument']}` | {classes.get(row['instrument'], '')} | "
            f"{_fmt(row.get('total_pnl'))} | {_fmt(row.get('expected_return_annual'), 'pct')} | "
            f"{_fmt(row.get('sharpe'))} | {_fmt(row.get('max_drawdown'), 'pct')} | "
            f"{_fmt(row.get('win_rate'), 'pct')} | {_fmt(row.get('payoff_ratio'))} | "
            f"{_fmt(row.get('profit_factor'))} | {_fmt(row.get('expectancy_per_trade'))} | "
            f"{_fmt(row.get('n_trades'), 'int')} | {_fmt(row.get('avg_bars_held'))} |"
        )
    lines.append("")
    (OUT_DIR / "strategy_results.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"  tables -> {(OUT_DIR / 'strategy_results.md').relative_to(REPO_ROOT)}")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("loading cached series ...")
    series, classes, dropped = load_series()

    aligned, filled_counts = align_on_common_calendar(series)
    quality = data_quality_report(aligned, filled_counts)

    panel = build_return_panel(series, classes)
    panel = panel[panel.index >= pd.Timestamp(START)]
    panel = quality_filter(panel, dropped)
    print(f"  {panel.shape[1]} instruments, {panel.shape[0]} bars, dropped {len(dropped)}")

    # The union-index bug silently zeroed 30/39 instruments while still
    # reporting a Sharpe. Never ship a result without checking coverage again.
    live = tsmom_signal(panel, PRIMARY_LOOKBACK, lag=1).notna().sum()
    dead = [c for c in panel.columns if live[c] == 0]
    if dead:
        raise SystemExit(f"ABORT: {len(dead)} instruments never produce a signal: {dead}")
    print(f"  signal coverage: all {panel.shape[1]} instruments live "
          f"(median {int(live.median())} bars)")

    config = StudyConfig(lookback_months=PRIMARY_LOOKBACK)
    print("running primary specification ...")
    primary = run_tsmom(panel, classes, config)
    metrics = primary.metrics
    net = primary.net_returns.dropna()

    print("running lookback grid ...")
    net_by_lookback = {}
    grid_rows = []
    for lookback in LOOKBACK_GRID:
        result = run_tsmom(panel, classes, StudyConfig(lookback_months=lookback))
        net_by_lookback[lookback] = result.net_returns
        grid_rows.append({"lookback_months": lookback, "net_sharpe": result.metrics["net_sharpe"]})
        print(f"  {lookback:>2}m  net Sharpe {result.metrics['net_sharpe']:.3f}")

    print("cost sensitivity ...")
    cost_rows = []
    for multiplier in (0.0, 1.0, 2.0, 3.0, 5.0):
        result = run_tsmom(panel, classes, StudyConfig(lookback_months=PRIMARY_LOOKBACK, cost_multiplier=multiplier))
        cost_rows.append({"multiplier": multiplier, "net_sharpe": result.metrics["net_sharpe"]})
        print(f"  {multiplier:>3.1f}x  net Sharpe {result.metrics['net_sharpe']:.3f}")

    print("leave-one-instrument-out ...")
    loo_rows = []
    for column in panel.columns:
        subset = panel.drop(columns=[column])
        result = run_tsmom(subset, classes, config)
        loo_rows.append({"excluded": column, "net_sharpe": result.metrics["net_sharpe"]})
    loo_rows.sort(key=lambda row: row["net_sharpe"])

    print("walk-forward ...")
    wfo = walk_forward_by_slicing(net_by_lookback, train_days=5 * TRADING_DAYS, oos_days=TRADING_DAYS)

    print("bootstrap + DSR ...")
    values = net.to_numpy()
    boot_lo, boot_hi = stationary_bootstrap_ci(values, np.mean, n_bootstrap=1000, rng_seed=42)
    variant_sharpes = [row["net_sharpe"] for row in grid_rows]
    dsr = deflated_sharpe_ratio(
        values, n_variants=len(LOOKBACK_GRID), variant_sharpes=variant_sharpes
    )

    yearly = net.groupby(net.index.year).apply(lambda s: float((1 + s).prod() - 1))
    share_positive_years = float((yearly > 0).mean())

    by_class: dict[str, float] = {}
    for asset_class in sorted(set(classes[c] for c in panel.columns)):
        members = [c for c in panel.columns if classes[c] == asset_class]
        # Diagnostic sleeves are allowed to be small; the min-instrument guard
        # protects the headline portfolio, not the breakdown.
        sleeve = run_tsmom(
            panel[members], classes, StudyConfig(lookback_months=PRIMARY_LOOKBACK, min_instruments=1)
        )
        by_class[asset_class] = sleeve.metrics["net_sharpe"]

    # ---------------- gate evaluation ----------------
    gates = {
        "G-1": (metrics["net_sharpe"] > 0.30, f"net Sharpe = {metrics['net_sharpe']:.3f}"),
        "G-2": (dsr > 0.95, f"DSR = {dsr:.4f} (n_variants={len(LOOKBACK_GRID)})"),
        "G-3": (
            wfo["total_oos_return"] > 0 and wfo["share_positive_sharpe"] >= 0.60,
            f"OOS total return = {wfo['total_oos_return']:.2%}, "
            f"{wfo['share_positive_sharpe']:.0%} of {wfo['n_windows']} windows positive",
        ),
        "G-4": (
            next(r["net_sharpe"] for r in cost_rows if r["multiplier"] == 3.0) > 0,
            f"net Sharpe at 3x costs = {next(r['net_sharpe'] for r in cost_rows if r['multiplier'] == 3.0):.3f}",
        ),
        "G-5": (
            all(r["net_sharpe"] > 0.20 for r in loo_rows),
            f"worst exclusion = {loo_rows[0]['excluded']} at {loo_rows[0]['net_sharpe']:.3f}",
        ),
        "G-6": (share_positive_years >= 0.55, f"{share_positive_years:.0%} of {len(yearly)} years positive"),
        "G-7": (boot_lo > 0, f"95% CI on mean daily net return = [{boot_lo:.6f}, {boot_hi:.6f}]"),
        "G-8": (metrics["net_sharpe"] < 1.5, f"net Sharpe = {metrics['net_sharpe']:.3f}"),
    }
    n_passed = sum(1 for passed, _ in gates.values() if passed)
    verdict = (
        "PROVISIONALLY VALIDATED"
        if n_passed == 8
        else "PROMISING, NOT DEPLOYABLE"
        if n_passed >= 6
        else "REJECTED"
    )

    # ------------------------------------------------------------------
    # Per-strategy and per-instrument statistics
    # ------------------------------------------------------------------
    print("building per-strategy statistics ...")
    strategy_rows = []
    for lookback in LOOKBACK_GRID:
        result = run_tsmom(panel, classes, StudyConfig(lookback_months=lookback))
        summary = performance_summary(
            result.net_returns, result.positions, panel, execution_lag=1
        )
        summary["strategy"] = f"TSMOM {lookback}m"
        strategy_rows.append(summary)

    sleeve_rows = []
    for asset_class in sorted(set(classes[c] for c in panel.columns)):
        members = [c for c in panel.columns if classes[c] == asset_class]
        sleeve = run_tsmom(
            panel[members], classes, StudyConfig(lookback_months=PRIMARY_LOOKBACK, min_instruments=1)
        )
        summary = performance_summary(
            sleeve.net_returns, sleeve.positions, panel[members], execution_lag=1
        )
        summary["strategy"] = f"{asset_class} ({len(members)})"
        sleeve_rows.append(summary)

    instrument_frame = per_instrument_summary(primary.positions, panel, execution_lag=1)
    instrument_rows = instrument_frame.to_dict(orient="records")

    _write_tables(strategy_rows, sleeve_rows, instrument_frame, metrics, classes)

    payload = {
        "generated_at": date.today().isoformat(),
        "instruments": list(panel.columns),
        "n_instruments": panel.shape[1],
        "sample": {"start": str(panel.index.min().date()), "end": str(panel.index.max().date())},
        "dropped": dropped,
        "data_quality": quality,
        "metrics": metrics,
        "by_asset_class": by_class,
        "lookback_grid": grid_rows,
        "cost_sensitivity": cost_rows,
        "leave_one_out": loo_rows,
        "walk_forward": wfo,
        "bootstrap_ci": {"lower": boot_lo, "upper": boot_hi},
        "deflated_sharpe": dsr,
        "variant_sharpes": variant_sharpes,
        "strategy_table": strategy_rows,
        "sleeve_table": sleeve_rows,
        "instrument_table": instrument_rows,
        "yearly_returns": {str(k): float(v) for k, v in yearly.items()},
        "gates": {k: {"passed": bool(p), "evidence": e, "criterion": PRE_REGISTERED_GATES[k]} for k, (p, e) in gates.items()},
        "n_gates_passed": n_passed,
        "verdict": verdict,
    }
    (OUT_DIR / "results.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 64)
    print(f"VERDICT: {verdict}  ({n_passed}/8 gates)")
    print("=" * 64)
    for key, (passed, evidence) in gates.items():
        print(f"  {'PASS' if passed else 'FAIL'}  {key}  {evidence}")
    print(f"\nnet Sharpe {metrics['net_sharpe']:.3f} | CAGR {metrics['net_cagr']:.2%} | "
          f"vol {metrics['net_vol']:.2%} | maxDD {metrics['max_drawdown']:.2%}")
    print(f"results -> {(OUT_DIR / 'results.json').relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
