from __future__ import annotations

import pandas as pd

from core.quant_core.data import _slugify_index_name, _standardize_ohlcv_index
from services.api.app.market_data_formats import parse_datetime_series
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


def test_is_symbol_allowed_for_upload_scope_rejects_non_stock_placeholders() -> None:
    for symbol in ("INSTRUMENT", "MAJ"):
        allowed, reason = ingest_mod._is_symbol_allowed_for_upload_scope(symbol, "other")
        assert allowed is False
        assert reason == "non_stock_symbol_rejected"


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


def test_msi20_index_upload_headers_standardize_to_daily_index_bars() -> None:
    raw = pd.DataFrame(
        {
            "séance": ["23/04/2026", "22/04/2026"],
            "code indice": ["MSI20", "MSI20"],
            "libellé indice": ["MASI 20", "MASI 20"],
            "valeur indice": ["1401.7831360000", "1407.4348360000"],
            "plus haut": ["1410.8287420000", "1409.7103610000"],
            "plus bas": ["1399.5584870000", "1402.8007150000"],
        }
    )

    renamed = ingest_mod._rename_index_columns(raw)
    assert {"date", "libelle", "close", "high", "low"} <= set(renamed.columns)
    assert _slugify_index_name(str(renamed.loc[0, "libelle"])) == "MASI_20"

    frame = renamed.drop(columns=["libelle"], errors="ignore").copy()
    frame["date"] = parse_datetime_series(frame["date"], day_first=True)
    frame = frame.dropna(subset=["date"]).set_index("date")
    standardized = _standardize_ohlcv_index(frame)

    assert list(standardized.columns) == ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    assert standardized.index.min().strftime("%Y-%m-%d") == "2026-04-22"
    assert standardized.index.max().strftime("%Y-%m-%d") == "2026-04-23"
    assert standardized["Volume"].eq(0.0).all()
