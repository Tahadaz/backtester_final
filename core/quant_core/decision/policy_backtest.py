from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from ..data import MarketData
from ..engine import BacktestBundle, build_strategy
from ..indicators import FeaturesData, IndicatorEngine
from ..plots import make_drawdown_plot
from ..portfolio import CostModel, Fill, PortfolioEngine, PortfolioResult
from ..results import ResultsAnalyzer
from ..strategy import SignalFrame, default_plot_indicators
from .decision_page import build_decision_page
from .levels import compute_levels_support_resistance
from .risk import compute_rr_and_invalidation
from .scoring import (
    compute_confidence_score,
    compute_opportunity_score,
    deterministic_seed_from_key,
)


ExecutionMode = Literal["next_open", "next_close"]
DecisionAsOfMode = Literal["close_t", "close_t-1"]


@dataclass
class _OpenTrade:
    direction: int
    qty_abs: int
    qty_signed: int
    entry_idx: int
    monitor_start_idx: int
    entry_ts: pd.Timestamp
    entry_price: float
    entry_cost: float
    stop: float
    target: float
    opportunity_score: float
    confidence_score: float
    decision_date: pd.Timestamp
    risk_per_share: float


def _coerce_bars(bars: pd.DataFrame) -> pd.DataFrame:
    if bars is None or bars.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    out = bars.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index, errors="coerce")
    out = out[~out.index.isna()].sort_index()
    out = out[~out.index.duplicated(keep="last")]

    needed = ["Open", "High", "Low", "Close"]
    missing = [c for c in needed if c not in out.columns]
    if missing:
        raise ValueError(f"Bars are missing required columns: {missing}")

    if "Volume" not in out.columns:
        out["Volume"] = 0.0
    for col in ("Open", "High", "Low", "Close", "Volume"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=["Open", "High", "Low", "Close"])
    return out[["Open", "High", "Low", "Close", "Volume"]]


def _as_timestamp(value: Any) -> pd.Timestamp:
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        raise ValueError(f"Invalid date value: {value}")
    return pd.Timestamp(ts)


def _align_boundary_to_index_tz(idx: pd.DatetimeIndex, ts: pd.Timestamp) -> pd.Timestamp:
    idx_tz = getattr(idx, "tz", None)
    if idx_tz is None:
        if getattr(ts, "tzinfo", None) is not None:
            return ts.tz_convert(None)
        return ts
    if getattr(ts, "tzinfo", None) is None:
        return ts.tz_localize(idx_tz)
    return ts.tz_convert(idx_tz)


def _annualized_cagr(returns: pd.Series, periods_per_year: int) -> float:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty:
        return 0.0
    total = float((1.0 + clean).prod() - 1.0)
    n = int(len(clean))
    base = 1.0 + total
    if base <= 0.0 or n <= 0:
        return -1.0
    return float(base ** (float(periods_per_year) / float(n)) - 1.0)


def _sharpe(returns: pd.Series, periods_per_year: int, rf_annual: float) -> float:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if len(clean) <= 1:
        return 0.0
    vol = float(clean.std(ddof=1) * np.sqrt(float(periods_per_year)))
    if vol <= 1e-12:
        return 0.0
    cagr = _annualized_cagr(clean, periods_per_year)
    return float((cagr - float(rf_annual)) / vol)


def _max_drawdown(returns: pd.Series) -> float:
    clean = pd.to_numeric(returns, errors="coerce").fillna(0.0)
    if clean.empty:
        return 0.0
    equity = (1.0 + clean).cumprod()
    peak = equity.cummax()
    dd = (equity / peak) - 1.0
    return float(dd.min()) if not dd.empty else 0.0


def _build_features_and_signals(
    *,
    bars: pd.DataFrame,
    symbol: str,
    strategy_kind: str,
    strategy_params: dict[str, Any],
    indicator_engine: IndicatorEngine,
) -> tuple[FeaturesData, SignalFrame]:
    md = MarketData(
        bars={symbol: bars},
        source="decision_policy_backtest",
        timezone="GMT",
        interval="1d",
    )
    strategy = build_strategy(strategy_kind, strategy_params)
    specs = list(strategy.required_features() or [])
    if specs:
        feats = indicator_engine.compute(md, specs=specs, symbols=[symbol])
    else:
        feats = FeaturesData(
            features={symbol: pd.DataFrame(index=bars.index)},
            source=md.source,
            timezone=md.timezone,
            interval=md.interval,
            meta={"specs": [], "engine_version": "decision_policy"},
        )
    signals = strategy.generate_signals(md, feats, symbols=[symbol])
    return feats, signals


def _safe_signal_at_end(signal_frame: SignalFrame, symbol: str) -> int:
    s = signal_frame.signals.get(symbol)
    if s is None or s.empty:
        return 0
    v = pd.to_numeric(s, errors="coerce").fillna(0.0).iloc[-1]
    if float(v) > 0.0:
        return 1
    if float(v) < 0.0:
        return -1
    return 0


def _make_fill(
    *,
    ts: pd.Timestamp,
    symbol: str,
    qty_signed: int,
    price: float,
    cost: float,
    breakdown: dict[str, float],
    pos_before: int,
    pos_after: int,
    avg_entry_before: float,
    avg_entry_after: float,
    realized_pnl: float,
    realized_return: float,
) -> Fill:
    qty_abs = max(1, int(abs(qty_signed)))
    if qty_signed > 0:
        net_price = float(price + (cost / float(qty_abs)))
    else:
        net_price = float(price - (cost / float(qty_abs)))
    return Fill(
        timestamp=pd.Timestamp(ts),
        symbol=str(symbol),
        qty=int(qty_signed),
        price=float(price),
        notional=float(abs(int(qty_signed) * float(price))),
        cost=float(cost),
        cost_breakdown=dict(breakdown or {}),
        pos_before=int(pos_before),
        pos_after=int(pos_after),
        avg_entry_price_before=float(avg_entry_before),
        avg_entry_price_after=float(avg_entry_after),
        net_price=float(net_price),
        realized_pnl=float(realized_pnl),
        realized_return=float(realized_return),
    )


def _trade_calibration_table(
    trades_df: pd.DataFrame,
    *,
    score_col: str,
) -> pd.DataFrame:
    cols = [
        "decile",
        "n_trades",
        "hit_rate_target_first",
        "avg_r_multiple",
        "avg_pnl_pct",
        "win_rate",
    ]
    if trades_df is None or trades_df.empty or score_col not in trades_df.columns:
        return pd.DataFrame(columns=cols)

    frame = trades_df.copy()
    frame[score_col] = pd.to_numeric(frame[score_col], errors="coerce")
    frame["r_multiple"] = pd.to_numeric(frame.get("r_multiple"), errors="coerce")
    frame["pnl_pct"] = pd.to_numeric(frame.get("pnl_pct"), errors="coerce")
    frame["target_first"] = frame.get("exit_reason", "").astype(str).str.lower().eq("target_hit")
    frame["win"] = frame.get("outcome", "").astype(str).str.lower().eq("win")
    frame = frame.dropna(subset=[score_col])
    if frame.empty:
        return pd.DataFrame(columns=cols)

    n = len(frame)
    q = min(10, n)
    ranked = frame[score_col].rank(method="first")
    frame["decile"] = pd.qcut(ranked, q=q, labels=False, duplicates="drop") + 1

    grouped = (
        frame.groupby("decile", dropna=True)
        .agg(
            n_trades=(score_col, "count"),
            hit_rate_target_first=("target_first", "mean"),
            avg_r_multiple=("r_multiple", "mean"),
            avg_pnl_pct=("pnl_pct", "mean"),
            win_rate=("win", "mean"),
        )
        .reset_index()
        .sort_values("decile")
    )
    grouped["decile"] = grouped["decile"].astype(int)
    return grouped[cols]


def _make_r_distribution_plot(trades_df: pd.DataFrame) -> dict[str, Any]:
    fig = go.Figure()
    if trades_df is not None and not trades_df.empty and "r_multiple" in trades_df.columns:
        r = pd.to_numeric(trades_df["r_multiple"], errors="coerce").dropna()
        if not r.empty:
            fig.add_trace(
                go.Histogram(
                    x=r.values,
                    nbinsx=min(30, max(10, int(np.sqrt(len(r))))),
                    name="R-multiple",
                    marker=dict(color="#2563eb", line=dict(color="#1e3a8a", width=1)),
                    opacity=0.85,
                )
            )
    fig.update_layout(
        title="Trade R-Multiple Distribution",
        template="plotly_white",
        font=dict(family="Arial", size=12),
        margin=dict(l=40, r=20, t=60, b=40),
        bargap=0.05,
    )
    fig.update_xaxes(title_text="R-multiple")
    fig.update_yaxes(title_text="Count")
    return fig.to_plotly_json()


def _make_calibration_plot(table: pd.DataFrame, *, title: str) -> dict[str, Any]:
    fig = go.Figure()
    if table is not None and not table.empty:
        x = table["decile"].astype(str)
        fig.add_trace(
            go.Bar(
                x=x,
                y=table["n_trades"],
                name="N trades",
                marker=dict(color="#94a3b8"),
                opacity=0.6,
                yaxis="y2",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=x,
                y=table["hit_rate_target_first"],
                name="Hit-rate (target before stop)",
                mode="lines+markers",
                line=dict(color="#16a34a", width=2),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=x,
                y=table["avg_r_multiple"],
                name="Avg R",
                mode="lines+markers",
                line=dict(color="#dc2626", width=2, dash="dot"),
            )
        )
    fig.update_layout(
        title=title,
        template="plotly_white",
        font=dict(family="Arial", size=12),
        margin=dict(l=40, r=40, t=60, b=40),
        legend=dict(orientation="h"),
        yaxis2=dict(title="N trades", overlaying="y", side="right", showgrid=False),
    )
    fig.update_xaxes(title_text="Score decile")
    fig.update_yaxes(title_text="Rate / Avg R")
    return fig.to_plotly_json()


def simulate_decision_policy(
    *,
    bars: pd.DataFrame,
    strategy_name: str,
    params: dict[str, Any],
    test_start: Any,
    test_end: Any,
    warmup_bars: int = 250,
    execution: ExecutionMode = "next_open",
    decision_asof: DecisionAsOfMode = "close_t",
    op_threshold: float = 70.0,
    conf_threshold: float = 60.0,
    max_holding_days: int = 20,
    top_k_decisions: int | None = None,
    cost_model: CostModel | None = None,
    cost_bps: float | None = None,
    slippage_bps: float | None = None,
    initial_cash: float = 100_000.0,
    allow_short: bool = True,
    symbol: str = "__ALL__",
    periods_per_year: int = 252,
    rf_annual: float = 0.0,
    stop_target_precedence: Literal["stop_first", "target_first"] = "stop_first",
    _decision_page_override: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> BacktestBundle:
    del top_k_decisions  # reserved for future multi-strategy extensions

    bars_all = _coerce_bars(bars)
    if bars_all.empty:
        raise ValueError("Decision policy backtest requires non-empty OHLCV bars.")

    start_ts = _as_timestamp(test_start)
    end_ts = _as_timestamp(test_end)
    if start_ts > end_ts:
        raise ValueError("test_start must be <= test_end.")
    if execution not in {"next_open", "next_close"}:
        raise ValueError("execution must be one of: next_open, next_close.")
    if decision_asof not in {"close_t", "close_t-1"}:
        raise ValueError("decision_asof must be one of: close_t, close_t-1.")
    if max_holding_days <= 0:
        raise ValueError("max_holding_days must be positive.")

    if cost_model is None:
        brokerage = float(cost_bps) if cost_bps is not None else 0.2
        slip = float(slippage_bps) if slippage_bps is not None else 0.0
        cost_model = CostModel(brokerage_bps=brokerage, slippage_bps=slip)

    strategy_kind = str(strategy_name).strip().lower()
    strategy_params = dict(params or {})
    if not allow_short:
        strategy_params["allow_short"] = False

    indicator_engine = IndicatorEngine(
        cache_dir=None,
        enable_disk_cache=False,
        enable_memory_cache=False,
        engine_version="decision_policy_v1",
    )

    cash = float(initial_cash)
    position_qty = 0
    fills: list[Fill] = []
    closed_trades: list[dict[str, Any]] = []
    equity_points: list[tuple[pd.Timestamp, float]] = []
    positions_hist: list[tuple[pd.Timestamp, dict[str, int]]] = []
    open_trade: _OpenTrade | None = None
    pending_entry: dict[str, Any] | None = None
    decision_trace: list[dict[str, Any]] = []

    idx = bars_all.index
    start_ts = _align_boundary_to_index_tz(idx, pd.Timestamp(start_ts))
    end_ts = _align_boundary_to_index_tz(idx, pd.Timestamp(end_ts))
    test_mask = (idx >= start_ts) & (idx <= end_ts)
    test_i = np.where(test_mask)[0]
    if len(test_i) == 0:
        raise ValueError("No bars found inside the requested test_start/test_end window.")
    test_i_set = set(int(v) for v in test_i.tolist())

    def _apply_cash_fill(qty_signed: int, px: float, fee: float) -> None:
        nonlocal cash
        notional = abs(float(qty_signed) * float(px))
        if qty_signed > 0:
            cash -= notional + float(fee)
        else:
            cash += notional - float(fee)

    def _close_open_trade(i: int, exit_px: float, reason: str) -> None:
        nonlocal open_trade, position_qty
        if open_trade is None:
            return
        ts = pd.Timestamp(idx[i])
        qty_signed = -int(open_trade.qty_signed)
        notional = abs(float(qty_signed) * float(exit_px))
        exit_cost, exit_breakdown = cost_model.estimate_cost(notional)
        _apply_cash_fill(qty_signed, exit_px, exit_cost)

        qty_abs = int(open_trade.qty_abs)
        gross = (
            (float(exit_px) - float(open_trade.entry_price)) * float(qty_abs)
            if open_trade.direction > 0
            else (float(open_trade.entry_price) - float(exit_px)) * float(qty_abs)
        )
        net = float(gross - open_trade.entry_cost - exit_cost)
        denom = abs(float(open_trade.entry_price) * float(qty_abs))
        pnl_pct = float(net / denom) if denom > 0 else 0.0
        risk_notional = float(open_trade.risk_per_share) * float(qty_abs)
        r_multiple = float(net / risk_notional) if risk_notional > 0 else np.nan
        hold_days = int(max(1, i - open_trade.entry_idx + 1))
        outcome = "win" if net > 0 else "loss" if net < 0 else "flat"

        fill = _make_fill(
            ts=ts,
            symbol=symbol,
            qty_signed=qty_signed,
            price=float(exit_px),
            cost=float(exit_cost),
            breakdown=exit_breakdown,
            pos_before=int(position_qty),
            pos_after=0,
            avg_entry_before=float(open_trade.entry_price),
            avg_entry_after=0.0,
            realized_pnl=float(net),
            realized_return=float(pnl_pct),
        )
        fills.append(fill)
        position_qty = 0

        closed_trades.append(
            {
                "symbol": symbol,
                "entry_time": open_trade.entry_ts,
                "entry_date": open_trade.entry_ts,
                "entry_price": float(open_trade.entry_price),
                "entry_px": float(open_trade.entry_price),
                "exit_time": ts,
                "exit_date": ts,
                "exit_price": float(exit_px),
                "exit_px": float(exit_px),
                "side": "LONG" if open_trade.direction > 0 else "SHORT",
                "direction": "long" if open_trade.direction > 0 else "short",
                "qty": int(qty_abs),
                "gross_pnl": float(gross),
                "net_pnl": float(net),
                "pnl": float(net),
                "return_pct": float(pnl_pct),
                "pnl_pct": float(pnl_pct),
                "r_multiple": float(r_multiple) if np.isfinite(r_multiple) else np.nan,
                "outcome": outcome,
                "exit_reason": str(reason),
                "stop": float(open_trade.stop),
                "target": float(open_trade.target),
                "hold_days": hold_days,
                "opportunity_score": float(open_trade.opportunity_score),
                "confidence_score": float(open_trade.confidence_score),
                "target_before_stop": bool(str(reason).lower() == "target_hit"),
            }
        )
        open_trade = None

    for i, ts in enumerate(idx):
        bar = bars_all.iloc[i]

        if pending_entry is not None and int(pending_entry["exec_i"]) == i and execution == "next_open" and open_trade is None:
            entry_px = float(bar["Open"])
            direction = int(pending_entry["direction"])
            qty_abs = max(1, int(cash / max(entry_px, 1e-12)))
            qty_signed = int(qty_abs if direction > 0 else -qty_abs)
            notional = abs(float(qty_signed) * entry_px)
            entry_cost, entry_breakdown = cost_model.estimate_cost(notional)
            _apply_cash_fill(qty_signed, entry_px, entry_cost)
            fill = _make_fill(
                ts=ts,
                symbol=symbol,
                qty_signed=qty_signed,
                price=entry_px,
                cost=entry_cost,
                breakdown=entry_breakdown,
                pos_before=0,
                pos_after=qty_signed,
                avg_entry_before=0.0,
                avg_entry_after=entry_px,
                realized_pnl=0.0,
                realized_return=0.0,
            )
            fills.append(fill)
            position_qty = qty_signed
            open_trade = _OpenTrade(
                direction=direction,
                qty_abs=qty_abs,
                qty_signed=qty_signed,
                entry_idx=i,
                monitor_start_idx=i,
                entry_ts=pd.Timestamp(ts),
                entry_price=entry_px,
                entry_cost=float(entry_cost),
                stop=float(pending_entry["stop"]),
                target=float(pending_entry["target"]),
                opportunity_score=float(pending_entry["opportunity_score"]),
                confidence_score=float(pending_entry["confidence_score"]),
                decision_date=pd.Timestamp(pending_entry["decision_date"]),
                risk_per_share=float(abs(entry_px - float(pending_entry["stop"]))),
            )
            pending_entry = None

        if open_trade is not None and i >= open_trade.monitor_start_idx:
            high = float(bar["High"])
            low = float(bar["Low"])
            stop_hit = False
            target_hit = False
            if open_trade.direction > 0:
                stop_hit = low <= open_trade.stop
                target_hit = high >= open_trade.target
            else:
                stop_hit = high >= open_trade.stop
                target_hit = low <= open_trade.target

            if stop_hit and target_hit:
                if stop_target_precedence == "target_first":
                    _close_open_trade(i, float(open_trade.target), "target_hit")
                else:
                    _close_open_trade(i, float(open_trade.stop), "stop_hit")
            elif stop_hit:
                _close_open_trade(i, float(open_trade.stop), "stop_hit")
            elif target_hit:
                _close_open_trade(i, float(open_trade.target), "target_hit")
            elif (i - open_trade.entry_idx + 1) >= int(max_holding_days):
                _close_open_trade(i, float(bar["Close"]), "max_holding_days")

        if pending_entry is not None and int(pending_entry["exec_i"]) == i and execution == "next_close" and open_trade is None:
            entry_px = float(bar["Close"])
            direction = int(pending_entry["direction"])
            qty_abs = max(1, int(cash / max(entry_px, 1e-12)))
            qty_signed = int(qty_abs if direction > 0 else -qty_abs)
            notional = abs(float(qty_signed) * entry_px)
            entry_cost, entry_breakdown = cost_model.estimate_cost(notional)
            _apply_cash_fill(qty_signed, entry_px, entry_cost)
            fill = _make_fill(
                ts=ts,
                symbol=symbol,
                qty_signed=qty_signed,
                price=entry_px,
                cost=entry_cost,
                breakdown=entry_breakdown,
                pos_before=0,
                pos_after=qty_signed,
                avg_entry_before=0.0,
                avg_entry_after=entry_px,
                realized_pnl=0.0,
                realized_return=0.0,
            )
            fills.append(fill)
            position_qty = qty_signed
            open_trade = _OpenTrade(
                direction=direction,
                qty_abs=qty_abs,
                qty_signed=qty_signed,
                entry_idx=i,
                monitor_start_idx=i + 1,
                entry_ts=pd.Timestamp(ts),
                entry_price=entry_px,
                entry_cost=float(entry_cost),
                stop=float(pending_entry["stop"]),
                target=float(pending_entry["target"]),
                opportunity_score=float(pending_entry["opportunity_score"]),
                confidence_score=float(pending_entry["confidence_score"]),
                decision_date=pd.Timestamp(pending_entry["decision_date"]),
                risk_per_share=float(abs(entry_px - float(pending_entry["stop"]))),
            )
            pending_entry = None

        close_px = float(bar["Close"])
        equity = float(cash + float(position_qty) * close_px)
        equity_points.append((pd.Timestamp(ts), equity))
        positions_hist.append((pd.Timestamp(ts), {symbol: int(position_qty)}))

        if i not in test_i_set or i >= (len(idx) - 1):
            continue

        asof_i = i if decision_asof == "close_t" else i - 1
        if asof_i < 0 or asof_i < (int(warmup_bars) - 1):
            continue
        if open_trade is not None or pending_entry is not None:
            continue

        bars_slice = bars_all.iloc[: asof_i + 1].copy()
        feats_slice, signals_slice = _build_features_and_signals(
            bars=bars_slice,
            symbol=symbol,
            strategy_kind=strategy_kind,
            strategy_params=strategy_params,
            indicator_engine=indicator_engine,
        )
        signal_dir = _safe_signal_at_end(signals_slice, symbol)
        if (not allow_short) and signal_dir < 0:
            signal_dir = 0

        levels = compute_levels_support_resistance(bars_slice, direction=int(signal_dir))
        risk_payload = compute_rr_and_invalidation(
            direction=int(signal_dir),
            entry=float(levels.get("entry")) if levels.get("entry") is not None else None,
            stop=float(levels.get("stop")) if levels.get("stop") is not None else None,
            target=float(levels.get("target")) if levels.get("target") is not None else None,
        )
        opportunity = compute_opportunity_score(
            bars=bars_slice,
            strategy_direction=int(signal_dir),
            strategy_kind=strategy_kind,
            levels_payload=levels,
        )

        signal_series = pd.to_numeric(signals_slice.signals.get(symbol), errors="coerce").fillna(0.0)
        close_series = pd.to_numeric(bars_slice["Close"], errors="coerce")
        ret_series = close_series.pct_change().fillna(0.0)
        strat_rets = (ret_series * signal_series.shift(1).fillna(0.0)).dropna()
        perf_row = {
            "strategy_kind": strategy_kind,
            "best_params_json": {f"strategy.{k}": v for k, v in strategy_params.items()},
            "cagr": _annualized_cagr(strat_rets, periods_per_year),
            "sharpe": _sharpe(strat_rets, periods_per_year, rf_annual),
            "max_drawdown": _max_drawdown(strat_rets),
            "n_fills": int((signal_series.diff().fillna(0.0) != 0.0).sum()),
            "efficiency": 0.0,
        }
        seed_key = f"{symbol}:{strategy_kind}:{pd.Timestamp(idx[asof_i]).date().isoformat()}"
        confidence = compute_confidence_score(
            row=perf_row,
            same_strategy_rows=[perf_row],
            trade_ledger=closed_trades,
            returns=[float(v) for v in strat_rets.tail(252).tolist()],
            mc_paths=64,
            random_seed=deterministic_seed_from_key(seed_key),
        )

        as_of_date = pd.Timestamp(idx[asof_i]).date().isoformat()
        page = build_decision_page(
            symbol=symbol,
            strategy_kind=strategy_kind,
            trial_id=f"decision_{i}",
            strategy_direction=int(signal_dir),
            levels=levels,
            risk_payload=risk_payload,
            opportunity=opportunity,
            confidence=confidence,
            extra_explain={"source": "decision_policy_backtest"},
            as_of_date=as_of_date,
        ).model_dump(mode="json")

        if callable(_decision_page_override):
            override_payload = _decision_page_override(
                {
                    "decision_index": int(i),
                    "decision_date": pd.Timestamp(ts),
                    "as_of_date": pd.Timestamp(idx[asof_i]),
                    "bars_slice": bars_slice,
                    "direction": int(signal_dir),
                    "levels": levels,
                    "risk_payload": risk_payload,
                    "opportunity": opportunity,
                    "confidence": confidence,
                    "page": page,
                }
            )
            if isinstance(override_payload, dict):
                page = dict(override_payload)
        else:
            # Make trade/watch status respect configured thresholds in this simulation mode.
            opp_score_base = float(page.get("opportunity_score") or 0.0)
            conf_score_base = float(page.get("confidence_score") or 0.0)
            rr_now = float(risk_payload.get("rr") or 0.0)
            levels_valid = bool(risk_payload.get("levels_valid", True))
            if signal_dir == 0 or (not levels_valid):
                page["status"] = "no_trade"
            elif (
                opp_score_base >= float(op_threshold)
                and conf_score_base >= float(conf_threshold)
                and rr_now >= 1.0
            ):
                page["status"] = "trade"
            elif (
                opp_score_base >= max(45.0, float(op_threshold) * 0.7)
                and conf_score_base >= max(40.0, float(conf_threshold) * 0.7)
                and rr_now >= 0.8
            ):
                page["status"] = "watch"
            else:
                page["status"] = "no_trade"

        status = str(page.get("status") or "no_trade")
        opp_score = float(page.get("opportunity_score") or 0.0)
        conf_score = float(page.get("confidence_score") or 0.0)
        decision_trace.append(
            {
                "decision_date": pd.Timestamp(ts),
                "as_of_date": pd.Timestamp(idx[asof_i]),
                "slice_end_date": pd.Timestamp(bars_slice.index[-1]),
                "status": status,
                "opportunity_score": opp_score,
                "confidence_score": conf_score,
                "direction": signal_dir,
            }
        )

        eligible = (
            status == "trade"
            and opp_score >= float(op_threshold)
            and conf_score >= float(conf_threshold)
            and signal_dir != 0
            and (i + 1) < len(idx)
        )
        if not eligible:
            continue

        pending_entry = {
            "exec_i": int(i + 1),
            "decision_date": pd.Timestamp(ts),
            "direction": int(signal_dir),
            "stop": float(page.get("levels", {}).get("stop")) if page.get("levels") else float(levels.get("stop")),
            "target": float(page.get("levels", {}).get("target")) if page.get("levels") else float(levels.get("target")),
            "opportunity_score": opp_score,
            "confidence_score": conf_score,
        }

    if open_trade is not None:
        final_i = len(idx) - 1
        final_px = float(bars_all.iloc[final_i]["Close"])
        _close_open_trade(final_i, final_px, "end_of_data")
        last_equity = float(cash + float(position_qty) * final_px)
        if equity_points:
            equity_points[-1] = (equity_points[-1][0], last_equity)

    fills_df = PortfolioEngine._fills_to_df(fills)
    positions_df = PortfolioEngine._positions_history_to_df(positions_hist, [symbol])
    equity_series = pd.Series(
        [float(v) for _, v in equity_points],
        index=pd.DatetimeIndex([ts for ts, _ in equity_points], name="timestamp"),
        dtype="float64",
    )
    returns_series = equity_series.pct_change().fillna(0.0).astype(float)

    portfolio_result = PortfolioResult(
        equity_curve=equity_series,
        returns=returns_series,
        positions=positions_df,
        trades=fills_df,
        meta={"config": {"initial_cash": float(initial_cash), "strategy_kind": strategy_kind}},
    )

    feats_full, signals_full = _build_features_and_signals(
        bars=bars_all,
        symbol=symbol,
        strategy_kind=strategy_kind,
        strategy_params=strategy_params,
        indicator_engine=indicator_engine,
    )
    md_full = MarketData(
        bars={symbol: bars_all},
        source="decision_policy_backtest",
        timezone="GMT",
        interval="1d",
    )

    analyzer = ResultsAnalyzer(periods_per_year=periods_per_year, rf_annual=rf_annual)
    report = analyzer.analyze(
        portfolio_result,
        market_data=md_full,
        symbols=[symbol],
        features_data=feats_full,
        plot_indicators=default_plot_indicators(strategy_kind, strategy_params),
        benchmark_market_data=None,
        benchmark_symbol=None,
    )

    trades_df = pd.DataFrame(closed_trades)
    opportunity_cal = _trade_calibration_table(trades_df, score_col="opportunity_score")
    confidence_cal = _trade_calibration_table(trades_df, score_col="confidence_score")

    report.tables["trades"] = trades_df
    report.tables["trade_ledger"] = trades_df
    report.tables["opportunity_calibration"] = opportunity_cal
    report.tables["confidence_calibration"] = confidence_cal

    total_gross = float(pd.to_numeric(trades_df.get("gross_pnl"), errors="coerce").sum()) if not trades_df.empty else 0.0
    total_net = float(pd.to_numeric(trades_df.get("net_pnl"), errors="coerce").sum()) if not trades_df.empty else 0.0
    turnover = float(pd.to_numeric(fills_df.get("notional"), errors="coerce").fillna(0.0).sum())
    exposure = float((positions_df[symbol] != 0).mean()) if (not positions_df.empty and symbol in positions_df.columns) else 0.0
    net_return = float((equity_series.iloc[-1] / equity_series.iloc[0]) - 1.0) if len(equity_series) > 1 else 0.0
    gross_return = float(total_gross / float(initial_cash)) if float(initial_cash) > 0 else 0.0

    report.metrics["Gross PnL"] = float(total_gross)
    report.metrics["Net PnL"] = float(total_net)
    report.metrics["Gross return"] = float(gross_return)
    report.metrics["Net return"] = float(net_return)
    report.metrics["Turnover"] = float(turnover)
    report.metrics["Exposure"] = float(exposure)
    report.metrics["Trades"] = float(len(trades_df))

    summary_plot_artifacts = {
        "trade_r_distribution": _make_r_distribution_plot(trades_df),
        "opportunity_calibration": _make_calibration_plot(opportunity_cal, title="Opportunity Score Calibration"),
        "confidence_calibration": _make_calibration_plot(confidence_cal, title="Confidence Score Calibration"),
        "drawdown": make_drawdown_plot(report.series.get("drawdown")).to_plotly_json(),
    }

    decision_stats = {
        "op_threshold": float(op_threshold),
        "conf_threshold": float(conf_threshold),
        "execution": execution,
        "decision_asof": decision_asof,
        "max_holding_days": int(max_holding_days),
        "n_decisions": int(len(decision_trace)),
        "n_trades": int(len(trades_df)),
    }

    return BacktestBundle(
        md=md_full,
        feats=feats_full,
        signals=signals_full,
        portfolio_result=portfolio_result,
        report=report,
        meta={
            "summary_plot_artifacts": summary_plot_artifacts,
            "decision_stats": decision_stats,
            "decision_trace": decision_trace,
        },
    )
