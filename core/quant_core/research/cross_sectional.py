"""Cross-sectional momentum factor engine — Phase 1 (battery) + Phase 2 (backtests).

Four classic momentum definitions for the MASI universe:

    mom_12_1    — 12-month return, skip most-recent 1 month (academic standard)
    mom_6_1     — 6-month return, skip 1 month (faster, shorter history required)
    mom_risk_adj — (12-1 return) / trailing 12-month annualised vol (dampens noise)
    mom_12_0    — 12-month return, no skip (control baseline)

No-look-ahead invariant (guardrail §1):
  score(t) uses only close prices up to and including t;
  the formation window ends at t − SKIP_1M bars for skip variants;
  forward return uses the open interval (t, t+h].

Execution timing (config.execution):
  "next_open" (default) — enter at first close after rebalance date, exit at first
                           close after next rebalance date.  Approximates executing
                           at the open of the day following the signal.
  "close"               — enter at rebalance-date close; standard for academic research.

Costs:
  config.cost_bps is the per-side transaction cost in basis points.
  Round-trip cost per unit one-way turnover = 2 * cost_bps / 10_000.

Thin cross-section (< tercile_fallback_threshold names):
  Backtest functions fall back to terciles (3 buckets) automatically.
  The statistical battery (evaluate_factor) always uses config.n_quintiles.

Phase 1 public API:
  compute_momentum_score / build_score_panel / evaluate_factor → FactorEvaluation

Phase 2 public API:
  backtest_long_only_top_quintile / backtest_long_short → PortfolioResult
  run_momentum_bakeoff → BakeoffResult
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Any, Mapping

import numpy as np
import pandas as pd

from ..horizons import DEFAULT_COST_BPS_PER_SIDE
from .stats.fdr import bh_adjusted_pvalues
from .stats.ic import _newey_west_var
from .stats.portfolio_stats import (
    assign_quintiles,
    equity_curve_with_stats,
    forward_return_horizon,
    price_at_or_before,
    quintile_return_summary,
    rebalance_dates as _get_rebalance_dates,
)

# ── Window constants (trading days) ──────────────────────────────────────────
DAYS_12M: int = 252
DAYS_6M: int = 126
DAYS_1M: int = 21
SKIP_1M: int = 21   # 1-month reversal skip (same as DAYS_1M)

VARIANTS: tuple[str, ...] = ("mom_12_1", "mom_6_1", "mom_risk_adj", "mom_12_0")

DEFAULT_COST_BPS: float = DEFAULT_COST_BPS_PER_SIDE   # 33 bps per-side from horizons.py
DEFAULT_MIN_NAMES: int = 8
DEFAULT_N_QUINTILES: int = 5
TERCILE_THRESHOLD: int = 15   # fall back to 3 buckets when cross-section < this

# Type alias: {rebalance_date -> {symbol -> score}}
ScorePanel = dict[dt.date, dict[str, float]]


# ── Config ────────────────────────────────────────────────────────────────────

@dataclass
class CrossSectionalConfig:
    min_names: int = DEFAULT_MIN_NAMES
    n_quintiles: int = DEFAULT_N_QUINTILES
    primary_horizon: int = DAYS_1M
    cost_bps: float = DEFAULT_COST_BPS         # per-side in basis points
    fdr_alpha: float = 0.10
    execution: str = "next_open"               # "close" | "next_open"
    tercile_fallback_threshold: int = TERCILE_THRESHOLD


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class FactorEvaluation:
    """Phase 1 battery output for one momentum variant."""
    variant: str
    rank_ic_mean: float
    rank_ic_tstat: float        # Newey-West t-stat on the IC time-series
    ic_pvalue: float            # two-sided p-value (standard-normal approximation)
    ic_by_date: list[dict[str, Any]]    # [{date, ic, n}, …]
    ic_decay: list[dict[str, Any]]      # [{horizon_days, mean_ic, n}, …]
    quintile_returns: list[dict[str, Any]]  # output of quintile_return_summary
    quintile_spread: float      # mean(Q_max) − mean(Q_min) forward return
    quintile_monotonicity: float  # Spearman(quintile_index, mean_return)
    n_dates: int
    n_skipped: int
    warnings: list[str] = field(default_factory=list)


@dataclass
class PortfolioResult:
    """Phase 2 backtest output: long-only or long-short portfolio equity curve."""
    dates: list[str]              # exit dates (ISO)
    equity: list[float]           # cumulative NAV (starts at 1.0)
    drawdown: list[float]         # running drawdown from peak
    gross_returns: list[float]    # per-period gross return
    net_returns: list[float]      # per-period net-of-cost return
    total_return: float           # terminal NAV − 1
    gross_sharpe: float           # annualised Sharpe on gross returns (diagnostic only)
    after_cost_sharpe: float      # annualised Sharpe on net returns (headline)
    max_drawdown: float           # worst peak-to-trough drawdown (negative)
    n_trades: int                 # total individual stock-level transactions (buys + sells)
    turnover: list[float]         # per-period one-way portfolio turnover
    avg_turnover: float           # mean one-way turnover across periods
    holdings: list[dict[str, Any]]  # [{date, top_quintile, bottom_quintile}, …]
    mode: str                     # "long_only" | "long_short"
    execution: str                # "close" | "next_open"
    warnings: list[str] = field(default_factory=list)


@dataclass
class BakeoffResult:
    """Phase 2 bake-off output: all 4 variants, BH FDR, and winner selection."""
    variants: list[str]
    evaluations: dict[str, FactorEvaluation]   # Phase 1 battery per variant
    long_only: dict[str, PortfolioResult]
    long_short: dict[str, PortfolioResult]
    bh_qvalues: dict[str, float]               # BH-adjusted p-values (family = 4 variants)
    winner_key: str                            # "" if no variant passes FDR
    ranked_variants: list[str]                 # sorted by net Sharpe desc, IC t-stat desc
    fdr_pass: dict[str, bool]                  # whether each variant passes BH FDR
    survivorship_warning: str                  # non-empty if bias is detected


# ── Phase 1: score functions ──────────────────────────────────────────────────

def compute_momentum_score(
    close: pd.Series,
    variant: str,
    asof: pd.Timestamp,
) -> float | None:
    """Momentum score at rebalance date `asof` using only close prices ≤ asof.

    Returns None when there is insufficient price history for the requested
    variant (so the caller can skip this symbol/date cleanly).

    No look-ahead: formation window ends at asof − SKIP_1M bars for variants
    with a skip; asof itself for mom_12_0.
    """
    # Restrict to history available at asof (no look-ahead)
    hist = close[close.index <= asof].sort_index()
    n = len(hist)

    if variant == "mom_12_1":
        # formation: bar[-(DAYS_12M + SKIP_1M + 1)] → bar[-(SKIP_1M + 1)]
        needed = DAYS_12M + SKIP_1M + 1
        if n < needed:
            return None
        p_start = float(hist.iloc[-(DAYS_12M + SKIP_1M + 1)])
        p_end = float(hist.iloc[-(SKIP_1M + 1)])
        return _safe_return(p_start, p_end)

    if variant == "mom_6_1":
        needed = DAYS_6M + SKIP_1M + 1
        if n < needed:
            return None
        p_start = float(hist.iloc[-(DAYS_6M + SKIP_1M + 1)])
        p_end = float(hist.iloc[-(SKIP_1M + 1)])
        return _safe_return(p_start, p_end)

    if variant == "mom_risk_adj":
        # (12-1 return) / annualised vol over the same formation window
        needed = DAYS_12M + SKIP_1M + 1
        if n < needed:
            return None
        form_start_idx = n - (DAYS_12M + SKIP_1M + 1)
        skip_end_idx = n - (SKIP_1M + 1)
        p_start = float(hist.iloc[form_start_idx])
        p_end = float(hist.iloc[skip_end_idx])
        ret = _safe_return(p_start, p_end)
        if ret is None:
            return None
        # Daily-return vol over the formation window
        window = hist.iloc[form_start_idx : skip_end_idx + 1]
        daily_rets = window.pct_change().dropna()
        if len(daily_rets) < 10:
            return None
        vol = float(daily_rets.std(ddof=1))
        if vol <= 0 or not math.isfinite(vol):
            return None
        ann_vol = vol * math.sqrt(DAYS_12M)
        return ret / ann_vol

    if variant == "mom_12_0":
        # Control: no skip — formation ends at asof itself
        needed = DAYS_12M + 1
        if n < needed:
            return None
        p_start = float(hist.iloc[-(DAYS_12M + 1)])
        p_end = float(hist.iloc[-1])
        return _safe_return(p_start, p_end)

    raise ValueError(f"Unknown momentum variant: {variant!r}. Valid: {VARIANTS}")


def build_score_panel(
    close_by_symbol: Mapping[str, pd.Series],
    rebalance_dates: list[pd.Timestamp],
    variant: str,
    *,
    min_names: int = DEFAULT_MIN_NAMES,
) -> tuple[ScorePanel, list[dt.date]]:
    """Score all symbols at each rebalance date for `variant`.

    Returns:
        panel   — {date: {symbol: score}} for dates with ≥ min_names valid scores
        skipped — dates dropped because fewer than min_names names were scoreable
    """
    panel: ScorePanel = {}
    skipped: list[dt.date] = []

    for ts in rebalance_dates:
        scores: dict[str, float] = {}
        for sym, close in close_by_symbol.items():
            s = compute_momentum_score(close, variant, ts)
            if s is not None and math.isfinite(s):
                scores[sym] = s

        if len(scores) < min_names:
            skipped.append(ts.date())
            continue

        panel[ts.date()] = scores

    return panel, skipped


# ── Phase 1: factor evaluation battery ───────────────────────────────────────

def evaluate_factor(
    score_panel: ScorePanel,
    close_by_symbol: Mapping[str, pd.Series],
    fwd_horizons: list[int],
    config: CrossSectionalConfig | None = None,
    *,
    variant: str = "",
) -> FactorEvaluation:
    """Full cross-sectional battery for a pre-built score panel.

    For each rebalance date t in score_panel:
      1. Compute forward returns over config.primary_horizon trading days.
      2. Compute cross-sectional rank-IC (Spearman of score vs fwd return).
      3. Assign quintiles on the scored universe.

    Then aggregate IC series (Newey-West t-stat, two-sided p-value, IC decay
    at each horizon in fwd_horizons) and quintile return statistics.
    """
    cfg = config or CrossSectionalConfig()
    h = cfg.primary_horizon

    ic_by_date: list[dict[str, Any]] = []
    period_records: list[dict[str, Any]] = []
    n_skipped = 0

    for date in sorted(score_panel):
        scores = score_panel[date]
        ts = pd.Timestamp(date)

        # Forward returns — only symbols present in scores AND in close_by_symbol
        fwd: dict[str, float] = {}
        for sym, score in scores.items():
            if sym not in close_by_symbol:
                continue
            r = forward_return_horizon(close_by_symbol[sym], ts, h)
            if r is not None and math.isfinite(r):
                fwd[sym] = r

        if len(fwd) < cfg.min_names:
            n_skipped += 1
            continue

        # Cross-sectional rank-IC at this date
        sig = pd.Series({sym: scores[sym] for sym in fwd}, dtype=float)
        ret_s = pd.Series(fwd, dtype=float)
        ic = _cross_spearman(sig, ret_s)
        ic_by_date.append({"date": date.isoformat(), "ic": ic, "n": len(fwd)})

        # Quintile records (always use config.n_quintiles for the battery)
        qs = assign_quintiles({sym: scores[sym] for sym in fwd}, n=cfg.n_quintiles)
        for sym, fwd_ret in fwd.items():
            period_records.append({
                "date": date.isoformat(),
                "symbol": sym,
                "signal": scores[sym],
                "forward_return": fwd_ret,
                "quintile": qs.get(sym, 0),
            })

    # ── Aggregate IC stats ────────────────────────────────────────────────────
    ic_vals = [
        row["ic"] for row in ic_by_date
        if row["ic"] is not None and math.isfinite(row["ic"])
    ]
    ic_arr = np.array(ic_vals, dtype=float)

    if len(ic_arr) >= 3:
        rank_ic_mean = float(np.mean(ic_arr))
        nw_var = _newey_west_var(ic_arr)
        if math.isfinite(nw_var) and nw_var > 0:
            rank_ic_tstat = rank_ic_mean / math.sqrt(nw_var)
        else:
            rank_ic_tstat = 0.0
        ic_pvalue = _two_sided_pvalue(rank_ic_tstat)
    else:
        rank_ic_mean = 0.0
        rank_ic_tstat = 0.0
        ic_pvalue = 1.0

    # ── IC decay ──────────────────────────────────────────────────────────────
    ic_decay = _compute_ic_decay(score_panel, close_by_symbol, fwd_horizons, cfg)

    # ── Quintile stats ────────────────────────────────────────────────────────
    q_summary = quintile_return_summary(period_records) if period_records else []

    n_q = cfg.n_quintiles
    q5_ret = next((q["mean_forward_return"] for q in q_summary if q["quintile"] == n_q), 0.0)
    q1_ret = next((q["mean_forward_return"] for q in q_summary if q["quintile"] == 1), 0.0)
    quintile_spread = q5_ret - q1_ret

    q_indices = [float(q["quintile"]) for q in q_summary]
    q_means = [float(q["mean_forward_return"]) for q in q_summary]
    monotonicity = _small_spearman(q_indices, q_means)

    warnings: list[str] = []
    if not period_records:
        warnings.append("no_rebalance_records")

    return FactorEvaluation(
        variant=variant,
        rank_ic_mean=rank_ic_mean,
        rank_ic_tstat=rank_ic_tstat,
        ic_pvalue=ic_pvalue,
        ic_by_date=ic_by_date,
        ic_decay=ic_decay,
        quintile_returns=q_summary,
        quintile_spread=quintile_spread,
        quintile_monotonicity=monotonicity,
        n_dates=len(ic_by_date),
        n_skipped=n_skipped,
        warnings=warnings,
    )


# ── Phase 2: portfolio backtests ──────────────────────────────────────────────

def backtest_long_only_top_quintile(
    score_panel: ScorePanel,
    close_by_symbol: Mapping[str, pd.Series],
    config: CrossSectionalConfig | None = None,
) -> PortfolioResult:
    """Equal-weight long position in the top quintile/tercile, monthly rebalance.

    Tercile fallback: when n_names < config.tercile_fallback_threshold (default 15),
    uses 3 buckets instead of 5 to avoid over-concentration in the top bucket.

    Cost: 2 × cost_bps/10_000 × one_way_turnover per period
    (one-way turnover = fraction of the portfolio that is new vs previous period).
    """
    cfg = config or CrossSectionalConfig()
    cost = cfg.cost_bps / 10_000.0  # per-side fraction

    sorted_dates = sorted(score_panel.keys())
    if len(sorted_dates) < 2:
        return _empty_portfolio_result("long_only", cfg.execution)

    eq_rows: list[dict[str, Any]] = []
    turnover_list: list[float] = []
    holdings_list: list[dict[str, Any]] = []
    n_trades_total = 0
    equity = 1.0
    prev_top: set[str] = set()

    for i in range(len(sorted_dates) - 1):
        entry_date = sorted_dates[i]
        exit_date = sorted_dates[i + 1]
        entry_ts = pd.Timestamp(entry_date)
        exit_ts = pd.Timestamp(exit_date)

        scores = score_panel[entry_date]
        n_names = len(scores)
        if n_names < cfg.min_names:
            continue

        # Tercile fallback for thin cross-sections
        n_q = _effective_n_quintiles(n_names, cfg)
        quintile_map = assign_quintiles(scores, n=n_q)
        top_names = sorted(sym for sym, q in quintile_map.items() if q == n_q)

        # Per-position returns
        pos_rets: list[float] = []
        valid_top: set[str] = set()
        for sym in top_names:
            if sym not in close_by_symbol:
                continue
            r = _position_return(close_by_symbol[sym], entry_ts, exit_ts, cfg.execution)
            if r is not None and math.isfinite(r):
                pos_rets.append(r)
                valid_top.add(sym)

        if not pos_rets:
            continue

        gross_return = float(np.mean(pos_rets))

        # Turnover and trade count
        new_entries = valid_top - prev_top
        old_exits = prev_top - valid_top
        n_trades_total += len(new_entries) + len(old_exits)
        turnover = _compute_turnover(prev_top, valid_top)
        prev_top = valid_top

        # Round-trip cost: sell exits + buy entries
        net_return = gross_return - 2.0 * cost * turnover
        equity *= 1.0 + net_return

        eq_rows.append({
            "date": exit_date.isoformat(),
            "gross_return": gross_return,
            "net_return": net_return,
            "equity": equity,
            "top_quintile_count": len(valid_top),
            "bottom_quintile_count": 0,
        })
        turnover_list.append(turnover)
        holdings_list.append({
            "date": entry_date.isoformat(),
            "top_quintile": sorted(valid_top),
            "bottom_quintile": [],
        })

    if not eq_rows:
        return _empty_portfolio_result("long_only", cfg.execution)

    ec = equity_curve_with_stats(eq_rows, periods_per_year=12)
    gross_arr = np.array([r["gross_return"] for r in eq_rows], dtype=float)
    net_arr = np.array([r["net_return"] for r in eq_rows], dtype=float)
    equity_arr = np.array([r["equity"] for r in eq_rows], dtype=float)

    return PortfolioResult(
        dates=[r["date"] for r in ec],
        equity=[r["equity"] for r in ec],
        drawdown=[r["drawdown"] for r in ec],
        gross_returns=gross_arr.tolist(),
        net_returns=net_arr.tolist(),
        total_return=float(equity_arr[-1] - 1.0),
        gross_sharpe=_sharpe_monthly(gross_arr),
        after_cost_sharpe=_sharpe_monthly(net_arr),
        max_drawdown=_max_dd(equity_arr),
        n_trades=n_trades_total,
        turnover=turnover_list,
        avg_turnover=float(np.mean(turnover_list)) if turnover_list else 0.0,
        holdings=holdings_list,
        mode="long_only",
        execution=cfg.execution,
    )


def backtest_long_short(
    score_panel: ScorePanel,
    close_by_symbol: Mapping[str, pd.Series],
    config: CrossSectionalConfig | None = None,
) -> PortfolioResult:
    """Dollar-neutral: long top-quintile, short bottom-quintile.

    gross_return = mean(top_returns) − mean(bottom_returns)

    Costs are applied independently to each book:
      net = gross − 2×cost×long_turnover − 2×cost×short_turnover
    """
    cfg = config or CrossSectionalConfig()
    cost = cfg.cost_bps / 10_000.0

    sorted_dates = sorted(score_panel.keys())
    if len(sorted_dates) < 2:
        return _empty_portfolio_result("long_short", cfg.execution)

    eq_rows: list[dict[str, Any]] = []
    turnover_list: list[float] = []
    holdings_list: list[dict[str, Any]] = []
    n_trades_total = 0
    equity = 1.0
    prev_top: set[str] = set()
    prev_bot: set[str] = set()

    for i in range(len(sorted_dates) - 1):
        entry_date = sorted_dates[i]
        exit_date = sorted_dates[i + 1]
        entry_ts = pd.Timestamp(entry_date)
        exit_ts = pd.Timestamp(exit_date)

        scores = score_panel[entry_date]
        n_names = len(scores)
        if n_names < cfg.min_names:
            continue

        n_q = _effective_n_quintiles(n_names, cfg)
        quintile_map = assign_quintiles(scores, n=n_q)

        top_names = sorted(sym for sym, q in quintile_map.items() if q == n_q)
        bot_names = sorted(sym for sym, q in quintile_map.items() if q == 1)

        # Long book
        long_rets: list[float] = []
        valid_top: set[str] = set()
        for sym in top_names:
            if sym not in close_by_symbol:
                continue
            r = _position_return(close_by_symbol[sym], entry_ts, exit_ts, cfg.execution)
            if r is not None and math.isfinite(r):
                long_rets.append(r)
                valid_top.add(sym)

        # Short book (negate for P&L: we profit when shorts fall)
        short_rets: list[float] = []
        valid_bot: set[str] = set()
        for sym in bot_names:
            if sym not in close_by_symbol:
                continue
            r = _position_return(close_by_symbol[sym], entry_ts, exit_ts, cfg.execution)
            if r is not None and math.isfinite(r):
                short_rets.append(r)
                valid_bot.add(sym)

        if not long_rets or not short_rets:
            continue

        mean_long = float(np.mean(long_rets))
        mean_short = float(np.mean(short_rets))
        gross_return = mean_long - mean_short   # dollar-neutral spread return

        # Turnover for each book
        new_long = valid_top - prev_top
        old_long = prev_top - valid_top
        new_short = valid_bot - prev_bot
        old_short = prev_bot - valid_bot
        n_trades_total += len(new_long) + len(old_long) + len(new_short) + len(old_short)

        long_turn = _compute_turnover(prev_top, valid_top)
        short_turn = _compute_turnover(prev_bot, valid_bot)
        prev_top = valid_top
        prev_bot = valid_bot

        # Round-trip cost on each book independently
        net_return = gross_return - 2.0 * cost * long_turn - 2.0 * cost * short_turn
        equity *= 1.0 + net_return

        eq_rows.append({
            "date": exit_date.isoformat(),
            "gross_return": gross_return,
            "net_return": net_return,
            "equity": equity,
            "top_quintile_count": len(valid_top),
            "bottom_quintile_count": len(valid_bot),
        })
        turnover_list.append((long_turn + short_turn) / 2.0)
        holdings_list.append({
            "date": entry_date.isoformat(),
            "top_quintile": sorted(valid_top),
            "bottom_quintile": sorted(valid_bot),
        })

    if not eq_rows:
        return _empty_portfolio_result("long_short", cfg.execution)

    ec = equity_curve_with_stats(eq_rows, periods_per_year=12)
    gross_arr = np.array([r["gross_return"] for r in eq_rows], dtype=float)
    net_arr = np.array([r["net_return"] for r in eq_rows], dtype=float)
    equity_arr = np.array([r["equity"] for r in eq_rows], dtype=float)

    return PortfolioResult(
        dates=[r["date"] for r in ec],
        equity=[r["equity"] for r in ec],
        drawdown=[r["drawdown"] for r in ec],
        gross_returns=gross_arr.tolist(),
        net_returns=net_arr.tolist(),
        total_return=float(equity_arr[-1] - 1.0),
        gross_sharpe=_sharpe_monthly(gross_arr),
        after_cost_sharpe=_sharpe_monthly(net_arr),
        max_drawdown=_max_dd(equity_arr),
        n_trades=n_trades_total,
        turnover=turnover_list,
        avg_turnover=float(np.mean(turnover_list)) if turnover_list else 0.0,
        holdings=holdings_list,
        mode="long_short",
        execution=cfg.execution,
    )


def run_momentum_bakeoff(
    close_by_symbol: Mapping[str, pd.Series],
    config: CrossSectionalConfig | None = None,
) -> BakeoffResult:
    """Run all 4 momentum variants through Phase 1 battery + Phase 2 backtests.

    Returns per-variant FactorEvaluation + PortfolioResult (long-only and long-short),
    BH-adjusted q-values across the 4-variant family, and winner selection.

    winner_key: highest net-Sharpe variant that also passes BH FDR.
    Returns "" if no variant survives FDR — this is a valid result ("no alpha found").
    """
    cfg = config or CrossSectionalConfig()

    non_empty = {sym: s for sym, s in close_by_symbol.items() if not s.empty}
    if not non_empty:
        return _empty_bakeoff_result()

    all_idx = pd.concat(list(non_empty.values())).index
    start = pd.Timestamp(all_idx.min())
    end = pd.Timestamp(all_idx.max())
    reb = _get_rebalance_dates(non_empty, start=start, end=end)

    evaluations: dict[str, FactorEvaluation] = {}
    long_only_results: dict[str, PortfolioResult] = {}
    long_short_results: dict[str, PortfolioResult] = {}

    for variant in VARIANTS:
        panel, _ = build_score_panel(non_empty, reb, variant, min_names=cfg.min_names)
        ev = evaluate_factor(
            panel, non_empty, [DAYS_1M, DAYS_6M, DAYS_12M], cfg, variant=variant,
        )
        evaluations[variant] = ev
        long_only_results[variant] = backtest_long_only_top_quintile(panel, non_empty, cfg)
        long_short_results[variant] = backtest_long_short(panel, non_empty, cfg)

    # BH FDR adjustment across 4 IC p-values (family = 4 variants)
    p_vals = [evaluations[v].ic_pvalue for v in VARIANTS]
    q_vals = bh_adjusted_pvalues(p_vals)
    bh_qvalues = dict(zip(VARIANTS, q_vals))
    fdr_pass = {v: q <= cfg.fdr_alpha for v, q in bh_qvalues.items()}

    ranked = _rank_bakeoff_variants(evaluations, long_only_results)
    fdr_winners = [v for v in ranked if fdr_pass[v]]
    winner_key = fdr_winners[0] if fdr_winners else ""

    return BakeoffResult(
        variants=list(VARIANTS),
        evaluations=evaluations,
        long_only=long_only_results,
        long_short=long_short_results,
        bh_qvalues=bh_qvalues,
        winner_key=winner_key,
        ranked_variants=ranked,
        fdr_pass=fdr_pass,
        survivorship_warning=_check_survivorship(close_by_symbol),
    )


# ── Private helpers (Phase 1) ─────────────────────────────────────────────────

def _safe_return(p_start: float, p_end: float) -> float | None:
    if not (math.isfinite(p_start) and math.isfinite(p_end)):
        return None
    if p_start <= 0:
        return None
    return float(p_end / p_start - 1.0)


def _cross_spearman(signal: pd.Series, returns: pd.Series) -> float | None:
    """Cross-sectional Spearman rank correlation."""
    aligned = pd.concat([signal.rename("s"), returns.rename("r")], axis=1).dropna()
    if len(aligned) < 3:
        return None
    ra = aligned["s"].rank()
    rb = aligned["r"].rank()
    if ra.nunique() < 2 or rb.nunique() < 2:
        return None
    corr = ra.corr(rb)
    return float(corr) if math.isfinite(corr) else None


def _small_spearman(x: list[float], y: list[float]) -> float:
    """Spearman on small lists (e.g., 5 quintile means)."""
    if len(x) < 3 or len(x) != len(y):
        return float("nan")
    rx = pd.Series(x, dtype=float).rank().values
    ry = pd.Series(y, dtype=float).rank().values
    mu_rx, mu_ry = rx.mean(), ry.mean()
    cov = float(np.dot(rx - mu_rx, ry - mu_ry))
    std_rx = float(np.sqrt(np.sum((rx - mu_rx) ** 2)))
    std_ry = float(np.sqrt(np.sum((ry - mu_ry) ** 2)))
    if std_rx == 0 or std_ry == 0:
        return float("nan")
    return cov / (std_rx * std_ry)


def _norm_cdf(z: float) -> float:
    """Standard normal CDF via math.erfc (no scipy dependency)."""
    return 0.5 * math.erfc(-z / math.sqrt(2.0))


def _two_sided_pvalue(tstat: float) -> float:
    if not math.isfinite(tstat):
        return 1.0
    p = 2.0 * (1.0 - _norm_cdf(abs(tstat)))
    return max(0.0, min(1.0, p))


def _compute_ic_decay(
    score_panel: ScorePanel,
    close_by_symbol: Mapping[str, pd.Series],
    fwd_horizons: list[int],
    cfg: CrossSectionalConfig,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for h in fwd_horizons:
        ics_at_h: list[float] = []
        for date in sorted(score_panel):
            scores = score_panel[date]
            ts = pd.Timestamp(date)
            fwd: dict[str, float] = {}
            for sym, score in scores.items():
                if sym not in close_by_symbol:
                    continue
                r = forward_return_horizon(close_by_symbol[sym], ts, h)
                if r is not None and math.isfinite(r):
                    fwd[sym] = r
            if len(fwd) < cfg.min_names:
                continue
            sig = pd.Series({sym: scores[sym] for sym in fwd}, dtype=float)
            ret_s = pd.Series(fwd, dtype=float)
            ic = _cross_spearman(sig, ret_s)
            if ic is not None and math.isfinite(ic):
                ics_at_h.append(ic)
        mean_ic = float(np.mean(ics_at_h)) if ics_at_h else float("nan")
        out.append({"horizon_days": h, "mean_ic": mean_ic, "n": len(ics_at_h)})
    return out


# ── Private helpers (Phase 2) ─────────────────────────────────────────────────

def _price_first_after(series: pd.Series, date: pd.Timestamp) -> float | None:
    """First close price strictly after `date` — proxy for next-day open."""
    future = series[series.index > date]
    if future.empty:
        return None
    val = float(future.iloc[0])
    return val if math.isfinite(val) else None


def _position_return(
    series: pd.Series,
    entry: pd.Timestamp,
    exit_: pd.Timestamp,
    execution: str,
) -> float | None:
    """Return for a single position under the configured execution mode."""
    if execution == "next_open":
        p_in = _price_first_after(series, entry)
        p_out = _price_first_after(series, exit_)
    else:  # "close"
        p_in = price_at_or_before(series, entry)
        p_out = price_at_or_before(series, exit_)
    if p_in is None or p_out is None or p_in <= 0:
        return None
    return float(p_out / p_in - 1.0)


def _effective_n_quintiles(n_names: int, cfg: CrossSectionalConfig) -> int:
    """Tercile fallback: use 3 buckets when the cross-section is below the threshold."""
    if n_names < cfg.tercile_fallback_threshold:
        return 3
    return cfg.n_quintiles


def _compute_turnover(prev: set[str], current: set[str]) -> float:
    """One-way portfolio turnover: fraction of current holdings that are new."""
    if not current:
        return 0.0
    if not prev:
        return 1.0  # first period: entire portfolio is new
    return len(current - prev) / len(current)


def _sharpe_monthly(returns: np.ndarray) -> float:
    """Annualised Sharpe ratio for a monthly-frequency return series."""
    if len(returns) < 5:
        return float("nan")
    mu = float(np.mean(returns))
    sigma = float(np.std(returns, ddof=1))
    if sigma <= 0:
        return float("nan")
    return float(mu / sigma * math.sqrt(12))


def _max_dd(equity: np.ndarray) -> float:
    """Worst peak-to-trough drawdown (negative value)."""
    if len(equity) == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd = equity / np.where(peak <= 0, 1.0, peak) - 1.0
    return float(np.min(dd))


def _empty_portfolio_result(mode: str, execution: str) -> PortfolioResult:
    return PortfolioResult(
        dates=[], equity=[], drawdown=[], gross_returns=[], net_returns=[],
        total_return=0.0, gross_sharpe=float("nan"), after_cost_sharpe=float("nan"),
        max_drawdown=0.0, n_trades=0, turnover=[], avg_turnover=0.0, holdings=[],
        mode=mode, execution=execution, warnings=["no_rebalance_records"],
    )


def _rank_bakeoff_variants(
    evaluations: dict[str, FactorEvaluation],
    long_only: dict[str, PortfolioResult],
) -> list[str]:
    """Sort variants: net Sharpe DESC (primary), IC t-stat DESC (secondary); NaN last."""
    def _key(v: str) -> tuple[float, float]:
        sr = long_only[v].after_cost_sharpe
        t = evaluations[v].rank_ic_tstat
        return (
            -sr if math.isfinite(sr) else float("inf"),
            -t if math.isfinite(t) else float("inf"),
        )
    return sorted(VARIANTS, key=_key)


def _check_survivorship(close_by_symbol: Mapping[str, pd.Series]) -> str:
    """Heuristic: if ≥ 90% of symbols end near the same date, flag survivorship bias."""
    if not close_by_symbol:
        return ""
    last_dates = [s.index.max() for s in close_by_symbol.values() if not s.empty]
    if not last_dates:
        return ""
    max_last = max(last_dates)
    cutoff = max_last - pd.Timedelta(days=30)
    pct = sum(1 for d in last_dates if d >= cutoff) / len(last_dates)
    if pct >= 1.0:
        return (
            "WARN: all symbols end at the same date — "
            "delisted names may be absent (survivorship bias)"
        )
    if pct > 0.90:
        return (
            f"WARN: {pct:.0%} of symbols end near the most recent date — "
            "possible survivorship bias"
        )
    return ""


def _empty_bakeoff_result() -> BakeoffResult:
    empty_ev = FactorEvaluation(
        variant="", rank_ic_mean=0.0, rank_ic_tstat=0.0, ic_pvalue=1.0,
        ic_by_date=[], ic_decay=[], quintile_returns=[], quintile_spread=0.0,
        quintile_monotonicity=float("nan"), n_dates=0, n_skipped=0,
        warnings=["no_price_data"],
    )
    empty_port = _empty_portfolio_result("long_only", "next_open")
    return BakeoffResult(
        variants=list(VARIANTS),
        evaluations={v: empty_ev for v in VARIANTS},
        long_only={v: empty_port for v in VARIANTS},
        long_short={v: empty_port for v in VARIANTS},
        bh_qvalues={v: 1.0 for v in VARIANTS},
        winner_key="",
        ranked_variants=list(VARIANTS),
        fdr_pass={v: False for v in VARIANTS},
        survivorship_warning="",
    )
