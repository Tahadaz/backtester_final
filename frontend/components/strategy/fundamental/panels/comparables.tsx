"use client"

import { useEffect, useMemo, useState, type ReactNode } from "react"
import useSWR from "swr"
import {
  fetchDashboardIndices,
  getFundamentalSnapshotBatch,
  type DashboardCustomIndex,
  type FundamentalLightSnapshot,
  type FundamentalStockDetail,
  type FundamentalUniverseRow,
} from "@/lib/api"
import { BUILTIN_CUSTOM_DASHBOARD_INDICES, BUILTIN_WEIGHTED_MASI_INDEX } from "@/lib/builtin-dashboard-indices"
import { cn } from "@/lib/utils"
import { GlossaryTerm } from "@/components/ui/glossary-term"
import { COMPARABLE_METRIC_GLOSSARY_IDS, COMPARABLE_METRICS, DEFAULT_FORWARD_GROWTH, DEFAULT_STABLE_PAYOUT, LOWER_BETTER_COMPARABLE_METRICS, VALUATION_COMPARABLE_METRICS } from "../lib/constants"
import { asNumber, asPositiveNumber, asRatio, comparableMetricLabel, fmtCap, fmtMoney, fmtPct, formatComparableContribution, formatComparableValue, safeRatioValue } from "../lib/formatters"
import { FundCard, StatTile } from "../shared/cards"
import { VerdictChip, type VerdictTone } from "../shared/verdict-chip"
import { ComparableBenchmarkView, ComparableChoice, ComparableIndexDefinition, ComparableModelSummary, ComparablePeerFairValue, ComparablePeerView, ComparableView } from "../lib/types"
import { comparableModelSummary, enabledRelativeValuationMetrics, readDefaultComparatorId, writeDefaultComparatorId } from "../lib/view-models"

function comparableMetricHeader(metric: string): ReactNode {
  const glossaryId = COMPARABLE_METRIC_GLOSSARY_IDS[metric]
  const label = comparableMetricLabel(metric)
  return glossaryId ? <GlossaryTerm id={glossaryId}>{label}</GlossaryTerm> : label
}

function comparableGapVerdictTone(metric: string, gap: number | null): VerdictTone {
  if (gap == null) return "neutral"
  const favorable = LOWER_BETTER_COMPARABLE_METRICS.has(metric) ? gap <= 0 : gap >= 0
  return favorable ? "good" : "serious"
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


export function firstAnnualMetric(metrics: Record<string, number | null>, names: string[]): number | null {
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


export function evToEbitdaFairValue(peerMultiple: number | null, ebitda: number | null, netDebt: number | null, shares: number | null): number | null {
  if (peerMultiple == null || peerMultiple <= 0 || ebitda == null || ebitda <= 0 || netDebt == null || shares == null || shares <= 0) return null
  return Math.max(0, peerMultiple * ebitda - netDebt) / shares
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


export function comparableChoiceForIndex(definition: ComparableIndexDefinition, targetSymbol: string): ComparableChoice | null {
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


export function medianValue(values: number[]): number | null {
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


export function comparablePeerFairValueSummary(
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


export function buildIndexComparatorChoices(
  dashboardIndices: DashboardCustomIndex[] | undefined,
  targetSymbol: string,
): ComparableChoice[] {
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
  return sourceIndices
    .map((definition) => comparableChoiceForIndex(definition, targetSymbol))
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
}


export function resolveComparatorPeerSymbols(
  comparatorId: string,
  targetSymbol: string,
  dashboardIndices: DashboardCustomIndex[] | undefined,
): string[] | undefined {
  if (!comparatorId.startsWith("index:") || !targetSymbol) return undefined
  const choice = buildIndexComparatorChoices(dashboardIndices, targetSymbol).find((item) => item.id === comparatorId)
  if (!choice) return undefined
  const target = normalizeComparableSymbol(targetSymbol)
  return choice.symbols.filter((symbol) => symbol !== target)
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
    const indexChoices = buildIndexComparatorChoices(dashboardIndices, detail.symbol)
    return [sectorChoice, ...indexChoices]
  }, [dashboardIndices, detail, rows, selectedRow])
}


export function useOptionalSelectedComparableView(
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
                <th key={metric} className="r">FV {comparableMetricHeader(metric)} est.</th>
              ))}
              <th className="r">FV comparable</th>
              <th className="r">FV pondérée</th>
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


export function ComparableBenchmarkPanel({
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
  const [defaultComparatorSaved, setDefaultComparatorSaved] = useState(false)
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

  const isDefaultComparator = readDefaultComparatorId() === selectedComparator.id
  useEffect(() => {
    setDefaultComparatorSaved(false)
  }, [selectedComparator.id])

  const handleSaveDefaultComparator = () => {
    writeDefaultComparatorId(selectedComparator.id)
    setDefaultComparatorSaved(true)
  }

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
        <button
          type="button"
          className="fund-compare-metric"
          onClick={handleSaveDefaultComparator}
          disabled={isDefaultComparator}
          title="Utiliser ce benchmark par defaut sur toutes les fiches"
        >
          {isDefaultComparator ? "Benchmark par defaut ✓" : defaultComparatorSaved ? "Enregistre ✓" : "Definir par defaut"}
        </button>
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
        <StatTile label={detail.symbol} value={formatComparableValue(activeMetric, selectedValue)} sub={<>{comparableMetricHeader(activeMetric)} estimé</>} />
        <StatTile
          label="Benchmark"
          value={formatComparableValue(activeMetric, benchmark?.weighted_including_target)}
          sub={comparables.comparator.target_in_comparator ? "incl. titre" : "benchmark"}
        />
        <StatTile
          label="Peer-only"
          value={formatComparableValue(activeMetric, benchmark?.weighted_excluding_target)}
          sub={`${benchmark?.weighted_count ?? 0} valeurs pondérées`}
        />
        <StatTile label="Médiane" value={formatComparableValue(activeMetric, benchmark?.median)} sub={`${benchmark?.eligible_count ?? 0} valeurs éligibles`} />
        <StatTile
          label="FV modèle"
          value={`${fmtMoney(comparableFairValue.fairValue, 1)} ${detail.ensemble?.currency ?? "MAD"}`}
          sub={comparableFairValue.peerCount ? `${comparableFairValue.peerCount} comparables` : `${comparableFairValue.count} multiples`}
        />
        <div className="fund-stat">
          <span className="lbl">Écart peer-only</span>
          <span className="val">
            <VerdictChip
              tone={comparableGapVerdictTone(activeMetric, gapVsBenchmark)}
              label={gapVsBenchmark == null ? "Non renseigné" : `${fmtPct(gapVsBenchmark, 1)} vs pairs`}
            />
          </span>
          <span className="sub">{LOWER_BETTER_COMPARABLE_METRICS.has(activeMetric) ? "plus bas = moins cher" : "plus haut = mieux"}</span>
        </div>
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
              {showPerColumn ? <th className="r">{comparableMetricHeader("PER")} est.</th> : null}
              <th className="r">{comparableMetricHeader(activeMetric)} est.</th>
              <th className="r">Poids</th>
              <th className="r">Contribution</th>
              <th className="r">Cours</th>
              <th className="r">Base poids</th>
              <th>Qualité</th>
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

