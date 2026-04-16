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

export interface DashboardStock {
  symbol: string
  display_name: string | null
  sector: string | null
  aggregate_score_pct: number | null
  aggregate_signal_label: string | null
  expanded_aggregate_score_pct?: number | null
  expanded_aggregate_signal_label?: string | null
  per_family: Record<string, FamilyScore>
  expanded_per_family?: Record<string, FamilyScore>
  categories: Record<string, CategoryScore>
  technical_levels?: DashboardTechnicalLevels | null
  support_resistance?: DashboardSupportResistance | null
  adv?: number | null
}

export interface DashboardSector {
  sector: string
  stock_count: number
  aggregate_score_pct: number | null
  aggregate_signal_label: string | null
  expanded_aggregate_score_pct?: number | null
  expanded_aggregate_signal_label?: string | null
  per_family: Record<string, FamilyScore>
  expanded_per_family?: Record<string, FamilyScore>
}

export interface DashboardBreadth {
  achat: number
  neutre: number
  vente: number
  indisponible: number
}

export interface DashboardIndex {
  name: string
  stock_count: number
  aggregate_score_pct: number | null
  aggregate_signal_label: string | null
  expanded_aggregate_score_pct?: number | null
  expanded_aggregate_signal_label?: string | null
  per_family: Record<string, FamilyScore>
  expanded_per_family?: Record<string, FamilyScore>
  breadth: DashboardBreadth
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

export type DashboardView = "stocks" | "sectors" | "index"
export type Horizon = "short" | "medium" | "long"
