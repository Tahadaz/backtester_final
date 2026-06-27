from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy.orm.attributes import flag_modified

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.quant_core.fundamentals.domain import AnnualMetricRow
from core.quant_core.fundamentals.providers import ProviderUnavailableError
from core.quant_core.fundamentals.providers.stockanalysis_provider import StockAnalysisFundamentalProvider
from services.api.app import models
from services.api.app.json_sanitize import sanitize_json_compatible
from services.api.app.services.fundamental_signal_engine import upsert_fundamental_signal_rows
from services.api.app.services.fundamentals import (
    _build_integrity_reports,
    _load_history,
    _persist_integrity_reports,
    _scope_for_symbols,
    latest_snapshot_rows_by_symbol,
    make_bulk_overrides_loader,
    persist_pillar_history_for_import,
    recompute_symbol_valuations_all_scenarios,
    rescore_universe,
)
from services.worker.db import SessionLocal


YEARS = tuple(range(2021, 2026))
DEFAULT_SYMBOLS = ("ATW", "IAM", "MSA", "BCP", "BOA")
AUDIT_DIR = ROOT / "data" / "stockanalysis_real_backfill_audits"
SOURCE_SHEET = "stockanalysis_real"
OLD_DETERMINISTIC_SHEETS = {
    "bvc_deterministic_pdf",
    "bvc_deterministic_proxy",
    "bvc_deterministic_integrity_repair",
}

REQUIRED_GROUPS: dict[str, tuple[str, ...]] = {
    "Revenue": ("Revenue", "Chiffre_daffaires", "Clean_Chiffre_daffaires"),
    "Gross_Profit": ("Gross_Profit", "Marge_Brute", "Marge_brute"),
    "EBITDA": ("EBITDA", "Excedent_brut_dexploitation"),
    "DandA": ("DandA", "Depreciation_Amortization", "Dotations_dexploitation"),
    "EBIT": ("EBIT", "Resultat_dexploitation", "Resultat_Exploitation"),
    "Interest_or_Financial_Result": (
        "Interest_Expense",
        "Charges_Interets",
        "Net_Interest_Expense",
        "Resultat_financier",
        "Net_Interest_Income",
    ),
    "Income_Tax": ("Income_Tax_Expense", "Impots_sur_les_resultats"),
    "NetIncome": ("NetIncome", "Net_Income", "Resultat_net", "Clean_Resultat_net"),
    "Total_Assets": ("Total_Assets", "Total_Actif"),
    "Current_Assets": ("Current_Assets", "Actif_circulant"),
    "Cash": ("Cash", "Cash_and_Equivalents", "Tresorerie_Actif", "CFS_Ending_Cash"),
    "Total_Liabilities": ("Total_Liabilities", "Total_Passif"),
    "Current_Liabilities": ("Current_Liabilities", "Passif_circulant"),
    "Total_Debt": ("Total_Debt", "Debt_Total", "Dettes_de_financement"),
    "Net_Debt": ("NetDebt", "Net_Debt"),
    "Total_Equity": ("Total_Equity", "Equity", "Capitaux_propres", "Clean_Capitaux_propres"),
    "Retained_Earnings": ("Retained_Earnings", "Reserves"),
    "Inventory": ("Inventory", "Stocks"),
    "Receivables": ("Accounts_Receivable", "Creances_de_lactif_circulant"),
    "Payables": ("Accounts_Payable", "Dettes_du_passif_circulant"),
    "Operating_CF": ("Operating_Cash_Flow", "CF_Operating", "Flux_de_tresorerie_lies_a_lactivite"),
    "Investing_CF": ("CF_Investing", "Flux_de_tresorerie_lies_aux_investissements"),
    "Financing_CF": ("CF_Financing", "Flux_de_tresorerie_lies_au_financement"),
    "Capex": ("Capex", "Capital_Expenditures", "Flux_tresorerie_investissement_CAPEX"),
    "Free_Cash_Flow": ("Free_Cash_Flow",),
    "Dividends": ("Dividendes", "Dividends_Paid", "Clean_Dividendes"),
    "Working_Capital_or_Delta": (
        "Working_Capital",
        "Change_in_Working_Capital",
        "Variation_du_besoin_de_financement_global",
    ),
    "CAF": ("CAF", "Capacite_dautofinancement"),
    "Beginning_Cash": ("CFS_Beginning_Cash", "Beginning_Cash"),
    "Ending_Cash": ("CFS_Ending_Cash", "Ending_Cash", "Cash", "Cash_and_Equivalents", "Tresorerie_Actif"),
    "CFS_NetIncome_Top": ("CFS_Net_Income_Top_Of_CFS",),
}
CORE_REPLACED_METRICS = {metric for aliases in REQUIRED_GROUPS.values() for metric in aliases}


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _valid_value(value: Any) -> bool:
    if value is None:
        return False
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(numeric)


def _stock_rows(db, symbols: Iterable[str]) -> dict[str, models.StockMaster]:
    rows = db.query(models.StockMaster).filter(models.StockMaster.symbol.in_([s.upper() for s in symbols])).all()
    return {str(row.symbol).upper(): row for row in rows}


def _fetch_source_rows(symbol: str, stock: models.StockMaster | None) -> tuple[list[AnnualMetricRow], dict[str, Any]]:
    provider = StockAnalysisFundamentalProvider(timeout_seconds=30, retries=2)
    workbook = provider.fetch(
        symbol,
        display_name=(stock.display_name if stock is not None else symbol),
        market_region=(stock.market_region if stock is not None else "masi"),
        shares_outstanding=(stock.shares_outstanding if stock is not None else None),
    )
    rows: list[AnnualMetricRow] = []
    today = _utcnow().date()
    for row in workbook.annual_metrics:
        if row.statement_year not in YEARS or not _valid_value(row.metric_value):
            continue
        rows.append(
            replace(
                row,
                source_sheet=SOURCE_SHEET,
                source_field=f"stockanalysis:{row.source_field or row.metric_name}",
                is_proxy=False,
                as_of_date=today,
            )
        )
    return rows, sanitize_json_compatible(workbook.summary or {})


def _source_document(db, *, import_id: Any, symbol: str, summary: dict[str, Any]) -> int | None:
    urls = list(summary.get("source_urls") or [])
    url = urls[0] if urls else f"https://stockanalysis.com/quote/cbse/{symbol}/financials/"
    existing = (
        db.query(models.FundamentalSourceDocument)
        .filter(models.FundamentalSourceDocument.import_id == import_id)
        .filter(models.FundamentalSourceDocument.source_url == url)
        .first()
    )
    if existing is not None:
        existing.status = "succeeded"
        existing.raw_json = sanitize_json_compatible({"source_urls": urls, "source": "stockanalysis", "replacement": True})
        flag_modified(existing, "raw_json")
        db.add(existing)
        db.flush()
        return int(existing.id) if existing.id is not None else None
    doc = models.FundamentalSourceDocument(
        import_id=import_id,
        symbol=symbol,
        company_name=symbol,
        document_title=f"StockAnalysis real annual financial statements for {symbol}",
        source_url=url,
        document_kind="stockanalysis",
        publication_date=_utcnow().date(),
        fiscal_year=max(YEARS),
        period_type="annual",
        period_label="FY",
        status="succeeded",
        extracted_field_count=0,
        raw_json=sanitize_json_compatible({"source_urls": urls, "source": "stockanalysis", "replacement": True}),
    )
    db.add(doc)
    db.flush()
    return int(doc.id) if doc.id is not None else None


def _delete_stale_replaced_rows(db, *, import_id: Any, symbol: str) -> tuple[int, set[str]]:
    rows = (
        db.query(models.FundamentalAnnualMetric)
        .filter(models.FundamentalAnnualMetric.import_id == import_id)
        .filter(models.FundamentalAnnualMetric.symbol == symbol)
        .filter(models.FundamentalAnnualMetric.statement_year.in_(YEARS))
        .all()
    )
    rows = [
        row
        for row in rows
        if (
            row.source_sheet in OLD_DETERMINISTIC_SHEETS
            or bool(row.is_proxy)
        )
    ]
    metric_names = {str(row.metric_name) for row in rows}
    for row in rows:
        db.delete(row)
    return len(rows), metric_names


def _can_stockanalysis_fill_existing(row: models.FundamentalAnnualMetric) -> bool:
    if row.metric_value is None:
        return True
    if bool(row.is_proxy):
        return True
    source_sheet = str(row.source_sheet or "")
    return source_sheet in OLD_DETERMINISTIC_SHEETS or source_sheet in {"stockanalysis", "stockanalysis_supplement", SOURCE_SHEET}


def _upsert_real_rows(db, *, import_id: Any, symbol: str, rows: list[AnnualMetricRow], doc_id: int | None) -> dict[str, int]:
    existing = {
        (int(row.statement_year), str(row.metric_name)): row
        for row in (
            db.query(models.FundamentalAnnualMetric)
            .filter(models.FundamentalAnnualMetric.import_id == import_id)
            .filter(models.FundamentalAnnualMetric.symbol == symbol)
            .filter(models.FundamentalAnnualMetric.statement_year.in_(YEARS))
            .all()
        )
    }
    inserted = updated = unchanged = preserved_existing = 0
    for row in rows:
        key = (int(row.statement_year), str(row.metric_name))
        current = existing.get(key)
        value = float(row.metric_value)
        if current is None:
            db.add(
                models.FundamentalAnnualMetric(
                    import_id=import_id,
                    symbol=symbol,
                    company_name=row.company_name or symbol,
                    statement_year=int(row.statement_year),
                    metric_name=row.metric_name,
                    metric_value=value,
                    raw_metric_name=row.raw_metric_name or row.metric_name,
                    source_sheet=SOURCE_SHEET,
                    source_field=row.source_field,
                    is_proxy=False,
                    as_of_date=row.as_of_date,
                    source_document_id=doc_id,
                )
            )
            inserted += 1
            continue
        if not _can_stockanalysis_fill_existing(current):
            preserved_existing += 1
            continue
        same_value = current.metric_value is not None and abs(float(current.metric_value) - value) <= max(abs(value), 1.0) * 1e-10
        same_lineage = current.source_sheet == SOURCE_SHEET and not bool(current.is_proxy)
        if same_value and same_lineage:
            unchanged += 1
            continue
        current.metric_value = value
        current.raw_metric_name = row.raw_metric_name or row.metric_name
        current.source_sheet = SOURCE_SHEET
        current.source_field = row.source_field
        current.is_proxy = False
        current.as_of_date = row.as_of_date or current.as_of_date
        current.source_document_id = doc_id or current.source_document_id
        db.add(current)
        updated += 1
    db.flush()
    return {"inserted": inserted, "updated": updated, "unchanged": unchanged, "preserved_existing": preserved_existing}


def _refresh_snapshots_without_stale_metrics(
    db,
    *,
    import_id: Any,
    symbols: Iterable[str],
    removed_metrics_by_symbol: dict[str, set[str]],
) -> int:
    updated = 0
    for snapshot in (
        db.query(models.FundamentalLatestSnapshot)
        .filter(models.FundamentalLatestSnapshot.import_id == import_id)
        .filter(models.FundamentalLatestSnapshot.symbol.in_(sorted({s.upper() for s in symbols})))
        .all()
    ):
        symbol = str(snapshot.symbol).upper()
        latest_year = (
            db.query(models.FundamentalAnnualMetric.statement_year)
            .filter(models.FundamentalAnnualMetric.import_id == import_id)
            .filter(models.FundamentalAnnualMetric.symbol == symbol)
            .filter(models.FundamentalAnnualMetric.metric_value.isnot(None))
            .order_by(models.FundamentalAnnualMetric.statement_year.desc())
            .limit(1)
            .scalar()
        )
        if latest_year is None:
            continue
        latest_rows = (
            db.query(models.FundamentalAnnualMetric)
            .filter(models.FundamentalAnnualMetric.import_id == import_id)
            .filter(models.FundamentalAnnualMetric.symbol == symbol)
            .filter(models.FundamentalAnnualMetric.statement_year == int(latest_year))
            .filter(models.FundamentalAnnualMetric.metric_value.isnot(None))
            .all()
        )
        metrics = dict(snapshot.metrics_json or {})
        for metric_name in removed_metrics_by_symbol.get(symbol, set()):
            metrics.pop(metric_name, None)
        for row in latest_rows:
            metrics[str(row.metric_name)] = row.metric_value
        coverage = dict(snapshot.coverage_json or {})
        source = dict(snapshot.source_json or {})
        coverage["metric_count"] = sum(value is not None for value in metrics.values())
        coverage["stockanalysis_real_replacement_latest_metric_count"] = len(latest_rows)
        source["stockanalysis_real_replacement"] = {
            "as_of": _utcnow().date().isoformat(),
            "latest_statement_year": int(latest_year),
            "removed_stale_metric_count": len(removed_metrics_by_symbol.get(symbol, set())),
        }
        snapshot.latest_statement_year = int(latest_year)
        snapshot.metrics_json = sanitize_json_compatible(metrics)
        snapshot.coverage_json = sanitize_json_compatible(coverage)
        snapshot.source_json = sanitize_json_compatible(source)
        snapshot.updated_at = _utcnow()
        flag_modified(snapshot, "metrics_json")
        flag_modified(snapshot, "coverage_json")
        flag_modified(snapshot, "source_json")
        db.add(snapshot)
        updated += 1
    db.flush()
    return updated


def _missing_groups(rows: Iterable[AnnualMetricRow], symbols: Iterable[str], years: Iterable[int]) -> dict[str, dict[int, list[str]]]:
    present: dict[str, dict[int, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in rows:
        if row.metric_value is None:
            continue
        present[row.symbol.upper()][int(row.statement_year)].add(row.metric_name)
    missing: dict[str, dict[int, list[str]]] = {}
    for symbol in sorted({symbol.upper() for symbol in symbols}):
        for year in sorted(set(years)):
            names = present[symbol][year]
            gaps = [group for group, aliases in REQUIRED_GROUPS.items() if not names.intersection(aliases)]
            if gaps:
                missing.setdefault(symbol, {})[year] = gaps
    return missing


def _existing_rows(db, *, import_id: Any, symbols: Iterable[str]) -> list[AnnualMetricRow]:
    out: list[AnnualMetricRow] = []
    for row in (
        db.query(models.FundamentalAnnualMetric)
        .filter(models.FundamentalAnnualMetric.import_id == import_id)
        .filter(models.FundamentalAnnualMetric.symbol.in_(sorted({s.upper() for s in symbols})))
        .filter(models.FundamentalAnnualMetric.statement_year.in_(YEARS))
        .filter(models.FundamentalAnnualMetric.metric_value.isnot(None))
        .all()
    ):
        out.append(
            AnnualMetricRow(
                symbol=str(row.symbol).upper(),
                company_name=row.company_name,
                statement_year=int(row.statement_year),
                metric_name=str(row.metric_name),
                metric_value=row.metric_value,
                raw_metric_name=row.raw_metric_name,
                source_sheet=row.source_sheet,
                source_field=row.source_field,
                is_proxy=bool(row.is_proxy),
                as_of_date=row.as_of_date,
                source_document_id=row.source_document_id,
            )
        )
    return out


def _refresh_downstream(db, symbols: list[str], import_ids_by_symbol: dict[str, Any]) -> dict[str, Any]:
    scope = _scope_for_symbols(db, symbols)
    overrides_loader = make_bulk_overrides_loader(db, symbols)
    snapshots = latest_snapshot_rows_by_symbol(db, symbols=symbols, scope="masi")
    rescored = rescore_universe(db, scope=scope)
    for import_id in sorted(set(import_ids_by_symbol.values()), key=str):
        persist_pillar_history_for_import(db, import_id=import_id)
    valuation_rows = 0
    for symbol in symbols:
        snapshot = snapshots.get(symbol)
        if snapshot is None:
            continue
        valuation_rows += len(recompute_symbol_valuations_all_scenarios(db, symbol=symbol, import_id=snapshot.import_id))
    signal_result = upsert_fundamental_signal_rows(db, symbols=symbols)
    db.flush()
    return {
        "rescored_snapshot_count": rescored,
        "valuation_row_count": valuation_rows,
        "signal_rows": signal_result,
    }


def replace_with_stockanalysis(symbols: list[str], *, dry_run: bool) -> dict[str, Any]:
    symbols = [symbol.upper() for symbol in symbols]
    db = SessionLocal()
    try:
        snapshots = latest_snapshot_rows_by_symbol(db, symbols=symbols, scope="masi")
        missing_active = sorted(set(symbols) - set(snapshots))
        stocks = _stock_rows(db, symbols)
        import_ids = {symbol: snapshots[symbol].import_id for symbol in symbols if symbol in snapshots}

        fetched_rows: dict[str, list[AnnualMetricRow]] = {}
        fetch_summaries: dict[str, dict[str, Any]] = {}
        fetch_errors: dict[str, str] = {}
        for symbol in symbols:
            try:
                rows, summary = _fetch_source_rows(symbol, stocks.get(symbol))
            except ProviderUnavailableError as exc:
                fetch_errors[symbol] = str(exc)
                continue
            fetched_rows[symbol] = rows
            fetch_summaries[symbol] = summary

        before_rows: list[AnnualMetricRow] = []
        for import_id in sorted(set(import_ids.values()), key=str):
            import_symbols = [symbol for symbol, item_import_id in import_ids.items() if item_import_id == import_id]
            before_rows.extend(_existing_rows(db, import_id=import_id, symbols=import_symbols))
        source_missing = _missing_groups([row for rows in fetched_rows.values() for row in rows], symbols, YEARS)

        write_summary: dict[str, Any] = {}
        removed_metrics_by_import_symbol: dict[Any, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        if not dry_run:
            for symbol, rows in fetched_rows.items():
                snapshot = snapshots.get(symbol)
                if snapshot is None:
                    continue
                doc_id = _source_document(db, import_id=snapshot.import_id, symbol=symbol, summary=fetch_summaries.get(symbol, {}))
                deleted, removed_metric_names = _delete_stale_replaced_rows(db, import_id=snapshot.import_id, symbol=symbol)
                removed_metrics_by_import_symbol[snapshot.import_id][symbol].update(removed_metric_names)
                counts = _upsert_real_rows(db, import_id=snapshot.import_id, symbol=symbol, rows=rows, doc_id=doc_id)
                write_summary[symbol] = {
                    "import_id": str(snapshot.import_id),
                    "fetched_rows": len(rows),
                    "deleted_stale_replaced_rows": deleted,
                    **counts,
                }

            for import_id, symbol_metrics in removed_metrics_by_import_symbol.items():
                import_symbols = set(symbol_metrics)
                _refresh_snapshots_without_stale_metrics(
                    db,
                    import_id=import_id,
                    symbols=import_symbols,
                    removed_metrics_by_symbol=symbol_metrics,
                )
                history = [
                    row
                    for row in _load_history(db, import_id)
                    if row.symbol.upper() in import_symbols and row.statement_year in YEARS
                ]
                _persist_integrity_reports(db, import_id=import_id, reports=_build_integrity_reports(history))
                run = db.get(models.FundamentalImport, import_id)
                if run is not None:
                    run.annual_metric_count = (
                        db.query(models.FundamentalAnnualMetric)
                        .filter(models.FundamentalAnnualMetric.import_id == import_id)
                        .count()
                    )
                    summary = dict(run.summary_json or {})
                    summary["stockanalysis_real_replacement"] = {
                        "symbols": sorted(import_symbols),
                        "years": list(YEARS),
                        "completed_at": _utcnow().isoformat(),
                    }
                    run.summary_json = sanitize_json_compatible(summary)
                    flag_modified(run, "summary_json")
                    db.add(run)
            db.commit()
            downstream = _refresh_downstream(db, [s for s in symbols if s in snapshots], import_ids)
            db.commit()
        else:
            downstream = {"dry_run": True}

        after_rows: list[AnnualMetricRow] = []
        for import_id in sorted(set(import_ids.values()), key=str):
            import_symbols = [symbol for symbol, item_import_id in import_ids.items() if item_import_id == import_id]
            after_rows.extend(_existing_rows(db, import_id=import_id, symbols=import_symbols))
        after_missing = _missing_groups(after_rows, symbols, YEARS)
        old_rows_remaining = {}
        for symbol, snapshot in snapshots.items():
            old_rows_remaining[symbol] = (
                db.query(models.FundamentalAnnualMetric)
                .filter(models.FundamentalAnnualMetric.import_id == snapshot.import_id)
                .filter(models.FundamentalAnnualMetric.symbol == symbol)
                .filter(models.FundamentalAnnualMetric.statement_year.in_(YEARS))
                .filter(models.FundamentalAnnualMetric.source_sheet.in_(sorted(OLD_DETERMINISTIC_SHEETS)))
                .count()
            )

        result = {
            "dry_run": dry_run,
            "symbols": symbols,
            "years": list(YEARS),
            "missing_active": missing_active,
            "fetch_errors": fetch_errors,
            "source_missing": source_missing,
            "before_missing": _missing_groups(before_rows, symbols, YEARS),
            "after_missing": after_missing,
            "old_deterministic_rows_remaining": old_rows_remaining,
            "write_summary": write_summary,
            "downstream": downstream,
            "source_urls": {
                symbol: fetch_summaries.get(symbol, {}).get("source_urls", [])
                for symbol in symbols
            },
        }
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        audit_path = AUDIT_DIR / f"top5_stockanalysis_real_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        audit_path.write_text(json.dumps(sanitize_json_compatible(result), indent=2, sort_keys=True), encoding="utf-8")
        result["audit_path"] = str(audit_path)
        return result
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Replace top-five deterministic/proxy fundamentals with real StockAnalysis CBSE rows.")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS), help="Comma-separated MASI symbols.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    result = replace_with_stockanalysis(symbols, dry_run=bool(args.dry_run))
    print(json.dumps(sanitize_json_compatible(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
