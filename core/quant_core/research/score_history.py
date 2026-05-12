"""Per-bar signal score reconstruction + bucketed predictive-ability metrics.

The signal engine and WFO only persist the *current-bar* score per
(symbol, family/category, horizon, variant). To evaluate predictive ability
we need the historical per-bar score series. This module rebuilds that
series by replaying the chosen representative variants over the full
historical close array, then computes bucket × forward-horizon stats
(mean return, bootstrap CI, hit rate with Wilson CI).

Backbone:
    - compute_variant_signal_array (core/quant_core/signal_engine/variant_detail.py)
        returns per-bar {-1, 0, +1} signals for one variant.
    - representatives_json (DB) gives the chosen variants + weights.
    - reuses wilson_ci, stationary_bootstrap_ci from research.stats.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np
import pandas as pd

from ..signal_engine.domain import (
    CATEGORY_FAMILIES,
    VARIANT_FAMILIES,
    LEGACY_CATEGORY_FAMILIES,
    FactorConditionMeta,
    VariantDef,
)
from ..signal_engine.modes import signal_mode_storage_name
from ..signal_engine.variant_detail import compute_variant_signal_array
from .stats.hit_rate import wilson_ci
from .stats.robustness import stationary_bootstrap_ci


# ---------------------------------------------------------------------------
# Bucket definitions (user-specified thresholds)
# ---------------------------------------------------------------------------

BUCKET_NAMES = ("strong_sell", "sell", "hold", "buy", "strong_buy")
BUCKET_EDGES = (-math.inf, -50.0, -15.0, 15.0, 50.0, math.inf)


def _bucket_for(score: float) -> str:
    if score < -50:
        return "strong_sell"
    if score < -15:
        return "sell"
    if score <= 15:
        return "hold"
    if score <= 50:
        return "buy"
    return "strong_buy"


# ---------------------------------------------------------------------------
# Variant reconstruction from representatives_json
# ---------------------------------------------------------------------------

def _variant_from_rep(rep: dict[str, Any]) -> VariantDef | None:
    """Rebuild a VariantDef from a JSON-serialized representative dict."""
    variant_id = str(rep.get("variant_id") or "").strip()
    family = str(rep.get("family") or "").strip()
    archetype = str(rep.get("archetype") or "").strip()
    if not variant_id or not family or not archetype:
        return None
    params = rep.get("params") or {}
    if not isinstance(params, dict):
        return None
    factor_condition = None
    raw_condition = rep.get("factor_condition")
    if isinstance(raw_condition, dict):
        try:
            factor_condition = FactorConditionMeta(
                condition_id=str(raw_condition["condition_id"]),
                factor_ticker=str(raw_condition["factor_ticker"]),
                form=str(raw_condition["form"]),
                lookback=int(raw_condition["lookback"]),
                threshold=float(raw_condition["threshold"]),
                direction=str(raw_condition["direction"]),
            )
        except Exception:
            factor_condition = None
    return VariantDef(
        variant_id=variant_id,
        family=family,
        archetype=archetype,
        params=dict(params),
        description=str(rep.get("description") or ""),
        factor_condition=factor_condition,
    )


def _weighted_family_signal(
    representatives: list[dict[str, Any]],
    *,
    close: np.ndarray,
    volume: np.ndarray | None,
    high: np.ndarray | None,
    low: np.ndarray | None,
    precomputed_signals: dict[str, np.ndarray] | None = None,
) -> np.ndarray | None:
    """Combine representative variants into a per-bar family score in [-100, +100]."""
    n = len(close)
    if n == 0 or not representatives:
        return None

    weighted = np.zeros(n, dtype="float64")
    total_w = 0.0
    any_signal = False
    precomputed = precomputed_signals or {}

    for rep in representatives:
        variant = _variant_from_rep(rep)
        if variant is None:
            continue
        w_raw = rep.get("reliability_weight")
        if w_raw is None or (isinstance(w_raw, float) and math.isnan(w_raw)):
            w_raw = rep.get("normalized_weight") or 1.0
        try:
            w = max(float(w_raw), 1e-9)
        except (TypeError, ValueError):
            w = 1.0
        try:
            if variant.variant_id in precomputed:
                sig = np.asarray(precomputed[variant.variant_id], dtype="float64")
            elif variant.factor_condition is not None or variant.family.endswith("@fx"):
                continue
            else:
                sig = compute_variant_signal_array(
                    close, variant, volume=volume, high=high, low=low,
                )
        except Exception:
            continue
        if len(sig) != n:
            continue
        weighted += w * sig
        total_w += w
        any_signal = True

    if not any_signal or total_w <= 0:
        return None

    return (weighted / total_w) * 100.0


# ---------------------------------------------------------------------------
# Engine + WFO category series builders
# ---------------------------------------------------------------------------

def _category_for_variant(variant: str) -> dict[str, list[str]]:
    try:
        return VARIANT_FAMILIES[signal_mode_storage_name(variant)]
    except Exception:
        return LEGACY_CATEGORY_FAMILIES if variant == "legacy" else CATEGORY_FAMILIES


def build_engine_category_series(
    *,
    symbol: str,
    horizon: str,
    variant: str,
    close: np.ndarray,
    volume: np.ndarray | None,
    high: np.ndarray | None,
    low: np.ndarray | None,
    family_rows: dict[str, list[dict[str, Any]]],
    index: pd.DatetimeIndex,
    precomputed_signals: dict[str, np.ndarray] | None = None,
) -> dict[str, pd.Series]:
    """For each category, build the per-bar aggregated score series.

    `family_rows` maps family_id -> list of representative dicts (from
    SignalEngineFamilyResult.representatives_json).

    Returns {category: pd.Series indexed by `index`} with values in [-100, +100].
    """
    cat_map = _category_for_variant(variant)
    out: dict[str, pd.Series] = {}
    for category, families in cat_map.items():
        family_series: list[np.ndarray] = []
        for fam in families:
            reps = family_rows.get(fam) or []
            sig = _weighted_family_signal(
                reps, close=close, volume=volume, high=high, low=low,
                precomputed_signals=precomputed_signals,
            )
            if sig is not None:
                family_series.append(sig)
        if not family_series:
            continue
        stacked = np.vstack(family_series)
        cat_score = stacked.mean(axis=0)
        out[category] = pd.Series(cat_score, index=index, name=category)
    return out


def build_wfo_category_series(
    *,
    symbol: str,
    horizon: str,
    close: np.ndarray,
    volume: np.ndarray | None,
    high: np.ndarray | None,
    low: np.ndarray | None,
    category_reps: dict[str, list[dict[str, Any]]],
    index: pd.DatetimeIndex,
    precomputed_signals: dict[str, np.ndarray] | None = None,
) -> dict[str, pd.Series]:
    """Build per-category WFO score series from picked representatives.

    `category_reps` maps category -> WfoSignalSummary.representatives_json (list).
    Output values are continuous in [-100, +100] (weighted ensemble signal).
    """
    out: dict[str, pd.Series] = {}
    for category, reps in category_reps.items():
        sig = _weighted_family_signal(
            reps, close=close, volume=volume, high=high, low=low,
            precomputed_signals=precomputed_signals,
        )
        if sig is None:
            continue
        out[category] = pd.Series(sig, index=index, name=category)
    return out


# ---------------------------------------------------------------------------
# Bucketed forward-return analytics
# ---------------------------------------------------------------------------

def _strip_tz(s: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    """Return series/frame with a tz-naive DatetimeIndex (strips timezone if present)."""
    if isinstance(s.index, pd.DatetimeIndex) and s.index.tz is not None:
        return s.set_axis(s.index.tz_localize(None))
    return s


def _calculate_forward_returns(
    prices: pd.Series | pd.DataFrame, h: int, method: str = "close_to_close"
) -> pd.Series:
    """Centralized forward-return logic for multiple entry/exit modes.

    Standard EOD Shift (Signal at T):
    - close_to_close: Entry Close(T), Exit Close(T+h)
    - open_to_open: Entry Open(T+1), Exit Open(T+h+1)
    - close_to_open: Entry Close(T), Exit Open(T+h)
    - open_to_close: Entry Open(T+1), Exit Close(T+h)
    """
    if isinstance(prices, pd.Series):
        if method != "close_to_close":
            # If we only have one series, we can't do open/close crosses reliably
            # unless we assume it's one of them. For backward compatibility,
            # we allow close_to_close.
            return prices.pct_change(h).shift(-h)
        return prices.pct_change(h).shift(-h)

    # prices is a DataFrame
    p = prices.copy()
    p.columns = [str(c).lower() for c in p.columns]

    # Ensure we have close and open
    if "close" not in p.columns:
        if "adj close" in p.columns:
            p["close"] = p["adj close"]
        else:
            p["close"] = p.iloc[:, 0]
    if "open" not in p.columns:
        p["open"] = p["close"]

    if method == "close_to_close":
        return p["close"].pct_change(h).shift(-h)
    elif method == "open_to_open":
        # Entry: Open(T+1), Exit: Open(T+h+1)
        return (p["open"].shift(-(h + 1)) / p["open"].shift(-1)) - 1
    elif method == "close_to_open":
        # Entry: Close(T), Exit: Open(T+h)
        return (p["open"].shift(-h) / p["close"]) - 1
    elif method == "open_to_close":
        # Entry: Open(T+1), Exit: Close(T+h)
        return (p["close"].shift(-h) / p["open"].shift(-1)) - 1
    else:
        # Fallback to close_to_close
        return p["close"].pct_change(h).shift(-h)


def bucketed_forward_returns(
    score_series: pd.Series,
    prices: pd.Series | pd.DataFrame,
    fwd_horizons: Iterable[int],
    *,
    n_bootstrap: int = 5000,
    return_calc_method: str = "close_to_close",
    oos_dates: pd.DatetimeIndex | None = None,
    recent_window: tuple[int, int] | None = None,
    max_lookback_years: float | None = None,
) -> list[dict[str, Any]]:
    """For each (bucket, fwd_h) cell, return mean / CI / hit-rate metrics.

    score_series: continuous [-100, +100] indexed by date.
    prices: close prices Series or OHLC DataFrame indexed by date.
    fwd_horizons: list of forward-return horizons in trading days.
    return_calc_method: 'close_to_close' | 'open_to_open' | 'close_to_open' | 'open_to_close'
    oos_dates: if given, restrict the aligned index to these dates only
        (Edge-OOS path; defaults to None = full series, preserving legacy callers).
    recent_window: (n_min, n_target). If set, after the OOS filter, take the
        most recent up to n_target obs per (bucket, fwd_h) cell. If the cell
        ends up with fewer than n_min obs, emit an empty cell with the
        truncated n.
    max_lookback_years: hard ceiling on the aligned index measured from its
        max date. None = no ceiling.
    Returns a list of cell dicts, one per (bucket, fwd_h).
    """
    score_series = _strip_tz(score_series)
    prices = _strip_tz(prices)
    cells: list[dict[str, Any]] = []

    if score_series.name is None:
        score_series = score_series.rename("score")

    # For alignment, we just need the index.
    # _calculate_forward_returns handles the specific logic.
    if isinstance(prices, pd.Series):
        aligned_idx = pd.concat([score_series, prices], axis=1).dropna().index
    else:
        aligned_idx = pd.concat([score_series, prices], axis=1).dropna(subset=[score_series.name]).index

    if oos_dates is not None:
        aligned_idx = aligned_idx.intersection(pd.DatetimeIndex(oos_dates))
    if max_lookback_years is not None and len(aligned_idx) > 0:
        cutoff = aligned_idx.max() - pd.Timedelta(days=int(365.25 * max_lookback_years))
        aligned_idx = aligned_idx[aligned_idx >= cutoff]

    if len(aligned_idx) < 20:
        return cells

    score = score_series.loc[aligned_idx]
    # Pre-compute bucket assignments once (a numeric category column)
    buckets = score.apply(_bucket_for).rename("bucket")

    for h in fwd_horizons:
        h = int(h)
        fwd = _calculate_forward_returns(prices, h, method=return_calc_method)
        df = pd.concat([score, fwd, buckets], axis=1, keys=["score", "fwd", "bucket"]).dropna()
        if oos_dates is not None and not df.empty:
            oos_idx = pd.DatetimeIndex(oos_dates)
            exit_idx = df.index.map(lambda ts: _forward_exit_date(prices.index, pd.Timestamp(ts), h, return_calc_method))
            exit_mask = pd.DatetimeIndex(exit_idx).isin(oos_idx)
            df = df.loc[exit_mask]
        if df.empty:
            for b in BUCKET_NAMES:
                cells.append(_empty_cell(b, h))
            continue

        for b in BUCKET_NAMES:
            sub = df[df["bucket"] == b]
            if recent_window is not None:
                n_min, n_target = recent_window
                sub = sub.sort_index().tail(int(n_target))
                if len(sub) < int(n_min):
                    cells.append(_empty_cell(b, h, n=int(len(sub))))
                    continue
            n = int(len(sub))
            if n < 5:
                cells.append(_empty_cell(b, h, n=n))
                continue

            r = sub["fwd"].to_numpy(dtype="float64")
            mean = float(np.mean(r))
            std = float(np.std(r, ddof=1)) if n > 1 else 0.0

            # Hit rate: % positive for buy buckets, % negative for sell buckets,
            # and overall directional accuracy for hold (both directions count).
            if b in ("buy", "strong_buy"):
                hits = int(np.sum(r > 0))
            elif b in ("sell", "strong_sell"):
                hits = int(np.sum(r < 0))
            else:
                hits = int(np.sum(np.abs(r) < std)) if std > 0 else 0
            hit_rate = hits / n
            hit_lo, hit_hi = wilson_ci(hits, n)

            # Bootstrap CI on the mean
            try:
                ci_lo, ci_hi = stationary_bootstrap_ci(
                    r, lambda v: float(np.mean(v)) if len(v) else float("nan"),
                    n_bootstrap=n_bootstrap,
                )
            except Exception:
                ci_lo, ci_hi = float("nan"), float("nan")

            sub_idx = sub.index
            window_start = pd.Timestamp(sub_idx.min()).date().isoformat()
            window_end = pd.Timestamp(sub_idx.max()).date().isoformat()
            lookback_business_days = int(len(pd.bdate_range(sub_idx.min(), sub_idx.max())))

            cells.append({
                "bucket": b,
                "fwd_h": h,
                "n": n,
                "mean": _finite(mean),
                "std": _finite(std),
                "ci_lower": _finite(ci_lo),
                "ci_upper": _finite(ci_hi),
                "hit_rate": _finite(hit_rate),
                "hit_ci_lower": _finite(hit_lo),
                "hit_ci_upper": _finite(hit_hi),
                "window_start": window_start,
                "window_end": window_end,
                "lookback_business_days": lookback_business_days,
            })

    return cells


def _empty_cell(bucket: str, h: int, n: int = 0) -> dict[str, Any]:
    return {
        "bucket": bucket, "fwd_h": int(h), "n": int(n),
        "mean": None, "std": None,
        "ci_lower": None, "ci_upper": None,
        "hit_rate": None, "hit_ci_lower": None, "hit_ci_upper": None,
        "window_start": None, "window_end": None, "lookback_business_days": None,
    }


def _forward_exit_date(
    price_index: pd.Index,
    entry_date: pd.Timestamp,
    h: int,
    method: str,
) -> pd.Timestamp | pd.NaT:
    """Return the price-index date used as the forward-return exit bar."""
    idx = pd.DatetimeIndex(price_index)
    try:
        pos = idx.get_loc(entry_date)
    except KeyError:
        return pd.NaT
    if not isinstance(pos, (int, np.integer)):
        return pd.NaT
    offset = h + 1 if method == "open_to_open" else h
    exit_pos = int(pos) + int(offset)
    if exit_pos < 0 or exit_pos >= len(idx):
        return pd.NaT
    return pd.Timestamp(idx[exit_pos])


def _finite(v: float) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# ---------------------------------------------------------------------------
# Subset aggregation helper
# ---------------------------------------------------------------------------

def aggregate_subset(
    category_series: dict[str, pd.Series],
    categories: Iterable[str],
) -> pd.Series | None:
    """Mean across the requested category subset (skips missing categories)."""
    selected = [category_series[c] for c in categories if c in category_series]
    if not selected:
        return None
    df = pd.concat(selected, axis=1)
    return df.mean(axis=1)


# ---------------------------------------------------------------------------
# Information Coefficient + HAC t-stat (overall predictive ability)
# ---------------------------------------------------------------------------

def ic_table(
    score_series: pd.Series,
    prices: pd.Series | pd.DataFrame,
    fwd_horizons: Iterable[int],
    *,
    return_calc_method: str = "close_to_close",
) -> tuple[dict[int, float | None], dict[int, float | None], int]:
    """Spearman IC + Newey-West t-stat at each forward horizon.

    Returns (ic_by_h, tstat_by_h, n_aligned). t-stat uses HAC variance of
    the per-bar standardized rank-product to absorb autocorrelation in
    overlapping forward returns (bandwidth = max(h, default rule)).
    """
    from .stats.ic import _newey_west_var, _spearman_corr

    score_series = _strip_tz(score_series)
    prices = _strip_tz(prices)

    if score_series.name is None:
        score_series = score_series.rename("score")

    if isinstance(prices, pd.Series):
        aligned_idx = pd.concat([score_series, prices], axis=1).dropna().index
    else:
        aligned_idx = pd.concat([score_series, prices], axis=1).dropna(subset=[score_series.name]).index

    if len(aligned_idx) < 30:
        return {}, {}, int(len(aligned_idx))

    score = score_series.loc[aligned_idx]
    ic_out: dict[int, float | None] = {}
    t_out: dict[int, float | None] = {}

    for h in fwd_horizons:
        h = int(h)
        fwd = _calculate_forward_returns(prices, h, method=return_calc_method)
        df = pd.concat([score, fwd], axis=1, keys=["s", "r"]).dropna()
        n = int(len(df))
        if n < 20:
            ic_out[h] = None
            t_out[h] = None
            continue

        ic = _spearman_corr(df["s"], df["r"])
        if ic != ic:  # nan
            ic_out[h] = None
            t_out[h] = None
            continue

        # HAC t-stat: per-bar product of standardized ranks has mean ≈ ic.
        ranks_s = df["s"].rank()
        ranks_r = df["r"].rank()
        zs = (ranks_s - ranks_s.mean()) / (ranks_s.std() or 1.0)
        zr = (ranks_r - ranks_r.mean()) / (ranks_r.std() or 1.0)
        prod = (zs * zr).to_numpy(dtype="float64")
        bandwidth = max(h, max(1, int(4 * (n / 100) ** (2 / 9))))
        nw_var = _newey_west_var(prod, bandwidth=bandwidth)
        if nw_var is None or nw_var != nw_var or nw_var <= 0:
            t = None
        else:
            t = ic / math.sqrt(nw_var)

        ic_out[h] = _finite(ic)
        t_out[h] = _finite(t) if t is not None else None

    return ic_out, t_out, int(aligned_idx.shape[0])
