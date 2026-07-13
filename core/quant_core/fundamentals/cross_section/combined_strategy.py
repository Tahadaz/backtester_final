"""Combined value x technical gated-vintage strategy engine — Phase 1 (engine
core + G0 parity).

This module is a *sibling* engine to `live_like_strategy.py`, not a
replacement or a copy. It reuses the incumbent's vintage machinery
(`LiveLikeConfig`, `VINTAGE_LIFE_MONTHS`, `summarize_performance`) and the
shared PIT price / turnover helpers from `portfolio_backtest.py`
(`_pit_price`, `one_way_turnover`) by import, never by duplicating their
logic.

Semantics (pre-registered in the Stage-1 research plan, 2026-07-12):

- G0 (no gate) reproduces `run_vintage_backtest` / `build_trade_ledger`
  bit-for-bit (locked by the parity tests in `test_combined_strategy.py`).
- Gate check at each monthly formation date: a value-selected name enters only
  if its gate stance is long (G1 trend / G2 honest-OOS WFO). A blocked name's
  reserved weight sits in CASH inside its vintage slice -- never redistributed
  -- so the gating cost/benefit is cleanly attributable.
- Late confirmation: a pending name is re-checked at each subsequent monthly
  step while `months_held < confirm_window_months`; it enters at its reserved
  weight on an explicit long stance (missing data never triggers a late entry).
- X1 exit overlay: a confirmed name whose gate stance flips explicitly to
  False at a monthly check is sold to cash for the remainder of its vintage
  (no re-entry). X0 ignores gate flips after entry. A vintage expiring this
  step is left to the normal expiry SELL (no same-month exit churn).
- Missing gate data at formation follows `missing_gate_policy` ("pass" =
  enter, i.e. uncovered names behave exactly as G0 -- the pre-registered
  default for the coverage-limited G2 gate; "block" = stay pending).
- Risk overlays (applied to each formation's intra-vintage weights BEFORE the
  engine runs, via `apply_overlays_to_holdings`): optional PIT-ADV eligibility
  floor (missing ADV passes), sector cap, max-single-name cap. Cap
  redistribution goes to uncapped names; if everything is capped the residual
  stays in cash (visible in `cash_weight`).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ...periods import MASI_PERIODS
from ...significance import monte_carlo_luck_test, sharpe_ratio
from .live_like_strategy import (  # noqa: F401  (summarize_performance re-exported for callers/tests)
    LiveLikeConfig,
    VINTAGE_LIFE_MONTHS,
    _tercile_holdings,
    summarize_performance,
)
from .portfolio_backtest import _apply_sector_cap, _max_drawdown, _pit_price, one_way_turnover

# ---------------------------------------------------------------------------
# Holdings builders (signal-only and rank-composite) -- for signals that are
# not one of the incumbent's canonical S1/S2/S3 strategies (e.g. momentum, or
# a value+momentum composite), reusing `_tercile_holdings`'s exact top-tercile
# arithmetic so results stay comparable to `build_vintage_holdings_by_date`.
# ---------------------------------------------------------------------------


def build_signal_holdings(
    panel: pd.DataFrame,
    *,
    signal_col: str,
    eligibility_col: str = "eligible_universe",
    config: LiveLikeConfig,
) -> dict[dt.date, dict[str, float]]:
    """Per as_of_date top-tercile holdings for a single PIT signal column:
    filters rows where `eligibility_col` is True AND `signal_col` is notna,
    then applies `_tercile_holdings`. Mirrors
    `build_vintage_holdings_by_date`'s shape/return type."""
    holdings_by_date: dict[dt.date, dict[str, float]] = {}
    for as_of, sub in panel.groupby("as_of_date"):
        eligible = sub[sub[eligibility_col].astype(bool) & sub[signal_col].notna()]
        holdings_by_date[pd.Timestamp(as_of).date()] = _tercile_holdings(
            eligible, signal_col, min_names=config.min_universe_names
        )
    return holdings_by_date


def build_rank_composite_holdings(
    panel: pd.DataFrame,
    *,
    components: list[tuple[str, float]],
    eligibility_cols: list[str],
    config: LiveLikeConfig,
) -> dict[dt.date, dict[str, float]]:
    """Per as_of_date top-tercile holdings on a weighted rank composite of
    multiple PIT signal columns. Filters rows where ALL `eligibility_cols`
    are True AND every component signal is notna; composite =
    sum(weight * pct_rank(signal)) using the same `rank(pct=True)`
    convention as `live_like_strategy._composite_score`, then top tercile via
    `_tercile_holdings` on the composite column."""
    holdings_by_date: dict[dt.date, dict[str, float]] = {}
    for as_of, sub in panel.groupby("as_of_date"):
        mask = pd.Series(True, index=sub.index)
        for col in eligibility_cols:
            mask &= sub[col].astype(bool)
        for signal_col, _weight in components:
            mask &= sub[signal_col].notna()
        eligible = sub[mask].copy()
        if eligible.empty:
            holdings_by_date[pd.Timestamp(as_of).date()] = {}
            continue
        composite = pd.Series(0.0, index=eligible.index)
        for signal_col, weight in components:
            composite = composite + weight * eligible[signal_col].rank(pct=True)
        eligible["_rank_composite"] = composite
        holdings_by_date[pd.Timestamp(as_of).date()] = _tercile_holdings(
            eligible, "_rank_composite", min_names=config.min_universe_names
        )
    return holdings_by_date


def build_graceful_composite_holdings(
    panel: pd.DataFrame,
    *,
    primary: tuple[str, float],
    secondary: tuple[str, float],
    eligibility_col: str,
    config: LiveLikeConfig,
) -> dict[dt.date, dict[str, float]]:
    """Per as_of_date top-tercile holdings on a "graceful" primary+secondary
    composite (value-momentum study v2): the universe requires only the
    PRIMARY signal -- `eligibility_col` True AND the primary signal notna.
    The secondary signal is deliberately NOT required for universe membership
    (that is the point of "graceful" integration vs
    `build_rank_composite_holdings`'s hard intersection requirement): a name
    missing the secondary signal stays in the universe and is scored on the
    primary signal alone via neutral imputation.

    `primary_rank` = pct rank of the primary signal over the WHOLE universe.
    `secondary_rank` = pct rank of the secondary signal computed only among
    the subset of the universe where it is notna, then reindexed onto the
    full universe with missing values imputed at 0.5 (the cross-sectional
    neutral rank -- neither rewards nor penalizes a name for lacking
    secondary data). composite = w_primary * primary_rank + w_secondary *
    secondary_rank_imputed. Top tercile via `_tercile_holdings` on the
    composite column (same convention as `build_rank_composite_holdings`).
    """
    primary_col, w_primary = primary
    secondary_col, w_secondary = secondary
    holdings_by_date: dict[dt.date, dict[str, float]] = {}
    for as_of, sub in panel.groupby("as_of_date"):
        universe = sub[sub[eligibility_col].astype(bool) & sub[primary_col].notna()].copy()
        if universe.empty:
            holdings_by_date[pd.Timestamp(as_of).date()] = {}
            continue
        primary_rank = universe[primary_col].rank(pct=True)
        secondary_notna = universe[secondary_col].notna()
        secondary_rank = pd.Series(0.5, index=universe.index)
        if secondary_notna.any():
            secondary_rank.loc[secondary_notna] = universe.loc[secondary_notna, secondary_col].rank(pct=True)
        universe["_graceful_composite"] = w_primary * primary_rank + w_secondary * secondary_rank
        holdings_by_date[pd.Timestamp(as_of).date()] = _tercile_holdings(
            universe, "_graceful_composite", min_names=config.min_universe_names
        )
    return holdings_by_date


# Event ledger action constants. BUY/SELL are used by Phase 1 (G0 path);
# LATE_BUY/GATE_BLOCK/EARLY_EXIT are defined now (per spec) so downstream
# code/tests can reference stable names, but Phase 1 never emits them --
# they're wired up when gating (Phase 2) lands.
ACTION_BUY = "BUY"
ACTION_SELL = "SELL"
ACTION_LATE_BUY = "LATE_BUY"
ACTION_GATE_BLOCK = "GATE_BLOCK"
ACTION_EARLY_EXIT = "EARLY_EXIT"


@dataclass(frozen=True)
class CombinedConfig:
    base: LiveLikeConfig = field(default_factory=LiveLikeConfig)
    gate: str = "G1"  # "G0" | "G1" | "G2"
    g1_rule: str = "either"  # "sma" | "momentum" | "either"
    g1_sma_days: int = 210
    g1_mom_formation_days: int = 231
    g1_mom_skip_days: int = 21
    confirm_window_months: int = 2
    exit_mode: str = "X1"  # "X0" | "X1"
    sector_cap: float | None = 0.30
    max_name_weight: float | None = 0.10
    adv_floor_mad: float | None = None
    wfo_long_threshold: float = 20.0
    missing_gate_policy: str = "pass"  # "pass" | "block"
    # G2 only: a stitched-OOS WFO stance older than this many calendar days at
    # the check date is treated as MISSING (policy applies) rather than carried
    # forward -- PIT hygiene so a months-stale fold signal can't gate a trade.
    g2_max_staleness_days: int = 45


@dataclass
class GatedVintageState:
    formed_date: dt.date
    reserved: dict[str, float]  # symbol -> original formation weight (intra-vintage, sums to 1.0)
    confirmed: dict[str, float]  # symbol -> currently held weight (intra-vintage)
    pending: dict[str, float]  # symbol -> awaiting gate confirmation (blocked at formation, still within confirm window)
    exited: dict[str, float]  # symbol -> early-exited to cash (X1), never re-enters this vintage
    months_held: int = 0


def _gate_lookup(series: pd.Series | None, as_of: dt.date, *, max_staleness_days: int | None = None) -> bool | None:
    """As-of lookup of a gate series (float 1.0/0.0 with NaN = undefined).

    Returns True/False for a defined stance at the latest bar <= as_of, or
    None when no defined value exists yet (or the latest defined value is
    older than `max_staleness_days` calendar days -- used for the sparse G2
    OOS series so a months-stale fold stance is treated as missing)."""
    if series is None:
        return None
    defined = series.dropna()
    if defined.empty:
        return None
    ts = pd.Timestamp(as_of)
    idx = defined.index.searchsorted(ts, side="right") - 1
    if idx < 0:
        return None
    if max_staleness_days is not None and (ts - defined.index[idx]).days > max_staleness_days:
        return None
    return bool(float(defined.iloc[idx]) > 0.5)


def _gate_stance(symbol: str, as_of: dt.date, *, gate_by_symbol: dict[str, pd.Series] | None, config: CombinedConfig) -> bool | None:
    """Raw gate stance for `symbol` as of `as_of`: True (long-ok), False
    (blocked), or None (no gate data -- `missing_gate_policy` decides entry;
    None never triggers an exit or a late entry)."""
    series = (gate_by_symbol or {}).get(symbol)
    staleness = config.g2_max_staleness_days if config.gate == "G2" else None
    return _gate_lookup(series, as_of, max_staleness_days=staleness)


def _entry_allowed(stance: bool | None, config: CombinedConfig) -> bool:
    if stance is None:
        return config.missing_gate_policy == "pass"
    return stance


def _combined_weights_from_states(active: list[GatedVintageState]) -> dict[str, float]:
    combined: dict[str, float] = {}
    for state in active:
        for sym, w in state.confirmed.items():
            combined[sym] = combined.get(sym, 0.0) + w / VINTAGE_LIFE_MONTHS
    return combined


def run_gated_vintage_backtest(
    holdings_by_date: dict[dt.date, dict[str, float]],
    *,
    price_by_symbol: dict[str, pd.Series | None],
    gate_by_symbol: dict[str, pd.Series] | None = None,
    config: CombinedConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Gated sibling of `run_vintage_backtest`. Mirrors its loop order and
    arithmetic exactly for the G0 (no-gate) path:

      1. realize this period's return from vintages active BEFORE today
         (confirmed holdings only; skip i==0), counting stale price events
         via `_pit_price` the same way the incumbent does;
      2. age all active vintages by 1 month, expire those reaching
         VINTAGE_LIFE_MONTHS;
      3. form today's new vintage (enters next period) -- in G0 (or when
         `gate_by_symbol` is None / `config.gate == "G0"`), every formed name
         goes straight to `confirmed`; `pending`/`exited` stay empty.

    Combined weights = sum of confirmed-holding weights / VINTAGE_LIFE_MONTHS
    over active vintages. Turnover/cost use the same one_way_turnover +
    (cost_bps/10000)*2.0*turnover convention as the incumbent, applied to the
    combined weight vector (i.e., reflecting confirmed exposure only).

    With a gate active, formation routes names failing `_entry_allowed` to
    `pending` (weight in cash, GATE_BLOCK event); monthly gate re-checks run
    between return realization and aging (late confirmation within
    `confirm_window_months` on an explicit long stance -> LATE_BUY; X1 early
    exit on an explicit False stance -> EARLY_EXIT, cash until expiry).
    Extra columns: `cash_weight`, `gate_blocked_weight`, `n_pending` (stocks
    at month end) and `n_confirmed_late`, `n_early_exits` (flows this month).
    """
    no_gate = gate_by_symbol is None or config.gate == "G0"

    dates = sorted(holdings_by_date)
    active: list[GatedVintageState] = []
    prev_combined: dict[str, float] = {}
    rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    for i, as_of in enumerate(dates):
        # 1. realize this period's return using vintages active BEFORE today's
        #    formation (confirmed holdings only), held over (prev_date, as_of].
        if i == 0:
            period_return = 0.0
            n_stale = 0
        else:
            start, end = dates[i - 1], as_of
            period_return = 0.0
            n_stale = 0
            for state in active:
                vintage_weight = 1.0 / VINTAGE_LIFE_MONTHS
                vintage_ret = 0.0
                for sym, w in state.confirmed.items():
                    p0, p0_date = _pit_price(price_by_symbol.get(sym), start)
                    p1, p1_date = _pit_price(price_by_symbol.get(sym), end)
                    if p0 is None or p1 is None:
                        continue
                    if p0_date != start or p1_date != end:
                        n_stale += 1
                    vintage_ret += w * (p1 / p0 - 1.0)
                period_return += vintage_weight * vintage_ret

        # Gate re-checks at today's date, BEFORE aging: the return over
        # (prev_date, as_of] was realized above with the OLD confirmed
        # holdings; exits/late entries decided now take effect for the NEXT
        # period, mirroring formation semantics. Vintages expiring this step
        # are skipped (their normal expiry SELL below handles them).
        n_confirmed_late = 0
        n_early_exits = 0
        if not no_gate:
            for state in active:
                if state.months_held + 1 >= VINTAGE_LIFE_MONTHS:
                    continue
                # X1 early exits first, so a name late-confirmed this month is
                # not immediately exit-checked against the same stance.
                if config.exit_mode == "X1" and state.confirmed:
                    for sym in sorted(state.confirmed):
                        if _gate_stance(sym, as_of, gate_by_symbol=gate_by_symbol, config=config) is False:
                            w = state.confirmed.pop(sym)
                            state.exited[sym] = w
                            n_early_exits += 1
                            events.append(
                                {
                                    "date": as_of,
                                    "action": ACTION_EARLY_EXIT,
                                    "symbol": sym,
                                    "vintage_formed": state.formed_date,
                                    "weight": w / VINTAGE_LIFE_MONTHS,
                                }
                            )
                # Late confirmation while inside the confirm window; requires
                # an EXPLICIT long stance (missing data never late-enters).
                if state.pending and state.months_held < config.confirm_window_months:
                    for sym in sorted(state.pending):
                        if _gate_stance(sym, as_of, gate_by_symbol=gate_by_symbol, config=config) is True:
                            w = state.pending.pop(sym)
                            state.confirmed[sym] = w
                            n_confirmed_late += 1
                            events.append(
                                {
                                    "date": as_of,
                                    "action": ACTION_LATE_BUY,
                                    "symbol": sym,
                                    "vintage_formed": state.formed_date,
                                    "weight": w / VINTAGE_LIFE_MONTHS,
                                }
                            )

        # 2. age active vintages by one month, expire any that reached VINTAGE_LIFE_MONTHS
        for state in active:
            state.months_held += 1
        expiring = [state for state in active if state.months_held >= VINTAGE_LIFE_MONTHS]
        active = [state for state in active if state.months_held < VINTAGE_LIFE_MONTHS]
        for state in expiring:
            for sym, w in sorted(state.confirmed.items()):
                events.append(
                    {
                        "date": as_of,
                        "action": ACTION_SELL,
                        "symbol": sym,
                        "vintage_formed": state.formed_date,
                        "weight": w / VINTAGE_LIFE_MONTHS,
                    }
                )

        # 3. form a new vintage from today's holdings (enters starting next period)
        new_holdings = holdings_by_date[as_of]
        if new_holdings:
            if no_gate:
                confirmed = dict(new_holdings)
                pending: dict[str, float] = {}
            else:
                confirmed = {}
                pending = {}
                for sym, w in sorted(new_holdings.items()):
                    stance = _gate_stance(sym, as_of, gate_by_symbol=gate_by_symbol, config=config)
                    if _entry_allowed(stance, config):
                        confirmed[sym] = w
                    else:
                        pending[sym] = w
                        events.append(
                            {
                                "date": as_of,
                                "action": ACTION_GATE_BLOCK,
                                "symbol": sym,
                                "vintage_formed": as_of,
                                "weight": w / VINTAGE_LIFE_MONTHS,
                            }
                        )
            new_state = GatedVintageState(
                formed_date=as_of,
                reserved=dict(new_holdings),
                confirmed=confirmed,
                pending=pending,
                exited={},
                months_held=0,
            )
            active.append(new_state)
            for sym, w in sorted(confirmed.items()):
                events.append(
                    {
                        "date": as_of,
                        "action": ACTION_BUY,
                        "symbol": sym,
                        "vintage_formed": as_of,
                        "weight": w / VINTAGE_LIFE_MONTHS,
                    }
                )

        combined = _combined_weights_from_states(active)
        turnover = one_way_turnover(prev_combined, combined)
        cost = (config.base.cost_bps / 10000.0) * 2.0 * turnover if i > 0 else 0.0
        net_return = period_return - cost

        # Stocks at month end: n_pending / gate_blocked_weight. Flows this
        # month: n_confirmed_late / n_early_exits (set in the gate-check block
        # above; zero in G0).
        n_pending = sum(len(state.pending) for state in active)
        gate_blocked_weight = sum(
            w / VINTAGE_LIFE_MONTHS for state in active for w in state.pending.values()
        )
        cash_weight = 1.0 - sum(combined.values())

        rows.append(
            {
                "as_of_date": as_of,
                "n_active_vintages": len(active),
                "n_holdings": len(combined),
                "gross_return": period_return,
                "turnover": turnover,
                "cost": cost,
                "net_return": net_return,
                "stale_price_events": n_stale,
                "cash_weight": cash_weight,
                "n_pending": n_pending,
                "n_confirmed_late": n_confirmed_late,
                "n_early_exits": n_early_exits,
                "gate_blocked_weight": gate_blocked_weight,
            }
        )
        prev_combined = combined

    monthly = pd.DataFrame(
        rows,
        columns=[
            "as_of_date",
            "n_active_vintages",
            "n_holdings",
            "gross_return",
            "turnover",
            "cost",
            "net_return",
            "stale_price_events",
            "cash_weight",
            "n_pending",
            "n_confirmed_late",
            "n_early_exits",
            "gate_blocked_weight",
        ],
    )
    events_df = pd.DataFrame(
        events,
        columns=["date", "action", "symbol", "vintage_formed", "weight"],
    )
    return monthly, events_df


# ---------------------------------------------------------------------------
# Gate builders
# ---------------------------------------------------------------------------


def _clean_close(series: pd.Series | None) -> pd.Series | None:
    if series is None:
        return None
    close = pd.to_numeric(series, errors="coerce").dropna()
    if close.empty:
        return None
    close = close.sort_index()
    return close.groupby(level=0).last()


def build_trend_gate_series(
    close_by_symbol: dict[str, pd.Series | None],
    config: CombinedConfig,
) -> dict[str, pd.Series]:
    """G1 trend gate: per-symbol daily float series (1.0 long-ok / 0.0 blocked /
    NaN undefined during indicator warm-up).

    - "sma": close > rolling SMA over `g1_sma_days` trading bars (full window
      required; NaN until then).
    - "momentum": 12-1 momentum > 0, i.e. return over `g1_mom_formation_days`
      trading bars ending `g1_mom_skip_days` bars ago (positional shifts on the
      trading-bar index; NaN until both prices exist).
    - "either": OR with NaN-aware semantics -- 1 if either rule fires, 0 only
      if all defined rules say 0, NaN when both are undefined.

    Strictly point-in-time: every value at bar t uses closes up to t only.
    """
    if config.g1_rule not in {"sma", "momentum", "either"}:
        raise ValueError(f"unknown g1_rule {config.g1_rule!r}")
    out: dict[str, pd.Series] = {}
    for symbol, raw in close_by_symbol.items():
        close = _clean_close(raw)
        if close is None:
            continue
        parts: list[pd.Series] = []
        if config.g1_rule in {"sma", "either"}:
            sma = close.rolling(config.g1_sma_days, min_periods=config.g1_sma_days).mean()
            parts.append((close > sma).astype(float).where(sma.notna()))
        if config.g1_rule in {"momentum", "either"}:
            p_end = close.shift(config.g1_mom_skip_days)
            p_start = close.shift(config.g1_mom_skip_days + config.g1_mom_formation_days)
            mom = p_end / p_start - 1.0
            parts.append((mom > 0.0).astype(float).where(mom.notna()))
        if len(parts) == 1:
            gate = parts[0]
        else:
            # max() with skipna: (1,NaN)->1, (0,NaN)->0, (NaN,NaN)->NaN
            gate = pd.concat(parts, axis=1).max(axis=1)
        out[symbol] = gate.rename(symbol)
    return out


def aggregate_wfo_gate(
    scores: pd.DataFrame,
    *,
    threshold: float = 20.0,
    min_categories: int = 1,
) -> dict[str, pd.Series]:
    """G2 gate from honest stitched-OOS WFO category scores.

    `scores` is long-format with columns (date, symbol, category, score_pct),
    pre-filtered by the caller to `is_oos=True` rows only (that filter is what
    makes the gate point-in-time honest -- each bar's score comes from the
    fold-local winner trained strictly before its OOS window).

    Pre-registered aggregation: equal-weight mean of the category scores
    available on a date (the product's live fitted category weights are NOT
    used -- they are fitted on the latest full run and would leak); stance =
    1.0 iff mean >= threshold. Dates with fewer than `min_categories` defined
    categories are NaN (undefined).
    """
    required = {"date", "symbol", "category", "score_pct"}
    missing = required - set(scores.columns)
    if missing:
        raise ValueError(f"scores frame missing columns: {sorted(missing)}")
    out: dict[str, pd.Series] = {}
    if scores.empty:
        return out
    frame = scores.copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.tz_localize(None).dt.normalize()
    frame["score_pct"] = pd.to_numeric(frame["score_pct"], errors="coerce")
    for symbol, sub in frame.groupby("symbol"):
        pivot = sub.pivot_table(index="date", columns="category", values="score_pct", aggfunc="mean")
        n_defined = pivot.notna().sum(axis=1)
        mean_score = pivot.mean(axis=1)
        gate = (mean_score >= threshold).astype(float).where(n_defined >= min_categories)
        out[str(symbol).strip().upper()] = gate.sort_index().rename(str(symbol))
    return out


# ---------------------------------------------------------------------------
# Risk overlays (applied to intra-vintage formation weights BEFORE the engine)
# ---------------------------------------------------------------------------


def compute_pit_adv_series(
    price_frames: dict[str, pd.DataFrame],
    *,
    window: int = 20,
    min_obs: int = 10,
) -> dict[str, pd.Series]:
    """Rolling PIT dirham ADV per symbol: mean(Volume*Close) over the last
    `window` bars, requiring `min_obs` defined observations -- the same
    formula as `characteristic_study._risk_stats`' adv20, as a full series."""
    out: dict[str, pd.Series] = {}
    for symbol, df in price_frames.items():
        if df is None or "Volume" not in df or "Close" not in df:
            continue
        vol = pd.to_numeric(df["Volume"], errors="coerce")
        px = pd.to_numeric(df["Close"], errors="coerce")
        dollar = (vol * px).sort_index()
        dollar = dollar.groupby(level=0).last()
        adv = dollar.rolling(window, min_periods=min_obs).mean()
        out[str(symbol).strip().upper()] = adv.rename(symbol)
    return out


def pit_value(series: pd.Series | None, as_of: dt.date) -> float | None:
    """Latest defined value of `series` at a bar <= as_of, else None."""
    if series is None:
        return None
    defined = series.dropna()
    if defined.empty:
        return None
    idx = defined.index.searchsorted(pd.Timestamp(as_of), side="right") - 1
    if idx < 0:
        return None
    value = float(defined.iloc[idx])
    return value if np.isfinite(value) else None


def _apply_name_cap(weights: dict[str, float], cap: float) -> dict[str, float]:
    """Cap single-name weights, redistributing the freed weight to uncapped
    names proportionally; if every name is at the cap the shortfall stays in
    cash (weights then sum to < 1, surfaced by the engine's cash_weight)."""
    adjusted = dict(weights)
    for _ in range(8):
        over = {sym: w for sym, w in adjusted.items() if w > cap + 1e-12}
        if not over:
            break
        freed = sum(w - cap for w in over.values())
        for sym in over:
            adjusted[sym] = cap
        uncapped = [sym for sym in adjusted if sym not in over and adjusted[sym] < cap - 1e-12]
        uncapped_total = sum(adjusted[sym] for sym in uncapped)
        if freed <= 0 or uncapped_total <= 0:
            break
        scale = (uncapped_total + freed) / uncapped_total
        for sym in uncapped:
            adjusted[sym] *= scale
    return adjusted


def apply_risk_overlays(
    weights: dict[str, float],
    *,
    sector_map: dict[str, str | None],
    config: CombinedConfig,
    adv_by_symbol: dict[str, float | None] | None = None,
) -> dict[str, float]:
    """ADV eligibility floor (missing ADV passes; survivors renormalized to
    1.0), then iterated sector cap (reused `_apply_sector_cap`) + max-name cap
    until stable (each cap's redistribution can re-violate the other, so the
    pair is iterated; residual that cannot be redistributed stays cash)."""
    if not weights:
        return {}
    adjusted = dict(weights)
    if config.adv_floor_mad is not None and adv_by_symbol is not None:
        kept = {
            sym: w
            for sym, w in adjusted.items()
            if adv_by_symbol.get(sym) is None or float(adv_by_symbol[sym]) >= config.adv_floor_mad
        }
        if not kept:
            return {}
        total = sum(kept.values())
        adjusted = {sym: w / total for sym, w in kept.items()}
    for _ in range(4):
        before = dict(adjusted)
        if config.sector_cap is not None:
            adjusted = _apply_sector_cap(adjusted, sector_map, config.sector_cap)
        if config.max_name_weight is not None:
            adjusted = _apply_name_cap(adjusted, config.max_name_weight)
        if max(abs(adjusted.get(sym, 0.0) - before.get(sym, 0.0)) for sym in set(adjusted) | set(before)) < 1e-12:
            break
    return adjusted


def apply_overlays_to_holdings(
    holdings_by_date: dict[dt.date, dict[str, float]],
    *,
    sector_map: dict[str, str | None],
    config: CombinedConfig,
    adv_series_by_symbol: dict[str, pd.Series] | None = None,
) -> dict[dt.date, dict[str, float]]:
    """Map `apply_risk_overlays` over every formation date, resolving each
    symbol's PIT ADV at that date. Pure pre-processing of the engine input."""
    out: dict[dt.date, dict[str, float]] = {}
    for as_of, weights in holdings_by_date.items():
        adv_now: dict[str, float | None] | None = None
        if config.adv_floor_mad is not None and adv_series_by_symbol is not None:
            adv_now = {sym: pit_value(adv_series_by_symbol.get(sym), as_of) for sym in weights}
        out[as_of] = apply_risk_overlays(
            weights, sector_map=sector_map, config=config, adv_by_symbol=adv_now
        )
    return out


# ---------------------------------------------------------------------------
# Statistics: difference test, acceptance verdict, sub-period table
# ---------------------------------------------------------------------------


def difference_test(
    strategy: pd.DataFrame,
    incumbent: pd.DataFrame,
    *,
    return_col: str = "net_return",
    n_iter: int = 5000,
    block_mean: int = 6,
    seed: int = 42,
) -> dict[str, Any]:
    """Stationary-block bootstrap test on the monthly net-return DIFFERENCE
    (strategy - incumbent), aligned on as_of_date. block_mean=6 matches the
    6-month vintage overlap's serial correlation. One-sided: p = P(centered
    null >= observed total-return difference) for a positive observation."""
    merged = strategy[["as_of_date", return_col]].merge(
        incumbent[["as_of_date", return_col]],
        on="as_of_date",
        suffixes=("_strategy", "_incumbent"),
    )
    diff = (
        pd.to_numeric(merged[f"{return_col}_strategy"], errors="coerce")
        - pd.to_numeric(merged[f"{return_col}_incumbent"], errors="coerce")
    ).dropna()
    result = monte_carlo_luck_test(
        diff.tolist(),
        metric="total_return",
        n_iter=n_iter,
        seed=seed,
        periods_per_year=12,
        block_mean=block_mean,
    )
    return {
        "nobs": int(len(diff)),
        "mean_monthly_diff": float(diff.mean()) if len(diff) else None,
        "annualized_diff": float(diff.mean() * 12.0) if len(diff) else None,
        "observed_total_return_diff": result.get("observed"),
        "pvalue": result.get("pvalue"),
        "method": "stationary_block_bootstrap_on_monthly_net_return_difference",
        "block_mean": block_mean,
        "n_iter": n_iter,
    }


def evaluate_acceptance(
    primary: dict[str, Any],
    incumbent: dict[str, Any],
    diff: dict[str, Any],
    *,
    masi_sharpe: float | None = None,
    dd_tolerance: float = 0.02,
    p_threshold: float = 0.10,
) -> dict[str, Any]:
    """Pre-registered Stage-1 acceptance verdict (see plan 2026-07-12).

    (a) net Sharpe(P) >= net Sharpe(incumbent)
    (b) maxDD(P) no worse than incumbent's by more than dd_tolerance
        (max_drawdown is negative, so: dd_P >= dd_inc - dd_tolerance)
    (c) block-bootstrap p-value of the return difference (reported; < p_threshold
        AND a positive mean monthly difference needed for verdict A -- a
        significant NEGATIVE difference must not satisfy this criterion)
    Verdict: A = (a) & (b) & p < threshold & Sharpe(P) >= Sharpe(MASI);
             B = (a) & (b) otherwise; C = gate rejected, value-only stands.
    """
    p_sharpe = primary.get("sharpe")
    i_sharpe = incumbent.get("sharpe")
    p_dd = primary.get("max_drawdown")
    i_dd = incumbent.get("max_drawdown")
    pvalue = diff.get("pvalue")

    crit_a = p_sharpe is not None and i_sharpe is not None and float(p_sharpe) >= float(i_sharpe)
    crit_b = p_dd is not None and i_dd is not None and float(p_dd) >= float(i_dd) - dd_tolerance
    crit_p = (
        pvalue is not None
        and float(pvalue) < p_threshold
        and (diff.get("mean_monthly_diff") or 0) > 0
    )
    crit_masi = True if masi_sharpe is None else (p_sharpe is not None and float(p_sharpe) >= float(masi_sharpe))

    if crit_a and crit_b and crit_p and crit_masi:
        verdict = "A"
    elif crit_a and crit_b:
        verdict = "B"
    else:
        verdict = "C"
    return {
        "verdict": verdict,
        "criteria": {
            "a_sharpe_ge_incumbent": {"pass": crit_a, "primary": p_sharpe, "incumbent": i_sharpe},
            "b_drawdown_tolerance": {"pass": crit_b, "primary": p_dd, "incumbent": i_dd, "tolerance": dd_tolerance},
            "c_difference_pvalue": {"pass": crit_p, "pvalue": pvalue, "threshold": p_threshold},
            "d_sharpe_ge_masi": {"pass": crit_masi, "primary": p_sharpe, "masi": masi_sharpe},
        },
        "difference_test": diff,
    }


def subperiod_summary(
    monthly: pd.DataFrame,
    *,
    return_col: str = "net_return",
    periods: dict[str, tuple[str, str]] | None = None,
    min_months: int = 3,
) -> pd.DataFrame:
    """Per-regime performance over MASI_PERIODS (or custom windows)."""
    registry = periods or MASI_PERIODS
    dates = pd.to_datetime(monthly["as_of_date"])
    rows: list[dict[str, Any]] = []
    for label, (start, end) in registry.items():
        mask = (dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))
        r = pd.to_numeric(monthly.loc[mask, return_col], errors="coerce").dropna()
        if len(r) < min_months:
            continue
        equity = np.cumprod(1.0 + r.to_numpy())
        rows.append(
            {
                "period": label,
                "months": int(len(r)),
                "cumulative_return": float(equity[-1] - 1.0),
                "sharpe": sharpe_ratio(r.tolist(), periods_per_year=12),
                "max_drawdown": _max_drawdown(equity.tolist()),
            }
        )
    return pd.DataFrame(rows, columns=["period", "months", "cumulative_return", "sharpe", "max_drawdown"])
