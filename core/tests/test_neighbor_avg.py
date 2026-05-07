from __future__ import annotations

from core.quant_core.wfo.neighbor_avg import neighbor_average_1d, neighbor_average_nd


def test_neighbor_average_1d_handles_boundaries() -> None:
    scores = {5: 0.2, 6: 0.3, 7: 0.8, 8: 0.3}
    smoothed = neighbor_average_1d(scores)
    assert round(smoothed[5], 2) == 0.25
    assert round(smoothed[6], 2) == 0.43
    assert round(smoothed[7], 2) == 0.47
    assert round(smoothed[8], 2) == 0.55


def test_neighbor_average_nd_prefers_plateau_over_spike() -> None:
    scores = {
        (1, 1): 0.2,
        (1, 2): 0.4,
        (1, 3): 0.5,
        (2, 1): 0.3,
        (2, 2): 0.9,
        (2, 3): 0.55,
        (3, 1): 0.31,
        (3, 2): 0.52,
        (3, 3): 0.51,
    }
    smoothed = neighbor_average_nd(scores)
    winner = max(smoothed, key=smoothed.get)
    assert winner in {(2, 3), (3, 2), (3, 3)}
    assert smoothed[(2, 2)] < smoothed[winner]

