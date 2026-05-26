from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

from .horizons import DEFAULT_COST_BPS_PER_SIDE, HORIZON_PARAMS, canonical_horizon
from .mean_reversion import adf_test, estimate_half_life
from .research.stats.fdr import bh_adjusted_pvalues
from .significance import sharpe_ratio, t_stat_mean_return


StatArbArchetype = Literal["same_bar_cointegration", "lagged_cointegration", "lead_lag_continuation"]
StatArbAction = Literal["long_y_short_x", "short_y_long_x", "buy_buy", "none"]


@dataclass(frozen=True)
class StatArbConfig:
    horizon: str = "short"
    min_obs: int = 252
    entry_z: float = 2.0
    exit_z: float = 0.5
    lag_bars: int = 1
    fdr_q: float = 0.10
    min_folds: int = 3
    min_profitable_fold_ratio: float = 0.60
    max_drawdown_floor: float = -0.20
    cost_bps_per_side: float = DEFAULT_COST_BPS_PER_SIDE
    slippage_bps_per_side: float = 5.0
    borrow_bps_annual: float = 300.0
    train_bars: int | None = None
    oos_bars: int | None = None
    step_bars: int | None = None
    max_chart_points: int = 500

    @property
    def canonical_horizon(self) -> str:
        return canonical_horizon(self.horizon, allow_legacy=True)

    @property
    def resolved_train_bars(self) -> int:
        return int(self.train_bars or HORIZON_PARAMS[self.canonical_horizon]["train"])

    @property
    def resolved_oos_bars(self) -> int:
        return int(self.oos_bars or HORIZON_PARAMS[self.canonical_horizon]["test"])

    @property
    def resolved_step_bars(self) -> int:
        return int(self.step_bars or HORIZON_PARAMS[self.canonical_horizon]["step"])

    @property
    def total_trade_cost_rate(self) -> float:
        return (float(self.cost_bps_per_side) + float(self.slippage_bps_per_side)) / 10_000.0

    @property
    def daily_borrow_rate(self) -> float:
        return float(self.borrow_bps_annual) / 10_000.0 / 252.0


@dataclass
class StatArbPairResult:
    pair_id: str
    symbol_y: str
    symbol_x: str
    horizon: str
    archetype: StatArbArchetype
    lag_bars: int
    action_type: StatArbAction
    current_signal: StatArbAction
    direction: str
    validation_status: str
    status: str
    n_obs: int
    n_folds: int
    hedge_ratio: float | None = None
    intercept: float | None = None
    zscore: float | None = None
    half_life: float | None = None
    adf_pvalue: float | None = None
    raw_pvalue: float = 1.0
    fdr_qvalue: float | None = None
    oos_sharpe: float | None = None
    oos_return: float | None = None
    max_drawdown: float | None = None
    profitable_fold_ratio: float | None = None
    data_as_of: str | None = None
    cost_bps_per_side: float = DEFAULT_COST_BPS_PER_SIDE
    slippage_bps_per_side: float = 5.0
    borrow_bps_annual: float = 300.0
    metrics: dict[str, Any] = field(default_factory=dict)
    chart: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def pair_identifier(
    *,
    symbol_y: str,
    symbol_x: str,
    horizon: str,
    archetype: str,
    lag_bars: int,
) -> str:
    raw = f"{symbol_y.upper()}|{symbol_x.upper()}|{horizon}|{archetype}|{int(lag_bars)}"
    return "sa_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def evaluate_pair(
    symbol_y: str,
    y_close: pd.Series,
    symbol_x: str,
    x_close: pd.Series,
    *,
    archetype: StatArbArchetype,
    config: StatArbConfig | None = None,
) -> StatArbPairResult:
    cfg = config or StatArbConfig()
    horizon = cfg.canonical_horizon
    symbol_y = symbol_y.upper()
    symbol_x = symbol_x.upper()
    lag_bars = int(cfg.lag_bars if archetype != "same_bar_cointegration" else 0)
    pid = pair_identifier(
        symbol_y=symbol_y,
        symbol_x=symbol_x,
        horizon=horizon,
        archetype=archetype,
        lag_bars=lag_bars,
    )

    try:
        if archetype == "lead_lag_continuation":
            result = _evaluate_lead_lag_buy_buy(symbol_y, y_close, symbol_x, x_close, cfg, pid)
        else:
            result = _evaluate_cointegration(symbol_y, y_close, symbol_x, x_close, archetype, cfg, pid, lag_bars)
    except Exception as exc:
        return StatArbPairResult(
            pair_id=pid,
            symbol_y=symbol_y,
            symbol_x=symbol_x,
            horizon=horizon,
            archetype=archetype,
            lag_bars=lag_bars,
            action_type="none",
            current_signal="none",
            direction="none",
            validation_status="error",
            status="failed",
            n_obs=0,
            n_folds=0,
            raw_pvalue=1.0,
            cost_bps_per_side=cfg.cost_bps_per_side,
            slippage_bps_per_side=cfg.slippage_bps_per_side,
            borrow_bps_annual=cfg.borrow_bps_annual,
            warnings=[str(exc)],
        )
    return result


def scan_pairs(
    close_by_symbol: dict[str, pd.Series],
    *,
    horizon: str = "short",
    config: StatArbConfig | None = None,
    include_same_bar: bool = True,
    include_lagged: bool = True,
    include_buy_buy: bool = True,
) -> list[StatArbPairResult]:
    cfg = config or StatArbConfig(horizon=horizon)
    cfg = StatArbConfig(**{**cfg.__dict__, "horizon": horizon})
    symbols = sorted(s.upper() for s in close_by_symbol if str(s).strip())
    series_by_symbol = {s.upper(): close_by_symbol[s].copy() for s in close_by_symbol}

    results: list[StatArbPairResult] = []
    for i, left in enumerate(symbols):
        for right in symbols[i + 1 :]:
            if include_same_bar:
                results.append(evaluate_pair(left, series_by_symbol[left], right, series_by_symbol[right], archetype="same_bar_cointegration", config=cfg))
            if include_lagged:
                results.append(evaluate_pair(left, series_by_symbol[left], right, series_by_symbol[right], archetype="lagged_cointegration", config=cfg))
                results.append(evaluate_pair(right, series_by_symbol[right], left, series_by_symbol[left], archetype="lagged_cointegration", config=cfg))
            if include_buy_buy:
                results.append(evaluate_pair(left, series_by_symbol[left], right, series_by_symbol[right], archetype="lead_lag_continuation", config=cfg))
                results.append(evaluate_pair(right, series_by_symbol[right], left, series_by_symbol[left], archetype="lead_lag_continuation", config=cfg))

    return apply_fdr_and_status(results, cfg)


def apply_fdr_and_status(results: list[StatArbPairResult], config: StatArbConfig | None = None) -> list[StatArbPairResult]:
    cfg = config or StatArbConfig()
    valid = [r for r in results if r.status != "failed"]
    qvalues = bh_adjusted_pvalues([_finite_pvalue(r.raw_pvalue) for r in valid])
    q_by_id = {r.pair_id: q for r, q in zip(valid, qvalues)}

    out: list[StatArbPairResult] = []
    for row in results:
        if row.status == "failed":
            row.fdr_qvalue = None
            out.append(row)
            continue
        row.fdr_qvalue = float(q_by_id.get(row.pair_id, 1.0))
        pass_gate = _passes_validation(row, cfg)
        if pass_gate and row.current_signal != "none":
            row.validation_status = "pass"
            row.status = "actionable"
        elif pass_gate:
            row.validation_status = "pass"
            row.status = "watch"
        else:
            row.validation_status = "reject"
            row.status = "rejected"
            if row.fdr_qvalue is not None and row.fdr_qvalue > cfg.fdr_q:
                row.warnings.append("failed_fdr")
            if int(row.n_folds or 0) < cfg.min_folds:
                row.warnings.append("insufficient_oos_folds")
            if row.max_drawdown is None or row.max_drawdown < cfg.max_drawdown_floor:
                row.warnings.append("drawdown_gate")
        out.append(row)

    out.sort(
        key=lambda r: (
            {"actionable": 0, "watch": 1, "rejected": 2, "failed": 3}.get(r.status, 9),
            -(r.oos_sharpe if r.oos_sharpe is not None and math.isfinite(r.oos_sharpe) else -999.0),
            r.symbol_y,
            r.symbol_x,
        )
    )
    return out


def _evaluate_cointegration(
    symbol_y: str,
    y_close: pd.Series,
    symbol_x: str,
    x_close: pd.Series,
    archetype: StatArbArchetype,
    cfg: StatArbConfig,
    pair_id: str,
    lag_bars: int,
) -> StatArbPairResult:
    frame = _aligned_price_frame(y_close, x_close, lag_bars=lag_bars)
    n = len(frame)
    warnings: list[str] = []
    if n < cfg.min_obs:
        raise ValueError(f"insufficient aligned observations: {n} < {cfg.min_obs}")

    folds = _walk_forward_slices(n, cfg.resolved_train_bars, cfg.resolved_oos_bars, cfg.resolved_step_bars)
    oos_returns: list[pd.Series] = []
    fold_pvalues: list[float] = []
    fold_returns: list[float] = []
    for train_start, train_end, test_start, test_end in folds:
        train = frame.iloc[train_start:train_end]
        test = frame.iloc[test_start:test_end]
        if len(train) < max(50, cfg.min_obs // 2) or len(test) < 5:
            continue
        fit = _fit_spread(train["y"].to_numpy(dtype=float), train["x"].to_numpy(dtype=float))
        if fit["hedge_ratio"] <= 0:
            continue
        spread_train = fit["spread"]
        spread_test = test["y"].to_numpy(dtype=float) - (fit["intercept"] + fit["hedge_ratio"] * test["x"].to_numpy(dtype=float))
        mean = float(np.mean(spread_train))
        std = float(np.std(spread_train, ddof=1))
        if std <= 1e-12 or not math.isfinite(std):
            continue
        z = pd.Series((spread_test - mean) / std, index=test.index)
        pos = _cointegration_position_from_z(z, entry_z=cfg.entry_z, exit_z=cfg.exit_z)
        returns = _pair_position_returns(
            y=frame["y_raw"].reindex(test.index),
            x=frame["x_raw"].reindex(test.index),
            direction=pos,
            hedge_ratio=fit["hedge_ratio"],
            cfg=cfg,
        )
        if not returns.empty:
            oos_returns.append(returns)
            fold_returns.append(float((1.0 + returns).prod() - 1.0))
        try:
            adf = adf_test(spread_train)
            fold_pvalues.append(float(adf["pvalue"]))
        except Exception:
            pass

    oos = pd.concat(oos_returns).sort_index() if oos_returns else pd.Series(dtype=float)
    full_fit = _fit_spread(frame["y"].to_numpy(dtype=float), frame["x"].to_numpy(dtype=float))
    if full_fit["hedge_ratio"] <= 0:
        warnings.append("non_positive_hedge_ratio")
    spread_full = pd.Series(full_fit["spread"], index=frame.index)
    z_full = (spread_full - spread_full.rolling(cfg.resolved_train_bars, min_periods=min(cfg.resolved_train_bars, 60)).mean()) / spread_full.rolling(cfg.resolved_train_bars, min_periods=min(cfg.resolved_train_bars, 60)).std(ddof=1)
    z_latest = _safe_last(z_full)
    current = _cointegration_action(z_latest, cfg.entry_z)

    adf_pvalue = None
    half_life = None
    try:
        adf_full = adf_test(spread_full)
        adf_pvalue = float(adf_full["pvalue"])
    except Exception as exc:
        warnings.append(f"adf_unavailable:{exc}")
    try:
        hl = estimate_half_life(spread_full)
        half_life = float(hl["half_life"])
    except Exception as exc:
        warnings.append(f"half_life_unavailable:{exc}")

    metrics = _oos_metrics(oos, fold_returns, cfg)
    oos_p = metrics.get("oos_pvalue")
    raw_p = max(
        _finite_pvalue(adf_pvalue if adf_pvalue is not None else (min(fold_pvalues) if fold_pvalues else 1.0)),
        _finite_pvalue(oos_p if oos_p is not None else 1.0),
    )
    chart = _cointegration_chart(frame.index, spread_full, z_full, cfg)
    return StatArbPairResult(
        pair_id=pair_id,
        symbol_y=symbol_y,
        symbol_x=symbol_x,
        horizon=cfg.canonical_horizon,
        archetype=archetype,
        lag_bars=lag_bars,
        action_type=current,
        current_signal=current,
        direction=_direction_label(current),
        validation_status="pending",
        status="pending",
        n_obs=n,
        n_folds=int(len(fold_returns)),
        hedge_ratio=float(full_fit["hedge_ratio"]),
        intercept=float(full_fit["intercept"]),
        zscore=z_latest,
        half_life=half_life,
        adf_pvalue=adf_pvalue,
        raw_pvalue=raw_p,
        oos_sharpe=metrics.get("oos_sharpe"),
        oos_return=metrics.get("oos_return"),
        max_drawdown=metrics.get("max_drawdown"),
        profitable_fold_ratio=metrics.get("profitable_fold_ratio"),
        data_as_of=frame.index[-1].date().isoformat(),
        cost_bps_per_side=cfg.cost_bps_per_side,
        slippage_bps_per_side=cfg.slippage_bps_per_side,
        borrow_bps_annual=cfg.borrow_bps_annual,
        metrics=metrics,
        chart=chart,
        warnings=warnings,
    )


def _evaluate_lead_lag_buy_buy(
    symbol_y: str,
    y_close: pd.Series,
    symbol_x: str,
    x_close: pd.Series,
    cfg: StatArbConfig,
    pair_id: str,
) -> StatArbPairResult:
    lag_bars = int(cfg.lag_bars)
    prices = _aligned_price_frame(y_close, x_close, lag_bars=0)
    y_ret = prices["y_raw"].pct_change()
    x_lag_ret = prices["x_raw"].pct_change().shift(lag_bars)
    frame = pd.concat([y_ret.rename("y_ret"), x_lag_ret.rename("x_lag_ret")], axis=1).dropna()
    n = len(frame)
    warnings: list[str] = []
    if n < cfg.min_obs:
        raise ValueError(f"insufficient aligned observations: {n} < {cfg.min_obs}")

    folds = _walk_forward_slices(n, cfg.resolved_train_bars, cfg.resolved_oos_bars, cfg.resolved_step_bars)
    oos_returns: list[pd.Series] = []
    fold_returns: list[float] = []
    beta_pvalues: list[float] = []
    thresholds: list[float] = []
    for train_start, train_end, test_start, test_end in folds:
        train = frame.iloc[train_start:train_end]
        test = frame.iloc[test_start:test_end]
        fit = _fit_predictive_beta(train["y_ret"].to_numpy(dtype=float), train["x_lag_ret"].to_numpy(dtype=float))
        beta = fit["beta"]
        beta_pvalues.append(float(fit["pvalue"]))
        if beta <= 0:
            continue
        threshold = float(train["x_lag_ret"].std(ddof=1))
        thresholds.append(threshold)
        active = pd.Series((test["x_lag_ret"] > threshold).astype(float), index=test.index)
        returns = _buy_buy_returns(prices, active, cfg)
        if not returns.empty:
            oos_returns.append(returns)
            fold_returns.append(float((1.0 + returns).prod() - 1.0))

    full_fit = _fit_predictive_beta(frame["y_ret"].to_numpy(dtype=float), frame["x_lag_ret"].to_numpy(dtype=float))
    threshold_full = float(np.nanmean(thresholds)) if thresholds else float(frame["x_lag_ret"].std(ddof=1))
    latest_predictor = _safe_last(frame["x_lag_ret"])
    current: StatArbAction = "buy_buy" if latest_predictor is not None and latest_predictor > threshold_full and full_fit["beta"] > 0 else "none"

    oos = pd.concat(oos_returns).sort_index() if oos_returns else pd.Series(dtype=float)
    metrics = _oos_metrics(oos, fold_returns, cfg)
    raw_p = max(
        _finite_pvalue(full_fit["pvalue"]),
        _finite_pvalue(metrics.get("oos_pvalue") if metrics.get("oos_pvalue") is not None else 1.0),
    )
    chart = _lead_lag_chart(frame, threshold_full, cfg)
    return StatArbPairResult(
        pair_id=pair_id,
        symbol_y=symbol_y,
        symbol_x=symbol_x,
        horizon=cfg.canonical_horizon,
        archetype="lead_lag_continuation",
        lag_bars=lag_bars,
        action_type=current,
        current_signal=current,
        direction="buy_buy" if current == "buy_buy" else "none",
        validation_status="pending",
        status="pending",
        n_obs=n,
        n_folds=int(len(fold_returns)),
        hedge_ratio=None,
        intercept=float(full_fit["alpha"]),
        zscore=None,
        half_life=None,
        adf_pvalue=float(full_fit["pvalue"]),
        raw_pvalue=raw_p,
        oos_sharpe=metrics.get("oos_sharpe"),
        oos_return=metrics.get("oos_return"),
        max_drawdown=metrics.get("max_drawdown"),
        profitable_fold_ratio=metrics.get("profitable_fold_ratio"),
        data_as_of=frame.index[-1].date().isoformat(),
        cost_bps_per_side=cfg.cost_bps_per_side,
        slippage_bps_per_side=cfg.slippage_bps_per_side,
        borrow_bps_annual=cfg.borrow_bps_annual,
        metrics={**metrics, "lead_lag_beta": float(full_fit["beta"]), "lead_lag_t_stat": float(full_fit["t_stat"]), "trigger_threshold": threshold_full, "latest_leader_return": latest_predictor},
        chart=chart,
        warnings=warnings,
    )


def _aligned_price_frame(y_close: pd.Series, x_close: pd.Series, *, lag_bars: int) -> pd.DataFrame:
    y = _clean_price_series(y_close)
    x_raw = _clean_price_series(x_close)
    x_for_signal = x_raw.shift(int(lag_bars)) if int(lag_bars) > 0 else x_raw
    frame = pd.concat(
        [
            y.rename("y_raw"),
            x_raw.rename("x_raw"),
            y.rename("y"),
            x_for_signal.rename("x"),
        ],
        axis=1,
        join="inner",
    ).dropna()
    return frame.sort_index()


def _clean_price_series(series: pd.Series) -> pd.Series:
    s = pd.Series(series).copy()
    s.index = pd.DatetimeIndex(s.index)
    if s.index.tz is not None:
        s.index = s.index.tz_convert(None)
    s = pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    return s[s > 0].sort_index()


def _fit_spread(y: np.ndarray, x: np.ndarray) -> dict[str, Any]:
    design = np.column_stack([np.ones(len(x), dtype=float), x])
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    intercept = float(beta[0])
    hedge_ratio = float(beta[1])
    spread = y - (intercept + hedge_ratio * x)
    return {"intercept": intercept, "hedge_ratio": hedge_ratio, "spread": spread}


def _fit_predictive_beta(y: np.ndarray, x: np.ndarray) -> dict[str, float]:
    mask = np.isfinite(y) & np.isfinite(x)
    y = y[mask]
    x = x[mask]
    if len(y) < 25:
        return {"alpha": 0.0, "beta": 0.0, "t_stat": 0.0, "pvalue": 1.0}
    design = np.column_stack([np.ones(len(x), dtype=float), x])
    beta, *_ = np.linalg.lstsq(design, y, rcond=None)
    resid = y - design @ beta
    nobs, nparams = design.shape
    sigma2 = float(np.dot(resid, resid) / max(1, nobs - nparams))
    try:
        xtx_inv = np.linalg.inv(design.T @ design)
        stderr = math.sqrt(max(float(xtx_inv[1, 1]) * sigma2, 1e-18))
        t_stat = float(beta[1] / stderr)
    except np.linalg.LinAlgError:
        t_stat = 0.0
    pvalue = float(2.0 * (1.0 - _norm_cdf(abs(t_stat))))
    return {"alpha": float(beta[0]), "beta": float(beta[1]), "t_stat": t_stat, "pvalue": pvalue}


def _walk_forward_slices(n: int, train: int, oos: int, step: int) -> list[tuple[int, int, int, int]]:
    train = max(25, int(train))
    oos = max(5, int(oos))
    step = max(1, int(step))
    out: list[tuple[int, int, int, int]] = []
    start = 0
    while start + train + oos <= n:
        train_start = start
        train_end = start + train
        test_start = train_end
        test_end = train_end + oos
        out.append((train_start, train_end, test_start, test_end))
        start += step
    if not out and n >= train + 5:
        out.append((0, train, train, n))
    return out


def _cointegration_position_from_z(z: pd.Series, *, entry_z: float, exit_z: float) -> pd.Series:
    current = 0.0
    out: list[float] = []
    for value in z.astype(float).to_numpy():
        if not math.isfinite(value):
            out.append(current)
            continue
        if current == 0.0:
            if value <= -entry_z:
                current = 1.0
            elif value >= entry_z:
                current = -1.0
        elif abs(value) <= exit_z:
            current = 0.0
        out.append(current)
    return pd.Series(out, index=z.index, dtype=float)


def _cointegration_action(z: float | None, entry_z: float) -> StatArbAction:
    if z is None or not math.isfinite(z):
        return "none"
    if z <= -entry_z:
        return "long_y_short_x"
    if z >= entry_z:
        return "short_y_long_x"
    return "none"


def _pair_position_returns(
    *,
    y: pd.Series,
    x: pd.Series,
    direction: pd.Series,
    hedge_ratio: float,
    cfg: StatArbConfig,
) -> pd.Series:
    prices = pd.concat([y.rename("y"), x.rename("x"), direction.rename("dir")], axis=1).dropna()
    if len(prices) < 2:
        return pd.Series(dtype=float)
    ret_y = prices["y"].pct_change().shift(-1)
    ret_x = prices["x"].pct_change().shift(-1)
    gross = max(1.0 + abs(float(hedge_ratio)), 1e-12)
    wy = prices["dir"] / gross
    wx = -prices["dir"] * float(hedge_ratio) / gross
    pnl = (wy * ret_y + wx * ret_x).iloc[:-1]
    wy = wy.iloc[:-1]
    wx = wx.iloc[:-1]
    prev_wy = wy.shift(1).fillna(0.0)
    prev_wx = wx.shift(1).fillna(0.0)
    turnover = (wy - prev_wy).abs() + (wx - prev_wx).abs()
    short_gross = wy.clip(upper=0.0).abs() + wx.clip(upper=0.0).abs()
    costs = turnover * cfg.total_trade_cost_rate
    borrow = short_gross * cfg.daily_borrow_rate
    out = (pnl - costs - borrow).replace([np.inf, -np.inf], np.nan).dropna()
    return out.astype(float)


def _buy_buy_returns(prices: pd.DataFrame, active: pd.Series, cfg: StatArbConfig) -> pd.Series:
    aligned = pd.concat([prices["y_raw"].rename("y"), prices["x_raw"].rename("x"), active.rename("active")], axis=1).dropna()
    if len(aligned) < 2:
        return pd.Series(dtype=float)
    ret_y = aligned["y"].pct_change().shift(-1)
    ret_x = aligned["x"].pct_change().shift(-1)
    active_w = aligned["active"].clip(lower=0.0, upper=1.0)
    wy = 0.5 * active_w
    wx = 0.5 * active_w
    pnl = (wy * ret_y + wx * ret_x).iloc[:-1]
    turnover = (wy.diff().abs().fillna(wy.abs()) + wx.diff().abs().fillna(wx.abs())).iloc[:-1]
    out = (pnl - turnover * cfg.total_trade_cost_rate).replace([np.inf, -np.inf], np.nan).dropna()
    return out.astype(float)


def _oos_metrics(oos: pd.Series, fold_returns: list[float], cfg: StatArbConfig) -> dict[str, Any]:
    if oos.empty:
        return {
            "oos_sharpe": None,
            "oos_return": None,
            "max_drawdown": None,
            "profitable_fold_ratio": None,
            "oos_pvalue": 1.0,
            "n_oos_returns": 0,
        }
    sharpe = sharpe_ratio(oos)
    total_return = float((1.0 + oos).prod() - 1.0)
    equity = (1.0 + oos).cumprod()
    dd = equity / equity.cummax() - 1.0
    t = t_stat_mean_return(oos)
    profitable = float(np.mean([r > 0 for r in fold_returns])) if fold_returns else 0.0
    return {
        "oos_sharpe": float(sharpe) if math.isfinite(float(sharpe)) else None,
        "oos_return": total_return,
        "max_drawdown": float(dd.min()) if len(dd) else None,
        "profitable_fold_ratio": profitable,
        "oos_pvalue": t.get("pvalue") if t.get("pvalue") is not None else 1.0,
        "n_oos_returns": int(len(oos)),
        "trade_cost_rate": cfg.total_trade_cost_rate,
        "daily_borrow_rate": cfg.daily_borrow_rate,
    }


def _passes_validation(row: StatArbPairResult, cfg: StatArbConfig) -> bool:
    if row.status == "failed":
        return False
    return bool(
        int(row.n_folds or 0) >= cfg.min_folds
        and row.fdr_qvalue is not None
        and row.fdr_qvalue <= cfg.fdr_q
        and row.oos_sharpe is not None
        and row.oos_sharpe > 0
        and row.profitable_fold_ratio is not None
        and row.profitable_fold_ratio >= cfg.min_profitable_fold_ratio
        and row.max_drawdown is not None
        and row.max_drawdown >= cfg.max_drawdown_floor
    )


def _cointegration_chart(index: pd.DatetimeIndex, spread: pd.Series, zscore: pd.Series, cfg: StatArbConfig) -> dict[str, Any]:
    frame = pd.DataFrame({"spread": spread, "zscore": zscore}).dropna().tail(int(cfg.max_chart_points))
    return {
        "dates": [pd.Timestamp(ts).date().isoformat() for ts in frame.index],
        "spread": [_json_float(v) for v in frame["spread"]],
        "zscore": [_json_float(v) for v in frame["zscore"]],
        "entry_z": float(cfg.entry_z),
        "exit_z": float(cfg.exit_z),
    }


def _lead_lag_chart(frame: pd.DataFrame, threshold: float, cfg: StatArbConfig) -> dict[str, Any]:
    out = frame.tail(int(cfg.max_chart_points))
    return {
        "dates": [pd.Timestamp(ts).date().isoformat() for ts in out.index],
        "target_return": [_json_float(v) for v in out["y_ret"]],
        "lagged_leader_return": [_json_float(v) for v in out["x_lag_ret"]],
        "trigger_threshold": _json_float(threshold),
    }


def _safe_last(series: pd.Series) -> float | None:
    s = pd.Series(series).replace([np.inf, -np.inf], np.nan).dropna()
    if s.empty:
        return None
    value = float(s.iloc[-1])
    return value if math.isfinite(value) else None


def _finite_pvalue(value: Any) -> float:
    try:
        out = float(value)
    except Exception:
        return 1.0
    if not math.isfinite(out):
        return 1.0
    return max(0.0, min(1.0, out))


def _json_float(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _direction_label(action: StatArbAction) -> str:
    if action == "long_y_short_x":
        return "long_y_short_x"
    if action == "short_y_long_x":
        return "short_y_long_x"
    if action == "buy_buy":
        return "buy_buy"
    return "none"


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(float(x) / math.sqrt(2.0)))
