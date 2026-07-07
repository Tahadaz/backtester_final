"""Guards the local-copy helpers in services/api/app/services/value_signal.py against
silently drifting from the canonical originals in methodology_bakeoff.py/characteristic_study.py.

The API's Docker image intentionally excludes statsmodels (only the worker installs it), so
value_signal.py cannot import those research modules directly -- see the module docstring
there for the full explanation. This test is the enforcement mechanism: it runs in the full
dev environment (which has both) and asserts behavioral parity."""
from __future__ import annotations

import math

from core.quant_core.fundamentals.cross_section.characteristic_study import _ratio_or_none as canonical_ratio_or_none
from core.quant_core.fundamentals.cross_section.methodology_bakeoff import (
    METRIC_ALIASES as canonical_metric_aliases,
    _finite as canonical_finite,
    _metric as canonical_metric,
)
from services.api.app.services.value_signal import (
    METRIC_ALIASES as api_metric_aliases,
    _finite as api_finite,
    _metric as api_metric,
    _ratio_or_none as api_ratio_or_none,
)


def test_metric_aliases_subset_matches_canonical_exactly():
    for key in ("book_equity", "cash_flow_ops"):
        assert api_metric_aliases[key] == canonical_metric_aliases[key]


def test_finite_behaves_identically():
    for value in (1.5, "2.0", None, "abc", float("nan"), float("inf"), 0):
        assert api_finite(value) == canonical_finite(value)


def test_metric_lookup_behaves_identically():
    metrics = {"Total_Equity": 100.0, "Capitaux_propres": 200.0, "Operating_Cash_Flow": None}
    for names in (("Total_Equity",), ("Missing", "Capitaux_propres"), ("Operating_Cash_Flow", "CFO")):
        assert api_metric(metrics, *names) == canonical_metric(metrics, *names)


def test_ratio_or_none_behaves_identically():
    cases = [(10.0, 2.0), (10.0, 0.0), (10.0, -5.0), (None, 5.0), (5.0, None), (float("nan"), 5.0)]
    for num, den in cases:
        left = api_ratio_or_none(num, den)
        right = canonical_ratio_or_none(num, den)
        if left is None or right is None:
            assert left is right
        else:
            assert math.isclose(left, right)
