"""OOS sample resolution for Edge metrics.

Pure functions that turn persisted WFO/signal-engine state into a normalized
`OosSample` describing which `(date, fold)` pairs constitute the out-of-sample
universe for one `(symbol, horizon, source)`. No I/O — all data is injected by
the caller (loaders, OHLCV index) so the module is unit-testable with synthetic
inputs.

Two key constraints baked in here:
- WFO `folds_json` rows in production carry **bar-index** OOS bounds, not
  timestamps. The optional `*_date` keys emitted by recent writers are
  preferred when present; otherwise we resolve via the symbol's OHLCV index.
- `oos_end` is exclusive in bar-index space; `OosWindow.end` is inclusive in
  date space, so the conversion is `index[oos_end - 1]`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Literal, Mapping

import pandas as pd


Source = Literal["wfo", "signal_engine"]
Horizon = Literal["weekly", "monthly", "quarterly"]
ScoreMode = Literal["fold_scoped_winner", "terminal_holdout"]


@dataclass(frozen=True)
class OosWindow:
    """One contiguous OOS interval, optionally tagged with the fold winner.

    For `source='wfo'`, one window per completed fold; `winner_variant_id`
    identifies which variant produced the score on those dates. For
    `source='signal_engine'`, a single window covers the terminal holdout and
    `fold_id` / `winner_*` are None.
    """
    fold_id: int | str | None
    start: pd.Timestamp  # inclusive
    end: pd.Timestamp    # inclusive
    winner_variant_id: str | None = None
    winner_params: dict[str, Any] | None = None


@dataclass(frozen=True)
class OosSample:
    source: Source
    horizon: Horizon
    windows: tuple[OosWindow, ...]
    dates: pd.DatetimeIndex
    score_mode: ScoreMode


# ---------------------------------------------------------------------------
# WFO path
# ---------------------------------------------------------------------------

def _coerce_ts(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    try:
        ts = pd.Timestamp(value)
    except (ValueError, TypeError):
        return None
    return None if pd.isna(ts) else ts


def _align_ts_to_index(ts: pd.Timestamp | None, index: pd.DatetimeIndex | None) -> pd.Timestamp | None:
    if ts is None or index is None or len(index) == 0:
        return ts
    index_tz = index.tz
    if index_tz is None:
        return ts.tz_convert(None) if ts.tzinfo is not None else ts
    if ts.tzinfo is None:
        return ts.tz_localize(index_tz)
    return ts.tz_convert(index_tz)


def _fold_to_window(fold: Mapping[str, Any],
                    ohlcv_index: pd.DatetimeIndex | None) -> OosWindow | None:
    """Convert one element of `WfoSignalSummary.folds_json` to an OosWindow.

    Tolerates: missing `*_date` keys (resolves via `ohlcv_index`), empty-string
    `winner_variant_id` (treated as None), absent `index`/`winner_*` keys.
    Returns None if the fold cannot be resolved to a usable window.
    """
    start = _coerce_ts(fold.get("oos_start_date"))
    end = _coerce_ts(fold.get("oos_end_date"))

    if start is None or end is None:
        if ohlcv_index is None or len(ohlcv_index) == 0:
            return None
        try:
            s_idx = int(fold["oos_start"])
            e_idx = int(fold["oos_end"])
        except (KeyError, TypeError, ValueError):
            return None
        if s_idx < 0 or e_idx <= s_idx or e_idx > len(ohlcv_index):
            return None
        if start is None:
            start = pd.Timestamp(ohlcv_index[s_idx])
        if end is None:
            # `oos_end` is exclusive in bar-index space → inclusive in date space.
            end = pd.Timestamp(ohlcv_index[e_idx - 1])
    else:
        # JSON dates: writer emits `oos_end_date` via `_window_date(end_exclusive=True)`,
        # i.e. it already points to the bar AFTER the last OOS bar. Step back one
        # business day to land on an inclusive boundary that matches the
        # bar-index path above.
        if ohlcv_index is not None and len(ohlcv_index) > 0:
            start = _align_ts_to_index(start, ohlcv_index)
            end = _align_ts_to_index(end, ohlcv_index)
            pos = ohlcv_index.searchsorted(end, side="left")
            if pos > 0:
                end = pd.Timestamp(ohlcv_index[pos - 1])

    if end < start:
        return None

    raw_id = fold.get("winner_variant_id")
    winner_id = (str(raw_id).strip() or None) if raw_id is not None else None

    fold_id_raw = fold.get("index")
    try:
        fold_id: int | str | None = int(fold_id_raw) if fold_id_raw is not None else None
    except (TypeError, ValueError):
        fold_id = str(fold_id_raw)

    return OosWindow(
        fold_id=fold_id,
        start=start,
        end=end,
        winner_variant_id=winner_id,
        winner_params=None,  # not in folds_json; resolve via representatives_json upstream
    )


def oos_windows_from_wfo(
    folds_json: Iterable[Mapping[str, Any]] | None,
    *,
    ohlcv_index: pd.DatetimeIndex | None = None,
) -> list[OosWindow]:
    """Parse `WfoSignalSummary.folds_json` into normalized OOS windows.

    Tolerates the production fold shape established in §4.1.a-finding:
    bar-index bounds, optional date keys, possibly-empty `winner_variant_id`.
    """
    if folds_json is None:
        return []
    out: list[OosWindow] = []
    for fold in folds_json:
        if not isinstance(fold, Mapping):
            continue
        w = _fold_to_window(fold, ohlcv_index)
        if w is not None:
            out.append(w)
    return out


def _date_union(windows: Iterable[OosWindow]) -> pd.DatetimeIndex:
    """Sorted, deduplicated union of all dates covered by `windows`."""
    parts: list[pd.DatetimeIndex] = []
    for w in windows:
        parts.append(pd.date_range(start=w.start, end=w.end, freq="B"))
    if not parts:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex(sorted(set().union(*[set(p) for p in parts])))


# ---------------------------------------------------------------------------
# Signal-engine path
# ---------------------------------------------------------------------------

def oos_sample_for_signal_engine(
    score_history_rows: Iterable[Mapping[str, Any]],
    *,
    horizon: Horizon,
    holdout_bars: int,
) -> OosSample:
    """Returns the terminal holdout sample for `source='signal_engine'`.

    Rules (§B.2 amendment):
    - If any row carries `is_oos=True`, restrict to those rows (post-migration).
    - Else fall back to the final `holdout_bars` distinct dates in the input.

    Caller is expected to pre-filter rows to `(symbol, horizon, source ∈
    {engine_legacy, engine_expanded})`. We do not re-filter here.
    """
    rows = [r for r in score_history_rows if r.get("date") is not None]
    rows.sort(key=lambda r: pd.Timestamp(r["date"]))

    flagged = [r for r in rows if bool(r.get("is_oos"))]
    if flagged:
        oos_dates = pd.DatetimeIndex(sorted({pd.Timestamp(r["date"]) for r in flagged}))
    else:
        all_dates = pd.DatetimeIndex(sorted({pd.Timestamp(r["date"]) for r in rows}))
        if holdout_bars <= 0 or len(all_dates) == 0:
            oos_dates = pd.DatetimeIndex([])
        else:
            oos_dates = all_dates[-int(holdout_bars):]

    if len(oos_dates) == 0:
        windows: tuple[OosWindow, ...] = ()
    else:
        windows = (OosWindow(
            fold_id=None,
            start=pd.Timestamp(oos_dates[0]),
            end=pd.Timestamp(oos_dates[-1]),
            winner_variant_id=None,
            winner_params=None,
        ),)

    return OosSample(
        source="signal_engine",
        horizon=horizon,
        windows=windows,
        dates=oos_dates,
        score_mode="terminal_holdout",
    )


# ---------------------------------------------------------------------------
# Top-level entry
# ---------------------------------------------------------------------------

def oos_sample_for(
    *,
    symbol: str,
    horizon: Horizon,
    source: Source,
    wfo_loader: Callable[[str, Horizon], Mapping[str, Any] | None] | None = None,
    score_history_loader: Callable[[str, Horizon], Iterable[Mapping[str, Any]]] | None = None,
    ohlcv_index_loader: Callable[[str], pd.DatetimeIndex | None] | None = None,
    holdout_bars: int = 0,
) -> OosSample:
    """Top-level entry; returns fold-scoped OOS windows + convenience date union.

    Loaders are injected (no DB I/O here) so this is testable with synthetic
    inputs. The endpoint layer (§A.2.b) is responsible for caching by
    `(symbol, horizon, source, content_hash)`.
    """
    if source == "wfo":
        if wfo_loader is None:
            raise ValueError("wfo_loader is required for source='wfo'")
        payload = wfo_loader(symbol, horizon) or {}
        folds = payload.get("folds_json") if isinstance(payload, Mapping) else None
        ohlcv_index = ohlcv_index_loader(symbol) if ohlcv_index_loader is not None else None
        windows = tuple(oos_windows_from_wfo(folds, ohlcv_index=ohlcv_index))
        return OosSample(
            source="wfo",
            horizon=horizon,
            windows=windows,
            dates=_date_union(windows),
            score_mode="fold_scoped_winner",
        )

    if source == "signal_engine":
        if score_history_loader is None:
            raise ValueError("score_history_loader is required for source='signal_engine'")
        rows = score_history_loader(symbol, horizon)
        return oos_sample_for_signal_engine(
            rows, horizon=horizon, holdout_bars=holdout_bars,
        )

    raise ValueError(f"unknown source: {source!r}")
