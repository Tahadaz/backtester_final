from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant_core.research.horizon import get_horizon_config  # noqa: E402


def test_get_horizon_config_short_defaults() -> None:
    cfg = get_horizon_config("short")
    assert cfg.name.value == "short"
    assert cfg.train_window == 504
    assert cfg.test_window == 21
    assert cfg.step_size == 21
