"""
data.py — Research-first data layer with institutional-style separation:

- MarketData: normalized dataset container ("bundle-lite")
- BaseDataSource: stable interface (like QuantStart's DataHandler idea)
- YahooFinanceDataSource: yfinance adapter (testing)
- BMCEDataSource: CSV adapter for BMCE-like format

Canonical output schema per symbol:
Index: pd.DatetimeIndex (tz-aware, sorted, unique)
Columns: Open, High, Low, Close, Adj Close (optional), Volume
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union
import hashlib
import json

import numpy as np
import pandas as pd


CANONICAL_COLS = ["Open", "High", "Low", "Close", "Volume"]


def _infer_epoch_unit(values: pd.Series) -> str:
    numeric = pd.to_numeric(values, errors="coerce")
    numeric = numeric[np.isfinite(numeric.to_numpy(dtype="float64", copy=False))]
    if numeric.empty:
        return "s"
    scale = float(np.nanmedian(np.abs(numeric.to_numpy(dtype="float64"))))
    if scale >= 1e17:
        return "ns"
    if scale >= 1e14:
        return "us"
    if scale >= 1e11:
        return "ms"
    return "s"


def _coerce_datetime_series(values: pd.Series, *, utc: bool = False) -> pd.Series:
    s = values.copy()
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns, UTC]" if utc else "datetime64[ns]")
    numeric = pd.to_numeric(s, errors="coerce")
    mask_numeric = numeric.notna()

    if (~mask_numeric).any():
        out.loc[~mask_numeric] = pd.to_datetime(s.loc[~mask_numeric], utc=utc, errors="coerce")

    if mask_numeric.any():
        num = numeric.loc[mask_numeric]
        abs_num = num.abs()
        mask_ns = abs_num >= 1e17
        mask_us = (abs_num >= 1e14) & (abs_num < 1e17)
        mask_ms = (abs_num >= 1e11) & (abs_num < 1e14)
        mask_s = abs_num < 1e11
        if mask_ns.any():
            out.loc[num.index[mask_ns]] = pd.to_datetime(num.loc[mask_ns], unit="ns", utc=utc, errors="coerce")
        if mask_us.any():
            out.loc[num.index[mask_us]] = pd.to_datetime(num.loc[mask_us], unit="us", utc=utc, errors="coerce")
        if mask_ms.any():
            out.loc[num.index[mask_ms]] = pd.to_datetime(num.loc[mask_ms], unit="ms", utc=utc, errors="coerce")
        if mask_s.any():
            out.loc[num.index[mask_s]] = pd.to_datetime(num.loc[mask_s], unit="s", utc=utc, errors="coerce")

    return out


def _stable_symbol_offset(symbol: str) -> int:
    digest = hashlib.md5(symbol.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


# Module-level cache for business-day date ranges shared across symbols
# (keyed by (start, end, freq, tz)).  Avoids redundant pd.date_range(freq="B")
# calls — which cost ~25 ms each — when multiple symbols share the same window.
_DATE_RANGE_CACHE: Dict[tuple, pd.DatetimeIndex] = {}


def make_synthetic_ohlcv(
    symbol: str,
    start: str | None,
    end: str | None,
    periods: int | None,
    freq: str = "B",
    seed: int = 42,
    start_price: float = 100.0,
    mu: float = 0.0003,
    sigma: float = 0.01,
    vol_min: int = 100_000,
    vol_max: int = 300_000,
) -> pd.DataFrame:
    if start and end:
        _cache_key = (start, end, freq, "UTC")
        idx = _DATE_RANGE_CACHE.get(_cache_key)
        if idx is None:
            idx = pd.date_range(start=start, end=end, freq=freq, tz="UTC")
            _DATE_RANGE_CACHE[_cache_key] = idx
    elif periods is not None:
        idx = pd.date_range("2024-01-01", periods=int(periods), freq=freq, tz="UTC")
    else:
        raise ValueError("Synthetic data requires either (start and end) or periods.")

    idx = idx.sort_values().unique()
    idx = pd.DatetimeIndex(idx, tz="UTC", name="timestamp")

    n = len(idx)
    if n == 0:
        return pd.DataFrame(columns=CANONICAL_COLS, index=idx)

    if vol_min > vol_max:
        raise ValueError(f"vol_min must be <= vol_max. Got vol_min={vol_min}, vol_max={vol_max}")

    local_seed = (int(seed) + _stable_symbol_offset(symbol)) % (2**32 - 1)
    rng = np.random.default_rng(local_seed)

    drift = float(mu) - 0.5 * float(sigma) * float(sigma)
    eps = rng.normal(0.0, 1.0, size=max(n - 1, 0))
    log_rets = drift + float(sigma) * eps
    log_close = np.empty(n, dtype=float)
    log_close[0] = np.log(float(start_price))
    if n > 1:
        log_close[1:] = log_close[0] + np.cumsum(log_rets)
    close = np.exp(log_close)

    open_px = np.empty(n, dtype=float)
    open_px[0] = close[0]
    if n > 1:
        open_px[1:] = close[:-1]

    spread = rng.uniform(0.0, 0.01, size=n)
    base_high = np.maximum(open_px, close)
    base_low = np.minimum(open_px, close)
    high = base_high * (1.0 + spread)
    low = base_low * (1.0 - spread)

    high = np.maximum(high, base_high)
    low = np.minimum(low, base_low)
    volume = rng.integers(int(vol_min), int(vol_max) + 1, size=n, dtype=np.int64)

    df = pd.DataFrame(
        {
            "Open": open_px.astype(float),
            "High": high.astype(float),
            "Low": low.astype(float),
            "Close": close.astype(float),
            "Volume": volume,
        },
        index=idx,
    )
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df.index = pd.DatetimeIndex(df.index, tz="UTC", name="timestamp")
    return df[["Open", "High", "Low", "Close", "Volume"]]


# ----------------------------
# Layer 1: MarketData container
# ----------------------------
@dataclass(frozen=True)
class MarketData:
    """
    Normalized market data for research backtesting.

    bars: dict[symbol -> DataFrame] where each DF:
      - index: tz-aware DatetimeIndex, sorted ascending, unique
      - columns: Open, High, Low, Close, Volume (+ optional Adj Close)
    """
    bars: Dict[str, pd.DataFrame]
    source: str
    timezone: str = "GMT"
    interval: str = "1d"
    meta: Dict[str, object] = field(default_factory=dict)

    def symbols(self) -> List[str]:
        return list(self.bars.keys())

    def get(self, symbol: str) -> pd.DataFrame:
        return self.bars[symbol]


# ----------------------------
# Layer 4: Normalization utils
# ----------------------------
def _ensure_datetime_index(
    df: pd.DataFrame,
    tz: str = "GMT",
) -> pd.DataFrame:
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("DataFrame index must be a DatetimeIndex after parsing.")
    # Sort, drop duplicates
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]

    # Localize/convert timezone
    if df.index.tz is None:
        df.index = df.index.tz_localize(tz)
    else:
        df.index = df.index.tz_convert(tz)

    return df


def _coerce_numeric(df: pd.DataFrame, cols: Sequence[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _standardize_ohlcv(
    df: pd.DataFrame,
    tz: str = "GMT",
    require_ohlc: bool = True,
    fill_adj_close: bool = True,
) -> pd.DataFrame:
    """
    Enforce canonical columns and a clean datetime index.
    """
    df = _ensure_datetime_index(df, tz=tz)

    # Normalize column names (common variants)
    rename_map = {
        "AdjClose": "Adj Close",
        "Adj_Close": "Adj Close",
        "adj_close": "Adj Close",
        "close": "Close",
        "open": "Open",
        "high": "High",
        "low": "Low",
        "volume": "Volume",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    # Basic schema checks
    needed = ["Open", "High", "Low", "Close"] if require_ohlc else ["Close"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}. Found: {list(df.columns)}")

    # Adj Close handling
    if fill_adj_close and "Adj Close" not in df.columns:
        # For many research tasks, using Close is acceptable; keep explicit
        df["Adj Close"] = df["Close"]

    # Coerce numeric
    numeric_cols = [c for c in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if c in df.columns]
    df = _coerce_numeric(df, numeric_cols)

    # Keep only canonical cols that exist (preserve order)
    keep = [c for c in CANONICAL_COLS if c in df.columns]
    df = df[keep]

    # Drop rows where close is missing
    df = df.dropna(subset=["Close"])

    return df


def _validate_ohlcv(df: pd.DataFrame, symbol: str = "") -> pd.DataFrame:
    """
    Check OHLC bar integrity and drop (with a warning) any bars that violate:
      High >= max(Open, Close) >= min(Open, Close) >= Low >= 0

    Returns a cleaned DataFrame. Raises nothing — data quality issues are
    surfaced as warnings so existing pipelines aren't broken.
    """
    import logging
    import warnings

    tag = f"[{symbol}] " if symbol else ""
    bad = pd.Series(False, index=df.index)

    if "High" in df.columns and "Low" in df.columns:
        mask = df["High"] < df["Low"]
        if mask.any():
            warnings.warn(
                f"OHLC integrity {tag}High < Low on {mask.sum()} bar(s); dropping those rows.",
                stacklevel=3,
            )
            bad |= mask

    if "High" in df.columns and "Open" in df.columns:
        mask = df["High"] < df["Open"]
        if mask.any():
            warnings.warn(
                f"OHLC integrity {tag}High < Open on {mask.sum()} bar(s); dropping those rows.",
                stacklevel=3,
            )
            bad |= mask

    if "High" in df.columns and "Close" in df.columns:
        mask = df["High"] < df["Close"]
        if mask.any():
            warnings.warn(
                f"OHLC integrity {tag}High < Close on {mask.sum()} bar(s); dropping those rows.",
                stacklevel=3,
            )
            bad |= mask

    if "Low" in df.columns and "Open" in df.columns:
        mask = df["Low"] > df["Open"]
        if mask.any():
            warnings.warn(
                f"OHLC integrity {tag}Low > Open on {mask.sum()} bar(s); dropping those rows.",
                stacklevel=3,
            )
            bad |= mask

    if "Low" in df.columns and "Close" in df.columns:
        mask = df["Low"] > df["Close"]
        if mask.any():
            warnings.warn(
                f"OHLC integrity {tag}Low > Close on {mask.sum()} bar(s); dropping those rows.",
                stacklevel=3,
            )
            bad |= mask

    if "Low" in df.columns:
        mask = df["Low"] < 0
        if mask.any():
            warnings.warn(
                f"OHLC integrity {tag}negative prices on {mask.sum()} bar(s); dropping those rows.",
                stacklevel=3,
            )
            bad |= mask

    if bad.any():
        df = df[~bad]

    return df


def slice_date_range(df: pd.DataFrame, start: Optional[str], end: Optional[str]) -> pd.DataFrame:
    if start is not None:
        df = df[df.index >= pd.Timestamp(start, tz=df.index.tz)]
    if end is not None:
        df = df[df.index <= pd.Timestamp(end, tz=df.index.tz)]
    return df


def align_symbols(
    bars: Dict[str, pd.DataFrame],
    how: str = "inner",
    fill_method: Optional[str] = None,
) -> Dict[str, pd.DataFrame]:
    """
    Align all symbols to a common index (inner = intersection; outer = union).
    Useful once you do multi-asset comparisons.

    fill_method: None, "ffill", "bfill"
    """
    if not bars:
        return bars

    indexes = [df.index for df in bars.values()]
    common_idx = indexes[0]
    for idx in indexes[1:]:
        common_idx = common_idx.intersection(idx) if how == "inner" else common_idx.union(idx)

    out: Dict[str, pd.DataFrame] = {}
    for sym, df in bars.items():
        tmp = df.reindex(common_idx)
        if fill_method is not None:
            tmp = tmp.fillna(method=fill_method)
        out[sym] = tmp
    return out


# ----------------------------
# Layer 2: BaseDataSource interface
# ----------------------------
class BaseDataSource:
    """
    Stable interface for data acquisition adapters.

    Inspired by the idea of a common DataHandler/Feed interface:
    - QuantStart: ABC interface to ensure compatibility across components :contentReference[oaicite:7]{index=7}
    - Backtrader: multiple data feeds that plug into the engine :contentReference[oaicite:8]{index=8}
    """

    def __init__(
        self,
        timezone: str = "GMT",
        cache_dir: Optional[Union[str, Path]] = None,
        use_cache: bool = True,
    ) -> None:
        self.timezone = timezone
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.use_cache = use_cache

        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def load(
        self,
        symbols: Sequence[str],
        start: Optional[str] = None,
        end: Optional[str] = None,
        interval: str = "1d",
        align: bool = False,
        align_how: str = "inner",
        fill_method: Optional[str] = None,
        **kwargs,
    ) -> MarketData:
        """
        Public API: return MarketData with normalized per-symbol OHLCV.

        align=True is helpful for multi-asset research comparisons.
        """
        symbols = list(symbols)
        cache_key = self._cache_key(symbols, start, end, interval, kwargs)

        if self.use_cache and self.cache_dir:
            cached = self._try_load_cache(cache_key)
            if cached is not None:
                bars = cached
            else:
                bars = self._load_impl(symbols, start, end, interval, **kwargs)
                self._save_cache(cache_key, bars)
        else:
            bars = self._load_impl(symbols, start, end, interval, **kwargs)

        # Normalize, validate OHLC integrity, then slice
        normed: Dict[str, pd.DataFrame] = {}
        for sym, df in bars.items():
            df = _standardize_ohlcv(df, tz=self.timezone)
            df = _validate_ohlcv(df, symbol=sym)
            df = slice_date_range(df, start, end)
            normed[sym] = df

        if align and len(normed) > 1:
            normed = align_symbols(normed, how=align_how, fill_method=fill_method)

        return MarketData(
            bars=normed,
            source=self.__class__.__name__,
            timezone=self.timezone,
            interval=interval,
            meta={
                "start": start,
                "end": end,
                "symbols": symbols,
                "interval": interval,
                **({"adapter_kwargs": kwargs} if kwargs else {}),
            },
        )

    # ---- adapter-specific implementation hook
    def _load_impl(
        self,
        symbols: Sequence[str],
        start: Optional[str],
        end: Optional[str],
        interval: str,
        **kwargs,
    ) -> Dict[str, pd.DataFrame]:
        raise NotImplementedError

    # ---- caching (simple, research-friendly)
    def _cache_key(
        self,
        symbols: Sequence[str],
        start: Optional[str],
        end: Optional[str],
        interval: str,
        kwargs: dict,
    ) -> str:
        payload = {
            "cls": self.__class__.__name__,
            "symbols": list(symbols),
            "start": start,
            "end": end,
            "interval": interval,
            "timezone": self.timezone,
            "kwargs": kwargs,
        }
        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def _try_load_cache(self, key: str) -> Optional[Dict[str, pd.DataFrame]]:
        assert self.cache_dir is not None
        path = self.cache_dir / f"{key}.pkl"
        if not path.exists():
            return None
        return pd.read_pickle(path)

    def _save_cache(self, key: str, bars: Dict[str, pd.DataFrame]) -> None:
        assert self.cache_dir is not None
        path = self.cache_dir / f"{key}.pkl"
        pd.to_pickle(bars, path)


# ----------------------------
# Layer 3a: yfinance adapter (testing)
# ----------------------------
class YahooFinanceDataSource(BaseDataSource):
    """
    Research-friendly Yahoo adapter (yfinance).

    Notes:
    - yfinance often returns MultiIndex columns if multiple tickers are requested.
    - We convert to dict[symbol -> DataFrame] to keep downstream logic explicit.
    """

    def _load_impl(
        self,
        symbols: Sequence[str],
        start: Optional[str],
        end: Optional[str],
        interval: str,
        auto_adjust: bool = False,
        progress: bool = False,
        **kwargs,
    ) -> Dict[str, pd.DataFrame]:
        try:
            import yfinance as yf
        except ImportError as e:
            raise ImportError("yfinance is not installed. `pip install yfinance`") from e

        # yfinance download
        df = yf.download(
            tickers=list(symbols),
            start=start,
            end=end,
            interval=interval,
            auto_adjust=auto_adjust,
            progress=progress,
            group_by="column",
            **kwargs,
        )

        out: Dict[str, pd.DataFrame] = {}

        # Multi-ticker format: columns are MultiIndex: (field, ticker)
        if isinstance(df.columns, pd.MultiIndex):
            # fields: Open/High/Low/Close/Adj Close/Volume
            for sym in symbols:
                sub = df.xs(sym, axis=1, level=1, drop_level=True).copy()
                out[sym] = sub
        else:
            # Single ticker: columns are normal
            sym = symbols[0] if symbols else "UNKNOWN"
            out[sym] = df.copy()

        # Index is usually naive GMT; normalization will localize to self.timezone
        return out


# ----------------------------
# Layer 3b: BMCE-like CSV adapter
# Example CSV:
# Date,"Price","Open","High","Low","Vol.","Change %"
# 01/23/2025,"90.90","89.51","90.90","89.26","355.87K","1.91%"
# ----------------------------
def _parse_human_volume(x: object) -> float:
    """
    Convert strings like '355.87K', '1.2M', '3B' into numeric volume.
    Returns float to preserve fidelity; you can cast to int later if desired.
    """
    if pd.isna(x):
        return float("nan")
    s = str(x).strip().replace(",", "")
    if s == "":
        return float("nan")

    mult = 1.0
    last = s[-1].upper()
    if last in ("K", "M", "B"):
        s_num = s[:-1]
        mult = {"K": 1e3, "M": 1e6, "B": 1e9}[last]
    else:
        s_num = s

    try:
        return float(s_num) * mult
    except ValueError:
        return float("nan")


def _parse_percent(x: object) -> float:
    """'1.91%' -> 0.0191"""
    if pd.isna(x):
        return float("nan")
    s = str(x).strip().replace("%", "")
    if s == "":
        return float("nan")
    try:
        return float(s) / 100.0
    except ValueError:
        return float("nan")


def _normalize_bmce_column_label(value: object) -> str:
    return " ".join(str(value).strip().lower().split())


_BMCE_COLUMN_RENAMES: Dict[str, str] = {
    "date": "Date",
    "séance": "Date",
    "seance": "Date",
    "sã©ance": "Date",
    "open": "Open",
    "ouvt": "Open",
    "ouverture": "Open",
    "'+haut": "High",
    "+haut": "High",
    "+haut du jour": "High",
    "plus haut": "High",
    "'+bas": "Low",
    "+bas": "Low",
    "+bas du jour": "Low",
    "plus bas": "Low",
    "clôture": "Close",
    "cloture": "Close",
    "clã´ture": "Close",
    "close": "Close",
    "dernier cours": "Close",
    "Price": "Close",
    "cours": "Close",
    "volume": "Volume",
    "vol.": "Volume",
    "volue": "Volume",
    "nombre de titres échangés": "Volume",
    "nombre de titres echanges": "Volume",
    "nombre de titres ã©changã©s": "Volume",
}


def _rename_bmce_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    for col in df.columns:
        canonical = _BMCE_COLUMN_RENAMES.get(_normalize_bmce_column_label(col))
        if canonical is not None:
            rename_map[col] = canonical
    return df.rename(columns=rename_map)


class BMCEDataSource(BaseDataSource):
    """
    CSV adapter for the given BMCE-like format.

    Design is intentionally "Generic CSV"-style: map input fields to canonical OHLCV,
    similar in spirit to Backtrader's Generic CSV support. :contentReference[oaicite:9]{index=9}
    """

    def __init__(
        self,
        timezone: str = "GMT",
        cache_dir: Optional[Union[str, Path]] = None,
        use_cache: bool = True,
        dayfirst: bool = False,
        date_format: Optional[str] = None,
    ) -> None:
        super().__init__(timezone=timezone, cache_dir=cache_dir, use_cache=use_cache)
        self.dayfirst = dayfirst
        self.date_format = date_format

    def _load_impl(
        self,
        symbols: Sequence[str],
        start: Optional[str],
        end: Optional[str],
        interval: str,
        paths: Union[str, Path, Dict[str, Union[str, Path]]],
        **kwargs,
    ) -> Dict[str, pd.DataFrame]:
        """
        paths:
        - if single symbol: a single path
        - if multiple symbols: dict {symbol: path}
        """
        if interval != "1d":
            # You can extend later; keep explicit now
            raise ValueError("BMCEDataSource currently supports daily bars only (interval='1d').")

        out: Dict[str, pd.DataFrame] = {}

        if isinstance(paths, (str, Path)):
            p = Path(paths)
            ext = p.suffix.lower()

            # ✅ Special case: ONE workbook contains MANY symbols as sheets
            if ext in [".xlsx", ".xls"] and len(symbols) >= 1:
                # Open once (faster than reopening per symbol)
                xls = pd.ExcelFile(p)
                available_map = {str(name).strip().upper(): str(name) for name in xls.sheet_names}
                available_labels = list(available_map.values())

                for sym in symbols:
                    lookup = str(sym).strip().upper()
                    if lookup not in available_map:
                        raise ValueError(
                            f"Workbook '{p.name}' has no sheet '{sym}'. "
                            f"Available sheets: {available_labels}"
                        )
                    out[str(sym)] = self._read_one_file(p, sheet_name=available_map[lookup])

            else:
                # ✅ Original behavior (single file = single symbol)
                if len(symbols) != 1:
                    raise ValueError(
                        "If `paths` is a single path, `symbols` must have length 1 "
                        "(unless it's an .xlsx workbook with one sheet per symbol)."
                    )
                sym = symbols[0]
                out[sym] = self._read_one_file(p)

        else:
            # dict mapping (already works)
            excel_sheets_by_path: Dict[str, Dict[str, str]] = {}
            for sym in symbols:
                if sym not in paths:
                    raise ValueError(f"Missing path for symbol '{sym}'. Provided keys: {list(paths.keys())}")
                p = Path(paths[sym])
                ext = p.suffix.lower()
                if ext in [".xlsx", ".xls"]:
                    cache_key = str(p.resolve())
                    if cache_key not in excel_sheets_by_path:
                        xls = pd.ExcelFile(p)
                        excel_sheets_by_path[cache_key] = {
                            str(name).strip().upper(): str(name) for name in xls.sheet_names
                        }
                    lookup = str(sym).strip().upper()
                    sheet_map = excel_sheets_by_path[cache_key]
                    if lookup not in sheet_map:
                        raise ValueError(
                            f"Workbook '{p.name}' has no sheet '{sym}'. "
                            f"Available sheets: {list(sheet_map.values())}"
                        )
                    out[sym] = self._read_one_file(p, sheet_name=sheet_map[lookup])
                else:
                    out[sym] = self._read_one_file(p)

        return out


    def _read_one_file(self, path: Path, sheet_name: str | None = None) -> pd.DataFrame:
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        # 1) Read file depending on extension
        ext = path.suffix.lower()
        if ext in [".xlsx", ".xls"]:
            df = pd.read_excel(path, sheet_name=sheet_name, engine="openpyxl")
        elif ext == ".csv":
            df = pd.read_csv(path, encoding="utf-8-sig", sep=None, engine="python")
        else:
            raise ValueError(f"Unsupported file extension: {ext}")

        # 2) Clean column names (BMCE exports often have spaces)
        df.columns = df.columns.astype(str).str.strip()

        # 3) Rename BMCE columns -> canonical raw names
        rename = {
            "Ouvt": "Open",
            "'+Haut": "High",
            "'+Bas": "Low",
            "Clôture": "Close",
            "Volume": "Volume",
        }
        df = _rename_bmce_columns(df)

        # 4) Parse Date and set index
        if "Date" not in df.columns:
            raise ValueError(f"'Date' column not found. Found columns: {list(df.columns)}")

        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")  # add dayfirst=True if needed
        df = df.dropna(subset=["Date"]).set_index("Date")

        # 5) Convert numbers (handle comma decimals if they appear)
        for c in ["Open", "High", "Low", "Close", "Volume"]:
            if c in df.columns and df[c].dtype == "object":
                df[c] = (
                    df[c].astype(str)
                    .str.replace(" ", "", regex=False)
                    .str.replace(",", ".", regex=False)
                )
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce")

        # 6) Keep only OHLCV
        keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
        missing = [c for c in ["Open", "High", "Low", "Close"] if c not in df.columns]
        if missing:
            raise ValueError(f"Missing required OHLC columns after rename: {missing}. Columns: {list(df.columns)}")

        return df[keep]


# ----------------------------
# Moroccan symbol normalization
# ----------------------------
import re as _re

def normalize_symbol(raw: str) -> str:
    """Normalize a raw ticker string to the internal canonical form.

    Rules:
    - Uppercase and strip whitespace
    - Remove exchange suffixes: .CS, .MA, .BVC, :BVC, :MA
    - Remove parenthetical suffixes: "ATW (ATIJARI)" → "ATW"
    """
    s = str(raw or "").strip().upper()
    # Remove parenthetical suffix
    s = _re.sub(r"\s*\(.*\)$", "", s)
    # Remove known exchange suffixes
    s = _re.sub(r"\.(CS|MA|BVC)$", "", s, flags=_re.IGNORECASE)
    s = _re.sub(r":(BVC|MA)$", "", s, flags=_re.IGNORECASE)
    return s.strip()


# ----------------------------
# Layer 3c: Bourse de Casablanca HTTP adapter
# ----------------------------
class BourseDirectAdapter(BaseDataSource):
    """
    Adapter that fetches OHLCV data from the Bourse de Casablanca public
    download endpoint.

    IMPORTANT: The exact URL template must be verified against the live
    Bourse de Casablanca website before use. Set the environment variable
    BOURSE_DIRECT_URL_TEMPLATE to the correct endpoint, e.g.:
      https://www.casablanca-bourse.com/bourseweb/cours-historiques-download?valeur={symbol}&...

    The response is expected to be an Excel file in BMCE column format
    (same column mapping as BMCEDataSource). If the endpoint returns CSV,
    set BOURSE_DIRECT_RESPONSE_FORMAT=csv.

    Per-symbol HTTP errors are caught and returned as empty DataFrames so
    that a bulk refresh can continue with remaining symbols.
    """

    def __init__(
        self,
        timezone: str = "UTC",
        cache_dir: Optional[Union[str, Path]] = None,
        use_cache: bool = False,
        url_template: Optional[str] = None,
        response_format: str = "excel",
        rate_limit_delay_s: float = 0.5,
    ) -> None:
        import os
        super().__init__(timezone=timezone, cache_dir=cache_dir, use_cache=use_cache)
        self.url_template: str = (
            url_template
            or os.environ.get("BOURSE_DIRECT_URL_TEMPLATE", "")
        )
        self.response_format: str = (
            os.environ.get("BOURSE_DIRECT_RESPONSE_FORMAT", response_format)
        )
        self.rate_limit_delay_s = float(rate_limit_delay_s)

    def _load_impl(
        self,
        symbols: Sequence[str],
        start: Optional[str],
        end: Optional[str],
        interval: str,
        **kwargs,
    ) -> Dict[str, pd.DataFrame]:
        import time
        import io

        try:
            import requests as _requests
        except ImportError as e:
            raise ImportError(
                "requests is required for BourseDirectAdapter. `pip install requests`"
            ) from e

        if not self.url_template:
            raise ValueError(
                "BourseDirectAdapter: url_template is not configured. "
                "Set the BOURSE_DIRECT_URL_TEMPLATE environment variable."
            )

        # Reuse the BMCE column rename logic already in BMCEDataSource
        _bmce_rename = {
            "Ouvt": "Open",
            "'+Haut": "High",
            "'+Bas": "Low",
            "Clôture": "Close",
            "Volume": "Volume",
        }

        session = _requests.Session()
        out: Dict[str, pd.DataFrame] = {}

        for i, sym in enumerate(symbols):
            if i > 0:
                time.sleep(self.rate_limit_delay_s)
            try:
                url = self.url_template.format(
                    symbol=sym,
                    start=start or "",
                    end=end or "",
                )
                resp = session.get(url, timeout=30)
                resp.raise_for_status()

                raw = io.BytesIO(resp.content)
                if self.response_format == "excel":
                    df = pd.read_excel(raw, engine="openpyxl")
                else:
                    df = pd.read_csv(raw, encoding="utf-8-sig", sep=None, engine="python")

                df.columns = df.columns.astype(str).str.strip()
                df = _rename_bmce_columns(df)

                # Parse date column
                date_col = next(
                    (c for c in ("Date", "date", "Timestamp", "timestamp") if c in df.columns),
                    None,
                )
                if date_col is None:
                    raise ValueError(f"No date column found for {sym}. Columns: {list(df.columns)}")
                df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
                df = df.dropna(subset=[date_col]).set_index(date_col)

                # Coerce numeric OHLCV
                for c in ["Open", "High", "Low", "Close", "Volume"]:
                    if c in df.columns and df[c].dtype == object:
                        df[c] = (
                            df[c].astype(str)
                            .str.replace(" ", "", regex=False)
                            .str.replace(",", ".", regex=False)
                        )
                    if c in df.columns:
                        df[c] = pd.to_numeric(df[c], errors="coerce")

                keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
                out[sym] = df[keep]

            except Exception as exc:
                import warnings
                warnings.warn(
                    f"BourseDirectAdapter: failed to fetch {sym}: {type(exc).__name__}: {exc}",
                    stacklevel=2,
                )
                # Return empty DataFrame for this symbol so bulk refresh can continue
                out[sym] = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

        return out


# ----------------------------
# Layer 3d: Yahoo Finance Morocco adapter
# ----------------------------
class YFinanceMoroccoAdapter(YahooFinanceDataSource):
    """
    Thin wrapper on YahooFinanceDataSource for Moroccan stocks.

    Automatically appends the `.CS` suffix when fetching from Yahoo Finance
    and strips it from the returned symbol keys so callers always see the
    internal canonical symbol (e.g. "ATW", not "ATW.CS").

    Symbol mapping can be overridden via the ``provider_map`` dict:
      {internal_symbol: yahoo_ticker}
    """

    YAHOO_SUFFIX = ".CS"

    def __init__(
        self,
        timezone: str = "UTC",
        cache_dir: Optional[Union[str, Path]] = None,
        use_cache: bool = False,
        provider_map: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(timezone=timezone, cache_dir=cache_dir, use_cache=use_cache)
        # {internal_symbol → yahoo_ticker}; if not provided, auto-append .CS
        self.provider_map: Dict[str, str] = provider_map or {}

    def _yahoo_ticker(self, symbol: str) -> str:
        return self.provider_map.get(symbol, f"{symbol}{self.YAHOO_SUFFIX}")

    def _load_impl(
        self,
        symbols: Sequence[str],
        start: Optional[str],
        end: Optional[str],
        interval: str,
        **kwargs,
    ) -> Dict[str, pd.DataFrame]:
        yahoo_symbols = [self._yahoo_ticker(s) for s in symbols]
        raw = super()._load_impl(yahoo_symbols, start, end, interval, **kwargs)

        # Remap keys back to internal symbols
        out: Dict[str, pd.DataFrame] = {}
        for internal_sym, yahoo_sym in zip(symbols, yahoo_symbols):
            if yahoo_sym in raw:
                out[internal_sym] = raw[yahoo_sym]
        return out


class BDCSessionAdapter(BaseDataSource):
    """
    Scrapes the current trading session OHLCV (Données de la séance) from the
    public Bourse de Casablanca instrument page.

    URL pattern:
        https://www.casablanca-bourse.com/fr/live-market/instruments/{SYMBOL}?pwa=1

    The page is server-side rendered; no XHR or headless browser is needed.
    Verified field mapping (from the live BCP page, 2026-03-06):

        Page label       OHLCV column
        Cours (MAD)   -> Close
        Ouverture     -> Open
        Plus haut     -> High
        Plus bas      -> Low
        Volume en titre -> Volume

    Session date is parsed from the "vendredi 6 mars 2026" header embedded in the HTML.
    Falls back to today (Africa/Casablanca = UTC+1) only when no date is found.

    The ``start``/``end`` parameters from the base-class ``load()`` call are ignored
    because this adapter always returns only the current/last session row.  The
    base-class ``slice_date_range`` step will drop it if it pre-dates ``start``,
    which is the correct behaviour (nothing new to merge).

    Numbers use French formatting (comma decimal, space thousands) and are
    converted to float before returning.
    """

    _BASE_URL = (
        "https://www.casablanca-bourse.com/fr/live-market/instruments/{symbol}?pwa=1"
    )
    # (th-label prefix, canonical OHLCV column).
    # Prefix for "Cours" because the live label is "Cours (MAD)".
    _FIELDS: List[Tuple[str, str]] = [
        ("Cours",            "Close"),
        ("Ouverture",        "Open"),
        ("Plus haut",        "High"),
        ("Plus bas",         "Low"),
        ("Volume en titre",  "Volume"),
    ]
    _MONTH_MAP: Dict[str, int] = {
        "janvier": 1,
        "fevrier": 2, "février": 2,
        "mars": 3,
        "avril": 4,
        "mai": 5,
        "juin": 6,
        "juillet": 7,
        "aout": 8, "août": 8,
        "septembre": 9,
        "octobre": 10,
        "novembre": 11,
        "decembre": 12, "décembre": 12,
    }
    _USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )

    def _load_impl(
        self,
        symbols: Sequence[str],
        start: Optional[str],
        end: Optional[str],
        interval: str,
        **kwargs,
    ) -> Dict[str, pd.DataFrame]:
        import re
        import datetime
        import warnings
        import requests

        http = requests.Session()
        http.headers["User-Agent"] = self._USER_AGENT

        results: Dict[str, pd.DataFrame] = {}

        for symbol in symbols:
            url = self._BASE_URL.format(symbol=symbol)
            try:
                resp = http.get(url, timeout=30, verify=False)
                resp.raise_for_status()
                html = resp.text
            except Exception as exc:
                warnings.warn(f"BDCSessionAdapter: HTTP error for {symbol}: {exc}")
                results[symbol] = pd.DataFrame()
                continue

            # --- Session date from "vendredi 6 mars 2026" header ---------------
            date_m = re.search(
                r"(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)"
                r"\s+(\d{1,2})\s+"
                r"(janvier|f[eé]vrier|mars|avril|mai|juin|juillet|ao[uû]t"
                r"|septembre|octobre|novembre|d[eé]cembre)\s+(\d{4})",
                html,
                re.IGNORECASE,
            )
            if date_m:
                day = int(date_m.group(1))
                raw_month = date_m.group(2).lower()
                month = self._MONTH_MAP.get(raw_month)
                if month is None:
                    raise ValueError(
                        f"BDCSessionAdapter: unrecognized month '{raw_month}' "
                        f"on page for symbol '{symbol}'"
                    )
                year = int(date_m.group(3))
                session_date: datetime.date = datetime.date(year, month, day)
            else:
                warnings.warn(
                    f"BDCSessionAdapter: no session date found for {symbol}; "
                    "falling back to today (Africa/Casablanca)"
                )
                try:
                    import zoneinfo
                    session_date = datetime.datetime.now(
                        zoneinfo.ZoneInfo("Africa/Casablanca")
                    ).date()
                except Exception:
                    session_date = datetime.datetime.utcnow().date()

            # --- Parse each OHLCV field ----------------------------------------
            # Server-rendered HTML structure:
            #   <th ...>Cours (MAD)</th><td ...>...<span dir="ltr">255,00</span></td>
            row: Dict[str, float] = {}
            for label_prefix, col in self._FIELDS:
                pattern = (
                    r"<th[^>]*>\s*"
                    + re.escape(label_prefix)
                    + r"[^<]*</th>\s*<td[^>]*>.*?<span\s+dir=[\"']ltr[\"']>([^<]+)</span>"
                )
                m = re.search(pattern, html, re.DOTALL)
                if not m:
                    raise KeyError(
                        f"BDCSessionAdapter: required field '{label_prefix}' not found "
                        f"on the BDC page for symbol '{symbol}' (url={url}). "
                        "The page layout may have changed — "
                        "do NOT invent a fallback value."
                    )
                raw_val = m.group(1).strip()
                # French number format: "261,00" -> 261.0  |  "77 180" -> 77180.0
                normalized = (
                    raw_val.replace("\u00a0", "").replace(" ", "").replace(",", ".")
                )
                try:
                    row[col] = float(normalized)
                except ValueError:
                    raise ValueError(
                        f"BDCSessionAdapter: cannot parse value '{raw_val}' for "
                        f"field '{label_prefix}' (symbol={symbol})"
                    )

            # --- Build single-row DataFrame ------------------------------------
            # Naive timestamp; base-class load() calls _standardize_ohlcv which
            # tz-localizes to self.timezone (UTC by default).
            ts = pd.Timestamp(session_date)
            df = pd.DataFrame([row], index=pd.DatetimeIndex([ts], name="Date"))
            results[symbol] = df

        return results


class ParquetDataSource(BaseDataSource):
    """
    Local parquet adapter.

    This is used by the worker after it materializes MinIO objects to local temp files.
    Core remains pure: it only reads local files.

    Parquet contract:
      - Either:
          (A) DatetimeIndex (recommended), OR
          (B) a 'timestamp' column
      - Columns include Open/High/Low/Close/Volume (case-insensitive tolerated via _standardize_ohlcv)
    """

    def _load_impl(
        self,
        symbols: Sequence[str],
        start: Optional[str],
        end: Optional[str],
        interval: str,
        paths: Union[str, Path, Dict[str, Union[str, Path]]],
        timestamp_col: str = "timestamp",
        **kwargs,
    ) -> Dict[str, pd.DataFrame]:
        if interval.lower() not in ("1d", "1D"):
            raise ValueError("ParquetDataSource currently supports daily bars only (interval='1d').")

        def _read_one(p: Path) -> pd.DataFrame:
            if not p.exists():
                raise FileNotFoundError(f"Parquet file not found: {p}")
            df = pd.read_parquet(p)

            # Ensure datetime index
            if not isinstance(df.index, pd.DatetimeIndex):
                if timestamp_col in df.columns:
                    df[timestamp_col] = _coerce_datetime_series(df[timestamp_col], utc=False)
                    df = df.dropna(subset=[timestamp_col]).set_index(timestamp_col)
                else:
                    raise ValueError(
                        f"Parquet must have DatetimeIndex or a '{timestamp_col}' column. "
                        f"Columns: {list(df.columns)}"
                    )
            return df

        out: Dict[str, pd.DataFrame] = {}

        if isinstance(paths, (str, Path)):
            if len(symbols) != 1:
                raise ValueError("If `paths` is a single path, `symbols` must have length 1.")
            sym = str(symbols[0])
            out[sym] = _read_one(Path(paths))
        else:
            for sym in symbols:
                sym = str(sym)
                if sym not in paths:
                    raise ValueError(f"Missing parquet path for symbol '{sym}'. Provided keys: {list(paths.keys())}")
                out[sym] = _read_one(Path(paths[sym]))

        # Standardize + apply date slice using your existing logic
        # BaseDataSource.load() will call _standardize_ohlcv + date slicing,
        # so here we just return raw df(s).
        return out
