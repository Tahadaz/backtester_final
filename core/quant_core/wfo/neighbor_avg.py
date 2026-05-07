from __future__ import annotations

from collections.abc import Hashable, Mapping
from statistics import mean


def neighbor_average_1d(
    prom_values: Mapping[Hashable, float],
    radius: int = 1,
) -> dict[Hashable, float]:
    if radius < 0:
        raise ValueError("radius must be non-negative")
    sorted_keys = sorted(prom_values.keys())
    smoothed: dict[Hashable, float] = {}
    for index, key in enumerate(sorted_keys):
        neighbor_values = [
            prom_values[sorted_keys[pos]]
            for pos in range(max(0, index - radius), min(len(sorted_keys), index + radius + 1))
        ]
        smoothed[key] = mean(neighbor_values)
    return smoothed


def neighbor_average_nd(
    prom_values: Mapping[tuple[Hashable, ...], float],
    radius: int = 1,
) -> dict[tuple[Hashable, ...], float]:
    if radius < 0:
        raise ValueError("radius must be non-negative")
    if not prom_values:
        return {}

    dimensions = len(next(iter(prom_values)))
    smoothed: dict[tuple[Hashable, ...], float] = {}

    for point, score in prom_values.items():
        axis_means: list[float] = []
        for axis in range(dimensions):
            axis_neighbors: list[float] = []
            for other_point, other_score in prom_values.items():
                if other_point == point:
                    axis_neighbors.append(other_score)
                    continue
                if any(other_point[i] != point[i] for i in range(dimensions) if i != axis):
                    continue
                distance = abs(float(other_point[axis]) - float(point[axis]))
                if distance <= radius:
                    axis_neighbors.append(other_score)
            if axis_neighbors:
                axis_means.append(mean(axis_neighbors))
        smoothed[point] = mean(axis_means) if axis_means else score
    return smoothed
