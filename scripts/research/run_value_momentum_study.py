"""Driver for the cross-sectional momentum mechanism test + gated value+momentum
combination study (Stage 1/2 research plan, pre-registered
research-out/value-momentum-study/PREREGISTRATION.md, 2026-07-12).

Deliberate deviation from the plan's `_load_panel` route (same deviation the
prior combined-strategy runner made, for the same reason): this runner loads
the SAME repaired panel CSV + `eligibility_mask` as
`scripts/research/run_combined_value_technical_strategy.py` (rather than
`methodology_bakeoff._load_panel`), so the C0a parity/sanity check against
that prior study is apples-to-apples -- same panel, same engine, same inputs.

Read-only: no writes to the DB. All I/O side effects are local CSV/JSON files
under research-out/value-momentum-study/<UTC ts>/.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import pandas as pd

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://app:app@127.0.0.1:5555/quant")
os.environ.setdefault("S3_ENDPOINT_URL", "http://127.0.0.1:9000")
os.environ.setdefault("AWS_ACCESS_KEY_ID", os.environ.get("S3_ACCESS_KEY", "minio"))
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", os.environ.get("S3_SECRET_KEY", "minio12345"))
os.environ.setdefault("S3_BUCKET", "quant-artifacts")

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import create_engine, text  # noqa: E402

from core.quant_core.fundamentals.cross_section.characteristic_study import _full_price_loader  # noqa: E402
from core.quant_core.fundamentals.cross_section.combined_strategy import (  # noqa: E402
    CombinedConfig,
    apply_overlays_to_holdings,
    build_rank_composite_holdings,
    build_signal_holdings,
    difference_test,
    evaluate_acceptance,
    run_gated_vintage_backtest,
    subperiod_summary,
    summarize_performance,
)
from core.quant_core.fundamentals.cross_section.live_like_strategy import (  # noqa: E402
    LiveLikeConfig,
    build_vintage_holdings_by_date,
    combine_sleeves,
    eligibility_mask,
)

PANEL_PATH = Path(
    "research-out/data-quality-forensic-repair/2026-07-06/characteristic-study-after-repair/"
    "20260706-194324/panel_characteristics.csv"
)
OUT_DIR = Path("research-out/value-momentum-study") / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
PRIOR_STUDY_METRICS = Path("research-out/combined-portfolio-strategy/20260712-161305/metrics.json")

SECTOR_CAP = 0.30
MAX_NAME_WEIGHT = 0.10
COST_BPS_PRIMARY = 33.0
DD_TOLERANCE = 0.02
P_THRESHOLD = 0.10


def _rel_close(a: float | None, b: float | None, tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    if b == 0:
        return abs(a - b) <= tol
    return abs(a - b) / abs(b) <= tol


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report: dict = {"run_metadata": {}, "anomalies": []}

    # --- 1. Panel (same route as the prior combined-strategy runner) ---
    if not PANEL_PATH.exists():
        raise SystemExit(f"ABORT: panel CSV not found at {PANEL_PATH} -- cannot proceed.")
    panel = pd.read_csv(PANEL_PATH)
    panel["as_of_date"] = pd.to_datetime(panel["as_of_date"]).dt.date
    panel = eligibility_mask(panel)
    print(f"Loaded panel: {PANEL_PATH} ({len(panel)} rows, {panel['symbol'].nunique()} symbols)")

    momentum_coverage = {
        "momentum_12_1_raw_notna": int(panel["momentum_12_1_raw"].notna().sum()),
        "momentum_6_1_raw_notna": int(panel["momentum_6_1_raw"].notna().sum()),
        "total_rows": int(len(panel)),
    }
    print(f"Momentum column coverage: {momentum_coverage}")
    report["run_metadata"]["momentum_coverage"] = momentum_coverage

    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)

    # --- 2. Sector map (same query as the prior runner) ---
    sector_rows = pd.read_sql(text("SELECT symbol, sector FROM stock_master"), engine)
    sector_map: dict[str, str | None] = {}
    for _, row in sector_rows.iterrows():
        sym = str(row["symbol"]).strip().upper()
        sec = row["sector"]
        if pd.notna(sec):
            sector_map[sym] = str(sec)
    n_from_db = len(sector_map)
    if "sector" in panel.columns:
        panel_sector = panel.dropna(subset=["sector"]).groupby("symbol")["sector"].first()
        for sym, sec in panel_sector.items():
            symu = str(sym).strip().upper()
            if symu not in sector_map:
                sector_map[symu] = str(sec)
    print(f"Sector map: {n_from_db} from stock_master, {len(sector_map) - n_from_db} fallback from panel, {len(sector_map)} total")

    # --- 3. Prices / MASI benchmark (same route as the prior runner) ---
    print("Loading full daily price series...")
    price_frames = _full_price_loader()
    close_by_symbol = {sym: (df["Close"] if "Close" in df.columns else None) for sym, df in price_frames.items()}
    masi_close = None
    if "MASI" in price_frames and "Close" in price_frames["MASI"].columns:
        masi_close = pd.to_numeric(price_frames["MASI"]["Close"], errors="coerce").dropna()
    else:
        report["anomalies"].append("MASI close series not found in price_frames -- benchmark will be empty.")
    print(f"Loaded prices for {len(price_frames)} symbols; MASI present={masi_close is not None}")

    # --- 4. Holdings ---
    base_cfg = LiveLikeConfig(cost_bps=COST_BPS_PRIMARY)  # min_universe_names=9 default
    c0a_holdings = build_vintage_holdings_by_date(panel, strategy="S1_bm", config=base_cfg)
    m12_holdings = build_signal_holdings(panel, signal_col="momentum_12_1_raw", config=base_cfg)
    m6_holdings = build_signal_holdings(panel, signal_col="momentum_6_1_raw", config=base_cfg)
    vm_int_holdings = build_rank_composite_holdings(
        panel,
        components=[("book_to_market_raw", 0.5), ("momentum_12_1_raw", 0.5)],
        eligibility_cols=["eligible_bm"],
        config=base_cfg,
    )
    vm_int_w37_holdings = build_rank_composite_holdings(
        panel,
        components=[("book_to_market_raw", 0.3), ("momentum_12_1_raw", 0.7)],
        eligibility_cols=["eligible_bm"],
        config=base_cfg,
    )
    vm_int_w73_holdings = build_rank_composite_holdings(
        panel,
        components=[("book_to_market_raw", 0.7), ("momentum_12_1_raw", 0.3)],
        eligibility_cols=["eligible_bm"],
        config=base_cfg,
    )
    overlay_cfg = CombinedConfig(sector_cap=SECTOR_CAP, max_name_weight=MAX_NAME_WEIGHT, adv_floor_mad=None)
    vm_int_capped_holdings = apply_overlays_to_holdings(
        vm_int_holdings, sector_map=sector_map, config=overlay_cfg, adv_series_by_symbol=None
    )
    print(
        f"Holdings formed: C0a={len(c0a_holdings)} M12={len(m12_holdings)} M6={len(m6_holdings)} "
        f"VM_int={len(vm_int_holdings)} VM_int_capped={len(vm_int_capped_holdings)} dates"
    )

    # --- 5. Run cells (G0 mode) ---
    cells: dict[str, dict] = {
        "C0a": dict(holdings=c0a_holdings, cost=COST_BPS_PRIMARY),
        "M12": dict(holdings=m12_holdings, cost=COST_BPS_PRIMARY),
        "M6": dict(holdings=m6_holdings, cost=COST_BPS_PRIMARY),
        "VM_int": dict(holdings=vm_int_holdings, cost=COST_BPS_PRIMARY),
        "VM_int_capped": dict(holdings=vm_int_capped_holdings, cost=COST_BPS_PRIMARY),  # PRIMARY
        "VM_int_capped_cost50": dict(holdings=vm_int_capped_holdings, cost=50.0),
        "VM_int_capped_cost75": dict(holdings=vm_int_capped_holdings, cost=75.0),
        "VM_int_w37": dict(holdings=vm_int_w37_holdings, cost=COST_BPS_PRIMARY),
        "VM_int_w73": dict(holdings=vm_int_w73_holdings, cost=COST_BPS_PRIMARY),
    }

    results: dict[str, pd.DataFrame] = {}
    for name, spec in cells.items():
        config = CombinedConfig(base=LiveLikeConfig(cost_bps=spec["cost"]), gate="G0")
        monthly, events = run_gated_vintage_backtest(
            spec["holdings"], price_by_symbol=close_by_symbol, gate_by_symbol=None, config=config
        )
        monthly.to_csv(OUT_DIR / f"monthly_returns_{name}.csv", index=False)
        events.to_csv(OUT_DIR / f"events_{name}.csv", index=False)
        results[name] = monthly
        print(f"Cell {name}: {len(monthly)} months, {len(events)} events, formed from {len(spec['holdings'])} formation dates")

    # VM_mix: 50/50 sleeve blend of C0a and M12 realized returns (both already
    # run at the primary 33bps cost above). Combine at the return level FIRST,
    # slice to the common invested window AFTER (per spec).
    vm_mix_monthly = combine_sleeves(results["C0a"], results["M12"])
    vm_mix_monthly.to_csv(OUT_DIR / "monthly_returns_VM_mix.csv", index=False)
    results["VM_mix"] = vm_mix_monthly
    print(f"Cell VM_mix: {len(vm_mix_monthly)} months (50/50 blend of C0a and M12 realized returns; no separate event ledger)")

    # --- 6. Benchmark (MASI monthly, aligned to sorted panel formation dates) ---
    all_dates = sorted(c0a_holdings)
    bench_rows = []
    if masi_close is not None:
        for i in range(1, len(all_dates)):
            start, end = all_dates[i - 1], all_dates[i]
            s = masi_close[masi_close.index <= pd.Timestamp(start)]
            e = masi_close[masi_close.index <= pd.Timestamp(end)]
            if s.empty or e.empty:
                continue
            bench_rows.append({"as_of_date": end, "benchmark_return": float(e.iloc[-1] / s.iloc[-1] - 1.0)})
    bench_df = pd.DataFrame(bench_rows)
    bench_df.to_csv(OUT_DIR / "benchmark_returns.csv", index=False)
    masi_series = bench_df.set_index("as_of_date")["benchmark_return"] if not bench_df.empty else pd.Series(dtype=float)

    # --- 7. Common invested window: first date where BOTH C0a and M12 have
    #     n_holdings > 0, through the last panel date. ---
    c0a_monthly = results["C0a"]
    m12_monthly = results["M12"]
    both = c0a_monthly[["as_of_date", "n_holdings"]].merge(
        m12_monthly[["as_of_date", "n_holdings"]], on="as_of_date", suffixes=("_c0a", "_m12")
    )
    both_invested = both[(both["n_holdings_c0a"] > 0) & (both["n_holdings_m12"] > 0)]
    if both_invested.empty:
        raise SystemExit("ABORT: no date where both C0a and M12 hold names -- cannot determine common invested window.")
    common_start = both_invested["as_of_date"].iloc[0]
    common_end = c0a_monthly["as_of_date"].iloc[-1]
    print(f"\nCommon invested window: {common_start} .. {common_end}")

    def slice_invested(df: pd.DataFrame) -> pd.DataFrame:
        return df[(df["as_of_date"] >= common_start) & (df["as_of_date"] <= common_end)].reset_index(drop=True)

    masi_sliced = masi_series[(masi_series.index >= common_start) & (masi_series.index <= common_end)]

    # --- 8. Metrics per cell (full + invested) ---
    metrics: dict = {"cells": {}}
    for name, monthly in results.items():
        full_summary = summarize_performance(monthly, periods_per_year=12, benchmark_returns=masi_series)
        inv_summary = summarize_performance(slice_invested(monthly), periods_per_year=12, benchmark_returns=masi_sliced)
        metrics["cells"][name] = {"full": full_summary, "invested": inv_summary}

    masi_frame_full = pd.DataFrame({"as_of_date": masi_series.index, "net_return": masi_series.values, "turnover": 0.0})
    masi_summary_full = summarize_performance(masi_frame_full, periods_per_year=12) if len(masi_series) >= 2 else {"insufficient_data": True}
    masi_frame_inv = pd.DataFrame({"as_of_date": masi_sliced.index, "net_return": masi_sliced.values, "turnover": 0.0})
    masi_summary_inv = summarize_performance(masi_frame_inv, periods_per_year=12) if len(masi_sliced) >= 2 else {"insufficient_data": True}
    metrics["cells"]["MASI"] = {"full": masi_summary_full, "invested": masi_summary_inv}

    # --- 9. Difference tests (on the common invested window) ---
    vm_int_capped_sliced = slice_invested(results["VM_int_capped"])
    c0a_sliced = slice_invested(results["C0a"])
    m12_sliced = slice_invested(results["M12"])
    vm_mix_sliced = slice_invested(results["VM_mix"])

    diff_primary = difference_test(vm_int_capped_sliced, c0a_sliced)
    diff_m12_c0a = difference_test(m12_sliced, c0a_sliced)
    diff_vmmix_c0a = difference_test(vm_mix_sliced, c0a_sliced)
    metrics["difference_test_VM_int_capped_vs_C0a"] = diff_primary
    metrics["difference_test_M12_vs_C0a"] = diff_m12_c0a
    metrics["difference_test_VM_mix_vs_C0a"] = diff_vmmix_c0a

    # --- 10. Monthly return correlation, M12 vs C0a (common window) ---
    corr_merged = m12_sliced[["as_of_date", "net_return"]].merge(
        c0a_sliced[["as_of_date", "net_return"]], on="as_of_date", suffixes=("_m12", "_c0a")
    )
    m12_c0a_correlation = float(corr_merged["net_return_m12"].corr(corr_merged["net_return_c0a"]))
    metrics["m12_c0a_monthly_return_correlation"] = m12_c0a_correlation
    print(f"M12 vs C0a monthly return correlation (common window): {m12_c0a_correlation:.4f}")

    # --- 11. Subperiod table (VM_int_capped, C0a, M12 -- full monthly frames) ---
    sub_vm = subperiod_summary(results["VM_int_capped"])
    sub_vm["cell"] = "VM_int_capped"
    sub_c0a = subperiod_summary(results["C0a"])
    sub_c0a["cell"] = "C0a"
    sub_m12 = subperiod_summary(results["M12"])
    sub_m12["cell"] = "M12"
    subperiods = pd.concat([sub_vm, sub_c0a, sub_m12], ignore_index=True)
    subperiods.to_csv(OUT_DIR / "subperiods.csv", index=False)

    # --- 12. Turnover / breakeven cost for every cell (invested window) ---
    turnover_rows = []
    for name in cells:
        inv = metrics["cells"][name]["invested"]
        turnover_rows.append({"cell": name, "avg_turnover": inv.get("avg_turnover")})
    turnover_df = pd.DataFrame(turnover_rows)

    merged_be = vm_int_capped_sliced[["as_of_date", "gross_return", "turnover"]].merge(
        c0a_sliced[["as_of_date", "gross_return", "turnover"]], on="as_of_date", suffixes=("_VM", "_C0a")
    )
    gross_diff_mean = float((merged_be["gross_return_VM"] - merged_be["gross_return_C0a"]).mean())
    turnover_diff_mean = float((merged_be["turnover_VM"] - merged_be["turnover_C0a"]).mean())
    breakeven_bps = (gross_diff_mean / (2.0 * turnover_diff_mean) * 1e4) if turnover_diff_mean > 0 else None
    metrics["breakeven_cost_bps_VM_int_capped_vs_C0a"] = breakeven_bps
    metrics["breakeven_inputs"] = {"mean_gross_diff_monthly": gross_diff_mean, "mean_turnover_diff_monthly": turnover_diff_mean}
    if breakeven_bps is not None and breakeven_bps < 0:
        report["anomalies"].append(
            "Analytic breakeven cost for VM_int_capped vs C0a is negative "
            f"({breakeven_bps:.1f} bps) -- VM_int_capped's mean GROSS return is already "
            "below C0a's (mean_gross_diff_monthly="
            f"{gross_diff_mean:.5f}), so the underperformance is not a cost/turnover "
            "artifact; the breakeven figure is degenerate (no positive cost level makes "
            "VM_int_capped competitive on this metric)."
        )

    cost_rows = []
    for cbps, cellname in [(33.0, "VM_int_capped"), (50.0, "VM_int_capped_cost50"), (75.0, "VM_int_capped_cost75")]:
        inv = metrics["cells"][cellname]["invested"]
        cost_rows.append(
            {
                "cost_bps": cbps,
                "cagr": inv.get("cagr"),
                "sharpe": inv.get("sharpe"),
                "max_drawdown": inv.get("max_drawdown"),
                "avg_turnover": inv.get("avg_turnover"),
                "breakeven_bps_analytic": breakeven_bps,
            }
        )
    cost_df = pd.DataFrame(cost_rows)
    cost_df.to_csv(OUT_DIR / "cost_sensitivity.csv", index=False)
    turnover_df.to_csv(OUT_DIR / "turnover_by_cell.csv", index=False)

    # --- 13. Momentum candidate coverage per formation date ---
    coverage_rows = []
    for as_of, sub in panel.groupby("as_of_date"):
        n_eligible_universe = int(sub["eligible_universe"].sum())
        n_eligible_bm = int(sub["eligible_bm"].sum())
        n_mom12_notna = int((sub["eligible_universe"] & sub["momentum_12_1_raw"].notna()).sum())
        n_mom6_notna = int((sub["eligible_universe"] & sub["momentum_6_1_raw"].notna()).sum())
        coverage_rows.append(
            {
                "as_of_date": pd.Timestamp(as_of).date(),
                "n_eligible_universe": n_eligible_universe,
                "n_eligible_bm": n_eligible_bm,
                "n_momentum_12_1_notna": n_mom12_notna,
                "n_momentum_6_1_notna": n_mom6_notna,
                "pct_momentum_12_1_of_eligible_bm": (n_mom12_notna / n_eligible_bm) if n_eligible_bm else None,
            }
        )
    coverage_df = pd.DataFrame(coverage_rows).sort_values("as_of_date").reset_index(drop=True)
    coverage_df.to_csv(OUT_DIR / "coverage.csv", index=False)
    covered = coverage_df[coverage_df["n_eligible_bm"] > 0]
    coverage_summary = {
        "mean_n_eligible_bm": float(covered["n_eligible_bm"].mean()) if not covered.empty else None,
        "mean_n_momentum_12_1_notna": float(covered["n_momentum_12_1_notna"].mean()) if not covered.empty else None,
        "mean_pct_momentum_12_1_of_eligible_bm": float(covered["pct_momentum_12_1_of_eligible_bm"].mean()) if not covered.empty else None,
        "n_formation_dates": int(len(coverage_df)),
    }
    metrics["coverage_summary"] = coverage_summary
    if coverage_summary.get("mean_pct_momentum_12_1_of_eligible_bm") and coverage_summary["mean_pct_momentum_12_1_of_eligible_bm"] > 1.0:
        report["anomalies"].append(
            "mean_pct_momentum_12_1_of_eligible_bm > 1.0: momentum_12_1_raw notna is "
            "counted within eligible_universe (the broader momentum-cell universe), which "
            "is larger than eligible_bm (requires book_to_market_raw notna too) on many "
            "dates -- not a data bug, just two different eligibility denominators."
        )

    # --- 14. STAGE-A mechanism gate (on the common invested window) ---
    m12_inv = metrics["cells"]["M12"]["invested"]
    masi_inv = masi_summary_inv if isinstance(masi_summary_inv, dict) else {}
    m12_sharpe = m12_inv.get("sharpe")
    masi_sharpe = masi_inv.get("sharpe")
    m12_ir = m12_inv.get("information_ratio")
    stage_a_crit_sharpe = m12_sharpe is not None and masi_sharpe is not None and float(m12_sharpe) >= float(masi_sharpe)
    stage_a_crit_ir = m12_ir is not None and float(m12_ir) > 0
    stage_a_pass = bool(stage_a_crit_sharpe and stage_a_crit_ir)
    stage_a = {
        "pass": stage_a_pass,
        "criteria": {
            "i_m12_sharpe_ge_masi_sharpe": {"pass": stage_a_crit_sharpe, "m12_sharpe": m12_sharpe, "masi_sharpe": masi_sharpe},
            "ii_m12_information_ratio_gt_0": {"pass": stage_a_crit_ir, "m12_information_ratio": m12_ir},
        },
    }
    metrics["stage_a_gate"] = stage_a
    print(f"\nSTAGE-A GATE: {'PASS' if stage_a_pass else 'FAIL'}")
    print(json.dumps(stage_a, indent=2, default=str))

    # --- 15. STAGE-B acceptance (primary = VM_int_capped vs C0a; fixed-sign crit_p) ---
    vm_int_capped_inv = metrics["cells"]["VM_int_capped"]["invested"]
    c0a_inv = metrics["cells"]["C0a"]["invested"]
    stage_b_acceptance = evaluate_acceptance(
        vm_int_capped_inv, c0a_inv, diff_primary, masi_sharpe=masi_sharpe, dd_tolerance=DD_TOLERANCE, p_threshold=P_THRESHOLD
    )
    metrics["stage_b_acceptance"] = stage_b_acceptance

    if stage_a_pass:
        overall_verdict = stage_b_acceptance["verdict"]
        stage_b_status = "CONFIRMED (Stage A passed)"
    else:
        overall_verdict = "C (mechanism absent)"
        stage_b_status = "EXPLORATORY ONLY (Stage A failed -- not promotable regardless of numbers)"
    print(f"\nSTAGE-B acceptance verdict (raw): {stage_b_acceptance['verdict']} -- status: {stage_b_status}")
    print(f"OVERALL VERDICT: {overall_verdict}")

    # --- 16. Sanity check: C0a full-frame summary vs prior study's C0a ---
    sanity_result: dict = {"pass": False, "fields": {}, "note": None}
    if not PRIOR_STUDY_METRICS.exists():
        sanity_result["note"] = f"{PRIOR_STUDY_METRICS} not found -- sanity check could not run."
        report["anomalies"].append(sanity_result["note"])
    else:
        prior_metrics = json.loads(PRIOR_STUDY_METRICS.read_text(encoding="utf-8"))
        prior_c0a_full = prior_metrics.get("cells", {}).get("C0a", {}).get("full", {})
        c0a_full = metrics["cells"]["C0a"]["full"]
        sanity_pass = True
        for field in ("cumulative_return", "sharpe", "max_drawdown", "periods", "cagr"):
            a = c0a_full.get(field)
            b = prior_c0a_full.get(field)
            ok = _rel_close(a, b) if isinstance(a, float) or isinstance(b, float) else (a == b)
            sanity_pass = sanity_pass and ok
            sanity_result["fields"][field] = {"this_run_C0a": a, "prior_study_C0a": b, "pass": ok}
        sanity_result["pass"] = sanity_pass
        sanity_result["prior_study_metrics_path"] = str(PRIOR_STUDY_METRICS)
    metrics["c0a_sanity_check"] = sanity_result
    print("\nC0a SANITY CHECK (vs prior combined-portfolio-strategy study):", "PASS" if sanity_result["pass"] else "FAIL")
    for field, v in sanity_result.get("fields", {}).items():
        print(f"  {field}: this_run={v['this_run_C0a']!r} prior_study={v['prior_study_C0a']!r} pass={v['pass']}")
    if sanity_result["note"]:
        print(f"  note: {sanity_result['note']}")
    if not sanity_result["pass"] and sanity_result["note"] is None:
        report["anomalies"].append("C0a SANITY CHECK FAILED -- same panel/engine as the prior study should reproduce exactly.")

    # --- 17. Artifacts ---
    report["run_metadata"].update(
        {
            "timestamp_utc": OUT_DIR.name,
            "panel_path": str(PANEL_PATH),
            "common_invested_window": [str(common_start), str(common_end)],
            "sector_cap": SECTOR_CAP,
            "max_name_weight": MAX_NAME_WEIGHT,
            "cost_bps_primary": COST_BPS_PRIMARY,
            "dd_tolerance": DD_TOLERANCE,
            "p_threshold": P_THRESHOLD,
        }
    )

    metrics_out = {**report, **metrics}
    (OUT_DIR / "metrics.json").write_text(json.dumps(metrics_out, indent=2, default=str), encoding="utf-8")
    verdict_json = {
        "overall_verdict": overall_verdict,
        "stage_a_gate": stage_a,
        "stage_b_acceptance": stage_b_acceptance,
        "stage_b_status": stage_b_status,
        "c0a_sanity_check": sanity_result,
        "m12_c0a_monthly_return_correlation": m12_c0a_correlation,
        "breakeven_cost_bps_VM_int_capped_vs_C0a": breakeven_bps,
        "coverage_summary": coverage_summary,
        "anomalies": report["anomalies"],
    }
    (OUT_DIR / "verdict.json").write_text(json.dumps(verdict_json, indent=2, default=str), encoding="utf-8")

    verdict_md = _render_verdict_md(
        report=report,
        metrics=metrics,
        cost_df=cost_df,
        turnover_df=turnover_df,
        coverage_summary=coverage_summary,
        stage_a=stage_a,
        stage_b_acceptance=stage_b_acceptance,
        stage_b_status=stage_b_status,
        overall_verdict=overall_verdict,
        sanity_result=sanity_result,
        m12_c0a_correlation=m12_c0a_correlation,
        breakeven_bps=breakeven_bps,
        common_start=common_start,
        common_end=common_end,
    )
    (OUT_DIR / "verdict.md").write_text(verdict_md, encoding="utf-8")

    print(f"\nWritten to {OUT_DIR}")
    print(f"OVERALL VERDICT: {overall_verdict}")


def _render_verdict_md(
    *,
    report: dict,
    metrics: dict,
    cost_df: pd.DataFrame,
    turnover_df: pd.DataFrame,
    coverage_summary: dict,
    stage_a: dict,
    stage_b_acceptance: dict,
    stage_b_status: str,
    overall_verdict: str,
    sanity_result: dict,
    m12_c0a_correlation: float,
    breakeven_bps: float | None,
    common_start,
    common_end,
) -> str:
    lines: list[str] = []
    lines.append("# Value + Momentum Study -- Verdict Report")
    lines.append("")
    lines.append(f"Run timestamp (UTC): {report['run_metadata']['timestamp_utc']}")
    lines.append(f"Panel: {report['run_metadata']['panel_path']}")
    lines.append(f"Common invested window: {common_start} .. {common_end}")
    lines.append("")
    lines.append("## Config echo")
    lines.append("")
    for k, v in report["run_metadata"].items():
        lines.append(f"- `{k}`: {v}")
    lines.append("")

    lines.append("## Headline metrics -- ALL cells (invested window)")
    lines.append("")
    lines.append("| Cell | CAGR | Sharpe | MaxDD | HitRate | AvgTurnover | IR vs MASI |")
    lines.append("|---|---|---|---|---|---|---|")
    for name, block in metrics["cells"].items():
        inv = block["invested"]
        if inv.get("insufficient_data"):
            lines.append(f"| {name} | n/a | n/a | n/a | n/a | n/a | n/a |")
            continue
        cagr = inv.get("cagr")
        sharpe = inv.get("sharpe")
        dd = inv.get("max_drawdown")
        hit = inv.get("hit_rate")
        turn = inv.get("avg_turnover")
        ir = inv.get("information_ratio")
        cagr_s = "n/a" if cagr is None else f"{cagr:.4f}"
        lines.append(
            f"| {name} | {cagr_s} | {sharpe:.3f} | {dd:.4f} | {hit:.3f} | {turn:.4f} | "
            f"{ir if ir is None else round(ir, 3)} |"
        )
    lines.append("")

    lines.append("## STAGE-A mechanism gate (M12 vs MASI, common window)")
    lines.append("")
    lines.append(f"**Stage A: {'PASS' if stage_a['pass'] else 'FAIL'}**")
    lines.append("")
    for key, crit in stage_a["criteria"].items():
        status = "PASS" if crit["pass"] else "FAIL"
        lines.append(f"- `{key}`: {status} -- {crit}")
    lines.append("")
    if not stage_a["pass"]:
        lines.append(
            "Stage A FAILED -- per pre-registration, the study verdict is automatically "
            "\"C (mechanism absent)\" and all Stage-B numbers below are EXPLORATORY ONLY."
        )
        lines.append("")

    lines.append("## STAGE-B acceptance (primary = VM_int_capped vs incumbent C0a)")
    lines.append("")
    lines.append(f"Status: **{stage_b_status}**")
    lines.append(f"Raw Stage-B verdict: {stage_b_acceptance['verdict']}")
    lines.append("")
    for key, crit in stage_b_acceptance["criteria"].items():
        status = "PASS" if crit["pass"] else "FAIL"
        lines.append(f"- `{key}`: {status} -- {crit}")
    lines.append("")
    lines.append(f"Difference test (VM_int_capped - C0a): {stage_b_acceptance['difference_test']}")
    lines.append("")
    lines.append(f"## OVERALL VERDICT: {overall_verdict}")
    lines.append("")

    lines.append("## Monthly return correlation, M12 vs C0a (common window)")
    lines.append("")
    lines.append(f"correlation = {m12_c0a_correlation:.4f}")
    lines.append("")

    lines.append("## Momentum candidate coverage")
    lines.append("")
    for k, v in coverage_summary.items():
        lines.append(f"- `{k}`: {v}")
    lines.append("")

    lines.append("## Turnover by cell (invested window)")
    lines.append("")
    try:
        lines.append(turnover_df.to_markdown(index=False))
    except ImportError:
        lines.append(turnover_df.to_string(index=False))
    lines.append("")

    lines.append("## Cost sensitivity (VM_int_capped)")
    lines.append("")
    try:
        lines.append(cost_df.to_markdown(index=False))
    except ImportError:
        lines.append(cost_df.to_string(index=False))
    lines.append("")
    lines.append(f"Analytic breakeven cost (bps), VM_int_capped vs C0a: {breakeven_bps}")
    lines.append("")

    lines.append("## C0a sanity check (this run's full-frame C0a vs the prior combined-portfolio-strategy study's C0a)")
    lines.append("")
    lines.append(f"Result: {'PASS' if sanity_result['pass'] else 'FAIL'}")
    for field, v in sanity_result.get("fields", {}).items():
        lines.append(f"- {field}: this_run={v['this_run_C0a']} prior_study={v['prior_study_C0a']} pass={v['pass']}")
    if sanity_result.get("note"):
        lines.append(f"- note: {sanity_result['note']}")
    lines.append("")

    if report["anomalies"]:
        lines.append("## Anomalies / deviations")
        lines.append("")
        for a in report["anomalies"]:
            lines.append(f"- {a}")
        lines.append("")

    lines.append("## Analysis (orchestrator)")
    lines.append("")
    lines.append("_Placeholder -- final prose verdict analysis is written by the orchestrator, not this script._")
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    main()
