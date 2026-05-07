# core/quant_core/wfo/window.py

from __future__ import annotations

from dataclasses import dataclass

from .config import WalkForwardConfig


@dataclass(frozen=True)
class WalkForwardWindow:
    index: int
    train_start: int
    train_end: int
    oos_start: int
    oos_end: int

    @property
    def train_bars(self) -> int:
        return self.train_end - self.train_start

    @property
    def oos_bars(self) -> int:
        return self.oos_end - self.oos_start


def build_walk_forward_windows(
    data_length: int,
    config: WalkForwardConfig,
    *,
    max_lookback: int = 0,
) -> list[WalkForwardWindow]:
    if data_length <= 0:
        return []
    if config.train_bars <= 0 or config.oos_bars <= 0:
        raise ValueError("train_bars and oos_bars must be positive")
    step = config.effective_step
    if step <= 0:
        raise ValueError("step must be positive")

    windows: list[WalkForwardWindow] = []
    train_start = max_lookback
    index = 0
    while True:
        train_end = train_start + config.train_bars
        oos_start = train_end
        oos_end = oos_start + config.oos_bars
        if oos_end > data_length:
            break
        windows.append(
            WalkForwardWindow(
                index=index,
                train_start=train_start,
                train_end=train_end,
                oos_start=oos_start,
                oos_end=oos_end,
            )
        )
        index += 1
        train_start += step
    return windows


def enumerate_feasible_window_configs(
    data_length: int,
    *,
    max_lookback: int,
    train_candidates: list[int],
    oos_candidates: list[int],
    min_walk_forwards: int = 5,
) -> list[WalkForwardConfig]:
    configs: list[WalkForwardConfig] = []
    for train_bars in train_candidates:
        for oos_bars in oos_candidates:
            config = WalkForwardConfig(
                train_bars=train_bars,
                oos_bars=oos_bars,
                step_bars=oos_bars,
                min_walk_forwards=min_walk_forwards,
            )
            windows = build_walk_forward_windows(
                data_length,
                config,
                max_lookback=max_lookback,
            )
            if len(windows) >= min_walk_forwards:
                configs.append(config)
    return configs

