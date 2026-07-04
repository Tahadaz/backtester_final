from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from math import isfinite
from typing import Literal

import numpy as np
import pandas as pd

from core.quant_core.data import normalize_symbol
from core.quant_core.research.stats.regression import RegressionResult as _RegressionResult
from core.quant_core.research.stats.regression import ols_beta as _ols_beta


BetaFrequency = Literal["weekly", "monthly"]


@dataclass(frozen=True)
class BetaConfig:
    proxy_symbol: str = "MASI"
    frequency: BetaFrequency = "weekly"
    window_years: int = 2
    min_obs: int = 60
    min_traded_periods: int = 60
    zero_return_threshold: float = 0.30
    zero_return_tolerance: float = 1e-10
    blume_weight: float = 0.67
    dimson_lags: int = 1
    robust_min_nonzero_periods: int = 20
    robust_r2_floor: float = 0.01


@dataclass(frozen=True)
class BetaEstimate:
    symbol: str
    as_of: dt.date
    beta: float
    raw_beta: float
    method: str
    r2: float | None
    n_obs: int
    zero_week_frac: float
    liquidity_flag: bool
    proxy: str = "MASI"
    frequency: BetaFrequency = "weekly"
    window_years: int = 2
    warnings: list[str] = field(default_factory=list)


def unlever_beta(beta: float, debt_to_equity: float | None, tax_rate: float) -> float:
    """Convert an observed levered equity beta to an asset beta."""

    beta_f = _finite_float(beta)
    if beta_f is None:
        raise ValueError("beta must be finite")
    de = max(0.0, _finite_float(debt_to_equity) or 0.0)
    tax = max(0.0, min(1.0, _finite_float(tax_rate) if tax_rate is not None else 0.0))
    return beta_f / (1.0 + (1.0 - tax) * de)


def relever_beta(unlevered_beta: float, debt_to_equity: float | None, tax_rate: float) -> float:
    """Re-lever an asset beta at a target capital structure."""

    beta_f = _finite_float(unlevered_beta)
    if beta_f is None:
        raise ValueError("unlevered_beta must be finite")
    de = max(0.0, _finite_float(debt_to_equity) or 0.0)
    tax = max(0.0, min(1.0, _finite_float(tax_rate) if tax_rate is not None else 0.0))
    return beta_f * (1.0 + (1.0 - tax) * de)


def cost_of_equity_capm(*, risk_free_rate: float, beta: float, equity_risk_premium: float) -> float:
    return float(risk_free_rate) + float(beta) * float(equity_risk_premium)


def wacc_build_up(
    *,
    cost_of_equity: float,
    cost_of_debt: float,
    tax_rate: float,
    equity_weight: float,
    debt_weight: float,
) -> dict[str, float]:
    """Return a transparent WACC build-up dict for valuation inputs."""

    we = max(0.0, float(equity_weight))
    wd = max(0.0, float(debt_weight))
    total = we + wd
    if total <= 0.0:
        we, wd, total = 0.70, 0.30, 1.0
    we /= total
    wd /= total
    tax = max(0.0, min(1.0, float(tax_rate)))
    ke = float(cost_of_equity)
    kd = float(cost_of_debt)
    wacc = we * ke + wd * kd * (1.0 - tax)
    return {
        "cost_of_equity": ke,
        "cost_of_debt": kd,
        "tax_rate": tax,
        "equity_weight": we,
        "debt_weight": wd,
        "wacc": wacc,
    }


def estimate_beta(
    *,
    symbol: str,
    stock_close: pd.Series,
    market_close: pd.Series,
    as_of: dt.date | None = None,
    config: BetaConfig | None = None,
    peer_unlevered_beta: float | None = None,
    debt_to_equity: float | None = None,
    tax_rate: float = 0.35,
) -> BetaEstimate:
    """Estimate a PIT equity beta from stock and market close series.

    Default is 2-year weekly OLS vs broad MASI. Very low-liquidity names route
    through Dimson+Blume and, if that is unstable, a peer unlever/relever fallback.
    """

    cfg = config or BetaConfig()
    if cfg.dimson_lags != 1:
        raise ValueError("only Dimson 1-lag beta is currently supported")

    stock = _prepare_close(stock_close)
    market = _prepare_close(market_close)
    if stock.empty:
        raise ValueError("stock_close is empty after normalization")
    if market.empty:
        raise ValueError("market_close is empty after normalization")

    effective_as_of = _effective_as_of(stock, market, as_of)
    stock = _window_series(stock, effective_as_of, cfg.window_years)
    market = _window_series(market, effective_as_of, cfg.window_years)
    stock_returns = _period_returns(stock, cfg.frequency)
    market_returns = _period_returns(market, cfg.frequency)
    aligned = _aligned_returns(stock_returns, market_returns)
    if len(aligned) < 2:
        raise ValueError("not enough overlapping return observations for beta")

    zero_frac = _zero_return_fraction(aligned["stock"], cfg.zero_return_tolerance)
    nonzero_periods = int((aligned["stock"].abs() > cfg.zero_return_tolerance).sum())
    liquidity_flag = bool(
        zero_frac > cfg.zero_return_threshold
        or len(aligned) < cfg.min_obs
        or nonzero_periods < cfg.min_traded_periods
    )
    warnings: list[str] = []
    if liquidity_flag:
        warnings.append("very_low_liquidity")

    if not liquidity_flag:
        ols = _ols_beta(aligned["stock"].to_numpy(dtype=float), aligned["market"].to_numpy(dtype=float))
        return BetaEstimate(
            symbol=normalize_symbol(symbol),
            as_of=effective_as_of,
            beta=ols.beta,
            raw_beta=ols.beta,
            method="ols",
            r2=ols.r2,
            n_obs=ols.n_obs,
            zero_week_frac=zero_frac,
            liquidity_flag=False,
            proxy=normalize_symbol(cfg.proxy_symbol),
            frequency=cfg.frequency,
            window_years=cfg.window_years,
            warnings=warnings,
        )

    dimson = _dimson_beta(aligned["stock"], aligned["market"])
    beta_raw = dimson.beta
    beta_adj = cfg.blume_weight * beta_raw + (1.0 - cfg.blume_weight) * 1.0
    unstable = (
        not isfinite(beta_adj)
        or dimson.n_obs < max(3, cfg.robust_min_nonzero_periods)
        or nonzero_periods < cfg.robust_min_nonzero_periods
        or (dimson.r2 is not None and dimson.r2 < cfg.robust_r2_floor)
    )
    if unstable:
        warnings.append("dimson_unstable")
        peer_beta = _finite_float(peer_unlevered_beta)
        if peer_beta is not None:
            relevered = relever_beta(peer_beta, debt_to_equity, tax_rate)
            return BetaEstimate(
                symbol=normalize_symbol(symbol),
                as_of=effective_as_of,
                beta=relevered,
                raw_beta=relevered,
                method="peer_relevered",
                r2=dimson.r2,
                n_obs=dimson.n_obs,
                zero_week_frac=zero_frac,
                liquidity_flag=True,
                proxy=normalize_symbol(cfg.proxy_symbol),
                frequency=cfg.frequency,
                window_years=cfg.window_years,
                warnings=warnings,
            )

    return BetaEstimate(
        symbol=normalize_symbol(symbol),
        as_of=effective_as_of,
        beta=beta_adj,
        raw_beta=beta_raw,
        method="dimson_blume" if not unstable else "dimson_blume_unstable",
        r2=dimson.r2,
        n_obs=dimson.n_obs,
        zero_week_frac=zero_frac,
        liquidity_flag=True,
        proxy=normalize_symbol(cfg.proxy_symbol),
        frequency=cfg.frequency,
        window_years=cfg.window_years,
        warnings=warnings,
    )


def _finite_float(value: object) -> float | None:
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _prepare_close(close: pd.Series) -> pd.Series:
    if not isinstance(close, pd.Series):
        close = pd.Series(close)
    index = pd.to_datetime(close.index, errors="coerce")
    if isinstance(index, pd.DatetimeIndex) and index.tz is not None:
        index = index.tz_convert(None)
    series = pd.Series(pd.to_numeric(close.to_numpy(), errors="coerce"), index=index)
    series = series[~series.index.isna()]
    series = series.where(series > 0).dropna()
    series = series.sort_index()
    series = series[~series.index.duplicated(keep="last")]
    return series.astype(float)


def _effective_as_of(stock: pd.Series, market: pd.Series, as_of: dt.date | None) -> dt.date:
    last_stock = stock.index.max().date()
    last_market = market.index.max().date()
    last_common = min(last_stock, last_market)
    if as_of is None:
        return last_common
    return min(as_of, last_common)


def _window_series(series: pd.Series, as_of: dt.date, window_years: int) -> pd.Series:
    end = pd.Timestamp(as_of)
    start = end - pd.DateOffset(years=max(1, int(window_years)))
    return series.loc[(series.index <= end) & (series.index >= start)]


def _period_returns(close: pd.Series, frequency: BetaFrequency) -> pd.Series:
    if frequency == "weekly":
        prices = close.resample("W-FRI").last()
    elif frequency == "monthly":
        prices = close.resample("ME").last()
    else:
        raise ValueError(f"unsupported beta frequency: {frequency!r}")
    returns = prices.pct_change()
    returns = returns.replace([np.inf, -np.inf], np.nan).dropna()
    return returns.astype(float)


def _aligned_returns(stock_returns: pd.Series, market_returns: pd.Series) -> pd.DataFrame:
    frame = pd.concat({"stock": stock_returns, "market": market_returns}, axis=1, join="inner")
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna()
    return frame.astype(float)


def _zero_return_fraction(stock_returns: pd.Series, tolerance: float) -> float:
    if stock_returns.empty:
        return 1.0
    return float((stock_returns.abs() <= tolerance).sum() / len(stock_returns))


def _dimson_beta(stock_returns: pd.Series, market_returns: pd.Series) -> _RegressionResult:
    frame = pd.concat({"stock": stock_returns, "market": market_returns}, axis=1, join="inner")
    frame["market_lag1"] = frame["market"].shift(1)
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna()
    if len(frame) < 3:
        raise ValueError("Dimson beta requires at least three aligned observations")
    y = frame["stock"].to_numpy(dtype=float)
    x0 = frame["market"].to_numpy(dtype=float)
    x1 = frame["market_lag1"].to_numpy(dtype=float)
    x = np.column_stack([np.ones(len(frame)), x0, x1])
    coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    fitted = x @ coef
    beta = float(coef[1] + coef[2])
    return _RegressionResult(beta=beta, r2=_r2(y, fitted), n_obs=len(frame))


def _r2(y: np.ndarray, fitted: np.ndarray) -> float | None:
    total = float(np.sum((y - y.mean()) ** 2))
    if total <= 0.0:
        return None
    resid = float(np.sum((y - fitted) ** 2))
    return max(0.0, min(1.0, 1.0 - resid / total))
