from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.quant_core.fundamentals.domain import AnnualMetricRow, CompanyMapping, FundamentalSnapshot, FundamentalWorkbook
from scripts.backfill_stockanalysis_fundamentals import _persist_workbook, backfill_stockanalysis_fundamentals
from services.api.app import models
from services.api.app.json_sanitize import sanitize_json_compatible
from services.api.app.services.fundamentals import (
    create_import_run,
    latest_snapshot_rows_by_symbol,
    make_bulk_overrides_loader,
    persist_pillar_history_for_import,
    recompute_symbol_valuations_all_scenarios,
    rescore_universe,
)
from services.worker.db import SessionLocal

DEFAULT_SYMBOLS = ["ATW", "BOA", "MNG", "IAM", "TQM"]
SCENARIOS = ("bear", "base", "bull")

DEMO_PROFILES: dict[str, dict[str, Any]] = {
    "ATW": {"name": "Attijariwafa Bank", "sector": "Banks", "price": 530.0, "shares": 215_000_000, "revenue": 31_500.0, "net_income": 7_800.0, "equity": 65_000.0, "debt": 18_000.0},
    "BOA": {"name": "Bank of Africa", "sector": "Banks", "price": 205.0, "shares": 205_000_000, "revenue": 18_500.0, "net_income": 3_100.0, "equity": 34_000.0, "debt": 12_000.0},
    "MNG": {"name": "Managem", "sector": "Mines", "price": 2_750.0, "shares": 10_000_000, "revenue": 8_900.0, "net_income": 1_250.0, "equity": 9_600.0, "debt": 4_300.0},
    "IAM": {"name": "Maroc Telecom", "sector": "Telecoms", "price": 95.0, "shares": 879_000_000, "revenue": 36_800.0, "net_income": 6_200.0, "equity": 19_500.0, "debt": 15_500.0},
    "TQM": {"name": "Taqa Morocco", "sector": "Utilities", "price": 1_180.0, "shares": 23_600_000, "revenue": 13_700.0, "net_income": 1_520.0, "equity": 8_700.0, "debt": 8_200.0},
}


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _symbols_from_args(raw: list[str] | None) -> list[str]:
    items = raw or DEFAULT_SYMBOLS
    symbols: list[str] = []
    for item in items:
        symbols.extend(part.strip().upper() for part in item.split(",") if part.strip())
    out: list[str] = []
    for symbol in symbols:
        if symbol not in out:
            out.append(symbol)
    return out


def _profile(symbol: str, index: int) -> dict[str, Any]:
    if symbol in DEMO_PROFILES:
        return {**DEMO_PROFILES[symbol], "symbol": symbol}
    price = 100.0 + index * 18.0
    shares = 20_000_000 + index * 3_000_000
    revenue = 5_000.0 + index * 850.0
    net_income = revenue * (0.10 + index * 0.004)
    return {
        "symbol": symbol,
        "name": symbol,
        "sector": "Industrie",
        "price": price,
        "shares": shares,
        "revenue": revenue,
        "net_income": net_income,
        "equity": revenue * 1.4,
        "debt": revenue * 0.45,
    }


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _ensure_stock_rows(db, profiles: list[dict[str, Any]]) -> None:
    for index, profile in enumerate(profiles):
        symbol = profile["symbol"]
        row = db.query(models.StockMaster).filter(models.StockMaster.symbol == symbol).first()
        if row is None:
            row = models.StockMaster(symbol=symbol)
        row.display_name = row.display_name or profile["name"]
        row.sector = row.sector or profile["sector"]
        row.market_region = "masi"
        row.is_active = True
        if row.shares_outstanding is None:
            row.shares_outstanding = int(profile["shares"])
            row.shares_source = row.shares_source or "demo_fixture"
            row.shares_as_of = row.shares_as_of or dt.date(2026, 5, 31)
        db.add(row)

        market = (
            db.query(models.MarketDataStore)
            .filter(models.MarketDataStore.symbol == symbol, models.MarketDataStore.timeframe == "1D")
            .first()
        )
        if market is None:
            market = models.MarketDataStore(symbol=symbol, timeframe="1D", object_key=f"demo/{symbol}.parquet")
        market.asset_class = "equity"
        market.close_last = float(profile["price"])
        market.prev_close = float(profile["price"]) * 0.99
        market.adv_20d = 500_000.0 + index * 125_000.0
        market.data_as_of = dt.date(2026, 5, 31)
        db.add(market)
    db.flush()


def _snapshot(profile: dict[str, Any], *, index: int) -> FundamentalSnapshot:
    price = float(profile["price"])
    shares = float(profile["shares"])
    revenue = float(profile["revenue"])
    net_income = float(profile["net_income"])
    equity = float(profile["equity"])
    debt = float(profile["debt"])
    cash = debt * 0.22
    ebit = net_income / 0.70
    ebitda = ebit * 1.22
    fcf = net_income * (0.72 + index * 0.02)
    dividends = net_income * 0.48
    assets = equity + debt
    market_cap = price * shares / 1_000_000.0
    enterprise_value = market_cap + debt - cash
    metrics = {
        "Current_Price": price,
        "Shares_Outstanding": shares,
        "MarketCap_Calc": market_cap,
        "ADV20": 500_000.0 + index * 125_000.0,
        "Revenue": revenue,
        "Chiffre_daffaires": revenue,
        "Resultat_net": net_income,
        "NetIncome": net_income,
        "EBIT": ebit,
        "Resultat_dexploitation": ebit,
        "EBITDA": ebitda,
        "Free_Cash_Flow": fcf,
        "Dividendes": dividends,
        "Total_Debt": debt,
        "Debt_Total": debt,
        "Cash": cash,
        "NetDebt": debt - cash,
        "Total_Equity": equity,
        "Total_Assets": assets,
        "Total_Liabilities": debt,
        "EnterpriseValue": enterprise_value,
        "PER": _safe_ratio(market_cap, net_income),
        "Price_to_Book": _safe_ratio(market_cap, equity),
        "Price_to_Sales": _safe_ratio(market_cap, revenue),
        "EV_to_EBITDA": _safe_ratio(enterprise_value, ebitda),
        "ROE": _safe_ratio(net_income, equity),
        "ROA": _safe_ratio(net_income, assets),
        "Asset_Turnover": _safe_ratio(revenue, assets),
        "Equity_Multiplier": _safe_ratio(assets, equity),
        "Net_Margin": _safe_ratio(net_income, revenue),
        "Current_Ratio": 1.15 + index * 0.05,
        "Debt_to_Equity": _safe_ratio(debt, equity),
        "Operating_Margin": _safe_ratio(ebit, revenue),
        "FCF_Margin": _safe_ratio(fcf, revenue),
        "FCF_Yield": _safe_ratio(fcf, market_cap),
        "Dividend_Yield": _safe_ratio(dividends, market_cap),
        "Revenue_Growth": 0.045 + index * 0.006,
        "NetIncome_Growth": 0.035 + index * 0.005,
        "Dividend_Payout": _safe_ratio(dividends, net_income),
    }
    return FundamentalSnapshot(
        symbol=profile["symbol"],
        company_name=profile["name"],
        latest_statement_year=2024,
        metrics=metrics,
        coverage={"provider": "demo_fixture", "status": "synthetic_demo"},
        source={"currency": "MAD", "provider": "demo_fixture"},
    )


def _annual_rows(profile: dict[str, Any], *, index: int) -> list[AnnualMetricRow]:
    rows: list[AnnualMetricRow] = []
    symbol = profile["symbol"]
    name = profile["name"]
    base_revenue = float(profile["revenue"])
    base_net_income = float(profile["net_income"])
    base_equity = float(profile["equity"])
    base_debt = float(profile["debt"])
    for offset, year in enumerate(range(2020, 2025)):
        scale = 0.78 + offset * 0.055 + index * 0.006
        revenue = base_revenue * scale
        net_income = base_net_income * scale * (0.94 + offset * 0.015)
        equity = base_equity * (0.82 + offset * 0.045)
        debt = base_debt * (0.95 - offset * 0.025)
        cash = debt * 0.22
        ebit = net_income / 0.70
        ebitda = ebit * 1.22
        fcf = net_income * (0.68 + offset * 0.025)
        dividends = net_income * 0.46
        assets = equity + debt
        metric_values = {
            "Revenue": revenue,
            "Chiffre_daffaires": revenue,
            "Resultat_net": net_income,
            "NetIncome": net_income,
            "EBIT": ebit,
            "Resultat_dexploitation": ebit,
            "EBITDA": ebitda,
            "Free_Cash_Flow": fcf,
            "Dividendes": dividends,
            "Total_Debt": debt,
            "Debt_Total": debt,
            "Cash": cash,
            "NetDebt": debt - cash,
            "Total_Equity": equity,
            "Total_Assets": assets,
            "Total_Liabilities": debt,
            "Capex": revenue * 0.045,
            "Depreciation_Amortization": ebitda - ebit,
            "Working_Capital": revenue * 0.08,
            "ROE": _safe_ratio(net_income, equity),
            "ROA": _safe_ratio(net_income, assets),
            "FCF_Margin": _safe_ratio(fcf, revenue),
            "Dividend_Yield": 0.025 + offset * 0.002,
        }
        for metric, value in metric_values.items():
            rows.append(
                AnnualMetricRow(
                    symbol=symbol,
                    company_name=name,
                    statement_year=year,
                    metric_name=metric,
                    metric_value=value,
                    raw_metric_name=metric,
                    source_sheet="demo_fixture",
                    source_field=metric,
                )
            )
    return rows


def _fixture_workbook(symbols: list[str]) -> tuple[FundamentalWorkbook, list[dict[str, Any]]]:
    profiles = [_profile(symbol, index) for index, symbol in enumerate(symbols)]
    workbook = FundamentalWorkbook(
        mappings=[
            CompanyMapping(
                company_name=profile["name"],
                mapped_company_name=profile["name"],
                canonical_company_name=profile["name"],
                symbol=profile["symbol"],
                shares_outstanding=float(profile["shares"]),
                match_type="demo_fixture",
                score_note="synthetic demo fixture",
                source="demo_fixture",
            )
            for profile in profiles
        ],
        annual_metrics=[row for index, profile in enumerate(profiles) for row in _annual_rows(profile, index=index)],
        latest_snapshots=[_snapshot(profile, index=index) for index, profile in enumerate(profiles)],
        summary={"provider": "demo_fixture", "symbols": symbols},
    )
    return workbook, profiles


def seed_fixture(symbols: list[str]) -> dict[str, Any]:
    started = time.perf_counter()
    workbook, profiles = _fixture_workbook(symbols)
    digest = hashlib.sha256(("demo_fixture:" + ",".join(symbols) + ":" + _utcnow().isoformat()).encode("utf-8")).hexdigest()
    db = SessionLocal()
    try:
        _ensure_stock_rows(db, profiles)
        run = create_import_run(
            db,
            data_source="demo_fixture",
            source_universe="masi",
            filename=f"demo_fixture_fundamentals_{digest[:12]}",
            source_hash=digest,
            summary={"triggered_by": "seed_fundamental_demo", "symbols": symbols},
        )
        run.status = "running"
        run.imported_at = _utcnow()
        db.add(run)
        db.commit()

        _persist_workbook(db, run.id, workbook, data_source="demo_fixture")
        run.symbol_count = len(symbols)
        run.company_count = len(symbols)
        run.annual_metric_count = len(workbook.annual_metrics)
        run.latest_snapshot_count = len(workbook.latest_snapshots)
        run.quality_issue_count = 0
        run.status = "succeeded"
        run.completed_at = _utcnow()
        run.summary_json = sanitize_json_compatible({**dict(run.summary_json or {}), "elapsed_seconds": round(time.perf_counter() - started, 2)})
        db.add(run)
        db.commit()

        rescore_universe(db, scope="masi")
        persist_pillar_history_for_import(db, import_id=run.id)
        db.commit()

        failed: dict[str, str] = {}
        valuation_counts: dict[str, int] = {}
        overrides_loader = make_bulk_overrides_loader(db, symbols)
        for symbol in symbols:
            try:
                rows = recompute_symbol_valuations_all_scenarios(
                    db,
                    import_id=run.id,
                    symbol=symbol,
                    overrides_loader=overrides_loader,
                )
                valuation_counts[symbol] = len(rows)
                db.commit()
            except Exception as exc:  # pragma: no cover - operator-facing seed guard
                db.rollback()
                failed[symbol] = str(exc)

        run.summary_json = sanitize_json_compatible({**dict(run.summary_json or {}), "valuation_counts": valuation_counts, "failed": failed})
        run.status = "partial" if failed else "succeeded"
        db.add(run)
        db.commit()
        return {
            "provider": "fixture",
            "import_id": str(run.id),
            "status": run.status,
            "succeeded": [symbol for symbol in symbols if symbol not in failed],
            "failed": failed,
            "elapsed_seconds": round(time.perf_counter() - started, 2),
        }
    finally:
        db.close()


def verify_demo_coverage(symbols: list[str]) -> dict[str, Any]:
    db = SessionLocal()
    try:
        snapshots = latest_snapshot_rows_by_symbol(db, symbols=symbols, scope="masi")
        rows = (
            db.query(models.FundamentalEnsembleResult)
            .filter(models.FundamentalEnsembleResult.symbol.in_(symbols), models.FundamentalEnsembleResult.scenario.in_(SCENARIOS))
            .all()
        )
        by_symbol: dict[str, dict[str, Any]] = {}
        for symbol in symbols:
            scenario_rows = [row for row in rows if row.symbol == symbol]
            scenarios = sorted({row.scenario for row in scenario_rows})
            base = next((row for row in scenario_rows if row.scenario == "base" and row.fair_value_base is not None), None)
            by_symbol[symbol] = {
                "has_snapshot": symbol in snapshots,
                "scenarios": scenarios,
                "has_base_fair_value": base is not None,
                "base_fair_value": base.fair_value_base if base else None,
            }
        usable = [
            symbol
            for symbol, status in by_symbol.items()
            if status["has_snapshot"] and set(status["scenarios"]) >= set(SCENARIOS) and status["has_base_fair_value"]
        ]
        return {"usable_symbols": usable, "count": len(usable), "symbols": by_symbol}
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed a fundamentals demo universe and verify base/bear/bull valuations.")
    parser.add_argument("--provider", choices=["stockanalysis", "fixture"], default="stockanalysis")
    parser.add_argument("--symbols", nargs="*", default=DEFAULT_SYMBOLS, help="Symbols, space-separated or comma-separated.")
    parser.add_argument("--min-symbols", type=int, default=4, help="Minimum symbols that must have snapshot plus bear/base/bull valuation coverage.")
    parser.add_argument("--missing-only", action="store_true", help="StockAnalysis mode: refresh only symbols with incomplete coverage.")
    parser.add_argument("--fallback-fixture", action="store_true", help="If StockAnalysis underfills the minimum, seed fixture data for the requested symbols.")
    args = parser.parse_args()

    symbols = _symbols_from_args(args.symbols)
    if args.provider == "fixture":
        seed_result = seed_fixture(symbols)
    else:
        seed_result = backfill_stockanalysis_fundamentals(symbols, triggered_by="fundamental_product_deck", missing_only=args.missing_only)

    verification = verify_demo_coverage(symbols)
    if args.provider == "stockanalysis" and args.fallback_fixture and verification["count"] < args.min_symbols:
        seed_result = {"stockanalysis": seed_result, "fixture": seed_fixture(symbols)}
        verification = verify_demo_coverage(symbols)

    payload = {"seed": seed_result, "verification": verification, "min_symbols": args.min_symbols}
    print(json.dumps(payload, indent=2, sort_keys=True))
    if verification["count"] < args.min_symbols:
        raise SystemExit(f"Only {verification['count']} symbols have complete demo valuation coverage; expected at least {args.min_symbols}.")


if __name__ == "__main__":
    main()
