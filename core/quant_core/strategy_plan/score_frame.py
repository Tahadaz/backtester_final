from __future__ import annotations

from typing import Any

import pandas as pd

from core.quant_core.signal_engine.ensemble import FamilyHistoryMode
from core.quant_core.strategy_plan.score_sources import (
    compute_strategy_score_frame as compute_strategy_score_frame_shared,
    derive_max_lookback as derive_max_lookback_shared,
)


def derive_max_lookback(
    stock_config: dict[str, Any],
    *,
    horizon: str = "medium",
    strict_indicator_rows: bool = False,
) -> int:
    return derive_max_lookback_shared(
        stock_config,
        horizon=horizon,
        strict_indicator_rows=strict_indicator_rows,
    )


def compute_strategy_score_frame(
    *,
    stock_config: dict[str, Any],
    ohlcv: pd.DataFrame,
    symbol: str | None = None,
    horizon: str = "medium",
    timeframe: str = "1D",
    signal_cost_bps: float = 10.0,
    cooldown_bars: int = 0,
    family_history_mode: FamilyHistoryMode = "static_current_reps",
) -> pd.DataFrame:
    return compute_strategy_score_frame_shared(
        stock_config=stock_config,
        ohlcv=ohlcv,
        symbol=symbol,
        horizon=horizon,
        timeframe=timeframe,
        signal_cost_bps=signal_cost_bps,
        cooldown_bars=cooldown_bars,
        family_history_mode=family_history_mode,
    )
