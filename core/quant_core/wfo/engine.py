# core/quant_core/wfo/engine.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Hashable, Mapping

from .config import WalkForwardConfig
from .neighbor_avg import neighbor_average_1d
from .profile import ProfileResult, evaluate_optimization_profile
from .wfe import ReturnWindow, compute_robustness_ratio, compute_single_window_dominance, compute_wfe
from .window import WalkForwardWindow, build_walk_forward_windows


@dataclass(frozen=True)
class WindowScoreResult:
    raw_scores: dict[Hashable, float]
    is_returns: dict[Hashable, float]
    oos_returns: dict[Hashable, float]
    oos_sharpes: dict[Hashable, float] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluatedWindow:
    window: WalkForwardWindow
    winner_key: Hashable
    winner_prom: float
    profile: ProfileResult
    is_return: float
    oos_return: float
    oos_sharpe: float = 0.0
    smoothed_scores: dict[Hashable, float] = field(default_factory=dict)


@dataclass(frozen=True)
class EngineResult:
    config: WalkForwardConfig
    windows: list[EvaluatedWindow]
    wfe: float
    robustness_ratio: float
    single_window_dominance: float


def run_wfo_engine(
    *,
    data_length: int,
    config: WalkForwardConfig,
    evaluate_window: Callable[[WalkForwardWindow], WindowScoreResult],
    max_lookback: int = 0,
) -> EngineResult:
    windows = build_walk_forward_windows(data_length, config, max_lookback=max_lookback)
    evaluated: list[EvaluatedWindow] = []
    return_windows: list[ReturnWindow] = []

    for window in windows:
        score_result = evaluate_window(window)
        smoothed = neighbor_average_1d(score_result.raw_scores)
        winner_key = max(smoothed, key=smoothed.get)
        profile = evaluate_optimization_profile(
            score_result.raw_scores,
            smoothed,
            winner_key,
            neighbor_values=list(smoothed.values()),
        )
        is_return = score_result.is_returns.get(winner_key, 0.0)
        oos_return = score_result.oos_returns.get(winner_key, 0.0)
        oos_sharpe = getattr(score_result, 'oos_sharpes', {}).get(winner_key, 0.0)
        
        import math
        if math.isnan(oos_sharpe):
            oos_sharpe = 0.0
            
        evaluated.append(
            EvaluatedWindow(
                window=window,
                winner_key=winner_key,
                winner_prom=smoothed[winner_key],
                profile=profile,
                is_return=is_return,
                oos_return=oos_return,
                oos_sharpe=oos_sharpe,
                smoothed_scores=dict(smoothed),
            )
        )
        return_windows.append(
            ReturnWindow(
                is_return=is_return,
                oos_return=oos_return,
                is_bars=window.train_bars,
                oos_bars=window.oos_bars,
            )
        )

    oos_returns = [item.oos_return for item in evaluated]
    return EngineResult(
        config=config,
        windows=evaluated,
        wfe=compute_wfe(return_windows),
        robustness_ratio=compute_robustness_ratio(oos_returns),
        single_window_dominance=compute_single_window_dominance(oos_returns),
    )
