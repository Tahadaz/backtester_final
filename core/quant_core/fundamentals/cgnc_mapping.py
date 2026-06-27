from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import replace
from math import isfinite
from typing import Iterable

from .domain import AnnualMetricRow


CGNC_TO_ENGINE_METRICS: dict[str, tuple[str, ...]] = {
    "Chiffre_daffaires": ("Revenue", "Clean_Chiffre_daffaires"),
    "Resultat_dexploitation": ("EBIT",),
    "Resultat_financier": ("Net_Interest_Expense",),
    "Resultat_net": ("NetIncome", "Net_Income", "Clean_Resultat_net"),
    "Resultat_net_part_du_groupe": ("NetIncome_Group",),
    "Excedent_brut_dexploitation": ("EBITDA",),
    "Dotations_dexploitation": ("Depreciation_Amortization", "DandA"),
    "Capacite_dautofinancement": ("CAF",),
    "Valeur_ajoutee": ("Value_Added",),
    "Marge_brute": ("Gross_Profit",),
    "Impots_sur_les_resultats": ("Income_Tax_Expense",),
    "Total_Actif": ("Total_Assets",),
    "Total_Passif": ("Total_Liabilities_And_Equity",),
    "Actif_circulant": ("Current_Assets",),
    "Passif_circulant": ("Current_Liabilities",),
    "Stocks": ("Inventory",),
    "Creances_de_lactif_circulant": ("Accounts_Receivable",),
    "Dettes_du_passif_circulant": ("Accounts_Payable",),
    "Tresorerie_Actif": ("Cash", "Cash_and_Equivalents", "CFS_Ending_Cash"),
    "Tresorerie_Passif": ("Short_Term_Debt",),
    "Capitaux_propres": ("Total_Equity", "Clean_Capitaux_propres", "Equity"),
    "Capitaux_propres_part_du_groupe": ("Equity_Group", "Total_Equity_Group"),
    "Interets_minoritaires": ("Minority_Interest",),
    "Dettes_de_financement": ("Total_Debt", "Debt_Total"),
    "Flux_de_tresorerie_lies_a_lactivite": ("Operating_Cash_Flow", "CF_Operating"),
    "Flux_tresorerie_activites_operationnelles": ("Operating_Cash_Flow", "CF_Operating"),
    "Flux_de_tresorerie_lies_aux_investissements": ("CF_Investing",),
    "Flux_de_tresorerie_lies_au_financement": ("CF_Financing",),
    "Variation_de_tresorerie": ("Change_in_Cash",),
    "Variation_du_besoin_de_financement_global": ("Change_in_Working_Capital",),
    "Produit_Net_Bancaire": ("PNB",),
    "Resultat_Brut_Exploitation": ("RBE",),
    "Marge_RBE": ("Marge_RBE",),
    "Cout_du_risque": ("Cout_du_risque",),
    "Creances_sur_la_clientele": ("Loans_Net",),
}

DIVIDEND_METRICS = {"Dividendes", "Dividends_Paid", "Clean_Dividendes"}
ESG_FIELDS = {"Marge_brute", "Valeur_ajoutee", "Excedent_brut_dexploitation", "Capacite_dautofinancement"}
IFRS_GROUP_FIELDS = {"Resultat_net_part_du_groupe", "Capitaux_propres_part_du_groupe", "Interets_minoritaires"}
BANK_FIELD_TOKENS = (
    # French / BVC tokens (existing)
    "pnb", "produit_net_bancaire", "interets_et_produits", "commissions",
    # English / StockAnalysis tokens — extend so SA bank lines are detected
    "net_interest_income", "interest_income_on_loans", "interest_paid_on_deposits",
    "customer_deposits", "total_deposits", "net_loans", "provision_for_loan_losses",
    "revenues_before_loan_losses", "total_noninterest_income",
)
INSURANCE_FIELD_TOKENS = ("assurance", "insurance", "takaful", "premiums_earned")
FINANCIAL_ARCHETYPES = {"bank", "insurance"}
FINANCIAL_SUPPRESSED_METRICS = {
    "Capex",
    "Capital_Expenditures",
    "EBITDA",
    "EnterpriseValue",
    "Enterprise_Value",
    "EV_to_EBITDA",
    "EV_to_Sales",
    "FCF_Margin",
    "FCF_Yield",
    "Free_Cash_Flow",
    "Net_Debt",
    "Price_to_Sales",
}

# ---------------------------------------------------------------------------
# Canonical metric names — the ONLY names written to storage going forward.
# Derived from scoring.py pillar tuples plus the raw items ratios are built from.
# ---------------------------------------------------------------------------
CANONICAL_METRICS: frozenset[str] = frozenset({
    # --- Industrial raw statement items ---
    "Revenue", "NetIncome", "EBIT", "EBITDA", "Gross_Profit",
    "Depreciation_Amortization", "Interest_Expense", "Income_Tax_Expense",
    "Pretax_Income", "Minority_Interest",
    "Total_Assets", "Total_Liabilities", "Total_Equity", "Total_Debt",
    "Net_Debt", "Cash", "Current_Assets", "Current_Liabilities",
    "Operating_Cash_Flow", "Free_Cash_Flow", "Capital_Expenditures",
    "CAF", "Dividendes", "Shares_Outstanding",
    "Working_Capital", "Retained_Earnings", "Operating_Expenses",
    "Dividend_Per_Share", "Basic_EPS", "Diluted_EPS", "Book_Value_Per_Share",
    "CF_Investing", "CF_Financing", "Change_in_Cash", "Change_in_Working_Capital",
    # --- Bank / insurer raw items ---
    "Net_Interest_Income", "Total_Interest_Income", "Interest_Income_on_Loans",
    "Interest_Paid_on_Deposits", "Total_NonInterest_Income",
    "Revenues_Before_Loan_Losses", "Provision_for_Loan_Losses",
    "Loans_Net", "Customer_Deposits", "PNB", "Cout_du_risque",
    "Premiums_Earned", "Policy_Benefits", "Policy_Acquisition_Costs",
    # --- Computed ratios: value pillar ---
    "PER", "Price_to_Book", "Price_to_Sales", "EV_to_EBITDA",
    "FCF_Yield", "Dividend_Yield",
    # --- Computed ratios: quality pillar ---
    "ROE", "ROA", "Operating_Margin", "Net_Margin",
    # --- Computed ratios: growth pillar ---
    "Revenue_Growth", "EBIT_Growth", "NetIncome_Growth",
    # --- Computed ratios: risk pillar ---
    "Debt_to_Equity", "NetDebt_to_Equity", "NetDebt_to_EBITDA", "Equity_Multiplier",
    # --- Computed ratios: cash-flow pillar ---
    "FCF_Margin", "Operating_CF_Margin", "CAF_Margin",
    # --- Computed ratios: health pillar ---
    "Current_Ratio", "Cash_Ratio", "Interest_Coverage",
    # --- Computed ratios: bank-specific ---
    "Net_Interest_Margin", "Cost_to_Income", "Loans_to_Deposits",
    # --- Computed ratios: insurer-specific ---
    "Combined_Ratio",
    # --- Computed ratios: ancillary ---
    "Asset_Turnover", "Dividend_Payout", "Dividend_Coverage",
    # --- Intermediate values (stored for diagnostics) ---
    "Market_Cap_Calc", "EV_Calc",
})

# Maps each canonical name to its legacy read-only aliases (Clean_*, French, variant spellings).
# Storage rule: only canonical names are written. Aliases are resolved at read time via
# resolve_metric_name / canonicalize_metrics and never persisted.
METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    # Income statement
    "Revenue": ("Chiffre_daffaires", "Clean_Chiffre_daffaires"),
    "NetIncome": ("Resultat_net", "Net_Income", "Clean_Resultat_net"),
    "EBIT": ("Resultat_dexploitation",),
    "EBITDA": ("Excedent_brut_dexploitation",),
    "Gross_Profit": ("Marge_brute", "Marge_Brute"),
    "Depreciation_Amortization": ("Dotations_dexploitation", "DandA"),
    "Income_Tax_Expense": ("Impots_sur_les_resultats",),
    "Interest_Expense": ("Charges_Interets",),
    # Balance sheet
    "Total_Assets": ("Total_Actif",),
    "Total_Liabilities": ("Total_Passif",),
    "Total_Equity": ("Capitaux_propres", "Clean_Capitaux_propres", "Equity"),
    "Total_Debt": ("Dettes_de_financement", "Debt_Total"),
    "Net_Debt": ("NetDebt",),
    "Cash": ("Tresorerie_Actif", "Cash_and_Equivalents", "CFS_Ending_Cash"),
    "Current_Assets": ("Actif_circulant",),
    "Current_Liabilities": ("Passif_circulant",),
    # Cash flow
    "Operating_Cash_Flow": (
        "CF_Operating",
        "Flux_de_tresorerie_lies_a_lactivite",
        "Flux_tresorerie_activites_operationnelles",
    ),
    "CAF": ("Capacite_dautofinancement",),
    # Dividends
    "Dividendes": ("Dividends_Paid", "Clean_Dividendes"),
    # Bank-specific
    "PNB": ("Produit_Net_Bancaire",),
    "Loans_Net": ("Creances_sur_la_clientele",),
    "Cout_du_risque": ("Cost_of_Risk",),
}

# Inverted lookup built once at module load — alias → canonical.
_ALIAS_TO_CANONICAL: dict[str, str] = {
    alias: canonical
    for canonical, aliases in METRIC_ALIASES.items()
    for alias in aliases
}


def resolve_metric_name(name: str) -> str:
    """Return the canonical name for *name*, or *name* itself if already canonical / unknown."""
    return _ALIAS_TO_CANONICAL.get(name, name)


def canonicalize_metrics(metrics: dict) -> dict:
    """Return a new dict with all keys resolved to their canonical names.

    Priority rules (regardless of dict iteration order):
    - A canonical key always beats any alias value already stored.
    - An alias fills in only when the canonical slot is still null.
    Input is never mutated.
    """
    out: dict = {}
    for key, value in metrics.items():
        canonical = resolve_metric_name(key)
        is_alias = key in _ALIAS_TO_CANONICAL
        if canonical not in out:
            out[canonical] = value
        elif not is_alias and value is not None:
            # canonical key encountered after an alias was stored — canonical wins
            out[canonical] = value
        elif is_alias and value is not None and out[canonical] is None:
            # alias fills in a null canonical slot
            out[canonical] = value
    return out


def infer_statement_archetype_from_values(metrics: dict) -> str:
    """Like infer_statement_archetype but ignores null-valued keys.

    The StockAnalysis provider writes bank-specific keys (Net_Interest_Income,
    Customer_Deposits, …) for every symbol with null values for industrials.
    Passing those key *names* alone to infer_statement_archetype would falsely
    classify industrials as banks after the English tokens were added to
    BANK_FIELD_TOKENS.  This wrapper filters to non-null keys first.
    """
    return infer_statement_archetype(
        name for name, value in metrics.items() if value is not None
    )


def normalize_cgnc_metric_value(metric_name: str, value: float | None) -> float | None:
    """Apply the lightweight BVC normalizer rules needed inside the app.

    The scraper's full normalizer handles multi-row 1000x scale detection before
    export. The app-side mapper only repeats deterministic single-cell fixes so
    imported BVC lineage remains robust when older rows are replayed.
    """

    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(numeric):
        return None
    if metric_name in DIVIDEND_METRICS and numeric < 0:
        return abs(numeric)
    return numeric


def infer_statement_archetype(metric_names: Iterable[str]) -> str:
    names = {str(name or "") for name in metric_names}
    lowered = {name.lower() for name in names}
    if any(token in name for token in BANK_FIELD_TOKENS for name in lowered):
        return "bank"
    if any(token in name for token in INSURANCE_FIELD_TOKENS for name in lowered):
        return "insurance"
    if names & ESG_FIELDS:
        return "cgnc_social"
    if names & IFRS_GROUP_FIELDS:
        return "ifrs_consolidated"
    if {"Total_Actif", "Total_Passif", "Resultat_net"} & names:
        return "cgnc_social"
    return "unknown"


def map_cgnc_annual_metrics(rows: Iterable[AnnualMetricRow]) -> list[AnnualMetricRow]:
    """Return original CGNC rows plus canonical engine aliases and derived lines."""

    normalized_rows = [_normalized_row(row) for row in rows]
    grouped: dict[tuple[str, int], list[AnnualMetricRow]] = defaultdict(list)
    for row in normalized_rows:
        grouped[(row.symbol.upper(), row.statement_year)].append(row)

    out: list[AnnualMetricRow] = []
    for group_rows in grouped.values():
        archetype = infer_statement_archetype(row.metric_name for row in group_rows)
        source_rows = _drop_financial_industrial_metrics(group_rows, archetype)
        out.extend(source_rows)
        out.extend(_direct_alias_rows(source_rows, archetype=archetype))
        out.extend(_derived_rows(source_rows, archetype=archetype))
    out.extend(_cross_year_derived_rows(out))
    return _dedupe_rows(out)


def _normalized_row(row: AnnualMetricRow) -> AnnualMetricRow:
    value = normalize_cgnc_metric_value(row.metric_name, row.metric_value)
    if value == row.metric_value:
        return row
    return replace(row, metric_value=value)


def _is_financial_archetype(archetype: str) -> bool:
    return str(archetype or "").lower() in FINANCIAL_ARCHETYPES


def _drop_financial_industrial_metrics(rows: list[AnnualMetricRow], archetype: str) -> list[AnnualMetricRow]:
    if not _is_financial_archetype(archetype):
        return list(rows)
    return [row for row in rows if row.metric_name not in FINANCIAL_SUPPRESSED_METRICS]


def _direct_alias_rows(rows: list[AnnualMetricRow], *, archetype: str = "unknown") -> list[AnnualMetricRow]:
    aliases: list[AnnualMetricRow] = []
    financial = _is_financial_archetype(archetype)
    for row in rows:
        value = normalize_cgnc_metric_value(row.metric_name, row.metric_value)
        if value is None:
            continue
        for metric_name in CGNC_TO_ENGINE_METRICS.get(row.metric_name, ()):
            if financial and metric_name in FINANCIAL_SUPPRESSED_METRICS:
                continue
            aliases.append(
                replace(
                    row,
                    metric_name=metric_name,
                    metric_value=value,
                    raw_metric_name=row.raw_metric_name or row.metric_name,
                    source_sheet=row.source_sheet or "bvc_cgnc",
                    source_field=row.source_field or row.metric_name,
                )
            )
        if not financial and row.metric_name == "Flux_de_tresorerie_lies_aux_investissements":
            aliases.append(
                replace(
                    row,
                    metric_name="Capex",
                    metric_value=abs(value),
                    raw_metric_name=row.raw_metric_name or row.metric_name,
                    source_sheet=row.source_sheet or "bvc_cgnc",
                    source_field=row.source_field or row.metric_name,
                )
            )
        if not financial and row.metric_name == "Flux_tresorerie_investissement_CAPEX":
            for metric_name in ("Capex", "Capital_Expenditures"):
                aliases.append(
                    replace(
                        row,
                        metric_name=metric_name,
                        metric_value=abs(value),
                        raw_metric_name=row.raw_metric_name or row.metric_name,
                        source_sheet=row.source_sheet or "bvc_cgnc",
                        source_field=row.source_field or row.metric_name,
                    )
                )
    return aliases


def _derived_rows(rows: list[AnnualMetricRow], *, archetype: str = "unknown") -> list[AnnualMetricRow]:
    financial = _is_financial_archetype(archetype)
    by_metric = _best_rows_by_metric(rows + _direct_alias_rows(rows, archetype=archetype))
    template = _template_row(rows)
    if template is None:
        return []

    derived: list[AnnualMetricRow] = []
    ebit = _metric_value(by_metric, "EBIT", "Resultat_dexploitation")
    dand_a = _metric_value(by_metric, "Depreciation_Amortization", "Dotations_dexploitation")
    if not financial and _metric_value(by_metric, "EBITDA", "Excedent_brut_dexploitation") is None and ebit is not None and dand_a is not None:
        derived.append(_derived_row(template, "EBITDA", ebit + dand_a, "derived:ebit_plus_dotations"))

    cfo = _metric_value(by_metric, "Operating_Cash_Flow", "CF_Operating", "Flux_de_tresorerie_lies_a_lactivite")
    caf = _metric_value(by_metric, "CAF", "Capacite_dautofinancement")
    delta_bfg = _metric_value(by_metric, "Change_in_Working_Capital", "Variation_du_besoin_de_financement_global")
    if cfo is None and caf is not None and delta_bfg is not None:
        cfo = caf - delta_bfg
        derived.append(_derived_row(template, "Operating_Cash_Flow", cfo, "derived:caf_minus_delta_bfg"))
        derived.append(_derived_row(template, "CF_Operating", cfo, "derived:caf_minus_delta_bfg"))

    investing = _metric_value(by_metric, "CF_Investing", "Flux_de_tresorerie_lies_aux_investissements")
    if not financial and _metric_value(by_metric, "Free_Cash_Flow") is None and cfo is not None and investing is not None:
        derived.append(_derived_row(template, "Free_Cash_Flow", cfo + investing, "derived:cfo_plus_investing_cf"))
    capex = _metric_value(by_metric, "Capex", "Capital_Expenditures", "Flux_tresorerie_investissement_CAPEX")
    if not financial and _metric_value(by_metric, "Free_Cash_Flow") is None and cfo is not None and investing is None and capex is not None:
        derived.append(_derived_row(template, "Free_Cash_Flow", cfo - abs(capex), "derived:cfo_minus_capex"))

    debt = _metric_value(by_metric, "Total_Debt", "Debt_Total", "Dettes_de_financement")
    cash = _metric_value(by_metric, "Cash", "Cash_and_Equivalents", "Tresorerie_Actif")
    if not financial and debt is not None and cash is not None:
        derived.append(_derived_row(template, "Net_Debt", debt - cash, "derived:debt_minus_cash"))

    total_passif = _metric_value(by_metric, "Total_Liabilities_And_Equity", "Total_Passif")
    equity = _metric_value(
        by_metric,
        "Total_Equity",
        "Shareholders_Equity",
        "Total_Shareholders_Equity",
        "Stockholders_Equity",
        "Total_Stockholders_Equity",
        "Clean_Capitaux_propres",
        "Capitaux_propres",
        "Equity",
        "Total_Common_Equity",
        "Common_Equity",
    )
    if _metric_value(by_metric, "Total_Liabilities") is None and total_passif is not None and equity is not None:
        derived.append(_derived_row(template, "Total_Liabilities", total_passif - equity, "derived:passif_minus_equity"))

    current_assets = _metric_value(by_metric, "Current_Assets", "Actif_circulant")
    current_liabilities = _metric_value(by_metric, "Current_Liabilities", "Passif_circulant")
    if current_assets is not None and current_liabilities is not None:
        derived.append(_derived_row(template, "Working_Capital", current_assets - current_liabilities, "derived:current_assets_minus_liabilities"))
        if current_liabilities > 0:
            derived.append(_derived_row(template, "Current_Ratio", current_assets / current_liabilities, "derived:current_assets_over_liabilities"))

    if debt is not None and equity is not None and equity > 0:
        derived.append(_derived_row(template, "Debt_to_Equity", debt / equity, "derived:debt_over_equity"))

    dividends = _metric_value(by_metric, "Dividendes", "Dividends_Paid", "Clean_Dividendes")
    net_income = _metric_value(by_metric, "NetIncome", "Net_Income", "Resultat_net", "Clean_Resultat_net")
    if dividends is not None and net_income is not None and net_income > 0:
        derived.append(_derived_row(template, "Dividend_Payout", abs(dividends) / net_income, "derived:dividends_over_net_income"))
    if net_income is not None and dividends is not None and dividends > 0:
        derived.append(_derived_row(template, "Dividend_Coverage", net_income / dividends, "derived:net_income_over_dividends"))

    return derived


def _cross_year_derived_rows(rows: Iterable[AnnualMetricRow]) -> list[AnnualMetricRow]:
    grouped: dict[str, dict[int, dict[str, AnnualMetricRow]]] = defaultdict(lambda: defaultdict(dict))
    for row in rows:
        if row.metric_value is None:
            continue
        current = grouped[row.symbol.upper()][row.statement_year].get(row.metric_name)
        if current is None or _row_rank(row) > _row_rank(current):
            grouped[row.symbol.upper()][row.statement_year][row.metric_name] = row

    derived: list[AnnualMetricRow] = []
    for years in grouped.values():
        sorted_years = sorted(years)
        for index, year in enumerate(sorted_years):
            by_metric = years[year]
            template = _template_row(list(by_metric.values()))
            if template is None:
                continue
            net_income_group = _metric_value(
                by_metric,
                "NetIncome_Group",
                "Net_Income_Group",
                "Resultat_net_part_du_groupe",
                "RNPG",
            )
            net_income = net_income_group
            if net_income is None:
                net_income = _metric_value(by_metric, "NetIncome", "Net_Income", "Resultat_net", "Clean_Resultat_net")
            equity_group = _metric_value(
                by_metric,
                "Equity_Group",
                "Total_Equity_Group",
                "Capitaux_propres_part_du_groupe",
                "Total_Common_Equity",
                "Common_Equity",
            )
            equity = _metric_value(
                by_metric,
                "Total_Equity",
                "Shareholders_Equity",
                "Total_Shareholders_Equity",
                "Stockholders_Equity",
                "Total_Stockholders_Equity",
                "Clean_Capitaux_propres",
                "Capitaux_propres",
                "Equity",
                "Total_Common_Equity",
                "Common_Equity",
            )
            if equity_group is not None:
                equity = equity_group
            previous_equity = None
            if index > 0:
                previous_equity_group = _metric_value(
                    years[sorted_years[index - 1]],
                    "Equity_Group",
                    "Total_Equity_Group",
                    "Capitaux_propres_part_du_groupe",
                    "Total_Common_Equity",
                    "Common_Equity",
                )
                previous_equity = _metric_value(
                    years[sorted_years[index - 1]],
                    "Total_Equity",
                    "Shareholders_Equity",
                    "Total_Shareholders_Equity",
                    "Stockholders_Equity",
                    "Total_Stockholders_Equity",
                    "Clean_Capitaux_propres",
                    "Capitaux_propres",
                    "Equity",
                    "Total_Common_Equity",
                    "Common_Equity",
                )
                if previous_equity_group is not None:
                    previous_equity = previous_equity_group
            if _metric_value(by_metric, "ROE") is None and net_income is not None and equity is not None:
                average_equity = (previous_equity + equity) / 2.0 if previous_equity is not None else equity
                if average_equity > 0:
                    derived.append(_derived_row(template, "ROE", net_income / average_equity, "derived:group_net_income_over_avg_group_equity"))
            if index == 0:
                continue
            previous = years[sorted_years[index - 1]]
            for metric_name, aliases, output_name in (
                ("Revenue", ("Revenue", "Chiffre_daffaires", "Clean_Chiffre_daffaires"), "Revenue_Growth"),
                ("NetIncome", ("NetIncome", "Net_Income", "Resultat_net", "Clean_Resultat_net"), "NetIncome_Growth"),
            ):
                if _metric_value(by_metric, output_name) is not None:
                    continue
                latest_value = _metric_value(by_metric, *aliases)
                previous_value = _metric_value(previous, *aliases)
                if latest_value is None or previous_value in (None, 0):
                    continue
                derived.append(
                    _derived_row(
                        template,
                        output_name,
                        (latest_value - previous_value) / abs(previous_value),
                        f"derived:{metric_name.lower()}_growth_yoy",
                    )
                )
    return derived


def _template_row(rows: list[AnnualMetricRow]) -> AnnualMetricRow | None:
    dated = [row for row in rows if row.as_of_date is not None]
    candidates = dated or rows
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda row: (
            row.as_of_date or dt.date.min,
            row.source_document_id or 0,
            row.metric_name,
        ),
        reverse=True,
    )[0]


def _derived_row(template: AnnualMetricRow, metric_name: str, value: float, source_field: str) -> AnnualMetricRow:
    return AnnualMetricRow(
        symbol=template.symbol,
        company_name=template.company_name,
        statement_year=template.statement_year,
        metric_name=metric_name,
        metric_value=value,
        raw_metric_name=source_field,
        source_sheet="bvc_cgnc_mapping",
        source_field=source_field,
        is_proxy=True,
        as_of_date=template.as_of_date,
        source_document_id=template.source_document_id,
    )


def _best_rows_by_metric(rows: Iterable[AnnualMetricRow]) -> dict[str, AnnualMetricRow]:
    best: dict[str, AnnualMetricRow] = {}
    for row in rows:
        if row.metric_value is None:
            continue
        current = best.get(row.metric_name)
        if current is None or _row_rank(row) > _row_rank(current):
            best[row.metric_name] = row
    return best


def _metric_value(by_metric: dict[str, AnnualMetricRow], *metric_names: str) -> float | None:
    for metric_name in metric_names:
        row = by_metric.get(metric_name)
        if row is not None and row.metric_value is not None:
            return row.metric_value
    return None


def _dedupe_rows(rows: Iterable[AnnualMetricRow]) -> list[AnnualMetricRow]:
    best: dict[tuple[str, int, str], AnnualMetricRow] = {}
    for row in rows:
        key = (row.symbol.upper(), row.statement_year, row.metric_name)
        current = best.get(key)
        if current is None or _row_rank(row) > _row_rank(current):
            best[key] = row
    return sorted(best.values(), key=lambda row: (row.symbol.upper(), row.statement_year, row.metric_name))


def _row_rank(row: AnnualMetricRow) -> tuple[int, int, int, int]:
    return (
        1 if row.metric_value is not None else 0,
        0 if row.is_proxy else 1,
        (row.as_of_date or dt.date.min).toordinal(),
        int(row.source_document_id or 0),
    )
