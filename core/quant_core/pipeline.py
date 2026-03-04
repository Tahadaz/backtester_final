# core/quant_core/pipeline.py
from __future__ import annotations
from dataclasses import replace
from typing import Any, Dict, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import logging
import os
import time
import numpy as np
import pandas as pd

_pipeline_logger = logging.getLogger(__name__)
from .engine import BacktestEngine, DataConfig, IndicatorsConfig, StrategyConfig, EngineSpec
from .research.horizon import get_horizon_config
from .optimize import (
    OptimizeConfig,
    OptimizeTiming,
    ParamDef,
    batch_optimize_by_period,
    build_spec_from_result_row,
    default_param_catalog,
    run_optimization,
)
from .portfolio import CostModel, PortfolioConfig
from .run_spec import build_run_spec
from .decision import simulate_decision_policy

from .plots import (
    make_batch_period_heatmap_plot,
    make_cumreturn_vs_benchmark_plot,
    make_drawdown_plot,
    make_monthly_heatmap_plot,
    make_yearly_return_bar_plot,
    plot_price_indicators_trades_line,
)


_WF_UNIT_ALIASES: dict[str, str] = {
    "d": "days",
    "day": "days",
    "days": "days",
    "w": "weeks",
    "week": "weeks",
    "weeks": "weeks",
    "m": "months",
    "month": "months",
    "months": "months",
    "y": "years",
    "yr": "years",
    "year": "years",
    "years": "years",
}

_WF_HORIZON_ORDER: tuple[str, ...] = ("short", "medium", "long")


def _normalize_walk_forward_unit(raw: Any, *, field_name: str) -> str:
    unit = _WF_UNIT_ALIASES.get(str(raw or "").strip().lower())
    if unit is None:
        raise ValueError(f"{field_name} must be one of: days, weeks, months, years.")
    return unit


def _coerce_positive_int(raw: Any, *, field_name: str) -> int:
    try:
        out = int(raw)
    except Exception as exc:
        raise ValueError(f"{field_name} must be a positive integer.") from exc
    if out <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return out


def _shift_timestamp(ts: pd.Timestamp, *, value: int, unit: str) -> pd.Timestamp:
    if unit == "days":
        return ts + pd.Timedelta(days=value)
    if unit == "weeks":
        return ts + pd.Timedelta(weeks=value)
    if unit == "months":
        return ts + pd.DateOffset(months=value)
    if unit == "years":
        return ts + pd.DateOffset(years=value)
    raise ValueError(f"Unsupported walk-forward unit: {unit}")


def build_walk_forward_period_entries(
    *,
    start: str,
    end: str,
    train_value: int,
    train_unit: str,
    test_value: int,
    test_unit: str,
    step_value: int,
    step_unit: str,
    anchored: bool,
    max_folds: int | None = None,
) -> list[dict[str, str]]:
    start_ts = pd.to_datetime(start, errors="coerce")
    end_ts = pd.to_datetime(end, errors="coerce")
    if pd.isna(start_ts) or pd.isna(end_ts):
        raise ValueError("Walk-forward requires valid data.start and data.end dates.")

    start_ts = pd.Timestamp(start_ts).normalize()
    end_ts = pd.Timestamp(end_ts).normalize()
    if start_ts >= end_ts:
        raise ValueError("Walk-forward requires data.start < data.end.")

    first_test_start = _shift_timestamp(start_ts, value=int(train_value), unit=str(train_unit))
    if first_test_start > end_ts:
        raise ValueError("Walk-forward train duration is too long for the selected date range.")

    one_day = pd.Timedelta(days=1)
    test_start = first_test_start
    rows: list[dict[str, str]] = []
    fold_idx = 0

    while test_start <= end_ts:
        if max_folds is not None and fold_idx >= max_folds:
            break

        train_start_ts = (
            start_ts
            if anchored
            else _shift_timestamp(test_start, value=-int(train_value), unit=str(train_unit))
        )
        if train_start_ts < start_ts:
            train_start_ts = start_ts

        train_end_ts = test_start - one_day
        if train_end_ts < train_start_ts:
            break

        test_end_candidate = _shift_timestamp(test_start, value=int(test_value), unit=str(test_unit)) - one_day
        test_end_ts = min(test_end_candidate, end_ts)
        if test_end_ts < test_start:
            break

        rows.append(
            {
                "label": f"Fold {fold_idx + 1}",
                "start": test_start.date().isoformat(),
                "end": test_end_ts.date().isoformat(),
                "train_start": train_start_ts.date().isoformat(),
                "train_end": train_end_ts.date().isoformat(),
                "test_start": test_start.date().isoformat(),
                "test_end": test_end_ts.date().isoformat(),
            }
        )

        fold_idx += 1
        test_start = _shift_timestamp(test_start, value=int(step_value), unit=str(step_unit))

    if not rows:
        raise ValueError("Walk-forward generated zero folds. Adjust train/test/step durations or date range.")
    return rows


def run_pipeline(spec_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Canonical pipeline entry point.

    Returns a dict with:
      - leaderboard: list[dict]
      - plot_artifacts: Dict[str, Any]
      - strategy_results: Dict[str, Any] (per-strategy trade_ledger + plot_artifacts + best params)
      - decision_support: Dict[str, Any] (canonical decision inputs + optional walk-forward OOS context)
      - metrics: Dict[str, Any]
      - fills: list[dict]
      - position_ledger: list[dict]
      - artifacts: Dict[str, Any] (run metadata, best params by kind)
    """
    data_json = spec_json.get("data", {})
    portfolio_json = spec_json.get("portfolio", {})
    strategy_json = spec_json.get("strategy", {})
    indicators_json = spec_json.get("indicators", {})
    optimization_json = spec_json.get("optimization", {})
    decision_json = dict(spec_json.get("decision_backtest") or {})

    def _norm_windows(v: Any) -> list[Tuple[str, str]] | None:
        if not v:
            return None
        return [(str(a), str(b)) for a, b in v]

    include_windows = _norm_windows(data_json.get("include_windows"))
    exclude_windows = _norm_windows(data_json.get("exclude_windows"))
    symbols = list(spec_json.get("symbols") or data_json.get("symbols") or [])

    data_cfg = DataConfig(
        source=str(spec_json.get("source_key") or data_json.get("source") or "yfinance"),
        symbols=symbols,
        timezone=str(data_json.get("timezone", "GMT")),
        interval=str(data_json.get("interval", "1d")),
        start=data_json.get("start"),
        end=data_json.get("end"),
        periods=(int(data_json["periods"]) if data_json.get("periods") is not None else None),
        freq=str(data_json.get("freq", "B")),
        include_windows=include_windows,
        exclude_windows=exclude_windows,
        bmce_paths=data_json.get("bmce_paths"),
        yf_period=str(data_json.get("yf_period", "max")),
        yf_interval=str(data_json.get("yf_interval", "1d")),
        yf_auto_adjust=bool(data_json.get("yf_auto_adjust", False)),
        synthetic=dict(data_json.get("synthetic") or {}),
        parquet_paths=data_json.get("parquet_paths"),
    )

    indicators_cfg = IndicatorsConfig(
        specs=indicators_json.get("specs"),
        cache_dir=indicators_json.get("cache_dir", ".cache/features"),
        enable_disk_cache=bool(indicators_json.get("enable_disk_cache", True)),
        enable_memory_cache=bool(indicators_json.get("enable_memory_cache", True)),
        engine_version=str(indicators_json.get("engine_version", "v1")),
    )

    strategy_cfg = StrategyConfig(
        kind=str(strategy_json.get("kind", "buy_hold")),
        params=dict(strategy_json.get("params") or {}),
    )

    cost_model_cfg = CostModel(
        brokerage_bps=float(portfolio_json.get("cost_model", {}).get("brokerage_bps", 0.2)),
        comm_bourse_bps=float(portfolio_json.get("cost_model", {}).get("comm_bourse_bps", 0.1)),
        reg_liv_bps=float(portfolio_json.get("cost_model", {}).get("reg_liv_bps", 0.0)),
        slippage_bps=float(portfolio_json.get("cost_model", {}).get("slippage_bps", 0.0)),
        tva_rate=float(portfolio_json.get("cost_model", {}).get("tva_rate", 0.000300000142168438)),
    )

    portfolio_cfg = PortfolioConfig(
        allow_short=bool(portfolio_json.get("allow_short", True)),
        initial_cash=float(portfolio_json.get("initial_cash", 100000.0)),
        rebalance_policy=str(portfolio_json.get("rebalance_policy", "on_change")),
        sizing_mode=str(portfolio_json.get("sizing_mode", "target_weight")),
        buy_pct_cash=float(portfolio_json.get("buy_pct_cash", 1.0)),
        sell_pct_shares=float(portfolio_json.get("sell_pct_shares", 1.0)),
        cooldown_bars=int(portfolio_json.get("cooldown_bars", 0)),
        min_return_before_sell=float(portfolio_json.get("min_return_before_sell", 0.0)),
        use_volume_gate=bool(portfolio_json.get("volume_gate", {}).get("enabled", portfolio_json.get("use_volume_gate", False))),
        volume_gate_kind=str(portfolio_json.get("volume_gate", {}).get("kind", portfolio_json.get("volume_gate_kind", "min_ratio_adv"))),
        min_volume_abs=float(portfolio_json.get("volume_gate", {}).get("min_volume_abs", portfolio_json.get("min_volume_abs", 0.0))),
        min_volume_ratio_adv=float(portfolio_json.get("volume_gate", {}).get("min_volume_ratio_adv", portfolio_json.get("min_volume_ratio_adv", 0.1))),
        volume_gate_adv_window=int(portfolio_json.get("volume_gate", {}).get("adv_window", portfolio_json.get("volume_gate_adv_window", 20))),
        use_participation_cap=bool(portfolio_json.get("participation_cap", {}).get("enabled", portfolio_json.get("use_participation_cap", False))),
        participation_rate=float(portfolio_json.get("participation_cap", {}).get("rate", portfolio_json.get("participation_rate", 0.05))),
        participation_basis=str(portfolio_json.get("participation_cap", {}).get("basis", portfolio_json.get("participation_basis", "adv"))),
        adv_window=int(portfolio_json.get("participation_cap", {}).get("adv_window", portfolio_json.get("adv_window", 20))),
        cost_model=cost_model_cfg,
    )

    engine_spec = EngineSpec(
        data=data_cfg,
        indicators=indicators_cfg,
        strategy=strategy_cfg,
        portfolio=portfolio_cfg,
        periods_per_year=int(spec_json.get("periods_per_year", 252)),
        rf_annual=float(spec_json.get("rf_annual", 0.0)),
        include_windows=include_windows,
        exclude_windows=exclude_windows,
    )

    run_spec = spec_json if "optimization" in spec_json and "portfolio" in spec_json and "data" in spec_json else build_run_spec(
        source_key=str(spec_json.get("source_key", data_cfg.source)),
        symbols=symbols,
        start=data_cfg.start,
        end=data_cfg.end,
        include_windows=include_windows,
        exclude_windows=exclude_windows,
        interval=data_cfg.interval,
        yf_period=data_cfg.yf_period,
        yf_interval=data_cfg.yf_interval,
        yf_auto_adjust=data_cfg.yf_auto_adjust,
        rank_metric=str(optimization_json.get("rank_metric", "sharpe")),
        lb_opt_kinds=list(optimization_json.get("kinds") or []),
        opt_method=str(optimization_json.get("method", "random")),
        n_trials=int(optimization_json.get("n_trials", 0)),
        top_k=int(optimization_json.get("top_k", 1)),
        allow_short=portfolio_cfg.allow_short,
        initial_cash=portfolio_cfg.initial_cash,
        cooldown_bars=portfolio_cfg.cooldown_bars,
        min_return_before_sell=portfolio_cfg.min_return_before_sell,
        cost_model=portfolio_json.get("cost_model", {}),
        volume_gate=portfolio_json.get("volume_gate", {}),
        participation_cap=portfolio_json.get("participation_cap", {}),
        domains_by_kind=dict(optimization_json.get("domains_by_kind") or {}),
        app_version=str(spec_json.get("app_version", "v1")),
    )

    def _params_from_catalog(kind: str) -> list[ParamDef]:
        catalog = default_param_catalog(kind)
        domains_by_kind = dict(optimization_json.get("domains_by_kind") or {})
        custom = domains_by_kind.get(kind)

        if not custom:
            return [p for p in catalog.values() if p.enabled]

        if isinstance(custom, dict):
            keys = []
            for key, dom in custom.items():
                if key in catalog:
                    p = catalog[key]
                    catalog[key] = ParamDef(key=p.key, kind=p.kind, domain=dom, cast=p.cast, enabled=True)
                    keys.append(key)
            return [catalog[k] for k in keys if k in catalog]

        if isinstance(custom, list):
            out: list[ParamDef] = []
            for item in custom:
                if isinstance(item, str):
                    p = catalog.get(item)
                    if p is not None and p.enabled:
                        out.append(p)
                elif isinstance(item, dict):
                    k = item.get("key")
                    if not k:
                        continue
                    base = catalog.get(k)
                    if base is None:
                        continue
                    out.append(
                        ParamDef(
                            key=str(k),
                            kind=str(item.get("kind", base.kind)),
                            domain=item.get("domain", base.domain),
                            cast=base.cast,
                            enabled=bool(item.get("enabled", True)),
                        )
                    )
            return [p for p in out if p.enabled]

        return [p for p in catalog.values() if p.enabled]

    def _best_params_from_spec(spec: EngineSpec) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in dict(spec.strategy.params or {}).items():
            out[f"strategy.{key}"] = value
        for key in (
            "cooldown_bars",
            "buy_pct_cash",
            "sell_pct_shares",
            "min_return_before_sell",
        ):
            out[f"portfolio.{key}"] = getattr(spec.portfolio, key)
        out["portfolio.volume_gate.enabled"] = bool(spec.portfolio.use_volume_gate)
        out["portfolio.volume_gate.kind"] = str(spec.portfolio.volume_gate_kind)
        out["portfolio.volume_gate.min_volume_abs"] = float(spec.portfolio.min_volume_abs)
        out["portfolio.volume_gate.min_volume_ratio_adv"] = float(spec.portfolio.min_volume_ratio_adv)
        out["portfolio.volume_gate.adv_window"] = int(spec.portfolio.volume_gate_adv_window)
        out["portfolio.participation_cap.enabled"] = bool(spec.portfolio.use_participation_cap)
        out["portfolio.participation_cap.rate"] = float(spec.portfolio.participation_rate)
        out["portfolio.participation_cap.basis"] = str(spec.portfolio.participation_basis)
        out["portfolio.participation_cap.adv_window"] = int(spec.portfolio.adv_window)
        return out

    def _best_params_from_lb_row(row: pd.Series) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in dict(row.to_dict()).items():
            if not isinstance(key, str):
                continue
            if key.startswith("strategy.") or key.startswith("portfolio.") or key == "data.window":
                out[key] = value
        return out

    def _best_params_from_any_row(row: pd.Series | dict[str, Any]) -> dict[str, Any]:
        src = row.to_dict() if isinstance(row, pd.Series) else dict(row)
        out: dict[str, Any] = {}
        for key, value in src.items():
            if not isinstance(key, str):
                continue
            if key.startswith("param.strategy.") or key.startswith("param.portfolio.") or key == "param.data.window":
                out[key[len("param."):]] = value
                continue
            if key.startswith("strategy.") or key.startswith("portfolio.") or key == "data.window":
                out[key] = value
        return out

    def _metric_from_report(metrics: dict[str, Any], objective: str) -> float | None:
        if not metrics:
            return None
        folded = {str(k).strip().lower(): v for k, v in metrics.items()}
        objective_key = str(objective).strip().lower()
        key_options = {
            "pnl": ["net pnl", "pnl"],
            "cagr": ["cagr"],
            "total_return": ["total return", "total_return"],
            "sharpe": ["sharpe", "sharpe ratio"],
            "max_drawdown": ["max drawdown", "max_drawdown"],
            "win_pct": ["win rate", "trade winning %"],
            "efficiency": ["efficiency"],
            "n_fills": ["trades", "n_fills", "fills"],
        }.get(objective_key, [objective_key])
        for key in key_options:
            if key not in folded:
                continue
            try:
                value = float(folded[key])
                if pd.notna(value):
                    return value
            except Exception:
                continue
        return None

    def _normalize_batch_period_entries(raw: Any) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        source: list[Any] = []

        if isinstance(raw, dict):
            for label, item in raw.items():
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    source.append({"label": label, "start": item[0], "end": item[1]})
                elif isinstance(item, dict):
                    source.append(
                        {
                            "label": item.get("label", label),
                            "start": item.get("start"),
                            "end": item.get("end"),
                        }
                    )
        elif isinstance(raw, list):
            source = list(raw)

        for i, item in enumerate(source):
            if isinstance(item, dict):
                label = str(item.get("label") or item.get("name") or f"Period {i + 1}").strip()
                start = item.get("start")
                end = item.get("end")
            elif isinstance(item, (list, tuple)) and len(item) >= 3:
                label = str(item[0]).strip()
                start = item[1]
                end = item[2]
            else:
                continue

            if not label or start is None or end is None:
                continue
            rows.append({"label": label, "start": str(start), "end": str(end)})

        used: dict[str, int] = {}
        out: list[dict[str, str]] = []
        for row in rows:
            label = row["label"]
            count = used.get(label, 0)
            used[label] = count + 1
            if count > 0:
                label = f"{label} ({count + 1})"
            out.append({"label": label, "start": row["start"], "end": row["end"]})
        return out

    plots_json = dict(spec_json.get("plots") or {})
    plot_kinds = {str(k).strip().lower() for k in (plots_json.get("kinds") or [])}

    def _plot_enabled(plot_kind: str) -> bool:
        return bool(plots_json.get("enabled", False)) and str(plot_kind).lower() in plot_kinds

    def _normalize_record_frame(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        for c in out.columns:
            if pd.api.types.is_datetime64_any_dtype(out[c]) or pd.api.types.is_datetime64tz_dtype(out[c]):
                out[c] = pd.to_datetime(out[c], utc=True, errors="coerce").dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                out[c] = out[c].str.replace(".000000Z", "Z", regex=False)
        # Cast to object first so None survives in numeric columns (instead of bouncing back to NaN).
        out = out.astype(object).where(pd.notna(out), None)
        return out

    def _df_to_records(df: pd.DataFrame | None, *, ensure_timestamp: bool = True) -> list[dict[str, Any]]:
        if df is None:
            return []

        out = df.copy()
        if ensure_timestamp and "timestamp" not in out.columns:
            if "signal_date" in out.columns:
                out["timestamp"] = out["signal_date"]
            else:
                out["timestamp"] = out.index

        if ensure_timestamp:
            out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
            if out["timestamp"].isna().all() and len(out) > 0:
                out["timestamp"] = pd.Timestamp.now(tz="UTC")

        out = _normalize_record_frame(out)
        return out.to_dict("records")

    def _table_to_records(df: pd.DataFrame | None) -> list[dict[str, Any]]:
        if df is None:
            return []
        out = _normalize_record_frame(df.copy())
        return out.to_dict("records")

    def _table_to_metric_records(df: pd.DataFrame | None) -> list[dict[str, Any]]:
        if df is None:
            return []
        out = df.copy()
        if out.empty:
            return []
        if out.index.name:
            out = out.reset_index().rename(columns={out.index.name: "metric"})
        else:
            out = out.reset_index().rename(columns={"index": "metric"})
        out = out.rename(columns={"Value": "value", "value": "value", "metric_name": "metric"})
        if "metric" not in out.columns and len(out.columns) > 0:
            out = out.rename(columns={out.columns[0]: "metric"})
        if "value" not in out.columns and len(out.columns) > 1:
            out = out.rename(columns={out.columns[1]: "value"})
        cols = [c for c in ("metric", "value") if c in out.columns]
        if not cols:
            return []
        out = _normalize_record_frame(out[cols])
        return out.to_dict("records")

    def _normalize_trade_ledger_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not rows:
            return []

        alias_map: dict[str, tuple[str, ...]] = {
            "side": ("trade_side", "direction"),
            "prix_execution_open_jour": ("price", "prix_execution_open_du_jour"),
            "quantite": ("qty", "quantity"),
            "pnl_realise": ("pnl_realized", "pnl_realised"),
            "close_du_jour": ("mark_price", "_mark"),
            "cost": ("fees",),
        }

        out_rows: list[dict[str, Any]] = []
        for row in rows:
            normalized = dict(row or {})
            for canonical, aliases in alias_map.items():
                if canonical in normalized and normalized.get(canonical) is not None:
                    continue
                for alias in aliases:
                    if alias in normalized and normalized.get(alias) is not None:
                        normalized[canonical] = normalized.get(alias)
                        break

            # Keep UI "notional" populated when presentation rows only expose qty/price aliases.
            if normalized.get("notional") is None:
                try:
                    qty = normalized.get("quantite")
                    px = normalized.get("prix_execution_open_jour")
                    if qty is not None and px is not None:
                        normalized["notional"] = abs(float(qty)) * float(px)
                except Exception:
                    pass
            out_rows.append(normalized)
        return out_rows

    def _safe_metrics(metrics: dict[str, Any] | None) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in dict(metrics or {}).items():
            if isinstance(v, (int, float)):
                out[str(k)] = float(v)
            else:
                try:
                    vv = float(v)
                    out[str(k)] = vv
                except Exception:
                    out[str(k)] = v
        return out

    def _returns_summary(returns: pd.Series | None) -> dict[str, float | int]:
        r = pd.to_numeric(returns, errors="coerce").dropna() if isinstance(returns, pd.Series) else pd.Series(dtype=float)
        if r.empty:
            return {
                "n_obs": 0,
                "total_return": 0.0,
                "cagr": 0.0,
                "sharpe": 0.0,
                "max_drawdown": 0.0,
            }
        total_return = float((1.0 + r).prod() - 1.0)
        n = len(r)
        cagr = float(((1.0 + total_return) ** (252.0 / max(n, 1))) - 1.0) if (1.0 + total_return) > 0 else -1.0
        std = float(r.std(ddof=1)) if n > 1 else 0.0
        sharpe = float((r.mean() / std) * (252.0 ** 0.5)) if std > 1e-12 else 0.0
        equity = (1.0 + r).cumprod()
        peak = equity.cummax()
        dd = (equity / peak) - 1.0
        return {
            "n_obs": int(n),
            "total_return": total_return,
            "cagr": cagr,
            "sharpe": sharpe,
            "max_drawdown": float(dd.min()) if not dd.empty else 0.0,
        }

    def _signal_snapshot_from_bundle(bundle: Any, *, preferred_symbol: str | None = None) -> dict[str, Any]:
        signals_obj = getattr(bundle, "signals", None)
        signals_df = getattr(signals_obj, "signals", None)
        validity_df = getattr(signals_obj, "validity", None)
        if not isinstance(signals_df, pd.DataFrame) or signals_df.empty:
            return {"signal_today": 0.0, "signal_label": "HOLD", "signal_date": None}

        symbol = str(preferred_symbol or "").strip()
        if not symbol or symbol not in signals_df.columns:
            symbol = str(signals_df.columns[0]) if len(signals_df.columns) > 0 else ""
        if not symbol or symbol not in signals_df.columns:
            return {"signal_today": 0.0, "signal_label": "HOLD", "signal_date": None}

        signal_series = pd.to_numeric(signals_df[symbol], errors="coerce")
        if signal_series.dropna().empty:
            return {"signal_today": 0.0, "signal_label": "HOLD", "signal_date": None}

        valid_mask = pd.Series(True, index=signal_series.index)
        if isinstance(validity_df, pd.DataFrame) and symbol in validity_df.columns:
            valid_mask = validity_df[symbol].astype(bool).reindex(signal_series.index).fillna(False)
        signal_series = signal_series.where(valid_mask, np.nan)
        signal_series = signal_series.dropna()
        if signal_series.empty:
            return {"signal_today": 0.0, "signal_label": "HOLD", "signal_date": None}

        signal_value = float(signal_series.iloc[-1])
        signal_date = pd.to_datetime(signal_series.index[-1], errors="coerce")
        if signal_value > 0:
            signal_label = "BUY"
        elif signal_value < 0:
            signal_label = "SELL"
        else:
            signal_label = "HOLD"
        return {
            "signal_today": signal_value,
            "signal_label": signal_label,
            "signal_date": (pd.Timestamp(signal_date) if pd.notna(signal_date) else None),
        }

    def _build_decision_inputs(bundle: Any) -> dict[str, Any]:
        symbols_payload: dict[str, Any] = {}
        bars_map = getattr(bundle.md, "bars", {}) or {}
        feats_map = getattr(bundle.feats, "features", {}) or {}
        signals_df = getattr(getattr(bundle, "signals", None), "signals", None)

        for sym, bars in bars_map.items():
            if not isinstance(bars, pd.DataFrame) or bars.empty:
                continue
            cols = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in bars.columns]
            bars_tail = bars[cols].tail(320) if cols else bars.tail(320)
            bars_records = _df_to_records(bars_tail)

            feats = feats_map.get(sym)
            if isinstance(feats, pd.DataFrame) and not feats.empty:
                feats_tail = feats.tail(320)
                if len(feats_tail.columns) > 40:
                    feats_tail = feats_tail.iloc[:, :40]
                feat_records = _df_to_records(feats_tail)
            else:
                feat_records = []

            signal_records: list[dict[str, Any]] = []
            if isinstance(signals_df, pd.DataFrame) and sym in signals_df.columns:
                sig = pd.DataFrame({"signal": signals_df[sym]}).tail(320)
                signal_records = _df_to_records(sig)

            symbols_payload[str(sym)] = {
                "bars": bars_records,
                "features": feat_records,
                "signals": signal_records,
            }

        report_series = dict(getattr(bundle.report, "series", None) or {})
        returns_series = report_series.get("returns")
        returns_records: list[dict[str, Any]] = []
        if isinstance(returns_series, pd.Series):
            returns_df = pd.DataFrame({"return": returns_series}).tail(320)
            returns_records = _df_to_records(returns_df)

        return {
            "symbols": symbols_payload,
            "returns": returns_records,
        }

    def _build_plot_inputs(bundle: Any) -> Dict[str, Any]:
        if not bool(plots_json.get("enabled", False)):
            return {"symbols": {}}

        kinds = set(str(k) for k in (plots_json.get("kinds") or []))
        if "price_indicators_trades" not in kinds:
            return {"symbols": {}}

        selected = set(str(s) for s in (plots_json.get("symbols") or []))
        out_symbols: Dict[str, Any] = {}

        all_trades = bundle.portfolio_result.trades if isinstance(bundle.portfolio_result.trades, pd.DataFrame) else pd.DataFrame()

        def _trades_for_symbol(df: pd.DataFrame, sym: str) -> pd.DataFrame:
            if not isinstance(df, pd.DataFrame) or df.empty:
                return pd.DataFrame()
            if "symbol" not in df.columns:
                return df.copy()

            sym_key = str(sym).strip().upper()
            series = df["symbol"].astype(str).str.strip().str.upper()
            matched = df[series == sym_key].copy()

            # Fallback for legacy/inconsistent symbol formatting:
            # compare alphanumeric-only keys (e.g., "MASI.CS" vs "MASICS").
            if matched.empty:
                def _norm(s: str) -> str:
                    return "".join(ch for ch in str(s).upper() if ch.isalnum())
                norm_sym = _norm(sym_key)
                norm_series = series.map(_norm)
                matched = df[norm_series == norm_sym].copy()
                if matched.empty and norm_sym:
                    fuzzy = norm_series.map(lambda v: bool(v) and (v.startswith(norm_sym) or norm_sym.startswith(v)))
                    matched = df[fuzzy].copy()

            # If still no match and fills only contain one symbol, keep all rows.
            if matched.empty and len(set(series.tolist())) <= 1:
                return df.copy()
            return matched

        for sym, bars in bundle.md.bars.items():
            if selected and sym not in selected:
                continue
            pp = dict(bundle.report.plots.get("price_panel") or {})
            ind_df = pp.get("indicators")
            if isinstance(ind_df, pd.DataFrame) and sym in bundle.feats.features:
                ind_df = bundle.feats.features[sym]
            elif sym in bundle.feats.features:
                ind_df = bundle.feats.features[sym]

            trades_df = pp.get("trades")
            if isinstance(all_trades, pd.DataFrame) and not all_trades.empty and "symbol" in all_trades.columns:
                trades_df = _trades_for_symbol(all_trades, sym)
                if isinstance(trades_df, pd.DataFrame) and trades_df.empty and isinstance(pp.get("trades"), pd.DataFrame):
                    # Defensive fallback to report payload if raw fill symbol matching fails.
                    trades_df = pp.get("trades")

            out_symbols[sym] = {
                "bars": _df_to_records(bars.reset_index()),
                "indicators": _df_to_records(ind_df.reset_index()) if isinstance(ind_df, pd.DataFrame) else [],
                "trades": _df_to_records(trades_df.reset_index()) if isinstance(trades_df, pd.DataFrame) else _df_to_records(bundle.portfolio_result.trades),
            }

        return {"symbols": out_symbols}

    def _build_plot_artifacts(
        bundle: Any,
        *,
        strategy_params: dict[str, Any] | None = None,
        port_cfg: PortfolioConfig | None = None,
    ) -> Dict[str, Any]:
        if not bool(plots_json.get("enabled", False)):
            return {"symbols": {}}
        if not bool(plots_json.get("return_plot_artifacts", False)):
            return {"symbols": {}}
        kinds = set(str(k) for k in (plots_json.get("kinds") or []))
        if "price_indicators_trades" not in kinds:
            return {"symbols": {}}

        selected = set(str(s) for s in (plots_json.get("symbols") or []))
        out_symbols: Dict[str, Any] = {}
        all_trades = bundle.portfolio_result.trades if isinstance(bundle.portfolio_result.trades, pd.DataFrame) else pd.DataFrame()

        def _trades_for_symbol(df: pd.DataFrame, sym: str) -> pd.DataFrame:
            if not isinstance(df, pd.DataFrame) or df.empty:
                return pd.DataFrame()
            if "symbol" not in df.columns:
                return df.copy()

            sym_key = str(sym).strip().upper()
            series = df["symbol"].astype(str).str.strip().str.upper()
            matched = df[series == sym_key].copy()

            # Fallback for legacy/inconsistent symbol formatting:
            # compare alphanumeric-only keys (e.g., "MASI.CS" vs "MASICS").
            if matched.empty:
                def _norm(s: str) -> str:
                    return "".join(ch for ch in str(s).upper() if ch.isalnum())
                norm_sym = _norm(sym_key)
                norm_series = series.map(_norm)
                matched = df[norm_series == norm_sym].copy()
                if matched.empty and norm_sym:
                    fuzzy = norm_series.map(lambda v: bool(v) and (v.startswith(norm_sym) or norm_sym.startswith(v)))
                    matched = df[fuzzy].copy()

            # If still no match and fills only contain one symbol, keep all rows.
            if matched.empty and len(set(series.tolist())) <= 1:
                return df.copy()
            return matched

        for sym, bars in bundle.md.bars.items():
            if selected and sym not in selected:
                continue
            pp = dict(bundle.report.plots.get("price_panel") or {})
            ind_df = pp.get("indicators")
            if isinstance(ind_df, pd.DataFrame) and sym in bundle.feats.features:
                ind_df = bundle.feats.features[sym]
            elif sym in bundle.feats.features:
                ind_df = bundle.feats.features[sym]

            trades_df = pp.get("trades")
            if isinstance(all_trades, pd.DataFrame) and not all_trades.empty and "symbol" in all_trades.columns:
                trades_df = _trades_for_symbol(all_trades, sym)
                if isinstance(trades_df, pd.DataFrame) and trades_df.empty and isinstance(pp.get("trades"), pd.DataFrame):
                    # Defensive fallback to report payload if raw fill symbol matching fails.
                    trades_df = pp.get("trades")
            try:
                fig = plot_price_indicators_trades_line(
                    bars=bars,
                    strategy_params=dict(strategy_params or {}),
                    indicators=ind_df if isinstance(ind_df, pd.DataFrame) else None,
                    trades=trades_df if isinstance(trades_df, pd.DataFrame) else bundle.portfolio_result.trades,
                    indicator_cols=list(ind_df.columns) if isinstance(ind_df, pd.DataFrame) else None,
                    port_cfg=port_cfg,
                )
                out_symbols[sym] = fig.to_plotly_json()
            except Exception:
                _pipeline_logger.warning(
                    "plot_price_indicators_trades_line failed for symbol %s", sym, exc_info=True
                )
                # Do NOT store empty dict — frontend treats {} as a broken figure.
        return {"symbols": out_symbols}

    def _build_summary_plot_artifacts(bundle: Any) -> dict[str, Any]:
        if not bool(plots_json.get("enabled", False)):
            return {}
        if not bool(plots_json.get("return_plot_artifacts", False)):
            return {}

        report_plots = dict(getattr(bundle.report, "plots", None) or {})
        out: dict[str, Any] = {}

        try:
            if _plot_enabled("drawdown"):
                dd = report_plots.get("drawdown")
                if isinstance(dd, pd.Series):
                    out["drawdown"] = make_drawdown_plot(dd).to_plotly_json()
        except Exception:
            pass

        try:
            if _plot_enabled("cumreturn_vs_benchmark") or _plot_enabled("cum_vs_bench"):
                cvb = dict(report_plots.get("cum_vs_bench") or {})
                strat = cvb.get("strategy")
                bench = cvb.get("benchmark")
                if isinstance(strat, pd.Series):
                    out["cumreturn_vs_benchmark"] = make_cumreturn_vs_benchmark_plot(strat, bench if isinstance(bench, pd.Series) else None).to_plotly_json()
        except Exception:
            pass

        try:
            if _plot_enabled("monthly_heatmap"):
                monthly = report_plots.get("monthly_heatmap")
                if isinstance(monthly, pd.DataFrame):
                    out["monthly_heatmap"] = make_monthly_heatmap_plot(monthly).to_plotly_json()
        except Exception:
            pass

        try:
            if _plot_enabled("yearly_return_barplot") or _plot_enabled("yearly_bar"):
                yearly = report_plots.get("yearly_bar")
                if isinstance(yearly, (pd.Series, pd.DataFrame)):
                    out["yearly_return_barplot"] = make_yearly_return_bar_plot(yearly).to_plotly_json()
        except Exception:
            pass

        extra_summary = dict((getattr(bundle, "meta", None) or {}).get("summary_plot_artifacts") or {})
        for name_raw, fig_json in extra_summary.items():
            safe_name = str(name_raw).strip().lower().replace(" ", "_")
            if not safe_name:
                continue
            if not _plot_enabled(safe_name):
                continue
            if isinstance(fig_json, dict) and fig_json:
                out[safe_name] = fig_json

        return out

    def _bundle_to_strategy_result(
        kind: str,
        bundle: Any,
        best_params: dict[str, Any],
        *,
        strategy_params: dict[str, Any] | None = None,
        port_cfg: PortfolioConfig | None = None,
    ) -> dict[str, Any]:
        report_tables = dict(getattr(bundle.report, "tables", None) or {})
        symbols_in_bundle = [str(s) for s in list(getattr(bundle.md, "bars", {}).keys())]
        decision_stats = dict((getattr(bundle, "meta", None) or {}).get("decision_stats") or {})
        per_fill_trade_ledger = _normalize_trade_ledger_records(
            _table_to_records(report_tables.get("trades"))
        )
        fifo_trade_ledger = _table_to_records(report_tables.get("trade_ledger"))
        return {
            "strategy_kind": kind,
            "best_strategy_params": dict(best_params or {}),
            "symbols": symbols_in_bundle,
            "metrics": _safe_metrics(getattr(bundle.report, "metrics", None) or {}),
            # Canonical UI ledger is the per-fill accounting table from results._prepare_trades_table.
            "trade_ledger": per_fill_trade_ledger,
            # Keep FIFO round-trips available for downstream consumers.
            "fifo_trade_ledger": fifo_trade_ledger,
            "trade_performance": _table_to_metric_records(report_tables.get("trade_performance")),
            "opportunity_calibration": _table_to_records(report_tables.get("opportunity_calibration")),
            "confidence_calibration": _table_to_records(report_tables.get("confidence_calibration")),
            "decision_stats": _safe_metrics(decision_stats),
            "plot_artifacts": dict(
                (
                    _build_plot_artifacts(
                        bundle,
                        strategy_params=strategy_params,
                        port_cfg=port_cfg,
                    )
                    or {}
                ).get("symbols")
                or {}
            ),
            "summary_plot_artifacts": _build_summary_plot_artifacts(bundle),
            "decision_inputs": _build_decision_inputs(bundle),
        }

    def _runtime_payload(bundle: Any) -> dict[str, Any]:
        report_tables = dict(getattr(bundle.report, "tables", None) or {})
        raw_fills = bundle.portfolio_result.trades if isinstance(bundle.portfolio_result.trades, pd.DataFrame) else None
        return {
            "metrics": _safe_metrics(getattr(bundle.report, "metrics", None) or {}),
            "fills": _table_to_records(raw_fills),
            "position_ledger": _table_to_records(report_tables.get("trades")),
        }

    def _build_decision_support(
        strategy_results_payload: dict[str, Any],
        *,
        walk_forward_rows: list[dict[str, Any]] | None = None,
        walk_forward_oos_summary_by_kind: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        inputs_by_kind: dict[str, Any] = {}
        for kind_raw, payload_any in dict(strategy_results_payload or {}).items():
            kind = str(kind_raw).strip().lower()
            if not kind:
                continue
            payload = payload_any if isinstance(payload_any, dict) else {}
            decision_inputs = payload.get("decision_inputs")
            if not isinstance(decision_inputs, dict):
                decision_inputs = {"symbols": {}, "returns": []}
            trade_ledger = payload.get("trade_ledger")
            inputs_by_kind[kind] = {
                "symbols": [str(s) for s in list(payload.get("symbols") or []) if str(s).strip()],
                "decision_inputs": decision_inputs,
                "trade_ledger": [r for r in list(trade_ledger or []) if isinstance(r, dict)],
            }

        return {
            "schema_version": 1,
            "inputs_by_kind": inputs_by_kind,
            "walk_forward_rows": [r for r in list(walk_forward_rows or []) if isinstance(r, dict)],
            "walk_forward_oos_summary_by_kind": dict(walk_forward_oos_summary_by_kind or {}),
        }

    decision_enabled = bool(decision_json.get("enabled", False))
    if decision_enabled:
        if len(symbols) != 1:
            raise ValueError("Decision Backtest currently supports exactly one symbol.")

        kind = str(strategy_cfg.kind).strip().lower()
        decision_symbol = str(symbols[0]).strip()

        preload_bundle = BacktestEngine(engine_spec).run()
        bars_by_symbol = getattr(preload_bundle.md, "bars", {}) or {}
        bars_for_symbol = bars_by_symbol.get(decision_symbol)
        if not isinstance(bars_for_symbol, pd.DataFrame) or bars_for_symbol.empty:
            raise ValueError(f"No bars available for symbol '{decision_symbol}'.")

        thresholds_json = dict(decision_json.get("thresholds") or {})
        decision_start = (
            decision_json.get("test_start")
            or data_cfg.start
            or str(pd.Timestamp(bars_for_symbol.index.min()).date())
        )
        decision_end = (
            decision_json.get("test_end")
            or data_cfg.end
            or str(pd.Timestamp(bars_for_symbol.index.max()).date())
        )

        execution_mode = str(decision_json.get("execution", "next_open")).strip().lower() or "next_open"
        decision_asof_mode = str(decision_json.get("decision_asof", "close_t")).strip().lower() or "close_t"
        stop_target_precedence = str(
            decision_json.get("stop_target_precedence", "stop_first")
        ).strip().lower() or "stop_first"

        decision_bundle = simulate_decision_policy(
            bars=bars_for_symbol,
            strategy_name=kind,
            params=dict(strategy_cfg.params or {}),
            test_start=decision_start,
            test_end=decision_end,
            warmup_bars=int(decision_json.get("warmup_bars", 250)),
            execution=execution_mode,  # type: ignore[arg-type]
            decision_asof=decision_asof_mode,  # type: ignore[arg-type]
            op_threshold=float(thresholds_json.get("op_threshold", decision_json.get("op_threshold", 70.0))),
            conf_threshold=float(thresholds_json.get("conf_threshold", decision_json.get("conf_threshold", 60.0))),
            max_holding_days=int(decision_json.get("max_holding_days", 20)),
            top_k_decisions=(
                int(decision_json.get("top_k_decisions"))
                if decision_json.get("top_k_decisions") is not None
                else None
            ),
            cost_model=portfolio_cfg.cost_model,
            initial_cash=portfolio_cfg.initial_cash,
            allow_short=portfolio_cfg.allow_short,
            symbol=decision_symbol,
            periods_per_year=int(engine_spec.periods_per_year),
            rf_annual=float(engine_spec.rf_annual),
            stop_target_precedence=stop_target_precedence,  # type: ignore[arg-type]
        )

        strategy_results = {
            kind: _bundle_to_strategy_result(
                kind,
                decision_bundle,
                _best_params_from_spec(engine_spec),
                strategy_params=dict(engine_spec.strategy.params or {}),
                port_cfg=engine_spec.portfolio,
            )
        }
        decision_stats = dict((getattr(decision_bundle, "meta", None) or {}).get("decision_stats") or {})
        return {
            "leaderboard": [],
            "plot_artifacts": _build_plot_artifacts(
                decision_bundle,
                strategy_params=dict(engine_spec.strategy.params or {}),
                port_cfg=engine_spec.portfolio,
            ),
            "strategy_results": strategy_results,
            "decision_support": _build_decision_support(strategy_results),
            **_runtime_payload(decision_bundle),
            "artifacts": {
                "run_spec": run_spec,
                "primary_kind": kind,
                "optimized_kinds": [kind],
                "best_strategy_params_by_kind": {kind: _best_params_from_spec(engine_spec)},
                "decision_backtest": {
                    "enabled": True,
                    "symbol": decision_symbol,
                    "test_start": str(decision_start),
                    "test_end": str(decision_end),
                    "strategy_kind": kind,
                    **decision_stats,
                },
            },
        }

    walk_forward_json = dict(optimization_json.get("walk_forward") or {})
    walk_forward_enabled = bool(walk_forward_json.get("enabled", False))

    opt_method = str(optimization_json.get("method", "random"))
    n_trials = int(optimization_json.get("n_trials", 0))
    top_k = int(optimization_json.get("top_k", 1))
    opt_kinds = list(optimization_json.get("kinds") or [])
    run_opt = bool(n_trials > 0 or opt_kinds or walk_forward_enabled)

    if not run_opt:
        bundle = BacktestEngine(engine_spec).run()
        strategy_results = {
            str(strategy_cfg.kind): _bundle_to_strategy_result(
                str(strategy_cfg.kind),
                bundle,
                _best_params_from_spec(engine_spec),
                strategy_params=dict(engine_spec.strategy.params or {}),
                port_cfg=engine_spec.portfolio,
            )
        }
        return {
            "leaderboard": [],
            "plot_artifacts": _build_plot_artifacts(
                bundle,
                strategy_params=dict(engine_spec.strategy.params or {}),
                port_cfg=engine_spec.portfolio,
            ),
            "strategy_results": strategy_results,
            "decision_support": _build_decision_support(strategy_results),
            **_runtime_payload(bundle),
            "artifacts": {
                "run_spec": run_spec,
                "primary_kind": str(strategy_cfg.kind),
                "optimized_kinds": [str(strategy_cfg.kind)],
                "best_strategy_params_by_kind": {str(strategy_cfg.kind): _best_params_from_spec(engine_spec)},
            },
        }

    if not opt_kinds:
        opt_kinds = [engine_spec.strategy.kind]

    _analysis_cfg = dict(spec_json.get("analysis") or {})
    _profile_cfg = dict(_analysis_cfg.get("profile") or {})
    _profiling_enabled = bool(_profile_cfg.get("enabled", False))

    opt_cfg = OptimizeConfig(
        method=opt_method,
        seed=int(optimization_json.get("seed", 42)),
        n_trials=n_trials if opt_method.lower() == "random" else 0,
        top_k=top_k,
        feature_cache_dir=str(indicators_cfg.cache_dir or ".cache/features"),
        enable_disk_cache=bool(optimization_json.get("enable_disk_cache", True)),
        enable_memory_cache=bool(optimization_json.get("enable_memory_cache", True)),
        profiling_enabled=_profiling_enabled,
    )

    symbol_label = symbols[0] if len(symbols) == 1 else "__ALL__"

    def _safe_float_scalar(raw: Any) -> float | None:
        try:
            out = float(raw)
            return out if pd.notna(out) else None
        except Exception:
            return None

    def _safe_int_scalar(raw: Any) -> int | None:
        try:
            out = int(raw)
            return out
        except Exception:
            return None

    def _normalize_requested_horizons(raw: Any) -> list[str]:
        source = list(raw) if isinstance(raw, (list, tuple, set)) else list(_WF_HORIZON_ORDER)
        out: list[str] = []
        for item in source:
            token = str(item or "").strip().lower()
            if token in _WF_HORIZON_ORDER and token not in out:
                out.append(token)
        return out or list(_WF_HORIZON_ORDER)

    walk_forward_multi_horizon = bool(walk_forward_json.get("multi_horizon", False))
    if walk_forward_enabled and walk_forward_multi_horizon:
        requested_horizons = _normalize_requested_horizons(walk_forward_json.get("horizons"))
        primary_horizon = str(walk_forward_json.get("horizon") or "medium").strip().lower() or "medium"
        if primary_horizon not in requested_horizons:
            primary_horizon = requested_horizons[0]

        wf_horizon_overrides_raw = walk_forward_json.get("horizon_overrides")
        wf_horizon_overrides = (
            dict(wf_horizon_overrides_raw)
            if isinstance(wf_horizon_overrides_raw, dict)
            else None
        )

        per_horizon_outputs: dict[str, dict[str, Any]] = {}
        _mh_perf: dict[str, Any] = {}
        for horizon in requested_horizons:
            horizon_spec = copy.deepcopy(spec_json)
            horizon_opt = dict(horizon_spec.get("optimization") or {})
            horizon_wf = dict(horizon_opt.get("walk_forward") or {})
            horizon_cfg = get_horizon_config(horizon, overrides=wf_horizon_overrides)

            horizon_wf["enabled"] = True
            horizon_wf["multi_horizon"] = False
            horizon_wf["horizon"] = str(horizon_cfg.name.value)
            horizon_wf["train"] = {"value": int(horizon_cfg.train_window), "unit": "days"}
            horizon_wf["test"] = {"value": int(horizon_cfg.test_window), "unit": "days"}
            horizon_wf["step"] = {"value": int(horizon_cfg.step_size), "unit": "days"}
            horizon_wf["wf_train_len"] = int(horizon_cfg.train_window)
            horizon_wf["wf_test_len"] = int(horizon_cfg.test_window)
            horizon_wf["wf_step"] = int(horizon_cfg.step_size)
            horizon_opt["walk_forward"] = horizon_wf
            horizon_spec["optimization"] = horizon_opt

            _t_h = time.perf_counter()
            per_horizon_outputs[horizon] = run_pipeline(horizon_spec)
            _h_ms = round((time.perf_counter() - _t_h) * 1000.0, 2)
            _h_inner = dict(per_horizon_outputs[horizon].get("_perf") or {})
            _h_inner["horizon_ms"] = _h_ms
            _mh_perf[horizon] = _h_inner
            _pipeline_logger.info(
                "[perf] horizon=%s %.0f ms folds=%d",
                horizon, _h_ms, _h_inner.get("folds_count", 0),
            )

        primary_output = (
            per_horizon_outputs.get(primary_horizon)
            or per_horizon_outputs.get(requested_horizons[0])
            or {}
        )

        combined_leaderboard: list[dict[str, Any]] = []
        rows_by_horizon: dict[str, list[dict[str, Any]]] = {}

        for horizon_index, horizon in enumerate(requested_horizons):
            horizon_output = dict(per_horizon_outputs.get(horizon) or {})
            horizon_cfg = get_horizon_config(horizon, overrides=wf_horizon_overrides)
            batch_period = dict(horizon_output.get("batch_period") or {})
            objective_name = str(batch_period.get("objective") or "pnl").strip().lower() or "pnl"
            rows_raw = [
                dict(row)
                for row in list(batch_period.get("results") or [])
                if isinstance(row, dict)
            ]
            rows_raw.sort(
                key=lambda row: _safe_float_scalar(row.get("objective_value")) if _safe_float_scalar(row.get("objective_value")) is not None else float("-inf"),
                reverse=True,
            )

            best_row_by_kind: dict[str, dict[str, Any]] = {}
            for row in rows_raw:
                strategy_kind = str(row.get("strategy_kind") or "").strip().lower()
                if not strategy_kind or strategy_kind in best_row_by_kind:
                    continue
                best_row_by_kind[strategy_kind] = row

            ranked_rows = sorted(
                best_row_by_kind.values(),
                key=lambda row: _safe_float_scalar(row.get("objective_value")) if _safe_float_scalar(row.get("objective_value")) is not None else float("-inf"),
                reverse=True,
            )

            horizon_rows_for_ui: list[dict[str, Any]] = []
            for local_rank, row in enumerate(ranked_rows, start=1):
                strategy_kind = str(row.get("strategy_kind") or "").strip().lower()
                if not strategy_kind:
                    continue
                objective_value = _safe_float_scalar(row.get("objective_value"))
                storage_rank = horizon_index * 1000 + local_rank
                best_params_json = _best_params_from_any_row(row)
                best_params_json["walk_forward.horizon"] = horizon
                best_params_json["walk_forward.horizon_label"] = str(horizon_cfg.label)
                best_params_json["walk_forward.objective"] = objective_name
                best_params_json["walk_forward.objective_value"] = objective_value
                best_params_json["walk_forward.period"] = row.get("period")
                best_params_json["walk_forward.start"] = row.get("start")
                best_params_json["walk_forward.end"] = row.get("end")
                best_params_json["simple_wfo.horizon"] = horizon
                best_params_json["simple_wfo.horizon_label"] = str(horizon_cfg.label)
                best_params_json["simple_wfo.rank"] = int(local_rank)
                best_params_json["simple_wfo.storage_rank"] = int(storage_rank)

                combined_leaderboard.append(
                    {
                        "symbol": str(row.get("symbol") or symbol_label),
                        "strategy_kind": strategy_kind,
                        "rank": int(storage_rank),
                        "pnl": _safe_float_scalar(row.get("stat.pnl") if "stat.pnl" in row else row.get("pnl")),
                        "cagr": _safe_float_scalar(row.get("stat.cagr") if "stat.cagr" in row else row.get("cagr")),
                        "efficiency": _safe_float_scalar(row.get("stat.efficiency") if "stat.efficiency" in row else row.get("efficiency")),
                        "n_fills": _safe_int_scalar(row.get("stat.n_fills") if "stat.n_fills" in row else row.get("n_fills")),
                        "signal_today": 0.0,
                        "signal_label": "HOLD",
                        "signal_date": None,
                        "best_params_json": best_params_json,
                    }
                )

                horizon_rows_for_ui.append(
                    {
                        "strategy_kind": strategy_kind,
                        "rank": int(local_rank),
                        "objective": objective_name,
                        "objective_value": objective_value,
                        "pnl": _safe_float_scalar(row.get("stat.pnl") if "stat.pnl" in row else row.get("pnl")),
                        "cagr": _safe_float_scalar(row.get("stat.cagr") if "stat.cagr" in row else row.get("cagr")),
                        "period": row.get("period"),
                        "start": row.get("start"),
                        "end": row.get("end"),
                    }
                )

            rows_by_horizon[horizon] = horizon_rows_for_ui

        combined_leaderboard.sort(
            key=lambda row: (
                _safe_int_scalar(row.get("rank")) if _safe_int_scalar(row.get("rank")) is not None else 999999,
                str(row.get("strategy_kind") or ""),
            )
        )

        primary_strategy_results = dict(primary_output.get("strategy_results") or {})
        primary_decision_support = primary_output.get("decision_support")
        if not isinstance(primary_decision_support, dict):
            primary_decision_support = _build_decision_support(primary_strategy_results)

        primary_artifacts = dict(primary_output.get("artifacts") or {})
        primary_artifacts["simple_wfo_multi_horizon"] = {
            "enabled": True,
            "horizons": requested_horizons,
            "primary_horizon": primary_horizon,
            "rows_by_horizon": rows_by_horizon,
        }

        return {
            "leaderboard": combined_leaderboard,
            "plot_artifacts": dict(primary_output.get("plot_artifacts") or {}),
            "strategy_results": primary_strategy_results,
            "decision_support": primary_decision_support,
            "batch_period": dict(primary_output.get("batch_period") or {}),
            "simple_wfo_multi_horizon": {
                "enabled": True,
                "horizons": requested_horizons,
                "primary_horizon": primary_horizon,
                "rows_by_horizon": rows_by_horizon,
            },
            "metrics": dict(primary_output.get("metrics") or {}),
            "fills": [r for r in list(primary_output.get("fills") or []) if isinstance(r, dict)],
            "position_ledger": [r for r in list(primary_output.get("position_ledger") or []) if isinstance(r, dict)],
            "artifacts": primary_artifacts,
            "_perf": {
                "mode": "multi_horizon",
                "horizons": _mh_perf,
                "total_horizons": len(requested_horizons),
            },
        }

    batch_cfg = dict(optimization_json.get("batch_periods") or {})
    batch_enabled = bool(batch_cfg.get("enabled", False))
    batch_objective = str(batch_cfg.get("objective", "pnl")).strip().lower() or "pnl"
    batch_optimize_within_each = bool(batch_cfg.get("optimize_within_each", True))
    batch_period_entries = _normalize_batch_period_entries(batch_cfg.get("periods"))
    period_mode: str | None = None
    period_objective = batch_objective
    period_optimize_within_each = batch_optimize_within_each
    period_entries: list[dict[str, str]] = []
    walk_forward_meta: dict[str, Any] | None = None

    if walk_forward_enabled:
        wf_resolved_start = str(walk_forward_json.get("resolved_start_date") or data_cfg.start or "").strip()
        wf_resolved_end = str(walk_forward_json.get("resolved_end_date") or data_cfg.end or "").strip()
        if not wf_resolved_start or not wf_resolved_end:
            raise ValueError("Walk-forward requires resolved start/end dates in run config.")

        wf_horizon_overrides_raw = walk_forward_json.get("horizon_overrides")
        wf_horizon_overrides = (
            dict(wf_horizon_overrides_raw)
            if isinstance(wf_horizon_overrides_raw, dict)
            else None
        )
        wf_horizon_cfg = get_horizon_config(
            walk_forward_json.get("horizon"),
            overrides=wf_horizon_overrides,
        )

        wf_train = dict(walk_forward_json.get("train") or {})
        wf_test = dict(walk_forward_json.get("test") or {})
        wf_step = dict(walk_forward_json.get("step") or {})

        if wf_train.get("value") in (None, ""):
            wf_train["value"] = int(wf_horizon_cfg.train_window)
        if str(wf_train.get("unit") or "").strip() == "":
            wf_train["unit"] = "days"
        if wf_test.get("value") in (None, ""):
            wf_test["value"] = int(wf_horizon_cfg.test_window)
        if str(wf_test.get("unit") or "").strip() == "":
            wf_test["unit"] = "days"
        if wf_step.get("value") in (None, ""):
            wf_step["value"] = int(wf_horizon_cfg.step_size)
        if str(wf_step.get("unit") or "").strip() == "":
            wf_step["unit"] = "days"

        train_value = _coerce_positive_int(wf_train.get("value"), field_name="walk_forward.train.value")
        train_unit = _normalize_walk_forward_unit(
            wf_train.get("unit"),
            field_name="walk_forward.train.unit",
        )
        test_value = _coerce_positive_int(wf_test.get("value"), field_name="walk_forward.test.value")
        test_unit = _normalize_walk_forward_unit(
            wf_test.get("unit"),
            field_name="walk_forward.test.unit",
        )
        step_value = _coerce_positive_int(wf_step.get("value"), field_name="walk_forward.step.value")
        step_unit = _normalize_walk_forward_unit(
            wf_step.get("unit"),
            field_name="walk_forward.step.unit",
        )

        max_folds_raw = walk_forward_json.get("max_folds")
        max_folds: int | None
        if max_folds_raw in (None, "", 0, "0"):
            max_folds = None
        else:
            max_folds = _coerce_positive_int(max_folds_raw, field_name="walk_forward.max_folds")

        period_entries = build_walk_forward_period_entries(
            start=wf_resolved_start,
            end=wf_resolved_end,
            train_value=train_value,
            train_unit=train_unit,
            test_value=test_value,
            test_unit=test_unit,
            step_value=step_value,
            step_unit=step_unit,
            anchored=bool(walk_forward_json.get("anchored", False)),
            max_folds=max_folds,
        )
        period_mode = "walk_forward"
        period_objective = str(walk_forward_json.get("objective", "pnl")).strip().lower() or "pnl"
        period_optimize_within_each = True
        walk_forward_meta = {
            "enabled": True,
            "objective": period_objective,
            "anchored": bool(walk_forward_json.get("anchored", False)),
            "train": {"value": train_value, "unit": train_unit},
            "test": {"value": test_value, "unit": test_unit},
            "step": {"value": step_value, "unit": step_unit},
            "horizon": str(wf_horizon_cfg.name.value),
            "horizon_label": str(wf_horizon_cfg.label),
            "horizon_cfg": {
                "train_window": int(wf_horizon_cfg.train_window),
                "test_window": int(wf_horizon_cfg.test_window),
                "step_size": int(wf_horizon_cfg.step_size),
                "use_test_window": bool(wf_horizon_cfg.use_test_window),
            },
            "start_date": walk_forward_json.get("start_date"),
            "end_date": walk_forward_json.get("end_date"),
            "end_date_policy": str(walk_forward_json.get("end_date_policy") or "latest").strip().lower() or "latest",
            "resolved_start_date": wf_resolved_start,
            "resolved_end_date": wf_resolved_end,
            "date_resolution": dict(walk_forward_json.get("date_resolution") or {}),
            "use_test_window": True,
            "max_folds": max_folds,
            "folds": period_entries,
        }
    elif batch_enabled and batch_period_entries:
        period_mode = "batch_period"
        period_entries = list(batch_period_entries)

    if period_mode and period_entries:
        periods_map: dict[str, tuple[str, str]] = {
            str(p["label"]): (str(p["start"]), str(p["end"])) for p in period_entries
        }
        period_rows_by_label: dict[str, dict[str, str]] = {str(p["label"]): dict(p) for p in period_entries}
        selected_periods = list(periods_map.keys())

        batch_frames: list[pd.DataFrame] = []
        base_spec_by_kind: dict[str, EngineSpec] = {}
        wf_returns_by_kind: dict[str, list[pd.Series]] = {}
        _fold_perf_by_kind: dict[str, list[dict]] = {}

        for kind_raw in opt_kinds:
            kind = str(kind_raw).strip().lower()
            if not kind:
                continue

            base_params = dict(strategy_cfg.params or {}) if kind == str(strategy_cfg.kind).strip().lower() else {}
            base_spec_k = replace(engine_spec, strategy=StrategyConfig(kind=kind, params=base_params))
            base_spec_by_kind[kind] = base_spec_k

            if period_mode == "walk_forward":
                active_params = _params_from_catalog(kind)
                rows: list[dict[str, Any]] = []
                top_variants_per_fold = max(1, int(opt_cfg.top_k or 1))
                _fold_perf: list[dict] = []
                def _eval_fold(fold_idx_label: tuple[int, str]):
                    fold_idx, label = fold_idx_label
                    _t_fold = time.perf_counter()
                    _fp_opt_ms, _fp_n_trials = 0.0, 0
                    fold = period_rows_by_label[label]
                    test_start = str(fold.get("test_start") or fold["start"])
                    test_end = str(fold.get("test_end") or fold["end"])
                    train_start = str(fold.get("train_start") or fold["start"])
                    train_end = str(fold.get("train_end") or fold["end"])

                    train_spec = replace(
                        base_spec_k,
                        data=replace(
                            base_spec_k.data,
                            start=str(train_start),
                            end=str(train_end),
                            include_windows=None,
                            exclude_windows=None,
                        ),
                    )

                    train_candidates: list[tuple[int, EngineSpec, float | None]] = []
                    if kind == "buy_hold" or not active_params:
                        train_candidates.append((1, train_spec, None))
                    else:
                        _t_opt = time.perf_counter()
                        _, top_df_train, _, best_train_spec, ranked_df_train, _wfo_timing = run_optimization(
                            base_spec=train_spec,
                            active_params=active_params,
                            cfg=opt_cfg,
                        )
                        _fp_opt_ms = round((time.perf_counter() - _t_opt) * 1000.0, 2)
                        _fp_n_trials = _wfo_timing.n_trials_run
                        train_rank_source = ranked_df_train if isinstance(ranked_df_train, pd.DataFrame) else pd.DataFrame()
                        if train_rank_source.empty and isinstance(top_df_train, pd.DataFrame):
                            train_rank_source = top_df_train.copy()
                        if train_rank_source.empty:
                            train_candidates.append((1, best_train_spec, None))
                        else:
                            train_rank_source = train_rank_source.head(top_variants_per_fold).reset_index(drop=True)
                            for trial_rank, train_row in enumerate(train_rank_source.to_dict("records"), start=1):
                                train_row_spec = build_spec_from_result_row(train_spec, train_row)
                                train_metric = pd.to_numeric(train_row.get(period_objective), errors="coerce")
                                train_obj_val = None if pd.isna(train_metric) else float(train_metric)
                                train_candidates.append((trial_rank, train_row_spec, train_obj_val))

                    _t_bt = time.perf_counter()
                    _fold_rows: list[dict[str, Any]] = []
                    _fold_ret_series: list[pd.Series] = []
                    for trial_rank, train_candidate_spec, train_objective_value in train_candidates:
                        test_spec = replace(
                            train_candidate_spec,
                            data=replace(
                                train_candidate_spec.data,
                                start=str(test_start),
                                end=str(test_end),
                                include_windows=None,
                                exclude_windows=None,
                            ),
                        )
                        bundle = BacktestEngine(test_spec).run(fast_mode=True)
                        if trial_rank == 1:
                            ret_series = dict(getattr(bundle.report, "series", None) or {}).get("returns")
                            if isinstance(ret_series, pd.Series):
                                _fold_ret_series.append(pd.to_numeric(ret_series, errors="coerce").dropna())
                        metrics = dict(getattr(bundle.report, "metrics", None) or {})
                        signal_snapshot = _signal_snapshot_from_bundle(bundle, preferred_symbol=symbol_label)
                        row = {
                            "fold_index": int(fold_idx),
                            "period": label,
                            "start": str(test_start),
                            "end": str(test_end),
                            "train_start": str(train_start),
                            "train_end": str(train_end),
                            "test_start": str(test_start),
                            "test_end": str(test_end),
                            "trial_rank": int(trial_rank),
                            "objective": period_objective,
                            "objective_value": _metric_from_report(metrics, period_objective),
                            "train_objective_value": train_objective_value,
                            "strategy_kind": kind,
                            "horizon": (
                                str((walk_forward_meta or {}).get("horizon"))
                                if isinstance(walk_forward_meta, dict)
                                else None
                            ),
                            "horizon_label": (
                                str((walk_forward_meta or {}).get("horizon_label"))
                                if isinstance(walk_forward_meta, dict)
                                else None
                            ),
                            "stat.pnl": _metric_from_report(metrics, "pnl"),
                            "stat.cagr": _metric_from_report(metrics, "cagr"),
                            "stat.efficiency": _metric_from_report(metrics, "efficiency"),
                            "stat.n_fills": _metric_from_report(metrics, "n_fills"),
                            "signal_today": signal_snapshot.get("signal_today"),
                            "signal_label": signal_snapshot.get("signal_label"),
                            "signal_date": signal_snapshot.get("signal_date"),
                        }
                        for k_param, v_param in _best_params_from_spec(test_spec).items():
                            row[f"param.{k_param}"] = v_param
                        _fold_rows.append(row)

                    _fp_bt_ms = round((time.perf_counter() - _t_bt) * 1000.0, 2)
                    _fp_total_ms = round((time.perf_counter() - _t_fold) * 1000.0, 2)
                    _fold_perf_item = {
                        "idx": fold_idx, "label": label,
                        "train_start": train_start, "test_start": test_start,
                        "opt_ms": _fp_opt_ms, "n_trials": _fp_n_trials,
                        "backtest_ms": _fp_bt_ms, "fold_ms": _fp_total_ms,
                    }
                    _pipeline_logger.info(
                        "[perf] kind=%s fold %d/%d '%s' opt=%.0f ms bt=%.0f ms total=%.0f ms",
                        kind, fold_idx + 1, len(selected_periods), label,
                        _fp_opt_ms, _fp_bt_ms, _fp_total_ms,
                    )
                    return _fold_rows, _fold_ret_series, _fold_perf_item

                _n_fold_workers = min(len(selected_periods), max(1, (os.cpu_count() or 4)))
                with ThreadPoolExecutor(max_workers=_n_fold_workers) as _fold_pool:
                    _fold_futures = [
                        _fold_pool.submit(_eval_fold, (fi, lbl))
                        for fi, lbl in enumerate(selected_periods)
                    ]
                    for _fut in as_completed(_fold_futures):
                        try:
                            _fold_rows, _fold_ret_series, _fold_perf_item = _fut.result()
                            rows.extend(_fold_rows)
                            for _rs in _fold_ret_series:
                                wf_returns_by_kind.setdefault(kind, []).append(_rs)
                            _fold_perf.append(_fold_perf_item)
                        except Exception as _fold_exc:
                            _pipeline_logger.error("[wfo] fold error: %s", _fold_exc, exc_info=True)

                _fold_perf_by_kind[kind] = _fold_perf
                if rows:
                    batch_frames.append(pd.DataFrame(rows))
                continue

            if kind == "buy_hold":
                rows: list[dict[str, Any]] = []
                for label in selected_periods:
                    p_start, p_end = periods_map[label]
                    per_spec = replace(
                        base_spec_k,
                        data=replace(base_spec_k.data, start=str(p_start), end=str(p_end), include_windows=None, exclude_windows=None),
                    )
                    bundle = BacktestEngine(per_spec).run(fast_mode=True)
                    metrics = dict(getattr(bundle.report, "metrics", None) or {})
                    row = {
                        "period": label,
                        "start": str(p_start),
                        "end": str(p_end),
                        "objective": period_objective,
                        "objective_value": _metric_from_report(metrics, period_objective),
                        "strategy_kind": kind,
                        "stat.pnl": _metric_from_report(metrics, "pnl"),
                        "stat.cagr": _metric_from_report(metrics, "cagr"),
                    }
                    for k_param, v_param in _best_params_from_spec(per_spec).items():
                        row[f"param.{k_param}"] = v_param
                    rows.append(row)
                if rows:
                    batch_frames.append(pd.DataFrame(rows))
                continue

            active_params = _params_from_catalog(kind)
            if period_optimize_within_each and active_params:
                df_k = batch_optimize_by_period(
                    base_spec=base_spec_k,
                    active_params=active_params,
                    cfg=opt_cfg,
                    periods=periods_map,
                    selected_period_labels=selected_periods,
                    objective=period_objective,
                )
                if isinstance(df_k, pd.DataFrame) and not df_k.empty:
                    df_k = df_k.copy()
                    df_k["strategy_kind"] = kind
                    batch_frames.append(df_k)
                continue

            rows: list[dict[str, Any]] = []
            for label in selected_periods:
                p_start, p_end = periods_map[label]
                per_spec = replace(
                    base_spec_k,
                    data=replace(base_spec_k.data, start=str(p_start), end=str(p_end), include_windows=None, exclude_windows=None),
                )
                bundle = BacktestEngine(per_spec).run(fast_mode=True)
                metrics = dict(getattr(bundle.report, "metrics", None) or {})
                row = {
                    "period": label,
                    "start": str(p_start),
                    "end": str(p_end),
                    "objective": period_objective,
                    "objective_value": _metric_from_report(metrics, period_objective),
                    "strategy_kind": kind,
                    "stat.pnl": _metric_from_report(metrics, "pnl"),
                    "stat.cagr": _metric_from_report(metrics, "cagr"),
                }
                for k_param, v_param in _best_params_from_spec(per_spec).items():
                    row[f"param.{k_param}"] = v_param
                rows.append(row)
            if rows:
                batch_frames.append(pd.DataFrame(rows))

        if batch_frames:
            batch_df = pd.concat(batch_frames, ignore_index=True)
            batch_df["strategy_kind"] = batch_df["strategy_kind"].astype(str).str.strip().str.lower()
            batch_df["period"] = batch_df["period"].astype(str)
            batch_df["objective"] = period_objective
            batch_df["objective_value"] = pd.to_numeric(batch_df.get("objective_value"), errors="coerce")

            batch_df = batch_df.sort_values(
                ["strategy_kind", "objective_value"],
                ascending=[True, False],
                na_position="last",
            ).reset_index(drop=True)
            batch_df["rank"] = batch_df.groupby("strategy_kind").cumcount() + 1

            batch_df_global = batch_df.sort_values("objective_value", ascending=False, na_position="last").reset_index(drop=True)
            winner_row = batch_df_global.iloc[0]
            winner_kind = str(winner_row.get("strategy_kind") or opt_kinds[0]).strip().lower()
            winner_base_spec = base_spec_by_kind.get(
                winner_kind,
                replace(engine_spec, strategy=StrategyConfig(kind=winner_kind, params={})),
            )
            winner_spec = build_spec_from_result_row(winner_base_spec, winner_row)
            winner_start = str(winner_row.get("start") or winner_spec.data.start)
            winner_end = str(winner_row.get("end") or winner_spec.data.end)
            if period_mode == "walk_forward":
                winner_start = str((walk_forward_meta or {}).get("resolved_start_date") or winner_start)
                winner_end = str((walk_forward_meta or {}).get("resolved_end_date") or winner_end)
            winner_spec = replace(
                winner_spec,
                data=replace(
                    winner_spec.data,
                    start=winner_start,
                    end=winner_end,
                    include_windows=None,
                    exclude_windows=None,
                ),
            )

            bundles_by_kind: Dict[str, Any] = {}
            best_specs_by_kind: Dict[str, EngineSpec] = {}
            for kind, base_spec_k in base_spec_by_kind.items():
                best_row_k_df = batch_df[batch_df["strategy_kind"] == kind]
                if best_row_k_df.empty:
                    continue
                best_row_k = best_row_k_df.sort_values("objective_value", ascending=False, na_position="last").iloc[0]
                best_spec_k = build_spec_from_result_row(base_spec_k, best_row_k)
                best_start = str(best_row_k.get("start") or best_spec_k.data.start)
                best_end = str(best_row_k.get("end") or best_spec_k.data.end)
                if period_mode == "walk_forward":
                    best_start = str((walk_forward_meta or {}).get("resolved_start_date") or best_start)
                    best_end = str((walk_forward_meta or {}).get("resolved_end_date") or best_end)
                best_spec_k = replace(
                    best_spec_k,
                    data=replace(
                        best_spec_k.data,
                        start=best_start,
                        end=best_end,
                        include_windows=None,
                        exclude_windows=None,
                    ),
                )
                bundles_by_kind[kind] = BacktestEngine(best_spec_k).run()
                best_specs_by_kind[kind] = best_spec_k

            if winner_kind not in bundles_by_kind:
                bundles_by_kind[winner_kind] = BacktestEngine(winner_spec).run()
                best_specs_by_kind[winner_kind] = winner_spec

            primary_bundle = bundles_by_kind[winner_kind]

            heatmap_df = (
                batch_df.pivot_table(index="period", columns="strategy_kind", values="objective_value", aggfunc="max")
                if not batch_df.empty
                else pd.DataFrame()
            )
            if not heatmap_df.empty:
                ordered_cols = [str(k).strip().lower() for k in opt_kinds if str(k).strip().lower() in heatmap_df.columns]
                remaining_cols = [c for c in heatmap_df.columns if c not in ordered_cols]
                heatmap_df = heatmap_df.reindex(index=selected_periods, columns=ordered_cols + remaining_cols)

            leaderboard_df = batch_df.copy()
            leaderboard_df["Strategy"] = leaderboard_df["strategy_kind"]
            leaderboard_df["symbol"] = symbol_label
            leaderboard_df["pnl"] = pd.to_numeric(leaderboard_df.get("stat.pnl"), errors="coerce")
            leaderboard_df["cagr"] = pd.to_numeric(leaderboard_df.get("stat.cagr"), errors="coerce")
            if "stat.efficiency" in leaderboard_df.columns:
                leaderboard_df["efficiency"] = pd.to_numeric(leaderboard_df["stat.efficiency"], errors="coerce")
            if "stat.n_fills" in leaderboard_df.columns:
                leaderboard_df["n_fills"] = pd.to_numeric(leaderboard_df["stat.n_fills"], errors="coerce")
            if "signal_today" in leaderboard_df.columns:
                leaderboard_df["signal_today"] = pd.to_numeric(leaderboard_df["signal_today"], errors="coerce").fillna(0.0)
            else:
                leaderboard_df["signal_today"] = 0.0
            if "signal_label" in leaderboard_df.columns:
                signal_labels = leaderboard_df["signal_label"].copy()
                signal_labels = signal_labels.where(signal_labels.notna(), "HOLD")
                leaderboard_df["signal_label"] = signal_labels.astype(str).str.strip().str.upper().replace({"": "HOLD"})
            else:
                leaderboard_df["signal_label"] = "HOLD"
            if "signal_date" not in leaderboard_df.columns:
                leaderboard_df["signal_date"] = None
            period_prefix = "walk_forward" if period_mode == "walk_forward" else "batch"
            leaderboard_df["best_params_json"] = [
                {
                    **_best_params_from_any_row(leaderboard_df.iloc[i]),
                    f"{period_prefix}.period": leaderboard_df.iloc[i].get("period"),
                    f"{period_prefix}.start": leaderboard_df.iloc[i].get("start"),
                    f"{period_prefix}.end": leaderboard_df.iloc[i].get("end"),
                    f"{period_prefix}.objective": leaderboard_df.iloc[i].get("objective"),
                    f"{period_prefix}.objective_value": leaderboard_df.iloc[i].get("objective_value"),
                    f"{period_prefix}.rank": leaderboard_df.iloc[i].get("rank"),
                }
                for i in range(len(leaderboard_df))
            ]

            strategy_results = {
                k: _bundle_to_strategy_result(
                    k,
                    b,
                    _best_params_from_spec(best_specs_by_kind[k]),
                    strategy_params=dict(best_specs_by_kind[k].strategy.params or {}),
                    port_cfg=best_specs_by_kind[k].portfolio,
                )
                for k, b in bundles_by_kind.items()
            }
            walk_forward_oos_summary_by_kind: dict[str, Any] = {}
            if period_mode == "walk_forward":
                for kind in sorted(base_spec_by_kind.keys()):
                    series_parts = wf_returns_by_kind.get(kind, [])
                    merged_returns = (
                        pd.concat(series_parts).sort_index()
                        if series_parts
                        else pd.Series(dtype=float)
                    )
                    returns_summary = _returns_summary(merged_returns if isinstance(merged_returns, pd.Series) else None)

                    kind_rows = batch_df[batch_df["strategy_kind"] == kind] if "strategy_kind" in batch_df.columns else pd.DataFrame()
                    if isinstance(kind_rows, pd.DataFrame) and not kind_rows.empty and "trial_rank" in kind_rows.columns:
                        trial_rank_numeric = pd.to_numeric(kind_rows["trial_rank"], errors="coerce")
                        kind_rows = kind_rows[trial_rank_numeric == 1]
                    oos_vals = pd.to_numeric(kind_rows.get("objective_value"), errors="coerce").dropna()
                    train_vals = pd.to_numeric(kind_rows.get("train_objective_value"), errors="coerce").dropna()
                    gap_ratio = None
                    if not oos_vals.empty and not train_vals.empty:
                        n = min(len(oos_vals), len(train_vals))
                        base = train_vals.iloc[:n].abs().replace(0, 1.0)
                        gap = (train_vals.iloc[:n] - oos_vals.iloc[:n]).abs() / base
                        gap_ratio = float(gap.median()) if len(gap) else None

                    walk_forward_oos_summary_by_kind[kind] = {
                        "n_folds": int(len(kind_rows)),
                        "objective_mean": float(oos_vals.mean()) if not oos_vals.empty else None,
                        "objective_median": float(oos_vals.median()) if not oos_vals.empty else None,
                        "is_oos_gap_median": gap_ratio,
                        **returns_summary,
                    }

                if isinstance(walk_forward_meta, dict):
                    walk_forward_meta["oos_summary_by_kind"] = walk_forward_oos_summary_by_kind

            heatmap_title = (
                f"Walk-Forward Heatmap ({period_objective.upper()})"
                if period_mode == "walk_forward"
                else f"Batch Period Heatmap ({period_objective.upper()})"
            )
            batch_heatmap_fig = make_batch_period_heatmap_plot(
                heatmap_df,
                objective=period_objective,
                title=heatmap_title,
            )

            batch_period_payload: dict[str, Any] = {
                "mode": period_mode,
                "objective": period_objective,
                "optimize_within_each": period_optimize_within_each,
                "results": _df_to_records(batch_df_global, ensure_timestamp=False),
                "heatmap": batch_heatmap_fig.to_plotly_json(),
                "winner": {
                    "strategy_kind": winner_kind,
                    "period": winner_row.get("period"),
                    "start": winner_row.get("start"),
                    "end": winner_row.get("end"),
                    "objective_value": winner_row.get("objective_value"),
                },
            }
            if period_mode == "walk_forward":
                batch_period_payload["walk_forward"] = walk_forward_meta
                batch_period_payload["oos_summary_by_kind"] = walk_forward_oos_summary_by_kind

            artifacts_payload: dict[str, Any] = {
                "run_spec": run_spec,
                "primary_kind": winner_kind,
                "optimized_kinds": sorted(best_specs_by_kind.keys()),
                "best_strategy_params_by_kind": {k: _best_params_from_spec(v) for k, v in best_specs_by_kind.items()},
            }
            if period_mode == "batch_period":
                artifacts_payload["batch_periods"] = {
                    "enabled": True,
                    "objective": period_objective,
                    "periods": period_entries,
                }
            if period_mode == "walk_forward":
                artifacts_payload["walk_forward"] = walk_forward_meta or {"enabled": True, "periods": period_entries}

            walk_forward_rows_payload = batch_period_payload.get("results") if period_mode == "walk_forward" else []
            return {
                "leaderboard": _df_to_records(leaderboard_df, ensure_timestamp=False),
                "plot_artifacts": _build_plot_artifacts(
                    primary_bundle,
                    strategy_params=dict(best_specs_by_kind[winner_kind].strategy.params or {}),
                    port_cfg=best_specs_by_kind[winner_kind].portfolio,
                ),
                "strategy_results": strategy_results,
                "decision_support": _build_decision_support(
                    strategy_results,
                    walk_forward_rows=walk_forward_rows_payload if isinstance(walk_forward_rows_payload, list) else [],
                    walk_forward_oos_summary_by_kind=(
                        walk_forward_oos_summary_by_kind if period_mode == "walk_forward" else {}
                    ),
                ),
                "batch_period": batch_period_payload,
                **_runtime_payload(primary_bundle),
                "artifacts": artifacts_payload,
                "_perf": {
                    "mode": period_mode or "walk_forward",
                    "folds_count": len(period_entries),
                    "folds_by_kind": _fold_perf_by_kind,
                    "folds_total_ms": round(
                        sum(f.get("fold_ms", 0) for fl in _fold_perf_by_kind.values() for f in fl), 2
                    ),
                },
            }

    bundles_by_kind: Dict[str, Any] = {}
    best_specs_by_kind: Dict[str, EngineSpec] = {}
    lb_parts: list[pd.DataFrame] = []
    _all_timings: list[OptimizeTiming] = []

    def _run_kind(kind_raw: Any) -> tuple[str, pd.DataFrame, EngineSpec | None, Any | None, OptimizeTiming | None]:
        k = str(kind_raw)
        if k == "buy_hold":
            bh_spec = replace(engine_spec, strategy=StrategyConfig(kind="buy_hold", params={}))
            return k, pd.DataFrame(), bh_spec, BacktestEngine(bh_spec).run(), None

        active_params = _params_from_catalog(k)
        if not active_params:
            return k, pd.DataFrame(), None, None, None

        base_spec_k = replace(engine_spec, strategy=StrategyConfig(kind=k, params={}))
        _, top_df, _, best_spec, _, _opt_timing = run_optimization(
            base_spec=base_spec_k,
            active_params=active_params,
            cfg=opt_cfg,
        )
        top_df = top_df.copy() if isinstance(top_df, pd.DataFrame) else pd.DataFrame()
        bundle = BacktestEngine(best_spec).run()
        return k, top_df, best_spec, bundle, _opt_timing

    raw_workers = optimization_json.get("strategy_parallel_workers")
    auto_workers = max(1, min(len(opt_kinds), max(1, (os.cpu_count() or 1) - 1)))
    if raw_workers is None:
        strategy_workers = auto_workers
    elif isinstance(raw_workers, str) and raw_workers.strip().lower() in {"auto", "default"}:
        strategy_workers = auto_workers
    else:
        try:
            strategy_workers = max(1, int(raw_workers))
        except Exception:
            strategy_workers = auto_workers
        strategy_workers = min(strategy_workers, max(1, len(opt_kinds)))

    outputs: list[tuple[str, pd.DataFrame, EngineSpec | None, Any | None, Any]] = []
    if strategy_workers <= 1 or len(opt_kinds) <= 1:
        outputs = [_run_kind(kind) for kind in opt_kinds]
    else:
        with ThreadPoolExecutor(max_workers=strategy_workers) as ex:
            fut_map = {ex.submit(_run_kind, kind): str(kind) for kind in opt_kinds}
            for fut in as_completed(fut_map):
                outputs.append(fut.result())

    for k, top_df, best_spec, bundle, _kind_timing in outputs:
        if best_spec is None or bundle is None:
            continue

        if _kind_timing is not None:
            _all_timings.append(_kind_timing)

        if not top_df.empty:
            top_df["Strategy"] = k
            top_df["symbol"] = symbol_label
            top_df["best_params_json"] = [
                _best_params_from_lb_row(top_df.iloc[i])
                for i in range(len(top_df))
            ]
            lb_parts.append(top_df)

        bundles_by_kind[k] = bundle
        best_specs_by_kind[k] = best_spec

    if not bundles_by_kind:
        bundle = BacktestEngine(engine_spec).run()
        strategy_results = {
            str(strategy_cfg.kind): _bundle_to_strategy_result(
                str(strategy_cfg.kind),
                bundle,
                _best_params_from_spec(engine_spec),
                strategy_params=dict(engine_spec.strategy.params or {}),
                port_cfg=engine_spec.portfolio,
            )
        }
        return {
            "leaderboard": [],
            "plot_artifacts": _build_plot_artifacts(
                bundle,
                strategy_params=dict(engine_spec.strategy.params or {}),
                port_cfg=engine_spec.portfolio,
            ),
            "strategy_results": strategy_results,
            "decision_support": _build_decision_support(strategy_results),
            **_runtime_payload(bundle),
            "artifacts": {"run_spec": run_spec},
        }

    primary_kind = str(opt_kinds[0])
    if primary_kind not in bundles_by_kind:
        primary_kind = next(iter(bundles_by_kind))

    primary_bundle = bundles_by_kind[primary_kind]
    leaderboard = pd.concat(lb_parts, ignore_index=True) if lb_parts else None
    strategy_results = {
        k: _bundle_to_strategy_result(
            k,
            b,
            _best_params_from_spec(best_specs_by_kind[k]),
            strategy_params=dict(best_specs_by_kind[k].strategy.params or {}),
            port_cfg=best_specs_by_kind[k].portfolio,
        )
        for k, b in bundles_by_kind.items()
    }

    # Aggregate timing from all optimization calls
    _timing_summary: dict[str, Any] = {}
    if _all_timings:
        _timing_summary = {
            "load_ms": sum(t.load_ms for t in _all_timings),
            "bank_ms": sum(t.bank_ms for t in _all_timings),
            "trial_total_ms": sum(t.trial_total_ms for t in _all_timings),
            "n_trials_run": sum(t.n_trials_run for t in _all_timings),
            "avg_trial_ms": (
                sum(t.trial_total_ms for t in _all_timings) / sum(t.n_trials_run for t in _all_timings)
                if sum(t.n_trials_run for t in _all_timings) > 0 else 0.0
            ),
            "cache_hits": sum(t.cache_hits for t in _all_timings),
            "cache_misses": sum(t.cache_misses for t in _all_timings),
            "profile_text": next(
                (t.profile_text for t in _all_timings if t.profile_text), None
            ),
        }

    return {
        "leaderboard": _df_to_records(leaderboard, ensure_timestamp=False),
        "plot_artifacts": _build_plot_artifacts(
            primary_bundle,
            strategy_params=dict(best_specs_by_kind[primary_kind].strategy.params or {}),
            port_cfg=best_specs_by_kind[primary_kind].portfolio,
        ),
        "strategy_results": strategy_results,
        "decision_support": _build_decision_support(strategy_results),
        **_runtime_payload(primary_bundle),
        "artifacts": {
            "run_spec": run_spec,
            "primary_kind": primary_kind,
            "optimized_kinds": sorted(best_specs_by_kind.keys()),
            "best_strategy_params_by_kind": {k: _best_params_from_spec(v) for k, v in best_specs_by_kind.items()},
        },
        "optimization_timing": _timing_summary,
        "_perf": {
            "mode": "optimize",
            "opt_timing": {k: v for k, v in _timing_summary.items() if k != "profile_text"},
        },
    }
