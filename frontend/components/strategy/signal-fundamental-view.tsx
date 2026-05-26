"use client"

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react"
import type { ReactNode } from "react"
import useSWR from "swr"
import { AlertTriangle, ChevronDown, ChevronRight, Landmark, Loader2, Save, Search } from "lucide-react"
import {
  fetchDashboardIndices,
  getFundamentalSnapshotBatch,
  getFundamentalSensitivity,
  getFundamentalStockDetail,
  getFundamentalUniverse,
  updateFundamentalAssumptions,
  type DashboardCustomIndex,
  type FundamentalLightSnapshot,
  type FundamentalSensitivity,
  type FundamentalStockDetail,
  type FundamentalUniverseRow,
  type FundamentalValuationResult,
} from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { buildFundamentalEstimateTable } from "@/lib/fundamental-estimates-utils.js"
import { buildFinancialStatementTable } from "@/lib/fundamental-statement-utils.js"
import {
  BUILTIN_CUSTOM_DASHBOARD_INDICES,
  BUILTIN_WEIGHTED_MASI_INDEX,
} from "@/lib/builtin-dashboard-indices"
import { cn } from "@/lib/utils"

type Scenario = "bear" | "base" | "bull"
type DetailTab = "thesis" | "valuation" | "quality" | "estimates" | "comparables"
type SortKey =
  | "upside"
  | "overall"
  | "conviction"
  | "market_cap"
  | "magic"
  | "peg"
  | "altman"
  | "eva"
  | "regression"
type Recommendation = "BUY" | "HOLD" | "SELL"
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

type ValuationSelectionSummary = {
  fairValue: number | null
  low: number | null
  high: number | null
  upside: number | null
  includedCount: number
  usableCount: number
  weightSource: "model weights" | "equal weights"
  effectiveWeights: Map<string, number>
}

type ValuationTargetOverride = {
  fairValue: number | null
  upside: number | null
}

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

const FUND_TABS: Array<{ value: DetailTab; label: string }> = [
  { value: "thesis", label: "These" },
  { value: "valuation", label: "Valorisation" },
  { value: "quality", label: "Qualite & ROE" },
  { value: "estimates", label: "Estimations" },
  { value: "comparables", label: "Comparables" },
]

const MODEL_ORDER = ["fcff_dcf", "fcfe_dcf", "ddm", "residual_income", "justified_multiples", "relative_multiples", "reverse_dcf"]
const VALUATION_EXCLUSIONS_STORAGE_KEY = "fundamental_valuation_exclusions_by_symbol"

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
    assumptionKeys: ["wacc", "terminal_growth", "growth", "forecast_years", "growth_cap", "tax_rate"],
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
    assumptionKeys: ["cost_of_equity", "terminal_growth", "growth", "forecast_years", "growth_cap", "tax_rate"],
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
    assumptionKeys: ["cost_of_equity", "terminal_growth", "growth", "stable_payout_ratio", "growth_cap"],
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
    assumptionKeys: ["cost_of_equity", "fade_years", "payout", "stable_payout_ratio"],
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
    assumptionKeys: ["cost_of_equity", "terminal_growth", "growth", "sustainable_growth", "payout", "fade_years"],
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
    assumptionKeys: ["peer_min_count"],
    technicalInputKeys: ["own_multiples", "peer_stats"],
    statementKeys: {
      income: ["revenue", "ebitda", "net_income"],
      balance: ["total_equity", "net_debt"],
      cashflow: ["free_cash_flow"],
    },
  },
  reverse_dcf: {
    formula: "Implied g = WACC - FCF Yield",
    secondaryFormula: "Diagnostic only: compares the market price with the perpetual growth embedded in that price.",
    explanation: "Does not produce a fair value; it explains what growth assumption the current market price already requires.",
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
  market_cap: "Market cap",
  net_debt: "Net debt",
  net_debt_source: "Net debt source",
  own_multiples: "Own multiples",
  payout: "Payout",
  peer_min_count: "Peer minimum",
  peer_stats: "Peer medians",
  roe: "ROE",
  stable_payout_ratio: "Stable payout",
  sustainable_growth: "Sustainable growth",
  tax_rate: "Tax rate",
  terminal_growth: "Terminal growth",
  wacc: "WACC",
}

const ASSUMPTION_FIELDS = [
  ["wacc", "WACC"],
  ["cost_of_equity", "Cout des fonds propres"],
  ["terminal_growth", "Croissance terminale"],
  ["growth_cap", "Cap de croissance"],
  ["tax_rate", "Taux IS"],
  ["stable_payout_ratio", "Payout stable"],
] as const

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
  PER: "PER",
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

function comparableModelSummary(comparables: ComparableView, currentPrice: number | null | undefined): ComparableModelSummary {
  const current = asNumber(currentPrice)
  const impliedPrices: Array<{ metric: string; fairValue: number; selectedValue: number; benchmark: number }> = []
  for (const metric of VALUATION_COMPARABLE_METRICS) {
    const selectedValue = asNumber(comparables.selected_metrics[metric])
    const benchmark = comparables.benchmarks[metric]
    const primaryBenchmark = benchmark?.weighted_excluding_target ?? benchmark?.weighted_including_target ?? benchmark?.median ?? null
    if (current == null || current <= 0 || selectedValue == null || selectedValue <= 0 || primaryBenchmark == null || primaryBenchmark <= 0) {
      continue
    }
    impliedPrices.push({
      metric,
      fairValue: current * primaryBenchmark / selectedValue,
      selectedValue,
      benchmark: primaryBenchmark,
    })
  }
  const peerFairValueSummary = comparablePeerFairValueSummary(comparables, current)
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
): { fairValue: number | null; peerCount: number; weightSource: string; rows: ComparablePeerFairValue[] } {
  if (currentPrice == null || currentPrice <= 0) {
    return { fairValue: null, peerCount: 0, weightSource: "none", rows: [] }
  }

  const rows = comparables.peers
    .filter((peer) => peer.is_comparator_member && !peer.is_target)
    .map((peer) => {
      const metricFairValues: Record<string, number | null> = {}
      for (const metric of VALUATION_COMPARABLE_METRICS) {
        const ownMultiple = asPositiveNumber(comparables.selected_metrics[metric])
        const peerMultiple = asPositiveNumber(peer.metrics[metric])
        metricFairValues[metric] = ownMultiple != null && peerMultiple != null
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

function scenarioFromQuery(value: string | null): Scenario {
  const token = String(value ?? "").trim().toLowerCase()
  return SCENARIOS.includes(token as Scenario) ? (token as Scenario) : "base"
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
  if (sortKey === "overall") return row.overall_score ?? -Infinity
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
  return value ?? "N/R"
}

function RecChip({ value }: { value: Recommendation | null | undefined }) {
  return <span className={cn("fund-rec-chip", recommendationClass(value))}>{recommendationLabel(value)}</span>
}

function ScoreChip({ value }: { value: number | null | undefined }) {
  return <span className={cn("font-mono text-[11px] font-bold", scoreClass(value))}>{fmtNumber(value, 0)}</span>
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
  selectedSymbol,
  isLoading,
  onSelect,
}: {
  rows: FundamentalUniverseRow[]
  selectedSymbol: string | null
  isLoading: boolean
  onSelect: (symbol: string) => void
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

  return (
    <aside className="signal-fund-universe">
      <div className="signal-fund-universe-header">
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs font-bold">Couverture - {rows.length} titres</span>
          <span className="text-[10px] text-muted-foreground">FY {latestYear ?? "-"}</span>
        </div>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
          <Input className="h-7 rounded-md pl-7 text-xs" placeholder="Rechercher un titre..." value={query} onChange={(event) => setQuery(event.target.value)} />
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
            <option value="overall">Score</option>
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
              <th className="r">Score</th>
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
                  No fundamental rows.
                </td>
              </tr>
            ) : (
              filteredRows.map((row) => {
                const active = row.symbol === selectedSymbol
                return (
                  <tr key={row.symbol} className={cn("cursor-pointer", active && "signal-fund-row-active")} onClick={() => onSelect(row.symbol)}>
                    <td>
                      <div className={cn("font-mono text-[11px] font-bold", active && "text-primary")}>{row.symbol}</div>
                      <div className="truncate text-[9px] text-muted-foreground">{row.sector ?? row.display_name ?? "-"}</div>
                    </td>
                    <td className="r">
                      <RecChip value={row.recommendation} />
                    </td>
                    <td className="r">
                      <ScoreChip value={row.overall_score} />
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
  valuationTargetOverride,
}: {
  row: FundamentalUniverseRow | null
  detail: FundamentalStockDetail | null
  isRefreshing: boolean
  valuationTargetOverride?: ValuationTargetOverride
}) {
  const symbol = detail?.symbol ?? row?.symbol ?? "-"
  const companyName = detail?.display_name ?? detail?.company_name ?? row?.display_name ?? row?.company_name ?? "-"
  const sector = detail?.sector ?? row?.sector ?? "No sector"
  const currency = detail?.ensemble?.currency ?? row?.ensemble?.currency ?? "MAD"
  const currentPrice = detail?.ensemble?.current_price ?? asNumber(detail?.metrics?.Current_Price) ?? row?.current_price ?? null
  const targetPrice = valuationTargetOverride !== undefined
    ? valuationTargetOverride.fairValue
    : detail?.target_price ?? row?.target_price ?? detail?.ensemble?.fair_value_base ?? row?.ensemble?.fair_value_base ?? null
  const upside = valuationTargetOverride !== undefined
    ? valuationTargetOverride.upside
    : detail?.ensemble?.upside_pct ?? rowUpside(row)
  const marketCap = asNumber(detail?.metrics?.MarketCap_Calc) ?? row?.market_cap ?? null
  const recommendation = detail?.recommendation ?? row?.recommendation ?? null
  const conviction = detail?.conviction ?? row?.conviction ?? 0
  const asOf = detail?.as_of_date ?? row?.as_of_date ?? detail?.imported_at ?? row?.imported_at
  const revision = detail?.revision_direction ?? row?.revision_direction ?? "="
  const freeFloat = detail?.free_float_pct ?? row?.free_float_pct ?? null

  return (
    <div className="research-ticket">
      <div className="rt-left">
        <div className="rt-name-row">
          <span className="rt-sym">{symbol}</span>
          {isRefreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" /> : null}
          <span className="rt-coname">{companyName}</span>
          <span className="rt-meta">
            <strong>{sector}</strong> - {row?.market_region ?? "Maroc"} - {currency}
          </span>
        </div>
        <div className="rt-prices">
          <div className="rt-price-block">
            <span className="lbl">Cours actuel</span>
            <span className="val">{fmtMoney(currentPrice, 2)}</span>
            <span className="sub">au {formatDate(asOf)}</span>
          </div>
          <div className="rt-price-block">
            <span className="lbl">Objectif 12M</span>
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
            <span className="sub">Free float {freeFloat == null ? "-" : fmtPct(freeFloat, 0, false)}</span>
          </div>
        </div>
      </div>
      <div className="rt-right">
        <div className={cn("rt-rec-card", recommendationClass(recommendation))}>
          <div className="rt-rec-lbl">Recommandation</div>
          <div className={cn("rt-rec-val", recommendationClass(recommendation))}>{recommendationLabel(recommendation)}</div>
          <div className="rt-conviction">
            <span>Conviction</span>
            {[1, 2, 3, 4, 5].map((item) => (
              <span key={item} className={cn("conv-dot", item <= conviction && "on")} />
            ))}
          </div>
        </div>
        <div className="flex justify-between px-1 text-[10px] text-muted-foreground">
          <span>Analyste - {detail?.analyst ?? row?.analyst ?? "Systeme quantitatif"}</span>
          <span>v3 - {formatDate(asOf)}</span>
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
      label: "Bear",
      probability: 0.25,
      price: bear,
      tone: "bear",
      drivers: ["Marge sous pression", "Multiples sectoriels en contraction", "Hausse du cout du capital"],
    },
    {
      key: "base",
      label: "Base",
      probability: 0.55,
      price: base,
      tone: "base",
      drivers: ["Execution conforme aux tendances historiques", "Ponderation multi-modeles active", "Qualite des donnees integree"],
    },
    {
      key: "bull",
      label: "Bull",
      probability: 0.20,
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
  valuationTargetOverride,
}: {
  detail: FundamentalStockDetail
  row: FundamentalUniverseRow | null
  valuationTargetOverride?: ValuationTargetOverride
}) {
  const scenarios = buildScenarios(detail, valuationTargetOverride?.fairValue)
  const expected = scenarios.some((scenario) => scenario.price != null) ? scenarios.reduce((sum, scenario) => sum + (scenario.price ?? 0) * scenario.probability, 0) : null
  const fairValue = valuationTargetOverride !== undefined ? valuationTargetOverride.fairValue : detail.target_price ?? detail.ensemble?.fair_value_base
  const upside = valuationTargetOverride !== undefined ? valuationTargetOverride.upside : detail.ensemble?.upside_pct ?? rowUpside(row)
  const recommendation = detail.recommendation ?? row?.recommendation ?? null
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

      <div>
        <div className="fund-section-label">Scenarios a 12 mois - distribution probabiliste</div>
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
          E[Prix] = <strong className="text-foreground">{fmtMoney(expected, 1)} MAD</strong> - objectif central probabilise
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

function currentPriceForValuationRow(row: FundamentalValuationResult, detail: FundamentalStockDetail): number | null {
  return row.current_price ?? detail.ensemble?.current_price ?? asNumber(detail.metrics.Current_Price)
}

function upsideForFairValue(fairValue: number | null, currentPrice: number | null): number | null {
  return fairValue != null && currentPrice != null && currentPrice > 0 ? fairValue / currentPrice - 1 : null
}

function buildValuationSelectionSummary({
  rows,
  excludedModelIds,
  comparableSummary,
  currentPrice,
}: {
  rows: FundamentalValuationResult[]
  excludedModelIds: Set<string>
  comparableSummary: ComparableModelSummary | null
  currentPrice: number | null
}): ValuationSelectionSummary {
  const includedRows = rows.filter((row) => row.family !== "diagnostic" && !excludedModelIds.has(row.model))
  const usable = includedRows
    .map((row) => {
      const fairValue = fairValueForValuationRow(row, comparableSummary)
      if (fairValue == null || fairValue <= 0) return null
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
  const weighted = usable
    .map((item) => ({ ...item, effectiveWeight: hasModelWeights ? Math.max(0, item.rawWeight ?? 0) : 1 }))
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
      weightSource: hasModelWeights ? "model weights" : "equal weights",
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
    weightSource: hasModelWeights ? "model weights" : "equal weights",
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
    .filter((row) => row.family !== "diagnostic" && fairValueForValuationRow(row, comparableSummary) != null)
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
      method: "Selection ponderee",
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
  return (
    <div className="valuation-method-metrics">
      <StatTile
        label="Fair value"
        value={isLoading && summary.fairValue == null ? "..." : `${fmtMoney(summary.fairValue, 1)} ${detail.ensemble?.currency ?? "MAD"}`}
        sub={summary.peerCount ? `${summary.peerCount} comparables` : `${summary.count} multiples`}
      />
      <StatTile label="Current" value={currentPrice != null ? `${fmtMoney(currentPrice, 1)} ${detail.ensemble?.currency ?? "MAD"}` : "-"} />
      <StatTile label="Upside" value={isLoading && upside == null ? "..." : fmtPct(upside)} tone={(upside ?? 0) >= 0 ? "t-pos" : "t-neg"} />
      <StatTile label="Weight" value={!isIncluded ? "Excluded" : weight == null ? "-" : `${(weight * 100).toFixed(0)}%`} />
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
}) {
  const meta = valuationFormulaMeta(row.model)
  const statementGroups = statementEvidence(detail, row.model)
  const assumptions = valuationAssumptionItems(row, detail)
  const inputs = technicalInputItems(row)
  const outputs = outputItems(row)
  const isUnavailable = row.confidence === "unavailable"
  const isComparablesModel = row.model === "relative_multiples"
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
        <div className="valuation-formula-line">{meta.formula}</div>
        {meta.secondaryFormula ? <div className="valuation-formula-sub">{meta.secondaryFormula}</div> : null}
        <p>{meta.explanation}</p>
      </div>

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
      ) : (
        <div className="valuation-method-grid">
          <ModelValueGrid title="Hypotheses" items={assumptions} empty="No scenario assumptions persisted." />
          <ModelValueGrid title="Inputs modele" items={inputs} empty="No model inputs persisted." />
          <ModelValueGrid title="Outputs calcules" items={outputs} empty="No additional output persisted." />
        </div>
      )}

      <div>
        <div className="valuation-subtitle">Donnees 3 etats utilisees</div>
        <div className="valuation-statement-grid">
          {statementGroups.map((group) => (
            <StatementEvidenceCard key={group.key} group={group} />
          ))}
        </div>
      </div>

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
            <th className="r">Fair value</th>
            <th className="r">Current</th>
            <th className="r">Upside</th>
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

function SensitivityHeatmap({
  sensitivity,
  assumptions,
  isLoading,
}: {
  sensitivity: FundamentalSensitivity | undefined
  assumptions: Record<string, unknown>
  isLoading: boolean
}) {
  if (isLoading && !sensitivity) {
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
  if (!sensitivity) return null
  const values = sensitivity.matrix.flat().filter((value): value is number => value != null && Number.isFinite(value))
  const min = values.length ? Math.min(...values) : 0
  const max = values.length ? Math.max(...values) : 1
  const baseX = asNumber(assumptions.wacc)
  const baseY = asNumber(assumptions.terminal_growth)
  const closestX = baseX == null ? -1 : sensitivity.xs.reduce((best, value, index) => (Math.abs(value - baseX) < Math.abs(sensitivity.xs[best] - baseX) ? index : best), 0)
  const closestY = baseY == null ? -1 : sensitivity.ys.reduce((best, value, index) => (Math.abs(value - baseY) < Math.abs(sensitivity.ys[best] - baseY) ? index : best), 0)

  return (
    <FundCard title="Sensibilite - juste valeur" aside={`${sensitivity.axis_y} x ${sensitivity.axis_x}`}>
      <div className="overflow-x-auto">
        <table className="claude-table min-w-[560px]">
          <thead>
            <tr>
              <th>{sensitivity.axis_y} \ {sensitivity.axis_x}</th>
              {sensitivity.xs.map((x) => (
                <th key={x} className="r">{fmtPct(x, 1, false)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sensitivity.ys.map((y, rowIndex) => (
              <tr key={y}>
                <td className="font-mono font-semibold">{fmtPct(y, 1, false)}</td>
                {sensitivity.matrix[rowIndex]?.map((value, colIndex) => {
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
    </FundCard>
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
              {isSaving ? "Saving" : "Save"}
            </Button>
          </div>
        </div>
      </details>
    </FundCard>
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
}) {
  const controllableRows = rows.filter((row) => row.family !== "diagnostic")
  if (!controllableRows.length) return null

  return (
    <div className="valuation-model-controls">
      <div className="valuation-model-controls-head">
        <div>
          <span className="valuation-mini-title">Modeles inclus dans la cible</span>
        </div>
        <div className="valuation-model-actions">
          <button type="button" onClick={onIncludeAll}>Tout inclure</button>
          <button type="button" onClick={onExcludeAll}>Tout exclure</button>
        </div>
      </div>

      <div className="valuation-model-summary">
        <StatTile
          label="Cible retenue"
          value={selectionSummary.fairValue != null ? `${fmtMoney(selectionSummary.fairValue, 1)} ${currency}` : "-"}
          sub={originalTarget != null ? `Initiale ${fmtMoney(originalTarget, 1)} ${currency}` : undefined}
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
        <StatTile label="Ponderation" value={selectionSummary.weightSource === "model weights" ? "Modele" : "Egale"} />
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
    </div>
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
}) {
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
  const target = selectionSummary.fairValue
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

  return (
    <div className="fund-gap">
      <div className="flex flex-wrap items-center gap-2">
        <span className="fund-section-label mb-0">Scenario</span>
        <div className="seg">
          {SCENARIOS.map((item) => (
            <button key={item} type="button" className={scenario === item ? "active" : ""} onClick={() => onScenarioChange(item)}>
              {item}
            </button>
          ))}
        </div>
        <span className="ml-auto text-[11px] text-muted-foreground">
          WACC <span className="font-mono text-foreground">{fmtPct(asNumber(detail.assumptions.wacc), 1, false)}</span> - g terminal{" "}
          <span className="font-mono text-foreground">{fmtPct(asNumber(detail.assumptions.terminal_growth), 1, false)}</span> - Devise <span className="font-mono text-foreground">{currency}</span>
        </span>
      </div>

      <FundCard title="Football Field - fourchette de valorisation par methode" aside={`Cours ${fmtMoney(current, 1)} - Cible ${fmtMoney(target, 1)}`}>
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
        />
        <FootballField methods={methods} currentPrice={current} targetPrice={target} />
      </FundCard>

      <div className="valuation-method-section">
        <div className="valuation-method-section-header">
          <div>
            <span className="fund-section-label mb-1 block">Detail par methode de valorisation</span>
            <p>Chaque modele explicite sa formule, ses hypotheses et les donnees des trois etats financiers utilisees.</p>
          </div>
          <span>{visibleValuations.length} modeles</span>
        </div>
        <ValuationMethodRows
          rows={visibleValuations}
          detail={detail}
          selectedRow={row}
          universeRows={rows}
          selectedComparatorId={selectedComparatorId}
          onSelectedComparatorIdChange={onSelectedComparatorIdChange}
          excludedModelIds={excludedModelIds}
          onModelIncludedChange={setModelIncluded}
          effectiveWeights={selectionSummary.effectiveWeights}
          comparableSummary={comparableSummary}
          isComparableSummaryLoading={isComparableSummaryLoading}
        />
      </div>

      <AssumptionStrip detail={detail} draft={assumptionDraft} onDraftChange={onAssumptionDraftChange} onSave={onSaveAssumptions} isSaving={isSaving} />
      <SensitivityHeatmap sensitivity={sensitivity} assumptions={detail.assumptions} isLoading={isSensitivityLoading} />
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

function ZoneGauge({ value, zone }: { value: number | null; zone: string | null }) {
  const pct = value == null ? 0 : Math.max(0, Math.min(100, value))
  return (
    <div>
      <div className="zone-gauge">
        <span className="danger" />
        <span className="watch" />
        <span className="safe" />
        <i style={{ left: `${pct}%` }} />
      </div>
      <div className="mt-2 flex justify-between text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        <span>Distress</span>
        <span>{zone ?? "N/A"}</span>
        <span>Safe</span>
      </div>
    </div>
  )
}

function QualityTab({ detail, row }: { detail: FundamentalStockDetail; row: FundamentalUniverseRow | null }) {
  const diagnostics = detail.diagnostics
  const dupont = asRecord(diagnostics.dupont)
  const metricBreakdown = asRecord(diagnostics.metric_breakdown)
  const screens = screensFor(detail, row)
  const altman = screenRecord(screens, "altman_z")
  const evaScreen = screenRecord(screens, "eva")
  const peerRows = [
    ["ROE", "ROE", "pct", "pos"],
    ["Marge oper.", "Operating_Margin", "pct", "pos"],
    ["FCF margin", "FCF_Margin", "pct", "pos"],
    ["Couverture interets", "Interest_Coverage", "x", "pos"],
    ["Dette / equity", "Debt_to_Equity", "x", "neg"],
    ["Accruals", "accrual_quality", "score", "pos"],
  ] as const

  return (
    <div className="fund-gap">
      <div className="grid gap-3 md:grid-cols-4">
        <StatTile label="Score global" value={fmtNumber(asNumber(detail.scores.overall) ?? row?.overall_score, 0)} tone={scoreClass(asNumber(detail.scores.overall) ?? row?.overall_score)} sub="Composite" />
        <StatTile label="Score qualite" value={fmtNumber(asNumber(detail.scores.quality) ?? row?.quality_score, 0)} tone={scoreClass(asNumber(detail.scores.quality) ?? row?.quality_score)} sub="DuPont + discipline" />
        <StatTile label="Score sante" value={fmtNumber(asNumber(detail.scores.health) ?? row?.health_score, 0)} tone={scoreClass(asNumber(detail.scores.health) ?? row?.health_score)} sub="Bilan" />
        <StatTile label="Score croiss." value={fmtNumber(asNumber(detail.scores.growth) ?? row?.growth_score, 0)} tone={scoreClass(asNumber(detail.scores.growth) ?? row?.growth_score)} sub="Trajectoire" />
      </div>

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

      <FundCard title="Indicateurs qualite - comparaison peers">
        <div className="peer-list">
          {peerRows.map(([label, metric, format, direction]) => {
            const entry = asRecord(metricBreakdown[metric])
            const score = recordNumber(entry, "score")
            const own = recordNumber(entry, "value") ?? asNumber(detail.metrics[metric])
            const median = recordNumber(entry, "median")
            const percentile = Math.max(0, Math.min(100, score ?? 50))
            const ownText = format === "pct" ? fmtPct(own, 1, false) : format === "x" ? fmtRatio(own, 1) : fmtNumber(own, 0)
            const peerText = format === "pct" ? fmtPct(median, 1, false) : format === "x" ? fmtRatio(median, 1) : fmtNumber(median, 0)
            return (
              <div key={metric} className="peer-row">
                <span>{label}</span>
                <div className="peer-bar-wrap">
                  <div className="peer-bar">
                    <div className="peer-bar-fill" style={{ width: `${percentile}%`, background: direction === "neg" ? "var(--neg)" : direction === "pos" ? "var(--pos)" : "var(--primary)" }} />
                    <div className="peer-bar-mark" style={{ left: "50%" }} />
                  </div>
                </div>
                <span className={cn("r font-mono text-[11px] font-bold", direction === "neg" ? "t-neg" : "t-pos")}>{ownText}</span>
                <span className="r font-mono text-[10px] text-muted-foreground">{peerText}</span>
              </div>
            )
          })}
        </div>
      </FundCard>

      <FundCard title="Risque de defaut - Altman Z-score" aside={String(altman.zone ?? "N/A")}>
        <ZoneGauge value={recordNumber(altman, "score")} zone={typeof altman.zone === "string" ? altman.zone : null} />
        <div className="mt-3 overflow-x-auto">
          <table className="claude-table">
            <tbody>
              {Object.entries(asRecord(altman.components)).map(([key, value]) => (
                <tr key={key}>
                  <td>{key.replaceAll("_", " ")}</td>
                  <td className="r font-mono">{fmtNumber(asNumber(value), 3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </FundCard>

      <FundCard title="Creation de valeur - ROIC vs WACC" aside={evaScreen.applicable === false ? "Non applicable" : fmtPct(recordNumber(evaScreen, "roic_spread"), 2)}>
        {evaScreen.applicable === false ? (
          <div className="fund-empty-small">EVA n'est pas applique aux secteurs financiers.</div>
        ) : (
          <div className="space-y-3">
            {[
              ["ROIC", recordNumber(evaScreen, "roic"), "var(--pos)"],
              ["WACC", recordNumber(evaScreen, "wacc_used"), "var(--primary)"],
            ].map(([label, value, color]) => (
              <div key={label as string} className="eva-row">
                <span>{label}</span>
                <div className="peer-bar">
                  <div className="peer-bar-fill" style={{ width: `${Math.max(0, Math.min(100, (Number(value) / 0.2) * 100))}%`, background: color as string }} />
                </div>
                <span className="font-mono font-bold">{fmtPct(value as number | null, 1, false)}</span>
              </div>
            ))}
            <div className="grid gap-3 md:grid-cols-3">
              <StatTile label="EVA" value={fmtMoney(recordNumber(evaScreen, "eva_value"), 0)} sub="spread x capital" />
              <StatTile label="Marge EVA" value={fmtPct(recordNumber(evaScreen, "eva_margin"), 1, false)} />
              <StatTile label="Capital investi" value={fmtMoney(recordNumber(evaScreen, "invested_capital"), 0)} />
            </div>
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

function EstimatesTab({ detail }: { detail: FundamentalStockDetail }) {
  const table = buildFundamentalEstimateTable(detail)
  return (
    <div className="fund-gap">
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

      <FundCard title="Consensus marche vs maison" aside={`FY ${table.currentEstimateLabel ?? "-"}`}>
        <table className="claude-table">
          <thead>
            <tr>
              <th>Metrique</th>
              <th className="r">Consensus</th>
              <th className="r">Maison</th>
              <th className="r">Ecart</th>
              <th>Position</th>
            </tr>
          </thead>
          <tbody>
            {table.rows.slice(0, 3).map((row) => {
              const house = table.currentEstimateIndex == null ? null : row.values[table.currentEstimateIndex] ?? null
              return (
                <tr key={row.label}>
                  <td>{row.label}</td>
                  <td className="r text-muted-foreground">N/A</td>
                  <td className="r font-mono font-bold">{formatEstimate(house, row.format)}</td>
                  <td className="r text-muted-foreground">-</td>
                  <td className="text-muted-foreground">Non disponible</td>
                </tr>
              )
            })}
          </tbody>
        </table>
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
  return (
    <div className="comp-fv-panel">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="fund-section-label mb-0">Fair values par comparable - estimes</span>
        <span className="text-[11px] text-muted-foreground">
          Ponderation: {summary.weightSource.replaceAll("_", " ")}
        </span>
      </div>
      <div className="overflow-x-auto rounded-md border border-line">
        <table className="claude-table min-w-[1040px] comp-fv-table">
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Nom</th>
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
                <td>{peer.displayName}</td>
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
              <td colSpan={7} className="font-semibold">Total pondere des comparables</td>
              <td className="r text-muted-foreground">-</td>
              <td className="r font-mono font-semibold">{fmtMoney(summary.fairValue, 1)} {currency}</td>
              <td className={cn("r font-mono font-semibold", (totalUpside ?? 0) >= 0 ? "t-pos" : "t-neg")}>{fmtPct(totalUpside)}</td>
            </tr>
          </tbody>
        </table>
      </div>
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
  )
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
        currency={detail.ensemble?.currency ?? "MAD"}
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
  const scenarioParam = searchParams.get("scenario")
  const scenario = scenarioFromQuery(scenarioParam)
  const apiScenario = scenarioParam ? scenario : "auto"
  const activeTab = tabFromQuery(searchParams.get("fund_tab"))
  const selectedComparableBenchmarkId = searchParams.get("fund_benchmark") || "sector"
  const excludedValuationModelsParam = searchParams.get("fund_excluded_models")
  const selectedSymbolKey = valuationSymbolKey(selectedSymbol)
  const [valuationExclusionsBySymbol, setValuationExclusionsBySymbol] = useState<Record<string, string>>(() => readValuationExclusionsBySymbol())
  const lastSelectedValuationSymbolRef = useRef<string | null>(null)
  const [assumptionDraft, setAssumptionDraft] = useState<Record<string, number>>({})
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

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

  const rows = universeRows ?? []

  useEffect(() => {
    if (!selectedSymbolKey) {
      lastSelectedValuationSymbolRef.current = null
      return
    }

    const previousSymbolKey = lastSelectedValuationSymbolRef.current
    const storedValue = valuationExclusionsBySymbol[selectedSymbolKey] ?? null
    const urlValue = excludedValuationModelsParam?.trim() || null

    if (previousSymbolKey == null && urlValue && storedValue == null) {
      const next = { ...valuationExclusionsBySymbol, [selectedSymbolKey]: urlValue }
      setValuationExclusionsBySymbol(next)
      writeValuationExclusionsBySymbol(next)
      lastSelectedValuationSymbolRef.current = selectedSymbolKey
      return
    }

    lastSelectedValuationSymbolRef.current = selectedSymbolKey
    if (storedValue !== urlValue) {
      updateSearchParams({ fund_excluded_models: storedValue })
    }
  }, [excludedValuationModelsParam, selectedSymbolKey, updateSearchParams, valuationExclusionsBySymbol])

  useEffect(() => {
    if (!selectedSymbol && rows.length > 0) {
      onSelectSymbol(rows[0].symbol)
    }
  }, [onSelectSymbol, rows, selectedSymbol])

  const selectedRow = useMemo(() => rows.find((row) => row.symbol === selectedSymbol) ?? null, [rows, selectedSymbol])

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
  const resolvedScenario = scenarioParam ? scenario : scenarioFromQuery(detail?.ensemble?.scenario ?? "base")
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

  const visibleValuations = useMemo(() => detail ? sortValuationRows(detail.valuations) : [], [detail])
  const excludedValuationModelsForSelected = selectedSymbolKey ? valuationExclusionsBySymbol[selectedSymbolKey] ?? null : null
  const excludedValuationModelIds = useMemo(() => parseExcludedModelIds(excludedValuationModelsForSelected), [excludedValuationModelsForSelected])
  const selectedCurrentPrice = detail ? detail.ensemble?.current_price ?? asNumber(detail.metrics.Current_Price) : null
  const {
    comparables: selectedComparableView,
    isLoading: isValuationComparableLoading,
  } = useOptionalSelectedComparableView(detail, selectedRow, rows, selectedComparableBenchmarkId)
  const valuationComparableSummary = useMemo<ComparableModelSummary>(
    () => selectedComparableView
      ? comparableModelSummary(selectedComparableView, selectedCurrentPrice)
      : emptyComparableModelSummary(),
    [selectedComparableView, selectedCurrentPrice],
  )
  const valuationSelectionSummary = useMemo<ValuationSelectionSummary>(
    () => detail
      ? buildValuationSelectionSummary({
        rows: visibleValuations,
        excludedModelIds: excludedValuationModelIds,
        comparableSummary: valuationComparableSummary,
        currentPrice: selectedCurrentPrice,
      })
      : {
        fairValue: null,
        low: null,
        high: null,
        upside: null,
        includedCount: 0,
        usableCount: 0,
        weightSource: "equal weights",
        effectiveWeights: new Map(),
      },
    [detail, excludedValuationModelIds, selectedCurrentPrice, valuationComparableSummary, visibleValuations],
  )
  const valuationTargetOverride = detail
    ? { fairValue: valuationSelectionSummary.fairValue, upside: valuationSelectionSummary.upside }
    : undefined

  useEffect(() => {
    if (!detail) {
      setAssumptionDraft({})
      return
    }
    const next: Record<string, number> = {}
    for (const [key] of ASSUMPTION_FIELDS) {
      const value = asNumber(detail.assumptions[key])
      if (value != null) next[key] = value
    }
    setAssumptionDraft(next)
  }, [detail, resolvedScenario])

  function setScenario(next: Scenario) {
    updateSearchParams({ scenario: next })
  }

  function setActiveTab(next: DetailTab) {
    updateSearchParams({ fund_tab: next === "thesis" ? null : next })
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
    setIsSaving(true)
    setSaveError(null)
    try {
      await updateFundamentalAssumptions(selectedSymbol, resolvedScenario, assumptionDraft)
      await Promise.all([mutateDetail(), mutateUniverse(), mutateSensitivity()])
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Failed to save assumptions")
    } finally {
      setIsSaving(false)
    }
  }

  const displayError = universeError ?? detailError

  return (
    <div className="signal-fund-layout">
      <UniverseScreen rows={rows} selectedSymbol={selectedSymbol} isLoading={isUniverseLoading} onSelect={handleSelectSymbol} />

      <section className="signal-fund-detail">
        {displayError ? (
          <div className="m-3 flex items-start gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>{displayError instanceof Error ? displayError.message : "Fundamentals unavailable."}</span>
          </div>
        ) : null}

        {!selectedSymbol ? (
          <div className="signal-fund-empty">
            <Landmark className="h-10 w-10 opacity-[0.15]" />
            Selectionnez un titre pour afficher la recherche fondamentale.
          </div>
        ) : (
          <>
            <ResearchTicket
              row={selectedRow}
              detail={detail}
              isRefreshing={isDetailValidating || isUniverseValidating}
              valuationTargetOverride={valuationTargetOverride}
            />

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
                  {activeTab === "thesis" ? <ThesisTab detail={detail} row={selectedRow} valuationTargetOverride={valuationTargetOverride} /> : null}
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
                    />
                  ) : null}
                  {activeTab === "quality" ? <QualityTab detail={detail} row={selectedRow} /> : null}
                  {activeTab === "estimates" ? <EstimatesTab detail={detail} /> : null}
                  {activeTab === "comparables" ? (
                    <ComparablesTab
                      detail={detail}
                      row={selectedRow}
                      rows={rows}
                      selectedComparatorId={selectedComparableBenchmarkId}
                      onSelectedComparatorIdChange={setSelectedComparableBenchmarkId}
                    />
                  ) : null}
                </>
              )}
            </div>
          </>
        )}
      </section>
    </div>
  )
}
