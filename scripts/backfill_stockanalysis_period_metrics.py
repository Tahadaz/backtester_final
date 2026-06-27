from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy.orm.attributes import flag_modified

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.quant_core.fundamentals.domain import PeriodMetricRow
from core.quant_core.fundamentals.providers import ProviderUnavailableError
from core.quant_core.fundamentals.providers.stockanalysis_provider import (
    BASE_URL,
    SUPPORTED_CURRENCY,
    StockAnalysisFundamentalProvider,
    _abs_money,
    _first_non_null,
    _safe_ratio,
    _scaled_money,
    _scaled_money_first,
    _scaled_shares,
)
from services.api.app import models
from services.api.app.json_sanitize import sanitize_json_compatible
from services.api.app.services.fundamental_signal_engine import upsert_fundamental_signal_rows
from services.api.app.services.fundamentals import (
    latest_snapshot_rows_by_symbol,
    make_bulk_overrides_loader,
    recompute_symbol_valuations_all_scenarios,
)
from services.worker.db import SessionLocal


SOURCE_DOCUMENT_KIND = "stockanalysis"
SOURCE_TITLE = "StockAnalysis interim financial tables"
AUDIT_DIR = ROOT / "data" / "stockanalysis_period_backfill_audits"
DEFAULT_MIN_YEAR = 2021
NON_STOCK_SYMBOLS = {"INSTRUMENT", "MAJ", "MAJJ", "WORKSHEET"}


@dataclass(frozen=True)
class PeriodColumn:
    index: int = field(compare=False)
    fiscal_year: int
    period_type: str
    period_label: str
    period_end_date: dt.date | None


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _active_masi_symbols(db, requested: list[str] | None = None) -> list[str]:
    query = (
        db.query(models.StockMaster.symbol)
        .filter(models.StockMaster.market_region == "masi")
        .filter(models.StockMaster.is_active.is_(True))
        .filter(~models.StockMaster.symbol.in_(sorted(NON_STOCK_SYMBOLS)))
    )
    if requested:
        query = query.filter(models.StockMaster.symbol.in_(sorted({symbol.upper() for symbol in requested})))
    return [str(row[0]).upper() for row in query.order_by(models.StockMaster.symbol.asc()).all()]


def _stock_rows(db, symbols: Iterable[str]) -> dict[str, models.StockMaster]:
    rows = db.query(models.StockMaster).filter(models.StockMaster.symbol.in_(sorted({s.upper() for s in symbols}))).all()
    return {str(row.symbol).upper(): row for row in rows}


def _parse_period_end(value: str) -> dt.date | None:
    match = re.search(r"([A-Z][a-z]{2})\s+(\d{1,2}),\s+(20\d{2}|19\d{2})", value or "")
    if not match:
        return None
    try:
        return dt.datetime.strptime(" ".join(match.groups()), "%b %d %Y").date()
    except ValueError:
        return None


def _period_columns(rows: list[list[str]], *, min_year: int) -> list[PeriodColumn]:
    if not rows:
        return []
    period_endings: dict[int, dt.date | None] = {}
    for row in rows[1:3]:
        if row and row[0].strip().lower() == "period ending":
            for index, cell in enumerate(row[1:], start=1):
                period_endings[index] = _parse_period_end(cell)
            break

    columns: list[PeriodColumn] = []
    for index, header in enumerate(rows[0][1:], start=1):
        match = re.match(r"^\s*([QH])([1-4])\s+(20\d{2}|19\d{2})\s*$", header or "", flags=re.IGNORECASE)
        if not match:
            continue
        kind, number, year_text = match.groups()
        fiscal_year = int(year_text)
        if fiscal_year < min_year:
            continue
        kind = kind.upper()
        period_label = f"{kind}{number}"
        period_type = "quarterly" if kind == "Q" else "semiannual"
        if period_type == "semiannual" and number not in {"1", "2"}:
            continue
        columns.append(
            PeriodColumn(
                index=index,
                fiscal_year=fiscal_year,
                period_type=period_type,
                period_label=period_label,
                period_end_date=period_endings.get(index),
            )
        )
    return columns


def _safe_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text in {"-", "--", "N/A"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.replace("MAD", "").replace("%", "").replace(",", "").replace("(", "").replace(")", "")
    try:
        out = float(text)
    except (TypeError, ValueError):
        return None
    if negative:
        out = -out
    return out if math.isfinite(out) else None


def _table_values_by_period(rows: list[list[str]], *, min_year: int) -> dict[PeriodColumn, dict[str, float | None]]:
    columns = _period_columns(rows, min_year=min_year)
    out: dict[PeriodColumn, dict[str, float | None]] = {column: {} for column in columns}
    for row in rows[1:]:
        if len(row) < 2:
            continue
        label = row[0].strip()
        if not label or label.lower() == "period ending":
            continue
        for column in columns:
            if column.index >= len(row):
                continue
            out[column][label] = _safe_float(row[column.index])
    return out


def _period_sort_key(column: PeriodColumn) -> tuple[dt.date, int, str, str]:
    return (
        column.period_end_date or dt.date(column.fiscal_year, 12, 31),
        column.fiscal_year,
        column.period_type,
        column.period_label,
    )


def _period_growth(
    values_by_period: dict[PeriodColumn, dict[str, float | None]],
    column: PeriodColumn,
    metric: str,
) -> float | None:
    current = values_by_period.get(column, {}).get(metric)
    previous_column = next(
        (
            item
            for item in values_by_period
            if item.period_type == column.period_type
            and item.period_label == column.period_label
            and item.fiscal_year == column.fiscal_year - 1
        ),
        None,
    )
    previous = values_by_period.get(previous_column, {}).get(metric) if previous_column else None
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / abs(previous)


def _has_core_period_values(values: dict[str, float | None]) -> bool:
    core_fields = (
        "Revenue",
        "NetIncome",
        "Total_Assets",
        "Total_Equity",
        "Operating_Cash_Flow",
        "Free_Cash_Flow",
        "Total_Debt",
    )
    return sum(1 for metric in core_fields if values.get(metric) is not None) >= 2


def _previous_period_column(column: PeriodColumn, period_columns: list[PeriodColumn]) -> PeriodColumn | None:
    ordered = [item for item in period_columns if item.period_type == column.period_type]
    try:
        index = ordered.index(column)
    except ValueError:
        return None
    if index <= 0:
        return None
    return ordered[index - 1]


def _normalized_period_rows(
    *,
    symbol: str,
    company_name: str,
    tables: dict[str, list[list[str]]],
    urls: dict[str, str],
    shares_outstanding: float | None,
    min_year: int,
) -> list[PeriodMetricRow]:
    income = _table_values_by_period(tables.get("income", []), min_year=min_year)
    balance = _table_values_by_period(tables.get("balance", []), min_year=min_year)
    cash_flow = _table_values_by_period(tables.get("cash_flow", []), min_year=min_year)
    period_columns = sorted(set(income) | set(balance) | set(cash_flow), key=_period_sort_key)
    cash_by_period = {
        column: _scaled_money(balance.get(column, {}).get("Cash & Equivalents"))
        for column in period_columns
    }
    rows: list[PeriodMetricRow] = []

    for column in period_columns:
        inc = income.get(column, {})
        bal = balance.get(column, {})
        cf = cash_flow.get(column, {})
        shares = shares_outstanding
        if shares is None:
            shares = _scaled_shares(bal.get("Total Common Shares Outstanding"))
        if shares is None:
            shares = _scaled_shares(inc.get("Diluted Shares Outstanding"))

        total_debt = _scaled_money(bal.get("Total Debt"))
        cash = _scaled_money(bal.get("Cash & Equivalents"))
        net_cash = _scaled_money(bal.get("Net Cash (Debt)"))
        net_debt = -net_cash if net_cash is not None else (total_debt - cash if total_debt is not None and cash is not None else None)
        revenue = _scaled_money(inc.get("Revenue"))
        net_income = _scaled_money(inc.get("Net Income"))
        cost_of_revenue = _scaled_money(inc.get("Cost of Revenue"))
        gross_profit = _scaled_money(inc.get("Gross Profit"))
        if gross_profit is None and revenue is not None and cost_of_revenue is not None:
            gross_profit = revenue - cost_of_revenue
        operating_expenses = _scaled_money_first(inc.get("Operating Expenses"), inc.get("Total Non-Interest Expense"))
        ebit = _scaled_money_first(inc.get("EBIT"), inc.get("Operating Income"))
        depreciation_amortization = _scaled_money_first(
            inc.get("D&A For EBITDA"),
            cf.get("Depreciation & Amortization"),
        )
        ebitda = _scaled_money(inc.get("EBITDA"))
        if ebitda is None and ebit is not None and depreciation_amortization is not None:
            ebitda = ebit + depreciation_amortization
        interest_expense = _abs_money(_scaled_money_first(inc.get("Interest Expense"), inc.get("Interest Paid on Deposits")))
        income_tax = _scaled_money(inc.get("Income Tax Expense"))
        total_assets = _scaled_money(bal.get("Total Assets"))
        equity = _scaled_money(bal.get("Shareholders' Equity"))
        current_assets = _scaled_money(bal.get("Total Current Assets"))
        current_liabilities = _scaled_money(bal.get("Total Current Liabilities"))
        accounts_receivable = _scaled_money_first(bal.get("Receivables"), bal.get("Accounts Receivable"))
        accounts_payable = _scaled_money(bal.get("Accounts Payable"))
        inventory = _scaled_money(bal.get("Inventory"))
        retained_earnings = _scaled_money(bal.get("Retained Earnings"))
        working_capital = _scaled_money(bal.get("Working Capital"))
        operating_cf = _scaled_money(cf.get("Operating Cash Flow"))
        investing_cf = _scaled_money(cf.get("Investing Cash Flow"))
        financing_cf = _scaled_money(cf.get("Financing Cash Flow"))
        free_cf = _scaled_money(cf.get("Free Cash Flow"))
        capital_expenditures = _scaled_money(cf.get("Capital Expenditures"))
        common_dividends_paid = _scaled_money(cf.get("Common Dividends Paid"))
        change_in_working_capital = _scaled_money(cf.get("Change in Working Capital"))
        dividends = _abs_money(common_dividends_paid)
        previous_column = _previous_period_column(column, period_columns)
        beginning_cash = cash_by_period.get(previous_column) if previous_column is not None else None
        ending_cash = cash
        values_by_source = {
            "income": {
                "Has_Core_Fundamentals": 1.0,
                "Chiffre_daffaires": revenue,
                "Clean_Chiffre_daffaires": revenue,
                "Revenue": revenue,
                "Cost_of_Revenue": cost_of_revenue,
                "Gross_Profit": gross_profit,
                "Marge_Brute": gross_profit,
                "Operating_Expenses": operating_expenses,
                "Selling_General_Admin": _scaled_money(inc.get("Selling, General & Admin")),
                "Other_Operating_Expenses": _scaled_money(inc.get("Other Operating Expenses")),
                "Occupancy_Expenses": _scaled_money(inc.get("Occupancy Expenses")),
                "Other_NonInterest_Expense": _scaled_money(inc.get("Other Non-Interest Expense")),
                "EBITDA": ebitda,
                "Excedent_brut_dexploitation": ebitda,
                "EBIT": ebit,
                "Resultat_dexploitation": ebit,
                "Depreciation_Amortization": depreciation_amortization,
                "DandA": depreciation_amortization,
                "Dotations_dexploitation": depreciation_amortization,
                "Interest_Expense": interest_expense,
                "Charges_Interets": interest_expense,
                "Net_Interest_Income": _scaled_money(inc.get("Net Interest Income")),
                "Total_Interest_Income": _scaled_money(inc.get("Total Interest Income")),
                "Interest_Income_on_Loans": _scaled_money(inc.get("Interest Income on Loans")),
                "Interest_Paid_on_Deposits": _scaled_money(inc.get("Interest Paid on Deposits")),
                "Total_NonInterest_Income": _scaled_money(inc.get("Total Non-Interest Income")),
                "Revenues_Before_Loan_Losses": _scaled_money(inc.get("Revenues Before Loan Losses")),
                "Provision_for_Loan_Losses": _scaled_money(inc.get("Provision for Loan Losses")),
                "Pretax_Income": _scaled_money(inc.get("Pretax Income")),
                "Income_Tax_Expense": income_tax,
                "Impots_sur_les_resultats": income_tax,
                "Resultat_net": net_income,
                "NetIncome": net_income,
                "Net_Income": net_income,
                "Clean_Resultat_net": net_income,
                "Operating_Margin": _safe_ratio(ebit, revenue),
                "Basic_EPS": inc.get("EPS (Basic)"),
                "Diluted_EPS": inc.get("EPS (Diluted)"),
            },
            "balance": {
                "Total_Actif": total_assets,
                "Total_Assets": total_assets,
                "Total_Liabilities": _scaled_money(bal.get("Total Liabilities")),
                "Total_Liabilities_And_Equity": _scaled_money(bal.get("Total Liabilities & Equity")),
                "Capitaux_propres": equity,
                "Clean_Capitaux_propres": equity,
                "Total_Equity": equity,
                "Equity": equity,
                "Total_Debt": total_debt,
                "Debt_Total": total_debt,
                "Dettes_de_financement": total_debt,
                "Cash": cash,
                "Cash_and_Equivalents": cash,
                "Tresorerie_Actif": cash,
                "NetDebt": net_debt,
                "Net_Debt": net_debt,
                "Loans_Net": _scaled_money(bal.get("Net Loans")),
                "Customer_Deposits": _scaled_money(bal.get("Total Deposits")),
                "Current_Assets": current_assets,
                "Actif_circulant": current_assets,
                "Current_Liabilities": current_liabilities,
                "Passif_circulant": current_liabilities,
                "Inventory": inventory,
                "Stocks": inventory,
                "Accounts_Receivable": accounts_receivable,
                "Creances_de_lactif_circulant": accounts_receivable,
                "Accounts_Payable": accounts_payable,
                "Dettes_du_passif_circulant": accounts_payable,
                "Retained_Earnings": retained_earnings,
                "Reserves": retained_earnings,
                "Working_Capital": working_capital,
                "Shares_Outstanding": shares,
                "Book_Value_Per_Share": bal.get("Book Value Per Share"),
                "Debt_to_Equity": _safe_ratio(total_debt, equity),
                "NetDebt_to_Equity": _safe_ratio(net_debt, equity),
                "NetDebt_to_EBITDA": _safe_ratio(net_debt, ebitda),
                "ROA": _safe_ratio(net_income, total_assets),
                "ROE": _safe_ratio(net_income, equity),
                "Current_Ratio": _safe_ratio(current_assets, current_liabilities),
                "Cash_Ratio": _safe_ratio(cash, current_liabilities),
            },
            "cash_flow": {
                "CFS_Net_Income_Top_Of_CFS": _scaled_money(cf.get("Net Income")),
                "Beginning_Cash": beginning_cash,
                "CFS_Beginning_Cash": beginning_cash,
                "Ending_Cash": ending_cash,
                "CFS_Ending_Cash": ending_cash,
                "Operating_Cash_Flow": operating_cf,
                "CF_Operating": operating_cf,
                "CF_Investing": investing_cf,
                "CF_Financing": financing_cf,
                "CF_FX_Effect": _scaled_money(cf.get("Foreign Exchange Rate Adjustments")),
                "Change_in_Cash": _scaled_money(cf.get("Net Cash Flow")),
                "Change_in_Working_Capital": change_in_working_capital,
                "Variation_du_besoin_de_financement_global": change_in_working_capital,
                "Free_Cash_Flow": free_cf,
                "Capital_Expenditures": capital_expenditures,
                "Capex": _abs_money(capital_expenditures),
                "Common_Dividends_Paid": common_dividends_paid,
                "Dividends_Paid": dividends,
                "Dividendes": dividends,
                "Clean_Dividendes": dividends,
                "FCF_Margin": _safe_ratio(free_cf, revenue),
                "Operating_CF_Margin": _safe_ratio(operating_cf, revenue),
            },
        }
        all_values = {
            metric: value
            for source_values in values_by_source.values()
            for metric, value in source_values.items()
        }
        if not _has_core_period_values(all_values):
            continue
        values_by_source["income"]["Net_Margin"] = _safe_ratio(net_income, revenue)
        values_by_source["income"]["Asset_Turnover"] = _safe_ratio(revenue, total_assets)
        values_by_source["income"]["Dividend_Payout"] = _safe_ratio(dividends, net_income)
        values_by_source["income"]["Dividend_Coverage"] = _safe_ratio(net_income, dividends)
        for metric, source_key, source_metric in (
            ("Revenue_Growth", "income", "Revenue"),
            ("NetIncome_Growth", "income", "Net Income"),
            ("OperatingCF_Growth", "cash_flow", "Operating Cash Flow"),
            ("FCF_Growth", "cash_flow", "Free Cash Flow"),
        ):
            values_by_source[source_key][metric] = _period_growth(
                income if source_key == "income" else cash_flow,
                column,
                source_metric,
            )

        for source_key, values in values_by_source.items():
            for metric_name, metric_value in sorted(values.items()):
                if metric_value is None:
                    continue
                try:
                    numeric = float(metric_value)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(numeric):
                    continue
                rows.append(
                    PeriodMetricRow(
                        symbol=symbol,
                        company_name=company_name,
                        fiscal_year=column.fiscal_year,
                        period_type=column.period_type,
                        period_label=column.period_label,
                        period_end_date=column.period_end_date.isoformat() if column.period_end_date else None,
                        metric_name=metric_name,
                        metric_value=numeric,
                        raw_metric_name=metric_name,
                        source_url=urls[source_key],
                        document_title=f"{SOURCE_TITLE} - {source_key.replace('_', ' ').title()}",
                        is_proxy=False,
                    )
                )
    return rows


def fetch_stockanalysis_period_rows(
    symbol: str,
    stock: models.StockMaster | None,
    *,
    min_year: int,
    provider: StockAnalysisFundamentalProvider | None = None,
) -> tuple[list[PeriodMetricRow], dict[str, Any]]:
    provider = provider or StockAnalysisFundamentalProvider(timeout_seconds=30, retries=2)
    provider_symbol = symbol.upper()
    base = BASE_URL.format(symbol=provider_symbol)
    urls = {
        "income": f"{base}/financials/?p=quarterly",
        "balance": f"{base}/financials/balance-sheet/?p=quarterly",
        "cash_flow": f"{base}/financials/cash-flow-statement/?p=quarterly",
    }
    tables: dict[str, list[list[str]]] = {}
    currencies: set[str] = set()
    for statement_name, url in urls.items():
        try:
            rows, currency = provider._fetch_table_with_currency(url)
        except ProviderUnavailableError:
            tables[statement_name] = []
            continue
        tables[statement_name] = rows
        if currency:
            currencies.add(currency)
    if not any(tables.values()):
        raise ProviderUnavailableError(f"no StockAnalysis interim statement tables found for {symbol}")
    if len(currencies) > 1:
        raise ProviderUnavailableError(f"mixed StockAnalysis interim currencies for {symbol}: {sorted(currencies)}")
    currency = next(iter(currencies), SUPPORTED_CURRENCY)
    if currency != SUPPORTED_CURRENCY:
        raise ProviderUnavailableError(f"StockAnalysis reports {symbol} interim financials in {currency}; {SUPPORTED_CURRENCY} conversion is not implemented")
    company_name = (
        getattr(stock, "display_name", None)
        or getattr(stock, "name", None)
        or getattr(stock, "company_name", None)
        or symbol
    )
    rows = _normalized_period_rows(
        symbol=symbol.upper(),
        company_name=company_name,
        tables=tables,
        urls=urls,
        shares_outstanding=getattr(stock, "shares_outstanding", None) if stock is not None else None,
        min_year=min_year,
    )
    if not rows:
        raise ProviderUnavailableError(f"StockAnalysis interim tables for {symbol} had no usable Q/H period columns from {min_year}")
    period_row_counts = Counter(row.period_type for row in rows)
    periods = sorted(
        {
            (row.period_type, row.period_label, row.fiscal_year, row.period_end_date)
            for row in rows
        },
        key=lambda item: (item[3] or "", item[2], item[0], item[1]),
    )
    return rows, {
        "source_urls": list(urls.values()),
        "currency": currency,
        "period_row_counts": dict(period_row_counts),
        "period_counts": dict(Counter(period_type for period_type, _label, _year, _end in periods)),
        "periods": [
            {
                "period_type": period_type,
                "period_label": period_label,
                "fiscal_year": fiscal_year,
                "period_end_date": period_end_date,
            }
            for period_type, period_label, fiscal_year, period_end_date in periods
        ],
    }


def _date_or_none(value: str | dt.date | None) -> dt.date | None:
    if value is None or isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        return None


def _source_document(db, *, import_id: Any, symbol: str, row: PeriodMetricRow) -> int | None:
    url = row.source_url or f"https://stockanalysis.com/quote/cbse/{symbol}/financials/?p=quarterly"
    existing = (
        db.query(models.FundamentalSourceDocument)
        .filter(models.FundamentalSourceDocument.import_id == import_id)
        .filter(models.FundamentalSourceDocument.source_url == url)
        .filter(models.FundamentalSourceDocument.symbol == symbol)
        .first()
    )
    if existing is not None:
        existing.status = "succeeded"
        existing.error_message = None
        existing.document_kind = SOURCE_DOCUMENT_KIND
        existing.period_type = "interim"
        existing.raw_json = sanitize_json_compatible({**dict(existing.raw_json or {}), "stockanalysis_period_backfill": True})
        db.add(existing)
        db.flush()
        return int(existing.id) if existing.id is not None else None
    doc = models.FundamentalSourceDocument(
        import_id=import_id,
        symbol=symbol,
        company_name=row.company_name,
        document_title=row.document_title or SOURCE_TITLE,
        source_url=url,
        document_kind=SOURCE_DOCUMENT_KIND,
        publication_date=_utcnow().date(),
        fiscal_year=row.fiscal_year,
        period_type="interim",
        period_label=row.period_label,
        period_end_date=_date_or_none(row.period_end_date),
        status="succeeded",
        extracted_field_count=0,
        raw_json=sanitize_json_compatible({"stockanalysis_period_backfill": True}),
    )
    db.add(doc)
    db.flush()
    return int(doc.id) if doc.id is not None else None


def _upsert_period_rows(db, *, import_id: Any, symbol: str, rows: list[PeriodMetricRow]) -> dict[str, int]:
    docs_by_url: dict[str, int | None] = {}
    existing = {
        (int(row.fiscal_year), str(row.period_type), str(row.period_label), str(row.metric_name)): row
        for row in (
            db.query(models.FundamentalPeriodMetric)
            .filter(models.FundamentalPeriodMetric.import_id == import_id)
            .filter(models.FundamentalPeriodMetric.symbol == symbol)
            .all()
        )
    }
    inserted = updated = unchanged = 0
    for row in rows:
        key = (int(row.fiscal_year), str(row.period_type), str(row.period_label), str(row.metric_name))
        source_url = row.source_url or ""
        if source_url not in docs_by_url:
            docs_by_url[source_url] = _source_document(db, import_id=import_id, symbol=symbol, row=row)
        doc_id = docs_by_url[source_url]
        period_end = _date_or_none(row.period_end_date)
        current = existing.get(key)
        value = None if row.metric_value is None else float(row.metric_value)
        if current is None:
            db.add(
                models.FundamentalPeriodMetric(
                    import_id=import_id,
                    source_document_id=doc_id,
                    symbol=symbol,
                    company_name=row.company_name or symbol,
                    fiscal_year=int(row.fiscal_year),
                    period_type=row.period_type,
                    period_label=row.period_label,
                    period_end_date=period_end,
                    metric_name=row.metric_name,
                    metric_value=value,
                    raw_metric_name=row.raw_metric_name or row.metric_name,
                    source_url=row.source_url,
                    document_title=row.document_title,
                    is_proxy=False,
                )
            )
            inserted += 1
            continue
        current_value = None if current.metric_value is None else float(current.metric_value)
        if (
            current_value != value
            or bool(current.is_proxy)
            or current.source_url != row.source_url
            or current.raw_metric_name != (row.raw_metric_name or row.metric_name)
            or current.period_end_date != period_end
        ):
            current.source_document_id = doc_id
            current.company_name = row.company_name or current.company_name or symbol
            current.period_end_date = period_end
            current.metric_value = value
            current.raw_metric_name = row.raw_metric_name or row.metric_name
            current.source_url = row.source_url
            current.document_title = row.document_title
            current.is_proxy = False
            db.add(current)
            updated += 1
        else:
            unchanged += 1
    db.flush()
    return {"inserted": inserted, "updated": updated, "unchanged": unchanged}


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
    latest_period = max(
        (
            (
                row.period_end_date or dt.date(int(row.fiscal_year), 12, 31),
                row.period_type,
                row.period_label,
                int(row.fiscal_year),
            )
            for row in rows
        ),
        default=None,
    )
    coverage = dict(snapshot.coverage_json or {})
    source = dict(snapshot.source_json or {})
    coverage["period_metric_count"] = len(rows)
    coverage["period_types"] = period_types
    coverage["has_quarterly_period_metrics"] = "quarterly" in period_types
    coverage["has_semiannual_period_metrics"] = "semiannual" in period_types
    if latest_period is not None:
        coverage["latest_period_end_date"] = latest_period[0].isoformat()
        coverage["latest_period_type"] = latest_period[1]
        coverage["latest_period_label"] = latest_period[2]
        coverage["latest_period_fiscal_year"] = latest_period[3]
    source["stockanalysis_period_backfill"] = {
        "as_of": _utcnow().date().isoformat(),
        "period_types": period_types,
        "period_metric_count": len(rows),
    }
    snapshot.coverage_json = sanitize_json_compatible(coverage)
    snapshot.source_json = sanitize_json_compatible(source)
    flag_modified(snapshot, "coverage_json")
    flag_modified(snapshot, "source_json")
    db.add(snapshot)


def _period_row_count(db, *, import_id: Any, symbol: str, period_type: str | None = None) -> int:
    query = (
        db.query(models.FundamentalPeriodMetric)
        .filter(models.FundamentalPeriodMetric.import_id == import_id)
        .filter(models.FundamentalPeriodMetric.symbol == symbol)
        .filter(models.FundamentalPeriodMetric.metric_value.isnot(None))
    )
    if period_type:
        query = query.filter(models.FundamentalPeriodMetric.period_type == period_type)
    return query.count()


def _refresh_downstream(db, symbols: list[str], import_ids_by_symbol: dict[str, Any]) -> dict[str, Any]:
    valuation_rows = 0
    overrides_loader = make_bulk_overrides_loader(db, symbols)
    for symbol in symbols:
        import_id = import_ids_by_symbol.get(symbol)
        if import_id is None:
            continue
        valuation_rows += len(
            recompute_symbol_valuations_all_scenarios(
                db,
                symbol=symbol,
                import_id=import_id,
                overrides_loader=overrides_loader,
            )
        )
    signal_rows = upsert_fundamental_signal_rows(db, symbols=symbols)
    db.flush()
    return {"valuation_row_count": valuation_rows, "signal_rows": signal_rows}


def backfill_stockanalysis_period_metrics(
    symbols: list[str] | None,
    *,
    min_year: int,
    dry_run: bool = False,
    skip_downstream: bool = False,
) -> dict[str, Any]:
    db = SessionLocal()
    try:
        selected = _active_masi_symbols(db, symbols)
        stocks = _stock_rows(db, selected)
        snapshots = latest_snapshot_rows_by_symbol(db, symbols=selected, scope="masi")
        import_ids = {symbol: snapshots[symbol].import_id for symbol in selected if symbol in snapshots}
        fetched_rows: dict[str, list[PeriodMetricRow]] = {}
        fetch_summaries: dict[str, dict[str, Any]] = {}
        fetch_errors: dict[str, str] = {}
        provider = StockAnalysisFundamentalProvider(timeout_seconds=30, retries=2)
        for symbol in selected:
            try:
                rows, summary = fetch_stockanalysis_period_rows(
                    symbol,
                    stocks.get(symbol),
                    min_year=min_year,
                    provider=provider,
                )
            except ProviderUnavailableError as exc:
                fetch_errors[symbol] = str(exc)
                continue
            fetched_rows[symbol] = rows
            fetch_summaries[symbol] = summary

        write_summary: dict[str, Any] = {}
        if not dry_run:
            for symbol in selected:
                snapshot = snapshots.get(symbol)
                if snapshot is None:
                    continue
                rows = fetched_rows.get(symbol, [])
                counts = {"inserted": 0, "updated": 0, "unchanged": 0}
                if rows:
                    counts = _upsert_period_rows(db, import_id=snapshot.import_id, symbol=symbol, rows=rows)
                _refresh_snapshot_period_coverage(db, import_id=snapshot.import_id, symbol=symbol)
                write_summary[symbol] = {
                    "import_id": str(snapshot.import_id),
                    "fetched_rows": len(rows),
                    "period_counts": fetch_summaries.get(symbol, {}).get("period_counts", {}),
                    **counts,
                }
            db.commit()
            if skip_downstream:
                downstream = {"skipped": True}
            else:
                downstream = _refresh_downstream(db, [symbol for symbol in selected if symbol in snapshots], import_ids)
                db.commit()
        else:
            downstream = {"dry_run": True}

        period_counts_by_symbol: dict[str, dict[str, int]] = {}
        for symbol, snapshot in snapshots.items():
            period_counts_by_symbol[symbol] = {
                "quarterly": _period_row_count(db, import_id=snapshot.import_id, symbol=symbol, period_type="quarterly"),
                "semiannual": _period_row_count(db, import_id=snapshot.import_id, symbol=symbol, period_type="semiannual"),
                "total": _period_row_count(db, import_id=snapshot.import_id, symbol=symbol),
            }

        result = {
            "dry_run": dry_run,
            "selected_symbols": selected,
            "symbol_count": len(selected),
            "min_year": min_year,
            "missing_snapshots": sorted(set(selected) - set(snapshots)),
            "fetch_errors": fetch_errors,
            "fetched_symbol_count": len(fetched_rows),
            "fetched_period_counts": {
                symbol: summary.get("period_counts", {})
                for symbol, summary in fetch_summaries.items()
            },
            "period_counts_by_symbol": period_counts_by_symbol,
            "write_summary": write_summary,
            "downstream": downstream,
            "source_urls": {
                symbol: fetch_summaries.get(symbol, {}).get("source_urls", [])
                for symbol in selected
            },
        }
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        audit_path = AUDIT_DIR / f"stockanalysis_period_backfill_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        audit_path.write_text(json.dumps(sanitize_json_compatible(result), indent=2, sort_keys=True), encoding="utf-8")
        result["audit_path"] = str(audit_path)
        return result
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill real StockAnalysis quarterly/semiannual period metrics for active MASI symbols.")
    parser.add_argument("--symbols", default="", help="Comma-separated symbols. Default: all active MASI symbols.")
    parser.add_argument("--min-year", type=int, default=DEFAULT_MIN_YEAR)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-downstream", action="store_true", help="Only write period rows and snapshot coverage; skip valuation/signals refresh.")
    args = parser.parse_args()
    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()] or None
    result = backfill_stockanalysis_period_metrics(
        symbols,
        min_year=int(args.min_year),
        dry_run=bool(args.dry_run),
        skip_downstream=bool(args.skip_downstream),
    )
    print(json.dumps(sanitize_json_compatible(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
