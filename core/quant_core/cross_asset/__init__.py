"""Pure, deterministic cross-asset research primitives."""

from .backtest import BacktestResult, run_backtest
from .strategy_spec import StrategyDefinition

__all__ = ["BacktestResult", "StrategyDefinition", "run_backtest"]
