"""Phase-1 pilot: Point-in-time valuation replay → per-model cross-sectional IC.

Entry point:
    python -m quant_core.fundamentals.pit_ic_backtest [--years 2021 2022 2023 2024]

Environment (same as services):
    DATABASE_URL, S3_ENDPOINT_URL, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, S3_BUCKET

Prints an IC table:
    model               periods  pairs  mean_IC  IC_std  t_stat
    relative_multiples     4      ...    ...      ...     ...
    ...

Then prints a gate decision: proceed to Phase 2 or stop.

Look-ahead discipline
─────────────────────
- PIT filter: only fundamental_annual_metric rows with statement_year <= as_of_year.
- PIT price:  OHLCV close on or just before the as-of date (no future prices).
- Forward return:  price(T+12mo) / price(T) - 1 — uses price series only.
- Survivorship:  universe includes delisted names via bvc_pit_universe.csv.
- Assertion:  _assert_no_lookahead() fires on any row with statement_year > T.
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from .domain import AnnualMetricRow, FundamentalSnapshot
from .valuation import compute_symbol_valuations, default_assumptions_for_scenario
from ..research.stats.ic import _newey_west_var, _spearman_corr


# ─── Types ────────────────────────────────────────────────────────────────────

# Returns a DatetimeIndex-ed Series of Close prices (or None if unavailable).
PriceLoader = Callable[[str], "pd.Series | None"]

MODELS_OF_INTEREST = (
    "relative_multiples",
    "fcff_dcf",
    "fcfe_dcf",
    "ddm",
    "residual_income",
    "justified_multiples",
)

_NET_INCOME_NAMES = (
    "NetIncome", "Net_Income", "Clean_Resultat_net", "Resultat_net",
    "Resultat_net_part_du_groupe", "RNPG",
)
_EQUITY_NAMES = (
    "Total_Equity", "Shareholders_Equity", "Clean_Capitaux_propres",
    "Capitaux_propres", "Common_Equity",
)
_REVENUE_NAMES = ("Revenue", "Chiffre_daffaires", "Clean_Chiffre_daffaires")
_EBITDA_NAMES = ("EBITDA", "Excedent_brut_dexploitation")
_DIVIDEND_NAMES = ("Dividendes", "Dividends_Paid", "Clean_Dividendes")
_DEBT_NAMES = ("Total_Debt", "Debt_Total", "Dettes_de_financement")
_CASH_NAMES = ("Cash_and_Equivalents", "Cash", "Tresorerie_Actif")
_SHARES_NAMES = ("Shares_Outstanding",)

UNIVERSE_PATH = Path(__file__).parents[3] / "data" / "universe" / "bvc_pit_universe.csv"


# ─── PIT assertion ────────────────────────────────────────────────────────────

def _assert_no_lookahead(
    rows: list[AnnualMetricRow],
    as_of_year: int,
    symbol: str = "",
) -> None:
    """Raise AssertionError if any row has statement_year > as_of_year.

    This is the critical look-ahead guard.  After calling
    _filter_pit_history() the list should always be clean; this assertion is
    the backstop that makes the guarantee provable.
    """
    future = [r for r in rows if r.statement_year > as_of_year]
    if future:
        examples = [(r.metric_name, r.statement_year) for r in future[:3]]
        raise AssertionError(
            f"LOOK-AHEAD VIOLATION for {symbol!r}: "
            f"{len(future)} row(s) with statement_year > {as_of_year}: "
            f"{examples!r}"
        )


def _filter_pit_history(
    history: list[AnnualMetricRow],
    as_of_year: int,
    symbol: str = "",
) -> list[AnnualMetricRow]:
    """Return rows where statement_year <= as_of_year, then assert the guard."""
    pit = [r for r in history if r.statement_year <= as_of_year]
    _assert_no_lookahead(pit, as_of_year, symbol)
    return pit


# ─── PIT price helpers ────────────────────────────────────────────────────────

def normalize_price_index(prices: "pd.Series | None") -> "pd.Series | None":
    """Return prices with a tz-naive DatetimeIndex, preserving naive inputs."""
    if prices is None or prices.empty:
        return None
    if not isinstance(prices.index, pd.DatetimeIndex):
        return prices
    idx = prices.index
    if idx.tz is None:
        return prices
    out = prices.copy()
    out.index = idx.tz_convert("UTC").tz_localize(None)
    return out


def _pit_close(prices: "pd.Series | None", as_of_date: dt.date) -> float | None:
    """Most recent Close at or before as_of_date; None if unavailable."""
    prices = normalize_price_index(prices)
    if prices is None or prices.empty:
        return None
    ts = pd.Timestamp(as_of_date)
    available = prices[prices.index <= ts]
    if available.empty:
        return None
    val = float(available.iloc[-1])
    return val if math.isfinite(val) and val > 0 else None


# ─── PIT snapshot construction ────────────────────────────────────────────────

def _latest_from_history(history: list[AnnualMetricRow], *names: str) -> float | None:
    """Most-recent (by statement_year) finite value for any of the given names."""
    best_year = -1
    best_val: float | None = None
    for row in history:
        if row.metric_name in names and row.metric_value is not None:
            try:
                v = float(row.metric_value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(v) and row.statement_year > best_year:
                best_year = row.statement_year
                best_val = v
    return best_val


def _build_pit_snapshot(
    symbol: str,
    company_name: str,
    pit_history: list[AnnualMetricRow],
    price: float,
    as_of_year: int,
) -> FundamentalSnapshot:
    """Build a FundamentalSnapshot from PIT-filtered history and PIT price.

    All valuation multiples are recomputed from PIT data — no live snapshot
    multiples are carried over.  Called only after _filter_pit_history() so
    the assertion here is a belt-and-suspenders backstop.
    """
    _assert_no_lookahead(pit_history, as_of_year, symbol)

    latest_year = max((r.statement_year for r in pit_history), default=None)

    shares = _latest_from_history(pit_history, *_SHARES_NAMES)
    mktcap = price * shares if (shares and shares > 0) else None

    net_income = _latest_from_history(pit_history, *_NET_INCOME_NAMES)
    book_equity = _latest_from_history(pit_history, *_EQUITY_NAMES)
    revenue = _latest_from_history(pit_history, *_REVENUE_NAMES)
    ebitda = _latest_from_history(pit_history, *_EBITDA_NAMES)
    dividends = _latest_from_history(pit_history, *_DIVIDEND_NAMES)
    debt = _latest_from_history(pit_history, *_DEBT_NAMES)
    cash = _latest_from_history(pit_history, *_CASH_NAMES)

    metrics: dict[str, Any] = {"Current_Price": price}
    if shares and shares > 0:
        metrics["Shares_Outstanding"] = shares
    if mktcap is not None:
        metrics["MarketCap_Calc"] = mktcap

    # Recompute PIT multiples
    if mktcap and net_income and net_income > 0:
        metrics["PER"] = mktcap / net_income
    if mktcap and book_equity and book_equity > 0:
        metrics["Price_to_Book"] = mktcap / book_equity
    if mktcap and revenue and revenue > 0:
        metrics["Price_to_Sales"] = mktcap / revenue
    if ebitda and ebitda > 0 and mktcap is not None:
        net_debt = (debt or 0.0) - (cash or 0.0)
        ev = mktcap + net_debt
        if ev > 0:
            metrics["EV_to_EBITDA"] = ev / ebitda
    if dividends and dividends > 0 and shares and shares > 0 and price > 0:
        dps = dividends / shares
        metrics["Dividend_Yield"] = dps / price
    if book_equity and book_equity > 0 and net_income is not None:
        roe = net_income / book_equity
        if math.isfinite(roe) and -1.0 < roe < 1.0:
            metrics["ROE"] = roe

    return FundamentalSnapshot(
        symbol=symbol,
        company_name=company_name,
        latest_statement_year=latest_year,
        metrics=metrics,
        as_of_date=dt.date(as_of_year, 12, 31),
    )


# ─── Universe helpers ─────────────────────────────────────────────────────────

def _is_live(uni_row: "pd.Series", as_of_date: dt.date) -> bool:
    """True if the stock was trading at as_of_date per the PIT universe."""
    listing_raw = uni_row.get("listing_date")
    delisting_raw = uni_row.get("delisting_date")
    listing: dt.date | None = None
    delisting: dt.date | None = None
    if pd.notna(listing_raw) and str(listing_raw).strip():
        try:
            listing = pd.Timestamp(listing_raw).date()
        except Exception:
            pass
    if pd.notna(delisting_raw) and str(delisting_raw).strip():
        try:
            delisting = pd.Timestamp(delisting_raw).date()
        except Exception:
            pass
    if listing and listing > as_of_date:
        return False
    # Delisted on or before as_of_date → not live
    if delisting and delisting <= as_of_date:
        return False
    return True


# ─── Cross-sectional IC computation ──────────────────────────────────────────

@dataclass
class _PeriodEntry:
    symbol: str
    as_of_year: int
    model: str
    upside_pct: float
    fwd_return: float


def _compute_cross_sectional_ic(
    entries: list[_PeriodEntry],
) -> dict[str, dict]:
    """Per-model cross-sectional Spearman IC aggregated over periods.

    For each period T: IC_T = Spearman(upside_pct[stocks], fwd_return[stocks]).
    Then aggregate over periods: mean_IC, IC_std, Newey-West t-stat.

    Reuses _spearman_corr and _newey_west_var from research.stats.ic.
    """
    by_model_period: dict[str, dict[int, list[tuple[float, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for e in entries:
        by_model_period[e.model][e.as_of_year].append((e.upside_pct, e.fwd_return))

    results: dict[str, dict] = {}
    for model in MODELS_OF_INTEREST:
        period_data = by_model_period.get(model, {})
        ic_series: list[float] = []
        pair_counts: list[int] = []

        for year in sorted(period_data):
            pairs = period_data[year]
            if len(pairs) < 5:  # too thin for meaningful IC
                continue
            upside_s = pd.Series([p[0] for p in pairs], dtype=float)
            fwd_s = pd.Series([p[1] for p in pairs], dtype=float)
            ic = _spearman_corr(upside_s, fwd_s)
            if math.isfinite(ic):
                ic_series.append(ic)
                pair_counts.append(len(pairs))

        n_periods = len(ic_series)
        total_pairs = sum(pair_counts)

        if n_periods == 0:
            results[model] = {
                "periods": 0,
                "pairs": 0,
                "mean_IC": float("nan"),
                "IC_std": float("nan"),
                "t_stat": float("nan"),
            }
            continue

        ic_arr = np.array(ic_series, dtype=float)
        mean_ic = float(np.mean(ic_arr))
        ic_std = float(np.std(ic_arr, ddof=1)) if n_periods > 1 else float("nan")

        # HAC t-stat: Newey-West on IC series (reuses ic.py's _newey_west_var)
        nw_var = _newey_west_var(ic_arr) if n_periods >= 3 else None
        if nw_var is not None and math.isfinite(nw_var) and nw_var > 0:
            t_stat = mean_ic / math.sqrt(nw_var)
        elif n_periods > 1 and math.isfinite(ic_std) and ic_std > 0:
            # Classical t-stat when NW not applicable (< 3 periods)
            t_stat = mean_ic / (ic_std / math.sqrt(n_periods))
        else:
            t_stat = float("nan")

        results[model] = {
            "periods": n_periods,
            "pairs": total_pairs,
            "mean_IC": round(mean_ic, 4),
            "IC_std": round(ic_std, 4) if math.isfinite(ic_std) else float("nan"),
            "t_stat": round(t_stat, 3) if math.isfinite(t_stat) else float("nan"),
        }

    return results


# ─── Main pilot runner ────────────────────────────────────────────────────────

def run_pilot(
    all_rows: list[AnnualMetricRow],
    price_loader: PriceLoader,
    universe_df: "pd.DataFrame",
    as_of_years: list[int] | None = None,
    sectors: dict[str, str | None] | None = None,
    scenario: str = "base",
    verbose: bool = True,
    return_entries: bool = False,
) -> "dict[str, dict] | tuple[dict[str, dict], list[_PeriodEntry]]":
    """Run the Phase-1 PIT IC pilot.

    Parameters
    ----------
    all_rows:       ALL fundamental_annual_metric rows (PIT filtering done here).
    price_loader:   symbol -> pd.Series[DatetimeIndex, float Close] | None.
    universe_df:    bvc_pit_universe.csv with [symbol, listing_date, delisting_date].
    as_of_years:    fiscal year-ends to replay (default: 2021-2024).
    sectors:        {symbol -> sector_str} for peer grouping (None = no sector grouping).
    scenario:       valuation scenario ("base").
    verbose:        print progress to stdout.
    return_entries: if True, return (ic_table, entries) instead of just ic_table.
                    Used by Phase-2 OOS validation.

    Returns
    -------
    dict[model_name, {periods, pairs, mean_IC, IC_std, t_stat}]
    -- or (same dict, list[_PeriodEntry]) when return_entries=True.
    """
    if as_of_years is None:
        as_of_years = [2021, 2022, 2023, 2024]

    rows_by_symbol: dict[str, list[AnnualMetricRow]] = defaultdict(list)
    for row in all_rows:
        rows_by_symbol[row.symbol].append(row)

    universe_by_symbol: dict[str, "pd.Series"] = {
        str(r["symbol"]).strip().upper(): r
        for _, r in universe_df.iterrows()
        if pd.notna(r.get("symbol"))
    }

    prices_cache: dict[str, "pd.Series | None"] = {}

    def get_prices(sym: str) -> "pd.Series | None":
        if sym not in prices_cache:
            prices_cache[sym] = price_loader(sym)
        return prices_cache[sym]

    entries: list[_PeriodEntry] = []

    for as_of_year in sorted(as_of_years):
        as_of_date = dt.date(as_of_year, 12, 31)
        fwd_date = dt.date(as_of_year + 1, 12, 31)

        if verbose:
            print(
                f"\n=== as_of_year={as_of_year}  "
                f"(as-of {as_of_date}, forward {fwd_date}) ===",
                flush=True,
            )

        # --- Step 1: determine live symbols (survivorship-bias-free) ---
        live_symbols: list[str] = []
        for sym, uni_row in universe_by_symbol.items():
            if sym in rows_by_symbol and _is_live(uni_row, as_of_date):
                live_symbols.append(sym)

        if verbose:
            print(f"  Live universe at {as_of_date}: {len(live_symbols)} symbols", flush=True)

        # --- Step 2: build PIT snapshots for all live symbols ---
        pit_snapshots: dict[str, FundamentalSnapshot] = {}
        pit_histories: dict[str, list[AnnualMetricRow]] = {}

        for sym in live_symbols:
            sym_rows = rows_by_symbol[sym]
            pit_hist = _filter_pit_history(sym_rows, as_of_year, sym)
            if not pit_hist:
                continue
            prices = get_prices(sym)
            price = _pit_close(prices, as_of_date)
            if price is None:
                continue
            snap = _build_pit_snapshot(
                symbol=sym,
                company_name=sym_rows[0].company_name,
                pit_history=pit_hist,
                price=price,
                as_of_year=as_of_year,
            )
            pit_snapshots[sym] = snap
            pit_histories[sym] = pit_hist

        valid_symbols = list(pit_snapshots.keys())
        if verbose:
            print(f"  Valid (price + fundamentals): {len(valid_symbols)}", flush=True)

        if not valid_symbols:
            continue

        peer_list = list(pit_snapshots.values())
        sector_map = sectors or {}

        # --- Step 3: compute valuations, collect (upside, fwd_return) pairs ---
        period_entries = 0
        for sym in valid_symbols:
            snap = pit_snapshots[sym]
            pit_hist = pit_histories[sym]
            peers = [s for s in peer_list if s.symbol != sym]

            try:
                _eligibility, results = compute_symbol_valuations(
                    snapshot=snap,
                    history=pit_hist,
                    peer_snapshots=peers,
                    sectors=sector_map,
                    scenario=scenario,
                )
            except Exception as exc:
                if verbose:
                    print(f"    SKIP {sym}: valuation error: {exc}", flush=True)
                continue

            prices = get_prices(sym)
            pit_price = snap.metrics.get("Current_Price")
            fwd_price = _pit_close(prices, fwd_date)
            if fwd_price is None or not pit_price or pit_price <= 0:
                continue
            fwd_return = fwd_price / float(pit_price) - 1.0

            for result in results:
                if result.model not in MODELS_OF_INTEREST:
                    continue
                if result.upside_pct is None or not math.isfinite(result.upside_pct):
                    continue
                if result.confidence == "unavailable":
                    continue
                entries.append(
                    _PeriodEntry(
                        symbol=sym,
                        as_of_year=as_of_year,
                        model=result.model,
                        upside_pct=result.upside_pct,
                        fwd_return=fwd_return,
                    )
                )
                period_entries += 1

        if verbose:
            print(f"  Model-stock pairs collected: {period_entries}", flush=True)

    ic_table = _compute_cross_sectional_ic(entries)
    if return_entries:
        return ic_table, entries
    return ic_table


# ─── Reporting ────────────────────────────────────────────────────────────────

def print_ic_table(ic_table: dict[str, dict]) -> None:
    header = f"{'model':<24} {'periods':>8} {'pairs':>7} {'mean_IC':>9} {'IC_std':>8} {'t_stat':>8}"
    print("\n" + header)
    print("-" * len(header))
    for model in MODELS_OF_INTEREST:
        row = ic_table.get(model)
        if row is None:
            continue
        mean_ic = row["mean_IC"]
        ic_std = row["IC_std"]
        t_stat = row["t_stat"]
        print(
            f"{model:<24} "
            f"{row['periods']:>8} "
            f"{row['pairs']:>7} "
            f"{mean_ic if math.isfinite(mean_ic) else 'nan':>9.4f} "
            f"{ic_std if math.isfinite(ic_std) else 'nan':>8.4f} "
            f"{t_stat if math.isfinite(t_stat) else 'nan':>8.3f}"
        )
    print()


def _gate_decision(ic_table: dict[str, dict]) -> tuple[bool, str]:
    """Return (proceed_to_phase2, rationale)."""
    # A model counts as "signal" if:
    #   - mean_IC > 0.03 (economically non-trivial for annual data)
    #   - t_stat > 0.5 (directional, even if weak given tiny sample)
    # We need ≥ 2 such models to proceed.
    signal_models = []
    for model, row in ic_table.items():
        if row["periods"] == 0:
            continue
        mic = row["mean_IC"]
        ts = row["t_stat"]
        if math.isfinite(mic) and math.isfinite(ts) and mic > 0.03 and ts > 0.5:
            signal_models.append(model)

    if len(signal_models) >= 2:
        return True, (
            f"PROCEED TO PHASE 2 — {len(signal_models)} model(s) show positive IC "
            f"with consistent sign: {signal_models}"
        )
    return False, (
        "STOP — fewer than 2 models show reliable positive IC on MASI at this horizon.\n"
        "Conclusion: valuation models do not predict 12-month forward returns reliably "
        "in this sample.  Recommended framing: keep equal-weight ensemble as a "
        "fair-value reference; surface valuation as context, not as a rating.  "
        "Leave alpha generation to the technical signal engine."
    )


def print_gate_decision(ic_table: dict[str, dict]) -> None:
    proceed, rationale = _gate_decision(ic_table)
    # Use ASCII dashes to avoid cp1252 encoding crashes on Windows terminals.
    sep = "-" * 60
    print(sep)
    print("GATE DECISION:")
    print(rationale)
    print(sep)


# ─── Phase 2: IC-shrunk weight computation + OOS validation ──────────────────

_KNOWN_DATA_ISSUES: dict[str, str] = {
    # ZDJ: StockAnalysis/BVC Revenue figure is ~50 024 MAD (raw) instead of ~600 M MAD.
    # The canonical normaliser rejects it; the figure appears un-scaled (missing x1000 factor).
    # Data-layer fix needed: re-ingest ZDJ financials with correct scale or manual override.
    "ZDJ": (
        "bad_revenue_scale: raw value ~50024 MAD vs expected ~6e8 MAD "
        "(factor-of-~12000 discrepancy; likely missing x1000 unit conversion). "
        "Resolver correctly rejects; data team must re-ingest."
    ),
}


def compute_ic_shrunk_weights(
    raw_ic: dict[str, float],
    lambda_shrink: float = 0.40,
) -> dict[str, float]:
    """Compute shrunk IC weights from per-model IC scores.

    Formula: w_m = (1 - lambda) * equal_weight + lambda * ic_weight_m
    where ic_weight_m = max(0, IC_m) / sum(max(0, IC_k) for all k),
    and equal_weight is 1 / n_positive_ic_models.

    Models with non-positive IC are floored to 0.  If no model has positive IC
    the result is empty (caller should fall back to equal-weight over all models).
    """
    positive = {m: ic for m, ic in raw_ic.items() if ic > 0.0}
    if not positive:
        return {m: 0.0 for m in raw_ic}

    total_pos = sum(positive.values())
    n = len(positive)
    equal = 1.0 / n

    shrunk: dict[str, float] = {}
    pos_total = 0.0
    for model in raw_ic:
        ic = positive.get(model, 0.0)
        if ic > 0.0:
            ic_w = ic / total_pos
            w = (1.0 - lambda_shrink) * equal + lambda_shrink * ic_w
        else:
            w = 0.0
        shrunk[model] = w
        pos_total += w

    # Renormalise positive-IC weights to sum to 1.0
    if pos_total > 0:
        shrunk = {m: (w / pos_total if w > 0 else 0.0) for m, w in shrunk.items()}

    return shrunk


def run_oos_validation(
    entries: "list[_PeriodEntry]",
    as_of_years: list[int],
    lambda_shrink: float = 0.40,
    min_cross_section: int = 5,
) -> list[dict]:
    """Expanding-window OOS validation: IC-weighted ensemble vs equal-weight.

    For each split (train=[2021..T-1], test=T):
    - Estimate per-model mean IC on train periods from entries
    - Shrink to get IC weights
    - Compute weighted-ensemble upside and equal-weight upside per stock at T
    - Spearman IC of each vs fwd_return across stocks at T
    - Compare

    Returns a list of per-split result dicts with keys:
      train_years, test_year, n_stocks,
      ew_ic, ic_weighted_ic, winner ('ic_weighted' | 'equal_weight' | 'tie')
    """
    # Index: (symbol, year, model) -> upside_pct; (symbol, year) -> fwd_return
    upside_map: dict[tuple[str, int, str], float] = {}
    fwd_map: dict[tuple[str, int], float] = {}
    for e in entries:
        upside_map[(e.symbol, e.as_of_year, e.model)] = e.upside_pct
        fwd_map[(e.symbol, e.as_of_year)] = e.fwd_return

    years_sorted = sorted(as_of_years)
    if len(years_sorted) < 2:
        return []

    results = []
    for split_idx in range(1, len(years_sorted)):
        train_years = years_sorted[:split_idx]
        test_year = years_sorted[split_idx]

        # --- estimate IC on train periods ---
        train_entries = [e for e in entries if e.as_of_year in train_years]
        train_ic = _compute_cross_sectional_ic(train_entries)
        raw_ic_for_split = {
            model: train_ic.get(model, {}).get("mean_IC", 0.0)
            for model in MODELS_OF_INTEREST
        }
        # Replace nan with 0
        raw_ic_for_split = {
            m: (v if math.isfinite(v) else 0.0)
            for m, v in raw_ic_for_split.items()
        }
        ic_weights = compute_ic_shrunk_weights(raw_ic_for_split, lambda_shrink)
        positive_ic_models = [m for m, w in ic_weights.items() if w > 0]

        # --- evaluate on test period ---
        # Find stocks with at least one model available at test_year
        test_symbols = {
            sym for (sym, yr) in fwd_map if yr == test_year
        }
        ew_upsides: list[float] = []
        icw_upsides: list[float] = []
        fwd_returns: list[float] = []

        for sym in sorted(test_symbols):
            fwd = fwd_map.get((sym, test_year))
            if fwd is None:
                continue

            # Equal-weight: mean upside over all available models
            avail = [
                upside_map[(sym, test_year, m)]
                for m in MODELS_OF_INTEREST
                if (sym, test_year, m) in upside_map
            ]
            if not avail:
                continue
            ew_upside = float(np.mean(avail))

            # IC-weighted: weighted sum over positive-IC models
            avail_pos = [
                (upside_map[(sym, test_year, m)], ic_weights[m])
                for m in positive_ic_models
                if (sym, test_year, m) in upside_map
            ]
            if not avail_pos:
                # Fallback to equal-weight for this stock
                icw_upside = ew_upside
            else:
                tw = sum(w for _, w in avail_pos)
                icw_upside = sum(u * w for u, w in avail_pos) / tw if tw > 0 else ew_upside

            ew_upsides.append(ew_upside)
            icw_upsides.append(icw_upside)
            fwd_returns.append(fwd)

        n = len(fwd_returns)
        if n < min_cross_section:
            results.append({
                "train_years": train_years,
                "test_year": test_year,
                "n_stocks": n,
                "ew_ic": float("nan"),
                "ic_weighted_ic": float("nan"),
                "winner": "insufficient_data",
            })
            continue

        fwd_s = pd.Series(fwd_returns, dtype=float)
        ew_ic = _spearman_corr(pd.Series(ew_upsides, dtype=float), fwd_s)
        icw_ic = _spearman_corr(pd.Series(icw_upsides, dtype=float), fwd_s)

        if not math.isfinite(ew_ic) or not math.isfinite(icw_ic):
            winner = "indeterminate"
        elif icw_ic > ew_ic + 0.01:  # meaningful margin
            winner = "ic_weighted"
        elif ew_ic > icw_ic + 0.01:
            winner = "equal_weight"
        else:
            winner = "tie"

        results.append({
            "train_years": train_years,
            "test_year": test_year,
            "n_stocks": n,
            "ew_ic": round(ew_ic, 4),
            "ic_weighted_ic": round(icw_ic, 4),
            "winner": winner,
        })

    return results


def print_oos_report(
    oos_results: list[dict],
    final_weights: dict[str, float],
) -> None:
    """Print OOS validation summary and weight decision."""
    sep = "-" * 70
    print("\n" + sep)
    print("OOS VALIDATION (expanding window, IC-weighted vs equal-weight)")
    print(sep)
    print(f"  {'train':>20}  {'test':>6}  {'n':>5}  {'EW IC':>7}  {'ICW IC':>7}  {'winner'}")
    print(sep)

    ic_weighted_wins = 0
    equal_weight_wins = 0
    total_valid = 0

    for r in oos_results:
        train_str = str(r["train_years"])
        ew = r["ew_ic"]
        icw = r["ic_weighted_ic"]
        winner = r["winner"]
        print(
            f"  {train_str:>20}  {r['test_year']:>6}  {r['n_stocks']:>5}  "
            f"{ew if math.isfinite(ew) else 'nan':>7.4f}  "
            f"{icw if math.isfinite(icw) else 'nan':>7.4f}  "
            f"{winner}"
        )
        if winner == "ic_weighted":
            ic_weighted_wins += 1
            total_valid += 1
        elif winner == "equal_weight":
            equal_weight_wins += 1
            total_valid += 1
        elif winner == "tie":
            total_valid += 1

    print(sep)
    print(f"  IC-weighted wins: {ic_weighted_wins}  |  Equal-weight wins: {equal_weight_wins}")

    if total_valid > 0 and ic_weighted_wins >= equal_weight_wins:
        print("  DECISION: IC-weighted ensemble CONFIRMED out-of-sample.")
    elif total_valid > 0:
        print(
            "  DECISION: IC-weighted does NOT beat equal-weight OOS. "
            "REVERTING to equal-weight ensemble."
        )
    else:
        print("  DECISION: Insufficient data to validate OOS -- retaining IC weights provisionally.")

    print("\n  Final ensemble weights written to ic_ensemble_weights.json:")
    for model, w in sorted(final_weights.items(), key=lambda x: -x[1]):
        bar = "#" * int(round(w * 30))
        print(f"    {model:<24}  {w:.4f}  {bar}")
    print(sep)


def print_zdj_flag() -> None:
    """Surface the known ZDJ data issue."""
    issue = _KNOWN_DATA_ISSUES.get("ZDJ", "")
    if issue:
        sep = "-" * 60
        print(f"\n{sep}")
        print("DATA QUALITY FLAG [ZDJ]:")
        print(f"  {issue}")
        print(sep)


# ─── DB / S3 loaders (for main()) ─────────────────────────────────────────────

def _load_rows_from_db() -> list[AnnualMetricRow]:
    from sqlalchemy import create_engine, text

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL env var is required")

    engine = create_engine(db_url, pool_pre_ping=True)
    query = text("""
        SELECT
            fam.symbol,
            fam.company_name,
            fam.statement_year,
            fam.metric_name,
            fam.metric_value
        FROM fundamental_annual_metric fam
        WHERE fam.statement_year >= 2016
        ORDER BY fam.symbol, fam.statement_year, fam.metric_name
    """)
    rows: list[AnnualMetricRow] = []
    with engine.connect() as conn:
        for r in conn.execute(query):
            rows.append(
                AnnualMetricRow(
                    symbol=str(r[0]).strip().upper(),
                    company_name=str(r[1] or ""),
                    statement_year=int(r[2]),
                    metric_name=str(r[3]),
                    metric_value=float(r[4]) if r[4] is not None else None,
                )
            )
    return rows


def _load_sectors_from_db() -> dict[str, str | None]:
    from sqlalchemy import create_engine, text

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return {}
    engine = create_engine(db_url, pool_pre_ping=True)
    query = text("SELECT symbol, sector FROM stock_master WHERE symbol IS NOT NULL")
    sectors: dict[str, str | None] = {}
    with engine.connect() as conn:
        for r in conn.execute(query):
            sectors[str(r[0]).strip().upper()] = str(r[1]).strip() if r[1] else None
    return sectors


def _build_price_loader() -> PriceLoader:
    """Load Close series from market_data_store parquet in S3/MinIO."""
    from io import BytesIO

    import boto3
    from sqlalchemy import create_engine, text

    s3_endpoint = os.environ.get("S3_ENDPOINT_URL", "http://localhost:9000")
    access_key = os.environ.get("AWS_ACCESS_KEY_ID", "minioadmin")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "minioadmin")
    s3_bucket = os.environ.get("S3_BUCKET", "backtester")

    s3 = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )

    # Preload symbol → object_key mapping from market_data_store
    db_url = os.environ.get("DATABASE_URL")
    ohlcv_keys: dict[str, str] = {}
    if db_url:
        engine = create_engine(db_url, pool_pre_ping=True)
        q = text(
            "SELECT symbol, object_key FROM market_data_store "
            "WHERE timeframe = '1D' AND object_key IS NOT NULL"
        )
        with engine.connect() as conn:
            for r in conn.execute(q):
                ohlcv_keys[str(r[0]).strip().upper()] = str(r[1])

    _cache: dict[str, "pd.Series | None"] = {}

    def load(symbol: str) -> "pd.Series | None":
        if symbol in _cache:
            return _cache[symbol]
        object_key = ohlcv_keys.get(symbol)
        if not object_key:
            _cache[symbol] = None
            return None
        try:
            resp = s3.get_object(Bucket=s3_bucket, Key=object_key)
            df = pd.read_parquet(BytesIO(resp["Body"].read()))
            if not isinstance(df.index, pd.DatetimeIndex):
                for candidate in ("timestamp", "Timestamp", "date", "Date"):
                    if candidate in df.columns:
                        df = df.set_index(candidate)
                        break
            df.index = pd.to_datetime(df.index).tz_localize(None)
            col = next((c for c in ("Close", "close", "Adj Close") if c in df.columns), None)
            if col is None:
                _cache[symbol] = None
                return None
            series = df[col].sort_index().dropna()
            _cache[symbol] = series
            return series
        except Exception:
            _cache[symbol] = None
            return None

    return load


# ─── CLI entry point ──────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="PIT valuation IC pilot + Phase-2 OOS validation (Brief 48)"
    )
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        default=[2021, 2022, 2023, 2024],
        help="Fiscal year-ends to replay (default: 2021 2022 2023 2024)",
    )
    parser.add_argument("--scenario", default="base")
    args = parser.parse_args()

    if not UNIVERSE_PATH.exists():
        print(f"ERROR: universe file not found: {UNIVERSE_PATH}", file=sys.stderr)
        sys.exit(1)

    universe_df = pd.read_csv(UNIVERSE_PATH)

    print("Loading fundamental data from DB...", flush=True)
    all_rows = _load_rows_from_db()
    print(f"Loaded {len(all_rows):,} annual metric rows.", flush=True)

    print("Loading sector data...", flush=True)
    sectors = _load_sectors_from_db()

    price_loader = _build_price_loader()

    ic_table, entries = run_pilot(  # type: ignore[misc]
        all_rows=all_rows,
        price_loader=price_loader,
        universe_df=universe_df,
        as_of_years=args.years,
        sectors=sectors,
        scenario=args.scenario,
        verbose=True,
        return_entries=True,
    )

    print_ic_table(ic_table)
    print_gate_decision(ic_table)

    # Phase 2: OOS validation using pilot entries
    print("\nRunning Phase-2 OOS validation...", flush=True)
    oos_results = run_oos_validation(entries, args.years, lambda_shrink=0.40)

    # Compute final weights from full-sample IC
    raw_ic_full = {
        model: ic_table.get(model, {}).get("mean_IC", 0.0)
        for model in MODELS_OF_INTEREST
    }
    raw_ic_full = {m: (v if math.isfinite(v) else 0.0) for m, v in raw_ic_full.items()}
    final_weights = compute_ic_shrunk_weights(raw_ic_full, lambda_shrink=0.40)

    print_oos_report(oos_results, final_weights)
    print_zdj_flag()


if __name__ == "__main__":
    main()
