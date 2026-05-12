# core/quant_core/plots.py
from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

LOGGER = logging.getLogger(__name__)


def _infer_epoch_unit(values: pd.Series) -> str:
    numeric = pd.to_numeric(values, errors="coerce")
    numeric = numeric[np.isfinite(numeric.to_numpy(dtype="float64", copy=False))]
    if numeric.empty:
        return "s"
    scale = float(np.nanmedian(np.abs(numeric.to_numpy(dtype="float64"))))
    if scale >= 1e17:
        return "ns"
    if scale >= 1e14:
        return "us"
    if scale >= 1e11:
        return "ms"
    return "s"


def _coerce_datetime_series(values: pd.Series, *, utc: bool = False) -> pd.Series:
    s = values.copy()
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns, UTC]" if utc else "datetime64[ns]")
    numeric = pd.to_numeric(s, errors="coerce")
    mask_numeric = numeric.notna()

    if (~mask_numeric).any():
        out.loc[~mask_numeric] = pd.to_datetime(s.loc[~mask_numeric], utc=utc, errors="coerce")

    if mask_numeric.any():
        num = numeric.loc[mask_numeric]
        abs_num = num.abs()
        mask_ns = abs_num >= 1e17
        mask_us = (abs_num >= 1e14) & (abs_num < 1e17)
        mask_ms = (abs_num >= 1e11) & (abs_num < 1e14)
        mask_s = abs_num < 1e11
        if mask_ns.any():
            out.loc[num.index[mask_ns]] = pd.to_datetime(num.loc[mask_ns], unit="ns", utc=utc, errors="coerce")
        if mask_us.any():
            out.loc[num.index[mask_us]] = pd.to_datetime(num.loc[mask_us], unit="us", utc=utc, errors="coerce")
        if mask_ms.any():
            out.loc[num.index[mask_ms]] = pd.to_datetime(num.loc[mask_ms], unit="ms", utc=utc, errors="coerce")
        if mask_s.any():
            out.loc[num.index[mask_s]] = pd.to_datetime(num.loc[mask_s], unit="s", utc=utc, errors="coerce")

    return out


def _find_matching_columns(df: pd.DataFrame, candidate: str) -> list[Any]:
    cand = str(candidate).strip().lower()
    out: list[Any] = []
    for c in df.columns:
        if str(c).strip().lower() == cand:
            out.append(c)
    return out


def _pick_series(df: pd.DataFrame, candidates: list[str]) -> Optional[pd.Series]:
    for name in candidates:
        matches = _find_matching_columns(df, name)
        if not matches:
            continue
        col = matches[0]
        data = df[col]
        if isinstance(data, pd.DataFrame):
            if data.shape[1] == 0:
                continue
            return data.iloc[:, 0]
        return data
    return None


def _pick_numeric_series(df: pd.DataFrame, candidates: list[str]) -> Optional[pd.Series]:
    for name in candidates:
        matches = _find_matching_columns(df, name)
        if not matches:
            continue
        for col in matches:
            same = df.loc[:, df.columns == col]
            if same.empty:
                continue
            for i in range(same.shape[1]):
                s = pd.to_numeric(same.iloc[:, i], errors="coerce")
                if s.notna().any():
                    return s
            return pd.to_numeric(same.iloc[:, 0], errors="coerce")
    return None


def _normalize_trade_side_value(value: Any) -> str | None:
    raw = str(value).strip().upper()
    if not raw:
        return None
    mapping = {
        "BUY": "BUY",
        "B": "BUY",
        "LONG": "BUY",
        "ENTRY": "BUY",
        "BUY_TO_COVER": "BUY",
        "ACHAT": "BUY",
        "SELL": "SELL",
        "S": "SELL",
        "SHORT": "SELL",
        "EXIT": "SELL",
        "SELL_SHORT": "SELL",
        "VENTE": "SELL",
    }
    if raw in mapping:
        return mapping[raw]
    if raw in {"1", "+1"}:
        return "BUY"
    if raw == "-1":
        return "SELL"
    if "BUY" in raw:
        return "BUY"
    if "SELL" in raw:
        return "SELL"
    return None


def _expand_round_trip_ledger_events(trades: pd.DataFrame) -> pd.DataFrame:
    """
    Convert closed-trade ledger rows (entry/exit) into marker events.

    Expected ledger-ish columns:
      - side: LONG/SHORT (or BUY/SELL)
      - entry_time / exit_time
      - entry_price / exit_price
    """
    if trades is None or trades.empty:
        return pd.DataFrame(columns=["timestamp", "side", "price"])

    t = trades.copy()
    side_raw = _pick_series(t, ["side", "direction", "position_side", "trade_side"])
    entry_ts_raw = _pick_series(t, ["entry_time", "entry_ts", "open_time", "start_time", "entry_date"])
    exit_ts_raw = _pick_series(t, ["exit_time", "exit_ts", "close_time", "end_time", "exit_date"])
    entry_px = _pick_numeric_series(t, ["entry_price", "open_price", "entry_px", "buy_price"])
    exit_px = _pick_numeric_series(t, ["exit_price", "close_price", "exit_px", "sell_price"])
    qty = _pick_numeric_series(t, ["qty", "quantite", "quantity", "size", "closed_qty"])

    if side_raw is None or (entry_ts_raw is None and exit_ts_raw is None):
        return pd.DataFrame(columns=["timestamp", "side", "price"])

    def _parse_ts(s: pd.Series | None) -> pd.Series:
        if s is None:
            return pd.Series(pd.NaT, index=t.index, dtype="datetime64[ns]")
        out = pd.to_datetime(s, utc=True, errors="coerce")
        if out.isna().all():
            out = pd.to_datetime(s, errors="coerce")
        return out.reindex(t.index)

    entry_ts = _parse_ts(entry_ts_raw)
    exit_ts = _parse_ts(exit_ts_raw)
    side_series = side_raw.reindex(t.index).astype(str)
    entry_px_series = pd.to_numeric(entry_px, errors="coerce").reindex(t.index) if entry_px is not None else pd.Series(np.nan, index=t.index)
    exit_px_series = pd.to_numeric(exit_px, errors="coerce").reindex(t.index) if exit_px is not None else pd.Series(np.nan, index=t.index)
    qty_series = pd.to_numeric(qty, errors="coerce").reindex(t.index) if qty is not None else pd.Series(np.nan, index=t.index)

    rows: list[dict[str, Any]] = []
    for i in t.index:
        side_norm = _normalize_trade_side_value(side_series.loc[i])
        if side_norm is None:
            qv = float(qty_series.loc[i]) if np.isfinite(qty_series.loc[i]) else np.nan
            if np.isfinite(qv):
                side_norm = "BUY" if qv >= 0.0 else "SELL"
        if side_norm is None:
            continue

        entry_side = side_norm
        exit_side = "SELL" if side_norm == "BUY" else "BUY"

        ts_entry = entry_ts.loc[i]
        ts_exit = exit_ts.loc[i]
        px_entry = float(entry_px_series.loc[i]) if np.isfinite(entry_px_series.loc[i]) else np.nan
        px_exit = float(exit_px_series.loc[i]) if np.isfinite(exit_px_series.loc[i]) else np.nan

        if pd.notna(ts_entry):
            rows.append({"timestamp": ts_entry, "side": entry_side, "price": px_entry})
        if pd.notna(ts_exit):
            rows.append({"timestamp": ts_exit, "side": exit_side, "price": px_exit})

    if not rows:
        return pd.DataFrame(columns=["timestamp", "side", "price"])
    return pd.DataFrame(rows, columns=["timestamp", "side", "price"])


def _clean_bars_for_plot(bars: pd.DataFrame | None) -> pd.DataFrame:
    if bars is None:
        return pd.DataFrame()

    df = bars.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, errors="coerce")
    else:
        df.index = pd.to_datetime(df.index, errors="coerce")

    df = df[~df.index.isna()]
    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]

    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    price_cols = [c for c in ("Open", "High", "Low", "Close") if c in df.columns]
    if price_cols:
        has_bar_data = df[price_cols].notna().any(axis=1)
        if "Close" in df.columns:
            has_bar_data = has_bar_data & pd.to_numeric(df["Close"], errors="coerce").notna()
        df = df.loc[has_bar_data]

    return df


def _missing_date_values(index: pd.Index) -> list[str]:
    if not isinstance(index, pd.DatetimeIndex) or len(index) < 2:
        return []

    idx = pd.DatetimeIndex(index).sort_values()
    if idx.tz is None:
        trading_days = pd.DatetimeIndex(idx.normalize()).unique().sort_values()
    else:
        trading_days = pd.DatetimeIndex(idx.tz_convert("UTC").normalize()).unique().sort_values()

    if len(trading_days) < 2:
        return []

    full_days = pd.date_range(trading_days.min(), trading_days.max(), freq="D")
    missing = full_days.difference(trading_days)
    return [d.strftime("%Y-%m-%d") for d in missing]


def _apply_no_data_date_filter(fig: go.Figure, index: pd.Index) -> None:
    missing_values = _missing_date_values(index)
    if missing_values:
        fig.update_xaxes(rangebreaks=[dict(values=missing_values)])


def _apply_daily_date_format(fig: go.Figure) -> None:
    # d3 format in Plotly: day number (no leading zero), short month name, full year.
    fig.update_xaxes(tickformat="%-d %b %Y", hoverformat="%-d %b %Y")


def make_equity_curve_plot(equity: pd.Series, *, title: str = "Equity Curve") -> go.Figure:
    """
    Pure plot function:
      - input: equity series indexed by datetime
      - output: plotly Figure
    """
    if equity is None:
        equity = pd.Series(dtype=float)

    e = equity.copy()
    if not isinstance(e.index, pd.DatetimeIndex):
        e.index = pd.to_datetime(e.index, errors="coerce")
    e = e.sort_index()
    e = e[~e.index.isna()]
    e = pd.to_numeric(e, errors="coerce")

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=e.index,
            y=e.values,
            mode="lines",
            name="Equity",
        )
    )

    fig.update_layout(
        title=title,
        template="plotly_white",
        font=dict(family="Arial", size=12),
        margin=dict(l=40, r=20, t=60, b=40),
        legend=dict(orientation="h"),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="Equity")
    _apply_no_data_date_filter(fig, e.index)
    _apply_daily_date_format(fig)
    return fig


def make_price_indicators_trades_plot(
    bars: pd.DataFrame,
    indicators: Optional[pd.DataFrame],
    fills: Optional[pd.DataFrame],
    *,
    strategy_params: Optional[dict] = None,
    indicator_cols: Optional[list[str]] = None,
) -> go.Figure:
    """
    MVP price panel:
      - bars: OHLCV dataframe indexed by datetime
      - indicators: optional indicator dataframe indexed by datetime
      - fills: trades/fills dataframe (your existing plotting uses `trades`)
    """
    return plot_price_indicators_trades_line(
        bars=bars,
        strategy_params=strategy_params,
        indicators=indicators,
        trades=fills,
        indicator_cols=indicator_cols,
        port_cfg=None,  # keep pure: no portfolio config needed for plotting
    )


# ======================================================================
# Legacy plotting helper kept pure Plotly with no UI or DB dependency.
# Keep the name to minimize changes across your codebase.
# ======================================================================
def plot_price_indicators_trades_line(
    bars: pd.DataFrame,
    strategy_params: dict | None = None,
    indicators: pd.DataFrame | None = None,
    trades: pd.DataFrame | None = None,
    indicator_cols: list[str] | None = None,
    *,
    port_cfg: Any | None = None,
    rsi_low: float = 30.0,
    rsi_high: float = 70.0,
) -> go.Figure:
    """
    Price (row 1), RSI and/or MACD panels (middle rows), Volume (last row).

    - RSI is plotted in its own panel with threshold lines + shaded regions.
    - MACD panel plots EMA_fast, EMA_slow + histogram (EMA_fast-EMA_slow) as bars
      with per-bar green/red intensity (stronger color as magnitude increases).
    """

    df = _clean_bars_for_plot(bars)

    ind = None
    if indicators is not None and not indicators.empty:
        ind = indicators.copy()
        if not isinstance(ind.index, pd.DatetimeIndex):
            ind.index = pd.to_datetime(ind.index)
        ind = ind.reindex(df.index)

        if indicator_cols is not None:
            keep = [c for c in indicator_cols if c in ind.columns]

            # Always keep any "known indicator families" if present, even if UI didn't request them.
            prefixes = ("sma_", "ema_", "rsi_", "macd_", "std_", "vwap_", "stoch_", "ichimoku_")
            keep += [c for c in ind.columns if c.startswith(prefixes)]
            keep += [c for c in ind.columns if c == "obv" or c.startswith("obv_ema_")]

            keep = sorted(set(keep))
            if keep:
                ind = ind[keep]

    def _maybe_add_bollinger_overlay():
        nonlocal fig, df, ind, indicator_cols

        if ind is None or ind.empty:
            return

        cols = list(ind.columns)

        # --- HARD GATE: only plot BB if explicitly requested ---
        is_bollinger_strategy = bool(strategy_params) and (
            ("bb_k" in (strategy_params or {})) or ("bb_window" in (strategy_params or {}))
        )

        has_std_col = any(c.startswith("std_") for c in cols)
        has_std_requested = bool(indicator_cols) and any(c.startswith("std_") for c in (indicator_cols or []))

        if not (is_bollinger_strategy or has_std_col or has_std_requested):
            return

        w = None

        if indicator_cols:
            for c in indicator_cols:
                if c.startswith("std_"):
                    try:
                        w = int(c.split("_", 1)[1])
                        break
                    except Exception:
                        pass

        if w is None:
            for c in cols:
                if c.startswith("std_"):
                    try:
                        w = int(c.split("_", 1)[1])
                        break
                    except Exception:
                        pass

        if w is None and is_bollinger_strategy:
            for c in cols:
                if c.startswith("sma_"):
                    try:
                        w = int(c.split("_", 1)[1])
                        break
                    except Exception:
                        pass

        if w is None:
            return

        k = float((strategy_params or {}).get("bb_k", 2.0))
        col_mid = f"sma_{w}"
        col_std = f"std_{w}"

        if col_mid not in ind.columns:
            return

        mid = pd.to_numeric(ind[col_mid], errors="coerce")

        if col_std in ind.columns:
            std = pd.to_numeric(ind[col_std], errors="coerce")
        else:
            if not is_bollinger_strategy:
                return
            std = pd.to_numeric(df["Close"], errors="coerce").rolling(int(w), min_periods=int(w)).std()

        upper = mid + k * std
        lower = mid - k * std

        fig.add_trace(go.Scatter(x=df.index, y=mid, mode="lines", name=f"BB mid (SMA{w})", line=dict(width=1)), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=upper, mode="lines", name=f"BB upper (k={k})", line=dict(width=1, dash="dash")), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=lower, mode="lines", name=f"BB lower (k={k})", line=dict(width=1, dash="dash")), row=1, col=1)

        fig.add_trace(
            go.Scatter(x=df.index, y=upper, mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"),
            row=1, col=1
        )
        fig.add_trace(
            go.Scatter(x=df.index, y=lower, mode="lines", fill="tonexty", line=dict(width=0), name="BB band", opacity=0.12, hoverinfo="skip"),
            row=1, col=1
        )

    # ----------------------------
    # Detect panels / overlays
    # ----------------------------
    rsi_col: str | None = None
    macd_base: str | None = None

    obv_col: str | None = None
    obv_ema_col: str | None = None

    stoch_k_col: str | None = None
    stoch_d_col: str | None = None
    vwap_col: str | None = None

    ich_tenkan_col: str | None = None
    ich_kijun_col: str | None = None
    ich_span_a_col: str | None = None
    ich_span_b_col: str | None = None

    has_rsi = False
    has_macd = False
    has_obv = False
    has_stoch = False
    has_ichimoku = False
    has_vwap = False

    if ind is not None and not ind.empty:
        cols = list(ind.columns)

        # ---------- RSI ----------
        rsi_cols = [c for c in cols if c.startswith("rsi_")]
        if rsi_cols:
            w = (strategy_params or {}).get("rsi_window", None)
            if w is not None:
                cand = f"rsi_{int(w)}"
                if cand in ind.columns:
                    rsi_col = cand
            if rsi_col is None and indicator_cols:
                for c in indicator_cols:
                    if c in ind.columns and c.startswith("rsi_"):
                        rsi_col = c
                        break
            if rsi_col is None:
                rsi_col = sorted(rsi_cols)[-1]
            has_rsi = rsi_col is not None

        # ---------- MACD ----------
        macd_bases = sorted({c.split("__", 1)[0] for c in cols if c.startswith("macd_") and "__" in c})
        if macd_bases:
            macd_base = macd_bases[-1]
            has_macd = True

        # ---------- OBV ----------
        if "obv" in cols:
            obv_col = "obv"
            has_obv = True
            ema_cols = [c for c in cols if c.startswith("obv_ema_")]
            if ema_cols:
                span = (strategy_params or {}).get("obv_span", None)
                if span is not None:
                    cand = f"obv_ema_{int(span)}"
                    if cand in cols:
                        obv_ema_col = cand
                if obv_ema_col is None:
                    obv_ema_col = sorted(ema_cols)[-1]

        # ---------- STOCH + VWAP ----------
        stoch_k = [c for c in cols if c.endswith("__k") and c.startswith("stoch_")]
        stoch_d = [c for c in cols if c.endswith("__d") and c.startswith("stoch_")]
        if stoch_k and stoch_d:
            stoch_k_col = sorted(stoch_k)[-1]
            stoch_d_col = sorted(stoch_d)[-1]
            has_stoch = True
        vwap = [c for c in cols if c.startswith("vwap_")]
        if vwap:
            vwap_col = sorted(vwap)[-1]
            has_vwap = True

        # ---------- ICHIMOKU ----------
        ich_bases = sorted({c.split("__", 1)[0] for c in cols if c.startswith("ichimoku_") and "__" in c})
        if ich_bases:
            base = ich_bases[-1]
            t = f"{base}__tenkan"
            k = f"{base}__kijun"
            a = f"{base}__span_a"
            b = f"{base}__span_b"
            if all(x in cols for x in (t, k, a, b)):
                ich_tenkan_col, ich_kijun_col, ich_span_a_col, ich_span_b_col = t, k, a, b
                has_ichimoku = True

    # ----------------------------
    # Layout: dynamic rows
    # ----------------------------
    panels = []
    if has_rsi:
        panels.append("rsi")
    if has_macd:
        panels.append("macd")
    if has_obv:
        panels.append("obv")
    if has_stoch:
        panels.append("stoch")
    if has_ichimoku:
        panels.append("ichimoku")  # plotted on price row, but keep notionally

    n_rows = 1 + (1 if ("rsi" in panels) else 0) + (1 if ("macd" in panels) else 0) + (1 if ("obv" in panels) else 0) + (1 if ("stoch" in panels) else 0) + 1
    vol_row = n_rows

    row_heights = [0.55]
    for p in panels:
        if p == "ichimoku":
            continue
        row_heights.append(0.12)
    row_heights.append(0.21)

    # Build subplot specs: only MACD row needs secondary_y=True (histogram)
    specs = [[{"secondary_y": False}] for _ in range(n_rows)]

    # Determine 1-based row index of each panel row (excluding price row, including volume at end)
    row_ptr = 2  # first mid-panel row (row 1 is price)
    panel_row = {}
    for p in panels:
        if p == "ichimoku":
            continue  # ichimoku is overlaid on price row
        panel_row[p] = row_ptr
        row_ptr += 1

    # Enable secondary axis on MACD row (because we plot histogram on secondary_y=True)
    if "macd" in panel_row:
        specs[panel_row["macd"] - 1][0] = {"secondary_y": True}

    fig = make_subplots(
        rows=n_rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=row_heights,
        specs=specs,
    )


    # ----------------------------
    # PRICE (row 1)
    # ----------------------------
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=pd.to_numeric(df.get("Open"), errors="coerce"),
            high=pd.to_numeric(df.get("High"), errors="coerce"),
            low=pd.to_numeric(df.get("Low"), errors="coerce"),
            close=pd.to_numeric(df.get("Close"), errors="coerce"),
            name="Price",
            increasing=dict(line=dict(color="#16a34a"), fillcolor="#dcfce7"),
            decreasing=dict(line=dict(color="#dc2626"), fillcolor="#fee2e2"),
        ),
        row=1,
        col=1,
    )

    if ind is not None and not ind.empty:
        # generic overlays: SMA/EMA/VWAP + Ichimoku lines
        for c in ind.columns:
            if c.startswith(("sma_", "ema_", "vwap_")):
                fig.add_trace(go.Scatter(x=df.index, y=ind[c], mode="lines", name=c, line=dict(width=1)), row=1, col=1)

        if has_ichimoku:
            fig.add_trace(go.Scatter(x=df.index, y=ind[ich_tenkan_col], mode="lines", name="Tenkan", line=dict(width=1)), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=ind[ich_kijun_col], mode="lines", name="Kijun", line=dict(width=1)), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=ind[ich_span_a_col], mode="lines", name="Span A", line=dict(width=1, dash="dot")), row=1, col=1)
            fig.add_trace(go.Scatter(x=df.index, y=ind[ich_span_b_col], mode="lines", name="Span B", line=dict(width=1, dash="dot")), row=1, col=1)

    _maybe_add_bollinger_overlay()

    # ----------------------------
    # Trade markers (BUY/SELL) on price
    # ----------------------------
    if trades is not None and not trades.empty:
        debug = False
        t = trades.copy()
        ts_raw = _pick_series(
            t,
            [
                "timestamp",
                "time",
                "datetime",
                "date",
                "trade_date",
                "signal_date",
                "ts",
            ],
        )
        if ts_raw is None:
            if isinstance(t.index, pd.DatetimeIndex):
                ts_raw = pd.Series(t.index, index=t.index)
            else:
                ts_raw = _pick_series(t, ["index"])
        if ts_raw is None:
            ledger_events = _expand_round_trip_ledger_events(t)
            if not ledger_events.empty:
                t = ledger_events
                ts_raw = t["timestamp"]
        if ts_raw is not None:
            t["timestamp"] = _coerce_datetime_series(pd.Series(ts_raw, index=t.index), utc=True)
            if t["timestamp"].isna().all():
                # Fallback for non-UTC parseable string/object timestamps.
                t["timestamp"] = _coerce_datetime_series(pd.Series(ts_raw, index=t.index), utc=False)

            t = t.dropna(subset=["timestamp"]).sort_values("timestamp")

            qty = _pick_numeric_series(t, ["qty", "quantite", "quantity", "position_change", "delta_qty"])

            side_raw = _pick_series(t, ["side", "order_side", "action", "trade_side", "direction", "signal"])
            if side_raw is None:
                if qty is not None:
                    side = np.where(pd.to_numeric(qty, errors="coerce").fillna(0.0) > 0.0, "BUY", "SELL")
                    t["side"] = pd.Series(side, index=t.index)
                else:
                    t["side"] = "BUY"
            else:
                t["side"] = side_raw

            t["side"] = t["side"].astype(str).str.strip().str.upper()
            t["side"] = t["side"].replace(
                {
                    "1": "BUY",
                    "+1": "BUY",
                    "LONG": "BUY",
                    "B": "BUY",
                    "ENTRY": "BUY",
                    "BUY_TO_COVER": "BUY",
                    "-1": "SELL",
                    "SHORT": "SELL",
                    "S": "SELL",
                    "EXIT": "SELL",
                    "SELL_SHORT": "SELL",
                }
            )

            # If side labels are non-canonical, infer from qty when possible.
            if qty is not None:
                q = pd.to_numeric(qty, errors="coerce").reindex(t.index).fillna(0.0)
                bad_side = ~t["side"].isin(["BUY", "SELL"])
                t.loc[bad_side & (q > 0.0), "side"] = "BUY"
                t.loc[bad_side & (q <= 0.0), "side"] = "SELL"

            price = _pick_numeric_series(
                t,
                [
                    "price",
                    "fill_price",
                    "execution_price",
                    "net_price",
                    "prix_execution_open_jour",
                    "prix d'execution (open du jour)",
                    "prix d'éxécution (open du jour)",
                    "prix d'Ã©xÃ©cution (open du jour)",
                    "close_du_jour",
                    "close",
                    "_mark",
                ],
            )
            if price is None:
                y = pd.Series(np.nan, index=t.index, dtype="float64")
            else:
                y = pd.to_numeric(price, errors="coerce").reindex(t.index)

            # Normalize trade timestamps to the same tz-naive/tz-aware convention as bars index.
            df_idx = pd.to_datetime(df.index, utc=True, errors="coerce")
            if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is None:
                if getattr(t["timestamp"].dt, "tz", None) is not None:
                    t["timestamp"] = t["timestamp"].dt.tz_convert(None)
                df_ts = pd.DatetimeIndex(df_idx).tz_convert(None)
            else:
                target_tz = getattr(getattr(df.index, "tz", None), "key", None) or getattr(df.index, "tz", None)
                if target_tz is not None:
                    if getattr(t["timestamp"].dt, "tz", None) is None:
                        t["timestamp"] = t["timestamp"].dt.tz_localize(target_tz)
                    else:
                        t["timestamp"] = t["timestamp"].dt.tz_convert(target_tz)
                    df_ts = pd.DatetimeIndex(df_idx).tz_convert(target_tz)
                else:
                    df_ts = pd.DatetimeIndex(df_idx)

            close_vals = pd.to_numeric(df["Close"], errors="coerce").to_numpy(dtype="float64")
            close_ref = (
                pd.DataFrame({"bar_ts": df_ts, "close": close_vals})
                .dropna(subset=["bar_ts", "close"])
                .sort_values("bar_ts")
            )

            tol = pd.Timedelta(hours=36)
            if len(df_ts) >= 2:
                diffs = pd.Series(df_ts).sort_values().diff().dropna()
                diffs = diffs[diffs > pd.Timedelta(0)]
                if not diffs.empty:
                    med = pd.Timedelta(diffs.median())
                    min_tol = pd.Timedelta(hours=1)
                    scaled = med * 3
                    tol = scaled if scaled > min_tol else min_tol

            # Use nearest close for each trade time (not exact reindex) with a reasonable tolerance.
            if close_ref.empty:
                close_map = np.full(len(t), np.nan, dtype="float64")
            else:
                probe = pd.DataFrame({"_i": np.arange(len(t), dtype="int64"), "timestamp": t["timestamp"]})
                probe = probe.sort_values("timestamp")
                mapped = pd.merge_asof(
                    probe,
                    close_ref,
                    left_on="timestamp",
                    right_on="bar_ts",
                    direction="nearest",
                    tolerance=tol,
                )
                mapped = mapped.sort_values("_i")
                close_map = mapped["close"].to_numpy(dtype="float64")

            price_vals = y.to_numpy(dtype="float64")
            is_price_valid = np.isfinite(price_vals) & (price_vals > 0.0)
            close_is_valid = np.isfinite(close_map) & (close_map > 0.0)

            rel_diff = np.full(len(t), np.nan, dtype="float64")
            both_valid = is_price_valid & close_is_valid
            rel_diff[both_valid] = np.abs(price_vals[both_valid] - close_map[both_valid]) / close_map[both_valid]

            # Keep trade price only if sane; otherwise anchor marker to nearest close.
            use_trade_price = is_price_valid & (~close_is_valid | (rel_diff <= 0.25))
            t["y_plot"] = np.where(use_trade_price, price_vals, close_map)
            t["x_plot"] = t["timestamp"]

            if debug:
                LOGGER.info(
                    "Trade marker debug bars=%d trades=%d ts_nan=%d x_nan=%d y_nan=%d tol=%s bars_range=[%s, %s] trades_range=[%s, %s]",
                    len(df_ts),
                    len(t),
                    int(t["timestamp"].isna().sum()),
                    int(t["x_plot"].isna().sum()),
                    int(pd.Series(t["y_plot"]).isna().sum()),
                    str(tol),
                    str(df_ts.min()) if len(df_ts) else "NaT",
                    str(df_ts.max()) if len(df_ts) else "NaT",
                    str(t["timestamp"].min()) if not t.empty else "NaT",
                    str(t["timestamp"].max()) if not t.empty else "NaT",
                )

            buys = t[t["side"] == "BUY"]
            sells = t[t["side"] == "SELL"]

            buys = buys[
                buys["x_plot"].notna() & np.isfinite(pd.to_numeric(buys["y_plot"], errors="coerce").to_numpy(dtype="float64"))
            ]
            sells = sells[
                sells["x_plot"].notna() & np.isfinite(pd.to_numeric(sells["y_plot"], errors="coerce").to_numpy(dtype="float64"))
            ]

            if not buys.empty:
                fig.add_trace(
                    go.Scatter(
                        x=buys["x_plot"],
                        y=buys["y_plot"],
                        mode="markers+text",
                        marker=dict(
                            size=18,
                            symbol="triangle-up",
                            color="#00E676",
                            opacity=1.0,
                            line=dict(color="#004D00", width=2),
                        ),
                        text=["▲ BUY"] * len(buys),
                        textposition="top center",
                        textfont=dict(size=11, color="#004D00", family="Arial Black"),
                        name="BUY",
                        showlegend=True,
                    ),
                    row=1, col=1
                )
            if not sells.empty:
                fig.add_trace(
                    go.Scatter(
                        x=sells["x_plot"],
                        y=sells["y_plot"],
                        mode="markers+text",
                        marker=dict(
                            size=18,
                            symbol="triangle-down",
                            color="#FF1744",
                            opacity=1.0,
                            line=dict(color="#7F0000", width=2),
                        ),
                        text=["▼ SELL"] * len(sells),
                        textposition="bottom center",
                        textfont=dict(size=11, color="#7F0000", family="Arial Black"),
                        name="SELL",
                        showlegend=True,
                    ),
                    row=1, col=1
                )

    # ----------------------------
    # Indicator panels
    # ----------------------------
    row_ptr = 2

    if has_rsi and ind is not None:
        r = pd.to_numeric(ind[rsi_col], errors="coerce")
        fig.add_trace(go.Scatter(x=df.index, y=r, mode="lines", name=f"RSI ({rsi_col})", line=dict(width=1)), row=row_ptr, col=1)
        fig.add_hline(y=rsi_low, line_dash="dash", row=row_ptr, col=1)
        fig.add_hline(y=rsi_high, line_dash="dash", row=row_ptr, col=1)
        row_ptr += 1

    if has_macd and ind is not None and macd_base is not None:
        line_col = f"{macd_base}__line"
        sig_col  = f"{macd_base}__signal"
        hist_col = f"{macd_base}__hist"

        row = panel_row.get("macd", row_ptr)  # prefer mapped row

        line = pd.to_numeric(ind.get(line_col), errors="coerce")
        sigl = pd.to_numeric(ind.get(sig_col), errors="coerce")
        hist = pd.to_numeric(ind[hist_col], errors="coerce") if (hist_col in ind.columns) else (line - sigl)

        # MACD lines on primary axis
        fig.add_trace(go.Scatter(x=df.index, y=line, mode="lines", name=f"{macd_base} line"), row=row, col=1, secondary_y=False)
        fig.add_trace(go.Scatter(x=df.index, y=sigl, mode="lines", name=f"{macd_base} signal"), row=row, col=1, secondary_y=False)

        # Histogram on secondary axis (this is why specs must enable secondary_y on this row)
        h = hist.fillna(0.0).astype(float)
        fig.add_trace(go.Bar(x=df.index, y=h.values, name=f"{macd_base} hist"), row=row, col=1, secondary_y=True)

        # Optional: zero line on histogram axis (same idea as app.py)
        fig.add_trace(
            go.Scatter(x=df.index, y=np.zeros(len(df.index)), mode="lines", showlegend=False),
            row=row, col=1, secondary_y=True
        )

        fig.update_yaxes(title_text="MACD", row=row, col=1, secondary_y=False)
        fig.update_yaxes(title_text="Hist", row=row, col=1, secondary_y=True)


    if has_obv and ind is not None:
        obv = pd.to_numeric(ind[obv_col], errors="coerce")
        fig.add_trace(go.Scatter(x=df.index, y=obv, mode="lines", name="OBV", line=dict(width=1)), row=row_ptr, col=1)
        if obv_ema_col and obv_ema_col in ind.columns:
            fig.add_trace(go.Scatter(x=df.index, y=ind[obv_ema_col], mode="lines", name=obv_ema_col, line=dict(width=1)), row=row_ptr, col=1)
        row_ptr += 1

    if has_stoch and ind is not None:
        k = pd.to_numeric(ind[stoch_k_col], errors="coerce")
        d = pd.to_numeric(ind[stoch_d_col], errors="coerce")
        fig.add_trace(go.Scatter(x=df.index, y=k, mode="lines", name="Stoch %K", line=dict(width=1)), row=row_ptr, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=d, mode="lines", name="Stoch %D", line=dict(width=1)), row=row_ptr, col=1)
        row_ptr += 1

    # ----------------------------
    # VOLUME (last row) + gate/cap overlays
    # ----------------------------
    vcol = str(getattr(port_cfg, "volume_col", "Volume")) if port_cfg is not None else "Volume"
    if vcol in df.columns:
        vol = pd.to_numeric(df[vcol], errors="coerce").fillna(0.0).astype(float)
        fig.add_trace(go.Bar(x=df.index, y=vol, name="Volume"), row=vol_row, col=1)

        def _adv(series: pd.Series, window: int) -> pd.Series:
            w = int(max(1, window))
            return series.rolling(w, min_periods=1).mean()

        if port_cfg is not None:
            if bool(getattr(port_cfg, "use_volume_gate", False)):
                kind = str(getattr(port_cfg, "volume_gate_kind", "min_abs"))
                if kind == "min_abs":
                    gate_val = float(getattr(port_cfg, "min_volume_abs", 0.0))
                    gate_line = pd.Series(gate_val, index=df.index, dtype="float64")
                else:
                    ratio = float(getattr(port_cfg, "min_volume_ratio_adv", 0.0))
                    w = int(getattr(port_cfg, "volume_gate_adv_window", 20))
                    gate_line = ratio * _adv(vol, w)

                fig.add_trace(
                    go.Scatter(
                        x=df.index,
                        y=gate_line.values,
                        mode="lines",
                        name="Gate",
                        line=dict(width=1, dash="dot"),
                    ),
                    row=vol_row,
                    col=1,
                )

            if bool(getattr(port_cfg, "use_participation_cap", False)):
                pr = float(getattr(port_cfg, "participation_rate", 0.05))
                basis = str(getattr(port_cfg, "participation_basis", "bar"))
                if basis == "bar":
                    liq = vol
                else:
                    w = int(getattr(port_cfg, "adv_window", 20))
                    liq = _adv(vol, w)
                cap_line = pr * liq

                fig.add_trace(
                    go.Scatter(
                        x=df.index,
                        y=cap_line.values,
                        mode="lines",
                        name="Cap",
                        line=dict(width=1, dash="dash"),
                    ),
                    row=vol_row,
                    col=1,
                )

    fig.update_layout(
        template="plotly_white",
        font=dict(family="Arial", size=12),
        legend=dict(orientation="h"),
        margin=dict(l=40, r=20, t=60, b=40),
        bargap=0.0,
        hovermode="x unified",
        xaxis_rangeslider_visible=False,
    )
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=vol_row, col=1)
    _apply_no_data_date_filter(fig, df.index)
    _apply_daily_date_format(fig)

    return fig


def _coerce_series_for_plot(series: pd.Series | None) -> pd.Series:
    if series is None:
        return pd.Series(dtype=float)
    out = series.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index, errors="coerce")
    out = out.sort_index()
    out = out[~out.index.isna()]
    return pd.to_numeric(out, errors="coerce")


def make_drawdown_plot(
    drawdown: pd.Series | None,
    *,
    title: str = "Drawdown",
) -> go.Figure:
    dd = _coerce_series_for_plot(drawdown)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=dd.index,
            y=dd.values,
            mode="lines",
            name="Drawdown",
            line=dict(color="#dc2626", width=2),
            fill="tozeroy",
            fillcolor="rgba(220,38,38,0.20)",
        )
    )
    fig.update_layout(
        title=title,
        template="plotly_white",
        font=dict(family="Arial", size=12),
        margin=dict(l=40, r=20, t=60, b=40),
        legend=dict(orientation="h"),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="Drawdown", tickformat=".1%")
    _apply_no_data_date_filter(fig, dd.index)
    _apply_daily_date_format(fig)
    return fig


def make_cumreturn_vs_benchmark_plot(
    strategy_cum: pd.Series | None,
    benchmark_cum: pd.Series | None,
    *,
    strategy_label: str = "Strategy",
    benchmark_label: str = "Benchmark",
    title: str = "Cumulative Returns vs Benchmark",
) -> go.Figure:
    strat = _coerce_series_for_plot(strategy_cum)
    bench = _coerce_series_for_plot(benchmark_cum)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=strat.index,
            y=strat.values,
            mode="lines",
            name=strategy_label,
            line=dict(width=2),
        )
    )
    if not bench.empty:
        fig.add_trace(
            go.Scatter(
                x=bench.index,
                y=bench.values,
                mode="lines",
                name=benchmark_label,
                line=dict(width=2, dash="dot"),
            )
        )

    fig.update_layout(
        title=title,
        template="plotly_white",
        font=dict(family="Arial", size=12),
        margin=dict(l=40, r=20, t=60, b=40),
        legend=dict(orientation="h"),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="Cumulative Return", tickformat=".1%")
    _apply_no_data_date_filter(fig, strat.index)
    _apply_daily_date_format(fig)
    return fig


def make_monthly_heatmap_plot(
    monthly_returns: pd.DataFrame | None,
    *,
    title: str = "Monthly Returns Heatmap",
) -> go.Figure:
    months = list(range(1, 13))
    month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    if monthly_returns is None or monthly_returns.empty:
        fig = go.Figure()
        fig.update_layout(title=f"{title} (no data)", template="plotly_white")
        return fig

    monthly = monthly_returns.copy()
    monthly = monthly.reindex(columns=months)
    monthly = monthly.sort_index()
    z = (monthly.astype(float) * 100.0).to_numpy()
    text = np.where(np.isfinite(z), np.char.add(np.round(z, 1).astype(str), "%"), "")

    zmin = float(np.nanmin(z)) if np.isfinite(z).any() else -1.0
    zmax = float(np.nanmax(z)) if np.isfinite(z).any() else 1.0
    if np.isclose(zmin, zmax):
        zmin -= 1.0
        zmax += 1.0

    fig = go.Figure(
        data=[
            go.Heatmap(
                z=z,
                x=month_labels,
                y=[str(y) for y in monthly.index.tolist()],
                colorscale="RdYlGn",
                zmid=0.0,
                zmin=zmin,
                zmax=zmax,
                text=text,
                texttemplate="%{text}",
                hovertemplate="Year=%{y}<br>Month=%{x}<br>Return=%{z:.2f}%<extra></extra>",
                colorbar=dict(title="%"),
            )
        ]
    )
    fig.update_layout(
        title=title,
        template="plotly_white",
        font=dict(family="Arial", size=12),
        margin=dict(l=60, r=20, t=60, b=40),
    )
    return fig


def make_batch_period_heatmap_plot(
    objective_matrix: pd.DataFrame | None,
    *,
    objective: str = "pnl",
    title: str = "Batch Period Heatmap",
) -> go.Figure:
    if objective_matrix is None or objective_matrix.empty:
        fig = go.Figure()
        fig.update_layout(title=f"{title} (no data)", template="plotly_white")
        return fig

    matrix = objective_matrix.copy()
    z_raw = matrix.astype(float).to_numpy()

    is_cagr_like = str(objective).strip().lower() in {"cagr", "total_return", "sharpe", "max_drawdown", "win_pct"}
    z = z_raw * 100.0 if is_cagr_like else z_raw
    suffix = "%" if is_cagr_like else ""
    text = np.where(np.isfinite(z), np.char.add(np.round(z, 2).astype(str), suffix), "")

    if np.isfinite(z).any():
        zmin = float(np.nanmin(z))
        zmax = float(np.nanmax(z))
    else:
        zmin, zmax = -1.0, 1.0
    if np.isclose(zmin, zmax):
        zmin -= 1.0
        zmax += 1.0

    fig = go.Figure(
        data=[
            go.Heatmap(
                z=z,
                x=[str(c) for c in matrix.columns.tolist()],
                y=[str(i) for i in matrix.index.tolist()],
                colorscale="RdYlGn",
                zmid=0.0,
                zmin=zmin,
                zmax=zmax,
                text=text,
                texttemplate="%{text}",
                hovertemplate="Period=%{y}<br>Strategy=%{x}<br>Value=%{z:.4f}<extra></extra>",
                colorbar=dict(title=suffix or "value"),
            )
        ]
    )
    fig.update_layout(
        title=title,
        template="plotly_white",
        font=dict(family="Arial", size=12),
        margin=dict(l=80, r=20, t=60, b=40),
    )
    return fig


def make_yearly_return_bar_plot(
    yearly_returns: pd.Series | pd.DataFrame | None,
    *,
    title: str = "Yearly Returns",
) -> go.Figure:
    if yearly_returns is None:
        fig = go.Figure()
        fig.update_layout(title=f"{title} (no data)", template="plotly_white")
        return fig

    if isinstance(yearly_returns, pd.DataFrame):
        if yearly_returns.empty:
            fig = go.Figure()
            fig.update_layout(title=f"{title} (no data)", template="plotly_white")
            return fig
        yearly = pd.to_numeric(yearly_returns.iloc[:, 0], errors="coerce")
    else:
        yearly = pd.to_numeric(yearly_returns, errors="coerce")

    yearly = yearly.dropna()
    if yearly.empty:
        fig = go.Figure()
        fig.update_layout(title=f"{title} (no data)", template="plotly_white")
        return fig

    years = [str(y) for y in yearly.index.tolist()]
    vals = yearly.astype(float).tolist()
    colors = ["#16a34a" if v >= 0 else "#dc2626" for v in vals]

    fig = go.Figure(
        data=[
            go.Bar(
                x=years,
                y=vals,
                marker=dict(color=colors),
                hovertemplate="Year=%{x}<br>Return=%{y:.2%}<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        title=title,
        template="plotly_white",
        font=dict(family="Arial", size=12),
        margin=dict(l=40, r=20, t=60, b=40),
        hovermode="x unified",
    )
    fig.update_yaxes(title_text="Return", tickformat=".1%")
    return fig
