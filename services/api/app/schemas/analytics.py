"""Pydantic schemas for analytics API.

Matches quant_core.research.domain dataclasses.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ICCurveOut(BaseModel):
    horizons: list[int]
    ic_values: list[float]
    ic_se: list[float]
    ic_ci_lower: list[float]
    ic_ci_upper: list[float]
    n_obs: list[int]


class PortfolioStatsOut(BaseModel):
    sharpe: float
    sortino: float
    max_drawdown: float
    calmar: float
    turnover: float
    hit_rate: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    after_cost_sharpe: float
    n_trades: int
    total_return: float


class RobustnessOut(BaseModel):
    dsr: float
    psr: float
    sharpe_bootstrap_ci: list[float]   # [lower, upper]
    ic_bootstrap_ci: list[float]       # [lower, upper]
    ic_cv: float
    sharpe_cv: float
    n_variants: int


class SignalEvaluationReportOut(BaseModel):
    signal_id: str
    symbol: str
    n_obs: int
    horizons: list[int]
    ic_curve: ICCurveOut
    hit_rate_h1: float
    hit_rate_ci: list[float]           # [lower, upper]
    conditional_return_tstat: float
    portfolio: PortfolioStatsOut
    robustness: RobustnessOut


class SignalOverviewRow(BaseModel):
    symbol: str
    category: str
    horizon: str
    signal_id: str                     # "symbol:category:horizon"
    ic_h1: Optional[float] = None
    ic_h5: Optional[float] = None
    dsr: Optional[float] = None
    psr: Optional[float] = None
    sharpe: float
    after_cost_sharpe: Optional[float] = None
    hit_rate: Optional[float] = None
    n_obs: int
    fdr_pass: bool = False
    engine_score_pct: Optional[float] = None   # signal engine family score (0-100)
    engine_label: Optional[str] = None         # "Haussier" | "Baissier" | "Neutre"


class FactorRelevanceRow(BaseModel):
    """Spearman IC-based relevance for one (factor, stock) pair."""
    factor_id: str                     # "VIX", "DXY", etc.
    symbol: str
    ic: float                          # mean rank IC over sample
    t_stat: float                      # Newey-West t-stat
    p_value: float
    ic_cv: float                       # rolling IC stability (CV)
    n_obs: int
    significant: bool                  # |t_stat| > 1.96


class FactorLeaderboardRow(BaseModel):
    """Per-stock macro-factor significance summary for the leaderboard."""
    symbol: str
    n_significant: int                 # count of significant factors (out of 6)
    best_factor: str                   # factor_id with highest |t_stat|
    max_t_stat: float
    max_ic: float
    n_obs: int


class FactorRelevanceMatrixOut(BaseModel):
    """All factors vs one stock."""
    symbol: str
    as_of: str
    pairs: list[FactorRelevanceRow]


class AllFactorRelevanceOut(BaseModel):
    """Summary: for each factor, how many stocks pass significance test."""
    factor_id: str
    n_significant: int
    n_total: int
    top_symbols: list[str]             # top-5 by |IC|


class MacroIngestRequestOut(BaseModel):
    canonical_id: str
    job_id: str
    status: str = "enqueued"


class PredictiveAbilityCell(BaseModel):
    bucket: str                           # 'strong_sell' | 'sell' | 'hold' | 'buy' | 'strong_buy'
    fwd_h: int                            # forward-return horizon (trading days)
    n: int
    mean: Optional[float] = None
    std: Optional[float] = None
    ci_lower: Optional[float] = None
    ci_upper: Optional[float] = None
    hit_rate: Optional[float] = None
    hit_ci_lower: Optional[float] = None
    hit_ci_upper: Optional[float] = None
    window_start: Optional[str] = None         # ISO date of earliest score in cell
    window_end: Optional[str] = None           # ISO date of latest score in cell
    lookback_business_days: Optional[int] = None  # business-day span window_start → window_end


class PredictiveAbilityMatrix(BaseModel):
    symbol: str
    source: str                           # 'engine_legacy' | 'engine_expanded' | 'wfo'
    horizon: str                          # 'short' | 'medium' | 'long'
    categories: list[str]
    n_obs: int
    buckets: list[str]
    fwd_horizons: list[int]
    cells: list[PredictiveAbilityCell]
    available: bool = True
    message: Optional[str] = None
    current_score: Optional[float] = None
    current_bucket: Optional[str] = None


class CategoryCombinationRow(BaseModel):
    categories: list[str]
    n_strong_buy: int
    n_strong_sell: int
    strong_buy_mean: Optional[float] = None
    strong_sell_mean: Optional[float] = None
    monotonicity_score: Optional[float] = None   # strong_buy_mean - strong_sell_mean


class CategoryCombinationsOut(BaseModel):
    symbol: str
    source: str
    horizon: str
    fwd_h: int
    rows: list[CategoryCombinationRow]


class PredictiveHistoryStatus(BaseModel):
    total: int
    pending: int
    running: int
    succeeded: int
    failed: int


class PredictiveHistoryTriggerOut(BaseModel):
    triggered: int
    job_ids: list[str] = []


class LeaderboardRow(BaseModel):
    symbol: str
    source: str                                  # 'engine_legacy' | 'engine_expanded' | 'wfo'
    n: int
    ic_by_fwd_h: dict[int, Optional[float]]      # fwd horizon -> Spearman IC
    tstat_by_fwd_h: dict[int, Optional[float]]   # fwd horizon -> Newey-West t-stat
    mean_ic: Optional[float] = None              # mean across the row's fwd horizons
    mean_hit_rate: Optional[float] = None        # mean directional hit rate across fwd horizons
    mean_sharpe: Optional[float] = None          # annualised Sharpe of O→O daily PnL stream


class LeaderboardOut(BaseModel):
    engine_horizon: str
    fwd_horizons: list[int]
    rows: list[LeaderboardRow]


class MethodEvaluationRow(BaseModel):
    source: str
    label: str
    verdict: str                                  # keep | watch | discard | no_data
    tested_count: int
    eligible_count: int
    coverage_pct: Optional[float] = None
    median_n: Optional[float] = None
    median_ic: Optional[float] = None
    median_abs_tstat: Optional[float] = None
    median_hit_rate: Optional[float] = None
    median_sharpe: Optional[float] = None
    evidence_score: Optional[float] = None
    reason_codes: list[str] = Field(default_factory=list)


class MethodEvaluationOut(BaseModel):
    engine_horizon: str
    universe: str
    return_calc_method: str
    rows: list[MethodEvaluationRow]


class MacroIngestStatusOut(BaseModel):
    canonical_id: str
    rows_total: Optional[int] = None
    rows_fetched: Optional[int] = None
    inserted: Optional[int] = None
    updated: Optional[int] = None
    status: Optional[str] = None
    error: Optional[str] = None


class FactorSignalEvalOut(BaseModel):
    factor_id: str
    signal_name: str
    symbol: str
    citation: str
    channel_filter: list[str]
    applicable: bool
    # Headline metrics — zeroed when applicable=False
    ic_h1: float
    ic_h5: float
    hit_rate: float
    sharpe: float
    after_cost_sharpe: float
    dsr: float
    psr: float
    conditional_return_tstat: float
    n_obs: int
    fdr_pass: bool
    # Full detail (reuses existing schemas)
    ic_curve: ICCurveOut
    portfolio: PortfolioStatsOut
    robustness: RobustnessOut


# ---------------------------------------------------------------------------
# Edge metrics (§4.2 of the edge-deploy plan, Amendment E gross/net pairs)
# ---------------------------------------------------------------------------

class ExpectancyDecompOut(BaseModel):
    p_win: float
    avg_win: float
    p_loss: float
    avg_loss: float
    expectancy: float


class EdgeGatesOut(BaseModel):
    mc_gross: bool
    mc_net: bool
    label_shuffle_gross: bool = False
    label_shuffle_net: bool = False
    wilson: bool
    n: bool
    freshness_gross: bool = False
    freshness_net: bool = False


class EdgeMetricsOut(BaseModel):
    symbol: str
    horizon: str                              # weekly | monthly | quarterly
    source: str                               # signal_engine | wfo
    variant: str = "expanded_ta_simple"
    bucket: str                               # strong_sell | sell | hold | buy | strong_buy
    direction: str                            # long | short | none
    n: int
    window_start: Optional[str] = None        # ISO date
    window_end: Optional[str] = None          # ISO date
    fwd_horizon_bars: Optional[int] = None
    return_calc_method: str = "open_to_exit_ladder"
    entry_price_kind: str = "open"
    entry_lag_bars: int = 1
    exit_price_kind: str = "open"
    exit_lag_bars: Optional[int] = None
    exit_timing_label: str = ""
    holding_period_min_bars: Optional[int] = None
    holding_period_max_bars: Optional[int] = None
    holding_period_candidate_count: int = 0
    holding_period_selection_metric: str = "max_net_action_expected_return"
    side_policy: str = "long_short"
    action_expected_return_gross: Optional[float] = None
    action_expected_return_gross_ci_lower: Optional[float] = None
    action_expected_return_gross_ci_upper: Optional[float] = None
    action_expected_return_net: Optional[float] = None
    action_expected_return_net_ci_lower: Optional[float] = None
    action_expected_return_net_ci_upper: Optional[float] = None
    stock_expected_return: Optional[float] = None
    stock_expected_return_ci_lower: Optional[float] = None
    stock_expected_return_ci_upper: Optional[float] = None
    expected_return_gross: Optional[float] = None
    expected_return_gross_ci_lower: Optional[float] = None
    expected_return_gross_ci_upper: Optional[float] = None
    expected_return_net: Optional[float] = None
    expected_return_net_ci_lower: Optional[float] = None
    expected_return_net_ci_upper: Optional[float] = None
    hit_rate: Optional[float] = None
    hit_ci_lower: Optional[float] = None
    hit_ci_upper: Optional[float] = None
    expectancy_gross: Optional[ExpectancyDecompOut] = None
    expectancy_net: Optional[ExpectancyDecompOut] = None
    edge_ratio_gross: Optional[float] = None
    edge_ratio_net: Optional[float] = None
    profit_factor_gross: Optional[float] = None
    profit_factor_net: Optional[float] = None
    mc_luck_pvalue_gross: Optional[float] = None
    mc_luck_pvalue_net: Optional[float] = None
    label_shuffle_pvalue_gross: Optional[float] = None
    label_shuffle_pvalue_net: Optional[float] = None
    mc_luck_pvalue_gross_adj: Optional[float] = None
    mc_luck_pvalue_net_adj: Optional[float] = None
    label_shuffle_pvalue_gross_adj: Optional[float] = None
    label_shuffle_pvalue_net_adj: Optional[float] = None
    proven_edge_gross: bool = False
    proven_edge_net: bool = False
    gates: EdgeGatesOut
    cost_bps_per_side: float
    methodology_version: str
    proof_max_lookback_years: Optional[float] = None
    freshness_lookback_years: Optional[float] = None
    freshness_min_n: int = 10
    freshness_n: int = 0
    freshness_window_start: Optional[str] = None
    freshness_window_end: Optional[str] = None
    freshness_action_expected_return_gross: Optional[float] = None
    freshness_action_expected_return_net: Optional[float] = None
    freshness_hit_rate: Optional[float] = None
    freshness_status: str = "unavailable"
    selection_n: int = 0
    selection_window_start: Optional[str] = None
    selection_window_end: Optional[str] = None
    selection_action_expected_return_gross: Optional[float] = None
    selection_action_expected_return_net: Optional[float] = None
    selection_hit_rate: Optional[float] = None
    proof_n: int = 0
    proof_window_start: Optional[str] = None
    proof_window_end: Optional[str] = None
    proof_method: str = "same_oos_sample"
    multiple_testing_count: int = 1
    fragility_label: str = "unavailable"
    fragility_fold_count: int = 0
    fragility_details: list[dict[str, Any]] = Field(default_factory=list)
