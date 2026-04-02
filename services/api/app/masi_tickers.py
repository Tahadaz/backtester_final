"""Canonical MASI (Moroccan All Shares Index) ticker registry.

Sector labels are progressively aligned to Bourse de Casablanca wording.
Where we do not have a confident official match yet, we keep the prior label
as a conservative fallback instead of inventing a category.

Last updated: 2026-03-26.
"""

from __future__ import annotations

_RAW_MASI_TICKERS: dict[str, dict[str, str]] = {
    "ADH": {"display_name": "Douja Promotion Groupe Addoha", "sector": "Immobilier"},
    "ADI": {"display_name": "Alliances", "sector": "Immobilier"},
    "AFI": {"display_name": "Afric Industries", "sector": "Distribution"},
    "AFM": {"display_name": "AFMA", "sector": "Assurances"},
    "AGM": {"display_name": "AGMA", "sector": "Assurances"},
    "AKT": {"display_name": "Akdital", "sector": "Autre"},
    "ALM": {"display_name": "Aluminium du Maroc", "sector": "Mines"},
    "ARD": {"display_name": "Aradei Capital", "sector": "Immobilier"},
    "ATH": {"display_name": "Auto Hall", "sector": "Distribution"},
    "ATL": {"display_name": "AtlantaSanad", "sector": "Assurances"},
    "ATW": {"display_name": "Attijariwafa Bank", "sector": "Banques"},
    "BAL": {"display_name": "Balima", "sector": "Immobilier"},
    "BCI": {"display_name": "BMCI", "sector": "Banques"},
    "BCP": {"display_name": "Banque Centrale Populaire", "sector": "Banques"},
    "BOA": {"display_name": "Bank of Africa", "sector": "Banques"},
    "CAP": {"display_name": "Cash Plus", "sector": "Autre"},
    "CDA": {"display_name": "Centrale Danone", "sector": "Agroalimentaire"},
    "CDM": {"display_name": "Crédit du Maroc", "sector": "Banques"},
    "CFG": {"display_name": "CFG Bank", "sector": "Banques"},
    "CIH": {"display_name": "CIH Bank", "sector": "Banques"},
    "CMA": {"display_name": "Ciments du Maroc", "sector": "BTP"},
    "CMG": {"display_name": "CMGP Group", "sector": "Autre"},
    "CMT": {"display_name": "Compagnie Minière de Touissit", "sector": "Mines"},
    "COL": {"display_name": "Colorado", "sector": "BTP"},
    "CRS": {"display_name": "Cartier Saada", "sector": "Agroalimentaire"},
    "CSR": {"display_name": "Cosumar", "sector": "Agroalimentaire"},
    "CTM": {"display_name": "CTM", "sector": "Transport"},
    "DHO": {"display_name": "Delta Holding", "sector": "BTP"},
    "DIS": {"display_name": "Diac Salaf", "sector": "Autre"},
    "DLM": {"display_name": "Delattre Levivier Maroc", "sector": "BTP"},
    "DRI": {"display_name": "Dari Couspate", "sector": "Agroalimentaire"},
    "DWY": {"display_name": "Disway", "sector": "Distribution"},
    "DYT": {"display_name": "Disty Technologies", "sector": "Distribution"},
    "EQD": {"display_name": "Eqdom", "sector": "Autre"},
    "FBR": {"display_name": "Fenie Brossette", "sector": "Distribution"},
    "GAZ": {"display_name": "Afriquia Gaz", "sector": "Energie"},
    "GTM": {"display_name": "SGTM", "sector": "BTP"},
    "HPS": {"display_name": "HPS", "sector": "Autre"},
    "IAM": {"display_name": "Maroc Telecom", "sector": "Télécommunications"},
    "IBC": {"display_name": "IB Maroc.com", "sector": "Autre"},
    "IMO": {"display_name": "Immorente Invest", "sector": "Immobilier"},
    "INV": {"display_name": "Involys", "sector": "Autre"},
    "JET": {"display_name": "Jet Contractors", "sector": "BTP"},
    "LBV": {"display_name": "Label Vie", "sector": "Distribution"},
    "LES": {"display_name": "Lesieur Cristal", "sector": "Agroalimentaire"},
    "LHM": {"display_name": "LafargeHolcim Maroc", "sector": "BTP"},
    "LYD": {"display_name": "Lydec", "sector": "Energie"},
    "M2M": {"display_name": "M2M Group", "sector": "Autre"},
    "MAB": {"display_name": "Maghrebail", "sector": "Autre"},
    "MDP": {"display_name": "Med Paper", "sector": "Autre"},
    "MIC": {"display_name": "Microdata", "sector": "Autre"},
    "MLE": {"display_name": "Maroc Leasing", "sector": "Autre"},
    "MNG": {"display_name": "Managem", "sector": "Mines"},
    "MOX": {"display_name": "Maghreb Oxygène", "sector": "Autre"},
    "MSA": {"display_name": "Marsa Maroc", "sector": "Transport"},
    "MUT": {"display_name": "Mutandis", "sector": "Agroalimentaire"},
    "NEJ": {"display_name": "Auto Nejma", "sector": "Distribution"},
    "NEX": {"display_name": "Nexans Maroc", "sector": "Autre"},
    "NKL": {"display_name": "Ennakl", "sector": "Distribution"},
    "OUL": {"display_name": "Oulmès", "sector": "Agroalimentaire"},
    "PRO": {"display_name": "Promopharm", "sector": "Autre"},
    "RDS": {"display_name": "Résidences Dar Saada", "sector": "Immobilier"},
    "REB": {"display_name": "Rebab Company", "sector": "Autre"},
    "RIS": {"display_name": "Risma", "sector": "Autre"},
    "S2M": {"display_name": "S2M", "sector": "Autre"},
    "SAH": {"display_name": "Sanlam Maroc", "sector": "Assurances"},
    "SBM": {"display_name": "Société des Boissons du Maroc", "sector": "Agroalimentaire"},
    "SID": {"display_name": "Sonasid", "sector": "Mines"},
    "SLF": {"display_name": "Salafin", "sector": "Autre"},
    "SMI": {"display_name": "SMI", "sector": "Mines"},
    "SNA": {"display_name": "Stokvis Nord Afrique", "sector": "Distribution"},
    "SNP": {"display_name": "SNEP", "sector": "Autre"},
    "SOT": {"display_name": "Sothema", "sector": "Autre"},
    "SRM": {"display_name": "SRM", "sector": "Autre"},
    "STR": {"display_name": "Stroc Industrie", "sector": "BTP"},
    "TGC": {"display_name": "TGCC", "sector": "BTP"},
    "TIM": {"display_name": "Timar", "sector": "Transport"},
    "TMA": {"display_name": "TotalEnergies Marketing Maroc", "sector": "Energie"},
    "TQM": {"display_name": "TAQA Morocco", "sector": "Energie"},
    "UMR": {"display_name": "Unimer", "sector": "Agroalimentaire"},
    "VCN": {"display_name": "Vicenne", "sector": "Autre"},
    "WAA": {"display_name": "Wafa Assurance", "sector": "Assurances"},
    "ZDJ": {"display_name": "Zellidja", "sector": "Mines"},
}

_OFFICIAL_SECTOR_ALIASES: dict[str, str] = {
    "Immobilier": "Immobilier",
    "Distribution": "Distribution",
    "Agroalimentaire": "Agroalimentaire",
    "BTP": "BTP",
    "Transport": "Transport",
}

_OFFICIAL_SECTOR_OVERRIDES: dict[str, str] = {
    "AFI": "BTP",
    "AKT": "Santé",
    "ALM": "BTP",
    "CAP": "Sociétés de financement",
    "CMG": "Industrie",
    "DIS": "Sociétés de financement",
    "DLM": "Industrie",
    "DWY": "Informatique",
    "DYT": "Informatique",
    "EQD": "Sociétés de financement",
    "GAZ": "Énergie",
    "HPS": "Informatique",
    "IBC": "Informatique",
    "INV": "Informatique",
    "LYD": "Services publics",
    "M2M": "Informatique",
    "MAB": "Sociétés de financement",
    "MIC": "Informatique",
    "MLE": "Sociétés de financement",
    "MOX": "Chimie",
    "MSA": "Transport",
    "NEX": "Industrie",
    "PRO": "Santé",
    "REB": "Mines",
    "RIS": "Loisirs & Hôtels",
    "SBM": "Boissons",
    "SID": "BTP",
    "SLF": "Sociétés de financement",
    "SNA": "Distribution",
    "SNP": "Chimie",
    "SOT": "Santé",
    "STR": "Industrie",
    "TMA": "Énergie",
    "TQM": "Électricité",
    "VCN": "Santé",
}


def _official_sector(symbol: str, legacy_sector: str) -> str:
    return _OFFICIAL_SECTOR_OVERRIDES.get(
        symbol,
        _OFFICIAL_SECTOR_ALIASES.get(legacy_sector, legacy_sector),
    )


MASI_TICKERS: dict[str, dict[str, str]] = {
    symbol: {
        "display_name": info["display_name"],
        "sector": _official_sector(symbol, info["sector"]),
    }
    for symbol, info in _RAW_MASI_TICKERS.items()
}


def _normalize(symbol: str) -> str:
    """Normalize ticker: strip, uppercase, remove common suffixes (.MA, .CS)."""
    s = symbol.strip().upper()
    for suffix in (".MA", ".CS"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s


def is_masi_ticker(symbol: str) -> bool:
    return _normalize(symbol) in MASI_TICKERS


def get_masi_info(symbol: str) -> dict[str, str] | None:
    return MASI_TICKERS.get(_normalize(symbol))


def all_masi_tickers() -> list[dict[str, str]]:
    return [
        {"symbol": sym, **info}
        for sym, info in sorted(MASI_TICKERS.items())
    ]
