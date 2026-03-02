from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Callable
import itertools
import json
import math
import random
import hashlib
import time

import numpy as np
import pandas as pd

from .data import BMCEDataSource, YahooFinanceDataSource, MarketData, make_synthetic_ohlcv
from .strategy import SignalFrame
from .indicators import IndicatorEngine, FeatureSpec, FeaturesData
from .engine import EngineSpec, DataConfig, StrategyConfig, estimate_warmup_bars_from_params, BacktestEngine
from .portfolio import PortfolioEngine, PortfolioConfig


_MARKET_DATA_CACHE: Dict[str, MarketData] = {}


# ============================================================
# Public dataclasses
# ============================================================

@dataclass(frozen=True)
class OptimizeConfig:
    method: str = "random"        # "random" | "grid"
    seed: int = 42
    n_trials: int = 300           # for random
    top_k: int = 3

    # indicator engine cache options (optimization usually wants memory cache only)
    feature_cache_dir: str = ".cache/features"
    enable_disk_cache: bool = False
    enable_memory_cache: bool = True

    # profiling: when True, cProfile is captured over the trial loop and returned
    # in OptimizeTiming.profile_text (can be written as _debug/profile.txt artifact)
    profiling_enabled: bool = False


@dataclass(frozen=True)
class ParamDef:
    """
    key:
      - "strategy.sma_fast_window", "strategy.sma_slow_window", "strategy.sma_window"
      - "portfolio.cooldown_bars", "portfolio.buy_pct_cash", "portfolio.sell_pct_shares"
      - "data.window" -> tuple(start,end) strings

    kind:
      - "int" | "float" | "choice" | "date_window"

    domain:
      - int:   (lo, hi, step)
      - float: (lo, hi, step)
      - choice: [v1, v2, ...]
      - date_window: [(start, end), ...]
    """
    key: str
    kind: str
    domain: Any
    cast: Callable[[Any], Any] = lambda x: x
    enabled: bool = True


@dataclass(frozen=True)
class TrialResult:
    params: Dict[str, Any]
    pnl: float
    traded_notional: float
    efficiency: float
    n_fills: int
    cagr: float
    error: Optional[str] = None


@dataclass
class OptimizeTiming:
    """Timing and cache statistics for a single run_optimization() call."""
    load_ms: float = 0.0           # data load duration
    bank_ms: float = 0.0           # indicator bank build duration
    trial_total_ms: float = 0.0    # cumulative time inside _eval_one_trial (uncached)
    n_trials_run: int = 0          # trials actually evaluated (not from cache)
    avg_trial_ms: float = 0.0      # trial_total_ms / n_trials_run
    cache_hits: int = 0            # trial results served from eval_cache
    cache_misses: int = 0          # trial results actually computed
    profile_text: Optional[str] = None  # cProfile output text when profiling_enabled


@dataclass
class BankRequest:
    # Existing
    sma: set[int] = field(default_factory=set)
    rsi: set[int] = field(default_factory=set)
    ema: set[int] = field(default_factory=set)
    macd: set[tuple[int, int, int]] = field(default_factory=set)
    std: set[int] = field(default_factory=set)   # rolling std windows

    # New
    obv_ema: set[int] = field(default_factory=set)                 # EMA spans applied to OBV
    vwap: set[int] = field(default_factory=set)                    # rolling VWAP windows
    stoch: set[tuple[int, int, int]] = field(default_factory=set)  # (k_window, d_window, smooth_k)
    ichimoku: set[tuple[int, int, int, int]] = field(default_factory=set)  # (tenkan, kijun, senkou_b, shift)

    def merge(self, other: "BankRequest") -> "BankRequest":
        self.sma |= other.sma
        self.rsi |= other.rsi
        self.ema |= other.ema
        self.macd |= other.macd
        self.std |= other.std

        self.obv_ema |= other.obv_ema
        self.vwap |= other.vwap
        self.stoch |= other.stoch
        self.ichimoku |= other.ichimoku
        return self




def rolling_std_cumsum(close: np.ndarray, w: int) -> np.ndarray:
    x = np.asarray(close, np.float64)
    n = x.size
    out = np.full(n, np.nan, dtype=np.float64)
    if w <= 0 or w > n:
        return out

    c1 = np.cumsum(np.insert(x, 0, 0.0))
    c2 = np.cumsum(np.insert(x * x, 0, 0.0))

    sum_x = c1[w:] - c1[:-w]
    sum_x2 = c2[w:] - c2[:-w]

    mean = sum_x / w
    var = (sum_x2 / w) - mean * mean
    var = np.maximum(var, 0.0)  # numerical guard
    out[w-1:] = np.sqrt(var)
    return out


def sma_cumsum(close: np.ndarray, w: int) -> np.ndarray:
    x = np.asarray(close, np.float64)
    n = x.size
    out = np.full(n, np.nan, dtype=np.float64)
    if w <= 0 or w > n:
        return out
    c = np.cumsum(np.insert(x, 0, 0.0))
    out[w-1:] = (c[w:] - c[:-w]) / w
    return out

def ema(x: np.ndarray, span: int) -> np.ndarray:
    a = np.asarray(x, np.float64)
    n = a.size
    out = np.full(n, np.nan, dtype=np.float64)
    if span <= 0 or n == 0:
        return out
    alpha = 2.0 / (span + 1.0)
    # seed at first finite
    i0 = np.argmax(np.isfinite(a))
    if not np.isfinite(a[i0]):
        return out
    out[i0] = a[i0]
    for i in range(i0 + 1, n):
        if np.isfinite(a[i]):
            out[i] = alpha * a[i] + (1 - alpha) * out[i-1]
        else:
            out[i] = out[i-1]
    return out
# ============================================================
# "Today" signal helpers (used for optimizer leaderboard)
# ============================================================

def _signal_to_label(sig: Any) -> str:
    """
    Map numeric signal to label.
    Convention:
      +1 => BUY
      -1 => SELL
       0 => HOLD
      NaN/None => NA
    """
    if sig is None or (isinstance(sig, float) and np.isnan(sig)):
        return "NA"
    try:
        s = int(sig)
    except Exception:
        return "NA"
    if s > 0:
        return "BUY"
    if s < 0:
        return "SELL"
    return "HOLD"


def _extract_params_from_row(row: dict) -> Dict[str, Any]:
    """
    Keep only param-like keys from a leaderboard row.
    (Avoid passing metrics like pnl/cagr/n_fills/error into the adapter.)
    """
    out: Dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(k, str) and (
            k.startswith("strategy.") or k.startswith("portfolio.") or k.startswith("data.")
        ):
            out[k] = v
    return out


def _latest_signal_for_params(
    *,
    adapter: "StrategyAdapter",
    base_spec: EngineSpec,
    symbols: List[str],
    index: pd.DatetimeIndex,
    bank: Dict[str, Dict[str, np.ndarray]],
    bars_close: Dict[str, np.ndarray],
    bars_high: Dict[str, np.ndarray],
    bars_low: Dict[str, np.ndarray],
    bars_vol: Dict[str, np.ndarray],
    params: Dict[str, Any],
) -> Tuple[pd.Timestamp, float, str]:
    """
    Compute last-bar signal using the SAME adapter logic used during optimization.
    Returns: (signal_date, numeric_signal, label)

    Uses the fast array path (make_signal_arrays_fast) when available to avoid
    DataFrame construction for just one bar lookup.
    """
    signal_date = pd.Timestamp(index[-1])
    sym0 = symbols[0]

    _fast_fn = getattr(adapter, "make_signal_arrays_fast", None)
    if _fast_fn is not None:
        # Fast path: get full signal array, take last element — no DataFrame allocation.
        need_vol = base_spec.strategy.kind.lower() in ("obv", "stoch_vwap")
        _sig_arrays = _fast_fn(
            symbols=symbols,
            bank=bank,
            bars_close=bars_close,
            bars_high=bars_high,
            bars_low=bars_low,
            bars_vol=bars_vol if need_vol else {},
            params=params,
            base_spec=base_spec,
        )
        arr = _sig_arrays.get(sym0)
        if arr is None or len(arr) == 0:
            return signal_date, float("nan"), "NA"
        raw = float(arr[-1])
        if np.isnan(raw):
            return signal_date, raw, "NA"
        sig_val = 1.0 if raw > 0.0 else (-1.0 if raw < 0.0 else 0.0)
        return signal_date, sig_val, _signal_to_label(sig_val)

    # Legacy fallback: DataFrame-based signal generation.
    sf = adapter.make_signals_from_bank(
        symbols=symbols,
        index=index,
        bank=bank,
        bars_close=bars_close,
        bars_high=bars_high,
        bars_low=bars_low,
        bars_vol=bars_vol,
        params=params,
        base_spec=base_spec,
    )

    sig_val = np.nan
    is_valid = True

    if sf.signals is not None and sym0 in sf.signals.columns and len(sf.signals) > 0:
        sig_val = sf.signals[sym0].iloc[-1]

    if sf.validity is not None and sym0 in sf.validity.columns and len(sf.validity) > 0:
        is_valid = bool(sf.validity[sym0].iloc[-1])

    if not is_valid:
        return signal_date, float(sig_val) if sig_val is not None else float("nan"), "NA"

    label = _signal_to_label(sig_val)
    return signal_date, float(sig_val) if sig_val is not None else float("nan"), label
def obv_array(close: np.ndarray, vol: np.ndarray) -> np.ndarray:
    c = np.asarray(close, np.float64)
    v = np.asarray(vol, np.float64)
    n = c.size
    out = np.full(n, np.nan, dtype=np.float64)
    if n == 0:
        return out
    out[0] = 0.0
    dc = np.diff(c)
    sign = np.sign(dc)  # +1,0,-1
    inc = sign * v[1:]
    out[1:] = np.cumsum(inc)
    return out


def rolling_vwap_array(high: np.ndarray, low: np.ndarray, close: np.ndarray, vol: np.ndarray, window: int) -> np.ndarray:
    h = np.asarray(high, np.float64)
    l = np.asarray(low, np.float64)
    c = np.asarray(close, np.float64)
    v = np.asarray(vol, np.float64)

    n = c.size
    out = np.full(n, np.nan, dtype=np.float64)
    if window <= 0 or n < window:
        return out

    tp = (h + l + c) / 3.0
    pv = tp * v

    # rolling sums via cumulative sums
    c_pv = np.cumsum(np.insert(pv, 0, 0.0))
    c_v  = np.cumsum(np.insert(v, 0, 0.0))

    num = c_pv[window:] - c_pv[:-window]
    den = c_v[window:] - c_v[:-window]
    den = np.where(den == 0.0, np.nan, den)

    out[window-1:] = num / den
    return out


def stoch_kd_arrays(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    k_window: int,
    d_window: int,
    smooth_k: int,
) -> Tuple[np.ndarray, np.ndarray]:
    # Use pandas rolling for correctness/stability (acceptable compute for n_trials scale)
    idx = pd.RangeIndex(len(close))
    h = pd.Series(np.asarray(high, np.float64), index=idx)
    l = pd.Series(np.asarray(low, np.float64), index=idx)
    c = pd.Series(np.asarray(close, np.float64), index=idx)

    hh = h.rolling(k_window, min_periods=k_window).max()
    ll = l.rolling(k_window, min_periods=k_window).min()
    denom = (hh - ll).replace(0.0, np.nan)

    k = 100.0 * (c - ll) / denom
    if smooth_k and smooth_k > 1:
        k = k.rolling(smooth_k, min_periods=smooth_k).mean()
    d = k.rolling(d_window, min_periods=d_window).mean()

    return k.to_numpy(np.float64), d.to_numpy(np.float64)


def ichimoku_arrays(
    high: np.ndarray,
    low: np.ndarray,
    tenkan: int,
    kijun: int,
    senkou_b: int,
    shift: int,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    idx = pd.RangeIndex(len(high))
    h = pd.Series(np.asarray(high, np.float64), index=idx)
    l = pd.Series(np.asarray(low, np.float64), index=idx)

    tenkan_line = (h.rolling(tenkan, min_periods=tenkan).max() + l.rolling(tenkan, min_periods=tenkan).min()) / 2.0
    kijun_line  = (h.rolling(kijun,  min_periods=kijun ).max() + l.rolling(kijun,  min_periods=kijun ).min()) / 2.0

    span_a = ((tenkan_line + kijun_line) / 2.0).shift(shift)
    span_b = ((h.rolling(senkou_b, min_periods=senkou_b).max() + l.rolling(senkou_b, min_periods=senkou_b).min()) / 2.0).shift(shift)

    return (
        tenkan_line.to_numpy(np.float64),
        kijun_line.to_numpy(np.float64),
        span_a.to_numpy(np.float64),
        span_b.to_numpy(np.float64),
    )

def rsi_wilder(close: np.ndarray, window: int) -> np.ndarray:
    x = np.asarray(close, np.float64)
    n = x.size
    out = np.full(n, np.nan, dtype=np.float64)
    if window <= 0 or n < window + 1:
        return out

    delta = np.diff(x)
    up = np.maximum(delta, 0.0)
    dn = np.maximum(-delta, 0.0)

    avg_up = np.full(n-1, np.nan, dtype=np.float64)
    avg_dn = np.full(n-1, np.nan, dtype=np.float64)

    avg_up[window-1] = np.mean(up[:window])
    avg_dn[window-1] = np.mean(dn[:window])

    alpha = 1.0 / window
    for i in range(window, n-1):
        avg_up[i] = (1 - alpha) * avg_up[i-1] + alpha * up[i]
        avg_dn[i] = (1 - alpha) * avg_dn[i-1] + alpha * dn[i]

    rs = avg_up / np.where(avg_dn == 0.0, np.nan, avg_dn)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    out[1:] = rsi
    return out

def macd_pack(close: np.ndarray, fast: int, slow: int, signal: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    ef = ema(close, fast)
    es = ema(close, slow)
    macd_line = ef - es
    sig_line = ema(macd_line, signal)
    hist = macd_line - sig_line
    return macd_line, sig_line, hist

def build_bank(
    close_by_sym: Dict[str, np.ndarray],
    high_by_sym: Dict[str, np.ndarray],
    low_by_sym: Dict[str, np.ndarray],
    vol_by_sym: Dict[str, np.ndarray],
    req: BankRequest
) -> Dict[str, Dict[str, np.ndarray]]:
    bank: Dict[str, Dict[str, np.ndarray]] = {sym: {} for sym in close_by_sym}

    # If MACD requested, we implicitly need EMA(close, fast/slow)
    if req.macd:
        for (f, s, _g) in req.macd:
            req.ema.add(int(f))
            req.ema.add(int(s))

    for sym, close in close_by_sym.items():
        sym_bank: Dict[str, np.ndarray] = bank[sym]

        # ---- SMA ----
        for w in sorted(req.sma):
            sym_bank[f"sma_{int(w)}"] = sma_cumsum(close, int(w))

        # ---- RSI ----
        for w in sorted(req.rsi):
            sym_bank[f"rsi_{int(w)}"] = rsi_wilder(close, int(w))

        # ---- EMA(close) ----
        ema_close_cache: Dict[int, np.ndarray] = {}
        for span in sorted(req.ema):
            span = int(span)
            ema_close_cache[span] = ema(close, span)
            sym_bank[f"ema_{span}"] = ema_close_cache[span]

        # ---- MACD ----
        for (f, s, g) in sorted(req.macd):
            f, s, g = int(f), int(s), int(g)
            m, ms, h = macd_pack_cached(close, f, s, g, ema_close_cache)
            sym_bank[f"macd_{f}_{s}_{g}"] = m
            sym_bank[f"macd_signal_{f}_{s}_{g}"] = ms
            sym_bank[f"macd_hist_{f}_{s}_{g}"] = h

        # ---- Rolling STD ----
        for w in sorted(req.std):
            sym_bank[f"std_{int(w)}"] = rolling_std_cumsum(close, int(w))

        # -------------------------
        # OBV + EMA(OBV)
        # -------------------------
        if req.obv_ema:
            if "obv" not in sym_bank:
                sym_bank["obv"] = obv_array(close_by_sym[sym], vol_by_sym[sym])
            obv = sym_bank["obv"]
            for span in sorted(req.obv_ema):
                sym_bank[f"obv_ema_{int(span)}"] = ema(obv, int(span))

        # -------------------------
        # Rolling VWAP (daily proxy)
        # -------------------------
        if req.vwap:
            for w in sorted(req.vwap):
                w = int(w)
                sym_bank[f"vwap_{w}"] = rolling_vwap_array(
                    high_by_sym[sym], low_by_sym[sym], close_by_sym[sym], vol_by_sym[sym], w
                )

        # -------------------------
        # Stochastic %K/%D
        # -------------------------
        if req.stoch:
            for (k_w, d_w, s_k) in sorted(req.stoch):
                k_w, d_w, s_k = int(k_w), int(d_w), int(s_k)
                k, d = stoch_kd_arrays(
                    high_by_sym[sym], low_by_sym[sym], close_by_sym[sym],
                    k_window=k_w, d_window=d_w, smooth_k=s_k
                )
                key = f"stoch_{k_w}_{d_w}_{s_k}"
                sym_bank[f"{key}__k"] = k
                sym_bank[f"{key}__d"] = d

        # -------------------------
        # Ichimoku
        # -------------------------
        if req.ichimoku:
            for (ten, kij, sb, sh) in sorted(req.ichimoku):
                ten, kij, sb, sh = int(ten), int(kij), int(sb), int(sh)
                tenkan_line, kijun_line, span_a, span_b = ichimoku_arrays(
                    high_by_sym[sym], low_by_sym[sym],
                    tenkan=ten, kijun=kij, senkou_b=sb, shift=sh
                )
                key = f"ichimoku_{ten}_{kij}_{sb}_{sh}"
                sym_bank[f"{key}__tenkan"] = tenkan_line
                sym_bank[f"{key}__kijun"] = kijun_line
                sym_bank[f"{key}__span_a"] = span_a
                sym_bank[f"{key}__span_b"] = span_b

    return bank



# ============================================================
# Strategy adapter registry (fast + strategy-agnostic optimization)
# ============================================================

@dataclass(frozen=True)
class StrategyAdapter:
    kind: str

    def required_bank(self, base_spec: EngineSpec, active_params: list[ParamDef]) -> BankRequest:
        return BankRequest()

    def make_signals_from_bank(
        self,
        symbols: List[str],
        index: pd.DatetimeIndex,
        bank: Dict[str, Dict[str, np.ndarray]],
        bars_close: Dict[str, np.ndarray],
        bars_high: Dict[str, np.ndarray],
        bars_low: Dict[str, np.ndarray],
        bars_vol: Dict[str, np.ndarray],
        params: Dict[str, Any],
        base_spec: EngineSpec,
    ) -> SignalFrame:
        raise NotImplementedError(f"{self.kind}: make_signals_from_bank not implemented")



    def validate_params(self, params: Dict[str, Any], base_spec: EngineSpec) -> Tuple[bool, Optional[str]]:
        return True, None


class MACrossAdapter(StrategyAdapter):
    def __init__(self):
        super().__init__(kind="ma_cross")

    def validate_params(self, params: Dict[str, Any], base_spec: EngineSpec) -> Tuple[bool, Optional[str]]:
        base_params = dict(base_spec.strategy.params or {})
        f = int(
            params.get(
                "strategy.sma_fast_window",
                base_params.get("sma_fast_window", base_params.get("fast_window", 15)),
            )
        )
        s = int(
            params.get(
                "strategy.sma_slow_window",
                base_params.get("sma_slow_window", base_params.get("slow_window", 50)),
            )
        )
        if f >= s:
            return False, "fast_window must be < slow_window"
        if f <= 0 or s <= 0:
            return False, "windows must be positive"
        return True, None

    def required_bank(self, base_spec, active_params):
        req = BankRequest()
        base_params = dict(base_spec.strategy.params or {})
        f0 = int(base_params.get("sma_fast_window", base_params.get("fast_window", 15)))
        s0 = int(base_params.get("sma_slow_window", base_params.get("slow_window", 50)))
        req.sma.add(f0)
        req.sma.add(s0)
        req.sma |= set(_domain_values_int(active_params, "strategy.sma_fast_window"))
        req.sma |= set(_domain_values_int(active_params, "strategy.sma_slow_window"))
        return req


    def make_signals_from_bank(
        self,
        symbols: List[str],
        index: pd.DatetimeIndex,
        bank: Dict[str, Dict[str, np.ndarray]],
        bars_close: Dict[str, np.ndarray],
        bars_high: Dict[str, np.ndarray],
        bars_low: Dict[str, np.ndarray],
        bars_vol: Dict[str, np.ndarray],
        params: Dict[str, Any],
        base_spec: EngineSpec,
    ) -> SignalFrame:
        base_params = dict(base_spec.strategy.params or {})
        f = int(
            params.get(
                "strategy.sma_fast_window",
                base_params.get("sma_fast_window", base_params.get("fast_window", 15)),
            )
        )
        s = int(
            params.get(
                "strategy.sma_slow_window",
                base_params.get("sma_slow_window", base_params.get("slow_window", 50)),
            )
        )

        allow_short = bool(base_params.get("allow_short", False))
        # allow overriding allow_short if the app exposes it as a choice param
        if "strategy.allow_short" in params:
            allow_short = bool(params["strategy.allow_short"])

        nan_policy = str(base_params.get("nan_policy", "flat"))
        if "strategy.nan_policy" in params:
            nan_policy = str(params["strategy.nan_policy"])

        col_fast = f"sma_{f}"
        col_slow = f"sma_{s}"

        sig = pd.DataFrame(index=index, columns=symbols, dtype="float64")
        valid = pd.DataFrame(index=index, columns=symbols, dtype="bool")

        for sym in symbols:
            fast = bank[sym][col_fast]
            slow = bank[sym][col_slow]

            v = (~np.isnan(fast)) & (~np.isnan(slow))
            long_mask = fast > slow
            short_mask = fast < slow
            # Match runtime strategy semantics: emit -1 as exit intent even when allow_short is False.
            out = np.zeros(len(index), dtype=np.float64)
            out[long_mask] = 1.0
            out[short_mask] = -1.0

            if nan_policy == "flat":
                out = np.where(v, out, 0.0)
            else:
                out = np.where(v, out, np.nan)

            sig[sym] = out
            valid[sym] = v

        return SignalFrame(
            signals=sig,
            validity=valid,
            meta={"adapter": "ma_cross", "fast_window": f, "slow_window": s, "allow_short": allow_short, "nan_policy": nan_policy},
        )

    def make_signal_arrays_fast(
        self,
        symbols: List[str],
        bank: Dict[str, Dict[str, np.ndarray]],
        bars_close: Dict[str, np.ndarray],
        bars_high: Dict[str, np.ndarray],
        bars_low: Dict[str, np.ndarray],
        bars_vol: Dict[str, np.ndarray],
        params: Dict[str, Any],
        base_spec: "EngineSpec",
    ) -> Dict[str, np.ndarray]:
        base_params = dict(base_spec.strategy.params or {})
        f = int(params.get("strategy.sma_fast_window", base_params.get("sma_fast_window", base_params.get("fast_window", 15))))
        s = int(params.get("strategy.sma_slow_window", base_params.get("sma_slow_window", base_params.get("slow_window", 50))))
        nan_policy = str(params.get("strategy.nan_policy", base_params.get("nan_policy", "flat")))
        col_fast = f"sma_{f}"
        col_slow = f"sma_{s}"
        out: Dict[str, np.ndarray] = {}
        for sym in symbols:
            fast = bank[sym][col_fast]
            slow = bank[sym][col_slow]
            v = (~np.isnan(fast)) & (~np.isnan(slow))
            arr = np.zeros(len(fast), dtype=np.float64)
            arr[fast > slow] = 1.0
            arr[fast < slow] = -1.0
            if nan_policy == "flat":
                arr = np.where(v, arr, 0.0)
            else:
                arr = np.where(v, arr, np.nan)
            out[sym] = arr
        return out


class PriceAboveSMAAdapter(StrategyAdapter):
    def __init__(self):
        super().__init__(kind="sma_price")

    def required_bank(self, base_spec: EngineSpec, active_params: List[ParamDef]) -> BankRequest:
        req = BankRequest()
        base_params = dict(base_spec.strategy.params or {})
        w0 = int(base_params.get("sma_window", base_params.get("window", 50)))
        req.sma.add(w0)
        req.sma |= set(_domain_values_int(active_params, "strategy.sma_window"))
        return req


    def validate_params(self, params: Dict[str, Any], base_spec: EngineSpec) -> Tuple[bool, Optional[str]]:
        base_params = dict(base_spec.strategy.params or {})
        w = int(params.get("strategy.sma_window", base_params.get("sma_window", base_params.get("window", 50))))
        if w <= 0:
            return False, "window must be positive"
        signal_mode = str(
            params.get(
                "strategy.signal_mode",
                params.get("strategy.sma_signal_mode", base_params.get("signal_mode", "level")),
            )
        ).strip().lower()
        if signal_mode not in {"level", "cross"}:
            return False, "signal_mode must be one of: level, cross"
        return True, None

    def make_signals_from_bank(
        self,
        symbols: List[str],
        index: pd.DatetimeIndex,
        bank: Dict[str, Dict[str, np.ndarray]],
        bars_close: Dict[str, np.ndarray],
        bars_high: Dict[str, np.ndarray],
        bars_low: Dict[str, np.ndarray],
        bars_vol: Dict[str, np.ndarray],
        params: Dict[str, Any],
        base_spec: EngineSpec,
    ) -> SignalFrame:
        base_params = dict(base_spec.strategy.params or {})
        w = int(params.get("strategy.sma_window", base_params.get("sma_window", base_params.get("window", 50))))

        allow_short = bool(base_params.get("allow_short", False))
        if "strategy.allow_short" in params:
            allow_short = bool(params["strategy.allow_short"])

        nan_policy = str(base_params.get("nan_policy", "flat"))
        if "strategy.nan_policy" in params:
            nan_policy = str(params["strategy.nan_policy"])
        signal_mode = str(
            params.get(
                "strategy.signal_mode",
                params.get("strategy.sma_signal_mode", base_params.get("signal_mode", "level")),
            )
        ).strip().lower()
        if signal_mode not in {"level", "cross"}:
            signal_mode = "level"

        col_sma = f"sma_{w}"

        sig = pd.DataFrame(index=index, columns=symbols, dtype="float64")
        valid = pd.DataFrame(index=index, columns=symbols, dtype="bool")

        for sym in symbols:
            close = bars_close[sym]
            sma = bank[sym][col_sma]
            v = (~np.isnan(close)) & (~np.isnan(sma))

            if signal_mode == "cross":
                prev_close = np.roll(close, 1)
                prev_sma = np.roll(sma, 1)
                prev_close[0] = np.nan
                prev_sma[0] = np.nan

                long_mask = (close > sma) & (prev_close <= prev_sma)
                short_mask = (close < sma) & (prev_close >= prev_sma)
                out = np.zeros(len(index), dtype=np.float64)
                out[long_mask] = 1.0
                if allow_short:
                    out[short_mask] = -1.0
            else:
                long_mask = close > sma
                short_mask = close < sma
                if allow_short:
                    out = np.zeros(len(index), dtype=np.float64)
                    out[long_mask] = 1.0
                    out[short_mask] = -1.0
                else:
                    out = long_mask.astype(np.float64)

            if nan_policy == "flat":
                out = np.where(v, out, 0.0)
            else:
                out = np.where(v, out, np.nan)

            sig[sym] = out
            valid[sym] = v

        return SignalFrame(
            signals=sig,
            validity=valid,
            meta={
                "adapter": "sma_price",
                "window": w,
                "allow_short": allow_short,
                "signal_mode": signal_mode,
                "nan_policy": nan_policy,
            },
        )

    def make_signal_arrays_fast(
        self,
        symbols: List[str],
        bank: Dict[str, Dict[str, np.ndarray]],
        bars_close: Dict[str, np.ndarray],
        bars_high: Dict[str, np.ndarray],
        bars_low: Dict[str, np.ndarray],
        bars_vol: Dict[str, np.ndarray],
        params: Dict[str, Any],
        base_spec: "EngineSpec",
    ) -> Dict[str, np.ndarray]:
        base_params = dict(base_spec.strategy.params or {})
        w = int(params.get("strategy.sma_window", base_params.get("sma_window", base_params.get("window", 50))))
        allow_short = bool(params.get("strategy.allow_short", base_params.get("allow_short", False)))
        nan_policy = str(params.get("strategy.nan_policy", base_params.get("nan_policy", "flat")))
        signal_mode = str(params.get("strategy.signal_mode", params.get("strategy.sma_signal_mode", base_params.get("signal_mode", "level")))).strip().lower()
        if signal_mode not in {"level", "cross"}:
            signal_mode = "level"
        col_sma = f"sma_{w}"
        out: Dict[str, np.ndarray] = {}
        for sym in symbols:
            close = bars_close[sym]
            sma = bank[sym][col_sma]
            v = (~np.isnan(close)) & (~np.isnan(sma))
            if signal_mode == "cross":
                prev_close = np.roll(close, 1); prev_close[0] = np.nan
                prev_sma = np.roll(sma, 1); prev_sma[0] = np.nan
                arr = np.zeros(len(close), dtype=np.float64)
                arr[(close > sma) & (prev_close <= prev_sma)] = 1.0
                if allow_short:
                    arr[(close < sma) & (prev_close >= prev_sma)] = -1.0
            else:
                if allow_short:
                    arr = np.zeros(len(close), dtype=np.float64)
                    arr[close > sma] = 1.0
                    arr[close < sma] = -1.0
                else:
                    arr = (close > sma).astype(np.float64)
            if nan_policy == "flat":
                arr = np.where(v, arr, 0.0)
            else:
                arr = np.where(v, arr, np.nan)
            out[sym] = arr
        return out


class RSIStrategyAdapter(StrategyAdapter):
    def __init__(self):
        super().__init__(kind="rsi")

    def validate_params(self, params: Dict[str, Any], base_spec: EngineSpec) -> Tuple[bool, Optional[str]]:
        base_params = dict(base_spec.strategy.params or {})
        w = int(params.get("strategy.rsi_window", base_params.get("rsi_window", base_params.get("period", 14))))
        low = float(params.get("strategy.rsi_oversold", base_params.get("rsi_oversold", base_params.get("low", 30.0))))
        high = float(params.get("strategy.rsi_overbought", base_params.get("rsi_overbought", base_params.get("high", 70.0))))
        mode = str(params.get("strategy.mode", base_params.get("mode", "reversal"))).strip().lower()

        if w <= 0:
            return False, "rsi_window must be positive"
        if not (0.0 <= low <= 100.0 and 0.0 <= high <= 100.0):
            return False, "rsi_oversold/rsi_overbought must be in [0, 100]"
        if low >= high:
            return False, "rsi_oversold must be < rsi_overbought"
        if mode not in {"reversal", "momentum"}:
            return False, "mode must be one of: reversal, momentum"
        return True, None

    def required_bank(self, base_spec: EngineSpec, active_params: List[ParamDef]) -> BankRequest:
        req = BankRequest()
        base_params = dict(base_spec.strategy.params or {})
        w0 = int(base_params.get("rsi_window", base_params.get("period", 14)))
        req.rsi.add(w0)
        req.rsi |= set(_domain_values_int(active_params, "strategy.rsi_window"))
        return req


    def make_signals_from_bank(
        self,
        symbols: List[str],
        index: pd.DatetimeIndex,
        bank: Dict[str, Dict[str, np.ndarray]],
        bars_close: Dict[str, np.ndarray],
        bars_high: Dict[str, np.ndarray],
        bars_low: Dict[str, np.ndarray],
        bars_vol: Dict[str, np.ndarray],
        params: Dict[str, Any],
        base_spec: EngineSpec,
    ) -> SignalFrame:
        base_params = dict(base_spec.strategy.params or {})
        w = int(params.get("strategy.rsi_window", base_params.get("rsi_window", base_params.get("period", 14))))
        low = float(params.get("strategy.rsi_oversold", base_params.get("rsi_oversold", base_params.get("low", 30.0))))
        high = float(params.get("strategy.rsi_overbought", base_params.get("rsi_overbought", base_params.get("high", 70.0))))
        mode = str(params.get("strategy.mode", base_params.get("mode", "reversal"))).strip().lower()
        if mode not in {"reversal", "momentum"}:
            mode = "reversal"

        allow_short = bool(base_params.get("allow_short", False))
        if "strategy.allow_short" in params:
            allow_short = bool(params["strategy.allow_short"])

        nan_policy = str(base_params.get("nan_policy", "flat"))
        if "strategy.nan_policy" in params:
            nan_policy = str(params["strategy.nan_policy"])

        col = f"rsi_{w}"

        sig = pd.DataFrame(index=index, columns=symbols, dtype="float64")
        valid = pd.DataFrame(index=index, columns=symbols, dtype="bool")

        for sym in symbols:
            rsi = bank[sym][col]
            v = ~np.isnan(rsi)

            if mode == "reversal":
                long_mask = rsi < low
                short_mask = rsi > high
            else:
                long_mask = rsi > high
                short_mask = rsi < low

            # Match runtime strategy semantics: always emit exit intent (-1) on short_mask.
            out = np.zeros(len(index), dtype=np.float64)
            out[long_mask] = 1.0
            out[short_mask] = -1.0

            if nan_policy == "flat":
                out = np.where(v, out, 0.0)
            else:
                out = np.where(v, out, np.nan)

            sig[sym] = out
            valid[sym] = v

        return SignalFrame(
            signals=sig,
            validity=valid,
            meta={
                "adapter": "rsi",
                "rsi_window": w,
                "rsi_oversold": low,
                "rsi_overbought": high,
                "mode": mode,
                "allow_short": allow_short,
                "nan_policy": nan_policy,
            },
        )

    def make_signal_arrays_fast(
        self,
        symbols: List[str],
        bank: Dict[str, Dict[str, np.ndarray]],
        bars_close: Dict[str, np.ndarray],
        bars_high: Dict[str, np.ndarray],
        bars_low: Dict[str, np.ndarray],
        bars_vol: Dict[str, np.ndarray],
        params: Dict[str, Any],
        base_spec: "EngineSpec",
    ) -> Dict[str, np.ndarray]:
        base_params = dict(base_spec.strategy.params or {})
        w = int(params.get("strategy.rsi_window", base_params.get("rsi_window", base_params.get("period", 14))))
        low = float(params.get("strategy.rsi_oversold", base_params.get("rsi_oversold", base_params.get("low", 30.0))))
        high = float(params.get("strategy.rsi_overbought", base_params.get("rsi_overbought", base_params.get("high", 70.0))))
        mode = str(params.get("strategy.mode", base_params.get("mode", "reversal"))).strip().lower()
        if mode not in {"reversal", "momentum"}:
            mode = "reversal"
        nan_policy = str(params.get("strategy.nan_policy", base_params.get("nan_policy", "flat")))
        col = f"rsi_{w}"
        out: Dict[str, np.ndarray] = {}
        for sym in symbols:
            rsi = bank[sym][col]
            v = ~np.isnan(rsi)
            arr = np.zeros(len(rsi), dtype=np.float64)
            if mode == "reversal":
                arr[rsi < low] = 1.0
                arr[rsi > high] = -1.0
            else:
                arr[rsi > high] = 1.0
                arr[rsi < low] = -1.0
            if nan_policy == "flat":
                arr = np.where(v, arr, 0.0)
            else:
                arr = np.where(v, arr, np.nan)
            out[sym] = arr
        return out


class MACDStrategyAdapter(StrategyAdapter):
    def __init__(self):
        super().__init__(kind="macd")

    def validate_params(self, params: Dict[str, Any], base_spec: EngineSpec) -> Tuple[bool, Optional[str]]:
        base_params = dict(base_spec.strategy.params or {})
        f = int(params.get("strategy.macd_fast_window", base_params.get("macd_fast_window", base_params.get("fast", 12))))
        s = int(params.get("strategy.macd_slow_window", base_params.get("macd_slow_window", base_params.get("slow", 26))))
        sig = int(params.get("strategy.macd_signal_window", base_params.get("macd_signal_window", base_params.get("signal", 9))))

        if f <= 0 or s <= 0 or sig <= 0:
            return False, "macd_fast/slow/signal must be positive"
        if f >= s:
            return False, "macd_fast must be < macd_slow"
        return True, None

    def required_bank(self, base_spec: EngineSpec, active_params: List[ParamDef]) -> BankRequest:
        req = BankRequest()
        base_params = dict(base_spec.strategy.params or {})

        f0 = int(base_params.get("macd_fast_window", base_params.get("fast", 12)))
        s0 = int(base_params.get("macd_slow_window", base_params.get("slow", 26)))
        g0 = int(base_params.get("macd_signal_window", base_params.get("signal", 9)))

        fs = _domain_values_int(active_params, "strategy.macd_fast_window") or [f0]
        ss = _domain_values_int(active_params, "strategy.macd_slow_window") or [s0]
        gs = _domain_values_int(active_params, "strategy.macd_signal_window") or [g0]

        for f in (fs + [f0]):
            for s in (ss + [s0]):
                for g in (gs + [g0]):
                    f, s, g = int(f), int(s), int(g)
                    if f > 0 and s > 0 and g > 0 and f < s:
                        req.macd.add((f, s, g))

        return req


    def make_signals_from_bank(
        self,
        symbols: List[str],
        index: pd.DatetimeIndex,
        bank: Dict[str, Dict[str, np.ndarray]],
        bars_close: Dict[str, np.ndarray],
        bars_high: Dict[str, np.ndarray],
        bars_low: Dict[str, np.ndarray],
        bars_vol: Dict[str, np.ndarray],
        params: Dict[str, Any],
        base_spec: EngineSpec,
    ) -> SignalFrame:
        base_params = dict(base_spec.strategy.params or {})
        f = int(params.get("strategy.macd_fast_window", base_params.get("macd_fast_window", base_params.get("fast", 12))))
        s = int(params.get("strategy.macd_slow_window", base_params.get("macd_slow_window", base_params.get("slow", 26))))
        g = int(params.get("strategy.macd_signal_window", base_params.get("macd_signal_window", base_params.get("signal", 9))))

        use_hist = bool(base_params.get("macd_use_hist", False))
        if "strategy.macd_use_hist" in params:
            use_hist = bool(params["strategy.macd_use_hist"])

        allow_short = bool(base_params.get("allow_short", False))
        if "strategy.allow_short" in params:
            allow_short = bool(params["strategy.allow_short"])

        nan_policy = str(base_params.get("nan_policy", "flat"))
        if "strategy.nan_policy" in params:
            nan_policy = str(params["strategy.nan_policy"])
        trigger = str(
            params.get(
                "strategy.trigger",
                params.get("strategy.macd_trigger", base_params.get("trigger", "cross")),
            )
        ).strip().lower()
        if trigger not in {"cross", "zero"}:
            trigger = "cross"

        col_macd = f"macd_{f}_{s}_{g}"          # MACD line
        col_sig  = f"macd_signal_{f}_{s}_{g}"   # signal line
        col_hist = f"macd_hist_{f}_{s}_{g}"     # histogram

        sig_df = pd.DataFrame(index=index, columns=symbols, dtype="float64")
        valid_df = pd.DataFrame(index=index, columns=symbols, dtype="bool")

        for sym in symbols:
            if use_hist:
                line = bank[sym][col_hist]
                sigl = np.zeros_like(line)
                v = ~np.isnan(line)
            else:
                line = bank[sym][col_macd]
                sigl = bank[sym][col_sig]
                v = (~np.isnan(line)) & (~np.isnan(sigl))

            out = np.zeros(len(index), dtype=np.float64)

            if trigger == "cross":
                prev_line = np.roll(line, 1)
                prev_sigl = np.roll(sigl, 1)
                prev_line[0] = np.nan
                prev_sigl[0] = np.nan
                buy = (line > sigl) & (prev_line <= prev_sigl)
                sell = (line < sigl) & (prev_line >= prev_sigl)
            else:
                prev_line = np.roll(line, 1)
                prev_line[0] = np.nan
                buy = (line > 0.0) & (prev_line <= 0.0)
                sell = (line < 0.0) & (prev_line >= 0.0)
            out[buy] = 1.0
            # Match runtime strategy semantics: emit exit intent even in long-only mode.
            out[sell] = -1.0

            if nan_policy == "flat":
                out = np.where(v, out, 0.0)
            else:
                out = np.where(v, out, np.nan)

            sig_df[sym] = out
            valid_df[sym] = v

        return SignalFrame(
            signals=sig_df,
            validity=valid_df,
            meta={
                "adapter": "macd",
                "fast": f,
                "slow": s,
                "signal": g,
                "trigger": trigger,
                "use_hist": use_hist,
                "allow_short": allow_short,
                "nan_policy": nan_policy,
            },
        )

    def make_signal_arrays_fast(
        self,
        symbols: List[str],
        bank: Dict[str, Dict[str, np.ndarray]],
        bars_close: Dict[str, np.ndarray],
        bars_high: Dict[str, np.ndarray],
        bars_low: Dict[str, np.ndarray],
        bars_vol: Dict[str, np.ndarray],
        params: Dict[str, Any],
        base_spec: "EngineSpec",
    ) -> Dict[str, np.ndarray]:
        base_params = dict(base_spec.strategy.params or {})
        f = int(params.get("strategy.macd_fast_window", base_params.get("macd_fast_window", base_params.get("fast", 12))))
        s = int(params.get("strategy.macd_slow_window", base_params.get("macd_slow_window", base_params.get("slow", 26))))
        g = int(params.get("strategy.macd_signal_window", base_params.get("macd_signal_window", base_params.get("signal", 9))))
        use_hist = bool(params.get("strategy.macd_use_hist", base_params.get("macd_use_hist", False)))
        nan_policy = str(params.get("strategy.nan_policy", base_params.get("nan_policy", "flat")))
        trigger = str(params.get("strategy.trigger", params.get("strategy.macd_trigger", base_params.get("trigger", "cross")))).strip().lower()
        if trigger not in {"cross", "zero"}:
            trigger = "cross"
        col_macd = f"macd_{f}_{s}_{g}"
        col_sig  = f"macd_signal_{f}_{s}_{g}"
        col_hist = f"macd_hist_{f}_{s}_{g}"
        out: Dict[str, np.ndarray] = {}
        for sym in symbols:
            if use_hist:
                line = bank[sym][col_hist]
                sigl = np.zeros_like(line)
                v = ~np.isnan(line)
            else:
                line = bank[sym][col_macd]
                sigl = bank[sym][col_sig]
                v = (~np.isnan(line)) & (~np.isnan(sigl))
            arr = np.zeros(len(line), dtype=np.float64)
            if trigger == "cross":
                prev_line = np.roll(line, 1); prev_line[0] = np.nan
                prev_sigl = np.roll(sigl, 1); prev_sigl[0] = np.nan
                arr[(line > sigl) & (prev_line <= prev_sigl)] = 1.0
                arr[(line < sigl) & (prev_line >= prev_sigl)] = -1.0
            else:
                prev_line = np.roll(line, 1); prev_line[0] = np.nan
                arr[(line > 0.0) & (prev_line <= 0.0)] = 1.0
                arr[(line < 0.0) & (prev_line >= 0.0)] = -1.0
            if nan_policy == "flat":
                arr = np.where(v, arr, 0.0)
            else:
                arr = np.where(v, arr, np.nan)
            out[sym] = arr
        return out


class BollingerAdapter(StrategyAdapter):
    def __init__(self):
        super().__init__(kind="bollinger")

    def validate_params(self, params: Dict[str, Any], base_spec: EngineSpec) -> Tuple[bool, Optional[str]]:
        w = int(params.get("strategy.bb_window", base_spec.strategy.params.get("bb_window", 20)))
        k = float(params.get("strategy.bb_k", base_spec.strategy.params.get("bb_k", 2.0)))
        if w <= 1:
            return False, "bb_window must be > 1"
        if k <= 0:
            return False, "bb_k must be positive"
        return True, None

    def required_bank(self, base_spec: EngineSpec, active_params: List[ParamDef]) -> BankRequest:
        req = BankRequest()
        w0 = int(base_spec.strategy.params.get("bb_window", 20))
        req.sma.add(w0)
        req.std.add(w0)

        ws = _domain_values_int(active_params, "strategy.bb_window")
        for w in ws:
            if w is not None and int(w) > 1:
                req.sma.add(int(w))
                req.std.add(int(w))
        return req

    def make_signals_from_bank(
        self,
        symbols: List[str],
        index: pd.DatetimeIndex,
        bank: Dict[str, Dict[str, np.ndarray]],
        bars_close: Dict[str, np.ndarray],
        bars_high: Dict[str, np.ndarray],
        bars_low: Dict[str, np.ndarray],
        bars_vol: Dict[str, np.ndarray],
        params: Dict[str, Any],
        base_spec: EngineSpec,
    ) -> SignalFrame:
        w = int(params.get("strategy.bb_window", base_spec.strategy.params.get("bb_window", 20)))
        k = float(params.get("strategy.bb_k", base_spec.strategy.params.get("bb_k", 2.0)))

        allow_short = bool(base_spec.strategy.params.get("allow_short", False))
        if "strategy.allow_short" in params:
            allow_short = bool(params["strategy.allow_short"])

        nan_policy = str(base_spec.strategy.params.get("nan_policy", "flat"))
        if "strategy.nan_policy" in params:
            nan_policy = str(params["strategy.nan_policy"])

        col_mid = f"sma_{w}"
        col_std = f"std_{w}"

        sig = pd.DataFrame(index=index, columns=symbols, dtype="float64")
        valid = pd.DataFrame(index=index, columns=symbols, dtype="bool")

        for sym in symbols:
            close = bars_close[sym]
            mid = bank[sym][col_mid]
            std = bank[sym][col_std]

            v = np.isfinite(close) & np.isfinite(mid) & np.isfinite(std)
            upper = mid + k * std
            lower = mid - k * std

            long_mask = close < lower
            short_mask = close > upper
            # Match runtime strategy semantics: emit -1 as exit intent even when allow_short is False.
            out = np.zeros(len(index), dtype=np.float64)
            out[long_mask] = 1.0
            out[short_mask] = -1.0

            if nan_policy == "flat":
                out = np.where(v, out, 0.0)
            else:
                out = np.where(v, out, np.nan)

            sig[sym] = out
            valid[sym] = v

        return SignalFrame(
            signals=sig,
            validity=valid,
            meta={"adapter": "bollinger", "bb_window": w, "bb_k": k, "allow_short": allow_short, "nan_policy": nan_policy},
        )

    def make_signal_arrays_fast(
        self,
        symbols: List[str],
        bank: Dict[str, Dict[str, np.ndarray]],
        bars_close: Dict[str, np.ndarray],
        bars_high: Dict[str, np.ndarray],
        bars_low: Dict[str, np.ndarray],
        bars_vol: Dict[str, np.ndarray],
        params: Dict[str, Any],
        base_spec: "EngineSpec",
    ) -> Dict[str, np.ndarray]:
        w = int(params.get("strategy.bb_window", base_spec.strategy.params.get("bb_window", 20)))
        k = float(params.get("strategy.bb_k", base_spec.strategy.params.get("bb_k", 2.0)))
        nan_policy = str(params.get("strategy.nan_policy", base_spec.strategy.params.get("nan_policy", "flat")))
        col_mid = f"sma_{w}"
        col_std = f"std_{w}"
        out: Dict[str, np.ndarray] = {}
        for sym in symbols:
            close = bars_close[sym]
            mid = bank[sym][col_mid]
            std = bank[sym][col_std]
            v = np.isfinite(close) & np.isfinite(mid) & np.isfinite(std)
            upper = mid + k * std
            lower = mid - k * std
            arr = np.zeros(len(close), dtype=np.float64)
            arr[close < lower] = 1.0
            arr[close > upper] = -1.0
            if nan_policy == "flat":
                arr = np.where(v, arr, 0.0)
            else:
                arr = np.where(v, arr, np.nan)
            out[sym] = arr
        return out


class OBVAdapter(StrategyAdapter):
    def __init__(self):
        super().__init__(kind="obv")

    def required_bank(self, base_spec: EngineSpec, active_params: list[ParamDef]) -> BankRequest:
        req = BankRequest()
        span0 = int(base_spec.strategy.params.get("obv_span", 20))
        req.obv_ema.add(span0)
        req.obv_ema |= set(_domain_values_int(active_params, "strategy.obv_span"))
        return req

    def make_signals_from_bank(
        self,
        symbols: List[str],
        index: pd.DatetimeIndex,
        bank: Dict[str, Dict[str, np.ndarray]],
        bars_close: Dict[str, np.ndarray],
        bars_high: Dict[str, np.ndarray],
        bars_low: Dict[str, np.ndarray],
        bars_vol: Dict[str, np.ndarray],
        params: Dict[str, Any],
        base_spec: EngineSpec,
    ) -> SignalFrame:
        sym = symbols[0]
        span = int(params.get("strategy.obv_span", base_spec.strategy.params.get("obv_span", 20)))
        allow_short = bool(params.get("strategy.allow_short", base_spec.strategy.params.get("allow_short", False)))
        nan_policy = str(params.get("strategy.nan_policy", base_spec.strategy.params.get("nan_policy", "flat")))

        obv = bank[sym]["obv"]
        obv_ema = bank[sym][f"obv_ema_{span}"]

        valid = np.isfinite(obv) & np.isfinite(obv_ema)
        sig = np.zeros_like(obv, dtype=np.float64)

        sig[obv > obv_ema] = 1.0
        if allow_short:
            sig[obv < obv_ema] = -1.0
        else:
            sig[obv < obv_ema] = -1.0  # exit intent

        if nan_policy == "flat":
            sig = np.where(valid, sig, 0.0)
        else:
            sig = np.where(valid, sig, np.nan)

        return SignalFrame(
            signals=pd.DataFrame({sym: sig}, index=index),
            validity=pd.DataFrame({sym: valid.astype(bool)}, index=index),
            meta={"adapter": "obv", "obv_span": span, "allow_short": allow_short, "nan_policy": nan_policy},
        )

    def make_signal_arrays_fast(
        self,
        symbols: List[str],
        bank: Dict[str, Dict[str, np.ndarray]],
        bars_close: Dict[str, np.ndarray],
        bars_high: Dict[str, np.ndarray],
        bars_low: Dict[str, np.ndarray],
        bars_vol: Dict[str, np.ndarray],
        params: Dict[str, Any],
        base_spec: "EngineSpec",
    ) -> Dict[str, np.ndarray]:
        sym = symbols[0]
        span = int(params.get("strategy.obv_span", base_spec.strategy.params.get("obv_span", 20)))
        nan_policy = str(params.get("strategy.nan_policy", base_spec.strategy.params.get("nan_policy", "flat")))
        obv = bank[sym]["obv"]
        obv_ema = bank[sym][f"obv_ema_{span}"]
        valid = np.isfinite(obv) & np.isfinite(obv_ema)
        arr = np.zeros_like(obv, dtype=np.float64)
        arr[obv > obv_ema] = 1.0
        arr[obv < obv_ema] = -1.0
        if nan_policy == "flat":
            arr = np.where(valid, arr, 0.0)
        else:
            arr = np.where(valid, arr, np.nan)
        return {sym: arr}


class StochVWAPAdapter(StrategyAdapter):
    def __init__(self):
        super().__init__(kind="stoch_vwap")

    def required_bank(self, base_spec: EngineSpec, active_params: list[ParamDef]) -> BankRequest:
        req = BankRequest()

        k0 = int(base_spec.strategy.params.get("k_window", 14))
        d0 = int(base_spec.strategy.params.get("d_window", 3))
        s0 = int(base_spec.strategy.params.get("smooth_k", 1))
        v0 = int(base_spec.strategy.params.get("vwap_window", 20))

        req.stoch.add((k0, d0, s0))
        req.vwap.add(v0)

        # domains
        ks = set(_domain_values_int(active_params, "strategy.k_window"))
        ds = set(_domain_values_int(active_params, "strategy.d_window"))
        ss = set(_domain_values_int(active_params, "strategy.smooth_k"))
        vs = set(_domain_values_int(active_params, "strategy.vwap_window"))

        # If any domain missing, keep at least base values
        if not ks: ks = {k0}
        if not ds: ds = {d0}
        if not ss: ss = {s0}

        for k in ks:
            for d in ds:
                for s in ss:
                    req.stoch.add((int(k), int(d), int(s)))

        req.vwap |= {int(x) for x in (vs if vs else {v0})}
        return req

    @staticmethod
    def _cross_up(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return (a[:-1] <= b[:-1]) & (a[1:] > b[1:])

    @staticmethod
    def _cross_down(a: np.ndarray, b: np.ndarray) -> np.ndarray:
        return (a[:-1] >= b[:-1]) & (a[1:] < b[1:])

    def make_signals_from_bank(
        self,
        symbols: List[str],
        index: pd.DatetimeIndex,
        bank: Dict[str, Dict[str, np.ndarray]],
        bars_close: Dict[str, np.ndarray],
        bars_high: Dict[str, np.ndarray],
        bars_low: Dict[str, np.ndarray],
        bars_vol: Dict[str, np.ndarray],
        params: Dict[str, Any],
        base_spec: EngineSpec,
    ) -> SignalFrame:
        sym = symbols[0]

        k_w = int(params.get("strategy.k_window", base_spec.strategy.params.get("k_window", 14)))
        d_w = int(params.get("strategy.d_window", base_spec.strategy.params.get("d_window", 3)))
        s_k = int(params.get("strategy.smooth_k", base_spec.strategy.params.get("smooth_k", 1)))
        v_w = int(params.get("strategy.vwap_window", base_spec.strategy.params.get("vwap_window", 20)))

        allow_short = bool(params.get("strategy.allow_short", base_spec.strategy.params.get("allow_short", False)))
        nan_policy = str(params.get("strategy.nan_policy", base_spec.strategy.params.get("nan_policy", "flat")))

        key = f"stoch_{k_w}_{d_w}_{s_k}"
        k = bank[sym][f"{key}__k"]
        d = bank[sym][f"{key}__d"]
        vwap = bank[sym][f"vwap_{v_w}"]
        close = bars_close[sym]

        valid = np.isfinite(k) & np.isfinite(d) & np.isfinite(vwap) & np.isfinite(close)

        # cross arrays are length n-1; align by putting False at t=0
        n = close.size
        kx_up = np.zeros(n, dtype=bool)
        kx_dn = np.zeros(n, dtype=bool)
        cx_up = np.zeros(n, dtype=bool)
        cx_dn = np.zeros(n, dtype=bool)
        kx_up[1:] = self._cross_up(k, d)
        kx_dn[1:] = self._cross_down(k, d)
        cx_up[1:] = self._cross_up(close, vwap)
        cx_dn[1:] = self._cross_down(close, vwap)

        buy1 = kx_up & (k < 20) & (d < 20) & (close > vwap)
        buy2 = (k > 50) & (k < 80) & (d > 50) & (d < 80) & cx_up
        buy3 = kx_up & (k < 80) & (d < 80) & (close > vwap)
        buy = buy1 | buy2 | buy3

        sell1 = kx_dn & (k > 80) & (d > 80) & (close < vwap)
        sell2 = (k > 20) & (k < 50) & (d > 20) & (d < 50) & cx_dn
        sell3 = kx_dn & (k > 20) & (d > 20) & (close < vwap)
        sell = sell1 | sell2 | sell3

        sig = np.zeros(n, dtype=np.float64)
        sig[buy] = 1.0
        # precedence: SELL overrides
        sig[sell] = -1.0

        if nan_policy == "flat":
            sig = np.where(valid, sig, 0.0)
        else:
            sig = np.where(valid, sig, np.nan)

        return SignalFrame(
            signals=pd.DataFrame({sym: sig}, index=index),
            validity=pd.DataFrame({sym: valid.astype(bool)}, index=index),
            meta={
                "adapter": "stoch_vwap",
                "k_window": k_w, "d_window": d_w, "smooth_k": s_k, "vwap_window": v_w,
                "allow_short": allow_short, "nan_policy": nan_policy,
            },
        )

    def make_signal_arrays_fast(
        self,
        symbols: List[str],
        bank: Dict[str, Dict[str, np.ndarray]],
        bars_close: Dict[str, np.ndarray],
        bars_high: Dict[str, np.ndarray],
        bars_low: Dict[str, np.ndarray],
        bars_vol: Dict[str, np.ndarray],
        params: Dict[str, Any],
        base_spec: "EngineSpec",
    ) -> Dict[str, np.ndarray]:
        sym = symbols[0]
        k_w = int(params.get("strategy.k_window", base_spec.strategy.params.get("k_window", 14)))
        d_w = int(params.get("strategy.d_window", base_spec.strategy.params.get("d_window", 3)))
        s_k = int(params.get("strategy.smooth_k", base_spec.strategy.params.get("smooth_k", 1)))
        v_w = int(params.get("strategy.vwap_window", base_spec.strategy.params.get("vwap_window", 20)))
        nan_policy = str(params.get("strategy.nan_policy", base_spec.strategy.params.get("nan_policy", "flat")))
        key = f"stoch_{k_w}_{d_w}_{s_k}"
        k = bank[sym][f"{key}__k"]
        d = bank[sym][f"{key}__d"]
        vwap = bank[sym][f"vwap_{v_w}"]
        close = bars_close[sym]
        valid = np.isfinite(k) & np.isfinite(d) & np.isfinite(vwap) & np.isfinite(close)
        n = close.size
        kx_up = np.zeros(n, dtype=bool); kx_dn = np.zeros(n, dtype=bool)
        cx_up = np.zeros(n, dtype=bool); cx_dn = np.zeros(n, dtype=bool)
        kx_up[1:] = self._cross_up(k, d); kx_dn[1:] = self._cross_down(k, d)
        cx_up[1:] = self._cross_up(close, vwap); cx_dn[1:] = self._cross_down(close, vwap)
        buy = (kx_up & (k < 20) & (d < 20) & (close > vwap)) | ((k > 50) & (k < 80) & (d > 50) & (d < 80) & cx_up) | (kx_up & (k < 80) & (d < 80) & (close > vwap))
        sell = (kx_dn & (k > 80) & (d > 80) & (close < vwap)) | ((k > 20) & (k < 50) & (d > 20) & (d < 50) & cx_dn) | (kx_dn & (k > 20) & (d > 20) & (close < vwap))
        arr = np.zeros(n, dtype=np.float64)
        arr[buy] = 1.0; arr[sell] = -1.0
        if nan_policy == "flat":
            arr = np.where(valid, arr, 0.0)
        else:
            arr = np.where(valid, arr, np.nan)
        return {sym: arr}


class IchimokuAdapter(StrategyAdapter):
    def __init__(self):
        super().__init__(kind="ichimoku")

    def required_bank(self, base_spec: EngineSpec, active_params: list[ParamDef]) -> BankRequest:
        req = BankRequest()
        ten = int(base_spec.strategy.params.get("tenkan", 9))
        kij = int(base_spec.strategy.params.get("kijun", 26))
        sb  = int(base_spec.strategy.params.get("senkou_b", 52))
        sh  = int(base_spec.strategy.params.get("shift", 26))

        req.ichimoku.add((ten, kij, sb, sh))

        # If you decide later to optimize these windows, you can extend domains here.
        return req

    def make_signals_from_bank(
        self,
        symbols: List[str],
        index: pd.DatetimeIndex,
        bank: Dict[str, Dict[str, np.ndarray]],
        bars_close: Dict[str, np.ndarray],
        bars_high: Dict[str, np.ndarray],
        bars_low: Dict[str, np.ndarray],
        bars_vol: Dict[str, np.ndarray],
        params: Dict[str, Any],
        base_spec: EngineSpec,
    ) -> SignalFrame:
        sym = symbols[0]

        ten = int(params.get("strategy.tenkan", base_spec.strategy.params.get("tenkan", 9)))
        kij = int(params.get("strategy.kijun", base_spec.strategy.params.get("kijun", 26)))
        sb  = int(params.get("strategy.senkou_b", base_spec.strategy.params.get("senkou_b", 52)))
        sh  = int(params.get("strategy.shift", base_spec.strategy.params.get("shift", 26)))

        allow_short = bool(params.get("strategy.allow_short", base_spec.strategy.params.get("allow_short", False)))
        nan_policy = str(params.get("strategy.nan_policy", base_spec.strategy.params.get("nan_policy", "flat")))

        key = f"ichimoku_{ten}_{kij}_{sb}_{sh}"
        tenkan = bank[sym][f"{key}__tenkan"]
        kijun  = bank[sym][f"{key}__kijun"]
        span_a = bank[sym][f"{key}__span_a"]
        span_b = bank[sym][f"{key}__span_b"]
        close  = bars_close[sym]

        cloud_top = np.maximum(span_a, span_b)
        cloud_bot = np.minimum(span_a, span_b)

        valid = np.isfinite(close) & np.isfinite(tenkan) & np.isfinite(kijun) & np.isfinite(cloud_top) & np.isfinite(cloud_bot)

        buy  = (close > cloud_top) & (tenkan > kijun)
        sell = (close < cloud_bot) & (tenkan < kijun)

        sig = np.zeros(close.size, dtype=np.float64)
        sig[buy] = 1.0
        sig[sell] = -1.0

        if nan_policy == "flat":
            sig = np.where(valid, sig, 0.0)
        else:
            sig = np.where(valid, sig, np.nan)

        return SignalFrame(
            signals=pd.DataFrame({sym: sig}, index=index),
            validity=pd.DataFrame({sym: valid.astype(bool)}, index=index),
            meta={"adapter": "ichimoku", "tenkan": ten, "kijun": kij, "senkou_b": sb, "shift": sh,
                  "allow_short": allow_short, "nan_policy": nan_policy},
        )

    def make_signal_arrays_fast(
        self,
        symbols: List[str],
        bank: Dict[str, Dict[str, np.ndarray]],
        bars_close: Dict[str, np.ndarray],
        bars_high: Dict[str, np.ndarray],
        bars_low: Dict[str, np.ndarray],
        bars_vol: Dict[str, np.ndarray],
        params: Dict[str, Any],
        base_spec: "EngineSpec",
    ) -> Dict[str, np.ndarray]:
        sym = symbols[0]
        ten = int(params.get("strategy.tenkan", base_spec.strategy.params.get("tenkan", 9)))
        kij = int(params.get("strategy.kijun", base_spec.strategy.params.get("kijun", 26)))
        sb  = int(params.get("strategy.senkou_b", base_spec.strategy.params.get("senkou_b", 52)))
        sh  = int(params.get("strategy.shift", base_spec.strategy.params.get("shift", 26)))
        nan_policy = str(params.get("strategy.nan_policy", base_spec.strategy.params.get("nan_policy", "flat")))
        key = f"ichimoku_{ten}_{kij}_{sb}_{sh}"
        tenkan = bank[sym][f"{key}__tenkan"]
        kijun  = bank[sym][f"{key}__kijun"]
        span_a = bank[sym][f"{key}__span_a"]
        span_b = bank[sym][f"{key}__span_b"]
        close  = bars_close[sym]
        cloud_top = np.maximum(span_a, span_b)
        cloud_bot = np.minimum(span_a, span_b)
        valid = np.isfinite(close) & np.isfinite(tenkan) & np.isfinite(kijun) & np.isfinite(cloud_top) & np.isfinite(cloud_bot)
        arr = np.zeros(close.size, dtype=np.float64)
        arr[(close > cloud_top) & (tenkan > kijun)] = 1.0
        arr[(close < cloud_bot) & (tenkan < kijun)] = -1.0
        if nan_policy == "flat":
            arr = np.where(valid, arr, 0.0)
        else:
            arr = np.where(valid, arr, np.nan)
        return {sym: arr}


STRATEGY_ADAPTERS: Dict[str, StrategyAdapter] = {
    "ma_cross": MACrossAdapter(),
    "sma_price": PriceAboveSMAAdapter(),
    "rsi": RSIStrategyAdapter(),
    "macd": MACDStrategyAdapter(),
    "bollinger": BollingerAdapter(),
    "obv": OBVAdapter(),
    "stoch_vwap": StochVWAPAdapter(),
    "ichimoku": IchimokuAdapter(),
}



# ============================================================
# Catalog helpers (optional but useful for Streamlit UI)
# ============================================================

def default_param_catalog(strategy_kind: str) -> Dict[str, ParamDef]:
    cat: Dict[str, ParamDef] = {}

    if strategy_kind == "ma_cross":
        cat["strategy.sma_fast_window"] = ParamDef("strategy.sma_fast_window", "int", (5, 60, 1), int)
        cat["strategy.sma_slow_window"] = ParamDef("strategy.sma_slow_window", "int", (20, 250, 1), int)
      

    elif strategy_kind == "sma_price":
        cat["strategy.sma_window"] = ParamDef("strategy.sma_window", "int", (10, 250, 1), int)
    
    elif strategy_kind == "rsi":
        cat["strategy.rsi_window"] = ParamDef("strategy.rsi_window", "int", (5, 100, 1), int)
        cat["strategy.rsi_oversold"] = ParamDef("strategy.rsi_oversold", "float", (10.0, 40.0, 10.0), float)
        cat["strategy.rsi_overbought"] = ParamDef("strategy.rsi_overbought", "float", (60.0, 90.0, 10.0), float)

    elif strategy_kind == "macd":
        cat["strategy.macd_fast_window"] = ParamDef("strategy.macd_fast_window", "int", (5, 50, 1), int)
        cat["strategy.macd_slow_window"] = ParamDef("strategy.macd_slow_window", "int", (20, 200, 1), int)
        cat["strategy.macd_signal_window"] = ParamDef("strategy.macd_signal_window", "int", (5, 50, 1), int)

    elif strategy_kind == "bollinger":
        cat["strategy.bb_window"] = ParamDef("strategy.bb_window", "int", (10, 100, 1), int)
        cat["strategy.bb_k"] = ParamDef("strategy.bb_k", "float", (2.0, 5.0, 0.5), float)
    
    elif strategy_kind == "obv":
        cat["strategy.obv_span"] = ParamDef("strategy.obv_span", "int", (5, 200, 1), int)

    elif strategy_kind == "stoch_vwap":
        cat["strategy.k_window"] = ParamDef("strategy.k_window", "int", (5, 60, 1), int)
        cat["strategy.d_window"] = ParamDef("strategy.d_window", "int", (2, 20, 1), int)
        cat["strategy.smooth_k"] = ParamDef("strategy.smooth_k", "int", (1, 10, 1), int)
        cat["strategy.vwap_window"] = ParamDef("strategy.vwap_window", "int", (5, 100, 1), int)

    elif strategy_kind == "ichimoku":
        # baseline fixed: keep disabled by default (optimize won't vary them)
        cat["strategy.tenkan"] = ParamDef("strategy.tenkan", "int", [9], int, enabled=False)
        cat["strategy.kijun"] = ParamDef("strategy.kijun", "int", [26], int, enabled=False)
        cat["strategy.senkou_b"] = ParamDef("strategy.senkou_b", "int", [52], int, enabled=False)
        cat["strategy.shift"] = ParamDef("strategy.shift", "int", [26], int, enabled=False)

       
    # portfolio knobs you mentioned
    cat["portfolio.cooldown_bars"] = ParamDef("portfolio.cooldown_bars", "int", (0, 30, 1), int)
    cat["portfolio.buy_pct_cash"] = ParamDef("portfolio.buy_pct_cash", "float", (0.25, 1.1, 0.25), float)
    cat["portfolio.sell_pct_shares"] = ParamDef("portfolio.sell_pct_shares", "float", (0.25, 1.1, 0.25), float)

    return cat

def macd_pack_cached(
    close: np.ndarray,
    fast: int,
    slow: int,
    signal: int,
    ema_close_cache: Dict[int, np.ndarray],
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    # cache EMA(close, span)
    ef = ema_close_cache.get(fast)
    if ef is None:
        ef = ema(close, fast)
        ema_close_cache[fast] = ef

    es = ema_close_cache.get(slow)
    if es is None:
        es = ema(close, slow)
        ema_close_cache[slow] = es

    macd_line = ef - es

    # cannot reuse across different (fast,slow), but cheap enough
    sig_line = ema(macd_line, signal)
    hist = macd_line - sig_line
    return macd_line, sig_line, hist


# ============================================================
# Core optimization
# ============================================================

def run_optimization(
    base_spec: EngineSpec,
    active_params: List[ParamDef],
    cfg: OptimizeConfig,
) -> Tuple[TrialResult, pd.DataFrame, Dict[str, Any], EngineSpec, pd.DataFrame, "OptimizeTiming"]:
    """
    Fast optimizer:
      - load MarketData once
      - precompute required features once (union of needed SMA windows)
      - per trial: generate signals from precomputed arrays (adapter), apply cooldown via PortfolioConfig, run portfolio stats fast

    Returns:
      best_result, top_df, best_params, best_spec, ranked_df, timing
    """
    if not active_params:
        raise ValueError("active_params is empty; nothing to optimize.")

    strategy_kind = base_spec.strategy.kind.lower()
    if strategy_kind not in STRATEGY_ADAPTERS:
        raise ValueError(f"No StrategyAdapter registered for strategy kind '{strategy_kind}'")

    adapter = STRATEGY_ADAPTERS[strategy_kind]

    _t0_total = time.perf_counter()

    # 1) Load data once with warmup padding so fast-optimizer signals match runtime indicator history.
    data_cfg = base_spec.data
    load_cfg = data_cfg
    warmup_pad = estimate_warmup_bars_from_params(base_spec, active_params)
    if data_cfg.start and warmup_pad > 0:
        start_dt = pd.to_datetime(data_cfg.start)
        pad_start = start_dt - pd.tseries.offsets.BDay(int(warmup_pad))
        load_cfg = replace(load_cfg, start=pad_start.date().isoformat())
    if data_cfg.end:
        load_cfg = replace(load_cfg, end=data_cfg.end)

    _t_load_start = time.perf_counter()
    md_full = _load_market_data_from_spec(load_cfg)
    _load_ms = (time.perf_counter() - _t_load_start) * 1000.0

    symbols = list(base_spec.data.symbols)
    if not symbols:
        raise ValueError("No symbols in base_spec.data.symbols")

    # 2) Build a common index once (inner intersection across symbols for robustness)
    #    This ensures arrays are aligned and portfolio doesn't hit missing timestamps.
    md = _align_marketdata_inner(md_full, symbols)

    common_index = md.bars[symbols[0]].index
    if len(common_index) < 2:
        raise ValueError("Not enough bars after alignment; need at least 2 timestamps.")


    # --- aligned price arrays ONCE ---
    bars_open: Dict[str, np.ndarray] = {}
    bars_close: Dict[str, np.ndarray] = {}
    bars_vol: Dict[str, np.ndarray] = {}
    bars_high: Dict[str, np.ndarray] = {}
    bars_low: Dict[str, np.ndarray] = {}

    need_volume = bool(base_spec.portfolio.use_participation_cap or base_spec.portfolio.use_volume_gate)
    need_volume_for_strategy = base_spec.strategy.kind.lower() in ("obv", "stoch_vwap")  # obv needs vol; stoch_vwap needs vol for vwap proxy
    need_volume = bool(need_volume or need_volume_for_strategy)
    adv_by_window_np: Dict[int, Dict[str, np.ndarray]] = {}

    for s in symbols:
        b = md.bars[s].reindex(common_index)  # aligned already; reindex ok & explicit
        bars_open[s] = b["Open"].to_numpy(dtype=np.float64, copy=False)
        bars_close[s] = b["Close"].to_numpy(dtype=np.float64, copy=False)
        bars_high[s] = b["High"].to_numpy(dtype=np.float64, copy=False)
        bars_low[s] = b["Low"].to_numpy(dtype=np.float64, copy=False)
        if need_volume:
            vcol = base_spec.portfolio.volume_col
            if vcol not in b.columns:
                raise KeyError(f"Missing volume column '{vcol}' for {s}. Available: {list(b.columns)}")
            bars_vol[s] = b[vcol].to_numpy(dtype=np.float64, copy=False)
            
    # 3) Precompute arrays once (ALWAYS) + SMA bank (IF NEEDED)
    _t_bank_start = time.perf_counter()
    req = adapter.required_bank(base_spec, active_params)
    bank = build_bank(bars_close, bars_high, bars_low, bars_vol, req)
    _bank_ms = (time.perf_counter() - _t_bank_start) * 1000.0
        
    if need_volume:
        adv_windows: List[int] = []
        if base_spec.portfolio.use_participation_cap and str(base_spec.portfolio.participation_basis) == "adv":
            adv_windows.append(int(base_spec.portfolio.adv_window))
        if base_spec.portfolio.use_volume_gate and str(base_spec.portfolio.volume_gate_kind) == "min_ratio_adv":
            adv_windows.append(int(base_spec.portfolio.volume_gate_adv_window))
        adv_windows = sorted(set(w for w in adv_windows if w >= 1))

        for w in adv_windows:
            adv_by_window_np[w] = {}
            for s in symbols:
                v = bars_vol[s]
                # min_periods=1 behavior
                c = np.cumsum(np.insert(v, 0, 0.0))
                adv = np.empty_like(v)
                # first part: min_periods=1
                idx = np.arange(v.size)
                lo = np.maximum(0, idx - (w - 1))
                den = (idx - lo + 1).astype(np.float64)
                adv[:] = (c[idx + 1] - c[lo]) / den
                adv_by_window_np[w][s] = adv

    # 3b) Evaluate trials on the original user window, while keeping padded history in features.
    eval_index = _slice_index(common_index, data_cfg.start, data_cfg.end)
    if eval_index is None or len(eval_index) < 2:
        raise ValueError("Not enough bars after applying base data start/end window.")
    if len(eval_index) != len(common_index):
        idx_pos_eval = common_index.get_indexer_for(eval_index)
        common_index = eval_index

        for s in symbols:
            bars_open[s] = bars_open[s][idx_pos_eval]
            bars_close[s] = bars_close[s][idx_pos_eval]
            bars_high[s] = bars_high[s][idx_pos_eval]
            bars_low[s] = bars_low[s][idx_pos_eval]
            if need_volume:
                bars_vol[s] = bars_vol[s][idx_pos_eval]
            bank[s] = {k: v[idx_pos_eval] for k, v in bank[s].items()}

        for w, by_symbol in adv_by_window_np.items():
            for s in symbols:
                by_symbol[s] = by_symbol[s][idx_pos_eval]

    




    # 4) Candidate iterator
    method = cfg.method.lower()
    if method == "grid":
        candidates = _iter_grid([p for p in active_params if p.enabled])
    elif method == "random":
        candidates = _iter_random([p for p in active_params if p.enabled], n_trials=int(cfg.n_trials), seed=int(cfg.seed))
    else:
        raise ValueError(f"Unknown optimization method: {cfg.method}")

    # 4b) Pre-hoist PortfolioEngine when no portfolio params are being varied.
    #     Avoids creating N identical PortfolioEngine/NBConfig objects in the loop.
    _PORT_PARAM_KEYS = frozenset(("portfolio.cooldown_bars", "portfolio.buy_pct_cash", "portfolio.sell_pct_shares"))
    _active_keys = frozenset(p.key for p in active_params if p.enabled)
    _precomputed_port: Optional[PortfolioEngine] = None
    if not (_active_keys & _PORT_PARAM_KEYS):
        _precomputed_port = PortfolioEngine(base_spec.portfolio)

    # 5) Evaluate
    results: List[TrialResult] = []
    eval_cache: Dict[str, TrialResult] = {}
    _trial_total_ms = 0.0
    _n_trials_run = 0
    _cache_hits = 0
    _cache_misses = 0

    # Optional cProfile capture
    import cProfile, pstats, io as _io
    _prof = cProfile.Profile() if cfg.profiling_enabled else None
    if _prof is not None:
        _prof.enable()

    for params in candidates:
        params_key = _trial_params_key(params)
        cached_result = eval_cache.get(params_key)
        if cached_result is not None:
            _cache_hits += 1
            results.append(cached_result)
            continue

        ok, err = adapter.validate_params(params, base_spec)
        if not ok:
            invalid_result = TrialResult(
                params=params,
                pnl=float("-inf"),
                traded_notional=0.0,
                efficiency=float("-inf"),
                n_fills=0,
                cagr=float("-inf"),
                error=err or "invalid params",
            )
            eval_cache[params_key] = invalid_result
            results.append(invalid_result)
            _cache_misses += 1
            continue

        _t_trial = time.perf_counter()
        r = _eval_one_trial(
            base_spec=base_spec,
            md=md,
            common_index=common_index,
            bank=bank,
            bars_open=bars_open,
            bars_close=bars_close,
            bars_high=bars_high,
            bars_low=bars_low,
            bars_vol=bars_vol,
            adv_by_window_np=adv_by_window_np,
            adapter=adapter,
            params=params,
            precomputed_port=_precomputed_port,
        )
        _trial_total_ms += (time.perf_counter() - _t_trial) * 1000.0
        _n_trials_run += 1
        _cache_misses += 1

        eval_cache[params_key] = r
        results.append(r)

    if _prof is not None:
        _prof.disable()
        _sb = _io.StringIO()
        _ps = pstats.Stats(_prof, stream=_sb).sort_stats("cumulative")
        _ps.print_stats(30)
        _profile_text: Optional[str] = _sb.getvalue()
    else:
        _profile_text = None

    _timing = OptimizeTiming(
        load_ms=_load_ms,
        bank_ms=_bank_ms,
        trial_total_ms=_trial_total_ms,
        n_trials_run=_n_trials_run,
        avg_trial_ms=(_trial_total_ms / _n_trials_run) if _n_trials_run > 0 else 0.0,
        cache_hits=_cache_hits,
        cache_misses=_cache_misses,
        profile_text=_profile_text,
    )

    df = pd.DataFrame([{
        **r.params,
        "pnl": r.pnl,
        "traded_notional": r.traded_notional,
        "efficiency": r.efficiency,
        "n_fills": r.n_fills,
        "cagr": r.cagr,
        "error": r.error,
    } for r in results])

    # rank valid rows by (pnl desc, efficiency desc)
    df_valid = df[df["error"].isna()].copy()
    if df_valid.empty:
        ranked_df = df.sort_values(["pnl", "cagr"], ascending=[False, False]).reset_index(drop=True)
        top_df = ranked_df.head(int(cfg.top_k)).reset_index(drop=True)

        # ---- add last-bar ("today") signal columns to leaderboard ----
        sig_dates: List[pd.Timestamp] = []
        sig_nums: List[float] = []
        sig_labels: List[str] = []

        for _, row in top_df.iterrows():
            row_params = _extract_params_from_row(row.to_dict())
            d, n, lab = _latest_signal_for_params(
                adapter=adapter,
                base_spec=base_spec,
                symbols=symbols,
                index=common_index,
                bank=bank,
                bars_close=bars_close,
                bars_high=bars_high,
                bars_low=bars_low,
                bars_vol=bars_vol,
                params=row_params,
            )
            sig_dates.append(d)
            sig_nums.append(n)
            sig_labels.append(lab)

        top_df["signal_date"] = sig_dates
        top_df["signal_today"] = sig_nums
        top_df["signal_label"] = sig_labels


        best_row = top_df.iloc[0].to_dict()
        best_params = {k: best_row[k] for k in best_row.keys() if k not in ("pnl", "traded_notional", "cagr", "n_fills", "error")}
        best = TrialResult(
            params=best_params,
            pnl=float(best_row["pnl"]),
            traded_notional=float(best_row.get("traded_notional", 0.0)),
            efficiency=float(best_row.get("efficiency", float("-inf"))),
            n_fills=int(best_row.get("n_fills", 0)),
            cagr=float(best_row["cagr"]),
            error=str(best_row.get("error")) if best_row.get("error") is not None else None,
        )
        best_spec = _apply_params_to_spec(base_spec, best.params)
        return best, top_df, best_params, best_spec, ranked_df, _timing

    ranked_df = df_valid.sort_values(["pnl", "cagr"], ascending=[False, False]).reset_index(drop=True)
    df_valid = df_valid.sort_values(["pnl", "cagr"], ascending=[False, False])
    top_df = ranked_df.head(int(cfg.top_k)).reset_index(drop=True)
    # ---- add last-bar ("today") signal columns to leaderboard ----
    sig_dates: List[pd.Timestamp] = []
    sig_nums: List[float] = []
    sig_labels: List[str] = []

    for _, row in top_df.iterrows():
        row_params = _extract_params_from_row(row.to_dict())
        d, n, lab = _latest_signal_for_params(
            adapter=adapter,
            base_spec=base_spec,
            symbols=symbols,
            index=common_index,
            bank=bank,
            bars_close=bars_close,
            bars_high=bars_high,
            bars_low=bars_low,
            bars_vol=bars_vol,
            params=row_params,
        )
        sig_dates.append(d)
        sig_nums.append(n)
        sig_labels.append(lab)

    top_df["signal_date"] = sig_dates
    top_df["signal_today"] = sig_nums
    top_df["signal_label"] = sig_labels

    

    best_row = top_df.iloc[0].to_dict()
    best_params = {k: best_row[k] for k in best_row.keys() if k not in ("pnl", "traded_notional", "cagr", "n_fills", "error")}
    best = TrialResult(
        params=best_params,
        pnl=float(best_row["pnl"]),
        traded_notional=float(best_row["traded_notional"]),
        efficiency=float(best_row["efficiency"]),
        n_fills=int(best_row["n_fills"]),
        cagr=float(best_row["cagr"]),
        error=None,
    )
    best_spec = _apply_params_to_spec(base_spec, best.params)
    return best, top_df, best_params, best_spec, ranked_df, _timing

from typing import Dict, List, Tuple, Optional, Any
import pandas as pd
def eval_stats_only_for_spec_arrays(
    spec: EngineSpec,
) -> Dict[str, Any]:
    """
    Runs one fast stats-only backtest for a spec and returns a flat dict.
    Uses same alignment logic + PortfolioEngine.run_stats_only_arrays.
    """
    # Load + align
    md_full = _load_market_data_from_spec(spec.data)
    symbols = list(spec.data.symbols)
    md = _align_marketdata_inner(md_full, symbols)

    if len(symbols) != 1:
        raise ValueError("stats_only eval currently supports single-symbol (same as optimize fast path).")

    sym = symbols[0]
    idx = md.bars[sym].index
    if len(idx) < 2:
        raise ValueError("Not enough bars after alignment.")
    
    # Apply data window from spec.data.start/end (the same semantics as optimization)
    idx2 = _slice_index(idx, spec.data.start, spec.data.end)
    if idx2 is None or len(idx2) < 2:
        raise ValueError("Window too small after slicing.")
    b = md.bars[sym].loc[idx2[0]:idx2[-1]]

    open_px  = b["Open"].to_numpy(dtype=np.float64, copy=False)
    close_px = b["Close"].to_numpy(dtype=np.float64, copy=False)
    bars_high = {sym: b["High"].to_numpy(dtype=np.float64, copy=False)}
    bars_low = {sym: b["Low"].to_numpy(dtype=np.float64, copy=False)}
    bars_vol = {sym: b[spec.portfolio.volume_col].to_numpy(dtype=np.float64, copy=False)} if spec.portfolio.use_participation_cap or spec.portfolio.use_volume_gate else {}

    # NEW: volume/ADV support (so volume gate & participation cap work)
    need_volume = bool(spec.portfolio.use_participation_cap or spec.portfolio.use_volume_gate)

    vol_px = None
    adv_cap_px = None
    adv_gate_px = None

    if need_volume:
        vcol = spec.portfolio.volume_col
        if vcol not in b.columns:
            raise KeyError(f"Missing volume column '{vcol}' in bars for {sym}. Available: {list(b.columns)}")
        vol_px = b[vcol].to_numpy(dtype=np.float64, copy=False)

        # Build ADV arrays only for the windows actually needed
        adv_windows = []
        if spec.portfolio.use_participation_cap and str(spec.portfolio.participation_basis) == "adv":
            adv_windows.append(int(spec.portfolio.adv_window))
        if spec.portfolio.use_volume_gate and str(spec.portfolio.volume_gate_kind) == "min_ratio_adv":
            adv_windows.append(int(spec.portfolio.volume_gate_adv_window))
        adv_windows = sorted(set(w for w in adv_windows if w >= 1))

        adv_by_w = {}
        for w in adv_windows:
            v = vol_px
            c = np.cumsum(np.insert(v, 0, 0.0))
            adv = np.empty_like(v)
            idx = np.arange(v.size)
            lo = np.maximum(0, idx - (w - 1))
            den = (idx - lo + 1).astype(np.float64)
            adv[:] = (c[idx + 1] - c[lo]) / den
            adv_by_w[w] = adv

        if spec.portfolio.use_participation_cap and str(spec.portfolio.participation_basis) == "adv":
            adv_cap_px = adv_by_w[int(spec.portfolio.adv_window)]

        if spec.portfolio.use_volume_gate and str(spec.portfolio.volume_gate_kind) == "min_ratio_adv":
            adv_gate_px = adv_by_w[int(spec.portfolio.volume_gate_adv_window)]


    # Build signals using strategy adapter + SMA bank (minimal compute: only needed windows)
    sk = spec.strategy.kind.lower()
    if sk not in STRATEGY_ADAPTERS:
        raise ValueError(f"No adapter for strategy kind '{sk}'")

    adapter = STRATEGY_ADAPTERS[sk]

    # Build SMA bank only for required windows of THIS spec (not full domain)
    # We can reuse your sma builder
    def _sma_bank_numpy(close: np.ndarray, windows: List[int]) -> Dict[str, np.ndarray]:
        n = close.size
        csum = np.cumsum(np.insert(close.astype(np.float64, copy=False), 0, 0.0))
        out: Dict[str, np.ndarray] = {}
        for w0 in windows:
            w = int(w0)
            sma = np.full(n, np.nan, dtype=np.float64)
            if 0 < w <= n:
                sma[w - 1 :] = (csum[w:] - csum[:-w]) / w
            out[f"sma_{w}"] = sma
        return out

    # Determine required SMA windows from current spec params only
    if sk == "sma_price":
        w = int(spec.strategy.params.get("window", 50))
        req = [w]
    elif sk == "ma_cross":
        f = int(spec.strategy.params.get("fast_window", 15))
        s = int(spec.strategy.params.get("slow_window", 50))
        req = [f, s]
    elif sk == "rsi":
        w = int(spec.strategy.params.get("rsi_window", 14))
        os= int(spec.strategy.params.get("rsi_oversold", 30))
        ob= int(spec.strategy.params.get("rsi_overbought", 70))
        req = [w,ob,os]
    elif sk == "macd":
        f = int(spec.strategy.params.get("macd_fast_window", 12))
        s = int(spec.strategy.params.get("macd_slow_window", 26))
        sig = int(spec.strategy.params.get("macd_signal_window", 9))
        req = [f, s, sig]
    elif sk == "bollinger":
        w = int(spec.strategy.params.get("bb_window", 20))
        k = float(spec.strategy.params.get("bb_k", 2.0))
        req = [w]

    bars_close = {sym: close_px}
    req = adapter.required_bank(spec, active_params=[])  # spec-only: no domain
    bank = build_bank(bars_close, bars_high, bars_low, bars_vol, req)

    sf = adapter.make_signals_from_bank(
        symbols=[sym],
        index=b.index,   # already sliced window
        bank=bank,
        bars_close=bars_close,
        bars_high=bars_high,
        bars_low=bars_low,
        bars_vol=bars_vol,
        params={},       # no overrides, spec.params only
        base_spec=spec,
    )
    sig = sf.signals[sym].to_numpy(dtype=np.float64, copy=False)

    
    # Portfolio stats only
    port = PortfolioEngine(spec.portfolio)
    stats = port.run_stats_only_arrays(open_px=open_px, close_px=close_px, sig=sig, vol_px=vol_px, adv_cap_px=adv_cap_px, adv_gate_px=adv_gate_px)
    E0 = float(spec.portfolio.initial_cash)
    pnl = float(stats.pnl)

    # prefer final_equity if available, else infer
    ET = float(getattr(stats, "final_equity", E0 + pnl))

    n = int(close_px.size)
    ppy = float(getattr(spec, "periods_per_year", 252))

    if n <= 1 or E0 <= 0 or ET <= 0:
        cagr = np.nan
    else:
        cagr = (ET / E0) ** (ppy / n) - 1.0

    # Flatten into dict for UI table
    return {
        "pnl": float(stats.pnl),
        "traded_notional": float(stats.traded_notional),
        "n_fills": int(stats.n_fills),
        "cagr": float(cagr) if np.isfinite(cagr) else np.nan,
        # keep your efficiency logic if stats has volume_inv; else use traded_notional
        "efficiency": 1.0 if float(getattr(stats, "volume_inv", stats.traded_notional)) <= 0 else float(stats.pnl) / float(getattr(stats, "volume_inv", stats.traded_notional)),
        # optional extras if available
        "final_equity": float(getattr(stats, "final_equity", np.nan)),
        "max_drawdown": float(getattr(stats, "max_drawdown", np.nan)),
    }

from datetime import timedelta

def batch_optimize_by_period(
    base_spec: EngineSpec,
    active_params: List[ParamDef],
    cfg: OptimizeConfig,
    periods: Dict[str, Tuple[str, str]],
    selected_period_labels: List[str],
    objective: str = "pnl",
) -> pd.DataFrame:

    rows = []

    for label in selected_period_labels:
        p_start, p_end = periods[label]

        per_spec = replace(
            base_spec,
            data=replace(base_spec.data, start=str(p_start), end=str(p_end)),
        )

        best, top_df, best_params, best_spec, ranked_df, _bt_timing = run_optimization(
            base_spec=per_spec,
            active_params=active_params,
            cfg=cfg,
        )

        # ---- stats-only evaluation (fast) ----
        stats = eval_stats_only_for_spec_arrays(best_spec)
        score = stats.get(objective, np.nan)

        # ✅ CREATE row FIRST
        row = {
            "period": label,
            "start": p_start,
            "end": p_end,
            "objective": objective,
            "objective_value": float(score) if score is not None else np.nan,
        }

        # record best params (flatten)
        for k, v in best_params.items():
            row[f"param.{k}"] = v

        # record stats-only (flatten)
        for k, v in stats.items():
            row[f"stat.{k}"] = v

        # ---- FULL run ONLY for best spec (fills -> trade ledger/perf) ----
        try:
            best_bundle = BacktestEngine(best_spec).run()

            trades_df = best_bundle.report.tables.get("trades", pd.DataFrame())
            ledger = best_bundle.report.tables.get("trade_ledger", pd.DataFrame())
            tperf  = best_bundle.report.tables.get("trade_performance", pd.DataFrame())

            row["best.trades"] = int(len(trades_df))
            row["best.ledger_trades"] = int(len(ledger))

            if (tperf is not None) and (not tperf.empty) and ("Value" in tperf.columns) and ("Win Rate" in tperf.index):
                row["best.win_rate"] = float(tperf.loc["Win Rate", "Value"])
            else:
                row["best.win_rate"] = np.nan

        except Exception as e:
            # Don't kill the batch if full run fails; keep audit trail
            row["best.trades"] = np.nan
            row["best.ledger_trades"] = np.nan
            row["best.win_rate"] = np.nan
            row["best.full_run_error"] = f"{type(e).__name__}: {e}"

        rows.append(row)

    return pd.DataFrame(rows)



    

def build_spec_from_result_row(base_spec: EngineSpec, row: Any) -> EngineSpec:
    """
    Accepts either:
      - optimizer-ranked rows with raw keys: "strategy.sma_window", "portfolio.cooldown_bars", ...
      - batch rows with prefixed keys: "param.strategy.sma_window", "param.portfolio.cooldown_bars", ...

    Ignores:
      - metrics: pnl, cagr, n_fills, traded_notional, efficiency, error
      - batch/meta columns: period, start, end, objective, objective_value
      - stat.* columns
    """
    if isinstance(row, pd.Series):
        d = row.to_dict()
    else:
        d = dict(row)

    metric_cols = {"pnl", "traded_notional", "cagr", "n_fills", "efficiency", "error"}
    meta_cols = {"period", "start", "end", "objective", "objective_value"}

    params: Dict[str, Any] = {}

    for k, v in d.items():
        if k in metric_cols or k in meta_cols:
            continue
        if isinstance(k, str) and k.startswith("stat."):
            continue

        # batch format: param.<real_key>
        if isinstance(k, str) and k.startswith("param."):
            real_k = k[len("param."):]
            params[real_k] = v
            continue

        # normal optimization format: real key already
        if isinstance(k, str) and (k.startswith("strategy.") or k.startswith("portfolio.") or k == "data.window"):
            params[k] = v

    return _apply_params_to_spec(base_spec, params)

def _eval_one_trial_slow_pandas(*args, **kwargs) -> TrialResult:
    """Fallback path for multi-symbol trials.

    Not implemented in this project snapshot. If you hit this, either:
      - restrict optimization to a single symbol, or
      - implement a multi-symbol portfolio simulation + stats extraction.
    """
    return TrialResult(params=kwargs.get("params", {}), pnl=float("-inf"), traded_notional=0.0, efficiency=float("-inf"), n_fills=0,cagr=float("-inf"), error="multi-symbol optimize not implemented")

# ============================================================
# Trial evaluation
# ============================================================
def _eval_one_trial(
    base_spec: EngineSpec,
    md: MarketData,
    common_index: pd.DatetimeIndex,
    bank: Dict[str, Dict[str, np.ndarray]],
    bars_open: Dict[str, np.ndarray],
    bars_high: Dict[str, np.ndarray],
    bars_low: Dict[str, np.ndarray],
    bars_close: Dict[str, np.ndarray],
    bars_vol: Dict[str, np.ndarray],
    adv_by_window_np: Dict[int, Dict[str, np.ndarray]],
    adapter: StrategyAdapter,
    params: Dict[str, Any],
    precomputed_port: Optional[PortfolioEngine] = None,
) -> TrialResult:
    try:
        symbols = list(base_spec.data.symbols)
        if not symbols:
            return TrialResult(
                params=params,
                pnl=float("-inf"),
                traded_notional=0.0,
                efficiency=float("-inf"),
                n_fills=0,
                cagr=float("-inf"),
                error="no symbols for trial",
            )

        idx_pos: Optional[np.ndarray] = None
        if "data.window" in params and params["data.window"] is not None:
            start, end = params["data.window"]
            idx_slice = common_index
            if start is not None:
                idx_slice = idx_slice[idx_slice >= pd.to_datetime(start)]
            if end is not None:
                idx_slice = idx_slice[idx_slice <= pd.to_datetime(end)]
            if len(idx_slice) < 2:
                return TrialResult(
                    params=params,
                    pnl=float("-inf"),
                    traded_notional=0.0,
                    efficiency=float("-inf"),
                    n_fills=0,
                    cagr=float("-inf"),
                    error="window too small",
                )
            idx_pos = common_index.get_indexer_for(idx_slice)

        trial_index = common_index if idx_pos is None else common_index[idx_pos]
        if len(trial_index) < 2:
            return TrialResult(
                params=params,
                pnl=float("-inf"),
                traded_notional=0.0,
                efficiency=float("-inf"),
                n_fills=0,
                cagr=float("-inf"),
                error="window too small",
            )

        need_volume = bool(base_spec.portfolio.use_participation_cap or base_spec.portfolio.use_volume_gate)
        need_volume_for_strategy = base_spec.strategy.kind.lower() in ("obv", "stoch_vwap")
        need_volume = bool(need_volume or need_volume_for_strategy)

        # Use pre-hoisted engine when no portfolio params are being varied;
        # otherwise apply per-trial portfolio overrides.
        if precomputed_port is not None:
            port = precomputed_port
            port_cfg = port.cfg
        else:
            port_cfg = _apply_portfolio_params(base_spec.portfolio, params)
            port = PortfolioEngine(port_cfg)

        bars_open_trial: Dict[str, np.ndarray] = {}
        bars_close_trial: Dict[str, np.ndarray] = {}
        bars_high_trial: Dict[str, np.ndarray] = {}
        bars_low_trial: Dict[str, np.ndarray] = {}
        bars_vol_trial: Dict[str, np.ndarray] = {}
        bank_trial: Dict[str, Dict[str, np.ndarray]] = {}
        adv_cap_by_symbol: Dict[str, Optional[np.ndarray]] = {}
        adv_gate_by_symbol: Dict[str, Optional[np.ndarray]] = {}

        for sym in symbols:
            open_px = bars_open[sym] if idx_pos is None else bars_open[sym][idx_pos]
            close_px = bars_close[sym] if idx_pos is None else bars_close[sym][idx_pos]
            high_px = bars_high[sym] if idx_pos is None else bars_high[sym][idx_pos]
            low_px = bars_low[sym] if idx_pos is None else bars_low[sym][idx_pos]

            bars_open_trial[sym] = open_px
            bars_close_trial[sym] = close_px
            bars_high_trial[sym] = high_px
            bars_low_trial[sym] = low_px

            if need_volume:
                bars_vol_trial[sym] = bars_vol[sym] if idx_pos is None else bars_vol[sym][idx_pos]

            sym_bank = bank[sym]
            if idx_pos is not None:
                sym_bank = {k: v[idx_pos] for k, v in sym_bank.items()}
            bank_trial[sym] = sym_bank

            adv_cap_px = None
            adv_gate_px = None
            if port_cfg.use_participation_cap and str(port_cfg.participation_basis) == "adv":
                w = int(port_cfg.adv_window)
                a = adv_by_window_np.get(w, {}).get(sym)
                if a is None:
                    return TrialResult(
                        params=params,
                        pnl=float("-inf"),
                        traded_notional=0.0,
                        efficiency=float("-inf"),
                        n_fills=0,
                        cagr=float("-inf"),
                        error=f"missing ADV cap series for window={w}",
                    )
                adv_cap_px = a if idx_pos is None else a[idx_pos]

            if port_cfg.use_volume_gate and str(port_cfg.volume_gate_kind) == "min_ratio_adv":
                w = int(port_cfg.volume_gate_adv_window)
                a = adv_by_window_np.get(w, {}).get(sym)
                if a is None:
                    return TrialResult(
                        params=params,
                        pnl=float("-inf"),
                        traded_notional=0.0,
                        efficiency=float("-inf"),
                        n_fills=0,
                        cagr=float("-inf"),
                        error=f"missing ADV gate series for window={w}",
                    )
                adv_gate_px = a if idx_pos is None else a[idx_pos]

            adv_cap_by_symbol[sym] = adv_cap_px
            adv_gate_by_symbol[sym] = adv_gate_px

        # Fast path: bypass DataFrame allocation in make_signals_from_bank.
        # make_signal_arrays_fast() returns Dict[str, np.ndarray] with {-1,0,1} arrays directly.
        _fast_fn = getattr(adapter, "make_signal_arrays_fast", None)
        if _fast_fn is not None:
            _sig_arrays = _fast_fn(
                symbols=symbols,
                bank=bank_trial,
                bars_close=bars_close_trial,
                bars_high=bars_high_trial,
                bars_low=bars_low_trial,
                bars_vol=bars_vol_trial if need_volume else {},
                params=params,
                base_spec=base_spec,
            )
            # Normalize: NaN → 0, then clamp to {-1, 0, 1}
            _sig_norm: Dict[str, np.ndarray] = {}
            for _s, _a in _sig_arrays.items():
                _a = np.nan_to_num(np.asarray(_a, dtype=np.float64), nan=0.0, posinf=1.0, neginf=-1.0)
                _sig_norm[_s] = np.where(_a > 0.0, 1.0, np.where(_a < 0.0, -1.0, 0.0))
        else:
            sf = adapter.make_signals_from_bank(
                symbols=symbols,
                index=trial_index,
                bank=bank_trial,
                bars_close=bars_close_trial,
                bars_high=bars_high_trial,
                bars_low=bars_low_trial,
                bars_vol=bars_vol_trial if need_volume else {},
                params=params,
                base_spec=base_spec,
            )
            _sig_norm = {}
            for _s in symbols:
                _c = sf.signals[_s].to_numpy(dtype=np.float64, copy=False)
                if sf.validity is not None and _s in sf.validity.columns:
                    _v = sf.validity[_s].to_numpy(dtype=bool, copy=False)
                    _c = np.where(_v, _c, 0.0)
                _c = np.nan_to_num(_c, nan=0.0, posinf=1.0, neginf=-1.0)
                _sig_norm[_s] = np.where(_c > 0.0, 1.0, np.where(_c < 0.0, -1.0, 0.0))

        pnl_total = 0.0
        traded_total = 0.0
        n_fills_total = 0
        final_equity_total = 0.0
        volume_inv_total = 0.0

        for sym in symbols:
            sig_col = _sig_norm[sym]

            stats = port.run_stats_only_arrays(
                open_px=bars_open_trial[sym],
                close_px=bars_close_trial[sym],
                sig=sig_col,
                vol_px=bars_vol_trial.get(sym) if need_volume else None,
                adv_cap_px=adv_cap_by_symbol.get(sym),
                adv_gate_px=adv_gate_by_symbol.get(sym),
            )

            pnl_sym = float(stats.pnl)
            traded_sym = float(stats.traded_notional)
            n_fills_sym = int(stats.n_fills)
            final_eq_sym = float(getattr(stats, "final_equity", float(port_cfg.initial_cash) + pnl_sym))

            volume_inv_sym = (
                getattr(stats, "volume_inv", None)
                or getattr(stats, "volume_invested", None)
                or getattr(stats, "volumeinv", None)
            )
            if volume_inv_sym is None:
                volume_inv_sym = traded_sym

            pnl_total += pnl_sym
            traded_total += traded_sym
            n_fills_total += n_fills_sym
            final_equity_total += final_eq_sym
            volume_inv_total += float(volume_inv_sym)

        n = int(len(trial_index))
        ppy = float(getattr(base_spec, "periods_per_year", 252))
        initial_total = float(port_cfg.initial_cash) * float(len(symbols))

        if n <= 1 or initial_total <= 0 or final_equity_total <= 0:
            cagr = float("-inf")
        else:
            cagr = float((final_equity_total / initial_total) ** (ppy / n) - 1.0)

        eff = 1.0 if volume_inv_total <= 0 else float(pnl_total / volume_inv_total)

        return TrialResult(
            params=params,
            pnl=float(pnl_total),
            traded_notional=float(traded_total),
            efficiency=float(eff),
            n_fills=int(n_fills_total),
            error=None,
            cagr=float(cagr),
        )

    except Exception as e:
        return TrialResult(
            params=params,
            pnl=float("-inf"),
            traded_notional=0.0,
            efficiency=float("-inf"),
            n_fills=0,
            cagr=float("-inf"),
            error=str(e),
        )




# ============================================================
# Candidate generation
# ============================================================

def _expand_domain(p: ParamDef) -> List[Any]:
    if p.kind in ("choice", "date_window"):
        return list(p.domain)
    if p.kind == "int":
        lo, hi, step = p.domain
        return list(range(int(lo), int(hi) + 1, int(step)))
    if p.kind == "float":
        lo, hi, step = map(float, p.domain)
        n = int(math.floor((hi - lo) / step)) + 1
        return [lo + i * step for i in range(n)]
    raise ValueError(f"Unknown ParamDef kind: {p.kind}")


def _trial_params_key(params: Dict[str, Any]) -> str:
    """Stable key for trial-level memoization/dedup."""
    return json.dumps(params, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)

def _iter_grid(active: List[ParamDef]) -> Iterable[Dict[str, Any]]:
    grids = [_expand_domain(p) for p in active]
    keys = [p.key for p in active]
    casts = [p.cast for p in active]
    for combo in itertools.product(*grids):
        out: Dict[str, Any] = {}
        for k, v, c in zip(keys, combo, casts):
            out[k] = c(v)
        yield out

def _iter_random(active: List[ParamDef], n_trials: int, seed: int) -> Iterable[Dict[str, Any]]:
    rng = random.Random(seed)
    grids = {p.key: _expand_domain(p) for p in active}
    casts = {p.key: p.cast for p in active}
    keys = [p.key for p in active]

    # Random search without replacement whenever possible to avoid wasted
    # repeated evaluations on the same parameter set.
    total_unique = 1
    for k in keys:
        total_unique *= max(1, len(grids[k]))
    target = min(int(n_trials), int(total_unique))

    seen: set[str] = set()
    attempts = 0
    max_attempts = max(target * 10, target + 100)

    while len(seen) < target and attempts < max_attempts:
        attempts += 1
        out: Dict[str, Any] = {}
        for k in keys:
            out[k] = casts[k](rng.choice(grids[k]))
        trial_key = _trial_params_key(out)
        if trial_key in seen:
            continue
        seen.add(trial_key)
        yield out


def _domain_values_int(active: List[ParamDef], key: str) -> List[int]:
    p = next((x for x in active if x.key == key and x.enabled), None)
    if p is None:
        return []

    # Accept manual-list domains too (UI converts int->choice)
    if p.kind not in ("int", "choice"):
        return []

    vals = _expand_domain(p)
    out = []
    for v in vals:
        try:
            out.append(int(v))
        except Exception:
            pass
    return sorted(set(out))



# ============================================================
# Apply params to spec/configs (for returning best_spec)
# ============================================================

def _apply_params_to_spec(base_spec: EngineSpec, params: Dict[str, Any]) -> EngineSpec:
    # DataConfig: apply date window if optimized
    data_cfg = base_spec.data
    if "data.window" in params and params["data.window"] is not None:
        start, end = params["data.window"]
        data_cfg = replace(data_cfg, start=str(start), end=str(end))

    # StrategyConfig: apply strategy params
    strat_cfg = base_spec.strategy
    sp = dict(strat_cfg.params or {})
    if "strategy.sma_fast_window" in params:
        sp["fast_window"] = int(params["strategy.sma_fast_window"])
    if "strategy.sma_slow_window" in params:
        sp["slow_window"] = int(params["strategy.sma_slow_window"])
    if "strategy.sma_window" in params:
        sp["window"] = int(params["strategy.sma_window"])
    if "strategy.bb_window" in params:
        sp["bb_window"] = int(params["strategy.bb_window"])
    if "strategy.bb_k" in params:
        sp["bb_k"] = float(params["strategy.bb_k"])
    if "strategy.rsi_window" in params:
        sp["rsi_window"] = int(params["strategy.rsi_window"])
    if "strategy.rsi_oversold" in params:
        sp["rsi_oversold"] = float(params["strategy.rsi_oversold"])
    if "strategy.rsi_overbought" in params:
        sp["rsi_overbought"] = float(params["strategy.rsi_overbought"])
    if "strategy.macd_fast_window" in params:
        sp["macd_fast_window"] = int(params["strategy.macd_fast_window"])
    if "strategy.macd_slow_window" in params:   
        sp["macd_slow_window"] = int(params["strategy.macd_slow_window"])
    if "strategy.macd_signal_window" in params:
        sp["macd_signal_window"] = int(params["strategy.macd_signal_window"])
        # --- OBV ---
    if "strategy.obv_span" in params:
        sp["obv_span"] = int(params["strategy.obv_span"])

    # --- Stoch+VWAP ---
    if "strategy.k_window" in params:
        sp["k_window"] = int(params["strategy.k_window"])
    if "strategy.d_window" in params:
        sp["d_window"] = int(params["strategy.d_window"])
    if "strategy.smooth_k" in params:
        sp["smooth_k"] = int(params["strategy.smooth_k"])
    if "strategy.vwap_window" in params:
        sp["vwap_window"] = int(params["strategy.vwap_window"])

    # --- Ichimoku ---
    if "strategy.tenkan" in params:
        sp["tenkan"] = int(params["strategy.tenkan"])
    if "strategy.kijun" in params:
        sp["kijun"] = int(params["strategy.kijun"])
    if "strategy.senkou_b" in params:
        sp["senkou_b"] = int(params["strategy.senkou_b"])
    if "strategy.shift" in params:
        sp["shift"] = int(params["strategy.shift"])

    if "strategy.allow_short" in params:
        sp["allow_short"] = bool(params["strategy.allow_short"])
    if "strategy.nan_policy" in params:
        sp["nan_policy"] = str(params["strategy.nan_policy"])
    strat_cfg = replace(strat_cfg, params=sp)


    # PortfolioConfig
    port_cfg = _apply_portfolio_params(base_spec.portfolio, params)

    return replace(base_spec, data=data_cfg, strategy=strat_cfg, portfolio=port_cfg)


def _apply_portfolio_params(port_cfg: PortfolioConfig, params: Dict[str, Any]) -> PortfolioConfig:
    upd = port_cfg
    if "portfolio.cooldown_bars" in params:
        upd = replace(upd, cooldown_bars=int(params["portfolio.cooldown_bars"]))
    if "portfolio.buy_pct_cash" in params:
        upd = replace(upd, buy_pct_cash=float(params["portfolio.buy_pct_cash"]))
    if "portfolio.sell_pct_shares" in params:
        upd = replace(upd, sell_pct_shares=float(params["portfolio.sell_pct_shares"]))
    return upd


# ============================================================
# Data loading + alignment + slicing
# ============================================================

def _jsonify_cfg_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonify_cfg_value(v) for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple, set)):
        return [_jsonify_cfg_value(v) for v in value]
    return str(value) if hasattr(value, "__fspath__") else value


def _market_data_cache_key(cfg: DataConfig) -> str:
    payload = {
        "source": str(cfg.source),
        "symbols": list(cfg.symbols),
        "timezone": str(cfg.timezone),
        "interval": str(cfg.interval),
        "start": cfg.start,
        "end": cfg.end,
        "periods": cfg.periods,
        "freq": str(cfg.freq),
        "include_windows": _jsonify_cfg_value(cfg.include_windows),
        "exclude_windows": _jsonify_cfg_value(cfg.exclude_windows),
        "bmce_paths": _jsonify_cfg_value(cfg.bmce_paths),
        "yf_period": str(cfg.yf_period),
        "yf_interval": str(cfg.yf_interval),
        "yf_auto_adjust": bool(cfg.yf_auto_adjust),
        "synthetic": _jsonify_cfg_value(cfg.synthetic),
        "parquet_paths": _jsonify_cfg_value(cfg.parquet_paths),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_market_data_from_spec(cfg: DataConfig) -> MarketData:
    cache_key = _market_data_cache_key(cfg)
    cached = _MARKET_DATA_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if cfg.source == "bmce":
        if cfg.bmce_paths is None:
            raise ValueError("BMCE source selected but bmce_paths is None.")
        ds = BMCEDataSource(timezone=cfg.timezone)
        md = ds.load(
            symbols=cfg.symbols,
            start=cfg.start,
            end=cfg.end,
            interval=cfg.interval,
            paths=cfg.bmce_paths,
        )
        _MARKET_DATA_CACHE[cache_key] = md
        return md

    if cfg.source == "yfinance":
        ds = YahooFinanceDataSource(timezone=cfg.timezone)
        md = ds.load(
            symbols=cfg.symbols,
            start=cfg.start,
            end=cfg.end,
            interval=cfg.interval,
            auto_adjust=cfg.yf_auto_adjust,
            progress=False,
        )
        _MARKET_DATA_CACHE[cache_key] = md
        return md

    if cfg.source == "synthetic":
        syn = dict(cfg.synthetic or {})
        bars: Dict[str, pd.DataFrame] = {}
        for sym in cfg.symbols:
            bars[sym] = make_synthetic_ohlcv(
                symbol=sym,
                start=cfg.start,
                end=cfg.end,
                periods=cfg.periods,
                freq=str(syn.get("freq", cfg.freq or "B")),
                seed=int(syn.get("seed", 42)),
                start_price=float(syn.get("start_price", 100.0)),
                mu=float(syn.get("mu", 0.0003)),
                sigma=float(syn.get("sigma", 0.01)),
                vol_min=int(syn.get("vol_min", 100_000)),
                vol_max=int(syn.get("vol_max", 300_000)),
            )
        md = MarketData(
            bars=bars,
            source="synthetic",
            timezone="UTC",
            interval=str(syn.get("freq", cfg.freq or "B")),
            meta={
                "symbols": list(cfg.symbols),
                "start": cfg.start,
                "end": cfg.end,
                "periods": cfg.periods,
                "synthetic": syn,
            },
        )
        _MARKET_DATA_CACHE[cache_key] = md
        return md

    raise ValueError(f"Unknown data source: {cfg.source}")


def _align_marketdata_inner(md: MarketData, symbols: List[str]) -> MarketData:
    # inner intersection index across symbols (robust multi-asset)
    idx = md.bars[symbols[0]].index
    for s in symbols[1:]:
        idx = idx.intersection(md.bars[s].index)
    idx = idx.sort_values()

    bars_aligned: Dict[str, pd.DataFrame] = {}
    for s in symbols:
        bars_aligned[s] = md.bars[s].reindex(idx)

    return MarketData(
        bars=bars_aligned,
        source=md.source,
        timezone=md.timezone,
        interval=md.interval,
        meta=dict(md.meta),
    )


def _slice_marketdata(md: MarketData, symbols: List[str], index: pd.DatetimeIndex) -> MarketData:
    """Slice MarketData to a given DatetimeIndex.

    Optimization hot loop calls this only when you optimize data.window.
    Prefer a cheap .loc[start:end] slice when possible; fall back to reindex
    only if the slice doesn't exactly match the requested index.
    """
    bars: Dict[str, pd.DataFrame] = {}

    if len(index) == 0:
        for s in symbols:
            bars[s] = md.bars[s].iloc[0:0].reindex(index)
        return MarketData(
            bars=bars,
            source=md.source,
            timezone=md.timezone,
            interval=md.interval,
            meta=dict(md.meta),
        )

    start = index[0]
    end = index[-1]

    for s in symbols:
        df = md.bars[s]
        df_span = df.loc[start:end]
        # If df_span already has the exact index, keep it; else reindex
        if df_span.index.equals(index):
            bars[s] = df_span
        else:
            bars[s] = df.reindex(index)

    return MarketData(
        bars=bars,
        source=md.source,
        timezone=md.timezone,
        interval=md.interval,
        meta=dict(md.meta),
    )

def _slice_index(index: pd.DatetimeIndex, start: Optional[str], end: Optional[str]) -> Optional[pd.DatetimeIndex]:
    if start is None and end is None:
        return index
    tz = index.tz
    s = pd.Timestamp(start, tz=tz) if start is not None else None
    e = pd.Timestamp(end, tz=tz) if end is not None else None
    out = index
    if s is not None:
        out = out[out >= s]
    if e is not None:
        out = out[out <= e]
    return out if len(out) > 0 else None
