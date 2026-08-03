from pathlib import Path
from io import StringIO

import pytest

from quant_core.cross_asset.importer import import_canonical_csv


def test_canonical_fixture_imports_to_tidy_panel():
    path = Path(__file__).parent / "fixtures" / "cross_asset" / "fx_g10_sample.csv"
    panel, report = import_canonical_csv(path)
    assert ("EURUSD", "spot") in panel.columns
    assert not report.blocks_backtest


def test_schema_violation_is_precise():
    with pytest.raises(ValueError, match="missing columns: field"):
        import_canonical_csv(StringIO("instrument_id,date,value,currency,contract_expiry,source\nA,2025-01-01,1,USD,,x\n"))
