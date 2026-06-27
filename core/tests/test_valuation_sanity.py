from __future__ import annotations

import os
from pathlib import Path

import pytest

from services.api.scripts.validate_vs_bkgr import _latest_ensembles, _load_fixture, _metrics, _validation_rows


FIXTURE = Path("core/tests/fixtures/bkgr_jun2026.csv")
DEFAULT_DB_URL = "postgresql+psycopg2://app:app@127.0.0.1:5555/quant"


def _bkgr_rows():
    fixture = _load_fixture(FIXTURE)
    try:
        ensembles = _latest_ensembles(os.getenv("DATABASE_URL", DEFAULT_DB_URL), [row.ticker for row in fixture], "base")
    except Exception as exc:  # pragma: no cover - local DB is expected in the project workspace.
        pytest.skip(f"local fundamental database unavailable: {exc}")
    rows = _validation_rows(fixture, ensembles)
    if sum(1 for row in rows if row.engine_upside_pct is not None) < 10:
        pytest.skip("not enough stored BKGR fixture ensembles for sanity validation")
    return rows


def test_bkgr_fixture_structural_sanity_guardrails() -> None:
    """Loose guardrails against fabricated floors/tails and directional collapse; not a BKGR fit target."""

    rows = _bkgr_rows()
    metrics = _metrics(rows)
    active = [row for row in rows if row.engine_rating != "NR" and row.usable_models >= 3]

    assert [row.ticker for row in active if row.engine_upside_pct is not None and row.engine_upside_pct <= -95.0] == []
    assert [row.ticker for row in active if row.engine_upside_pct is not None and row.engine_upside_pct > 150.0] == []
    assert metrics["mean_bias_pct"] is not None
    # Brief 41 expands verified coverage to names that were previously NR; keep
    # this as a broad bias guardrail, not a fit to the BKGR fixture.
    assert -20.0 <= float(metrics["mean_bias_pct"]) <= 25.0

    strong_bkgr_buys = [
        row
        for row in rows
        if row.bkgr_rating == "Acheter"
        and row.bkgr_upside_pct > 30.0
        and row.usable_models >= 3
        and row.confidence is not None
        and row.confidence >= 0.5
        and row.engine_upside_pct is not None
        and row.engine_upside_pct <= -75.0
        and not row.warnings
    ]
    assert [row.ticker for row in strong_bkgr_buys if row.engine_rating in {"SELL", "REDUCE"}] == []

    if metrics["quorum_count"] >= 10:
        assert metrics["buy_or_accumulate_count"] > 0
