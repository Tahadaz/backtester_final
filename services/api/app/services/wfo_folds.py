from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _iso_index_date(index: pd.DatetimeIndex, position: int) -> str | None:
    if position < 0 or position >= len(index):
        return None
    value = index[position]
    if hasattr(value, "date"):
        return value.date().isoformat()
    return str(value)[:10]


def _resolve_cap_offset(config_json: Mapping[str, Any] | None, index: pd.DatetimeIndex) -> int | None:
    config = config_json or {}
    explicit = _safe_int(config.get("horizon_cap_start_offset"))
    if explicit is not None and explicit >= 0:
        return explicit

    cap_bars = _safe_int(config.get("horizon_cap_bars_used"))
    if cap_bars is None or cap_bars <= 0:
        return None

    data_bars = _safe_int(config.get("data_bars"))
    base_len = data_bars if data_bars is not None and data_bars >= cap_bars else len(index)
    offset = int(base_len) - int(cap_bars)
    return offset if offset > 0 else None


def normalize_wfo_folds_json(
    folds_json: Iterable[Mapping[str, Any]] | None,
    *,
    config_json: Mapping[str, Any] | None = None,
    ohlcv_index: pd.DatetimeIndex | None = None,
) -> list[dict[str, Any]] | None:
    """Return WFO folds with absolute OOS indices/dates when cap metadata exists.

    Some older persisted WFO rows were evaluated on a recent horizon-capped slice
    but stored fold-local indices and dates against the full OHLCV index. When
    `horizon_cap_bars_used` is present, this reconstructs absolute indices so
    OOS readers map the folds onto the intended recent slice.
    """
    if folds_json is None:
        return None
    folds = [dict(fold) for fold in folds_json if isinstance(fold, Mapping)]
    if not folds or ohlcv_index is None or len(ohlcv_index) == 0:
        return folds

    index = pd.DatetimeIndex(ohlcv_index)
    offset = _resolve_cap_offset(config_json, index)

    out: list[dict[str, Any]] = []
    for fold in folds:
        normalized = dict(fold)
        start_abs = _safe_int(normalized.get("oos_start_abs_idx"))
        end_abs = _safe_int(normalized.get("oos_end_abs_idx"))

        if start_abs is None or end_abs is None:
            start_local = _safe_int(normalized.get("oos_start"))
            end_local = _safe_int(normalized.get("oos_end"))
            if offset is not None and start_local is not None and end_local is not None:
                start_abs = start_local + offset
                end_abs = end_local + offset

        if start_abs is not None and end_abs is not None and 0 <= start_abs < end_abs <= len(index):
            normalized["oos_start_abs_idx"] = start_abs
            normalized["oos_end_abs_idx"] = end_abs
            start_date = _iso_index_date(index, start_abs)
            end_date = _iso_index_date(index, end_abs - 1)
            if start_date is not None:
                normalized["oos_start_date"] = start_date
            if end_date is not None:
                normalized["oos_end_date"] = end_date

        out.append(normalized)

    return out
