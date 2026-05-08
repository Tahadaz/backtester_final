"""Generate per-variant OOS plots and trade ledger.

Pure function — no DB/API dependencies.  Takes signal engine data +
OHLCV DataFrame and produces Plotly JSON figures + trade records.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from core.quant_core.horizons import DEFAULT_COST_BPS_PER_SIDE
from core.quant_core.optimize import ema, obv_array

from .domain import OOSWindowResult, VariantDef
from .indicator_series import (
    compute_ad_series,
    compute_adx_series,
    compute_cci_series,
    compute_cmf_series,
    compute_ema_cross_series,
    compute_ema_series,
    compute_force_index_series,
    compute_ichimoku_series,
    compute_macd_pack_series,
    compute_mfi_series,
    compute_psar_series,
    compute_roc_series,
    compute_rsi_series,
    compute_sma_series,
    compute_stochastic_series,
    compute_trix_series,
    compute_tsi_series,
    compute_uo_series,
    compute_vwap_series,
)
from .oos_eval import apply_cooldown, compute_signal_array, signal_to_long_only_positions
from .rsi_semantics import (
    compute_rsi_variant_actions,
    compute_rsi_variant_positions,
    is_rsi_level_variant,
    rsi_window_marker_indices,
    transition_marker_indices,
)


# ---------------------------------------------------------------------------
# Indicator computation dispatch
# ---------------------------------------------------------------------------

def _compute_indicator(
    close: np.ndarray,
    variant: VariantDef,
    *,
    volume: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
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
        return {"type": "overlay", "name": f"SMA-{w}", "values": compute_sma_series(close, w)}

    if arch == "sma_cross":
        fast_arr = compute_sma_series(close, int(p["fast"]))
        slow_arr = compute_sma_series(close, int(p["slow"]))
        return {"type": "overlay_dual", "name": f"SMA({p['fast']},{p['slow']})",
                "fast": fast_arr, "slow": slow_arr,
                "fast_label": f"SMA-{p['fast']}", "slow_label": f"SMA-{p['slow']}"}

    if arch == "slope_confirmed":
        w = int(p["window"])
        return {"type": "overlay", "name": f"SMA-{w}", "values": compute_sma_series(close, w)}

    if arch == "price_vs_ema":
        w = int(p["window"])
        return {"type": "overlay", "name": f"EMA-{w}", "values": compute_ema_series(close, w)}

    if arch == "ema_cross":
        fast_arr, slow_arr = compute_ema_cross_series(close, int(p["fast"]), int(p["slow"]))
        return {
            "type": "overlay_dual",
            "name": f"EMA({p['fast']},{p['slow']})",
            "fast": fast_arr,
            "slow": slow_arr,
            "fast_label": f"EMA-{p['fast']}",
            "slow_label": f"EMA-{p['slow']}",
        }

    if arch == "ichi_cloud" and high is not None and low is not None:
        ichi = compute_ichimoku_series(high, low, close, int(p["tenkan"]), int(p["kijun"]), int(p["senkou_b"]))
        return {
            "type": "overlay_cloud",
            "name": f"Ichimoku({p['tenkan']},{p['kijun']},{p['senkou_b']})",
            **ichi,
        }

    if arch == "psar_trend" and high is not None and low is not None:
        sar = compute_psar_series(high, low, close, float(p["af_step"]), float(p["af_max"]))
        return {"type": "overlay_dots", "name": "Parabolic SAR", "values": sar}

    if arch == "rsi_level":
        period = int(p["period"])
        rsi_vals = compute_rsi_series(close, period)
        return {"type": "secondary_yaxis", "name": f"RSI({period})",
                "values": rsi_vals,
                "thresholds": [float(p["oversold"]), float(p["overbought"])],
                "y_range": [0, 100]}

    if arch == "macd_cross":
        fast, slow, sig = int(p["fast"]), int(p["slow"]), int(p["signal"])
        macd_line, sig_line, hist = compute_macd_pack_series(close, fast, slow, sig)
        return {"type": "secondary_yaxis", "name": f"MACD({fast},{slow},{sig})",
                "macd_line": macd_line, "signal_line": sig_line, "histogram": hist}

    if arch == "roc_zero":
        vals = compute_roc_series(close, int(p["period"]))
        return {"type": "secondary_yaxis", "name": f"ROC({p['period']})", "values": vals, "zero_line": True}

    if arch == "trix_zero":
        vals = compute_trix_series(close, int(p["period"]))
        return {"type": "secondary_yaxis", "name": f"TRIX({p['period']})", "values": vals, "zero_line": True}

    if arch == "adx_trend" and high is not None and low is not None:
        plus_di, minus_di, adx = compute_adx_series(high, low, close, int(p["period"]))
        return {
            "type": "secondary_yaxis",
            "name": f"ADX({p['period']})",
            "plus_di": plus_di,
            "minus_di": minus_di,
            "adx": adx,
            "thresholds": [float(p["adx_threshold"])],
        }

    if arch == "tsi_zero":
        long_period = int(p.get("long_period", p["quarterly_period"]))
        short_period = int(p.get("short_period", p["weekly_period"]))
        vals = compute_tsi_series(close, long_period, short_period)
        return {"type": "secondary_yaxis", "name": f"TSI({long_period},{short_period})", "values": vals, "zero_line": True}

    if arch == "stoch_level" and high is not None and low is not None:
        k_vals, d_vals = compute_stochastic_series(high, low, close, int(p["k_period"]), int(p["d_period"]))
        return {
            "type": "secondary_yaxis",
            "name": f"Stochastic({p['k_period']},{p['d_period']})",
            "k": k_vals,
            "d": d_vals,
            "thresholds": [20.0, 80.0],
            "y_range": [0, 100],
        }

    if arch == "cci_level" and high is not None and low is not None:
        vals = compute_cci_series(high, low, close, int(p["period"]))
        return {"type": "secondary_yaxis", "name": f"CCI({p['period']})", "values": vals, "thresholds": [-100.0, 100.0]}

    if arch == "mfi_level" and volume is not None and high is not None and low is not None:
        vals = compute_mfi_series(high, low, close, volume, int(p["period"]))
        return {
            "type": "secondary_yaxis",
            "name": f"MFI({p['period']})",
            "values": vals,
            "thresholds": [float(p["oversold"]), float(p["overbought"])],
            "y_range": [0, 100],
        }

    if arch == "uo_level" and high is not None and low is not None:
        vals = compute_uo_series(high, low, close, int(p["period_1"]), int(p["period_2"]), int(p["period_3"]))
        return {"type": "secondary_yaxis", "name": f"UO({p['period_1']},{p['period_2']},{p['period_3']})", "values": vals, "thresholds": [30.0, 70.0], "y_range": [0, 100]}

    if arch == "obv_trend":
        ema_period = int(p["ema_period"])
        vol = volume if volume is not None else np.zeros(len(close))
        obv_vals = obv_array(close, vol)
        obv_ema_vals = compute_ema_series(obv_vals, ema_period)
        return {"type": "secondary_yaxis", "name": f"OBV-EMA({ema_period})",
                "obv": obv_vals, "ema_values": obv_ema_vals}

    if arch == "cmf_flow" and volume is not None and high is not None and low is not None:
        vals = compute_cmf_series(high, low, close, volume, int(p["period"]))
        return {"type": "secondary_yaxis", "name": f"CMF({p['period']})", "values": vals, "thresholds": [-0.05, 0.05], "zero_line": True}

    if arch == "ad_trend" and volume is not None and high is not None and low is not None:
        ad_vals = compute_ad_series(high, low, close, volume)
        ad_ema_vals = compute_ema_series(ad_vals, int(p["ema_period"]))
        return {"type": "secondary_yaxis", "name": f"AD-EMA({p['ema_period']})", "ad": ad_vals, "ema_values": ad_ema_vals}

    if arch == "vwap_dev" and volume is not None:
        vwap = compute_vwap_series(close, volume, int(p["period"]))
        threshold = float(p["threshold_pct"]) / 100.0
        return {
            "type": "overlay_band",
            "name": f"VWAP({p['period']})",
            "values": vwap,
            "upper": vwap * (1.0 + threshold),
            "lower": vwap * (1.0 - threshold),
        }

    if arch == "fi_trend" and volume is not None:
        vals = compute_force_index_series(close, volume, int(p["period"]))
        return {"type": "secondary_yaxis", "name": f"Force Index({p['period']})", "values": vals, "zero_line": True}

    # Fallback: no indicator plot
    return {"type": "none"}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def compute_variant_signal_array(
    close: np.ndarray,
    variant: VariantDef,
    *,
    volume: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    cooldown_bars: int = 0,
) -> np.ndarray:
    """Compute the signal array used by variant detail/backtests."""
    if is_rsi_level_variant(variant):
        return compute_rsi_variant_actions(close, variant, cooldown_bars=cooldown_bars)

    sig = compute_signal_array(close, variant, volume=volume, high=high, low=low)
    return apply_cooldown(sig, cooldown_bars)


def compute_variant_position_array(
    close: np.ndarray,
    variant: VariantDef,
    *,
    volume: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    cooldown_bars: int = 0,
) -> np.ndarray:
    """Compute the carried position array used by variant backtests."""
    if is_rsi_level_variant(variant):
        return compute_rsi_variant_positions(close, variant, cooldown_bars=cooldown_bars)

    raw_signal = compute_variant_signal_array(
        close,
        variant,
        volume=volume,
        high=high,
        low=low,
        cooldown_bars=cooldown_bars,
    )
    return signal_to_long_only_positions(raw_signal, variant)


def compute_variant_trade_register(
    ohlcv: pd.DataFrame,
    close: np.ndarray,
    variant: VariantDef,
    oos_windows: list[OOSWindowResult],
    *,
    volume: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    cost_bps: float = DEFAULT_COST_BPS_PER_SIDE,
    cooldown_bars: int = 0,
    force_valid_windows: bool = False,
) -> tuple[list[dict[str, Any]], dict[int, float]]:
    """Return the per-fill trade ledger for one variant without building plots."""
    position_sig = compute_variant_position_array(
        close,
        variant,
        volume=volume,
        high=high,
        low=low,
        cooldown_bars=cooldown_bars,
    )
    return _extract_trade_register(
        position_sig,
        close,
        ohlcv["Open"].to_numpy(),
        ohlcv.index,
        oos_windows,
        cost_bps,
        force_valid_windows=force_valid_windows,
    )


def compute_variant_detail(
    ohlcv: pd.DataFrame,
    close: np.ndarray,
    variant: VariantDef,
    oos_windows: list[OOSWindowResult],
    *,
    volume: np.ndarray | None = None,
    high: np.ndarray | None = None,
    low: np.ndarray | None = None,
    cost_bps: float = DEFAULT_COST_BPS_PER_SIDE,
    cooldown_bars: int = 0,
    force_valid_windows: bool = False,
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
    high_arr = high if high is not None else (ohlcv["High"].to_numpy(dtype=np.float64) if "High" in ohlcv.columns else None)
    low_arr = low if low is not None else (ohlcv["Low"].to_numpy(dtype=np.float64) if "Low" in ohlcv.columns else None)
    indicator = _compute_indicator(close, variant, volume=volume, high=high_arr, low=low_arr)
    action_sig = compute_variant_signal_array(
        close,
        variant,
        volume=volume,
        high=high_arr,
        low=low_arr,
        cooldown_bars=cooldown_bars,
    )
    position_sig = compute_variant_position_array(
        close,
        variant,
        volume=volume,
        high=high_arr,
        low=low_arr,
        cooldown_bars=cooldown_bars,
    )

    # --- trades across all OOS windows ---
    trades, window_cash_starts = compute_variant_trade_register(
        ohlcv,
        close,
        variant,
        oos_windows,
        volume=volume,
        high=high_arr,
        low=low_arr,
        cost_bps=cost_bps,
        cooldown_bars=cooldown_bars,
        force_valid_windows=force_valid_windows,
    )

    # --- plots ---
    plots: dict[str, Any] = {}
    plots["price_indicator_signal"] = _plot_price_indicator_signal(
        close, action_sig, dates, oos_windows, indicator, variant,
    )

    eq_plot, dd_plot = _plot_oos_equity_and_drawdown(
        position_sig, close, dates, oos_windows, cost_bps,
    )
    if eq_plot is not None:
        plots["oos_equity"] = eq_plot
    if dd_plot is not None:
        plots["drawdown"] = dd_plot

    # --- trade performance summary ---
    perf = _trade_performance_summary(trades)
    total_pnl_realise_1u = round(sum(float(t.get("pnl_realise", 0.0)) for t in trades), 2)

    # --- aggregate metrics (same as stub but kept for compat) ---
    metrics: dict[str, Any] = {
        "total_pnl_realise_1u": total_pnl_realise_1u,
    }
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
            metrics["total_pnl_100k"] = metrics["total_pnl"]
            metrics["n_oos_windows"] = len(oos_windows)
            metrics["n_valid_windows"] = len(valid)
            metrics["total_trades"] = sum(w.n_trades for w in valid)

    # --- per-window detail ---
    cost_factor = cost_bps / 10_000.0
    per_window: list[dict[str, Any]] = []
    for w in oos_windows:
        if not w.is_valid and not force_valid_windows:
            continue
        window_start_cash = float(window_cash_starts.get(w.window_index, 0.0))
        window_start_realized = 0.0
        for trade in trades:
            if trade.get("oos_window") == w.window_index:
                window_start_realized = float(trade.get("pnl_realise_cumule", 0.0)) - float(trade.get("pnl_realise", 0.0))
                break
        window_trades = [
            _rebase_trade_totals(t, window_start_cash, window_start_realized)
            for t in trades
            if t.get("oos_window") == w.window_index
        ]
        end_idx = min(w.test_end, len(dates) - 1)
        eq_plot_w, dd_plot_w = _plot_single_window_equity_dd(position_sig, close, dates, w, cost_factor)
        per_window.append({
            "window_index": w.window_index,
            "start_date": str(dates[w.test_start])[:10],
            "end_date": str(dates[end_idx])[:10],
            "sharpe": round(w.sharpe, 4),
            "pnl": round(w.pnl, 2),
            "pnl_100k": round(w.pnl, 2),
            "n_trades": w.n_trades,
            "is_valid": w.is_valid,
            "plot": _plot_single_window(close, action_sig, position_sig, dates, w, indicator, variant),
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

def _extract_trade_register_legacy(
    sig: np.ndarray,
    close: np.ndarray,
    open_prices: np.ndarray,
    dates: pd.DatetimeIndex,
    oos_windows: list[OOSWindowResult],
    cost_bps: float,
    force_valid_windows: bool = False,
) -> tuple[list[dict[str, Any]], dict[int, float]]:
    """Extract per-fill trade register with realized/latent PnL.

    Signal fires at close of bar i → execution at open of bar i+1.
    One row per signal change (per-fill), not round-trip.
    """
    cost_factor = cost_bps / 10_000.0
    trades: list[dict[str, Any]] = []
    window_cash_starts: dict[int, float] = {}
    tresorerie = 0.0
    pnl_realise_cumule = 0.0

    for w in oos_windows:
        if not w.is_valid and not force_valid_windows:
            continue
        ts, te = w.test_start, w.test_end
        sig_oos = sig[ts:te]
        close_oos = close[ts:min(te + 1, len(close))]
        open_oos = open_prices[ts:min(te + 1, len(open_prices))]
        dates_oos = dates[ts:min(te + 1, len(dates))]
        cumulative_returns = _window_cumulative_returns(sig_oos, close_oos, cost_factor)

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
            cmp_display = 0.0

            if prev_pos == 0:
                # Opening: capitalize cost into CMP
                cmp = _cmp_after_open(exec_price, cost, new_pos)
                cmp_display = cmp
            elif new_pos == 0:
                # Closing position
                cmp_display = cmp
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
                cmp_display = cmp

            position = new_pos
            tresorerie += _cash_delta(exec_price, cost_factor, prev_pos, new_pos)
            pnl_realise_cumule += pnl_realise

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
                "open_t_plus_1": round(exec_price, 4),
                "prix_execution": round(exec_price, 4),
                "close_du_jour": round(close_du_jour, 4),
                "cmp": round(cmp_display, 4),
                "position": round(position, 1),
                "return_cumule": round(_sample_cumulative_return(cumulative_returns, exec_idx - 1), 10),
                "cash_cumulee": round(tresorerie, 4),
                "tresorerie": round(tresorerie, 4),
                "pnl_realise": round(pnl_realise, 4),
                "pnl_realise_cumule": round(pnl_realise_cumule, 4),
                "pnl_latent": round(pnl_latent, 4),
                "cout": round(cost, 4),
                "oos_window": w.window_index,
            })

        # Force-close any open position at end of window
        if position != 0:
            px = float(close_oos[-1])
            date_str = str(dates_oos[-1])[:10]
            cost = cost_factor * abs(position) * px
            cmp_display = cmp
            if position > 0:
                pnl_realise = px - cmp - cost
            else:
                pnl_realise = cmp - px - cost
            tresorerie += _cash_delta(px, cost_factor, position, 0.0)
            pnl_realise_cumule += pnl_realise
            trades.append({
                "date": date_str,
                "side": "VENTE" if position > 0 else "ACHAT",
                "open_t_plus_1": round(px, 4),
                "prix_execution": round(px, 4),
                "close_du_jour": round(px, 4),
                "cmp": round(cmp_display, 4),
                "position": 0.0,
                "return_cumule": round(_sample_cumulative_return(cumulative_returns, len(cumulative_returns) - 1), 10),
                "cash_cumulee": round(tresorerie, 4),
                "tresorerie": round(tresorerie, 4),
                "pnl_realise": round(pnl_realise, 4),
                "pnl_realise_cumule": round(pnl_realise_cumule, 4),
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


def _rebase_trade_totals(
    trade: dict[str, Any],
    start_cash: float,
    start_realized: float,
) -> dict[str, Any]:
    """Return a copy of a trade row rebased to the window's starting totals."""
    rebased = dict(trade)
    for key in ("tresorerie", "cash_cumulee"):
        cash_value = rebased.get(key)
        if isinstance(cash_value, (int, float)):
            rebased[key] = round(float(cash_value) - start_cash, 4)
    pnl_realise_cumule = rebased.get("pnl_realise_cumule")
    if isinstance(pnl_realise_cumule, (int, float)):
        rebased["pnl_realise_cumule"] = round(float(pnl_realise_cumule) - start_realized, 4)
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


def _window_net_returns(sig: np.ndarray, close: np.ndarray, cost_factor: float) -> np.ndarray:
    """Return per-bar net returns on the same basis as the OOS evaluator."""
    bars = min(len(sig), max(len(close) - 1, 0))
    if bars <= 0:
        return np.array([], dtype=float)

    sig_eff = sig[:bars]
    close_eff = close[:bars + 1]
    price_ret = close_eff[1:] / close_eff[:-1] - 1.0
    sig_change = np.abs(np.diff(sig_eff, prepend=0.0))
    return sig_eff * price_ret - cost_factor * sig_change


def _window_cumulative_returns(sig: np.ndarray, close: np.ndarray, cost_factor: float) -> np.ndarray:
    """Return cumulative compounded returns from the OOS evaluator return stream."""
    ret = _window_net_returns(sig, close, cost_factor)
    if len(ret) == 0:
        return np.array([], dtype=float)
    return np.cumprod(1.0 + ret) - 1.0


def _sample_cumulative_return(cumulative_returns: np.ndarray, idx: int) -> float:
    """Return a safe cumulative-return snapshot for a trade row."""
    if len(cumulative_returns) == 0:
        return 0.0
    clamped_idx = max(0, min(idx, len(cumulative_returns) - 1))
    return float(cumulative_returns[clamped_idx])


def _extract_trade_register(
    sig: np.ndarray,
    close: np.ndarray,
    open_prices: np.ndarray,
    dates: pd.DatetimeIndex,
    oos_windows: list[OOSWindowResult],
    cost_bps: float,
    force_valid_windows: bool = False,
) -> tuple[list[dict[str, Any]], dict[int, float]]:
    """Extract a long-only per-fill trade register.

    Signal fires at close of bar i -> execution at open of bar i+1.
    The carried position series must already be long-only in {0.0, +1.0}.
    """
    cost_factor = cost_bps / 10_000.0
    trades: list[dict[str, Any]] = []
    window_cash_starts: dict[int, float] = {}
    tresorerie = 0.0
    pnl_realise_cumule = 0.0

    for w in oos_windows:
        if not w.is_valid and not force_valid_windows:
            continue

        ts, te = w.test_start, w.test_end
        sig_oos = np.where(sig[ts:te] > 0.0, 1.0, 0.0)
        close_oos = close[ts:min(te + 1, len(close))]
        open_oos = open_prices[ts:min(te + 1, len(open_prices))]
        dates_oos = dates[ts:min(te + 1, len(dates))]
        cumulative_returns = _window_cumulative_returns(sig_oos, close_oos, cost_factor)

        position = 0.0
        cmp = 0.0
        window_cash_starts[w.window_index] = tresorerie

        for i, cur_sig in enumerate(sig_oos):
            if cur_sig == position:
                continue

            exec_idx = i + 1
            if exec_idx >= len(open_oos):
                break

            prev_pos = position
            new_pos = cur_sig
            exec_price = float(open_oos[exec_idx])
            close_du_jour = float(close_oos[exec_idx])
            cost = cost_factor * abs(new_pos - prev_pos) * exec_price
            pnl_realise = 0.0

            if prev_pos == 0.0:
                cmp = _cmp_after_open(exec_price, cost, new_pos)
                cmp_display = cmp
            else:
                cmp_display = cmp
                pnl_realise = exec_price - cmp - cost
                cmp = 0.0

            position = new_pos
            tresorerie += _cash_delta(exec_price, cost_factor, prev_pos, new_pos)
            pnl_realise_cumule += pnl_realise
            pnl_latent = (close_du_jour - cmp) if position > 0.0 else 0.0

            trades.append({
                "date": str(dates_oos[exec_idx])[:10],
                "side": "ACHAT" if new_pos > prev_pos else "VENTE",
                "open_t_plus_1": round(exec_price, 4),
                "prix_execution": round(exec_price, 4),
                "close_du_jour": round(close_du_jour, 4),
                "cmp": round(cmp_display, 4),
                "position": round(position, 1),
                "return_cumule": round(_sample_cumulative_return(cumulative_returns, exec_idx - 1), 10),
                "cash_cumulee": round(tresorerie, 4),
                "tresorerie": round(tresorerie, 4),
                "pnl_realise": round(pnl_realise, 4),
                "pnl_realise_cumule": round(pnl_realise_cumule, 4),
                "pnl_latent": round(pnl_latent, 4),
                "cout": round(cost, 4),
                "oos_window": w.window_index,
            })

        if position != 0.0:
            px = float(close_oos[-1])
            cost = cost_factor * px
            pnl_realise = px - cmp - cost
            tresorerie += _cash_delta(px, cost_factor, position, 0.0)
            pnl_realise_cumule += pnl_realise
            trades.append({
                "date": str(dates_oos[-1])[:10],
                "side": "VENTE",
                "open_t_plus_1": round(px, 4),
                "prix_execution": round(px, 4),
                "close_du_jour": round(px, 4),
                "cmp": round(cmp, 4),
                "position": 0.0,
                "return_cumule": round(_sample_cumulative_return(cumulative_returns, len(cumulative_returns) - 1), 10),
                "cash_cumulee": round(tresorerie, 4),
                "tresorerie": round(tresorerie, 4),
                "pnl_realise": round(pnl_realise, 4),
                "pnl_realise_cumule": round(pnl_realise_cumule, 4),
                "pnl_latent": 0.0,
                "cout": round(cost, 4),
                "oos_window": w.window_index,
            })

    return trades, window_cash_starts


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
    data: list[dict],
    close: np.ndarray,
    date_strs: list[str],
    *,
    buy_idx: list[int],
    sell_idx: list[int],
) -> None:
    """Append BUY/SELL marker traces to data list."""
    buy_x = [date_strs[i] for i in buy_idx if 0 <= i < len(date_strs)]
    buy_y = [float(close[i]) for i in buy_idx if 0 <= i < len(close)]
    sell_x = [date_strs[i] for i in sell_idx if 0 <= i < len(date_strs)]
    sell_y = [float(close[i]) for i in sell_idx if 0 <= i < len(close)]

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


def _slice_vals(values: np.ndarray, start: int, end: int) -> list[float | None]:
    return [float(v) if not np.isnan(v) else None for v in values[start : end + 1]]


def _extend_indicator_traces(data: list[dict], date_strs: list[str], indicator: dict[str, Any], start: int, end: int) -> None:
    ind_type = indicator.get("type", "none")
    if ind_type == "overlay":
        data.append({
            "type": "scatter",
            "x": date_strs,
            "y": _slice_vals(indicator["values"], start, end),
            "mode": "lines",
            "name": indicator["name"],
            "line": {"color": "#f97316", "width": 1.5, "dash": "dash"},
        })
        return
    if ind_type == "overlay_dual":
        for key, label, color in [("fast", indicator["fast_label"], "#f97316"), ("slow", indicator["slow_label"], "#8b5cf6")]:
            data.append({
                "type": "scatter",
                "x": date_strs,
                "y": _slice_vals(indicator[key], start, end),
                "mode": "lines",
                "name": label,
                "line": {"color": color, "width": 1.5, "dash": "dash"},
            })
        return
    if ind_type == "overlay_cloud":
        for key, label, color in [("tenkan_sen", "Tenkan", "#f97316"), ("kijun_sen", "Kijun", "#3b82f6")]:
            data.append({
                "type": "scatter",
                "x": date_strs,
                "y": _slice_vals(indicator[key], start, end),
                "mode": "lines",
                "name": label,
                "line": {"color": color, "width": 1.5},
            })
        data.append({
            "type": "scatter",
            "x": date_strs,
            "y": _slice_vals(indicator["senkou_a"], start, end),
            "mode": "lines",
            "name": "Senkou A",
            "line": {"color": "#16a34a", "width": 1.0},
        })
        data.append({
            "type": "scatter",
            "x": date_strs,
            "y": _slice_vals(indicator["senkou_b"], start, end),
            "mode": "lines",
            "name": "Senkou B",
            "line": {"color": "#dc2626", "width": 1.0},
            "fill": "tonexty",
            "fillcolor": "rgba(59,130,246,0.10)",
        })
        return
    if ind_type == "overlay_dots":
        data.append({
            "type": "scatter",
            "x": date_strs,
            "y": _slice_vals(indicator["values"], start, end),
            "mode": "markers",
            "name": indicator["name"],
            "marker": {"color": "#0f172a", "size": 5},
        })
        return
    if ind_type == "overlay_band":
        data.append({
            "type": "scatter",
            "x": date_strs,
            "y": _slice_vals(indicator["values"], start, end),
            "mode": "lines",
            "name": indicator["name"],
            "line": {"color": "#f97316", "width": 1.5},
        })
        data.append({
            "type": "scatter",
            "x": date_strs,
            "y": _slice_vals(indicator["upper"], start, end),
            "mode": "lines",
            "name": "Upper Band",
            "line": {"color": "#94a3b8", "width": 1.0, "dash": "dot"},
        })
        data.append({
            "type": "scatter",
            "x": date_strs,
            "y": _slice_vals(indicator["lower"], start, end),
            "mode": "lines",
            "name": "Lower Band",
            "line": {"color": "#94a3b8", "width": 1.0, "dash": "dot"},
            "fill": "tonexty",
            "fillcolor": "rgba(148,163,184,0.10)",
        })
        return
    if ind_type != "secondary_yaxis":
        return

    if "values" in indicator:
        data.append({
            "type": "scatter",
            "x": date_strs,
            "y": _slice_vals(indicator["values"], start, end),
            "mode": "lines",
            "name": indicator["name"],
            "line": {"color": "#8b5cf6", "width": 1.5},
            "yaxis": "y2",
        })
    if "macd_line" in indicator:
        data.append({
            "type": "scatter",
            "x": date_strs,
            "y": _slice_vals(indicator["macd_line"], start, end),
            "mode": "lines",
            "name": "MACD",
            "line": {"color": "#8b5cf6", "width": 1.5},
            "yaxis": "y2",
        })
    if "signal_line" in indicator:
        data.append({
            "type": "scatter",
            "x": date_strs,
            "y": _slice_vals(indicator["signal_line"], start, end),
            "mode": "lines",
            "name": "Signal",
            "line": {"color": "#f97316", "width": 1.5, "dash": "dash"},
            "yaxis": "y2",
        })
    if "histogram" in indicator:
        data.append({
            "type": "bar",
            "x": date_strs,
            "y": [0.0 if v is None else v for v in _slice_vals(indicator["histogram"], start, end)],
            "name": "Histogram",
            "yaxis": "y2",
            "marker": {"color": ["#10b981" if (v or 0.0) >= 0 else "#ef4444" for v in _slice_vals(indicator["histogram"], start, end)]},
        })
    if "obv" in indicator:
        data.append({
            "type": "scatter",
            "x": date_strs,
            "y": _slice_vals(indicator["obv"], start, end),
            "mode": "lines",
            "name": "OBV",
            "line": {"color": "#8b5cf6", "width": 1.5},
            "yaxis": "y2",
        })
    if "ad" in indicator:
        data.append({
            "type": "scatter",
            "x": date_strs,
            "y": _slice_vals(indicator["ad"], start, end),
            "mode": "lines",
            "name": "A/D Line",
            "line": {"color": "#8b5cf6", "width": 1.5},
            "yaxis": "y2",
        })
    if "ema_values" in indicator:
        data.append({
            "type": "scatter",
            "x": date_strs,
            "y": _slice_vals(indicator["ema_values"], start, end),
            "mode": "lines",
            "name": indicator["name"],
            "line": {"color": "#f97316", "width": 1.5, "dash": "dash"},
            "yaxis": "y2",
        })
    for key, label, color in [("plus_di", "+DI", "#10b981"), ("minus_di", "-DI", "#ef4444"), ("adx", "ADX", "#0f172a"), ("k", "%K", "#8b5cf6"), ("d", "%D", "#f97316")]:
        if key in indicator:
            data.append({
                "type": "scatter",
                "x": date_strs,
                "y": _slice_vals(indicator[key], start, end),
                "mode": "lines",
                "name": label,
                "line": {"color": color, "width": 1.5},
                "yaxis": "y2",
            })


def _indicator_shapes(indicator: dict[str, Any]) -> list[dict]:
    if indicator.get("type") != "secondary_yaxis":
        return []
    shapes: list[dict] = []
    if indicator.get("zero_line"):
        shapes.append({
            "type": "line",
            "xref": "paper",
            "yref": "y2",
            "x0": 0,
            "x1": 1,
            "y0": 0,
            "y1": 0,
            "line": {"color": "#94a3b8", "width": 1, "dash": "dot"},
        })
    for threshold in indicator.get("thresholds", []):
        shapes.append({
            "type": "line",
            "xref": "paper",
            "yref": "y2",
            "x0": 0,
            "x1": 1,
            "y0": threshold,
            "y1": threshold,
            "line": {"color": "#94a3b8", "width": 1, "dash": "dot"},
        })
    return shapes


def _plot_single_window(
    close: np.ndarray,
    action_sig: np.ndarray,
    position_sig: np.ndarray,
    dates: pd.DatetimeIndex,
    w: OOSWindowResult,
    indicator: dict[str, Any],
    variant: VariantDef,
) -> dict[str, Any]:
    """Generate a price+indicator+trades plot for a single OOS window."""
    ts = w.test_start
    te = min(w.test_end, len(dates) - 1)

    close_slice = close[ts:te + 1]
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

    ind_type = indicator.get("type", "none")
    _extend_indicator_traces(data, date_strs, indicator, ts, te)

    if is_rsi_level_variant(variant):
        buy_idx, sell_idx = rsi_window_marker_indices(
            action_sig,
            position_sig,
            start=ts,
            end=te,
        )
    else:
        buy_idx, sell_idx = transition_marker_indices(action_sig, start=ts, end=te)

    local_buy_idx = [i - ts for i in buy_idx if ts <= i <= te]
    local_sell_idx = [i - ts for i in sell_idx if ts <= i <= te]
    _add_buy_sell_markers(
        data,
        close_slice,
        date_strs,
        buy_idx=local_buy_idx,
        sell_idx=local_sell_idx,
    )

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
        if "y_range" in indicator:
            y2_config["range"] = indicator["y_range"]
        for shape in _indicator_shapes(indicator):
            layout.setdefault("shapes", []).append(shape)
        layout["yaxis2"] = y2_config
        layout["margin"]["r"] = 60

    return {"data": data, "layout": layout}


def _plot_price_indicator_signal(
    close: np.ndarray,
    action_sig: np.ndarray,
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

    ind_type = indicator.get("type", "none")
    _extend_indicator_traces(data, date_strs, indicator, 0, len(close) - 1)

    buy_idx, sell_idx = transition_marker_indices(action_sig)
    _add_buy_sell_markers(
        data,
        close,
        date_strs,
        buy_idx=buy_idx,
        sell_idx=sell_idx,
    )

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

    if ind_type == "secondary_yaxis":
        shapes.extend(_indicator_shapes(indicator))

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
        if "y_range" in indicator:
            y2_config["range"] = indicator["y_range"]
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
        ret = _window_net_returns(sig_oos, close_oos, cost_factor)

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
    ret = _window_net_returns(sig_oos, close_oos, cost_factor)

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
