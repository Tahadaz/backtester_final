from __future__ import annotations

from core.quant_core.wfo.config import WalkForwardConfig
from core.quant_core.wfo.engine import WindowScoreResult, run_wfo_engine


def test_run_wfo_engine_selects_smoothed_winner_and_computes_summary() -> None:
    config = WalkForwardConfig(train_bars=20, oos_bars=10, min_walk_forwards=2)

    def evaluate_window(window):
        shift = window.index * 0.01
        return WindowScoreResult(
            raw_scores={5: 0.20 + shift, 6: 0.26 + shift, 7: 0.24 + shift},
            is_returns={5: 0.03, 6: 0.05, 7: 0.04},
            oos_returns={5: 0.02, 6: 0.04, 7: 0.03},
        )

    result = run_wfo_engine(data_length=70, config=config, evaluate_window=evaluate_window)
    assert len(result.windows) >= 2
    assert result.wfe > 0
    assert result.robustness_ratio == 1.0

