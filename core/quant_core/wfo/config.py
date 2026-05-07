from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParameterRange:
    min_value: float
    max_value: float
    step: float

    def values(self) -> list[float]:
        if self.step <= 0:
            raise ValueError("step must be positive")
        if self.max_value < self.min_value:
            raise ValueError("max_value must be >= min_value")
        values: list[float] = []
        current = self.min_value
        epsilon = self.step / 10_000
        while current <= self.max_value + epsilon:
            values.append(round(current, 10))
            current += self.step
        return values


@dataclass(frozen=True)
class WalkForwardConfig:
    train_bars: int
    oos_bars: int
    step_bars: int | None = None
    min_walk_forwards: int = 5

    @property
    def effective_step(self) -> int:
        return self.step_bars or self.oos_bars

