"""Driver for the combined value x technical gated-vintage strategy (Stage 1
research, 2026-07-12 plan). Runs the pre-registered variant grid defined in
`core/quant_core/fundamentals/cross_section/combined_strategy.py` against the
dev stack and writes verdict artifacts.

Deliberate deviation from the plan's `_load_panel` route: this runner loads
the SAME repaired panel CSV + `eligibility_mask` as the incumbent
`scripts/run_live_like_value_strategy.py` (rather than
`methodology_bakeoff._load_panel`) so the C0a parity check against the
incumbent run is apples-to-apples. See the parity check at the end of `main`.

Read-only: no writes to the DB. All I/O side effects are local CSV/JSON files
under research-out/combined-portfolio-strategy/<UTC ts>/.
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
    aggregate_wfo_gate,
    apply_overlays_to_holdings,
    build_trend_gate_series,
    compute_pit_adv_series,
    difference_test,
    evaluate_acceptance,
    pit_value,
    run_gated_vintage_backtest,
    subperiod_summary,
    summarize_performance,
)
from core.quant_core.fundamentals.cross_section.live_like_strategy import (  # noqa: E402
    LiveLikeConfig,
    build_vintage_holdings_by_date,
    eligibility_mask,
)

PANEL_PATH = Path(
    "research-out/data-quality-forensic-repair/2026-07-06/characteristic-study-after-repair/"
    "20260706-194324/panel_characteristics.csv"
)
OUT_DIR = Path("research-out/combined-portfolio-strategy") / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
LIVE_LIKE_DIR = Path("research-out/live-like-value-strategy")

EXPECTED_G2_SOURCE = "wfo:expanded_ta_simple"
G2_CATEGORIES = ("tendance", "momentum", "oscillation", "volume")
G2_MAX_STALENESS_DAYS = 45
SECTOR_CAP = 0.30
MAX_NAME_WEIGHT = 0.10


def _rel_close(a: float | None, b: float | None, tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    if b == 0:
        return abs(a - b) <= tol
    return abs(a - b) / abs(b) <= tol


def _g2_defined_nonstale(series: pd.Series | None, as_of: dt.date, max_days: int = G2_MAX_STALENESS_DAYS) -> bool:
    """Mirrors combined_strategy._gate_lookup's definedness+staleness check
    without requiring the True/False stance -- used for the coverage report."""
    if series is None:
        return False
    defined = series.dropna()
    if defined.empty:
        return False
    ts = pd.Timestamp(as_of)
    idx = defined.index.searchsorted(ts, side="right") - 1
    if idx < 0:
        return False
    return (ts - defined.index[idx]).days <= max_days


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report: dict = {"run_metadata": {}, "anomalies": []}

    # --- 1. Panel (same route as the incumbent runner, deliberate deviation
    #     from the plan's methodology_bakeoff._load_panel route -- see docstring) ---
    if not PANEL_PATH.exists():
        raise SystemExit(f"ABORT: panel CSV not found at {PANEL_PATH} -- cannot proceed.")
    panel = pd.read_csv(PANEL_PATH)
    panel["as_of_date"] = pd.to_datetime(panel["as_of_date"]).dt.date
    panel = eligibility_mask(panel)
    print(f"Loaded panel: {PANEL_PATH} ({len(panel)} rows, {panel['symbol'].nunique()} symbols)")

    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)

    # --- 2. Sector map ---
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

    # --- 3. Prices / ADV ---
    print("Loading full daily price series...")
    price_frames = _full_price_loader()
    close_by_symbol = {sym: (df["Close"] if "Close" in df.columns else None) for sym, df in price_frames.items()}
    masi_close = None
    if "MASI" in price_frames and "Close" in price_frames["MASI"].columns:
        masi_close = pd.to_numeric(price_frames["MASI"]["Close"], errors="coerce").dropna()
    else:
        report["anomalies"].append("MASI close series not found in price_frames -- benchmark will be empty.")
    adv_series = compute_pit_adv_series(price_frames)
    print(f"Loaded prices for {len(price_frames)} symbols; ADV series for {len(adv_series)} symbols; MASI present={masi_close is not None}")

    # --- 4. G1 gates (primary config defaults: either / sma210 / mom231-21) ---
    g1_config = CombinedConfig()
    g1_gates = build_trend_gate_series(close_by_symbol, g1_config)
    print(f"G1 trend gates built for {len(g1_gates)} symbols (rule={g1_config.g1_rule}, sma={g1_config.g1_sma_days}d, mom={g1_config.g1_mom_formation_days}/{g1_config.g1_mom_skip_days}d)")

    # --- 5. G2 gates: diagnostic query first ---
    diag_sql = """
        SELECT source, horizon, COUNT(*) n, COUNT(DISTINCT symbol) syms, MIN(date) min_date, MAX(date) max_date
        FROM signal_score_history
        WHERE is_oos AND source LIKE 'wfo%'
        GROUP BY source, horizon
        ORDER BY n DESC
    """
    diag_df = pd.read_sql(text(diag_sql), engine)
    diag_df.to_csv(OUT_DIR / "g2_source_diagnostics.csv", index=False)
    print("\nG2 source diagnostics (is_oos AND source LIKE 'wfo%'):")
    print(diag_df.to_string(index=False))

    monthly_sources = diag_df[diag_df["horizon"] == "monthly"]
    g2_source_flagged = False
    if (monthly_sources["source"] == EXPECTED_G2_SOURCE).any():
        g2_source = EXPECTED_G2_SOURCE
    else:
        if monthly_sources.empty:
            raise SystemExit("ABORT: no wfo% source with horizon='monthly' found in signal_score_history.")
        g2_source = str(monthly_sources.sort_values("n", ascending=False).iloc[0]["source"])
        g2_source_flagged = True
        msg = f"FLAG: expected G2 source {EXPECTED_G2_SOURCE!r} absent from monthly wfo% sources; using closest available: {g2_source!r}"
        print(msg)
        report["anomalies"].append(msg)

    g2_sql = text(
        """
        SELECT date, symbol, category, score_pct
        FROM signal_score_history
        WHERE is_oos AND source = :source AND horizon = 'monthly'
          AND category IN ('tendance','momentum','oscillation','volume')
        """
    )
    g2_raw = pd.read_sql(g2_sql, engine, params={"source": g2_source})
    g2_gates = aggregate_wfo_gate(g2_raw, threshold=20.0, min_categories=1)
    print(f"G2 gates built from source={g2_source!r}: {len(g2_raw)} rows -> {len(g2_gates)} symbols with a defined gate series (flagged={g2_source_flagged})")

    report["run_metadata"]["g2_source"] = g2_source
    report["run_metadata"]["g2_source_flagged"] = g2_source_flagged

    # --- 6. Holdings (S1_bm, S3_composite) + overlay variants ---
    base_cfg = LiveLikeConfig()  # cost_bps=33 default
    s1_holdings = build_vintage_holdings_by_date(panel, strategy="S1_bm", config=base_cfg)
    s3_holdings = build_vintage_holdings_by_date(panel, strategy="S3_composite", config=base_cfg)

    risk_cfg = CombinedConfig(sector_cap=SECTOR_CAP, max_name_weight=MAX_NAME_WEIGHT, adv_floor_mad=None)
    s1_capped = apply_overlays_to_holdings(s1_holdings, sector_map=sector_map, config=risk_cfg, adv_series_by_symbol=None)
    s3_capped = apply_overlays_to_holdings(s3_holdings, sector_map=sector_map, config=risk_cfg, adv_series_by_symbol=None)

    risk_cfg_adv100k = CombinedConfig(sector_cap=SECTOR_CAP, max_name_weight=MAX_NAME_WEIGHT, adv_floor_mad=100_000.0)
    s1_capped_adv100k = apply_overlays_to_holdings(s1_holdings, sector_map=sector_map, config=risk_cfg_adv100k, adv_series_by_symbol=adv_series)

    risk_cfg_adv250k = CombinedConfig(sector_cap=SECTOR_CAP, max_name_weight=MAX_NAME_WEIGHT, adv_floor_mad=250_000.0)
    s1_capped_adv250k = apply_overlays_to_holdings(s1_holdings, sector_map=sector_map, config=risk_cfg_adv250k, adv_series_by_symbol=adv_series)

    # --- 7. Pre-registered grid ---
    cells: dict[str, dict] = {
        "C0a": dict(
            holdings=s1_holdings, gate=None,
            config=CombinedConfig(base=LiveLikeConfig(cost_bps=33.0), gate="G0"),
        ),
        "C0b": dict(
            holdings=s3_holdings, gate=None,
            config=CombinedConfig(base=LiveLikeConfig(cost_bps=33.0), gate="G0"),
        ),
        "P": dict(
            holdings=s1_capped, gate=g1_gates,
            config=CombinedConfig(base=LiveLikeConfig(cost_bps=33.0), gate="G1", g1_rule="either",
                                   exit_mode="X1", sector_cap=SECTOR_CAP, max_name_weight=MAX_NAME_WEIGHT),
        ),
        "P_X0": dict(
            holdings=s1_capped, gate=g1_gates,
            config=CombinedConfig(base=LiveLikeConfig(cost_bps=33.0), gate="G1", g1_rule="either",
                                   exit_mode="X0", sector_cap=SECTOR_CAP, max_name_weight=MAX_NAME_WEIGHT),
        ),
        "P_noRisk": dict(
            holdings=s1_holdings, gate=g1_gates,
            config=CombinedConfig(base=LiveLikeConfig(cost_bps=33.0), gate="G1", g1_rule="either",
                                   exit_mode="X1", sector_cap=None, max_name_weight=None),
        ),
        "P_G0risk": dict(
            holdings=s1_capped, gate=None,
            config=CombinedConfig(base=LiveLikeConfig(cost_bps=33.0), gate="G0",
                                   exit_mode="X0", sector_cap=SECTOR_CAP, max_name_weight=MAX_NAME_WEIGHT),
        ),
        "S3_mirror": dict(
            holdings=s3_capped, gate=g1_gates,
            config=CombinedConfig(base=LiveLikeConfig(cost_bps=33.0), gate="G1", g1_rule="either",
                                   exit_mode="X1", sector_cap=SECTOR_CAP, max_name_weight=MAX_NAME_WEIGHT),
        ),
        "G2_cell": dict(
            holdings=s1_capped, gate=g2_gates,
            config=CombinedConfig(base=LiveLikeConfig(cost_bps=33.0), gate="G2",
                                   exit_mode="X1", sector_cap=SECTOR_CAP, max_name_weight=MAX_NAME_WEIGHT,
                                   missing_gate_policy="pass"),
        ),
        "P_cost50": dict(
            holdings=s1_capped, gate=g1_gates,
            config=CombinedConfig(base=LiveLikeConfig(cost_bps=50.0), gate="G1", g1_rule="either",
                                   exit_mode="X1", sector_cap=SECTOR_CAP, max_name_weight=MAX_NAME_WEIGHT),
        ),
        "P_cost75": dict(
            holdings=s1_capped, gate=g1_gates,
            config=CombinedConfig(base=LiveLikeConfig(cost_bps=75.0), gate="G1", g1_rule="either",
                                   exit_mode="X1", sector_cap=SECTOR_CAP, max_name_weight=MAX_NAME_WEIGHT),
        ),
        "P_adv100k": dict(
            holdings=s1_capped_adv100k, gate=g1_gates,
            config=CombinedConfig(base=LiveLikeConfig(cost_bps=33.0), gate="G1", g1_rule="either",
                                   exit_mode="X1", sector_cap=SECTOR_CAP, max_name_weight=MAX_NAME_WEIGHT,
                                   adv_floor_mad=100_000.0),
        ),
        "P_adv250k": dict(
            holdings=s1_capped_adv250k, gate=g1_gates,
            config=CombinedConfig(base=LiveLikeConfig(cost_bps=33.0), gate="G1", g1_rule="either",
                                   exit_mode="X1", sector_cap=SECTOR_CAP, max_name_weight=MAX_NAME_WEIGHT,
                                   adv_floor_mad=250_000.0),
        ),
    }

    results: dict[str, pd.DataFrame] = {}
    for name, spec in cells.items():
        monthly, events = run_gated_vintage_backtest(
            spec["holdings"], price_by_symbol=close_by_symbol, gate_by_symbol=spec["gate"], config=spec["config"]
        )
        monthly.to_csv(OUT_DIR / f"monthly_returns_{name}.csv", index=False)
        events.to_csv(OUT_DIR / f"events_{name}.csv", index=False)
        results[name] = monthly
        print(f"Cell {name}: {len(monthly)} months, {len(events)} events, formed from {len(spec['holdings'])} formation dates")

    # --- 8. Benchmark (MASI monthly, aligned to sorted S1 formation dates) ---
    all_dates = sorted(s1_holdings)
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

    # --- 9. Common invested window ---
    c0a_monthly = results["C0a"]
    invested_rows = c0a_monthly[c0a_monthly["n_holdings"] > 0]
    if invested_rows.empty:
        raise SystemExit("ABORT: C0a never holds any names -- cannot determine common invested window.")
    common_start = invested_rows["as_of_date"].iloc[0]
    common_end = c0a_monthly["as_of_date"].iloc[-1]
    print(f"\nCommon invested window: {common_start} .. {common_end}")

    def slice_invested(df: pd.DataFrame) -> pd.DataFrame:
        return df[df["as_of_date"] >= common_start].reset_index(drop=True)

    masi_sliced = masi_series[masi_series.index >= common_start]

    # --- 10. Metrics per cell (full + invested) ---
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

    p_sliced = slice_invested(results["P"])
    c0a_sliced = slice_invested(results["C0a"])
    diff = difference_test(p_sliced, c0a_sliced)
    metrics["difference_test_P_vs_C0a"] = diff

    sub_p = subperiod_summary(results["P"])
    sub_p["cell"] = "P"
    sub_c0a = subperiod_summary(results["C0a"])
    sub_c0a["cell"] = "C0a"
    subperiods = pd.concat([sub_p, sub_c0a], ignore_index=True)
    subperiods.to_csv(OUT_DIR / "subperiods.csv", index=False)

    # Analytic breakeven cost
    merged = p_sliced[["as_of_date", "gross_return", "turnover"]].merge(
        c0a_sliced[["as_of_date", "gross_return", "turnover"]], on="as_of_date", suffixes=("_P", "_C0a")
    )
    gross_diff_mean = float((merged["gross_return_P"] - merged["gross_return_C0a"]).mean())
    turnover_diff_mean = float((merged["turnover_P"] - merged["turnover_C0a"]).mean())
    breakeven_bps = (gross_diff_mean / (2.0 * turnover_diff_mean) * 1e4) if turnover_diff_mean > 0 else None
    metrics["breakeven_cost_bps"] = breakeven_bps
    metrics["breakeven_inputs"] = {"mean_gross_diff_monthly": gross_diff_mean, "mean_turnover_diff_monthly": turnover_diff_mean}

    cost_rows = []
    for cbps, cellname in [(33.0, "P"), (50.0, "P_cost50"), (75.0, "P_cost75")]:
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

    # --- 11. G2 coverage + restricted pair ---
    coverage_rows = []
    for as_of in sorted(s1_holdings):
        holdings_dict = s1_holdings[as_of]
        n = len(holdings_dict)
        if n == 0:
            coverage_rows.append({"as_of_date": as_of, "n_candidates": 0, "pct_g1_defined": None, "pct_g2_defined_nonstale": None})
            continue
        g1_defined = sum(1 for sym in holdings_dict if pit_value(g1_gates.get(sym), as_of) is not None)
        g2_defined = sum(1 for sym in holdings_dict if _g2_defined_nonstale(g2_gates.get(sym), as_of))
        coverage_rows.append(
            {
                "as_of_date": as_of,
                "n_candidates": n,
                "pct_g1_defined": g1_defined / n,
                "pct_g2_defined_nonstale": g2_defined / n,
            }
        )
    coverage_df = pd.DataFrame(coverage_rows)
    coverage_df.to_csv(OUT_DIR / "gate_coverage.csv", index=False)

    g2_active = coverage_df[coverage_df["pct_g2_defined_nonstale"].fillna(0) > 0]
    g2_secondary: dict | None = None
    if not g2_active.empty:
        g2_start, g2_end = g2_active["as_of_date"].iloc[0], g2_active["as_of_date"].iloc[-1]

        def slice_g2(df: pd.DataFrame) -> pd.DataFrame:
            return df[(df["as_of_date"] >= g2_start) & (df["as_of_date"] <= g2_end)].reset_index(drop=True)

        p_g2 = slice_g2(results["P"])
        g2c_g2 = slice_g2(results["G2_cell"])
        g2_secondary = {
            "window": [str(g2_start), str(g2_end)],
            "n_months": int(len(p_g2)),
            "P": summarize_performance(p_g2, periods_per_year=12),
            "G2_cell": summarize_performance(g2c_g2, periods_per_year=12),
            "difference_test_G2_vs_P": difference_test(g2c_g2, p_g2),
        }
    else:
        report["anomalies"].append("G2 coverage is zero on every S1 formation date -- no G2 secondary window computed.")
    metrics["g2_secondary"] = g2_secondary

    covered_dates = coverage_df[coverage_df["n_candidates"] > 0]
    g2_coverage_stats = {
        "mean_pct_g1_defined": float(covered_dates["pct_g1_defined"].mean()) if not covered_dates.empty else None,
        "mean_pct_g2_defined_nonstale": float(covered_dates["pct_g2_defined_nonstale"].mean()) if not covered_dates.empty else None,
        "n_formation_dates_with_any_g2_coverage": int(len(g2_active)),
        "n_formation_dates_total": int(len(covered_dates)),
    }
    metrics["g2_coverage_stats"] = g2_coverage_stats

    # --- 12. Acceptance ---
    p_summary_invested = metrics["cells"]["P"]["invested"]
    c0a_summary_invested = metrics["cells"]["C0a"]["invested"]
    masi_sharpe_invested = masi_summary_inv.get("sharpe") if isinstance(masi_summary_inv, dict) else None
    acceptance = evaluate_acceptance(p_summary_invested, c0a_summary_invested, diff, masi_sharpe=masi_sharpe_invested)
    metrics["acceptance"] = acceptance

    # --- 14. Parity check (hard requirement) ---
    live_like_runs = sorted(LIVE_LIKE_DIR.glob("*/strategy_metrics.json")) if LIVE_LIKE_DIR.exists() else []
    parity_result: dict = {"pass": False, "fields": {}, "note": None}
    if not live_like_runs:
        parity_result["note"] = f"No {LIVE_LIKE_DIR}/*/strategy_metrics.json found -- parity check could not run."
        report["anomalies"].append(parity_result["note"])
    else:
        latest_run = live_like_runs[-1]
        incumbent_metrics = json.loads(latest_run.read_text(encoding="utf-8"))
        incumbent_s1 = incumbent_metrics.get("S1_bm", {})
        c0a_full = metrics["cells"]["C0a"]["full"]
        parity_pass = True
        for field in ("cumulative_return", "sharpe", "max_drawdown"):
            a = c0a_full.get(field)
            b = incumbent_s1.get(field)
            ok = _rel_close(a, b)
            parity_pass = parity_pass and ok
            parity_result["fields"][field] = {"combined_C0a": a, "incumbent_S1_bm": b, "pass": ok}
        parity_result["pass"] = parity_pass
        parity_result["incumbent_run"] = str(latest_run)
    metrics["parity_check"] = parity_result

    print("\nPARITY CHECK:", "PASS" if parity_result["pass"] else "FAIL")
    for field, v in parity_result.get("fields", {}).items():
        print(f"  {field}: combined_C0a={v['combined_C0a']!r} incumbent_S1_bm={v['incumbent_S1_bm']!r} pass={v['pass']}")
    if parity_result["note"]:
        print(f"  note: {parity_result['note']}")
    if not parity_result["pass"] and live_like_runs:
        report["anomalies"].append("PARITY CHECK FAILED -- engine/runner discrepancy vs incumbent S1_bm; verdict below is unreliable until resolved. Engine NOT modified per instructions.")

    # --- 13. Artifacts ---
    report["run_metadata"].update(
        {
            "timestamp_utc": OUT_DIR.name,
            "panel_path": str(PANEL_PATH),
            "common_invested_window": [str(common_start), str(common_end)],
            "sector_cap": SECTOR_CAP,
            "max_name_weight": MAX_NAME_WEIGHT,
            "g1_rule": g1_config.g1_rule,
            "g1_sma_days": g1_config.g1_sma_days,
            "g1_mom_formation_days": g1_config.g1_mom_formation_days,
            "g1_mom_skip_days": g1_config.g1_mom_skip_days,
            "cost_bps_primary": 33.0,
            "wfo_long_threshold": 20.0,
            "g2_max_staleness_days": G2_MAX_STALENESS_DAYS,
        }
    )

    metrics_out = {**report, **metrics}
    (OUT_DIR / "metrics.json").write_text(json.dumps(metrics_out, indent=2, default=str), encoding="utf-8")
    (OUT_DIR / "verdict.json").write_text(
        json.dumps({"acceptance": acceptance, "parity_check": parity_result, "breakeven_cost_bps": breakeven_bps, "g2_secondary": g2_secondary, "anomalies": report["anomalies"]}, indent=2, default=str),
        encoding="utf-8",
    )

    verdict_md = _render_verdict_md(
        report=report,
        metrics=metrics,
        cost_df=cost_df,
        coverage_stats=g2_coverage_stats,
        parity_result=parity_result,
        acceptance=acceptance,
        breakeven_bps=breakeven_bps,
        common_start=common_start,
        common_end=common_end,
    )
    (OUT_DIR / "verdict.md").write_text(verdict_md, encoding="utf-8")

    print(f"\nWritten to {OUT_DIR}")
    print(f"Verdict: {acceptance['verdict']}")
    print(json.dumps(acceptance, indent=2, default=str))


def _render_verdict_md(
    *,
    report: dict,
    metrics: dict,
    cost_df: pd.DataFrame,
    coverage_stats: dict,
    parity_result: dict,
    acceptance: dict,
    breakeven_bps: float | None,
    common_start,
    common_end,
) -> str:
    lines: list[str] = []
    lines.append("# Combined Value x Technical Strategy -- Verdict Report (Stage 1)")
    lines.append("")
    lines.append(f"Run timestamp (UTC): {report['run_metadata']['timestamp_utc']}")
    lines.append(f"Panel: {report['run_metadata']['panel_path']}")
    lines.append(f"Common invested window: {common_start} .. {common_end}")
    lines.append(f"G2 source used: {report['run_metadata']['g2_source']} (flagged={report['run_metadata']['g2_source_flagged']})")
    lines.append("")
    lines.append("## Config echo")
    lines.append("")
    for k, v in report["run_metadata"].items():
        lines.append(f"- `{k}`: {v}")
    lines.append("")

    lines.append("## Headline metrics (invested window)")
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
        lines.append(
            f"| {name} | {cagr:.4f} | {sharpe:.3f} | {dd:.4f} | {hit:.3f} | {turn:.4f} | "
            f"{ir if ir is None else round(ir, 3)} |"
        )
    lines.append("")

    lines.append("## Acceptance criteria (verbatim)")
    lines.append("")
    lines.append(f"**Verdict: {acceptance['verdict']}**")
    lines.append("")
    for key, crit in acceptance["criteria"].items():
        status = "PASS" if crit["pass"] else "FAIL"
        lines.append(f"- `{key}`: {status} -- {crit}")
    lines.append("")
    lines.append(f"Difference test (P - C0a): {acceptance['difference_test']}")
    lines.append("")

    lines.append("## G2 secondary (informational; never upgrades the verdict)")
    lines.append("")
    g2sec = metrics.get("g2_secondary")
    if g2sec:
        lines.append(f"Window: {g2sec['window']} ({g2sec['n_months']} months)")
        lines.append(f"- P (restricted to window): {g2sec['P']}")
        lines.append(f"- G2_cell (restricted to window): {g2sec['G2_cell']}")
        lines.append(f"- difference_test(G2_cell, P): {g2sec['difference_test_G2_vs_P']}")
    else:
        lines.append("No G2 secondary window (zero coverage on every S1 formation date).")
    lines.append("")
    lines.append("## G2 coverage stats")
    lines.append("")
    for k, v in coverage_stats.items():
        lines.append(f"- `{k}`: {v}")
    lines.append("")

    lines.append("## Cost sensitivity")
    lines.append("")
    try:
        lines.append(cost_df.to_markdown(index=False))
    except ImportError:
        lines.append(cost_df.to_string(index=False))
    lines.append("")
    lines.append(f"Analytic breakeven cost (bps): {breakeven_bps}")
    lines.append("")

    lines.append("## Parity check (C0a full-frame vs incumbent S1_bm)")
    lines.append("")
    lines.append(f"Result: {'PASS' if parity_result['pass'] else 'FAIL'}")
    for field, v in parity_result.get("fields", {}).items():
        lines.append(f"- {field}: combined_C0a={v['combined_C0a']} incumbent_S1_bm={v['incumbent_S1_bm']} pass={v['pass']}")
    if parity_result.get("note"):
        lines.append(f"- note: {parity_result['note']}")
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
