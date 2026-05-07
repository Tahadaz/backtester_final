from __future__ import annotations

import numpy as np
import pandas as pd

from core.quant_core.data import drop_incomplete_ohlcv_rows


def test_drop_incomplete_ohlcv_rows_excludes_partial_dates() -> None:
    bars = pd.DataFrame(
        {
            "Open": [100.0, np.nan, 102.0],
            "High": [101.0, 102.0, 103.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [100.5, 101.5, np.nan],
            "Volume": [1000.0, 1100.0, 1200.0],
        },
        index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
    )

    cleaned = drop_incomplete_ohlcv_rows(bars)

    assert cleaned.index.strftime("%Y-%m-%d").tolist() == ["2024-01-02"]


def test_drop_incomplete_ohlcv_rows_requires_all_ohlcv_columns() -> None:
    bars = pd.DataFrame(
        {
            "Open": [100.0],
            "High": [101.0],
            "Low": [99.0],
            "Close": [100.5],
        },
        index=pd.to_datetime(["2024-01-02"]),
    )

    cleaned = drop_incomplete_ohlcv_rows(bars)

    assert cleaned.empty
    assert "Volume" in cleaned.columns
