"""True walk-forward evaluation (WFO) for the support/resistance layer.

Pure module: no DB/HTTP/plotting imports. All randomness is seeded.

Fixes two known biases present in the legacy single-window touch simulator
(`_sr_simulate_window_touch` in the router):
  1. Entry fills always at the level itself, even on a gap-down open — this
     module fills at `open` when it is more favourable to the counterparty
     (i.e. below the support level), which is the true achievable fill.
  2. Same-bar round trips (buy AND sell on the same bar) were allowed even
     though intrabar OHLC ordering is unknowable — this module forbids
     exiting on the same bar a position was opened.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from core.quant_core.research.edge import (
    MC_PVALUE_THRESHOLD,
    N_MIN,
    WILSON_LB_THRESHOLD,
)
from core.quant_core.research.stats.hit_rate import wilson_ci

SR_WFO_VERSION = "2026-07-08-sr-wfo-v1"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _finite(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if np.isfinite(out) else None


def _max_drawdown(returns: np.ndarray) -> float:
    if returns.size == 0:
        return 0.0
    equity = np.cumprod(1.0 + returns.astype("float64"))
    peak = np.maximum.accumulate(equity)
    drawdown = (peak - equity) / np.where(peak > 0.0, peak, 1.0)
    return float(np.nanmax(drawdown)) if drawdown.size else 0.0


def _sharpe(returns: np.ndarray, *, periods_per_year: float = 252.0) -> float:
    if returns.size < 2:
        return 0.0
    std = float(np.std(returns, ddof=1))
    if std <= 0.0 or not np.isfinite(std):
        return 0.0
    mean = float(np.mean(returns))
    value = mean / std * np.sqrt(float(periods_per_year))
    return float(value) if np.isfinite(value) else 0.0


def _clamp01(value: float) -> float:
    if not np.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, float(value)))


def _total_return(returns: np.ndarray) -> float:
    if returns.size == 0:
        return 0.0
    return float(np.prod(1.0 + returns.astype("float64")) - 1.0)


def _cagr(total_return: float, n_bars: int, *, periods_per_year: float = 252.0) -> float:
    if total_return <= -1.0:
        return -1.0
    years = max(int(n_bars), 1) / float(periods_per_year)
    return float((1.0 + total_return) ** (1.0 / years) - 1.0)


# ---------------------------------------------------------------------------
# window plan (pure replica of the router's `_sr_window_plan`)
# ---------------------------------------------------------------------------


def sr_window_plan(*, train: int, test: int, step: int, n_bars: int) -> list[tuple[int, int, int, int, int]]:
    """Return list of (window_index, train_start, train_end, test_start, test_end)."""
    train_len = int(train)
    test_len = int(test)
    step_len = int(step)
    if n_bars < (train_len + test_len + 1):
        return []
    windows: list[tuple[int, int, int, int, int]] = []
    window_index = 0
    for start in range(0, n_bars - train_len - test_len, step_len):
        train_end = start + train_len
        test_start = train_end
        test_end = min(test_start + test_len, n_bars - 1)
        oos_len = test_end - test_start
        if oos_len < 2:
            continue
        windows.append((window_index, start, train_end, test_start, test_end))
        window_index += 1
    return windows


# ---------------------------------------------------------------------------
# fill-aware, no-same-bar-round-trip touch simulator
# ---------------------------------------------------------------------------


def simulate_touch_pair(
    *,
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    open_: np.ndarray | None,
    support_series: np.ndarray,
    resistance_series: np.ndarray,
    start: int,
    end: int,
    cost_bps: float,
    cooldown_bars: int,
) -> dict[str, Any]:
    """Long-only, 1-unit touch simulation over bars (start, end], flat at `start`.

    Execution model: SAME-BAR at the level, never deferred to the next bar's
    open. Support/resistance levels at bar t are computed from data through
    t-1 (causal), so a resting limit order at that level is genuinely
    implementable intraday on bar t itself: entry fills at `support[t]` (or
    `open[t]` if the bar gaps below it) on the very bar the touch occurs.
    A "touch" additionally requires `support[t] <= close[t-1]` — the market
    must dip DOWN to a level that sat at or below the prior close. Without
    this guard a support series above the market (possible for ma_anchor or
    quantile-derived series) would satisfy `low <= support` on every bar and
    degenerate into quasi buy-and-hold, falsely flagging the line as
    pertinent. The exit side needs no such guard: selling at a resistance
    already below the market simply fills at the open, which is economically
    real. Exit fills at `resistance[t]` (or `open[t]` if the bar gaps above it) on
    exit fills at `resistance[t]` (or `open[t]` if the bar gaps above it) on
    the very bar the touch occurs. The goal is to measure the pertinence of
    the line itself, so the fill is credited at the line, not delayed a bar.
    The ONLY next-bar deferral in this simulator is that a position opened on
    bar t cannot also exit at resistance on bar t (no same-bar round trips —
    intrabar OHLC ordering is unknowable, so exit is deferred to bar t+1 at
    the earliest). Forced liquidation at the end of a slice is marked at
    `close[end]`, never at a following bar.

    Returns {"returns": np.ndarray of length end-start, "trades": list[dict], "n_trades": int}.
    """
    if end <= start:
        return {"returns": np.zeros(0, dtype="float64"), "trades": [], "n_trades": 0}

    cost_frac = float(cost_bps) / 10_000.0
    n_out = end - start
    returns = np.zeros(n_out, dtype="float64")
    trades: list[dict[str, Any]] = []

    position = 0
    entry_fill: float | None = None
    entry_bar: int | None = None
    cooldown_left = 0

    for bar_index in range(start + 1, end + 1):
        out_idx = bar_index - start - 1
        prev_close = float(close[bar_index - 1])
        cur_close = float(close[bar_index])
        hi = float(high[bar_index])
        lo = float(low[bar_index])
        op = float(open_[bar_index]) if open_ is not None else None
        support = _finite(support_series[bar_index])
        resistance = _finite(resistance_series[bar_index])

        opened_this_bar = False
        exited_this_bar = False

        # 1. Entry
        if (
            position == 0
            and cooldown_left <= 0
            and support is not None
            and lo <= support
            and support <= prev_close
            and (resistance is None or support < resistance)
        ):
            fill = support
            if op is not None and op < support:
                fill = op
            entry_fill = fill
            entry_bar = bar_index
            position = 1
            opened_this_bar = True
            returns[out_idx] += (cur_close / fill - 1.0) - cost_frac

        # 2. Exit (only if not opened this bar — no same-bar round trips)
        elif (
            position == 1
            and not opened_this_bar
            and resistance is not None
            and hi >= resistance
        ):
            fill = resistance
            if op is not None and op > resistance:
                fill = op
            exit_ret = (fill / prev_close - 1.0) - cost_frac
            returns[out_idx] += exit_ret
            pnl_return = (fill * (1.0 - cost_frac)) / (float(entry_fill) * (1.0 + cost_frac)) - 1.0 if entry_fill else 0.0
            trades.append(
                {
                    "entry_bar": int(entry_bar) if entry_bar is not None else None,
                    "exit_bar": int(bar_index),
                    "entry_price": float(entry_fill) if entry_fill is not None else None,
                    "exit_price": float(fill),
                    "pnl_return": float(pnl_return),
                    "bars_held": int(bar_index - entry_bar) if entry_bar is not None else None,
                    "exit_reason": "resistance",
                }
            )
            position = 0
            entry_fill = None
            entry_bar = None
            cooldown_left = int(cooldown_bars)
            exited_this_bar = True

        # 3. Holding bar (no fill this bar)
        elif position == 1 and not opened_this_bar:
            returns[out_idx] += cur_close / prev_close - 1.0

        # 4. flat bar -> 0.0 already default

        if not opened_this_bar and not exited_this_bar and cooldown_left > 0:
            cooldown_left -= 1
        elif exited_this_bar:
            pass  # cooldown_left just set above; do not decrement same bar

    # 5. Forced liquidation at close[end] if still long.
    # The entry-bar return (if entry was on `end`) or the holding-bar return
    # (if entry was earlier) already marks the position to close[end]; forced
    # liquidation adds the exit-side cost on top of that.
    if position == 1 and entry_fill is not None and entry_bar is not None:
        fill = float(close[end])
        out_idx = end - start - 1
        returns[out_idx] -= cost_frac
        pnl_return = (fill * (1.0 - cost_frac)) / (float(entry_fill) * (1.0 + cost_frac)) - 1.0
        trades.append(
            {
                "entry_bar": int(entry_bar),
                "exit_bar": int(end),
                "entry_price": float(entry_fill),
                "exit_price": float(fill),
                "pnl_return": float(pnl_return),
                "bars_held": int(end - entry_bar),
                "exit_reason": "forced",
            }
        )

    return {"returns": returns, "trades": trades, "n_trades": len(trades)}


# ---------------------------------------------------------------------------
# objective (mirrors `_sr_direct_objective_summary` weights)
# ---------------------------------------------------------------------------


def _objective(returns: np.ndarray, trades: list[dict[str, Any]]) -> dict[str, float]:
    total_return = _total_return(returns)
    max_drawdown = _max_drawdown(returns)
    n_trades = len(trades)
    wins = sum(1 for t in trades if float(t.get("pnl_return") or 0.0) > 0.0)
    win_rate = float(wins / n_trades) if n_trades > 0 else 0.0

    net_return_score = _clamp01(0.5 + total_return * 2.5)
    consistency_score = _clamp01(win_rate)
    drawdown_score = _clamp01(1.0 - (max_drawdown / 0.25))
    trade_activity_score = _clamp01(n_trades / 3.0)
    sr_objective_score = (
        0.45 * net_return_score
        + 0.25 * consistency_score
        + 0.20 * drawdown_score
        + 0.10 * trade_activity_score
    )
    return {
        "sr_objective_score": float(sr_objective_score),
        "net_return_score": float(net_return_score),
        "consistency_score": float(consistency_score),
        "drawdown_score": float(drawdown_score),
        "trade_activity_score": float(trade_activity_score),
        "n_trades": float(n_trades),
        "total_return": float(total_return),
        "max_drawdown": float(max_drawdown),
        "win_rate": float(win_rate),
    }


def _bootstrap_mean_positive_pvalue(returns: np.ndarray, *, seed: int, n_iter: int) -> float | None:
    """Bootstrap p-value that the true mean stitched return is <= 0.

    Resamples the stitched returns with replacement `n_iter` times and reports
    the fraction of bootstrap means that are non-positive. A low value means
    the observed positive mean return is unlikely to be a sampling artifact.
    """
    if returns.size < 2:
        return None
    observed = float(np.mean(returns))
    if not np.isfinite(observed):
        return None
    rng = np.random.default_rng(int(seed))
    samples = max(100, int(n_iter))
    boot_means = np.empty(samples, dtype="float64")
    for i in range(samples):
        draw = rng.choice(returns, size=returns.size, replace=True)
        boot_means[i] = float(np.mean(draw))
    p_nonpositive = float(np.mean(boot_means <= 0.0))
    return p_nonpositive


def _stitched_metrics(
    returns: np.ndarray,
    trades: list[dict[str, Any]],
    *,
    seed: int,
    bootstrap_iter: int,
    periods_per_year: float = 252.0,
) -> dict[str, Any]:
    total_return = _total_return(returns)
    cagr = _cagr(total_return, returns.size, periods_per_year=periods_per_year)
    sharpe = _sharpe(returns, periods_per_year=periods_per_year)
    max_drawdown = _max_drawdown(returns)
    n_trades = len(trades)
    wins = sum(1 for t in trades if float(t.get("pnl_return") or 0.0) > 0.0)
    hit_rate = float(wins / n_trades) if n_trades > 0 else 0.0
    wilson_lower, wilson_upper = wilson_ci(wins, n_trades) if n_trades > 0 else (0.0, 1.0)
    pvalue = _bootstrap_mean_positive_pvalue(returns, seed=seed, n_iter=bootstrap_iter)
    return {
        "total_return": float(total_return),
        "cagr": float(cagr),
        "sharpe": float(sharpe),
        "max_drawdown": float(max_drawdown),
        "n_trades": int(n_trades),
        "hit_rate": float(hit_rate),
        "wilson_lb": float(wilson_lower),
        "wilson_ub": float(wilson_upper),
        "bootstrap_pvalue": float(pvalue) if pvalue is not None else None,
        "n_bars": int(returns.size),
    }


# ---------------------------------------------------------------------------
# main WFO driver
# ---------------------------------------------------------------------------


def run_sr_wfo(
    *,
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    open_: np.ndarray | None,
    pair_series: dict[str, tuple[np.ndarray, np.ndarray]],
    pair_meta: dict[str, dict[str, Any]],
    train: int,
    test: int,
    step: int,
    cost_bps: float,
    cooldown_bars: int,
    min_train_trades: int = 3,
    bootstrap_iter: int = 1000,
    seed: int = 42,
    periods_per_year: float = 252.0,
) -> dict[str, Any]:
    params_echo = {
        "train": int(train),
        "test": int(test),
        "step": int(step),
        "cost_bps": float(cost_bps),
        "cooldown_bars": int(cooldown_bars),
        "min_train_trades": int(min_train_trades),
        "bootstrap_iter": int(bootstrap_iter),
        "seed": int(seed),
        "periods_per_year": float(periods_per_year),
    }
    n_bars = int(len(close))
    windows_plan = sr_window_plan(train=train, test=test, step=step, n_bars=n_bars)
    if not windows_plan:
        return {
            "version": SR_WFO_VERSION,
            "status": "insufficient_history",
            "windows": [],
            "procedure_oos": {},
            "baselines": {},
            "stability": {},
            "live_recommendation": {},
            "decision": "no_edge",
            "explanation": "Historique insuffisant pour construire au moins une fenetre walk-forward.",
            "params_echo": params_echo,
        }

    pair_ids = sorted(pair_series.keys())

    # 2. simulate each pair ONCE over the full history
    continuous: dict[str, dict[str, Any]] = {}
    for pair_id in pair_ids:
        support_s, resistance_s = pair_series[pair_id]
        sim = simulate_touch_pair(
            close=close,
            high=high,
            low=low,
            open_=open_,
            support_series=support_s,
            resistance_series=resistance_s,
            start=0,
            end=n_bars - 1,
            cost_bps=cost_bps,
            cooldown_bars=cooldown_bars,
        )
        continuous[pair_id] = sim

    def _train_slice_objective(pair_id: str, train_start: int, train_end: int) -> tuple[dict[str, float], int] | None:
        sim = continuous[pair_id]
        returns = sim["returns"]
        slice_returns = returns[train_start:train_end]
        trades_in_slice = [
            t for t in sim["trades"]
            if t.get("exit_bar") is not None and train_start <= int(t["exit_bar"]) < train_end
        ]
        n_closed = len(trades_in_slice)
        if n_closed < int(min_train_trades):
            return None
        return _objective(slice_returns, trades_in_slice), n_closed

    window_records: list[dict[str, Any]] = []
    stitched_returns_parts: list[np.ndarray] = []
    stitched_trades: list[dict[str, Any]] = []
    stitched_offset = 0
    pair_win_counts: dict[str, int] = {}
    support_win_counts: dict[str, int] = {}
    resistance_win_counts: dict[str, int] = {}
    n_selectable_windows = 0

    for window in windows_plan:
        window_index, train_start, train_end, test_start, test_end = window
        eligible: list[tuple[str, float]] = []
        for pair_id in pair_ids:
            result = _train_slice_objective(pair_id, train_start, train_end)
            if result is None:
                continue
            objective, _n_closed = result
            eligible.append((pair_id, objective["sr_objective_score"]))

        selected_pair_id: str | None = None
        train_objective: float | None = None
        if eligible:
            n_selectable_windows += 1
            eligible.sort(key=lambda item: (-item[1], item[0]))
            selected_pair_id, train_objective = eligible[0]
            pair_win_counts[selected_pair_id] = pair_win_counts.get(selected_pair_id, 0) + 1
            meta = pair_meta.get(selected_pair_id, {})
            s_key = f"{meta.get('support_method_id')}:{meta.get('support_line_id')}"
            r_key = f"{meta.get('resistance_method_id')}:{meta.get('resistance_line_id')}"
            support_win_counts[s_key] = support_win_counts.get(s_key, 0) + 1
            resistance_win_counts[r_key] = resistance_win_counts.get(r_key, 0) + 1

            support_s, resistance_s = pair_series[selected_pair_id]
            test_sim = simulate_touch_pair(
                close=close,
                high=high,
                low=low,
                open_=open_,
                support_series=support_s,
                resistance_series=resistance_s,
                start=test_start,
                end=test_end,
                cost_bps=cost_bps,
                cooldown_bars=cooldown_bars,
            )
            test_returns = test_sim["returns"]
            test_trades = test_sim["trades"]
        else:
            test_returns = np.zeros(max(0, test_end - test_start), dtype="float64")
            test_trades = []

        # offset trades to global bar index already correct (absolute bar indices used)
        for t in test_trades:
            t2 = dict(t)
            stitched_trades.append(t2)
        stitched_returns_parts.append(test_returns)

        window_records.append(
            {
                "window_index": int(window_index),
                "train_start": int(train_start),
                "train_end": int(train_end),
                "test_start": int(test_start),
                "test_end": int(test_end),
                "selected_pair_id": selected_pair_id,
                "selected_pair_meta": dict(pair_meta.get(selected_pair_id, {})) if selected_pair_id else None,
                "train_objective": float(train_objective) if train_objective is not None else None,
                "test_metrics": {
                    "sharpe": _sharpe(test_returns, periods_per_year=periods_per_year),
                    "total_return": _total_return(test_returns),
                    "max_drawdown": _max_drawdown(test_returns),
                    "n_trades": len(test_trades),
                },
                "test_trades": [dict(t) for t in test_trades],
            }
        )
        stitched_offset += test_returns.size

    stitched_returns = np.concatenate(stitched_returns_parts) if stitched_returns_parts else np.zeros(0, dtype="float64")
    procedure_oos = _stitched_metrics(
        stitched_returns,
        stitched_trades,
        seed=seed,
        bootstrap_iter=bootstrap_iter,
        periods_per_year=periods_per_year,
    )

    # 5a. buy & hold baseline over the same stitched test spans
    bh_parts: list[np.ndarray] = []
    for window in windows_plan:
        _wi, _ts, _te, test_start, test_end = window
        if test_end <= test_start:
            bh_parts.append(np.zeros(0, dtype="float64"))
            continue
        seg_close = close[test_start:test_end + 1].astype("float64")
        bh_returns = seg_close[1:] / seg_close[:-1] - 1.0
        bh_parts.append(bh_returns)
    bh_stitched = np.concatenate(bh_parts) if bh_parts else np.zeros(0, dtype="float64")
    buy_hold = {
        "total_return": _total_return(bh_stitched),
        "cagr": _cagr(_total_return(bh_stitched), bh_stitched.size, periods_per_year=periods_per_year),
        "sharpe": _sharpe(bh_stitched, periods_per_year=periods_per_year),
        "max_drawdown": _max_drawdown(bh_stitched),
        "n_bars": int(bh_stitched.size),
    }

    # 5b. in-sample-best baseline: single best pair on FULL history, evaluated flat-start per test window
    full_history_scores: list[tuple[str, float]] = []
    for pair_id in pair_ids:
        sim = continuous[pair_id]
        objective = _objective(sim["returns"], sim["trades"])
        full_history_scores.append((pair_id, objective["sr_objective_score"]))
    in_sample_best_pair_id: str | None = None
    if full_history_scores:
        full_history_scores.sort(key=lambda item: (-item[1], item[0]))
        in_sample_best_pair_id = full_history_scores[0][0]

    isb_returns_parts: list[np.ndarray] = []
    isb_trades: list[dict[str, Any]] = []
    if in_sample_best_pair_id is not None:
        support_s, resistance_s = pair_series[in_sample_best_pair_id]
        for window in windows_plan:
            _wi, _ts, _te, test_start, test_end = window
            sim = simulate_touch_pair(
                close=close,
                high=high,
                low=low,
                open_=open_,
                support_series=support_s,
                resistance_series=resistance_s,
                start=test_start,
                end=test_end,
                cost_bps=cost_bps,
                cooldown_bars=cooldown_bars,
            )
            isb_returns_parts.append(sim["returns"])
            isb_trades.extend(sim["trades"])
    isb_stitched = np.concatenate(isb_returns_parts) if isb_returns_parts else np.zeros(0, dtype="float64")
    in_sample_best = {
        "pair_id": in_sample_best_pair_id,
        "pair_meta": dict(pair_meta.get(in_sample_best_pair_id, {})) if in_sample_best_pair_id else None,
        "total_return": _total_return(isb_stitched),
        "cagr": _cagr(_total_return(isb_stitched), isb_stitched.size, periods_per_year=periods_per_year),
        "sharpe": _sharpe(isb_stitched, periods_per_year=periods_per_year),
        "max_drawdown": _max_drawdown(isb_stitched),
        "n_trades": len(isb_trades),
    }

    # 6. stability
    modal_pair_id, modal_wins = (None, 0)
    if pair_win_counts:
        modal_pair_id, modal_wins = max(pair_win_counts.items(), key=lambda item: (item[1], item[0]))
    selection_stability = (
        float(modal_wins / n_selectable_windows) if n_selectable_windows > 0 else 0.0
    )
    stability = {
        "pair_win_counts": dict(pair_win_counts),
        "support_win_counts": dict(support_win_counts),
        "resistance_win_counts": dict(resistance_win_counts),
        "modal_pair_id": modal_pair_id,
        "modal_pair_wins": int(modal_wins),
        "n_selectable_windows": int(n_selectable_windows),
        "selection_stability": float(selection_stability),
    }

    # 7. live recommendation: rank on last train_bars ending at final bar
    live_train_start = max(0, n_bars - 1 - int(train))
    live_train_end = n_bars - 1
    live_eligible: list[tuple[str, float]] = []
    for pair_id in pair_ids:
        result = _train_slice_objective(pair_id, live_train_start, live_train_end)
        if result is None:
            continue
        objective, _n_closed = result
        live_eligible.append((pair_id, objective["sr_objective_score"]))
    live_recommendation: dict[str, Any] = {
        "pair_id": None,
        "pair_meta": None,
        "train_objective": None,
        "note": (
            "Recommandation basee sur le classement in-sample le plus recent; "
            "la qualite attendue est celle du procedure_oos ci-dessus, pas les "
            "statistiques in-sample de cette paire."
        ),
    }
    if live_eligible:
        live_eligible.sort(key=lambda item: (-item[1], item[0]))
        live_pair_id, live_objective = live_eligible[0]
        live_recommendation["pair_id"] = live_pair_id
        live_recommendation["pair_meta"] = dict(pair_meta.get(live_pair_id, {}))
        live_recommendation["train_objective"] = float(live_objective)
        confidence_denominator = int(n_selectable_windows)
        confidence_numerator = int(pair_win_counts.get(live_pair_id, 0))
        live_recommendation["confidence"] = {
            "rate": (
                float(confidence_numerator / confidence_denominator)
                if confidence_denominator > 0
                else None
            ),
            "basis": "exact_pair_stability",
            "numerator": confidence_numerator,
            "denominator": confidence_denominator,
            "explanation": (
                "Current live S/R pair recurrence across selectable historical "
                "walk-forward training windows."
            ),
        }

    # 8. decision gate
    bootstrap_pvalue = procedure_oos.get("bootstrap_pvalue")
    wilson_lb = procedure_oos.get("wilson_lb", 0.0)
    proc_n_trades = procedure_oos.get("n_trades", 0)
    proc_sharpe = procedure_oos.get("sharpe", 0.0)
    proc_total_return = procedure_oos.get("total_return", 0.0)

    actionable = bool(
        bootstrap_pvalue is not None
        and bootstrap_pvalue <= MC_PVALUE_THRESHOLD
        and wilson_lb >= WILSON_LB_THRESHOLD
        and proc_n_trades >= N_MIN
        and proc_sharpe > buy_hold["sharpe"]
    )
    weak = bool((not actionable) and proc_total_return > 0.0 and proc_n_trades >= 5)
    if actionable:
        decision = "actionable"
        explanation = (
            "Edge statistiquement valide sur l'ensemble des fenetres test walk-forward "
            "(p-value bootstrap <= seuil, borne inferieure de Wilson >= seuil, "
            "nombre de trades suffisant, Sharpe superieur au buy-and-hold)."
        )
    elif weak:
        decision = "weak"
        explanation = (
            "Rendement positif sur l'echantillon test mais les criteres statistiques "
            "complets (p-value, Wilson, Sharpe vs buy-and-hold) ne sont pas tous satisfaits."
        )
    else:
        decision = "no_edge"
        explanation = "Aucun edge net demontre apres couts sur les fenetres test walk-forward."

    return {
        "version": SR_WFO_VERSION,
        "status": "ok",
        "windows": window_records,
        "procedure_oos": procedure_oos,
        "baselines": {
            "buy_hold": buy_hold,
            "in_sample_best": in_sample_best,
        },
        "stability": stability,
        "live_recommendation": live_recommendation,
        "decision": decision,
        "explanation": explanation,
        "params_echo": params_echo,
    }


# ---------------------------------------------------------------------------
# touch/bounce diagnostics per line option
# ---------------------------------------------------------------------------


def line_touch_stats(
    *,
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    level_series: np.ndarray,
    side: str,
    forward_bars: int,
) -> dict[str, Any]:
    n = int(len(close))
    forward = max(1, int(forward_bars))
    n_touches = 0
    n_bounces = 0
    for t in range(1, n - 1):
        level = _finite(level_series[t])
        if level is None:
            continue
        prev_close = float(close[t - 1])
        forward_idx = min(t + forward, n - 1)
        if side == "support":
            touched = float(low[t]) <= level and prev_close > level
            if not touched:
                continue
            n_touches += 1
            if float(close[forward_idx]) > level:
                n_bounces += 1
        else:
            touched = float(high[t]) >= level and prev_close < level
            if not touched:
                continue
            n_touches += 1
            if float(close[forward_idx]) < level:
                n_bounces += 1
    bounce_rate = float(n_bounces / n_touches) if n_touches > 0 else 0.0
    lower, upper = wilson_ci(n_bounces, n_touches) if n_touches > 0 else (0.0, 1.0)
    return {
        "n_touches": int(n_touches),
        "n_bounces": int(n_bounces),
        "bounce_rate": float(bounce_rate),
        "wilson_ci_lower": float(lower),
        "wilson_ci_upper": float(upper),
    }
