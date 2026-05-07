export interface FamilyScore {
  score_pct: number
  label: string
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
  per_family: Record<string, FamilyScore>
  expanded_per_family?: Record<string, FamilyScore>
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

export interface DashboardStock {
  symbol: string
  display_name: string | null
  sector: string | null
  scores: ScoresBlock
  adv?: number | null
  asset_type?: string | null      // "equity" | "commodity" | "forex" | "bond"
  market_region?: string | null   // "masi" | "us" | "european" | "asian" | null
}

export interface DashboardSector {
  sector: string
  stock_count: number
  scores: ScoresBlock
}

export interface DashboardIndex {
  name: string
  stock_count: number
  scores: ScoresBlock
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
}

export type DashboardScoreSource = "both" | "signal_engine" | "wfo"
export type DashboardView = "stocks" | "sectors" | "index"
export type Horizon = "short" | "medium" | "long"
