from __future__ import annotations

from core.quant_core.wfo.option_e import ordered_level_combinations, requires_joint_wfo, select_best_level_count


def test_ordered_level_combinations_builds_increasing_combos() -> None:
    combos = ordered_level_combinations([10, 20, 30, 40], 3)
    assert combos == [(10, 20, 30), (10, 20, 40), (10, 30, 40), (20, 30, 40)]


def test_select_best_level_count_returns_best_score() -> None:
    result = select_best_level_count({2: 0.21, 3: 0.35, 4: 0.31})
    assert result is not None
    assert result.level_count == 3


def test_requires_joint_wfo_detects_wfo_modes() -> None:
    assert requires_joint_wfo(["manual", "wfo"])
    assert not requires_joint_wfo(["manual", "manual"])

