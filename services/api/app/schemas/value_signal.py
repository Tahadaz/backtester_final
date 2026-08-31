"""Pydantic schemas for the canonical B/M + CF/P value signal and the six-vintage
live-like strategy snapshot (2026-07-06 research, production entrypoint).

These are the first typed response models for this signal -- the older SFC composite
endpoints (analytics.py) return untyped dicts; this module intentionally provides explicit
schemas per Phase 6/7 of the integration brief (single source of truth, typed API objects).
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from pydantic import BaseModel, Field


class ValueSignalRow(BaseModel):
    symbol: str
    as_of_date: str
    bm_raw: Optional[float] = None
    market_equity: Optional[float] = Field(None, description="Decision-date close multiplied by PIT shares; stored workbook market cap is never used.")
    decision_close: Optional[float] = None
    shares_outstanding: Optional[float] = None
    book_equity: Optional[float] = None
    book_equity_provenance: Optional[dict[str, Any]] = None
    shares_provenance: Optional[dict[str, Any]] = None
    bm_percentile: Optional[float] = Field(None, description="Cross-sectional percentile within the eligible universe; higher = structurally cheaper (higher B/M).")
    bm_rank: Optional[int] = None
    cfp_raw: Optional[float] = None
    cfp_percentile: Optional[float] = Field(None, description="Cross-sectional percentile within the eligible universe; higher = stronger cash-flow yield.")
    cfp_rank: Optional[int] = None
    cfp_applicable: bool = Field(..., description="False for bank/insurance issuers, where CF/P is excluded by canonical sector-applicability policy.")
    eligible_bm: bool
    eligible_cfp: bool
    eligible_universe: bool = Field(..., description="False if excluded from the trusted universe entirely (e.g. SAH — unresolved data-quality issue).")
    exclusion_reasons: list[str] = Field(default_factory=list)
    sector: Optional[str] = None
    is_financial: bool
    methodology_version: str


class ValueSignalResponse(BaseModel):
    as_of_date: str
    methodology_version: str
    eligible_bm_count: int
    eligible_cfp_count: int
    total_rows: int
    publication_coverage: dict[str, Any] = Field(default_factory=dict)
    market_equity_formula: str
    rows: list[ValueSignalRow]


class ValueStrategyHolding(BaseModel):
    symbol: str
    target_weight: float
    sector: Optional[str] = None


class UniverseSummary(BaseModel):
    total_names: int
    eligible_bm_count: int
    excluded_count: int
    excluded_symbols: dict[str, str] = Field(default_factory=dict, description="symbol -> exclusion reason code")


class SnapshotFreshness(BaseModel):
    state: str = Field(..., description="fresh | aging | stale | failed_refresh | no_snapshot")
    age_days: Optional[float] = None
    last_successful_computed_at: Optional[str] = None


class EquityCurvePoint(BaseModel):
    date: str
    equity: float = Field(..., description="Cumulative growth of 1 unit of capital, genuine realized net returns (see monthly_realized_returns in prior research, not overlapping forward-return diagnostics).")
    net_return: float
    turnover: float
    masi: Optional[float] = Field(None, description="MASI price index, rebased to 1.0 at the strategy's first invested date. Price index only, not total-return.")
    masi20: Optional[float] = Field(None, description="MASI20 price index, rebased to 1.0 at the strategy's first invested date. Price index only, not total-return.")


class TradeLedgerRow(BaseModel):
    date: str
    action: str = Field(..., description="BUY or SELL")
    symbol: str
    vintage_formed: str = Field(..., description="Formation date of the 6-month vintage this trade belongs to.")
    weight: float = Field(..., description="Capital weight of this trade (1/6 of the vintage's equal-weight allocation).")
    requested_notional_mad: Optional[float] = None
    filled_notional_mad: Optional[float] = None
    unfilled_notional_mad: Optional[float] = None
    adv_mad: Optional[float] = None
    participation_rate: Optional[float] = None
    status: str = "filled"


class ValueStrategyLiquiditySettings(BaseModel):
    liquidity_enabled: bool = True
    portfolio_nav_mad: float = Field(10_000_000.0, gt=0)
    min_order_enabled: bool = True
    min_order_mad: float = Field(100_000.0, ge=0)
    min_adv_enabled: bool = True
    min_adv_mad: float = Field(500_000.0, ge=0)
    max_participation_enabled: bool = True
    max_participation_rate: float = Field(0.20, ge=0, le=1)
    adv_window_days: int = Field(20, ge=1, le=252)
    execution_horizon_days: int = Field(1, ge=1, le=20)


class ValueStrategyRecomputeRequest(BaseModel):
    liquidity: ValueStrategyLiquiditySettings = Field(default_factory=ValueStrategyLiquiditySettings)


class ValueStrategySnapshotResponse(BaseModel):
    live_trading_authorized: bool = Field(
        ...,
        description="Fail-closed authorization. False until every documented production-readiness gate passes.",
    )
    production_readiness: dict[str, Any] = Field(
        default_factory=dict,
        description="Versioned evidence gates and remediation required before live use.",
    )
    research_status: str = Field(..., description='Research-only classification; not proven alpha, a live track record, or an authorization.')
    recommended_architecture: str
    model_version: str = Field(..., description="Frozen methodology identifier, not a runtime timestamp.")
    as_of_date: Optional[str] = None
    data_cutoff: Optional[str] = None
    universe_summary: Optional[UniverseSummary] = None
    current_holdings: list[ValueStrategyHolding]
    strategy_metrics: dict[str, Any]
    equity_curve: list[EquityCurvePoint] = Field(default_factory=list)
    trade_ledger: list[TradeLedgerRow] = Field(default_factory=list, description="Most recent 500 BUY/SELL events, newest first.")
    liquidity_settings: ValueStrategyLiquiditySettings = Field(default_factory=ValueStrategyLiquiditySettings)
    capacity_summary: dict[str, Any] = Field(default_factory=dict)
    caveats: list[str]
    config_hash: str
    computed_at: Optional[str] = None
    freshness: SnapshotFreshness


class ValueStrategyRecomputeResponse(BaseModel):
    job_id: str
    rq_job_id: Optional[str] = None
    status: str


class ValueStrategyJobRow(BaseModel):
    id: str
    status: str
    rq_job_id: Optional[str] = None
    triggered_by: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class ValueStrategyStatusResponse(BaseModel):
    job_type: str
    jobs: list[ValueStrategyJobRow] = Field(default_factory=list)
