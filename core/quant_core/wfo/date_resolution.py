from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd

from .date_presets import HORIZON_LOOKBACK_YEARS, TRADING_BARS_PER_YEAR


def _coerce_date(value: Any, *, field_name: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value))
    except Exception as exc:
        raise ValueError(f"{field_name} must be a valid ISO date (YYYY-MM-DD).") from exc


def _to_index_timestamp(value: date, index: pd.DatetimeIndex) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if index.tz is not None:
        if ts.tzinfo is None:
            ts = ts.tz_localize(index.tz)
        else:
            ts = ts.tz_convert(index.tz)
    elif ts.tzinfo is not None:
        ts = ts.tz_convert(None)
    return ts


def resolve_wfo_start_end_dates(
    bars_df: pd.DataFrame,
    *,
    horizon: str,
    start_date: date | None,
    end_date: date | None,
    end_date_policy: str = "latest",
) -> dict[str, Any]:
    index = bars_df.index
    if not isinstance(index, pd.DatetimeIndex):
        raise ValueError("bars_df must have a DatetimeIndex.")
    if index.empty:
        raise ValueError("bars_df index is empty; cannot resolve walk-forward dates.")
    if not index.is_monotonic_increasing or not index.is_unique:
        raise ValueError("bars_df index must be sorted ascending and unique.")

    requested_start = _coerce_date(start_date, field_name="start_date")
    requested_end = _coerce_date(end_date, field_name="end_date")
    policy = str(end_date_policy or "latest").strip().lower()
    first_bar = index[0]
    last_bar = index[-1]
    warnings: list[str] = []

    end_aligned = False
    if requested_end is not None:
        requested_end_ts = _to_index_timestamp(requested_end, index)
        end_pos = int(index.searchsorted(requested_end_ts, side="right")) - 1
        if end_pos < 0:
            raise ValueError(
                f"Requested end_date {requested_end.isoformat()} is before first available bar "
                f"{first_bar.date().isoformat()}."
            )
        resolved_end_ts = index[end_pos]
        end_aligned = resolved_end_ts.date() != requested_end
    else:
        if policy == "latest":
            resolved_end_ts = last_bar
        elif policy == "fixed":
            raise ValueError("end_date is required when end_date_policy='fixed'.")
        else:
            raise ValueError("end_date_policy must be either 'latest' or 'fixed'.")

    start_aligned = False
    if requested_start is not None:
        requested_start_ts = _to_index_timestamp(requested_start, index)
        start_pos = int(index.searchsorted(requested_start_ts, side="left"))
        if start_pos >= len(index):
            raise ValueError(
                f"Requested start_date {requested_start.isoformat()} is after last available bar "
                f"{last_bar.date().isoformat()}."
            )
        resolved_start_ts = index[start_pos]
        start_aligned = resolved_start_ts.date() != requested_start
        if resolved_start_ts > resolved_end_ts:
            raise ValueError(
                f"Resolved start_date {resolved_start_ts.date().isoformat()} is after resolved end_date "
                f"{resolved_end_ts.date().isoformat()}."
            )
    else:
        horizon_key = str(horizon or "").strip().lower()
        lookback_years = HORIZON_LOOKBACK_YEARS.get(horizon_key)
        if lookback_years is None:
            valid = ", ".join(sorted(HORIZON_LOOKBACK_YEARS.keys()))
            raise ValueError(f"Invalid horizon '{horizon}'. Expected one of: {valid}.")
        lookback_bars = int(lookback_years) * TRADING_BARS_PER_YEAR
        end_pos = int(index.get_loc(resolved_end_ts))
        unclamped_start_pos = end_pos - lookback_bars
        start_pos = max(0, unclamped_start_pos)
        resolved_start_ts = index[start_pos]
        if unclamped_start_pos < 0:
            warnings.append(
                "Lookback exceeded available history; start_date was clamped to the earliest available bar."
            )

    alignment_notes = {
        "start_aligned": bool(start_aligned),
        "start_alignment": "next" if start_aligned else "none",
        "end_aligned": bool(end_aligned),
        "end_alignment": "prev" if end_aligned else "none",
    }

    return {
        "resolved_start_date": resolved_start_ts.date(),
        "resolved_end_date": resolved_end_ts.date(),
        "warnings": warnings,
        "alignment_notes": alignment_notes,
    }
