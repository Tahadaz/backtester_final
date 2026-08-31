"""Six-vintage B/M + CF/P live-like strategy snapshot -- the production entrypoint for
core.quant_core.fundamentals.cross_section.live_like_strategy (2026-07-06 research:
RESEARCH ONLY -- UNVALIDATED, not proven alpha and not production-ready trading).

This is a genuinely heavy computation (full daily price-history load + vintage backtest over
~9 years), so unlike value_signal.py it is NOT computed per-request. It follows the exact same
"compute once, persist, serve read-only" pattern as
services/api/app/services/fundamental_cross_section.py's SFC backtest snapshot
(fundamental_sfc_backtest_snapshot table) -- see FundamentalValueStrategySnapshot in models.py.

Recomputation is triggered by POST /value-strategy/recompute (enqueues an async RQ job via
services/worker/tasks/value_strategy.py, mirroring the SFC backtest's job pattern exactly) or
by the weekly_value_strategy_refresh scheduled job (services/api/app/services/
scheduler_registry.py). scripts/seed_value_strategy_snapshot.py remains available for a
one-off manual seed/backfill.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
from dataclasses import asdict, replace
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from core.quant_core.fundamentals.cross_section.live_like_strategy import (
    LiveLikeConfig,
    TRUSTED_UNIVERSE_EXCLUSIONS,
    VINTAGE_LIFE_MONTHS,
    attach_point_in_time_adv,
    build_trade_ledger,
    build_vintage_holdings_by_date,
    combine_sleeves,
    eligibility_mask,
    run_vintage_backtest,
    run_capacity_constrained_backtest,
    summarize_performance,
)
from core.quant_core.fundamentals.cross_section.portfolio_backtest import _pit_price
from core.quant_core.fundamentals.cross_section.production_readiness import current_repository_readiness
from core.quant_core.fundamentals.cross_section.market_equity import decision_date_market_equity

from .. import models
from ..json_sanitize import sanitize_json_compatible
from ..market_data_loader import load_close_series_from_store
from .value_signal import compute_value_signal_frame

VALUE_STRATEGY_METHODOLOGY_VERSION = "structural_value_six_vintage_v2_1_liquidity_2026_08_30"
VALUE_STRATEGY_RESEARCH_STATUS = "RESEARCH ONLY — UNVALIDATED"
RECOMMENDED_ARCHITECTURE = "S1_bm"

# Model version: identifies the FROZEN methodology (canonical B/M, canonical CF/P, trusted-
# universe exclusions, six-vintage architecture, cost policy) -- not a runtime timestamp. Bump
# this only when the methodology itself changes (e.g. a new canonical definition, a new
# exclusion policy). Distinct from `computed_at` (when this particular snapshot ran) and from
# `config_hash` (a hash of the below, used for DB lookups).
MODEL_VERSION = "Fundamental Value Strategy v2.1"

DEFAULT_LIQUIDITY_SETTINGS: dict[str, Any] = {
    "liquidity_enabled": True,
    "portfolio_nav_mad": 10_000_000.0,
    "min_order_enabled": True,
    "min_order_mad": 100_000.0,
    "min_adv_enabled": True,
    "min_adv_mad": 500_000.0,
    "max_participation_enabled": True,
    "max_participation_rate": 0.20,
    "adv_window_days": 20,
    "execution_horizon_days": 1,
}

# Expected refresh cadence for staleness classification (see snapshot_freshness()). The
# underlying B/M/CF/P panel only meaningfully refreshes on the weekly fundamentals cadence
# (see services/api/app/services/scheduler_registry.py: weekly_fundamental_cross_section runs
# Sat 20:30 UTC); the six-vintage strategy itself reforms monthly. A snapshot computed within
# the last ~10 days is "fresh" (comfortably covers one missed weekly run); within ~40 days is
# "aging" (covers one missed monthly vintage formation); beyond that is "stale".
FRESH_MAX_AGE_DAYS = 10
AGING_MAX_AGE_DAYS = 40

_CONFIG_PAYLOAD = {
    "methodology_version": VALUE_STRATEGY_METHODOLOGY_VERSION,
    "vintage_life_months": VINTAGE_LIFE_MONTHS,
    "cost_policy": "requires_VALUE_STRATEGY_COST_BPS_and_VALUE_STRATEGY_COST_SOURCE",
    "trusted_universe_exclusions": sorted(TRUSTED_UNIVERSE_EXCLUSIONS),
    "require_observed_publication_date": True,
    "market_equity_formula": "decision_date_close_x_pit_shares",
}
VALUE_STRATEGY_CONFIG_HASH = hashlib.sha256(json.dumps(_CONFIG_PAYLOAD, sort_keys=True).encode("utf-8")).hexdigest()[:16]

# SignalEngineBatchJob sentinel identity for this job family (mirrors
# analytics.py's SFC_BACKTEST_JOB_SYMBOL/SFC_BACKTEST_JOB_TYPE convention).
VALUE_STRATEGY_JOB_SYMBOL = "__VALUE_STRATEGY__"
VALUE_STRATEGY_JOB_HORIZON = "vintage6"
VALUE_STRATEGY_JOB_TYPE = "value_strategy"


def _resolved_desk_cost_config(liquidity_settings: dict[str, Any] | None = None) -> tuple[LiveLikeConfig, str]:
    """Require an explicit, sourced desk cost instead of the legacy 33 bps convention."""

    raw_cost = os.environ.get("VALUE_STRATEGY_COST_BPS", "").strip()
    source = os.environ.get("VALUE_STRATEGY_COST_SOURCE", "").strip()
    if not raw_cost or not source:
        raise ValueStrategyComputeError(
            "Structural Value v2 requires VALUE_STRATEGY_COST_BPS and VALUE_STRATEGY_COST_SOURCE; "
            "the legacy unsourced 33 bps convention is not accepted"
        )
    try:
        cost_bps = float(raw_cost)
    except ValueError as exc:
        raise ValueStrategyComputeError("VALUE_STRATEGY_COST_BPS must be numeric") from exc
    if not math.isfinite(cost_bps) or cost_bps < 0:
        raise ValueStrategyComputeError("VALUE_STRATEGY_COST_BPS must be finite and non-negative")
    supplied = {**DEFAULT_LIQUIDITY_SETTINGS, **(liquidity_settings or {})}
    try:
        config = replace(
            LiveLikeConfig(cost_bps=cost_bps),
            liquidity_enabled=bool(supplied["liquidity_enabled"]),
            portfolio_nav_mad=float(supplied["portfolio_nav_mad"]),
            min_order_enabled=bool(supplied["min_order_enabled"]),
            min_order_mad=float(supplied["min_order_mad"]),
            min_adv_enabled=bool(supplied["min_adv_enabled"]),
            min_adv_mad=float(supplied["min_adv_mad"]),
            max_participation_enabled=bool(supplied["max_participation_enabled"]),
            max_participation_rate=float(supplied["max_participation_rate"]),
            adv_window_days=int(supplied["adv_window_days"]),
            execution_horizon_days=int(supplied["execution_horizon_days"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueStrategyComputeError(f"Invalid liquidity settings: {exc}") from exc
    numeric_nonnegative = (config.portfolio_nav_mad, config.min_order_mad, config.min_adv_mad, config.max_participation_rate)
    if not all(math.isfinite(value) and value >= 0 for value in numeric_nonnegative):
        raise ValueStrategyComputeError("Liquidity numeric settings must be finite and non-negative")
    if config.portfolio_nav_mad <= 0 or config.adv_window_days < 1 or config.execution_horizon_days < 1:
        raise ValueStrategyComputeError("Portfolio NAV, ADV window, and execution horizon must be positive")
    if config.max_participation_rate > 1:
        raise ValueStrategyComputeError("Maximum ADV participation rate cannot exceed 100%")
    return config, source


def _runtime_config_payload(config: LiveLikeConfig) -> dict[str, Any]:
    return {**_CONFIG_PAYLOAD, "liquidity_settings": {key: asdict(config)[key] for key in DEFAULT_LIQUIDITY_SETTINGS}}


def _runtime_config_hash(config: LiveLikeConfig) -> str:
    payload = _runtime_config_payload(config)
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _ensure_s3_env_vars() -> None:
    """Bridges this container's env var naming (S3_ENDPOINT/S3_ACCESS_KEY/S3_SECRET_KEY,
    see infra/docker-compose.yml) to the names the research code's os.environ.setdefault
    fallbacks expect (S3_ENDPOINT_URL/AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY). Without this,
    the research code's hardcoded 127.0.0.1:9000 fallback silently wins inside the container
    (unreachable there -- minio is a separate container reachable at minio:9000), causing
    every price fetch to fail silently and cascade into an empty-but-"succeeded" result. Found
    via a real end-to-end run on 2026-07-06 (job reported succeeded with zero holdings)."""
    if os.environ.get("S3_ENDPOINT") and not os.environ.get("S3_ENDPOINT_URL"):
        os.environ["S3_ENDPOINT_URL"] = os.environ["S3_ENDPOINT"]
    if os.environ.get("S3_ACCESS_KEY") and not os.environ.get("AWS_ACCESS_KEY_ID"):
        os.environ["AWS_ACCESS_KEY_ID"] = os.environ["S3_ACCESS_KEY"]
    if os.environ.get("S3_SECRET_KEY") and not os.environ.get("AWS_SECRET_ACCESS_KEY"):
        os.environ["AWS_SECRET_ACCESS_KEY"] = os.environ["S3_SECRET_KEY"]


def _load_index_close_series(db: Session, symbol: str) -> pd.Series | None:
    """Loads a raw price index (MASI, MASI_20) close series from MarketDataStore for the
    equity-curve benchmark overlay -- same source/pattern as fundamental_cross_section.py's
    _load_masi_close_series, generalized to any index symbol."""
    row = (
        db.query(models.MarketDataStore)
        .filter(
            models.MarketDataStore.symbol == symbol,
            models.MarketDataStore.timeframe.in_(["1D", "1d"]),
            models.MarketDataStore.object_key.isnot(None),
        )
        .first()
    )
    if row is None:
        return None
    try:
        return load_close_series_from_store(object_key=str(row.object_key))
    except Exception:
        return None


def _build_full_history_panel(db: Session) -> pd.DataFrame:
    """Builds the full monthly PIT panel (not a single as-of-date cross-section) with
    B/M and CF/P computed at every historical date, needed to form each monthly vintage."""
    from core.quant_core.fundamentals.cross_section.methodology_bakeoff import _load_panel, BakeoffConfig

    _ensure_s3_env_vars()
    panel, _ = _load_panel(BakeoffConfig())
    return panel


class ValueStrategyComputeError(RuntimeError):
    """Raised when the computation produces no usable result. Deliberately a hard failure
    (not a silently-empty "succeeded" payload) so the worker task marks the job as failed and
    the previous valid snapshot is preserved and clearly flagged as failed_refresh -- see
    services/worker/tasks/value_strategy.py and snapshot_freshness()."""


def compute_value_strategy_snapshot(db: Session, *, liquidity_settings: dict[str, Any] | None = None) -> dict[str, Any]:
    _ensure_s3_env_vars()
    full_panel = _build_full_history_panel(db)
    if full_panel.empty:
        raise ValueStrategyComputeError("PIT panel is empty -- check DB fundamentals data and S3/minio price connectivity")

    # Reuse compute_value_signal_frame's exact B/M/CF/P formulas, applied per historical date
    # rather than a single as-of cross-section (same primitives, same canonical exclusions).
    from core.quant_core.fundamentals.cross_section.characteristic_study import _ratio_or_none
    from core.quant_core.fundamentals.cross_section.methodology_bakeoff import METRIC_ALIASES, _finite, _metric

    computed = []
    for idx, row in full_panel.iterrows():
        metrics = dict(row["metrics"])
        close = _finite(row.get("close"))
        shares = _metric(metrics, "Shares_Outstanding")
        mcap = decision_date_market_equity(close=close, shares_outstanding=shares)
        book = _metric(metrics, *METRIC_ALIASES["book_equity"])
        cfo = _metric(metrics, *METRIC_ALIASES["cash_flow_ops"])
        is_financial = bool(row.get("is_financial", False))
        computed.append(
            {
                "_idx": idx,
                "market_cap_raw": mcap,
                "book_to_market_raw": _ratio_or_none(book, mcap) if book is not None and book > 0 else None,
                "cashflow_price_raw": _ratio_or_none(cfo, mcap) if not is_financial else None,
            }
        )
    raw = pd.DataFrame(computed).set_index("_idx")
    panel = full_panel.join(raw)
    panel["as_of_date"] = pd.to_datetime(panel["as_of_date"]).dt.date

    # Local import: characteristic_study.py needs statsmodels (for its own beta/momentum
    # regressions, unused here), which is not installed in the API container -- only the
    # worker's requirements-dev.txt has it. This function only ever runs on the worker
    # (see services/worker/tasks/value_strategy.py), so a top-level import would needlessly
    # break API process startup even though the API never calls this function's body.
    from core.quant_core.fundamentals.cross_section.characteristic_study import _full_price_loader

    price_frames = _full_price_loader()
    price_by_symbol = {sym: df["Close"] if "Close" in df else None for sym, df in price_frames.items()}
    config, cost_source = _resolved_desk_cost_config(liquidity_settings)
    panel = attach_point_in_time_adv(panel, price_frames=price_frames, window_days=config.adv_window_days)
    panel = eligibility_mask(panel, config=config)

    s1_holdings = build_vintage_holdings_by_date(panel, strategy="S1_bm", config=config)
    s2_holdings = build_vintage_holdings_by_date(panel, strategy="S2_cfp", config=config)

    capacity_summary: dict[str, Any] = {}
    capacity_ledger = pd.DataFrame()
    actual_current_weights: dict[str, float] = {}
    if config.liquidity_enabled:
        s1, capacity_ledger, capacity_summary, actual_current_weights = run_capacity_constrained_backtest(
            s1_holdings, price_frames=price_frames, config=config
        )
        s2, _, _, _ = run_capacity_constrained_backtest(s2_holdings, price_frames=price_frames, config=config)
    else:
        s1 = run_vintage_backtest(s1_holdings, price_by_symbol=price_by_symbol, config=config)
        s2 = run_vintage_backtest(s2_holdings, price_by_symbol=price_by_symbol, config=config)
    s4 = combine_sleeves(s1, s2)

    def _invested(frame: pd.DataFrame) -> pd.DataFrame:
        return frame[frame["n_holdings"] > 0].reset_index(drop=True)

    strategies = {"S1_bm": _invested(s1), "S2_cfp": _invested(s2), "S4_sleeves": s4[s4["as_of_date"].isin(_invested(s1)["as_of_date"])].reset_index(drop=True)}
    metrics = {name: summarize_performance(frame, periods_per_year=12) for name, frame in strategies.items()}

    # Equity curve for the recommended architecture (S1_bm), invested period only -- genuine
    # cumulative product of realized net returns, not a fabricated smooth line. MASI/MASI20
    # are overlaid on the exact same dates, each rebased to 1.0 at the strategy's first
    # invested date so the comparison starts from a common baseline (not total-return, price
    # index only -- see caveats).
    recommended_frame = strategies.get(RECOMMENDED_ARCHITECTURE, pd.DataFrame())
    masi_series = _load_index_close_series(db, "MASI")
    masi20_series = _load_index_close_series(db, "MASI_20")
    equity_curve: list[dict[str, Any]] = []
    if not recommended_frame.empty:
        equity = 1.0
        masi_equity = 1.0 if masi_series is not None else None
        masi20_equity = 1.0 if masi20_series is not None else None
        prev_date = None
        for _, r in recommended_frame.sort_values("as_of_date").iterrows():
            as_of = r["as_of_date"]
            equity *= 1.0 + float(r["net_return"])
            if prev_date is not None:
                if masi_equity is not None:
                    p0, _ = _pit_price(masi_series, prev_date)
                    p1, _ = _pit_price(masi_series, as_of)
                    if p0 and p1:
                        masi_equity *= p1 / p0
                if masi20_equity is not None:
                    p0, _ = _pit_price(masi20_series, prev_date)
                    p1, _ = _pit_price(masi20_series, as_of)
                    if p0 and p1:
                        masi20_equity *= p1 / p0
            equity_curve.append(
                {
                    "date": as_of.isoformat(),
                    "equity": equity,
                    "net_return": float(r["net_return"]),
                    "turnover": float(r["turnover"]),
                    "masi": masi_equity,
                    "masi20": masi20_equity,
                }
            )
            prev_date = as_of

    # Real BUY/SELL trade ledger for the recommended architecture, derived from the exact same
    # vintage lifecycle the backtest engine uses (see build_trade_ledger docstring) -- not a
    # fabricated or illustrative history.
    ledger_df = capacity_ledger if config.liquidity_enabled else build_trade_ledger(s1_holdings)
    trade_ledger = [
        {
            "date": row["date"].isoformat(),
            "action": row["action"],
            "symbol": row["symbol"],
            "vintage_formed": row["vintage_formed"].isoformat(),
            "weight": float(row["weight"]),
            "requested_notional_mad": float(row["requested_notional_mad"]) if pd.notna(row.get("requested_notional_mad")) else None,
            "filled_notional_mad": float(row["filled_notional_mad"]) if pd.notna(row.get("filled_notional_mad")) else None,
            "unfilled_notional_mad": float(row["unfilled_notional_mad"]) if pd.notna(row.get("unfilled_notional_mad")) else None,
            "adv_mad": float(row["adv_mad"]) if pd.notna(row.get("adv_mad")) else None,
            "participation_rate": float(row["participation_rate"]) if pd.notna(row.get("participation_rate")) else None,
            "status": str(row.get("status") or "filled"),
        }
        for _, row in ledger_df.sort_values("date", ascending=False).head(500).iterrows()
    ] if not ledger_df.empty else []

    if not any(s1_holdings.values()):
        # Every formation date produced zero eligible names -- this is not a normal "between
        # vintages" gap (that would still show other dates with real holdings), it means the
        # trusted universe construction itself is broken (e.g. price/S3 fetch silently
        # returned nothing for every symbol). Fail loudly rather than persist an empty
        # "succeeded" strategy state.
        raise ValueStrategyComputeError("No eligible B/M holdings were formed on any historical date -- trusted universe construction likely broken")

    latest_date = max(s1_holdings) if s1_holdings else None
    current_holdings = actual_current_weights if config.liquidity_enabled else (s1_holdings.get(latest_date, {}) if latest_date else {})
    sector_map = {str(r["symbol"]): r.get("sector") for _, r in panel.drop_duplicates("symbol").iterrows()}

    latest_slice = panel[panel["as_of_date"] == latest_date] if latest_date else panel.iloc[0:0]
    eligible_bm_symbols = sorted(latest_slice.loc[latest_slice["eligible_bm"], "symbol"].astype(str).unique().tolist())
    all_symbols = sorted(latest_slice["symbol"].astype(str).unique().tolist())
    excluded_symbols = sorted(set(all_symbols) - set(eligible_bm_symbols))
    excluded_summary = {
        sym: ("excluded_from_trusted_universe" if sym in TRUSTED_UNIVERSE_EXCLUSIONS else "no_eligible_bm_signal_this_date")
        for sym in excluded_symbols
    }
    data_cutoff = max((d for d in s1_holdings), default=None)

    readiness = current_repository_readiness()
    result = {
        "research_status": VALUE_STRATEGY_RESEARCH_STATUS,
        "live_trading_authorized": readiness.live_trading_authorized,
        "production_readiness": readiness.to_dict(),
        "recommended_architecture": RECOMMENDED_ARCHITECTURE,
        "model_version": MODEL_VERSION,
        "methodology_version": VALUE_STRATEGY_METHODOLOGY_VERSION,
        "transaction_cost_source": cost_source,
        "liquidity_settings": {key: asdict(config)[key] for key in DEFAULT_LIQUIDITY_SETTINGS},
        "capacity_summary": capacity_summary,
        "as_of_date": latest_date.isoformat() if latest_date else None,
        "signal_as_of_date": latest_date.isoformat() if latest_date else None,
        "strategy_as_of_date": latest_date.isoformat() if latest_date else None,
        "data_cutoff": data_cutoff.isoformat() if data_cutoff else None,
        "universe_summary": {
            "total_names": len(all_symbols),
            "eligible_bm_count": len(eligible_bm_symbols),
            "excluded_count": len(excluded_symbols),
            "excluded_symbols": excluded_summary,
        },
        "current_holdings": [
            {"symbol": sym, "target_weight": weight if config.liquidity_enabled else weight / VINTAGE_LIFE_MONTHS, "sector": sector_map.get(sym)}
            for sym, weight in sorted(current_holdings.items(), key=lambda kv: -kv[1])
        ],
        "strategy_metrics": metrics,
        "equity_curve": equity_curve,
        "trade_ledger": trade_ledger,
        "caveats": [
            "LIVE TRADING IS NOT AUTHORIZED: see production_readiness.blocker_ids and the prop-desk readiness review.",
            "All Structural Value v1 performance is withdrawn; only a fully rerun v2 snapshot may be evaluated.",
            "Historical effective shares and corporate actions are not yet independently certified.",
            "Liquidity controls use strictly lagged historical ADTV; missing ADTV is rejected and unfilled notional remains cash.",
            "Default liquidity values are editable research calibrations, not approved desk risk limits.",
            "Benchmark comparison (if shown) uses MASI/MASI20 price indices rebased to the strategy's start date, not confirmed total-return series.",
            "Execution-lag/no-fill behavior remains a failed release gate; these research metrics are not executable performance.",
            f"Transaction-cost input source: {cost_source}.",
            "This is backtested research evidence, not a live or paper trading track record.",
        ],
    }
    return sanitize_json_compatible(result)


def snapshot_freshness(row: models.FundamentalValueStrategySnapshot | None, *, latest_job_status: str | None = None) -> dict[str, Any]:
    """Classifies the current snapshot state: fresh / aging / stale / failed_refresh / no_snapshot.

    A failed latest recompute never destroys a previous valid snapshot -- this only changes the
    *label* shown alongside it, never the underlying data. `latest_job_status` should be the
    status of the most recently ATTEMPTED recompute job (which may be newer than `row` itself,
    e.g. if the latest attempt failed and `row` is the last successful one)."""
    now = dt.datetime.now(dt.timezone.utc)
    if row is None:
        return {"state": "no_snapshot", "age_days": None, "last_successful_computed_at": None}
    computed_at = row.computed_at
    if computed_at.tzinfo is None:
        computed_at = computed_at.replace(tzinfo=dt.timezone.utc)
    age_days = (now - computed_at).total_seconds() / 86400.0
    if latest_job_status == "failed":
        state = "failed_refresh"
    elif age_days <= FRESH_MAX_AGE_DAYS:
        state = "fresh"
    elif age_days <= AGING_MAX_AGE_DAYS:
        state = "aging"
    else:
        state = "stale"
    return {"state": state, "age_days": round(age_days, 1), "last_successful_computed_at": computed_at.isoformat()}


def persist_value_strategy_snapshot(
    db: Session,
    *,
    triggered_by: str | None = None,
    batch_id: str | None = None,
    liquidity_settings: dict[str, Any] | None = None,
) -> models.FundamentalValueStrategySnapshot:
    result = compute_value_strategy_snapshot(db, liquidity_settings=liquidity_settings)
    config, _ = _resolved_desk_cost_config(liquidity_settings)
    config_hash = _runtime_config_hash(config)
    result["triggered_by"] = triggered_by or "manual"
    result["batch_id"] = batch_id
    row = models.FundamentalValueStrategySnapshot(
        config_hash=config_hash,
        params_json=sanitize_json_compatible({**_runtime_config_payload(config), "triggered_by": triggered_by or "manual", "batch_id": batch_id}),
        result_json=sanitize_json_compatible(result),
        computed_at=dt.datetime.now(dt.timezone.utc),
    )
    db.add(row)
    db.flush()
    return row


def recompute_and_persist_value_strategy(
    db: Session,
    *,
    triggered_by: str | None = None,
    batch_id: str | None = None,
    liquidity_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = persist_value_strategy_snapshot(
        db, triggered_by=triggered_by, batch_id=batch_id, liquidity_settings=liquidity_settings
    )
    db.commit()
    return {"snapshot_id": int(row.id), "config_hash": row.config_hash, "computed_at": row.computed_at.isoformat() if row.computed_at else None}


def latest_value_strategy_snapshot(db: Session) -> models.FundamentalValueStrategySnapshot | None:
    rows = (
        db.query(models.FundamentalValueStrategySnapshot)
        .order_by(models.FundamentalValueStrategySnapshot.computed_at.desc())
        .limit(100)
        .all()
    )
    return next(
        (
            row for row in rows
            if isinstance(row.result_json, dict) and row.result_json.get("model_version") == MODEL_VERSION
        ),
        None,
    )


def latest_value_strategy_job(db: Session) -> models.SignalEngineBatchJob | None:
    """Most recent recompute *attempt* (may be a failure newer than the last valid snapshot)."""
    return (
        db.query(models.SignalEngineBatchJob)
        .filter_by(symbol=VALUE_STRATEGY_JOB_SYMBOL, job_type=VALUE_STRATEGY_JOB_TYPE)
        .order_by(models.SignalEngineBatchJob.created_at.desc())
        .first()
    )
