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
from .oos_eval import compute_signal_array


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
    cost_bps: float = 33.0,
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
    indicator = _compute_indicator(close, variant, volume=volume)
    sig = compute_signal_array(close, variant, volume=volume)

    # --- trades across all OOS windows ---
    trades = _extract_trades(sig, close, dates, oos_windows, cost_bps)

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
        window_trades = [t for t in trades if t.get("oos_window") == w.window_index]
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

def _extract_trades(
    sig: np.ndarray,
    close: np.ndarray,
    dates: pd.DatetimeIndex,
    oos_windows: list[OOSWindowResult],
    cost_bps: float,
) -> list[dict[str, Any]]:
    """Extract round-trip trades from signal transitions across OOS windows."""
    cost_factor = cost_bps / 10_000.0
    trades: list[dict[str, Any]] = []

    for w in oos_windows:
        if not w.is_valid:
            continue
        ts = w.test_start
        te = w.test_end

        sig_oos = sig[ts:te]
        close_oos = close[ts:te]
        dates_oos = dates[ts:te]

        # Find signal transitions (entries)
        prev_sig = 0.0
        entry_idx: int | None = None
        entry_side: float = 0.0

        for i in range(len(sig_oos)):
            cur = sig_oos[i]
            if cur != prev_sig:
                # Close previous trade if one was open
                if entry_idx is not None and entry_side != 0.0:
                    _close_trade(
                        trades, entry_idx, i, entry_side,
                        close_oos, dates_oos, w.window_index,
                        cost_factor,
                    )
                    entry_idx = None
                    entry_side = 0.0

                # Open new trade if signal is non-zero
                if cur != 0.0:
                    entry_idx = i
                    entry_side = cur

            prev_sig = cur

        # Close any open trade at end of window
        if entry_idx is not None and entry_side != 0.0:
            _close_trade(
                trades, entry_idx, len(sig_oos) - 1, entry_side,
                close_oos, dates_oos, w.window_index,
                cost_factor,
            )

    return trades


def _close_trade(
    trades: list[dict],
    entry_i: int,
    exit_i: int,
    side: float,
    close_oos: np.ndarray,
    dates_oos: pd.DatetimeIndex,
    window_index: int,
    cost_factor: float,
) -> None:
    entry_price = float(close_oos[entry_i])
    exit_price = float(close_oos[exit_i])
    bars_held = exit_i - entry_i

    if side > 0:  # long
        raw_return = (exit_price / entry_price - 1.0) if entry_price > 0 else 0.0
        pnl = exit_price - entry_price
    else:  # short
        raw_return = (entry_price / exit_price - 1.0) if exit_price > 0 else 0.0
        pnl = entry_price - exit_price

    cost = cost_factor * 2 * entry_price  # entry + exit cost
    pnl_net = pnl - cost
    return_net = raw_return - cost_factor * 2

    entry_date = str(dates_oos[entry_i])[:10] if entry_i < len(dates_oos) else ""
    exit_date = str(dates_oos[exit_i])[:10] if exit_i < len(dates_oos) else ""

    trades.append({
        "entry_time": entry_date,
        "exit_time": exit_date,
        "side": "BUY" if side > 0 else "SELL",
        "entry_price": round(entry_price, 4),
        "exit_price": round(exit_price, 4),
        "bars_held": bars_held,
        "pnl": round(pnl_net, 4),
        "return_pct": round(return_net * 100, 4),
        "oos_window": window_index,
    })


# ---------------------------------------------------------------------------
# Trade performance summary
# ---------------------------------------------------------------------------

def _trade_performance_summary(trades: list[dict]) -> list[dict[str, Any]]:
    """Compute summary statistics from trade ledger."""
    if not trades:
        return []

    n = len(trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    n_wins = len(wins)
    n_losses = len(losses)

    win_rate = n_wins / n if n > 0 else 0.0
    avg_win = sum(t["return_pct"] for t in wins) / n_wins if n_wins > 0 else 0.0
    avg_loss = sum(t["return_pct"] for t in losses) / n_losses if n_losses > 0 else 0.0
    avg_bars = sum(t["bars_held"] for t in trades) / n if n > 0 else 0.0
    total_pnl = sum(t["pnl"] for t in trades)

    gross_wins = sum(t["pnl"] for t in wins)
    gross_losses = abs(sum(t["pnl"] for t in losses))
    profit_factor = gross_wins / gross_losses if gross_losses > 0 else float("inf") if gross_wins > 0 else 0.0

    # Max consecutive wins/losses
    max_consec_w = _max_consecutive(trades, win=True)
    max_consec_l = _max_consecutive(trades, win=False)

    return [
        {"metric": "total_trades", "value": n},
        {"metric": "win_rate", "value": round(win_rate * 100, 1)},
        {"metric": "avg_win_return", "value": round(avg_win, 2)},
        {"metric": "avg_loss_return", "value": round(avg_loss, 2)},
        {"metric": "profit_factor", "value": round(profit_factor, 2) if profit_factor != float("inf") else 999.99},
        {"metric": "avg_bars_held", "value": round(avg_bars, 1)},
        {"metric": "total_pnl", "value": round(total_pnl, 2)},
        {"metric": "max_consecutive_wins", "value": max_consec_w},
        {"metric": "max_consecutive_losses", "value": max_consec_l},
    ]


def _max_consecutive(trades: list[dict], *, win: bool) -> int:
    max_c = 0
    cur = 0
    for t in trades:
        if (t["pnl"] > 0) == win:
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
