"""CLI entrypoint for the exit-policy horse-race harness.

Run from repo root:
    python scripts/research/exit_policy_horse_race.py \\
        --horizon weekly --variant expanded \\
        --policies A,B,C,D,E \\
        --bootstrap 10000 \\
        --out results/exit_policy/

Outputs:
    <out>/report.md    — Markdown ranking table with CI and SPA verdict
    <out>/results.csv  — Per-policy metrics CSV

Connection uses DATABASE_URL env var or the default psycopg2 URL.
S3/MinIO uses S3_ENDPOINT_URL / S3_ACCESS_KEY / S3_SECRET_KEY env vars.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

# Repo root on sys.path → imports `core` and `services.api.app`
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from services.api.app.db import _ensure_session_factory
from core.quant_core.research.exit_policy import HarnessConfig, run_harness, format_report
from core.quant_core.research.exit_policy.policies import K_GRID


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Exit-policy horse race: score TP/SL policies on WFO OOS trades."
    )
    p.add_argument("--horizon", default="weekly", help="Signal horizon (weekly/daily/monthly)")
    p.add_argument("--variant", default="expanded", help="Signal variant")
    p.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated symbol list; default = all qualifying.",
    )
    p.add_argument(
        "--policies",
        default="A,B,C,D,E",
        help="Comma-separated policy letters to run (A=baseline, B=ATR, C=calibrated, D=S/R, E=hybrid).",
    )
    p.add_argument(
        "--k-grid",
        default=",".join(str(k) for k in K_GRID),
        help="Comma-separated k values for B/E variants.",
    )
    p.add_argument("--min-calib-trades", type=int, default=20, help="Minimum trades for calibration (Policy C).")
    p.add_argument("--bootstrap", type=int, default=10_000, help="Number of bootstrap resamples.")
    p.add_argument("--no-sr", action="store_true", help="Skip S/R computation (disables policies D/E).")
    p.add_argument("--out", default=None, help="Output directory for report files.")
    return p.parse_args()


def main() -> None:
    # Windows consoles default to cp1252, which can't encode report glyphs (Δ, ≤).
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    args = parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] if args.symbols else None
    policies = [p.strip().upper() for p in args.policies.split(",") if p.strip()]
    k_grid = [float(k) for k in args.k_grid.split(",") if k.strip()]

    config = HarnessConfig(
        horizon=args.horizon,
        variant=args.variant,
        symbols=symbols,
        policies=policies,  # type: ignore[arg-type]
        k_grid=k_grid,
        min_calib_trades=args.min_calib_trades,
        bootstrap_B=args.bootstrap,
        out_dir=args.out,
        compute_sr=not args.no_sr,
    )

    print(f"Exit-policy horse race: horizon={config.horizon} variant={config.variant}")
    print(f"Policies: {config.policies}  |  k-grid: {config.k_grid}")
    print(f"Symbols: {config.symbols or 'ALL qualifying'}  |  Bootstrap: {config.bootstrap_B:,}")
    print()

    SessionLocal = _ensure_session_factory()
    db = SessionLocal()
    try:
        report = run_harness(db, config)
    finally:
        db.close()

    # Print summary to stdout
    md = format_report(report)
    print(md)

    # Write output files
    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)

        report_path = out_dir / "report.md"
        report_path.write_text(md, encoding="utf-8")
        print(f"\nReport written to: {report_path}")

        csv_path = out_dir / "results.csv"
        _write_csv(csv_path, report)
        print(f"CSV written to:    {csv_path}")


def _write_csv(path: Path, report) -> None:
    """Write per-policy metrics to CSV."""
    rows = []
    for pr in report.policy_results:
        m = pr.metrics
        st = report.stats.get(pr.name, {})
        rows.append({
            "policy": pr.name,
            "policy_letter": pr.policy,
            "sharpe": m.get("sharpe", ""),
            "total_return": m.get("total_return", ""),
            "cagr": m.get("cagr", ""),
            "max_drawdown": m.get("max_drawdown", ""),
            "win_rate": m.get("win_rate", ""),
            "expectancy": m.get("expectancy", ""),
            "payoff_ratio": m.get("payoff_ratio", ""),
            "n_trades": m.get("n_trades", ""),
            "mean_diff_vs_A": st.get("mean_diff", ""),
            "ci_lower": st.get("ci_lower", ""),
            "ci_upper": st.get("ci_upper", ""),
            "spa_pvalue": st.get("spa_pvalue", ""),
            "rc_pvalue": st.get("rc_pvalue", ""),
            "exit_reasons": str(pr.exit_reasons),
        })

    if rows:
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)


if __name__ == "__main__":
    main()
