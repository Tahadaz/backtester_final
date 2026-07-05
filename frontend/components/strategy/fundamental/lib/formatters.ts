
import { COMPARABLE_METRIC_LABELS, COMPARABLE_PERCENT_METRICS, VALUE_LABELS } from "../lib/constants"
import { medianValue } from "../panels/comparables"
import { DcfBridgeStep, ModelStoryMetricFormat, Recommendation } from "../lib/types"

export function clampValue(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}


export function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}


export function asPositiveNumber(value: unknown): number | null {
  const numberValue = asNumber(value)
  return numberValue != null && numberValue > 0 ? numberValue : null
}


export function asRatio(value: unknown): number | null {
  const numberValue = asNumber(value)
  if (numberValue == null) return null
  return Math.abs(numberValue) > 2 ? numberValue / 100 : numberValue
}


export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {}
}


export function boundedMask(value: number | null, fallback: number, max: number): number {
  if (value == null) return fallback
  return Math.max(0, Math.min(max, Math.trunc(value)))
}


export function recordNumber(record: Record<string, unknown>, key: string): number | null {
  return asNumber(record[key])
}


export function fmtNumber(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "-"
  return value.toLocaleString("fr-FR", { maximumFractionDigits: digits, minimumFractionDigits: digits })
}


export function fmtMoney(value: number | null | undefined, digits = 0): string {
  if (value == null || Number.isNaN(value)) return "-"
  return value.toLocaleString("fr-FR", { maximumFractionDigits: digits, minimumFractionDigits: digits })
}


export function fmtPct(value: number | null | undefined, digits = 1, sign = true): string {
  if (value == null || Number.isNaN(value)) return "-"
  return `${value >= 0 && sign ? "+" : ""}${(value * 100).toFixed(digits)}%`
}


export function fmtAssumptionValue(value: unknown, unit?: string | null): string {
  const numberValue = asNumber(value)
  if (numberValue == null) return value == null || value === "" ? "-" : String(value)
  if (unit === "percent") return fmtPct(numberValue, 2, false)
  if (unit === "years" || unit === "count") return fmtNumber(numberValue, 0)
  if (unit === "x") return fmtRatio(numberValue, 2)
  if (unit === "flag") return numberValue >= 0.5 ? "Oui" : "Non"
  return fmtNumber(numberValue, 3)
}


export function assumptionRangeLabel(range: number[] | null | undefined, unit?: string | null): string {
  if (!range || range.length < 2) return "-"
  return `${fmtAssumptionValue(range[0], unit)} - ${fmtAssumptionValue(range[1], unit)}`
}


export function fmtRatio(value: number | null | undefined, digits = 1): string {
  if (value == null || Number.isNaN(value)) return "-"
  return `${value.toFixed(digits)}x`
}


export function fmtCap(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "-"
  const abs = Math.abs(value)
  if (abs >= 1_000_000_000) return `${fmtNumber(value / 1_000_000_000, 1)} Bn`
  if (abs >= 1_000_000) return `${fmtNumber(value / 1_000_000, 1)} M`
  return fmtMoney(value)
}


export function fmtCompactMad(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "-"
  const abs = Math.abs(value)
  if (abs >= 1_000_000) return `${fmtNumber(value / 1_000_000, 1)} M`
  if (abs >= 1_000) return `${fmtNumber(value / 1_000, 0)} k`
  return fmtMoney(value)
}


export function comparableMetricLabel(metric: string): string {
  return COMPARABLE_METRIC_LABELS[metric] ?? metric.replaceAll("_", " ")
}


export function formatComparableValue(metric: string, value: number | null | undefined): string {
  if (metric === "Dividend_Yield") {
    if (value == null || Number.isNaN(value)) return "-"
    const percentValue = Math.abs(value) >= 0.25 ? value : value * 100
    return `${fmtNumber(percentValue, 1)}%`
  }
  if (COMPARABLE_PERCENT_METRICS.has(metric)) return fmtPct(value, 1, false)
  return fmtRatio(value, 1)
}


export function formatComparableContribution(metric: string, value: number | null | undefined): string {
  if (metric === "Dividend_Yield") return value == null || Number.isNaN(value) ? "-" : `${fmtNumber(value, 2)}%`
  return formatComparableValue(metric, value)
}


export function safeRatioValue(numerator: number | null, denominator: number | null): number | null {
  return numerator != null && denominator != null && denominator > 0 ? numerator / denominator : null
}


export function formatDate(value: string | null | undefined): string {
  if (!value) return "-"
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value.slice(0, 10)
  return parsed.toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "numeric" })
}


export function scoreClass(value: number | null | undefined): string {
  if (value == null) return "text-muted-foreground"
  if (value >= 70) return "t-pos"
  if (value <= 35) return "t-neg"
  return "text-foreground"
}


export function confidenceClass(confidence: string | null | undefined): string {
  if (confidence === "high") return "signal-conf-high"
  if (confidence === "medium") return "signal-conf-medium"
  if (confidence === "low") return "signal-conf-low"
  return "signal-conf-empty"
}


export function confidenceLabel(score: number | null | undefined): string | null {
  if (score == null) return null
  if (score >= 0.75) return "high"
  if (score >= 0.45) return "medium"
  if (score > 0) return "low"
  return "unavailable"
}


export function recommendationClass(value: Recommendation | null | undefined): string {
  if (value === "BUY" || value === "ACCUMULATE") return "buy"
  if (value === "HOLD") return "hold"
  if (value === "REDUCE" || value === "SELL") return "sell"
  return "not-rated"
}


const RECOMMENDATION_LABELS: Record<Recommendation, string> = {
  BUY: "Acheter",
  ACCUMULATE: "Accumuler",
  HOLD: "Conserver",
  REDUCE: "Alléger",
  SELL: "Vendre",
  NR: "NR",
}


export function recommendationLabel(value: Recommendation | null | undefined): string {
  return value == null ? "NR" : RECOMMENDATION_LABELS[value] ?? "NR"
}


export function valueLabel(key: string): string {
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


export function formatStatementValue(value: number | null | undefined, format: string): string {
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


export function formatModelScalar(key: string, value: number): string {
  if (isPercentLikeKey(key)) return fmtPct(value, 1, false)
  if (key.toLowerCase().includes("year") || key.toLowerCase().includes("count")) return fmtNumber(value, 0)
  if (isMoneyLikeKey(key)) return fmtCap(value)
  return fmtNumber(value, Math.abs(value) < 10 ? 3 : 1)
}


export function formatNestedModelValue(key: string, value: unknown): string {
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


export function formatProjectionValue(value: number | null, format: "money" | "pct" | "number"): string {
  if (format === "pct") return fmtPct(value, 1, false)
  if (format === "money") return fmtMoney(value, 0)
  return fmtNumber(value, 2)
}


export function formatDcfStepValue(step: DcfBridgeStep): string {
  if (step.value == null) return "-"
  if (step.kind === "divide") return fmtNumber(step.value, 0)
  if (step.kind === "result") return fmtMoney(step.value, 2)
  return fmtMoney(step.value, 0)
}


export function formatStoryValue(value: unknown, format?: ModelStoryMetricFormat, digits?: number): string {
  const numberValue = asNumber(value)
  if (numberValue == null) return value == null || value === "" ? "-" : String(value)
  if (format === "money") return fmtMoney(numberValue, digits ?? 2)
  if (format === "pct") return fmtPct(numberValue, digits ?? 2, false)
  if (format === "ratio") return fmtRatio(numberValue, digits ?? 2)
  return fmtNumber(numberValue, digits ?? (Math.abs(numberValue) < 10 ? 2 : 0))
}
