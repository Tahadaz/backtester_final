"""Global security master for cross-asset research.

Pure data plus lookup. No I/O, no SQLAlchemy, no FastAPI, no network client --
this module is imported by the quant core, the API router and the worker alike.

Every instrument declares:

* an ordered tuple of Bloomberg ticker candidates (the bridge probes them in
  order, exactly as it already does for MASI equities);
* a free-data fallback, or an explicit ``None`` with a stated reason;
* the engine metadata ``cross_asset.instruments`` needs (currency, point value,
  roll rule);
* ``history_start`` and ``history_note`` as *data*, so a backtest reads the
  regime boundary instead of silently starting wherever the download happens to
  begin (program decision G11).

Nothing here assumes Bloomberg is entitled (G9). ``free_proxy`` is the path that
must keep working when it is not.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal


SourceTag = Literal["bloomberg", "free_proxy", "fixture"]
"""Provenance of a resolved series. Must survive into the run record (G5)."""

AssetClass = Literal["fx", "rates", "credit", "commodity", "equity_index", "equity"]

FreeProxySource = Literal["yfinance", "fred", "none"]


@dataclass(frozen=True)
class SecurityMasterEntry:
    """One tradable (or proxy-able) instrument."""

    canonical_id: str
    asset_class: AssetClass
    description: str
    currency: str
    history_start: date
    history_note: str
    bloomberg_candidates: tuple[str, ...] = ()
    bloomberg_verified: bool = False
    free_proxy: str | None = None
    free_proxy_source: FreeProxySource = "none"
    free_proxy_note: str = ""
    point_value: float = 1.0
    quote_convention: str = ""
    roll_rule: str | None = None
    tick_size: float | None = None
    base_ccy: str = ""
    quote_ccy: str = ""
    market_region: str = "global"
    tags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.canonical_id or not self.canonical_id.strip():
            raise ValueError("canonical_id is required")
        if not self.currency:
            raise ValueError(f"{self.canonical_id}: currency is required")
        if self.point_value <= 0:
            raise ValueError(f"{self.canonical_id}: point_value must be positive")
        if not self.bloomberg_candidates:
            raise ValueError(f"{self.canonical_id}: at least one Bloomberg candidate is required")
        if self.free_proxy is None and not self.free_proxy_note:
            raise ValueError(
                f"{self.canonical_id}: free_proxy=None must state a reason in free_proxy_note"
            )
        if self.free_proxy is not None and self.free_proxy_source == "none":
            raise ValueError(f"{self.canonical_id}: free_proxy set but free_proxy_source is 'none'")
        if not self.history_note:
            raise ValueError(f"{self.canonical_id}: history_note is required (G11)")
        if self.roll_rule is not None:
            valid = self.roll_rule in {"first_notice", "volume_crossover"} or self.roll_rule.startswith(
                "n_days_before_expiry:"
            )
            if not valid:
                raise ValueError(f"{self.canonical_id}: unsupported roll_rule {self.roll_rule!r}")
        if self.asset_class == "fx" and not (self.base_ccy and self.quote_ccy):
            raise ValueError(f"{self.canonical_id}: fx entries require base_ccy and quote_ccy")

    @property
    def preferred_bloomberg_ticker(self) -> str:
        return self.bloomberg_candidates[0]

    @property
    def has_free_path(self) -> bool:
        return self.free_proxy is not None


# ---------------------------------------------------------------------------
# FX -- 9 G10 pairs.
#
# Canonical ids and yfinance tickers are kept byte-identical to FX_PAIRS in
# services/api/app/services/cross_asset/datasources.py:11 so the existing FX
# vertical resolves through this registry without changing its data.
# ---------------------------------------------------------------------------

_FX: tuple[SecurityMasterEntry, ...] = (
    SecurityMasterEntry(
        canonical_id="EURUSD",
        asset_class="fx",
        description="Euro / US dollar",
        currency="USD",
        base_ccy="EUR",
        quote_ccy="USD",
        quote_convention="USD per EUR",
        bloomberg_candidates=("EURUSD Curncy", "EUR Curncy"),
        free_proxy="EURUSD=X",
        free_proxy_source="yfinance",
        free_proxy_note="Spot only; carry needs FRED policy rates (FRED_RATE_SERIES).",
        history_start=date(1999, 1, 4),
        history_note="Euro launch. Pre-1999 EUR is a synthetic ECU/basket splice and is excluded.",
        tags=("g10",),
    ),
    SecurityMasterEntry(
        canonical_id="USDJPY",
        asset_class="fx",
        description="US dollar / Japanese yen",
        currency="JPY",
        base_ccy="USD",
        quote_ccy="JPY",
        quote_convention="JPY per USD",
        bloomberg_candidates=("USDJPY Curncy", "JPY Curncy"),
        free_proxy="JPY=X",
        free_proxy_source="yfinance",
        free_proxy_note="Spot only; carry needs FRED policy rates.",
        history_start=date(1990, 1, 1),
        history_note="Free-float since 1973; 1990 start keeps the sample within the modern policy regime.",
        tags=("g10",),
    ),
    SecurityMasterEntry(
        canonical_id="GBPUSD",
        asset_class="fx",
        description="Sterling / US dollar",
        currency="USD",
        base_ccy="GBP",
        quote_ccy="USD",
        quote_convention="USD per GBP",
        bloomberg_candidates=("GBPUSD Curncy", "GBP Curncy"),
        free_proxy="GBPUSD=X",
        free_proxy_source="yfinance",
        free_proxy_note="Spot only; carry needs FRED policy rates.",
        history_start=date(1993, 1, 1),
        history_note="Post-ERM-exit (Sep 1992). The ERM peg period is a different regime and is excluded.",
        tags=("g10",),
    ),
    SecurityMasterEntry(
        canonical_id="USDCHF",
        asset_class="fx",
        description="US dollar / Swiss franc",
        currency="CHF",
        base_ccy="USD",
        quote_ccy="CHF",
        quote_convention="CHF per USD",
        bloomberg_candidates=("USDCHF Curncy", "CHF Curncy"),
        free_proxy="CHF=X",
        free_proxy_source="yfinance",
        free_proxy_note="Spot only; carry needs FRED policy rates.",
        history_start=date(1990, 1, 1),
        history_note=(
            "Contains the SNB EURCHF floor (Sep 2011 - Jan 2015) and its removal, a one-day ~20% "
            "gap. Retained deliberately: it is the canonical tail event for FX carry and trend."
        ),
        tags=("g10",),
    ),
    SecurityMasterEntry(
        canonical_id="AUDUSD",
        asset_class="fx",
        description="Australian dollar / US dollar",
        currency="USD",
        base_ccy="AUD",
        quote_ccy="USD",
        quote_convention="USD per AUD",
        bloomberg_candidates=("AUDUSD Curncy", "AUD Curncy"),
        free_proxy="AUDUSD=X",
        free_proxy_source="yfinance",
        free_proxy_note="Spot only; carry needs FRED policy rates.",
        history_start=date(1990, 1, 1),
        history_note="Free-float since 1983; 1990 start aligns the G10 panel.",
        tags=("g10", "commodity_ccy"),
    ),
    SecurityMasterEntry(
        canonical_id="USDCAD",
        asset_class="fx",
        description="US dollar / Canadian dollar",
        currency="CAD",
        base_ccy="USD",
        quote_ccy="CAD",
        quote_convention="CAD per USD",
        bloomberg_candidates=("USDCAD Curncy", "CAD Curncy"),
        free_proxy="CAD=X",
        free_proxy_source="yfinance",
        free_proxy_note="Spot only; carry needs FRED policy rates.",
        history_start=date(1990, 1, 1),
        history_note="Aligned with the G10 panel start.",
        tags=("g10", "commodity_ccy"),
    ),
    SecurityMasterEntry(
        canonical_id="NZDUSD",
        asset_class="fx",
        description="New Zealand dollar / US dollar",
        currency="USD",
        base_ccy="NZD",
        quote_ccy="USD",
        quote_convention="USD per NZD",
        bloomberg_candidates=("NZDUSD Curncy", "NZD Curncy"),
        free_proxy="NZDUSD=X",
        free_proxy_source="yfinance",
        free_proxy_note="Spot only; carry needs FRED policy rates.",
        history_start=date(1990, 1, 1),
        history_note="Aligned with the G10 panel start. Thinner liquidity than the majors.",
        tags=("g10", "commodity_ccy"),
    ),
    SecurityMasterEntry(
        canonical_id="USDNOK",
        asset_class="fx",
        description="US dollar / Norwegian krone",
        currency="NOK",
        base_ccy="USD",
        quote_ccy="NOK",
        quote_convention="NOK per USD",
        bloomberg_candidates=("USDNOK Curncy", "NOK Curncy"),
        free_proxy="NOK=X",
        free_proxy_source="yfinance",
        free_proxy_note="Spot only; carry needs FRED policy rates.",
        history_start=date(1990, 1, 1),
        history_note="Scandi pair; materially wider spreads than the majors. Cost model must reflect that.",
        tags=("g10", "scandi"),
    ),
    SecurityMasterEntry(
        canonical_id="USDSEK",
        asset_class="fx",
        description="US dollar / Swedish krona",
        currency="SEK",
        base_ccy="USD",
        quote_ccy="SEK",
        quote_convention="SEK per USD",
        bloomberg_candidates=("USDSEK Curncy", "SEK Curncy"),
        free_proxy="SEK=X",
        free_proxy_source="yfinance",
        free_proxy_note="Spot only; carry needs FRED policy rates.",
        history_start=date(1993, 1, 1),
        history_note="Post-1992 krona float. The pegged period is a different regime and is excluded.",
        tags=("g10", "scandi"),
    ),
)


# ---------------------------------------------------------------------------
# Sovereign rates -- 12 futures.
#
# point_value figures are the standard contract multipliers. They MUST be
# confirmed against the terminal (DES / CT) before any live sizing -- see
# `unverified_for_live_sizing()`.
# ---------------------------------------------------------------------------

_RATES: tuple[SecurityMasterEntry, ...] = (
    SecurityMasterEntry(
        canonical_id="TU",
        asset_class="rates",
        description="US 2-year Treasury note future",
        currency="USD",
        bloomberg_candidates=("TU1 Comdty", "TU1 Index"),
        free_proxy="DGS2",
        free_proxy_source="fred",
        free_proxy_note="Yield series, not a contract. Duration proxy only -- never labelled tradable.",
        point_value=2000.0,
        roll_rule="n_days_before_expiry:5",
        tick_size=0.0078125,
        history_start=date(1990, 6, 1),
        history_note="CBOT 2y note future listed 1990.",
        tags=("sovereign", "us"),
    ),
    SecurityMasterEntry(
        canonical_id="FV",
        asset_class="rates",
        description="US 5-year Treasury note future",
        currency="USD",
        bloomberg_candidates=("FV1 Comdty", "FV1 Index"),
        free_proxy="DGS5",
        free_proxy_source="fred",
        free_proxy_note="Yield series, not a contract. Duration proxy only.",
        point_value=1000.0,
        roll_rule="n_days_before_expiry:5",
        tick_size=0.0078125,
        history_start=date(1988, 5, 1),
        history_note="CBOT 5y note future listed 1988.",
        tags=("sovereign", "us"),
    ),
    SecurityMasterEntry(
        canonical_id="TY",
        asset_class="rates",
        description="US 10-year Treasury note future",
        currency="USD",
        bloomberg_candidates=("TY1 Comdty", "TY1 Index"),
        free_proxy="DGS10",
        free_proxy_source="fred",
        free_proxy_note="Yield series, not a contract. Duration proxy only.",
        point_value=1000.0,
        roll_rule="n_days_before_expiry:5",
        tick_size=0.015625,
        history_start=date(1990, 1, 1),
        history_note="Listed 1982; 1990 start aligns the global rates panel.",
        tags=("sovereign", "us", "benchmark"),
    ),
    SecurityMasterEntry(
        canonical_id="US",
        asset_class="rates",
        description="US long bond future",
        currency="USD",
        bloomberg_candidates=("US1 Comdty", "US1 Index"),
        free_proxy="DGS30",
        free_proxy_source="fred",
        free_proxy_note="Yield series, not a contract. Duration proxy only.",
        point_value=1000.0,
        roll_rule="n_days_before_expiry:5",
        tick_size=0.03125,
        history_start=date(1990, 1, 1),
        history_note=(
            "Listed 1977. Note the 2000-2005 30y issuance suspension distorts the deliverable "
            "basket over that window."
        ),
        tags=("sovereign", "us"),
    ),
    SecurityMasterEntry(
        canonical_id="DU",
        asset_class="rates",
        description="Euro-Schatz (German 2y) future",
        currency="EUR",
        bloomberg_candidates=("DU1 Comdty", "DU1 Index"),
        free_proxy=None,
        free_proxy_source="none",
        free_proxy_note="No wired free source for German yields; ECB/Bundesbank feed is not ingested.",
        point_value=1000.0,
        roll_rule="n_days_before_expiry:5",
        tick_size=0.005,
        history_start=date(1999, 1, 4),
        history_note="EUR-denominated from euro launch; pre-1999 DEM contracts are a different instrument.",
        tags=("sovereign", "europe"),
    ),
    SecurityMasterEntry(
        canonical_id="OE",
        asset_class="rates",
        description="Euro-Bobl (German 5y) future",
        currency="EUR",
        bloomberg_candidates=("OE1 Comdty", "OE1 Index"),
        free_proxy=None,
        free_proxy_source="none",
        free_proxy_note="No wired free source for German yields.",
        point_value=1000.0,
        roll_rule="n_days_before_expiry:5",
        tick_size=0.01,
        history_start=date(1999, 1, 4),
        history_note="EUR-denominated from euro launch.",
        tags=("sovereign", "europe"),
    ),
    SecurityMasterEntry(
        canonical_id="RX",
        asset_class="rates",
        description="Euro-Bund (German 10y) future",
        currency="EUR",
        bloomberg_candidates=("RX1 Comdty", "RX1 Index"),
        free_proxy=None,
        free_proxy_source="none",
        free_proxy_note="No wired free source for German yields.",
        point_value=1000.0,
        roll_rule="n_days_before_expiry:5",
        tick_size=0.01,
        history_start=date(1999, 1, 4),
        history_note="EUR-denominated from euro launch. The European rates benchmark.",
        tags=("sovereign", "europe", "benchmark"),
    ),
    SecurityMasterEntry(
        canonical_id="UB",
        asset_class="rates",
        description="Euro-Buxl (German 30y) future",
        currency="EUR",
        bloomberg_candidates=("UB1 Comdty", "UB1 Index"),
        free_proxy=None,
        free_proxy_source="none",
        free_proxy_note="No wired free source for German yields.",
        point_value=1000.0,
        roll_rule="n_days_before_expiry:5",
        tick_size=0.02,
        history_start=date(2005, 9, 1),
        history_note="Buxl listed 2005. Shortest rates history in the panel -- weights W8 conclusions.",
        tags=("sovereign", "europe"),
    ),
    SecurityMasterEntry(
        canonical_id="G",
        asset_class="rates",
        description="Long Gilt future",
        currency="GBP",
        bloomberg_candidates=("G 1 Comdty", "G1 Comdty"),
        free_proxy=None,
        free_proxy_source="none",
        free_proxy_note="No wired free source for gilt yields.",
        point_value=1000.0,
        roll_rule="n_days_before_expiry:5",
        tick_size=0.01,
        history_start=date(1990, 1, 1),
        history_note=(
            "Contains the Sep-Oct 2022 LDI gilt crisis, the most violent sovereign move in the "
            "panel. Retained deliberately (G11)."
        ),
        tags=("sovereign", "uk"),
    ),
    SecurityMasterEntry(
        canonical_id="JB",
        asset_class="rates",
        description="Japanese Government Bond 10y future",
        currency="JPY",
        bloomberg_candidates=("JB1 Comdty", "JB1 Index"),
        free_proxy=None,
        free_proxy_source="none",
        free_proxy_note="No wired free source for JGB yields.",
        point_value=1_000_000.0,
        roll_rule="n_days_before_expiry:5",
        tick_size=0.01,
        history_start=date(1990, 1, 1),
        history_note=(
            "Yield-curve-control era (2016-2024) makes JGB vol structurally non-stationary. "
            "Trend/carry signals here must be interpreted with that in mind."
        ),
        tags=("sovereign", "japan"),
    ),
    SecurityMasterEntry(
        canonical_id="IK",
        asset_class="rates",
        description="Italian BTP 10y future",
        currency="EUR",
        bloomberg_candidates=("IK1 Comdty", "IK1 Index"),
        free_proxy=None,
        free_proxy_source="none",
        free_proxy_note="No wired free source for BTP yields.",
        point_value=1000.0,
        roll_rule="n_days_before_expiry:5",
        tick_size=0.01,
        history_start=date(2009, 9, 1),
        history_note="BTP future listed 2009. Carries the 2011-12 euro sovereign crisis -- a key spread regime.",
        tags=("sovereign", "europe", "periphery"),
    ),
    SecurityMasterEntry(
        canonical_id="OAT",
        asset_class="rates",
        description="French OAT 10y future",
        currency="EUR",
        bloomberg_candidates=("OAT1 Comdty", "OAT1 Index"),
        free_proxy=None,
        free_proxy_source="none",
        free_proxy_note="No wired free source for OAT yields.",
        point_value=1000.0,
        roll_rule="n_days_before_expiry:5",
        tick_size=0.01,
        history_start=date(2012, 4, 1),
        history_note="OAT future listed 2012. Shortest sovereign history alongside UB.",
        tags=("sovereign", "europe"),
    ),
)


# ---------------------------------------------------------------------------
# Credit -- 4 indices.
#
# HIGHEST entitlement risk in the registry. Tickers are unverified candidates;
# the W1 discovery report (docs/global-desk/01 §6) confirms or replaces them and
# decides whether W4 ships real credit or proxy-only.
# ---------------------------------------------------------------------------

_CREDIT: tuple[SecurityMasterEntry, ...] = (
    SecurityMasterEntry(
        canonical_id="CDX_IG",
        asset_class="credit",
        description="Markit CDX North America Investment Grade",
        currency="USD",
        bloomberg_candidates=("IBOXUMAE Index", "CDX IG CDSI GEN 5Y Corp"),
        bloomberg_verified=False,
        free_proxy="LQD",
        free_proxy_source="yfinance",
        free_proxy_note=(
            "IG corporate bond ETF. Carries duration as well as spread, so it is NOT a clean "
            "credit proxy -- duration must be hedged or the exposure labelled mixed."
        ),
        history_start=date(2004, 1, 1),
        history_note="CDX IG series began 2003-04. No credit-index history before then, at any price.",
        tags=("credit", "us", "entitlement_risk"),
    ),
    SecurityMasterEntry(
        canonical_id="CDX_HY",
        asset_class="credit",
        description="Markit CDX North America High Yield",
        currency="USD",
        bloomberg_candidates=("IBOXHYSE Index", "CDX HY CDSI GEN 5Y Corp"),
        bloomberg_verified=False,
        free_proxy="HYG",
        free_proxy_source="yfinance",
        free_proxy_note="HY corporate ETF. Mixed duration/spread exposure; see CDX_IG note.",
        history_start=date(2004, 1, 1),
        history_note="CDX HY series began 2003-04.",
        tags=("credit", "us", "entitlement_risk"),
    ),
    SecurityMasterEntry(
        canonical_id="ITRAXX_MAIN",
        asset_class="credit",
        description="Markit iTraxx Europe Main",
        currency="EUR",
        bloomberg_candidates=("ITRXEBE Index", "ITRAXX EUROPE CDSI GEN 5Y Corp"),
        bloomberg_verified=False,
        free_proxy="IEAC.L",
        free_proxy_source="yfinance",
        free_proxy_note="EUR IG corporate ETF; mixed duration/spread exposure. Ticker suffix may vary by listing.",
        history_start=date(2004, 6, 1),
        history_note="iTraxx Europe began 2004.",
        tags=("credit", "europe", "entitlement_risk"),
    ),
    SecurityMasterEntry(
        canonical_id="ITRAXX_XOVER",
        asset_class="credit",
        description="Markit iTraxx Europe Crossover",
        currency="EUR",
        bloomberg_candidates=("ITRXEXE Index", "ITRAXX XOVER CDSI GEN 5Y Corp"),
        bloomberg_verified=False,
        free_proxy="IHYG.L",
        free_proxy_source="yfinance",
        free_proxy_note="EUR HY corporate ETF; mixed duration/spread exposure.",
        history_start=date(2004, 6, 1),
        history_note="iTraxx Crossover began 2004.",
        tags=("credit", "europe", "entitlement_risk"),
    ),
)


# ---------------------------------------------------------------------------
# Commodities -- 14 futures.
#
# Bloomberg gives genuine per-contract chains, which is what turns the engine's
# existing roll accounting from illustrative into real (program decision G7).
# The `=F` free proxies are back-adjusted continuous series: display aids, never
# tradable P&L (cross-asset invariant §6.1).
# ---------------------------------------------------------------------------

_CONTINUOUS_PROXY_NOTE = (
    "Back-adjusted continuous front-month series. A display aid, NOT tradable P&L -- "
    "any run built on it carries a warning and is labelled non-tradable."
)

_COMMODITIES: tuple[SecurityMasterEntry, ...] = (
    SecurityMasterEntry(
        canonical_id="CL",
        asset_class="commodity",
        description="WTI crude oil",
        currency="USD",
        bloomberg_candidates=("CL1 Comdty",),
        free_proxy="CL=F",
        free_proxy_source="yfinance",
        free_proxy_note=_CONTINUOUS_PROXY_NOTE,
        point_value=1000.0,
        roll_rule="first_notice",
        tick_size=0.01,
        history_start=date(1990, 1, 1),
        history_note=(
            "Includes 2020-04-20, when the May contract settled at -$37.63. Negative prices break "
            "log-return and percentage-carry code -- the engine must handle this, not filter it."
        ),
        tags=("energy",),
    ),
    SecurityMasterEntry(
        canonical_id="CO",
        asset_class="commodity",
        description="Brent crude oil",
        currency="USD",
        bloomberg_candidates=("CO1 Comdty",),
        free_proxy="BZ=F",
        free_proxy_source="yfinance",
        free_proxy_note=_CONTINUOUS_PROXY_NOTE,
        point_value=1000.0,
        roll_rule="n_days_before_expiry:5",
        tick_size=0.01,
        history_start=date(1990, 1, 1),
        history_note="ICE Brent. Cash-settled, so it did not go negative in 2020 as WTI did.",
        tags=("energy",),
    ),
    SecurityMasterEntry(
        canonical_id="NG",
        asset_class="commodity",
        description="Henry Hub natural gas",
        currency="USD",
        bloomberg_candidates=("NG1 Comdty",),
        free_proxy="NG=F",
        free_proxy_source="yfinance",
        free_proxy_note=_CONTINUOUS_PROXY_NOTE,
        point_value=10000.0,
        roll_rule="first_notice",
        tick_size=0.001,
        history_start=date(1993, 1, 1),
        history_note="Strong seasonality and the highest vol in the panel. Vol targeting is essential here.",
        tags=("energy",),
    ),
    SecurityMasterEntry(
        canonical_id="HO",
        asset_class="commodity",
        description="NY Harbor ULSD (heating oil)",
        currency="USD",
        bloomberg_candidates=("HO1 Comdty",),
        free_proxy="HO=F",
        free_proxy_source="yfinance",
        free_proxy_note=_CONTINUOUS_PROXY_NOTE,
        point_value=42000.0,
        roll_rule="first_notice",
        tick_size=0.0001,
        history_start=date(1990, 1, 1),
        history_note="Specification changed from heating oil to ULSD in 2013; treat as a continuity break.",
        tags=("energy",),
    ),
    SecurityMasterEntry(
        canonical_id="XB",
        asset_class="commodity",
        description="RBOB gasoline",
        currency="USD",
        bloomberg_candidates=("XB1 Comdty",),
        free_proxy="RB=F",
        free_proxy_source="yfinance",
        free_proxy_note=_CONTINUOUS_PROXY_NOTE,
        point_value=42000.0,
        roll_rule="first_notice",
        tick_size=0.0001,
        history_start=date(2006, 1, 1),
        history_note="RBOB replaced the unleaded (HU) contract in 2006. Do not splice the two.",
        tags=("energy",),
    ),
    SecurityMasterEntry(
        canonical_id="GC",
        asset_class="commodity",
        description="COMEX gold",
        currency="USD",
        bloomberg_candidates=("GC1 Comdty",),
        free_proxy="GC=F",
        free_proxy_source="yfinance",
        free_proxy_note=_CONTINUOUS_PROXY_NOTE,
        point_value=100.0,
        roll_rule="first_notice",
        tick_size=0.1,
        history_start=date(1990, 1, 1),
        history_note="Deep history available; 1990 start aligns the panel.",
        tags=("metal", "precious"),
    ),
    SecurityMasterEntry(
        canonical_id="SI",
        asset_class="commodity",
        description="COMEX silver",
        currency="USD",
        bloomberg_candidates=("SI1 Comdty",),
        free_proxy="SI=F",
        free_proxy_source="yfinance",
        free_proxy_note=_CONTINUOUS_PROXY_NOTE,
        point_value=5000.0,
        roll_rule="first_notice",
        tick_size=0.005,
        history_start=date(1990, 1, 1),
        history_note="Prone to squeezes (2011, 2021). Fat tails are a feature of the series, not errors.",
        tags=("metal", "precious"),
    ),
    SecurityMasterEntry(
        canonical_id="HG",
        asset_class="commodity",
        description="COMEX copper",
        currency="USD",
        bloomberg_candidates=("HG1 Comdty",),
        free_proxy="HG=F",
        free_proxy_source="yfinance",
        free_proxy_note=_CONTINUOUS_PROXY_NOTE,
        point_value=25000.0,
        roll_rule="first_notice",
        tick_size=0.0005,
        history_start=date(1990, 1, 1),
        history_note="Quoted USD/lb. Note LME copper is the deeper venue; COMEX is chosen for data consistency.",
        tags=("metal", "base"),
    ),
    SecurityMasterEntry(
        canonical_id="PL",
        asset_class="commodity",
        description="NYMEX platinum",
        currency="USD",
        bloomberg_candidates=("PL1 Comdty",),
        free_proxy="PL=F",
        free_proxy_source="yfinance",
        free_proxy_note=_CONTINUOUS_PROXY_NOTE,
        point_value=50.0,
        roll_rule="first_notice",
        tick_size=0.1,
        history_start=date(1990, 1, 1),
        history_note="Thinnest metal in the panel. Capacity analysis (invariant 9) matters most here.",
        tags=("metal", "precious"),
    ),
    SecurityMasterEntry(
        canonical_id="C",
        asset_class="commodity",
        description="CBOT corn",
        currency="USD",
        bloomberg_candidates=("C 1 Comdty", "C1 Comdty"),
        free_proxy="ZC=F",
        free_proxy_source="yfinance",
        free_proxy_note=_CONTINUOUS_PROXY_NOTE,
        point_value=50.0,
        roll_rule="first_notice",
        tick_size=0.25,
        history_start=date(2000, 1, 1),
        history_note=(
            "Quoted in cents/bushel: point_value 50 is USD per cent on 5,000 bu. Pre-2000 ag "
            "liquidity is materially thinner (G11)."
        ),
        tags=("ag", "grain"),
    ),
    SecurityMasterEntry(
        canonical_id="S",
        asset_class="commodity",
        description="CBOT soybeans",
        currency="USD",
        bloomberg_candidates=("S 1 Comdty", "S1 Comdty"),
        free_proxy="ZS=F",
        free_proxy_source="yfinance",
        free_proxy_note=_CONTINUOUS_PROXY_NOTE,
        point_value=50.0,
        roll_rule="first_notice",
        tick_size=0.25,
        history_start=date(2000, 1, 1),
        history_note="Cents/bushel, 5,000 bu. Pre-2000 liquidity materially thinner.",
        tags=("ag", "grain"),
    ),
    SecurityMasterEntry(
        canonical_id="W",
        asset_class="commodity",
        description="CBOT wheat",
        currency="USD",
        bloomberg_candidates=("W 1 Comdty", "W1 Comdty"),
        free_proxy="ZW=F",
        free_proxy_source="yfinance",
        free_proxy_note=_CONTINUOUS_PROXY_NOTE,
        point_value=50.0,
        roll_rule="first_notice",
        tick_size=0.25,
        history_start=date(2000, 1, 1),
        history_note="Cents/bushel, 5,000 bu. Contains the 2022 Ukraine invasion spike and limit moves.",
        tags=("ag", "grain"),
    ),
    SecurityMasterEntry(
        canonical_id="SB",
        asset_class="commodity",
        description="ICE sugar no. 11",
        currency="USD",
        bloomberg_candidates=("SB1 Comdty",),
        free_proxy="SB=F",
        free_proxy_source="yfinance",
        free_proxy_note=_CONTINUOUS_PROXY_NOTE,
        point_value=1120.0,
        roll_rule="first_notice",
        tick_size=0.01,
        history_start=date(2000, 1, 1),
        history_note="Cents/lb on 112,000 lb: point_value 1120 is USD per cent.",
        tags=("ag", "soft"),
    ),
    SecurityMasterEntry(
        canonical_id="KC",
        asset_class="commodity",
        description="ICE coffee C",
        currency="USD",
        bloomberg_candidates=("KC1 Comdty",),
        free_proxy="KC=F",
        free_proxy_source="yfinance",
        free_proxy_note=_CONTINUOUS_PROXY_NOTE,
        point_value=375.0,
        roll_rule="first_notice",
        tick_size=0.05,
        history_start=date(2000, 1, 1),
        history_note="Cents/lb on 37,500 lb: point_value 375 is USD per cent. Weather-driven fat tails.",
        tags=("ag", "soft"),
    ),
)


# ---------------------------------------------------------------------------
# Equity index -- 8 futures.
# ---------------------------------------------------------------------------

_EQUITY_INDEX: tuple[SecurityMasterEntry, ...] = (
    SecurityMasterEntry(
        canonical_id="ES",
        asset_class="equity_index",
        description="E-mini S&P 500 future",
        currency="USD",
        bloomberg_candidates=("ES1 Index", "ES1 Comdty"),
        free_proxy="ES=F",
        free_proxy_source="yfinance",
        free_proxy_note="Continuous front-month proxy; display aid, not tradable P&L.",
        point_value=50.0,
        roll_rule="n_days_before_expiry:5",
        tick_size=0.25,
        history_start=date(1997, 9, 1),
        history_note="E-mini listed Sep 1997. The deepest equity future in the world.",
        tags=("equity_index", "us", "benchmark"),
    ),
    SecurityMasterEntry(
        canonical_id="NQ",
        asset_class="equity_index",
        description="E-mini Nasdaq 100 future",
        currency="USD",
        bloomberg_candidates=("NQ1 Index", "NQ1 Comdty"),
        free_proxy="NQ=F",
        free_proxy_source="yfinance",
        free_proxy_note="Continuous front-month proxy; display aid, not tradable P&L.",
        point_value=20.0,
        roll_rule="n_days_before_expiry:5",
        tick_size=0.25,
        history_start=date(1999, 6, 1),
        history_note="E-mini Nasdaq listed 1999; carries the full dot-com unwind.",
        tags=("equity_index", "us"),
    ),
    SecurityMasterEntry(
        canonical_id="VG",
        asset_class="equity_index",
        description="Euro Stoxx 50 future",
        currency="EUR",
        bloomberg_candidates=("VG1 Index", "VG1 Comdty"),
        free_proxy="^STOXX50E",
        free_proxy_source="yfinance",
        free_proxy_note="Index level, not the future. No roll or financing embedded.",
        point_value=10.0,
        roll_rule="n_days_before_expiry:5",
        tick_size=1.0,
        history_start=date(1999, 1, 4),
        history_note="EUR-denominated from euro launch.",
        tags=("equity_index", "europe", "benchmark"),
    ),
    SecurityMasterEntry(
        canonical_id="GX",
        asset_class="equity_index",
        description="DAX future",
        currency="EUR",
        bloomberg_candidates=("GX1 Index", "GX1 Comdty"),
        free_proxy="^GDAXI",
        free_proxy_source="yfinance",
        free_proxy_note="Index level, not the future.",
        point_value=25.0,
        roll_rule="n_days_before_expiry:5",
        tick_size=0.5,
        history_start=date(1999, 1, 4),
        history_note=(
            "DAX is a total-return index, unlike most peers -- its level embeds dividends. "
            "Cross-index comparisons must account for that."
        ),
        tags=("equity_index", "europe"),
    ),
    SecurityMasterEntry(
        canonical_id="CF",
        asset_class="equity_index",
        description="CAC 40 future",
        currency="EUR",
        bloomberg_candidates=("CF1 Index", "CF1 Comdty"),
        free_proxy="^FCHI",
        free_proxy_source="yfinance",
        free_proxy_note="Index level, not the future.",
        point_value=10.0,
        roll_rule="n_days_before_expiry:5",
        tick_size=0.5,
        history_start=date(1999, 1, 4),
        history_note="EUR-denominated from euro launch.",
        tags=("equity_index", "europe"),
    ),
    SecurityMasterEntry(
        canonical_id="Z",
        asset_class="equity_index",
        description="FTSE 100 future",
        currency="GBP",
        bloomberg_candidates=("Z 1 Index", "Z1 Index"),
        free_proxy="^FTSE",
        free_proxy_source="yfinance",
        free_proxy_note="Index level, not the future.",
        point_value=10.0,
        roll_rule="n_days_before_expiry:5",
        tick_size=0.5,
        history_start=date(1990, 1, 1),
        history_note="Long history; heavy commodity/financial sector weighting versus peers.",
        tags=("equity_index", "uk"),
    ),
    SecurityMasterEntry(
        canonical_id="NK",
        asset_class="equity_index",
        description="Nikkei 225 future",
        currency="JPY",
        bloomberg_candidates=("NK1 Index", "NK1 Comdty"),
        free_proxy="^N225",
        free_proxy_source="yfinance",
        free_proxy_note="Index level, not the future.",
        point_value=1000.0,
        roll_rule="n_days_before_expiry:5",
        tick_size=5.0,
        history_start=date(1990, 1, 1),
        history_note=(
            "Starts at the post-bubble peak; the 1990s are a multi-year bear regime that "
            "usefully stresses any long-biased signal."
        ),
        tags=("equity_index", "japan"),
    ),
    SecurityMasterEntry(
        canonical_id="HI",
        asset_class="equity_index",
        description="Hang Seng future",
        currency="HKD",
        bloomberg_candidates=("HI1 Index", "HI1 Comdty"),
        free_proxy="^HSI",
        free_proxy_source="yfinance",
        free_proxy_note="Index level, not the future.",
        point_value=50.0,
        roll_rule="n_days_before_expiry:5",
        tick_size=1.0,
        history_start=date(1990, 1, 1),
        history_note="HKD is USD-pegged, so FX translation risk is small but the peg is a policy assumption.",
        tags=("equity_index", "asia"),
    ),
)


REGISTRY: tuple[SecurityMasterEntry, ...] = _FX + _RATES + _CREDIT + _COMMODITIES + _EQUITY_INDEX

_BY_ID: dict[str, SecurityMasterEntry] = {entry.canonical_id: entry for entry in REGISTRY}

if len(_BY_ID) != len(REGISTRY):  # pragma: no cover - guarded by test_security_master
    raise RuntimeError("duplicate canonical_id in security master registry")


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------


def get(canonical_id: str) -> SecurityMasterEntry:
    """Look up one entry. Raises KeyError with the available ids on a miss."""
    key = str(canonical_id or "").strip().upper()
    try:
        return _BY_ID[key]
    except KeyError:
        raise KeyError(f"unknown canonical_id {canonical_id!r}; known ids: {sorted(_BY_ID)}") from None


def find(canonical_id: str) -> SecurityMasterEntry | None:
    """Look up one entry, or ``None``."""
    return _BY_ID.get(str(canonical_id or "").strip().upper())


def all_entries() -> tuple[SecurityMasterEntry, ...]:
    return REGISTRY


def by_asset_class(asset_class: AssetClass) -> tuple[SecurityMasterEntry, ...]:
    return tuple(entry for entry in REGISTRY if entry.asset_class == asset_class)


def by_tag(tag: str) -> tuple[SecurityMasterEntry, ...]:
    token = str(tag or "").strip().lower()
    return tuple(entry for entry in REGISTRY if token in entry.tags)


def bloomberg_candidates(canonical_id: str) -> list[str]:
    """Ordered Bloomberg tickers to probe. Empty list for an unknown id."""
    entry = find(canonical_id)
    return list(entry.bloomberg_candidates) if entry else []


def free_proxy_map(canonical_ids: list[str] | None = None) -> dict[str, str]:
    """Canonical id -> free ticker, skipping instruments with no free path."""
    ids = canonical_ids if canonical_ids is not None else [e.canonical_id for e in REGISTRY]
    out: dict[str, str] = {}
    for cid in ids:
        entry = find(cid)
        if entry is not None and entry.free_proxy is not None:
            out[entry.canonical_id] = entry.free_proxy
    return out


def instruments_without_free_path() -> tuple[SecurityMasterEntry, ...]:
    """Instruments that go dark without Bloomberg. G9 requires these be known."""
    return tuple(entry for entry in REGISTRY if not entry.has_free_path)


def unverified_for_live_sizing() -> tuple[SecurityMasterEntry, ...]:
    """Entries whose Bloomberg mapping is an unconfirmed candidate.

    Contract multipliers and tickers here are taken from public specifications
    and MUST be confirmed against the terminal before they size a real trade.
    """
    return tuple(entry for entry in REGISTRY if not entry.bloomberg_verified)
