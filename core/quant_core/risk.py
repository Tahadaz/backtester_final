from __future__ import annotations

import math
from typing import Any

import numpy as np


def _to_returns(values: Any) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    return arr.astype(float, copy=False)


def kelly_fraction(returns: Any) -> float:
    r = _to_returns(returns)
    if len(r) < 2:
        return 0.0
    mean = float(np.mean(r))
    var = float(np.var(r, ddof=1))
    if var <= 0 or not math.isfinite(var):
        return 0.0
    return float(mean / var)


def monte_carlo_risk(
    returns: Any,
    *,
    n_paths: int = 2000,
    seed: int = 42,
    chosen_leverage: float = 1.0,
    leverage_cap: float = 2.0,
    cost_bps: float = 0.0,
    slippage_bps: float = 0.0,
    avg_turnover: float = 1.0,
    alpha: float = 0.95,
) -> dict[str, Any]:
    r = _to_returns(returns)
    n = len(r)
    if n < 3:
        return {
            "nobs": int(n),
            "n_paths": int(n_paths),
            "mc_drawdown_pctl": None,
            "mc_var": None,
            "mc_cvar": None,
            "drawdown_quantiles": {},
            "terminal_return_quantiles": {},
            "method": "bootstrap_returns_with_frictions",
        }

    lev = float(min(max(chosen_leverage, 0.0), leverage_cap))
    friction = float((cost_bps + slippage_bps) / 10000.0 * max(avg_turnover, 0.0))

    rng = np.random.default_rng(int(seed))
    terminal_returns = np.empty(int(n_paths), dtype=float)
    max_drawdowns = np.empty(int(n_paths), dtype=float)

    for i in range(int(n_paths)):
        sample = r[rng.integers(0, n, size=n)]
        step = lev * sample - friction
        step = np.clip(step, -0.99, None)
        equity = np.cumprod(1.0 + step)
        peak = np.maximum.accumulate(equity)
        drawdown = 1.0 - (equity / np.where(peak <= 0.0, 1.0, peak))
        terminal_returns[i] = float(equity[-1] - 1.0)
        max_drawdowns[i] = float(np.max(drawdown))

    left_tail = np.quantile(terminal_returns, 1.0 - alpha)
    cvar_slice = terminal_returns[terminal_returns <= left_tail]
    cvar = float(np.mean(cvar_slice)) if cvar_slice.size else float(left_tail)

    return {
        "nobs": int(n),
        "n_paths": int(n_paths),
        "alpha": float(alpha),
        "mc_drawdown_pctl": float(np.quantile(max_drawdowns, alpha)),
        "mc_var": float(left_tail),
        "mc_cvar": float(cvar),
        "drawdown_quantiles": {
            "q50": float(np.quantile(max_drawdowns, 0.5)),
            "q90": float(np.quantile(max_drawdowns, 0.9)),
            "q95": float(np.quantile(max_drawdowns, 0.95)),
            "q99": float(np.quantile(max_drawdowns, 0.99)),
        },
        "terminal_return_quantiles": {
            "q01": float(np.quantile(terminal_returns, 0.01)),
            "q05": float(np.quantile(terminal_returns, 0.05)),
            "q50": float(np.quantile(terminal_returns, 0.50)),
            "q95": float(np.quantile(terminal_returns, 0.95)),
            "q99": float(np.quantile(terminal_returns, 0.99)),
        },
        "method": "bootstrap_returns_with_frictions",
    }


def stationary_block_bootstrap(
    returns: np.ndarray,
    *,
    n_paths: int = 2000,
    block_mean: int = 5,
    seed: int = 42,
) -> np.ndarray:
    """Politis–Romano stationary block bootstrap.

    Geometric block lengths with mean `block_mean` (p = 1/block_mean) preserve
    short-term autocorrelation — the institutional standard for continuous-exposure
    signal backtests.

    Returns a (n_paths, T) float64 matrix of bootstrapped return sequences.
    """
    r = np.asarray(returns, dtype=np.float64)
    T = len(r)
    if T < 3:
        return np.zeros((int(n_paths), max(T, 1)), dtype=np.float64)

    rng = np.random.default_rng(int(seed))
    p = 1.0 / max(float(block_mean), 1.0)
    paths = np.empty((int(n_paths), T), dtype=np.float64)

    for i in range(int(n_paths)):
        out = np.empty(T, dtype=np.float64)
        pos = 0
        while pos < T:
            start = int(rng.integers(0, T))
            # Geometric block length: at least 1, drawn independently each step
            length = int(rng.geometric(p))
            length = min(length, T - pos)
            indices = np.arange(start, start + length) % T
            out[pos : pos + length] = r[indices]
            pos += length
        paths[i] = out[:T]

    return paths


def trade_bootstrap(
    trade_pnls: np.ndarray,
    trade_start_indices: np.ndarray,
    T: int,
    *,
    n_paths: int = 2000,
    seed: int = 42,
) -> np.ndarray:
    """Trade-level bootstrap.

    Resamples realized trade PnLs with replacement and scatters them at the
    original trade start indices in a (n_paths, T) return matrix.
    Suitable when trade count >= 30; use block bootstrap otherwise.

    trade_pnls: 1-D array of per-trade returns (len = n_trades)
    trade_start_indices: 1-D int array of bar indices where each trade opens
    T: total bar count (window length)
    Returns: (n_paths, T) float64 matrix
    """
    pnls = np.asarray(trade_pnls, dtype=np.float64)
    starts = np.asarray(trade_start_indices, dtype=np.intp)
    n_trades = len(pnls)

    if n_trades == 0 or T < 1:
        return np.zeros((int(n_paths), max(T, 1)), dtype=np.float64)

    rng = np.random.default_rng(int(seed))
    paths = np.zeros((int(n_paths), T), dtype=np.float64)

    for i in range(int(n_paths)):
        idx = rng.integers(0, n_trades, size=n_trades)
        sampled = pnls[idx]
        for j in range(n_trades):
            bar = int(starts[j])
            if 0 <= bar < T:
                paths[i, bar] += sampled[j]

    return paths


def _sharpe_from_returns(returns: np.ndarray) -> float:
    if len(returns) < 2:
        return 0.0
    mu = float(np.mean(returns))
    sigma = float(np.std(returns, ddof=1))
    if sigma <= 0:
        return 0.0
    return float(mu / sigma * math.sqrt(252))


def monte_carlo_equity_paths(
    returns: np.ndarray,
    *,
    method: str = "block_bootstrap",
    n_paths: int = 2000,
    block_mean: int | None = None,
    trade_events: dict | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    """Build a Monte Carlo equity-path fan for signal-based backtests.

    Returns per-timestep percentile envelopes (p05/p25/p50/p75/p95) and
    terminal-return / CAGR / Sharpe / max-DD distributions.  Unlike the
    existing `monte_carlo_risk`, this preserves the full time dimension so
    the frontend can draw a fan chart.

    Parameters
    ----------
    returns:
        Per-bar strategy returns (1-D, realized backtest).
    method:
        "block_bootstrap" (default) or "trade_bootstrap".
    n_paths:
        Number of simulated paths.
    block_mean:
        Mean block length for stationary block bootstrap.
        None → auto = ceil(T^(1/3)).
    trade_events:
        Required when method="trade_bootstrap".
        Dict with keys "pnls" (float[]) and "start_indices" (int[]).
    seed:
        RNG seed for reproducibility.
    """
    r = np.asarray(returns, dtype=np.float64)
    T = len(r)

    if T < 3:
        empty: list[float] = []
        return {
            "method": method, "n_paths": n_paths, "block_mean": block_mean, "seed": seed,
            "envelope": {"p05": empty, "p25": empty, "p50": empty, "p75": empty, "p95": empty},
            "stats": {
                "total_return": {"p05": None, "p50": None, "p95": None},
                "cagr": {"p05": None, "p50": None, "p95": None},
                "sharpe": {"p05": None, "p50": None, "p95": None},
                "max_drawdown": {"p05": None, "p50": None, "p95": None},
                "var95": None, "cvar95": None, "prob_positive_terminal": None,
            },
        }

    effective_block_mean = int(block_mean) if block_mean is not None else max(1, math.ceil(T ** (1.0 / 3.0)))

    if method == "trade_bootstrap":
        if trade_events is None:
            raise ValueError("trade_events required for method='trade_bootstrap'")
        paths_r = trade_bootstrap(
            np.asarray(trade_events["pnls"], dtype=np.float64),
            np.asarray(trade_events["start_indices"], dtype=np.intp),
            T,
            n_paths=n_paths,
            seed=seed,
        )
    else:
        paths_r = stationary_block_bootstrap(r, n_paths=n_paths, block_mean=effective_block_mean, seed=seed)

    # Equity curves: (n_paths, T), normalized start = 1.0
    clipped = np.clip(paths_r, -0.99, None)
    equity_paths = np.cumprod(1.0 + clipped, axis=1)

    # Per-timestep percentile envelopes
    qs = np.quantile(equity_paths, [0.05, 0.25, 0.50, 0.75, 0.95], axis=0)

    def _q3(arr: np.ndarray) -> dict[str, float | None]:
        return {
            "p05": float(np.quantile(arr, 0.05)),
            "p50": float(np.quantile(arr, 0.50)),
            "p95": float(np.quantile(arr, 0.95)),
        }

    # Terminal return distribution
    terminal = equity_paths[:, -1] - 1.0

    # CAGR distribution (annualized, assuming 252 trading days/year)
    years = T / 252.0
    cagr_dist = np.where(
        equity_paths[:, -1] > 0,
        equity_paths[:, -1] ** (1.0 / max(years, 1e-9)) - 1.0,
        -1.0,
    )

    # Sharpe distribution
    sharpe_dist = np.array([_sharpe_from_returns(paths_r[i]) for i in range(n_paths)])

    # Max-drawdown distribution
    running_max = np.maximum.accumulate(equity_paths, axis=1)
    safe_max = np.where(running_max <= 0, 1.0, running_max)
    drawdowns = 1.0 - equity_paths / safe_max
    max_dd_dist = np.max(drawdowns, axis=1)

    # VaR / CVaR on terminal return
    var95 = float(np.quantile(terminal, 0.05))
    cvar_slice = terminal[terminal <= var95]
    cvar95 = float(np.mean(cvar_slice)) if cvar_slice.size else var95
    prob_positive = float(np.mean(terminal > 0))

    return {
        "method": method,
        "n_paths": n_paths,
        "block_mean": effective_block_mean,
        "seed": seed,
        "envelope": {
            "p05": qs[0].tolist(),
            "p25": qs[1].tolist(),
            "p50": qs[2].tolist(),
            "p75": qs[3].tolist(),
            "p95": qs[4].tolist(),
        },
        "stats": {
            "total_return": _q3(terminal),
            "cagr": _q3(cagr_dist),
            "sharpe": _q3(sharpe_dist),
            "max_drawdown": _q3(max_dd_dist),
            "var95": var95,
            "cvar95": cvar95,
            "prob_positive_terminal": prob_positive,
        },
    }


def shuffled_trade_analysis(
    trade_pnls: np.ndarray,
    *,
    n_paths: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
    """Bootstrap trade PnL distribution to estimate EV and confidence intervals.

    Resamples realized trade PnLs with replacement and compounds them into
    equity curves, answering: "if I drew this many trades at random from my
    realized distribution, what would the terminal equity look like?"

    Distinct from trade_bootstrap (which preserves time-order / bar indices).
    This function only cares about the trade PnL distribution, not timing.

    Returns
    -------
    dict with keys:
      status         : "ok" | "insufficient_trades"
      n_trades       : int
      expected_return: float | None   (mean PnL per trade)
      ci95           : [lo, hi] | None  (bootstrap 95% CI of mean PnL)
      prob_positive  : float | None   (fraction of paths with positive terminal)
      var95          : float | None   (5th percentile of terminal return distribution)
      cvar95         : float | None   (mean of returns below var95)
      envelope       : {p05,p25,p50,p75,p95} each float[] | None  (per-trade cumulative curves, n_trades long)
    """
    pnls = np.asarray(trade_pnls, dtype=np.float64)
    n_trades = len(pnls)

    null_result: dict[str, Any] = {
        "status": "insufficient_trades",
        "n_trades": n_trades,
        "expected_return": None,
        "ci95": None,
        "prob_positive": None,
        "var95": None,
        "cvar95": None,
        "envelope": None,
    }

    if n_trades < 3:
        return null_result

    rng = np.random.default_rng(int(seed))
    # Each path: resample n_trades PnLs with replacement, compound into equity
    paths = np.empty((int(n_paths), n_trades), dtype=np.float64)
    for i in range(int(n_paths)):
        sample = pnls[rng.integers(0, n_trades, size=n_trades)]
        clipped = np.clip(sample, -0.99, None)
        paths[i] = np.cumprod(1.0 + clipped)

    terminal = paths[:, -1] - 1.0

    # Bootstrap CI of mean PnL (per trade)
    means = np.array([
        float(np.mean(pnls[rng.integers(0, n_trades, size=n_trades)]))
        for _ in range(min(int(n_paths), 2000))
    ])

    var95 = float(np.quantile(terminal, 0.05))
    cvar_slice = terminal[terminal <= var95]
    cvar95 = float(np.mean(cvar_slice)) if cvar_slice.size else var95

    qs = np.quantile(paths, [0.05, 0.25, 0.50, 0.75, 0.95], axis=0)

    return {
        "status": "ok",
        "n_trades": n_trades,
        "expected_return": float(np.mean(pnls)),
        "ci95": [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))],
        "prob_positive": float(np.mean(terminal > 0)),
        "var95": var95,
        "cvar95": cvar95,
        "envelope": {
            "p05": qs[0].tolist(),
            "p25": qs[1].tolist(),
            "p50": qs[2].tolist(),
            "p75": qs[3].tolist(),
            "p95": qs[4].tolist(),
        },
    }


def build_risk_summary(
    returns: Any,
    *,
    seed: int = 42,
    n_paths: int = 2000,
    leverage_cap: float = 2.0,
    cost_bps: float = 0.0,
    slippage_bps: float = 0.0,
    avg_turnover: float = 1.0,
) -> dict[str, Any]:
    r = _to_returns(returns)
    kelly = float(kelly_fraction(r))
    half_kelly = float(0.5 * kelly)
    chosen = float(min(max(half_kelly, 0.0), leverage_cap))

    mc = monte_carlo_risk(
        r,
        n_paths=n_paths,
        seed=seed,
        chosen_leverage=chosen,
        leverage_cap=leverage_cap,
        cost_bps=cost_bps,
        slippage_bps=slippage_bps,
        avg_turnover=avg_turnover,
        alpha=0.95,
    )

    return {
        "kelly_fraction": kelly,
        "half_kelly": half_kelly,
        "chosen_leverage": chosen,
        "mc_drawdown_pctl": mc.get("mc_drawdown_pctl"),
        "mc_var": mc.get("mc_var"),
        "mc_cvar": mc.get("mc_cvar"),
        "details": mc,
    }
