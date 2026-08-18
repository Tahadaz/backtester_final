"""Run the pre-registered cross-asset carry study and grade it against the gates.

    python tools/global_desk/run_carry_study.py

Requires ingest_free_panel.py and ingest_rates.py to have run. Evaluates the
nine gates in docs/global-desk/03-carry-preregistration.md §4 and writes to
research-out/global-desk-carry/<date>/.
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

from quant_core.cross_asset.carry_study import (  # noqa: E402
    CARRY_VARIANTS,
    RATES_TENOR,
    fx_carry,
    lag_monthly_rates,
    rates_curve_carry,
)
from quant_core.cross_asset.performance import (  # noqa: E402
    per_instrument_summary,
    performance_summary,
)
from quant_core.cross_asset.security_master import REGISTRY, get as sm_get  # noqa: E402
from quant_core.cross_asset.tsmom_study import (  # noqa: E402
    StudyConfig,
    TRADING_DAYS,
    build_return_panel,
    run_signal_portfolio,
    run_tsmom,
)
from quant_core.research.stats.robustness import (  # noqa: E402
    deflated_sharpe_ratio,
    stationary_bootstrap_ci,
)

PRICE_DIR = REPO_ROOT / "data" / "global_desk" / "raw"
RATE_DIR = REPO_ROOT / "data" / "global_desk" / "rates"
OUT_DIR = REPO_ROOT / "research-out" / "global-desk-carry" / date.today().isoformat()

FX_INSTRUMENTS = [e.canonical_id for e in REGISTRY if e.asset_class == "fx"]
RATES_INSTRUMENTS = list(RATES_TENOR)
CURVE_COLUMNS = ["DGS3MO", "DGS1", "DGS2", "DGS5", "DGS10", "DGS30"]
PRIMARY_VARIANT = "sign"

GATES = {
    "C-1": "Net Sharpe > 0.20",
    "C-2": "Deflated Sharpe Ratio > 0.95 (3 variants)",
    "C-3": "WFO OOS net return > 0 and OOS Sharpe > 0 in >= 55% of windows",
    "C-4": "Net Sharpe > 0 at 3x declared costs",
    "C-5": "Leave-one-instrument-out: net Sharpe > 0.10 for every exclusion",
    "C-6": "Positive net return in >= 50% of calendar years",
    "C-7": "95% stationary-bootstrap lower bound on mean net return > 0",
    "C-8": "Net Sharpe < 1.5 (sanity ceiling)",
    "C-9": "Correlation with the TSMOM sleeve < 0.50",
}


def _load(directory: pathlib.Path, name: str) -> pd.Series | None:
    path = directory / f"{name}.parquet"
    if not path.exists():
        return None
    series = pd.read_parquet(path)["value"].astype(float).dropna()
    series.index = pd.to_datetime(series.index)
    return series


def build_panels() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, str], list[str]]:
    notes: list[str] = []
    prices: dict[str, pd.Series] = {}
    classes: dict[str, str] = {}
    for instrument in FX_INSTRUMENTS + RATES_INSTRUMENTS:
        series = _load(PRICE_DIR, instrument)
        if series is None:
            notes.append(f"{instrument}: no cached price data")
            continue
        prices[instrument] = series
        classes[instrument] = sm_get(instrument).asset_class

    returns = build_return_panel(prices, classes)
    calendar = returns.index

    rate_by_currency: dict[str, pd.Series] = {}
    for currency in sorted({sm_get(i).base_ccy for i in FX_INSTRUMENTS} | {sm_get(i).quote_ccy for i in FX_INSTRUMENTS}):
        series = _load(RATE_DIR, f"IB3M_{currency}")
        if series is None:
            notes.append(f"{currency}: no interbank rate series")
            continue
        rate_by_currency[currency] = lag_monthly_rates(series)

    pairs = {i: (sm_get(i).base_ccy, sm_get(i).quote_ccy) for i in FX_INSTRUMENTS}
    fx = fx_carry(rate_by_currency, pairs, calendar)

    curve_frame = {}
    for column in CURVE_COLUMNS:
        series = _load(RATE_DIR, column)
        if series is None:
            notes.append(f"{column}: missing from the curve")
            continue
        curve_frame[column] = series.reindex(series.index.union(calendar)).ffill().reindex(calendar)
    curve = pd.DataFrame(curve_frame, index=calendar)
    rates = rates_curve_carry(curve)

    carry = pd.concat([fx, rates], axis=1).reindex(columns=returns.columns)
    return returns, carry, classes, notes


def walk_forward(net_by_variant: dict[str, pd.Series], train_days: int, oos_days: int) -> dict:
    reference = net_by_variant[PRIMARY_VARIANT].dropna()
    index = reference.index
    windows = []
    start = 0
    while start + train_days + oos_days <= len(index):
        scores = {}
        for name, series in net_by_variant.items():
            train = series.reindex(index).iloc[start : start + train_days].dropna()
            scores[name] = (
                float(train.mean() / train.std(ddof=1) * np.sqrt(TRADING_DAYS))
                if len(train) > 30 and train.std(ddof=1) > 0
                else -np.inf
            )
        winner = max(scores, key=scores.get)
        oos = net_by_variant[winner].reindex(index).iloc[start + train_days : start + train_days + oos_days].dropna()
        if len(oos) > 30:
            windows.append(
                {
                    "oos_start": str(index[start + train_days].date()),
                    "winner": winner,
                    "oos_total_return": float((1 + oos).prod() - 1),
                    "oos_sharpe": float(oos.mean() / oos.std(ddof=1) * np.sqrt(TRADING_DAYS))
                    if oos.std(ddof=1) > 0
                    else 0.0,
                }
            )
        start += oos_days
    positive = [w for w in windows if w["oos_sharpe"] > 0]
    return {
        "windows": windows,
        "n_windows": len(windows),
        "total_oos_return": float(np.prod([1 + w["oos_total_return"] for w in windows]) - 1) if windows else float("nan"),
        "share_positive_sharpe": len(positive) / len(windows) if windows else float("nan"),
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("building panels ...")
    returns, carry, classes, notes = build_panels()
    live = carry.notna().sum()
    dead = [c for c in carry.columns if live[c] == 0]
    if dead:
        raise SystemExit(f"ABORT: no carry signal for {dead}")
    print(f"  {returns.shape[1]} instruments, {returns.shape[0]} bars")
    print(f"  carry coverage: {int(live.min())}-{int(live.max())} bars per instrument")

    config = StudyConfig(min_instruments=5)

    print("running variants ...")
    net_by_variant: dict[str, pd.Series] = {}
    results = {}
    strategy_rows = []
    for name, fn in CARRY_VARIANTS.items():
        signal = fn(carry)
        result = run_signal_portfolio(returns, signal, classes, config)
        net_by_variant[name] = result.net_returns
        results[name] = result
        summary = performance_summary(result.net_returns, result.positions, returns)
        summary["strategy"] = f"Carry ({name})"
        strategy_rows.append(summary)
        print(f"  {name:<10} net Sharpe {result.metrics['net_sharpe']:6.3f}")

    primary = results[PRIMARY_VARIANT]
    metrics = primary.metrics
    net = primary.net_returns.dropna()

    print("cost sensitivity ...")
    cost_rows = []
    for multiplier in (0.0, 1.0, 2.0, 3.0, 5.0):
        result = run_signal_portfolio(
            returns, CARRY_VARIANTS[PRIMARY_VARIANT](carry), classes,
            StudyConfig(min_instruments=5, cost_multiplier=multiplier),
        )
        cost_rows.append({"multiplier": multiplier, "net_sharpe": result.metrics["net_sharpe"]})
        print(f"  {multiplier:>3.1f}x  net Sharpe {result.metrics['net_sharpe']:.3f}")

    print("leave-one-out ...")
    loo_rows = []
    for column in returns.columns:
        subset = returns.drop(columns=[column])
        result = run_signal_portfolio(
            subset, CARRY_VARIANTS[PRIMARY_VARIANT](carry.drop(columns=[column])), classes,
            StudyConfig(min_instruments=1),
        )
        loo_rows.append({"excluded": column, "net_sharpe": result.metrics["net_sharpe"]})
    loo_rows.sort(key=lambda row: row["net_sharpe"])

    print("sleeve breakdown ...")
    sleeve_rows = []
    by_class = {}
    for asset_class in sorted(set(classes.values())):
        members = [c for c in returns.columns if classes[c] == asset_class]
        sleeve = run_signal_portfolio(
            returns[members], CARRY_VARIANTS[PRIMARY_VARIANT](carry[members]), classes,
            StudyConfig(min_instruments=1),
        )
        summary = performance_summary(sleeve.net_returns, sleeve.positions, returns[members])
        summary["strategy"] = f"{asset_class} ({len(members)})"
        sleeve_rows.append(summary)
        by_class[asset_class] = sleeve.metrics["net_sharpe"]

    print("walk-forward, bootstrap, DSR ...")
    wfo = walk_forward(net_by_variant, train_days=5 * TRADING_DAYS, oos_days=TRADING_DAYS)
    values = net.to_numpy()
    boot_lo, boot_hi = stationary_bootstrap_ci(values, np.mean, n_bootstrap=1000, rng_seed=42)
    variant_sharpes = [row["sharpe"] for row in strategy_rows]
    dsr = deflated_sharpe_ratio(values, n_variants=len(CARRY_VARIANTS), variant_sharpes=variant_sharpes)

    yearly = net.groupby(net.index.year).apply(lambda s: float((1 + s).prod() - 1))
    share_positive_years = float((yearly > 0).mean())

    print("correlation with TSMOM ...")
    tsmom_prices, tsmom_classes = {}, {}
    for entry in REGISTRY:
        series = _load(PRICE_DIR, entry.canonical_id)
        if series is not None and series.size >= 3 * TRADING_DAYS:
            tsmom_prices[entry.canonical_id] = series
            tsmom_classes[entry.canonical_id] = entry.asset_class
    tsmom_panel = build_return_panel(tsmom_prices, tsmom_classes)
    tsmom_net = run_tsmom(tsmom_panel, tsmom_classes, StudyConfig(lookback_months=12)).net_returns
    joined = pd.concat([net.rename("carry"), tsmom_net.rename("tsmom")], axis=1).dropna()
    correlation = float(joined["carry"].corr(joined["tsmom"])) if len(joined) > 100 else float("nan")

    instrument_frame = per_instrument_summary(primary.positions, returns)

    gates = {
        "C-1": (metrics["net_sharpe"] > 0.20, f"net Sharpe = {metrics['net_sharpe']:.3f}"),
        "C-2": (dsr > 0.95, f"DSR = {dsr:.4f}"),
        "C-3": (
            wfo["total_oos_return"] > 0 and wfo["share_positive_sharpe"] >= 0.55,
            f"OOS return {wfo['total_oos_return']:.2%}, {wfo['share_positive_sharpe']:.0%} of {wfo['n_windows']} windows",
        ),
        "C-4": (
            next(r["net_sharpe"] for r in cost_rows if r["multiplier"] == 3.0) > 0,
            f"3x costs Sharpe = {next(r['net_sharpe'] for r in cost_rows if r['multiplier'] == 3.0):.3f}",
        ),
        "C-5": (
            all(r["net_sharpe"] > 0.10 for r in loo_rows),
            f"worst = {loo_rows[0]['excluded']} at {loo_rows[0]['net_sharpe']:.3f}",
        ),
        "C-6": (share_positive_years >= 0.50, f"{share_positive_years:.0%} of {len(yearly)} years positive"),
        "C-7": (boot_lo > 0, f"95% CI = [{boot_lo:.6f}, {boot_hi:.6f}]"),
        "C-8": (metrics["net_sharpe"] < 1.5, f"net Sharpe = {metrics['net_sharpe']:.3f}"),
        "C-9": (correlation < 0.50, f"corr with TSMOM = {correlation:.3f}"),
    }
    n_passed = sum(1 for passed, _ in gates.values() if passed)
    verdict = (
        "PROVISIONALLY VALIDATED" if n_passed == 9
        else "PROMISING, NOT DEPLOYABLE" if n_passed >= 7
        else "REJECTED"
    )

    payload = {
        "generated_at": date.today().isoformat(),
        "instruments": list(returns.columns),
        "sample": {"start": str(returns.index.min().date()), "end": str(returns.index.max().date())},
        "notes": notes,
        "metrics": metrics,
        "by_asset_class": by_class,
        "strategy_table": strategy_rows,
        "sleeve_table": sleeve_rows,
        "instrument_table": instrument_frame.to_dict(orient="records"),
        "cost_sensitivity": cost_rows,
        "leave_one_out": loo_rows,
        "walk_forward": wfo,
        "bootstrap_ci": {"lower": boot_lo, "upper": boot_hi},
        "deflated_sharpe": dsr,
        "correlation_with_tsmom": correlation,
        "yearly_returns": {str(k): float(v) for k, v in yearly.items()},
        "gates": {k: {"passed": bool(p), "evidence": e, "criterion": GATES[k]} for k, (p, e) in gates.items()},
        "n_gates_passed": n_passed,
        "verdict": verdict,
    }
    (OUT_DIR / "results.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    print("\n" + "=" * 64)
    print(f"VERDICT: {verdict}  ({n_passed}/9 gates)")
    print("=" * 64)
    for key, (passed, evidence) in gates.items():
        print(f"  {'PASS' if passed else 'FAIL'}  {key}  {evidence}")
    print(f"\nnet Sharpe {metrics['net_sharpe']:.3f} | CAGR {metrics['net_cagr']:.2%} | "
          f"vol {metrics['net_vol']:.2%} | maxDD {metrics['max_drawdown']:.2%}")
    print(f"results -> {(OUT_DIR / 'results.json').relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
