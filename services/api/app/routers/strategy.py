"""Strategy plan API — universe filtering, S/R levels, execution, sizing."""

from __future__ import annotations

import json
import logging
import inspect
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
import numpy as np
from sqlalchemy.orm import Session

from .. import models
from ..db import get_db
from ..market_data_loader import load_ohlcv_for_symbol
from ..masi_tickers import get_masi_info
from ..schemas.strategy import (
    ExecutionPlanOut,
    ExecutionRequest,
    FamilyScoreOut,
    FocusedKellyOut,
    HandoffOut,
    LevelsOut,
    LevelsRequest,
    PivotPoints,
    ReviewOut,
    ReviewRequest,
    RiskPreviewOut,
    RiskPreviewRequest,
    RulePreviewOut,
    RulePreviewRequest,
    RulePreviewRow,
    SRLevel,
    SavedStrategyCreate,
    StrategyAllocationOut,
    StrategyAllocationRequest,
    StrategyAllocationRowOut,
    SavedStrategyListItem,
    SavedStrategyOut,
    SavedStrategyUpdate,
    SignalCandidateOut,
    SignalCandidateRequest,
    SignalConsensusOut,
    SignalConsensusRequest,
    SignalConstructionPreviewOut,
    SignalConstructionPreviewRequest,
    StrategyBacktestRequest,
    StrategyBacktestResponse,
    SizingOut,
    SizingRequest,
    StockSizingRow,
    UniverseFilterRequest,
    UniverseStockOut,
)
import pandas as pd
from .strategy_signals import (
    _get_all_representative_indicators,
    _get_or_compute,
    _get_top_representative_indicator,
    _score_to_label,
    _safe_float,
)

from core.quant_core.data import drop_incomplete_ohlcv_rows
from core.quant_core.horizons import canonical_horizon
from core.quant_core.strategy_plan.allocation import compute_strategy_allocation
from core.quant_core.strategy_plan.backtest import (
    build_rule_snapshot,
    describe_rule_conditions,
    rule_condition_count,
    rule_triggered,
    run_strategy_plan_backtest,
)
from core.quant_core.signal_engine.domain import (
    CATEGORY_FAMILIES,
    FAMILY_SIGNAL_TYPE,
    HORIZON_PARAMS,
    signal_type_label,
)
from core.quant_core.signal_engine.ensemble import family_signal_is_available
from core.quant_core.strategy_plan.execution import compute_execution_plan
from core.quant_core.strategy_plan.execution_policy import build_execution_horizon_policy
from core.quant_core.strategy_plan.signal_policy import compute_consensus
from core.quant_core.strategy_plan.score_sources import (
    compute_strategy_score_frame,
    iter_score_sources,
    source_has_wfo_params,
    source_params_bundle,
    score_source_variant,
    source_wfo_param_names,
    score_variable_catalog,
)
from core.quant_core.strategy_plan.sizing import (
    compute_kelly_ceiling,
    compute_portfolio_allocation,
)
from core.quant_core.strategy_plan.universe import filter_universe
from core.quant_core.strategy_plan.levels import (
    compute_atr,
    compute_pivot_points,
    detect_swing_levels,
)
from core.quant_core.signal_engine.variant_detail import _compute_indicator
from ..strategy_v2 import (
    build_legacy_backtest_config_from_v2,
    build_strategy_handoff,
    build_strategy_review,
    get_basket_from_strategy_config,
    migrate_strategy_config_v2,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/strategy/plan", tags=["strategy-plan"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truncate_for_horizon(ohlcv, horizon: str):
    signal_horizon = canonical_horizon(horizon, allow_legacy=True)
    max_bars = HORIZON_PARAMS[signal_horizon]["max_years"] * 252
    if len(ohlcv) > max_bars:
        return ohlcv.iloc[-max_bars:]
    return ohlcv


def _clean_ohlcv(ohlcv):
    return drop_incomplete_ohlcv_rows(ohlcv)


def _compute_adv20_value(ohlcv: pd.DataFrame) -> float | None:
    if ohlcv.empty or "Close" not in ohlcv.columns or "Volume" not in ohlcv.columns:
        return None
    recent = ohlcv.tail(20)
    close = pd.to_numeric(recent["Close"], errors="coerce")
    volume = pd.to_numeric(recent["Volume"], errors="coerce")
    traded_value = (close * volume).replace([np.inf, -np.inf], np.nan).dropna()
    if traded_value.empty:
        return None
    adv20 = float(traded_value.mean())
    return adv20 if np.isfinite(adv20) else None


def _resolve_execution_policy(
    horizon: str,
    timeframe: str,
    *,
    execution_holding_bars: int | None = None,
):
    return build_execution_horizon_policy(
        horizon,
        timeframe=timeframe,
        holding_bars=execution_holding_bars,
    )


def _compute_batch_scores(
    db: Session,
    symbols: list[str],
    horizon: str,
    timeframe: str,
    cost_bps: float,
    cooldown_bars: int,
) -> dict[str, dict[str, Any]]:
    """Compute signal scores for multiple symbols, identical to batch_scores endpoint logic."""
    result: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        family_scores: dict[str, float] = {}
        family_labels: dict[str, str] = {}
        for family in ("sma", "rsi", "macd", "obv"):
            try:
                detail = _get_or_compute(
                    db, family, symbol, horizon, timeframe, cost_bps, cooldown_bars,
                )
                if not family_signal_is_available(detail.signal):
                    continue
                family_scores[family] = detail.signal.family_score_pct
                family_labels[family] = detail.signal.family_signal_label
            except HTTPException:
                pass

        categories: dict[str, dict[str, Any]] = {}
        for cat_name, cat_fams in CATEGORY_FAMILIES.items():
            cat_scores = [family_scores[f] for f in cat_fams if f in family_scores]
            if cat_scores:
                cat_avg = sum(cat_scores) / len(cat_scores)
                st = FAMILY_SIGNAL_TYPE.get(cat_fams[0], "trend")
                categories[cat_name] = {
                    "score_pct": round(cat_avg, 2),
                    "label": signal_type_label(st, cat_avg),
                    "families": cat_fams,
                }

        all_scores = list(family_scores.values())
        if all_scores:
            agg = sum(all_scores) / len(all_scores)
            result[symbol] = {
                "aggregate_score_pct": round(agg, 2),
                "aggregate_signal_label": _score_to_label(agg),
                "categories": categories,
                "per_family": {
                    f: {"score_pct": round(s, 2), "label": family_labels.get(f, "N/A")}
                    for f, s in family_scores.items()
                },
            }
        else:
            result[symbol] = {
                "aggregate_score_pct": None,
                "aggregate_signal_label": None,
                "categories": {},
                "per_family": {},
            }
    return result


def _build_universe_stock_dicts(db: Session, timeframe: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Build the strategy universe from tracked stocks plus stored equity data."""
    stocks_raw = (
        db.query(models.StockMaster)
        .order_by(models.StockMaster.symbol.asc())
        .all()
    )
    stores_raw = (
        db.query(models.MarketDataStore)
        .filter(
            models.MarketDataStore.timeframe == timeframe,
            models.MarketDataStore.asset_class == "equity",
        )
        .order_by(models.MarketDataStore.symbol.asc())
        .all()
    )
    store_by_symbol = {store.symbol: store for store in stores_raw}
    stock_by_symbol = {stock.symbol: stock for stock in stocks_raw if stock.is_active}
    inactive_symbols = {stock.symbol for stock in stocks_raw if not stock.is_active}
    symbols = sorted(set(stock_by_symbol) | (set(store_by_symbol) - inactive_symbols))

    stock_dicts: list[dict[str, Any]] = []
    for symbol in symbols:
        stock = stock_by_symbol.get(symbol)
        store = store_by_symbol.get(symbol)
        masi_info = get_masi_info(symbol) or {}
        adv20 = None
        try:
            ohlcv = load_ohlcv_for_symbol(db, symbol, timeframe)
            ohlcv = _clean_ohlcv(ohlcv)
            adv20 = _compute_adv20_value(ohlcv)
        except Exception:
            logger.debug("ADV20 unavailable for %s", symbol, exc_info=True)

        stock_dicts.append({
            "symbol": symbol,
            "display_name": (stock.display_name if stock else None) or masi_info.get("name") or symbol,
            "sector": (stock.sector if stock else None) or masi_info.get("sector"),
            "market_cap_class": stock.market_cap_class if stock else None,
            "row_count": store.row_count if store else 0,
            "data_as_of": str(store.data_as_of)[:10] if store and store.data_as_of else None,
            "adv20": adv20,
        })

    return stock_dicts, symbols


def _candidate_id_for(row: dict[str, Any]) -> str:
    parts = [
        row.get("symbol"),
        row.get("source"),
        row.get("variant"),
        row.get("bucket"),
        row.get("direction"),
        row.get("fwd_horizon_bars"),
    ]
    return ":".join(str(part or "").strip().lower() for part in parts)


def _candidate_float(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if np.isfinite(out) else None


def _candidate_int(value: Any) -> int | None:
    try:
        out = int(value)
    except Exception:
        return None
    return out


def _basic_candidate_exclusion(stock: dict[str, Any], body: SignalCandidateRequest) -> str | None:
    row_count = _candidate_int(stock.get("row_count")) or 0
    if row_count < body.min_bars:
        return f"Insufficient history: {row_count} bars < {body.min_bars}."
    adv20 = _candidate_float(stock.get("adv20"))
    if body.min_adv20 > 0 and (adv20 is None or adv20 < body.min_adv20):
        return "Below ADV20 liquidity gate."
    if body.sector_filter:
        wanted = {str(item).strip().lower() for item in body.sector_filter if str(item).strip()}
        sector = str(stock.get("sector") or "").strip().lower()
        if wanted and sector not in wanted:
            return "Outside selected sector filter."
    return None


def _edge_payloads_for_signal_candidate(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    cost_bps: float,
) -> list[dict[str, Any]]:
    try:
        from ..services.dashboard_builder import (
            EDGE_CANDIDATE_COUNT,
            EDGE_SIGNAL_MODES,
            _apply_wfo_all_oos_proof_to_edge,
            _best_signal_rank,
            _bucket_to_signal_label,
            _signal_method_label,
        )
        from .analytics import _build_edge_metrics_from_db, _edge_metrics_to_out
    except Exception:
        logger.exception("signal candidate dependencies unavailable")
        return []

    out: list[dict[str, Any]] = []
    for source in ("signal_engine", "wfo"):
        for variant in EDGE_SIGNAL_MODES:
            try:
                metrics = _build_edge_metrics_from_db(
                    symbol=symbol,
                    horizon=horizon,
                    source=source,
                    variant=variant,
                    cost_bps=cost_bps,
                    db=db,
                    multiple_testing_count=EDGE_CANDIDATE_COUNT,
                )
                if metrics is None:
                    continue
                edge = json.loads(_edge_metrics_to_out(metrics).model_dump_json())
                if source == "wfo":
                    edge = _apply_wfo_all_oos_proof_to_edge(
                        db,
                        symbol=symbol,
                        horizon=horizon,
                        variant=variant,
                        edge=edge,
                        cost_bps=cost_bps,
                    )
            except Exception:
                logger.exception(
                    "signal candidate edge build failed",
                    extra={"symbol": symbol, "horizon": horizon, "source": source, "variant": variant},
                )
                try:
                    db.rollback()
                except Exception:
                    pass
                continue

            rank = _best_signal_rank(edge)
            if rank is None:
                continue

            out.append(
                {
                    "_rank": rank,
                    "source": source,
                    "variant": variant,
                    "label": _signal_method_label(source, variant),
                    "signal_label": _bucket_to_signal_label(edge.get("bucket")),
                    "triage": "proven" if bool(edge.get("proven_edge_net")) else "watch",
                    "bucket": edge.get("bucket"),
                    "direction": edge.get("direction"),
                    "edge_score": edge.get("edge_score"),
                    "edge_score_components": edge.get("edge_score_components") if isinstance(edge.get("edge_score_components"), dict) else {},
                    "score": rank[2] if len(rank) > 2 else rank[1],
                    "action_expected_return_net": edge.get("action_expected_return_net"),
                    "action_expected_return_net_ci_lower": edge.get("action_expected_return_net_ci_lower"),
                    "action_expected_return_net_ci_upper": edge.get("action_expected_return_net_ci_upper"),
                    "hit_rate": edge.get("hit_rate"),
                    "hit_ci_lower": edge.get("hit_ci_lower"),
                    "hit_ci_upper": edge.get("hit_ci_upper"),
                    "n": edge.get("n"),
                    "proof_n": edge.get("proof_n"),
                    "proof_window_start": edge.get("proof_window_start"),
                    "proof_window_end": edge.get("proof_window_end"),
                    "fwd_horizon_bars": edge.get("fwd_horizon_bars"),
                    "return_calc_method": edge.get("return_calc_method"),
                    "entry_price_kind": edge.get("entry_price_kind"),
                    "entry_lag_bars": edge.get("entry_lag_bars"),
                    "exit_price_kind": edge.get("exit_price_kind"),
                    "exit_lag_bars": edge.get("exit_lag_bars"),
                    "exit_timing_label": edge.get("exit_timing_label"),
                    "gates": edge.get("gates") if isinstance(edge.get("gates"), dict) else {},
                    "proven_edge_net": edge.get("proven_edge_net"),
                }
            )
    return out


def _sort_signal_candidate_rows(rows: list[dict[str, Any]], body: SignalCandidateRequest) -> list[dict[str, Any]]:
    metric_key = {
        "edge_score": "edge_score",
        "expected_return": "action_expected_return_net",
        "hit_rate": "hit_rate",
        "adv20": "adv20",
        "symbol": "symbol",
    }.get(body.sort_by, "score")
    reverse = body.sort_dir != "asc"

    def metric_value(row: dict[str, Any]) -> Any:
        if metric_key == "symbol":
            return str(row.get("symbol") or "")
        metric = _candidate_float(row.get(metric_key))
        if metric is None and metric_key == "edge_score":
            metric = _candidate_float(row.get("score"))
        if metric is None:
            return -float("inf") if reverse else float("inf")
        return metric

    sorted_rows = sorted(rows, key=metric_value, reverse=reverse)
    return sorted(sorted_rows, key=lambda row: 0 if bool(row.get("eligible")) else 1)


def _build_signal_candidate_rows(db: Session, body: SignalCandidateRequest) -> list[dict[str, Any]]:
    stock_dicts, _symbols = _build_universe_stock_dicts(db, body.timeframe)
    triage_allowed = {str(item).strip().lower() for item in body.triage_filter if str(item).strip()}
    if not triage_allowed:
        triage_allowed = {"proven", "watch"}
    source_allowed = {str(item).strip().lower() for item in body.source_filter or [] if str(item).strip()}
    rows: list[dict[str, Any]] = []

    for stock in stock_dicts:
        symbol = str(stock.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        base_exclusion = _basic_candidate_exclusion(stock, body)
        payloads = _edge_payloads_for_signal_candidate(
            db,
            symbol=symbol,
            horizon=body.horizon,
            cost_bps=body.cost_bps,
        )
        if body.mode == "best" and payloads:
            payloads = [max(payloads, key=lambda item: item.get("_rank") or (0, 0.0, 0.0))]

        for payload in payloads:
            triage = str(payload.get("triage") or "").strip().lower()
            source = str(payload.get("source") or "").strip().lower()
            if triage not in triage_allowed:
                continue
            if source_allowed and source not in source_allowed:
                continue
            exclusion_reason = base_exclusion
            if exclusion_reason is None and not payload.get("direction"):
                exclusion_reason = "No actionable direction."
            row = {
                **stock,
                **{key: value for key, value in payload.items() if key != "_rank"},
                "candidate_id": "",
                "symbol": symbol,
                "eligible": exclusion_reason is None,
                "exclusion_reason": exclusion_reason,
            }
            row["candidate_id"] = _candidate_id_for(row)
            rows.append(row)

    return _sort_signal_candidate_rows(rows, body)


def _extract_enabled_families(stock_config: dict[str, Any]) -> list[str]:
    seen: list[str] = []
    for source in iter_score_sources(stock_config):
        if source.family_id not in seen:
            seen.append(source.family_id)
    return seen


def _score_label_for_source(source_family: str, score: float | None) -> str | None:
    if score is None:
        return None
    value = float(score)
    return signal_type_label(FAMILY_SIGNAL_TYPE.get(source_family, "trend"), value)


def _normalize_indicator_payload(
    indicator: dict[str, Any] | None,
    *,
    family_id: str,
    fallback_name: str,
) -> dict[str, Any] | None:
    if not isinstance(indicator, dict) or indicator.get("type") == "none":
        return None

    payload: dict[str, Any] = {
        "type": indicator.get("type"),
        "name": indicator.get("name", fallback_name),
    }
    for key, value in indicator.items():
        if key in {"type", "name"}:
            continue
        if isinstance(value, np.ndarray):
            payload[key] = [None if not np.isfinite(item) else float(item) for item in value.tolist()]
        else:
            payload[key] = value

    if "obv" in payload and "ema_values" in payload:
        payload["bar_signals"] = [
            "accumulation" if o is not None and e is not None and o > e else
            "distribution" if o is not None and e is not None and o < e else
            "neutral"
            for o, e in zip(payload["obv"], payload["ema_values"])
        ]
        payload["deviation_values"] = [
            None if o is None or e is None or e == 0 else float((float(o) - float(e)) / float(e))
            for o, e in zip(payload["obv"], payload["ema_values"])
        ]
    if "ad" in payload and "ema_values" in payload:
        payload["bar_signals"] = [
            "accumulation" if a is not None and e is not None and a > e else
            "distribution" if a is not None and e is not None and a < e else
            "neutral"
            for a, e in zip(payload["ad"], payload["ema_values"])
        ]
        payload["deviation_values"] = [
            None if a is None or e is None or e == 0 else float((float(a) - float(e)) / abs(float(e)))
            for a, e in zip(payload["ad"], payload["ema_values"])
        ]
    if "macd_line" in payload and "signal_line" in payload:
        crossovers: list[dict[str, Any]] = []
        macd_line = payload["macd_line"]
        signal_line = payload["signal_line"]
        prev_diff: float | None = None
        for index, (macd_value, signal_value) in enumerate(zip(macd_line, signal_line)):
            if macd_value is None or signal_value is None:
                prev_diff = None
                continue
            diff = float(macd_value) - float(signal_value)
            if prev_diff is not None:
                if prev_diff <= 0 < diff:
                    crossovers.append({"bar_index": index, "direction": "bullish"})
                elif prev_diff >= 0 > diff:
                    crossovers.append({"bar_index": index, "direction": "bearish"})
            prev_diff = diff
        payload["crossovers"] = crossovers
    if payload.get("type") == "overlay" and "values" in payload:
        payload["plot_kind"] = "line"
        payload["plot_values"] = payload["values"]
        payload["plot_axis"] = "price"
    elif payload.get("type") == "overlay_dual" and "fast" in payload:
        payload["plot_kind"] = "line"
        payload["plot_values"] = payload["fast"]
        payload["plot_axis"] = "price"
    elif payload.get("type") == "overlay_cloud" and "cloud_top" in payload:
        payload["plot_kind"] = "line"
        payload["plot_values"] = payload["cloud_top"]
        payload["plot_axis"] = "price"
    elif payload.get("type") == "overlay_dots" and "values" in payload:
        payload["plot_kind"] = "dots"
        payload["plot_values"] = payload["values"]
        payload["plot_axis"] = "price"
    elif payload.get("type") == "overlay_band" and "values" in payload:
        payload["plot_kind"] = "line"
        payload["plot_values"] = payload["values"]
        payload["plot_axis"] = "price"
    elif "histogram" in payload:
        payload["plot_kind"] = "histogram"
        payload["plot_values"] = payload["histogram"]
        payload["plot_axis"] = "indicator"
        payload["zero_line"] = 0.0
    elif "deviation_values" in payload:
        payload["plot_kind"] = "line"
        payload["plot_values"] = payload["deviation_values"]
        payload["plot_axis"] = "indicator"
        payload["zero_line"] = 0.0
    elif "adx" in payload:
        payload["plot_kind"] = "line"
        payload["plot_values"] = payload["adx"]
        payload["plot_axis"] = "indicator"
    elif "k" in payload:
        payload["plot_kind"] = "line"
        payload["plot_values"] = payload["k"]
        payload["plot_axis"] = "indicator"
        payload["zero_line"] = 50.0
    elif "values" in payload:
        payload["plot_kind"] = "line"
        payload["plot_values"] = payload["values"]
        payload["plot_axis"] = "indicator"
        if payload.get("zero_line") is True:
            payload["zero_line"] = 0.0
        elif family_id in {"rsi", "mfi", "uo", "stochastic"}:
            payload["zero_line"] = 50.0
    return payload


def _indicator_payload_for_source(
    source: Any,
    close: Any,
    volume: Any,
    *,
    high: Any | None = None,
    low: Any | None = None,
    params_override: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    variant = score_source_variant(source, params_override=params_override)
    indicator = _compute_indicator(close, variant, volume=volume, high=high, low=low)
    return _normalize_indicator_payload(indicator, family_id=source.family_id, fallback_name=source.label)


def _call_indicator_helper(func: Any, detail: Any, close: Any, volume: Any, high: Any | None, low: Any | None) -> Any:
    try:
        signature = inspect.signature(func)
        has_varargs = any(param.kind == inspect.Parameter.VAR_POSITIONAL for param in signature.parameters.values())
        if not has_varargs and len(signature.parameters) <= 3:
            return func(detail, close, volume)
    except (TypeError, ValueError):
        pass
    return func(detail, close, volume, high, low)


def _build_chart_payload(
    db: Session,
    *,
    stock_config: dict[str, Any],
    symbol: str,
    horizon: str,
    timeframe: str,
    cost_bps: float,
    cooldown_bars: int,
    ohlcv: pd.DataFrame,
    frame: pd.DataFrame,
) -> dict[str, Any]:
    close = ohlcv["Close"].astype(float).to_numpy(dtype="float64")
    high = ohlcv["High"].astype(float).to_numpy(dtype="float64") if "High" in ohlcv.columns else None
    low = ohlcv["Low"].astype(float).to_numpy(dtype="float64") if "Low" in ohlcv.columns else None
    volume = ohlcv["Volume"].astype(float).to_numpy(dtype="float64") if "Volume" in ohlcv.columns else None
    bars: list[dict[str, Any]] = []
    for index, row in ohlcv.iterrows():
        bars.append(
            {
                "date": str(index)[:10],
                "open": _safe_float(row.get("Open")),
                "high": _safe_float(row.get("High")),
                "low": _safe_float(row.get("Low")),
                "close": _safe_float(row.get("Close")),
                "volume": _safe_float(row.get("Volume")) if "Volume" in ohlcv.columns else None,
            }
        )

    sources_payload: list[dict[str, Any]] = []
    for source in iter_score_sources(stock_config):
        wfo_param_names = source_wfo_param_names(source)
        source_payload = {
            "score_key": source.score_key,
            "label": source.label,
            "family": source.family_id,
            "source_kind": source.source_kind,
            "source_mode_label": "Family score" if source.source_kind == "family_ensemble" else ("WFO range" if source_has_wfo_params(source) else "Specific setup"),
            "scores": [round(float(v), 2) for v in frame[source.score_key].fillna(0.0).tolist()] if source.score_key in frame.columns else [],
            "wfo_param_names": wfo_param_names,
            "wfo_range_active": bool(wfo_param_names),
        }
        if source.source_kind == "family_ensemble":
            detail = _get_or_compute(db, source.family_id, symbol, horizon, timeframe, cost_bps, cooldown_bars)
            reps = _call_indicator_helper(_get_all_representative_indicators, detail, close, volume, high, low)
            source_payload["representatives"] = [
                {
                    **rep,
                    "indicator": _normalize_indicator_payload(
                        rep.get("indicator"),
                        family_id=source.family_id,
                        fallback_name=str(rep.get("label") or source.label),
                    ),
                }
                for rep in reps
            ]
            source_payload["indicator"] = _normalize_indicator_payload(
                _call_indicator_helper(_get_top_representative_indicator, detail, close, volume, high, low),
                family_id=source.family_id,
                fallback_name=source.label,
            )
            source_payload["wfo_start_indicator"] = None
            source_payload["wfo_end_indicator"] = None
        else:
            source_payload["representatives"] = []
            source_payload["indicator"] = _indicator_payload_for_source(source, close, volume, high=high, low=low)
            if wfo_param_names:
                source_payload["wfo_start_indicator"] = _indicator_payload_for_source(
                    source,
                    close,
                    volume,
                    high=high,
                    low=low,
                    params_override=source_params_bundle(source, boundary="start"),
                )
                source_payload["wfo_end_indicator"] = _indicator_payload_for_source(
                    source,
                    close,
                    volume,
                    high=high,
                    low=low,
                    params_override=source_params_bundle(source, boundary="end"),
                )
            else:
                source_payload["wfo_start_indicator"] = None
                source_payload["wfo_end_indicator"] = None
        sources_payload.append(source_payload)
    return {
        "symbol": symbol,
        "horizon": horizon,
        "bars": bars,
        "sources": sources_payload,
    }


def _preview_score_bundle(
    db: Session,
    *,
    stock_config: dict[str, Any],
    symbol: str,
    horizon: str,
    timeframe: str,
    cost_bps: float,
    cooldown_bars: int,
    family_history_mode: str = "static_current_reps",
) -> tuple[dict[str, float | None], list[dict[str, Any]], dict[str, Any], list[dict[str, str]]]:
    preview_key = "__PREVIEW__"
    migrated = migrate_strategy_config_v2(
        {
            "schema_version": 3,
            "app_domain": "four_pages",
            "stocks": {preview_key: stock_config},
            "portfolio": {
                "universe": {"basket": [preview_key]},
                "allocation": {},
                "total_capital_mad": 0,
            },
        },
        horizon=horizon,
    )
    stocks = migrated.get("stocks") if isinstance(migrated.get("stocks"), dict) else {}
    portfolio = migrated.get("portfolio") if isinstance(migrated.get("portfolio"), dict) else {}
    universe = portfolio.get("universe") if isinstance(portfolio.get("universe"), dict) else {}
    basket = [str(item).strip() for item in list(universe.get("basket") or []) if str(item).strip()]
    preview_candidates = [preview_key, preview_key.upper(), *basket]
    canonical = next((stocks.get(candidate) for candidate in preview_candidates if isinstance(stocks.get(candidate), dict)), None)
    if canonical is None and len(stocks) == 1:
        only_stock = next(iter(stocks.values()))
        canonical = only_stock if isinstance(only_stock, dict) else None
    if canonical is None:
        raise HTTPException(status_code=422, detail="Unable to resolve preview stock configuration.")
    ohlcv = load_ohlcv_for_symbol(db, symbol, timeframe)
    ohlcv = _truncate_for_horizon(ohlcv, horizon)
    ohlcv = _clean_ohlcv(ohlcv)
    if ohlcv.empty:
        raise HTTPException(status_code=422, detail=f"No usable OHLCV rows for {symbol}")
    frame = compute_strategy_score_frame(
        stock_config=canonical,
        ohlcv=ohlcv,
        symbol=symbol,
        horizon=horizon,
        timeframe=timeframe,
        signal_cost_bps=cost_bps,
        cooldown_bars=cooldown_bars,
        family_history_mode=family_history_mode,
    )
    last_row = frame.iloc[-1] if not frame.empty else pd.Series(dtype="float64")
    snapshot = {column: float(last_row[column]) for column in frame.columns}

    # For family_ensemble sources, use the authoritative score from the signal
    # page pipeline (_get_or_compute) instead of the timeseries last-bar value,
    # which can diverge slightly due to different weighting code paths.
    family_ensemble_scores: dict[str, tuple[float, str | None]] = {}
    for source in iter_score_sources(canonical):
        if source.source_kind == "family_ensemble":
            try:
                detail = _get_or_compute(db, source.family_id, symbol, horizon, timeframe, cost_bps, cooldown_bars)
                if not family_signal_is_available(detail.signal):
                    continue
                family_ensemble_scores[source.score_key] = (
                    detail.signal.family_score_pct,
                    _score_label_for_source(source.family_id, detail.signal.family_score_pct),
                )
            except HTTPException:
                pass

    active_scores = [
        {
            "score_key": source.score_key,
            "label": source.label,
            "family": source.family_id,
            "source_kind": source.source_kind,
            "score": round(family_ensemble_scores[source.score_key][0], 4)
                if source.score_key in family_ensemble_scores
                else (round(float(snapshot.get(source.score_key, 0.0)), 4) if source.score_key in snapshot else None),
            "signal_label": family_ensemble_scores[source.score_key][1]
                if source.score_key in family_ensemble_scores
                else _score_label_for_source(source.family_id, snapshot.get(source.score_key)),
        }
        for source in iter_score_sources(canonical)
        if source.score_key in snapshot or source.score_key in family_ensemble_scores
    ]
    chart = _build_chart_payload(
        db,
        stock_config=canonical,
        symbol=symbol,
        horizon=horizon,
        timeframe=timeframe,
        cost_bps=cost_bps,
        cooldown_bars=cooldown_bars,
        ohlcv=ohlcv,
        frame=frame,
    )
    return snapshot, active_scores, chart, score_variable_catalog(canonical)


def _latest_score_snapshot(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    timeframe: str,
    stock_config: dict[str, Any],
    cost_bps: float,
    cooldown_bars: int,
    family_history_mode: str = "static_current_reps",
) -> dict[str, float | None]:
    snapshot, _active_scores, _chart, _catalog = _preview_score_bundle(
        db,
        stock_config=stock_config,
        symbol=symbol,
        horizon=horizon,
        timeframe=timeframe,
        cost_bps=cost_bps,
        cooldown_bars=cooldown_bars,
        family_history_mode=family_history_mode,
    )
    return snapshot


def _latest_rule_preview_context(
    db: Session,
    *,
    symbol: str,
    horizon: str,
    timeframe: str,
    stock_config: dict[str, Any],
    cost_bps: float,
    cooldown_bars: int,
) -> tuple[dict[str, float], pd.DataFrame | None, int | None]:
    score_snapshot = _latest_score_snapshot(
        db,
        symbol=symbol,
        horizon=horizon,
        timeframe=timeframe,
        stock_config=stock_config,
        cost_bps=cost_bps,
        cooldown_bars=cooldown_bars,
    )
    bars = load_ohlcv_for_symbol(db, symbol, timeframe)
    bars = _truncate_for_horizon(bars, horizon)
    bars = _clean_ohlcv(bars)
    if bars.empty:
        return build_rule_snapshot(score_snapshot), None, None
    index = len(bars.index) - 1
    return build_rule_snapshot(score_snapshot, bars=bars, index=index), bars, index


def _build_rule_preview_rows(
    rules: list[Any],
    snapshot: dict[str, float],
    *,
    bars: pd.DataFrame | None = None,
    index: int | None = None,
) -> list[RulePreviewRow]:
    out: list[RulePreviewRow] = []
    bar_index = index
    for rule_index, raw_rule in enumerate(rules):
        rule = raw_rule if isinstance(raw_rule, dict) else {}
        out.append(
            RulePreviewRow(
                id=str(rule.get("id") or f"rule_{rule_index + 1}"),
                label=str(rule.get("label") or f"Rule {rule_index + 1}"),
                config_option=str(rule.get("config_option") or "A"),
                condition_count=rule_condition_count(rule),
                triggered=rule_triggered(snapshot, rule, bars=bars, index=bar_index),
                conditions=describe_rule_conditions(rule),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/universe")
def get_universe(
    body: UniverseFilterRequest,
    db: Session = Depends(get_db),
) -> list[UniverseStockOut]:
    """Filter stock universe by data availability, signal strength, and sector."""

    # 1. Load all active stocks from StockMaster plus equity rows that already
    # exist in MarketDataStore. The latter prevents an empty strategy universe
    # when data has been ingested but the registry has not been backfilled yet.
    stock_dicts, symbols = _build_universe_stock_dicts(db, body.timeframe)

    # 2. Compute signal scores for all symbols
    signal_scores = _compute_batch_scores(
        db, symbols, body.horizon, body.timeframe,
        body.cost_bps, body.cooldown_bars,
    )

    # 3. Filter universe
    enriched = filter_universe(
        stock_dicts,
        signal_scores,
        min_bars=body.min_bars,
        min_abs_signal=body.min_abs_signal,
        min_adv20=body.min_adv20,
        sector_filter=body.sector_filter,
        sort_by=body.sort_by,
        sort_dir=body.sort_dir,
    )

    return [UniverseStockOut(**item) for item in enriched]


@router.post("/signal-candidates")
def get_signal_candidates(
    body: SignalCandidateRequest,
    db: Session = Depends(get_db),
) -> list[SignalCandidateOut]:
    """Return edge-qualified dashboard signals for strategy-universe selection."""

    return [SignalCandidateOut(**item) for item in _build_signal_candidate_rows(db, body)]


@router.post("/allocation")
def get_strategy_allocation(
    body: StrategyAllocationRequest,
    db: Session = Depends(get_db),
) -> StrategyAllocationOut:
    """Compute HRP-based stock allocation with optional manual overrides."""

    price_history: dict[str, pd.Series] = {}
    for symbol in body.symbols:
        try:
            ohlcv = load_ohlcv_for_symbol(db, symbol, body.timeframe)
            ohlcv = _clean_ohlcv(ohlcv)
            if not ohlcv.empty and "Close" in ohlcv.columns:
                price_history[symbol] = ohlcv["Close"].astype(float)
        except Exception:
            logger.debug("Allocation history unavailable for %s", symbol, exc_info=True)

    allocation = compute_strategy_allocation(
        symbols=body.symbols,
        total_capital_mad=body.total_capital_mad,
        price_history=price_history,
        manual_overrides_by_symbol=body.manual_overrides_by_symbol,
        lookback_bars=body.lookback_bars,
    )

    return StrategyAllocationOut(
        rows=[StrategyAllocationRowOut(**row) for row in allocation["rows"]],
        total_capital_mad=allocation["total_capital_mad"],
        allocated_capital_mad=allocation["allocated_capital_mad"],
        remaining_capital_mad=allocation["remaining_capital_mad"],
        explain=allocation["explain"],
    )


@router.post("/levels")
def get_levels(
    body: LevelsRequest,
    db: Session = Depends(get_db),
) -> LevelsOut:
    """Compute swing-based support/resistance, ATR, and pivot points for a symbol."""

    try:
        ohlcv = load_ohlcv_for_symbol(db, body.symbol, body.timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    ohlcv = _truncate_for_horizon(ohlcv, body.horizon)
    ohlcv = _clean_ohlcv(ohlcv)

    if ohlcv.empty or len(ohlcv) < 3:
        raise HTTPException(
            status_code=422,
            detail=f"Insufficient data for {body.symbol}: {len(ohlcv)} bars after cleaning.",
        )

    high = ohlcv["High"].values.astype("float64")
    low = ohlcv["Low"].values.astype("float64")
    close = ohlcv["Close"].values.astype("float64")
    idx = ohlcv.index
    policy = _resolve_execution_policy(
        body.horizon,
        body.timeframe,
        execution_holding_bars=body.execution_holding_bars,
    )
    left_bars = body.left_bars if body.left_bars is not None else policy.swing_left_bars
    right_bars = body.right_bars if body.right_bars is not None else policy.swing_right_bars
    max_levels = body.max_levels if body.max_levels is not None else policy.max_levels
    lookback = body.lookback if body.lookback is not None else policy.structural_lookback
    body.left_bars = left_bars
    body.right_bars = right_bars
    body.max_levels = max_levels
    body.lookback = lookback

    # S/R detection
    sr = detect_swing_levels(
        high, low, close,
        left_bars=left_bars,
        right_bars=right_bars,
        max_levels=max_levels,
        lookback=lookback,
        max_distance_atr=policy.max_level_distance_atr,
    )

    # Enrich with dates
    def _enrich_level(level: dict) -> SRLevel:
        bi = level["bar_index"]
        date_str = str(idx[bi])[:10] if 0 <= bi < len(idx) else None
        return SRLevel(
            price=level["price"],
            bar_index=bi,
            date=date_str,
            strength=level.get("strength", 0),
        )

    supports = [_enrich_level(s) for s in sr["supports"]]
    resistances = [_enrich_level(r) for r in sr["resistances"]]

    # ATR
    atr_abs, atr_ratio = compute_atr(high, low, close, window=14)

    # Pivot points from previous session (second-to-last bar)
    pivot = None
    if len(ohlcv) >= 2:
        prev = ohlcv.iloc[-2]
        pivot = PivotPoints(**compute_pivot_points(
            prev_high=float(prev["High"]),
            prev_low=float(prev["Low"]),
            prev_close=float(prev["Close"]),
        ))

    n_sup = len(supports)
    n_res = len(resistances)
    explain = (
        f"{n_sup} support(s) et {n_res} résistance(s) détectés "
        f"sur les {body.lookback} dernières barres "
        f"(pivot {body.left_bars}L/{body.right_bars}R). "
        f"ATR(14) = {atr_abs:.2f} ({atr_ratio*100:.2f}%)."
    )

    return LevelsOut(
        symbol=body.symbol,
        current_close=sr["current_close"],
        atr_14=round(atr_abs, 4),
        atr_pct=round(atr_ratio, 6),
        supports=supports,
        resistances=resistances,
        nearest_support=sr["nearest_support"],
        nearest_resistance=sr["nearest_resistance"],
        pivot=pivot,
        explain=explain,
    )


# ---------------------------------------------------------------------------
# Signal Consensus
# ---------------------------------------------------------------------------

@router.post("/signal-consensus")
def get_signal_consensus(
    body: SignalConsensusRequest,
    db: Session = Depends(get_db),
) -> SignalConsensusOut:
    """Compute weighted consensus across enabled signal families for a symbol."""

    if not body.enabled_families:
        return SignalConsensusOut(
            symbol=body.symbol,
            final_consensus=None,
            final_consensus_label=None,
            enabled_families=[],
            explain="Aucune famille active.",
        )

    # Compute per-family scores (reuses 5-min TTL cache)
    per_family_scores: dict[str, float] = {}
    per_family_labels: dict[str, str] = {}
    for family in body.enabled_families:
        try:
            detail = _get_or_compute(
                db, family, body.symbol, body.horizon,
                body.timeframe, body.cost_bps, body.cooldown_bars,
            )
            if not family_signal_is_available(detail.signal):
                continue
            per_family_scores[family] = detail.signal.family_score_pct
            per_family_labels[family] = detail.signal.family_signal_label
        except HTTPException:
            logger.warning("Signal computation failed for %s/%s", family, body.symbol)

    # Compute consensus
    result = compute_consensus(per_family_scores, body.enabled_families)

    # Build per-family output with labels
    per_family_out: dict[str, FamilyScoreOut] = {}
    for f, info in result["per_family"].items():
        per_family_out[f] = FamilyScoreOut(
            score_pct=info["score_pct"],
            label=per_family_labels.get(f, "N/A"),
            weight=info["weight"],
        )

    consensus = result["final_consensus"]
    consensus_label = _score_to_label(consensus) if consensus is not None else None

    n_active = len(result["family_weights"])
    n_enabled = len(body.enabled_families)
    explain = (
        f"Consensus calculé sur {n_active}/{n_enabled} famille(s) active(s) "
        f"avec pondération égale."
    )

    return SignalConsensusOut(
        symbol=body.symbol,
        final_consensus=consensus,
        final_consensus_label=consensus_label,
        enabled_families=body.enabled_families,
        family_weights=result["family_weights"],
        per_family=per_family_out,
        explain=explain,
    )


@router.post("/signal-construction/preview")
def preview_signal_construction(
    body: SignalConstructionPreviewRequest,
    db: Session = Depends(get_db),
) -> SignalConstructionPreviewOut:
    snapshot, active_scores, chart, variable_catalog = _preview_score_bundle(
        db,
        stock_config=body.stock_config if isinstance(body.stock_config, dict) else {},
        symbol=body.symbol,
        horizon=body.horizon,
        timeframe=body.timeframe,
        cost_bps=body.cost_bps,
        cooldown_bars=body.cooldown_bars,
        family_history_mode=body.family_history_mode,
    )
    return SignalConstructionPreviewOut(
        active_scores=active_scores,
        score_snapshot=snapshot,
        variable_catalog=variable_catalog,
        zone_chart=chart,
        explain="Preview reflects the active signal-construction sources exactly as configured for this stock.",
    )


@router.post("/entry-rules/preview")
def preview_entry_rules(
    body: RulePreviewRequest,
    db: Session = Depends(get_db),
) -> RulePreviewOut:
    stock_config = body.stock_config if isinstance(body.stock_config, dict) else {}
    snapshot, bars, bar_index = _latest_rule_preview_context(
        db,
        symbol=body.symbol,
        horizon=body.horizon,
        timeframe=body.timeframe,
        stock_config=stock_config,
        cost_bps=body.cost_bps,
        cooldown_bars=body.cooldown_bars,
    )
    rules = list((stock_config.get("entry_rules") if isinstance(stock_config, dict) else []) or [])
    return RulePreviewOut(
        symbol=body.symbol,
        score_snapshot=snapshot,
        rules=_build_rule_preview_rows(rules, snapshot, bars=bars, index=bar_index),
        explain="Preview evaluates the latest score and price context against the configured entry rules.",
    )


@router.post("/exit-rules/preview")
def preview_exit_rules(
    body: RulePreviewRequest,
    db: Session = Depends(get_db),
) -> RulePreviewOut:
    stock_config = body.stock_config if isinstance(body.stock_config, dict) else {}
    snapshot, bars, bar_index = _latest_rule_preview_context(
        db,
        symbol=body.symbol,
        horizon=body.horizon,
        timeframe=body.timeframe,
        stock_config=stock_config,
        cost_bps=body.cost_bps,
        cooldown_bars=body.cooldown_bars,
    )
    rules = list((stock_config.get("exit_rules") if isinstance(stock_config, dict) else []) or [])
    return RulePreviewOut(
        symbol=body.symbol,
        score_snapshot=snapshot,
        rules=_build_rule_preview_rows(rules, snapshot, bars=bars, index=bar_index),
        explain="Preview evaluates the latest score and price context against the configured exit rules.",
    )


@router.post("/risk/preview")
def preview_risk(
    body: RiskPreviewRequest,
    db: Session = Depends(get_db),
) -> RiskPreviewOut:
    try:
        ohlcv = load_ohlcv_for_symbol(db, body.symbol, body.timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    ohlcv = _truncate_for_horizon(ohlcv, body.horizon)
    ohlcv = _clean_ohlcv(ohlcv)
    if ohlcv.empty or len(ohlcv) < 3:
        raise HTTPException(status_code=422, detail=f"Insufficient data for {body.symbol}: {len(ohlcv)} bars.")

    high = ohlcv["High"].values.astype("float64")
    low = ohlcv["Low"].values.astype("float64")
    close = ohlcv["Close"].values.astype("float64")
    current_close = float(close[-1])
    atr_14, _ = compute_atr(high, low, close, window=14)
    risk = body.stock_config.get("risk") if isinstance(body.stock_config, dict) and isinstance(body.stock_config.get("risk"), dict) else {}
    stop_loss = risk.get("stop_loss") if isinstance(risk.get("stop_loss"), dict) else {}
    take_profit = risk.get("take_profit") if isinstance(risk.get("take_profit"), dict) else {}
    time_stop = risk.get("time_stop") if isinstance(risk.get("time_stop"), dict) else {}

    stop_price = None
    if str(stop_loss.get("mode") or "atr_based") == "manual_pct":
        stop_price = current_close * (1 - float(stop_loss.get("manual_pct") or 0.02))
    else:
        atr_multiplier = ((stop_loss.get("atr_multiplier") or {}).get("value") if isinstance(stop_loss.get("atr_multiplier"), dict) else 1.5) or 1.5
        stop_price = current_close - float(atr_14 or 0.0) * float(atr_multiplier)

    target_price = None
    if str(take_profit.get("mode") or "rr_target") == "manual_pct":
        target_price = current_close * (1 + float(take_profit.get("manual_pct") or 0.03))
    else:
        rr_ratio = ((take_profit.get("rr_ratio") or {}).get("value") if isinstance(take_profit.get("rr_ratio"), dict) else 1.5) or 1.5
        target_price = current_close + (current_close - float(stop_price or current_close)) * float(rr_ratio)

    return RiskPreviewOut(
        symbol=body.symbol,
        current_close=current_close,
        atr_14=atr_14,
        stop_loss=stop_price,
        take_profit=target_price,
        rr_ratio=((target_price - current_close) / max(current_close - float(stop_price or current_close), 1e-9)) if stop_price is not None and target_price is not None else None,
        cooldown_bars=int(((risk.get("cooldown_bars") or {}).get("value") if isinstance(risk.get("cooldown_bars"), dict) else 0) or 0),
        time_stop_bars=int(((time_stop.get("bars") or {}).get("value") if isinstance(time_stop.get("bars"), dict) else 0) or 0) if bool(time_stop.get("enabled", True)) else None,
        explain="Preview estimates stop, target, cooldown, and time-stop from the current risk configuration.",
    )


# ---------------------------------------------------------------------------
# Execution Plan
# ---------------------------------------------------------------------------

@router.post("/execution")
def get_execution_plan(
    body: ExecutionRequest,
    db: Session = Depends(get_db),
) -> ExecutionPlanOut:
    """Compute execution plan (entry zone, stop, targets, R:R) for a symbol."""

    # 1. Consensus — use override or compute
    if body.consensus_override is not None:
        consensus = body.consensus_override
    else:
        per_family_scores: dict[str, float] = {}
        for family in body.enabled_families:
            try:
                detail = _get_or_compute(
                    db, family, body.symbol, body.horizon,
                    body.timeframe, body.cost_bps, body.cooldown_bars,
                )
                if not family_signal_is_available(detail.signal):
                    continue
                per_family_scores[family] = detail.signal.family_score_pct
            except HTTPException:
                logger.warning("Signal failed for %s/%s", family, body.symbol)

        from core.quant_core.strategy_plan.signal_policy import compute_consensus as _cc
        result = _cc(per_family_scores, body.enabled_families)
        consensus = result["final_consensus"]

    # 2. Levels — reuse existing logic
    try:
        ohlcv = load_ohlcv_for_symbol(db, body.symbol, body.timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    ohlcv = _truncate_for_horizon(ohlcv, body.horizon)
    ohlcv = _clean_ohlcv(ohlcv)

    if ohlcv.empty or len(ohlcv) < 3:
        raise HTTPException(
            status_code=422,
            detail=f"Insufficient data for {body.symbol}: {len(ohlcv)} bars.",
        )

    high = ohlcv["High"].values.astype("float64")
    low = ohlcv["Low"].values.astype("float64")
    close = ohlcv["Close"].values.astype("float64")
    policy = _resolve_execution_policy(
        body.horizon,
        body.timeframe,
        execution_holding_bars=body.execution_holding_bars,
    )

    sr = detect_swing_levels(
        high,
        low,
        close,
        left_bars=policy.swing_left_bars,
        right_bars=policy.swing_right_bars,
        max_levels=policy.max_levels,
        lookback=policy.structural_lookback,
        max_distance_atr=policy.max_level_distance_atr,
    )
    atr_abs, _ = compute_atr(high, low, close, window=14)

    # 3. Compute execution plan
    plan = compute_execution_plan(
        consensus=consensus,
        side_policy=body.side_policy,
        nearest_support=sr["nearest_support"],
        nearest_resistance=sr["nearest_resistance"],
        supports=sr["supports"],
        resistances=sr["resistances"],
        atr=atr_abs,
        current_close=sr["current_close"],
        entry_threshold=body.entry_threshold,
        atr_multiplier=body.atr_multiplier,
        buffer_pct=body.buffer_pct,
        min_rr=body.min_rr,
        holding_bars=policy.holding_bars,
    )

    return ExecutionPlanOut(symbol=body.symbol, **plan)


# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------

@router.post("/sizing")
def get_sizing(body: SizingRequest) -> SizingOut:
    """Compute Kelly ceiling + portfolio allocation across basket stocks."""

    stock_dicts = [s.model_dump() for s in body.stocks]

    # Portfolio allocation
    alloc = compute_portfolio_allocation(
        stocks=stock_dicts,
        method=body.allocation_method,
        max_position_pct=body.max_position_pct,
        max_sector_pct=body.max_sector_pct,
        account_equity=body.account_equity,
        kelly_modifier=body.kelly_modifier,
        win_rate=body.win_rate,
        avg_wl_ratio=body.avg_wl_ratio,
    )

    # Focused Kelly (for the selected stock)
    focused_kelly = None
    if body.focused_symbol:
        for s in stock_dicts:
            if s["symbol"] == body.focused_symbol and s.get("entry_price") and s.get("stop_price"):
                kelly = compute_kelly_ceiling(
                    win_rate=body.win_rate,
                    avg_wl_ratio=body.avg_wl_ratio,
                    modifier=body.kelly_modifier,
                    entry_price=s["entry_price"],
                    stop_price=s["stop_price"],
                    account_equity=body.account_equity,
                )
                focused_kelly = FocusedKellyOut(**kelly)
                break

    return SizingOut(
        focused_kelly=focused_kelly,
        portfolio_table=[StockSizingRow(**row) for row in alloc["portfolio_table"]],
        total_exposure_pct=alloc["total_exposure_pct"],
        total_risk_pct=alloc["total_risk_pct"],
        capital_deployed=alloc["capital_deployed"],
        explain=alloc["explain"],
    )


# ---------------------------------------------------------------------------
# Saved Strategy CRUD
# ---------------------------------------------------------------------------

def _strategy_to_list_item(row: models.SavedStrategy) -> SavedStrategyListItem:
    basket = get_basket_from_strategy_config(row.config_json or {}, horizon=row.horizon)
    return SavedStrategyListItem(
        id=str(row.id),
        name=row.name,
        status=row.status,
        side_policy=row.side_policy,
        horizon=row.horizon,
        basket_count=len(basket),
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
    )


def _strategy_to_out(row: models.SavedStrategy) -> SavedStrategyOut:
    return SavedStrategyOut(
        id=str(row.id),
        name=row.name,
        note=row.note,
        status=row.status,
        side_policy=row.side_policy,
        horizon=row.horizon,
        config_json=row.config_json or {},
        created_at=row.created_at.isoformat() if row.created_at else "",
        updated_at=row.updated_at.isoformat() if row.updated_at else "",
    )


@router.get("/strategies")
def list_strategies(
    status: str | None = None,
    db: Session = Depends(get_db),
) -> list[SavedStrategyListItem]:
    """List saved strategies, optionally filtered by status."""
    q = db.query(models.SavedStrategy)
    if status:
        q = q.filter(models.SavedStrategy.status == status)
    else:
        q = q.filter(models.SavedStrategy.status != "archived")
    rows = q.order_by(models.SavedStrategy.updated_at.desc()).all()
    return [_strategy_to_list_item(r) for r in rows]


@router.get("/strategies/{strategy_id}")
def get_strategy(
    strategy_id: str,
    db: Session = Depends(get_db),
) -> SavedStrategyOut:
    """Get a single saved strategy with full config."""
    row = db.query(models.SavedStrategy).filter(
        models.SavedStrategy.id == strategy_id,
    ).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return _strategy_to_out(row)


@router.post("/backtest")
def backtest_strategy(
    body: StrategyBacktestRequest,
    db: Session = Depends(get_db),
) -> StrategyBacktestResponse:
    """Run a direct backtest for one saved strategy over a fixed date range."""
    row = db.query(models.SavedStrategy).filter(
        models.SavedStrategy.id == body.strategy_id,
    ).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")

    source_config_json = row.config_json or {}
    basket = get_basket_from_strategy_config(source_config_json, horizon=row.horizon)
    if not basket:
        raise HTTPException(status_code=422, detail="Saved strategy has an empty basket.")

    try:
        config_json = build_legacy_backtest_config_from_v2(source_config_json, horizon=row.horizon)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    bars_by_symbol: dict[str, pd.DataFrame] = {}
    missing_symbols: list[str] = []
    for symbol in basket:
        try:
            ohlcv = load_ohlcv_for_symbol(db, symbol, body.timeframe)
        except ValueError:
            missing_symbols.append(symbol)
            continue
        ohlcv = _clean_ohlcv(ohlcv)
        if ohlcv.empty:
            missing_symbols.append(symbol)
            continue
        bars_by_symbol[symbol] = ohlcv

    if not bars_by_symbol:
        raise HTTPException(
            status_code=422,
            detail="No basket symbols have usable market data for this backtest.",
        )

    try:
        result = run_strategy_plan_backtest(
            strategy_id=str(row.id),
            strategy_name=row.name,
            side_policy=row.side_policy,
            horizon=row.horizon,
            timeframe=body.timeframe,
            config_json=config_json,
            bars_by_symbol=bars_by_symbol,
            start_date=body.start_date,
            end_date=body.end_date,
            cost_model_raw=body.cost_model.model_dump(),
            volume_gate=body.volume_gate.model_dump(),
            cooldown_bars=body.cooldown_bars,
            family_history_mode=body.family_history_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception(
            "strategy backtest failed during response build",
            extra={
                "strategy_id": body.strategy_id,
                "start_date": body.start_date,
                "end_date": body.end_date,
            },
        )
        raise HTTPException(status_code=500, detail="Strategy backtest failed unexpectedly.") from exc

    assumptions = dict(result.get("assumptions") or {})
    existing_missing = list(assumptions.get("skipped_symbols") or [])
    assumptions["missing_symbols"] = sorted(set(existing_missing + missing_symbols))
    result["assumptions"] = assumptions
    try:
        return StrategyBacktestResponse(**result)
    except Exception as exc:
        logger.exception(
            "strategy backtest response serialization failed",
            extra={
                "strategy_id": body.strategy_id,
                "start_date": body.start_date,
                "end_date": body.end_date,
            },
        )
        raise HTTPException(status_code=500, detail="Strategy backtest response could not be serialized.") from exc


@router.post("/strategies", status_code=201)
def create_strategy(
    body: SavedStrategyCreate,
    db: Session = Depends(get_db),
) -> SavedStrategyOut:
    """Create a new strategy."""
    row = models.SavedStrategy(
        name=body.name,
        note=body.note,
        side_policy=body.side_policy,
        horizon=body.horizon,
        status="draft",
        config_json={},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _strategy_to_out(row)


@router.put("/strategies/{strategy_id}")
def update_strategy(
    strategy_id: str,
    body: SavedStrategyUpdate,
    db: Session = Depends(get_db),
) -> SavedStrategyOut:
    """Update a strategy's config or metadata."""
    row = db.query(models.SavedStrategy).filter(
        models.SavedStrategy.id == strategy_id,
    ).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(row, key, value)

    db.commit()
    db.refresh(row)
    return _strategy_to_out(row)


@router.post("/strategies/{strategy_id}/duplicate", status_code=201)
def duplicate_strategy(
    strategy_id: str,
    db: Session = Depends(get_db),
) -> SavedStrategyOut:
    """Duplicate a strategy."""
    original = db.query(models.SavedStrategy).filter(
        models.SavedStrategy.id == strategy_id,
    ).one_or_none()
    if not original:
        raise HTTPException(status_code=404, detail="Strategy not found")

    copy = models.SavedStrategy(
        name=f"{original.name} (copie)",
        note=original.note,
        side_policy=original.side_policy,
        horizon=original.horizon,
        status="draft",
        config_json=dict(original.config_json or {}),
    )
    db.add(copy)
    db.commit()
    db.refresh(copy)
    return _strategy_to_out(copy)


@router.patch("/strategies/{strategy_id}/archive")
def archive_strategy(
    strategy_id: str,
    db: Session = Depends(get_db),
) -> SavedStrategyOut:
    """Toggle archive status on a strategy."""
    row = db.query(models.SavedStrategy).filter(
        models.SavedStrategy.id == strategy_id,
    ).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")

    if row.status == "archived":
        row.status = "draft"
        row.archived_at = None
    else:
        row.status = "archived"
        from sqlalchemy.sql import func as sqlfunc
        row.archived_at = sqlfunc.now()

    db.commit()
    db.refresh(row)
    return _strategy_to_out(row)


@router.post("/review")
def review_strategy_config(body: ReviewRequest) -> ReviewOut:
    review = build_strategy_review(body.config_json or {}, horizon=body.horizon)
    review.pop("canonical_config", None)
    return ReviewOut(**review)


@router.post("/strategies/{strategy_id}/handoff")
def strategy_handoff(
    strategy_id: str,
    db: Session = Depends(get_db),
) -> HandoffOut:
    try:
        strategy_key = UUID(strategy_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Strategy not found")

    row = db.query(models.SavedStrategy).filter(
        models.SavedStrategy.id == strategy_key,
    ).one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Strategy not found")

    handoff = build_strategy_handoff(
        strategy_id=str(row.id),
        strategy_name=row.name,
        raw=row.config_json or {},
        horizon=row.horizon,
    )
    return HandoffOut(**handoff)
