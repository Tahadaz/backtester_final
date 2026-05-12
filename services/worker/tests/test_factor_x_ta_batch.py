from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.quant_core.signal_engine.domain import FactorConditionMeta
from services.worker.tasks import factor_x_ta_batch as fx_batch


def test_align_factor_arrays_uses_precede_open_lag(monkeypatch):
    dates = pd.bdate_range("2024-01-02", periods=5)
    ohlcv = pd.DataFrame({"Close": np.linspace(100.0, 104.0, len(dates))}, index=dates)
    factor = pd.Series(np.arange(10.0, 15.0), index=dates)
    condition = FactorConditionMeta(
        condition_id="vix_gate",
        factor_ticker="^VIX",
        form="level",
        lookback=1,
        threshold=0.0,
        direction="above",
    )

    monkeypatch.setattr(fx_batch, "_build_ticker_to_canonical", lambda: {"^VIX": "VIX"})
    monkeypatch.setattr(fx_batch, "_load_factor_close_series_from_store", lambda _db, _cid: factor)

    aligned = fx_batch._align_factor_arrays_for_conditions(object(), ohlcv, [condition])

    assert set(aligned) == {"^VIX"}
    assert np.isnan(aligned["^VIX"][0])
    np.testing.assert_allclose(aligned["^VIX"][1:], factor.to_numpy(dtype=float)[:-1])


@pytest.mark.parametrize(
    ("selected", "enabled", "expected"),
    [
        ({"^VIX"}, {"^VIX", "^GSPC"}, {"^VIX"}),
        (set(), {"^VIX", "^GSPC"}, set()),
        (None, {"^VIX", "^GSPC"}, {"^VIX", "^GSPC"}),
    ],
)
def test_runtime_inputs_treat_empty_selection_as_authoritative(monkeypatch, selected, enabled, expected):
    dates = pd.bdate_range("2024-01-02", periods=5)
    ohlcv = pd.DataFrame({"Close": np.linspace(100.0, 104.0, len(dates))}, index=dates)
    factor = pd.Series(np.arange(10.0, 15.0), index=dates)
    conditions = [
        FactorConditionMeta("vix_gate", "^VIX", "level", 1, 0.0, "above"),
        FactorConditionMeta("spx_gate", "^GSPC", "level", 1, 0.0, "above"),
    ]

    monkeypatch.setattr(fx_batch, "_get_selected_factor_tickers_with_status", lambda *_a: (selected, None))
    monkeypatch.setattr(fx_batch, "_get_enabled_factor_tickers", lambda *_a: set(enabled))
    monkeypatch.setattr(fx_batch, "_get_stock_sector", lambda *_a: "banks")
    monkeypatch.setattr(fx_batch, "_build_ticker_to_canonical", lambda: {"^VIX": "VIX", "^GSPC": "SP500"})
    monkeypatch.setattr(fx_batch, "_load_factor_close_series_from_store", lambda _db, _cid: factor)

    runtime = fx_batch._build_runtime_inputs(
        object(),
        symbol="AAA",
        horizon="weekly",
        ohlcv=ohlcv,
        all_conditions=conditions,
        channel_tags_yaml={"factors": {"VIX": {"tags": ["all"]}, "SP500": {"tags": ["all"]}}},
    )

    assert runtime.enabled_tickers == expected
    assert {condition.factor_ticker for condition in runtime.conditions} == expected
