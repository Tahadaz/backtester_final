from __future__ import annotations

import pandas as pd

import services.worker.tasks.ingest_market_data as ingest_mod


def test_is_symbol_allowed_for_upload_scope_rejects_non_masi() -> None:
    allowed, reason = ingest_mod._is_symbol_allowed_for_upload_scope("AAPL", "masi")
    assert allowed is False
    assert reason == "non_masi_symbol_rejected"


def test_is_symbol_allowed_for_upload_scope_accepts_masi() -> None:
    allowed, reason = ingest_mod._is_symbol_allowed_for_upload_scope("AFI", "masi")
    assert allowed is True
    assert reason is None


def test_is_symbol_allowed_for_upload_scope_other_accepts_any_symbol() -> None:
    allowed, reason = ingest_mod._is_symbol_allowed_for_upload_scope("AAPL", "other")
    assert allowed is True
    assert reason is None


def test_mark_ohlc_zeros_as_missing_keeps_volume_zero() -> None:
    frame = pd.DataFrame(
        {
            "Open": [0.0, 10.0],
            "High": [12.0, 0.0],
            "Low": [9.0, 0.0],
            "Close": [0.0, 11.0],
            "Volume": [0.0, 100.0],
        }
    )

    cleaned = ingest_mod._mark_ohlc_zeros_as_missing(frame)

    assert pd.isna(cleaned.loc[0, "Open"])
    assert pd.isna(cleaned.loc[1, "High"])
    assert pd.isna(cleaned.loc[1, "Low"])
    assert pd.isna(cleaned.loc[0, "Close"])
    assert cleaned.loc[0, "Volume"] == 0.0


def test_compute_adv_20d_value_uses_price_times_share_volume() -> None:
    frame = pd.DataFrame(
        {
            "Close": [10.0] * 10 + [20.0] * 20,
            "Volume": [100.0] * 30,
        }
    )

    assert ingest_mod._compute_adv_20d_value(frame) == 2_000.0
