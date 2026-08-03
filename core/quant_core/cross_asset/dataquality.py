from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from .instruments import FuturesContract, Instrument


@dataclass(frozen=True)
class InstrumentQuality:
    instrument: str
    first_observation: str | None
    last_observation: str | None
    missing_periods: int
    duplicate_dates: int
    price_discontinuities: int
    contract_metadata_complete: bool
    longest_stale_run: int
    suspicious_roll_jumps: int
    excluded: bool
    reason: str | None


@dataclass(frozen=True)
class DataQualityReport:
    instruments: tuple[InstrumentQuality, ...]
    blocks_backtest: bool
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _series_for(panel: pd.DataFrame, symbol: str) -> pd.Series:
    if isinstance(panel.columns, pd.MultiIndex):
        if symbol not in panel.columns.get_level_values(0):
            return pd.Series(index=panel.index, dtype=float)
        subset = panel[symbol]
        for preferred in ("return", "settle", "close", "spot", "front", "value"):
            if preferred in subset.columns:
                return subset[preferred]
        return subset.select_dtypes(include=[np.number]).iloc[:, 0] if not subset.empty else pd.Series(dtype=float)
    return panel[symbol] if symbol in panel.columns else pd.Series(index=panel.index, dtype=float)


def _longest_stale(series: pd.Series) -> int:
    clean = series.dropna()
    if clean.empty:
        return 0
    groups = clean.ne(clean.shift()).cumsum()
    return int(clean.groupby(groups).size().max())


def data_quality_report(
    panel: pd.DataFrame,
    instruments: list[Instrument],
    *,
    discontinuity_threshold: float = 0.35,
    stale_bars: int = 10,
) -> DataQualityReport:
    duplicate_count = int(panel.index.duplicated(keep=False).sum())
    qualities: list[InstrumentQuality] = []
    warnings: list[str] = []
    usable_ranges: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for instrument in instruments:
        series = _series_for(panel, instrument.symbol).astype(float)
        clean = series.dropna()
        stale = _longest_stale(series)
        all_stale = len(clean) > 1 and stale == len(clean)
        missing = int(series.isna().sum())
        jumps = int((series.pct_change(fill_method=None).abs() > discontinuity_threshold).sum())
        metadata_complete = not isinstance(instrument, FuturesContract) or (
            instrument.expiry is not None and bool(instrument.roll_rule)
        )
        reasons: list[str] = []
        if clean.empty:
            reasons.append("no observations")
        if all_stale:
            reasons.append("all observations stale")
        if duplicate_count:
            reasons.append("duplicate dates")
        if not metadata_complete:
            reasons.append("incomplete contract metadata")
        if len(clean):
            usable_ranges.append((pd.Timestamp(clean.index.min()), pd.Timestamp(clean.index.max())))
        if missing:
            warnings.append(f"{instrument.symbol}: {missing} missing periods; no forward-fill applied")
        if stale >= stale_bars:
            warnings.append(f"{instrument.symbol}: stale run of {stale} bars")
        qualities.append(
            InstrumentQuality(
                instrument=instrument.symbol,
                first_observation=str(clean.index.min()) if len(clean) else None,
                last_observation=str(clean.index.max()) if len(clean) else None,
                missing_periods=missing,
                duplicate_dates=duplicate_count,
                price_discontinuities=jumps,
                contract_metadata_complete=metadata_complete,
                longest_stale_run=stale,
                suspicious_roll_jumps=jumps,
                excluded=bool(reasons),
                reason="; ".join(reasons) or None,
            )
        )
    no_overlap = bool(usable_ranges) and max(item[0] for item in usable_ranges) > min(item[1] for item in usable_ranges)
    if no_overlap:
        warnings.append("instruments have no overlapping observations")
    fatal = duplicate_count > 0 or no_overlap or any(
        item.reason and ("no observations" in item.reason or "all observations stale" in item.reason)
        for item in qualities
    )
    return DataQualityReport(tuple(qualities), fatal, tuple(dict.fromkeys(warnings)))
