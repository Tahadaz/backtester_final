from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd

from quant_core.research.stats.robustness import deflated_sharpe_ratio, stationary_bootstrap_ci
from quant_core.wfo.config import WalkForwardConfig
from quant_core.wfo.engine import WindowScoreResult, run_wfo_engine

from .backtest import run_backtest
from .strategy_spec import StrategyDefinition


def _json_number(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def walk_forward(spec: StrategyDefinition, panel: pd.DataFrame, config: WalkForwardConfig) -> dict[str, Any]:
    def evaluate(window: Any) -> WindowScoreResult:
        train = panel.iloc[window.train_start : window.train_end]
        test = panel.iloc[window.oos_start : window.oos_end]
        train_result = run_backtest(spec, train)
        test_result = run_backtest(spec, test)
        return WindowScoreResult(
            raw_scores={0: float(train_result.metrics["sharpe"] or 0.0)},
            is_returns={0: float(train_result.metrics["net_total_return"] or 0.0)},
            oos_returns={0: float(test_result.metrics["net_total_return"] or 0.0)},
            oos_sharpes={0: float(test_result.metrics["sharpe"] or 0.0)},
        )

    result = run_wfo_engine(data_length=len(panel), config=config, evaluate_window=evaluate)
    return {"wfe": result.wfe, "robustness_ratio": result.robustness_ratio, "single_window_dominance": result.single_window_dominance, "window_count": len(result.windows)}


def parameter_grid(spec: StrategyDefinition, panel: pd.DataFrame, grids: dict[str, list[Any]]) -> dict[str, Any]:
    lookbacks = grids.get("lookback_months", [spec.signal.lookback_months])
    rows = []
    best_returns = np.array([], dtype=float)
    for lookback in lookbacks:
        candidate = replace(spec, signal=replace(spec.signal, lookback_months=int(lookback)))
        result = run_backtest(candidate, panel)
        rows.append({"lookback_months": int(lookback), "sharpe": result.metrics["sharpe"]})
        if not best_returns.size or float(result.metrics["sharpe"] or -np.inf) >= max(float(row["sharpe"] or -np.inf) for row in rows):
            best_returns = result.stages["net_return"].dropna().to_numpy()
    count = len(rows)
    return {"matrix": rows, "n_variants": count, "deflated_sharpe": _json_number(deflated_sharpe_ratio(best_returns, n_variants=count)), "warning": "Multiple variants were compared; selection bias is disclosed." if count > 1 else None}


def leave_one_instrument_out(spec: StrategyDefinition, panel: pd.DataFrame) -> dict[str, Any]:
    output = {}
    for symbol in spec.universe.instruments:
        keep = tuple(item for item in spec.universe.instruments if item != symbol)
        candidate = replace(spec, universe=replace(spec.universe, instruments=keep))
        candidate_panel = panel.drop(columns=symbol, level=0) if isinstance(panel.columns, pd.MultiIndex) else panel.drop(columns=symbol)
        output[symbol] = run_backtest(candidate, candidate_panel).metrics
    return output


def subperiod(spec: StrategyDefinition, panel: pd.DataFrame) -> dict[str, Any]:
    return {str(year): run_backtest(spec, group).metrics for year, group in panel.groupby(panel.index.year)}


def cost_sensitivity(spec: StrategyDefinition, panel: pd.DataFrame) -> dict[str, Any]:
    output = {}
    for scale in range(4):
        execution = replace(spec.execution, half_spread_bps=spec.execution.half_spread_bps * scale, slippage_bps=spec.execution.slippage_bps * scale, commission_bps=spec.execution.commission_bps * scale)
        output[str(scale)] = run_backtest(replace(spec, execution=execution), panel).metrics
    return output


def bootstrap_ci(spec: StrategyDefinition, panel: pd.DataFrame, *, seed: int = 42) -> dict[str, float | None]:
    values = run_backtest(spec, panel, seed=seed).stages["net_return"].dropna().to_numpy()
    lo, hi = stationary_bootstrap_ci(values, np.mean, n_bootstrap=spec.validation.bootstrap_samples, rng_seed=seed)
    return {"lower": _json_number(lo), "upper": _json_number(hi)}
