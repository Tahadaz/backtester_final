from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy.orm.attributes import flag_modified

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.api.app import models
from services.api.app.json_sanitize import sanitize_json_compatible
from services.api.app.services.fundamentals import latest_snapshot_rows_by_symbol
from services.worker.db import SessionLocal


AUDIT_DIR = ROOT / "data" / "stockanalysis_period_backfill_audits"
NON_STOCK_SYMBOLS = {"INSTRUMENT", "MAJ", "MAJJ", "WORKSHEET"}

# H2 = FY - H1 is valid for period flow / P&L metrics. Do not use it for
# balance-sheet stock metrics such as assets, debt, equity, cash, inventory.
DERIVABLE_H2_METRICS = {
    "Revenue",
    "Clean_Chiffre_daffaires",
    "Chiffre_daffaires",
    "Cost_of_Revenue",
    "Gross_Profit",
    "Marge_Brute",
    "Operating_Expenses",
    "EBITDA",
    "Excedent_brut_dexploitation",
    "EBIT",
    "Resultat_dexploitation",
    "Depreciation_Amortization",
    "DandA",
    "Dotations_dexploitation",
    "NetIncome",
    "Net_Income",
    "Clean_Resultat_net",
    "Resultat_net",
    "Income_Tax_Expense",
    "Impots_sur_les_resultats",
    "Interest_Expense",
    "Charges_Interets",
    "CFS_Net_Income_Top_Of_CFS",
    "Operating_Cash_Flow",
    "CF_Operating",
    "CF_Investing",
    "CF_Financing",
    "Capital_Expenditures",
    "Free_Cash_Flow",
    "Common_Dividends_Paid",
    "Change_in_Working_Capital",
    "Variation_du_besoin_de_financement_global",
}


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _active_masi_symbols(db, requested: list[str] | None) -> list[str]:
    query = (
        db.query(models.StockMaster.symbol)
        .filter(models.StockMaster.market_region == "masi")
        .filter(models.StockMaster.is_active.is_(True))
        .filter(~models.StockMaster.symbol.in_(sorted(NON_STOCK_SYMBOLS)))
    )
    if requested:
        query = query.filter(models.StockMaster.symbol.in_(sorted({symbol.upper() for symbol in requested})))
    return [str(row[0]).upper() for row in query.order_by(models.StockMaster.symbol.asc()).all()]


def _source_url(symbol: str, year: int) -> str:
    return f"https://stockanalysis.com/quote/cbse/{symbol}/financials/#derived-h2-fy-minus-h1-{year}"


def _source_document(db, *, import_id: Any, symbol: str, company_name: str, year: int, annual_doc_ids: set[int]) -> int | None:
    url = _source_url(symbol, year)
    existing = (
        db.query(models.FundamentalSourceDocument)
        .filter(models.FundamentalSourceDocument.import_id == import_id)
        .filter(models.FundamentalSourceDocument.source_url == url)
        .filter(models.FundamentalSourceDocument.symbol == symbol)
        .first()
    )
    raw_json = sanitize_json_compatible(
        {
            "stockanalysis_h2_derivation": "FY - H1",
            "annual_source_document_ids": sorted(annual_doc_ids),
        }
    )
    if existing is not None:
        existing.status = "succeeded"
        existing.error_message = None
        existing.extracted_field_count = max(int(existing.extracted_field_count or 0), len(annual_doc_ids))
        existing.raw_json = sanitize_json_compatible({**dict(existing.raw_json or {}), **raw_json})
        flag_modified(existing, "raw_json")
        db.add(existing)
        db.flush()
        return int(existing.id) if existing.id is not None else None
    document = models.FundamentalSourceDocument(
        import_id=import_id,
        symbol=symbol,
        company_name=company_name,
        document_title="StockAnalysis H2 derived from FY minus H1",
        source_url=url,
        document_kind="sa_h2_derived",
        publication_date=_utcnow().date(),
        fiscal_year=year,
        period_type="semiannual",
        period_label="H2",
        period_end_date=dt.date(year, 12, 31),
        status="succeeded",
        extracted_field_count=len(annual_doc_ids),
        raw_json=raw_json,
    )
    db.add(document)
    db.flush()
    return int(document.id) if document.id is not None else None


def _refresh_snapshot_period_coverage(db, *, import_id: Any, symbol: str) -> None:
    snapshot = (
        db.query(models.FundamentalLatestSnapshot)
        .filter(models.FundamentalLatestSnapshot.import_id == import_id)
        .filter(models.FundamentalLatestSnapshot.symbol == symbol)
        .first()
    )
    if snapshot is None:
        return
    rows = (
        db.query(models.FundamentalPeriodMetric)
        .filter(models.FundamentalPeriodMetric.import_id == import_id)
        .filter(models.FundamentalPeriodMetric.symbol == symbol)
        .filter(models.FundamentalPeriodMetric.metric_value.isnot(None))
        .all()
    )
    period_types = sorted({str(row.period_type) for row in rows if row.period_type})
    coverage = dict(snapshot.coverage_json or {})
    source = dict(snapshot.source_json or {})
    coverage["period_metric_count"] = len(rows)
    coverage["period_types"] = period_types
    coverage["has_quarterly_period_metrics"] = "quarterly" in period_types
    coverage["has_semiannual_period_metrics"] = "semiannual" in period_types
    source["stockanalysis_h2_derivation"] = {
        "as_of": _utcnow().date().isoformat(),
        "method": "FY - H1",
    }
    snapshot.coverage_json = sanitize_json_compatible(coverage)
    snapshot.source_json = sanitize_json_compatible(source)
    flag_modified(snapshot, "coverage_json")
    flag_modified(snapshot, "source_json")
    db.add(snapshot)


def derive_h2_period_metrics(symbols: list[str] | None, *, min_year: int, dry_run: bool) -> dict[str, Any]:
    db = SessionLocal()
    try:
        selected = _active_masi_symbols(db, symbols)
        snapshots = latest_snapshot_rows_by_symbol(db, symbols=selected, scope="masi")
        import_symbols = [(row.import_id, row.symbol) for row in snapshots.values()]

        annual_values: dict[tuple[Any, str, int], dict[str, tuple[float, int | None]]] = defaultdict(dict)
        annual_rows = (
            db.query(models.FundamentalAnnualMetric)
            .filter(models.FundamentalAnnualMetric.statement_year >= min_year)
            .filter(models.FundamentalAnnualMetric.metric_name.in_(sorted(DERIVABLE_H2_METRICS)))
            .filter(models.FundamentalAnnualMetric.metric_value.isnot(None))
            .all()
        )
        allowed = set(import_symbols)
        for row in annual_rows:
            key = (row.import_id, str(row.symbol).upper())
            if key not in allowed:
                continue
            annual_values[(row.import_id, str(row.symbol).upper(), int(row.statement_year))][str(row.metric_name)] = (
                float(row.metric_value),
                int(row.source_document_id) if row.source_document_id is not None else None,
            )

        existing_period_keys: set[tuple[Any, str, int, str]] = set()
        all_period_rows = (
            db.query(models.FundamentalPeriodMetric.import_id, models.FundamentalPeriodMetric.symbol, models.FundamentalPeriodMetric.fiscal_year, models.FundamentalPeriodMetric.period_label)
            .filter(models.FundamentalPeriodMetric.period_type == "semiannual")
            .filter(models.FundamentalPeriodMetric.fiscal_year >= min_year)
            .all()
        )
        for import_id, symbol, fiscal_year, period_label in all_period_rows:
            key = (import_id, str(symbol).upper())
            if key in allowed:
                existing_period_keys.add((import_id, str(symbol).upper(), int(fiscal_year), str(period_label)))

        period_values: dict[tuple[Any, str, int, str], dict[str, models.FundamentalPeriodMetric]] = defaultdict(dict)
        period_rows = (
            db.query(models.FundamentalPeriodMetric)
            .filter(models.FundamentalPeriodMetric.period_type == "semiannual")
            .filter(models.FundamentalPeriodMetric.fiscal_year >= min_year)
            .filter(models.FundamentalPeriodMetric.metric_name.in_(sorted(DERIVABLE_H2_METRICS)))
            .filter(models.FundamentalPeriodMetric.metric_value.isnot(None))
            .all()
        )
        for row in period_rows:
            key = (row.import_id, str(row.symbol).upper())
            if key not in allowed:
                continue
            period_values[(row.import_id, str(row.symbol).upper(), int(row.fiscal_year), str(row.period_label))][str(row.metric_name)] = row

        inserted = 0
        skipped_existing = 0
        candidates = []
        docs_by_symbol_year: dict[tuple[Any, str, int], int | None] = {}
        for (import_id, symbol, year), fy_metrics in annual_values.items():
            h1 = period_values.get((import_id, symbol, year, "H1"), {})
            h2 = period_values.get((import_id, symbol, year, "H2"), {})
            if not h1:
                continue
            if (import_id, symbol, year, "H2") not in existing_period_keys:
                continue
            annual_doc_ids = {doc_id for _value, doc_id in fy_metrics.values() if doc_id is not None}
            period_end = next((row.period_end_date for row in h2.values() if row.period_end_date is not None), dt.date(year, 12, 31))
            company_name = next((row.company_name for row in h1.values() if row.company_name), symbol)
            for metric_name, (fy_value, _doc_id) in fy_metrics.items():
                h1_row = h1.get(metric_name)
                if h1_row is None:
                    continue
                if metric_name in h2:
                    skipped_existing += 1
                    continue
                h2_value = fy_value - float(h1_row.metric_value)
                candidates.append((import_id, symbol, year, company_name, period_end, metric_name, h2_value, annual_doc_ids))

        if not dry_run:
            for import_id, symbol, year, company_name, period_end, metric_name, h2_value, annual_doc_ids in candidates:
                doc_key = (import_id, symbol, year)
                if doc_key not in docs_by_symbol_year:
                    docs_by_symbol_year[doc_key] = _source_document(
                        db,
                        import_id=import_id,
                        symbol=symbol,
                        company_name=company_name,
                        year=year,
                        annual_doc_ids=annual_doc_ids,
                    )
                db.add(
                    models.FundamentalPeriodMetric(
                        import_id=import_id,
                        source_document_id=docs_by_symbol_year[doc_key],
                        symbol=symbol,
                        company_name=company_name,
                        fiscal_year=year,
                        period_type="semiannual",
                        period_label="H2",
                        period_end_date=period_end,
                        metric_name=metric_name,
                        metric_value=float(h2_value),
                        raw_metric_name="derived:FY-H1",
                        source_url=_source_url(symbol, year),
                        document_title="StockAnalysis H2 derived from FY minus H1",
                        is_proxy=True,
                    )
                )
                inserted += 1
            for snapshot in snapshots.values():
                _refresh_snapshot_period_coverage(db, import_id=snapshot.import_id, symbol=snapshot.symbol)
            db.commit()

        result = {
            "dry_run": dry_run,
            "symbol_count": len(selected),
            "selected_symbols": selected,
            "candidate_count": len(candidates),
            "inserted": inserted,
            "skipped_existing": skipped_existing,
            "candidate_by_symbol": dict(Counter(item[1] for item in candidates)),
            "candidate_by_metric": dict(Counter(item[5] for item in candidates)),
        }
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        audit_path = AUDIT_DIR / f"stockanalysis_h2_derivation_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        audit_path.write_text(json.dumps(sanitize_json_compatible(result), indent=2, sort_keys=True), encoding="utf-8")
        result["audit_path"] = str(audit_path)
        return result
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Derive missing StockAnalysis H2 period metrics from real FY and H1 values.")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols. Default: all active MASI symbols.")
    parser.add_argument("--min-year", type=int, default=2021)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()] or None
    result = derive_h2_period_metrics(symbols, min_year=int(args.min_year), dry_run=bool(args.dry_run))
    print(json.dumps(sanitize_json_compatible(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
