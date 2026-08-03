from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import os
from typing import Callable

import pandas as pd


FX_PAIRS: dict[str, tuple[str, str, str]] = {
    "EURUSD": ("EURUSD=X", "EUR", "USD"),
    "USDJPY": ("JPY=X", "USD", "JPY"),
    "GBPUSD": ("GBPUSD=X", "GBP", "USD"),
    "USDCHF": ("CHF=X", "USD", "CHF"),
    "AUDUSD": ("AUDUSD=X", "AUD", "USD"),
    "USDCAD": ("CAD=X", "USD", "CAD"),
    "NZDUSD": ("NZDUSD=X", "NZD", "USD"),
    "USDNOK": ("NOK=X", "USD", "NOK"),
    "USDSEK": ("SEK=X", "USD", "SEK"),
}

FRED_RATE_SERIES = {
    "USD": "DFF",
    "EUR": "ECBDFR",
    "JPY": "IRSTCI01JPM156N",
    "GBP": "IUDERB6",
    "CHF": "IRSTCI01CHM156N",
    "AUD": "IRSTCI01AUM156N",
    "CAD": "IRSTCI01CAM156N",
    "NZD": "IRSTCI01NZM156N",
    "NOK": "IRSTCI01NOM156N",
    "SEK": "IRSTCI01SEM156N",
}

FRED_TREASURY_SERIES = {2: "DGS2", 5: "DGS5", 10: "DGS10", 30: "DGS30"}


@dataclass(frozen=True)
class FxPanelResult:
    panel: pd.DataFrame
    warnings: tuple[str, ...]
    staleness_days: dict[str, int | None]
    source: str = "yfinance+fred"


def _download_spot(tickers: list[str], start: date, end: date) -> dict[str, pd.Series]:
    import yfinance as yf

    frame = yf.download(tickers, start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(), auto_adjust=False, progress=False, group_by="column")
    if frame.empty:
        raise RuntimeError("yfinance returned no FX spot observations")
    close = frame["Close"] if isinstance(frame.columns, pd.MultiIndex) else frame[["Close"]].rename(columns={"Close": tickers[0]})
    return {ticker: close[ticker].dropna().astype(float).rename(ticker) for ticker in tickers if ticker in close}


def _download_fred(series_id: str, api_key: str, start: date, end: date) -> pd.Series:
    import requests

    response = requests.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={"series_id": series_id, "api_key": api_key, "file_type": "json", "observation_start": start.isoformat(), "observation_end": end.isoformat()},
        timeout=30,
    )
    response.raise_for_status()
    observations = response.json().get("observations", [])
    values = {pd.Timestamp(item["date"]): float(item["value"]) / 100.0 for item in observations if item.get("value") not in {None, "."}}
    if not values:
        raise RuntimeError(f"FRED returned no observations for {series_id}")
    return pd.Series(values, name=series_id, dtype=float).sort_index()


def assemble_fx_panel(
    *,
    start: date | None = None,
    end: date | None = None,
    fred_api_key: str | None = None,
    spot_loader: Callable[[list[str], date, date], dict[str, pd.Series]] | None = None,
    rate_loader: Callable[[str, str, date, date], pd.Series] | None = None,
) -> FxPanelResult:
    key = fred_api_key or os.getenv("FRED_API_KEY")
    if not key:
        raise RuntimeError("FRED_API_KEY is required for cross-asset FX rate legs; no zero or stale fallback is permitted")
    end_date = end or date.today()
    start_date = start or (end_date - timedelta(days=365 * 15))
    load_spot = spot_loader or _download_spot
    load_rate = rate_loader or _download_fred
    tickers = [item[0] for item in FX_PAIRS.values()]
    spots = load_spot(tickers, start_date, end_date)
    missing_tickers = sorted(set(tickers) - set(spots))
    if missing_tickers:
        raise RuntimeError(f"yfinance omitted FX tickers: {', '.join(missing_tickers)}")
    rates = {ccy: load_rate(series_id, key, start_date, end_date) for ccy, series_id in FRED_RATE_SERIES.items()}
    columns: dict[tuple[str, str], pd.Series] = {}
    warnings: list[str] = [
        "Adapted replication: policy-rate proxies are not tradable forwards.",
        "Adapted replication: monthly rebalance styling differs from source publications.",
    ]
    staleness: dict[str, int | None] = {}
    for symbol, (ticker, base, quote) in FX_PAIRS.items():
        columns[(symbol, "spot")] = spots[ticker]
        columns[(symbol, "r_base")] = rates[base]
        columns[(symbol, "r_quote")] = rates[quote]
    panel = pd.concat(columns, axis=1).sort_index()
    # Carry is explicitly cross-sectional: centered ranks, with missing legs left missing.
    differentials = pd.DataFrame(
        {symbol: panel[(symbol, "r_base")] - panel[(symbol, "r_quote")] for symbol in FX_PAIRS},
        index=panel.index,
    )
    centered_ranks = differentials.rank(axis=1, pct=True, na_option="keep") - 0.5
    for symbol in FX_PAIRS:
        panel[(symbol, "carry")] = centered_ranks[symbol]
    panel = panel.sort_index(axis=1)
    as_of = pd.Timestamp(end_date)
    for label, series in {**{f"spot:{key}": value for key, value in spots.items()}, **{f"rate:{key}": value for key, value in rates.items()}}.items():
        clean = series.dropna()
        age = None if clean.empty else max(0, int((as_of.normalize() - pd.Timestamp(clean.index.max()).normalize()).days))
        staleness[label] = age
        if age is None:
            warnings.append(f"{label}: unavailable; no value was invented")
        elif age > 5:
            warnings.append(f"{label}: stale by {age} calendar days")
    missing = panel.isna().sum()
    for (symbol, field), count in missing[missing > 0].items():
        warnings.append(f"{symbol}.{field}: {int(count)} missing observations; no forward-fill applied")
    return FxPanelResult(panel=panel, warnings=tuple(dict.fromkeys(warnings)), staleness_days=staleness)


def assemble_rates_panel(
    *,
    start: date | None = None,
    end: date | None = None,
    fred_api_key: str | None = None,
    rate_loader: Callable[[str, str, date, date], pd.Series] | None = None,
) -> FxPanelResult:
    key = fred_api_key or os.getenv("FRED_API_KEY")
    if not key:
        raise RuntimeError("FRED_API_KEY is required for DGS rates; no zero or stale fallback is permitted")
    end_date = end or date.today()
    start_date = start or (end_date - timedelta(days=365 * 15))
    loader = rate_loader or _download_fred
    cash = loader(FRED_RATE_SERIES["USD"], key, start_date, end_date)
    columns: dict[tuple[str, str], pd.Series] = {}
    warnings = ["Duration-approximated from constant-maturity par yields; not reconstructed from traded bonds or futures."]
    staleness: dict[str, int | None] = {}
    for maturity, series_id in FRED_TREASURY_SERIES.items():
        symbol = f"DGS{maturity}"
        par_yield = loader(series_id, key, start_date, end_date)
        columns[(symbol, "par_yield")] = par_yield
        columns[(symbol, "cash_rate")] = cash
        clean = par_yield.dropna()
        age = None if clean.empty else max(0, int((pd.Timestamp(end_date).normalize() - pd.Timestamp(clean.index.max()).normalize()).days))
        staleness[symbol] = age
        if age is None or age > 5:
            warnings.append(f"{symbol}: {'unavailable' if age is None else f'stale by {age} calendar days'}")
    panel = pd.concat(columns, axis=1).sort_index()
    for (symbol, field), count in panel.isna().sum().items():
        if count:
            warnings.append(f"{symbol}.{field}: {int(count)} missing observations; no forward-fill applied")
    return FxPanelResult(panel, tuple(dict.fromkeys(warnings)), staleness, "fred")
