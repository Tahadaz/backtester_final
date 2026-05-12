from __future__ import annotations

import pytest

from services.api.app.services.factor_selection_state import (
    normalize_selection_horizon,
    to_pipeline_horizon,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("weekly", "short"),
        ("short", "short"),
        ("monthly", "mid"),
        ("medium", "mid"),
        ("mid", "mid"),
        ("quarterly", "long"),
        ("long", "long"),
    ],
)
def test_normalize_selection_horizon_accepts_runtime_and_legacy_names(raw, expected):
    assert normalize_selection_horizon(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("short", "weekly"),
        ("weekly", "weekly"),
        ("mid", "monthly"),
        ("medium", "monthly"),
        ("monthly", "monthly"),
        ("long", "quarterly"),
        ("quarterly", "quarterly"),
    ],
)
def test_to_pipeline_horizon_returns_canonical_runtime_names(raw, expected):
    assert to_pipeline_horizon(raw) == expected
