from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ICCurve:
    horizons: list[int]
    ic_values: list[float]
    ic_se: list[float]
    ic_ci_lower: list[float]
    ic_ci_upper: list[float]
    n_obs: list[int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "horizons": self.horizons,
            "ic_values": self.ic_values,
            "ic_se": self.ic_se,
            "ic_ci_lower": self.ic_ci_lower,
            "ic_ci_upper": self.ic_ci_upper,
            "n_obs": self.n_obs,
        }


@dataclass
class RobustnessReport:
    dsr: float
    psr: float
    sharpe_bootstrap_ci_lower: float
    sharpe_bootstrap_ci_upper: float
    ic_bootstrap_ci_lower: float
    ic_bootstrap_ci_upper: float
    ic_cv: float
    sharpe_cv: float
    n_variants: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "dsr": self.dsr,
            "psr": self.psr,
            "sharpe_bootstrap_ci": [self.sharpe_bootstrap_ci_lower, self.sharpe_bootstrap_ci_upper],
            "ic_bootstrap_ci": [self.ic_bootstrap_ci_lower, self.ic_bootstrap_ci_upper],
            "ic_cv": self.ic_cv,
            "sharpe_cv": self.sharpe_cv,
            "n_variants": self.n_variants,
        }


@dataclass
class PortfolioStats:
    sharpe: float
    sortino: float
    max_drawdown: float
    calmar: float
    turnover: float
    hit_rate: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    after_cost_sharpe: float
    n_trades: int
    total_return: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "sharpe": self.sharpe,
            "sortino": self.sortino,
            "max_drawdown": self.max_drawdown,
            "calmar": self.calmar,
            "turnover": self.turnover,
            "hit_rate": self.hit_rate,
            "profit_factor": self.profit_factor,
            "avg_win": self.avg_win,
            "avg_loss": self.avg_loss,
            "after_cost_sharpe": self.after_cost_sharpe,
            "n_trades": self.n_trades,
            "total_return": self.total_return,
        }


@dataclass
class SignalEvaluationReport:
    signal_id: str
    symbol: str
    n_obs: int
    ic_curve: ICCurve
    hit_rate_h1: float
    hit_rate_ci_lower: float
    hit_rate_ci_upper: float
    conditional_return_tstat: float
    portfolio: PortfolioStats
    robustness: RobustnessReport
    horizons: list[int] = field(default_factory=lambda: [1, 2, 3, 5, 10])

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "symbol": self.symbol,
            "n_obs": self.n_obs,
            "horizons": self.horizons,
            "ic_curve": self.ic_curve.to_dict(),
            "hit_rate_h1": self.hit_rate_h1,
            "hit_rate_ci": [self.hit_rate_ci_lower, self.hit_rate_ci_upper],
            "conditional_return_tstat": self.conditional_return_tstat,
            "portfolio": self.portfolio.to_dict(),
            "robustness": self.robustness.to_dict(),
        }
