"""
Asset taxonomy utilities: auto-detect asset_type and market_region from symbol.

asset_type  : "equity" | "commodity" | "forex" | "bond" | "crypto"
market_region: "masi" | "us" | "european" | "asian" | None
"""
from __future__ import annotations

_FOREX_ROOTS = {
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "USDCAD",
    "EURGBP", "EURJPY", "GBPJPY", "EURCHF", "AUDJPY", "CADJPY", "CHFJPY",
    "EURAUD", "EURCAD", "EURNZD", "GBPAUD", "GBPCAD", "GBPNZD",
    "USDMAD", "EURMAD", "GBPMAD", "USDBRL", "USDMXN", "USDINR",
    "USDCNH", "USDHKD", "USDSGD", "USDTRY", "USDZAR", "USDRUB",
    "DXY", "DXYF", "DX-Y.NYB", "DXYNB",
}
# Yahoo Finance appends "=X" to forex pairs
_FOREX_SUFFIXES = {"=X"}         # Yahoo Finance forex suffix; =F is futures (commodity)

_COMMODITY_ROOTS = {
    "BRENT", "WTI", "CRUD", "OIL", "NGAS", "NATGAS", "NG",
    "GOLD", "XAU", "SILVER", "XAG", "PLATINUM", "XPT", "PALLADIUM", "XPD",
    "COPPER", "ALU", "ALUMINIUM", "NICKEL", "ZINC", "LEAD", "TIN",
    "CORN", "WHEAT", "SOYA", "SOYBEAN", "SUGAR", "COFFEE", "COCOA", "COTTON",
    "BZ", "BZF", "BZ=F", "GC", "GC=F", "SI", "SI=F", "CL", "CL=F",
    "HG", "HG=F", "NG", "NG=F", "ZC", "ZC=F", "ZW", "ZW=F", "ZS", "ZS=F",
}

_BOND_ROOTS = {
    "US10Y", "US2Y", "US5Y", "US30Y", "US1Y", "US3M", "US6M",
    "TNX", "^TNX", "TYX", "^TYX", "FVX", "^FVX", "IRX", "^IRX",
    "TBOND", "TBILL", "TNOTE",
    "OAT10Y", "BUND10Y", "GILT10Y", "JGB10Y", "MA10Y",
    "EM10Y", "IG10Y", "HY10Y",
}

_MASI_REGION_TRACK_SOURCES = {"bourse_direct", "casablanca_bourse", "bmce_excel"}


def _strip_exchange_suffix(symbol: str) -> str:
    """Remove Yahoo-style exchange suffixes like .PA, .L, .T, =X, =F."""
    for sep in ("=", "."):
        if sep in symbol:
            return symbol.split(sep)[0]
    return symbol


def detect_asset_type(
    symbol: str,
    track_source: str | None = None,
    is_masi: bool = False,
) -> tuple[str, str | None]:
    """
    Returns (asset_type, market_region).

    Priority:
    1. Explicit MASI flag → equity / masi
    2. Forex patterns
    3. Commodity patterns
    4. Bond patterns
    5. track_source hint for regional equity classification
    6. Default equity (unknown region)
    """
    s = symbol.upper().strip()

    if is_masi:
        return ("equity", "masi")

    # Raw match
    if s in _FOREX_ROOTS or any(s.endswith(suf) for suf in _FOREX_SUFFIXES):
        return ("forex", None)
    if s in _COMMODITY_ROOTS:
        return ("commodity", None)
    if s in _BOND_ROOTS:
        return ("bond", None)

    # Strip Yahoo suffix (=X for forex, =F for futures) and retry
    root = _strip_exchange_suffix(s)
    if s.endswith("=F") or s.endswith("=X"):
        if root in _FOREX_ROOTS:
            return ("forex", None)
        if root in _COMMODITY_ROOTS:
            return ("commodity", None)
        if root in _BOND_ROOTS:
            return ("bond", None)
        # Unknown =F suffix → treat as commodity (Yahoo futures convention)
        if s.endswith("=F"):
            return ("commodity", None)
    if root in _FOREX_ROOTS:
        return ("forex", None)
    if root in _COMMODITY_ROOTS:
        return ("commodity", None)
    if root in _BOND_ROOTS:
        return ("bond", None)

    # 6-char currency pair heuristic (e.g. EURUSD without =X)
    if len(root) == 6 and root.isalpha():
        majors = {"USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD", "MAD"}
        if root[:3] in majors and root[3:] in majors:
            return ("forex", None)

    # track_source hints for regional classification
    if track_source in _MASI_REGION_TRACK_SOURCES:
        return ("equity", "masi")

    return ("equity", None)
