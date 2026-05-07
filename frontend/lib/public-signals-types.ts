import type { Horizon } from "@/lib/dashboard-types"

export interface PublicSignalRepresentative {
  variant_id: string
  signal: number
  signal_label: string
  reliability_weight: number
  normalized_weight: number
  contribution: number
  current_close: number | null
  indicator_value: number | null
  explanation: string
  description?: string
  params: Record<string, unknown>
  archetype: string
  selection_status: string
}

export interface PublicFamilySignalDetail {
  family: string
  family_score_pct: number
  family_signal_label: string
  tested_count: number
  viable_count: number
  competitive_count: number
  representative_count: number
  score_explanation: string
  representatives: PublicSignalRepresentative[]
  fallback_variants: PublicSignalRepresentative[]
  as_of: string
  latest_close: number | null
  is_provisional: boolean
  warning_message: string
}

export interface PublicSupportResistanceUsedMethod {
  id: string
  label: string
  support: number | null
  resistance: number | null
  status: string
  selected_for_support: boolean
  selected_for_resistance: boolean
  explanation: string
}

export interface PublicSupportResistanceUsedVariant {
  variant_id: string
  support_method_id: string
  resistance_method_id: string
  description: string
}

export interface PublicSupportResistanceDetail {
  final_support: number | null
  final_resistance: number | null
  selected_support_method_id: string | null
  selected_resistance_method_id: string | null
  summary_explanation: string
  trend_score_pct: number | null
  trend_label: string
  as_of: string
  used_methods: PublicSupportResistanceUsedMethod[]
  used_variant: PublicSupportResistanceUsedVariant | null
  warning_message: string
}

export interface PublicSignalsStock {
  symbol: string
  display_name: string | null
  sector: string | null
  aggregate_score_pct: number | null
  aggregate_signal_label: string | null
  expanded_aggregate_score_pct?: number | null
  expanded_aggregate_signal_label?: string | null
  per_family?: Record<string, { score_pct: number; label: string }>
  expanded_per_family?: Record<string, { score_pct: number; label: string }>
  families: Record<string, PublicFamilySignalDetail>
  support_resistance?: PublicSupportResistanceDetail | null
}

export interface PublicSignalsSnapshot {
  generated_at: string
  horizon: Horizon
  horizon_label: string
  stocks: PublicSignalsStock[]
}
