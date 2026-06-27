from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.api.app import models
from services.api.app.services.fundamentals import (
    create_import_run,
    latest_snapshot_rows_by_symbol,
)
from services.worker.db import SessionLocal
from services.worker.tasks.targeted_bvc_fundamentals import execute_bvc_fundamental_import


THREE_STATEMENT_METRIC_GROUPS: dict[str, tuple[str, list[str]]] = {
    "Revenue": ("Chiffre_daffaires", ["Clean_Chiffre_daffaires", "Chiffre_daffaires", "Revenue", "Total_Revenue", "Total_Revenues", "TotalRevenue"]),
    "Gross Profit": ("Marge_Brute", ["Gross_Profit", "GrossProfit", "Marge_Brute"]),
    "EBITDA": ("EBITDA", ["EBITDA", "Normalized_EBITDA"]),
    "EBIT": ("Resultat_Exploitation", ["EBIT", "Operating_Income", "OperatingIncome", "Resultat_Exploitation", "Clean_Resultat_dexploitation", "Resultat_dexploitation"]),
    "Net Income": ("Resultat_Net", ["Clean_Resultat_net", "Resultat_net", "NetIncome", "Net_Income", "IS_Net_Income", "Resultat_net"]),
    "Total Assets": ("Total_Actif", ["Total_Assets", "Total_Actif", "Actif_Total", "Clean_Total_Actif"]),
    "Current Assets": ("Actif_Courant", ["Current_Assets", "Total_Current_Assets", "Actif_Courant", "Actif_circulant", "Clean_Actif_circulant", "Clean_Actif_Circulant"]),
    "Cash": ("Tresorerie", ["Cash_and_Equivalents", "BS_Cash_and_Equivalents", "Cash", "Tresorerie", "Tresorerie_Actif", "Clean_Tresorerie_Actif"]),
    "Total Liabilities": ("Passif_Total", ["Total_Liabilities", "Total_Passif", "Passif_Total", "Clean_Total_Passif"]),
    "Current Liabilities": ("Passif_Courant", ["Current_Liabilities", "Total_Current_Liabilities", "Passif_Courant", "Passif_circulant", "Clean_Passif_circulant", "Clean_Passif_Circulant"]),
    "Total Debt": ("Dette_totale", ["Total_Debt", "Debt", "Financial_Debt", "Dette_Financiere", "Dettes", "Dettes_de_financement"]),
    "Net Debt": ("Net_Debt", ["NetDebt", "Net_Debt", "Clean_Net_Debt", "Net_Debt"]),
    "Total Equity": ("Capitaux_Propres", ["Total_Equity", "Clean_Capitaux_propres", "Clean_Capitaux_Propres", "Capitaux_Propres", "Capitaux_propres", "Total_Capitaux_Propres", "Fonds_Propres"]),
    "Retained Earnings": ("Resultats_Reportes", ["Retained_Earnings", "Reserves", "Resultats_reportes"]),
    "Operating CF": ("Flux_de_tresorerie_lies_a_lactivite", ["CF_Operating", "Operating_Cash_Flow", "Cash_from_Operations", "Cash_From_Operations", "Flux_Tresorerie_Exploitation", "Flux_tresorerie_activites_operationnelles", "Flux_de_tresorerie_lies_a_lactivite", "Flux_tresorerie_activites", "Clean_Flux_tresorerie_activites"]),
    "Investing CF": ("Flux_de_tresorerie_lies_aux_investissements", ["CF_Investing", "Investing_Cash_Flow", "Cash_from_Investing", "Cash_From_Investing", "Flux_tresorerie_investissement", "Flux_de_tresorerie_lies_aux_investissements", "Clean_Flux_tresorerie_investiss"]),
    "Financing CF": ("Flux_de_tresorerie_lies_au_financement", ["CF_Financing", "Financing_Cash_Flow", "Cash_from_Financing", "Cash_From_Financing", "Flux_de_tresorerie_lies_au_financement"]),
    "CAPEX": ("Capex", ["Capex", "CAPEX", "Capital_Expenditure", "Capital_Expenditures", "Flux_tresorerie_investissement_CAPEX"]),
    "Free Cash Flow": ("Free_Cash_Flow", ["Free_Cash_Flow", "Levered_Free_Cash_Flow", "Clean_Free_Cash_Flow"]),
    "Dividends Paid": ("Dividendes", ["Clean_Dividendes", "Dividendes", "Dividendes_distribues", "Dividends_Paid", "Dividendes_verses"]),
    "Beginning Cash": ("CFS_Beginning_Cash", ["CFS_Beginning_Cash", "Beginning_Cash", "Tresorerie_debut"]),
    "Ending Cash": ("CFS_Ending_Cash", ["CFS_Ending_Cash", "Ending_Cash", "Tresorerie_fin"]),
}


def _years_from_args(args: argparse.Namespace) -> list[int]:
    if args.years:
        return sorted({int(year) for year in args.years})
    current = dt.date.today().year
    back_years = max(1, int(args.back_years))
    return list(range(current - back_years + 1, current + 1))


def _top_liquid_symbols(db, *, top_n: int) -> list[str]:
    rows = (
        db.query(models.StockMaster.symbol, models.MarketDataStore.adv_20d)
        .join(models.MarketDataStore, models.MarketDataStore.symbol == models.StockMaster.symbol)
        .filter(models.StockMaster.is_active.is_(True))
        .filter(models.StockMaster.market_region == "masi")
        .filter(models.MarketDataStore.timeframe.ilike("1D"))
        .filter(models.MarketDataStore.object_key.is_not(None))
        .order_by(models.MarketDataStore.adv_20d.desc().nullslast(), models.StockMaster.symbol.asc())
        .limit(top_n)
        .all()
    )
    return [str(row[0]).upper() for row in rows]


def _symbol_adv_values(db, symbols: list[str]) -> dict[str, float | None]:
    rows = (
        db.query(models.StockMaster.symbol, models.MarketDataStore.adv_20d)
        .join(models.MarketDataStore, models.MarketDataStore.symbol == models.StockMaster.symbol)
        .filter(models.MarketDataStore.timeframe.ilike("1D"))
        .filter(models.StockMaster.symbol.in_(symbols))
        .order_by(models.StockMaster.symbol.asc())
        .all()
    )
    return {str(symbol).upper(): adv for symbol, adv in rows}


def _metric_presence(db, symbols: list[str], import_ids: list[str], years: list[int]) -> dict[str, dict[int, set[str]]]:
    if not symbols or not import_ids:
        return {}
    metric_names = {metric for _, aliases in THREE_STATEMENT_METRIC_GROUPS.values() for metric in aliases}
    rows = (
        db.query(
            models.FundamentalAnnualMetric.symbol,
            models.FundamentalAnnualMetric.statement_year,
            models.FundamentalAnnualMetric.metric_name,
        )
        .filter(models.FundamentalAnnualMetric.import_id.in_(import_ids))
        .filter(models.FundamentalAnnualMetric.symbol.in_(symbols))
        .filter(models.FundamentalAnnualMetric.statement_year.in_(years))
        .filter(models.FundamentalAnnualMetric.metric_name.in_(metric_names))
        .filter(models.FundamentalAnnualMetric.metric_value.is_not(None))
        .all()
    )
    present: dict[str, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    for symbol, statement_year, metric_name in rows:
        present[str(symbol).upper()][int(statement_year)].add(str(metric_name))
    return present


def _compute_missing(db, symbols: list[str], years: list[int]) -> tuple[dict[str, dict[int, list[str]]], dict[str, float | None], list[str]]:
    snapshots = latest_snapshot_rows_by_symbol(db, symbols=symbols, scope="masi")
    import_ids = [str(snapshot.import_id) for snapshot in snapshots.values() if snapshot is not None]

    present = _metric_presence(db, symbols=symbols, import_ids=import_ids, years=years)
    adv_by_symbol = _symbol_adv_values(db, symbols)
    missing: dict[str, dict[int, list[str]]] = {}
    skipped: list[str] = []

    for symbol in symbols:
        snapshot = snapshots.get(symbol)
        if snapshot is None:
            skipped.append(symbol)
            missing[symbol] = {year: [canonical for canonical, _aliases in THREE_STATEMENT_METRIC_GROUPS.values()] for year in years}
            continue

        symbol_missing: dict[int, list[str]] = {}
        by_year = present.get(symbol, {})
        for year in years:
            available = by_year.get(year, set())
            absent: list[str] = []
            for _label, (canonical_name, aliases) in THREE_STATEMENT_METRIC_GROUPS.items():
                if not available.intersection(set(aliases)):
                    absent.append(canonical_name)
            if absent:
                symbol_missing[year] = absent
        if symbol_missing:
            missing[symbol] = symbol_missing

    return missing, adv_by_symbol, skipped


def _print_report(missing: dict[str, dict[int, list[str]]], adv_by_symbol: dict[str, float | None], skipped: list[str]) -> None:
    if skipped:
        print(f"No active snapshot for {len(skipped)} symbol(s): {', '.join(skipped)}")
    if not missing:
        print("No missing rows detected.")
        return
    total_items = 0
    for symbol in sorted(missing):
        print(f"\n{symbol} (adv20={adv_by_symbol.get(symbol) if adv_by_symbol.get(symbol) is not None else 'N/A'})")
        for year in sorted(missing[symbol]):
            fields = missing[symbol][year]
            total_items += len(fields)
            print(f"  {year}: {', '.join(fields)}")
    print(f"\nSummary: {len(missing)} symbols with gaps, {total_items} missing field-year items.")


def _run_import(db, symbols: list[str], years: list[int], force: bool, dry_run: bool) -> None:
    run = create_import_run(
        db,
        data_source="bvc",
        source_universe="masi",
        filename="targeted_three_statement_fill.xlsx",
        source_hash=f"targeted_bvc_three_statement_{','.join(sorted(symbols))}_{','.join(map(str, years))}",
        summary={
            "purpose": "targeted_three_statement_refresh",
            "symbols": symbols,
            "years": years,
            "only_unseen": not force,
            "force": force,
            "scope": "top40_adv20_masi",
        },
    )
    db.commit()

    if dry_run:
        print(f"[dry-run] would start import_id={run.id} for {len(symbols)} symbols and years {years}")
        return

    result = execute_bvc_fundamental_import(
        str(run.id),
        symbols=symbols,
        period_types=["annual"],
        years=years,
        only_unseen=not force,
        force=force,
    )
    print(f"Import result: {result}")


def _run_targeted_imports(
    db,
    missing: dict[str, dict[int, list[str]]],
    force: bool,
    dry_run: bool,
) -> None:
    for symbol in sorted(missing):
        years = sorted(int(year) for year in missing[symbol] if missing[symbol][year])
        if not years:
            continue
        if dry_run:
            print(f"[dry-run] {symbol}: {len(years)} missing year(s) -> {years}")
        _run_import(db, symbols=[symbol], years=years, force=force, dry_run=dry_run)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run targeted BVC fetch for missing annual three-statement data on most liquid stocks."
    )
    parser.add_argument("--top", type=int, default=40, help="Number of most liquid symbols by adv20 (default: 40)")
    parser.add_argument(
        "--symbols",
        nargs="*",
        help="Explicit symbols to inspect; overrides --top when provided.",
    )
    parser.add_argument("--back-years", type=int, default=5, help="How many latest years to inspect (default: 5)")
    parser.add_argument("--years", nargs="*", type=int, help="Explicit years to target; overrides --back-years")
    parser.add_argument("--apply", action="store_true", help="Run import after generating missing report")
    parser.add_argument("--force", action="store_true", help="Re-run covered docs, not just unseen")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without creating import")
    parser.add_argument("--json", help="Optional path to write missing report as JSON")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    years = _years_from_args(args)

    db = SessionLocal()
    try:
        symbols = (
            sorted({symbol.strip().upper() for symbol in args.symbols if symbol and symbol.strip()})
            if args.symbols
            else _top_liquid_symbols(db, top_n=args.top)
        )
        if not symbols:
            print("No MASI symbols found for top liquid selection.")
            return

        missing, adv_by_symbol, skipped = _compute_missing(db, symbols, years)
        _print_report(missing, adv_by_symbol, skipped)

        if args.json:
            with open(args.json, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "years": years,
                        "symbols": symbols,
                        "missing": {
                            symbol: {str(year): fields for year, fields in by_year.items()}
                            for symbol, by_year in missing.items()
                        },
                    },
                    handle,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            print(f"Wrote missing report to {args.json}")

        if not missing:
            return

        if not args.apply and not args.dry_run:
            print("Run with --apply to execute BVC scrape.")
            return

        if args.apply:
            _run_targeted_imports(db, missing=missing, force=args.force, dry_run=args.dry_run)
    finally:
        db.close()


if __name__ == "__main__":
    main()
