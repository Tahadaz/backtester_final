from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

import requests
import urllib3
from sqlalchemy.orm.attributes import flag_modified

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.quant_core.fundamentals.cgnc_mapping import map_cgnc_annual_metrics
from core.quant_core.fundamentals.domain import AnnualMetricRow
from services.api.app import models
from services.api.app.json_sanitize import sanitize_json_compatible
from services.api.app.services.fundamental_signal_engine import upsert_fundamental_signal_rows
from services.api.app.services.fundamentals import (
    _build_integrity_reports,
    _load_history,
    _persist_integrity_reports,
    _scope_for_symbols,
    _sync_latest_snapshots_from_annual,
    latest_snapshot_rows_by_symbol,
    make_bulk_overrides_loader,
    persist_pillar_history_for_import,
    recompute_symbol_valuations_all_scenarios,
    rescore_universe,
)
from services.worker.db import SessionLocal

try:
    import pdfplumber
except Exception as exc:  # pragma: no cover - operational script
    raise SystemExit(f"pdfplumber is required for deterministic BVC extraction: {exc}")

try:
    import fitz
except Exception:  # pragma: no cover - optional speedup
    fitz = None


YEARS = tuple(range(2021, 2026))
PDF_DIR = ROOT / "data" / "bvc_top5_pdfs"
AUDIT_DIR = ROOT / "data" / "bvc_top5_backfill_audits"
CACHE_VERSION = 4

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


@dataclass(frozen=True)
class DocumentMeta:
    symbol: str
    fiscal_year: int
    url: str
    title: str
    publication_date: dt.date
    document_kind: str


@dataclass(frozen=True)
class MetricSpec:
    metric_name: str
    patterns: tuple[str, ...]
    skip_patterns: tuple[str, ...] = ()
    absolute: bool = False


DOCS: dict[str, list[DocumentMeta]] = {
    "ATW": [
        DocumentMeta("ATW", 2021, "https://media.casablanca-bourse.com/sites/default/files/BourseWeb/Documents/ATW/fr/ATW_RF_2021_fr.pdf", "Attijariwafa Bank - Resultats financiers 2021", dt.date(2022, 2, 24), "CP"),
        DocumentMeta("ATW", 2022, "https://media.casablanca-bourse.com/sites/default/files/2023-08/awb_rfa_2022_1.pdf", "ATW - Rapport financier annuel 2022", dt.date(2023, 4, 21), "RFA"),
        DocumentMeta("ATW", 2023, "https://media.casablanca-bourse.com/sites/default/files/2024-02/awb_2023.pdf", "Attijariwafa Bank - Resultats financiers 2023", dt.date(2024, 2, 28), "CP"),
        DocumentMeta("ATW", 2024, "https://media.casablanca-bourse.com/sites/default/files/2025-02/awb_2024.pdf", "Attijariwafa Bank - Resultats financiers 2024", dt.date(2025, 2, 28), "CP"),
        DocumentMeta("ATW", 2025, "https://media.casablanca-bourse.com/sites/default/files/2026-02/awb_2025.pdf", "Attijariwafa Bank - Resultats financiers 2025", dt.date(2026, 2, 24), "CP"),
    ],
    "IAM": [
        DocumentMeta("IAM", 2021, "https://media.casablanca-bourse.com/sites/default/files/BourseWeb/Documents/IAM/fr/IAM_RF_2021_fr.pdf", "IAM - Resultats financiers 2021", dt.date(2022, 2, 17), "CP"),
        DocumentMeta("IAM", 2022, "https://media.casablanca-bourse.com/sites/default/files/2023-08/maroc_telecom_document_enregistrement_universel_2022.pdf", "Maroc Telecom - Rapport financier annuel 2022", dt.date(2023, 4, 28), "RFA"),
        DocumentMeta("IAM", 2023, "https://media.casablanca-bourse.com/sites/default/files/2024-02/maroc_telecom_rapport_financier_2023_0.pdf", "Maroc Telecom - Rapport financier annuel 2023", dt.date(2024, 2, 19), "RFA"),
        DocumentMeta("IAM", 2024, "https://media.casablanca-bourse.com/sites/default/files/2025-03/maroc_telecom_rfa_2024_0.pdf", "Maroc Telecom - RFA 2024", dt.date(2025, 3, 10), "RFA"),
        DocumentMeta("IAM", 2025, "https://media.casablanca-bourse.com/sites/default/files/2026-04/maroc_telecom_rfa_2025.pdf", "Maroc Telecom - Rapport financier annuel 2025", dt.date(2026, 3, 4), "RFA"),
    ],
    "MSA": [
        DocumentMeta("MSA", 2021, "https://media.casablanca-bourse.com/sites/default/files/BourseWeb/Documents/MSA/fr/Marsa_Maroc_CP_RFA_2021_fr.PDF", "Marsa Maroc - Resultats financiers 2021", dt.date(2022, 4, 27), "CP"),
        DocumentMeta("MSA", 2022, "https://media.casablanca-bourse.com/sites/default/files/2023-08/marsa_maroc_rfa_2022.pdf", "Marsa Maroc - Rapport financier annuel 2022", dt.date(2023, 4, 28), "RFA"),
        DocumentMeta("MSA", 2023, "https://media.casablanca-bourse.com/sites/default/files/2024-04/marsa_maroc_2023.pdf", "Marsa Maroc - Resultats financiers 2023", dt.date(2024, 4, 26), "CP"),
        DocumentMeta("MSA", 2024, "https://media.casablanca-bourse.com/sites/default/files/2025-04/marsa_maroc_cp_rfa_2024.pdf", "Marsa Maroc - Resultats financiers 2024 et CP RFA 2024", dt.date(2025, 4, 29), "RFA"),
        DocumentMeta("MSA", 2025, "https://media.casablanca-bourse.com/sites/default/files/2026-04/marsa_2025.pdf", "Marsa Maroc - Resultats financiers 2025 et CP RFA 2025", dt.date(2026, 4, 29), "RFA"),
    ],
    "BCP": [
        DocumentMeta("BCP", 2021, "https://media.casablanca-bourse.com/sites/default/files/BourseWeb/Documents/BCP/fr/Cahier%20Financier%20BP_31_12_21_EXE_fr.pdf", "BCP - Resultats annuels 2021", dt.date(2022, 3, 18), "CP"),
        DocumentMeta("BCP", 2022, "https://media.casablanca-bourse.com/sites/default/files/2023-08/bcp_rfa_2022.pdf", "BCP - Rapport financier annuel 2022", dt.date(2023, 3, 27), "RFA"),
        DocumentMeta("BCP", 2023, "https://media.casablanca-bourse.com/sites/default/files/2024-03/bcp_2023.pdf", "BCP - Resultats financiers 2023", dt.date(2024, 3, 22), "CP"),
        DocumentMeta("BCP", 2024, "https://media.casablanca-bourse.com/sites/default/files/2025-03/bcp_2024.pdf", "BCP - Resultats financiers 2024", dt.date(2025, 2, 28), "CP"),
        DocumentMeta("BCP", 2025, "https://media.casablanca-bourse.com/sites/default/files/2026-03/bcp_2025_0.pdf", "BCP - Resultats financiers 2025", dt.date(2026, 2, 27), "CP"),
    ],
    "BOA": [
        DocumentMeta("BOA", 2021, "https://media.casablanca-bourse.com/sites/default/files/BourseWeb/Documents/BOA/fr/BOA_CP_T4_2021_fr.pdf", "Bank of Africa - Indicateurs du 4eme trimestre 2021", dt.date(2022, 2, 28), "CP"),
        DocumentMeta("BOA", 2022, "https://media.casablanca-bourse.com/sites/default/files/2023-08/boa_rfa_2022.pdf", "BOA - Rapport financier annuel 2022", dt.date(2023, 4, 28), "RFA"),
        DocumentMeta("BOA", 2023, "https://media.casablanca-bourse.com/sites/default/files/2024-03/boa_2023.pdf", "BOA - Resultats financiers 2023", dt.date(2024, 3, 26), "CP"),
        DocumentMeta("BOA", 2024, "https://media.casablanca-bourse.com/sites/default/files/2025-03/boa_2024.pdf", "BOA - Resultats financiers 2024", dt.date(2025, 2, 28), "CP"),
        DocumentMeta("BOA", 2025, "https://media.casablanca-bourse.com/sites/default/files/2026-03/boa_2025.pdf", "BOA - Resultats financiers 2025", dt.date(2026, 2, 27), "CP"),
    ],
}


SPECS: tuple[MetricSpec, ...] = (
    MetricSpec("Resultat_net_part_du_groupe", ("resultat net part du groupe", "part du groupe")),
    MetricSpec("CFS_Beginning_Cash", ("tresorerie a l ouverture", "tresorerie a l'ouverture", "tresorerie debut", "solde de tresorerie au debut")),
    MetricSpec("CFS_Ending_Cash", ("tresorerie a la cloture", "tresorerie a la cloture", "tresorerie fin", "solde de tresorerie a la fin")),
    MetricSpec("Flux_de_tresorerie_lies_a_lactivite", ("flux nets de tresorerie provenant des activites d exploitation", "flux nets de tresorerie generes par l activite", "flux de tresorerie lies a l activite", "flux de tresorerie lies aux activites operationnelles", "flux net de tresorerie provenant des activites d exploitation")),
    MetricSpec("Flux_de_tresorerie_lies_aux_investissements", ("flux nets de tresorerie provenant des activites d investissement", "flux de tresorerie lies aux activites d investissement", "flux de tresorerie lies aux investissements", "flux de tresorerie d investissement")),
    MetricSpec("Flux_de_tresorerie_lies_au_financement", ("flux nets de tresorerie provenant des activites de financement", "flux de tresorerie lies aux activites de financement", "flux de tresorerie lies au financement", "flux de tresorerie de financement")),
    MetricSpec("Flux_tresorerie_investissement_CAPEX", ("acquisitions d immobilisations corporelles", "acquisition d immobilisations corporelles", "acquisition d immobilisations", "investissements corporels", "capex"), absolute=True),
    MetricSpec("Dividendes", ("dividendes verses", "dividendes distribues", "dividendes payes", "distribution de dividendes", "dividendes"), absolute=True),
    MetricSpec("Capacite_dautofinancement", ("capacite d autofinancement", "marge brute d autofinancement", "autofinancement")),
    MetricSpec("Variation_du_besoin_de_financement_global", ("variation du besoin de financement global", "variation du besoin en fonds de roulement", "variation du bfr")),
    MetricSpec("Chiffre_daffaires", ("chiffre d affaires", "produit net bancaire", "pnb", "produits d exploitation bancaire")),
    MetricSpec("Marge_brute", ("marge brute",)),
    MetricSpec("Excedent_brut_dexploitation", ("excedent brut d exploitation", "resultat brut d exploitation", "ebitda")),
    MetricSpec("Dotations_dexploitation", ("dotations aux amortissements", "dotations d exploitation", "amortissements et autres retraitements", "depreciation amortization"), absolute=True),
    MetricSpec("Resultat_dexploitation", ("resultat d exploitation", "resultat operationnel")),
    MetricSpec("Resultat_financier", ("resultat financier",)),
    MetricSpec("Marge_dinteret", ("marge d interet", "marge d'interet", "marge d interets")),
    MetricSpec("Impots_sur_les_resultats", ("impots sur les resultats", "impots sur les societes", "charge d impot", "impot sur les benefices"), absolute=True),
    MetricSpec("Resultat_avant_impots", ("resultat avant impots", "resultat avant impot", "resultat des activites ordinaires")),
    MetricSpec("Resultat_net", ("resultat net de l exercice", "resultat net des entreprises integrees", "resultat net"), ("par action", "per share", "quote part", "mises en equivalence")),
    MetricSpec("Total_Liabilities", ("total dettes", "total des dettes")),
    MetricSpec("Total_Actif", ("total actif ifrs", "total actif")),
    MetricSpec("Total_Passif", ("total passif ifrs", "total passif")),
    MetricSpec("Actif_circulant", ("actif circulant", "actifs courants"), ("non courant", "non courants")),
    MetricSpec("Passif_circulant", ("passif circulant", "passifs courants"), ("non courant", "non courants")),
    MetricSpec("Tresorerie_Actif", ("tresorerie et equivalents", "tresorerie actif", "disponibilites", "valeurs en caisse")),
    MetricSpec("Dettes_de_financement", ("dettes de financement", "emprunts et autres passifs financiers", "dettes subordonnees", "titres de creance emis"), absolute=True),
    MetricSpec("Capitaux_propres", ("total capitaux propres consolides", "capitaux propres de l ensemble consolide", "capitaux propres")),
    MetricSpec("Retained_Earnings", ("resultats reportes", "reserves consolidees", "reserves")),
    MetricSpec("Stocks", ("stocks",)),
    MetricSpec("Creances_de_lactif_circulant", ("creances d exploitation", "creances de l actif circulant", "prets et creances sur la clientele", "creances sur la clientele")),
    MetricSpec("Dettes_du_passif_circulant", ("dettes d exploitation", "dettes du passif circulant", "dettes envers la clientele")),
)


REQUIRED_GROUPS: dict[str, tuple[str, ...]] = {
    "Revenue": ("Revenue", "Chiffre_daffaires", "Clean_Chiffre_daffaires"),
    "Gross_Profit": ("Gross_Profit", "Marge_Brute", "Marge_brute"),
    "EBITDA": ("EBITDA", "Excedent_brut_dexploitation"),
    "DandA": ("DandA", "Depreciation_Amortization", "Dotations_dexploitation"),
    "EBIT": ("EBIT", "Resultat_dexploitation", "Resultat_Exploitation"),
    "Interest_or_Financial_Result": ("Interest_Expense", "Charges_Interets", "Net_Interest_Expense", "Resultat_financier", "Marge_dinteret"),
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
    "Working_Capital_or_Delta": ("Working_Capital", "Change_in_Working_Capital", "Variation_du_besoin_de_financement_global"),
    "CAF": ("CAF", "Capacite_dautofinancement"),
    "Beginning_Cash": ("CFS_Beginning_Cash", "Beginning_Cash"),
    "Ending_Cash": ("CFS_Ending_Cash", "Ending_Cash", "Cash", "Cash_and_Equivalents", "Tresorerie_Actif"),
    "CFS_NetIncome_Top": ("CFS_Net_Income_Top_Of_CFS",),
}


BANK_TOKENS = ("banque", "bank", "assurance", "insurance", "credit", "leasing", "financement")


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.lower().replace("\u00a0", " ")
    text = re.sub(r"[^a-z0-9%/.,()'-]+", " ", text)
    return " ".join(text.split())


def _is_financial_sector(sector: str | None) -> bool:
    normalized = _normalize_text(sector)
    return any(token in normalized for token in BANK_TOKENS)


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _metric_value(by_metric: dict[str, AnnualMetricRow], *aliases: str) -> float | None:
    for alias in aliases:
        row = by_metric.get(alias)
        value = _safe_float(row.metric_value if row is not None else None)
        if value is not None:
            return value
    return None


def _best_by_metric(rows: Iterable[AnnualMetricRow]) -> dict[str, AnnualMetricRow]:
    best: dict[str, AnnualMetricRow] = {}
    for row in rows:
        if row.metric_value is None:
            continue
        current = best.get(row.metric_name)
        if current is None or _row_rank(row) > _row_rank(current):
            best[row.metric_name] = row
    return best


def _row_rank(row: AnnualMetricRow) -> tuple[int, int, int, int]:
    return (
        1 if row.metric_value is not None else 0,
        0 if row.is_proxy else 1,
        (row.as_of_date or dt.date.min).toordinal(),
        int(row.source_document_id or 0),
    )


def _model_row_rank(row: Any) -> tuple[int, int, int, int]:
    return (
        1 if row.metric_value is not None else 0,
        0 if bool(row.is_proxy) else 1,
        (row.as_of_date or dt.date.min).toordinal(),
        int(row.source_document_id or 0),
    )


def _parse_number_cell(value: Any) -> float | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw or raw in {"-", "--"}:
        return None
    raw = raw.replace("\u00a0", " ").replace("\u202f", " ")
    raw = raw.replace("\n", " ")
    is_negative = False
    if "(" in raw and ")" in raw:
        is_negative = True
    if raw.strip().startswith("-"):
        is_negative = True
    cleaned = re.sub(r"[^0-9,.\-]", "", raw)
    if not re.search(r"\d", cleaned):
        return None
    if cleaned.count(",") == 1 and cleaned.rfind(",") > cleaned.rfind("."):
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    cleaned = cleaned.replace("-", "")
    try:
        value_float = float(cleaned)
    except ValueError:
        return None
    return -value_float if is_negative else value_float


TOKEN_RE = re.compile(r"\(?-?\d+(?:[.,]\d+)?\)?")
LETTER_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")


def _is_numeric_cell(value: Any) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    if LETTER_RE.search(raw):
        return False
    return bool(TOKEN_RE.search(raw))


def _parse_grouped_tokens(tokens: list[str]) -> float | None:
    if not tokens:
        return None
    raw = " ".join(tokens)
    return _parse_number_cell(raw)


def _parse_values_from_line(line: str, count: int) -> list[float] | None:
    if count <= 0:
        return None
    normalized = _normalize_text(line)
    if "%" in line or any(token in normalized for token in ("progression", "hausse", "baisse", "superieur", "inferieur", "coefficient", "contre", "croissance")):
        return None
    stripped = re.sub(r"\b31[/-]12[/-](?:20)?\d{2}\b", " ", line)
    tokens = [token for token in TOKEN_RE.findall(stripped) if "%" not in token]
    if len(tokens) < count:
        return None
    if len(tokens) > count * 4 + 1:
        return None
    for drop in range(0, min(5, len(tokens) - count + 1)):
        candidate = tokens[drop:]
        if len(candidate) < count or len(candidate) % count != 0:
            continue
        group_size = len(candidate) // count
        if group_size > 4:
            continue
        values: list[float] = []
        ok = True
        for idx in range(count):
            parsed = _parse_grouped_tokens(candidate[idx * group_size : (idx + 1) * group_size])
            if parsed is None:
                ok = False
                break
            values.append(parsed)
        if ok:
            return values
    parsed_cells = [_parse_number_cell(token) for token in tokens[-count:]]
    if all(value is not None for value in parsed_cells):
        return [float(value) for value in parsed_cells if value is not None]
    return None


YEAR_PATTERNS = (
    re.compile(r"20(2[0-6])"),
    re.compile(r"31[-/ ](?:dec|dec\.|12)[-/ .]*(2[0-6])"),
    re.compile(r"31\s*-\s*dec\s*-\s*(2[0-6])"),
)


def _infer_years(text: str, doc_year: int) -> list[int]:
    hits: list[tuple[int, int]] = []
    normalized = _normalize_text(text)
    for pattern in YEAR_PATTERNS:
        for match in pattern.finditer(normalized):
            raw = match.group(0)
            if raw.startswith("20"):
                year = int(raw[:4])
            else:
                year = 2000 + int(match.group(1))
            if doc_year - 4 <= year <= doc_year:
                hits.append((match.start(), year))
    out: list[int] = []
    for _pos, year in sorted(hits):
        if year not in out:
            out.append(year)
    if doc_year in out and len(out) >= 2:
        return out[:3]
    if out:
        return out[:3]
    return [doc_year, doc_year - 1]


def _infer_scale(text: str, symbol: str) -> float:
    normalized = _normalize_text(text)
    if "en millions" in normalized or "en mdh" in normalized or "millions mad" in normalized:
        return 1_000_000.0
    if "en milliers" in normalized or "milliers de dirhams" in normalized:
        return 1_000.0
    if symbol in {"ATW", "BCP", "BOA"}:
        return 1_000.0
    return 1.0


def _line_spec_count(normalized: str) -> int:
    count = 0
    for spec in SPECS:
        if any(skip in normalized for skip in spec.skip_patterns):
            continue
        if any(pattern in normalized for pattern in spec.patterns):
            count += 1
    return count


def _match_spec(normalized: str) -> MetricSpec | None:
    for spec in SPECS:
        if any(skip in normalized for skip in spec.skip_patterns):
            continue
        if any(pattern in normalized for pattern in spec.patterns):
            return spec
    return None


def _has_metric_label(normalized: str) -> bool:
    return any(
        pattern in normalized
        for spec in SPECS
        for pattern in spec.patterns
    )


def _scaled_value(metric_name: str, value: float, scale: float) -> float:
    if metric_name in {"Dividendes", "Flux_tresorerie_investissement_CAPEX", "Dotations_dexploitation", "Impots_sur_les_resultats", "Dettes_de_financement"}:
        value = abs(value)
    return value * scale


def _page_texts(path: Path) -> Iterable[str]:
    if fitz is not None:
        with fitz.open(str(path)) as doc:
            for page in doc:
                yield page.get_text("text") or ""
        return
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            yield page.extract_text(layout=False) or ""


def _extract_from_pdf(path: Path, meta: DocumentMeta) -> list[AnnualMetricRow]:
    out: dict[tuple[int, str], AnnualMetricRow] = {}
    for text in _page_texts(path):
        if not text:
            continue
        normalized_page = _normalize_text(text)
        if not _has_metric_label(normalized_page):
            continue
        page_years = _infer_years(text, meta.fiscal_year)
        scale = _infer_scale(text, meta.symbol)
        for line in text.splitlines():
            normalized = _normalize_text(line)
            if not normalized or _line_spec_count(normalized) != 1:
                continue
            spec = _match_spec(normalized)
            if spec is None:
                continue
            values = _parse_values_from_line(line, len(page_years))
            if not values:
                continue
            for year, value in zip(page_years, values):
                if year not in YEARS:
                    continue
                metric_value = _scaled_value(spec.metric_name, value, scale)
                key = (year, spec.metric_name)
                row = AnnualMetricRow(
                    symbol=meta.symbol,
                    company_name=meta.title,
                    statement_year=year,
                    metric_name=spec.metric_name,
                    metric_value=metric_value,
                    raw_metric_name=spec.metric_name,
                    source_sheet="bvc_deterministic_pdf",
                    source_field=line[:250],
                    is_proxy=False,
                    as_of_date=meta.publication_date,
                )
                current = out.get(key)
                if current is None or _row_rank(row) > _row_rank(current):
                    out[key] = row
    return sorted(out.values(), key=lambda row: (row.statement_year, row.metric_name))


def _cache_path(path: Path, meta: DocumentMeta) -> Path:
    return path.with_name(f"{path.name}.{meta.symbol}_{meta.fiscal_year}.deterministic.json")


def _row_to_json(row: AnnualMetricRow) -> dict[str, Any]:
    return {
        "symbol": row.symbol,
        "company_name": row.company_name,
        "statement_year": row.statement_year,
        "metric_name": row.metric_name,
        "metric_value": row.metric_value,
        "raw_metric_name": row.raw_metric_name,
        "source_sheet": row.source_sheet,
        "source_field": row.source_field,
        "is_proxy": row.is_proxy,
        "as_of_date": row.as_of_date.isoformat() if row.as_of_date else None,
    }


def _row_from_json(data: dict[str, Any]) -> AnnualMetricRow:
    as_of = None
    if data.get("as_of_date"):
        as_of = dt.date.fromisoformat(str(data["as_of_date"])[:10])
    return AnnualMetricRow(
        symbol=str(data["symbol"]),
        company_name=str(data.get("company_name") or data["symbol"]),
        statement_year=int(data["statement_year"]),
        metric_name=str(data["metric_name"]),
        metric_value=_safe_float(data.get("metric_value")),
        raw_metric_name=data.get("raw_metric_name"),
        source_sheet=data.get("source_sheet"),
        source_field=data.get("source_field"),
        is_proxy=bool(data.get("is_proxy")),
        as_of_date=as_of,
    )


def _extract_from_pdf_cached(path: Path, meta: DocumentMeta) -> list[AnnualMetricRow]:
    cache_path = _cache_path(path, meta)
    if cache_path.exists() and cache_path.stat().st_mtime >= path.stat().st_mtime:
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if int(data.get("cache_version") or 0) != CACHE_VERSION:
                raise ValueError("stale deterministic extraction cache")
            rows = [_row_from_json(item) for item in data.get("rows", []) if isinstance(item, dict)]
            if rows:
                return rows
        except Exception:
            pass
    rows = _extract_from_pdf(path, meta)
    cache_path.write_text(
        json.dumps({"cache_version": CACHE_VERSION, "url": meta.url, "rows": [_row_to_json(row) for row in rows]}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return rows


def _download_pdf(meta: DocumentMeta) -> Path:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{meta.symbol}_{meta.fiscal_year}_{quote(Path(meta.url).name, safe='')}"
    path = PDF_DIR / filename
    if path.exists() and path.stat().st_size > 10_000:
        return path
    response = requests.get(meta.url, timeout=90, verify=False)
    response.raise_for_status()
    path.write_bytes(response.content)
    return path


def _source_document(db, import_id: Any, meta: DocumentMeta, extracted_count: int) -> models.FundamentalSourceDocument:
    row = (
        db.query(models.FundamentalSourceDocument)
        .filter(
            models.FundamentalSourceDocument.import_id == import_id,
            models.FundamentalSourceDocument.source_url == meta.url,
        )
        .first()
    )
    if row is None:
        row = models.FundamentalSourceDocument(
            import_id=import_id,
            symbol=meta.symbol,
            company_name=meta.title,
            source_url=meta.url,
        )
        db.add(row)
        db.flush()
    row.symbol = meta.symbol
    row.company_name = meta.title
    row.document_title = meta.title
    row.document_kind = meta.document_kind
    row.publication_date = meta.publication_date
    row.fiscal_year = meta.fiscal_year
    row.period_type = "annual"
    row.period_label = "FY"
    row.period_end_date = dt.date(meta.fiscal_year, 12, 31)
    row.status = "succeeded"
    row.error_message = None
    row.extracted_field_count = extracted_count
    row.raw_json = sanitize_json_compatible({"deterministic_bvc": True, "url": meta.url})
    row.updated_at = _utcnow()
    flag_modified(row, "raw_json")
    db.add(row)
    db.flush()
    return row


def _annual_from_model(row: models.FundamentalAnnualMetric) -> AnnualMetricRow:
    return AnnualMetricRow(
        symbol=row.symbol,
        company_name=row.company_name,
        statement_year=int(row.statement_year),
        metric_name=row.metric_name,
        metric_value=row.metric_value,
        raw_metric_name=row.raw_metric_name,
        source_sheet=row.source_sheet,
        source_field=row.source_field,
        is_proxy=bool(row.is_proxy),
        as_of_date=row.as_of_date,
        source_document_id=row.source_document_id,
    )


def _existing_rows(db, import_id: Any, symbols: Iterable[str], years: Iterable[int]) -> list[AnnualMetricRow]:
    rows = (
        db.query(models.FundamentalAnnualMetric)
        .filter(
            models.FundamentalAnnualMetric.import_id == import_id,
            models.FundamentalAnnualMetric.symbol.in_(sorted({symbol.upper() for symbol in symbols})),
            models.FundamentalAnnualMetric.statement_year.in_(sorted(set(years))),
            models.FundamentalAnnualMetric.metric_value.isnot(None),
        )
        .all()
    )
    return [_annual_from_model(row) for row in rows]


def _template(symbol: str, year: int, company_name: str, rows: list[AnnualMetricRow], doc_id: int | None) -> AnnualMetricRow:
    candidates = [row for row in rows if row.symbol.upper() == symbol and row.statement_year == year]
    if candidates:
        best = sorted(candidates, key=_row_rank, reverse=True)[0]
        return best
    return AnnualMetricRow(
        symbol=symbol,
        company_name=company_name,
        statement_year=year,
        metric_name="template",
        metric_value=0.0,
        source_sheet="bvc_deterministic_proxy",
        source_field="template",
        is_proxy=True,
        as_of_date=dt.date(year + 1, 4, 30),
        source_document_id=doc_id,
    )


def _proxy_row(template: AnnualMetricRow, metric_name: str, value: float | None, source_field: str) -> AnnualMetricRow | None:
    value = _safe_float(value)
    if value is None:
        return None
    return AnnualMetricRow(
        symbol=template.symbol.upper(),
        company_name=template.company_name,
        statement_year=template.statement_year,
        metric_name=metric_name,
        metric_value=value,
        raw_metric_name=source_field,
        source_sheet="bvc_deterministic_proxy",
        source_field=source_field,
        is_proxy=True,
        as_of_date=template.as_of_date,
        source_document_id=template.source_document_id,
    )


def _group_present(by_metric: dict[str, AnnualMetricRow], group: str) -> bool:
    return any(_metric_value(by_metric, alias) is not None for alias in REQUIRED_GROUPS[group])


def _ensure_bridges(
    *,
    symbol: str,
    sector: str | None,
    year: int,
    company_name: str,
    rows: list[AnnualMetricRow],
    doc_id: int | None,
) -> list[AnnualMetricRow]:
    financial = _is_financial_sector(sector)
    by_metric = _best_by_metric(row for row in rows if row.symbol.upper() == symbol and row.statement_year == year)
    template = _template(symbol, year, company_name, rows, doc_id)
    additions: list[AnnualMetricRow] = []

    def add(metric_name: str, value: float | None, source_field: str) -> None:
        row = _proxy_row(template, metric_name, value, source_field)
        if row is not None:
            additions.append(row)
            by_metric[metric_name] = row

    revenue = _metric_value(by_metric, *REQUIRED_GROUPS["Revenue"])
    ebit = _metric_value(by_metric, *REQUIRED_GROUPS["EBIT"])
    ebitda = _metric_value(by_metric, *REQUIRED_GROUPS["EBITDA"])
    dand_a = _metric_value(by_metric, *REQUIRED_GROUPS["DandA"])
    net_income = _metric_value(by_metric, *REQUIRED_GROUPS["NetIncome"])
    pretax = _metric_value(by_metric, "Resultat_avant_impots")
    assets = _metric_value(by_metric, *REQUIRED_GROUPS["Total_Assets"])
    equity = _metric_value(by_metric, *REQUIRED_GROUPS["Total_Equity"])
    liabilities = _metric_value(by_metric, *REQUIRED_GROUPS["Total_Liabilities"])
    cash = _metric_value(by_metric, *REQUIRED_GROUPS["Cash"])
    debt = _metric_value(by_metric, *REQUIRED_GROUPS["Total_Debt"])
    current_assets = _metric_value(by_metric, *REQUIRED_GROUPS["Current_Assets"])
    current_liabilities = _metric_value(by_metric, *REQUIRED_GROUPS["Current_Liabilities"])
    cfo = _metric_value(by_metric, *REQUIRED_GROUPS["Operating_CF"])
    cfi = _metric_value(by_metric, *REQUIRED_GROUPS["Investing_CF"])
    cff = _metric_value(by_metric, *REQUIRED_GROUPS["Financing_CF"])
    capex = _metric_value(by_metric, *REQUIRED_GROUPS["Capex"])
    dividends = _metric_value(by_metric, *REQUIRED_GROUPS["Dividends"])

    if liabilities is None and assets is not None and equity is not None:
        add("Total_Liabilities", assets - equity, "derived:assets_minus_equity")
        liabilities = assets - equity
    if current_assets is None and assets is not None:
        add("Current_Assets", assets if financial else assets, "proxy:current_assets_from_total_assets")
        current_assets = assets
    if current_liabilities is None:
        base = liabilities if liabilities is not None else assets - equity if assets is not None and equity is not None else None
        add("Current_Liabilities", base, "proxy:current_liabilities_from_total_liabilities")
        current_liabilities = base
    if not _group_present(by_metric, "Gross_Profit"):
        add("Gross_Profit", revenue, "proxy:gross_profit_not_disclosed_use_revenue_or_pnb")
    if ebitda is None:
        if ebit is None and financial:
            if pretax is not None:
                add("EBIT", pretax, "proxy:bank_ebit_bridge_from_pretax")
                ebit = pretax
            elif net_income is not None:
                add("EBIT", net_income, "proxy:bank_ebit_bridge_from_net_income")
                ebit = net_income
            elif revenue is not None:
                add("EBIT", revenue, "proxy:bank_ebit_bridge_from_pnb")
                ebit = revenue
        if ebit is not None and dand_a is not None:
            add("EBITDA", ebit + abs(dand_a), "derived:ebit_plus_dand_a")
            ebitda = ebit + abs(dand_a)
        elif ebit is not None:
            add("EBITDA", ebit, "proxy:ebitda_from_ebit_no_dand_a_disclosed")
            ebitda = ebit
    if dand_a is None:
        if ebitda is not None and ebit is not None and ebitda >= ebit:
            add("DandA", ebitda - ebit, "derived:ebitda_minus_ebit")
        else:
            add("DandA", 0.0, "proxy:dand_a_not_disclosed_zero")
        dand_a = _metric_value(by_metric, *REQUIRED_GROUPS["DandA"])
    if not _group_present(by_metric, "Interest_or_Financial_Result"):
        margin_interest = _metric_value(by_metric, "Marge_dinteret")
        add("Net_Interest_Expense", margin_interest if margin_interest is not None else 0.0, "proxy:financial_result_bridge")
    if not _group_present(by_metric, "Income_Tax"):
        if pretax is not None and net_income is not None:
            add("Income_Tax_Expense", abs(pretax - net_income), "derived:pretax_minus_net_income")
        elif ebit is not None and net_income is not None:
            add("Income_Tax_Expense", max(0.0, ebit - net_income), "proxy:ebit_minus_net_income")
        else:
            add("Income_Tax_Expense", 0.0, "proxy:income_tax_not_disclosed_zero")
    if debt is None:
        add("Total_Debt", 0.0 if not financial else liabilities, "proxy:debt_bridge_from_liabilities_or_zero")
        debt = _metric_value(by_metric, *REQUIRED_GROUPS["Total_Debt"])
    if cash is None:
        ending_cash = _metric_value(by_metric, *REQUIRED_GROUPS["Ending_Cash"])
        add("Cash", ending_cash if ending_cash is not None else 0.0, "proxy:cash_from_cfs_or_zero")
        cash = _metric_value(by_metric, *REQUIRED_GROUPS["Cash"])
    if not _group_present(by_metric, "Net_Debt") and debt is not None and cash is not None:
        add("Net_Debt", debt - cash, "derived:debt_minus_cash")
    if current_assets is not None and current_liabilities is not None:
        wc = current_assets - current_liabilities
        if not _group_present(by_metric, "Working_Capital_or_Delta"):
            add("Working_Capital", wc, "derived:current_assets_minus_current_liabilities")
        if _metric_value(by_metric, "Change_in_Working_Capital") is None:
            add("Change_in_Working_Capital", 0.0, "proxy:delta_working_capital_not_disclosed_zero")
    if not _group_present(by_metric, "Inventory"):
        add("Inventory", 0.0, "proxy:inventory_not_applicable_or_not_disclosed_zero")
    if not _group_present(by_metric, "Receivables"):
        add("Accounts_Receivable", max(0.0, (current_assets or 0.0) - (cash or 0.0)), "proxy:receivables_from_current_assets_minus_cash")
    if not _group_present(by_metric, "Payables"):
        add("Accounts_Payable", max(0.0, current_liabilities or 0.0), "proxy:payables_from_current_liabilities")
    if capex is None:
        if cfi is not None:
            add("Capex", abs(cfi), "proxy:capex_from_investing_cash_flow")
        else:
            add("Capex", 0.0, "proxy:capex_not_disclosed_zero")
        capex = _metric_value(by_metric, *REQUIRED_GROUPS["Capex"])
    if cfo is None:
        if net_income is not None:
            add("Operating_Cash_Flow", net_income + abs(dand_a or 0.0), "proxy:cfo_from_net_income_plus_dand_a")
        else:
            add("Operating_Cash_Flow", 0.0, "proxy:cfo_not_disclosed_zero")
        cfo = _metric_value(by_metric, *REQUIRED_GROUPS["Operating_CF"])
    if cfi is None:
        add("CF_Investing", -abs(capex or 0.0), "proxy:investing_cf_from_capex")
        cfi = _metric_value(by_metric, *REQUIRED_GROUPS["Investing_CF"])
    if cff is None:
        add("CF_Financing", 0.0, "proxy:financing_cf_not_disclosed_zero")
        cff = _metric_value(by_metric, *REQUIRED_GROUPS["Financing_CF"])
    if not _group_present(by_metric, "Free_Cash_Flow"):
        add("Free_Cash_Flow", (cfo or 0.0) + (cfi or 0.0), "derived:cfo_plus_investing_cf")
    if dividends is None:
        if net_income is not None and net_income > 0:
            add("Dividendes", net_income * 0.55, "proxy:stable_payout_from_net_income")
        else:
            add("Dividendes", 0.0, "proxy:dividends_not_disclosed_zero")
        dividends = _metric_value(by_metric, *REQUIRED_GROUPS["Dividends"])
    if not _group_present(by_metric, "CAF"):
        if cfo is not None:
            add("CAF", cfo, "proxy:caf_from_operating_cash_flow")
        elif net_income is not None:
            add("CAF", net_income + abs(dand_a or 0.0), "proxy:caf_from_net_income_plus_dand_a")
    if not _group_present(by_metric, "Retained_Earnings"):
        add("Retained_Earnings", 0.0, "proxy:retained_earnings_not_disclosed_zero")
    ending_cash = _metric_value(by_metric, *REQUIRED_GROUPS["Ending_Cash"])
    if ending_cash is None:
        add("CFS_Ending_Cash", cash if cash is not None else 0.0, "proxy:ending_cash_from_balance_sheet_cash")
        ending_cash = _metric_value(by_metric, *REQUIRED_GROUPS["Ending_Cash"])
    if not _group_present(by_metric, "Beginning_Cash"):
        change_cash = (cfo or 0.0) + (cfi or 0.0) + (cff or 0.0)
        add("CFS_Beginning_Cash", (ending_cash or 0.0) - change_cash, "derived:ending_cash_minus_net_cash_change")
    if not _group_present(by_metric, "CFS_NetIncome_Top"):
        add("CFS_Net_Income_Top_Of_CFS", net_income if net_income is not None else 0.0, "proxy:cfs_net_income_from_income_statement")
    return additions


def _upsert_annual_rows(db, import_id: Any, rows: list[AnnualMetricRow], *, overwrite_proxies: bool = False) -> tuple[int, int, int]:
    if not rows:
        return 0, 0, 0
    row_by_key: dict[tuple[str, int, str], AnnualMetricRow] = {}
    for row in rows:
        if row.metric_value is None:
            continue
        key = (row.symbol.upper(), int(row.statement_year), row.metric_name)
        current = row_by_key.get(key)
        if current is None or _row_rank(row) > _row_rank(current):
            row_by_key[key] = row
    symbols = sorted({key[0] for key in row_by_key})
    years = sorted({key[1] for key in row_by_key})
    existing = {
        (row.symbol.upper(), int(row.statement_year), row.metric_name): row
        for row in db.query(models.FundamentalAnnualMetric)
        .filter(
            models.FundamentalAnnualMetric.import_id == import_id,
            models.FundamentalAnnualMetric.symbol.in_(symbols),
            models.FundamentalAnnualMetric.statement_year.in_(years),
        )
        .all()
    }
    inserted = updated = skipped = 0
    for key, row in row_by_key.items():
        current = existing.get(key)
        if current is None:
            db.add(
                models.FundamentalAnnualMetric(
                    import_id=import_id,
                    symbol=row.symbol.upper(),
                    company_name=row.company_name,
                    statement_year=int(row.statement_year),
                    metric_name=row.metric_name,
                    metric_value=row.metric_value,
                    raw_metric_name=row.raw_metric_name,
                    source_sheet=row.source_sheet,
                    source_field=row.source_field,
                    is_proxy=row.is_proxy,
                    as_of_date=row.as_of_date,
                    source_document_id=row.source_document_id,
                )
            )
            inserted += 1
            continue
        should_update = current.metric_value is None or (overwrite_proxies and bool(current.is_proxy) and not row.is_proxy)
        if should_update and row.metric_value is not None:
            current.metric_value = row.metric_value
            current.raw_metric_name = row.raw_metric_name
            current.source_sheet = row.source_sheet
            current.source_field = row.source_field
            current.is_proxy = row.is_proxy
            current.as_of_date = row.as_of_date or current.as_of_date
            current.source_document_id = row.source_document_id or current.source_document_id
            db.add(current)
            updated += 1
        else:
            skipped += 1
    db.flush()
    return inserted, updated, skipped


def _set_repair_metric(
    db,
    *,
    import_id: Any,
    symbol: str,
    year: int,
    metric_name: str,
    value: float,
    template: AnnualMetricRow,
    source_field: str,
) -> bool:
    current = (
        db.query(models.FundamentalAnnualMetric)
        .filter(
            models.FundamentalAnnualMetric.import_id == import_id,
            models.FundamentalAnnualMetric.symbol == symbol.upper(),
            models.FundamentalAnnualMetric.statement_year == int(year),
            models.FundamentalAnnualMetric.metric_name == metric_name,
        )
        .first()
    )
    if current is None:
        db.add(
            models.FundamentalAnnualMetric(
                import_id=import_id,
                symbol=symbol.upper(),
                company_name=template.company_name,
                statement_year=int(year),
                metric_name=metric_name,
                metric_value=float(value),
                raw_metric_name=source_field,
                source_sheet="bvc_deterministic_integrity_repair",
                source_field=source_field,
                is_proxy=True,
                as_of_date=template.as_of_date,
                source_document_id=template.source_document_id,
            )
        )
        return True
    old = _safe_float(current.metric_value)
    if old is not None and abs(old - float(value)) <= max(abs(float(value)), 1.0) * 1e-9:
        return False
    current.metric_value = float(value)
    current.raw_metric_name = source_field
    current.source_sheet = "bvc_deterministic_integrity_repair"
    current.source_field = source_field
    current.is_proxy = True
    current.as_of_date = template.as_of_date or current.as_of_date
    current.source_document_id = template.source_document_id or current.source_document_id
    db.add(current)
    return True


def _repair_integrity_rows(db, *, import_id: Any, symbols: Iterable[str], years: Iterable[int]) -> int:
    rows = _existing_rows(db, import_id, symbols, years)
    grouped: dict[tuple[str, int], list[AnnualMetricRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.symbol.upper(), int(row.statement_year))].append(row)
    repaired = 0
    for (symbol, year), group_rows in sorted(grouped.items()):
        by_metric = _best_by_metric(group_rows)
        template = sorted(group_rows, key=_row_rank, reverse=True)[0]
        assets = _metric_value(by_metric, "Total_Assets", "Total_Actif")
        equity = _metric_value(by_metric, "Total_Equity", "Equity", "Capitaux_propres", "Clean_Capitaux_propres")
        liabilities = _metric_value(by_metric, "Total_Liabilities")
        if assets is not None and equity is not None and assets > 0:
            repaired_liabilities = assets - equity
            imbalance = None
            if liabilities is not None:
                imbalance = abs((assets - liabilities - equity) / max(abs(assets), 1.0))
            if repaired_liabilities >= 0 and (liabilities is None or (imbalance is not None and imbalance > 0.02)):
                if _set_repair_metric(
                    db,
                    import_id=import_id,
                    symbol=symbol,
                    year=year,
                    metric_name="Total_Liabilities",
                    value=repaired_liabilities,
                    template=template,
                    source_field="repair:assets_minus_equity_for_bs_balance",
                ):
                    repaired += 1
                by_metric["Total_Liabilities"] = _proxy_row(template, "Total_Liabilities", repaired_liabilities, "repair:assets_minus_equity_for_bs_balance") or by_metric.get("Total_Liabilities")

        bs_cash = _metric_value(by_metric, "BS_Cash_and_Equivalents", "Cash_and_Equivalents", "Cash", "Tresorerie_Actif")
        ending = _metric_value(by_metric, "CFS_Ending_Cash", "Ending_Cash")
        if bs_cash is not None and bs_cash >= 0:
            mismatch = None
            if ending is not None:
                mismatch = abs((ending - bs_cash) / max(abs(bs_cash), 1.0))
            if ending is None or (mismatch is not None and mismatch > 0.05):
                for metric_name in ("CFS_Ending_Cash", "Ending_Cash"):
                    if _set_repair_metric(
                        db,
                        import_id=import_id,
                        symbol=symbol,
                        year=year,
                        metric_name=metric_name,
                        value=bs_cash,
                        template=template,
                        source_field="repair:ending_cash_from_balance_sheet_cash",
                    ):
                        repaired += 1
                cfo = _metric_value(by_metric, "CF_Operating", "Operating_Cash_Flow")
                cfi = _metric_value(by_metric, "CF_Investing")
                cff = _metric_value(by_metric, "CF_Financing")
                fx = _metric_value(by_metric, "CF_FX_Effect") or 0.0
                if cfo is not None and cfi is not None and cff is not None:
                    beginning = bs_cash - (cfo + cfi + cff + fx)
                    for metric_name in ("CFS_Beginning_Cash", "Beginning_Cash"):
                        if _set_repair_metric(
                            db,
                            import_id=import_id,
                            symbol=symbol,
                            year=year,
                            metric_name=metric_name,
                            value=beginning,
                            template=template,
                            source_field="repair:ending_cash_minus_cash_flow_components",
                        ):
                            repaired += 1
    db.flush()
    return repaired


ALIAS_OUTLIER_REPAIR_TARGETS: dict[str, tuple[str, ...]] = {
    "Debt_Total": ("Total_Debt", "Dettes_de_financement"),
    "Equity": ("Total_Equity", "Capitaux_propres", "Clean_Capitaux_propres"),
}


def _repair_alias_outlier_rows(db, *, import_id: Any, symbols: Iterable[str], years: Iterable[int]) -> int:
    symbols_set = {symbol.upper() for symbol in symbols}
    years_set = {int(year) for year in years}
    metric_names = set(ALIAS_OUTLIER_REPAIR_TARGETS)
    for targets in ALIAS_OUTLIER_REPAIR_TARGETS.values():
        metric_names.update(targets)
    rows = (
        db.query(models.FundamentalAnnualMetric)
        .filter(
            models.FundamentalAnnualMetric.import_id == import_id,
            models.FundamentalAnnualMetric.symbol.in_(sorted(symbols_set)),
            models.FundamentalAnnualMetric.statement_year.in_(sorted(years_set)),
            models.FundamentalAnnualMetric.metric_name.in_(sorted(metric_names)),
            models.FundamentalAnnualMetric.metric_value.isnot(None),
        )
        .all()
    )
    grouped: dict[tuple[str, int], dict[str, list[Any]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        grouped[(str(row.symbol).upper(), int(row.statement_year))][str(row.metric_name)].append(row)

    repaired = 0
    repairable_sheets = {
        "bvc_deterministic_pdf",
        "bvc_deterministic_proxy",
        "bvc_deterministic_integrity_repair",
    }
    for (_symbol, _year), by_metric in grouped.items():
        for alias, targets in ALIAS_OUTLIER_REPAIR_TARGETS.items():
            alias_rows = by_metric.get(alias, [])
            if not alias_rows:
                continue
            target_row = None
            for target in targets:
                candidates = [row for row in by_metric.get(target, []) if _safe_float(row.metric_value) is not None]
                if candidates:
                    target_row = sorted(candidates, key=_model_row_rank, reverse=True)[0]
                    break
            if target_row is None:
                continue
            target_value = _safe_float(target_row.metric_value)
            if target_value is None:
                continue
            for row in alias_rows:
                current_value = _safe_float(row.metric_value)
                if current_value is None:
                    continue
                if str(row.source_sheet or "") not in repairable_sheets:
                    continue
                if abs(current_value - target_value) <= max(abs(target_value), 1.0) * 0.25:
                    continue
                row.metric_value = float(target_value)
                row.raw_metric_name = row.raw_metric_name or alias
                row.source_sheet = "bvc_deterministic_integrity_repair"
                row.source_field = f"repair:{alias}_from_{target_row.metric_name}"
                row.is_proxy = True
                row.as_of_date = row.as_of_date or target_row.as_of_date
                row.source_document_id = row.source_document_id or target_row.source_document_id
                db.add(row)
                repaired += 1
    db.flush()
    return repaired


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


def _active_top_symbols(db, top_n: int) -> list[str]:
    snapshots = latest_snapshot_rows_by_symbol(db, scope="masi")
    ranked: list[tuple[float, str]] = []
    for symbol, snapshot in snapshots.items():
        metrics = dict(snapshot.metrics_json or {})
        market_cap = _safe_float(metrics.get("MarketCap_Calc")) or 0.0
        if market_cap > 0:
            ranked.append((market_cap, symbol.upper()))
    return [symbol for _market_cap, symbol in sorted(ranked, reverse=True)[:top_n]]


def _stock_context(db, symbols: list[str]) -> dict[str, dict[str, Any]]:
    rows = (
        db.query(models.StockMaster)
        .filter(models.StockMaster.symbol.in_(symbols))
        .all()
    )
    return {
        str(row.symbol).upper(): {
            "display_name": row.display_name or row.symbol,
            "sector": row.sector,
            "shares_outstanding": row.shares_outstanding,
        }
        for row in rows
    }


def _refresh_downstream(db, symbols: list[str], import_ids_by_symbol: dict[str, Any]) -> dict[str, Any]:
    scope = _scope_for_symbols(db, symbols)
    scored_count = rescore_universe(db, scope=scope)
    for import_id in sorted(set(import_ids_by_symbol.values()), key=str):
        persist_pillar_history_for_import(db, import_id=import_id)
    valuation_count = 0
    loader = make_bulk_overrides_loader(db, symbols)
    refreshed_snapshots = latest_snapshot_rows_by_symbol(db, symbols=symbols, scope="masi")
    for symbol in symbols:
        snapshot = refreshed_snapshots.get(symbol)
        if snapshot is None:
            continue
        valuation_count += len(
            recompute_symbol_valuations_all_scenarios(
                db,
                import_id=snapshot.import_id,
                symbol=symbol,
                overrides_loader=loader,
            )
        )
    signal_rows = upsert_fundamental_signal_rows(db, symbols=symbols)
    return {"rescored_snapshot_count": scored_count, "valuation_row_count": valuation_count, "signal_rows": signal_rows}


def run(*, top_n: int, symbols_arg: list[str] | None, years: list[int], dry_run: bool) -> dict[str, Any]:
    db = SessionLocal()
    try:
        symbols = sorted({symbol.upper() for symbol in (symbols_arg or _active_top_symbols(db, top_n))})
        symbols = [symbol for symbol in symbols if symbol in DOCS]
        if not symbols:
            raise RuntimeError("No supported top-five BVC symbols found.")
        years = sorted({int(year) for year in years})
        snapshots = latest_snapshot_rows_by_symbol(db, symbols=symbols, scope="masi")
        missing_snapshots = sorted(set(symbols) - set(snapshots))
        if missing_snapshots:
            raise RuntimeError(f"Missing active snapshots for: {', '.join(missing_snapshots)}")
        import_ids = {symbol: snapshots[symbol].import_id for symbol in symbols}
        stocks = _stock_context(db, symbols)
        before_rows: list[AnnualMetricRow] = []
        for import_id in sorted(set(import_ids.values()), key=str):
            import_symbols = [symbol for symbol, item_import_id in import_ids.items() if item_import_id == import_id]
            before_rows.extend(_existing_rows(db, import_id, import_symbols, years))
        before_missing = _missing_groups(before_rows, symbols, years)

        extracted_by_symbol: dict[str, int] = defaultdict(int)
        direct_rows_by_import: dict[Any, list[AnnualMetricRow]] = defaultdict(list)
        doc_id_by_symbol_year: dict[tuple[str, int], int | None] = {}
        download_errors: list[dict[str, Any]] = []
        if dry_run:
            db.close()

        for symbol in symbols:
            for meta in [doc for doc in DOCS[symbol] if doc.fiscal_year in years]:
                try:
                    path = _download_pdf(meta)
                    extracted = _extract_from_pdf_cached(path, meta)
                except Exception as exc:
                    download_errors.append({"symbol": symbol, "year": meta.fiscal_year, "url": meta.url, "error": str(exc)})
                    continue
                document_id: int | None = None
                if not dry_run:
                    try:
                        document = _source_document(db, import_ids[symbol], meta, len(extracted))
                    except Exception:
                        db.rollback()
                        db.close()
                        db = SessionLocal()
                        document = _source_document(db, import_ids[symbol], meta, len(extracted))
                    document_id = int(document.id)
                doc_id_by_symbol_year[(symbol, meta.fiscal_year)] = document_id
                rows_with_doc = [
                    AnnualMetricRow(
                        symbol=row.symbol,
                        company_name=stocks.get(symbol, {}).get("display_name") or row.company_name,
                        statement_year=row.statement_year,
                        metric_name=row.metric_name,
                        metric_value=row.metric_value,
                        raw_metric_name=row.raw_metric_name,
                        source_sheet=row.source_sheet,
                        source_field=row.source_field,
                        is_proxy=row.is_proxy,
                        as_of_date=row.as_of_date,
                        source_document_id=document_id,
                    )
                    for row in extracted
                ]
                direct_rows_by_import[import_ids[symbol]].extend(rows_with_doc)
                extracted_by_symbol[symbol] += len(rows_with_doc)

        mapped_by_import: dict[Any, list[AnnualMetricRow]] = defaultdict(list)
        for import_id, rows in direct_rows_by_import.items():
            mapped_by_import[import_id].extend(map_cgnc_annual_metrics(rows))
            mapped_by_import[import_id].extend(_extra_direct_aliases(rows))

        proxy_by_import: dict[Any, list[AnnualMetricRow]] = defaultdict(list)
        combined_seed_rows: dict[Any, list[AnnualMetricRow]] = defaultdict(list)
        for import_id in sorted(set(import_ids.values()), key=str):
            import_symbols = [symbol for symbol, item_import_id in import_ids.items() if item_import_id == import_id]
            combined_seed_rows[import_id].extend(_existing_rows(db, import_id, import_symbols, years))
            combined_seed_rows[import_id].extend(mapped_by_import.get(import_id, []))

        for symbol in symbols:
            import_id = import_ids[symbol]
            context = stocks.get(symbol, {})
            for year in years:
                proxy_by_import[import_id].extend(
                    _ensure_bridges(
                        symbol=symbol,
                        sector=context.get("sector"),
                        year=year,
                        company_name=context.get("display_name") or symbol,
                        rows=combined_seed_rows[import_id] + proxy_by_import[import_id],
                        doc_id=doc_id_by_symbol_year.get((symbol, year)),
                    )
                )

        write_summary: dict[str, Any] = {}
        if not dry_run:
            for import_id in sorted(set(import_ids.values()), key=str):
                rows_to_write = [*mapped_by_import.get(import_id, []), *proxy_by_import.get(import_id, [])]
                inserted, updated, skipped = _upsert_annual_rows(db, import_id, rows_to_write, overwrite_proxies=True)
                import_symbols = {symbol for symbol, item_import_id in import_ids.items() if item_import_id == import_id}
                alias_repaired = _repair_alias_outlier_rows(db, import_id=import_id, symbols=import_symbols, years=years)
                repaired = _repair_integrity_rows(db, import_id=import_id, symbols=import_symbols, years=years)
                _sync_latest_snapshots_from_annual(db, import_id=import_id, symbols=import_symbols)
                history = [row for row in _load_history(db, import_id) if row.symbol.upper() in import_symbols and row.statement_year in years]
                _persist_integrity_reports(db, import_id=import_id, reports=_build_integrity_reports(history))
                import_row = db.get(models.FundamentalImport, import_id)
                if import_row is not None:
                    summary = dict(import_row.summary_json or {})
                    summary["top5_bvc_deterministic_backfill"] = {
                        "symbols": sorted(import_symbols),
                        "years": years,
                        "direct_rows": len(mapped_by_import.get(import_id, [])),
                        "proxy_rows": len(proxy_by_import.get(import_id, [])),
                        "inserted": inserted,
                        "updated": updated,
                        "alias_outlier_repaired": alias_repaired,
                        "integrity_repaired": repaired,
                        "skipped_existing": skipped,
                        "completed_at": _utcnow().isoformat(),
                    }
                    import_row.summary_json = sanitize_json_compatible(summary)
                    flag_modified(import_row, "summary_json")
                    db.add(import_row)
                write_summary[str(import_id)] = {
                    "inserted": inserted,
                    "updated": updated,
                    "skipped_existing": skipped,
                    "alias_outlier_repaired": alias_repaired,
                    "integrity_repaired": repaired,
                    "direct_rows": len(mapped_by_import.get(import_id, [])),
                    "proxy_rows": len(proxy_by_import.get(import_id, [])),
                }
            db.commit()
            downstream = _refresh_downstream(db, symbols, import_ids)
            db.commit()
        else:
            downstream = {"dry_run": True}

        after_rows: list[AnnualMetricRow] = []
        for import_id in sorted(set(import_ids.values()), key=str):
            import_symbols = [symbol for symbol, item_import_id in import_ids.items() if item_import_id == import_id]
            after_rows.extend(_existing_rows(db, import_id, import_symbols, years))
            if dry_run:
                after_rows.extend(mapped_by_import.get(import_id, []))
                after_rows.extend(proxy_by_import.get(import_id, []))
        after_missing = _missing_groups(after_rows, symbols, years)
        result = {
            "dry_run": dry_run,
            "symbols": symbols,
            "years": years,
            "import_ids": {symbol: str(import_id) for symbol, import_id in import_ids.items()},
            "before_missing": before_missing,
            "after_missing": after_missing,
            "extracted_direct_rows_by_symbol": dict(extracted_by_symbol),
            "download_errors": download_errors,
            "write_summary": write_summary,
            "downstream": downstream,
            "required_group_count": len(REQUIRED_GROUPS),
        }
        AUDIT_DIR.mkdir(parents=True, exist_ok=True)
        audit_path = AUDIT_DIR / f"top5_bvc_deterministic_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        audit_path.write_text(json.dumps(sanitize_json_compatible(result), indent=2, sort_keys=True), encoding="utf-8")
        result["audit_path"] = str(audit_path)
        return result
    finally:
        db.close()


def _extra_direct_aliases(rows: list[AnnualMetricRow]) -> list[AnnualMetricRow]:
    out: list[AnnualMetricRow] = []
    for row in rows:
        value = _safe_float(row.metric_value)
        if value is None:
            continue
        aliases: tuple[str, ...] = ()
        if row.metric_name == "Marge_dinteret":
            aliases = ("Net_Interest_Expense",)
        elif row.metric_name == "CFS_Beginning_Cash":
            aliases = ("Beginning_Cash",)
        elif row.metric_name == "CFS_Ending_Cash":
            aliases = ("Ending_Cash", "Cash", "Cash_and_Equivalents")
        elif row.metric_name == "CFS_Net_Income_Top_Of_CFS":
            aliases = ()
        elif row.metric_name == "Total_Liabilities":
            aliases = ()
        elif row.metric_name == "Retained_Earnings":
            aliases = ("Reserves",)
        for alias in aliases:
            out.append(
                AnnualMetricRow(
                    symbol=row.symbol,
                    company_name=row.company_name,
                    statement_year=row.statement_year,
                    metric_name=alias,
                    metric_value=value,
                    raw_metric_name=row.raw_metric_name or row.metric_name,
                    source_sheet=row.source_sheet,
                    source_field=row.source_field or row.metric_name,
                    is_proxy=row.is_proxy,
                    as_of_date=row.as_of_date,
                    source_document_id=row.source_document_id,
                )
            )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Deterministically backfill BVC top-five annual fundamentals without Gemini.")
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--symbols", default="", help="Comma-separated symbols. Defaults to active top N by market cap.")
    parser.add_argument("--years", default="2021,2022,2023,2024,2025")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()] or None
    years = [int(item.strip()) for item in args.years.split(",") if item.strip()]
    result = run(top_n=args.top_n, symbols_arg=symbols, years=years, dry_run=bool(args.dry_run))
    print(json.dumps(sanitize_json_compatible(result), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
