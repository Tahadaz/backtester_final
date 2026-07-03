import {
  type FundamentalMethodology,
  type FundamentalHorizonPrediction,
  type FundamentalStockDetail,
  type FundamentalUniverseRow,
  type FundamentalValuationResult,
} from "@/lib/api"
import { buildFinancialStatementTable } from "@/lib/fundamental-statement-utils.js"
import { ASSUMPTION_FIELDS, DEFAULT_VALUATION_FORMULA, ESTIMATION_ASSUMPTION_KEYS, EXTREME_VALUATION_FAIR_VALUE_MULTIPLE, FUNDAMENTAL_HORIZONS, FUNDAMENTAL_LIQUIDITY_ADV20_THRESHOLD, FUND_TABS, JUSTIFIED_MULTIPLE_RATIOS, JUSTIFIED_MULTIPLE_RATIO_DEFAULT_MASK, JUSTIFIED_MULTIPLE_RATIO_MASK_KEY, MODEL_FORMULA_META, MODEL_LABELS, MODEL_ORDER, RELATIVE_MULTIPLE_RATIOS, RELATIVE_MULTIPLE_RATIO_DEFAULT_MASK, RELATIVE_MULTIPLE_RATIO_MASK_KEY, SCENARIOS, SEVERE_FCF_WARNING_PREFIXES, SEVERE_VALUATION_WARNINGS, STATEMENT_TITLES, VALUATION_COMPARABLE_METRICS, VALUATION_EXCLUSIONS_STORAGE_KEY } from "../lib/constants"
import { asNumber, asPositiveNumber, asRatio, asRecord, boundedMask, comparableMetricLabel, confidenceLabel, fmtMoney, fmtNumber, fmtPct, fmtRatio, formatStatementValue, valueLabel } from "../lib/formatters"
import { comparablePeerFairValueSummary, evToEbitdaFairValue, medianValue } from "../panels/comparables"
import { ComparableModelSummary, ComparableView, DcfMode, DetailTab, FinancialStatementTable, FundamentalHorizon, ModelValueItem, MultipleRatioDefinition, ProjectionView, Scenario, SeriesPoint, SortKey, StatementEvidenceGroup, ValuationFormulaMeta, ValuationMethodRange, ValuationSelectionSummary, WeightMode } from "../lib/types"

export function detailRatioMask(
  detail: FundamentalStockDetail,
  draft: Record<string, number>,
  key: string,
  fallback: number,
  max: number,
): number {
  return boundedMask(asNumber(draft[key]) ?? asNumber(detail.assumptions[key]), fallback, max)
}


export function enabledRatioKeys(definitions: MultipleRatioDefinition[], mask: number): string[] {
  return definitions.filter((item) => (mask & item.bit) !== 0).map((item) => item.key)
}


export function enabledRelativeValuationMetrics(detail: FundamentalStockDetail | null): string[] {
  const mask = detail
    ? detailRatioMask(detail, {}, RELATIVE_MULTIPLE_RATIO_MASK_KEY, RELATIVE_MULTIPLE_RATIO_DEFAULT_MASK, RELATIVE_MULTIPLE_RATIO_DEFAULT_MASK)
    : RELATIVE_MULTIPLE_RATIO_DEFAULT_MASK
  return enabledRatioKeys(RELATIVE_MULTIPLE_RATIOS, mask)
}


export function enabledRelativeValuationMetricsForDraft(detail: FundamentalStockDetail | null, draft: Record<string, number>): string[] {
  const mask = detail
    ? detailRatioMask(detail, draft, RELATIVE_MULTIPLE_RATIO_MASK_KEY, RELATIVE_MULTIPLE_RATIO_DEFAULT_MASK, RELATIVE_MULTIPLE_RATIO_DEFAULT_MASK)
    : RELATIVE_MULTIPLE_RATIO_DEFAULT_MASK
  return enabledRatioKeys(RELATIVE_MULTIPLE_RATIOS, mask)
}


function editableAssumptionKeys(methodology?: FundamentalMethodology): string[] {
  if (!methodology) return Array.from(new Set([...ASSUMPTION_FIELDS.map(([key]) => key), ...ESTIMATION_ASSUMPTION_KEYS, JUSTIFIED_MULTIPLE_RATIO_MASK_KEY, RELATIVE_MULTIPLE_RATIO_MASK_KEY]))
  return Object.entries(methodology.assumptions)
    .filter(([, meta]) => meta.editable !== false)
    .map(([key]) => key)
}


export function editableAssumptionDraft(methodology: FundamentalMethodology | undefined, draft: Record<string, number>): Record<string, number> {
  const allowed = new Set(editableAssumptionKeys(methodology))
  return Object.fromEntries(Object.entries(draft).filter(([key, value]) => allowed.has(key) && Number.isFinite(value)))
}


export function comparableModelSummary(
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


export function emptyComparableModelSummary(): ComparableModelSummary {
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


export function rowUpside(row: FundamentalUniverseRow | null | undefined): number | null {
  if (!row) return null
  return asNumber(row.ensemble?.upside_pct) ?? asNumber(row.valuation_summary.consensus_upside_pct)
}


export function horizonPredictionsFor(
  detail: FundamentalStockDetail | null | undefined,
  row: FundamentalUniverseRow | null | undefined,
): FundamentalHorizonPrediction[] {
  const fromDetail = Array.isArray(detail?.horizon_predictions) ? detail.horizon_predictions : []
  if (fromDetail.length) return fromDetail
  return Array.isArray(row?.horizon_predictions) ? row.horizon_predictions : []
}


export function predictionForHorizon(
  detail: FundamentalStockDetail | null | undefined,
  row: FundamentalUniverseRow | null | undefined,
  horizon: FundamentalHorizon,
): FundamentalHorizonPrediction | null {
  const predictions = horizonPredictionsFor(detail, row)
  return predictions.find((item) => item.horizon === horizon && item.available !== false && item.forward_target != null) ?? null
}


export function effectiveHorizonPrediction(
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


export function rowAdv20(row: FundamentalUniverseRow | null | undefined): number | null {
  return asNumber(row?.adv20)
}


export function isLiquidFundamentalRow(row: FundamentalUniverseRow): boolean {
  const adv20 = rowAdv20(row)
  return adv20 != null && adv20 >= FUNDAMENTAL_LIQUIDITY_ADV20_THRESHOLD
}

// MASI = Moroccan market. MASI stocks carry market_region "masi" or null/empty;
// use a whitelist so any future foreign region tag is automatically excluded.


export function isMasiFundamentalRow(row: FundamentalUniverseRow): boolean {
  const region = (row.market_region ?? "").trim().toLowerCase()
  return region === "" || region === "masi"
}


export function scenarioFromQuery(value: string | null): Scenario {
  const token = String(value ?? "").trim().toLowerCase()
  return SCENARIOS.includes(token as Scenario) ? (token as Scenario) : "base"
}


export function horizonFromQuery(value: string | null): FundamentalHorizon {
  const token = String(value ?? "").trim().toLowerCase()
  return FUNDAMENTAL_HORIZONS.some((item) => item.value === token) ? (token as FundamentalHorizon) : "year"
}


export function tabFromQuery(value: string | null): DetailTab {
  const token = String(value ?? "").trim().toLowerCase()
  if (FUND_TABS.some((item) => item.value === token)) return token as DetailTab
  // Legacy fund_tab values from the six-tab layout (brief 57 §3.2).
  if (token === "thesis" || token === "summary" || token === "resume") return "synthese"
  if (token === "assumptions" || token === "financials") return "estimates"
  if (token === "comparables" || token === "qualite") return "quality"
  return "synthese"
}


export function weightModeFromQuery(value: string | null): WeightMode {
  return value?.trim() === "equal" ? "equal" : "ic"
}


export function screensFor(detail: FundamentalStockDetail | null | undefined, row?: FundamentalUniverseRow | null): Record<string, unknown> {
  if (detail?.screens && Object.keys(detail.screens).length > 0) return detail.screens
  const diagnosticsScreens = asRecord(detail?.diagnostics?.screens)
  if (Object.keys(diagnosticsScreens).length > 0) return diagnosticsScreens
  return row?.screens ?? {}
}


export function screenRecord(screens: Record<string, unknown>, name: string): Record<string, unknown> {
  return asRecord(screens[name])
}


export function sortValue(row: FundamentalUniverseRow, sortKey: SortKey): number {
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


export function compactFlagLabel(value: string): string {
  return value.replaceAll("_", " ")
}


function uniqueStrings(values: Array<string | null | undefined>): string[] {
  return Array.from(new Set(values.filter((item): item is string => Boolean(item))))
}


export function ensembleForFlags(detail: FundamentalStockDetail | null | undefined, row?: FundamentalUniverseRow | null) {
  return detail?.ensemble ?? row?.ensemble ?? null
}


export function ensembleWarningsFor(detail: FundamentalStockDetail | null | undefined, row?: FundamentalUniverseRow | null): string[] {
  const detailWarnings = detail?.ensemble?.warnings ?? []
  const rowWarnings = row?.ensemble?.warnings ?? []
  return uniqueStrings([...detailWarnings, ...rowWarnings])
}


export function overallCoveragePct(detail: FundamentalStockDetail | null | undefined, row?: FundamentalUniverseRow | null): number | null {
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


export function ratingFlagsFor(detail: FundamentalStockDetail | null | undefined, row?: FundamentalUniverseRow | null): string[] {
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


function modelSortIndex(model: string): number {
  const index = MODEL_ORDER.indexOf(model)
  return index === -1 ? MODEL_ORDER.length : index
}


export function sortValuationRows(rows: FundamentalValuationResult[]): FundamentalValuationResult[] {
  return [...rows].sort((a, b) => modelSortIndex(a.model) - modelSortIndex(b.model) || a.model.localeCompare(b.model))
}


function valuationSpread(confidence: string | null | undefined): number {
  return confidence === "high" ? 0.06 : confidence === "medium" ? 0.10 : 0.16
}


export function parseExcludedModelIds(value: string | null | undefined): Set<string> {
  return new Set(
    (value ?? "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
  )
}


export function valuationSymbolKey(symbol: string | null | undefined): string | null {
  const key = (symbol ?? "").trim().toUpperCase()
  return key || null
}


export function readValuationExclusionsBySymbol(): Record<string, string> {
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


export function writeValuationExclusionsBySymbol(value: Record<string, string>) {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(VALUATION_EXCLUSIONS_STORAGE_KEY, JSON.stringify(value))
  } catch {
    // Ignore storage failures; the URL still reflects the active stock.
  }
}


export function serializeExcludedModelIds(modelIds: Set<string>, rows: FundamentalValuationResult[]): string | null {
  if (modelIds.size === 0) return null
  const orderedModels = Array.from(new Set(sortValuationRows(rows).map((row) => row.model)))
  const ordered = [
    ...orderedModels.filter((model) => modelIds.has(model)),
    ...Array.from(modelIds).filter((model) => !orderedModels.includes(model)).sort(),
  ]
  return ordered.length ? ordered.join(",") : null
}


export function fairValueForValuationRow(row: FundamentalValuationResult, comparableSummary: ComparableModelSummary | null): number | null {
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


export function applyRatioDraftToValuationRows(
  rows: FundamentalValuationResult[],
  detail: FundamentalStockDetail | null,
  draft: Record<string, number>,
): FundamentalValuationResult[] {
  if (!detail) return rows
  return rows.map((row) => applyRatioDraftToValuationRow(row, detail, draft))
}


export function currentPriceForValuationRow(row: FundamentalValuationResult, detail: FundamentalStockDetail): number | null {
  return row.current_price ?? detail.ensemble?.current_price ?? asNumber(detail.metrics.Current_Price)
}


export function upsideForFairValue(fairValue: number | null, currentPrice: number | null): number | null {
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


export function buildValuationSelectionSummary({
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


export function valuationMethods(
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


export function valuationFormulaMeta(model: string): ValuationFormulaMeta {
  return MODEL_FORMULA_META[model] ?? DEFAULT_VALUATION_FORMULA
}


export function projectionFromDetail(detail: FundamentalStockDetail): ProjectionView | null {
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


export function projectedYears(projection: ProjectionView): number[] {
  return projection.statements.map((statement) => asNumber(statement.fiscal_year)).filter((year): year is number => year != null)
}


export function projectedValue(statement: Record<string, unknown>, key: string): number | null {
  return asNumber(statement[key])
}


export function driverProjectedValue(driver: Record<string, unknown>, year: number): number | null {
  const projected = asRecord(driver.projected_by_year)
  return asNumber(projected[String(year)]) ?? asNumber(projected[year])
}


export function projectionDriverRows(projection: ProjectionView): Array<{ key: string; label: string; format: "pct" | "number"; driver: Record<string, unknown> }> {
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


export function projectionStatementRows(): Array<{ key: string; label: string; format: "money" | "pct" }> {
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


export function projectionSeriesFromDriver(driver: Record<string, unknown>): SeriesPoint[] {
  const projected = asRecord(driver.projected_by_year)
  return Object.entries(projected)
    .flatMap(([year, value]): SeriesPoint[] => {
      const yearValue = Number(year)
      const numberValue = asNumber(value)
      return Number.isFinite(yearValue) && numberValue != null ? [{ year: yearValue, value: numberValue, kind: "projected" }] : []
    })
    .sort((a, b) => a.year - b.year)
}


export function historicalSeriesFromDriver(driver: Record<string, unknown>): SeriesPoint[] {
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


export function seriesFromRaw(value: unknown, kind: SeriesPoint["kind"] = "historical"): SeriesPoint[] {
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


export function seriesPath(points: SeriesPoint[], width: number, height: number, pad = 8): string {
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


export function seriesPointPosition(point: SeriesPoint, points: SeriesPoint[], width: number, height: number, pad = 8): { x: number; y: number } {
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


export function instantiatedFormula(row: FundamentalValuationResult, detail: FundamentalStockDetail): string | null {
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


export function statementEvidence(detail: FundamentalStockDetail, model: string): StatementEvidenceGroup[] {
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


export function valuationAssumptionItems(row: FundamentalValuationResult, detail: FundamentalStockDetail): ModelValueItem[] {
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


export function technicalInputItems(row: FundamentalValuationResult): ModelValueItem[] {
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


export function outputItems(row: FundamentalValuationResult): ModelValueItem[] {
  return Object.entries(asRecord(row.outputs)).map(([key, value]) => ({ key, label: valueLabel(key), value, source: "output" }))
}


export function dcfModeForModel(model: string): DcfMode | null {
  if (model === "fcff_dcf") return "fcff"
  if (model === "fcfe_dcf") return "fcfe"
  return null
}


export function dcfVerdict(displayUpside: number | null | undefined, mode: DcfMode): string {
  if (displayUpside == null) return `Verdict ${mode.toUpperCase()} non disponible.`
  const magnitude = fmtPct(Math.abs(displayUpside), 1, false)
  return displayUpside >= 0
    ? `Sous-evalue de ${magnitude} selon le DCF ${mode.toUpperCase()}.`
    : `Surevalue de ${magnitude} selon le DCF ${mode.toUpperCase()}.`
}

