"""Phase-4 gate: does the model forecaster beat naive-CAGR out-of-sample?
(brief 54 §3 Phase 4)

Builds the full cross-sectional, multi-year growth panel from
fundamental_annual_metric (all symbols, all years) with strict point-in-time
discipline (reuses pit_ic_backtest._filter_pit_history -- no lookahead), then
runs forecast_model.run_expanding_window_backtest() for both revenue growth
and net-income growth (the EPS proxy -- see forecast_model.py docstring).

Prints RMSE / MAE / hit-rate for the model vs. the exact naive-CAGR blend
already used in projection.py's mechanical fallback, and a plain gate
decision. This is the evidence behind the Phase-4 wiring decision recorded in
docs/fundamentals-layer/54-forward-estimate-layer-plan.md -- kept as a script
(not a pytest test) because it needs a live DB with real MASI fundamentals;
core/tests/test_forecast_model.py covers the pure-function mechanics with
synthetic data instead.

Usage:
    python services/api/scripts/forecast_model_validation.py
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "core") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "core"))

from sqlalchemy import create_engine, text  # noqa: E402

from quant_core.fundamentals.domain import AnnualMetricRow  # noqa: E402
from quant_core.fundamentals.forecast_model import (  # noqa: E402
    build_growth_observations,
    run_expanding_window_backtest,
)
from quant_core.fundamentals.pit_ic_backtest import _filter_pit_history  # noqa: E402
from quant_core.fundamentals.projection import NET_INCOME_ALIASES, REVENUE_ALIASES  # noqa: E402


def _load_rows(db_url: str) -> list[AnnualMetricRow]:
    engine = create_engine(db_url)
    query = text("""
        SELECT symbol, company_name, statement_year, metric_name, metric_value
        FROM fundamental_annual_metric
        WHERE statement_year >= 2000 AND metric_value IS NOT NULL
        ORDER BY symbol, statement_year, metric_name
    """)
    rows: list[AnnualMetricRow] = []
    with engine.connect() as conn:
        for r in conn.execute(query):
            rows.append(
                AnnualMetricRow(
                    symbol=str(r[0]).strip().upper(),
                    company_name=str(r[1] or ""),
                    statement_year=int(r[2]),
                    metric_name=str(r[3]),
                    metric_value=float(r[4]),
                )
            )
    return rows


def _load_sectors(db_url: str) -> dict[str, str | None]:
    engine = create_engine(db_url)
    query = text("SELECT symbol, sector FROM stock_master WHERE symbol IS NOT NULL")
    sectors: dict[str, str | None] = {}
    with engine.connect() as conn:
        for r in conn.execute(query):
            sectors[str(r[0]).strip().upper()] = str(r[1]).strip() if r[1] else None
    return sectors


def _build_full_panel(rows: list[AnnualMetricRow], sectors: dict[str, str | None], aliases: tuple[str, ...]):
    rows_by_symbol: dict[str, list[AnnualMetricRow]] = defaultdict(list)
    for row in rows:
        rows_by_symbol[row.symbol].append(row)

    all_years = sorted({row.statement_year for row in rows})
    min_year, max_year = min(all_years), max(all_years)

    panel = []
    for as_of_year in range(min_year + 3, max_year):
        pit_histories = {
            sym: _filter_pit_history(sym_rows, as_of_year, sym) for sym, sym_rows in rows_by_symbol.items()
        }
        realized_histories = {
            sym: _filter_pit_history(sym_rows, as_of_year + 1, sym) for sym, sym_rows in rows_by_symbol.items()
        }
        panel.extend(
            build_growth_observations(
                pit_histories, sectors, as_of_year, aliases, realized_histories_by_symbol=realized_histories
            )
        )
    return panel


def main() -> None:
    db_url = os.environ.get("DATABASE_URL", "postgresql://app:app@localhost:5555/quant")

    print("Loading fundamental_annual_metric + stock_master from DB...", flush=True)
    rows = _load_rows(db_url)
    sectors = _load_sectors(db_url)
    print(f"Loaded {len(rows):,} rows, {len(sectors)} symbols with sector.\n", flush=True)

    overall_gate = True
    for label, aliases in (("REVENUE growth", REVENUE_ALIASES), ("NET_INCOME growth (EPS proxy)", NET_INCOME_ALIASES)):
        print(f"=== {label} ===")
        panel = _build_full_panel(rows, sectors, aliases)
        years_with_target = sorted({obs.as_of_year for obs in panel if obs.target is not None})
        if not years_with_target:
            print("  INSUFFICIENT DATA (no realized targets in panel)\n")
            overall_gate = False
            continue
        test_years = [y for y in years_with_target if y >= years_with_target[0] + 3]
        result = run_expanding_window_backtest(panel, test_years)
        if result is None:
            print("  INSUFFICIENT DATA for expanding-window backtest\n")
            overall_gate = False
            continue

        model_m = result["model"]
        naive_m = result["naive_cagr"]
        print(f"  {'':10s}  {'n':>5}  {'RMSE':>8}  {'MAE':>8}  {'hit_rate':>9}")
        print(f"  {'model':10s}  {model_m.n:5d}  {model_m.rmse:8.4f}  {model_m.mae:8.4f}  {model_m.hit_rate:9.3f}")
        print(f"  {'naive_cagr':10s}  {naive_m.n:5d}  {naive_m.rmse:8.4f}  {naive_m.mae:8.4f}  {naive_m.hit_rate:9.3f}")

        beats_rmse = model_m.rmse < naive_m.rmse
        beats_mae = model_m.mae < naive_m.mae
        beats_hit = model_m.hit_rate >= naive_m.hit_rate
        passed = beats_rmse and beats_mae
        overall_gate = overall_gate and passed
        print(
            f"  GATE: RMSE better={beats_rmse}  MAE better={beats_mae}  "
            f"hit-rate>=naive={beats_hit}  -> {'PASS' if passed else 'FAIL'}\n"
        )

    sep = "-" * 60
    print(sep)
    if overall_gate:
        print("GATE DECISION: model beats naive-CAGR OOS on all metrics -- wire in as fallback.")
    else:
        print("GATE DECISION: model does NOT clear the bar on at least one metric -- do NOT wire in.")
    print(sep)


if __name__ == "__main__":
    main()
