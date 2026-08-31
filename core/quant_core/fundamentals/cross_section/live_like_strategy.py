"""Live-like long-only strategy engine for canonical B/M and CF/P signals.

This module is intentionally separate from `methodology_bakeoff.py` /
`characteristic_study.py`'s IC/portfolio_table machinery, which is PREDICTIVE
RESEARCH ONLY: those functions sample overlapping N-month forward returns at a
monthly cadence and their `portfolio_table()`'s cumulative-product "equity"
curve is NOT a valid sequential P&L (see the module-level warning added to
`portfolio_table` in `methodology_bakeoff.py`). Never feed a
`fwd_return_6m`-style column into this module's return engine, and never treat
this module's output as a substitute for the IC diagnostics -- they answer
different questions (does the signal predict returns cross-sectionally; can a
tradable portfolio realize that predictive edge as sequential wealth).

Engine design (six overlapping monthly vintages, the brief's preferred
specification):

- At each monthly formation date, form a NEW equal-weight top-tercile "vintage"
  portfolio from the trusted, eligible universe as of that date's PIT signal.
- Each vintage is intended to be held for 6 months, then expires.
- Total capital is split 1/6 per active vintage slot; during the first 5
  months (warm-up), fewer than 6 vintages are active and the unallocated
  fraction sits in cash (0% return) -- this is the honest behavior of actually
  implementing the scheme starting from a cold start, not an approximation.
- Each month's realized portfolio return is the capital-weighted sum of each
  active vintage's realized price-return over that one-month step (computed
  from real end-of-month prices, never from a stored overlapping forward-
  return research column).
- Turnover is computed between consecutive months' full realized portfolio
  weight vectors (entering vintage + expiring vintage + unchanged survivors),
  reusing the existing `one_way_turnover` from `portfolio_backtest.py`.

A semiannual non-overlapping variant (`run_semiannual_backtest`) is provided as
the robustness check the brief requires -- form once every six months, hold
until the next rebalance, no vintages.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ...significance import sharpe_ratio
from .portfolio_backtest import _max_drawdown, _pit_price, one_way_turnover

VINTAGE_LIFE_MONTHS = 6
TRUSTED_UNIVERSE_EXCLUSIONS: frozenset[str] = frozenset({"SAH"})
# SAH: workbook-sourced market cap / P-to-B confirmed wrong by a persistent ~29.3x
# factor across 2021-2024 (research-out/data-quality-forensic-repair/2026-07-06/
# known_cases_reb_sah_sbm.md); the root bad spreadsheet cell was never proven, so
# SAH remains excluded from the trusted universe rather than repaired or guessed.


@dataclass(frozen=True)
class LiveLikeConfig:
    cost_bps: float = 33.0
    execution_lag_days: int = 1
    tercile: str = "top"
    min_universe_names: int = 9
    liquidity_enabled: bool = True
    portfolio_nav_mad: float = 10_000_000.0
    min_order_enabled: bool = True
    min_order_mad: float = 100_000.0
    min_adv_enabled: bool = True
    min_adv_mad: float = 500_000.0
    max_participation_enabled: bool = True
    max_participation_rate: float = 0.20
    adv_window_days: int = 20
    execution_horizon_days: int = 1


@dataclass
class VintageState:
    formed_date: dt.date
    holdings: dict[str, float]  # symbol -> intra-vintage equal weight, sums to 1.0
    months_held: int = 0


def eligibility_mask(
    panel: pd.DataFrame,
    *,
    min_avg_names: int = 9,
    config: LiveLikeConfig | None = None,
) -> pd.DataFrame:
    """Adds `eligible_universe`, `eligible_bm`, `eligible_cfp` boolean columns.

    Trust rules applied (Phase 2): excludes TRUSTED_UNIVERSE_EXCLUSIONS (SAH);
    requires a valid PIT close and market cap; B/M requires book_to_market_raw
    not null (already encodes the canonical negative-book-equity exclusion);
    CF/P requires cashflow_price_raw not null (already encodes the canonical
    financial-sector exclusion). No liquidity filter is applied here if `adv20`
    is unavailable for a given row -- see trusted_universe.md for the
    liquidity-filter application at the caller level.
    """
    out = panel.copy()
    out["eligible_universe"] = (
        (~out["symbol"].isin(TRUSTED_UNIVERSE_EXCLUSIONS))
        & out["close"].notna()
        & out.get("market_cap_raw", pd.Series(index=out.index, dtype=float)).notna()
    )
    if config and config.liquidity_enabled and config.min_adv_enabled:
        adv = pd.to_numeric(out.get("adv_mad", pd.Series(index=out.index, dtype=float)), errors="coerce")
        out["eligible_liquidity"] = adv.notna() & (adv >= config.min_adv_mad)
        out["eligible_universe"] &= out["eligible_liquidity"]
    else:
        out["eligible_liquidity"] = True
    out["eligible_bm"] = out["eligible_universe"] & out["book_to_market_raw"].notna()
    out["eligible_cfp"] = out["eligible_universe"] & out["cashflow_price_raw"].notna()
    return out


def point_in_time_adv_mad(frame: pd.DataFrame | None, as_of: dt.date, *, window_days: int) -> float | None:
    """Trailing traded-value average known before ``as_of``; decision-day volume is excluded."""
    if frame is None or "Close" not in frame or "Volume" not in frame or window_days < 1:
        return None
    work = frame[["Close", "Volume"]].copy()
    work.index = pd.to_datetime(work.index, errors="coerce")
    work = work[work.index.date < as_of].sort_index().tail(window_days)
    if len(work) < window_days:
        return None
    close = pd.to_numeric(work["Close"], errors="coerce")
    volume = pd.to_numeric(work["Volume"], errors="coerce")
    traded_value = (close * volume).replace([np.inf, -np.inf], np.nan)
    if traded_value.isna().any() or (traded_value < 0).any():
        return None
    value = float(traded_value.mean())
    return value if math.isfinite(value) else None


def attach_point_in_time_adv(
    panel: pd.DataFrame,
    *,
    price_frames: dict[str, pd.DataFrame],
    window_days: int,
) -> pd.DataFrame:
    """Attach strictly lagged historical ADTV (MAD) to each signal formation row."""
    out = panel.copy()
    out["adv_mad"] = [
        point_in_time_adv_mad(
            price_frames.get(str(row["symbol"]).strip().upper()),
            pd.Timestamp(row["as_of_date"]).date(),
            window_days=window_days,
        )
        for _, row in out.iterrows()
    ]
    return out


def _tercile_holdings(sub: pd.DataFrame, signal_col: str, *, min_names: int) -> dict[str, float]:
    valid = sub.dropna(subset=[signal_col])
    if len(valid) < min_names:
        return {}
    ranked = valid.sort_values(signal_col, ascending=False)
    n_bucket = max(1, len(ranked) // 3)
    top = ranked.head(n_bucket)
    symbols = sorted(str(s).strip().upper() for s in top["symbol"])
    if not symbols:
        return {}
    w = 1.0 / len(symbols)
    return {s: w for s in symbols}


def _composite_score(sub: pd.DataFrame) -> pd.Series:
    bm_pct = sub["book_to_market_raw"].rank(pct=True)
    cfp_pct = sub["cashflow_price_raw"].rank(pct=True)
    both = bm_pct.notna() & cfp_pct.notna()
    score = pd.Series(np.nan, index=sub.index)
    score[both] = 0.5 * bm_pct[both] + 0.5 * cfp_pct[both]
    return score


def build_vintage_holdings_by_date(
    panel: pd.DataFrame,
    *,
    strategy: str,
    config: LiveLikeConfig,
) -> dict[dt.date, dict[str, float]]:
    """Computes the equal-weight top-tercile vintage formed at each panel date
    for one strategy ("S1_bm", "S2_cfp", "S3_composite"). S4 is built by the
    caller by combining independently-run S1 and S2 vintages 50/50."""
    holdings_by_date: dict[dt.date, dict[str, float]] = {}
    for as_of, sub in panel.groupby("as_of_date"):
        if strategy == "S1_bm":
            eligible = sub[sub["eligible_bm"]]
            signal = "book_to_market_raw"
        elif strategy == "S2_cfp":
            eligible = sub[sub["eligible_cfp"]]
            signal = "cashflow_price_raw"
        elif strategy == "S3_composite":
            eligible = sub[sub["eligible_bm"] & sub["eligible_cfp"]].copy()
            eligible["composite_raw"] = _composite_score(eligible)
            signal = "composite_raw"
        else:
            raise ValueError(f"unknown strategy {strategy!r}")
        holdings_by_date[pd.Timestamp(as_of).date()] = _tercile_holdings(eligible, signal, min_names=config.min_universe_names)
    return holdings_by_date


def _combined_weights(active: list[VintageState]) -> dict[str, float]:
    combined: dict[str, float] = {}
    n_active = len(active)
    if n_active == 0:
        return combined
    for v in active:
        for sym, w in v.holdings.items():
            combined[sym] = combined.get(sym, 0.0) + w / VINTAGE_LIFE_MONTHS
    return combined


def run_vintage_backtest(
    holdings_by_date: dict[dt.date, dict[str, float]],
    *,
    price_by_symbol: dict[str, pd.Series | None],
    config: LiveLikeConfig,
) -> pd.DataFrame:
    """The core novel engine: six overlapping monthly vintages, 1/6 capital
    each, genuine month-to-month realized returns from actual prices."""
    dates = sorted(holdings_by_date)
    active: list[VintageState] = []
    prev_combined: dict[str, float] = {}
    rows: list[dict[str, Any]] = []

    for i, as_of in enumerate(dates):
        # 1. realize this period's return using vintages that were already
        #    active BEFORE today's formation (i.e., held over (prev_date, as_of]).
        if i == 0:
            period_return = 0.0
            n_stale = 0
        else:
            start, end = dates[i - 1], as_of
            period_return = 0.0
            n_stale = 0
            for v in active:
                vintage_weight = 1.0 / VINTAGE_LIFE_MONTHS
                vintage_ret = 0.0
                for sym, w in v.holdings.items():
                    p0, p0_date = _pit_price(price_by_symbol.get(sym), start)
                    p1, p1_date = _pit_price(price_by_symbol.get(sym), end)
                    if p0 is None or p1 is None:
                        continue
                    if p0_date != start or p1_date != end:
                        n_stale += 1
                    vintage_ret += w * (p1 / p0 - 1.0)
                period_return += vintage_weight * vintage_ret

        # 2. age active vintages by one month, expire any that reached 6 months
        for v in active:
            v.months_held += 1
        active = [v for v in active if v.months_held < VINTAGE_LIFE_MONTHS]

        # 3. form a new vintage from today's holdings (enters starting next period)
        new_holdings = holdings_by_date[as_of]
        if new_holdings:
            active.append(VintageState(formed_date=as_of, holdings=new_holdings, months_held=0))

        combined = _combined_weights(active)
        turnover = one_way_turnover(prev_combined, combined)
        cost = (config.cost_bps / 10000.0) * 2.0 * turnover if i > 0 else 0.0
        net_return = period_return - cost

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
            }
        )
        prev_combined = combined

    return pd.DataFrame(rows)


def desired_vintage_weights_by_date(
    holdings_by_date: dict[dt.date, dict[str, float]],
) -> dict[dt.date, dict[str, float]]:
    """Convert vintage formations into the full target-weight schedule, including cash."""
    active: list[VintageState] = []
    targets: dict[dt.date, dict[str, float]] = {}
    for as_of in sorted(holdings_by_date):
        for vintage in active:
            vintage.months_held += 1
        active = [vintage for vintage in active if vintage.months_held < VINTAGE_LIFE_MONTHS]
        new_holdings = holdings_by_date[as_of]
        if new_holdings:
            active.append(VintageState(formed_date=as_of, holdings=new_holdings, months_held=0))
        targets[as_of] = _combined_weights(active)
    return targets


def run_capacity_constrained_backtest(
    holdings_by_date: dict[dt.date, dict[str, float]],
    *,
    price_frames: dict[str, pd.DataFrame],
    config: LiveLikeConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, float]]:
    """Simulate net monthly target orders with PIT ADTV caps and residual cash/positions.

    Orders are calculated against the portfolio's marked NAV. Small tickets are rejected;
    oversized orders are partially filled; missing/stale liquidity fails closed. Unfilled
    notional is never redistributed. Both entries and exits are constrained.
    """
    targets = desired_vintage_weights_by_date(holdings_by_date)
    positions: dict[str, float] = {}
    cash = float(config.portfolio_nav_mad)
    previous_nav = cash
    previous_date: dt.date | None = None
    rows: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}

    for as_of, target_weights in targets.items():
        stale_events = 0
        if previous_date is not None:
            for symbol, value in list(positions.items()):
                frame = price_frames.get(symbol)
                series = frame["Close"] if frame is not None and "Close" in frame else None
                p0, p0_date = _pit_price(series, previous_date)
                p1, p1_date = _pit_price(series, as_of)
                if p0 is None or p1 is None:
                    stale_events += 1
                    continue
                if p0_date != previous_date or p1_date != as_of:
                    stale_events += 1
                positions[symbol] = value * (p1 / p0)

        nav_before_orders = cash + sum(positions.values())
        gross_return = nav_before_orders / previous_nav - 1.0 if previous_date is not None and previous_nav else 0.0
        requested_total = 0.0
        filled_total = 0.0
        cost_total = 0.0

        for symbol in sorted(set(positions) | set(target_weights)):
            current_value = positions.get(symbol, 0.0)
            target_value = target_weights.get(symbol, 0.0) * nav_before_orders
            requested = target_value - current_value
            if abs(requested) < 1e-8:
                continue
            action = "BUY" if requested > 0 else "SELL"
            requested_abs = abs(requested)
            requested_total += requested_abs
            adv_mad = point_in_time_adv_mad(price_frames.get(symbol), as_of, window_days=config.adv_window_days)
            status = "filled"
            filled_abs = requested_abs

            if config.liquidity_enabled:
                if adv_mad is None:
                    filled_abs = 0.0
                    status = "rejected_missing_adv"
                elif config.min_order_enabled and requested_abs < config.min_order_mad:
                    filled_abs = 0.0
                    status = "rejected_min_order"
                elif config.max_participation_enabled:
                    capacity = adv_mad * config.max_participation_rate * config.execution_horizon_days
                    if filled_abs > capacity:
                        filled_abs = max(0.0, capacity)
                        status = "partial_capacity" if filled_abs > 0 else "rejected_capacity"

            if action == "BUY" and filled_abs > 0:
                affordable = cash / (1.0 + config.cost_bps / 10000.0)
                if filled_abs > affordable:
                    filled_abs = max(0.0, affordable)
                    status = "partial_cash" if filled_abs > 0 else "rejected_cash"

            cost = filled_abs * config.cost_bps / 10000.0
            if filled_abs > 0:
                if action == "BUY":
                    positions[symbol] = current_value + filled_abs
                    cash -= filled_abs + cost
                else:
                    filled_abs = min(filled_abs, current_value)
                    cost = filled_abs * config.cost_bps / 10000.0
                    remaining = current_value - filled_abs
                    if remaining > 1e-8:
                        positions[symbol] = remaining
                    else:
                        positions.pop(symbol, None)
                    cash += filled_abs - cost
                filled_total += filled_abs
                cost_total += cost

            status_counts[status] = status_counts.get(status, 0) + 1
            trades.append({
                "date": as_of,
                "action": action,
                "symbol": symbol,
                "vintage_formed": as_of,
                "weight": filled_abs / nav_before_orders if nav_before_orders else 0.0,
                "requested_notional_mad": requested_abs,
                "filled_notional_mad": filled_abs,
                "unfilled_notional_mad": requested_abs - filled_abs,
                "adv_mad": adv_mad,
                "participation_rate": filled_abs / adv_mad if adv_mad else None,
                "status": status,
            })

        nav_after_orders = cash + sum(positions.values())
        # Initial deployment costs are real P&L and must not disappear from the
        # first equity-curve observation.
        net_return = nav_after_orders / previous_nav - 1.0 if previous_nav else 0.0
        rows.append({
            "as_of_date": as_of,
            "n_active_vintages": None,
            "n_holdings": sum(value > 1e-8 for value in positions.values()),
            "gross_return": gross_return,
            "turnover": filled_total / (2.0 * nav_before_orders) if nav_before_orders else 0.0,
            "cost": cost_total / previous_nav if previous_nav else 0.0,
            "net_return": net_return,
            "stale_price_events": stale_events,
            "requested_notional_mad": requested_total,
            "filled_notional_mad": filled_total,
        })
        previous_nav = nav_after_orders
        previous_date = as_of

    final_nav = cash + sum(positions.values())
    final_weights = {symbol: value / final_nav for symbol, value in positions.items() if final_nav and value > 1e-8}
    summary = {
        "portfolio_nav_initial_mad": config.portfolio_nav_mad,
        "portfolio_nav_final_mad": final_nav,
        "requested_notional_mad": sum(float(row["requested_notional_mad"]) for row in trades),
        "filled_notional_mad": sum(float(row["filled_notional_mad"]) for row in trades),
        "unfilled_notional_mad": sum(float(row["unfilled_notional_mad"]) for row in trades),
        "orders": len(trades),
        "status_counts": status_counts,
    }
    return pd.DataFrame(rows), pd.DataFrame(trades), summary, final_weights


def build_trade_ledger(
    holdings_by_date: dict[dt.date, dict[str, float]],
    *,
    config: LiveLikeConfig | None = None,
) -> pd.DataFrame:
    """Real BUY/SELL trade ledger derived from the exact same vintage lifecycle
    `run_vintage_backtest` uses internally (same aging/expiry rule) -- added
    2026-07-07 for UI display (equity curve + trade history), not a new engine
    or a change to existing backtest behavior. A vintage's formation is logged
    as one BUY row per constituent (weight = 1/6 of capital, the vintage's
    fixed capital share); its expiry six months later is logged as one SELL
    row per constituent at that same weight."""
    dates = sorted(holdings_by_date)
    active: list[VintageState] = []
    rows: list[dict[str, Any]] = []
    for as_of in dates:
        for v in active:
            v.months_held += 1
        expiring = [v for v in active if v.months_held >= VINTAGE_LIFE_MONTHS]
        active = [v for v in active if v.months_held < VINTAGE_LIFE_MONTHS]
        for v in expiring:
            for sym, w in sorted(v.holdings.items()):
                rows.append(
                    {
                        "date": as_of,
                        "action": "SELL",
                        "symbol": sym,
                        "vintage_formed": v.formed_date,
                        "weight": w / VINTAGE_LIFE_MONTHS,
                    }
                )
        new_holdings = holdings_by_date[as_of]
        if new_holdings:
            active.append(VintageState(formed_date=as_of, holdings=new_holdings, months_held=0))
            for sym, w in sorted(new_holdings.items()):
                rows.append(
                    {
                        "date": as_of,
                        "action": "BUY",
                        "symbol": sym,
                        "vintage_formed": as_of,
                        "weight": w / VINTAGE_LIFE_MONTHS,
                    }
                )
    return pd.DataFrame(rows)


def run_fixed_stride_backtest(
    holdings_by_date: dict[dt.date, dict[str, float]],
    *,
    price_by_symbol: dict[str, pd.Series | None],
    config: LiveLikeConfig,
    stride_months: int,
) -> pd.DataFrame:
    """Non-overlapping rebalance every `stride_months` monthly formation
    dates, holding until the next rebalance. No vintage accounting -- a single
    portfolio replaced wholesale every Nth monthly formation date. Used for
    both the semiannual robustness check (stride=6) and the quarterly
    rebalance-frequency comparison (stride=3, 2026-07-06 continuation)."""
    all_dates = sorted(holdings_by_date)
    rebalance_dates = all_dates[::stride_months]
    rows: list[dict[str, Any]] = []
    prev_weights: dict[str, float] = {}
    for i, as_of in enumerate(rebalance_dates):
        if i > 0:
            start, end = rebalance_dates[i - 1], as_of
            period_return = 0.0
            for sym, w in prev_weights.items():
                p0, _ = _pit_price(price_by_symbol.get(sym), start)
                p1, _ = _pit_price(price_by_symbol.get(sym), end)
                if p0 is None or p1 is None:
                    continue
                period_return += w * (p1 / p0 - 1.0)
        else:
            period_return = 0.0
        new_weights = holdings_by_date[as_of]
        turnover = one_way_turnover(prev_weights, new_weights) if i > 0 else 0.0
        cost = (config.cost_bps / 10000.0) * 2.0 * turnover if i > 0 else 0.0
        rows.append(
            {
                "as_of_date": as_of,
                "n_holdings": len(new_weights),
                "gross_return": period_return,
                "turnover": turnover,
                "cost": cost,
                "net_return": period_return - cost,
            }
        )
        prev_weights = new_weights
    return pd.DataFrame(rows)


def combine_sleeves(sleeve_a: pd.DataFrame, sleeve_b: pd.DataFrame) -> pd.DataFrame:
    """S4: 50/50 capital split between two independently-run vintage sleeves,
    combined at realized-return level (never by averaging overlapping
    forward-looking research spreads)."""
    merged = sleeve_a.merge(sleeve_b, on="as_of_date", suffixes=("_a", "_b"))
    merged["gross_return"] = 0.5 * merged["gross_return_a"] + 0.5 * merged["gross_return_b"]
    merged["net_return"] = 0.5 * merged["net_return_a"] + 0.5 * merged["net_return_b"]
    merged["turnover"] = 0.5 * merged["turnover_a"] + 0.5 * merged["turnover_b"]
    merged["cost"] = 0.5 * merged["cost_a"] + 0.5 * merged["cost_b"]
    return merged[["as_of_date", "gross_return", "net_return", "turnover", "cost"]]


def summarize_performance(
    returns: pd.DataFrame,
    *,
    return_col: str = "net_return",
    periods_per_year: int = 12,
    benchmark_returns: pd.Series | None = None,
) -> dict[str, Any]:
    r = returns[return_col].dropna().tolist()
    if len(r) < 2:
        return {"periods": len(r), "insufficient_data": True}
    equity = np.cumprod([1.0 + x for x in r]).tolist()
    dd = _max_drawdown(equity)
    out: dict[str, Any] = {
        "periods": len(r),
        "cumulative_return": equity[-1] - 1.0,
        "annualized_vol": float(np.std(r, ddof=1) * math.sqrt(periods_per_year)),
        "sharpe": sharpe_ratio(r, periods_per_year=periods_per_year),
        "max_drawdown": dd,
        "hit_rate": float(np.mean([x > 0 for x in r])),
        "best_month": float(np.max(r)),
        "worst_month": float(np.min(r)),
        "avg_turnover": float(returns["turnover"].mean()),
    }
    years = len(r) / periods_per_year
    out["cagr"] = (equity[-1]) ** (1.0 / years) - 1.0 if years > 0 and equity[-1] > 0 else None
    if benchmark_returns is not None:
        aligned = pd.DataFrame({"strategy": returns.set_index("as_of_date")[return_col], "benchmark": benchmark_returns}).dropna()
        if len(aligned) >= 3:
            active = aligned["strategy"] - aligned["benchmark"]
            te = float(active.std(ddof=1) * math.sqrt(periods_per_year))
            out["excess_return_mean"] = float(active.mean())
            out["tracking_error"] = te
            out["information_ratio"] = float(active.mean()) * periods_per_year / te if te else None
            cov = np.cov(aligned["strategy"], aligned["benchmark"])
            out["beta"] = float(cov[0, 1] / cov[1, 1]) if cov[1, 1] != 0 else None
            out["benchmark_periods"] = len(aligned)
    return out


def run_semiannual_backtest(
    holdings_by_date: dict[dt.date, dict[str, float]],
    *,
    price_by_symbol: dict[str, pd.Series | None],
    config: LiveLikeConfig,
) -> pd.DataFrame:
    """Backwards-compatible wrapper: semiannual (stride=6) fixed-stride backtest."""
    return run_fixed_stride_backtest(holdings_by_date, price_by_symbol=price_by_symbol, config=config, stride_months=VINTAGE_LIFE_MONTHS)
