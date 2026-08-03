from __future__ import annotations

from pathlib import Path
from typing import IO

import pandas as pd

from .dataquality import DataQualityReport, data_quality_report
from .instruments import Instrument

REQUIRED_COLUMNS = (
    "instrument_id",
    "date",
    "field",
    "value",
    "currency",
    "contract_expiry",
    "source",
)
ALLOWED_FIELDS = {"settle", "open", "high", "low", "close", "volume", "open_interest", "rate", "forward_points", "spot", "front", "collateral_rate", "return", "carry", "r_base", "r_quote"}


def import_canonical_csv(source: str | Path | IO[str]) -> tuple[pd.DataFrame, DataQualityReport]:
    frame = pd.read_csv(source)
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(f"canonical CSV missing columns: {', '.join(missing)}")
    unknown = sorted(set(frame["field"].dropna().astype(str)) - ALLOWED_FIELDS)
    if unknown:
        raise ValueError(f"canonical CSV has unsupported fields: {', '.join(unknown)}")
    try:
        frame["date"] = pd.to_datetime(frame["date"], errors="raise")
        frame["value"] = pd.to_numeric(frame["value"], errors="raise")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"canonical CSV has invalid date or numeric value: {exc}") from exc
    duplicate_rows = frame.duplicated(["instrument_id", "date", "field"], keep=False)
    if duplicate_rows.any():
        duplicate_dates = frame.loc[duplicate_rows, "date"]
        # Keep duplicates in the index so the quality gate, rather than pivot, reports them.
        unique = frame.drop_duplicates(["instrument_id", "date", "field"], keep="first")
        panel = unique.pivot(index="date", columns=["instrument_id", "field"], values="value").sort_index()
        panel = pd.concat([panel, panel.loc[duplicate_dates.iloc[:1]]]).sort_index()
    else:
        panel = frame.pivot(index="date", columns=["instrument_id", "field"], values="value").sort_index()
    instruments = [
        Instrument(str(symbol), "unknown", str(group["currency"].dropna().iloc[0]), "field_value")
        for symbol, group in frame.groupby("instrument_id", sort=True)
    ]
    return panel, data_quality_report(panel, instruments)
