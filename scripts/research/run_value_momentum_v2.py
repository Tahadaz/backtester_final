"""Driver for the pre-registered CONFIRMATION study (v2) of the value+momentum
research (research-out/value-momentum-study/PREREGISTRATION_v2.md, 2026-07-12).

v2 is a targeted variation of `run_value_momentum_study.py` (v1): same panel
CSV, same price loader, same MASI benchmark alignment, same common-invested-
window / artifact conventions -- but the PRIMARY cell now uses the new
`build_graceful_composite_holdings` engine (universe = eligible_bm only,
momentum imputed at neutral 0.5 when missing) instead of v1's hard
intersection (`build_rank_composite_holdings`), and promotion requires ALL
SEVEN pre-registered gates (a)-(g), not just the four-criterion
`evaluate_acceptance` verdict.

Read-only: no writes to the DB. All I/O side effects are local CSV/JSON files
under research-out/value-momentum-study/v2-<UTC ts>/.
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
    build_graceful_composite_holdings,
    difference_test,
    evaluate_acceptance,
    run_gated_vintage_backtest,
    subperiod_summary,
    summarize_performance,
)
from core.quant_core.fundamentals.cross_section.live_like_strategy import (  # noqa: E402
    LiveLikeConfig,
    build_vintage_holdings_by_date,
    eligibility_mask,
)
from core.quant_core.fundamentals.cross_section.portfolio_backtest import _pit_price  # noqa: E402

PANEL_PATH = Path(
    "research-out/data-quality-forensic-repair/2026-07-06/characteristic-study-after-repair/"
    "20260706-194324/panel_characteristics.csv"
)
OUT_DIR = Path("research-out/value-momentum-study") / (
    "v2-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
)
V1_METRICS_PATH = Path("research-out/value-momentum-study/20260712-172056/metrics.json")

SECTOR_CAP = 0.30
COST_BPS_PRIMARY = 33.0
COST_BPS_ROBUST = 75.0
DD_TOLERANCE = 0.02
P_THRESHOLD = 0.10
PRIMARY_WEIGHTS = (0.7, 0.3)  # (value, momentum) -- the v1 sensitivity-cell winner; no further tuning in v2
SECONDARY_WEIGHTS_5050 = (0.5, 0.5)
MOMENTUM_COL = "momentum_12_1_raw"
VALUE_COL = "book_to_market_raw"
ELIGIBILITY_COL = "eligible_bm"


def _rel_close(a: float | None, b: float | None, tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    if b == 0:
        return abs(a - b) <= tol
    return abs(a - b) / abs(b) <= tol


def _common_invested_window(monthly_a: pd.DataFrame, monthly_b: pd.DataFrame, label_a: str, label_b: str):
    merged = monthly_a[["as_of_date", "n_holdings"]].merge(
        monthly_b[["as_of_date", "n_holdings"]], on="as_of_date", suffixes=(f"_{label_a}", f"_{label_b}")
    )
    both_invested = merged[(merged[f"n_holdings_{label_a}"] > 0) & (merged[f"n_holdings_{label_b}"] > 0)]
    if both_invested.empty:
        raise SystemExit(f"ABORT: no date where both {label_a} and {label_b} hold names.")
    start = both_invested["as_of_date"].iloc[0]
    end = monthly_a["as_of_date"].iloc[-1]
    return start, end


def _momentum_coverage(panel: pd.DataFrame, holdings_by_date: dict) -> pd.DataFrame:
    panel_idx = panel.copy()
    panel_idx["symbol_u"] = panel_idx["symbol"].astype(str).str.strip().str.upper()
    rows = []
    for as_of in sorted(holdings_by_date):
        holdings = holdings_by_date[as_of]
        if not holdings:
            rows.append({"as_of_date": as_of, "n_names": 0, "n_momentum_real": 0, "frac_momentum_real": None})
            continue
        sub = panel_idx[panel_idx["as_of_date"] == as_of]
        lookup = sub.drop_duplicates(subset="symbol_u").set_index("symbol_u")[MOMENTUM_COL]
        symbols = list(holdings.keys())
        n_real = sum(1 for s in symbols if s in lookup.index and pd.notna(lookup.loc[s]))
        rows.append(
            {
                "as_of_date": as_of,
                "n_names": len(symbols),
                "n_momentum_real": n_real,
                "frac_momentum_real": n_real / len(symbols) if symbols else None,
            }
        )
    return pd.DataFrame(rows)


def _cum_return(monthly: pd.DataFrame) -> float:
    r = pd.to_numeric(monthly["net_return"], errors="coerce").dropna()
    if r.empty:
        return float("nan")
    return float((1.0 + r).prod() - 1.0)


def _split_half(monthly: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    sorted_m = monthly.sort_values("as_of_date").reset_index(drop=True)
    n = len(sorted_m)
    first_n = n - n // 2  # ceil-first: 51 -> 26/25
    return sorted_m.iloc[:first_n], sorted_m.iloc[first_n:]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report: dict = {"run_metadata": {}, "anomalies": []}

    # --- 1. Panel (same route as v1) ---
    if not PANEL_PATH.exists():
        raise SystemExit(f"ABORT: panel CSV not found at {PANEL_PATH} -- cannot proceed.")
    panel = pd.read_csv(PANEL_PATH)
    panel["as_of_date"] = pd.to_datetime(panel["as_of_date"]).dt.date
    panel = eligibility_mask(panel)
    print(f"Loaded panel: {PANEL_PATH} ({len(panel)} rows, {panel['symbol'].nunique()} symbols)")

    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)

    # --- 2. Sector map (same query as v1) ---
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

    # --- 3. Prices / MASI benchmark (same route as v1) ---
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
    overlay_cfg = CombinedConfig(sector_cap=SECTOR_CAP, max_name_weight=None, adv_floor_mad=None)

    c0a_holdings = build_vintage_holdings_by_date(panel, strategy="S1_bm", config=base_cfg)

    vm2_raw_holdings = build_graceful_composite_holdings(
        panel,
        primary=(VALUE_COL, PRIMARY_WEIGHTS[0]),
        secondary=(MOMENTUM_COL, PRIMARY_WEIGHTS[1]),
        eligibility_col=ELIGIBILITY_COL,
        config=base_cfg,
    )
    vm2_capped_holdings = apply_overlays_to_holdings(
        vm2_raw_holdings, sector_map=sector_map, config=overlay_cfg, adv_series_by_symbol=None
    )

    vm2_5050_raw_holdings = build_graceful_composite_holdings(
        panel,
        primary=(VALUE_COL, SECONDARY_WEIGHTS_5050[0]),
        secondary=(MOMENTUM_COL, SECONDARY_WEIGHTS_5050[1]),
        eligibility_col=ELIGIBILITY_COL,
        config=base_cfg,
    )
    vm2_5050_capped_holdings = apply_overlays_to_holdings(
        vm2_5050_raw_holdings, sector_map=sector_map, config=overlay_cfg, adv_series_by_symbol=None
    )

    print(
        f"Holdings formed: C0a={len(c0a_holdings)} VM2_raw={len(vm2_raw_holdings)} "
        f"VM2_capped={len(vm2_capped_holdings)} VM2_5050_capped={len(vm2_5050_capped_holdings)} dates"
    )

    # --- 5. Run cells (G0 mode) ---
    cells: dict[str, dict] = {
        "C0a": dict(holdings=c0a_holdings, cost=COST_BPS_PRIMARY),
        "VM2": dict(holdings=vm2_capped_holdings, cost=COST_BPS_PRIMARY),  # PRIMARY
        "VM2_uncapped": dict(holdings=vm2_raw_holdings, cost=COST_BPS_PRIMARY),
        "VM2_5050": dict(holdings=vm2_5050_capped_holdings, cost=COST_BPS_PRIMARY),
        "VM2_cost50": dict(holdings=vm2_capped_holdings, cost=50.0),
        "VM2_cost75": dict(holdings=vm2_capped_holdings, cost=COST_BPS_ROBUST),
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

    # --- 7. Common invested window: first date where BOTH C0a and VM2 (primary)
    #     have n_holdings > 0, through the last panel date. ---
    c0a_monthly = results["C0a"]
    vm2_monthly = results["VM2"]
    common_start, common_end = _common_invested_window(c0a_monthly, vm2_monthly, "c0a", "vm2")
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

    masi_sharpe_inv = masi_summary_inv.get("sharpe") if isinstance(masi_summary_inv, dict) else None

    # --- 9. Difference test (primary VM2 vs C0a, common invested window) ---
    vm2_sliced = slice_invested(results["VM2"])
    c0a_sliced = slice_invested(results["C0a"])
    diff_primary = difference_test(vm2_sliced, c0a_sliced)
    metrics["difference_test_VM2_vs_C0a"] = diff_primary

    vm2_inv = metrics["cells"]["VM2"]["invested"]
    c0a_inv = metrics["cells"]["C0a"]["invested"]

    # --- 10. Gates (a)-(d) via evaluate_acceptance (criteria map 1:1 onto the
    #     pre-registered promotion bar). ---
    acceptance = evaluate_acceptance(
        vm2_inv, c0a_inv, diff_primary, masi_sharpe=masi_sharpe_inv, dd_tolerance=DD_TOLERANCE, p_threshold=P_THRESHOLD
    )
    gate_a = acceptance["criteria"]["a_sharpe_ge_incumbent"]
    gate_b = acceptance["criteria"]["b_drawdown_tolerance"]
    gate_c = acceptance["criteria"]["c_difference_pvalue"]
    gate_d = acceptance["criteria"]["d_sharpe_ge_masi"]

    # --- 11. Gate (e): split-half consistency ---
    vm2_h1, vm2_h2 = _split_half(vm2_sliced)
    c0a_h1, c0a_h2 = _split_half(c0a_sliced)
    vm2_h1_cum, vm2_h2_cum = _cum_return(vm2_h1), _cum_return(vm2_h2)
    c0a_h1_cum, c0a_h2_cum = _cum_return(c0a_h1), _cum_return(c0a_h2)
    gate_e_pass = bool(vm2_h1_cum >= c0a_h1_cum and vm2_h2_cum >= c0a_h2_cum)
    gate_e = {
        "pass": gate_e_pass,
        "half1": {"months": len(vm2_h1), "vm2_cum_return": vm2_h1_cum, "c0a_cum_return": c0a_h1_cum, "pass": bool(vm2_h1_cum >= c0a_h1_cum)},
        "half2": {"months": len(vm2_h2), "vm2_cum_return": vm2_h2_cum, "c0a_cum_return": c0a_h2_cum, "pass": bool(vm2_h2_cum >= c0a_h2_cum)},
    }

    # --- 12. Gate (f): cost robustness (VM2 @ 75bps vs C0a @ 33bps) ---
    vm2_cost75_inv = metrics["cells"]["VM2_cost75"]["invested"]
    c0a_sharpe = c0a_inv.get("sharpe")
    vm2_cost75_sharpe = vm2_cost75_inv.get("sharpe")
    gate_f_pass = (
        vm2_cost75_sharpe is not None and c0a_sharpe is not None and float(vm2_cost75_sharpe) >= float(c0a_sharpe)
    )
    gate_f = {"pass": bool(gate_f_pass), "vm2_cost75_sharpe": vm2_cost75_sharpe, "c0a_cost33_sharpe": c0a_sharpe}

    # --- 13. Gate (g): drop-the-winner ---
    vm2_dates_in_window = [d for d in vm2_capped_holdings if common_start <= d <= common_end]
    ever_held: set[str] = set()
    for d in vm2_dates_in_window:
        ever_held.update(vm2_capped_holdings[d].keys())

    winner_sym = None
    winner_ret = None
    candidate_returns: dict[str, float] = {}
    for sym in sorted(ever_held):
        series = close_by_symbol.get(sym)
        p0, p0_date = _pit_price(series, common_start)
        p1, p1_date = _pit_price(series, common_end)
        if p0 is None or p1 is None or p0 == 0:
            continue
        ret = float(p1 / p0 - 1.0)
        candidate_returns[sym] = ret
        if winner_ret is None or ret > winner_ret:
            winner_ret = ret
            winner_sym = sym

    gate_g: dict = {"pass": False, "winner_symbol": winner_sym, "winner_total_return": winner_ret}
    if winner_sym is None:
        report["anomalies"].append("Drop-the-winner: no ever-held VM2 symbol had resolvable PIT prices at both window endpoints -- gate (g) cannot run, treated as FAIL.")
    else:
        winner_u = winner_sym.strip().upper()
        panel_ex = panel[panel["symbol"].astype(str).str.strip().str.upper() != winner_u].copy()
        c0a_holdings_ex = build_vintage_holdings_by_date(panel_ex, strategy="S1_bm", config=base_cfg)
        vm2_raw_holdings_ex = build_graceful_composite_holdings(
            panel_ex,
            primary=(VALUE_COL, PRIMARY_WEIGHTS[0]),
            secondary=(MOMENTUM_COL, PRIMARY_WEIGHTS[1]),
            eligibility_col=ELIGIBILITY_COL,
            config=base_cfg,
        )
        vm2_holdings_ex = apply_overlays_to_holdings(
            vm2_raw_holdings_ex, sector_map=sector_map, config=overlay_cfg, adv_series_by_symbol=None
        )
        ex_config = CombinedConfig(base=LiveLikeConfig(cost_bps=COST_BPS_PRIMARY), gate="G0")
        c0a_monthly_ex, _ = run_gated_vintage_backtest(
            c0a_holdings_ex, price_by_symbol=close_by_symbol, gate_by_symbol=None, config=ex_config
        )
        vm2_monthly_ex, _ = run_gated_vintage_backtest(
            vm2_holdings_ex, price_by_symbol=close_by_symbol, gate_by_symbol=None, config=ex_config
        )
        c0a_monthly_ex.to_csv(OUT_DIR / "monthly_returns_C0a_ex_dropwinner.csv", index=False)
        vm2_monthly_ex.to_csv(OUT_DIR / "monthly_returns_VM2_ex_dropwinner.csv", index=False)

        ex_start, ex_end = _common_invested_window(c0a_monthly_ex, vm2_monthly_ex, "c0a_ex", "vm2_ex")

        def slice_ex(df: pd.DataFrame) -> pd.DataFrame:
            return df[(df["as_of_date"] >= ex_start) & (df["as_of_date"] <= ex_end)].reset_index(drop=True)

        c0a_ex_summary = summarize_performance(slice_ex(c0a_monthly_ex), periods_per_year=12)
        vm2_ex_summary = summarize_performance(slice_ex(vm2_monthly_ex), periods_per_year=12)
        gate_g_pass = bool(
            vm2_ex_summary.get("sharpe") is not None
            and c0a_ex_summary.get("sharpe") is not None
            and float(vm2_ex_summary["sharpe"]) >= float(c0a_ex_summary["sharpe"])
        )
        gate_g = {
            "pass": gate_g_pass,
            "winner_symbol": winner_sym,
            "winner_total_return": winner_ret,
            "ex_common_invested_window": [str(ex_start), str(ex_end)],
            "vm2_ex_sharpe": vm2_ex_summary.get("sharpe"),
            "c0a_ex_sharpe": c0a_ex_summary.get("sharpe"),
            "candidate_returns_all_ever_held": candidate_returns,
        }

    # --- 14. Overall promotion verdict ---
    all_gates = {
        "a_sharpe_ge_incumbent": gate_a,
        "b_drawdown_tolerance": gate_b,
        "c_difference_pvalue": gate_c,
        "d_sharpe_ge_masi": gate_d,
        "e_split_half_consistency": gate_e,
        "f_cost_robustness_75bps": gate_f,
        "g_drop_the_winner": gate_g,
    }
    promoted = all(g["pass"] for g in all_gates.values())
    overall_verdict = "PROMOTED" if promoted else "NOT PROMOTED (value-only C0a stands)"
    print(f"\nGATES: {json.dumps({k: v['pass'] for k, v in all_gates.items()}, indent=2)}")
    print(f"OVERALL VERDICT: {overall_verdict}")

    # --- 15. Informational: active-return correlation, subperiods, turnover, coverage ---
    active_merge = vm2_sliced[["as_of_date", "net_return"]].merge(
        c0a_sliced[["as_of_date", "net_return"]], on="as_of_date", suffixes=("_vm2", "_c0a")
    )
    masi_lookup = masi_sliced.reindex(active_merge["as_of_date"])
    active_vm2 = active_merge["net_return_vm2"].to_numpy() - masi_lookup.to_numpy()
    active_c0a = active_merge["net_return_c0a"].to_numpy() - masi_lookup.to_numpy()
    active_return_correlation = float(pd.Series(active_vm2).corr(pd.Series(active_c0a)))
    metrics["active_return_correlation_VM2_vs_C0a"] = active_return_correlation
    print(f"Active-return correlation (VM2-MASI vs C0a-MASI, common window): {active_return_correlation:.4f}")

    sub_vm2 = subperiod_summary(results["VM2"]); sub_vm2["cell"] = "VM2"
    sub_c0a = subperiod_summary(results["C0a"]); sub_c0a["cell"] = "C0a"
    sub_vm2u = subperiod_summary(results["VM2_uncapped"]); sub_vm2u["cell"] = "VM2_uncapped"
    subperiods = pd.concat([sub_vm2, sub_c0a, sub_vm2u], ignore_index=True)
    subperiods.to_csv(OUT_DIR / "subperiods.csv", index=False)

    turnover_rows = []
    for name in cells:
        inv = metrics["cells"][name]["invested"]
        turnover_rows.append({"cell": name, "avg_turnover": inv.get("avg_turnover")})
    turnover_df = pd.DataFrame(turnover_rows)
    turnover_df.to_csv(OUT_DIR / "turnover_by_cell.csv", index=False)

    cost_rows = []
    for cbps, cellname in [(33.0, "VM2"), (50.0, "VM2_cost50"), (75.0, "VM2_cost75")]:
        inv = metrics["cells"][cellname]["invested"]
        cost_rows.append(
            {
                "cost_bps": cbps,
                "cagr": inv.get("cagr"),
                "sharpe": inv.get("sharpe"),
                "max_drawdown": inv.get("max_drawdown"),
                "avg_turnover": inv.get("avg_turnover"),
            }
        )
    cost_df = pd.DataFrame(cost_rows)
    cost_df.to_csv(OUT_DIR / "cost_sensitivity.csv", index=False)

    coverage_df = _momentum_coverage(panel, vm2_capped_holdings)
    coverage_df.to_csv(OUT_DIR / "coverage.csv", index=False)
    covered = coverage_df[coverage_df["n_names"] > 0]
    coverage_mean = float(covered["frac_momentum_real"].mean()) if not covered.empty else None
    metrics["momentum_real_coverage_mean"] = coverage_mean
    print(f"Mean momentum-real coverage of VM2 selected names: {coverage_mean}")

    # --- 16. Sanity check: this run's C0a full-frame vs v1's C0a full-frame
    #     (same panel/engine -- must reproduce exactly). ---
    sanity_result: dict = {"pass": False, "fields": {}, "note": None}
    if not V1_METRICS_PATH.exists():
        sanity_result["note"] = f"{V1_METRICS_PATH} not found -- sanity check could not run."
        report["anomalies"].append(sanity_result["note"])
    else:
        v1_metrics = json.loads(V1_METRICS_PATH.read_text(encoding="utf-8"))
        v1_c0a_full = v1_metrics.get("cells", {}).get("C0a", {}).get("full", {})
        c0a_full = metrics["cells"]["C0a"]["full"]
        sanity_pass = True
        for field in ("cumulative_return", "sharpe", "max_drawdown", "periods", "cagr"):
            a = c0a_full.get(field)
            b = v1_c0a_full.get(field)
            ok = _rel_close(a, b) if isinstance(a, float) or isinstance(b, float) else (a == b)
            sanity_pass = sanity_pass and ok
            sanity_result["fields"][field] = {"this_run_C0a": a, "v1_C0a": b, "pass": ok}
        sanity_result["pass"] = sanity_pass
        sanity_result["v1_metrics_path"] = str(V1_METRICS_PATH)
    metrics["c0a_sanity_check"] = sanity_result
    print("\nC0a SANITY CHECK (vs v1 study C0a):", "PASS" if sanity_result["pass"] else "FAIL")
    if not sanity_result["pass"] and sanity_result["note"] is None:
        report["anomalies"].append("C0a SANITY CHECK FAILED -- same panel/engine as v1 should reproduce exactly.")

    # --- 17. Artifacts ---
    report["run_metadata"].update(
        {
            "timestamp_utc": OUT_DIR.name,
            "panel_path": str(PANEL_PATH),
            "common_invested_window": [str(common_start), str(common_end)],
            "sector_cap": SECTOR_CAP,
            "max_name_weight": None,
            "cost_bps_primary": COST_BPS_PRIMARY,
            "cost_bps_robust": COST_BPS_ROBUST,
            "dd_tolerance": DD_TOLERANCE,
            "p_threshold": P_THRESHOLD,
            "primary_weights_value_momentum": PRIMARY_WEIGHTS,
        }
    )

    metrics_out = {**report, **metrics}
    (OUT_DIR / "metrics.json").write_text(json.dumps(metrics_out, indent=2, default=str), encoding="utf-8")

    verdict_json = {
        "overall_verdict": overall_verdict,
        "promoted": promoted,
        "gates": all_gates,
        "acceptance_raw": acceptance,
        "c0a_sanity_check": sanity_result,
        "active_return_correlation_VM2_vs_C0a": active_return_correlation,
        "momentum_real_coverage_mean": coverage_mean,
        "anomalies": report["anomalies"],
    }
    (OUT_DIR / "verdict.json").write_text(json.dumps(verdict_json, indent=2, default=str), encoding="utf-8")

    verdict_md = _render_verdict_md(
        report=report,
        metrics=metrics,
        cost_df=cost_df,
        turnover_df=turnover_df,
        all_gates=all_gates,
        promoted=promoted,
        overall_verdict=overall_verdict,
        sanity_result=sanity_result,
        active_return_correlation=active_return_correlation,
        coverage_mean=coverage_mean,
        common_start=common_start,
        common_end=common_end,
        acceptance=acceptance,
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
    all_gates: dict,
    promoted: bool,
    overall_verdict: str,
    sanity_result: dict,
    active_return_correlation: float,
    coverage_mean: float | None,
    common_start,
    common_end,
    acceptance: dict,
) -> str:
    lines: list[str] = []
    lines.append("# Value + Momentum CONFIRMATION Study v2 -- Verdict Report")
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

    lines.append("## PROMOTION BAR -- gates (a)-(g)")
    lines.append("")
    lines.append(f"**OVERALL: {overall_verdict}**")
    lines.append("")
    for key, gate in all_gates.items():
        status = "PASS" if gate["pass"] else "FAIL"
        lines.append(f"- `{key}`: {status} -- {gate}")
    lines.append("")
    lines.append(f"Difference test (VM2 - C0a): {metrics['difference_test_VM2_vs_C0a']}")
    lines.append("")
    lines.append(f"Raw evaluate_acceptance verdict (a-d only, informational): {acceptance['verdict']}")
    lines.append("")

    lines.append("## Active-return correlation (VM2-MASI vs C0a-MASI, common window)")
    lines.append("")
    lines.append(f"correlation = {active_return_correlation:.4f}")
    lines.append("")

    lines.append("## Momentum-real coverage of VM2 selected names")
    lines.append("")
    lines.append(f"mean fraction of composite weight where momentum was REAL (not imputed): {coverage_mean}")
    lines.append("")

    lines.append("## Turnover by cell (invested window)")
    lines.append("")
    try:
        lines.append(turnover_df.to_markdown(index=False))
    except ImportError:
        lines.append(turnover_df.to_string(index=False))
    lines.append("")

    lines.append("## Cost sensitivity (VM2)")
    lines.append("")
    try:
        lines.append(cost_df.to_markdown(index=False))
    except ImportError:
        lines.append(cost_df.to_string(index=False))
    lines.append("")

    lines.append("## C0a sanity check (this run's full-frame C0a vs v1's C0a)")
    lines.append("")
    lines.append(f"Result: {'PASS' if sanity_result['pass'] else 'FAIL'}")
    for field, v in sanity_result.get("fields", {}).items():
        lines.append(f"- {field}: this_run={v['this_run_C0a']} v1={v['v1_C0a']} pass={v['pass']}")
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
