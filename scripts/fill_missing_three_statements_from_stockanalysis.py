from __future__ import annotations

import argparse
import datetime as dt
import math
import sys
import time
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.quant_core.fundamentals.domain import AnnualMetricRow  # noqa: E402
from core.quant_core.fundamentals.providers import ProviderUnavailableError  # noqa: E402
from core.quant_core.fundamentals.providers.stockanalysis_provider import StockAnalysisFundamentalProvider  # noqa: E402
from services.api.app import models  # noqa: E402
from services.api.app.json_sanitize import sanitize_json_compatible  # noqa: E402
from services.api.app.services.fundamentals import (  # noqa: E402
    latest_snapshot_rows_by_symbol,
)
from services.worker.db import SessionLocal  # noqa: E402


YEARS = tuple(range(2021, 2026))
NON_STOCK_SYMBOLS = {"INSTRUMENT", "MAJ", "MAJJ", "WORKSHEET"}

DIRECT_THREE_STATEMENT_METRICS = {
    "Revenue",
    "Chiffre_daffaires",
    "Clean_Chiffre_daffaires",
    "Net_Interest_Income",
    "Provision_for_Loan_Losses",
    "Pretax_Income",
    "Resultat_net",
    "NetIncome",
    "Net_Income",
    "Clean_Resultat_net",
    "Basic_EPS",
    "Diluted_EPS",
    "Total_Actif",
    "Total_Assets",
    "Total_Liabilities",
    "Capitaux_propres",
    "Clean_Capitaux_propres",
    "Total_Equity",
    "Total_Debt",
    "Dettes_de_financement",
    "Cash",
    "Cash_and_Equivalents",
    "Tresorerie_Actif",
    "NetDebt",
    "Net_Debt",
    "Loans_Net",
    "Customer_Deposits",
    "Shares_Outstanding",
    "Book_Value_Per_Share",
    "Operating_Cash_Flow",
    "CF_Operating",
    "CF_Investing",
    "CF_Financing",
    "CF_FX_Effect",
    "Free_Cash_Flow",
    "Capital_Expenditures",
    "Capex",
}

ALIASES_FROM_SOURCE = {
    "Revenue": ("Chiffre_daffaires", "Clean_Chiffre_daffaires"),
    "NetIncome": ("Resultat_net", "Net_Income", "Clean_Resultat_net"),
    "Total_Assets": ("Total_Actif",),
    "Total_Equity": ("Capitaux_propres", "Clean_Capitaux_propres"),
    "Total_Debt": ("Dettes_de_financement",),
    "Cash": ("Cash_and_Equivalents", "Tresorerie_Actif"),
    "CF_Operating": ("Operating_Cash_Flow", "Flux_de_tresorerie_lies_a_lactivite"),
    "Operating_Cash_Flow": ("CF_Operating", "Flux_de_tresorerie_lies_a_lactivite"),
    "CF_Investing": ("Flux_de_tresorerie_lies_aux_investissements",),
    "CF_Financing": ("Flux_de_tresorerie_lies_au_financement",),
    "Capital_Expenditures": ("Capex",),
}


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _selected_symbols(db, requested: list[str]) -> list[str]:
    wanted = sorted({symbol.strip().upper() for symbol in requested if symbol.strip()} - NON_STOCK_SYMBOLS)
    query = db.query(models.StockMaster.symbol).filter(
        models.StockMaster.is_active.is_(True),
        models.StockMaster.market_region == "masi",
        ~models.StockMaster.symbol.in_(NON_STOCK_SYMBOLS),
    )
    if wanted:
        query = query.filter(models.StockMaster.symbol.in_(wanted))
    return [str(row[0]).upper() for row in query.order_by(models.StockMaster.symbol.asc()).all()]


def _stock_rows(db, symbols: list[str]) -> dict[str, models.StockMaster]:
    rows = db.query(models.StockMaster).filter(models.StockMaster.symbol.in_(symbols)).all()
    return {str(row.symbol).upper(): row for row in rows}


def _valid_value(value: Any) -> bool:
    if value is None:
        return False
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(numeric)


def _latest_stockanalysis_rows(db, symbols: list[str]) -> dict[str, list[AnnualMetricRow]]:
    rows = (
        db.query(models.FundamentalAnnualMetric, models.FundamentalImport)
        .join(models.FundamentalImport, models.FundamentalAnnualMetric.import_id == models.FundamentalImport.id)
        .filter(models.FundamentalImport.data_source == "stockanalysis")
        .filter(models.FundamentalImport.status.in_(("succeeded", "partial")))
        .filter(models.FundamentalAnnualMetric.symbol.in_(symbols))
        .filter(models.FundamentalAnnualMetric.statement_year.in_(YEARS))
        .filter(models.FundamentalAnnualMetric.metric_value.isnot(None))
        .order_by(models.FundamentalImport.completed_at.desc().nullslast(), models.FundamentalImport.created_at.desc())
        .all()
    )
    seen: set[tuple[str, int, str]] = set()
    out: dict[str, list[AnnualMetricRow]] = defaultdict(list)
    for metric, import_row in rows:
        key = (str(metric.symbol).upper(), int(metric.statement_year), str(metric.metric_name))
        if key in seen:
            continue
        seen.add(key)
        out[key[0]].append(
            AnnualMetricRow(
                symbol=key[0],
                company_name=metric.company_name,
                statement_year=key[1],
                metric_name=key[2],
                metric_value=metric.metric_value,
                raw_metric_name=metric.raw_metric_name or metric.metric_name,
                source_sheet="stockanalysis_supplement",
                source_field=f"stockanalysis:{metric.source_field or metric.metric_name}",
                is_proxy=False,
                as_of_date=import_row.completed_at.date() if import_row.completed_at else None,
            )
        )
    return out


def _fetch_stockanalysis_rows(symbol: str, stock: models.StockMaster) -> list[AnnualMetricRow]:
    provider = StockAnalysisFundamentalProvider(timeout_seconds=30, retries=2)
    workbook = provider.fetch(
        symbol,
        display_name=stock.display_name,
        market_region=stock.market_region,
        shares_outstanding=stock.shares_outstanding,
    )
    rows: list[AnnualMetricRow] = []
    for row in workbook.annual_metrics:
        if row.statement_year not in YEARS or not _valid_value(row.metric_value):
            continue
        rows.append(
            replace(
                row,
                source_sheet="stockanalysis_supplement",
                source_field=f"stockanalysis:{row.source_field or row.metric_name}",
                as_of_date=_utcnow().date(),
                is_proxy=False,
            )
        )
    return rows


def _expand_rows(rows: list[AnnualMetricRow]) -> list[AnnualMetricRow]:
    by_key: dict[tuple[int, str], AnnualMetricRow] = {}
    for row in rows:
        if row.metric_name in DIRECT_THREE_STATEMENT_METRICS and _valid_value(row.metric_value):
            by_key.setdefault((row.statement_year, row.metric_name), row)
        for alias in ALIASES_FROM_SOURCE.get(row.metric_name, ()):
            if _valid_value(row.metric_value):
                by_key.setdefault(
                    (row.statement_year, alias),
                    replace(
                        row,
                        metric_name=alias,
                        raw_metric_name=row.raw_metric_name or row.metric_name,
                        source_field=f"{row.source_field}|alias:{row.metric_name}->{alias}",
                    ),
                )
    return sorted(by_key.values(), key=lambda row: (row.statement_year, row.metric_name))


def _source_document(db, *, import_id, symbol: str, source_urls: list[str]) -> int | None:
    url = source_urls[0] if source_urls else f"https://stockanalysis.com/quote/cbse/{symbol}/financials/"
    existing = (
        db.query(models.FundamentalSourceDocument)
        .filter(models.FundamentalSourceDocument.import_id == import_id)
        .filter(models.FundamentalSourceDocument.source_url == url)
        .first()
    )
    if existing is not None:
        return int(existing.id)
    doc = models.FundamentalSourceDocument(
        import_id=import_id,
        symbol=symbol,
        company_name=symbol,
        document_title=f"StockAnalysis supplemental three-statement data for {symbol}",
        source_url=url,
        document_kind="stockanalysis",
        publication_date=_utcnow().date(),
        fiscal_year=max(YEARS),
        period_type="annual",
        period_label="FY",
        status="succeeded",
        raw_json=sanitize_json_compatible({"source_urls": source_urls, "supplemental_fill": True}),
    )
    db.add(doc)
    db.flush()
    return int(doc.id) if doc.id is not None else None


def _merge_latest_snapshot_metrics(db, *, import_id, symbols: set[str]) -> int:
    if not symbols:
        return 0
    snapshots = (
        db.query(models.FundamentalLatestSnapshot)
        .filter(models.FundamentalLatestSnapshot.import_id == import_id)
        .filter(models.FundamentalLatestSnapshot.symbol.in_(sorted(symbols)))
        .all()
    )
    updated = 0
    for snapshot in snapshots:
        symbol = str(snapshot.symbol).upper()
        latest_year = snapshot.latest_statement_year
        if latest_year is None:
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
            snapshot.latest_statement_year = int(latest_year)
        rows = (
            db.query(models.FundamentalAnnualMetric)
            .filter(models.FundamentalAnnualMetric.import_id == import_id)
            .filter(models.FundamentalAnnualMetric.symbol == symbol)
            .filter(models.FundamentalAnnualMetric.statement_year == int(latest_year))
            .filter(models.FundamentalAnnualMetric.metric_value.isnot(None))
            .all()
        )
        metrics = dict(snapshot.metrics_json or {})
        added = 0
        for row in rows:
            if metrics.get(row.metric_name) is None:
                metrics[row.metric_name] = row.metric_value
                added += 1
        if not added:
            continue
        coverage = dict(snapshot.coverage_json or {})
        coverage["metric_count"] = sum(value is not None for value in metrics.values())
        coverage["stockanalysis_supplemental_latest_metric_count"] = (
            int(coverage.get("stockanalysis_supplemental_latest_metric_count") or 0) + added
        )
        source = dict(snapshot.source_json or {})
        source["stockanalysis_supplemental_fill"] = {
            "as_of": _utcnow().date().isoformat(),
            "latest_statement_year": int(latest_year),
            "added_latest_metric_count": added,
        }
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


def fill_missing_three_statement_rows(symbols: list[str], *, fetch_missing_source: bool, dry_run: bool) -> dict[str, Any]:
    db = SessionLocal()
    try:
        selected = _selected_symbols(db, symbols)
        stocks = _stock_rows(db, selected)
        active_snapshots = latest_snapshot_rows_by_symbol(db, symbols=selected, scope="masi")
        source_rows = _latest_stockanalysis_rows(db, selected)
        provider_failures: dict[str, str] = {}

        inserted = 0
        filled_null = 0
        skipped_existing = 0
        skipped_no_active = []
        skipped_no_source = []
        touched_import_symbols: dict[Any, set[str]] = defaultdict(set)
        per_symbol: dict[str, dict[str, int]] = {}

        for symbol in selected:
            snapshot = active_snapshots.get(symbol)
            if snapshot is None:
                skipped_no_active.append(symbol)
                continue
            rows = source_rows.get(symbol, [])
            if not rows and fetch_missing_source:
                try:
                    rows = _fetch_stockanalysis_rows(symbol, stocks[symbol])
                except ProviderUnavailableError as exc:
                    provider_failures[symbol] = str(exc)
                    rows = []
                if rows:
                    source_rows[symbol] = rows
            expanded = _expand_rows(rows)
            if not expanded:
                skipped_no_source.append(symbol)
                continue
            if not dry_run:
                touched_import_symbols[snapshot.import_id].add(symbol)

            existing = {
                (int(row.statement_year), str(row.metric_name)): row
                for row in db.query(models.FundamentalAnnualMetric)
                .filter(models.FundamentalAnnualMetric.import_id == snapshot.import_id)
                .filter(models.FundamentalAnnualMetric.symbol == symbol)
                .filter(models.FundamentalAnnualMetric.statement_year.in_(YEARS))
                .all()
            }
            doc_id = None
            symbol_inserted = 0
            symbol_filled_null = 0
            symbol_skipped_existing = 0
            for row in expanded:
                key = (row.statement_year, row.metric_name)
                current = existing.get(key)
                if current is not None and current.metric_value is not None:
                    skipped_existing += 1
                    symbol_skipped_existing += 1
                    continue
                if dry_run:
                    if current is None:
                        inserted += 1
                        symbol_inserted += 1
                    else:
                        filled_null += 1
                        symbol_filled_null += 1
                    continue
                if doc_id is None:
                    doc_id = _source_document(
                        db,
                        import_id=snapshot.import_id,
                        symbol=symbol,
                        source_urls=[
                            f"https://stockanalysis.com/quote/cbse/{symbol}/financials/",
                            f"https://stockanalysis.com/quote/cbse/{symbol}/financials/balance-sheet/",
                            f"https://stockanalysis.com/quote/cbse/{symbol}/financials/cash-flow-statement/",
                        ],
                    )
                if current is None:
                    db.add(
                        models.FundamentalAnnualMetric(
                            import_id=snapshot.import_id,
                            symbol=symbol,
                            company_name=snapshot.company_name or row.company_name or symbol,
                            statement_year=row.statement_year,
                            metric_name=row.metric_name,
                            metric_value=row.metric_value,
                            raw_metric_name=row.raw_metric_name or row.metric_name,
                            source_sheet=row.source_sheet,
                            source_field=row.source_field,
                            is_proxy=False,
                            as_of_date=row.as_of_date,
                            source_document_id=doc_id,
                        )
                    )
                    inserted += 1
                    symbol_inserted += 1
                else:
                    current.metric_value = row.metric_value
                    current.raw_metric_name = row.raw_metric_name or row.metric_name
                    current.source_sheet = row.source_sheet
                    current.source_field = row.source_field
                    current.is_proxy = False
                    current.as_of_date = current.as_of_date or row.as_of_date
                    current.source_document_id = current.source_document_id or doc_id
                    db.add(current)
                    filled_null += 1
                    symbol_filled_null += 1
                touched_import_symbols[snapshot.import_id].add(symbol)
            per_symbol[symbol] = {
                "inserted": symbol_inserted,
                "filled_null": symbol_filled_null,
                "skipped_existing": symbol_skipped_existing,
            }

        refreshed_snapshots = 0
        if not dry_run:
            db.flush()
            for import_id, item_symbols in touched_import_symbols.items():
                refreshed_snapshots += _merge_latest_snapshot_metrics(db, import_id=import_id, symbols=item_symbols)
                run = db.get(models.FundamentalImport, import_id)
                if run is not None:
                    run.annual_metric_count = (
                        db.query(models.FundamentalAnnualMetric)
                        .filter(models.FundamentalAnnualMetric.import_id == import_id)
                        .count()
                    )
                    summary = dict(run.summary_json or {})
                    fills = dict(summary.get("stockanalysis_supplemental_fill") or {})
                    fills[_utcnow().isoformat()] = {
                        "symbols": sorted(item_symbols),
                        "years": list(YEARS),
                    }
                    summary["stockanalysis_supplemental_fill"] = fills
                    run.summary_json = sanitize_json_compatible(summary)
                    db.add(run)
            db.commit()

        return {
            "dry_run": dry_run,
            "selected_symbols": len(selected),
            "inserted": inserted,
            "filled_null": filled_null,
            "skipped_existing": skipped_existing,
            "refreshed_snapshots": refreshed_snapshots,
            "touched_imports": {str(import_id): sorted(items) for import_id, items in touched_import_symbols.items()},
            "skipped_no_active": skipped_no_active,
            "skipped_no_source": skipped_no_source,
            "provider_failures": provider_failures,
            "per_symbol": per_symbol,
        }
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill missing/null 2021-2025 active three-statement rows from StockAnalysis without overwriting existing values.")
    parser.add_argument("symbols", nargs="*", help="Optional MASI symbols. Default: all active MASI symbols.")
    parser.add_argument("--no-fetch", action="store_true", help="Use only StockAnalysis rows already in the database.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    started = time.perf_counter()
    result = fill_missing_three_statement_rows(args.symbols, fetch_missing_source=not args.no_fetch, dry_run=args.dry_run)
    result["elapsed_seconds"] = round(time.perf_counter() - started, 2)
    print(result)


if __name__ == "__main__":
    main()
