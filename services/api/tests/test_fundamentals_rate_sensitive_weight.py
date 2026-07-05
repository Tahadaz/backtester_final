from __future__ import annotations

import pytest

from services.api.app.routers.fundamentals import _rate_sensitive_weight_from_weights


def test_rate_sensitive_weight_sums_dcf_family_only() -> None:
    assert _rate_sensitive_weight_from_weights(
        {
            "fcff_dcf": 0.20,
            "fcfe_dcf": 0.10,
            "ddm": 0.05,
            "residual_income": 0.15,
            "relative_multiples": 0.40,
            "justified_multiples": 0.10,
        }
    ) == pytest.approx(0.50)


def test_rate_sensitive_weight_ignores_bad_values_and_caps_at_one() -> None:
    assert _rate_sensitive_weight_from_weights(
        {
            "fcff_dcf": "0.70",
            "fcfe_dcf": 0.45,
            "ddm": -0.20,
            "residual_income": None,
            "relative_multiples": 1.0,
        }
    ) == pytest.approx(1.0)
