# ChatGPT Runtime Snapshot

Generated: 2026-02-19T10:39:30.4845502+00:00
Repo: C:\Users\taha\Downloads\backtester_final

## Git
```text
main
HEAD: (repository has no commits yet)

```

## Top-Level Tree
```text
.cache
.venv
.vscode
core
docs
infra
node_modules
original backtester
quant-backtesting-frontend
scripts
services
tests
tools
.dockerignore
DATA IAM - Copie.xlsx
equity_all_data.xlsx
mc.exe
package-lock.json
package.json
README.md
requirements-dev.txt
run.json
```

## Key Function Map
```text
core\quant_core\engine.py:293:def build_strategy(kind: str, params: Dict[str, Any]):
core\quant_core\engine.py:688:class BacktestEngine:
core\quant_core\optimize.py:1175:def default_param_catalog(strategy_kind: str) -> Dict[str, ParamDef]:
core\quant_core\pipeline.py:14:def run_pipeline(spec_json: Dict[str, Any]) -> Dict[str, Any]:
services\api\app\routers\runs.py:80:def create_run(payload: RunCreateRequest, db: Session = Depends(get_db)):
services\api\app\routers\runs.py:157:def start_run(run_id: UUID, db: Session = Depends(get_db)):
services\worker\tasks\execute_run.py:352:def _persist_pipeline_output(
services\worker\tasks\execute_run.py:527:def execute_run(run_id: str) -> dict:
```

## Key Files (First 220 Lines Each)

### core/quant_core/pipeline.py
```text
# core/quant_core/pipeline.py
from __future__ import annotations
from dataclasses import replace
from typing import Any, Dict, Tuple
import pandas as pd
from .engine import BacktestEngine, DataConfig, IndicatorsConfig, StrategyConfig, EngineSpec
from .optimize import OptimizeConfig, ParamDef, default_param_catalog, run_optimization
from .portfolio import CostModel, PortfolioConfig
from .run_spec import build_run_spec

from .plots import plot_price_indicators_trades_line


def run_pipeline(spec_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Canonical pipeline entry point.

    Returns a dict with:
      - leaderboard: list[dict]
      - plot_artifacts: Dict[str, Any]
      - strategy_results: Dict[str, Any] (per-strategy trade_ledger + plot_artifacts + best params)
      - artifacts: Dict[str, Any] (run metadata, best params by kind)
    """
    data_json = spec_json.get("data", {})
    portfolio_json = spec_json.get("portfolio", {})
    strategy_json = spec_json.get("strategy", {})
    indicators_json = spec_json.get("indicators", {})
    optimization_json = spec_json.get("optimization", {})

    def _norm_windows(v: Any) -> list[Tuple[str, str]] | None:
        if not v:
            return None
        return [(str(a), str(b)) for a, b in v]

    include_windows = _norm_windows(data_json.get("include_windows"))
    exclude_windows = _norm_windows(data_json.get("exclude_windows"))
    symbols = list(spec_json.get("symbols") or data_json.get("symbols") or [])

    data_cfg = DataConfig(
        source=str(spec_json.get("source_key") or data_json.get("source") or "yfinance"),
        symbols=symbols,
        timezone=str(data_json.get("timezone", "GMT")),
        interval=str(data_json.get("interval", "1d")),
        start=data_json.get("start"),
        end=data_json.get("end"),
        periods=(int(data_json["periods"]) if data_json.get("periods") is not None else None),
        freq=str(data_json.get("freq", "B")),
        include_windows=include_windows,
        exclude_windows=exclude_windows,
        bmce_paths=data_json.get("bmce_paths"),
        yf_period=str(data_json.get("yf_period", "max")),
        yf_interval=str(data_json.get("yf_interval", "1d")),
        yf_auto_adjust=bool(data_json.get("yf_auto_adjust", False)),
        synthetic=dict(data_json.get("synthetic") or {}),
        parquet_paths=data_json.get("parquet_paths"),
    )

    indicators_cfg = IndicatorsConfig(
        specs=indicators_json.get("specs"),
        cache_dir=indicators_json.get("cache_dir", ".cache/features"),
        enable_disk_cache=bool(indicators_json.get("enable_disk_cache", True)),
        enable_memory_cache=bool(indicators_json.get("enable_memory_cache", True)),
        engine_version=str(indicators_json.get("engine_version", "v1")),
    )

    strategy_cfg = StrategyConfig(
        kind=str(strategy_json.get("kind", "buy_hold")),
        params=dict(strategy_json.get("params") or {}),
    )

    cost_model_cfg = CostModel(
        brokerage_bps=float(portfolio_json.get("cost_model", {}).get("brokerage_bps", 0.2)),
        comm_bourse_bps=float(portfolio_json.get("cost_model", {}).get("comm_bourse_bps", 0.1)),
        reg_liv_bps=float(portfolio_json.get("cost_model", {}).get("reg_liv_bps", 0.0)),
        slippage_bps=float(portfolio_json.get("cost_model", {}).get("slippage_bps", 0.0)),
        tva_rate=float(portfolio_json.get("cost_model", {}).get("tva_rate", 0.000300000142168438)),
    )

    portfolio_cfg = PortfolioConfig(
        allow_short=bool(portfolio_json.get("allow_short", True)),
        initial_cash=float(portfolio_json.get("initial_cash", 100000.0)),
        rebalance_policy=str(portfolio_json.get("rebalance_policy", "on_change")),
        sizing_mode=str(portfolio_json.get("sizing_mode", "target_weight")),
        buy_pct_cash=float(portfolio_json.get("buy_pct_cash", 1.0)),
        sell_pct_shares=float(portfolio_json.get("sell_pct_shares", 1.0)),
        cooldown_bars=int(portfolio_json.get("cooldown_bars", 0)),
        min_return_before_sell=float(portfolio_json.get("min_return_before_sell", 0.0)),
        use_volume_gate=bool(portfolio_json.get("volume_gate", {}).get("enabled", portfolio_json.get("use_volume_gate", False))),
        volume_gate_kind=str(portfolio_json.get("volume_gate", {}).get("kind", portfolio_json.get("volume_gate_kind", "min_ratio_adv"))),
        min_volume_abs=float(portfolio_json.get("volume_gate", {}).get("min_volume_abs", portfolio_json.get("min_volume_abs", 0.0))),
        min_volume_ratio_adv=float(portfolio_json.get("volume_gate", {}).get("min_volume_ratio_adv", portfolio_json.get("min_volume_ratio_adv", 0.1))),
        volume_gate_adv_window=int(portfolio_json.get("volume_gate", {}).get("adv_window", portfolio_json.get("volume_gate_adv_window", 20))),
        use_participation_cap=bool(portfolio_json.get("participation_cap", {}).get("enabled", portfolio_json.get("use_participation_cap", False))),
        participation_rate=float(portfolio_json.get("participation_cap", {}).get("rate", portfolio_json.get("participation_rate", 0.05))),
        participation_basis=str(portfolio_json.get("participation_cap", {}).get("basis", portfolio_json.get("participation_basis", "adv"))),
        adv_window=int(portfolio_json.get("participation_cap", {}).get("adv_window", portfolio_json.get("adv_window", 20))),
        cost_model=cost_model_cfg,
    )

    engine_spec = EngineSpec(
        data=data_cfg,
        indicators=indicators_cfg,
        strategy=strategy_cfg,
        portfolio=portfolio_cfg,
        periods_per_year=int(spec_json.get("periods_per_year", 252)),
        rf_annual=float(spec_json.get("rf_annual", 0.0)),
        include_windows=include_windows,
        exclude_windows=exclude_windows,
    )

    run_spec = spec_json if "optimization" in spec_json and "portfolio" in spec_json and "data" in spec_json else build_run_spec(
        source_key=str(spec_json.get("source_key", data_cfg.source)),
        symbols=symbols,
        start=data_cfg.start,
        end=data_cfg.end,
        include_windows=include_windows,
        exclude_windows=exclude_windows,
        interval=data_cfg.interval,
        yf_period=data_cfg.yf_period,
        yf_interval=data_cfg.yf_interval,
        yf_auto_adjust=data_cfg.yf_auto_adjust,
        rank_metric=str(optimization_json.get("rank_metric", "sharpe")),
        lb_opt_kinds=list(optimization_json.get("kinds") or []),
        opt_method=str(optimization_json.get("method", "random")),
        n_trials=int(optimization_json.get("n_trials", 0)),
        top_k=int(optimization_json.get("top_k", 1)),
        allow_short=portfolio_cfg.allow_short,
        initial_cash=portfolio_cfg.initial_cash,
        cooldown_bars=portfolio_cfg.cooldown_bars,
        min_return_before_sell=portfolio_cfg.min_return_before_sell,
        cost_model=portfolio_json.get("cost_model", {}),
        volume_gate=portfolio_json.get("volume_gate", {}),
        participation_cap=portfolio_json.get("participation_cap", {}),
        domains_by_kind=dict(optimization_json.get("domains_by_kind") or {}),
        app_version=str(spec_json.get("app_version", "v1")),
    )

    def _params_from_catalog(kind: str) -> list[ParamDef]:
        catalog = default_param_catalog(kind)
        domains_by_kind = dict(optimization_json.get("domains_by_kind") or {})
        custom = domains_by_kind.get(kind)

        if not custom:
            return [p for p in catalog.values() if p.enabled]

        if isinstance(custom, dict):
            keys = []
            for key, dom in custom.items():
                if key in catalog:
                    p = catalog[key]
                    catalog[key] = ParamDef(key=p.key, kind=p.kind, domain=dom, cast=p.cast, enabled=True)
                    keys.append(key)
            return [catalog[k] for k in keys if k in catalog]

        if isinstance(custom, list):
            out: list[ParamDef] = []
            for item in custom:
                if isinstance(item, str):
                    p = catalog.get(item)
                    if p is not None and p.enabled:
                        out.append(p)
                elif isinstance(item, dict):
                    k = item.get("key")
                    if not k:
                        continue
                    base = catalog.get(k)
                    if base is None:
                        continue
                    out.append(
                        ParamDef(
                            key=str(k),
                            kind=str(item.get("kind", base.kind)),
                            domain=item.get("domain", base.domain),
                            cast=base.cast,
                            enabled=bool(item.get("enabled", True)),
                        )
                    )
            return [p for p in out if p.enabled]

        return [p for p in catalog.values() if p.enabled]

    def _best_params_from_spec(spec: EngineSpec) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in dict(spec.strategy.params or {}).items():
            out[f"strategy.{key}"] = value
        for key in (
            "cooldown_bars",
            "buy_pct_cash",
            "sell_pct_shares",
            "min_return_before_sell",
        ):
            out[f"portfolio.{key}"] = getattr(spec.portfolio, key)
        return out

    plots_json = dict(spec_json.get("plots") or {})

    def _normalize_record_frame(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        for c in out.columns:
            if pd.api.types.is_datetime64_any_dtype(out[c]) or pd.api.types.is_datetime64tz_dtype(out[c]):
                out[c] = pd.to_datetime(out[c], utc=True, errors="coerce").dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                out[c] = out[c].str.replace(".000000Z", "Z", regex=False)
        out = out.where(pd.notna(out), None)
        return out

    def _df_to_records(df: pd.DataFrame | None, *, ensure_timestamp: bool = True) -> list[dict[str, Any]]:
        if df is None:
            return []

        out = df.copy()
        if ensure_timestamp and "timestamp" not in out.columns:
            if "signal_date" in out.columns:
                out["timestamp"] = out["signal_date"]
            else:
                out["timestamp"] = out.index

        if ensure_timestamp:
            out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
            if out["timestamp"].isna().all() and len(out) > 0:
                out["timestamp"] = pd.Timestamp.now(tz="UTC")
```

### core/quant_core/engine.py
```text
from __future__ import annotations

from .data import YahooFinanceDataSource   # your class
from .data import MarketData
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple, Callable, Literal, Union
import numpy as np
import pandas as pd
from pathlib import Path
import copy
# ---- Project modules (adapt import paths if you have a package folder) ----
from .data import BMCEDataSource, ParquetDataSource, make_synthetic_ohlcv
from .indicators import IndicatorEngine, FeatureSpec, FeaturesData
from .strategy import (
    BaseStrategy,
    MovingAverageCrossStrategy,
    MovingAverageCrossParams,
    SignalFrame,
    PriceAboveSMAStrategy,
    PriceAboveSMAParams,
    RSIStrategy,
    RSIParams,
    MACDStrategy,
    MACDParams,
    BollingerBandsStrategy,
    BollingerParams,
    BuyHoldStrategy,
    BuyHoldParams,
    OBVStrategy, OBVParams,
    StochVWAPStrategy, StochVWAPParams,
    IchimokuStrategy, IchimokuParams,
)
from .portfolio import PortfolioEngine, PortfolioConfig, PortfolioResult
from .results import ResultsAnalyzer, BacktestReport
from .strategy import default_plot_indicators  # add import


DataSourceKind = Literal["bmce", "yfinance", "synthetic","parquet"]
StrategyKind = Literal["ma_cross","sma_price", "rsi","macd","bollinger", "buy_hold","obv","stoch_vwap","ichimoku"]  # add more as you implement them'"]
def slice_df_by_start_end(df: pd.DataFrame, start: Optional[str], end: Optional[str]) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index, errors="coerce")
    out = out.sort_index()
    if start:
        out = out.loc[pd.to_datetime(start):]
    if end:
        out = out.loc[:pd.to_datetime(end)]
    return out


def slice_marketdata(md: MarketData, start: Optional[str], end: Optional[str]) -> MarketData:
    if md is None:
        return md
    new_bars = {sym: slice_df_by_start_end(df, start, end) for sym, df in md.bars.items()}
    return MarketData(bars=new_bars, source=md.source, timezone=md.timezone, interval=md.interval)


def slice_features(feats: FeaturesData, md: MarketData) -> FeaturesData:
    # align feats strictly to md index per symbol
    new = {}
    for sym, bars in md.bars.items():
        f = feats.features.get(sym, pd.DataFrame(index=bars.index))
        new[sym] = f.reindex(bars.index)
    return FeaturesData(features=new, source=feats.source, timezone=feats.timezone, interval=feats.interval, meta=feats.meta)

# -----------------------------
# Engine Spec Objects
# -----------------------------
@dataclass(frozen=True)
class DataConfig:
    source: DataSourceKind
    symbols: List[str]

    timezone: str = "GMT"
    interval: str = "1d"
    start: Optional[str] = None
    end: Optional[str] = None
    periods: Optional[int] = None
    freq: str = "B"
        # Period filters (multi-window)
    include_windows: Optional[List[tuple[str, str]]] = None
    exclude_windows: Optional[List[tuple[str, str]]] = None


    # BMCE inputs:
    # - for single symbol: str/Path
    # - for multi symbols: dict {symbol: str/Path}
    bmce_paths: Optional[Union[str, Path, Dict[str, Union[str, Path]]]] = None

    parquet_paths: Optional[Union[str, Path, Dict[str, Union[str, Path]]]] = None


    # yfinance inputs
    yf_period: str = "max"
    yf_interval: str = "1d"
    yf_auto_adjust: bool = False

    # synthetic inputs
    synthetic: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IndicatorsConfig:
    """
    You can supply:
      - specs directly, OR
      - a builder that returns specs, OR
      - leave empty and let the engine infer specs from strategy kind (only for known strategies)
    """
    specs: Optional[List[FeatureSpec]] = None
    spec_builder: Optional[Callable[[], List[FeatureSpec]]] = None
    
    cache_dir: Optional[str] = ".cache/features"
    enable_disk_cache: bool = True
    enable_memory_cache: bool = True
    engine_version: str = "v1"


@dataclass(frozen=True)
class StrategyConfig:
    kind: StrategyKind
    params: Dict[str, Any] = field(default_factory=dict)

BenchmarkSource = Literal["yahoo"]

@dataclass(frozen=True)
class BenchmarkConfig:
    enabled: bool = False
    symbol: str = "SPY"
    source: BenchmarkSource = "yahoo"
    start: Optional[str] = None
    end: Optional[str] = None
    interval: str = "1d"
    auto_adjust: bool = False


@dataclass(frozen=True)
class EngineSpec:
    data: DataConfig
    indicators: IndicatorsConfig
    strategy: StrategyConfig
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)
    benchmark: BenchmarkConfig = field(default_factory=BenchmarkConfig)
    plot_indicators: List[str] = field(default_factory=list)
    periods_per_year: int = 252
    rf_annual: float = 0.0
    # Period filters (multi-window)
    include_windows: Optional[List[tuple[str, str]]] = None
    exclude_windows: Optional[List[tuple[str, str]]] = None




@dataclass(frozen=True)
class BacktestBundle:
    md: MarketData
    feats: FeaturesData
    signals: SignalFrame
    portfolio_result: PortfolioResult
    report: BacktestReport
    meta: Dict[str, Any] = field(default_factory=dict)


def _apply_time_windows_to_df(
    df: Any,
    include_windows: Optional[List[tuple[str, str]]],
    exclude_windows: Optional[List[tuple[str, str]]],
):
    if df is None or len(df) == 0:
        return df

    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index, errors="coerce")
    out = out.sort_index()
    out = out[~out.index.isna()]

    idx = out.index
    idx_tz = getattr(idx, "tz", None)

    def _coerce_ts(x):
        ts = pd.to_datetime(x)
        if idx_tz is None:
            # index is tz-naive -> make boundary tz-naive
            if getattr(ts, "tzinfo", None) is not None:
                ts = ts.tz_convert(None)
            return ts
        else:
            # index is tz-aware -> make boundary tz-aware in same tz
            if getattr(ts, "tzinfo", None) is None:
                ts = ts.tz_localize(idx_tz)
            else:
                ts = ts.tz_convert(idx_tz)
            return ts

    # include mask
    if include_windows:
        m_inc = pd.Series(False, index=idx)
        for s, e in include_windows:
            s_dt = _coerce_ts(s)
            e_dt = _coerce_ts(e)
            m_inc |= (idx >= s_dt) & (idx <= e_dt)

    else:
        m_inc = pd.Series(True, index=idx)

    # exclude mask
    if exclude_windows:
        m_exc = pd.Series(False, index=idx)
        for s, e in exclude_windows:
            s_dt = pd.to_datetime(s)
            e_dt = pd.to_datetime(e)
            m_exc |= (idx >= s_dt) & (idx <= e_dt)
    else:
        m_exc = pd.Series(False, index=idx)

    final_mask = m_inc & (~m_exc)
```

### core/quant_core/strategy.py
```text
# strategy.py
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple
from abc import ABC, abstractmethod

import pandas as pd
import numpy as np

# Import your FeatureSpec from the indicator layer.
# (Keep strategy -> indicators dependency; indicators should NOT depend on strategy.)
from .indicators import FeatureSpec


# =============================================================================
# Protocols (duck-typing) to avoid tight coupling between layers
# =============================================================================

class MarketDataLike(Protocol):
    """
    Minimal interface expected from the data layer.
    """
    bars: Dict[str, pd.DataFrame]
    source: str
    timezone: str
    interval: str
    meta: Dict[str, Any]


class FeaturesDataLike(Protocol):
    """
    Minimal interface expected from the indicator layer.
    """
    features: Dict[str, pd.DataFrame]
    source: str
    timezone: str
    interval: str
    meta: Dict[str, Any]


# =============================================================================
# Strategy outputs (what Strategy layer returns downstream)
# =============================================================================

@dataclass
class SignalFrame:
    """
    Canonical output of a Strategy: "intent" at time t.

    signals:
        DataFrame indexed by timestamps, columns = symbols.
        Values represent desired exposure/intention at time t:
            - for long/flat strategies: {0, +1}
            - if allow_short: {-1, 0, +1}
        IMPORTANT: execution semantics (fill at t+1, costs, slippage) are NOT here.
        Those belong to portfolio/execution layers.

    validity:
        Optional DataFrame of same shape as signals, True where signal is valid
        (e.g., after warmup), False otherwise. Useful for debugging/reporting.

    meta:
        Strategy signature and any diagnostics.
    """
    signals: pd.DataFrame
    validity: Optional[pd.DataFrame] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def assert_well_formed(self, symbols: Sequence[str]) -> None:
        if not isinstance(self.signals.index, pd.DatetimeIndex):
            raise TypeError("SignalFrame.signals must be indexed by a DatetimeIndex")
        missing_cols = [s for s in symbols if s not in self.signals.columns]
        if missing_cols:
            raise ValueError(f"SignalFrame missing symbols: {missing_cols}")

        if self.validity is not None:
            if not self.validity.index.equals(self.signals.index):
                raise ValueError("SignalFrame.validity index must match signals index")
            if list(self.validity.columns) != list(self.signals.columns):
                raise ValueError("SignalFrame.validity columns must match signals columns")


# =============================================================================
# Strategy base class (contracts)
# =============================================================================

@dataclass(frozen=True)
class StrategySpec:
    """
    A stable, serializable description of a strategy configuration.
    Useful for logging, caching, and optimizer bookkeeping.
    """
    name: str
    params: Dict[str, Any]

    def signature(self) -> str:
        # Deterministic signature (stable key order)
        items = [(k, self.params[k]) for k in sorted(self.params)]
        return f"{self.name}|" + "|".join([f"{k}={v}" for k, v in items])


class BaseStrategy(ABC):
    """
    Strategy layer responsibility:
        - declare which features are required (FeatureSpec list)
        - generate "signals/intent" from MarketData + FeaturesData

    Strategy layer DOES NOT:
        - size positions in shares/weights
        - apply transaction costs/slippage
        - implement fill semantics (t vs t+1)
        - maintain trade ledger
    """

    @property
    @abstractmethod
    def spec(self) -> StrategySpec:
        """Stable description of the strategy (name + params)."""
        raise NotImplementedError

    @abstractmethod
    def required_features(self) -> List[FeatureSpec]:
        """
        Return the list of FeatureSpec needed by this strategy.

        This allows the engine (or research runner) to compute indicators
        upstream in a consistent way.
        """
        raise NotImplementedError

    @abstractmethod
    def generate_signals(
        self,
        market_data: MarketDataLike,
        features_data: FeaturesDataLike,
        symbols: Optional[Sequence[str]] = None,
    ) -> SignalFrame:
        """
        Vectorized/batch implementation (research-first).
        Returns desired exposures at time t.
        """
        raise NotImplementedError

    # Optional extension point for future event-driven parity
    def on_bar(
        self,
        t: pd.Timestamp,
        symbol: str,
        bar_t: pd.Series,
        features_t: pd.Series,
        state: Optional[Dict[str, Any]] = None,
    ) -> float:
        """
        Optional incremental interface (not required for your current research-first engine).
        Returns desired exposure at time t for one symbol.
        """
        raise NotImplementedError("on_bar not implemented for this strategy.")

# --- Buy & Hold -------------------------------------------------

@dataclass(frozen=True)
class BuyHoldParams:
    buy_pct_cash: float = 1.0
    nan_policy: str = "flat"  # "flat" or "nan"


class BuyHoldStrategy(BaseStrategy):
    def __init__(self, params: BuyHoldParams) -> None:
        self.params = params

    @property
    def spec(self) -> StrategySpec:
        return StrategySpec(name="BuyHoldStrategy", params=asdict(self.params))

    def required_features(self) -> List[FeatureSpec]:
        # no indicators needed
        return []

    def generate_signals(
        self,
        market_data: MarketDataLike,
        features_data: FeaturesDataLike,
        symbols: Optional[Sequence[str]] = None,
    ) -> SignalFrame:

        symbols = list(symbols) if symbols is not None else list(market_data.bars.keys())

        # build a common index (union) consistent with your other strategies
        all_indexes = [market_data.bars[s].index for s in symbols]
        common_index = all_indexes[0]
        for idx in all_indexes[1:]:
            common_index = common_index.union(idx)
        common_index = common_index.sort_values()

        sig_df = pd.DataFrame(index=common_index, columns=symbols, dtype="float64")
        valid_df = pd.DataFrame(index=common_index, columns=symbols, dtype="bool")

        buy_pct = float(self.params.buy_pct_cash)

        for s in symbols:
            bars = market_data.bars[s].reindex(common_index)
            close = pd.to_numeric(bars["Close"], errors="coerce")

            valid = close.notna()
            out = pd.Series(0.0, index=common_index, dtype=float)

            # buy once on first valid bar and hold
            if valid.any():
                first_idx = valid.idxmax()  # first True
                out.loc[first_idx:] = 1.0 * buy_pct

            if self.params.nan_policy == "flat":
                out = out.where(valid, 0.0)
            else:
                out = out.where(valid, np.nan)

            sig_df[s] = out
            valid_df[s] = valid
```

### core/quant_core/optimize.py
```text
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Callable
import itertools
import math
import random

import numpy as np
import pandas as pd

from .data import BMCEDataSource, YahooFinanceDataSource, MarketData, make_synthetic_ohlcv
from .strategy import SignalFrame
from .indicators import IndicatorEngine, FeatureSpec, FeaturesData
from .engine import EngineSpec, DataConfig, StrategyConfig, estimate_warmup_bars_from_params, BacktestEngine
from .portfolio import PortfolioEngine, PortfolioConfig


# ============================================================
# Public dataclasses
# ============================================================

@dataclass(frozen=True)
class OptimizeConfig:
    method: str = "random"        # "random" | "grid"
    seed: int = 42
    n_trials: int = 300           # for random
    top_k: int = 30

    # indicator engine cache options (optimization usually wants memory cache only)
    feature_cache_dir: str = ".cache/features"
    enable_disk_cache: bool = False
    enable_memory_cache: bool = True


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
    """
    signal_date = pd.Timestamp(index[-1])

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

    sym0 = symbols[0]
```

### core/quant_core/plots.py
```text
# core/quant_core/plots.py
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def make_equity_curve_plot(equity: pd.Series, *, title: str = "Equity Curve") -> go.Figure:
    """
    Pure plot function:
      - input: equity series indexed by datetime
      - output: plotly Figure
    """
    if equity is None:
        equity = pd.Series(dtype=float)

    e = equity.copy()
    if not isinstance(e.index, pd.DatetimeIndex):
        e.index = pd.to_datetime(e.index, errors="coerce")
    e = e.sort_index()
    e = e[~e.index.isna()]
    e = pd.to_numeric(e, errors="coerce")

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=e.index,
            y=e.values,
            mode="lines",
            name="Equity",
        )
    )

    fig.update_layout(
        title=title,
        template="plotly_white",
        font=dict(family="Arial", size=12),
        margin=dict(l=40, r=20, t=60, b=40),
        legend=dict(orientation="h"),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="Equity")
    return fig


def make_price_indicators_trades_plot(
    bars: pd.DataFrame,
    indicators: Optional[pd.DataFrame],
    fills: Optional[pd.DataFrame],
    *,
    strategy_params: Optional[dict] = None,
    indicator_cols: Optional[list[str]] = None,
) -> go.Figure:
    """
    MVP price panel:
      - bars: OHLCV dataframe indexed by datetime
      - indicators: optional indicator dataframe indexed by datetime
      - fills: trades/fills dataframe (your existing plotting uses `trades`)
    """
    return plot_price_indicators_trades_line(
        bars=bars,
        strategy_params=strategy_params,
        indicators=indicators,
        trades=fills,
        indicator_cols=indicator_cols,
        port_cfg=None,  # keep pure: no portfolio config needed for plotting
    )


# ======================================================================
# MOVED FROM app.py (pure Plotly, no Streamlit, no DB)
# Keep the name to minimize changes across your codebase.
# ======================================================================
def plot_price_indicators_trades_line(
    bars: pd.DataFrame,
    strategy_params: dict | None = None,
    indicators: pd.DataFrame | None = None,
    trades: pd.DataFrame | None = None,
    indicator_cols: list[str] | None = None,
    *,
    port_cfg: Any | None = None,
    rsi_low: float = 30.0,
    rsi_high: float = 70.0,
) -> go.Figure:
    """
    Price (row 1), RSI and/or MACD panels (middle rows), Volume (last row).

    - RSI is plotted in its own panel with threshold lines + shaded regions.
    - MACD panel plots EMA_fast, EMA_slow + histogram (EMA_fast-EMA_slow) as bars
      with per-bar green/red intensity (stronger color as magnitude increases).
    """

    df = bars.copy().sort_index()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    ind = None
    if indicators is not None and not indicators.empty:
        ind = indicators.copy()
        if not isinstance(ind.index, pd.DatetimeIndex):
            ind.index = pd.to_datetime(ind.index)
        ind = ind.reindex(df.index)

        if indicator_cols is not None:
            keep = [c for c in indicator_cols if c in ind.columns]

            # Always keep any "known indicator families" if present, even if UI didn't request them.
            prefixes = ("sma_", "ema_", "rsi_", "macd_", "std_", "vwap_", "stoch_", "ichimoku_")
            keep += [c for c in ind.columns if c.startswith(prefixes)]
            keep += [c for c in ind.columns if c == "obv" or c.startswith("obv_ema_")]

            keep = sorted(set(keep))
            if keep:
                ind = ind[keep]

    def _maybe_add_bollinger_overlay():
        nonlocal fig, df, ind, indicator_cols

        if ind is None or ind.empty:
            return

        cols = list(ind.columns)

        # --- HARD GATE: only plot BB if explicitly requested ---
        is_bollinger_strategy = bool(strategy_params) and (
            ("bb_k" in (strategy_params or {})) or ("bb_window" in (strategy_params or {}))
        )

        has_std_col = any(c.startswith("std_") for c in cols)
        has_std_requested = bool(indicator_cols) and any(c.startswith("std_") for c in (indicator_cols or []))

        if not (is_bollinger_strategy or has_std_col or has_std_requested):
            return

        w = None

        if indicator_cols:
            for c in indicator_cols:
                if c.startswith("std_"):
                    try:
                        w = int(c.split("_", 1)[1])
                        break
                    except Exception:
                        pass

        if w is None:
            for c in cols:
                if c.startswith("std_"):
                    try:
                        w = int(c.split("_", 1)[1])
                        break
                    except Exception:
                        pass

        if w is None and is_bollinger_strategy:
            for c in cols:
                if c.startswith("sma_"):
                    try:
                        w = int(c.split("_", 1)[1])
                        break
                    except Exception:
                        pass

        if w is None:
            return

        k = float((strategy_params or {}).get("bb_k", 2.0))
        col_mid = f"sma_{w}"
        col_std = f"std_{w}"

        if col_mid not in ind.columns:
            return

        mid = pd.to_numeric(ind[col_mid], errors="coerce")

        if col_std in ind.columns:
            std = pd.to_numeric(ind[col_std], errors="coerce")
        else:
            if not is_bollinger_strategy:
                return
            std = pd.to_numeric(df["Close"], errors="coerce").rolling(int(w), min_periods=int(w)).std()

        upper = mid + k * std
        lower = mid - k * std

        fig.add_trace(go.Scatter(x=df.index, y=mid, mode="lines", name=f"BB mid (SMA{w})", line=dict(width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=upper, mode="lines", name=f"BB upper (k={k})", line=dict(width=1, dash="dash")), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=lower, mode="lines", name=f"BB lower (k={k})", line=dict(width=1, dash="dash")), row=1, col=1)

        fig.add_trace(
            go.Scatter(x=df.index, y=upper, mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"),
            row=1, col=1
        )
        fig.add_trace(
            go.Scatter(x=df.index, y=lower, mode="lines", fill="tonexty", line=dict(width=0), name="BB band", opacity=0.12, hoverinfo="skip"),
            row=1, col=1
        )

    # ----------------------------
    # Detect panels / overlays
    # ----------------------------
    rsi_col: str | None = None
    macd_base: str | None = None

    obv_col: str | None = None
    obv_ema_col: str | None = None

    stoch_k_col: str | None = None
    stoch_d_col: str | None = None
    vwap_col: str | None = None

    ich_tenkan_col: str | None = None
    ich_kijun_col: str | None = None
    ich_span_a_col: str | None = None
    ich_span_b_col: str | None = None
```

### services/worker/tasks/execute_run.py
```text
# services/worker/tasks/execute_run.py
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID, uuid4
from typing import Any
import copy
import traceback
import json
import hashlib
import pandas as pd
import time
from redis import Redis
from rq import get_current_job

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.worker.db import SessionLocal
from services.worker.config import settings
from services.worker.storage import s3_client, ensure_bucket

from core.quant_core.pipeline import run_pipeline


def _utcnow():
    return datetime.now(timezone.utc)


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()
def _rq_job_id() -> str | None:
    try:
        job = get_current_job()
        return job.id if job else None
    except Exception:
        return None

def _set_progress(
    job_id: str | None,
    *,
    stage: str,
    done: int,
    total: int,
    message: str = "",
) -> None:
    if not job_id:
        return
    try:
        job = get_current_job()
        if not job:
            return
        pct = 0 if total <= 0 else int(100 * done / total)
        job.meta["progress"] = {
            "stage": stage,
            "done": done,
            "total": total,
            "pct": pct,
            "message": message,
            "ts": _utcnow().isoformat(),
        }
        job.save_meta()
    except Exception:
        # Never break runs because progress reporting failed
        pass

def _redis_for_cancel() -> Redis:
    # Keep decode_responses=False consistent with your worker Redis usage
    return Redis.from_url(settings.REDIS_URL, decode_responses=False)


def _cancel_key(job_id: str) -> bytes:
    return f"rq:cancel:{job_id}".encode("utf-8")


def _cancel_requested(r: Redis, job_id: str) -> bool:
    try:
        return bool(r.get(_cancel_key(job_id)))
    except Exception:
        return False


class RunCanceled(Exception):
    pass


def _check_cancel(r: Redis, job_id: str | None) -> None:
    if not job_id:
        return
    if _cancel_requested(r, job_id):
        raise RunCanceled("Canceled by user")


def _json_default(value: Any) -> Any:
    # Plotly payloads can contain numpy/pandas scalar or ndarray values.
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _upload_json(object_key: str, payload: Any) -> tuple[int, str]:
    ensure_bucket()
    s3 = s3_client()
    content = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")
    s3.put_object(
        Bucket=settings.S3_BUCKET,
        Key=object_key,
        Body=content,
        ContentType="application/json",
    )
    return len(content), _sha256_bytes(content)


def _upload_csv(object_key: str, frame: pd.DataFrame) -> tuple[int, str]:
    ensure_bucket()
    s3 = s3_client()
    content = frame.to_csv(index=False).encode("utf-8")
    s3.put_object(
        Bucket=settings.S3_BUCKET,
        Key=object_key,
        Body=content,
        ContentType="text/csv",
    )
    return len(content), _sha256_bytes(content)


def _as_float(v, default: float | None = None) -> float | None:
    if v is None:
        return default
    try:
        out = float(v)
        if out != out:  # NaN
            return default
        return out
    except Exception:
        return default


def _as_int(v, default: int | None = None) -> int | None:
    if v is None:
        return default
    try:
        return int(v)
    except Exception:
        return default


def _as_dict(v) -> dict:
    if isinstance(v, dict):
        return dict(v)
    if isinstance(v, str):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def _to_pg_ts(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        s = v.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return v
    return v


def _build_dataset_object_key(filename: str, data_hash: str) -> str:
    return f"datasets/{data_hash}/{filename}"


def _materialize_dataset_file(*, filename: str, data_hash: str) -> Path:
    s3 = s3_client()
    object_key = _build_dataset_object_key(filename=filename, data_hash=data_hash)
    payload = s3.get_object(Bucket=settings.S3_BUCKET, Key=object_key)["Body"].read()

    suffix = Path(filename).suffix or ".bin"
    tmp = NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(payload)
    finally:
        tmp.close()

    return Path(tmp.name)


def _store_key_for_symbol(*, db: Session, symbol: str, timeframe: str = "1D") -> str:
    sym = str(symbol).strip().upper()
    row = db.execute(
        text("select object_key from market_data_store where symbol=:s and timeframe=:tf"),
        {"s": sym, "tf": timeframe},
    ).mappings().first()
    if not row:
        raise RuntimeError(f"Symbol not found in canonical store: {sym} ({timeframe})")
    return str(row["object_key"])


def _materialize_store_parquet(*, object_key: str) -> Path:
    s3 = s3_client()
    payload = s3.get_object(Bucket=settings.S3_BUCKET, Key=object_key)["Body"].read()
    if not payload:
        raise RuntimeError(f"Empty parquet object: {object_key}")

    tmp = NamedTemporaryFile(delete=False, suffix=".parquet")
    try:
        tmp.write(payload)
    finally:
```

### services/api/app/routers/runs.py
```text
# services/api/app/routers/runs.py
from __future__ import annotations

from datetime import datetime, timezone
import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Artifact, Fill, PositionLedger, Run, RunMetric, StrategyLeaderboard
from ..schemas.artifacts import ArtifactOut
from ..schemas.runs import (
    FillOut,
    PositionLedgerOut,
    RunCreateRequest,
    RunCreateResponse,
    RunListItemOut,
    RunMetricOut,
    StrategyLeaderboardOut,
)
from ..storage import presign_get





router = APIRouter(prefix="/runs", tags=["runs"])


def _parse_cursor(cursor: str | None) -> datetime | None:
    if cursor is None:
        return None

    raw = cursor.strip().replace(" ", "+")
    if not raw:
        return None

    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid cursor; expected ISO8601 timestamp") from exc

    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    return ts


def _infer_run_type(spec_json: dict) -> str:
    optimization = dict(spec_json.get("optimization") or {})
    n_trials = int(optimization.get("n_trials") or 0)
    kinds = list(optimization.get("kinds") or [])
    return "optimization" if n_trials > 0 or len(kinds) > 0 else "backtest"


def _compute_run_id(spec_hash: str, dataset_id: UUID | None) -> UUID:
    dataset_part = str(dataset_id) if dataset_id is not None else "none"
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{spec_hash}|{dataset_part}")


def _legacy_run_id_candidates(spec_hash: str) -> list[UUID]:
    out: list[UUID] = []
    try:
        out.append(UUID(spec_hash))
    except Exception:
        pass
    out.append(uuid.uuid5(uuid.NAMESPACE_URL, spec_hash))
    return out


def _artifact_strategy_kind(name: str) -> str:
    if not name:
        return ""
    return name.split(".", 1)[0].strip().lower()


@router.post("", response_model=RunCreateResponse)
def create_run(payload: RunCreateRequest, db: Session = Depends(get_db)):
    # Deterministic run_id is bound to (spec_hash, dataset_id), so changing
    # dataset does not accidentally collide with a previous run.
    run_id = _compute_run_id(payload.spec_hash, payload.dataset_id)

    run_type = _infer_run_type(payload.spec_json)

    # First check new identity. Then check legacy identities to preserve
    # backward-compatible idempotency for old runs created before this fix.
    candidate_ids = [run_id] + [c for c in _legacy_run_id_candidates(payload.spec_hash) if c != run_id]
    for candidate_id in candidate_ids:
        existing = db.get(Run, candidate_id)
        if existing is None:
            continue
        if str(existing.spec_hash) == str(payload.spec_hash) and existing.dataset_id == payload.dataset_id:
            return RunCreateResponse(
                run_id=existing.id,
                status=existing.status,
                run_type=str(existing.run_type or run_type),
            )

    run = Run(
        id=run_id,
        status="created",
        run_type=run_type,
        dataset_id=payload.dataset_id,
        spec_json=payload.spec_json,
        spec_hash=payload.spec_hash,
        engine_version="0.1.0",
        git_commit=None,
        error_message=None,
    )
    db.add(run)
    db.commit()

    return RunCreateResponse(run_id=run.id, status=run.status, run_type=run.run_type)


@router.get("", response_model=list[RunListItemOut])
def list_runs(
    status: str | None = Query(default=None),
    run_type: str | None = Query(default=None),
    dataset_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(Run)
    if status:
        q = q.filter(Run.status == status)
    if run_type:
        q = q.filter(Run.run_type == run_type)
    if dataset_id:
        q = q.filter(Run.dataset_id == dataset_id)

    rows = (
        q.order_by(Run.created_at.desc(), Run.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        {
            "run_id": row.id,
            "status": row.status,
            "run_type": row.run_type,
            "dataset_id": row.dataset_id,
            "created_at": row.created_at,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
        }
        for row in rows
    ]


@router.post("/{run_id}/start")
def start_run(run_id: UUID, db: Session = Depends(get_db)):
    from ..queue import get_queue

    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")

    # idempotency: if already queued/running/done, just return current status
    if run.status in {"queued", "running", "succeeded"}:
        return {"run_id": run.id, "status": run.status}

    if run.status == "failed":
        # allow restart (simple policy for MVP)
        run.error_message = None

    # set status to queued
    run.status = "queued"
    db.commit()

    q = get_queue()
    # enqueue by dotted path to avoid importing worker/quant_core in API process
    job = q.enqueue("services.worker.tasks.execute_run.execute_run", str(run.id))

    return {"run_id": run.id, "status": run.status, "job_id": job.id}


@router.get("/{run_id}")
def get_run(run_id: UUID, db: Session = Depends(get_db)):
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {
        "run_id": str(run.id),
        "status": run.status,
        "run_type": run.run_type,
        "dataset_id": run.dataset_id,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "error_message": run.error_message,
    }


@router.get("/{run_id}/metrics", response_model=list[RunMetricOut])
def list_run_metrics(run_id: UUID, db: Session = Depends(get_db)):
    rows = (
        db.query(RunMetric)
        .filter(RunMetric.run_id == run_id)
        .order_by(RunMetric.symbol.asc(), RunMetric.metric_name.asc())
        .all()
    )
    return [
        {
            "run_id": row.run_id,
            "symbol": row.symbol,
            "metric_name": row.metric_name,
            "metric_value": row.metric_value,
        }
        for row in rows
    ]


@router.get("/{run_id}/fills", response_model=list[FillOut])
def list_fills(
```

### services/api/app/models.py
```text
import uuid
from sqlalchemy import (
    Column, String, DateTime, ForeignKey, Text, BigInteger, Float, UniqueConstraint, Index, Integer
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func

from .db import Base



class Dataset(Base):
    __tablename__ = "dataset"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String, nullable=False)      # e.g. "BMCE_CSV", "Yahoo"
    symbol = Column(String, nullable=False)
    timeframe = Column(String, nullable=False)   # e.g. "1D"
    data_hash = Column(String, nullable=False)

    filename = Column(String, nullable=True)
    content_type = Column(String, nullable=True)
    object_key = Column(String, nullable=True)
    size_bytes = Column(BigInteger, nullable=False, default=0)
    meta_json = Column(JSONB, nullable=False, default=dict)

    start_ts = Column(DateTime(timezone=True), nullable=True)
    end_ts = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class MarketDataStore(Base):
    __tablename__ = "market_data_store"
    symbol = Column(String, primary_key=True)
    timeframe = Column(String, primary_key=True, default="1d")  # optional composite PK
    object_key = Column(String, nullable=False)
    start_ts = Column(DateTime(timezone=True))
    end_ts = Column(DateTime(timezone=True))
    row_count = Column(Integer)
    last_dataset_id = Column(ForeignKey("dataset.id"))
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Run(Base):
    __tablename__ = "run"

    id = Column(UUID(as_uuid=True), primary_key=True)  # we will set to spec_hash UUID
    status = Column(String, nullable=False)            # created/queued/running/succeeded/failed
    run_type = Column(String, nullable=False, default="backtest")  # backtest/optimization

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    engine_version = Column(String, nullable=True)
    git_commit = Column(String, nullable=True)

    dataset_id = Column(UUID(as_uuid=True), ForeignKey("dataset.id"), nullable=True)

    spec_json = Column(JSONB, nullable=False)
    spec_hash = Column(String, nullable=False)         # stable hash from your run_spec
    error_message = Column(Text, nullable=True)


class Artifact(Base):
    __tablename__ = "artifact"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False, index=True)
    symbol = Column(String, nullable=True, index=True)

    artifact_type = Column(String, nullable=False)   # plotly_json, table_csv, manifest_json, etc.
    name = Column(String, nullable=False)            # e.g. equity_curve, price_trades

    object_key = Column(String, nullable=False)      # path in MinIO bucket
    bucket = Column(String, nullable=False, default="quant-artifacts")

    content_type = Column(String, nullable=False)    # application/json, text/csv
    size_bytes = Column(BigInteger, nullable=False, default=0)
    sha256 = Column(String, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class RunMetric(Base):
    __tablename__ = "run_metric"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False)
    symbol = Column(String, nullable=False)
    metric_name = Column(String, nullable=False)
    metric_value = Column(Float, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "symbol", "metric_name", name="uq_run_metric_run_id_symbol_metric_name"),
    )


class Fill(Base):
    __tablename__ = "fill"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    symbol = Column(String, nullable=False)
    side = Column(String, nullable=False)
    qty = Column(Float, nullable=False)
    price = Column(Float, nullable=False)
    fees = Column(Float, nullable=False, default=0.0)
    notional = Column(Float, nullable=False)
    meta = Column(JSONB, nullable=True)

    __table_args__ = (
        Index("ix_fill_run_id_timestamp", "run_id", "timestamp"),
        Index("ix_fill_run_id_symbol_timestamp", "run_id", "symbol", "timestamp"),
    )


class PositionLedger(Base):
    __tablename__ = "position_ledger"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    symbol = Column(String, nullable=False)
    available_qty = Column(Float, nullable=False)
    cmp = Column(Float, nullable=False)
    position_value_cost = Column(Float, nullable=False)
    pnl_realise = Column(Float, nullable=False)
    pnl_latent = Column(Float, nullable=False)
    mark_price = Column(Float, nullable=False)

    __table_args__ = (
        Index("ix_position_ledger_run_id_timestamp", "run_id", "timestamp"),
        Index("ix_position_ledger_run_id_symbol_timestamp", "run_id", "symbol", "timestamp"),
    )


class StrategyLeaderboard(Base):
    __tablename__ = "strategy_leaderboard"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("run.id"), nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    strategy_kind = Column(String, nullable=False, index=True)
    rank = Column(Integer, nullable=False)

    pnl = Column(Float, nullable=True)
    cagr = Column(Float, nullable=True)
    efficiency = Column(Float, nullable=True)
    n_fills = Column(Integer, nullable=True)

    signal_label = Column(String, nullable=True)
    signal_today = Column(Float, nullable=True)
    signal_date = Column(DateTime(timezone=True), nullable=True)

    best_params_json = Column(JSONB, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "symbol", "strategy_kind", "rank", name="uq_strategy_leaderboard_run_symbol_kind_rank"),
        Index("ix_strategy_leaderboard_run_symbol", "run_id", "symbol"),
        Index("ix_strategy_leaderboard_symbol_created_at", "symbol", "created_at"),
    )
```

### services/api/app/schemas/runs.py
```text
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RunCreateRequest(BaseModel):
    spec_json: Dict[str, Any] = Field(..., description="Run specification JSON")
    spec_hash: str = Field(..., description="Stable hash of spec_json (from quant_core.run_spec)")
    dataset_id: Optional[UUID] = None


class RunCreateResponse(BaseModel):
    run_id: UUID
    status: str
    run_type: str


class RunListItemOut(BaseModel):
    run_id: UUID
    status: str
    run_type: str
    dataset_id: Optional[UUID]
    created_at: datetime
    started_at: Optional[datetime]
    finished_at: Optional[datetime]


class RunMetricOut(BaseModel):
    run_id: UUID
    symbol: str
    metric_name: str
    metric_value: float


class FillOut(BaseModel):
    id: UUID
    run_id: UUID
    timestamp: datetime
    symbol: str
    side: str
    qty: float
    price: float
    fees: float
    notional: float
    meta: Optional[Dict[str, Any]]


class PositionLedgerOut(BaseModel):
    id: UUID
    run_id: UUID
    timestamp: datetime
    symbol: str
    available_qty: float
    cmp: float
    position_value_cost: float
    pnl_realise: float
    pnl_latent: float
    mark_price: float


class StrategyLeaderboardOut(BaseModel):
    run_id: UUID
    symbol: str
    strategy_kind: str
    rank: int

    pnl: Optional[float]
    cagr: Optional[float]
    efficiency: Optional[float]
    n_fills: Optional[int]

    signal_label: Optional[str]
    signal_today: Optional[float]
    signal_date: Optional[datetime]

    best_params_json: Optional[Dict[str, Any]]
    plot_url: Optional[str]
    ledger_url: Optional[str]
```

### quant-backtesting-frontend/lib/api.ts
```text
import { z } from "zod"

const API_BASE = "/api"

export const RunStatusEnum = z.enum([
  "created",
  "queued",
  "running",
  "succeeded",
  "failed",
])
export type RunStatus = z.infer<typeof RunStatusEnum>

export const RunTypeEnum = z.enum(["backtest", "optimization"])
export type RunType = z.infer<typeof RunTypeEnum>

export const RunSchema = z.object({
  run_id: z.string(),
  status: RunStatusEnum,
  run_type: RunTypeEnum,
  dataset_id: z.string().nullable().optional(),
  spec_hash: z.string().optional(),
  created_at: z.string().optional(),
  started_at: z.string().nullable().optional(),
  finished_at: z.string().nullable().optional(),
  error_message: z.string().nullable().optional(),
})
export type Run = z.infer<typeof RunSchema>

export const RunCreateResponseSchema = z.object({
  run_id: z.string(),
  status: z.string(),
  run_type: z.string(),
})

export const RunStartResponseSchema = z.object({
  run_id: z.string(),
  status: z.string(),
  job_id: z.string().optional(),
})

const NumericLike = z.number().nullable().optional()

export const LeaderboardRowSchema = z.object({
  run_id: z.string().optional(),
  symbol: z.string(),
  strategy_kind: z.string(),
  rank: z.number().optional(),
  pnl: NumericLike,
  cagr: NumericLike,
  total_return: NumericLike,
  sharpe: NumericLike,
  max_drawdown: NumericLike,
  win_pct: NumericLike,
  n_fills: NumericLike,
  efficiency: NumericLike,
  signal_label: z.string().nullable().optional(),
  signal_today: NumericLike,
  signal_date: z.string().nullable().optional(),
  best_params_json: z.unknown().optional(),
  plot_url: z.string().url().nullable().optional(),
  ledger_url: z.string().url().nullable().optional(),
})
export type LeaderboardRow = z.infer<typeof LeaderboardRowSchema>

export const FillRowSchema = z.object({
  id: z.string().optional(),
  run_id: z.string().optional(),
  timestamp: z.string().nullable().optional(),
  symbol: z.string().nullable().optional(),
  side: z.string().nullable().optional(),
  qty: NumericLike,
  price: NumericLike,
  fees: NumericLike,
  notional: NumericLike,
  meta: z.record(z.unknown()).nullable().optional(),
})
export type FillRow = z.infer<typeof FillRowSchema>

export const PositionRowSchema = z.object({
  id: z.string().optional(),
  run_id: z.string().optional(),
  timestamp: z.string().nullable().optional(),
  symbol: z.string().nullable().optional(),
  available_qty: NumericLike,
  cmp: NumericLike,
  position_value_cost: NumericLike,
  pnl_realise: NumericLike,
  pnl_latent: NumericLike,
  mark_price: NumericLike,
})
export type PositionRow = z.infer<typeof PositionRowSchema>

export const MetricRowSchema = z.object({
  run_id: z.string().optional(),
  symbol: z.string().nullable().optional(),
  metric_name: z.string(),
  metric_value: z.union([z.number(), z.string()]),
})
export type MetricRow = z.infer<typeof MetricRowSchema>

export const ArtifactSchema = z.object({
  id: z.string(),
  run_id: z.string(),
  symbol: z.string().nullable().optional(),
  artifact_type: z.string(),
  name: z.string(),
  object_key: z.string(),
  bucket: z.string(),
  content_type: z.string(),
  size_bytes: z.number(),
  sha256: z.string(),
  created_at: z.string(),
  url: z.string().url(),
})
export type Artifact = z.infer<typeof ArtifactSchema>

export const PlotlyFigureSchema = z.object({
  data: z.array(z.record(z.unknown())).default([]),
  layout: z.record(z.unknown()).default({}),
  frames: z.array(z.record(z.unknown())).optional(),
})
export type PlotlyFigure = z.infer<typeof PlotlyFigureSchema>

export const STRATEGY_CATALOG = [
  { id: "sma_price", label: "SMA Price", description: "Simple Moving Average price crossover" },
  { id: "ma_cross", label: "MA Crossover", description: "Dual moving average crossover" },
  { id: "rsi", label: "RSI", description: "Relative Strength Index reversal/momentum" },
  { id: "macd", label: "MACD", description: "Moving Average Convergence Divergence" },
  { id: "bollinger", label: "Bollinger Bands", description: "Bollinger Bands mean reversion" },
  { id: "obv", label: "OBV", description: "On-Balance Volume trend" },
  { id: "stoch_vwap", label: "Stoch + VWAP", description: "Stochastic Oscillator with VWAP" },
  { id: "ichimoku", label: "Ichimoku", description: "Ichimoku Cloud trend system" },
] as const

export const PARAM_DEFAULTS: Record<string, string> = {
  "strategy.sma_window": "5,10,14,20,30,50,100,200",
  "strategy.sma_fast_window": "5,8,10,12,15,20,30",
  "strategy.sma_slow_window": "20,30,50,80,100,150,200",
  "strategy.rsi_window": "7,10,14,21,28",
  "strategy.rsi_oversold": "20,25,30,35",
  "strategy.rsi_overbought": "65,70,75,80",
  "strategy.macd_fast_window": "8,10,12,15,26",
  "strategy.macd_slow_window": "20,26,30,36,50",
  "strategy.macd_signal_window": "5,7,9,12,20",
  "strategy.bb_window": "10,14,20,30,50",
  "strategy.bb_k": "1,1.5,2,2.5,3",
  "strategy.obv_span": "5,10,14,20,30,50,100",
  "strategy.k_window": "7,10,14,21,28",
  "strategy.d_window": "2,3,5,7",
  "strategy.smooth_k": "1,2,3,5",
  "strategy.vwap_window": "10,14,20,30,50",
  "strategy.tenkan": "7,9,12",
  "strategy.kijun": "22,26,30",
  "strategy.senkou_b": "44,52,60",
  "strategy.shift": "22,26,30",
  "portfolio.cooldown_bars": "0,5,10,21,60,120",
  "portfolio.buy_pct_cash": "0.1,0.25,0.5,0.75,1.0",
  "portfolio.sell_pct_shares": "0.1,0.25,0.5,0.75,1.0",
  "portfolio.min_return_before_sell": "0.0,0.01,0.02,0.05,0.10",
}

class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`
  const headers = new Headers(options?.headers)
  const hasBody = options?.body !== undefined && options?.body !== null
  const isFormData = typeof FormData !== "undefined" && options?.body instanceof FormData
  if (hasBody && !isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }

  const res = await fetch(url, {
    ...options,
    headers,
    cache: options?.cache ?? "no-store",
  })

  if (!res.ok) {
    const text = await res.text().catch(() => "Unknown error")
    throw new ApiError(`${res.status}: ${text}`, res.status)
  }

  if (res.status === 204) {
    return undefined as T
  }
  return res.json() as Promise<T>
}

export async function createRun(body: {
  spec_hash: string
  dataset_id?: string | null
  spec_json: Record<string, unknown>
}) {
  const payload = await request<unknown>("/runs", {
    method: "POST",
    body: JSON.stringify(body),
  })
  return RunCreateResponseSchema.parse(payload)
}

export async function listRuns(params?: {
  status?: string
  run_type?: string
  dataset_id?: string
  limit?: number
  offset?: number
}) {
  const qs = new URLSearchParams()
  if (params?.status) qs.set("status", params.status)
  if (params?.run_type) qs.set("run_type", params.run_type)
```

### services/ui_streamlit/app.py
```text
from __future__ import annotations

from datetime import date
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import time
from typing import Any

import pandas as pd
import plotly.io as pio
import requests
import streamlit as st

from api_client import ApiClient, ApiClientError


DEFAULT_API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")
STRATEGY_KINDS = ["ma_cross", "sma_price", "rsi", "macd", "bollinger", "obv", "stoch_vwap", "ichimoku", "buy_hold"]
INDICATOR_CACHE_DIR = os.getenv("INDICATOR_CACHE_DIR", ".cache/features")
PERIOD_PRESETS: dict[str, tuple[str, str] | None] = {
    "Full History": None,
    "2008-2009 Crisis": ("2008-01-01", "2009-12-31"),
    "2011-2013 Volatility": ("2011-01-01", "2013-12-31"),
    "COVID 2020": ("2020-01-01", "2020-12-31"),
    "Recent (2023+)": ("2023-01-01", date.today().isoformat()),
}
OPTIMIZER_DOMAIN_DEFAULTS: dict[str, dict[str, str]] = {
    "ma_cross": {
        "strategy.sma_fast_window": "5,8,10,12,15,20,30",
        "strategy.sma_slow_window": "20,30,50,80,100,150,200",
    },
    "sma_price": {
        "strategy.sma_window": "10,20,30,50,100,200",
    },
    "rsi": {
        "strategy.rsi_window": "7,10,14,21,28",
        "strategy.rsi_oversold": "20,25,30,35",
        "strategy.rsi_overbought": "65,70,75,80",
    },
    "macd": {
        "strategy.macd_fast_window": "8,10,12,15,26",
        "strategy.macd_slow_window": "20,26,30,36,50",
        "strategy.macd_signal_window": "5,7,9,12,20",
    },
    "bollinger": {
        "strategy.bb_window": "10,14,20,30,50",
        "strategy.bb_k": "1,1.5,2,2.5,3",
    },
    "obv": {
        "strategy.obv_span": "5,10,14,20,30,50,100",
    },
    "stoch_vwap": {
        "strategy.k_window": "7,10,14,21,28",
        "strategy.d_window": "2,3,5,7",
        "strategy.smooth_k": "1,2,3,5",
        "strategy.vwap_window": "10,14,20,30,50",
    },
    "ichimoku": {
        "strategy.tenkan": "7,9,12",
        "strategy.kijun": "22,26,30",
        "strategy.senkou_b": "44,52,60",
        "strategy.shift": "22,26,30",
    },
}
PORTFOLIO_DOMAIN_DEFAULTS: dict[str, str] = {
    "portfolio.cooldown_bars": "0,5,10,21,60",
    "portfolio.buy_pct_cash": "0.25,0.5,0.75,1.0",
    "portfolio.sell_pct_shares": "0.25,0.5,0.75,1.0",
}


def compute_spec_hash(spec_json: dict[str, Any]) -> str:
    canonical = json.dumps(spec_json, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_symbols(raw: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for part in str(raw).split(","):
        symbol = part.strip().upper()
        if not symbol or symbol in seen:
            continue
        out.append(symbol)
        seen.add(symbol)
    return out


def parse_manual_values(raw: str) -> list[Any]:
    out: list[Any] = []
    for part in str(raw).split(","):
        token = part.strip()
        if not token:
            continue
        try:
            if "." in token:
                out.append(float(token))
            else:
                out.append(int(token))
        except Exception:
            continue
    return out


def to_iso_day(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return str(pd.to_datetime(value).date())
        except Exception:
            return None
    try:
        return str(pd.Timestamp(value).date())
    except Exception:
        return None


def collect_period_controls(key_prefix: str) -> dict[str, Any]:
    with st.expander("Period & Time Window", expanded=False):
        mode = st.radio(
            "Period mode",
            options=["Full History", "Preset", "Custom Dates"],
            horizontal=True,
            key=f"{key_prefix}_period_mode",
        )

        start: str | None = None
        end: str | None = None
        include_windows: list[tuple[str, str]] = []
        exclude_windows: list[tuple[str, str]] = []

        if mode == "Preset":
            preset = st.selectbox("Preset", options=list(PERIOD_PRESETS.keys()), index=1, key=f"{key_prefix}_period_preset")
            window = PERIOD_PRESETS.get(str(preset))
            if window is not None:
                start, end = window
        elif mode == "Custom Dates":
            c1, c2 = st.columns(2)
            default_start = pd.Timestamp("2020-01-01").date()
            default_end = date.today()
            start_input = c1.date_input("Start date", value=default_start, key=f"{key_prefix}_period_start")
            end_input = c2.date_input("End date", value=default_end, key=f"{key_prefix}_period_end")
            start = to_iso_day(start_input)
            end = to_iso_day(end_input)
            if start and end and start > end:
                st.warning("Start date must be before end date.")

        use_include = st.checkbox("Use include window (regime slice)", value=False, key=f"{key_prefix}_include_on")
        if use_include:
            c1, c2 = st.columns(2)
            inc_start = to_iso_day(c1.date_input("Include start", value=pd.Timestamp("2020-01-01").date(), key=f"{key_prefix}_inc_start"))
            inc_end = to_iso_day(c2.date_input("Include end", value=date.today(), key=f"{key_prefix}_inc_end"))
            if inc_start and inc_end and inc_start <= inc_end:
                include_windows = [(inc_start, inc_end)]

        use_exclude = st.checkbox("Use exclude window", value=False, key=f"{key_prefix}_exclude_on")
        if use_exclude:
            c1, c2 = st.columns(2)
            exc_start = to_iso_day(c1.date_input("Exclude start", value=pd.Timestamp("2021-01-01").date(), key=f"{key_prefix}_exc_start"))
            exc_end = to_iso_day(c2.date_input("Exclude end", value=pd.Timestamp("2021-06-30").date(), key=f"{key_prefix}_exc_end"))
            if exc_start and exc_end and exc_start <= exc_end:
                exclude_windows = [(exc_start, exc_end)]

        return {
            "start": start,
            "end": end,
            "include_windows": include_windows,
            "exclude_windows": exclude_windows,
        }


def collect_optimization_domains(strategy_kinds: list[str], key_prefix: str) -> dict[str, Any]:
    domains_by_kind: dict[str, Any] = {}
    with st.expander("Advanced Optimization Domains", expanded=False):
        enabled = st.checkbox(
            "Use manual parameter candidate lists",
            value=False,
            key=f"{key_prefix}_domains_on",
            help="When enabled, each selected strategy uses the candidate values you provide below.",
        )
        if not enabled:
            return domains_by_kind

        for kind in strategy_kinds:
            defaults = dict(OPTIMIZER_DOMAIN_DEFAULTS.get(str(kind), {}))
            if not defaults:
                continue
            st.markdown(f"**{kind} domains**")
            entries: list[dict[str, Any]] = []
            for param_key, default_raw in defaults.items():
                raw = st.text_input(
                    param_key,
                    value=default_raw,
                    key=f"{key_prefix}_domain_{kind}_{param_key}",
                    help="Comma-separated values. Example: 5,10,20",
                )
                parsed = parse_manual_values(raw)
                if parsed:
                    entries.append(
                        {
                            "key": param_key,
                            "kind": "choice",
                            "domain": parsed,
                            "enabled": True,
                        }
                    )

            st.markdown("Portfolio domains")
            for p_key, p_default in PORTFOLIO_DOMAIN_DEFAULTS.items():
                raw = st.text_input(
                    p_key,
                    value=p_default,
                    key=f"{key_prefix}_domain_{kind}_{p_key}",
                    help="Comma-separated values. These are applied during optimization for this strategy kind.",
                )
                parsed = parse_manual_values(raw)
```

