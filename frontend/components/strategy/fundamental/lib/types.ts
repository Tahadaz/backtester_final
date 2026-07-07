import {
  type FundamentalValuationResult,
} from "@/lib/api"

export type Scenario = "bear" | "base" | "bull"


export type DetailTab = "synthese" | "valuation" | "estimates" | "quality" | "strategie"


export type FundamentalHorizon = "quarter" | "semester" | "year"


export type SortKey =
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


export type Recommendation = "BUY" | "ACCUMULATE" | "HOLD" | "REDUCE" | "SELL" | "NR"


export type RecommendationFilter = "all" | Recommendation


export type ValuationMethodRange = {
  key: string
  method: string
  low: number
  mid: number
  high: number
  weight: number | null | undefined
  confidence: string
  row: FundamentalValuationResult | null
}


export type ComparableModelSummary = {
  fairValue: number | null
  upside: number | null
  count: number
  impliedPrices: Array<{ metric: string; fairValue: number; selectedValue: number; benchmark: number }>
  peerCount: number
  weightSource: string
  peerFairValues: ComparablePeerFairValue[]
}


export type ComparablePeerFairValue = {
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


export type ValuationSelectionSummary = {
  fairValue: number | null
  low: number | null
  high: number | null
  upside: number | null
  includedCount: number
  usableCount: number
  effectiveWeights: Map<string, number>
}


export type MultipleRatioDefinition = {
  key: string
  label: string
  bit: number
}


export type DcfMode = "fcff" | "fcfe"


type DcfPvRow = {
  index: number
  cashFlow: number
  growth: number | null
  period: number
  discountFactor: number | null
  pv: number | null
}


export type DcfBridgeStep = {
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


export type DcfAvailableViewModel = {
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


export type DcfViewModel = DcfUnavailableViewModel | DcfAvailableViewModel


export type FinancialStatementTab = "income" | "balance" | "cashflow"


export type FinancialStatementTable = {
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


export type StatementEvidenceGroup = {
  key: FinancialStatementTab
  title: string
  items: StatementEvidenceItem[]
}


export type ModelValueItem = {
  key: string
  label: string
  value: unknown
  source?: string
}


export type ModelStoryMetricFormat = "money" | "pct" | "number" | "ratio"


export type ModelStoryMetric = {
  label: string
  value: unknown
  format?: ModelStoryMetricFormat
  source?: unknown
}


export type ModelStoryTableCell = string | number | null | { value: unknown; format?: ModelStoryMetricFormat; digits?: number }


export type ModelStoryStep = {
  title: string
  description: string
  formula?: string
  metrics?: ModelStoryMetric[]
  table?: {
    columns: string[]
    rows: ModelStoryTableCell[][]
  }
}


export type ModelStory = {
  model: string
  title: string
  summary: string
  steps: ModelStoryStep[]
  checks: Array<{ label: string; ok: boolean }>
}


export type ProjectionView = {
  statements: Record<string, unknown>[]
  drivers: Record<string, Record<string, unknown>>
  fcff: number[]
  fcfe: number[]
  dividends: number[]
  bookValues: number[]
  growthDecomposition: Record<string, unknown>
  warnings: string[]
}


export type SeriesPoint = {
  year: number
  value: number
  kind?: "historical" | "projected" | "consensus"
}


export type SensitivityGridView = {
  axis_x: string
  axis_y: string
  xs: number[]
  ys: number[]
  matrix: Array<Array<number | null>>
  model?: string | null
}


export type ValuationFormulaMeta = {
  formula: string
  secondaryFormula?: string
  explanation: string
  assumptionKeys: string[]
  technicalInputKeys: string[]
  statementKeys: Record<FinancialStatementTab, string[]>
}


export interface SignalFundamentalViewProps {
  selectedSymbol: string | null
  onSelectSymbol: (symbol: string) => void
  searchParams: { get: (name: string) => string | null }
  updateSearchParams: (updates: Record<string, string | null>) => void
}


export type ComparableIndexDefinition = {
  id: string
  name: string
  symbols?: string[]
  component_shares?: Record<string, number>
  components?: Array<{ symbol: string; shares: number }>
  is_weighted_complete?: boolean
}


export type ComparableChoice = {
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


export type ComparableBenchmarkView = {
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


export type ComparablePeerView = {
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


export type ComparableView = {
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
