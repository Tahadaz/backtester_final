"use client"

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react"
import type { CSSProperties, ReactNode } from "react"
import useSWR, { useSWRConfig } from "swr"
import { AlertTriangle, CalendarDays, ChevronDown, ChevronRight, Landmark, Loader2, Save, Search, SlidersHorizontal } from "lucide-react"
import {
  fetchDashboardIndices,
  getFundamentalMethodology,
  getFundamentalResolvedAssumptions,
  getFundamentalSnapshotBatch,
  getFundamentalSensitivity,
  getFundamentalStockDetail,
  getFundamentalUniverse,
  updateFundamentalAssumptions,
  updateFundamentalDeskAssumptions,
  type DashboardCustomIndex,
  type FundamentalAssumptionMeta,
  type FundamentalLightSnapshot,
  type FundamentalMethodology,
  type FundamentalSensitivity,
  type FundamentalHorizonPrediction,
  type FundamentalStockDetail,
  type FundamentalUniverseRow,
  type FundamentalValuationResult,
} from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable"
import { Skeleton } from "@/components/ui/skeleton"
import { Switch } from "@/components/ui/switch"
import { buildFundamentalEstimateTable } from "@/lib/fundamental-estimates-utils.js"
import { buildDcfViewModel } from "@/lib/fundamental-dcf-utils.js"
import { GlossaryTerm } from "@/components/ui/glossary-term"
import { buildValuationModelStory } from "@/lib/fundamental-valuation-story-utils.js"
import { buildFinancialStatementTable, financialPeriodLabel } from "@/lib/fundamental-statement-utils.js"
import {
  BUILTIN_CUSTOM_DASHBOARD_INDICES,
  BUILTIN_WEIGHTED_MASI_INDEX,
} from "@/lib/builtin-dashboard-indices"
import { cn } from "@/lib/utils"

type Scenario = "bear" | "base" | "bull"
type DetailTab = "thesis" | "valuation" | "estimates" | "comparables" | "assumptions" | "quality"
type FundamentalHorizon = "quarter" | "semester" | "year"
type SortKey =
  | "upside"
  | "value"
  | "quality"
  | "conviction"
  | "market_cap"
  | "magic"
  | "peg"
  | "altman"
  | "eva"
  | "regression"
type Recommendation = "BUY" | "ACCUMULATE" | "HOLD" | "REDUCE" | "SELL" | "NR"
type RecommendationFilter = "all" | Recommendation

type ValuationMethodRange = {
  key: string
  method: string
  low: number
  mid: number
  high: number
  weight: number | null | undefined
  confidence: string
  row: FundamentalValuationResult | null
}

type ComparableModelSummary = {
  fairValue: number | null
  upside: number | null
  count: number
  impliedPrices: Array<{ metric: string; fairValue: number; selectedValue: number; benchmark: number }>
  peerCount: number
  weightSource: string
  peerFairValues: ComparablePeerFairValue[]
}

type ComparablePeerFairValue = {
  symbol: string
  displayName: string
  sector: string | null
  weight: number | null
  baseWeight: number | null
  fairValue: number | null
  weightedFairValue: number | null
  upside: number | null
  metricFairValues: Record<string, number | null>
}

type WeightMode = "ic" | "equal"

type ValuationSelectionSummary = {
  fairValue: number | null
  low: number | null
  high: number | null
  upside: number | null
  includedCount: number
  usableCount: number
  weightSource: "model weights" | "equal weights" | "ic fallback" | "user weights"
  effectiveWeights: Map<string, number>
}

type MultipleRatioDefinition = {
  key: string
  label: string
  bit: number
}

type DcfMode = "fcff" | "fcfe"

type DcfPvRow = {
  index: number
  cashFlow: number
  growth: number | null
  period: number
  discountFactor: number | null
  pv: number | null
}

type DcfBridgeStep = {
  key: string
  label: string
  value: number | null
  kind: "add" | "subtract" | "total" | "divide" | "result"
}

type DcfReconciliation = {
  key: string
  label: string
  reported: number | null
  computed: number | null
  diff: number | null
  ok: boolean
}

type DcfUnavailableViewModel = {
  available: false
  reason: string
  mode?: DcfMode
  discountRate?: number | null
  terminalGrowth?: number | null
  shares?: number | null
  fairValue?: number | null
  currentPrice?: number | null
}

type DcfAvailableViewModel = {
  available: true
  mode: DcfMode
  cashFlowLabel: string
  rateLabel: string
  discountRate: number
  terminalGrowth: number
  terminalBasis: Record<string, unknown>
  shares: number | null
  fairValue: number | null
  currentPrice: number | null
  netDebt: number | null
  netDebtSource: string | null
  midYearDiscounting: boolean
  midYearTerminal: boolean
  pvRows: DcfPvRow[]
  explicitPv: number | null
  explicitPvComputed: number
  terminalValue: number | null
  terminalFormulaValue: number | null
  terminalPeriod: number
  terminalDiscountFactor: number | null
  terminalPv: number | null
  terminalValuePct: number | null
  totalValue: number | null
  totalValueComputed: number
  equityValue: number | null
  finalFairValue: number | null
  finalFairValueComputed: number | null
  impliedExitEvToEbitda: number | null
  bridgeSteps: DcfBridgeStep[]
  flags: {
    gBelowRate: boolean
    terminalHeavy: boolean
  }
  reconciliations: DcfReconciliation[]
}

type DcfViewModel = DcfUnavailableViewModel | DcfAvailableViewModel

type FinancialStatementTab = "income" | "balance" | "cashflow"
type FinancialStatementTable = {
  periods: Array<{ key: string; label: string }>
  rows: Array<{
    key: string
    label: string
    format: string
    values: Array<{ value: number | null; sourceMetric?: string | null }>
  }>
}

type StatementEvidenceItem = {
  key: string
  label: string
  value: number | null
  formatted: string
  sourceMetric: string | null
  periodLabel: string
}

type StatementEvidenceGroup = {
  key: FinancialStatementTab
  title: string
  items: StatementEvidenceItem[]
}

type ModelValueItem = {
  key: string
  label: string
  value: unknown
  source?: string
}

type ModelStoryMetricFormat = "money" | "pct" | "number" | "ratio"

type ModelStoryMetric = {
  label: string
  value: unknown
  format?: ModelStoryMetricFormat
  source?: unknown
}

type ModelStoryTableCell = string | number | null | { value: unknown; format?: ModelStoryMetricFormat; digits?: number }

type ModelStoryStep = {
  title: string
  description: string
  formula?: string
  metrics?: ModelStoryMetric[]
  table?: {
    columns: string[]
    rows: ModelStoryTableCell[][]
  }
}

type ModelStory = {
  model: string
  title: string
  summary: string
  steps: ModelStoryStep[]
  checks: Array<{ label: string; ok: boolean }>
}

type ProjectionView = {
  statements: Record<string, unknown>[]
  drivers: Record<string, Record<string, unknown>>
  fcff: number[]
  fcfe: number[]
  dividends: number[]
  bookValues: number[]
  growthDecomposition: Record<string, unknown>
  warnings: string[]
}

type SeriesPoint = {
  year: number
  value: number
  kind?: "historical" | "projected"
}

type SensitivityGridView = {
  axis_x: string
  axis_y: string
  xs: number[]
  ys: number[]
  matrix: Array<Array<number | null>>
  model?: string | null
}

type ValuationFormulaMeta = {
  formula: string
  secondaryFormula?: string
  explanation: string
  assumptionKeys: string[]
  technicalInputKeys: string[]
  statementKeys: Record<FinancialStatementTab, string[]>
}

interface SignalFundamentalViewProps {
  selectedSymbol: string | null
  onSelectSymbol: (symbol: string) => void
  searchParams: { get: (name: string) => string | null }
  updateSearchParams: (updates: Record<string, string | null>) => void
}

const SCENARIOS: Scenario[] = ["bear", "base", "bull"]
const FUNDAMENTAL_HORIZONS: Array<{ value: FundamentalHorizon; label: string; periodType: "quarterly" | "semiannual" | "annual" }> = [
  { value: "quarter", label: "Trimestre", periodType: "quarterly" },
  { value: "semester", label: "Semestre", periodType: "semiannual" },
  { value: "year", label: "Annee", periodType: "annual" },
]

const FUND_TABS: Array<{ value: DetailTab; label: string }> = [
  { value: "thesis", label: "These" },
  { value: "valuation", label: "Valorisation" },
  { value: "estimates", label: "Estimations" },
  { value: "comparables", label: "Comparables" },
  { value: "assumptions", label: "Hypotheses" },
  { value: "quality", label: "Value / Qualite" },
]

const MODEL_ORDER = ["fcff_dcf", "fcfe_dcf", "ddm", "residual_income", "justified_multiples", "relative_multiples", "reverse_dcf"]
const VALUATION_EXCLUSIONS_STORAGE_KEY = "fundamental_valuation_exclusions_by_symbol"
const FUNDAMENTAL_LIQUIDITY_ADV20_THRESHOLD = 500_000
const JUSTIFIED_MULTIPLE_RATIO_MASK_KEY = "justified_multiple_ratio_mask"
const RELATIVE_MULTIPLE_RATIO_MASK_KEY = "relative_multiple_ratio_mask"
const JUSTIFIED_MULTIPLE_RATIO_DEFAULT_MASK = 3
const RELATIVE_MULTIPLE_RATIO_DEFAULT_MASK = 15
const EXTREME_VALUATION_FAIR_VALUE_MULTIPLE = 20
const SEVERE_VALUATION_WARNINGS = new Set([
  "missing_positive_fcf",
  "missing_positive_equity_cash_flow_proxy",
  "wacc_not_above_terminal_growth",
  "cost_of_equity_not_above_terminal_growth",
  "fcf_dcf_unavailable_nonpositive_equity_value",
  "dividend_yield_above_plausible_range",
  "price_to_book_below_plausible_range",
])
const SEVERE_FCF_WARNING_PREFIXES = ["fcf_model_unreliable_negative_"]
const JUSTIFIED_MULTIPLE_RATIOS: MultipleRatioDefinition[] = [
  { key: "justified_pb", label: "P/B", bit: 1 },
  { key: "justified_pe", label: "P/E", bit: 2 },
]
const RELATIVE_MULTIPLE_RATIOS: MultipleRatioDefinition[] = [
  { key: "PER", label: "P/E", bit: 1 },
  { key: "Price_to_Book", label: "P/B", bit: 2 },
  { key: "Price_to_Sales", label: "P/S", bit: 4 },
  { key: "EV_to_EBITDA", label: "EV/EBITDA", bit: 8 },
]

function clampValue(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

const MODEL_LABELS: Record<string, string> = {
  fcff_dcf: "DCF FCFF",
  fcfe_dcf: "DCF FCFE",
  ddm: "DDM",
  residual_income: "Revenu residuel",
  justified_multiples: "Multiples justifies",
  relative_multiples: "Comparables",
  reverse_dcf: "Reverse DCF",
}

const MODEL_FORMULA_META: Record<string, ValuationFormulaMeta> = {
  fcff_dcf: {
    formula: "FV/share = (PV(FCFF_1..n) + TV - Net Debt) / Shares",
    secondaryFormula: "TV = FCFF_n x (1 + g_terminal) / (WACC - g_terminal)",
    explanation: "Values the operating business from free cash flow to the firm, then bridges enterprise value to equity value.",
    assumptionKeys: ["wacc", "terminal_growth_firm", "default_debt_weight", "default_equity_weight", "use_balance_sheet_capital_weights", "cost_of_debt", "forecast_years", "growth_cap", "tax_rate"],
    technicalInputKeys: ["fcf_start", "fcf_source", "fcf_growth_source", "net_debt", "net_debt_source"],
    statementKeys: {
      income: ["revenue", "ebitda", "ebit", "net_income"],
      balance: ["cash", "total_debt", "net_debt", "total_equity"],
      cashflow: ["operating_cf", "capex", "free_cash_flow"],
    },
  },
  fcfe_dcf: {
    formula: "FV/share = (PV(FCFE_1..n) + TV) / Shares",
    secondaryFormula: "FCFE = FCF - Interest x (1 - tax) + Debt issuance - Debt repayment",
    explanation: "Discounts cash flow available to equity holders directly, so no net-debt bridge is applied after discounting.",
    assumptionKeys: ["cost_of_equity", "terminal_growth_equity", "cost_of_debt", "forecast_years", "growth_cap", "tax_rate"],
    technicalInputKeys: ["fcfe_start", "fcfe_source"],
    statementKeys: {
      income: ["revenue", "ebitda", "net_income"],
      balance: ["total_debt", "net_debt", "total_equity"],
      cashflow: ["operating_cf", "financing_cf", "free_cash_flow"],
    },
  },
  ddm: {
    formula: "FV/share = DPS_1 / (Cost of Equity - g)",
    secondaryFormula: "DPS_1 = Dividend per share x (1 + sustainable growth)",
    explanation: "Uses the Gordon dividend model when the stock has an observable dividend base.",
    assumptionKeys: ["cost_of_equity", "terminal_growth_equity", "stable_payout_ratio", "growth_cap"],
    technicalInputKeys: ["dividend_per_share", "growth_source"],
    statementKeys: {
      income: ["revenue", "net_income"],
      balance: ["total_equity"],
      cashflow: ["dividends_paid", "free_cash_flow"],
    },
  },
  residual_income: {
    formula: "FV/share = BVPS_0 + sum((ROE_t - Cost of Equity) x BVPS_{t-1}) / (1 + Cost of Equity)^t",
    secondaryFormula: "BVPS_t grows with retained earnings while ROE fades toward Cost of Equity.",
    explanation: "Starts from book value and adds the discounted value created above the required return on equity.",
    assumptionKeys: ["cost_of_equity", "terminal_growth_equity", "fade_years", "stable_payout_ratio"],
    technicalInputKeys: ["book_value_per_share", "roe"],
    statementKeys: {
      income: ["revenue", "net_income"],
      balance: ["total_equity", "retained_earnings"],
      cashflow: ["dividends_paid", "free_cash_flow"],
    },
  },
  justified_multiples: {
    formula: "FV/share = median(Current Price x Justified Multiple / Current Multiple)",
    secondaryFormula: "Justified P/B = (ROE - g) / (Cost of Equity - g), Justified P/E = payout x (1 + g) / (Cost of Equity - g)",
    explanation: "Translates ROE, payout and growth into internally justified P/B and P/E multiples.",
    assumptionKeys: ["cost_of_equity", "terminal_growth_equity", "stable_payout_ratio", "growth_cap", "fade_years", JUSTIFIED_MULTIPLE_RATIO_MASK_KEY],
    technicalInputKeys: ["roe"],
    statementKeys: {
      income: ["revenue", "net_income"],
      balance: ["total_equity"],
      cashflow: ["dividends_paid", "free_cash_flow"],
    },
  },
  relative_multiples: {
    formula: "FV/share = median(Current Price x Peer Median Multiple / Own Multiple)",
    secondaryFormula: "Applied to P/E, P/B, P/S and EV/EBITDA when each own and peer multiple is usable.",
    explanation: "Benchmarks the stock against sector peers first, then the market when the sector sample is too thin.",
    assumptionKeys: ["peer_min_count", RELATIVE_MULTIPLE_RATIO_MASK_KEY],
    technicalInputKeys: ["own_multiples", "peer_stats"],
    statementKeys: {
      income: ["revenue", "ebitda", "net_income"],
      balance: ["total_equity", "net_debt"],
      cashflow: ["free_cash_flow"],
    },
  },
  reverse_dcf: {
    formula: "Implied g = WACC - FCF Yield",
    secondaryFormula: "Diagnostic only: the result is an implied growth assumption, not a price target.",
    explanation: "Does not produce a fair value. It explains what perpetual-growth assumption the current market price already embeds.",
    assumptionKeys: ["wacc"],
    technicalInputKeys: ["market_cap", "fcf_yield"],
    statementKeys: {
      income: ["revenue", "net_income"],
      balance: ["net_debt", "total_equity"],
      cashflow: ["free_cash_flow"],
    },
  },
}

const DEFAULT_VALUATION_FORMULA: ValuationFormulaMeta = {
  formula: "FV/share = model output / Shares",
  explanation: "Model-specific details are available through persisted inputs and outputs.",
  assumptionKeys: [],
  technicalInputKeys: [],
  statementKeys: {
    income: ["revenue", "ebitda", "net_income"],
    balance: ["total_equity", "net_debt"],
    cashflow: ["free_cash_flow", "dividends_paid"],
  },
}

const STATEMENT_TITLES: Record<FinancialStatementTab, string> = {
  income: "Compte de resultat",
  balance: "Bilan",
  cashflow: "Cash-flow",
}

const VALUE_LABELS: Record<string, string> = {
  cost_of_equity: "Cost of equity",
  dividend_per_share: "Dividend / share",
  fade_years: "Fade years",
  fcf_growth_source: "FCF growth source",
  fcf_source: "FCF source",
  fcf_start: "Starting FCF",
  fcfe_source: "FCFE source",
  fcfe_start: "Starting FCFE",
  fcf_yield: "FCF yield",
  forecast_years: "Forecast years",
  growth: "Growth",
  growth_cap: "Growth cap",
  growth_source: "Growth source",
  justified_multiple_ratio_mask: "Selected justified ratios",
  market_cap: "Market cap",
  net_debt: "Net debt",
  net_debt_source: "Net debt source",
  own_multiples: "Own multiples",
  payout: "Payout",
  peer_min_count: "Peer minimum",
  peer_stats: "Peer medians",
  relative_multiple_ratio_mask: "Selected relative ratios",
  roe: "ROE",
  stable_payout_ratio: "Stable payout",
  sustainable_growth: "Sustainable growth",
  tax_rate: "Tax rate",
  terminal_growth: "Terminal growth",
  terminal_growth_firm: "Terminal growth firm",
  terminal_growth_equity: "Terminal growth equity",
  terminal_growth_basis: "Terminal growth basis",
  wacc: "WACC",
}

const ASSUMPTION_FIELDS = [
  ["risk_free_rate", "Taux sans risque"],
  ["equity_risk_premium", "Prime actions"],
  ["beta", "Beta"],
  ["cost_of_equity_floor", "Plancher Ke"],
  ["terminal_growth_firm", "g firm"],
  ["terminal_growth_equity", "g equity"],
  ["cost_of_debt", "Cout dette"],
  ["tax_rate", "Taux IS"],
  ["default_debt_weight", "Poids dette"],
] as const

const SCORE_SCOPE_LABELS = [
  ["value", "Valeur"],
  ["quality", "Qualite"],
] as const

const ESTIMATION_ASSUMPTION_KEYS = [
  "forecast_years",
  "growth_cap",
  "terminal_growth_firm",
  "tax_rate",
  "stable_payout_ratio",
] as const

const ESTIMATION_ASSUMPTION_KEY_SET = new Set<string>(ESTIMATION_ASSUMPTION_KEYS)

const ESTIMATION_ASSUMPTION_FALLBACK_META: Record<(typeof ESTIMATION_ASSUMPTION_KEYS)[number], FundamentalAssumptionMeta> = {
  forecast_years: {
    value: 5,
    label: "Horizon explicite",
    unit: "years",
    group: "projection",
    derivation: "Nombre d'annees explicites avant la valeur terminale.",
    source: "Valuation engine",
    plausible_range: [3, 7],
    scope: "desk",
    editable: true,
  },
  growth_cap: {
    value: 0.08,
    label: "Cap de croissance",
    unit: "percent",
    group: "projection",
    derivation: "Borne haute appliquee aux proxys de croissance.",
    source: "Valuation engine",
    plausible_range: [0.03, 0.15],
    scope: "desk",
    editable: true,
  },
  terminal_growth_firm: {
    value: 0.025,
    label: "Croissance terminale firm",
    unit: "percent",
    group: "projection",
    derivation: "Point d'arrivee de la trajectoire de croissance operationnelle.",
    source: "ROIC et reinvestissement historiques",
    plausible_range: [0, 0.055],
    scope: "symbol",
    editable: true,
  },
  tax_rate: {
    value: 0.35,
    label: "Taux IS",
    unit: "percent",
    group: "projection",
    derivation: "Taux d'impot applique a l'EBIT pour construire le NOPAT.",
    source: "Valuation engine",
    plausible_range: [0.20, 0.40],
    scope: "desk",
    editable: true,
  },
  stable_payout_ratio: {
    value: 0.55,
    label: "Payout stable",
    unit: "percent",
    group: "projection",
    derivation: "Fallback de distribution lorsque le payout historique est incomplet.",
    source: "Valuation engine",
    plausible_range: [0, 0.90],
    scope: "desk",
    editable: true,
  },
}

const ESTIMATION_STATEMENT_KEYS = new Set([
  "revenue",
  "ebit",
  "nopat",
  "capex",
  "delta_working_capital",
  "fcff",
  "fcfe",
  "net_income",
  "dividends",
])

const ESTIMATION_HISTORICAL_ALIASES: Record<string, string[]> = {
  revenue: ["Clean_Chiffre_daffaires", "Chiffre_daffaires", "Revenue", "Total_Revenue", "Total_Revenues", "TotalRevenue"],
  ebit: ["EBIT", "Operating_Income", "OperatingIncome", "Resultat_dexploitation", "Resultat_Exploitation"],
  nopat: ["NOPAT"],
  capex: ["Capex", "CAPEX", "Capital_Expenditure", "Capital_Expenditures"],
  delta_working_capital: ["Delta_Working_Capital", "Change_in_Working_Capital", "Variation_BFR"],
  fcff: ["FCFF", "Free_Cash_Flow", "Levered_Free_Cash_Flow"],
  fcfe: ["FCFE", "Free_Cash_Flow_to_Equity"],
  net_income: ["Clean_Resultat_net", "Resultat_net", "NetIncome", "Net_Income", "IS_Net_Income"],
  dividends: ["Clean_Dividendes", "Dividendes", "Dividends_Paid", "Cash_Dividends_Paid"],
}

const WORKING_CAPITAL_HISTORICAL_ALIASES = ["Working_Capital", "BFR"]
const HISTORICAL_TAX_ALIASES = ["Income_Tax_Expense", "Impots_sur_les_resultats"]
const HISTORICAL_TAX_RATE_ALIASES = ["Tax_Rate", "Effective_Tax_Rate"]
const HISTORICAL_REVENUE_GROWTH_ALIASES = ["Revenue_Growth"]
const HISTORICAL_DEPRECIATION_AMORTIZATION_ALIASES = ["Depreciation_Amortization", "DandA", "Dotations_dexploitation"]
const HISTORICAL_PAYOUT_ALIASES = ["Dividend_Payout", "Payout_Ratio"]

const COMPARABLE_METRICS = [
  "PER",
  "EV_to_EBITDA",
  "Price_to_Book",
  "Price_to_Sales",
  "ROE",
  "Dividend_Yield",
  "Revenue_Growth",
] as const

const VALUATION_COMPARABLE_METRICS = ["PER", "EV_to_EBITDA", "Price_to_Book", "Price_to_Sales"] as const

const COMPARABLE_METRIC_LABELS: Record<string, string> = {
  PER: "P/E",
  EV_to_EBITDA: "EV/EBITDA",
  Price_to_Book: "P/B",
  Price_to_Sales: "P/S",
  ROE: "ROE",
  Dividend_Yield: "Div Yield",
  Revenue_Growth: "g CA",
}

const COMPARABLE_PERCENT_METRICS = new Set(["ROE", "Dividend_Yield", "Revenue_Growth"])
const LOWER_BETTER_COMPARABLE_METRICS = new Set(["PER", "EV_to_EBITDA", "Price_to_Book", "Price_to_Sales"])
const DEFAULT_FORWARD_GROWTH = 0.03
const DEFAULT_STABLE_PAYOUT = 0.55

type ComparableIndexDefinition = {
  id: string
  name: string
  symbols?: string[]
  component_shares?: Record<string, number>
  components?: Array<{ symbol: string; shares: number }>
  is_weighted_complete?: boolean
}

type ComparableChoice = {
  id: string
  type: "sector" | "index"
  name: string
  label: string
  sector?: string | null
  symbols: string[]
  component_shares: Record<string, number>
  components: Array<{ symbol: string; shares: number }>
  containsTarget: boolean
  isWeighted: boolean
}

type ComparableBenchmarkView = {
  metric_key: string
  selected_value: number | null
  weighted_including_target: number | null
  weighted_excluding_target: number | null
  median: number | null
  eligible_count: number
  weighted_count: number
  missing_metric_count: number
  missing_weight_count: number
}

type ComparablePeerView = {
  symbol: string
  company_name: string
  display_name?: string | null
  sector?: string | null
  current_price: number | null
  shares: number | null
  market_value: number | null
  base_weight: number | null
  is_target: boolean
  is_comparator_member: boolean
  metrics: Record<string, number | null>
  weights: Record<string, number | null>
  contributions: Record<string, number | null>
  warnings: string[]
}

type ComparableView = {
  symbol: string
  comparator: {
    type: "sector" | "index"
    id: string
    name: string
    sector?: string | null
    target_in_comparator: boolean
    weight_source: string
  }
  metric_keys: string[]
  selected_metrics: Record<string, number | null>
  benchmarks: Record<string, ComparableBenchmarkView>
  peers: ComparablePeerView[]
  warnings: string[]
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

function asPositiveNumber(value: unknown): number | null {
  const numberValue = asNumber(value)
  return numberValue != null && numberValue > 0 ? numberValue : null
}

function asRatio(value: unknown): number | null {
  const numberValue = asNumber(value)
  if (numberValue == null) return null
  return Math.abs(numberValue) > 2 ? numberValue / 100 : numberValue
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}

function boundedMask(value: number | null, fallback: number, max: number): number {
  if (value == null) return fallback
  return Math.max(0, Math.min(max, Math.trunc(value)))
}

function detailRatioMask(
  detail: FundamentalStockDetail,
  draft: Record<string, number>,
  key: string,
  fallback: number,
  max: number,
): number {
  return boundedMask(asNumber(draft[key]) ?? asNumber(detail.assumptions[key]), fallback, max)
}

function enabledRatioKeys(definitions: MultipleRatioDefinition[], mask: number): string[] {
  return definitions.filter((item) => (mask & item.bit) !== 0).map((item) => item.key)
}

function enabledRelativeValuationMetrics(detail: FundamentalStockDetail | null): string[] {
  const mask = detail
    ? detailRatioMask(detail, {}, RELATIVE_MULTIPLE_RATIO_MASK_KEY, RELATIVE_MULTIPLE_RATIO_DEFAULT_MASK, RELATIVE_MULTIPLE_RATIO_DEFAULT_MASK)
    : RELATIVE_MULTIPLE_RATIO_DEFAULT_MASK
  return enabledRatioKeys(RELATIVE_MULTIPLE_RATIOS, mask)
}

function enabledRelativeValuationMetricsForDraft(detail: FundamentalStockDetail | null, draft: Record<string, number>): string[] {
  const mask = detail
    ? detailRatioMask(detail, draft, RELATIVE_MULTIPLE_RATIO_MASK_KEY, RELATIVE_MULTIPLE_RATIO_DEFAULT_MASK, RELATIVE_MULTIPLE_RATIO_DEFAULT_MASK)
    : RELATIVE_MULTIPLE_RATIO_DEFAULT_MASK
  return enabledRatioKeys(RELATIVE_MULTIPLE_RATIOS, mask)
}

function recordNumber(record: Record<string, unknown>, key: string): number | null {
  return asNumber(record[key])
}

function fmtNumber(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "-"
  return value.toLocaleString("fr-FR", { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

function fmtMoney(value: number | null | undefined, digits = 0): string {
  if (value == null || Number.isNaN(value)) return "-"
  return value.toLocaleString("fr-FR", { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

function fmtPct(value: number | null | undefined, digits = 1, sign = true): string {
  if (value == null || Number.isNaN(value)) return "-"
  return `${value >= 0 && sign ? "+" : ""}${(value * 100).toFixed(digits)}%`
}

function fmtAssumptionValue(value: unknown, unit?: string | null): string {
  const numberValue = asNumber(value)
  if (numberValue == null) return value == null || value === "" ? "-" : String(value)
  if (unit === "percent") return fmtPct(numberValue, 2, false)
  if (unit === "years" || unit === "count") return fmtNumber(numberValue, 0)
  if (unit === "x") return fmtRatio(numberValue, 2)
  if (unit === "flag") return numberValue >= 0.5 ? "Oui" : "Non"
  return fmtNumber(numberValue, 3)
}

function assumptionRangeLabel(range: number[] | null | undefined, unit?: string | null): string {
  if (!range || range.length < 2) return "-"
  return `${fmtAssumptionValue(range[0], unit)} - ${fmtAssumptionValue(range[1], unit)}`
}

function editableAssumptionKeys(methodology?: FundamentalMethodology): string[] {
  if (!methodology) return Array.from(new Set([...ASSUMPTION_FIELDS.map(([key]) => key), ...ESTIMATION_ASSUMPTION_KEYS, JUSTIFIED_MULTIPLE_RATIO_MASK_KEY, RELATIVE_MULTIPLE_RATIO_MASK_KEY]))
  return Object.entries(methodology.assumptions)
    .filter(([, meta]) => meta.editable !== false)
    .map(([key]) => key)
}

function editableAssumptionDraft(methodology: FundamentalMethodology | undefined, draft: Record<string, number>): Record<string, number> {
  const allowed = new Set(editableAssumptionKeys(methodology))
  return Object.fromEntries(Object.entries(draft).filter(([key, value]) => allowed.has(key) && Number.isFinite(value)))
}

function fmtRatio(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "-"
  return `${value.toFixed(digits)}x`
}

function fmtCap(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "-"
  const abs = Math.abs(value)
  if (abs >= 1_000_000_000) return `${fmtNumber(value / 1_000_000_000, 1)} Bn`
  if (abs >= 1_000_000) return `${fmtNumber(value / 1_000_000, 1)} M`
  return fmtMoney(value)
}

function fmtCompactMad(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "-"
  const abs = Math.abs(value)
  if (abs >= 1_000_000) return `${fmtNumber(value / 1_000_000, 1)} M`
  if (abs >= 1_000) return `${fmtNumber(value / 1_000, 0)} k`
  return fmtMoney(value)
}

function comparableMetricLabel(metric: string): string {
  return COMPARABLE_METRIC_LABELS[metric] ?? metric.replaceAll("_", " ")
}

function formatComparableValue(metric: string, value: number | null | undefined): string {
  if (metric === "Dividend_Yield") {
    if (value == null || Number.isNaN(value)) return "-"
    const percentValue = Math.abs(value) >= 0.25 ? value : value * 100
    return `${fmtNumber(percentValue, 1)}%`
  }
  if (COMPARABLE_PERCENT_METRICS.has(metric)) return fmtPct(value, 1, false)
  return fmtRatio(value, 1)
}

function formatComparableContribution(metric: string, value: number | null | undefined): string {
  if (metric === "Dividend_Yield") return value == null || Number.isNaN(value) ? "-" : `${fmtNumber(value, 2)}%`
  return formatComparableValue(metric, value)
}

function boundedForwardGrowth(value: number | null, fallback = DEFAULT_FORWARD_GROWTH): number {
  const growth = value ?? fallback
  return Math.max(-0.05, Math.min(0.10, growth))
}

function firstRatioMetric(metrics: Record<string, number | null> | undefined, names: string[]): number | null {
  for (const name of names) {
    const value = asRatio(metrics?.[name])
    if (value != null) return value
  }
  return null
}

function forwardMultiple(value: number | null, growth: number | null): number | null {
  if (value == null || value <= 0) return value
  const denominator = 1 + boundedForwardGrowth(growth)
  return denominator > 0 ? value / denominator : value
}

function sustainableBookGrowth(metrics: Record<string, number | null>, assumptions?: Record<string, unknown>): number | null {
  const roe = asRatio(metrics.ROE)
  if (roe == null) {
    return firstRatioMetric(metrics, ["NetIncome_Growth", "Revenue_Growth"])
  }
  const payout = asRatio(metrics.Dividend_Payout) ?? asRatio(assumptions?.stable_payout_ratio) ?? DEFAULT_STABLE_PAYOUT
  const retention = Math.max(0, Math.min(1, 1 - payout))
  return roe * retention
}

function estimatedComparableMetricValue(
  metric: string,
  metrics: Record<string, number | null>,
  assumptions?: Record<string, unknown>,
): number | null {
  const direct = asNumber(metrics[metric])
  if (metric === "PER") {
    return forwardMultiple(direct, firstRatioMetric(metrics, ["NetIncome_Growth", "EBIT_Growth", "Revenue_Growth"]))
  }
  if (metric === "Price_to_Sales") {
    return forwardMultiple(direct, firstRatioMetric(metrics, ["Revenue_Growth"]))
  }
  if (metric === "EV_to_EBITDA") {
    return forwardMultiple(direct, firstRatioMetric(metrics, ["EBITDA_Growth", "EBIT_Growth", "Revenue_Growth"]))
  }
  if (metric === "Price_to_Book") {
    return forwardMultiple(direct, sustainableBookGrowth(metrics, assumptions))
  }
  if (metric === "ROE") {
    const roe = asRatio(direct)
    const earningsGrowth = boundedForwardGrowth(firstRatioMetric(metrics, ["NetIncome_Growth", "EBIT_Growth", "Revenue_Growth"]))
    const bookGrowth = boundedForwardGrowth(sustainableBookGrowth(metrics, assumptions))
    return roe == null ? direct : roe * (1 + earningsGrowth) / (1 + bookGrowth)
  }
  if (metric === "Revenue_Growth") {
    return firstRatioMetric(metrics, ["Revenue_Growth"]) ?? direct
  }
  return direct
}

function comparableGapTone(metric: string, gap: number | null): string {
  if (gap == null) return "text-muted-foreground"
  if (LOWER_BETTER_COMPARABLE_METRICS.has(metric)) return gap <= 0 ? "t-pos" : "t-neg"
  return gap >= 0 ? "t-pos" : "t-neg"
}

function firstAnnualMetric(metrics: Record<string, number | null>, names: string[]): number | null {
  for (const name of names) {
    const value = asNumber(metrics[name])
    if (value != null) return value
  }
  return null
}

function latestAnnualMetric(detail: FundamentalStockDetail, names: string[]): number | null {
  const rows = [...detail.annual].sort((left, right) => right.statement_year - left.statement_year)
  for (const row of rows) {
    const value = firstAnnualMetric(row.metrics, names)
    if (value != null) return value
  }
  return null
}

function netDebtFromMetrics(metrics: Record<string, number | null>): number | null {
  const netDebt = asNumber(metrics.NetDebt)
  if (netDebt != null) return netDebt
  const debt = asNumber(metrics.Total_Debt) ?? asNumber(metrics.Debt_Total)
  const cash = asNumber(metrics.Cash) ?? asNumber(metrics.Cash_and_Equivalents)
  return debt != null && cash != null ? debt - cash : null
}

function evToEbitdaFairValue(peerMultiple: number | null, ebitda: number | null, netDebt: number | null, shares: number | null): number | null {
  if (peerMultiple == null || peerMultiple <= 0 || ebitda == null || ebitda <= 0 || netDebt == null || shares == null || shares <= 0) return null
  return Math.max(0, peerMultiple * ebitda - netDebt) / shares
}

function safeRatioValue(numerator: number | null, denominator: number | null): number | null {
  return numerator != null && denominator != null && denominator > 0 ? numerator / denominator : null
}

function currentMarketCap(detail: FundamentalStockDetail): number | null {
  const explicit = asNumber(detail.metrics.MarketCap_Calc)
  if (explicit != null) return explicit
  const price = asNumber(detail.metrics.Current_Price)
  const shares = asNumber(detail.metrics.Shares_Outstanding)
  return price != null && shares != null ? price * shares : null
}

function annualComparableMetricValue(
  metric: string,
  metrics: Record<string, number | null>,
  detail: FundamentalStockDetail,
  previousRevenue: number | null,
): number | null {
  const direct = asNumber(metrics[metric])
  if (direct != null) return direct

  const marketCap = currentMarketCap(detail)
  const revenue = firstAnnualMetric(metrics, ["Chiffre_daffaires", "Revenue", "Clean_Chiffre_daffaires"])
  const netIncome = firstAnnualMetric(metrics, ["Resultat_net", "NetIncome", "Clean_Resultat_net"])
  const equity = firstAnnualMetric(metrics, ["Total_Equity", "Equity"])
  const dividends = firstAnnualMetric(metrics, ["Dividendes", "Dividends_Paid", "Clean_Dividendes"])
  const ebitda = firstAnnualMetric(metrics, ["EBITDA"])

  if (metric === "PER") return safeRatioValue(marketCap, netIncome != null && netIncome > 0 ? netIncome : null)
  if (metric === "Price_to_Book") return safeRatioValue(marketCap, equity)
  if (metric === "Price_to_Sales") return safeRatioValue(marketCap, revenue)
  if (metric === "Dividend_Yield") {
    const ratio = safeRatioValue(dividends, marketCap)
    return ratio == null ? null : ratio * 100
  }
  if (metric === "EV_to_EBITDA") {
    const enterpriseValue = asNumber(detail.metrics.EnterpriseValue)
    return safeRatioValue(enterpriseValue, ebitda)
  }
  if (metric === "ROE") return safeRatioValue(netIncome, equity)
  if (metric === "Revenue_Growth") {
    const explicitGrowth = asNumber(metrics.Revenue_Growth_YoY) ?? asNumber(metrics.Revenue_Growth)
    if (explicitGrowth != null) return explicitGrowth
    return revenue != null && previousRevenue != null && previousRevenue > 0 ? revenue / previousRevenue - 1 : null
  }
  return null
}

function annualComparableMetricHistory(detail: FundamentalStockDetail, metric: string): Array<{ year: number; value: number }> {
  const rows = [...detail.annual].sort((left, right) => left.statement_year - right.statement_year)
  const out: Array<{ year: number; value: number }> = []
  let previousRevenue: number | null = null
  for (const row of rows) {
    const value = annualComparableMetricValue(metric, row.metrics, detail, previousRevenue)
    const revenue = firstAnnualMetric(row.metrics, ["Chiffre_daffaires", "Revenue", "Clean_Chiffre_daffaires"])
    if (value != null) out.push({ year: row.statement_year, value })
    if (revenue != null) previousRevenue = revenue
  }
  return out.reverse()
}

function normalizeComparableSymbol(value: unknown): string {
  return String(value ?? "").trim().toUpperCase()
}

function normalizeComparableSymbols(values: unknown[]): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const value of values) {
    const symbol = normalizeComparableSymbol(value)
    if (!symbol || seen.has(symbol)) continue
    seen.add(symbol)
    out.push(symbol)
  }
  return out
}

function comparableComponentShares(definition: ComparableIndexDefinition): Record<string, number> {
  const out: Record<string, number> = {}
  for (const [rawSymbol, rawShares] of Object.entries(definition.component_shares ?? {})) {
    const symbol = normalizeComparableSymbol(rawSymbol)
    const shares = Number(rawShares)
    if (symbol && Number.isFinite(shares) && shares > 0) out[symbol] = shares
  }
  for (const component of definition.components ?? []) {
    const symbol = normalizeComparableSymbol(component.symbol)
    const shares = Number(component.shares)
    if (symbol && Number.isFinite(shares) && shares > 0) out[symbol] = shares
  }
  return out
}

function comparableChoiceForIndex(definition: ComparableIndexDefinition, targetSymbol: string): ComparableChoice | null {
  const componentShares = comparableComponentShares(definition)
  const componentSymbols = (definition.components ?? []).map((component) => component.symbol)
  const symbols = normalizeComparableSymbols([
    ...(definition.symbols ?? []),
    ...componentSymbols,
    ...Object.keys(componentShares),
  ])
  if (symbols.length === 0) return null
  const target = normalizeComparableSymbol(targetSymbol)
  const components = symbols
    .map((symbol) => ({ symbol, shares: componentShares[symbol] }))
    .filter((component): component is { symbol: string; shares: number } => Number.isFinite(component.shares) && component.shares > 0)
  const isWeighted = symbols.every((symbol) => Number.isFinite(componentShares[symbol]) && componentShares[symbol] > 0)
  return {
    id: `index:${definition.id || definition.name}`,
    type: "index",
    name: definition.name,
    label: `${definition.name}${symbols.includes(target) ? " - membre" : ""}`,
    symbols,
    component_shares: componentShares,
    components,
    containsTarget: symbols.includes(target),
    isWeighted,
  }
}

function defaultSectorComparableChoice(
  detail: FundamentalStockDetail,
  selectedRow: FundamentalUniverseRow | null,
  rows: FundamentalUniverseRow[],
): ComparableChoice {
  const sector = selectedRow?.sector ?? detail.sector ?? null
  const sectorSymbols = sector
    ? rows.filter((item) => item.sector === sector).map((item) => item.symbol)
    : []
  return {
    id: "sector",
    type: "sector",
    name: sector ? `Sector - ${sector}` : "Sector",
    label: sector ? `Secteur - ${sector}` : "Secteur",
    sector,
    symbols: normalizeComparableSymbols([...sectorSymbols, detail.symbol]),
    component_shares: {},
    components: [],
    containsTarget: true,
    isWeighted: true,
  }
}

function medianValue(values: number[]): number | null {
  if (values.length === 0) return null
  const sorted = [...values].sort((left, right) => left - right)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}

function rowMetaBySymbol(rows: FundamentalUniverseRow[], selectedRow: FundamentalUniverseRow | null): Map<string, FundamentalUniverseRow> {
  const out = new Map<string, FundamentalUniverseRow>()
  for (const item of rows) {
    const symbol = normalizeComparableSymbol(item.symbol)
    if (symbol) out.set(symbol, item)
  }
  if (selectedRow) {
    const symbol = normalizeComparableSymbol(selectedRow.symbol)
    if (symbol) out.set(symbol, selectedRow)
  }
  return out
}

function snapshotBySymbol(snapshots: Record<string, FundamentalLightSnapshot | null> | undefined): Map<string, FundamentalLightSnapshot> {
  const out = new Map<string, FundamentalLightSnapshot>()
  for (const [rawSymbol, snapshot] of Object.entries(snapshots ?? {})) {
    if (!snapshot) continue
    const key = normalizeComparableSymbol(snapshot.symbol || rawSymbol)
    if (key) out.set(key, snapshot)
  }
  return out
}

function buildComparablesView({
  detail,
  selectedRow,
  rows,
  choice,
  snapshots,
}: {
  detail: FundamentalStockDetail
  selectedRow: FundamentalUniverseRow | null
  rows: FundamentalUniverseRow[]
  choice: ComparableChoice
  snapshots: Record<string, FundamentalLightSnapshot | null> | undefined
}): ComparableView {
  const targetSymbol = normalizeComparableSymbol(detail.symbol)
  const metadata = rowMetaBySymbol(rows, selectedRow)
  const snapshotMap = snapshotBySymbol(snapshots)
  const comparatorSymbols = new Set(normalizeComparableSymbols(choice.symbols))
  const symbols = normalizeComparableSymbols([...choice.symbols, detail.symbol])
  const warnings: string[] = []

  if (choice.type === "index" && !choice.isWeighted) {
    warnings.push("Certaines composantes n'ont pas de nombre d'actions; leur poids sera ignore.")
  }
  if (choice.type === "index" && !choice.containsTarget) {
    warnings.push("Le titre selectionne n'est pas membre du benchmark; il est affiche hors poids.")
  }
  if (choice.type === "sector" && symbols.length <= 1) {
    warnings.push("Pas assez de titres sectoriels disponibles dans l'univers courant.")
  }

  const peers: ComparablePeerView[] = symbols.map((symbol) => {
    const snapshot = snapshotMap.get(symbol)
    const meta = metadata.get(symbol)
    const isTarget = symbol === targetSymbol
    const sourceMetrics = isTarget ? detail.metrics : (snapshot?.metrics ?? {})
    const metrics: Record<string, number | null> = {}
    for (const metric of COMPARABLE_METRICS) {
      metrics[metric] = estimatedComparableMetricValue(metric, sourceMetrics, isTarget ? detail.assumptions : undefined)
    }

    const currentPrice =
      asNumber(snapshot?.metrics.Current_Price) ??
      asNumber(meta?.current_price) ??
      (isTarget ? asNumber(detail.metrics.Current_Price) : null)
    const shares = choice.type === "index" ? asNumber(choice.component_shares[symbol]) : null
    const marketCap = asNumber(meta?.market_cap) ?? asNumber(snapshot?.metrics.MarketCap_Calc)
    const marketValue = choice.type === "index"
      ? shares != null && currentPrice != null ? shares * currentPrice : null
      : marketCap
    const peerWarnings: string[] = []

    if (!snapshot && !isTarget) peerWarnings.push("snapshot manquant")
    if (choice.type === "index" && !shares && comparatorSymbols.has(symbol)) peerWarnings.push("shares manquantes")
    if (!marketValue && comparatorSymbols.has(symbol)) peerWarnings.push("poids manquant")

    return {
      symbol,
      company_name: meta?.company_name ?? snapshot?.symbol ?? detail.company_name,
      display_name: meta?.display_name ?? (isTarget ? detail.display_name : null),
      sector: meta?.sector ?? (isTarget ? detail.sector : null),
      current_price: currentPrice,
      shares,
      market_value: marketValue,
      base_weight: marketValue,
      is_target: isTarget,
      is_comparator_member: comparatorSymbols.has(symbol),
      metrics,
      weights: {},
      contributions: {},
      warnings: peerWarnings,
    }
  })

  const selectedMetrics: Record<string, number | null> = {}
  const benchmarks: Record<string, ComparableBenchmarkView> = {}

  for (const metric of COMPARABLE_METRICS) {
    const selectedValue = estimatedComparableMetricValue(metric, detail.metrics, detail.assumptions) ?? peers.find((peer) => peer.is_target)?.metrics[metric] ?? null
    selectedMetrics[metric] = selectedValue

    const eligible = peers.filter((peer) => peer.is_comparator_member && peer.metrics[metric] != null)
    const weightedRows = eligible.filter((peer) => peer.market_value != null && peer.market_value > 0)
    const weightedIncludingDenominator = weightedRows.reduce((acc, peer) => acc + (peer.market_value ?? 0), 0)
    const weightedIncludingTarget = weightedIncludingDenominator > 0
      ? weightedRows.reduce((acc, peer) => acc + (peer.metrics[metric] ?? 0) * (peer.market_value ?? 0), 0) / weightedIncludingDenominator
      : null

    const weightedExcludingRows = weightedRows.filter((peer) => !peer.is_target)
    const weightedExcludingDenominator = weightedExcludingRows.reduce((acc, peer) => acc + (peer.market_value ?? 0), 0)
    const weightedExcludingTarget = weightedExcludingDenominator > 0
      ? weightedExcludingRows.reduce((acc, peer) => acc + (peer.metrics[metric] ?? 0) * (peer.market_value ?? 0), 0) / weightedExcludingDenominator
      : null

    for (const peer of peers) {
      if (!peer.is_comparator_member || peer.metrics[metric] == null || peer.market_value == null || peer.market_value <= 0 || weightedIncludingDenominator <= 0) {
        peer.weights[metric] = null
        peer.contributions[metric] = null
        continue
      }
      const weight = peer.market_value / weightedIncludingDenominator
      peer.weights[metric] = weight
      peer.contributions[metric] = (peer.metrics[metric] ?? 0) * weight
    }

    benchmarks[metric] = {
      metric_key: metric,
      selected_value: selectedValue,
      weighted_including_target: weightedIncludingTarget,
      weighted_excluding_target: weightedExcludingTarget,
      median: medianValue(eligible.map((peer) => peer.metrics[metric]).filter((value): value is number => value != null)),
      eligible_count: eligible.length,
      weighted_count: weightedRows.length,
      missing_metric_count: peers.filter((peer) => peer.is_comparator_member && peer.metrics[metric] == null).length,
      missing_weight_count: eligible.filter((peer) => peer.market_value == null || peer.market_value <= 0).length,
    }
  }
  selectedMetrics.EBITDA = asNumber(detail.metrics.EBITDA) ?? latestAnnualMetric(detail, ["EBITDA", "Excedent_brut_dexploitation"])
  selectedMetrics.NetDebt = netDebtFromMetrics(detail.metrics)
  selectedMetrics.Total_Debt = asNumber(detail.metrics.Total_Debt) ?? latestAnnualMetric(detail, ["Total_Debt", "Debt_Total"])
  selectedMetrics.Cash = asNumber(detail.metrics.Cash) ?? asNumber(detail.metrics.Cash_and_Equivalents) ?? latestAnnualMetric(detail, ["Cash", "Cash_and_Equivalents"])
  selectedMetrics.Shares_Outstanding = asNumber(detail.metrics.Shares_Outstanding)

  peers.sort((left, right) => {
    if (left.is_target !== right.is_target) return left.is_target ? -1 : 1
    const leftWeight = left.weights.PER ?? left.base_weight ?? 0
    const rightWeight = right.weights.PER ?? right.base_weight ?? 0
    return rightWeight - leftWeight || left.symbol.localeCompare(right.symbol)
  })

  return {
    symbol: detail.symbol,
    comparator: {
      type: choice.type,
      id: choice.id,
      name: choice.name,
      sector: choice.sector,
      target_in_comparator: comparatorSymbols.has(targetSymbol),
      weight_source: choice.type === "index" ? "free float market value" : "market cap",
    },
    metric_keys: [...COMPARABLE_METRICS],
    selected_metrics: selectedMetrics,
    benchmarks,
    peers,
    warnings,
  }
}

function comparableModelSummary(
  comparables: ComparableView,
  currentPrice: number | null | undefined,
  metricKeys: readonly string[] = VALUATION_COMPARABLE_METRICS,
): ComparableModelSummary {
  const current = asNumber(currentPrice)
  const targetEbitda = asPositiveNumber(comparables.selected_metrics.EBITDA)
  const targetNetDebt = asNumber(comparables.selected_metrics.NetDebt)
  const targetShares = asPositiveNumber(comparables.selected_metrics.Shares_Outstanding)
  const impliedPrices: Array<{ metric: string; fairValue: number; selectedValue: number; benchmark: number }> = []
  for (const metric of metricKeys) {
    const selectedValue = asNumber(comparables.selected_metrics[metric])
    const benchmark = comparables.benchmarks[metric]
    const primaryBenchmark = benchmark?.weighted_excluding_target ?? benchmark?.weighted_including_target ?? benchmark?.median ?? null
    if (primaryBenchmark == null || primaryBenchmark <= 0) {
      continue
    }
    if (metric === "EV_to_EBITDA") {
      const bridgedFairValue = evToEbitdaFairValue(primaryBenchmark, targetEbitda, targetNetDebt, targetShares)
      if (bridgedFairValue != null && selectedValue != null) {
        impliedPrices.push({
          metric,
          fairValue: bridgedFairValue,
          selectedValue,
          benchmark: primaryBenchmark,
        })
      }
      continue
    }
    if (current == null || current <= 0 || selectedValue == null || selectedValue <= 0) {
      continue
    }
    impliedPrices.push({
      metric,
      fairValue: current * primaryBenchmark / selectedValue,
      selectedValue,
      benchmark: primaryBenchmark,
    })
  }
  const peerFairValueSummary = comparablePeerFairValueSummary(comparables, current, metricKeys)
  const fairValue = peerFairValueSummary.fairValue ?? medianValue(impliedPrices.map((item) => item.fairValue))
  return {
    fairValue,
    upside: fairValue != null && current != null && current > 0 ? fairValue / current - 1 : null,
    count: impliedPrices.length,
    impliedPrices,
    peerCount: peerFairValueSummary.peerCount,
    weightSource: peerFairValueSummary.weightSource,
    peerFairValues: peerFairValueSummary.rows,
  }
}

function emptyComparableModelSummary(): ComparableModelSummary {
  return {
    fairValue: null,
    upside: null,
    count: 0,
    impliedPrices: [],
    peerCount: 0,
    weightSource: "none",
    peerFairValues: [],
  }
}

function comparablePeerFairValueSummary(
  comparables: ComparableView,
  currentPrice: number | null,
  metricKeys: readonly string[] = VALUATION_COMPARABLE_METRICS,
): { fairValue: number | null; peerCount: number; weightSource: string; rows: ComparablePeerFairValue[] } {
  if (currentPrice == null || currentPrice <= 0) {
    return { fairValue: null, peerCount: 0, weightSource: "none", rows: [] }
  }
  const targetEbitda = asPositiveNumber(comparables.selected_metrics.EBITDA)
  const targetNetDebt = asNumber(comparables.selected_metrics.NetDebt)
  const targetShares = asPositiveNumber(comparables.selected_metrics.Shares_Outstanding)

  const rows = comparables.peers
    .filter((peer) => peer.is_comparator_member && !peer.is_target)
    .map((peer) => {
      const metricFairValues: Record<string, number | null> = {}
      for (const metric of metricKeys) {
        const ownMultiple = asPositiveNumber(comparables.selected_metrics[metric])
        const peerMultiple = asPositiveNumber(peer.metrics[metric])
        metricFairValues[metric] = metric === "EV_to_EBITDA"
          ? evToEbitdaFairValue(peerMultiple, targetEbitda, targetNetDebt, targetShares)
          : ownMultiple != null && peerMultiple != null
            ? currentPrice * peerMultiple / ownMultiple
            : null
      }
      const values = Object.values(metricFairValues).filter((value): value is number => value != null && value > 0)
      const fairValue = medianValue(values)
      return {
        symbol: peer.symbol,
        displayName: peer.display_name ?? peer.company_name ?? peer.symbol,
        sector: peer.sector ?? null,
        baseWeight: asPositiveNumber(peer.base_weight),
        fairValue,
        metricFairValues,
      }
    })
    .filter((row) => row.fairValue != null)

  const marketWeightedRows = rows.filter((row) => row.baseWeight != null)
  const useMarketWeights = marketWeightedRows.length > 0
  const denominator = useMarketWeights
    ? marketWeightedRows.reduce((acc, row) => acc + (row.baseWeight ?? 0), 0)
    : rows.length

  if (denominator <= 0) {
    return { fairValue: null, peerCount: rows.length, weightSource: "none", rows: [] }
  }

  const weightedRows: ComparablePeerFairValue[] = rows.map((row) => {
    const weight = useMarketWeights
      ? row.baseWeight != null ? row.baseWeight / denominator : null
      : 1 / denominator
    const weightedFairValue = weight != null && row.fairValue != null ? row.fairValue * weight : null
    return {
      symbol: row.symbol,
      displayName: row.displayName,
      sector: row.sector,
      weight,
      baseWeight: row.baseWeight,
      fairValue: row.fairValue,
      weightedFairValue,
      upside: row.fairValue != null ? row.fairValue / currentPrice - 1 : null,
      metricFairValues: row.metricFairValues,
    }
  })

  const fairValue = weightedRows.reduce((acc, row) => acc + (row.weightedFairValue ?? 0), 0)
  const weightedCount = weightedRows.filter((row) => row.weightedFairValue != null).length
  return {
    fairValue: weightedCount > 0 ? fairValue : null,
    peerCount: weightedCount,
    weightSource: useMarketWeights ? comparables.comparator.weight_source : "equal weight",
    rows: weightedRows,
  }
}

function useComparableChoices(
  detail: FundamentalStockDetail | null,
  selectedRow: FundamentalUniverseRow | null,
  rows: FundamentalUniverseRow[],
) {
  const { data: dashboardIndices } = useSWR<DashboardCustomIndex[]>(
    "fundamental-comparable-indices",
    () => fetchDashboardIndices().catch(() => []),
    { revalidateOnFocus: false, dedupingInterval: 60_000 },
  )
  return useMemo<ComparableChoice[]>(() => {
    if (!detail) return []
    const sectorChoice = defaultSectorComparableChoice(detail, selectedRow, rows)
    const userIndices = dashboardIndices ?? []
    const builtInIndices: ComparableIndexDefinition[] = [
      BUILTIN_WEIGHTED_MASI_INDEX,
      ...BUILTIN_CUSTOM_DASHBOARD_INDICES,
    ].filter((builtIn) => {
      const builtInName = builtIn.name.trim().toLowerCase()
      return !userIndices.some(
        (definition) =>
          definition.id === builtIn.id ||
          definition.name.trim().toLowerCase() === builtInName,
      )
    })
    const sourceIndices: ComparableIndexDefinition[] = [...builtInIndices, ...userIndices]
    const seenIds = new Set<string>()
    const seenNames = new Set<string>()
    const indexChoices = sourceIndices
      .map((definition) => comparableChoiceForIndex(definition, detail.symbol))
      .filter((choice): choice is ComparableChoice => Boolean(choice))
      .filter((choice) => choice.containsTarget)
      .filter((choice) => {
        const id = choice.id.trim().toLowerCase()
        const name = choice.name.trim().toLowerCase()
        if (seenIds.has(id) || seenNames.has(name)) return false
        seenIds.add(id)
        seenNames.add(name)
        return true
      })
    return [sectorChoice, ...indexChoices]
  }, [dashboardIndices, detail, rows, selectedRow])
}

function useOptionalSelectedComparableView(
  detail: FundamentalStockDetail | null,
  selectedRow: FundamentalUniverseRow | null,
  rows: FundamentalUniverseRow[],
  selectedComparatorId: string,
) {
  const comparatorChoices = useComparableChoices(detail, selectedRow, rows)
  const selectedComparator = comparatorChoices.find((choice) => choice.id === selectedComparatorId) ?? comparatorChoices[0] ?? null
  const comparableSymbols = useMemo(
    () => detail && selectedComparator ? normalizeComparableSymbols([...selectedComparator.symbols, detail.symbol]) : [],
    [detail, selectedComparator],
  )
  const {
    data: comparableSnapshots,
    error: comparableSnapshotsError,
    isLoading,
  } = useSWR<Record<string, FundamentalLightSnapshot | null>>(
    comparableSymbols.length ? ["fundamental-comparable-snapshots", comparableSymbols.join("|")] : null,
    () => getFundamentalSnapshotBatch(comparableSymbols),
    { keepPreviousData: true, revalidateOnFocus: false, dedupingInterval: 60_000 },
  )
  const comparables = useMemo(
    () => detail && selectedComparator
      ? buildComparablesView({ detail, selectedRow, rows, choice: selectedComparator, snapshots: comparableSnapshots })
      : null,
    [comparableSnapshots, detail, rows, selectedComparator, selectedRow],
  )
  return { comparatorChoices, selectedComparator, comparables, comparableSnapshots, comparableSnapshotsError, isLoading }
}

function useSelectedComparableView(
  detail: FundamentalStockDetail,
  selectedRow: FundamentalUniverseRow | null,
  rows: FundamentalUniverseRow[],
  selectedComparatorId: string,
) {
  const comparatorChoices = useComparableChoices(detail, selectedRow, rows)
  const selectedComparator = comparatorChoices.find((choice) => choice.id === selectedComparatorId) ?? comparatorChoices[0]
  const comparableSymbols = useMemo(
    () => normalizeComparableSymbols([...selectedComparator.symbols, detail.symbol]),
    [detail.symbol, selectedComparator],
  )
  const {
    data: comparableSnapshots,
    error: comparableSnapshotsError,
    isLoading,
  } = useSWR<Record<string, FundamentalLightSnapshot | null>>(
    comparableSymbols.length ? ["fundamental-comparable-snapshots", comparableSymbols.join("|")] : null,
    () => getFundamentalSnapshotBatch(comparableSymbols),
    { keepPreviousData: true, revalidateOnFocus: false, dedupingInterval: 60_000 },
  )
  const comparables = useMemo(
    () => buildComparablesView({ detail, selectedRow, rows, choice: selectedComparator, snapshots: comparableSnapshots }),
    [comparableSnapshots, detail, rows, selectedComparator, selectedRow],
  )
  return { comparatorChoices, selectedComparator, comparables, comparableSnapshots, comparableSnapshotsError, isLoading }
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "-"
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value.slice(0, 10)
  return parsed.toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" })
}

function scoreClass(value: number | null | undefined): string {
  if (value == null) return "text-muted-foreground"
  if (value >= 70) return "t-pos"
  if (value <= 35) return "t-neg"
  return "text-foreground"
}

function confidenceClass(confidence: string | null | undefined): string {
  if (confidence === "high") return "signal-conf-high"
  if (confidence === "medium") return "signal-conf-medium"
  if (confidence === "low") return "signal-conf-low"
  return "signal-conf-empty"
}

function confidenceLabel(score: number | null | undefined): string | null {
  if (score == null) return null
  if (score >= 0.75) return "high"
  if (score >= 0.45) return "medium"
  if (score > 0) return "low"
  return "unavailable"
}

function rowUpside(row: FundamentalUniverseRow | null | undefined): number | null {
  if (!row) return null
  return asNumber(row.ensemble?.upside_pct) ?? asNumber(row.valuation_summary.consensus_upside_pct)
}

function horizonPredictionsFor(
  detail: FundamentalStockDetail | null | undefined,
  row: FundamentalUniverseRow | null | undefined,
): FundamentalHorizonPrediction[] {
  const fromDetail = Array.isArray(detail?.horizon_predictions) ? detail.horizon_predictions : []
  if (fromDetail.length) return fromDetail
  return Array.isArray(row?.horizon_predictions) ? row.horizon_predictions : []
}

function predictionForHorizon(
  detail: FundamentalStockDetail | null | undefined,
  row: FundamentalUniverseRow | null | undefined,
  horizon: FundamentalHorizon,
): FundamentalHorizonPrediction | null {
  const predictions = horizonPredictionsFor(detail, row)
  return predictions.find((item) => item.horizon === horizon && item.available !== false && item.forward_target != null) ?? null
}

function effectiveHorizonPrediction(
  detail: FundamentalStockDetail | null | undefined,
  row: FundamentalUniverseRow | null | undefined,
  requested: FundamentalHorizon,
): { horizon: FundamentalHorizon; prediction: FundamentalHorizonPrediction | null } {
  const requestedPrediction = predictionForHorizon(detail, row, requested)
  if (requestedPrediction) return { horizon: requested, prediction: requestedPrediction }
  return { horizon: "year", prediction: predictionForHorizon(detail, row, "year") }
}

function rowConfidence(row: FundamentalUniverseRow | null | undefined): string | null {
  if (!row) return null
  const ensemble = confidenceLabel(row.ensemble?.confidence_score)
  if (ensemble) return ensemble
  const byModel = asRecord(row.valuation_summary.confidence_by_model)
  const values = Object.values(byModel)
  if (values.includes("high")) return "high"
  if (values.includes("medium")) return "medium"
  if (values.includes("low")) return "low"
  return values.includes("unavailable") ? "unavailable" : null
}

function rowAdv20(row: FundamentalUniverseRow | null | undefined): number | null {
  return asNumber(row?.adv20)
}

function isLiquidFundamentalRow(row: FundamentalUniverseRow): boolean {
  const adv20 = rowAdv20(row)
  return adv20 != null && adv20 >= FUNDAMENTAL_LIQUIDITY_ADV20_THRESHOLD
}

// MASI = Moroccan market. Non-MASI regions (yfinance imports) are tagged us/european/asian;
// MASI stocks carry market_region "masi" or null, so we exclude the known foreign regions.
const NON_MASI_MARKET_REGIONS = new Set(["us", "european", "asian"])

function isMasiFundamentalRow(row: FundamentalUniverseRow): boolean {
  const region = (row.market_region ?? "").trim().toLowerCase()
  return !NON_MASI_MARKET_REGIONS.has(region)
}

function scenarioFromQuery(value: string | null): Scenario {
  const token = String(value ?? "").trim().toLowerCase()
  return SCENARIOS.includes(token as Scenario) ? (token as Scenario) : "base"
}

function horizonFromQuery(value: string | null): FundamentalHorizon {
  const token = String(value ?? "").trim().toLowerCase()
  return FUNDAMENTAL_HORIZONS.some((item) => item.value === token) ? (token as FundamentalHorizon) : "year"
}

function tabFromQuery(value: string | null): DetailTab {
  const token = String(value ?? "").trim().toLowerCase()
  if (FUND_TABS.some((item) => item.value === token)) return token as DetailTab
  if (token === "summary" || token === "resume") return "thesis"
  if (token === "financials") return "estimates"
  if (token === "quality" || token === "qualite") return "quality"
  if (token === "valuation") return "valuation"
  return "thesis"
}

function weightModeFromQuery(value: string | null): WeightMode {
  return value?.trim() === "equal" ? "equal" : "ic"
}

function screensFor(detail: FundamentalStockDetail | null | undefined, row?: FundamentalUniverseRow | null): Record<string, unknown> {
  if (detail?.screens && Object.keys(detail.screens).length > 0) return detail.screens
  const diagnosticsScreens = asRecord(detail?.diagnostics?.screens)
  if (Object.keys(diagnosticsScreens).length > 0) return diagnosticsScreens
  return row?.screens ?? {}
}

function screenRecord(screens: Record<string, unknown>, name: string): Record<string, unknown> {
  return asRecord(screens[name])
}

function sortValue(row: FundamentalUniverseRow, sortKey: SortKey): number {
  if (sortKey === "upside") return rowUpside(row) ?? -Infinity
  if (sortKey === "value") return row.value_score ?? -Infinity
  if (sortKey === "quality") return row.quality_score ?? -Infinity
  if (sortKey === "conviction") return row.conviction ?? -Infinity
  if (sortKey === "market_cap") return row.market_cap ?? -Infinity
  if (sortKey === "magic") return row.magic_formula_score ?? -Infinity
  if (sortKey === "peg") return row.peg_value == null ? -Infinity : -row.peg_value
  if (sortKey === "altman") {
    const zoneScore = row.altman_zone === "safe" ? 3 : row.altman_zone === "grey" ? 2 : row.altman_zone === "distress" ? 1 : 0
    return zoneScore * 100 + (row.altman_z_score ?? 0)
  }
  if (sortKey === "eva") return row.eva_score ?? -Infinity
  return row.regression_adj_score ?? -Infinity
}

function revisionArrow(direction: string | null | undefined): ReactNode {
  if (direction === "up") return <span className="t-pos">^</span>
  if (direction === "down") return <span className="t-neg">v</span>
  return <span className="text-muted-foreground">-</span>
}

function recommendationClass(value: Recommendation | null | undefined): string {
  return value ? value.toLowerCase() : "not-rated"
}

function recommendationLabel(value: Recommendation | null | undefined): string {
  return value === "NR" || value == null ? "N/R" : value
}

function RecChip({ value }: { value: Recommendation | null | undefined }) {
  return <span className={cn("fund-rec-chip", recommendationClass(value))}>{recommendationLabel(value)}</span>
}

function compactFlagLabel(value: string): string {
  return value.replaceAll("_", " ")
}

function uniqueStrings(values: Array<string | null | undefined>): string[] {
  return Array.from(new Set(values.filter((item): item is string => Boolean(item))))
}

function ensembleForFlags(detail: FundamentalStockDetail | null | undefined, row?: FundamentalUniverseRow | null) {
  return detail?.ensemble ?? row?.ensemble ?? null
}

function ensembleWarningsFor(detail: FundamentalStockDetail | null | undefined, row?: FundamentalUniverseRow | null): string[] {
  const detailWarnings = detail?.ensemble?.warnings ?? []
  const rowWarnings = row?.ensemble?.warnings ?? []
  return uniqueStrings([...detailWarnings, ...rowWarnings])
}

function overallCoveragePct(detail: FundamentalStockDetail | null | undefined, row?: FundamentalUniverseRow | null): number | null {
  const scores = asRecord(detail?.scores)
  const detailCoverage = asRecord(detail?.coverage)
  const rowCoverage = asRecord(row?.coverage)
  return (
    asRatio(scores.overall_coverage_pct) ??
    asRatio(detailCoverage.overall_coverage_pct) ??
    asRatio(detailCoverage.coverage_pct) ??
    asRatio(rowCoverage.overall_coverage_pct) ??
    asRatio(rowCoverage.coverage_pct)
  )
}

function ratingFlagsFor(detail: FundamentalStockDetail | null | undefined, row?: FundamentalUniverseRow | null): string[] {
  const ensemble = ensembleForFlags(detail, row)
  const warnings = ensembleWarningsFor(detail, row)
  const coveragePct = overallCoveragePct(detail, row)
  const flags: string[] = []
  if (warnings.some((warning) => warning.startsWith("withheld_"))) flags.push("NR: target withheld")
  if (coveragePct != null && coveragePct < 0.5) flags.push("Coverage < 50%")
  else if (coveragePct != null && coveragePct < 0.7) flags.push("Partial coverage")
  if ((ensemble?.usable_model_count ?? 0) <= 0) flags.push("No usable valuation models")
  if (asNumber(ensemble?.model_dispersion_cv) != null && (asNumber(ensemble?.model_dispersion_cv) ?? 0) > 1) flags.push("High model dispersion")
  return uniqueStrings(flags)
}

function ScoreChip({ value }: { value: number | null | undefined }) {
  return <span className={cn("font-mono text-[11px] font-bold", scoreClass(value))}>{fmtNumber(value, 0)}</span>
}

function ScorePair({ valueScore, qualityScore }: { valueScore: number | null | undefined; qualityScore: number | null | undefined }) {
  return (
    <span className="inline-flex justify-end gap-1 font-mono text-[10px] font-bold">
      <span className={scoreClass(valueScore)}>V {fmtNumber(valueScore, 0)}</span>
      <span className={scoreClass(qualityScore)}>Q {fmtNumber(qualityScore, 0)}</span>
    </span>
  )
}

function LoadingRows() {
  return (
    <>
      {Array.from({ length: 10 }).map((_, index) => (
        <tr key={index}>
          <td colSpan={5}>
            <Skeleton className="h-7 w-full" />
          </td>
        </tr>
      ))}
    </>
  )
}

function UniverseScreen({
  rows,
  totalRows,
  liquidityFilter,
  selectedSymbol,
  isLoading,
  onSelect,
  onLiquidityFilterChange,
}: {
  rows: FundamentalUniverseRow[]
  totalRows: number
  liquidityFilter: boolean
  selectedSymbol: string | null
  isLoading: boolean
  onSelect: (symbol: string) => void
  onLiquidityFilterChange: (enabled: boolean) => void
}) {
  const [query, setQuery] = useState("")
  const [sortKey, setSortKey] = useState<SortKey>("upside")
  const [filter, setFilter] = useState<RecommendationFilter>("all")

  const filteredRows = useMemo(() => {
    const q = query.trim().toUpperCase()
    return [...rows]
      .filter((row) => {
        if (filter !== "all" && row.recommendation !== filter) return false
        if (!q) return true
        return `${row.symbol} ${row.company_name} ${row.display_name ?? ""} ${row.sector ?? ""}`.toUpperCase().includes(q)
      })
      .sort((a, b) => sortValue(b, sortKey) - sortValue(a, sortKey) || a.symbol.localeCompare(b.symbol))
  }, [filter, query, rows, sortKey])

  const summary = useMemo(() => {
    const count = (rec: Recommendation) => filteredRows.filter((row) => row.recommendation === rec).length
    const upsides = filteredRows.map(rowUpside).filter((value): value is number => value != null)
    return {
      buys: count("BUY"),
      holds: count("HOLD"),
      sells: count("SELL"),
      notRated: filteredRows.filter((row) => !row.recommendation).length,
      averageUpside: upsides.length ? upsides.reduce((sum, value) => sum + value, 0) / upsides.length : null,
    }
  }, [filteredRows])

  const latestYear = rows.reduce<number | null>((latest, row) => {
    if (row.latest_statement_year == null) return latest
    return latest == null ? row.latest_statement_year : Math.max(latest, row.latest_statement_year)
  }, null)
  const coverageLabel = liquidityFilter ? `${rows.length}/${totalRows} titres` : `${rows.length} titres`
  const thresholdLabel = `${fmtCompactMad(FUNDAMENTAL_LIQUIDITY_ADV20_THRESHOLD)} MAD`
  const liquidityScopeLabel = liquidityFilter ? "Eligibles" : "Univers"
  const liquidityScopeValue = liquidityFilter ? `${rows.length}/${totalRows}` : `${totalRows}`

  return (
    <aside className="signal-fund-universe">
      <div className="signal-fund-universe-header">
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs font-bold">Couverture - {coverageLabel}</span>
          <span className="text-[10px] text-muted-foreground">FY {latestYear ?? "-"}</span>
        </div>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
          <Input className="h-7 rounded-md pl-7 text-xs" placeholder="Rechercher un titre..." value={query} onChange={(event) => setQuery(event.target.value)} />
        </div>
        <div className={cn("fund-liquidity-filter", liquidityFilter && "active")}>
          <div className="fund-liquidity-head">
            <div className="fund-liquidity-icon">
              <SlidersHorizontal className="h-3.5 w-3.5" />
            </div>
            <div className="fund-liquidity-copy">
              <span className="fund-liquidity-kicker">Filtre institutionnel</span>
              <div className="fund-liquidity-title-row">
                <span className="fund-liquidity-title">Liquidité ADV20</span>
                <span className="fund-liquidity-status">{liquidityFilter ? "Actif" : "Inactif"}</span>
              </div>
            </div>
            <Switch
              checked={liquidityFilter}
              onCheckedChange={onLiquidityFilterChange}
              aria-label={liquidityFilter ? "Désactiver le filtre de liquidité" : "Activer le filtre de liquidité"}
            />
          </div>
          <div className="fund-liquidity-metrics">
            <div className="fund-liquidity-metric">
              <span className="fund-liquidity-metric-label">Seuil</span>
              <span className="fund-liquidity-metric-value">{`>= ${thresholdLabel}`}</span>
            </div>
            <div className="fund-liquidity-metric">
              <span className="fund-liquidity-metric-label">{liquidityScopeLabel}</span>
              <span className="fund-liquidity-metric-value">{liquidityScopeValue}</span>
            </div>
          </div>
        </div>
        <div className="flex gap-1.5">
          <div className="seg min-w-0 flex-1">
            {[
              ["all", "Tous"],
              ["BUY", "Buy"],
              ["HOLD", "Hold"],
              ["SELL", "Sell"],
            ].map(([key, label]) => (
              <button key={key} type="button" className={filter === key ? "active" : ""} onClick={() => setFilter(key as RecommendationFilter)}>
                {label}
              </button>
            ))}
          </div>
          <select className="h-[32px] rounded-md border border-line bg-card px-2 text-[11px] outline-none" value={sortKey} onChange={(event) => setSortKey(event.target.value as SortKey)}>
            <option value="upside">Upside</option>
            <option value="value">Value</option>
            <option value="quality">Quality</option>
            <option value="conviction">Conviction</option>
            <option value="market_cap">Mkt Cap</option>
            <option value="magic">Magic</option>
            <option value="peg">PEG</option>
            <option value="altman">Altman</option>
            <option value="eva">EVA</option>
            <option value="regression">Regression</option>
          </select>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <table className="claude-table signal-fund-universe-table">
          <thead>
            <tr>
              <th>Titre</th>
              <th className="r">Rec.</th>
              <th className="r">V/Q</th>
              <th className="r">Upside</th>
              <th>Rev</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <LoadingRows />
            ) : filteredRows.length === 0 ? (
              <tr>
                <td colSpan={5} className="py-8 text-center text-sm text-muted-foreground">
                  {liquidityFilter ? `Aucun titre avec ADV20 >= ${thresholdLabel}.` : "No fundamental rows."}
                </td>
              </tr>
            ) : (
              filteredRows.map((row) => {
                const active = row.symbol === selectedSymbol
                return (
                  <tr key={row.symbol} className={cn("cursor-pointer", active && "signal-fund-row-active")} onClick={() => onSelect(row.symbol)}>
                    <td>
                      <div className="fund-symbol-cell">
                        <div className="min-w-0">
                          <div className={cn("font-mono text-[11px] font-bold", active && "text-primary")}>{row.symbol}</div>
                          <div className="truncate text-[9px] text-muted-foreground">{row.sector ?? row.display_name ?? "-"}</div>
                        </div>
                      </div>
                    </td>
                    <td className="r">
                      <RecChip value={row.recommendation} />
                    </td>
                    <td className="r">
                      <ScorePair valueScore={row.value_score} qualityScore={row.quality_score} />
                    </td>
                    <td className={cn("r font-mono text-[11px] font-bold", (rowUpside(row) ?? 0) >= 0 ? "t-pos" : "t-neg")}>{fmtPct(rowUpside(row))}</td>
                    <td className="text-center text-[10px]">{revisionArrow(row.revision_direction)}</td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="fund-univ-footer">
        <span>
          <span className="t-pos font-bold">{summary.buys} Buy</span> - {summary.holds} Hold - <span className="t-neg font-bold">{summary.sells} Sell</span> - {summary.notRated} N/R
        </span>
        <span>
          Upside moy. <span className={cn("font-mono font-bold", (summary.averageUpside ?? 0) >= 0 ? "t-pos" : "t-neg")}>{fmtPct(summary.averageUpside)}</span>
        </span>
      </div>
    </aside>
  )
}

function ResearchTicket({
  row,
  detail,
  isRefreshing,
  selectedHorizon,
  onHorizonChange,
}: {
  row: FundamentalUniverseRow | null
  detail: FundamentalStockDetail | null
  isRefreshing: boolean
  selectedHorizon: FundamentalHorizon
  onHorizonChange: (horizon: FundamentalHorizon) => void
}) {
  const symbol = detail?.symbol ?? row?.symbol ?? "-"
  const companyName = detail?.display_name ?? detail?.company_name ?? row?.display_name ?? row?.company_name ?? "-"
  const sector = detail?.sector ?? row?.sector ?? "No sector"
  const currency = detail?.ensemble?.currency ?? row?.ensemble?.currency ?? "MAD"
  const currentPrice = detail?.ensemble?.current_price ?? asNumber(detail?.metrics?.Current_Price) ?? row?.current_price ?? null
  const { horizon: activeHorizon, prediction: activePrediction } = effectiveHorizonPrediction(detail, row, selectedHorizon)
  const ratable = (detail?.recommendation ?? row?.recommendation) !== "NR"
  const officialTargetPrice = detail?.target_price ?? row?.target_price ?? (ratable ? (detail?.ensemble?.fair_value_base ?? row?.ensemble?.fair_value_base ?? null) : null)
  const officialUpside = detail?.ensemble?.upside_pct ?? rowUpside(row)
  const targetPrice = activeHorizon === "year" ? officialTargetPrice : activePrediction?.forward_target ?? officialTargetPrice
  const upside = activeHorizon === "year" ? officialUpside : activePrediction?.upside ?? officialUpside
  const marketCap = asNumber(detail?.metrics?.MarketCap_Calc) ?? row?.market_cap ?? null
  const recommendation = detail?.recommendation ?? row?.recommendation ?? null
  const conviction = detail?.conviction ?? row?.conviction ?? 0
  const headlineScenario = detail?.headline_scenario ?? row?.headline_scenario ?? "base"
  const asOf = detail?.as_of_date ?? row?.as_of_date ?? detail?.imported_at ?? row?.imported_at
  const valuationDate = detail?.valuation_date ?? row?.valuation_date ?? null
  const targetDate = activeHorizon === "year" ? detail?.target_date ?? row?.target_date ?? activePrediction?.target_date ?? null : activePrediction?.target_date ?? detail?.target_date ?? row?.target_date ?? null
  const revision = detail?.revision_direction ?? row?.revision_direction ?? "="
  const freeFloat = detail?.free_float_pct ?? row?.free_float_pct ?? null
  const adv20 = asNumber(detail?.metrics?.ADV20) ?? rowAdv20(row)
  const availableHorizonValues = new Set<FundamentalHorizon>(
    FUNDAMENTAL_HORIZONS
      .map((item) => item.value)
      .filter((horizon) => predictionForHorizon(detail, row, horizon)),
  )
  if (!horizonPredictionsFor(detail, row).length && targetPrice != null) availableHorizonValues.add("year")
  const activeHorizonMeta = FUNDAMENTAL_HORIZONS.find((item) => item.value === activeHorizon) ?? FUNDAMENTAL_HORIZONS[2]
  const ticketRef = useRef<HTMLDivElement | null>(null)
  const [ticketLayout, setTicketLayout] = useState<{ scale: number; density: "compact" | "comfortable" | "expanded" }>({
    scale: 1,
    density: "comfortable",
  })

  useEffect(() => {
    const element = ticketRef.current
    if (!element || typeof ResizeObserver === "undefined") return

    let frame = 0
    const updateLayout = (width: number, height: number) => {
      if (width <= 0 || height <= 0) return
      window.cancelAnimationFrame(frame)
      frame = window.requestAnimationFrame(() => {
        const widthScale = clampValue(width / 900, 0.78, 1.12)
        const heightScale = clampValue(height / 155, 0.72, 1.16)
        const scale = Number(clampValue(Math.min(widthScale, heightScale), 0.72, 1.12).toFixed(3))
        const density = height < 118 || width < 720 ? "compact" : height > 205 && width > 880 ? "expanded" : "comfortable"
        setTicketLayout((current) =>
          Math.abs(current.scale - scale) > 0.01 || current.density !== density
            ? { scale, density }
            : current,
        )
      })
    }

    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect
      if (rect) updateLayout(rect.width, rect.height)
    })
    const rect = element.getBoundingClientRect()
    updateLayout(rect.width, rect.height)
    observer.observe(element)

    return () => {
      window.cancelAnimationFrame(frame)
      observer.disconnect()
    }
  }, [])

  return (
    <div
      ref={ticketRef}
      className="research-ticket"
      data-capture="tearsheet"
      data-density={ticketLayout.density}
      style={{ "--rt-scale": ticketLayout.scale } as CSSProperties}
    >
      <div className="rt-left">
        <div className="rt-header-row">
          <div className="rt-identity">
            <div className="rt-name-row">
              <span className="rt-sym">{symbol}</span>
              {isRefreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" /> : null}
              <span className="rt-coname">{companyName}</span>
              <span className="rt-meta">
                <strong>{sector}</strong> - {row?.market_region ?? "Maroc"} - {currency}
              </span>
            </div>
            <div className="rt-date-caption">
              <CalendarDays className="rt-date-icon" aria-hidden="true" />
              <span>Donnees au <strong>{formatDate(asOf)}</strong></span>
              <span>Valorise le <strong>{formatDate(valuationDate)}</strong></span>
              <span>Cible <strong>{formatDate(targetDate)}</strong></span>
            </div>
          </div>
          <div className="rt-horizon-control" role="group" aria-label="Horizon cible">
            <span className="rt-horizon-label">Horizon cible</span>
            <div className="rt-horizon-buttons">
              {FUNDAMENTAL_HORIZONS.map((item) => {
                const available = availableHorizonValues.has(item.value)
                return (
                  <button
                    key={item.value}
                    type="button"
                    className={cn("rt-horizon-btn", activeHorizon === item.value && "active")}
                    disabled={!available}
                    title={available ? item.label : "Historique sub-annuel insuffisant"}
                    onClick={() => onHorizonChange(item.value)}
                  >
                    {item.label}
                  </button>
                )
              })}
            </div>
          </div>
        </div>
        <div className="rt-prices">
          <div className="rt-price-block">
            <span className="lbl">Cours actuel</span>
            <span className="val">{fmtMoney(currentPrice, 2)}</span>
            <span className="sub">au {formatDate(asOf)}</span>
          </div>
          <div className="rt-price-block">
            <span className="lbl">Objectif {activeHorizon === "year" ? "12M" : financialPeriodLabel(activeHorizonMeta.periodType)}</span>
            <span className="val text-[oklch(0.30_0.14_260)]">{fmtMoney(targetPrice, 2)}</span>
            <span className="sub">{revisionArrow(revision)} revision {revision === "up" ? "haussiere" : revision === "down" ? "baissiere" : "inchangee"}</span>
          </div>
          <div className="rt-price-block">
            <span className="lbl">Upside / Downside</span>
            <span className={cn("val", (upside ?? 0) >= 0 ? "t-pos" : "t-neg")}>{fmtPct(upside)}</span>
            <span className="sub">vs cours actuel</span>
          </div>
          <div className="rt-price-block">
            <span className="lbl">Capitalisation</span>
            <span className="val">{fmtCap(marketCap)}</span>
            <span className="sub">Free float {freeFloat == null ? "-" : fmtPct(freeFloat, 0, false)} - ADV20 {fmtCompactMad(adv20)} MAD</span>
          </div>
        </div>
      </div>
      <div className="rt-right">
        <div className={cn("rt-rec-card", recommendationClass(recommendation))}>
          <div className="rt-rec-lbl">Recommandation {headlineScenario}</div>
          <div className={cn("rt-rec-val", recommendationClass(recommendation))}>{recommendationLabel(recommendation)}</div>
          <div className="rt-conviction">
            <span>Conviction</span>
            {[1, 2, 3, 4, 5].map((item) => (
              <span key={item} className={cn("conv-dot", item <= conviction && "on")} />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function FundCard({ title, aside, children, className }: { title: string; aside?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={cn("fund-card", className)}>
      <div className="fund-card-hdr">
        <span className="fund-card-title">{title}</span>
        {aside ? <span className="fund-card-aside">{aside}</span> : null}
      </div>
      <div className="fund-card-body">{children}</div>
    </div>
  )
}

function StatTile({ label, value, sub, tone }: { label: string; value: string; sub?: ReactNode; tone?: string }) {
  return (
    <div className="fund-stat">
      <span className="lbl">{label}</span>
      <span className={cn("val", tone)}>{value}</span>
      {sub ? <span className="sub">{sub}</span> : null}
    </div>
  )
}

function scenarioProbability(detail: FundamentalStockDetail, scenario: Scenario): number {
  const fromPayload = asNumber(detail.scenario_probabilities?.[scenario])
  if (fromPayload != null) return fromPayload
  const fromAssumptions = asNumber(detail.assumptions[`scenario_probability_${scenario}`])
  if (fromAssumptions != null) return fromAssumptions
  return 1 / SCENARIOS.length
}

function buildScenarios(detail: FundamentalStockDetail, targetOverride?: number | null) {
  const ensembleFor = (key: Scenario) => detail.ensembles?.[key]
  const current =
    detail.ensemble?.current_price ??
    ensembleFor("base")?.current_price ??
    ensembleFor("bear")?.current_price ??
    ensembleFor("bull")?.current_price ??
    asNumber(detail.metrics.Current_Price)
  const hasOverride = targetOverride !== undefined
  const selectedFairValue = detail.ensemble?.fair_value_base ?? detail.target_price ?? null
  const base = hasOverride
    ? targetOverride
    : ensembleFor("base")?.fair_value_base ?? (detail.ensemble?.scenario === "base" ? selectedFairValue : null) ?? detail.target_price ?? null
  const bear = hasOverride
    ? (base != null ? base * 0.85 : null)
    : ensembleFor("bear")?.fair_value_base ??
      (detail.ensemble?.scenario === "bear" ? selectedFairValue : null) ??
      detail.ensemble?.fair_value_low ??
      detail.ensemble?.monte_carlo_low ??
      (base != null ? base * 0.85 : null)
  const bull = hasOverride
    ? (base != null ? base * 1.15 : null)
    : ensembleFor("bull")?.fair_value_base ??
      (detail.ensemble?.scenario === "bull" ? selectedFairValue : null) ??
      detail.ensemble?.fair_value_high ??
      detail.ensemble?.monte_carlo_high ??
      (base != null ? base * 1.15 : null)
  return [
    {
      key: "bear",
      label: "Bear - downside",
      probability: scenarioProbability(detail, "bear"),
      price: bear,
      tone: "bear",
      drivers: ["Marge sous pression", "Multiples sectoriels en contraction", "Hausse du cout du capital"],
    },
    {
      key: "base",
      label: "Base - central",
      probability: scenarioProbability(detail, "base"),
      price: base,
      tone: "base",
      drivers: ["Execution conforme aux tendances historiques", "Ponderation multi-modeles active", "Qualite des donnees integree"],
    },
    {
      key: "bull",
      label: "Bull - upside",
      probability: scenarioProbability(detail, "bull"),
      price: bull,
      tone: "bull",
      drivers: ["Expansion des marges", "Re-rating de multiples", "Conversion cash meilleure que prevu"],
    },
  ].map((scenario) => ({
    ...scenario,
    upside: scenario.price != null && current != null && current > 0 ? scenario.price / current - 1 : null,
  }))
}

function ThesisTab({
  detail,
  row,
}: {
  detail: FundamentalStockDetail
  row: FundamentalUniverseRow | null
}) {
  const scenarios = buildScenarios(detail)
  const expected = scenarios.some((scenario) => scenario.price != null) ? scenarios.reduce((sum, scenario) => sum + (scenario.price ?? 0) * scenario.probability, 0) : null
  const recommendation = detail.recommendation ?? row?.recommendation ?? null
  const fairValue = detail.target_price ?? (recommendation !== "NR" ? detail.ensemble?.fair_value_base : null)
  const upside = detail.ensemble?.upside_pct ?? rowUpside(row)
  const screens = screensFor(detail, row)
  const altman = screenRecord(screens, "altman_z")
  const evaScreen = screenRecord(screens, "eva")

  const risks = [
    ["Valorisation", "Le prix de marche peut rester decorele de la juste valeur si la liquidite se contracte.", 2, "Baissier"],
    ["Bilan", altman.zone ? `Zone Altman: ${String(altman.zone)}.` : "Risque de bilan non qualifie par manque de donnees.", altman.zone === "distress" ? 3 : 2, "Baissier"],
    ["Capital", evaScreen.applicable === false ? "EVA non applicable au secteur financier." : "ROIC/WACC sensible aux hypotheses de marge et de capital employe.", 2, "Baissier"],
  ] as const

  return (
    <div className="fund-gap">
      <div className="fund-thesis">
        <div className="fund-eyebrow">These d'investissement</div>
        {recommendation ? (
          <p>
            {detail.symbol} ressort a <strong>{recommendation}</strong> avec un objectif 12 mois de <strong>{fmtMoney(fairValue, 2)} {detail.ensemble?.currency ?? "MAD"}</strong>, soit un potentiel de{" "}
            <strong className={(upside ?? 0) >= 0 ? "t-pos" : "t-neg"}>{fmtPct(upside)}</strong>. La recommandation combine la juste valeur issue des modeles, la confiance de l'ensemble et l'etendue des modeles utilisables.
          </p>
        ) : (
          <p>
            {detail.symbol} n'a pas de recommandation valorisation exploitable. Les scores fondamentaux restent disponibles, mais l'objectif 12 mois attend un ensemble de modeles avec prix cible et confiance calcules.
          </p>
        )}
        <p>
          La lecture fondamentale est completee par les scores transversaux, les diagnostics comptables et les ecrans institutionnels. Les risques principaux restent la qualite des donnees publiees, la dispersion entre modeles et la sensibilite aux hypotheses de cout du capital.
        </p>
      </div>

      <div data-capture="scenarios">
        <div className="fund-section-label">Scenarios a 12 mois - fourchette bear/base/bull</div>
        <div className="scn-grid">
          {scenarios.map((scenario) => (
            <div key={scenario.key} className={cn("scn-card", scenario.tone)}>
              <div className="scn-hdr">
                <span className={cn("scn-lbl", scenario.tone)}>{scenario.label} - {(scenario.probability * 100).toFixed(0)}%</span>
                <span className="scn-prob">P={scenario.probability.toFixed(2)}</span>
              </div>
              <span className={cn("scn-price", scenario.key === "bear" ? "t-neg" : scenario.key === "bull" ? "t-pos" : "text-[oklch(0.30_0.14_260)]")}>{fmtMoney(scenario.price, 1)} MAD</span>
              <span className={cn("scn-up", (scenario.upside ?? 0) >= 0 ? "t-pos" : "t-neg")}>{fmtPct(scenario.upside)}</span>
              <ul className="scn-drivers">
                {scenario.drivers.map((driver) => (
                  <li key={driver}>{driver}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
        <div className="mt-2 text-right text-[11px] text-muted-foreground">
          Valeur ponderee par scenario (probabilites maison) = <strong className="text-foreground">{fmtMoney(expected, 1)} MAD</strong>
        </div>
      </div>

      <FundCard title="Catalyseurs a venir" aside="Prochains 6 mois">
        <div className="cat-list">
          {[
            ["T+30j", "Publication financiere", "Mise a jour des derniers agregats annuels et periode intermediaire.", "high"],
            ["T+60j", "Revision hypotheses", "Revue du WACC, croissance terminale et payout apres donnees de marche.", "medium"],
            ["T+90j", "Rebalancement universe", "Reclassement relatif apres recompute des scores sectoriels.", "medium"],
          ].map(([date, title, desc, impact]) => (
            <div key={title} className="cat-item">
              <span className="cat-date">{date}</span>
              <span>
                <span className="cat-title">{title}</span>
                <span className="cat-desc">{desc}</span>
              </span>
              <span className={cn("cat-imp", impact)}>{impact === "high" ? "Eleve" : "Modere"}</span>
            </div>
          ))}
        </div>
      </FundCard>

      <FundCard title="Principaux risques">
        {risks.map(([category, text, severity, direction]) => (
          <div key={category} className="risk-row">
            <span className="risk-cat">{category}</span>
            <span className="risk-text">{text}</span>
            <span className="risk-meter">
              {[1, 2, 3].map((bar) => (
                <span key={bar} className={cn("risk-bar", bar <= severity && "on", severity === 3 ? "h" : severity === 2 ? "m" : "l")} />
              ))}
            </span>
            <span className={String(direction) === "Haussier" ? "t-pos" : "t-neg"}>{direction}</span>
          </div>
        ))}
      </FundCard>
    </div>
  )
}

function modelSortIndex(model: string): number {
  const index = MODEL_ORDER.indexOf(model)
  return index === -1 ? MODEL_ORDER.length : index
}

function sortValuationRows(rows: FundamentalValuationResult[]): FundamentalValuationResult[] {
  return [...rows].sort((a, b) => modelSortIndex(a.model) - modelSortIndex(b.model) || a.model.localeCompare(b.model))
}

function valuationSpread(confidence: string | null | undefined): number {
  return confidence === "high" ? 0.06 : confidence === "medium" ? 0.10 : 0.16
}

function parseExcludedModelIds(value: string | null | undefined): Set<string> {
  return new Set(
    (value ?? "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
  )
}

function valuationSymbolKey(symbol: string | null | undefined): string | null {
  const key = (symbol ?? "").trim().toUpperCase()
  return key || null
}

function readValuationExclusionsBySymbol(): Record<string, string> {
  if (typeof window === "undefined") return {}
  try {
    const parsed = JSON.parse(window.localStorage.getItem(VALUATION_EXCLUSIONS_STORAGE_KEY) ?? "{}")
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {}
    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>)
        .filter((entry): entry is [string, string] => typeof entry[1] === "string")
        .map(([key, value]) => [key.trim().toUpperCase(), value.trim()])
        .filter(([key, value]) => key && value),
    )
  } catch {
    return {}
  }
}

function writeValuationExclusionsBySymbol(value: Record<string, string>) {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(VALUATION_EXCLUSIONS_STORAGE_KEY, JSON.stringify(value))
  } catch {
    // Ignore storage failures; the URL still reflects the active stock.
  }
}

function serializeExcludedModelIds(modelIds: Set<string>, rows: FundamentalValuationResult[]): string | null {
  if (modelIds.size === 0) return null
  const orderedModels = Array.from(new Set(sortValuationRows(rows).map((row) => row.model)))
  const ordered = [
    ...orderedModels.filter((model) => modelIds.has(model)),
    ...Array.from(modelIds).filter((model) => !orderedModels.includes(model)).sort(),
  ]
  return ordered.length ? ordered.join(",") : null
}

function fairValueForValuationRow(row: FundamentalValuationResult, comparableSummary: ComparableModelSummary | null): number | null {
  if (row.model === "relative_multiples") return comparableSummary?.fairValue ?? row.fair_value ?? null
  return row.fair_value ?? null
}

function filteredRecord(record: Record<string, unknown>, allowedKeys: Set<string>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(record).filter(([key]) => allowedKeys.has(key)))
}

function filteredJustifiedOutputs(outputs: Record<string, unknown>, allowedKeys: Set<string>): Record<string, unknown> {
  return {
    ...outputs,
    implied_prices: filteredRecord(asRecord(outputs.implied_prices), allowedKeys),
    implied_prices_raw: filteredRecord(asRecord(outputs.implied_prices_raw), allowedKeys),
    justified_multiples: filteredRecord(
      asRecord(outputs.justified_multiples),
      new Set([
        ...(allowedKeys.has("justified_pb") ? ["implied_pb"] : []),
        ...(allowedKeys.has("justified_pe") ? ["implied_pe"] : []),
      ]),
    ),
    multiple_deltas: filteredRecord(
      asRecord(outputs.multiple_deltas),
      new Set([
        ...(allowedKeys.has("justified_pb") ? ["implied_pb_vs_current"] : []),
        ...(allowedKeys.has("justified_pe") ? ["implied_pe_vs_current"] : []),
      ]),
    ),
  }
}

function confidenceForMultipleCount(row: FundamentalValuationResult, count: number): string {
  if (count <= 0) return "unavailable"
  if (row.model === "relative_multiples") return count >= 3 ? "high" : count >= 2 ? "medium" : "low"
  return row.confidence === "high" && count > 0 ? "high" : "medium"
}

function applyRatioDraftToValuationRow(
  row: FundamentalValuationResult,
  detail: FundamentalStockDetail,
  draft: Record<string, number>,
): FundamentalValuationResult {
  if (row.model !== "justified_multiples" && row.model !== "relative_multiples") return row

  const isJustified = row.model === "justified_multiples"
  const maskKey = isJustified ? JUSTIFIED_MULTIPLE_RATIO_MASK_KEY : RELATIVE_MULTIPLE_RATIO_MASK_KEY
  const fallback = isJustified ? JUSTIFIED_MULTIPLE_RATIO_DEFAULT_MASK : RELATIVE_MULTIPLE_RATIO_DEFAULT_MASK
  const definitions = isJustified ? JUSTIFIED_MULTIPLE_RATIOS : RELATIVE_MULTIPLE_RATIOS
  const mask = detailRatioMask(detail, draft, maskKey, fallback, fallback)
  const allowedKeys = new Set(enabledRatioKeys(definitions, mask))
  const outputs = asRecord(row.outputs)
  const filteredOutputs = isJustified
    ? filteredJustifiedOutputs(outputs, allowedKeys)
    : { ...outputs, implied_prices: filteredRecord(asRecord(outputs.implied_prices), allowedKeys), implied_prices_raw: filteredRecord(asRecord(outputs.implied_prices_raw), allowedKeys) }
  const impliedValues = Object.values(asRecord(filteredOutputs.implied_prices))
    .map(asNumber)
    .filter((value): value is number => value != null && value > 0)
  const fairValue = medianValue(impliedValues)
  const warnings = row.warnings.filter((warning) => !warning.startsWith("all_") && !warning.startsWith("no_usable_"))
  if (allowedKeys.size === 0) warnings.push(isJustified ? "all_justified_multiples_excluded" : "all_relative_multiples_excluded")
  if (fairValue == null) warnings.push(isJustified ? "no_usable_justified_multiple" : "no_usable_peer_multiple")

  return {
    ...row,
    fair_value: fairValue,
    upside_pct: upsideForFairValue(fairValue, currentPriceForValuationRow(row, detail)),
    confidence: confidenceForMultipleCount(row, impliedValues.length),
    inputs: {
      ...row.inputs,
      selected_ratio_keys: Array.from(allowedKeys),
      [maskKey]: mask,
    },
    outputs: filteredOutputs,
    warnings,
  }
}

function applyRatioDraftToValuationRows(
  rows: FundamentalValuationResult[],
  detail: FundamentalStockDetail | null,
  draft: Record<string, number>,
): FundamentalValuationResult[] {
  if (!detail) return rows
  return rows.map((row) => applyRatioDraftToValuationRow(row, detail, draft))
}

function currentPriceForValuationRow(row: FundamentalValuationResult, detail: FundamentalStockDetail): number | null {
  return row.current_price ?? detail.ensemble?.current_price ?? asNumber(detail.metrics.Current_Price)
}

function upsideForFairValue(fairValue: number | null, currentPrice: number | null): number | null {
  return fairValue != null && currentPrice != null && currentPrice > 0 ? fairValue / currentPrice - 1 : null
}

function valuationHasSevereQualityWarning(row: FundamentalValuationResult): boolean {
  const warnings = Array.isArray(row.warnings) ? row.warnings : []
  if (row.model === "fcff_dcf" || row.model === "fcfe_dcf") {
    if (warnings.some((warning) => SEVERE_VALUATION_WARNINGS.has(warning) || SEVERE_FCF_WARNING_PREFIXES.some((prefix) => warning.startsWith(prefix)))) {
      return true
    }
  }
  if ((row.model === "ddm" || row.model === "residual_income") && warnings.some((warning) => SEVERE_VALUATION_WARNINGS.has(warning))) {
    return true
  }
  return false
}

function valuationIsExtremeOutlier(fairValue: number | null, currentPrice: number | null): boolean {
  return fairValue != null && currentPrice != null && currentPrice > 0 && fairValue / currentPrice > EXTREME_VALUATION_FAIR_VALUE_MULTIPLE
}

function valuationExcludedFromWorkingTarget(row: FundamentalValuationResult, fairValue: number | null, currentPrice: number | null): boolean {
  return valuationHasSevereQualityWarning(row) || valuationIsExtremeOutlier(fairValue, currentPrice)
}

function buildValuationSelectionSummary({
  rows,
  excludedModelIds,
  comparableSummary,
  currentPrice,
  weightMode = "ic",
}: {
  rows: FundamentalValuationResult[]
  excludedModelIds: Set<string>
  comparableSummary: ComparableModelSummary | null
  currentPrice: number | null
  weightMode?: WeightMode
}): ValuationSelectionSummary {
  const includedRows = rows.filter((row) => row.family !== "diagnostic" && !excludedModelIds.has(row.model))
  const usable = includedRows
    .map((row) => {
      const fairValue = fairValueForValuationRow(row, comparableSummary)
      if (fairValue == null || fairValue <= 0) return null
      if (valuationExcludedFromWorkingTarget(row, fairValue, currentPrice)) return null
      const spread = valuationSpread(row.confidence)
      return {
        row,
        fairValue,
        low: fairValue * (1 - spread),
        high: fairValue * (1 + spread),
        rawWeight: asNumber(row.weight),
      }
    })
    .filter((item): item is NonNullable<typeof item> => item != null)

  const hasModelWeights = usable.some((item) => item.rawWeight != null && item.rawWeight > 0)
  let weightSource: ValuationSelectionSummary["weightSource"]
  let getEffectiveWeight: (item: { rawWeight: number | null }) => number
  if (weightMode === "equal") {
    weightSource = "equal weights"
    getEffectiveWeight = () => 1
  } else if (hasModelWeights) {
    weightSource = "model weights"
    getEffectiveWeight = (item) => Math.max(0, item.rawWeight ?? 0)
  } else {
    weightSource = "ic fallback"
    getEffectiveWeight = () => 1
  }

  const weighted = usable
    .map((item) => ({ ...item, effectiveWeight: getEffectiveWeight(item) }))
    .filter((item) => item.effectiveWeight > 0)
  const denominator = weighted.reduce((acc, item) => acc + item.effectiveWeight, 0)
  const effectiveWeights = new Map<string, number>()

  if (denominator <= 0) {
    return {
      fairValue: null,
      low: null,
      high: null,
      upside: null,
      includedCount: includedRows.length,
      usableCount: 0,
      weightSource,
      effectiveWeights,
    }
  }

  for (const item of weighted) {
    effectiveWeights.set(item.row.model, item.effectiveWeight / denominator)
  }

  const fairValue = weighted.reduce((acc, item) => acc + item.fairValue * item.effectiveWeight, 0) / denominator
  const low = weighted.reduce((acc, item) => acc + item.low * item.effectiveWeight, 0) / denominator
  const high = weighted.reduce((acc, item) => acc + item.high * item.effectiveWeight, 0) / denominator

  return {
    fairValue,
    low,
    high,
    upside: upsideForFairValue(fairValue, currentPrice),
    includedCount: includedRows.length,
    usableCount: weighted.length,
    weightSource,
    effectiveWeights,
  }
}

function valuationMethods(
  detail: FundamentalStockDetail,
  rows: FundamentalValuationResult[] = detail.valuations,
  comparableSummary: ComparableModelSummary | null = null,
  selectionSummary: ValuationSelectionSummary | null = null,
): ValuationMethodRange[] {
  const current = detail.ensemble?.current_price ?? asNumber(detail.metrics.Current_Price)
  const modelRows: ValuationMethodRange[] = sortValuationRows(rows)
    .filter((row) => {
      const fairValue = fairValueForValuationRow(row, comparableSummary)
      return row.family !== "diagnostic" && fairValue != null && !valuationExcludedFromWorkingTarget(row, fairValue, current)
    })
    .map((row) => {
      const spread = valuationSpread(row.confidence)
      const mid = fairValueForValuationRow(row, comparableSummary) ?? 0
      return {
        key: row.model,
        method: MODEL_LABELS[row.model] ?? row.model,
        low: mid * (1 - spread),
        mid,
        high: mid * (1 + spread),
        weight: row.weight,
        confidence: row.confidence,
        row,
      }
    })
  if (selectionSummary?.fairValue != null) {
    modelRows.push({
      key: "ensemble",
      method: "Selection active",
      low: selectionSummary.low ?? selectionSummary.fairValue * 0.93,
      mid: selectionSummary.fairValue,
      high: selectionSummary.high ?? selectionSummary.fairValue * 1.07,
      weight: 1,
      confidence: selectionSummary.usableCount >= 4 ? "high" : selectionSummary.usableCount >= 2 ? "medium" : "low",
      row: null,
    })
  } else if (detail.ensemble?.fair_value_base != null) {
    modelRows.push({
      key: "ensemble",
      method: "Ensemble pondere",
      low: detail.ensemble.fair_value_low ?? detail.ensemble.fair_value_base * 0.93,
      mid: detail.ensemble.fair_value_base,
      high: detail.ensemble.fair_value_high ?? detail.ensemble.fair_value_base * 1.07,
      weight: 1,
      confidence: confidenceLabel(detail.ensemble.confidence_score) ?? "medium",
      row: null,
    })
  }
  return modelRows.filter((row) => row.low > 0 && row.high > 0 && current != null)
}

function FootballField({
  methods,
  currentPrice,
  targetPrice,
}: {
  methods: ReturnType<typeof valuationMethods>
  currentPrice: number | null
  targetPrice: number | null
}) {
  if (!methods.length || currentPrice == null || targetPrice == null) {
    return <div className="fund-empty-small">No usable valuation range.</div>
  }
  const width = 720
  const padLeft = 132
  const padRight = 82
  const rowHeight = 30
  const height = methods.length * rowHeight + 70
  const allValues = methods.flatMap((method) => [method.low, method.high]).concat([currentPrice, targetPrice])
  const minValue = Math.min(...allValues) * 0.94
  const maxValue = Math.max(...allValues) * 1.06
  const x = (value: number) => padLeft + ((value - minValue) / Math.max(1e-9, maxValue - minValue)) * (width - padLeft - padRight)
  const ticks = Array.from({ length: 5 }, (_, index) => minValue + ((maxValue - minValue) / 4) * index)

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="ff-svg" preserveAspectRatio="xMidYMid meet">
      {ticks.map((tick) => (
        <line key={tick} x1={x(tick)} x2={x(tick)} y1={18} y2={height - 32} stroke="var(--line)" strokeWidth="0.5" />
      ))}
      {methods.map((method, index) => {
        const centerY = 28 + index * rowHeight + rowHeight / 2
        const isEnsemble = method.key === "ensemble"
        const color = isEnsemble ? "var(--primary)" : "oklch(0.62 0.08 250)"
        return (
          <g key={method.key}>
            <text x={padLeft - 10} y={centerY + 4} fill="var(--fg2)" fontSize="11" textAnchor="end" fontWeight={isEnsemble ? 700 : 500}>
              {method.method}
            </text>
            <line x1={x(method.low)} x2={x(method.high)} y1={centerY} y2={centerY} stroke={color} strokeWidth={isEnsemble ? 12 : 9} strokeLinecap="round" opacity={isEnsemble ? 0.72 : 0.45} />
            <circle cx={x(method.mid)} cy={centerY} r={isEnsemble ? 5 : 4} fill={color} stroke="var(--card)" strokeWidth="1.5" />
            <text x={x(method.low) - 5} y={centerY + 4} textAnchor="end" fontSize="10" fill="var(--fg3)" fontFamily="var(--font-mono)">
              {fmtMoney(method.low, 0)}
            </text>
            <text x={x(method.high) + 5} y={centerY + 4} textAnchor="start" fontSize="10" fill="var(--fg3)" fontFamily="var(--font-mono)">
              {fmtMoney(method.high, 0)}
            </text>
          </g>
        )
      })}
      <line x1={x(currentPrice)} x2={x(currentPrice)} y1={18} y2={height - 32} stroke="var(--neg)" strokeWidth="1.5" strokeDasharray="4 3" opacity="0.85" />
      <text x={x(currentPrice)} y={14} textAnchor="middle" fontSize="10" fill="var(--neg)" fontWeight="700">
        CP - {fmtMoney(currentPrice, 1)}
      </text>
      <line x1={x(targetPrice)} x2={x(targetPrice)} y1={18} y2={height - 32} stroke="var(--pos)" strokeWidth="2" />
      <text x={x(targetPrice)} y={height - 10} textAnchor="middle" fontSize="10" fill="var(--pos)" fontWeight="700">
        Cible - {fmtMoney(targetPrice, 1)}
      </text>
      {ticks.map((tick) => (
        <text key={`tick-${tick}`} x={x(tick)} y={height - 22} textAnchor="middle" fontSize="9" fill="var(--fg3)" fontFamily="var(--font-mono)">
          {fmtMoney(tick, 0)}
        </text>
      ))}
    </svg>
  )
}

function valuationFormulaMeta(model: string): ValuationFormulaMeta {
  return MODEL_FORMULA_META[model] ?? DEFAULT_VALUATION_FORMULA
}

function valueLabel(key: string): string {
  return VALUE_LABELS[key] ?? key.replaceAll("_", " ")
}

function isPercentLikeKey(key: string): boolean {
  const token = key.toLowerCase()
  return (
    token.includes("wacc") ||
    token.includes("growth") ||
    token.includes("rate") ||
    token.includes("yield") ||
    token.includes("margin") ||
    token.includes("roe") ||
    token.includes("payout") ||
    token.includes("retention") ||
    token.includes("weight") ||
    token.includes("upside") ||
    token.includes("confidence_score")
  )
}

function isMoneyLikeKey(key: string): boolean {
  const token = key.toLowerCase()
  return (
    token.includes("price") ||
    token.includes("value") ||
    token.includes("cash") ||
    token.includes("fcf") ||
    token.includes("fcfe") ||
    token.includes("debt") ||
    token.includes("cap") ||
    token.includes("dividend") ||
    token.includes("income") ||
    token.includes("book")
  )
}

function formatStatementValue(value: number | null | undefined, format: string): string {
  if (value == null || Number.isNaN(value)) return "-"
  if (format === "money") return fmtCap(value)
  if (format === "percent") {
    const pct = Math.abs(value) > 2 ? value : value * 100
    return `${fmtNumber(pct, 1)}%`
  }
  if (format === "ratio") return fmtRatio(value, 1)
  if (format === "per_share") return fmtMoney(value, 2)
  return fmtNumber(value, Math.abs(value) < 10 ? 2 : 1)
}

function formatModelScalar(key: string, value: number): string {
  if (isPercentLikeKey(key)) return fmtPct(value, 1, false)
  if (key.toLowerCase().includes("year") || key.toLowerCase().includes("count")) return fmtNumber(value, 0)
  if (isMoneyLikeKey(key)) return fmtCap(value)
  return fmtNumber(value, Math.abs(value) < 10 ? 3 : 1)
}

function formatNestedModelValue(key: string, value: unknown): string {
  if (value == null) return "-"
  if (typeof value === "number") return formatModelScalar(key, value)
  if (typeof value === "string" || typeof value === "boolean") return String(value)
  const record = asRecord(value)
  if (Object.keys(record).length > 0) {
    const medianValue = asNumber(record.median)
    const countValue = asNumber(record.count)
    const scope = typeof record.scope === "string" ? record.scope : null
    if (medianValue != null || countValue != null || scope) {
      return [
        medianValue != null ? `median ${formatModelScalar(key, medianValue)}` : null,
        countValue != null ? `n=${fmtNumber(countValue, 0)}` : null,
        scope,
      ].filter(Boolean).join(", ")
    }
  }
  return JSON.stringify(value)
}

function ValuePreview({ itemKey, value }: { itemKey: string; value: unknown }) {
  if (value == null) return <span className="text-muted-foreground">-</span>
  if (typeof value === "number") return <span className="font-mono">{formatModelScalar(itemKey, value)}</span>
  if (typeof value === "string" || typeof value === "boolean") return <span>{String(value)}</span>
  if (Array.isArray(value)) {
    const preview = value.slice(0, 5).map((item, index) => {
      if (typeof item === "number") return `Y${index + 1} ${formatModelScalar(itemKey, item)}`
      if (item && typeof item === "object") return JSON.stringify(item)
      return String(item)
    })
    return (
      <code className="fund-code">
        {preview.join(" | ")}
        {value.length > preview.length ? " | ..." : ""}
      </code>
    )
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).slice(0, 5)
    return (
      <span className="valuation-object-preview">
        {entries.map(([key, item]) => (
          <span key={key} className="valuation-object-chip">
            <strong>{valueLabel(key)}</strong>
            <em>{formatNestedModelValue(key, item)}</em>
          </span>
        ))}
        {Object.keys(value as Record<string, unknown>).length > entries.length ? " | ..." : ""}
      </span>
    )
  }
  return <span>{String(value)}</span>
}

function projectionFromDetail(detail: FundamentalStockDetail): ProjectionView | null {
  const valuationProjection = detail.valuations
    .map((row) => asRecord(asRecord(row.outputs).projection))
    .find((projection) => Object.keys(projection).length > 0)
  const projection = valuationProjection && Object.keys(valuationProjection).length > 0 ? valuationProjection : {}
  const projectedStatements = Array.isArray(projection.statements)
    ? projection.statements.map((item) => asRecord(item)).filter((item) => Object.keys(item).length > 0)
    : Array.isArray(detail.integrity?.projected_statements)
      ? detail.integrity.projected_statements.map((item) => asRecord(item)).filter((item) => Object.keys(item).length > 0)
      : []
  if (!projectedStatements.length) return null
  const drivers = Object.fromEntries(
    Object.entries(asRecord(projection.drivers)).map(([key, value]) => [key, asRecord(value)]),
  )
  const warnings = Array.isArray(projection.warnings)
    ? projection.warnings.filter((item): item is string => typeof item === "string")
    : []
  const numberList = (value: unknown): number[] => Array.isArray(value) ? value.map(asNumber).filter((item): item is number => item != null) : []
  return {
    statements: projectedStatements,
    drivers,
    fcff: numberList(projection.fcff),
    fcfe: numberList(projection.fcfe),
    dividends: numberList(projection.dividends),
    bookValues: numberList(projection.book_values),
    growthDecomposition: asRecord(projection.growth_decomposition),
    warnings,
  }
}

function projectedYears(projection: ProjectionView): number[] {
  return projection.statements.map((statement) => asNumber(statement.fiscal_year)).filter((year): year is number => year != null)
}

function projectedValue(statement: Record<string, unknown>, key: string): number | null {
  return asNumber(statement[key])
}

function driverProjectedValue(driver: Record<string, unknown>, year: number): number | null {
  const projected = asRecord(driver.projected_by_year)
  return asNumber(projected[String(year)]) ?? asNumber(projected[year])
}

function projectionDriverRows(projection: ProjectionView): Array<{ key: string; label: string; format: "pct" | "number"; driver: Record<string, unknown> }> {
  const labels: Array<[string, string, "pct" | "number"]> = [
    ["revenue_growth", "Croissance CA", "pct"],
    ["ebit_margin", "Marge EBIT", "pct"],
    ["tax_rate", "Taux IS", "pct"],
    ["capex_pct", "Capex / CA", "pct"],
    ["working_capital_pct", "BFR / CA", "pct"],
    ["depreciation_amortization_pct", "D&A / CA", "pct"],
    ["payout_ratio", "Payout", "pct"],
  ]
  return labels
    .map(([key, label, format]) => ({ key, label, format, driver: projection.drivers[key] }))
    .filter((row): row is { key: string; label: string; format: "pct" | "number"; driver: Record<string, unknown> } => !!row.driver && Object.keys(row.driver).length > 0)
}

function projectionStatementRows(): Array<{ key: string; label: string; format: "money" | "pct" }> {
  return [
    { key: "revenue", label: "Chiffre d'affaires", format: "money" },
    { key: "ebitda", label: "EBITDA", format: "money" },
    { key: "ebit", label: "EBIT", format: "money" },
    { key: "nopat", label: "NOPAT", format: "money" },
    { key: "capex", label: "Capex", format: "money" },
    { key: "delta_working_capital", label: "Variation BFR", format: "money" },
    { key: "fcff", label: "FCFF", format: "money" },
    { key: "fcfe", label: "FCFE", format: "money" },
    { key: "net_income", label: "Resultat net", format: "money" },
    { key: "dividends", label: "Dividendes", format: "money" },
    { key: "cash", label: "Tresorerie", format: "money" },
    { key: "total_equity", label: "Fonds propres", format: "money" },
  ]
}

function formatProjectionValue(value: number | null, format: "money" | "pct" | "number"): string {
  if (format === "pct") return fmtPct(value, 1, false)
  if (format === "money") return fmtMoney(value, 0)
  return fmtNumber(value, 2)
}

function projectionSeriesFromDriver(driver: Record<string, unknown>): SeriesPoint[] {
  const projected = asRecord(driver.projected_by_year)
  return Object.entries(projected)
    .flatMap(([year, value]): SeriesPoint[] => {
      const yearValue = Number(year)
      const numberValue = asNumber(value)
      return Number.isFinite(yearValue) && numberValue != null ? [{ year: yearValue, value: numberValue, kind: "projected" }] : []
    })
    .sort((a, b) => a.year - b.year)
}

function historicalSeriesFromDriver(driver: Record<string, unknown>): SeriesPoint[] {
  const historical = Array.isArray(driver.historical_series) ? driver.historical_series : []
  return historical
    .flatMap((item): SeriesPoint[] => {
      const record = asRecord(item)
      const year = asNumber(record.year)
      const value = asNumber(record.value)
      return year != null && value != null ? [{ year, value, kind: "historical" }] : []
    })
    .sort((a, b) => a.year - b.year)
}

function seriesFromRaw(value: unknown, kind: SeriesPoint["kind"] = "historical"): SeriesPoint[] {
  const rows = Array.isArray(value) ? value : []
  return rows
    .flatMap((item): SeriesPoint[] => {
      const record = asRecord(item)
      const year = asNumber(record.year)
      const numberValue = asNumber(record.value)
      return year != null && numberValue != null && kind ? [{ year, value: numberValue, kind }] : []
    })
    .sort((a, b) => a.year - b.year)
}

function seriesPath(points: SeriesPoint[], width: number, height: number, pad = 8): string {
  if (!points.length) return ""
  const years = points.map((point) => point.year)
  const values = points.map((point) => point.value)
  const minYear = Math.min(...years)
  const maxYear = Math.max(...years)
  const minValue = Math.min(...values)
  const maxValue = Math.max(...values)
  const spanYear = Math.max(1, maxYear - minYear)
  const spanValue = Math.max(0.000001, maxValue - minValue)
  return points
    .map((point, index) => {
      const x = pad + ((point.year - minYear) / spanYear) * (width - pad * 2)
      const y = height - pad - ((point.value - minValue) / spanValue) * (height - pad * 2)
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`
    })
    .join(" ")
}

function seriesPointPosition(point: SeriesPoint, points: SeriesPoint[], width: number, height: number, pad = 8): { x: number; y: number } {
  const years = points.map((item) => item.year)
  const values = points.map((item) => item.value)
  const minYear = Math.min(...years)
  const maxYear = Math.max(...years)
  const minValue = Math.min(...values)
  const maxValue = Math.max(...values)
  const x = pad + ((point.year - minYear) / Math.max(1, maxYear - minYear)) * (width - pad * 2)
  const y = height - pad - ((point.value - minValue) / Math.max(0.000001, maxValue - minValue)) * (height - pad * 2)
  return { x, y }
}

function MiniSeriesChart({
  historical,
  projected,
  format,
}: {
  historical: SeriesPoint[]
  projected: SeriesPoint[]
  format: "pct" | "money" | "number"
}) {
  const width = 320
  const height = 110
  const allPoints = [...historical, ...projected]
  if (!allPoints.length) return <div className="fund-empty-small">Serie indisponible.</div>
  const historicalPath = seriesPath(historical, width, height)
  const projectedPath = seriesPath(projected, width, height)
  const latest = allPoints[allPoints.length - 1]
  return (
    <div className="mini-series">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Historique et projection">
        <line x1="8" x2={width - 8} y1={height - 8} y2={height - 8} stroke="var(--line)" />
        {historicalPath ? <path d={historicalPath} fill="none" stroke="var(--fg3)" strokeWidth="2" /> : null}
        {projectedPath ? <path d={projectedPath} fill="none" stroke="var(--primary)" strokeWidth="2.5" strokeDasharray="4 3" /> : null}
        {allPoints.map((point) => {
          const position = seriesPointPosition(point, allPoints, width, height)
          return <circle key={`${point.kind}-${point.year}-${point.value}`} cx={position.x} cy={position.y} r="2.8" fill={point.kind === "projected" ? "var(--primary)" : "var(--fg3)"} />
        })}
      </svg>
      <div className="mini-series-foot">
        <span>Dernier point</span>
        <strong>{formatProjectionValue(latest.value, format)}</strong>
      </div>
    </div>
  )
}

function DriverEvidenceChart({
  driver,
  label,
  format,
}: {
  driver: Record<string, unknown> | undefined
  label: string
  format: "pct" | "money" | "number"
}) {
  if (!driver || Object.keys(driver).length === 0) return null
  const historical = historicalSeriesFromDriver(driver)
  const projected = projectionSeriesFromDriver(driver)
  const warning = typeof driver.warning === "string" ? driver.warning : null
  const method = typeof driver.method === "string" ? driver.method : ""
  const anchor = asNumber(driver.anchor_value)
  const divergence = asNumber(driver.divergence)
  return (
    <div className="driver-evidence-card">
      <div className="driver-evidence-head">
        <div>
          <span className="valuation-mini-title">{label}</span>
          <p>{method || "Methode non renseignee."}</p>
        </div>
        <span className={cn("signal-conf-badge", warning ? "medium" : "high")}>{warning ? "Alerte" : "OK"}</span>
      </div>
      <MiniSeriesChart historical={historical} projected={projected} format={format} />
      <div className="driver-evidence-stats">
        <span>Ancrage <strong>{formatProjectionValue(anchor, format)}</strong></span>
        <span>Ecart <strong>{formatProjectionValue(divergence, format)}</strong></span>
      </div>
      {warning ? <span className="fund-warning-chip">{warning}</span> : null}
    </div>
  )
}

function GrowthDecompositionChart({ projection }: { projection: ProjectionView }) {
  const growth = projection.growthDecomposition
  const rows = [
    ["revenue_growth", "CA"],
    ["ebit_growth", "EBIT"],
    ["net_income_growth", "RN"],
    ["fcf_growth", "FCF"],
  ] as const
  const projected = seriesFromRaw(growth.projected_revenue_growth, "projected")
  const hasAny = rows.some(([key]) => seriesFromRaw(growth[key]).length > 0) || projected.length > 0
  if (!hasAny) return null
  return (
    <div className="growth-decomp-grid">
      {rows.map(([key, label]) => {
        const historical = seriesFromRaw(growth[key])
        return (
          <div key={key} className="growth-decomp-item">
            <div className="driver-evidence-head compact">
              <span className="valuation-mini-title">{label}</span>
              <span>{historical.length ? `${historical.length} pts` : "n/a"}</span>
            </div>
            <MiniSeriesChart historical={historical} projected={key === "revenue_growth" ? projected : []} format="pct" />
          </div>
        )
      })}
    </div>
  )
}

function FcfBridge({ projection, mode }: { projection: ProjectionView; mode: "fcff" | "fcfe" }) {
  const [selectedYear, setSelectedYear] = useState<number | null>(null)
  if (!projection.statements.length) return null
  const years = projectedYears(projection)
  const activeYear = selectedYear && years.includes(selectedYear) ? selectedYear : years[0]
  const statement = projection.statements.find((item) => projectedValue(item, "fiscal_year") === activeYear) ?? projection.statements[0]
  const targetKey = mode === "fcfe" ? "fcfe" : "fcff"
  const bridgeRows = [
    ["revenue", "Chiffre d'affaires", projectedValue(statement, "revenue")],
    ["ebit", "EBIT", projectedValue(statement, "ebit")],
    ["nopat", "NOPAT", projectedValue(statement, "nopat")],
    ["reinvestment", "Reinvestissement", projectedValue(statement, "reinvestment")],
    [targetKey, mode.toUpperCase(), projectedValue(statement, targetKey)],
  ] as const
  const maxAbs = Math.max(1, ...bridgeRows.map(([, , value]) => Math.abs(value ?? 0)))
  return (
    <div className="fcf-bridge">
      <div className="driver-evidence-head">
        <div>
          <span className="valuation-mini-title">Pont cash-flow</span>
          <p>{mode === "fcff" ? "CA -> EBIT -> NOPAT - reinvestissement = FCFF." : "CA -> EBIT -> NOPAT - reinvestissement - interets apres impot = FCFE."}</p>
        </div>
        <div className="seg compact">
          {years.map((year) => (
            <button key={year} type="button" className={activeYear === year ? "active" : ""} onClick={() => setSelectedYear(year)}>
              {year}
            </button>
          ))}
        </div>
      </div>
      <div className="fcf-bridge-bars">
        {bridgeRows.map(([key, label, value]) => {
          const width = `${Math.max(4, (Math.abs(value ?? 0) / maxAbs) * 100)}%`
          return (
            <div key={key} className="fcf-bridge-row">
              <span>{label}</span>
              <div className="fcf-bridge-track">
                <div className={cn("fcf-bridge-fill", (value ?? 0) < 0 && "neg")} style={{ width }} />
              </div>
              <strong>{fmtMoney(value, 0)}</strong>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function costOfCapitalBuildUp(detail: FundamentalStockDetail, row?: FundamentalValuationResult): Record<string, unknown> {
  const liveBuild = asRecord(detail.assumptions.cost_of_capital_build_up)
  const fromRow = asRecord(row ? asRecord(row.inputs).cost_of_capital : undefined)
  if (Object.keys(fromRow).length === 0) return liveBuild
  if (
    String(fromRow.beta_source ?? "") === "default_beta" &&
    String(liveBuild.beta_source ?? "") !== "default_beta" &&
    Object.keys(liveBuild).length > 0
  ) {
    return liveBuild
  }
  return fromRow
}

function CostOfCapitalBuildUp({ detail, row }: { detail: FundamentalStockDetail; row?: FundamentalValuationResult }) {
  const build = costOfCapitalBuildUp(detail, row)
  if (!Object.keys(build).length) return null
  const riskFree = asNumber(detail.assumptions.risk_free_rate)
  const baseErp = asNumber(build.base_equity_risk_premium) ?? asNumber(detail.assumptions.equity_risk_premium) ?? 0
  const countryRiskPremium = asNumber(build.country_risk_premium) ?? asNumber(detail.assumptions.country_risk_premium) ?? 0
  const scenarioErpAddon = asNumber(build.scenario_erp_addon) ?? asNumber(detail.assumptions.scenario_erp_addon) ?? 0
  const erp = asNumber(build.effective_equity_risk_premium) ?? baseErp + countryRiskPremium + scenarioErpAddon
  const beta = asNumber(build.beta)
  const keUnfloored = asNumber(build.cost_of_equity_unfloored)
  const keFloor = asNumber(build.cost_of_equity_floor) ?? asNumber(detail.assumptions.cost_of_equity_floor)
  const keFloorBound = build.cost_of_equity_floor_bound === true
  const ke = asNumber(build.cost_of_equity)
  const kd = asNumber(build.cost_of_debt)
  const scenarioDebtAddon = asNumber(build.scenario_cost_of_debt_addon) ?? asNumber(detail.assumptions.scenario_cost_of_debt_addon) ?? 0
  const debtSource = String(build.cost_of_debt_source ?? "-")
  const debtBucket = String(build.synthetic_bucket ?? "-")
  const tax = asNumber(build.tax_rate)
  const we = asNumber(build.equity_weight)
  const wd = asNumber(build.debt_weight)
  const wacc = asNumber(build.wacc)
  const betaSource = String(build.beta_source ?? "-")
  const betaMethod = String(build.beta_method ?? "-")
  const usesDefaultBeta = betaSource === "default_beta"
  const betaMeta = [
    `source=${betaSource}`,
    `method=${betaMethod}`,
    `proxy=${String(build.market_proxy ?? "MASI")}`,
    `freq=${String(build.beta_frequency ?? "weekly")}`,
    `window=${fmtNumber(asNumber(build.beta_window_years), 1)}y`,
    `n=${fmtNumber(asNumber(build.beta_n_obs), 0)}`,
    `r2=${fmtNumber(asNumber(build.beta_r2), 3)}`,
    `zero=${fmtPct(asNumber(build.beta_zero_week_frac), 1, false)}`,
  ].join(" | ")
  return (
    <div className="cost-build-panel" data-capture="wacc-buildup">
      <div className="valuation-formula-eyebrow">Construction cout du capital</div>
      {usesDefaultBeta ? (
        <div className="mb-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-[12px] font-medium text-amber-900">
          Beta non estime - serie proxy MASI absente ou beta history vide; WACC utilise beta=1.0 par defaut.
        </div>
      ) : betaMethod !== "ols" && betaMethod !== "-" ? (
        <div className="mb-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[12px] text-amber-900">
          Fallback beta actif: methode {betaMethod}, generalement declenchee par liquidite ou observations insuffisantes.
        </div>
      ) : null}
      <div className="cost-build-formulas">
        <code title={betaMeta}>
          Ke = max(rf {fmtPct(riskFree, 2, false)} + beta {fmtRatio(beta, 2)} x (ERP {fmtPct(baseErp, 2, false)} + pays {fmtPct(countryRiskPremium, 2, false)} + scenario {fmtPct(scenarioErpAddon, 2, false)}) = {fmtPct(keUnfloored, 2, false)}, floor {fmtPct(keFloor, 2, false)}) = {fmtPct(ke, 2, false)}
        </code>
        <code>
          WACC = We {fmtPct(we, 1, false)} x Ke {fmtPct(ke, 2, false)} + Wd {fmtPct(wd, 1, false)} x Kd {fmtPct(kd, 2, false)} x (1 - IS {fmtPct(tax, 1, false)}) = {fmtPct(wacc, 2, false)}
        </code>
      </div>
      <div className="cost-build-grid">
        <StatTile label="Beta" value={fmtRatio(beta, 2)} sub={betaSource} />
        <StatTile label="Ke brut" value={fmtPct(keUnfloored, 2, false)} sub="rf + beta x ERP" />
        <StatTile label="Plancher Ke" value={fmtPct(keFloor, 2, false)} sub={keFloorBound ? "actif" : "non lie"} tone={keFloorBound ? "t-neg" : undefined} />
        <StatTile label="ERP effective" value={fmtPct(erp, 2, false)} sub={`add-on ${fmtPct(scenarioErpAddon, 2, false)}`} />
        <StatTile label="Dette effective" value={fmtPct(kd, 2, false)} sub={`${debtSource} ${debtBucket !== "-" ? debtBucket : ""}`.trim() || `add-on ${fmtPct(scenarioDebtAddon, 2, false)}`} />
        <StatTile label="Coverage" value={fmtRatio(asNumber(build.interest_coverage), 2)} sub={`spread ${fmtPct(asNumber(build.synthetic_spread), 2, false)}`} />
        <StatTile label="Proxy marche" value={String(build.market_proxy ?? "MASI")} sub={String(build.beta_as_of ?? "non date")} />
        <StatTile label="Obs." value={fmtNumber(asNumber(build.beta_n_obs), 0)} sub={`R2 ${fmtNumber(asNumber(build.beta_r2), 3)}`} />
        <StatTile label="Structure" value={`${fmtPct(we, 0, false)} / ${fmtPct(wd, 0, false)}`} sub={String(build.weight_source ?? "default")} />
      </div>
    </div>
  )
}

function CoverageRatingPanel({ detail, row }: { detail: FundamentalStockDetail; row: FundamentalUniverseRow | null }) {
  const ensemble = ensembleForFlags(detail, row)
  const coveragePct = overallCoveragePct(detail, row)
  const dispersionCv = asNumber(ensemble?.model_dispersion_cv)
  const dispersionFactor = asNumber(ensemble?.dispersion_factor)
  const fairMean = asNumber(ensemble?.fair_value_mean)
  const flags = ratingFlagsFor(detail, row)
  const warnings = ensembleWarningsFor(detail, row)
  const scoreScopes = asRecord(asRecord(detail.diagnostics).score_scopes)
  const scopes = SCORE_SCOPE_LABELS.map(([key, label]) => {
    const rawScope = scoreScopes[key]
    const scope = asRecord(rawScope)
    const scopeLabel = typeof rawScope === "string" ? rawScope : typeof scope.scope === "string" ? scope.scope : typeof scope.status === "string" ? scope.status : "-"
    const count = asNumber(scope.count) ?? asNumber(scope.n) ?? asNumber(scope.eligible_count)
    return { key, label, scope: scopeLabel, count }
  })

  return (
    <div className="coverage-rating-panel">
      <div className="driver-evidence-head">
        <div>
          <span className="valuation-mini-title">Couverture & rating</span>
          <p>Gates affiches sur la tear sheet: BUY si upside &gt; 12% et confiance &gt;= 45%; SELL si upside &lt; -10% et confiance &gt;= 45%; NR si cible withheld ou donnees insuffisantes.</p>
        </div>
        {flags.length ? <AlertTriangle className="h-4 w-4 text-amber-700" /> : null}
      </div>
      <div className="coverage-rating-grid">
        <StatTile label="Couverture score" value={fmtPct(coveragePct, 0, false)} tone={coveragePct != null && coveragePct < 0.5 ? "t-neg" : coveragePct != null && coveragePct >= 0.7 ? "t-pos" : undefined} />
        <StatTile label="Dispersion CV" value={fmtRatio(dispersionCv, 2)} tone={dispersionCv != null && dispersionCv > 1 ? "t-neg" : undefined} />
        <StatTile label="Haircut disp." value={fmtPct(dispersionFactor, 0, false)} sub="facteur confiance" />
        <StatTile label="Mean vs median" value={fairMean == null || ensemble?.fair_value_base == null ? "-" : fmtMoney(fairMean - ensemble.fair_value_base, 1)} sub={`mean ${fmtMoney(fairMean, 1)}`} />
      </div>
      <div className="score-scope-strip">
        {scopes.map((item) => (
          <span key={item.key} className={cn("score-scope-chip", item.scope === "insufficient" && "low")}>
            {item.label}: {item.scope}{item.count != null ? ` (${fmtNumber(item.count, 0)})` : ""}
          </span>
        ))}
      </div>
      {flags.length || warnings.length ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {[...flags, ...warnings.map(compactFlagLabel)].slice(0, 10).map((flag) => (
            <span key={flag} className="fund-warning-chip">{flag}</span>
          ))}
        </div>
      ) : null}
    </div>
  )
}

function instantiatedFormula(row: FundamentalValuationResult, detail: FundamentalStockDetail): string | null {
  const inputs = asRecord(row.inputs)
  const outputs = asRecord(row.outputs)
  const bridge = asRecord(outputs.dcf_bridge)
  const shares = asNumber(inputs.shares) ?? asNumber(detail.metrics.Shares_Outstanding)
  const fairValue = fairValueForValuationRow(row, null)
  if (row.model === "fcff_dcf") {
    return `FV = (PV explicite ${fmtMoney(asNumber(bridge.explicit_pv), 0)} + PV terminale ${fmtMoney(asNumber(bridge.terminal_pv), 0)} - dette nette ${fmtMoney(asNumber(inputs.net_debt), 0)}) / actions ${fmtNumber(shares, 0)} = ${fmtMoney(fairValue, 2)}`
  }
  if (row.model === "fcfe_dcf") {
    return `FV = (PV explicite ${fmtMoney(asNumber(bridge.explicit_pv), 0)} + PV terminale ${fmtMoney(asNumber(bridge.terminal_pv), 0)}) / actions ${fmtNumber(shares, 0)} = ${fmtMoney(fairValue, 2)}`
  }
  if (row.model === "ddm") {
    return `FV = DPS ${fmtMoney(asNumber(inputs.dividend_per_share), 3)} x (1 + g ${fmtPct(asNumber(inputs.growth), 2, false)}) / (Ke ${fmtPct(asNumber(inputs.cost_of_equity), 2, false)} - g terminal ${fmtPct(asNumber(inputs.terminal_growth), 2, false)}) = ${fmtMoney(fairValue, 2)}`
  }
  if (row.model === "residual_income") {
    const book = asNumber(inputs.book_value_per_share)
    const residualPv = fairValue != null && book != null ? fairValue - book : null
    return `FV = BVPS ${fmtMoney(book, 2)} + PV revenus residuels ${fmtMoney(residualPv, 2)} = ${fmtMoney(fairValue, 2)}`
  }
  if (row.model === "justified_multiples") {
    const implied = asRecord(outputs.implied_prices)
    const justified = asRecord(outputs.justified_multiples)
    const roe = asNumber(inputs.roe)
    const growth = asNumber(inputs.growth)
    const costOfEquity = asNumber(inputs.cost_of_equity)
    const pbCalc = roe != null && growth != null && costOfEquity != null
      ? `PB justifie = (ROE ${fmtPct(roe, 2, false)} - g ${fmtPct(growth, 2, false)}) / (Ke ${fmtPct(costOfEquity, 2, false)} - g ${fmtPct(growth, 2, false)}) = ${fmtRatio(asNumber(justified.implied_pb), 2)}`
      : `PB justifie = ${fmtRatio(asNumber(justified.implied_pb), 2)}`
    return `${pbCalc}; FV = mediane prix implicites PB ${fmtMoney(asNumber(implied.justified_pb), 2)} / PE ${fmtMoney(asNumber(implied.justified_pe), 2)} = ${fmtMoney(fairValue, 2)}`
  }
  if (row.model === "relative_multiples") {
    const implied = Object.entries(asRecord(outputs.implied_prices))
      .map(([key, value]) => `FV ${comparableMetricLabel(key)} ${fmtMoney(asNumber(value), 2)}`)
      .join(" | ")
    return `FV modele = mediane des fair values par ratio (${implied || "n/a"}) = ${fmtMoney(fairValue, 2)}`
  }
  if (row.model === "reverse_dcf") {
    return `Resultat diagnostic, pas une FV: g implique = WACC ${fmtPct(asNumber(inputs.wacc), 2, false)} - FCF yield ${fmtPct(asNumber(inputs.fcf_yield), 2, false)} = ${fmtPct(asNumber(outputs.implied_perpetual_growth), 2, false)}`
  }
  return null
}

function sensitivityGridFromUnknown(value: unknown): SensitivityGridView | null {
  const record = asRecord(value)
  const xs = Array.isArray(record.xs) ? record.xs.map(asNumber).filter((item): item is number => item != null) : []
  const ys = Array.isArray(record.ys) ? record.ys.map(asNumber).filter((item): item is number => item != null) : []
  const matrix = Array.isArray(record.matrix)
    ? record.matrix.map((row) => (Array.isArray(row) ? row.map((item) => asNumber(item)) : []))
    : []
  if (!xs.length || !ys.length || !matrix.length) return null
  return {
    axis_x: typeof record.axis_x === "string" ? record.axis_x : "wacc",
    axis_y: typeof record.axis_y === "string" ? record.axis_y : "terminal_growth",
    xs,
    ys,
    matrix,
    model: typeof record.model === "string" ? record.model : null,
  }
}

function sensitivityGridFromResponse(sensitivity: FundamentalSensitivity | undefined): SensitivityGridView | null {
  return sensitivityGridFromUnknown(sensitivity)
}

function modelUsesSensitivityAxis(row: FundamentalValuationResult, axis: string): boolean {
  const meta = MODEL_FORMULA_META[row.model]
  const keys = new Set(meta?.assumptionKeys ?? Object.keys(asRecord(row.inputs)))
  switch (axis) {
    case "terminal_growth":
      return keys.has("terminal_growth") || keys.has("terminal_growth_firm") || keys.has("terminal_growth_equity")
    case "wacc":
      return keys.has("wacc")
    case "cost_of_equity":
      return keys.has("cost_of_equity")
    case "growth_cap":
      return keys.has("growth_cap")
    default:
      return keys.has(axis)
  }
}

function sensitivityGridHasVariation(grid: SensitivityGridView): boolean {
  const values = grid.matrix.flat().filter((value): value is number => value != null && Number.isFinite(value))
  if (!values.length) return false
  const first = values[0] ?? 0
  return values.some((value) => Math.abs(value - first) > Math.max(1e-6, Math.abs(first) * 1e-8))
}

function sensitivityGridAppliesToModel(row: FundamentalValuationResult, grid: SensitivityGridView): boolean {
  const axes = Array.from(new Set([grid.axis_x, grid.axis_y]))
  return axes.every((axis) => modelUsesSensitivityAxis(row, axis)) && sensitivityGridHasVariation(grid)
}

function modelSensitivityGrid(sensitivity: FundamentalSensitivity | undefined, row: FundamentalValuationResult): SensitivityGridView | null {
  if (!sensitivity) return null
  const grid = sensitivityGridFromUnknown(asRecord(sensitivity.model_grids)[row.model])
  return grid && sensitivityGridAppliesToModel(row, grid) ? grid : null
}

function axisDisplayLabel(axis: string): string {
  switch (axis) {
    case "wacc":
      return "WACC"
    case "terminal_growth":
      return "g terminal"
    case "growth_cap":
      return "plafond croissance"
    case "cost_of_equity":
      return "cout equity"
    default:
      return axis.replaceAll("_", " ")
  }
}

function latestStatementValue(
  row: FinancialStatementTable["rows"][number],
  periods: FinancialStatementTable["periods"],
): { value: number | null; sourceMetric: string | null; periodLabel: string } {
  for (let index = row.values.length - 1; index >= 0; index -= 1) {
    const value = row.values[index]?.value
    if (value != null) {
      return {
        value,
        sourceMetric: row.values[index]?.sourceMetric ?? null,
        periodLabel: periods[index]?.label ?? "Latest",
      }
    }
  }
  return { value: null, sourceMetric: null, periodLabel: periods.at(-1)?.label ?? "Latest" }
}

function statementEvidence(detail: FundamentalStockDetail, model: string): StatementEvidenceGroup[] {
  const meta = valuationFormulaMeta(model)
  return (["income", "balance", "cashflow"] as const).map((tab) => {
    const allowed = new Set(meta.statementKeys[tab])
    const table = buildFinancialStatementTable(detail, tab, "annual") as FinancialStatementTable
    const items = table.rows
      .filter((row) => allowed.has(row.key))
      .map((row) => {
        const resolved = latestStatementValue(row, table.periods)
        return {
          key: row.key,
          label: row.label,
          value: resolved.value,
          formatted: formatStatementValue(resolved.value, row.format),
          sourceMetric: resolved.sourceMetric,
          periodLabel: resolved.periodLabel,
        }
      })
    return { key: tab, title: STATEMENT_TITLES[tab], items }
  })
}

function valuationAssumptionItems(row: FundamentalValuationResult, detail: FundamentalStockDetail): ModelValueItem[] {
  const meta = valuationFormulaMeta(row.model)
  return meta.assumptionKeys
    .map((key) => {
      const inputValue = asRecord(row.inputs)[key]
      const assumptionValue = asRecord(detail.assumptions)[key]
      const value = inputValue ?? assumptionValue
      return {
        key,
        label: valueLabel(key),
        value,
        source: inputValue != null ? "model input" : assumptionValue != null ? "scenario" : undefined,
      }
    })
    .filter((item) => item.value != null)
}

function technicalInputItems(row: FundamentalValuationResult): ModelValueItem[] {
  const meta = valuationFormulaMeta(row.model)
  const inputs = asRecord(row.inputs)
  const preferred = meta.technicalInputKeys
    .filter((key) => inputs[key] != null)
    .map((key) => ({ key, label: valueLabel(key), value: inputs[key], source: "input" }))
  if (preferred.length > 0) return preferred
  return Object.entries(inputs)
    .slice(0, 6)
    .map(([key, value]) => ({ key, label: valueLabel(key), value, source: "input" }))
}

function outputItems(row: FundamentalValuationResult): ModelValueItem[] {
  return Object.entries(asRecord(row.outputs)).map(([key, value]) => ({ key, label: valueLabel(key), value, source: "output" }))
}

function ModelValueGrid({ title, items, empty }: { title: string; items: ModelValueItem[]; empty: string }) {
  return (
    <div className="valuation-mini-block">
      <div className="valuation-mini-title">{title}</div>
      {items.length ? (
        <div className="valuation-kv-list">
          {items.map((item) => (
            <div key={item.key} className="valuation-kv-row">
              <span className="valuation-kv-label">
                {item.label}
                {item.source ? <em>{item.source}</em> : null}
              </span>
              <span className="valuation-kv-value">
                <ValuePreview itemKey={item.key} value={item.value} />
              </span>
            </div>
          ))}
        </div>
      ) : (
        <div className="valuation-empty-line">{empty}</div>
      )}
    </div>
  )
}

function StatementEvidenceCard({ group }: { group: StatementEvidenceGroup }) {
  return (
    <div className="valuation-statement-card">
      <div className="valuation-statement-title">{group.title}</div>
      {group.items.length ? (
        <div className="valuation-statement-list">
          {group.items.map((item) => (
            <div key={item.key} className="valuation-statement-row">
              <span>
                <strong>{item.label}</strong>
                <em>{item.sourceMetric ? `${item.sourceMetric} - ${item.periodLabel}` : item.periodLabel}</em>
              </span>
              <b>{item.formatted}</b>
            </div>
          ))}
        </div>
      ) : (
        <div className="valuation-empty-line">No usable statement line.</div>
      )}
    </div>
  )
}

function ComparableValuationCells({
  currentPrice,
  summary,
  isLoading,
}: {
  currentPrice: number | null | undefined
  summary: ComparableModelSummary
  isLoading: boolean
}) {
  const current = asNumber(currentPrice)
  const upside = summary.fairValue != null && current != null && current > 0 ? summary.fairValue / current - 1 : summary.upside
  return (
    <>
      <td className="r font-mono">{isLoading && summary.fairValue == null ? "..." : fmtMoney(summary.fairValue, 1)}</td>
      <td className="r font-mono">{fmtMoney(currentPrice, 1)}</td>
      <td className={cn("r font-mono font-semibold", (upside ?? 0) >= 0 ? "t-pos" : "t-neg")}>
        {isLoading && upside == null ? "..." : fmtPct(upside)}
      </td>
    </>
  )
}

function ReverseDcfSummaryCells({ row, detail }: { row: FundamentalValuationResult; detail: FundamentalStockDetail }) {
  const inputs = asRecord(row.inputs)
  const outputs = asRecord(row.outputs)
  const impliedGrowth = asNumber(outputs.implied_perpetual_growth)
  const terminalGrowth = asNumber(detail.assumptions.terminal_growth_firm ?? detail.assumptions.terminal_growth)
  const spread = impliedGrowth != null && terminalGrowth != null ? impliedGrowth - terminalGrowth : null
  return (
    <>
      <td className="r font-mono font-semibold" title="Reverse DCF output: implied perpetual-growth assumption, not fair value">
        g {fmtPct(impliedGrowth, 2, false)}
      </td>
      <td className="r font-mono" title="Input used by the diagnostic">
        WACC {fmtPct(asNumber(inputs.wacc), 2, false)}
      </td>
      <td className={cn("r font-mono font-semibold", (spread ?? 0) > 0 ? "t-neg" : "t-pos")} title="Gap versus model terminal growth assumption">
        vs g {fmtPct(spread, 2, false)}
      </td>
    </>
  )
}

function ComparableValuationTiles({
  detail,
  currentPrice,
  weight,
  summary,
  isLoading,
  isIncluded,
}: {
  detail: FundamentalStockDetail
  currentPrice: number | null | undefined
  weight: number | null | undefined
  summary: ComparableModelSummary
  isLoading: boolean
  isIncluded: boolean
}) {
  const current = asNumber(currentPrice)
  const upside = summary.fairValue != null && current != null && current > 0 ? summary.fairValue / current - 1 : summary.upside
  const currency = detail.ensemble?.currency ?? "MAD"
  return (
    <div className="valuation-method-metrics">
      <StatTile
        label="Model FV"
        value={isLoading && summary.fairValue == null ? "..." : `${fmtMoney(summary.fairValue, 1)} ${currency}`}
        sub={summary.peerCount ? `${summary.peerCount} comparables` : `${summary.count} multiples`}
      />
      {summary.impliedPrices.map((item) => (
        <StatTile
          key={item.metric}
          label={`FV ${comparableMetricLabel(item.metric)}`}
          value={`${fmtMoney(item.fairValue, 1)} ${currency}`}
          sub={`pairs ${fmtRatio(item.benchmark, 1)} / titre ${fmtRatio(item.selectedValue, 1)}`}
        />
      ))}
      <StatTile label="Current" value={currentPrice != null ? `${fmtMoney(currentPrice, 1)} ${currency}` : "-"} />
      <StatTile label="Upside" value={isLoading && upside == null ? "..." : fmtPct(upside)} tone={(upside ?? 0) >= 0 ? "t-pos" : "t-neg"} />
      <StatTile label="Weight" value={!isIncluded ? "Excluded" : weight == null ? "-" : `${(weight * 100).toFixed(0)}%`} />
    </div>
  )
}

function dcfModeForModel(model: string): DcfMode | null {
  if (model === "fcff_dcf") return "fcff"
  if (model === "fcfe_dcf") return "fcfe"
  return null
}

function dcfVerdict(displayUpside: number | null | undefined, mode: DcfMode): string {
  if (displayUpside == null) return `Verdict ${mode.toUpperCase()} non disponible.`
  const magnitude = fmtPct(Math.abs(displayUpside), 1, false)
  return displayUpside >= 0
    ? `Sous-evalue de ${magnitude} selon le DCF ${mode.toUpperCase()}.`
    : `Surevalue de ${magnitude} selon le DCF ${mode.toUpperCase()}.`
}

function terminalBasisLine(dcf: DcfAvailableViewModel): string {
  const basis = dcf.terminalBasis
  const source = typeof basis.source === "string" ? basis.source.replaceAll("_", " ") : "hypothese modele"
  const binding = typeof basis.binding_constraint === "string" ? basis.binding_constraint.replaceAll("_", " ") : null
  const raw = asNumber(basis.raw_growth)
  const ceiling = asNumber(basis.ceiling)
  const floor = asNumber(basis.floor)
  const capText = [
    raw != null ? `brut ${fmtPct(raw, 2, false)}` : null,
    ceiling != null ? `plafond ${fmtPct(ceiling, 2, false)}` : null,
    floor != null ? `plancher ${fmtPct(floor, 2, false)}` : null,
    binding ? `contrainte ${binding}` : null,
  ].filter(Boolean).join(" | ")
  if (dcf.mode === "fcff") {
    const reinvestment = asNumber(basis.reinvestment_rate)
    const roic = asNumber(basis.roic)
    if (reinvestment != null && roic != null) {
      return `g firm = reinvestissement ${fmtPct(reinvestment, 2, false)} x ROIC ${fmtPct(roic, 2, false)} = ${fmtPct(dcf.terminalGrowth, 2, false)}${capText ? ` (${capText})` : ""}`
    }
  } else {
    const retention = asNumber(basis.retention)
    const roe = asNumber(basis.roe)
    if (retention != null && roe != null) {
      return `g equity = retention ${fmtPct(retention, 2, false)} x ROE ${fmtPct(roe, 2, false)} = ${fmtPct(dcf.terminalGrowth, 2, false)}${capText ? ` (${capText})` : ""}`
    }
  }
  return `g terminal = ${fmtPct(dcf.terminalGrowth, 2, false)} (${source}${capText ? ` | ${capText}` : ""})`
}

function formatDcfStepValue(step: DcfBridgeStep): string {
  if (step.value == null) return "-"
  if (step.kind === "divide") return fmtNumber(step.value, 0)
  if (step.kind === "result") return fmtMoney(step.value, 2)
  return fmtMoney(step.value, 0)
}

function DcfPvTable({ dcf }: { dcf: DcfAvailableViewModel }) {
  const cashFlowGlossaryId = dcf.mode === "fcff" ? "fcff" : "fcfe"
  return (
    <div className="dcf-table-wrap">
      <table className="claude-table dcf-pv-table">
        <thead>
          <tr>
            <th>Annee</th>
            <th className="r"><GlossaryTerm id={cashFlowGlossaryId}>{dcf.cashFlowLabel}</GlossaryTerm></th>
            <th className="r">Croissance</th>
            <th className="r"><GlossaryTerm id="discount-period">t</GlossaryTerm></th>
            <th className="r"><GlossaryTerm id="discount-factor">Facteur</GlossaryTerm></th>
            <th className="r"><GlossaryTerm id="present-value">PV</GlossaryTerm></th>
          </tr>
        </thead>
        <tbody>
          {dcf.pvRows.map((item) => (
            <tr key={item.index}>
              <td>Y{item.index}</td>
              <td className="r font-mono">{fmtMoney(item.cashFlow, 0)}</td>
              <td className="r font-mono">{fmtPct(item.growth, 1, false)}</td>
              <td className="r font-mono">{fmtNumber(item.period, 2)}</td>
              <td className="r font-mono">{fmtNumber(item.discountFactor, 4)}</td>
              <td className="r font-mono font-semibold">{fmtMoney(item.pv, 0)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan={5}>Somme PV explicite</td>
            <td className="r font-mono font-semibold">{fmtMoney(dcf.explicitPv, 0)}</td>
          </tr>
        </tfoot>
      </table>
      <p className="dcf-table-legend">
        <strong>t</strong> = nombre d'annees avant le flux. <strong>Facteur</strong> = 1 / (1 + {dcf.rateLabel})<sup>t</sup>, toujours entre 0 et 1.{" "}
        <strong>PV</strong> = flux x facteur, soit sa valeur d'aujourd'hui. Chaque terme renvoie au glossaire.
      </p>
    </div>
  )
}

function DcfHistoryStrip({ projection, mode, cashFlowLabel }: { projection: ProjectionView; mode: DcfMode; cashFlowLabel: string }) {
  const history = useMemo(() => {
    const driver = projection.drivers[mode]
    return driver ? historicalSeriesFromDriver(driver).slice(-5) : []
  }, [projection, mode])
  if (history.length < 2) return null
  const cashFlowGlossaryId = mode === "fcff" ? "fcff" : "fcfe"
  return (
    <div className="dcf-history-strip">
      <div className="dcf-history-head">
        <span className="valuation-mini-title">
          Historique <GlossaryTerm id={cashFlowGlossaryId}>{cashFlowLabel}</GlossaryTerm> (realise)
        </span>
        <span>{history.length} exercices avant projection</span>
      </div>
      <div className="dcf-history-row">
        {history.map((point) => (
          <div key={point.year} className="dcf-history-cell">
            <div className="dcf-history-year">{point.year}</div>
            <div className="dcf-history-value">{fmtMoney(point.value, 0)}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

function DcfTerminalBlock({ dcf }: { dcf: DcfAvailableViewModel }) {
  return (
    <div className="dcf-terminal-block">
      <div className="valuation-formula-panel">
        <div className="valuation-formula-eyebrow">Valeur terminale</div>
        <div className="valuation-formula-line">
          TV = {dcf.cashFlowLabel}_n {fmtMoney(dcf.pvRows.at(-1)?.cashFlow, 0)} x (1 + g {fmtPct(dcf.terminalGrowth, 2, false)}) / ({dcf.rateLabel} {fmtPct(dcf.discountRate, 2, false)} - g) = {fmtMoney(dcf.terminalValue, 0)}
        </div>
        <div className="valuation-formula-sub">{terminalBasisLine(dcf)}</div>
      </div>
      <div className="dcf-terminal-grid">
        <StatTile label="g terminal" value={fmtPct(dcf.terminalGrowth, 2, false)} sub={String(dcf.terminalBasis.binding_constraint ?? "modele")} />
        <StatTile label="TV nominale" value={fmtMoney(dcf.terminalValue, 0)} />
        <StatTile label="Facteur TV" value={fmtNumber(dcf.terminalDiscountFactor, 4)} sub={`t ${fmtNumber(dcf.terminalPeriod, 2)}`} />
        <StatTile label="PV(TV)" value={fmtMoney(dcf.terminalPv, 0)} />
        <StatTile label="Poids TV" value={fmtPct(dcf.terminalValuePct, 1, false)} tone={dcf.flags.terminalHeavy ? "t-neg" : undefined} />
        {dcf.mode === "fcff" ? <StatTile label="Exit EV/EBITDA" value={fmtRatio(dcf.impliedExitEvToEbitda, 2)} /> : null}
      </div>
    </div>
  )
}

function DcfValueWaterfall({ dcf }: { dcf: DcfAvailableViewModel }) {
  const maxAbs = Math.max(1, ...dcf.bridgeSteps.map((step) => Math.abs(step.value ?? 0)))
  return (
    <div className="dcf-waterfall">
      {dcf.bridgeSteps.map((step) => {
        const width = `${Math.max(5, (Math.abs(step.value ?? 0) / maxAbs) * 100)}%`
        return (
          <div key={step.key} className={cn("dcf-waterfall-row", step.kind)}>
            <span>{step.label}</span>
            <div className="dcf-waterfall-track">
              <div className={cn("dcf-waterfall-fill", step.kind, (step.value ?? 0) < 0 && "neg")} style={{ width }} />
            </div>
            <strong>{formatDcfStepValue(step)}</strong>
          </div>
        )
      })}
    </div>
  )
}

function DcfCoherenceChips({ dcf, row }: { dcf: DcfAvailableViewModel; row: FundamentalValuationResult }) {
  const chips = [
    { key: "g_lt_r", label: `g < ${dcf.rateLabel}`, ok: dcf.flags.gBelowRate },
    { key: "tv_weight", label: "TV < 75%", ok: !dcf.flags.terminalHeavy },
    { key: "proxy", label: row.is_proxy ? "Proxy" : "Non proxy", ok: !row.is_proxy },
    { key: "mid_year", label: dcf.midYearDiscounting ? "Mid-year ON" : "Mid-year OFF", ok: true },
    { key: "terminal", label: dcf.midYearTerminal ? "TV mid-year" : "TV full-year", ok: true },
    ...dcf.reconciliations.map((item) => ({ key: item.key, label: item.ok ? `${item.label} OK` : `${item.label} ecart`, ok: item.ok })),
  ]
  return (
    <div className="dcf-chip-row">
      {chips.map((chip) => (
        <span key={chip.key} className={cn("dcf-check-chip", chip.ok ? "ok" : "warn")}>{chip.label}</span>
      ))}
    </div>
  )
}

function DcfMethodView({
  row,
  detail,
  isIncluded,
  effectiveWeight,
  sensitivity,
  dcfMode,
}: {
  row: FundamentalValuationResult
  detail: FundamentalStockDetail
  isIncluded: boolean
  effectiveWeight: number | null
  sensitivity?: FundamentalSensitivity
  dcfMode: DcfMode
}) {
  const meta = valuationFormulaMeta(row.model)
  const dcf = buildDcfViewModel(row, detail, dcfMode) as DcfViewModel
  const projection = projectionFromDetail(detail)
  const statementGroups = statementEvidence(detail, row.model)
  const assumptions = valuationAssumptionItems(row, detail)
  const inputs = technicalInputItems(row)
  const outputs = outputItems(row)
  const formulaValues = instantiatedFormula(row, detail)
  const isUnavailable = row.confidence === "unavailable" || !dcf.available
  const effectiveFairValue = fairValueForValuationRow(row, null)
  const currency = row.currency ?? detail.ensemble?.currency ?? "MAD"
  const fairValue = effectiveFairValue != null ? `${fmtMoney(effectiveFairValue, 1)} ${currency}` : "-"
  const current = currentPriceForValuationRow(row, detail)
  const currentPrice = current != null ? `${fmtMoney(current, 1)} ${currency}` : "-"
  const displayUpside = upsideForFairValue(effectiveFairValue, current) ?? row.upside_pct

  return (
    <section className={cn("valuation-method-card dcf-method-card", isUnavailable && "unavailable", !isIncluded && row.family !== "diagnostic" && "excluded")}>
      <div className="valuation-method-top">
        <div>
          <div className="valuation-method-title-row">
            <h4>{MODEL_LABELS[row.model] ?? row.model}</h4>
            <span className={cn("signal-conf-badge", confidenceClass(row.confidence))}>
              {row.confidence}
              {row.is_proxy ? " proxy" : ""}
            </span>
          </div>
          <p>{row.methodology ?? meta.explanation}</p>
          <div className={cn("dcf-verdict", (displayUpside ?? 0) >= 0 ? "positive" : "negative")}>{dcfVerdict(displayUpside, dcfMode)}</div>
        </div>
        <div className="valuation-method-metrics">
          <StatTile label="Fair value" value={fairValue} />
          <StatTile label="Current" value={currentPrice} />
          <StatTile label="Upside" value={fmtPct(displayUpside)} tone={(displayUpside ?? 0) >= 0 ? "t-pos" : "t-neg"} />
          <StatTile label="Weight" value={!isIncluded && row.family !== "diagnostic" ? "Excluded" : effectiveWeight == null ? "-" : `${(effectiveWeight * 100).toFixed(0)}%`} />
        </div>
      </div>

      <div className="valuation-formula-panel">
        <div className="valuation-formula-eyebrow">Formule utilisee</div>
        <div className="valuation-formula-line">{formulaValues ?? meta.formula}</div>
        {formulaValues ? <div className="valuation-formula-sub">{meta.formula}</div> : null}
        {meta.secondaryFormula ? <div className="valuation-formula-sub">{meta.secondaryFormula}</div> : null}
        <p>{meta.explanation}</p>
      </div>

      {!dcf.available ? (
        <>
          <CostOfCapitalBuildUp detail={detail} row={row} />
          <div className="fund-empty-small">{dcf.reason}</div>
        </>
      ) : (
        <>
          <div className="dcf-step">
            <div className="dcf-step-head">
              <span>1</span>
              <div>
                <div className="valuation-mini-title">Taux d'actualisation</div>
                <p>
                  {dcf.mode === "fcff" ? (
                    <>
                      <GlossaryTerm id="fcff">FCFF</GlossaryTerm> = flux a tous les apporteurs de capital, actualise au{" "}
                      <GlossaryTerm id="wacc">WACC</GlossaryTerm>.
                    </>
                  ) : (
                    <>
                      <GlossaryTerm id="fcfe">FCFE</GlossaryTerm> = flux aux actionnaires, actualise au{" "}
                      <GlossaryTerm id="cost-of-equity">cout des fonds propres</GlossaryTerm>.
                    </>
                  )}
                </p>
              </div>
            </div>
            <CostOfCapitalBuildUp detail={detail} row={row} />
          </div>

          <div className="dcf-step">
            <div className="dcf-step-head">
              <span>2</span>
              <div>
                <div className="valuation-mini-title">Flux projetes et actualisation</div>
                <p>
                  Chaque flux projete est actualise avec {dcf.rateLabel} {fmtPct(dcf.discountRate, 2, false)} et sa periode{" "}
                  <GlossaryTerm id="discount-period">t</GlossaryTerm>. L'historique realise situe le point de depart des projections.
                </p>
              </div>
            </div>
            {projection ? <DcfHistoryStrip projection={projection} mode={dcf.mode} cashFlowLabel={dcf.cashFlowLabel} /> : null}
            <DcfPvTable dcf={dcf} />
          </div>

          <div className="dcf-step">
            <div className="dcf-step-head">
              <span>3</span>
              <div>
                <div className="valuation-mini-title"><GlossaryTerm id="terminal-value">Valeur terminale</GlossaryTerm></div>
                <p>
                  Perpetuite Gordon avec le <GlossaryTerm id="terminal-growth">g terminal</GlossaryTerm> du modele: elle resume
                  tous les flux au-dela de l'horizon explicite.
                </p>
              </div>
            </div>
            <DcfTerminalBlock dcf={dcf} />
          </div>

          <div className="dcf-step">
            <div className="dcf-step-head">
              <span>4</span>
              <div>
                <div className="valuation-mini-title"><GlossaryTerm id="net-debt-bridge">Pont vers la valeur par action</GlossaryTerm></div>
                <p>
                  {dcf.mode === "fcff" ? (
                    <>EV moins dette nette ({dcf.netDebtSource ?? "source non renseignee"}) puis division par les actions.</>
                  ) : (
                    <>FCFE est deja un flux aux actionnaires: aucun pont dette nette.</>
                  )}
                </p>
              </div>
            </div>
            <div className="dcf-value-grid">
              <DcfValueWaterfall dcf={dcf} />
              <ModelValueGrid
                title="Reconciliation"
                items={dcf.bridgeSteps.map((step) => ({ key: step.key, label: step.label, value: step.value, source: step.kind }))}
                empty="No bridge rows."
              />
            </div>
          </div>

          <ModelSensitivityPanel row={row} detail={detail} sensitivity={sensitivity} />

          {projection ? (
            <div>
              <div className="valuation-subtitle">Construction du flux</div>
              <div className="driver-evidence-grid">
                <DriverEvidenceChart driver={projection.drivers[dcf.mode]} label={dcf.cashFlowLabel} format="money" />
                <FcfBridge projection={projection} mode={dcf.mode} />
              </div>
            </div>
          ) : null}

          <div className="valuation-method-grid">
            <ModelValueGrid title="Hypotheses du modele" items={assumptions} empty="No scenario assumptions persisted." />
          </div>

          <DcfCoherenceChips dcf={dcf} row={row} />

          <details className="dcf-raw-disclosure">
            <summary>Donnees brutes (avance)</summary>
            <div className="valuation-method-grid">
              <ModelValueGrid title="Inputs modele" items={inputs} empty="No model inputs persisted." />
              <ModelValueGrid title="Outputs calcules" items={outputs} empty="No additional output persisted." />
            </div>
            <div>
              <div className="valuation-subtitle">Donnees 3 etats utilisees</div>
              <div className="valuation-statement-grid">
                {statementGroups.map((group) => (
                  <StatementEvidenceCard key={group.key} group={group} />
                ))}
              </div>
            </div>
          </details>
        </>
      )}

      <div className="valuation-warning-row">
        <span className="valuation-warning-label">Warnings</span>
        <div className="flex flex-wrap gap-1.5">
          {row.warnings.length ? row.warnings.map((warning) => <span key={warning} className="fund-warning-chip">{warning}</span>) : <span className="text-xs text-muted-foreground">No warnings.</span>}
        </div>
      </div>
    </section>
  )
}

function formatStoryValue(value: unknown, format?: ModelStoryMetricFormat, digits?: number): string {
  const numberValue = asNumber(value)
  if (numberValue == null) return value == null || value === "" ? "-" : String(value)
  if (format === "money") return fmtMoney(numberValue, digits ?? 2)
  if (format === "pct") return fmtPct(numberValue, digits ?? 2, false)
  if (format === "ratio") return fmtRatio(numberValue, digits ?? 2)
  return fmtNumber(numberValue, digits ?? (Math.abs(numberValue) < 10 ? 2 : 0))
}

function StoryMetricGrid({ metrics }: { metrics: ModelStoryMetric[] | undefined }) {
  const visible = (metrics ?? []).filter((metric) => metric.value != null)
  if (!visible.length) return null
  return (
    <div className="model-story-metric-grid">
      {visible.map((metric) => (
        <StatTile
          key={metric.label}
          label={metric.label}
          value={formatStoryValue(metric.value, metric.format)}
          sub={metric.source == null ? undefined : String(metric.source)}
        />
      ))}
    </div>
  )
}

function storyCellKey(cell: ModelStoryTableCell, index: number): string {
  if (cell && typeof cell === "object") return `${index}-${String(cell.value ?? "")}`
  return `${index}-${String(cell ?? "")}`
}

function StoryTable({ table }: { table: ModelStoryStep["table"] }) {
  if (!table || !table.rows.length) return null
  return (
    <div className="model-story-table-wrap">
      <table className="claude-table model-story-table">
        <thead>
          <tr>
            {table.columns.map((column, index) => (
              <th key={`${column}-${index}`} className={index === 0 ? undefined : "r"}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, rowIndex) => (
            <tr key={row.map(storyCellKey).join("|") || rowIndex}>
              {row.map((cell, cellIndex) => {
                const isObject = cell && typeof cell === "object"
                const text = isObject ? formatStoryValue(cell.value, cell.format, cell.digits) : typeof cell === "number" ? fmtNumber(cell, Math.abs(cell) < 10 ? 2 : 0) : cell == null || cell === "" ? "-" : String(cell)
                return (
                  <td key={storyCellKey(cell, cellIndex)} className={cn(cellIndex === 0 ? undefined : "r", cellIndex > 0 && "font-mono")}>
                    {text}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ModelStoryPanel({ story }: { story: ModelStory }) {
  return (
    <div className="model-story-panel">
      <div className="model-story-head">
        <div>
          <div className="valuation-mini-title">{story.title}</div>
          <p>{story.summary}</p>
        </div>
        <div className="dcf-chip-row">
          {story.checks.map((check) => (
            <span key={check.label} className={cn("dcf-check-chip", check.ok ? "ok" : "warn")}>{check.label}</span>
          ))}
        </div>
      </div>
      <div className="model-story-steps">
        {story.steps.map((step, index) => (
          <div key={`${step.title}-${index}`} className="model-story-step">
            <div className="dcf-step-head">
              <span>{index + 1}</span>
              <div>
                <div className="valuation-mini-title">{step.title}</div>
                <p>{step.description}</p>
              </div>
            </div>
            {step.formula ? (
              <div className="valuation-formula-panel model-story-formula">
                <div className="valuation-formula-eyebrow">Formule</div>
                <div className="valuation-formula-line">{step.formula}</div>
              </div>
            ) : null}
            <StoryMetricGrid metrics={step.metrics} />
            <StoryTable table={step.table} />
          </div>
        ))}
      </div>
    </div>
  )
}

function ReverseDcfDiagnosticTiles({
  row,
  detail,
  effectiveWeight,
  isIncluded,
}: {
  row: FundamentalValuationResult
  detail: FundamentalStockDetail
  effectiveWeight: number | null
  isIncluded: boolean
}) {
  const inputs = asRecord(row.inputs)
  const outputs = asRecord(row.outputs)
  const impliedGrowth = asNumber(outputs.implied_perpetual_growth)
  const terminalGrowth = asNumber(detail.assumptions.terminal_growth_firm ?? detail.assumptions.terminal_growth)
  const spread = impliedGrowth != null && terminalGrowth != null ? impliedGrowth - terminalGrowth : null
  return (
    <div className="valuation-method-metrics reverse-dcf-metrics">
      <StatTile label="Resultat" value={fmtPct(impliedGrowth, 2, false)} sub="g implicite, pas un prix" />
      <StatTile label="WACC" value={fmtPct(asNumber(inputs.wacc), 2, false)} sub="hypothese" />
      <StatTile label="FCF yield" value={fmtPct(asNumber(inputs.fcf_yield), 2, false)} sub="input marche" />
      <StatTile label="Ecart vs g modele" value={fmtPct(spread, 2, false)} tone={(spread ?? 0) > 0 ? "t-neg" : "t-pos"} sub={!isIncluded && row.family !== "diagnostic" ? "Excluded" : effectiveWeight == null ? "diagnostic" : `${(effectiveWeight * 100).toFixed(0)}%`} />
    </div>
  )
}

function MultipleRatioSelectionPanel({
  row,
  detail,
  draft,
  onDraftChange,
  onSave,
  isSaving,
}: {
  row: FundamentalValuationResult
  detail: FundamentalStockDetail
  draft: Record<string, number>
  onDraftChange: (draft: Record<string, number>) => void
  onSave: () => void
  isSaving: boolean
}) {
  const isJustified = row.model === "justified_multiples"
  const definitions = isJustified ? JUSTIFIED_MULTIPLE_RATIOS : row.model === "relative_multiples" ? RELATIVE_MULTIPLE_RATIOS : []
  if (!definitions.length) return null

  const maskKey = isJustified ? JUSTIFIED_MULTIPLE_RATIO_MASK_KEY : RELATIVE_MULTIPLE_RATIO_MASK_KEY
  const fallback = isJustified ? JUSTIFIED_MULTIPLE_RATIO_DEFAULT_MASK : RELATIVE_MULTIPLE_RATIO_DEFAULT_MASK
  const currentMask = detailRatioMask(detail, {}, maskKey, fallback, fallback)
  const activeMask = detailRatioMask(detail, draft, maskKey, fallback, fallback)
  const selectedCount = enabledRatioKeys(definitions, activeMask).length
  const hasPendingChange = draft[maskKey] != null && activeMask !== currentMask

  const setMask = (nextMask: number) => {
    const bounded = boundedMask(nextMask, fallback, fallback)
    const next = { ...draft }
    if (bounded === currentMask) delete next[maskKey]
    else next[maskKey] = bounded
    onDraftChange(next)
  }

  const toggleRatio = (definition: MultipleRatioDefinition, checked: boolean) => {
    const nextMask = checked ? activeMask | definition.bit : activeMask & ~definition.bit
    setMask(nextMask)
  }

  return (
    <div className="valuation-ratio-selection valuation-mini-block">
      <div className="driver-evidence-head">
        <span className="valuation-mini-title">Ratios retenus dans le modele</span>
        <span>{selectedCount}/{definitions.length} actifs{hasPendingChange ? " - non enregistre" : ""}</span>
      </div>
      <div className="valuation-ratio-toggle-grid">
        {definitions.map((definition) => {
          const checked = (activeMask & definition.bit) !== 0
          return (
            <label key={definition.key} className={cn("valuation-model-toggle", checked && "active")}>
              <input
                type="checkbox"
                checked={checked}
                disabled={isSaving}
                onChange={(event) => toggleRatio(definition, event.target.checked)}
              />
              <span className="valuation-model-toggle-main">
                <strong>{definition.label}</strong>
                <em>{definition.key}</em>
              </span>
              <span className="valuation-model-toggle-weight">{checked ? "On" : "Off"}</span>
            </label>
          )
        })}
      </div>
      <div className="valuation-model-actions">
        <button type="button" onClick={() => setMask(fallback)} disabled={isSaving || activeMask === fallback}>Tous</button>
        <button type="button" onClick={() => setMask(0)} disabled={isSaving || activeMask === 0}>Aucun</button>
        <Button type="button" size="sm" onClick={onSave} disabled={!hasPendingChange || isSaving}>
          {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          {isSaving ? "Enregistrement" : "Enregistrer selection"}
        </Button>
      </div>
    </div>
  )
}

function ValuationMethodCard({
  row,
  detail,
  selectedRow,
  universeRows,
  selectedComparatorId,
  onSelectedComparatorIdChange,
  comparableSummary,
  isComparableSummaryLoading,
  isIncluded,
  effectiveWeight,
  sensitivity,
  assumptionDraft,
  onAssumptionDraftChange,
  onSaveAssumptions,
  isSaving,
}: {
  row: FundamentalValuationResult
  detail: FundamentalStockDetail
  selectedRow: FundamentalUniverseRow | null
  universeRows: FundamentalUniverseRow[]
  selectedComparatorId: string
  onSelectedComparatorIdChange: (id: string) => void
  comparableSummary: ComparableModelSummary
  isComparableSummaryLoading: boolean
  isIncluded: boolean
  effectiveWeight: number | null
  sensitivity?: FundamentalSensitivity
  assumptionDraft: Record<string, number>
  onAssumptionDraftChange: (draft: Record<string, number>) => void
  onSaveAssumptions: () => void
  isSaving: boolean
}) {
  const dcfMode = dcfModeForModel(row.model)
  if (dcfMode) {
    return (
      <DcfMethodView
        row={row}
        detail={detail}
        isIncluded={isIncluded}
        effectiveWeight={effectiveWeight}
        sensitivity={sensitivity}
        dcfMode={dcfMode}
      />
    )
  }

  const meta = valuationFormulaMeta(row.model)
  const statementGroups = statementEvidence(detail, row.model)
  const assumptions = valuationAssumptionItems(row, detail)
  const inputs = technicalInputItems(row)
  const outputs = outputItems(row)
  const formulaValues = instantiatedFormula(row, detail)
  const story = buildValuationModelStory(row, detail) as ModelStory | null
  const isUnavailable = row.confidence === "unavailable"
  const isComparablesModel = row.model === "relative_multiples"
  const isReverseDcfModel = row.model === "reverse_dcf"
  const effectiveFairValue = fairValueForValuationRow(row, isComparablesModel ? comparableSummary : null)
  const fairValue = effectiveFairValue != null ? `${fmtMoney(effectiveFairValue, 1)} ${row.currency ?? detail.ensemble?.currency ?? "MAD"}` : "-"
  const currentPrice = row.current_price != null ? `${fmtMoney(row.current_price, 1)} ${row.currency ?? detail.ensemble?.currency ?? "MAD"}` : "-"
  const displayUpside = upsideForFairValue(effectiveFairValue, currentPriceForValuationRow(row, detail)) ?? row.upside_pct

  return (
    <section className={cn("valuation-method-card", isUnavailable && "unavailable", !isIncluded && row.family !== "diagnostic" && "excluded")}>
      <div className="valuation-method-top">
        <div>
          <div className="valuation-method-title-row">
            <h4>{MODEL_LABELS[row.model] ?? row.model}</h4>
            <span className={cn("signal-conf-badge", confidenceClass(row.confidence))}>
              {row.confidence}
              {row.is_proxy ? " proxy" : ""}
            </span>
          </div>
          <p>{row.methodology ?? meta.explanation}</p>
        </div>
        {isComparablesModel ? (
          <ComparableValuationTiles
            detail={detail}
            currentPrice={row.current_price}
            weight={effectiveWeight}
            summary={comparableSummary}
            isLoading={isComparableSummaryLoading}
            isIncluded={isIncluded}
          />
        ) : isReverseDcfModel ? (
          <ReverseDcfDiagnosticTiles row={row} detail={detail} effectiveWeight={effectiveWeight} isIncluded={isIncluded} />
        ) : (
          <div className="valuation-method-metrics">
            <StatTile label="Fair value" value={fairValue} />
            <StatTile label="Current" value={currentPrice} />
            <StatTile label="Upside" value={fmtPct(displayUpside)} tone={(displayUpside ?? 0) >= 0 ? "t-pos" : "t-neg"} />
            <StatTile label="Weight" value={!isIncluded && row.family !== "diagnostic" ? "Excluded" : effectiveWeight == null ? "-" : `${(effectiveWeight * 100).toFixed(0)}%`} />
          </div>
        )}
      </div>

      <div className="valuation-formula-panel">
        <div className="valuation-formula-eyebrow">Formule utilisee</div>
        <div className="valuation-formula-line">{formulaValues ?? meta.formula}</div>
        {formulaValues ? <div className="valuation-formula-sub">{meta.formula}</div> : null}
        {meta.secondaryFormula ? <div className="valuation-formula-sub">{meta.secondaryFormula}</div> : null}
        <p>{meta.explanation}</p>
      </div>

      <MultipleRatioSelectionPanel
        row={row}
        detail={detail}
        draft={assumptionDraft}
        onDraftChange={onAssumptionDraftChange}
        onSave={onSaveAssumptions}
        isSaving={isSaving}
      />

      {story ? <ModelStoryPanel story={story} /> : null}

      {isComparablesModel ? null : <CostOfCapitalBuildUp detail={detail} row={row} />}

      {isComparablesModel ? (
        <ComparableBenchmarkPanel
          detail={detail}
          row={selectedRow}
          rows={universeRows}
          selectedComparatorId={selectedComparatorId}
          onSelectedComparatorIdChange={onSelectedComparatorIdChange}
          embedded
          title="Comparables - modele principal"
        />
      ) : null}

      <ModelSensitivityPanel row={row} detail={detail} sensitivity={sensitivity} />

      <div className="valuation-method-grid">
        <ModelValueGrid title="Hypotheses du modele" items={assumptions} empty="No scenario assumptions persisted." />
      </div>

      <details className="dcf-raw-disclosure model-raw-disclosure">
        <summary>Donnees brutes (avance)</summary>
        <div className="valuation-method-grid">
          <ModelValueGrid title="Inputs modele" items={inputs} empty="No model inputs persisted." />
          <ModelValueGrid title="Outputs calcules" items={outputs} empty="No additional output persisted." />
        </div>
        <div>
          <div className="valuation-subtitle">Donnees 3 etats utilisees</div>
          <div className="valuation-statement-grid">
            {statementGroups.map((group) => (
              <StatementEvidenceCard key={group.key} group={group} />
            ))}
          </div>
        </div>
      </details>

      <div className="valuation-warning-row">
        <span className="valuation-warning-label">Warnings</span>
        <div className="flex flex-wrap gap-1.5">
          {row.warnings.length ? row.warnings.map((warning) => <span key={warning} className="fund-warning-chip">{warning}</span>) : <span className="text-xs text-muted-foreground">No warnings.</span>}
        </div>
      </div>
    </section>
  )
}

function ValuationMethodRows({
  rows,
  detail,
  selectedRow,
  universeRows,
  selectedComparatorId,
  onSelectedComparatorIdChange,
  excludedModelIds,
  onModelIncludedChange,
  effectiveWeights,
  comparableSummary,
  isComparableSummaryLoading,
  sensitivity,
  assumptionDraft,
  onAssumptionDraftChange,
  onSaveAssumptions,
  isSaving,
}: {
  rows: FundamentalValuationResult[]
  detail: FundamentalStockDetail
  selectedRow: FundamentalUniverseRow | null
  universeRows: FundamentalUniverseRow[]
  selectedComparatorId: string
  onSelectedComparatorIdChange: (id: string) => void
  excludedModelIds: Set<string>
  onModelIncludedChange: (model: string, included: boolean) => void
  effectiveWeights: Map<string, number>
  comparableSummary: ComparableModelSummary
  isComparableSummaryLoading: boolean
  sensitivity?: FundamentalSensitivity
  assumptionDraft: Record<string, number>
  onAssumptionDraftChange: (draft: Record<string, number>) => void
  onSaveAssumptions: () => void
  isSaving: boolean
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const toggle = (key: string) => {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  if (rows.length === 0) {
    return <div className="fund-empty-small">No valuation rows.</div>
  }

  return (
    <div className="valuation-method-table-wrap">
      <table className="claude-table valuation-method-table min-w-[920px]">
        <thead>
          <tr>
            <th className="c">Incl.</th>
            <th>Methode</th>
            <th className="r">FV/result</th>
            <th className="r">Current/input</th>
            <th className="r">Upside/gap</th>
            <th>Conf.</th>
            <th className="r">Poids</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const key = `${row.model}-${row.scenario}`
            const isExpanded = expanded.has(key)
            const isControllable = row.family !== "diagnostic"
            const isIncluded = isControllable && !excludedModelIds.has(row.model)
            const effectiveWeight = isIncluded ? effectiveWeights.get(row.model) ?? null : null
            const effectiveFairValue = fairValueForValuationRow(row, row.model === "relative_multiples" ? comparableSummary : null)
            const effectiveCurrent = currentPriceForValuationRow(row, detail)
            const effectiveUpside = upsideForFairValue(effectiveFairValue, effectiveCurrent) ?? row.upside_pct
            return (
              <Fragment key={key}>
              <tr
                className={cn("valuation-method-summary-row", !isIncluded && isControllable && "excluded")}
                onClick={() => toggle(key)}
                aria-expanded={isExpanded}
              >
                  <td className="c">
                    {isControllable ? (
                      <input
                        aria-label={`Include ${MODEL_LABELS[row.model] ?? row.model}`}
                        className="valuation-include-checkbox"
                        type="checkbox"
                        checked={isIncluded}
                        onClick={(event) => event.stopPropagation()}
                        onChange={(event) => onModelIncludedChange(row.model, event.target.checked)}
                      />
                    ) : (
                      <span className="valuation-model-static">Info</span>
                    )}
                  </td>
                  <td className="font-medium">
                    <span className="inline-flex items-center gap-1.5">
                      {isExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                      {MODEL_LABELS[row.model] ?? row.model}
                    </span>
                  </td>
                  {row.model === "relative_multiples" ? (
                    <ComparableValuationCells
                      currentPrice={row.current_price}
                      summary={comparableSummary}
                      isLoading={isComparableSummaryLoading}
                    />
                  ) : row.model === "reverse_dcf" ? (
                    <ReverseDcfSummaryCells row={row} detail={detail} />
                  ) : (
                    <>
                      <td className="r font-mono">{fmtMoney(effectiveFairValue, 1)}</td>
                      <td className="r font-mono">{fmtMoney(row.current_price, 1)}</td>
                      <td className={cn("r font-mono font-semibold", (effectiveUpside ?? 0) >= 0 ? "t-pos" : "t-neg")}>{fmtPct(effectiveUpside)}</td>
                    </>
                  )}
                  <td>
                    <span className={cn("signal-conf-badge", confidenceClass(row.confidence))}>
                    {row.confidence}
                    {row.is_proxy ? " proxy" : ""}
                  </span>
                </td>
                <td className="r font-mono">{!isControllable ? "-" : !isIncluded ? "Exclu" : effectiveWeight == null ? "No FV" : `${(effectiveWeight * 100).toFixed(0)}%`}</td>
              </tr>
              {isExpanded ? (
                <tr className="valuation-method-expanded-row">
                  <td colSpan={7} className="valuation-expanded-cell">
                    <ValuationMethodCard
                      row={row}
                      detail={detail}
                      selectedRow={selectedRow}
                      universeRows={universeRows}
                      selectedComparatorId={selectedComparatorId}
                      onSelectedComparatorIdChange={onSelectedComparatorIdChange}
                      comparableSummary={comparableSummary}
                      isComparableSummaryLoading={isComparableSummaryLoading}
                      isIncluded={isIncluded}
                      effectiveWeight={effectiveWeight}
                      sensitivity={sensitivity}
                      assumptionDraft={assumptionDraft}
                      onAssumptionDraftChange={onAssumptionDraftChange}
                      onSaveAssumptions={onSaveAssumptions}
                      isSaving={isSaving}
                    />
                  </td>
                </tr>
              ) : null}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function SensitivityMatrix({ grid, assumptions }: { grid: SensitivityGridView; assumptions: Record<string, unknown> }) {
  const values = grid.matrix.flat().filter((value): value is number => value != null && Number.isFinite(value))
  const min = values.length ? Math.min(...values) : 0
  const max = values.length ? Math.max(...values) : 1
  const baseX = asNumber(assumptions[grid.axis_x])
  const baseY = asNumber(assumptions[grid.axis_y])
  const closestX = baseX == null ? -1 : grid.xs.reduce((best, value, index) => (Math.abs(value - baseX) < Math.abs(grid.xs[best] - baseX) ? index : best), 0)
  const closestY = baseY == null ? -1 : grid.ys.reduce((best, value, index) => (Math.abs(value - baseY) < Math.abs(grid.ys[best] - baseY) ? index : best), 0)

  return (
    <div className="overflow-x-auto">
      <table className="claude-table min-w-[560px]">
        <thead>
          <tr>
            <th>{axisDisplayLabel(grid.axis_y)} \ {axisDisplayLabel(grid.axis_x)}</th>
            {grid.xs.map((x) => (
              <th key={x} className="r">{fmtPct(x, 1, false)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {grid.ys.map((y, rowIndex) => (
            <tr key={y}>
              <td className="font-mono font-semibold">{fmtPct(y, 1, false)}</td>
              {grid.matrix[rowIndex]?.map((value, colIndex) => {
                const pct = value == null || max === min ? 0.5 : (value - min) / (max - min)
                const isBase = rowIndex === closestY && colIndex === closestX
                const bg = isBase ? "oklch(0.94 0.04 260 / 0.55)" : `oklch(${0.55 + pct * 0.18} ${0.04 + pct * 0.14} ${pct >= 0.5 ? 165 : 25} / ${0.08 + pct * 0.30})`
                return (
                  <td key={`${rowIndex}-${colIndex}`} className="r font-mono" style={{ background: bg, color: isBase ? "var(--pri-dim)" : undefined, fontWeight: isBase ? 700 : 500, outline: isBase ? "1.5px solid var(--primary)" : undefined }}>
                    {fmtMoney(value)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SensitivityHeatmap({
  sensitivity,
  grid,
  assumptions,
  isLoading,
  title = "Sensibilite - juste valeur",
}: {
  sensitivity: FundamentalSensitivity | undefined
  grid?: SensitivityGridView | null
  assumptions: Record<string, unknown>
  isLoading: boolean
  title?: string
}) {
  const activeGrid = grid ?? sensitivityGridFromResponse(sensitivity)
  if (isLoading && !activeGrid) {
    return (
      <FundCard title="Sensibilite">
        <div className="grid grid-cols-6 gap-1">
          {Array.from({ length: 36 }).map((_, index) => (
            <Skeleton key={index} className="h-8 w-full" />
          ))}
        </div>
      </FundCard>
    )
  }
  if (!activeGrid) return null
  return (
    <div data-capture="sensitivity">
      <FundCard title={title} aside={`${axisDisplayLabel(activeGrid.axis_y)} x ${axisDisplayLabel(activeGrid.axis_x)}`}>
        <SensitivityMatrix grid={activeGrid} assumptions={assumptions} />
      </FundCard>
    </div>
  )
}

function ModelSensitivityPanel({
  row,
  detail,
  sensitivity,
}: {
  row: FundamentalValuationResult
  detail: FundamentalStockDetail
  sensitivity: FundamentalSensitivity | undefined
}) {
  const grid = modelSensitivityGrid(sensitivity, row)
  if (!grid) return null
  return (
    <div className="model-sensitivity-panel valuation-mini-block">
      <div className="driver-evidence-head">
        <span className="valuation-mini-title">Sensibilite modele - {MODEL_LABELS[row.model] ?? row.model}</span>
        <span>{axisDisplayLabel(grid.axis_y)} x {axisDisplayLabel(grid.axis_x)}</span>
      </div>
      <SensitivityMatrix grid={grid} assumptions={detail.assumptions} />
    </div>
  )
}

function AssumptionStrip({
  detail,
  draft,
  onDraftChange,
  onSave,
  isSaving,
}: {
  detail: FundamentalStockDetail
  draft: Record<string, number>
  onDraftChange: (draft: Record<string, number>) => void
  onSave: () => void
  isSaving: boolean
}) {
  return (
    <FundCard title="Hypotheses cles - DCF" aside="Scenario actif">
      <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        {ASSUMPTION_FIELDS.map(([key, label]) => {
          const value = asNumber(detail.assumptions[key])
          return <StatTile key={key} label={label} value={key.includes("year") ? fmtNumber(value, 0) : fmtPct(value, 1, false)} sub={key} />
        })}
      </div>
      <details className="mt-3">
        <summary className="cursor-pointer text-[11px] font-semibold text-muted-foreground">Modifier les hypotheses</summary>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          {ASSUMPTION_FIELDS.map(([key, label]) => (
            <label key={key} className="space-y-1">
              <span className="text-[10px] font-bold uppercase tracking-[0.08em] text-muted-foreground">{label}</span>
              <Input type="number" step="0.005" value={draft[key] ?? ""} onChange={(event) => onDraftChange({ ...draft, [key]: Number(event.target.value) })} />
            </label>
          ))}
          <div className="flex items-end">
            <Button type="button" size="sm" onClick={onSave} disabled={isSaving}>
              {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              {isSaving ? "Enregistrement" : "Enregistrer"}
            </Button>
          </div>
        </div>
      </details>
    </FundCard>
  )
}

function ModellingMapPanel({ detail }: { detail: FundamentalStockDetail }) {
  const projection = projectionFromDetail(detail)
  const build = costOfCapitalBuildUp(detail)
  const projectionChecks = detail.integrity?.projection_checks ?? []
  const alertChecks = projectionChecks.filter((check) => check.status === "warn" || check.status === "fail")
  const plugValues = (detail.integrity?.projected_statements ?? [])
    .map((statement) => asNumber(asRecord(statement).balance_sheet_plug))
    .filter((value): value is number => value != null)
  const maxPlug = plugValues.length ? Math.max(...plugValues.map((value) => Math.abs(value))) : null
  const modelRows = detail.valuations.filter((row) => row.family !== "diagnostic")
  return (
    <FundCard title="Carte de modelisation" aside="Flux complet">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
        <StatTile label="Inputs" value={`${detail.annual.length} annees`} sub={detail.data_source ?? detail.as_of_date ?? "-"} />
        <StatTile label="Capital" value={fmtPct(asNumber(detail.assumptions.wacc), 2, false)} sub={`beta ${fmtRatio(asNumber(build.beta), 2)}`} />
        <StatTile label="Projection" value={projection ? `${projectedYears(projection).length} ans` : "-"} sub={`${projectionDriverRows(projection ?? { statements: [], drivers: {}, fcff: [], fcfe: [], dividends: [], bookValues: [], growthDecomposition: {}, warnings: [] }).length} drivers`} />
        <StatTile label="Modeles" value={`${modelRows.filter((row) => fairValueForValuationRow(row, null) != null).length}/${modelRows.length}`} sub="fair values" />
        <StatTile label="Ensemble" value={fmtMoney(detail.ensemble?.fair_value_base, 1)} sub={fmtPct(detail.ensemble?.confidence_score, 1, false)} />
        <StatTile label="Integrite" value={alertChecks.length ? `${alertChecks.length} alertes` : "OK"} sub={maxPlug != null ? `plug max ${fmtMoney(maxPlug, 0)}` : "plug -"} tone={alertChecks.length ? "t-neg" : "t-pos"} />
      </div>
      {alertChecks.length ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {alertChecks.slice(0, 8).map((check) => (
            <span key={check.name} className={cn("signal-conf-badge", check.status === "fail" ? "low" : "medium")}>
              {check.name.replace("projection_", "")}: {check.status}
            </span>
          ))}
        </div>
      ) : null}
    </FundCard>
  )
}

function DecisionStrip({ detail }: { detail: FundamentalStockDetail }) {
  const build = costOfCapitalBuildUp(detail)
  const riskFree = asNumber(detail.assumptions.risk_free_rate)
  const baseErp = asNumber(build.base_equity_risk_premium) ?? asNumber(detail.assumptions.equity_risk_premium) ?? 0
  const countryRiskPremium = asNumber(build.country_risk_premium) ?? asNumber(detail.assumptions.country_risk_premium) ?? 0
  const scenarioErpAddon = asNumber(build.scenario_erp_addon) ?? asNumber(detail.assumptions.scenario_erp_addon) ?? 0
  const erp = asNumber(build.effective_equity_risk_premium) ?? baseErp + countryRiskPremium + scenarioErpAddon
  const beta = asNumber(build.beta) ?? asNumber(detail.assumptions.beta)
  const betaSource = String(build.beta_source ?? "-")
  const betaR2 = asNumber(build.beta_r2)
  const usesDefaultBeta = betaSource === "default_beta"
  const ke = asNumber(build.cost_of_equity) ?? asNumber(detail.assumptions.cost_of_equity)
  const wacc = asNumber(build.wacc) ?? asNumber(detail.assumptions.wacc)
  const g = asNumber(detail.assumptions.terminal_growth_firm) ?? asNumber(detail.assumptions.terminal_growth)
  const spread = wacc != null && g != null ? wacc - g : null
  return (
    <FundCard title="Hypotheses cles" aside="Scenario actif">
      <div className="grid gap-3 md:grid-cols-4 xl:grid-cols-7">
        <StatTile label="Taux sans risque" value={fmtPct(riskFree, 2, false)} sub="rf - input marche" />
        <StatTile label="Prime de risque" value={fmtPct(erp, 2, false)} sub={`ERP + pays ${fmtPct(countryRiskPremium, 2, false)}`} />
        <StatTile label="Beta" value={fmtRatio(beta, 2)} sub={usesDefaultBeta ? "defaut 1.0" : betaR2 != null ? `${betaSource} R2 ${fmtNumber(betaR2, 2)}` : betaSource} tone={usesDefaultBeta ? "t-neg" : undefined} />
        <StatTile label="Cout equity" value={fmtPct(ke, 2, false)} sub="Ke (CAPM)" />
        <StatTile label="WACC" value={fmtPct(wacc, 2, false)} sub="taux d'actualisation" />
        <StatTile label="Croissance terminale" value={fmtPct(g, 2, false)} sub="g (perpetuite)" />
        <StatTile label="Spread WACC - g" value={fmtPct(spread, 2, false)} sub="moteur valeur terminale" tone={spread != null && spread < 0.01 ? "t-neg" : undefined} />
      </div>
    </FundCard>
  )
}

function AssumptionsTab({
  detail,
  scenario,
  methodology,
  draft,
  onDraftChange,
  onSaveSymbol,
  onSaveDesk,
  isSaving,
  isDeskSaving,
}: {
  detail: FundamentalStockDetail
  scenario: Scenario
  methodology?: FundamentalMethodology
  draft: Record<string, number>
  onDraftChange: (draft: Record<string, number>) => void
  onSaveSymbol: () => void
  onSaveDesk: () => void
  isSaving: boolean
  isDeskSaving: boolean
}) {
  const provenance = asRecord(detail.assumption_provenance?.[scenario])
  const registry = methodology?.assumptions ?? {}
  const entries = Object.entries(registry).sort(([keyA, metaA], [keyB, metaB]) => {
    const group = String(metaA.group ?? "").localeCompare(String(metaB.group ?? ""))
    return group || String(metaA.label ?? keyA).localeCompare(String(metaB.label ?? keyB))
  })
  const sectionDefs = useMemo(() => {
    const entryByKey = new Map(entries)
    const rowsForKeys = (keys: string[]) => keys.map((key) => entryByKey.get(key) ? [key, entryByKey.get(key)!] as (typeof entries)[number] : null).filter((row): row is (typeof entries)[number] => row != null)
    const rowsForGroups = (groups: string[]) => entries.filter(([, meta]) => groups.includes(String(meta.group ?? "general")))
    const emptyRows: typeof entries = []
    return [
      { id: "cost_of_capital", label: "Cost of capital", rows: rowsForGroups(["cost_of_capital", "beta"]), advancedRows: emptyRows, model: null as string | null },
      {
        id: "projection",
        label: "Projection",
        rows: rowsForKeys([
          "revenue_growth",
          "ebit_margin",
          "tax_rate",
          "terminal_growth_firm",
          "terminal_growth_equity",
        ]),
        advancedRows: rowsForKeys([
          "capex_pct",
          "working_capital_pct",
          "depreciation_amortization_pct",
          "payout_ratio",
          "terminal_growth",
          "terminal_growth_floor",
          "terminal_growth_discount_buffer",
          "terminal_growth_ceiling_source",
          "forecast_years",
          "growth_cap",
          "mid_year_discounting",
          "mid_year_terminal",
        ]),
        model: null as string | null,
      },
      ...MODEL_ORDER.map((model) => ({
        id: `model:${model}`,
        label: MODEL_LABELS[model] ?? model,
        rows: rowsForKeys(MODEL_FORMULA_META[model]?.assumptionKeys ?? []),
        advancedRows: emptyRows,
        model,
      })),
      { id: "ensemble_weights", label: "Ponderation de l'ensemble", rows: rowsForGroups(["ensemble_weights"]), advancedRows: emptyRows, model: null as string | null },
    ].filter((section) => section.rows.length > 0 || section.advancedRows.length > 0)
  }, [entries])
  const [activeSectionId, setActiveSectionId] = useState(sectionDefs[0]?.id ?? "cost_of_capital")
  const [applyScope, setApplyScope] = useState<"stock" | "desk">("stock")
  const [showAdvanced, setShowAdvanced] = useState(false)
  const activeSection = sectionDefs.find((section) => section.id === activeSectionId) ?? sectionDefs[0]
  const activeFormula = activeSection?.model ? MODEL_FORMULA_META[activeSection.model] : null
  const { data: scenarioAssumptionRows } = useSWR(
    detail.symbol ? ["fundamental-resolved-assumptions", detail.symbol] : null,
    async () => Promise.all(SCENARIOS.map(async (item) => [item, await getFundamentalResolvedAssumptions(detail.symbol, item)] as const)),
  )
  const scenarioAssumptions = new Map(scenarioAssumptionRows ?? [])
  const draftPayload = editableAssumptionDraft(methodology, draft)
  const hasDraftChanges = Object.keys(draftPayload).length > 0
  const activeSavePending = applyScope === "stock" ? isSaving : isDeskSaving

  function saveActiveScope() {
    if (!hasDraftChanges) return
    if (applyScope === "desk") {
      if (window.confirm(`Ceci modifie les hypotheses pour toutes les valeurs du scenario ${scenario}. Continuer ?`)) {
        onSaveDesk()
      }
      return
    }
    onSaveSymbol()
  }

  function setDraftValue(key: string, rawValue: string) {
    const next = { ...draft }
    if (rawValue.trim() === "") delete next[key]
    else {
      const value = Number(rawValue)
      if (Number.isFinite(value)) next[key] = value
    }
    onDraftChange(next)
  }

  function renderAssumptionRow([key, meta]: (typeof entries)[number]) {
    const currentValue = detail.assumptions[key] ?? meta.value
    const editable = meta.editable !== false
    // For ensemble weight keys, show the current auto weight as placeholder so the desk
    // sees what they are overriding. Auto weight is 0 when the model is not in the
    // official ensemble (e.g. not usable for this symbol).
    let inputPlaceholder = fmtAssumptionValue(currentValue, meta.unit)
    if (key.startsWith("ensemble_weight_") && (currentValue == null || currentValue === 0)) {
      const modelName = key.slice("ensemble_weight_".length)
      const autoWeight = (detail.ensemble?.model_weights as Record<string, number> | null | undefined)?.[modelName]
      inputPlaceholder = autoWeight != null && autoWeight > 0
        ? `${(autoWeight * 100).toFixed(1)}% (auto)`
        : "0 (auto)"
    }
    return (
      <tr key={key}>
        <td>
          <div className="font-semibold">{meta.label}</div>
          <div className="font-mono text-[10px] text-muted-foreground">{key}</div>
        </td>
        <td className="font-mono">{fmtAssumptionValue(currentValue, meta.unit)}</td>
        <td>
          <span className="rounded border border-line px-2 py-0.5 text-[10px] font-semibold uppercase text-muted-foreground">
            {String(provenance[key] ?? "default")}
          </span>
        </td>
        <td className="font-mono">{assumptionRangeLabel(meta.plausible_range, meta.unit)}</td>
        <td>{meta.source ?? "-"}</td>
        <td>{meta.derivation ?? "-"}</td>
        <td>
          {editable ? (
            <div className="flex items-center gap-2">
              <Input
                type="number"
                step={meta.unit === "percent" ? "0.0025" : meta.unit === "flag" ? "1" : "0.01"}
                min={meta.unit === "flag" || meta.group === "ensemble_weights" ? 0 : undefined}
                max={meta.unit === "flag" ? 1 : meta.group === "ensemble_weights" ? 1 : undefined}
                value={draft[key] ?? ""}
                placeholder={inputPlaceholder}
                onChange={(event) => setDraftValue(key, event.target.value)}
                className="h-8 w-28"
              />
              {draft[key] != null ? (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    const next = { ...draft }
                    delete next[key]
                    onDraftChange(next)
                  }}
                >
                  Annuler
                </Button>
              ) : null}
            </div>
          ) : (
            <span className="text-[11px] text-muted-foreground">Calcule</span>
          )}
        </td>
      </tr>
    )
  }

  return (
    <div className="fund-gap">
      <ModellingMapPanel detail={detail} />

      <DecisionStrip detail={detail} />

      <details>
        <summary className="cursor-pointer text-[11px] font-semibold text-muted-foreground">Comparer les scenarios (bas / base / haut)</summary>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          {SCENARIOS.map((item) => {
            const resolved = scenarioAssumptions.get(item)
            const assumptions = (resolved?.assumptions ?? (item === scenario ? detail.assumptions : {})) as Record<string, unknown>
            return (
              <div key={item} className={cn("rounded-md border border-line bg-bg p-3", item === scenario && "border-primary/40 bg-bg2")}>
                <div className="mb-2 text-[11px] font-bold uppercase text-muted-foreground">{item}</div>
                <div className="grid grid-cols-3 gap-2">
                  <StatTile label="WACC" value={fmtPct(asNumber(assumptions.wacc), 2, false)} />
                  <StatTile label="g firm" value={fmtPct(asNumber(assumptions.terminal_growth_firm ?? assumptions.terminal_growth), 2, false)} />
                  <StatTile label="g equity" value={fmtPct(asNumber(assumptions.terminal_growth_equity ?? assumptions.terminal_growth), 2, false)} />
                </div>
              </div>
            )
          })}
        </div>
      </details>

      <CostOfCapitalBuildUp detail={detail} />

      <FundCard title="Registre des hypotheses" aside={`Scenario ${scenario}`}>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="inline-flex rounded-md border border-line bg-bg p-0.5">
            <button
              type="button"
              className={cn("rounded px-3 py-1.5 text-[12px] font-semibold text-muted-foreground", applyScope === "stock" && "bg-bg2 text-fg")}
              onClick={() => setApplyScope("stock")}
            >
              Appliquer au titre
            </button>
            <button
              type="button"
              className={cn("rounded px-3 py-1.5 text-[12px] font-semibold text-muted-foreground", applyScope === "desk" && "bg-bg2 text-fg")}
              onClick={() => setApplyScope("desk")}
            >
              Appliquer au desk
            </button>
          </div>
          <div className="text-[11px] font-semibold uppercase text-muted-foreground">{Object.keys(draftPayload).length} modifs</div>
        </div>
        <div className="grid gap-4 lg:grid-cols-[210px_minmax(0,1fr)]">
          <div className="flex gap-2 overflow-x-auto lg:block lg:overflow-visible">
            {sectionDefs.map((section) => (
              <button
                key={section.id}
                type="button"
                className={cn(
                  "mb-2 whitespace-nowrap rounded-md border border-line px-3 py-2 text-left text-[12px] font-semibold text-muted-foreground lg:block lg:w-full",
                  activeSection?.id === section.id && "border-primary/40 bg-bg2 text-fg",
                )}
                onClick={() => setActiveSectionId(section.id)}
              >
                {section.label}
              </button>
            ))}
          </div>
          <div className="min-w-0">
            {activeFormula ? (
              <div className="mb-3 rounded-md border border-line bg-bg2 p-3 text-sm">
                <div className="font-mono text-[12px] text-fg">{activeFormula.formula}</div>
                {activeFormula.secondaryFormula ? <div className="mt-1 font-mono text-[11px] text-muted-foreground">{activeFormula.secondaryFormula}</div> : null}
                <p className="mt-2 text-[12px] text-muted-foreground">{activeFormula.explanation}</p>
              </div>
            ) : null}
            {activeSectionId === "ensemble_weights" ? (() => {
              const ensembleWarnings = detail.ensemble?.warnings ?? []
              const isUserDefined = ensembleWarnings.includes("ensemble_user_defined_weights")
              const isIcFallback = ensembleWarnings.includes("ic_weight_fallback_no_coverage")
              const modeBadgeLabel = isUserDefined
                ? "Defini par l'utilisateur"
                : isIcFallback
                  ? "Auto (fiabilite)"
                  : "Auto (IC)"
              const modeBadgeClass = isUserDefined
                ? "bg-primary/10 text-primary border-primary/30"
                : "bg-bg2 text-muted-foreground border-line"
              const ensembleWeightDraftKeys = Object.keys(draft).filter(k => k.startsWith("ensemble_weight_"))
              const draftTotal = ensembleWeightDraftKeys.reduce((sum, k) => sum + Math.max(0, draft[k] ?? 0), 0)
              return (
                <div className="mb-3 space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-semibold text-muted-foreground uppercase">Mode actif :</span>
                    <span className={`rounded border px-2 py-0.5 text-[11px] font-semibold ${modeBadgeClass}`}>{modeBadgeLabel}</span>
                  </div>
                  {draftTotal > 0 ? (
                    <div className="rounded-md border border-line bg-bg2 p-2 text-[11px]">
                      <div className="mb-1 font-semibold text-muted-foreground">Apercu normalise (apres enregistrement) :</div>
                      <div className="flex flex-wrap gap-2">
                        {ensembleWeightDraftKeys
                          .filter(k => (draft[k] ?? 0) > 0)
                          .map(k => {
                            const model = k.slice("ensemble_weight_".length)
                            const pct = ((draft[k] ?? 0) / draftTotal * 100).toFixed(1)
                            return (
                              <span key={k} className="font-mono">
                                {MODEL_LABELS[model] ?? model}: <strong>{pct}%</strong>
                              </span>
                            )
                          })}
                      </div>
                    </div>
                  ) : null}
                  <p className="text-[11px] text-muted-foreground">
                    Entrez des poids entre 0 et 1. Laisser a 0 = automatique pour ce modele. Les poids sont renormalises sur les modeles utilisables apres enregistrement.
                  </p>
                </div>
              )
            })() : null}
            <div className="overflow-x-auto">
              <table className="claude-table min-w-[980px]">
                <thead>
                  <tr>
                    <th>Hypothese</th>
                    <th>Valeur</th>
                    <th>Provenance</th>
                    <th>Plage</th>
                    <th>Source</th>
                    <th>Regle</th>
                    <th>Edition</th>
                  </tr>
                </thead>
                <tbody>
                  {activeSection?.rows.length ? activeSection.rows.map(renderAssumptionRow) : (
                    <tr>
                      <td colSpan={7} className="py-8 text-center text-sm text-muted-foreground">Registre indisponible.</td>
                    </tr>
                  )}
                  {activeSection?.advancedRows.length ? (
                    <>
                      <tr>
                        <td colSpan={7} className="bg-bg2/40 py-2">
                          <button
                            type="button"
                            className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground hover:text-fg"
                            onClick={() => setShowAdvanced((value) => !value)}
                          >
                            {showAdvanced ? "Masquer" : "Afficher"} les hypotheses avancees ({activeSection.advancedRows.length})
                          </button>
                        </td>
                      </tr>
                      {showAdvanced ? activeSection.advancedRows.map(renderAssumptionRow) : null}
                    </>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button type="button" size="sm" onClick={saveActiveScope} disabled={!hasDraftChanges || isSaving || isDeskSaving}>
            {activeSavePending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {activeSavePending ? "Enregistrement" : applyScope === "stock" ? "Enregistrer titre" : "Enregistrer desk"}
          </Button>
          {Object.keys(draft).length ? (
            <Button type="button" size="sm" variant="ghost" onClick={() => onDraftChange({})} disabled={isSaving || isDeskSaving}>
              Annuler tout
            </Button>
          ) : null}
        </div>
      </FundCard>
    </div>
  )
}

function ValuationModelControls({
  rows,
  excludedModelIds,
  onModelIncludedChange,
  onIncludeAll,
  onExcludeAll,
  effectiveWeights,
  selectionSummary,
  comparableSummary,
  isComparableSummaryLoading,
  originalTarget,
  currency,
  weightMode,
  onWeightModeChange,
}: {
  rows: FundamentalValuationResult[]
  excludedModelIds: Set<string>
  onModelIncludedChange: (model: string, included: boolean) => void
  onIncludeAll: () => void
  onExcludeAll: () => void
  effectiveWeights: Map<string, number>
  selectionSummary: ValuationSelectionSummary
  comparableSummary: ComparableModelSummary
  isComparableSummaryLoading: boolean
  originalTarget: number | null
  currency: string
  weightMode: WeightMode
  onWeightModeChange: (mode: WeightMode) => void
}) {
  const controllableRows = rows.filter((row) => row.family !== "diagnostic")
  if (!controllableRows.length) return null

  return (
    <div className="valuation-model-controls">
      <div className="valuation-model-controls-head">
        <div>
          <span className="valuation-mini-title">Selection de modeles - cible de travail</span>
          <p className="mt-1 text-[11px] text-muted-foreground">
            La recommandation officielle reste basee sur l'ensemble valide par le backend; cette section sert a analyser une cible alternative.
          </p>
        </div>
        <div className="valuation-model-actions">
          <button type="button" onClick={onIncludeAll}>Tout inclure</button>
          <button type="button" onClick={onExcludeAll}>Tout exclure</button>
          <div className="seg compact">
            <button type="button" className={weightMode === "ic" ? "active" : ""} onClick={() => onWeightModeChange("ic")}>IC</button>
            <button type="button" className={weightMode === "equal" ? "active" : ""} onClick={() => onWeightModeChange("equal")}>Egale</button>
          </div>
        </div>
      </div>

      <div className="valuation-model-summary">
        <StatTile
          label="Cible de travail"
          value={selectionSummary.fairValue != null ? `${fmtMoney(selectionSummary.fairValue, 1)} ${currency}` : "-"}
          sub={originalTarget != null ? `Officielle ${fmtMoney(originalTarget, 1)} ${currency}` : undefined}
        />
        <StatTile
          label="Upside"
          value={fmtPct(selectionSummary.upside)}
          tone={(selectionSummary.upside ?? 0) >= 0 ? "t-pos" : "t-neg"}
        />
        <StatTile
          label="Modeles"
          value={`${selectionSummary.usableCount}/${controllableRows.length}`}
          sub={`${selectionSummary.includedCount} coches`}
        />
        <StatTile
          label="Ponderation"
          value={
            selectionSummary.weightSource === "model weights" ? "IC"
            : selectionSummary.weightSource === "ic fallback" ? "IC (repli egale)"
            : "Egale"
          }
        />
      </div>

      <div className="valuation-model-toggle-grid">
        {controllableRows.map((row) => {
          const isIncluded = !excludedModelIds.has(row.model)
          const fairValue = fairValueForValuationRow(row, row.model === "relative_multiples" ? comparableSummary : null)
          const effectiveWeight = isIncluded ? effectiveWeights.get(row.model) ?? null : null
          const isLoadingValue = row.model === "relative_multiples" && isComparableSummaryLoading && fairValue == null
          return (
            <label key={`${row.model}-${row.scenario}`} className={cn("valuation-model-toggle", isIncluded && "active", fairValue == null && "empty")}>
              <input
                type="checkbox"
                checked={isIncluded}
                onChange={(event) => onModelIncludedChange(row.model, event.target.checked)}
              />
              <span className="valuation-model-toggle-main">
                <strong>{MODEL_LABELS[row.model] ?? row.model}</strong>
                <em>{isLoadingValue ? "..." : fairValue != null ? `${fmtMoney(fairValue, 1)} ${currency}` : "No FV"}</em>
              </span>
              <span className="valuation-model-toggle-weight">
                {!isIncluded ? "Off" : effectiveWeight != null ? `${(effectiveWeight * 100).toFixed(0)}%` : "No FV"}
              </span>
            </label>
          )
        })}
      </div>
      <p className="mt-1 text-[10px] text-muted-foreground">Objectif = mediane des classes de methodes, pas moyenne des modeles.</p>
    </div>
  )
}

function SharedProjectionPanel({ detail }: { detail: FundamentalStockDetail }) {
  const projection = projectionFromDetail(detail)
  if (!projection) return null
  const years = projectedYears(projection)
  const driverRows = projectionDriverRows(projection)
  const statementRows = projectionStatementRows()
  const integrityChecks = detail.integrity?.projection_checks ?? []
  const failingChecks = integrityChecks.filter((check) => check.status === "fail" || check.status === "warn")
  return (
    <FundCard
      title="Projection operationnelle partagee"
      aside={`${years.length} ans explicites - convention mi-annee`}
    >
      <GrowthDecompositionChart projection={projection} />
      <div className="driver-evidence-grid">
        {projectionDriverRows(projection).slice(0, 4).map((row) => (
          <DriverEvidenceChart key={row.key} driver={row.driver} label={row.label} format={row.format} />
        ))}
      </div>

      <div className="projection-panel-grid">
        <div className="projection-table-wrap">
          <div className="valuation-mini-title">Drivers derives</div>
          <table className="claude-table projection-table min-w-[720px]">
            <thead>
              <tr>
                <th>Driver</th>
                {years.map((year) => <th key={year} className="r">{year}</th>)}
                <th>Preuve</th>
              </tr>
            </thead>
            <tbody>
              {driverRows.map((row) => {
                const method = typeof row.driver.method === "string" ? row.driver.method : ""
                const warning = typeof row.driver.warning === "string" ? row.driver.warning : null
                return (
                  <tr key={row.key}>
                    <td className="font-medium">{row.label}</td>
                    {years.map((year) => (
                      <td key={year} className="r font-mono" title={method}>
                        {formatProjectionValue(driverProjectedValue(row.driver, year), row.format)}
                      </td>
                    ))}
                    <td>
                      <span className={cn("signal-conf-badge", warning ? "low" : "high")}>
                        {warning ? "Divergence" : "Historique"}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        <div className="projection-table-wrap">
          <div className="valuation-mini-title">3 etats projetes</div>
          <table className="claude-table projection-table min-w-[760px]">
            <thead>
              <tr>
                <th>Ligne</th>
                {years.map((year) => <th key={year} className="r">{year}</th>)}
              </tr>
            </thead>
            <tbody>
              {statementRows.map((row) => (
                <tr key={row.key}>
                  <td className="font-medium">{row.label}</td>
                  {projection.statements.map((statement, index) => (
                    <td key={`${row.key}-${index}`} className="r font-mono">
                      {formatProjectionValue(projectedValue(statement, row.key), row.format)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="valuation-warning-row">
        <span className="valuation-warning-label">Controles projection</span>
        <div className="flex flex-wrap gap-1.5">
          <span className={cn("signal-conf-badge", failingChecks.length ? "medium" : "high")}>
            {failingChecks.length ? `${failingChecks.length} alertes` : "Tous les liens OK"}
          </span>
          {projection.warnings.map((warning) => <span key={warning} className="fund-warning-chip">{warning}</span>)}
        </div>
      </div>
    </FundCard>
  )
}

function ValuationTab({
  detail,
  row,
  rows,
  selectedComparatorId,
  onSelectedComparatorIdChange,
  onExcludedModelParamChange,
  visibleValuations,
  excludedModelIds,
  comparableSummary,
  isComparableSummaryLoading,
  selectionSummary,
  scenario,
  sensitivity,
  isSensitivityLoading,
  onScenarioChange,
  assumptionDraft,
  onAssumptionDraftChange,
  onSaveAssumptions,
  isSaving,
  weightMode,
  onWeightModeChange,
}: {
  detail: FundamentalStockDetail
  row: FundamentalUniverseRow | null
  rows: FundamentalUniverseRow[]
  selectedComparatorId: string
  onSelectedComparatorIdChange: (id: string) => void
  onExcludedModelParamChange: (value: string | null) => void
  visibleValuations: FundamentalValuationResult[]
  excludedModelIds: Set<string>
  comparableSummary: ComparableModelSummary
  isComparableSummaryLoading: boolean
  selectionSummary: ValuationSelectionSummary
  scenario: Scenario
  sensitivity: FundamentalSensitivity | undefined
  isSensitivityLoading: boolean
  onScenarioChange: (scenario: Scenario) => void
  assumptionDraft: Record<string, number>
  onAssumptionDraftChange: (draft: Record<string, number>) => void
  onSaveAssumptions: () => void
  isSaving: boolean
  weightMode: WeightMode
  onWeightModeChange: (mode: WeightMode) => void
}) {
  const [valuationSubTab, setValuationSubTab] = useState<string>("summary")
  const current = detail.ensemble?.current_price ?? asNumber(detail.metrics.Current_Price)
  const currency = detail.ensemble?.currency ?? "MAD"
  const originalTarget = detail.target_price ?? detail.ensemble?.fair_value_base ?? null
  const methods = useMemo(
    () => valuationMethods(
      detail,
      visibleValuations.filter((valuation) => valuation.family !== "diagnostic" && !excludedModelIds.has(valuation.model)),
      comparableSummary,
      selectionSummary,
    ),
    [comparableSummary, detail, excludedModelIds, selectionSummary, visibleValuations],
  )
  const target = originalTarget ?? selectionSummary.fairValue
  const workingTarget = selectionSummary.fairValue
  const setModelIncluded = useCallback(
    (model: string, included: boolean) => {
      const next = new Set(excludedModelIds)
      if (included) next.delete(model)
      else next.add(model)
      onExcludedModelParamChange(serializeExcludedModelIds(next, visibleValuations))
    },
    [excludedModelIds, onExcludedModelParamChange, visibleValuations],
  )
  const includeAllModels = useCallback(() => onExcludedModelParamChange(null), [onExcludedModelParamChange])
  const excludeAllModels = useCallback(() => {
    onExcludedModelParamChange(serializeExcludedModelIds(new Set(visibleValuations.filter((valuation) => valuation.family !== "diagnostic").map((valuation) => valuation.model)), visibleValuations))
  }, [onExcludedModelParamChange, visibleValuations])
  const subTabRows = useMemo(
    () => sortValuationRows(visibleValuations).filter((valuation) => MODEL_ORDER.includes(valuation.model)),
    [visibleValuations],
  )
  const activeModelRow = valuationSubTab === "summary" ? null : subTabRows.find((valuation) => valuation.model === valuationSubTab) ?? null
  const activeSubTab = valuationSubTab === "summary" || activeModelRow ? valuationSubTab : "summary"
  const activeModelIncluded = activeModelRow ? activeModelRow.family !== "diagnostic" && !excludedModelIds.has(activeModelRow.model) : false
  const activeModelWeight = activeModelRow && activeModelIncluded ? selectionSummary.effectiveWeights.get(activeModelRow.model) ?? null : null

  return (
    <div className="fund-gap">
      <div className="flex flex-wrap items-center gap-2">
        <span className="fund-section-label mb-0">Scenario detail</span>
        <div className="seg">
          {SCENARIOS.map((item) => (
            <button key={item} type="button" className={scenario === item ? "active" : ""} onClick={() => onScenarioChange(item)}>
              {item}
            </button>
          ))}
        </div>
        <span className="ml-auto text-[11px] text-muted-foreground">
          WACC <span className="font-mono text-foreground">{fmtPct(asNumber(detail.assumptions.wacc), 1, false)}</span> - g firm/equity{" "}
          <span className="font-mono text-foreground">
            {fmtPct(asNumber(detail.assumptions.terminal_growth_firm ?? detail.assumptions.terminal_growth), 1, false)} / {fmtPct(asNumber(detail.assumptions.terminal_growth_equity ?? detail.assumptions.terminal_growth), 1, false)}
          </span> - Devise <span className="font-mono text-foreground">{currency}</span>
        </span>
      </div>

      {scenario !== "base" ? (
        <div className="scenario-governance-banner">
          Vous consultez le scenario {scenario} (vue maison) - la recommandation reste ancree au scenario de base.
        </div>
      ) : null}

      <div className="valuation-subtabs">
        <button type="button" className={cn("valuation-subtab", activeSubTab === "summary" && "active")} onClick={() => setValuationSubTab("summary")}>
          Synthese
        </button>
        {subTabRows.map((valuation) => (
          <button key={valuation.model} type="button" className={cn("valuation-subtab", activeSubTab === valuation.model && "active")} onClick={() => setValuationSubTab(valuation.model)}>
            {valuation.model === "relative_multiples" ? "M. relatif" : MODEL_LABELS[valuation.model] ?? valuation.model}
          </button>
        ))}
      </div>

      {activeSubTab === "summary" ? (
        <>
          <div data-capture="valuation-models">
            <FundCard
              title="Football Field - fourchette de valorisation par methode"
              aside={`Cours ${fmtMoney(current, 1)} - Cible officielle ${fmtMoney(target, 1)}${workingTarget != null ? ` - Travail ${fmtMoney(workingTarget, 1)}` : ""}`}
            >
              <ValuationModelControls
                rows={visibleValuations}
                excludedModelIds={excludedModelIds}
                onModelIncludedChange={setModelIncluded}
                onIncludeAll={includeAllModels}
                onExcludeAll={excludeAllModels}
                effectiveWeights={selectionSummary.effectiveWeights}
                selectionSummary={selectionSummary}
                comparableSummary={comparableSummary}
                isComparableSummaryLoading={isComparableSummaryLoading}
                originalTarget={originalTarget}
                currency={currency}
                weightMode={weightMode}
                onWeightModeChange={onWeightModeChange}
              />
              <FootballField methods={methods} currentPrice={current} targetPrice={target} />
            </FundCard>
          </div>

          <div className="grid gap-3 xl:grid-cols-[minmax(0,1.25fr)_minmax(20rem,0.75fr)]">
            <CostOfCapitalBuildUp detail={detail} />
            <CoverageRatingPanel detail={detail} row={row} />
          </div>

          <SharedProjectionPanel detail={detail} />
          <EstimatesTab detail={detail} editable={false} />
          <AssumptionStrip detail={detail} draft={assumptionDraft} onDraftChange={onAssumptionDraftChange} onSave={onSaveAssumptions} isSaving={isSaving} />
          <SensitivityHeatmap sensitivity={sensitivity} assumptions={detail.assumptions} isLoading={isSensitivityLoading} />
        </>
      ) : activeModelRow ? (
        <div className="valuation-method-section">
          <div className="valuation-method-section-header">
            <div>
              <span className="fund-section-label mb-1 block">
                {activeModelRow.model === "relative_multiples" ? "M. relatif" : MODEL_LABELS[activeModelRow.model] ?? activeModelRow.model}
              </span>
              <p>Formule, hypotheses et donnees de reference du modele selectionne.</p>
            </div>
            <span>{activeModelRow.confidence}</span>
          </div>
          <ValuationMethodCard
            row={activeModelRow}
            detail={detail}
            selectedRow={row}
            universeRows={rows}
            selectedComparatorId={selectedComparatorId}
            onSelectedComparatorIdChange={onSelectedComparatorIdChange}
            comparableSummary={comparableSummary}
            isComparableSummaryLoading={isComparableSummaryLoading}
            isIncluded={activeModelIncluded}
            effectiveWeight={activeModelWeight}
            sensitivity={sensitivity}
            assumptionDraft={assumptionDraft}
            onAssumptionDraftChange={onAssumptionDraftChange}
            onSaveAssumptions={onSaveAssumptions}
            isSaving={isSaving}
          />
        </div>
      ) : null}
    </div>
  )
}

function DupontBox({ label, value, sub, result }: { label: string; value: string; sub?: string; result?: boolean }) {
  return (
    <div className={cn("dp-box", result && "result")}>
      <span className="dp-lbl">{label}</span>
      <span className="dp-val">{value}</span>
      {sub ? <span className="dp-peer">{sub}</span> : null}
      <div className="dp-bar-bg">
        <div className="dp-bar-fill" style={{ width: "68%", background: result ? "var(--pri-dim)" : "var(--primary)" }} />
      </div>
    </div>
  )
}

function screenWarnings(screen: Record<string, unknown>): string[] {
  return Array.isArray(screen.warnings) ? screen.warnings.map((warning) => String(warning)) : []
}

function ScreenWarningChips({ warnings }: { warnings: string[] }) {
  if (!warnings.length) return null
  return (
    <div className="mt-3 flex flex-wrap gap-1.5">
      {warnings.map((warning) => (
        <span key={warning} className="fund-warning-chip">{warning}</span>
      ))}
    </div>
  )
}

function ScreenUnavailable({ message, warnings }: { message: string; warnings: string[] }) {
  return (
    <>
      <div className="fund-empty-small">{message}</div>
      <ScreenWarningChips warnings={warnings} />
    </>
  )
}

function asRecordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map((item) => asRecord(item)).filter((item) => Object.keys(item).length > 0) : []
}

function peerScopeLabel(scope: string, cohortSize: number | null, sector: string | null | undefined): string {
  const n = cohortSize != null ? ` (n=${fmtNumber(cohortSize, 0)})` : ""
  if (scope === "sector") return `Secteur${sector ? ` ${sector}` : ""}${n}`
  if (scope === "market") return `Marche${n}`
  return "Echantillon insuffisant"
}

function peerDeviationLabel(zScore: number | null, pctDeviation: number | null): string | null {
  if (zScore != null) return `${zScore > 0 ? "+" : ""}${fmtNumber(zScore, 1)} sigma`
  if (pctDeviation != null) return `${fmtPct(pctDeviation, 0)} vs mediane`
  return null
}

function peerBarColor(score: number | null): string {
  if (score == null) return "var(--muted-foreground)"
  if (score >= 70) return "var(--pos)"
  if (score <= 35) return "var(--neg)"
  return "var(--primary)"
}

function peerValueTone(direction: "pos" | "neg", own: number | null, median: number | null): string {
  if (own == null || median == null) return "text-foreground"
  const favorable = direction === "neg" ? own <= median : own >= median
  return favorable ? "t-pos" : "t-neg"
}

type PeerMetricFormat = "pct" | "x" | "number"
type PeerMetricDirection = "pos" | "neg"
type PeerMetricRow = readonly [label: string, metric: string, format: PeerMetricFormat, direction: PeerMetricDirection]

function formatPeerMetricValue(value: number | null, format: PeerMetricFormat): string {
  if (format === "pct") return fmtPct(asRatio(value), 1, false)
  if (format === "x") return fmtRatio(value, 1)
  return fmtNumber(value, 0)
}

function PeerMetricRows({
  rows,
  metricBreakdown,
  detail,
}: {
  rows: readonly PeerMetricRow[]
  metricBreakdown: Record<string, unknown>
  detail: FundamentalStockDetail
}) {
  return (
    <div className="peer-list peer-list-detail">
      {rows.map(([label, metric, format, direction]) => {
        const entry = asRecord(metricBreakdown[metric])
        const score = recordNumber(entry, "score")
        const scope = String(entry.scope ?? "insufficient")
        const cohortSize = recordNumber(entry, "cohort_size")
        const own = recordNumber(entry, "value") ?? asNumber(detail.metrics[metric])
        const median = recordNumber(entry, "median")
        const insufficient = score == null || scope === "insufficient"
        const percentile = Math.max(0, Math.min(100, score ?? 0))
        const deviation = peerDeviationLabel(recordNumber(entry, "z_score"), recordNumber(entry, "pct_deviation_from_median"))
        const ownText = formatPeerMetricValue(own, format)
        const peerText = formatPeerMetricValue(median, format)
        return (
          <div key={metric} className="peer-row">
            <div className="peer-label">
              <span>{label}</span>
              <span className={cn("peer-scope-badge", scope === "sector" && "peer-scope-badge-sector", insufficient && "peer-scope-badge-muted")}>
                {peerScopeLabel(scope, cohortSize, detail.sector)}
              </span>
            </div>
            <div className="peer-bar-wrap">
              {insufficient ? (
                <div className="peer-bar-empty">{own == null ? "donnee indisponible" : "cohorte trop petite (n<3)"}</div>
              ) : (
                <>
                  <div className="peer-bar">
                    <div className="peer-bar-fill" style={{ width: `${percentile}%`, background: peerBarColor(score) }} />
                    <div className="peer-bar-mark" style={{ left: "50%" }} />
                  </div>
                  <div className="peer-caption">
                    Centile <span className={cn("font-mono font-bold", scoreClass(score))}>{fmtNumber(score, 0)}</span>/100{deviation ? ` - ${deviation}` : ""}
                  </div>
                </>
              )}
            </div>
            <span className="peer-number r">
              <small>Titre</small>
              <strong className={cn("font-mono", peerValueTone(direction, own, median))}>{ownText}</strong>
            </span>
            <span className="peer-number r">
              <small>Mediane</small>
              <strong className="font-mono text-muted-foreground">{peerText}</strong>
            </span>
          </div>
        )
      })}
    </div>
  )
}

const ALTMAN_TERM_DEFS = [
  ["wc_ta", "X1", "Fonds de roulement / Actif total", "liquidite court terme", 6.56],
  ["re_ta", "X2", "Reserves (report a nouveau) / Actif total", "rentabilite cumulee / age", 3.26],
  ["ebit_ta", "X3", "Resultat d'exploitation (EBIT) / Actif total", "productivite operationnelle", 6.72],
  ["equity_tl", "X4", "Capitaux propres comptables / Total des dettes", "solvabilite", 1.05],
] as const

function altmanTermRows(altman: Record<string, unknown>) {
  const payloadTerms = asRecordArray(altman.terms)
  if (payloadTerms.length) {
    return payloadTerms.map((term) => {
      const ratio = recordNumber(term, "ratio")
      const coefficient = recordNumber(term, "coefficient")
      return {
        key: String(term.key ?? term.term ?? ""),
        term: String(term.term ?? term.key ?? ""),
        label: String(term.label ?? term.key ?? ""),
        meaning: String(term.meaning ?? ""),
        ratio,
        coefficient,
        contribution: recordNumber(term, "contribution") ?? (ratio != null && coefficient != null ? ratio * coefficient : null),
      }
    })
  }
  const components = asRecord(altman.components)
  return ALTMAN_TERM_DEFS.map(([key, term, label, meaning, coefficient]) => {
    const ratio = recordNumber(components, key)
    return {
      key,
      term,
      label,
      meaning,
      ratio,
      coefficient,
      contribution: ratio != null ? ratio * coefficient : null,
    }
  })
}

function waccSourceLabel(source: unknown): string {
  if (source === "firm_build_up") return "WACC build-up firme"
  if (source === "assumption") return "WACC hypotheses"
  if (source === "default") return "WACC defaut univers"
  return "WACC source non precisee"
}

function altmanGaugePct(zValue: number | null): number | null {
  if (zValue == null) return null
  const z = Math.max(0, Math.min(3.5, zValue))
  if (z <= 1.1) return (z / 1.1) * 33
  if (z <= 2.6) return 33 + ((z - 1.1) / (2.6 - 1.1)) * 34
  return 67 + ((z - 2.6) / (3.5 - 2.6)) * 33
}

function ZoneGauge({ zValue, zone }: { zValue: number | null; zone: string | null }) {
  const pct = altmanGaugePct(zValue)
  return (
    <div>
      <div className="zone-gauge">
        <span className="danger" />
        <span className="watch" />
        <span className="safe" />
        {pct == null ? null : <i style={{ left: `${pct}%` }} />}
      </div>
      <div className="mt-2 flex justify-between text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        <span>&lt; 1.1</span>
        <span>{zValue == null ? "N/A" : `Z ${fmtNumber(zValue, 2)} - ${zone ?? "zone ?"}`}</span>
        <span>&gt; 2.6</span>
      </div>
    </div>
  )
}

function QualityTab({ detail, row }: { detail: FundamentalStockDetail; row: FundamentalUniverseRow | null }) {
  const diagnostics = detail.diagnostics
  const dupont = asRecord(diagnostics.dupont)
  const metricBreakdown = asRecord(diagnostics.metric_breakdown)
  const qualityComponents = asRecord(detail.scores.quality_components)
  const screens = screensFor(detail, row)
  const altman = screenRecord(screens, "altman_z")
  const evaScreen = screenRecord(screens, "eva")
  const altmanWarnings = screenWarnings(altman)
  const evaWarnings = screenWarnings(evaScreen)
  const altmanZ = recordNumber(altman, "z_value")
  const altmanApplicable = altman.applicable !== false
  const evaApplicable = evaScreen.applicable !== false
  const evaRoic = recordNumber(evaScreen, "roic")
  const evaWacc = recordNumber(evaScreen, "wacc_used")
  const evaSpread = recordNumber(evaScreen, "roic_spread")
  const evaScale = Math.max(0.2, Math.abs(evaRoic ?? 0), Math.abs(evaWacc ?? 0))
  const accrualQuality = asRecord(diagnostics.accrual_quality)
  const altmanTerms = altmanTermRows(altman)
  const altmanContributionSum = altmanTerms.reduce((sum, term) => sum + (term.contribution ?? 0), 0)
  const evaComponents = asRecord(evaScreen.components)
  const evaEbit = recordNumber(evaComponents, "ebit")
  const evaTaxRate = recordNumber(evaComponents, "tax_rate")
  const evaNopat = recordNumber(evaScreen, "nopat")
  const evaDebt = recordNumber(evaComponents, "total_debt")
  const evaBookEquity = recordNumber(evaComponents, "book_equity")
  const evaInvestedCapital = recordNumber(evaScreen, "invested_capital")
  const evaWaccSource = waccSourceLabel(evaScreen.wacc_source)
  const valueScore = asNumber(detail.scores.value) ?? row?.value_score
  const qualityScore = asNumber(detail.scores.quality) ?? row?.quality_score
  const valuePeerRows = [
    ["P/E", "PER", "x", "neg"],
    ["P/B", "Price_to_Book", "x", "neg"],
    ["P/S", "Price_to_Sales", "x", "neg"],
    ["EV/EBITDA", "EV_to_EBITDA", "x", "neg"],
    ["FCF yield", "FCF_Yield", "pct", "pos"],
    ["Div. yield", "Dividend_Yield", "pct", "pos"],
  ] as const satisfies readonly PeerMetricRow[]
  const qualityPeerRows = [
    ["ROE", "ROE", "pct", "pos"],
    ["ROA", "ROA", "pct", "pos"],
    ["Marge oper.", "Operating_Margin", "pct", "pos"],
    ["Marge nette", "Net_Margin", "pct", "pos"],
    ["FCF margin", "FCF_Margin", "pct", "pos"],
    ["Couverture interets", "Interest_Coverage", "x", "pos"],
    ["Dette / equity", "Debt_to_Equity", "x", "neg"],
  ] as const satisfies readonly PeerMetricRow[]

  return (
    <div className="fund-gap" data-capture="scoring">
      <div className="grid gap-3 md:grid-cols-2">
        <StatTile label="Score Value" value={fmtNumber(valueScore, 0)} tone={scoreClass(valueScore)} sub="Cheapness percentile vs peers" />
        <StatTile label="Score Quality" value={fmtNumber(qualityScore, 0)} tone={scoreClass(qualityScore)} sub="Profitability + accounting discipline" />
      </div>

      <FundCard title="Score Value - multiples vs peers" aside={<ScoreChip value={valueScore} />}>
        <div className="quality-card-note">
          Rang centile du titre face a sa cohorte de pairs. Pour les multiples, plus bas = meilleur; pour les yields, plus haut = meilleur. Cohorte = secteur si au moins 3 pairs, sinon marche.
        </div>
        <PeerMetricRows rows={valuePeerRows} metricBreakdown={metricBreakdown} detail={detail} />
      </FundCard>

      <FundCard title="Score Quality - rentabilite, cash et bilan" aside={<ScoreChip value={qualityScore} />}>
        <div className="quality-card-note">
          Score headline = profitabilite relative, discipline comptable et qualite des cash-flows. Levier, liquidite et couverture restent des diagnostics de red flag, pas des piliers separes.
        </div>
        <PeerMetricRows rows={qualityPeerRows} metricBreakdown={metricBreakdown} detail={detail} />
        <div className="mt-3 grid gap-3 md:grid-cols-5">
          <StatTile label="Profitabilite" value={fmtNumber(recordNumber(qualityComponents, "raw_percentile"), 0)} tone={scoreClass(recordNumber(qualityComponents, "raw_percentile"))} sub="ROE, ROA, marges" />
          <StatTile label="Discipline" value={fmtNumber(recordNumber(qualityComponents, "accounting_discipline"), 0)} tone={scoreClass(recordNumber(qualityComponents, "accounting_discipline"))} sub="DuPont + Piotroski" />
          <StatTile label="DuPont" value={fmtNumber(recordNumber(qualityComponents, "dupont_bridge") ?? recordNumber(dupont, "score"), 0)} tone={scoreClass(recordNumber(qualityComponents, "dupont_bridge") ?? recordNumber(dupont, "score"))} sub="coherence ROE" />
          <StatTile label="Piotroski" value={fmtNumber(recordNumber(qualityComponents, "piotroski_lite"), 0)} tone={scoreClass(recordNumber(qualityComponents, "piotroski_lite"))} sub="checks fondamentaux" />
          <StatTile label="Accruals" value={fmtNumber(recordNumber(qualityComponents, "accrual_quality") ?? recordNumber(accrualQuality, "score"), 0)} tone={scoreClass(recordNumber(qualityComponents, "accrual_quality") ?? recordNumber(accrualQuality, "score"))} sub={`cash ${fmtRatio(recordNumber(accrualQuality, "cash_conversion"), 2)}`} />
        </div>
      </FundCard>

      <div data-capture="diagnostics">
        <FundCard title={`Decomposition DuPont - ROE ${detail.latest_statement_year ?? ""}`} aside="ROE = marge x rotation x levier">
          <div className="dp-row">
            <DupontBox label="Marge nette" value={fmtPct(recordNumber(dupont, "net_margin"), 1, false)} />
            <span className="dp-op">x</span>
            <DupontBox label="Rotation actifs" value={fmtRatio(recordNumber(dupont, "asset_turnover"), 2)} />
            <span className="dp-op">x</span>
            <DupontBox label="Levier financier" value={fmtRatio(recordNumber(dupont, "equity_multiplier"), 2)} />
            <span className="dp-op">=</span>
            <DupontBox label="ROE composite" value={fmtPct(recordNumber(dupont, "reported_roe"), 1, false)} result />
          </div>
          <div className="mt-3 rounded-md border border-line bg-bg2 px-3 py-2 text-[11px] leading-5 text-muted-foreground">
            <strong className="text-foreground">Lecture :</strong> l'ecart entre ROE reporte et ROE implique mesure la coherence comptable du pont DuPont. Score DuPont: <span className="font-mono text-foreground">{fmtNumber(recordNumber(dupont, "score"), 0)}</span>.
          </div>
        </FundCard>
      </div>

      <FundCard title="Risque de defaut - Altman Z-score" aside={altmanApplicable ? String(altman.zone ?? "N/A") : "Non applicable"}>
        {!altmanApplicable ? (
          <ScreenUnavailable message="Altman Z n'est pas applique aux secteurs financiers." warnings={altmanWarnings} />
        ) : altmanZ == null ? (
          <ScreenUnavailable message="Altman Z indisponible: donnees bilan, EBIT, chiffre d'affaires ou capitalisation manquantes." warnings={altmanWarnings} />
        ) : (
          <>
            <ZoneGauge zValue={altmanZ} zone={typeof altman.zone === "string" ? altman.zone : null} />
            <div className="mt-3 grid gap-3 md:grid-cols-3">
              <StatTile label="Z-score" value={fmtNumber(altmanZ, 2)} sub={String(altman.variant ?? "Altman Z")} />
              <StatTile label="Score" value={fmtNumber(recordNumber(altman, "score"), 0)} sub="0-100 derive de Z, clippe" />
              <StatTile label="Zone" value={String(altman.zone ?? "N/A")} />
            </div>
            <div className="quality-card-note mt-3">
              Score = 25 + (Z - 1,1) / (2,6 - 1,1) x 50, clippe entre 0 et 100. Seuils: Safe &gt; 2,6; zone grise 1,1-2,6; detresse &lt; 1,1. Variante: {String(altman.variant ?? "Z''_EM")}.
            </div>
            <div className="mt-3 overflow-x-auto">
              <table className="claude-table min-w-[560px]">
                <thead>
                  <tr>
                    <th>Terme</th>
                    <th>Ratio</th>
                    <th>Coeff.</th>
                    <th>Contribution</th>
                    <th>Lecture</th>
                  </tr>
                </thead>
                <tbody>
                  {altmanTerms.map((term) => (
                    <tr key={term.key || term.term}>
                      <td>
                        <span className="font-semibold text-foreground">{term.term}</span> {term.label}
                      </td>
                      <td className="r font-mono">{fmtNumber(term.ratio, 3)}</td>
                      <td className="r font-mono">{fmtNumber(term.coefficient, 2)}</td>
                      <td className="r font-mono">{fmtNumber(term.contribution, 3)}</td>
                      <td>{term.meaning}</td>
                    </tr>
                  ))}
                  <tr>
                    <td className="font-semibold text-foreground">Somme des contributions = Z</td>
                    <td />
                    <td />
                    <td className="r font-mono font-bold">{fmtNumber(altmanContributionSum, 3)}</td>
                    <td className="font-mono text-muted-foreground">Z publie: {fmtNumber(altmanZ, 3)}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div className="quality-methodology">{String(altman.methodology ?? "Altman Z'' emerging-market: 6.56 X1 + 3.26 X2 + 6.72 X3 + 1.05 X4.")}</div>
            <ScreenWarningChips warnings={altmanWarnings} />
          </>
        )}
      </FundCard>

      <FundCard title="Creation de valeur - ROIC vs WACC" aside={!evaApplicable ? "Non applicable" : fmtPct(evaSpread, 2)}>
        {!evaApplicable ? (
          <ScreenUnavailable message="EVA n'est pas applique aux secteurs financiers." warnings={evaWarnings} />
        ) : evaRoic == null || evaWacc == null ? (
          <ScreenUnavailable message="EVA indisponible: EBIT, WACC ou capital investi manquant." warnings={evaWarnings} />
        ) : (
          <div className="space-y-3">
            <div className="quality-card-note">
              La societe {(evaSpread ?? 0) >= 0 ? "cree" : "detruit"} de la valeur quand son rendement sur capital investi (ROIC) {(evaSpread ?? 0) >= 0 ? "depasse" : "reste sous"} son cout du capital (WACC).
            </div>
            <div className="eva-compare">
              {[
                ["ROIC", evaRoic, "var(--pos)"],
                ["WACC", evaWacc, "var(--primary)"],
              ].map(([label, value, color]) => (
                <div key={label as string} className="eva-row">
                  <span>{label}</span>
                  <div className="peer-bar">
                    <div className="peer-bar-fill" style={{ width: `${Math.max(0, Math.min(100, (Math.abs(Number(value)) / evaScale) * 100))}%`, background: color as string }} />
                  </div>
                  <span className="font-mono font-bold">{fmtPct(value as number | null, 1, false)}</span>
                </div>
              ))}
              <div className="eva-spread-line">
                <span>Spread ROIC &minus; WACC</span>
                <strong className={cn("font-mono", (evaSpread ?? 0) >= 0 ? "t-pos" : "t-neg")}>{fmtPct(evaSpread, 2)}</strong>
              </div>
            </div>
            <div className="valuation-formula-panel">
              <div className="valuation-formula-eyebrow">Construction ROIC &amp; WACC</div>
              <div className="cost-build-formulas">
                <code>NOPAT = EBIT {fmtMoney(evaEbit, 0)} &times; (1 &minus; IS {fmtPct(evaTaxRate, 1, false)}) = {fmtMoney(evaNopat, 0)}</code>
                <code>Capital investi = dette {fmtMoney(evaDebt, 0)} + capitaux propres {fmtMoney(evaBookEquity, 0)} = {fmtMoney(evaInvestedCapital, 0)}</code>
                <code>ROIC = NOPAT {fmtMoney(evaNopat, 0)} / capital investi {fmtMoney(evaInvestedCapital, 0)} = {fmtPct(evaRoic, 2, false)}</code>
                <code>WACC = {fmtPct(evaWacc, 2, false)} &middot; source : {evaWaccSource}</code>
              </div>
            </div>
            <div className="grid gap-3 md:grid-cols-3">
              <StatTile label="EVA" value={fmtMoney(recordNumber(evaScreen, "eva_value"), 0)} sub="spread x capital" />
              <StatTile label="Marge EVA" value={fmtPct(recordNumber(evaScreen, "eva_margin"), 1, false)} />
              <StatTile label="Capital investi" value={fmtMoney(recordNumber(evaScreen, "invested_capital"), 0)} />
            </div>
            <ScreenWarningChips warnings={evaWarnings} />
          </div>
        )}
      </FundCard>
    </div>
  )
}

function formatEstimate(value: number | null, format: string): string {
  if (format === "pct") return fmtPct(value, 1, false)
  return fmtMoney(value, 0)
}

function estimateDraftPayload(methodology: FundamentalMethodology | undefined, draft: Record<string, number>): Record<string, number> {
  return Object.fromEntries(
    Object.entries(editableAssumptionDraft(methodology, draft)).filter(([key]) => ESTIMATION_ASSUMPTION_KEY_SET.has(key)),
  )
}

function estimationAssumptionRows(detail: FundamentalStockDetail, methodology?: FundamentalMethodology) {
  const registry = methodology?.assumptions ?? {}
  return ESTIMATION_ASSUMPTION_KEYS.map((key) => {
    const meta = registry[key] ?? ESTIMATION_ASSUMPTION_FALLBACK_META[key]
    return {
      key,
      meta,
      currentValue: detail.assumptions[key] ?? meta.value,
      editable: meta.editable !== false,
    }
  })
}

function assumptionInputStep(unit?: string | null): string {
  if (unit === "percent") return "0.0025"
  if (unit === "years" || unit === "count" || unit === "flag") return "1"
  return "0.01"
}

function estimationActualYears(detail: FundamentalStockDetail, firstForecastYear: number | null): number[] {
  const years = [...new Set(
    detail.annual
      .map((row) => asNumber(row.statement_year))
      .filter((year): year is number => year != null && (firstForecastYear == null || year < firstForecastYear)),
  )]
  return years.sort((a, b) => a - b).slice(-3)
}

function annualMetricsForYear(detail: FundamentalStockDetail, year: number): Record<string, number | null> | null {
  return detail.annual.find((row) => row.statement_year === year)?.metrics ?? null
}

function historicalWorkingCapital(detail: FundamentalStockDetail, year: number): number | null {
  const metrics = annualMetricsForYear(detail, year)
  return metrics ? firstAnnualMetric(metrics, WORKING_CAPITAL_HISTORICAL_ALIASES) : null
}

function historicalNopat(detail: FundamentalStockDetail, metrics: Record<string, number | null>): number | null {
  const direct = firstAnnualMetric(metrics, ESTIMATION_HISTORICAL_ALIASES.nopat)
  if (direct != null) return direct
  const ebit = firstAnnualMetric(metrics, ESTIMATION_HISTORICAL_ALIASES.ebit)
  if (ebit == null) return null
  const taxExpense = firstAnnualMetric(metrics, HISTORICAL_TAX_ALIASES)
  const netIncome = firstAnnualMetric(metrics, ESTIMATION_HISTORICAL_ALIASES.net_income)
  if (taxExpense != null && netIncome != null) {
    const pretax = netIncome + Math.abs(taxExpense)
    if (pretax > 0) return ebit * (1 - Math.max(0, Math.min(0.6, Math.abs(taxExpense) / pretax)))
  }
  const assumedTaxRate = asNumber(detail.assumptions.tax_rate) ?? 0.35
  return ebit * (1 - Math.max(0, Math.min(0.6, assumedTaxRate)))
}

function historicalEstimationValue(detail: FundamentalStockDetail, year: number, key: string): number | null {
  const metrics = annualMetricsForYear(detail, year)
  if (!metrics) return null
  if (key === "nopat") return historicalNopat(detail, metrics)
  if (key === "delta_working_capital") {
    const direct = firstAnnualMetric(metrics, ESTIMATION_HISTORICAL_ALIASES.delta_working_capital)
    if (direct != null) return direct
    const current = historicalWorkingCapital(detail, year)
    const previous = historicalWorkingCapital(detail, year - 1)
    return current != null && previous != null ? current - previous : null
  }
  const value = firstAnnualMetric(metrics, ESTIMATION_HISTORICAL_ALIASES[key] ?? [])
  if (value == null) return null
  if (key === "capex" || key === "dividends") return Math.abs(value)
  return value
}

function safeRatio(numerator: number | null, denominator: number | null): number | null {
  return denominator != null && denominator !== 0 && numerator != null ? numerator / denominator : null
}

function historicalDriverValue(detail: FundamentalStockDetail, year: number, key: string): number | null {
  const metrics = annualMetricsForYear(detail, year)
  if (!metrics) return null
  const revenue = historicalEstimationValue(detail, year, "revenue")
  if (key === "revenue_growth") {
    const direct = asRatio(firstAnnualMetric(metrics, HISTORICAL_REVENUE_GROWTH_ALIASES))
    if (direct != null) return direct
    const previousRevenue = historicalEstimationValue(detail, year - 1, "revenue")
    return revenue != null && previousRevenue != null && previousRevenue > 0 ? revenue / previousRevenue - 1 : null
  }
  if (key === "ebit_margin") return safeRatio(historicalEstimationValue(detail, year, "ebit"), revenue)
  if (key === "tax_rate") {
    const direct = asRatio(firstAnnualMetric(metrics, HISTORICAL_TAX_RATE_ALIASES))
    if (direct != null) return direct
    const taxExpense = firstAnnualMetric(metrics, HISTORICAL_TAX_ALIASES)
    const netIncome = historicalEstimationValue(detail, year, "net_income")
    const pretax = taxExpense != null && netIncome != null ? netIncome + Math.abs(taxExpense) : null
    return pretax != null && pretax > 0 && taxExpense != null ? Math.abs(taxExpense) / pretax : null
  }
  if (key === "capex_pct") return safeRatio(historicalEstimationValue(detail, year, "capex"), revenue)
  if (key === "working_capital_pct") return safeRatio(historicalWorkingCapital(detail, year), revenue)
  if (key === "depreciation_amortization_pct") {
    return safeRatio(firstAnnualMetric(metrics, HISTORICAL_DEPRECIATION_AMORTIZATION_ALIASES), revenue)
  }
  if (key === "payout_ratio") {
    const direct = asRatio(firstAnnualMetric(metrics, HISTORICAL_PAYOUT_ALIASES))
    if (direct != null) return direct
    const dividends = historicalEstimationValue(detail, year, "dividends")
    const netIncome = historicalEstimationValue(detail, year, "net_income")
    return netIncome != null && netIncome > 0 && dividends != null ? Math.abs(dividends) / netIncome : null
  }
  return null
}

function driverHistoricalValue(detail: FundamentalStockDetail, row: { key: string; driver: Record<string, unknown> }, year: number): number | null {
  return historicalSeriesFromDriver(row.driver).find((point) => point.year === year)?.value ?? historicalDriverValue(detail, year, row.key)
}

function driverHistoricalVariation(detail: FundamentalStockDetail, row: { key: string; driver: Record<string, unknown> }, actualYears: number[]): number | null {
  const values = actualYears
    .map((year) => driverHistoricalValue(detail, row, year))
    .filter((value): value is number => value != null)
  return values.length >= 2 ? values[values.length - 1] - values[0] : null
}

function formatDriverVariation(value: number | null, format: "pct" | "number"): string {
  if (format === "pct") return fmtPct(value, 1, true)
  if (value == null) return "-"
  return `${value >= 0 ? "+" : ""}${fmtNumber(value, 2)}`
}

function ProjectionAssumptionEditor({
  detail,
  methodology,
  draft,
  onDraftChange,
  onSave,
  isSaving,
}: {
  detail: FundamentalStockDetail
  methodology?: FundamentalMethodology
  draft: Record<string, number>
  onDraftChange: (draft: Record<string, number>) => void
  onSave: () => void
  isSaving: boolean
}) {
  const rows = estimationAssumptionRows(detail, methodology)
  const payload = estimateDraftPayload(methodology, draft)
  const hasChanges = Object.keys(payload).length > 0
  const setDraftValue = (key: string, rawValue: string) => {
    const next = { ...draft }
    if (rawValue.trim() === "") delete next[key]
    else {
      const value = Number(rawValue)
      if (Number.isFinite(value)) next[key] = value
    }
    onDraftChange(next)
  }
  return (
    <FundCard title="Hypotheses de projection" aside={`${Object.keys(payload).length} modifs`}>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        {rows.map(({ key, meta, currentValue, editable }) => (
          <label key={key} className="space-y-1 rounded-md border border-line bg-bg2 p-2">
            <span className="block text-[10px] font-bold uppercase text-muted-foreground">{meta.label}</span>
            <span className="block font-mono text-[12px] text-fg">{fmtAssumptionValue(currentValue, meta.unit)}</span>
            <Input
              type="number"
              step={assumptionInputStep(meta.unit)}
              min={meta.unit === "flag" ? 0 : undefined}
              max={meta.unit === "flag" ? 1 : undefined}
              value={draft[key] ?? ""}
              placeholder={fmtAssumptionValue(currentValue, meta.unit)}
              disabled={!editable || isSaving}
              onChange={(event) => setDraftValue(key, event.target.value)}
              className="h-8"
            />
            <span className="block text-[10px] text-muted-foreground">{assumptionRangeLabel(meta.plausible_range, meta.unit)}</span>
          </label>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button type="button" size="sm" onClick={onSave} disabled={!hasChanges || isSaving}>
          {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          {isSaving ? "Enregistrement" : "Enregistrer"}
        </Button>
        {hasChanges ? (
          <Button type="button" size="sm" variant="ghost" onClick={() => onDraftChange({})} disabled={isSaving}>
            Annuler
          </Button>
        ) : null}
      </div>
    </FundCard>
  )
}

function LegacyEstimateTable({ detail }: { detail: FundamentalStockDetail }) {
  const table = buildFundamentalEstimateTable(detail)
  return (
    <FundCard
      title="P&L detaille - reel + estimations"
      aside={
        <span className="flex gap-2">
          <span className="estimate-chip">Actuel</span>
          <span className="estimate-chip est">Estime</span>
        </span>
      }
    >
      <div className="overflow-x-auto">
        <table className="claude-table min-w-[720px] estimates-table">
          <thead>
            <tr>
              <th>Metrique</th>
              {table.years.map((year) => (
                <th key={year} className={cn("r", year.endsWith("E") && "estimated")}>{year}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row) => (
              <tr key={row.label}>
                <td className="font-semibold">{row.label}</td>
                {row.values.map((value, index) => (
                  <td key={`${row.label}-${index}`} className={cn("r font-mono", table.years[index]?.endsWith("E") && "estimated")}>
                    {formatEstimate(value, row.format)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </FundCard>
  )
}

function EstimatesTab({
  detail,
  methodology,
  draft,
  onDraftChange,
  onSave,
  isSaving,
  editable = true,
}: {
  detail: FundamentalStockDetail
  methodology?: FundamentalMethodology
  draft?: Record<string, number>
  onDraftChange?: (draft: Record<string, number>) => void
  onSave?: () => void
  isSaving?: boolean
  editable?: boolean
}) {
  const projection = projectionFromDetail(detail)
  if (!projection) {
    return (
      <div className="fund-gap">
        {editable && draft && onDraftChange && onSave ? (
          <ProjectionAssumptionEditor detail={detail} methodology={methodology} draft={draft} onDraftChange={onDraftChange} onSave={onSave} isSaving={Boolean(isSaving)} />
        ) : null}
        <LegacyEstimateTable detail={detail} />
      </div>
    )
  }
  const years = projectedYears(projection)
  const actualYears = estimationActualYears(detail, years[0] ?? null)
  const driverRows = projectionDriverRows(projection)
  const statementRows = projectionStatementRows().filter((row) => ESTIMATION_STATEMENT_KEYS.has(row.key))
  return (
    <div className="fund-gap">
      {editable && draft && onDraftChange && onSave ? (
        <ProjectionAssumptionEditor detail={detail} methodology={methodology} draft={draft} onDraftChange={onDraftChange} onSave={onSave} isSaving={Boolean(isSaving)} />
      ) : null}

      <FundCard title="Synthese projection maison" aside={`${years.length} ans explicites`}>
        <div className="grid gap-3 md:grid-cols-4">
          <StatTile label="Horizon" value={fmtNumber(asNumber(detail.assumptions.forecast_years), 0)} sub={years.length ? `${years[0]}-${years[years.length - 1]}` : "-"} />
          <StatTile label="g firm" value={fmtPct(asNumber(detail.assumptions.terminal_growth_firm ?? detail.assumptions.terminal_growth), 2, false)} sub="fade final" />
          <StatTile label="Cap croissance" value={fmtPct(asNumber(detail.assumptions.growth_cap), 2, false)} sub="borne" />
          <StatTile label="Taux IS" value={fmtPct(asNumber(detail.assumptions.tax_rate), 2, false)} sub="NOPAT" />
        </div>
        {projection.warnings.length ? (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {projection.warnings.map((warning) => <span key={warning} className="fund-warning-chip">{warning}</span>)}
          </div>
        ) : null}
      </FundCard>

      <FundCard title="Trajectoire de croissance" aside="Drivers">
        <GrowthDecompositionChart projection={projection} />
        <div className="driver-evidence-grid">
          {driverRows.slice(0, 4).map((row) => (
            <DriverEvidenceChart key={row.key} driver={row.driver} label={row.label} format={row.format} />
          ))}
        </div>
      </FundCard>

      <FundCard title="Drivers par annee" aside="Historique + hypotheses">
        <div className="projection-table-wrap">
          <table className="claude-table projection-table estimates-table min-w-[980px]">
            <thead>
              <tr>
                <th>Driver</th>
                {actualYears.map((year) => <th key={`${year}-actual`} className="r">{year}A</th>)}
                {actualYears.length ? <th className="r">Var. hist.</th> : null}
                {years.map((year) => <th key={year} className="r estimated">{year}E</th>)}
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {driverRows.map((row) => {
                const method = typeof row.driver.method === "string" ? row.driver.method : ""
                const warning = typeof row.driver.warning === "string" ? row.driver.warning : null
                const variation = driverHistoricalVariation(detail, row, actualYears)
                return (
                  <tr key={row.key}>
                    <td className="font-semibold">{row.label}</td>
                    {actualYears.map((year) => (
                      <td key={`${row.key}-${year}-actual`} className="r font-mono" title={method}>
                        {formatProjectionValue(driverHistoricalValue(detail, row, year), row.format)}
                      </td>
                    ))}
                    {actualYears.length ? (
                      <td className="r font-mono font-semibold" title="Variation entre le premier et le dernier point historique affiche">
                        {formatDriverVariation(variation, row.format)}
                      </td>
                    ) : null}
                    {years.map((year) => (
                      <td key={year} className="r font-mono estimated" title={method}>
                        {formatProjectionValue(driverProjectedValue(row.driver, year), row.format)}
                      </td>
                    ))}
                    <td>
                      <span className={cn("signal-conf-badge", warning ? "medium" : "high")}>
                        {warning ? "Alerte" : "Historique"}
                      </span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </FundCard>

      <FundCard
        title="P&L et cash-flow - historique + projection"
        aside={
          <span className="flex gap-2">
            <span className="estimate-chip">Actuel</span>
            <span className="estimate-chip est">Estime</span>
          </span>
        }
      >
        <div className="projection-table-wrap">
          <table className="claude-table projection-table estimates-table min-w-[820px]">
            <thead>
              <tr>
                <th>Ligne</th>
                {actualYears.map((year) => <th key={`${year}-actual`} className="r">{year}A</th>)}
                {years.map((year) => <th key={year} className="r estimated">{year}E</th>)}
              </tr>
            </thead>
            <tbody>
              {statementRows.map((row) => (
                <tr key={row.key}>
                  <td className="font-semibold">{row.label}</td>
                  {actualYears.map((year) => (
                    <td key={`${row.key}-${year}-actual`} className="r font-mono">
                      {formatProjectionValue(historicalEstimationValue(detail, year, row.key), row.format)}
                    </td>
                  ))}
                  {projection.statements.map((statement, index) => (
                    <td key={`${row.key}-${index}`} className="r font-mono estimated">
                      {formatProjectionValue(projectedValue(statement, row.key), row.format)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </FundCard>
    </div>
  )
}

function ScreenSummaryCard({ title, screen, children }: { title: string; screen: Record<string, unknown>; children?: ReactNode }) {
  const score = recordNumber(screen, "score")
  const warnings = Array.isArray(screen.warnings) ? screen.warnings : []
  return (
    <FundCard title={title} aside={<ScoreChip value={score} />}>
      {children}
      {warnings.length ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {warnings.map((warning) => (
            <span key={String(warning)} className="fund-warning-chip">{String(warning)}</span>
          ))}
        </div>
      ) : null}
    </FundCard>
  )
}

function ComparableFairValueTable({
  summary,
  currency,
  currentPrice,
}: {
  summary: ComparableModelSummary
  currency: string
  currentPrice: number | null | undefined
}) {
  if (!summary.peerFairValues.length) return null
  const current = asNumber(currentPrice)
  const totalUpside = summary.fairValue != null && current != null && current > 0
    ? summary.fairValue / current - 1
    : null
  const totalWeight = summary.peerFairValues.reduce((acc, peer) => acc + (peer.weight ?? 0), 0)
  const metricTotals = Object.fromEntries(
    VALUATION_COMPARABLE_METRICS.map((metric) => {
      const weightedRows = summary.peerFairValues
        .map((peer) => ({ value: peer.metricFairValues[metric], weight: peer.weight }))
        .filter((row): row is { value: number; weight: number } => row.value != null && row.weight != null && row.weight > 0)
      const denominator = weightedRows.reduce((acc, row) => acc + row.weight, 0)
      const value = denominator > 0
        ? weightedRows.reduce((acc, row) => acc + row.value * row.weight, 0) / denominator
        : null
      return [metric, value]
    }),
  ) as Record<(typeof VALUATION_COMPARABLE_METRICS)[number], number | null>

  return (
    <div className="comp-fv-panel">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="fund-section-label mb-0">Fair values par comparable - estimes</span>
        <span className="text-[11px] text-muted-foreground">
          Ponderation: {summary.weightSource.replaceAll("_", " ")}
        </span>
      </div>
      <div className="overflow-x-auto rounded-md border border-line">
        <table className="claude-table min-w-[920px] comp-fv-table">
          <thead>
            <tr>
              <th>Ticker</th>
              <th className="r">Poids</th>
              {VALUATION_COMPARABLE_METRICS.map((metric) => (
                <th key={metric} className="r">FV {comparableMetricLabel(metric)} est.</th>
              ))}
              <th className="r">FV comparable</th>
              <th className="r">FV ponderee</th>
              <th className="r">Upside</th>
            </tr>
          </thead>
          <tbody>
            {summary.peerFairValues.map((peer) => (
              <tr key={`fv-${peer.symbol}`}>
                <td className="font-mono font-bold">{peer.symbol}</td>
                <td className="r font-mono">{fmtPct(peer.weight, 1, false)}</td>
                {VALUATION_COMPARABLE_METRICS.map((metric) => (
                  <td key={`${peer.symbol}-${metric}`} className="r font-mono">
                    {peer.metricFairValues[metric] != null ? `${fmtMoney(peer.metricFairValues[metric], 1)} ${currency}` : "-"}
                  </td>
                ))}
                <td className="r font-mono font-semibold">{fmtMoney(peer.fairValue, 1)} {currency}</td>
                <td className="r font-mono">{peer.weightedFairValue != null ? `${fmtMoney(peer.weightedFairValue, 1)} ${currency}` : "-"}</td>
                <td className={cn("r font-mono font-semibold", (peer.upside ?? 0) >= 0 ? "t-pos" : "t-neg")}>{fmtPct(peer.upside)}</td>
              </tr>
            ))}
            <tr className="comp-fv-total">
              <td className="font-semibold">Total pondere des comparables</td>
              <td className="r font-mono font-semibold">{totalWeight > 0 ? fmtPct(totalWeight, 1, false) : "-"}</td>
              {VALUATION_COMPARABLE_METRICS.map((metric) => (
                <td key={`total-${metric}`} className="r font-mono font-semibold">
                  {metricTotals[metric] != null ? `${fmtMoney(metricTotals[metric], 1)} ${currency}` : "-"}
                </td>
              ))}
              <td className="r font-mono font-semibold">{fmtMoney(summary.fairValue, 1)} {currency}</td>
              <td className="r font-mono font-semibold">{fmtMoney(summary.fairValue, 1)} {currency}</td>
              <td className={cn("r font-mono font-semibold", (totalUpside ?? 0) >= 0 ? "t-pos" : "t-neg")}>{fmtPct(totalUpside)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">
        EV/EBITDA est converti en valeur action via EV = multiple x EBITDA, puis dette nette et nombre d'actions.
      </p>
    </div>
  )
}

function ComparableBenchmarkPanel({
  detail,
  row,
  rows,
  selectedComparatorId,
  onSelectedComparatorIdChange,
  embedded = false,
  title = "Comparables - benchmark detaille",
}: {
  detail: FundamentalStockDetail
  row: FundamentalUniverseRow | null
  rows: FundamentalUniverseRow[]
  selectedComparatorId: string
  onSelectedComparatorIdChange: (id: string) => void
  embedded?: boolean
  title?: string
}) {
  const [activeMetric, setActiveMetric] = useState<string>("PER")
  const {
    comparatorChoices,
    selectedComparator,
    comparables,
    comparableSnapshots,
    comparableSnapshotsError,
    isLoading: isComparablesLoading,
  } = useSelectedComparableView(detail, row, rows, selectedComparatorId)

  useEffect(() => {
    if (!comparatorChoices.some((choice) => choice.id === selectedComparatorId)) {
      onSelectedComparatorIdChange("sector")
    }
  }, [comparatorChoices, onSelectedComparatorIdChange, selectedComparatorId])

  const benchmark = comparables.benchmarks[activeMetric]
  const selectedValue = asNumber(comparables.selected_metrics[activeMetric]) ?? asNumber(detail.metrics[activeMetric])
  const primaryBenchmark = benchmark?.weighted_excluding_target ?? benchmark?.weighted_including_target ?? benchmark?.median ?? null
  const gapVsBenchmark = selectedValue != null && primaryBenchmark != null && primaryBenchmark !== 0
    ? selectedValue / primaryBenchmark - 1
    : null
  const comparableFairValue = comparableModelSummary(
    comparables,
    detail.ensemble?.current_price ?? asNumber(detail.metrics.Current_Price),
    enabledRelativeValuationMetrics(detail),
  )
  const currency = detail.ensemble?.currency ?? "MAD"
  const peerRows = comparables.peers
  const warnings = comparableSnapshotsError
    ? [...comparables.warnings, "Snapshots comparables indisponibles; les pairs peuvent etre incomplets."]
    : comparables.warnings
  const activeMetricHistory = useMemo(
    () => annualComparableMetricHistory(detail, activeMetric),
    [activeMetric, detail],
  )
  const showPerColumn = activeMetric !== "PER"
  const tableColumnCount = showPerColumn ? 10 : 9

  const content = (
    <>
      <div className="fund-compare-toolbar">
        <select
          className="fund-compare-select"
          value={selectedComparator.id}
          onChange={(event) => onSelectedComparatorIdChange(event.target.value)}
        >
          {comparatorChoices.map((choice) => (
            <option key={choice.id} value={choice.id}>
              {choice.label}
            </option>
          ))}
        </select>
        <div className="fund-compare-metrics">
          {COMPARABLE_METRICS.map((metric) => (
            <button
              key={metric}
              type="button"
              onClick={() => setActiveMetric(metric)}
              className={cn("fund-compare-metric", activeMetric === metric && "active")}
            >
              {comparableMetricLabel(metric)}
            </button>
          ))}
        </div>
      </div>

      <div className="mb-3 grid gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile label={detail.symbol} value={formatComparableValue(activeMetric, selectedValue)} sub={`${comparableMetricLabel(activeMetric)} estime`} />
        <StatTile
          label="Benchmark"
          value={formatComparableValue(activeMetric, benchmark?.weighted_including_target)}
          sub={comparables.comparator.target_in_comparator ? "incl. titre" : "benchmark"}
        />
        <StatTile
          label="Peer-only"
          value={formatComparableValue(activeMetric, benchmark?.weighted_excluding_target)}
          sub={`${benchmark?.weighted_count ?? 0} valeurs ponderees`}
        />
        <StatTile label="Mediane" value={formatComparableValue(activeMetric, benchmark?.median)} sub={`${benchmark?.eligible_count ?? 0} valeurs eligibles`} />
        <StatTile
          label="FV modele"
          value={`${fmtMoney(comparableFairValue.fairValue, 1)} ${detail.ensemble?.currency ?? "MAD"}`}
          sub={comparableFairValue.peerCount ? `${comparableFairValue.peerCount} comparables` : `${comparableFairValue.count} multiples`}
        />
        <StatTile
          label="Ecart peer-only"
          value={fmtPct(gapVsBenchmark, 1)}
          tone={comparableGapTone(activeMetric, gapVsBenchmark)}
          sub={LOWER_BETTER_COMPARABLE_METRICS.has(activeMetric) ? "plus bas = moins cher" : "plus haut = mieux"}
        />
      </div>

      {activeMetricHistory.length ? (
        <div className="fund-history-strip">
          <span className="fund-history-title">Historique {comparableMetricLabel(activeMetric)}</span>
          <div className="fund-history-items">
            {activeMetricHistory.slice(0, 7).map((item) => (
              <span key={`${activeMetric}-${item.year}`} className="fund-history-item">
                <b>{item.year}</b>
                <i>{formatComparableValue(activeMetric, item.value)}</i>
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {warnings.length ? (
        <div className="mb-3 flex flex-wrap gap-1.5">
          {warnings.map((warning) => (
            <span key={warning} className="fund-warning-chip">{warning}</span>
          ))}
        </div>
      ) : null}

      <div className="overflow-x-auto">
        <table className="claude-table min-w-[900px] comp-table">
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Nom</th>
              <th>Secteur</th>
              {showPerColumn ? <th className="r">PER est.</th> : null}
              <th className="r">{comparableMetricLabel(activeMetric)} est.</th>
              <th className="r">Poids</th>
              <th className="r">Contribution</th>
              <th className="r">Cours</th>
              <th className="r">Base poids</th>
              <th>Qualite</th>
            </tr>
          </thead>
          <tbody>
            {isComparablesLoading && !comparableSnapshots ? (
              <tr>
                <td colSpan={tableColumnCount} className="py-8 text-center text-sm text-muted-foreground">Chargement des comparables...</td>
              </tr>
            ) : peerRows.length === 0 ? (
              <tr>
                <td colSpan={tableColumnCount} className="py-8 text-center text-sm text-muted-foreground">Aucun comparable disponible.</td>
              </tr>
            ) : (
              peerRows.map((peer) => {
                const value = asNumber(peer.metrics[activeMetric])
                const perValue = asNumber(peer.metrics.PER)
                const weight = asNumber(peer.weights[activeMetric])
                const contribution = asNumber(peer.contributions[activeMetric])
                return (
                  <tr key={peer.symbol} className={peer.is_target ? "self" : undefined}>
                    <td className="font-mono font-bold">{peer.symbol}</td>
                    <td>{peer.display_name ?? peer.company_name}</td>
                    <td className="text-muted-foreground">{peer.sector ?? "-"}</td>
                    {showPerColumn ? <td className="r font-mono">{formatComparableValue("PER", perValue)}</td> : null}
                    <td className="r font-mono">{formatComparableValue(activeMetric, value)}</td>
                    <td className="r font-mono">{peer.is_comparator_member ? fmtPct(weight, 1, false) : "-"}</td>
                    <td className="r font-mono">{peer.is_comparator_member ? formatComparableContribution(activeMetric, contribution) : "-"}</td>
                    <td className="r font-mono">{fmtMoney(peer.current_price, 2)}</td>
                    <td className="r font-mono">{fmtCap(peer.market_value)}</td>
                    <td>
                      {peer.warnings.length ? (
                        <div className="flex flex-wrap gap-1">
                          {peer.warnings.slice(0, 2).map((warning) => (
                            <span key={warning} className="fund-warning-chip">{warning}</span>
                          ))}
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground">OK</span>
                      )}
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      <ComparableFairValueTable
        summary={comparableFairValue}
        currency={currency}
        currentPrice={detail.ensemble?.current_price ?? asNumber(detail.metrics.Current_Price)}
      />
    </>
  )

  if (embedded) {
    return (
      <div className="fund-comparable-embedded">
        <div className="fund-comparable-embedded-header">
          <span>{title}</span>
          <em>{comparables.comparator.weight_source.replaceAll("_", " ")}</em>
        </div>
        {content}
      </div>
    )
  }

  return (
    <FundCard title={title} aside={comparables.comparator.weight_source.replaceAll("_", " ")}>
      {content}
    </FundCard>
  )
}

function ComparablesTab({
  detail,
  row,
  rows,
  selectedComparatorId,
  onSelectedComparatorIdChange,
}: {
  detail: FundamentalStockDetail
  row: FundamentalUniverseRow | null
  rows: FundamentalUniverseRow[]
  selectedComparatorId: string
  onSelectedComparatorIdChange: (id: string) => void
}) {
  const screens = screensFor(detail, row)
  const magic = screenRecord(screens, "magic_formula")
  const peg = screenRecord(screens, "peg_garp")
  const regression = screenRecord(screens, "regression_adj")
  const richness = asRecord(regression.regression_richness)

  return (
    <div className="fund-gap">
      <ComparableBenchmarkPanel
        detail={detail}
        row={row}
        rows={rows}
        selectedComparatorId={selectedComparatorId}
        onSelectedComparatorIdChange={onSelectedComparatorIdChange}
      />

      <div className="grid gap-3 xl:grid-cols-2">
        <ScreenSummaryCard title="Magic Formula - Greenblatt" screen={magic}>
          <div className="space-y-2">
            <StatTile label="ROC" value={fmtPct(recordNumber(magic, "roc"), 1, false)} sub={`Rank ${fmtNumber(recordNumber(magic, "roc_rank"), 0)}`} />
            <StatTile label="Earnings yield" value={fmtPct(recordNumber(magic, "earnings_yield"), 1, false)} sub={`Rank ${fmtNumber(recordNumber(magic, "ey_rank"), 0)}`} />
          </div>
        </ScreenSummaryCard>
        <ScreenSummaryCard title="PEG - GARP" screen={peg}>
          <div className="grid gap-3 md:grid-cols-3">
            <StatTile label="PEG" value={fmtNumber(recordNumber(peg, "peg"), 2)} sub={String(peg.zone ?? "-")} />
            <StatTile label="P/E" value={fmtRatio(recordNumber(peg, "per"), 1)} />
            <StatTile label="Growth" value={fmtPct(recordNumber(peg, "growth_used"), 1, false)} />
          </div>
        </ScreenSummaryCard>
      </div>

      <ScreenSummaryCard title="Multiples ajustes par regression" screen={regression}>
        <div className="reg-grid">
          {Object.entries(richness).map(([metric, value]) => {
            const item = asRecord(value)
            const z = recordNumber(item, "richness_z")
            return (
              <div key={metric} className="reg-row">
                <span>{metric}</span>
                <div className="reg-track">
                  <i style={{ width: `${Math.min(50, Math.abs(z ?? 0) * 16)}%`, marginLeft: (z ?? 0) < 0 ? `${50 - Math.min(50, Math.abs(z ?? 0) * 16)}%` : "50%", background: (z ?? 0) <= 0 ? "var(--pos)" : "var(--neg)" }} />
                </div>
                <span className="font-mono">{fmtNumber(z, 2)}z</span>
              </div>
            )
          })}
        </div>
      </ScreenSummaryCard>
    </div>
  )
}

export function SignalFundamentalView({
  selectedSymbol,
  onSelectSymbol,
  searchParams,
  updateSearchParams,
}: SignalFundamentalViewProps) {
  const { mutate: mutateGlobal } = useSWRConfig()
  const scenarioParam = searchParams.get("scenario")
  const scenario = scenarioFromQuery(scenarioParam)
  const apiScenario = scenarioParam ? scenario : "base"
  const activeTab = tabFromQuery(searchParams.get("fund_tab"))
  const selectedHorizon = horizonFromQuery(searchParams.get("fund_horizon"))
  const selectedComparableBenchmarkId = searchParams.get("fund_benchmark") || "sector"
  const excludedValuationModelsParam = searchParams.get("fund_excluded_models")
  const weightModeParam = searchParams.get("fund_weight_mode")
  const weightMode = weightModeFromQuery(weightModeParam)
  const selectedSymbolKey = valuationSymbolKey(selectedSymbol)
  const [valuationExclusionsBySymbol, setValuationExclusionsBySymbol] = useState<Record<string, string>>(() => readValuationExclusionsBySymbol())
  const hydratedExclusionSymbolsRef = useRef(new Set<string>())
  const isFirstSymbolRef = useRef(true)
  const [assumptionDraft, setAssumptionDraft] = useState<Record<string, number>>({})
  const [isSaving, setIsSaving] = useState(false)
  const [isDeskSaving, setIsDeskSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [liquidityFilter, setLiquidityFilter] = useState(true)

  const {
    data: universeRows,
    error: universeError,
    isLoading: isUniverseLoading,
    isValidating: isUniverseValidating,
    mutate: mutateUniverse,
  } = useSWR<FundamentalUniverseRow[]>(["fundamentals-universe", apiScenario], () => getFundamentalUniverse({ scenario: apiScenario }), {
    keepPreviousData: true,
    revalidateOnFocus: false,
    dedupingInterval: 60_000,
  })

  const { data: methodology } = useSWR<FundamentalMethodology>("fundamentals-methodology", getFundamentalMethodology, {
    revalidateOnFocus: false,
    dedupingInterval: 300_000,
  })

  const rows = useMemo(() => (universeRows ?? []).filter(isMasiFundamentalRow), [universeRows])
  const visibleUniverseRows = useMemo(
    () => (liquidityFilter ? rows.filter(isLiquidFundamentalRow) : rows),
    [liquidityFilter, rows],
  )

  // One-directional hydration: URL → storage only on genuine first load / deep-link.
  // Never reverts user actions. Subsequent symbol switches are seeded by handleSelectSymbol.
  useEffect(() => {
    if (!selectedSymbolKey) return
    if (hydratedExclusionSymbolsRef.current.has(selectedSymbolKey)) return
    hydratedExclusionSymbolsRef.current.add(selectedSymbolKey)

    // Only hydrate from URL for the very first symbol (page load with deep-link).
    // For subsequent symbols the URL was already seeded from storage by handleSelectSymbol.
    if (!isFirstSymbolRef.current) return
    isFirstSymbolRef.current = false

    const urlValue = excludedValuationModelsParam?.trim() || null
    if (!urlValue) return

    const storedValue = valuationExclusionsBySymbol[selectedSymbolKey] ?? null
    if (storedValue === urlValue) return

    const next = { ...valuationExclusionsBySymbol, [selectedSymbolKey]: urlValue }
    setValuationExclusionsBySymbol(next)
    writeValuationExclusionsBySymbol(next)
  }, [excludedValuationModelsParam, selectedSymbolKey, valuationExclusionsBySymbol])

  useEffect(() => {
    if (visibleUniverseRows.length === 0) return
    if (!selectedSymbol) {
      onSelectSymbol(visibleUniverseRows[0].symbol)
    }
  }, [onSelectSymbol, selectedSymbol, visibleUniverseRows])

  const selectedRow = useMemo(() => rows.find((row) => row.symbol === selectedSymbol) ?? null, [rows, selectedSymbol])
  const selectedSymbolHiddenByLiquidity = Boolean(
    selectedSymbol &&
      liquidityFilter &&
      rows.some((row) => row.symbol === selectedSymbol) &&
      !visibleUniverseRows.some((row) => row.symbol === selectedSymbol),
  )

  const {
    data: detailRaw,
    error: detailError,
    isLoading: isDetailLoading,
    isValidating: isDetailValidating,
    mutate: mutateDetail,
  } = useSWR<FundamentalStockDetail>(selectedSymbol ? ["fundamental-detail", selectedSymbol, apiScenario] : null, () => getFundamentalStockDetail(selectedSymbol as string, apiScenario), {
    keepPreviousData: true,
    revalidateOnFocus: false,
    dedupingInterval: 60_000,
  })

  const detail = detailRaw?.symbol === selectedSymbol ? detailRaw : null
  const resolvedScenario = scenarioParam ? scenario : scenarioFromQuery(detail?.viewed_scenario ?? detail?.ensemble?.scenario ?? "base")
  const sensitivityScenario = scenarioParam ? scenario : detail ? resolvedScenario : null

  const {
    data: sensitivity,
    isLoading: isSensitivityLoading,
    mutate: mutateSensitivity,
  } = useSWR<FundamentalSensitivity>(
    selectedSymbol && activeTab === "valuation" && sensitivityScenario ? ["fundamental-sensitivity", selectedSymbol, sensitivityScenario] : null,
    () => getFundamentalSensitivity(selectedSymbol as string, sensitivityScenario as Scenario),
    {
      keepPreviousData: true,
      revalidateOnFocus: false,
      dedupingInterval: 60_000,
    },
  )

  const visibleValuations = useMemo(
    () => detail ? sortValuationRows(applyRatioDraftToValuationRows(detail.valuations, detail, assumptionDraft)) : [],
    [assumptionDraft, detail],
  )
  const excludedValuationModelsForSelected = selectedSymbolKey ? valuationExclusionsBySymbol[selectedSymbolKey] ?? null : null
  const excludedValuationModelIds = useMemo(() => parseExcludedModelIds(excludedValuationModelsForSelected), [excludedValuationModelsForSelected])
  const selectedCurrentPrice = detail ? detail.ensemble?.current_price ?? asNumber(detail.metrics.Current_Price) : null
  const {
    comparables: selectedComparableView,
    isLoading: isValuationComparableLoading,
  } = useOptionalSelectedComparableView(detail, selectedRow, rows, selectedComparableBenchmarkId)
  const relativeValuationMetricKeys = useMemo(() => enabledRelativeValuationMetricsForDraft(detail, assumptionDraft), [assumptionDraft, detail])
  const valuationComparableSummary = useMemo<ComparableModelSummary>(
    () => selectedComparableView
      ? comparableModelSummary(selectedComparableView, selectedCurrentPrice, relativeValuationMetricKeys)
      : emptyComparableModelSummary(),
    [relativeValuationMetricKeys, selectedComparableView, selectedCurrentPrice],
  )
  const valuationSelectionSummary = useMemo<ValuationSelectionSummary>(
    () => detail
      ? buildValuationSelectionSummary({
        rows: visibleValuations,
        excludedModelIds: excludedValuationModelIds,
        comparableSummary: valuationComparableSummary,
        currentPrice: selectedCurrentPrice,
        weightMode,
      })
      : {
        fairValue: null,
        low: null,
        high: null,
        upside: null,
        includedCount: 0,
        usableCount: 0,
        weightSource: "ic fallback",
        effectiveWeights: new Map(),
      },
    [detail, excludedValuationModelIds, selectedCurrentPrice, valuationComparableSummary, visibleValuations, weightMode],
  )
  useEffect(() => {
    setAssumptionDraft({})
  }, [detail?.symbol, resolvedScenario])

  function setScenario(next: Scenario) {
    updateSearchParams({ scenario: next })
  }

  function setActiveTab(next: DetailTab) {
    updateSearchParams({ fund_tab: next === "thesis" ? null : next })
  }

  function setWeightMode(next: WeightMode) {
    updateSearchParams({ fund_weight_mode: next === "ic" ? null : next })
  }

  function setFundamentalHorizon(next: FundamentalHorizon) {
    updateSearchParams({ fund_horizon: next === "year" ? null : next })
  }

  const setSelectedComparableBenchmarkId = useCallback(
    (next: string) => {
      updateSearchParams({ fund_benchmark: next === "sector" ? null : next })
    },
    [updateSearchParams],
  )

  const setExcludedValuationModelsParam = useCallback(
    (next: string | null) => {
      if (!selectedSymbolKey) return
      setValuationExclusionsBySymbol((current) => {
        const updated = { ...current }
        if (next) updated[selectedSymbolKey] = next
        else delete updated[selectedSymbolKey]
        writeValuationExclusionsBySymbol(updated)
        return updated
      })
      updateSearchParams({ fund_excluded_models: next })
    },
    [selectedSymbolKey, updateSearchParams],
  )

  function handleSelectSymbol(symbol: string) {
    const nextSymbolKey = valuationSymbolKey(symbol)
    const nextExcludedModels = nextSymbolKey ? valuationExclusionsBySymbol[nextSymbolKey] ?? null : null
    onSelectSymbol(symbol)
    updateSearchParams({ scenario: null, fund_tab: null, fund_excluded_models: nextExcludedModels })
  }

  async function saveAssumptions() {
    if (!selectedSymbol || !detail) return
    const payload = editableAssumptionDraft(methodology, assumptionDraft)
    if (!Object.keys(payload).length) return
    setIsSaving(true)
    setSaveError(null)
    try {
      await updateFundamentalAssumptions(selectedSymbol, resolvedScenario, payload)
      setAssumptionDraft({})
      await Promise.all([mutateDetail(), mutateUniverse(), mutateSensitivity(), mutateGlobal(["fundamental-resolved-assumptions", selectedSymbol])])
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Echec de l'enregistrement des hypotheses")
    } finally {
      setIsSaving(false)
    }
  }

  async function saveDeskAssumptions() {
    const payload = editableAssumptionDraft(methodology, assumptionDraft)
    if (!Object.keys(payload).length) return
    setIsDeskSaving(true)
    setSaveError(null)
    try {
      await updateFundamentalDeskAssumptions(resolvedScenario, payload)
      setAssumptionDraft({})
      await Promise.all([mutateDetail(), mutateUniverse(), mutateSensitivity(), selectedSymbol ? mutateGlobal(["fundamental-resolved-assumptions", selectedSymbol]) : Promise.resolve()])
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Echec de l'enregistrement desk")
    } finally {
      setIsDeskSaving(false)
    }
  }

  const displayError = universeError ?? detailError

  return (
    <ResizablePanelGroup
      direction="horizontal"
      autoSaveId="signals-fundamental-main-layout-v2"
      className="signal-fund-layout max-xl:block max-xl:h-auto"
    >
      <ResizablePanel defaultSize={28} minSize={18} maxSize={45} className="min-w-0 max-xl:!h-auto">
        <UniverseScreen
          rows={visibleUniverseRows}
          totalRows={rows.length}
          liquidityFilter={liquidityFilter}
          selectedSymbol={selectedSymbol}
          isLoading={isUniverseLoading}
          onSelect={handleSelectSymbol}
          onLiquidityFilterChange={setLiquidityFilter}
        />
      </ResizablePanel>

      <ResizableHandle withHandle className="max-xl:hidden" />

      <ResizablePanel defaultSize={72} minSize={45} className="min-w-0 max-xl:!h-auto">
        <section className="signal-fund-detail">
          {displayError ? (
            <div className="m-3 flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{displayError instanceof Error ? displayError.message : "Fundamentals unavailable."}</span>
            </div>
          ) : null}

          {selectedSymbolHiddenByLiquidity ? (
            <div className="m-3 flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{selectedSymbol} is selected but hidden from the left universe by the ADV20 liquidity filter.</span>
            </div>
          ) : null}

          {!selectedSymbol ? (
            <div className="signal-fund-empty">
              <Landmark className="h-10 w-10 opacity-[0.15]" />
              Selectionnez un titre pour afficher la recherche fondamentale.
            </div>
          ) : (
            <ResizablePanelGroup
              direction="vertical"
              autoSaveId="signals-fundamental-detail-layout-v6"
              className="signal-fund-detail-split"
            >
              <ResizablePanel defaultSize={18} minSize={14} maxSize={28} className="min-h-0">
                <div className="signal-fund-ticket-pane">
                  <ResearchTicket
                    row={selectedRow}
                    detail={detail}
                    isRefreshing={isDetailValidating || isUniverseValidating}
                    selectedHorizon={selectedHorizon}
                    onHorizonChange={setFundamentalHorizon}
                  />
                </div>
              </ResizablePanel>

              <ResizableHandle withHandle />

              <ResizablePanel defaultSize={82} minSize={45} className="min-h-0">
                <div className="signal-fund-tab-pane">
                  <div className="signal-fund-tabs">
                    {FUND_TABS.map((item) => (
                      <button key={item.value} type="button" className={cn("signal-fund-tab", activeTab === item.value && "active")} onClick={() => setActiveTab(item.value)}>
                        {item.label}
                      </button>
                    ))}
                  </div>

                  <div className="signal-fund-body">
                    {isDetailLoading && !detail ? (
                      <div className="space-y-3">
                        <Skeleton className="h-28 w-full" />
                        <Skeleton className="h-52 w-full" />
                      </div>
                    ) : !detail ? (
                      <div className="signal-fund-empty">
                        <Landmark className="h-10 w-10 opacity-[0.15]" />
                        No detail available for {selectedSymbol}.
                      </div>
                    ) : (
                      <>
                        {saveError ? <div className="mb-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">{saveError}</div> : null}
                        {activeTab === "thesis" ? <ThesisTab detail={detail} row={selectedRow} /> : null}
                        {activeTab === "valuation" ? (
                          <ValuationTab
                            detail={detail}
                            row={selectedRow}
                            rows={rows}
                            scenario={resolvedScenario}
                            sensitivity={sensitivity}
                            isSensitivityLoading={isSensitivityLoading}
                            onScenarioChange={setScenario}
                            assumptionDraft={assumptionDraft}
                            onAssumptionDraftChange={setAssumptionDraft}
                            onSaveAssumptions={() => void saveAssumptions()}
                            isSaving={isSaving}
                            selectedComparatorId={selectedComparableBenchmarkId}
                            onSelectedComparatorIdChange={setSelectedComparableBenchmarkId}
                            onExcludedModelParamChange={setExcludedValuationModelsParam}
                            visibleValuations={visibleValuations}
                            excludedModelIds={excludedValuationModelIds}
                            comparableSummary={valuationComparableSummary}
                            isComparableSummaryLoading={isValuationComparableLoading}
                            selectionSummary={valuationSelectionSummary}
                            weightMode={weightMode}
                            onWeightModeChange={setWeightMode}
                          />
                        ) : null}
                        {activeTab === "estimates" ? (
                          <EstimatesTab
                            detail={detail}
                            methodology={methodology}
                            draft={assumptionDraft}
                            onDraftChange={setAssumptionDraft}
                            onSave={() => void saveAssumptions()}
                            isSaving={isSaving}
                          />
                        ) : null}
                        {activeTab === "comparables" ? (
                          <ComparablesTab
                            detail={detail}
                            row={selectedRow}
                            rows={rows}
                            selectedComparatorId={selectedComparableBenchmarkId}
                            onSelectedComparatorIdChange={setSelectedComparableBenchmarkId}
                          />
                        ) : null}
                        {activeTab === "assumptions" ? (
                          <AssumptionsTab
                            detail={detail}
                            scenario={resolvedScenario}
                            methodology={methodology}
                            draft={assumptionDraft}
                            onDraftChange={setAssumptionDraft}
                            onSaveSymbol={() => void saveAssumptions()}
                            onSaveDesk={() => void saveDeskAssumptions()}
                            isSaving={isSaving}
                            isDeskSaving={isDeskSaving}
                          />
                        ) : null}
                        {activeTab === "quality" ? <QualityTab detail={detail} row={selectedRow} /> : null}
                      </>
                    )}
                  </div>
                </div>
              </ResizablePanel>
            </ResizablePanelGroup>
          )}
        </section>
      </ResizablePanel>
    </ResizablePanelGroup>
  )
}
