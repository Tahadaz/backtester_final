"""Generate per-variant OOS plots and trade ledger.

Pure function — no DB/API dependencies.  Takes signal engine data +
OHLCV DataFrame and produces Plotly JSON figures + trade records.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from core.quant_core.optimize import sma_cumsum, rsi_wilder, ema, macd_pack, obv_array

from .domain import OOSWindowResult, VariantDef
from .oos_eval import apply_cooldown, compute_signal_array


# ---------------------------------------------------------------------------
# Indicator computation dispatch
# ---------------------------------------------------------------------------

def _compute_indicator(
    close: np.ndarray, variant: VariantDef, *, volume: np.ndarray | None = None,
) -> dict[str, Any]:
    """Return indicator data dict for plotting.

    Keys vary by type:
    - overlay: {"type": "overlay", "name": str, "values": np.ndarray}
    - subplot: {"type": "subplot", "name": str, ...indicator-specific keys}
    """
    p = variant.params
    arch = variant.archetype

    if arch == "price_vs_sma":
        w = int(p["window"])
        return {"type": "overlay", "name": f"SMA-{w}", "values": sma_cumsum(close, w)}

    if arch == "sma_cross":
        fast_arr = sma_cumsum(close, int(p["fast"]))
        slow_arr = sma_cumsum(close, int(p["slow"]))
        return {"type": "overlay_dual", "name": f"SMA({p['fast']},{p['slow']})",
                "fast": fast_arr, "slow": slow_arr,
                "fast_label": f"SMA-{p['fast']}", "slow_label": f"SMA-{p['slow']}"}

    if arch == "slope_confirmed":
        w = int(p["window"])
        return {"type": "overlay", "name": f"SMA-{w}", "values": sma_cumsum(close, w)}

    if arch == "rsi_level":
        period = int(p["period"])
        rsi_vals = rsi_wilder(close, period)
        return {"type": "secondary_yaxis", "name": f"RSI({period})",
                "values": rsi_vals,
                "thresholds": [float(p["oversold"]), float(p["overbought"])],
                "y_range": [0, 100]}

    if arch == "macd_cross":
        fast, slow, sig = int(p["fast"]), int(p["slow"]), int(p["signal"])
        macd_line, sig_line, hist = macd_pack(close, fast, slow, sig)
        return {"type": "secondary_yaxis", "name": f"MACD({fast},{slow},{sig})",
                "macd_line": macd_line, "signal_line": sig_line, "histogram": hist}

    if arch == "obv_trend":
        ema_period = int(p["ema_period"])
        vol = volume if volume is not None else np.zeros(len(close))
        obv_vals = obv_array(close, vol)
        obv_ema_vals = ema(obv_vals, ema_period)
        return {"type": "secondary_yaxis", "name": f"OBV-EMA({ema_period})",
                "obv": obv_vals, "ema_values": obv_ema_vals}

    # Fallback: no indicator plot
    return {"type": "none"}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def compute_variant_detail(
    ohlcv: pd.DataFrame,
    close: np.ndarray,
    variant: VariantDef,
    oos_windows: list[OOSWindowResult],
    *,
    volume: np.ndarray | None = None,
    cost_bps: float = 10.0,
    cooldown_bars: int = 0,
) -> dict[str, Any]:
    """Return plots + trade ledger + trade performance for a variant.

    Parameters
    ----------
    ohlcv : DataFrame with DatetimeIndex and columns Open/High/Low/Close/Volume
    close : np.ndarray aligned with ohlcv (same length/order)
    variant : the VariantDef being inspected
    oos_windows : OOSWindowResult list from the ensemble pipeline
    volume : np.ndarray of volume data (needed for OBV family)
    cost_bps : transaction cost in basis points

    Returns
    -------
    dict with keys: plots, trade_ledger, trade_performance, metrics
    """
    dates = ohlcv.index
    open_prices = ohlcv["Open"].to_numpy()
    indicator = _compute_indicator(close, variant, volume=volume)
    sig = apply_cooldown(compute_signal_array(close, variant, volume=volume), cooldown_bars)

    # --- trades across all OOS windows ---
    trades, window_cash_starts = _extract_trade_register(
        sig, close, open_prices, dates, oos_windows, cost_bps,
    )

    # --- plots ---
    plots: dict[str, Any] = {}
    plots["price_indicator_signal"] = _plot_price_indicator_signal(
        close, sig, dates, oos_windows, indicator, variant,
    )

    eq_plot, dd_plot = _plot_oos_equity_and_drawdown(
        sig, close, dates, oos_windows, cost_bps,
    )
    if eq_plot is not None:
        plots["oos_equity"] = eq_plot
    if dd_plot is not None:
        plots["drawdown"] = dd_plot

    # --- trade performance summary ---
    perf = _trade_performance_summary(trades)

    # --- aggregate metrics (same as stub but kept for compat) ---
    metrics: dict[str, Any] = {}
    if oos_windows:
        valid = [w for w in oos_windows if w.is_valid]
        if valid:
            import statistics
            metrics["mean_sharpe"] = round(statistics.mean(w.sharpe for w in valid), 4)
            metrics["mean_max_drawdown"] = round(statistics.mean(w.max_drawdown for w in valid), 4)
            metrics["fraction_positive_windows"] = round(
                sum(1 for w in valid if w.sharpe > 0) / len(valid), 4,
            )
            metrics["cagr"] = round(statistics.mean(w.cagr for w in valid), 4)
            metrics["total_pnl"] = round(statistics.mean(w.pnl for w in valid), 2)
            metrics["n_oos_windows"] = len(oos_windows)
            metrics["n_valid_windows"] = len(valid)
            metrics["total_trades"] = sum(w.n_trades for w in valid)

    # --- per-window detail ---
    cost_factor = cost_bps / 10_000.0
    per_window: list[dict[str, Any]] = []
    for w in oos_windows:
        if not w.is_valid:
            continue
        window_start_cash = float(window_cash_starts.get(w.window_index, 0.0))
        window_trades = [
            _rebase_trade_tresorerie(t, window_start_cash)
            for t in trades
            if t.get("oos_window") == w.window_index
        ]
        end_idx = min(w.test_end, len(dates) - 1)
        eq_plot_w, dd_plot_w = _plot_single_window_equity_dd(sig, close, dates, w, cost_factor)
        per_window.append({
            "window_index": w.window_index,
            "start_date": str(dates[w.test_start])[:10],
            "end_date": str(dates[end_idx])[:10],
            "sharpe": round(w.sharpe, 4),
            "pnl": round(w.pnl, 2),
            "n_trades": w.n_trades,
            "is_valid": w.is_valid,
            "plot": _plot_single_window(close, sig, dates, w, indicator, variant),
            "equity_plot": eq_plot_w,
            "drawdown_plot": dd_plot_w,
            "trades": window_trades,
        })

    return {
        "plots": plots,
        "trade_ledger": trades,
        "trade_performance": perf,
        "metrics": metrics,
        "per_window": per_window,
    }


# ---------------------------------------------------------------------------
# Trade extraction
# ---------------------------------------------------------------------------

def _extract_trade_register(
    sig: np.ndarray,
    close: np.ndarray,
    open_prices: np.ndarray,
    dates: pd.DatetimeIndex,
    oos_windows: list[OOSWindowResult],
    cost_bps: float,
) -> tuple[list[dict[str, Any]], dict[int, float]]:
    """Extract per-fill trade register with realized/latent PnL.

    Signal fires at close of bar i → execution at open of bar i+1.
    One row per signal change (per-fill), not round-trip.
    """
    cost_factor = cost_bps / 10_000.0
    trades: list[dict[str, Any]] = []
    window_cash_starts: dict[int, float] = {}
    tresorerie = 0.0

    for w in oos_windows:
        if not w.is_valid:
            continue
        ts, te = w.test_start, w.test_end
        sig_oos = sig[ts:te]
        close_oos = close[ts:te]
        open_oos = open_prices[ts:te]
        dates_oos = dates[ts:te]

        position = 0.0
        cmp = 0.0  # cost mean price (internal, for PnL calc)
        window_cash_starts[w.window_index] = tresorerie

        for i in range(len(sig_oos)):
            cur_sig = sig_oos[i]
            if cur_sig == position:
                continue  # no signal change

            # Signal fires at bar i → execute at bar i+1
            exec_idx = i + 1
            if exec_idx >= len(open_oos):
                break  # can't execute, no next bar

            prev_pos = position
            new_pos = cur_sig
            exec_price = float(open_oos[exec_idx])
            close_du_jour = float(close_oos[exec_idx])
            date_str = str(dates_oos[exec_idx])[:10]
            pos_change = abs(new_pos - prev_pos)
            cost = cost_factor * pos_change * exec_price

            pnl_realise = 0.0

            if prev_pos == 0:
                # Opening: capitalize cost into CMP
                cmp = _cmp_after_open(exec_price, cost, new_pos)
            elif new_pos == 0:
                # Closing position
                if prev_pos > 0:
                    pnl_realise = exec_price - cmp - cost
                else:
                    pnl_realise = cmp - exec_price - cost
                cmp = 0.0
            else:
                # Flip (+1→-1 or -1→+1): close old, open new
                close_cost = cost_factor * abs(prev_pos) * exec_price
                open_cost = cost_factor * abs(new_pos) * exec_price
                if prev_pos > 0:
                    pnl_realise = exec_price - cmp - close_cost
                else:
                    pnl_realise = cmp - exec_price - close_cost
                cmp = _cmp_after_open(exec_price, open_cost, new_pos)

            position = new_pos
            tresorerie += _cash_delta(exec_price, cost_factor, prev_pos, new_pos)

            # Latent PnL on current position (mark-to-market vs close du jour)
            pnl_latent = 0.0
            if position > 0:
                pnl_latent = close_du_jour - cmp
            elif position < 0:
                pnl_latent = cmp - close_du_jour

            side = "ACHAT" if new_pos > prev_pos else "VENTE"

            trades.append({
                "date": date_str,
                "side": side,
                "prix_execution": round(exec_price, 4),
                "close_du_jour": round(close_du_jour, 4),
                "position": round(position, 1),
                "tresorerie": round(tresorerie, 4),
                "pnl_realise": round(pnl_realise, 4),
                "pnl_latent": round(pnl_latent, 4),
                "cout": round(cost, 4),
                "oos_window": w.window_index,
            })

        # Force-close any open position at end of window
        if position != 0:
            px = float(close_oos[-1])
            date_str = str(dates_oos[-1])[:10]
            cost = cost_factor * abs(position) * px
            if position > 0:
                pnl_realise = px - cmp - cost
            else:
                pnl_realise = cmp - px - cost
            tresorerie += _cash_delta(px, cost_factor, position, 0.0)
            trades.append({
                "date": date_str,
                "side": "VENTE" if position > 0 else "ACHAT",
                "prix_execution": round(px, 4),
                "close_du_jour": round(px, 4),
                "position": 0.0,
                "tresorerie": round(tresorerie, 4),
                "pnl_realise": round(pnl_realise, 4),
                "pnl_latent": 0.0,
                "cout": round(cost, 4),
                "oos_window": w.window_index,
            })
            position = 0.0
            cmp = 0.0

    return trades, window_cash_starts


def _cmp_after_open(exec_price: float, cost: float, position: float) -> float:
    """Return cost-adjusted carry price for a newly opened position."""
    if position > 0:
        return exec_price + cost
    if position < 0:
        return exec_price - cost
    return 0.0


def _rebase_trade_tresorerie(trade: dict[str, Any], start_cash: float) -> dict[str, Any]:
    """Return a copy of a trade row rebased to the window's starting cash."""
    rebased = dict(trade)
    tresorerie = rebased.get("tresorerie")
    if isinstance(tresorerie, (int, float)):
        rebased["tresorerie"] = round(float(tresorerie) - start_cash, 4)
    return rebased


def _cash_delta(exec_price: float, cost_factor: float, prev_pos: float, new_pos: float) -> float:
    """Return cumulative cash impact for a unit-position transition."""
    cash_delta = 0.0

    if prev_pos > 0:
        cash_delta += exec_price - (cost_factor * exec_price)
    elif prev_pos < 0:
        cash_delta -= exec_price + (cost_factor * exec_price)

    if new_pos > 0:
        cash_delta -= exec_price + (cost_factor * exec_price)
    elif new_pos < 0:
        cash_delta += exec_price - (cost_factor * exec_price)

    return cash_delta


# ---------------------------------------------------------------------------
# Trade performance summary
# ---------------------------------------------------------------------------

def _trade_performance_summary(trades: list[dict]) -> list[dict[str, Any]]:
    """Compute summary statistics from per-fill trade register."""
    if not trades:
        return []

    # Only count fills that realize PnL (closes and flips, not opens)
    closing_fills = [t for t in trades if t["pnl_realise"] != 0]
    n = len(closing_fills)

    wins = [t for t in closing_fills if t["pnl_realise"] > 0]
    losses = [t for t in closing_fills if t["pnl_realise"] <= 0]
    n_wins = len(wins)
    n_losses = len(losses)

    win_rate = n_wins / n if n > 0 else 0.0
    avg_win_pnl = sum(t["pnl_realise"] for t in wins) / n_wins if n_wins > 0 else 0.0
    avg_loss_pnl = sum(t["pnl_realise"] for t in losses) / n_losses if n_losses > 0 else 0.0
    total_pnl = sum(t["pnl_realise"] for t in closing_fills)
    total_cost = sum(t["cout"] for t in trades)

    gross_wins = sum(t["pnl_realise"] for t in wins)
    gross_losses = abs(sum(t["pnl_realise"] for t in losses))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else float("inf") if gross_wins > 0 else 0.0

    max_consec_w = _max_consecutive(closing_fills, win=True)
    max_consec_l = _max_consecutive(closing_fills, win=False)

    return [
        {"metric": "total_fills", "value": len(trades)},
        {"metric": "closing_fills", "value": n},
        {"metric": "win_rate", "value": round(win_rate * 100, 1)},
        {"metric": "avg_win_pnl", "value": round(avg_win_pnl, 2)},
        {"metric": "avg_loss_pnl", "value": round(avg_loss_pnl, 2)},
        {"metric": "profit_factor", "value": round(profit_factor, 2) if profit_factor != float("inf") else 999.99},
        {"metric": "total_pnl_realise", "value": round(total_pnl, 2)},
        {"metric": "total_cost", "value": round(total_cost, 2)},
        {"metric": "max_consecutive_wins", "value": max_consec_w},
        {"metric": "max_consecutive_losses", "value": max_consec_l},
    ]


def _max_consecutive(trades: list[dict], *, win: bool) -> int:
    max_c = 0
    cur = 0
    for t in trades:
        if (t["pnl_realise"] > 0) == win:
            cur += 1
            max_c = max(max_c, cur)
        else:
            cur = 0
    return max_c


# ---------------------------------------------------------------------------
# Plot builders (return Plotly-compatible dicts)
# ---------------------------------------------------------------------------

def _to_iso(dates: pd.DatetimeIndex) -> list[str]:
    """Convert DatetimeIndex to list of ISO date strings."""
    return [str(d)[:10] for d in dates]


def _add_buy_sell_markers(
    data: list[dict], sig: np.ndarray, close: np.ndarray, date_strs: list[str],
) -> None:
    """Append BUY/SELL marker traces to data list."""
    buy_x, buy_y = [], []
    sell_x, sell_y = [], []
    for i in range(1, len(sig)):
        if sig[i] == 1.0 and sig[i - 1] <= 0.0:
            buy_x.append(date_strs[i])
            buy_y.append(float(close[i]))
        elif sig[i] == -1.0 and sig[i - 1] >= 0.0:
            sell_x.append(date_strs[i])
            sell_y.append(float(close[i]))

    if buy_x:
        data.append({
            "type": "scatter",
            "x": buy_x, "y": buy_y,
            "mode": "markers", "name": "BUY",
            "marker": {"symbol": "triangle-up", "size": 8, "color": "#10b981",
                        "line": {"width": 1, "color": "#065f46"}},
        })
    if sell_x:
        data.append({
            "type": "scatter",
            "x": sell_x, "y": sell_y,
            "mode": "markers", "name": "SELL",
            "marker": {"symbol": "triangle-down", "size": 8, "color": "#ef4444",
                        "line": {"width": 1, "color": "#991b1b"}},
        })


def _plot_single_window(
    close: np.ndarray,
    sig: np.ndarray,
    dates: pd.DatetimeIndex,
    w: OOSWindowResult,
    indicator: dict[str, Any],
    variant: VariantDef,
) -> dict[str, Any]:
    """Generate a price+indicator+trades plot for a single OOS window."""
    ts = w.test_start
    te = min(w.test_end, len(dates) - 1)

    close_slice = close[ts:te + 1]
    sig_slice = sig[ts:te + 1]
    dates_slice = dates[ts:te + 1]
    date_strs = _to_iso(dates_slice)

    data: list[dict] = [
        {
            "type": "scatter",
            "x": date_strs,
            "y": [float(v) for v in close_slice],
            "mode": "lines",
            "name": "Close",
            "line": {"color": "#3b82f6", "width": 1.5},
        },
    ]

    # Add overlay indicator if applicable
    ind_type = indicator.get("type", "none")
    if ind_type == "overlay":
        vals = indicator["values"][ts:te + 1]
        data.append({
            "type": "scatter",
            "x": date_strs,
            "y": [float(v) if not np.isnan(v) else None for v in vals],
            "mode": "lines",
            "name": indicator["name"],
            "line": {"color": "#f97316", "width": 1.5, "dash": "dash"},
        })
    elif ind_type == "overlay_dual":
        for key, label, color in [("fast", indicator["fast_label"], "#f97316"), ("slow", indicator["slow_label"], "#8b5cf6")]:
            vals = indicator[key][ts:te + 1]
            data.append({
                "type": "scatter",
                "x": date_strs,
                "y": [float(v) if not np.isnan(v) else None for v in vals],
                "mode": "lines",
                "name": label,
                "line": {"color": color, "width": 1.5, "dash": "dash"},
            })
    elif ind_type == "secondary_yaxis":
        arch = variant.archetype
        if arch == "rsi_level":
            vals = indicator["values"][ts:te + 1]
            data.append({
                "type": "scatter", "x": date_strs,
                "y": [float(v) if not np.isnan(v) else None for v in vals],
                "mode": "lines", "name": indicator["name"],
                "line": {"color": "#8b5cf6", "width": 1.5},
                "yaxis": "y2",
            })
        elif arch == "macd_cross":
            for key, name, color, dash in [
                ("macd_line", "MACD", "#8b5cf6", None),
                ("signal_line", "Signal", "#f97316", "dash"),
            ]:
                vals = indicator[key][ts:te + 1]
                line_cfg: dict = {"color": color, "width": 1.5}
                if dash:
                    line_cfg["dash"] = dash
                data.append({
                    "type": "scatter", "x": date_strs,
                    "y": [float(v) if not np.isnan(v) else None for v in vals],
                    "mode": "lines", "name": name,
                    "line": line_cfg, "yaxis": "y2",
                })
        elif arch == "obv_trend":
            for key, name, color, dash in [
                ("obv", "OBV", "#8b5cf6", None),
                ("ema_values", indicator["name"], "#f97316", "dash"),
            ]:
                vals = indicator[key][ts:te + 1]
                line_cfg_o: dict = {"color": color, "width": 1.5}
                if dash:
                    line_cfg_o["dash"] = dash
                data.append({
                    "type": "scatter", "x": date_strs,
                    "y": [float(v) if not np.isnan(v) else None for v in vals],
                    "mode": "lines", "name": name,
                    "line": line_cfg_o, "yaxis": "y2",
                })

    _add_buy_sell_markers(data, sig_slice, close_slice, date_strs)

    start_label = date_strs[0] if date_strs else ""
    end_label = date_strs[-1] if date_strs else ""
    title = f"Fenetre OOS #{w.window_index} — {start_label} to {end_label}"

    layout: dict[str, Any] = {
        "title": {"text": title, "font": {"size": 13}},
        "xaxis": {"title": "Date", "type": "date"},
        "yaxis": {"title": "Prix"},
        "showlegend": True,
        "legend": {"orientation": "h", "y": -0.15},
        "margin": {"l": 50, "r": 20, "t": 40, "b": 40},
        "hovermode": "x unified",
    }

    if ind_type == "secondary_yaxis":
        y2_title = indicator.get("name", "Indicator")
        y2_config: dict[str, Any] = {"title": y2_title, "overlaying": "y", "side": "right", "showgrid": False}
        if variant.archetype == "rsi_level":
            y2_config["range"] = [0, 100]
            for t in indicator.get("thresholds", [30, 70]):
                layout.setdefault("shapes", []).append({
                    "type": "line", "xref": "paper", "yref": "y2",
                    "x0": 0, "x1": 1, "y0": t, "y1": t,
                    "line": {"color": "#ef4444" if t > 50 else "#10b981", "width": 1, "dash": "dot"},
                })
        layout["yaxis2"] = y2_config
        layout["margin"]["r"] = 60

    return {"data": data, "layout": layout}


def _plot_price_indicator_signal(
    close: np.ndarray,
    sig: np.ndarray,
    dates: pd.DatetimeIndex,
    oos_windows: list[OOSWindowResult],
    indicator: dict[str, Any],
    variant: VariantDef,
) -> dict[str, Any]:
    """Price + indicator overlay + OOS window shading + BUY/SELL markers."""
    date_strs = _to_iso(dates)

    data: list[dict] = [
        {
            "type": "scatter",
            "x": date_strs,
            "y": [float(v) for v in close],
            "mode": "lines",
            "name": "Close",
            "line": {"color": "#3b82f6", "width": 1.5},
        },
    ]

    # Add overlay indicator traces
    ind_type = indicator.get("type", "none")
    if ind_type == "overlay":
        data.append({
            "type": "scatter",
            "x": date_strs,
            "y": [float(v) if not np.isnan(v) else None for v in indicator["values"]],
            "mode": "lines",
            "name": indicator["name"],
            "line": {"color": "#f97316", "width": 1.5, "dash": "dash"},
        })
    elif ind_type == "overlay_dual":
        for key, label, color in [("fast", indicator["fast_label"], "#f97316"), ("slow", indicator["slow_label"], "#8b5cf6")]:
            data.append({
                "type": "scatter",
                "x": date_strs,
                "y": [float(v) if not np.isnan(v) else None for v in indicator[key]],
                "mode": "lines",
                "name": label,
                "line": {"color": color, "width": 1.5, "dash": "dash"},
            })
    elif ind_type == "secondary_yaxis":
        arch = variant.archetype
        if arch == "rsi_level":
            data.append({
                "type": "scatter", "x": date_strs,
                "y": [float(v) if not np.isnan(v) else None for v in indicator["values"]],
                "mode": "lines", "name": indicator["name"],
                "line": {"color": "#8b5cf6", "width": 1.5},
                "yaxis": "y2",
            })
        elif arch == "macd_cross":
            data.append({
                "type": "scatter", "x": date_strs,
                "y": [float(v) if not np.isnan(v) else None for v in indicator["macd_line"]],
                "mode": "lines", "name": "MACD",
                "line": {"color": "#8b5cf6", "width": 1.5},
                "yaxis": "y2",
            })
            data.append({
                "type": "scatter", "x": date_strs,
                "y": [float(v) if not np.isnan(v) else None for v in indicator["signal_line"]],
                "mode": "lines", "name": "Signal",
                "line": {"color": "#f97316", "width": 1.5, "dash": "dash"},
                "yaxis": "y2",
            })
        elif arch == "obv_trend":
            data.append({
                "type": "scatter", "x": date_strs,
                "y": [float(v) if not np.isnan(v) else None for v in indicator["obv"]],
                "mode": "lines", "name": "OBV",
                "line": {"color": "#8b5cf6", "width": 1.5},
                "yaxis": "y2",
            })
            data.append({
                "type": "scatter", "x": date_strs,
                "y": [float(v) if not np.isnan(v) else None for v in indicator["ema_values"]],
                "mode": "lines", "name": indicator["name"],
                "line": {"color": "#f97316", "width": 1.5, "dash": "dash"},
                "yaxis": "y2",
            })

    _add_buy_sell_markers(data, sig, close, date_strs)

    # OOS window shading via shapes
    shapes: list[dict] = []
    for w in oos_windows:
        if w.test_start >= len(dates) or w.test_end >= len(dates):
            continue
        x0 = date_strs[w.test_start]
        x1 = date_strs[min(w.test_end, len(dates) - 1)]
        color = "rgba(16,185,129,0.08)" if w.sharpe > 0 else "rgba(239,68,68,0.08)"
        shapes.append({
            "type": "rect",
            "xref": "x",
            "yref": "paper",
            "x0": x0,
            "x1": x1,
            "y0": 0,
            "y1": 1,
            "fillcolor": color,
            "line": {"width": 0},
            "layer": "below",
        })

    # Add RSI threshold shapes on secondary axis
    if ind_type == "secondary_yaxis" and variant.archetype == "rsi_level":
        for t in indicator.get("thresholds", [30, 70]):
            shapes.append({
                "type": "line", "xref": "paper", "yref": "y2",
                "x0": 0, "x1": 1, "y0": t, "y1": t,
                "line": {"color": "#ef4444" if t > 50 else "#10b981", "width": 1, "dash": "dot"},
            })

    layout: dict[str, Any] = {
        "title": {"text": f"{variant.description} — Prix + Signal", "font": {"size": 14}},
        "xaxis": {"title": "Date", "type": "date"},
        "yaxis": {"title": "Prix"},
        "shapes": shapes,
        "showlegend": True,
        "legend": {"orientation": "h", "y": -0.15},
        "margin": {"l": 50, "r": 20, "t": 40, "b": 40},
        "hovermode": "x unified",
    }

    if ind_type == "secondary_yaxis":
        y2_title = indicator.get("name", "Indicator")
        y2_config: dict[str, Any] = {"title": y2_title, "overlaying": "y", "side": "right", "showgrid": False}
        if variant.archetype == "rsi_level":
            y2_config["range"] = [0, 100]
        layout["yaxis2"] = y2_config
        layout["margin"]["r"] = 60

    return {"data": data, "layout": layout}


def _plot_indicator_subplot(
    dates: pd.DatetimeIndex,
    indicator: dict[str, Any],
    variant: VariantDef,
) -> dict[str, Any] | None:
    """Build a subplot for RSI, MACD, or OBV indicators."""
    date_strs = _to_iso(dates)
    arch = variant.archetype
    data: list[dict] = []

    if arch == "rsi_level":
        rsi_vals = indicator["values"]
        thresholds = indicator.get("thresholds", [30, 70])
        data.append({
            "type": "scatter",
            "x": date_strs,
            "y": [float(v) if not np.isnan(v) else None for v in rsi_vals],
            "mode": "lines",
            "name": indicator["name"],
            "line": {"color": "#8b5cf6", "width": 1.5},
        })
        # Threshold lines as shapes
        shapes = [
            {"type": "line", "xref": "paper", "yref": "y",
             "x0": 0, "x1": 1, "y0": t, "y1": t,
             "line": {"color": "#ef4444" if t > 50 else "#10b981", "width": 1, "dash": "dot"}}
            for t in thresholds
        ]
        return {
            "data": data,
            "layout": {
                "title": {"text": indicator["name"], "font": {"size": 13}},
                "xaxis": {"title": "Date", "type": "date"},
                "yaxis": {"title": "RSI", "range": [0, 100]},
                "shapes": shapes,
                "margin": {"l": 50, "r": 20, "t": 40, "b": 40},
                "hovermode": "x unified",
            },
        }

    if arch == "macd_cross":
        macd_line = indicator["macd_line"]
        sig_line = indicator["signal_line"]
        hist = indicator["histogram"]
        data.append({
            "type": "scatter",
            "x": date_strs,
            "y": [float(v) if not np.isnan(v) else None for v in macd_line],
            "mode": "lines",
            "name": "MACD",
            "line": {"color": "#3b82f6", "width": 1.5},
        })
        data.append({
            "type": "scatter",
            "x": date_strs,
            "y": [float(v) if not np.isnan(v) else None for v in sig_line],
            "mode": "lines",
            "name": "Signal",
            "line": {"color": "#f97316", "width": 1.5, "dash": "dash"},
        })
        # Histogram bars
        colors = ["#10b981" if v >= 0 else "#ef4444" for v in hist]
        data.append({
            "type": "bar",
            "x": date_strs,
            "y": [float(v) if not np.isnan(v) else 0 for v in hist],
            "name": "Histogram",
            "marker": {"color": colors},
        })
        return {
            "data": data,
            "layout": {
                "title": {"text": indicator["name"], "font": {"size": 13}},
                "xaxis": {"title": "Date", "type": "date"},
                "yaxis": {"title": "MACD"},
                "margin": {"l": 50, "r": 20, "t": 40, "b": 40},
                "hovermode": "x unified",
                "barmode": "relative",
            },
        }

    if arch == "obv_trend":
        obv_vals = indicator["obv"]
        ema_vals = indicator["ema_values"]
        data.append({
            "type": "scatter",
            "x": date_strs,
            "y": [float(v) if not np.isnan(v) else None for v in obv_vals],
            "mode": "lines",
            "name": "OBV",
            "line": {"color": "#3b82f6", "width": 1.5},
        })
        data.append({
            "type": "scatter",
            "x": date_strs,
            "y": [float(v) if not np.isnan(v) else None for v in ema_vals],
            "mode": "lines",
            "name": indicator["name"],
            "line": {"color": "#f97316", "width": 1.5, "dash": "dash"},
        })
        return {
            "data": data,
            "layout": {
                "title": {"text": indicator["name"], "font": {"size": 13}},
                "xaxis": {"title": "Date", "type": "date"},
                "yaxis": {"title": "OBV"},
                "margin": {"l": 50, "r": 20, "t": 40, "b": 40},
                "hovermode": "x unified",
            },
        }

    return None


def _plot_oos_equity_and_drawdown(
    sig: np.ndarray,
    close: np.ndarray,
    dates: pd.DatetimeIndex,
    oos_windows: list[OOSWindowResult],
    cost_bps: float,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Stitched OOS equity curve + drawdown chart."""
    valid_windows = [w for w in oos_windows if w.is_valid]
    if not valid_windows:
        return None, None

    cost_factor = cost_bps / 10_000.0

    all_dates: list[str] = []
    all_equity: list[float] = []
    all_dd: list[float] = []
    cumulative = 1.0
    peak = 1.0

    for w in valid_windows:
        ts, te = w.test_start, w.test_end
        sig_oos = sig[ts:te]
        close_oos = close[ts:te + 1]
        dates_oos = dates[ts:te]

        price_ret = close_oos[1:] / close_oos[:-1] - 1.0
        sig_change = np.abs(np.diff(sig_oos, prepend=0.0))
        ret = sig_oos * price_ret - cost_factor * sig_change

        for i in range(len(ret)):
            cumulative *= (1.0 + ret[i])
            peak = max(peak, cumulative)
            dd = (peak - cumulative) / peak if peak > 0 else 0.0

            if i < len(dates_oos):
                all_dates.append(str(dates_oos[i])[:10])
            all_equity.append(round(cumulative, 6))
            all_dd.append(round(-dd, 6))  # negative for downward fill

    if not all_dates:
        return None, None

    eq_fig: dict[str, Any] = {
        "data": [{
            "type": "scatter",
            "x": all_dates,
            "y": all_equity,
            "mode": "lines",
            "name": "Equity OOS",
            "line": {"color": "#3b82f6", "width": 1.5},
            "fill": "tozeroy",
            "fillcolor": "rgba(59,130,246,0.08)",
        }],
        "layout": {
            "title": {"text": "Courbe Equity — Periodes OOS", "font": {"size": 14}},
            "xaxis": {"title": "Date", "type": "date"},
            "yaxis": {"title": "Equity (base 1.0)"},
            "shapes": [{
                "type": "line",
                "xref": "paper",
                "yref": "y",
                "x0": 0, "x1": 1,
                "y0": 1.0, "y1": 1.0,
                "line": {"color": "#94a3b8", "width": 1, "dash": "dot"},
            }],
            "margin": {"l": 50, "r": 20, "t": 40, "b": 40},
            "hovermode": "x unified",
        },
    }

    dd_fig: dict[str, Any] = {
        "data": [{
            "type": "scatter",
            "x": all_dates,
            "y": all_dd,
            "mode": "lines",
            "name": "Drawdown",
            "line": {"color": "#ef4444", "width": 1.5},
            "fill": "tozeroy",
            "fillcolor": "rgba(239,68,68,0.12)",
        }],
        "layout": {
            "title": {"text": "Drawdown — Periodes OOS", "font": {"size": 14}},
            "xaxis": {"title": "Date", "type": "date"},
            "yaxis": {"title": "Drawdown", "tickformat": ".1%"},
            "margin": {"l": 50, "r": 20, "t": 40, "b": 40},
            "hovermode": "x unified",
        },
    }

    return eq_fig, dd_fig


def _plot_single_window_equity_dd(
    sig: np.ndarray,
    close: np.ndarray,
    dates: pd.DatetimeIndex,
    w: OOSWindowResult,
    cost_factor: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Equity curve + drawdown for a single OOS window."""
    ts, te = w.test_start, w.test_end
    sig_oos = sig[ts:te]
    close_oos = close[ts:te + 1]
    dates_oos = dates[ts:te]

    price_ret = close_oos[1:] / close_oos[:-1] - 1.0
    sig_change = np.abs(np.diff(sig_oos, prepend=0.0))
    ret = sig_oos * price_ret - cost_factor * sig_change

    w_dates: list[str] = []
    w_equity: list[float] = []
    w_dd: list[float] = []
    cumulative = 1.0
    peak = 1.0

    for i in range(len(ret)):
        cumulative *= (1.0 + ret[i])
        peak = max(peak, cumulative)
        dd = (peak - cumulative) / peak if peak > 0 else 0.0
        if i < len(dates_oos):
            w_dates.append(str(dates_oos[i])[:10])
        w_equity.append(round(cumulative, 6))
        w_dd.append(round(-dd, 6))

    start_label = w_dates[0] if w_dates else ""
    end_label = w_dates[-1] if w_dates else ""

    eq_fig: dict[str, Any] = {
        "data": [{
            "type": "scatter",
            "x": w_dates,
            "y": w_equity,
            "mode": "lines",
            "name": "Equity",
            "line": {"color": "#3b82f6", "width": 1.5},
            "fill": "tozeroy",
            "fillcolor": "rgba(59,130,246,0.08)",
        }],
        "layout": {
            "title": {"text": f"Equity — #{w.window_index + 1} ({start_label} to {end_label})", "font": {"size": 13}},
            "xaxis": {"title": "Date", "type": "date"},
            "yaxis": {"title": "Equity (base 1.0)"},
            "shapes": [{
                "type": "line", "xref": "paper", "yref": "y",
                "x0": 0, "x1": 1, "y0": 1.0, "y1": 1.0,
                "line": {"color": "#94a3b8", "width": 1, "dash": "dot"},
            }],
            "margin": {"l": 50, "r": 20, "t": 40, "b": 40},
            "hovermode": "x unified",
        },
    }

    dd_fig: dict[str, Any] = {
        "data": [{
            "type": "scatter",
            "x": w_dates,
            "y": w_dd,
            "mode": "lines",
            "name": "Drawdown",
            "line": {"color": "#ef4444", "width": 1.5},
            "fill": "tozeroy",
            "fillcolor": "rgba(239,68,68,0.12)",
        }],
        "layout": {
            "title": {"text": f"Drawdown — #{w.window_index + 1} ({start_label} to {end_label})", "font": {"size": 13}},
            "xaxis": {"title": "Date", "type": "date"},
            "yaxis": {"title": "Drawdown", "tickformat": ".1%"},
            "margin": {"l": 50, "r": 20, "t": 40, "b": 40},
            "hovermode": "x unified",
        },
    }

    return eq_fig, dd_fig
