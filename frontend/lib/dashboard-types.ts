import type { TradingHorizon } from "@/lib/horizon"
import type { EdgeMetrics } from "@/lib/api"

export interface FamilyScore {
  score_pct: number
  label: string
}

export interface FactorDependency {
  condition_id: string
  factor_ticker: string
  canonical_id: string
  label: string
  rule: string
}

export interface CategoryScore {
  score_pct: number
  label: string
  families: string[]
}

export interface DashboardTechnicalLevels {
  close_used: number | null
  support_buy_trigger: number | null
  resistance_sell_trigger: number | null
  support_reference?: number | null
  thresholds?: {
    buy: number
    sell: number
  }
  method?: string
  selected_support_method_id?: string | null
  selected_resistance_method_id?: string | null
}

export interface DashboardSupportResistanceUsedMethod {
  id: string
  label: string
  support: number | null
  resistance: number | null
  status: string
  selected_for_support: boolean
  selected_for_resistance: boolean
  explanation: string
}

export interface DashboardSupportResistanceUsedVariant {
  variant_id: string
  support_method_id: string
  resistance_method_id: string
  description: string
}

export interface DashboardSupportResistance {
  final_support: number | null
  final_resistance: number | null
  selected_support_method_id: string | null
  selected_resistance_method_id: string | null
  summary_explanation: string
  trend_score_pct: number | null
  trend_label: string
  as_of: string
  used_methods: DashboardSupportResistanceUsedMethod[]
  used_variant: DashboardSupportResistanceUsedVariant | null
  warning_message: string
}

export interface DashboardBreadth {
  achat: number
  neutre: number
  vente: number
  indisponible: number
}

export interface SignalEngineScores {
  variant: "legacy" | "expanded" | "factor_x_ta"
  aggregate_score_pct: number | null
  aggregate_signal_label: string | null
  expanded_aggregate_score_pct?: number | null
  expanded_aggregate_signal_label?: string | null
  factor_x_ta_aggregate_score_pct?: number | null
  factor_x_ta_aggregate_signal_label?: string | null
  per_family: Record<string, FamilyScore>
  expanded_per_family?: Record<string, FamilyScore>
  factor_x_ta_per_family?: Record<string, FamilyScore>
  factor_dependencies?: Record<string, FactorDependency[]>
  categories?: Record<string, CategoryScore>
  families?: Record<string, unknown>
  technical_levels?: DashboardTechnicalLevels | null
  support_resistance?: DashboardSupportResistance | null
  breadth?: DashboardBreadth
}

export interface WfoTechnicalLevels {
  support_buy_trigger: number | null
  resistance_sell_trigger: number | null
  support_reference: number | null
  support_method: string
  resistance_method: string
  method: string
}

export interface WfoScores {
  variant: "expanded" | "factor_x_ta"
  aggregate_score_pct: number | null
  aggregate_signal_label: string | null
  per_family: Record<string, FamilyScore>
  technical_levels?: WfoTechnicalLevels | null
  best_category?: string
  consensus_wfe_pct?: number | null
  consensus_robustness?: number | null
  status: "succeeded" | "failed" | "pending" | null
  breadth?: DashboardBreadth
}

export interface ScoresBlock {
  signal_engine: SignalEngineScores
  wfo: WfoScores | null
}

export interface DashboardBestSignal {
  source: "signal_engine" | "wfo"
  variant: string
  label: string
  signal_label?: string | null
  triage: "proven" | "watch" | string
  bucket: string | null
  direction: "long" | "short" | "none" | string
  n: number | null
  fwd_horizon_bars?: number | null
  return_calc_method?: string | null
  entry_price_kind?: string | null
  entry_lag_bars?: number | null
  exit_price_kind?: string | null
  exit_lag_bars?: number | null
  exit_timing_label?: string | null
  action_expected_return_net?: number | null
  action_expected_return_net_ci_lower?: number | null
  action_expected_return_net_ci_upper?: number | null
  hit_rate?: number | null
  hit_ci_lower?: number | null
  hit_ci_upper?: number | null
  selection_n?: number | null
  selection_window_start?: string | null
  selection_window_end?: string | null
  selection_action_expected_return_net?: number | null
  selection_hit_rate?: number | null
  proof_n?: number | null
  proof_window_start?: string | null
  proof_window_end?: string | null
  proof_method?: string | null
  multiple_testing_count?: number | null
  mc_luck_pvalue_net_adj?: number | null
  label_shuffle_pvalue_net_adj?: number | null
  proven_edge_gross?: boolean | null
  proven_edge_net?: boolean | null
  score?: number | null
}

export interface DashboardPortfolioEdge {
  label: string
  triage: "proven" | "watch" | "insufficient" | "hold" | "missing" | string
  horizon?: string | null
  methodology_version?: string | null
  side_policy?: string | null
  weighting?: string | null
  active_count: number
  total_count: number
  long_count: number
  short_count: number
  n: number
  window_start?: string | null
  window_end?: string | null
  fwd_horizon_bars?: number | null
  return_calc_method?: string | null
  entry_price_kind?: string | null
  entry_lag_bars?: number | null
  exit_price_kind?: string | null
  exit_lag_bars?: number | null
  exit_timing_label?: string | null
  selection_n?: number | null
  selection_window_start?: string | null
  selection_window_end?: string | null
  selection_action_expected_return_gross?: number | null
  selection_action_expected_return_net?: number | null
  selection_hit_rate?: number | null
  action_expected_return_gross?: number | null
  action_expected_return_gross_ci_lower?: number | null
  action_expected_return_gross_ci_upper?: number | null
  action_expected_return_net?: number | null
  action_expected_return_net_ci_lower?: number | null
  action_expected_return_net_ci_upper?: number | null
  stock_expected_return?: number | null
  stock_expected_return_ci_lower?: number | null
  stock_expected_return_ci_upper?: number | null
  expected_return_net?: number | null
  hit_rate?: number | null
  hit_ci_lower?: number | null
  hit_ci_upper?: number | null
  edge_ratio_gross?: number | null
  edge_ratio_net?: number | null
  profit_factor_gross?: number | null
  profit_factor_net?: number | null
  average_member_count?: number | null
  min_member_count?: number | null
  max_member_count?: number | null
  gates?: Record<string, boolean>
  proven_edge_net?: boolean | null
  score?: number | null
}

export interface DashboardBestTechnicalSignal {
  source: "signal_engine" | "wfo"
  variant: string
  label: string
  signal_label: string | null
  direction: "long" | "short" | "none" | string
  score_pct: number | null
  abs_score_pct: number | null
  per_family: Record<string, FamilyScore>
  factor_dependencies?: Record<string, FactorDependency[]>
}

export interface DashboardStock {
  symbol: string
  display_name: string | null
  sector: string | null
  scores: ScoresBlock
  last_price?: number | null
  prev_close?: number | null
  var1j_pct?: number | null
  adv?: number | null
  edge?: {
    signal_engine?: EdgeMetrics | null
    wfo?: EdgeMetrics | null
  }
  best_signal?: DashboardBestSignal | null
  best_technical_signal?: DashboardBestTechnicalSignal | null
  asset_class?: string | null     // "equity" | "index" | "factor"
  asset_type?: string | null      // "equity" | "commodity" | "forex" | "bond" | "crypto"
  market_region?: string | null   // "masi" | "us" | "european" | "asian" | null
}

export interface DashboardSector {
  sector: string
  stock_count: number
  scores: ScoresBlock
  portfolio_edge?: DashboardPortfolioEdge | null
}

export interface DashboardIndex {
  name: string
  stock_count: number
  scores: ScoresBlock
  portfolio_edge?: DashboardPortfolioEdge | null
}

export interface DashboardData {
  generated_at: string
  horizon: string
  horizon_label: string
  stocks: DashboardStock[]
  sectors: DashboardSector[]
  index: DashboardIndex
  custom_index_definitions?: DashboardCustomIndexDefinition[]
}

export interface DashboardCustomIndexDefinition {
  id: string
  name: string
  symbols: string[]
  portfolio_edge?: DashboardPortfolioEdge | null
}

export type DashboardScoreSource = "both" | "signal_engine" | "wfo"
export type DashboardView = "stocks" | "sectors" | "index"
export type DashboardDisplayMode = "trade_opportunities" | "technical_directions"
export type DashboardHorizon = TradingHorizon
export type DashboardHorizonAlias = DashboardHorizon | "short" | "medium" | "long"
export type Horizon = DashboardHorizonAlias
