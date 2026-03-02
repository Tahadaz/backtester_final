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
