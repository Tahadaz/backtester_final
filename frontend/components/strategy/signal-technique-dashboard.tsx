"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"
import { Activity, BarChart3, ExternalLink, TrendingUp } from "lucide-react"
import { useWfoSummary } from "@/hooks/use-wfo-summary"
import {
  fetchBestSignalBacktestChart,
  fetchIndicatorSeries,
  fetchSignalBacktestResultsWithBootstrap,
  fetchSignalEngineResultWithBootstrap,
  type SignalBacktestResult,
  type SignalEngineResult,
  type WfoSummaryResponse,
} from "@/lib/api"
import { formatNumber, formatPercent } from "@/lib/format"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { PriceSignalsChart, type IndicatorOverlaySeries } from "@/components/signals/price-signals-chart"
import { AccountingTradeLedgerTable } from "@/components/signals/trade-ledger-table"
import {
  INDICATOR_FAMILY_META,
  INDICATOR_FAMILY_ORDER,
  type IndicatorFamilyKey,
  type IndicatorFamilyMeta,
} from "./indicator-config"

type CategoryId = "tendance" | "momentum" | "oscillation" | "volume"
type RangeKey = "1J" | "5J" | "1M" | "6M" | "1A" | "Tout"
type TechniqueSource = "engine" | "wfo"
type TechniqueScope = {
  scope: string
  scopeKey: string
}
type TechniqueScopeOption = TechniqueScope & {
  id: string
  label: string
  rowCount: number
}

type FamilySignalRow = {
  key: string
  label: string
  params: string
  category: CategoryId
  signalLabel: string | null
  score: number | null
  representativeId: string | null
  factorDependencies: Array<{ ticker: string; label: string; rule: string; id: string }>
}

type RepresentativeIndicator = {
  id: string
  family: IndicatorFamilyKey
  variantId: string
  description: string
  params: Record<string, number>
}

const CATEGORY_META: Array<{
  id: CategoryId
  label: string
  icon: typeof TrendingUp
}> = [
  { id: "tendance", label: "Tendance", icon: TrendingUp },
  { id: "momentum", label: "Momentum", icon: Activity },
  { id: "oscillation", label: "Oscillation", icon: Activity },
  { id: "volume", label: "Volume", icon: BarChart3 },
]

const FAMILY_META_BY_KEY = Object.fromEntries(
  INDICATOR_FAMILY_META.map((meta) => [meta.key, meta]),
) as Record<IndicatorFamilyKey, IndicatorFamilyMeta>

const RANGE_TO_BARS: Record<RangeKey, number | null> = {
  "1J": 2,
  "5J": 6,
  "1M": 23,
  "6M": 132,
  "1A": 252,
  Tout: null,
}

const PRICE_AXIS_FAMILIES = new Set<IndicatorFamilyKey>(["sma", "ema", "ema_cross", "ichimoku", "psar", "vwap"])

const FACTOR_TICKER_LABELS: Record<string, string> = {
  "^VIX": "VIX",
  "^GSPC": "SP500",
  "^NDX": "NDX",
  "^N225": "N225",
  "^FCHI": "CAC",
  "^FTSE": "FTSE",
  "BZ=F": "BRENT",
  "GC=F": "GOLD",
  "SI=F": "SILVER",
  "DX-Y.NYB": "DXY",
  "EURUSD=X": "EURUSD",
  "AED=X": "AED",
  "^TNX": "US10Y",
  "BTC-USD": "BTC",
}

const TECHNIQUE_SOURCES: Array<{ key: TechniqueSource; label: string }> = [
  { key: "engine", label: "Signal Engine" },
  { key: "wfo", label: "WFO" },
]

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

function asString(value: unknown): string {
  return typeof value === "string" ? value : ""
}

function comboFamilyKey(variant: string, category: CategoryId): string {
  if (variant.startsWith("legacy_factor_x_ta")) return `legacy_fx_combo_${category}`
  if (variant.startsWith("expanded_factor_x_ta")) return `expanded_fx_combo_${category}`
  if (variant.startsWith("legacy_ta")) return `legacy_ta_combo_${category}`
  return `expanded_ta_combo_${category}`
}

function paramsLabel(meta: IndicatorFamilyMeta): string {
  return Object.entries(meta.defaults)
    .map(([key, value]) => `${key}=${value}`)
    .join(" ")
}

function paramsLabelFromValues(params: Record<string, number>): string {
  return Object.entries(params)
    .map(([key, value]) => `${key}=${Number.isInteger(value) ? value : Number(value.toFixed(4))}`)
    .join(" ")
}

function representativeDisplayLabel(family: IndicatorFamilyKey, params: Record<string, number>): string {
  const meta = FAMILY_META_BY_KEY[family]
  const paramText = paramsLabelFromValues(params)
  return paramText ? `${meta.shortLabel} ${paramText}` : meta.shortLabel
}

function isIndicatorFamilyKey(value: string): value is IndicatorFamilyKey {
  return INDICATOR_FAMILY_ORDER.includes(value as IndicatorFamilyKey)
}

function chartFamilyFromSignalFamily(value: string): IndicatorFamilyKey | null {
  const baseFamily = value.endsWith("@fx") ? value.slice(0, -3) : value
  return isIndicatorFamilyKey(baseFamily) ? baseFamily : null
}

function numericParamsFrom(raw: unknown): Record<string, number> {
  const params: Record<string, number> = {}
  const record = asRecord(raw) ?? {}
  for (const [key, value] of Object.entries(record)) {
    const numberValue = asNumber(value)
    if (numberValue != null) params[key] = numberValue
  }
  return params
}

function sourceLabel(source: string | null | undefined): string {
  return source === "wfo" ? "WFO" : "Signal Engine"
}

function techniqueSourceFromQuery(value: string | null): TechniqueSource {
  const token = String(value ?? "").trim().toLowerCase()
  return token === "engine" || token === "signal_engine" ? "engine" : "wfo"
}

function sidePolicyLabel(sidePolicy: string | null | undefined): string {
  return sidePolicy === "long_short" ? "Long/Short directionnel" : "Long-only"
}

function rowMatchesTechniqueSource(row: SignalBacktestResult, source: TechniqueSource): boolean {
  if (source === "wfo") return row.source === "wfo"
  return row.source === "engine" || row.source === "signal_engine"
}

function scopeOptionId(scope: string | null | undefined, scopeKey: string | null | undefined): string {
  return `${String(scope || "global")}:${String(scopeKey || "global")}`
}

function scopeFromQuery(scope: string | null, scopeKey: string | null): TechniqueScope {
  const normalizedScope = String(scope ?? "").trim() || "global"
  const normalizedKey = String(scopeKey ?? "").trim() || (normalizedScope === "global" ? "global" : "")
  return {
    scope: normalizedScope,
    scopeKey: normalizedKey || "global",
  }
}

function categoryLabel(category: string): string {
  return CATEGORY_META.find((item) => item.id === category)?.label ?? category
}

function scopeLabel(scope: string | null | undefined, scopeKey: string | null | undefined): string {
  const normalizedScope = String(scope || "global")
  const normalizedKey = String(scopeKey || "global")
  if (normalizedScope === "global") return "Global"
  if (normalizedScope === "per_category") return categoryLabel(normalizedKey)
  if (normalizedScope === "combination") {
    return normalizedKey.split("+").filter(Boolean).map(categoryLabel).join(" + ") || normalizedKey
  }
  return normalizedKey
}

function scopeSortKey(option: TechniqueScopeOption): string {
  if (option.scope === "global") return "0:global"
  if (option.scope === "per_category") {
    const index = CATEGORY_META.findIndex((item) => item.id === option.scopeKey)
    return `1:${index < 0 ? 99 : index}:${option.scopeKey}`
  }
  const categories = option.scopeKey.split("+").filter(Boolean)
  return `2:${categories.length}:${categories.join("+")}`
}

function signalScoreTone(score: number | null | undefined): string {
  if (score == null) return "text-muted-foreground"
  if (score > 15) return "text-[oklch(0.50_0.13_165)]"
  if (score < -15) return "text-[oklch(0.52_0.20_25)]"
  return "text-muted-foreground"
}

function signalClass(label: string | null | undefined): string {
  const lower = String(label ?? "").toLowerCase()
  if (lower.includes("achat") || lower.includes("haussier") || lower.includes("accum") || lower.includes("survendu")) {
    return "border-emerald-200 bg-emerald-50 text-emerald-700"
  }
  if (lower.includes("vente") || lower.includes("baissier") || lower.includes("distrib") || lower.includes("surachet")) {
    return "border-red-200 bg-red-50 text-red-700"
  }
  return "border-border bg-muted/30 text-muted-foreground"
}

function scoreText(score: number | null | undefined): string {
  if (score == null || !Number.isFinite(score)) return "--"
  return `${score >= 0 ? "+" : ""}${score.toFixed(1)}%`
}

function factorRule(condition: Record<string, unknown>): string {
  const direction = asString(condition.direction)
  const sym = direction === "below" ? "<" : ">"
  const form = asString(condition.form)
  const lookback = condition.lookback
  const threshold = typeof condition.threshold === "number" ? condition.threshold : Number(condition.threshold ?? 0)
  if (form === "zscore") return `z${lookback} ${sym} ${threshold}`
  if (form === "momentum") return `mom${lookback} ${sym} ${(threshold * 100).toFixed(1)}%`
  if (form === "change") return `change(${lookback}) ${sym} ${threshold}`
  if (form === "level") return `level ${sym} ${threshold}`
  if (form === "direction") return `dir ${sym} 0`
  return `${form}(${lookback}) ${sym} ${threshold}`
}

function factorDependenciesFromReps(reps: unknown[]): Array<{ ticker: string; label: string; rule: string; id: string }> {
  const out: Array<{ ticker: string; label: string; rule: string; id: string }> = []
  const seen = new Set<string>()
  const add = (raw: unknown) => {
    const condition = asRecord(raw)
    if (!condition) return
    const ticker = asString(condition.factor_ticker)
    const id = asString(condition.condition_id)
    if (!ticker || !id) return
    const key = `${ticker}:${id}`
    if (seen.has(key)) return
    seen.add(key)
    out.push({ ticker, id, label: FACTOR_TICKER_LABELS[ticker] ?? ticker, rule: factorRule(condition) })
  }
  for (const rawRep of reps) {
    const rep = asRecord(rawRep)
    add(rep?.factor_condition)
    const params = asRecord(rep?.params)
    for (const component of asArray(params?.components)) {
      const componentRecord = asRecord(component)
      add(componentRecord?.factor_condition)
    }
  }
  return out
}

function mean(values: Array<number | null | undefined>): number | null {
  const nums = values.filter((value): value is number => typeof value === "number" && Number.isFinite(value))
  if (nums.length === 0) return null
  return nums.reduce((sum, value) => sum + value, 0) / nums.length
}

function normalizeFamilies(result: SignalEngineResult | null, variant: string): FamilySignalRow[] {
  if (!result) return []
  const families = asRecord(result.families) ?? {}

  if (variant.endsWith("_combo")) {
    return CATEGORY_META.map((category) => {
      const familyKey = comboFamilyKey(variant, category.id)
      const payload = asRecord(families[familyKey])
      const detail = asRecord(payload?.family_detail) ?? {}
      const reps = asArray(detail.representatives).length > 0
        ? asArray(detail.representatives)
        : asArray(payload?.representatives)
      const firstRep = asRecord(reps[0])
      return {
        key: familyKey,
        label: "Combo",
        params: "strict AND",
        category: category.id,
        signalLabel: asString(detail.family_signal_label) || asString(payload?.signal_label) || null,
        score: asNumber(detail.family_score_pct) ?? asNumber(payload?.family_score_pct),
        representativeId: asString(firstRep?.variant_id) || asString(detail.best_variant_id) || null,
        factorDependencies: factorDependenciesFromReps(reps),
      }
    })
  }

  return INDICATOR_FAMILY_ORDER.flatMap((family) => {
    const meta = FAMILY_META_BY_KEY[family]
    const payload = asRecord(families[family])
    if (!payload) return []
    const detail = asRecord(payload.family_detail) ?? {}
    const reps = asArray(detail.representatives).length > 0
      ? asArray(detail.representatives)
      : asArray(payload.representatives)
    const firstRep = asRecord(reps[0])
    return [{
      key: family,
      label: meta.shortLabel,
      params: paramsLabel(meta),
      category: meta.category,
      signalLabel: asString(detail.family_signal_label) || asString(payload.signal_label) || null,
      score: asNumber(detail.family_score_pct) ?? asNumber(payload.family_score_pct),
      representativeId: asString(firstRep?.variant_id) || asString(detail.best_variant_id) || null,
      factorDependencies: factorDependenciesFromReps(reps),
    }]
  })
}

function extractRepresentativeIndicators(row: SignalBacktestResult | null): RepresentativeIndicator[] {
  const diagnostics = asRecord(row?.signal_diagnostics)
  const reps = asArray(diagnostics?.representatives)
  const seen = new Set<string>()
  const out: RepresentativeIndicator[] = []

  const addIndicator = (
    family: IndicatorFamilyKey,
    variantId: string,
    params: Record<string, number>,
    description?: string,
  ) => {
    if (!variantId) return
    const id = `${family}:${variantId}`
    if (seen.has(id)) return
    seen.add(id)
    out.push({
      id,
      family,
      variantId,
      description: description || representativeDisplayLabel(family, params),
      params,
    })
  }

  for (const rawRep of reps) {
    const rep = asRecord(rawRep)
    if (!rep) continue

    const rawParams = asRecord(rep.params) ?? {}
    const components = asArray(rawParams.components)
    if (components.length > 0) {
      let addedComponent = false
      components.forEach((rawComponent, index) => {
        const component = asRecord(rawComponent)
        if (!component) return
        const componentFamily = chartFamilyFromSignalFamily(asString(component.family))
        if (!componentFamily) return
        const parentVariantId = asString(rep.variant_id)
        const componentVariantId = asString(component.variant_id) || `${parentVariantId}:${componentFamily}:${index}`
        const componentParams = numericParamsFrom(component.params)
        const description = asString(component.description) || asString(component.label)
        addIndicator(componentFamily, componentVariantId, componentParams, description)
        addedComponent = true
      })
      if (addedComponent) continue
    }

    const family = chartFamilyFromSignalFamily(asString(rep.family))
    if (!family) continue
    const variantId = asString(rep.variant_id)
    if (!variantId) continue
    const params = numericParamsFrom(rawParams)
    addIndicator(family, variantId, params)
  }

  return out.slice(0, 8)
}

function sliceBacktestSeries(row: SignalBacktestResult | null, range: RangeKey) {
  const dates = row?.dates ?? null
  const close = row?.close_series ?? null
  const position = row?.position_series ?? null
  if (!dates || !close || !position) return { dates, close, position, start: 0 }
  const limit = RANGE_TO_BARS[range]
  const start = limit ? Math.max(0, dates.length - limit) : 0
  return {
    dates: dates.slice(start),
    close: close.slice(start),
    position: position.slice(start),
    start,
  }
}

function dateKey(value: unknown): string | null {
  if (typeof value !== "string") return null
  const key = value.slice(0, 10)
  return /^\d{4}-\d{2}-\d{2}$/.test(key) ? key : null
}

function filterLedgerByDates(
  ledger: SignalBacktestResult["trade_ledger"] | null | undefined,
  dates: string[] | null | undefined,
) {
  if (ledger == null) return ledger
  if (!dates || dates.length === 0) return ledger

  const startDate = dateKey(dates[0])
  const endDate = dateKey(dates[dates.length - 1])
  if (!startDate || !endDate) return ledger

  return ledger.filter((entry) => {
    const entryDate = dateKey(entry.date)
    return entryDate != null && entryDate >= startDate && entryDate <= endDate
  })
}

function hasBacktestChartPayload(row: SignalBacktestResult | null): boolean {
  return Boolean(
    row?.dates
    && row.close_series
    && row.position_series
    && row.dates.length > 1
    && row.close_series.length > 1
    && row.position_series.length > 1,
  )
}

function sliceIndicatorSeries(series: IndicatorOverlaySeries[], start: number): IndicatorOverlaySeries[] {
  return series.map((item) => ({
    ...item,
    values: item.values.slice(start),
    overlayValues: item.overlayValues?.slice(start),
    macdLineValues: item.macdLineValues?.slice(start),
  }))
}

function wfoLabelForFamily(wfoData: WfoSummaryResponse | null, family: string, category: CategoryId): string | null {
  const cat = wfoData?.categories?.[category]
  if (!cat || cat.status !== "succeeded") return null
  if (family.includes("_combo_") || family === "Combo") return cat.signal_label ?? null
  return cat.representatives.find((rep) => rep.family === family)?.signal_label ?? null
}

function CompactSignalBadge({ label }: { label: string | null }) {
  if (!label) return <span className="text-[10px] text-muted-foreground">--</span>
  return (
    <span className={cn("inline-flex rounded px-1.5 py-0.5 text-[10px] font-semibold", signalClass(label))}>
      {label}
    </span>
  )
}

function IndicatorResultsColumn({
  rows,
  wfoData,
  symbol,
  horizon,
  variant,
  cooldownBars,
}: {
  rows: FamilySignalRow[]
  wfoData: WfoSummaryResponse | null
  symbol: string
  horizon: string
  variant: string
  cooldownBars: number
}) {
  const router = useRouter()

  return (
    <div className="flex flex-col gap-3 xl:w-[340px] xl:shrink-0">
      {CATEGORY_META.map((category) => {
        const categoryRows = rows.filter((row) => row.category === category.id)
        const categoryScore = mean(categoryRows.map((row) => row.score))
        const categoryWfo = wfoData?.categories?.[category.id]
        const Icon = category.icon
        return (
          <div key={category.id} className="overflow-hidden rounded-md border border-line bg-card shadow-sm">
            <div className="border-b border-line bg-bg3 px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  <span className="truncate text-xs font-bold">{category.label}</span>
                </div>
                <span className={cn("font-mono text-xs font-semibold", signalScoreTone(categoryScore))}>
                  {scoreText(categoryScore)}
                </span>
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-1.5">
                <Badge variant="outline" className="h-5 text-[9px]">
                  SE {categoryRows.filter((row) => row.signalLabel).length}/{categoryRows.length}
                </Badge>
                <Badge variant="outline" className="h-5 text-[9px]">
                  WFO {categoryWfo?.status ?? "pending"}
                </Badge>
                <CompactSignalBadge label={categoryWfo?.signal_label ?? null} />
              </div>
            </div>
            <div className="divide-y divide-border/50">
              {categoryRows.length > 0 ? categoryRows.map((row) => {
                const wfoLabel = wfoLabelForFamily(wfoData, row.key, category.id)
                return (
                  <button
                    key={row.key}
                    type="button"
                    disabled={!row.representativeId}
                    onClick={() => {
                      if (!row.representativeId) return
                      router.push(
                        `/signals/variant/${encodeURIComponent(row.representativeId)}?symbol=${encodeURIComponent(symbol)}&horizon=${horizon}&cooldown=${cooldownBars}&variant=${variant}`,
                      )
                    }}
                    className="grid w-full grid-cols-[minmax(0,1fr)_auto] gap-2 px-3 py-2 text-left hover:bg-muted/30 disabled:cursor-default disabled:hover:bg-transparent"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-xs font-semibold">{row.label}</span>
                        {row.representativeId ? <ExternalLink className="h-3 w-3 shrink-0 text-muted-foreground" /> : null}
                      </div>
                      <div className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">{row.params}</div>
                      {row.factorDependencies.length > 0 ? (
                        <div className="mt-1 flex flex-wrap gap-1">
                          {row.factorDependencies.slice(0, 3).map((dependency) => (
                            <span
                              key={`${row.key}:${dependency.ticker}:${dependency.id}`}
                              className="inline-flex max-w-full items-center rounded border border-border bg-muted/35 px-1.5 py-0.5 text-[9px] font-semibold text-muted-foreground"
                              title={`${dependency.label} ${dependency.rule}`}
                            >
                              <span>{dependency.label}</span>
                              <span className="ml-1 font-mono font-normal">{dependency.rule}</span>
                            </span>
                          ))}
                          {row.factorDependencies.length > 3 ? (
                            <span className="text-[9px] text-muted-foreground">+{row.factorDependencies.length - 3}</span>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                    <div className="flex flex-col items-end gap-1">
                      <div className="flex items-center gap-1">
                        <span className="rounded bg-[oklch(0.94_0.04_260_/_0.4)] px-1 py-0.5 text-[9px] font-bold uppercase tracking-[0.06em] text-[oklch(0.30_0.14_260)]">SE</span>
                        <CompactSignalBadge label={row.signalLabel} />
                      </div>
                      <div className="flex items-center gap-1">
                        <span className="rounded bg-[oklch(0.95_0.06_80_/_0.5)] px-1 py-0.5 text-[9px] font-bold uppercase tracking-[0.06em] text-[oklch(0.35_0.10_80)]">WFO</span>
                        <CompactSignalBadge label={wfoLabel} />
                      </div>
                    </div>
                  </button>
                )
              }) : (
                <div className="px-2.5 py-3 text-xs text-muted-foreground">Aucun resultat.</div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function StatsStrip({ row }: { row: SignalBacktestResult | null }) {
  const metrics = row?.metrics
  const stats = [
    ["Return", formatPercent(metrics?.total_return), `${metrics?.n_trades ?? "--"} trades`],
    ["CAGR", formatPercent(metrics?.cagr), `${sourceLabel(row?.source)} / ${sidePolicyLabel(row?.side_policy)}`],
    ["Hit ratio", formatPercent(metrics?.win_rate), "historique"],
    ["Sharpe signal", formatNumber(metrics?.sharpe, 2), "net frais"],
  ]
  return (
    <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
      {stats.map(([label, value, sub]) => (
        <div key={label} className="rounded-md border border-line bg-card px-3 py-2">
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{label}</div>
          <div className={cn("mt-1 font-mono text-base font-bold", value.startsWith("+") ? "text-[oklch(0.50_0.13_165)]" : "")}>{value}</div>
          <div className="text-[10px] text-muted-foreground">{sub}</div>
        </div>
      ))}
    </div>
  )
}

function ledgerStatusMessage(row: SignalBacktestResult | null): string | null {
  if (!row) return "Aucun backtest directionnel disponible pour cette source."
  const ledger = row.trade_ledger
  if (ledger == null) return "Payload detaille manquant: relancez le backtest pour regenerer le ledger CMP."
  if (ledger.length > 0) return null

  const diagnostics = asRecord(row.signal_diagnostics)
  if (diagnostics?.flat_executed === true) {
    return "Backtest calcule, mais la position executee est restee plate: aucun achat/vente n'a ete genere."
  }
  if ((row.metrics?.n_trades ?? row.n_trades ?? 0) === 0) {
    return "Backtest calcule sans transition de position: aucun mouvement CMP a afficher."
  }
  return "Aucun mouvement CMP disponible pour ce resultat."
}

function TradeLedger({
  row,
  visibleDates,
}: {
  row: SignalBacktestResult | null
  visibleDates: string[] | null | undefined
}) {
  const ledger = row?.trade_ledger ?? null
  const visibleLedger = filterLedgerByDates(ledger, visibleDates)
  const statusMessage = ledgerStatusMessage(row)

  return (
    <div className="overflow-hidden rounded-md border border-line bg-bg2">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
        <div>
          <div className="text-sm font-semibold">Ledger CMP / OOS</div>
          <div className="text-[11px] text-muted-foreground">{sidePolicyLabel(row?.side_policy)}</div>
        </div>
        <span className="text-xs text-muted-foreground">
          {visibleLedger?.length ?? 0}
          {ledger && visibleLedger && visibleLedger.length !== ledger.length ? ` / ${ledger.length}` : ""} mouvements
        </span>
      </div>
      <div className="space-y-2 p-3">
        {statusMessage ? (
          <p className="rounded border border-line bg-card p-2 text-xs text-muted-foreground">
            {statusMessage}
          </p>
        ) : null}
        <AccountingTradeLedgerTable trades={visibleLedger} />
      </div>
    </div>
  )
}

export function SignalTechniqueDashboard({
  symbol,
  horizon,
  variant,
  cooldownBars,
}: {
  symbol: string
  horizon: string
  variant: string
  cooldownBars: number
}) {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const querySource = searchParams.get("source")
  const queryScope = searchParams.get("scope")
  const queryScopeKey = searchParams.get("scope_key")
  const [range, setRange] = useState<RangeKey>("6M")
  const [selectedSource, setSelectedSource] = useState<TechniqueSource>(() => techniqueSourceFromQuery(querySource))
  const [selectedScopeId, setSelectedScopeId] = useState(() => {
    const initialScope = scopeFromQuery(queryScope, queryScopeKey)
    return scopeOptionId(initialScope.scope, initialScope.scopeKey)
  })
  const { data: wfoData } = useWfoSummary(symbol, horizon, variant)
  const [engineResult, setEngineResult] = useState<SignalEngineResult | null>(null)
  const [engineLoading, setEngineLoading] = useState(false)
  const [backtestRows, setBacktestRows] = useState<SignalBacktestResult[]>([])
  const [backtestLoading, setBacktestLoading] = useState(false)
  const [backtestError, setBacktestError] = useState<string | null>(null)
  const [indicatorSeries, setIndicatorSeries] = useState<IndicatorOverlaySeries[]>([])
  const [indicatorLoading, setIndicatorLoading] = useState(false)
  const requestTokenRef = useRef(0)

  useEffect(() => {
    setSelectedSource(techniqueSourceFromQuery(querySource))
  }, [horizon, querySource, symbol, variant])

  useEffect(() => {
    const nextScope = scopeFromQuery(queryScope, queryScopeKey)
    setSelectedScopeId(scopeOptionId(nextScope.scope, nextScope.scopeKey))
  }, [horizon, queryScope, queryScopeKey, symbol, variant])

  function updateTechniqueQuery(updates: Record<string, string | null | undefined>) {
    const params = new URLSearchParams(searchParams.toString())
    for (const [key, value] of Object.entries(updates)) {
      if (value == null || value === "") {
        params.delete(key)
      } else {
        params.set(key, value)
      }
    }
    const query = params.toString()
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false })
  }

  useEffect(() => {
    const token = ++requestTokenRef.current
    setEngineLoading(true)

    fetchSignalEngineResultWithBootstrap(symbol, horizon, variant)
      .then((result) => {
        if (requestTokenRef.current === token) setEngineResult(result)
      })
      .catch(() => {
        if (requestTokenRef.current === token) setEngineResult(null)
      })
      .finally(() => {
        if (requestTokenRef.current === token) setEngineLoading(false)
      })

    return () => {
      requestTokenRef.current += 1
    }
  }, [horizon, symbol, variant])

  useEffect(() => {
    let cancelled = false
    setBacktestLoading(true)
    setBacktestError(null)
    setBacktestRows([])

    const request =
      selectedSource === "wfo"
        ? fetchBestSignalBacktestChart(symbol, horizon, { cooldownBars })
        : fetchSignalBacktestResultsWithBootstrap(symbol, horizon, variant, {
            source: "engine",
            cooldownBars,
          })

    request
      .then((res) => {
        if (cancelled) return
        const rows = res.results.filter((row) => row.status === "succeeded")
        setBacktestRows(rows)
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setBacktestRows([])
          setBacktestError(error instanceof Error ? error.message : String(error))
        }
      })
      .finally(() => {
        if (!cancelled) setBacktestLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [cooldownBars, horizon, selectedSource, symbol, variant])

  const sourceBacktestRows = useMemo(
    () => backtestRows.filter((row) => rowMatchesTechniqueSource(row, selectedSource)),
    [backtestRows, selectedSource],
  )
  const scopeOptions = useMemo<TechniqueScopeOption[]>(() => {
    const byId = new Map<string, TechniqueScopeOption>()
    for (const row of sourceBacktestRows) {
      const id = scopeOptionId(row.scope, row.scope_key)
      const existing = byId.get(id)
      if (existing) {
        existing.rowCount += 1
        continue
      }
      byId.set(id, {
        id,
        scope: row.scope,
        scopeKey: row.scope_key,
        label: scopeLabel(row.scope, row.scope_key),
        rowCount: 1,
      })
    }
    return Array.from(byId.values()).sort((left, right) => scopeSortKey(left).localeCompare(scopeSortKey(right)))
  }, [sourceBacktestRows])
  const activeScopeId = useMemo(() => {
    if (scopeOptions.some((option) => option.id === selectedScopeId)) return selectedScopeId
    return (
      scopeOptions.find((option) => option.scope === "global")?.id
      ?? scopeOptions[0]?.id
      ?? selectedScopeId
    )
  }, [scopeOptions, selectedScopeId])
  const activeScopeOption = useMemo(
    () => scopeOptions.find((option) => option.id === activeScopeId) ?? null,
    [activeScopeId, scopeOptions],
  )
  const backtestRow = useMemo(
    () =>
      sourceBacktestRows.find((row) => scopeOptionId(row.scope, row.scope_key) === activeScopeId)
      ?? sourceBacktestRows.find((row) => row.scope === "global")
      ?? sourceBacktestRows[0]
      ?? null,
    [activeScopeId, sourceBacktestRows],
  )

  const representatives = useMemo(() => extractRepresentativeIndicators(backtestRow), [backtestRow])

  useEffect(() => {
    if (!backtestRow?.dates || representatives.length === 0) {
      setIndicatorSeries([])
      return
    }

    let cancelled = false
    setIndicatorLoading(true)

    Promise.allSettled(
      representatives.map(async (rep) => {
        const series = await fetchIndicatorSeries({
          symbol,
          indicator: rep.family,
          params: rep.params,
          timeframe: "1D",
        })
        const byDate = new Map<string, number | null>()
        const overlayByDate = new Map<string, number | null>()
        const macdByDate = new Map<string, number | null>()
        const plotPayload = asRecord(series.plot_payload)
        const macdLine = Array.isArray(plotPayload?.macd_line) ? plotPayload.macd_line : null
        series.dates.forEach((date, index) => {
          const value = series.indicator_values[index]
          const overlayValue = series.indicator_overlay?.[index]
          const macdValue = macdLine?.[index]
          byDate.set(date, typeof value === "number" && Number.isFinite(value) ? value : null)
          overlayByDate.set(date, typeof overlayValue === "number" && Number.isFinite(overlayValue) ? overlayValue : null)
          macdByDate.set(date, typeof macdValue === "number" && Number.isFinite(macdValue) ? macdValue : null)
        })
        return {
          id: rep.id,
          label: rep.description,
          values: (backtestRow.dates ?? []).map((date) => byDate.get(date) ?? null),
          overlayValues: series.indicator_overlay
            ? (backtestRow.dates ?? []).map((date) => overlayByDate.get(date) ?? null)
            : undefined,
          macdLineValues: macdLine
            ? (backtestRow.dates ?? []).map((date) => macdByDate.get(date) ?? null)
            : undefined,
          axis: PRICE_AXIS_FAMILIES.has(rep.family) ? "price" : "indicator",
          family: rep.family,
          category: FAMILY_META_BY_KEY[rep.family]?.category,
          params: rep.params,
        } satisfies IndicatorOverlaySeries
      }),
    )
      .then((results) => {
        if (cancelled) return
        setIndicatorSeries(
          results.flatMap((result) => (result.status === "fulfilled" ? [result.value] : [])),
        )
      })
      .finally(() => {
        if (!cancelled) setIndicatorLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [backtestRow, representatives, symbol])

  const rows = useMemo(() => normalizeFamilies(engineResult, variant), [engineResult, variant])
  const sliced = useMemo(() => sliceBacktestSeries(backtestRow, range), [backtestRow, range])
  const hasChartData = hasBacktestChartPayload(backtestRow)
  const visibleLedger = useMemo(
    () => filterLedgerByDates(backtestRow?.trade_ledger ?? null, sliced.dates),
    [backtestRow?.trade_ledger, sliced.dates],
  )
  const visibleIndicatorSeries = useMemo(
    () => sliceIndicatorSeries(indicatorSeries, sliced.start),
    [indicatorSeries, sliced.start],
  )

  return (
    <div className="flex gap-3.5 max-xl:flex-col">
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <Card className="overflow-hidden rounded-md">
          <CardHeader className="flex flex-row items-center justify-between border-b border-line px-3 py-2">
            <div>
              <CardTitle className="text-sm">Backtest directionnel du signal</CardTitle>
              <p className="text-[11px] text-muted-foreground">
                Source: {sourceLabel(backtestRow?.source ?? selectedSource)} / {activeScopeOption?.label ?? scopeLabel(backtestRow?.scope, backtestRow?.scope_key)}
                {backtestRow?.side_policy ? ` / ${sidePolicyLabel(backtestRow.side_policy)}` : ""}
                {backtestLoading ? " / calcul OOS automatique..." : ""}
                {indicatorLoading ? " / chargement indicateurs..." : ""}
              </p>
            </div>
            <div className="flex flex-wrap justify-end gap-2">
              <span className="inline-flex rounded-md border border-line bg-bg2 p-0.5">
                {TECHNIQUE_SOURCES.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => {
                      setSelectedSource(item.key)
                      updateTechniqueQuery({ source: item.key === "wfo" ? "wfo" : "signal_engine" })
                    }}
                    className={cn(
                      "h-[22px] rounded px-2 text-[11px] text-muted-foreground",
                      selectedSource === item.key && "bg-card font-semibold text-foreground",
                    )}
                  >
                    {item.label}
                  </button>
                ))}
              </span>
              {scopeOptions.length > 0 ? (
                <span className="signals-scrollbar inline-flex max-w-[460px] overflow-x-auto rounded-md border border-line bg-bg2 p-0.5">
                  {scopeOptions.map((option) => (
                    <button
                      key={option.id}
                      type="button"
                      onClick={() => {
                        setSelectedScopeId(option.id)
                        updateTechniqueQuery({
                          scope: option.scope,
                          scope_key: option.scopeKey,
                        })
                      }}
                      className={cn(
                        "h-[22px] shrink-0 rounded px-2 text-[11px] text-muted-foreground",
                        activeScopeId === option.id && "bg-card font-semibold text-foreground",
                      )}
                    >
                      {option.label}
                    </button>
                  ))}
                </span>
              ) : null}
              <span className="inline-flex rounded-md border border-line bg-bg2 p-0.5">
                {(Object.keys(RANGE_TO_BARS) as RangeKey[]).map((key) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setRange(key)}
                    className={cn(
                      "h-[22px] rounded px-2 text-[11px] text-muted-foreground",
                      range === key && "bg-card font-semibold text-foreground",
                    )}
                  >
                    {key}
                  </button>
                ))}
              </span>
            </div>
          </CardHeader>
          <CardContent className="space-y-3 p-3">
            {backtestLoading && !hasChartData ? (
              <div className="space-y-2 p-2">
                <Skeleton className="h-[330px] w-full rounded-md" />
                <p className="text-xs text-muted-foreground">
                  Chargement des prix, positions et trades OOS. Si le resultat detaille ou directionnel manque, le backtest est lance automatiquement.
                </p>
              </div>
            ) : hasChartData ? (
              <PriceSignalsChart
                close={sliced.close}
                position={sliced.position}
                dates={sliced.dates}
                indicatorSeries={visibleIndicatorSeries}
                tradeMarkers={visibleLedger}
                height={520}
                maxHeight={560}
                title={undefined}
              />
            ) : (
              <p className="rounded border border-line bg-muted/20 p-3 text-xs text-muted-foreground">
                {backtestError ?? `Aucun resultat OOS detaille disponible pour ${selectedSource === "wfo" ? "WFO" : "Signal Engine"}.`}
              </p>
            )}

            {representatives.length > 0 ? (
              <div className="signals-scrollbar flex gap-1.5 overflow-x-auto">
                {representatives.map((rep) => (
                  <span
                    key={rep.id}
                    className="inline-flex h-[22px] shrink-0 items-center rounded border border-line bg-bg2 px-2 text-[10px] text-muted-foreground"
                    title={rep.variantId}
                  >
                    {rep.description}
                  </span>
                ))}
              </div>
            ) : null}

            <StatsStrip row={backtestRow} />
            <TradeLedger row={backtestRow} visibleDates={sliced.dates} />
          </CardContent>
        </Card>
      </div>

      {engineLoading && rows.length === 0 ? (
        <div className="flex flex-col gap-3 xl:w-[340px] xl:shrink-0">
          {[...Array(4)].map((_, index) => <Skeleton key={index} className="h-40 w-full rounded-md" />)}
        </div>
      ) : (
        <IndicatorResultsColumn
          rows={rows}
          wfoData={wfoData}
          symbol={symbol}
          horizon={horizon}
          variant={variant}
          cooldownBars={cooldownBars}
        />
      )}
    </div>
  )
}
