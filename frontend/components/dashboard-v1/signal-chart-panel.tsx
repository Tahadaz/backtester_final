"use client"

import Link from "next/link"
import { useEffect, useMemo, useState } from "react"
import { PriceSignalsChart, type IndicatorOverlaySeries } from "@/components/signals/price-signals-chart"
import { useStockOhlcvHistory } from "@/hooks/use-api"
import {
  fetchIndicatorSeries,
  fetchSignalEngineResult,
  fetchWfoSummary,
  type IndicatorLiveBar,
  type IndicatorSeriesResponse,
  type OhlcvBar,
  type SignalEngineResult,
  type WfoSummaryResponse,
} from "@/lib/api"
import type {
  DashboardDisplayMode,
  DashboardStock,
  DashboardTechnicalDirectionMode,
  Horizon,
} from "@/lib/dashboard-types"
import {
  INDICATOR_CATEGORY_BY_FAMILY,
  asNumber,
  asRecord,
  asText,
  chartTimeKey,
  chartFamilyFromSignalFamily,
  liveBarFromQuote,
  mergeLiveBarIntoBars,
  numericParamsFrom,
  resolveDashboardSignalDescriptor,
} from "@/lib/dashboard-signal-chart-utils.js"
import { cn } from "@/lib/utils"

type RangeKey = "3M" | "6M" | "1Y" | "All"

interface DashboardSignalChartPanelProps {
  stock: DashboardStock
  horizon: Horizon
  horizonDays: number
  displayMode: DashboardDisplayMode
  technicalDirectionMode: DashboardTechnicalDirectionMode
  evidenceHref: string
}

interface IndicatorDescriptor {
  id: string
  family: string
  label: string
  params: Record<string, number>
  category?: string
}

type SignalDescriptor = {
  kind: "trade" | "technical"
  source: "signal_engine" | "wfo" | string
  variant: string | null
  direction: "long" | "short" | "none"
  label: string
  signal_label?: string | null
}

const RANGE_TO_BARS: Record<RangeKey, number | null> = {
  "3M": 66,
  "6M": 132,
  "1Y": 252,
  All: null,
}
const INTRADAY_RANGE_TO_BARS: Record<RangeKey, number | null> = {
  "3M": 390,
  "6M": 780,
  "1Y": 1560,
  All: null,
}

const RANGE_OPTIONS: RangeKey[] = ["3M", "6M", "1Y", "All"]
const MAX_INDICATORS = 10
const TECHNICAL_CHART_TIMEFRAME: string = "1H"
const PRICE_AXIS_FAMILIES = new Set(["sma", "ema", "ema_cross", "ichimoku", "psar", "vwap"])
const CATEGORY_BY_FAMILY = INDICATOR_CATEGORY_BY_FAMILY as Record<string, string>

const CLASSIC_DESCRIPTORS: IndicatorDescriptor[] = [
  { id: "classic:sma:50", family: "sma", label: "SMA 50", params: { period: 50 }, category: "tendance" },
  { id: "classic:sma:200", family: "sma", label: "SMA 200", params: { period: 200 }, category: "tendance" },
  { id: "classic:macd:12-26-9", family: "macd", label: "MACD 12 26 9", params: { fast: 12, slow: 26, signal: 9 }, category: "momentum" },
  { id: "classic:rsi:14", family: "rsi", label: "RSI 14", params: { period: 14, oversold: 30, overbought: 70 }, category: "oscillation" },
  { id: "classic:obv:20", family: "obv", label: "OBV EMA 20", params: { ema_period: 20 }, category: "volume" },
]

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function canonicalIndicatorParams(family: string, params: Record<string, number>): Record<string, number> {
  if (family === "sma" && params.window != null) return { window: params.window }
  if (family === "sma" && params.period != null) return { period: params.period }
  if (family === "ema" && params.window == null && params.period != null) return { window: params.period }
  if (family === "rsi" || family === "mfi") {
    return {
      ...params,
      oversold: params.oversold ?? 30,
      overbought: params.overbought ?? 70,
    }
  }
  return params
}

function numericParams(raw: unknown): Record<string, number> {
  return numericParamsFrom(raw) as Record<string, number>
}

function descriptorKey(family: string, params: Record<string, number>) {
  const body = Object.keys(params)
    .sort()
    .map((key) => `${key}:${params[key]}`)
    .join("|")
  return `${family}:${body}`
}

function dedupeDescriptors(descriptors: IndicatorDescriptor[]): IndicatorDescriptor[] {
  const seen = new Set<string>()
  const out: IndicatorDescriptor[] = []
  for (const descriptor of descriptors) {
    const key = descriptorKey(descriptor.family, descriptor.params)
    if (seen.has(key)) continue
    seen.add(key)
    out.push(descriptor)
    if (out.length >= MAX_INDICATORS) break
  }
  return out
}

function representativeDescriptor(rawRep: unknown, fallbackCategory?: string, fallbackId?: string): IndicatorDescriptor | null {
  const rep = asRecord(rawRep) as Record<string, unknown> | null
  if (!rep) return null
  const family = chartFamilyFromSignalFamily(asText(rep.family))
  if (!family) return null
  const params = canonicalIndicatorParams(family, numericParams(rep.params))
  const id = asText(rep.variant_id) || asText(rep.archetype) || fallbackId || descriptorKey(family, params)
  const label = asText(rep.description) || asText(rep.signal_label) || `${family.toUpperCase()} ${Object.values(params).join(" ")}`
  return {
    id: `${family}:${id}`,
    family,
    label,
    params,
    category: fallbackCategory || CATEGORY_BY_FAMILY[family],
  }
}

function componentDescriptorsFromRepresentative(rawRep: unknown, fallbackCategory?: string): IndicatorDescriptor[] {
  const rep = asRecord(rawRep) as Record<string, unknown> | null
  if (!rep) return []
  const params = asRecord(rep.params) as Record<string, unknown> | null
  const components = asArray(params?.components)
  if (components.length === 0) return []

  return components.flatMap((rawComponent, index) => {
    const component = asRecord(rawComponent) as Record<string, unknown> | null
    if (!component) return []
    const family = chartFamilyFromSignalFamily(asText(component.family))
    if (!family) return []
    const componentParams = canonicalIndicatorParams(family, numericParams(component.params))
    const parentId = asText(rep.variant_id) || "combo"
    const id = asText(component.variant_id) || `${parentId}:${family}:${index}`
    const label = asText(component.description) || asText(component.label) || `${family.toUpperCase()} ${Object.values(componentParams).join(" ")}`
    return [{
      id: `${family}:${id}`,
      family,
      label,
      params: componentParams,
      category: fallbackCategory || CATEGORY_BY_FAMILY[family],
    }]
  })
}

function descriptorsFromWfo(summary: WfoSummaryResponse): IndicatorDescriptor[] {
  const descriptors: IndicatorDescriptor[] = []
  for (const [category, payload] of Object.entries(summary.categories ?? {})) {
    for (const rep of payload.representatives ?? []) {
      descriptors.push(...componentDescriptorsFromRepresentative(rep, category))
      const direct = representativeDescriptor(rep, category)
      if (direct) descriptors.push(direct)
    }
  }
  return dedupeDescriptors(descriptors)
}

function descriptorsFromSignalEngine(result: SignalEngineResult): IndicatorDescriptor[] {
  const families = asRecord(result.families) as Record<string, unknown> | null
  const descriptors: IndicatorDescriptor[] = []
  for (const [familyKey, rawPayload] of Object.entries(families ?? {})) {
    const payload = asRecord(rawPayload) as Record<string, unknown> | null
    if (!payload) continue
    const detail = (asRecord(payload.family_detail) ?? {}) as Record<string, unknown>
    const reps = asArray(detail.representatives).length > 0
      ? asArray(detail.representatives)
      : asArray(payload.representatives)
    const family = chartFamilyFromSignalFamily(familyKey)
    const fallbackCategory = family ? CATEGORY_BY_FAMILY[family] : undefined
    for (const rep of reps) {
      const components = componentDescriptorsFromRepresentative(rep, fallbackCategory)
      if (components.length > 0) {
        descriptors.push(...components)
        continue
      }
      const direct = representativeDescriptor(rep, fallbackCategory)
      if (direct) descriptors.push(direct)
    }
  }
  return dedupeDescriptors(descriptors)
}

function chartBarsFromHistory(historyBars: OhlcvBar[] | undefined, liveBar: IndicatorLiveBar | null) {
  const merged = mergeLiveBarIntoBars(historyBars ?? [], liveBar)
  return {
    bars: merged.bars
      .map((bar: OhlcvBar) => ({
        date: chartTimeKey(bar.date),
        open: asNumber(bar.open),
        high: asNumber(bar.high),
        low: asNumber(bar.low),
        close: asNumber(bar.close),
        volume: asNumber(bar.volume),
      }))
      .filter((bar: { date: string | null; close: number | null }) => bar.date && bar.close != null),
    liveApplied: Boolean(merged.applied),
  }
}

function sliceBars<T>(bars: T[], range: RangeKey, timeframe: string): T[] {
  const limit = timeframe === "1H" ? INTRADAY_RANGE_TO_BARS[range] : RANGE_TO_BARS[range]
  return limit ? bars.slice(Math.max(0, bars.length - limit)) : bars
}

function positionSeries(length: number, direction: string | null | undefined): Array<number | null> {
  const values = Array.from({ length }, () => 0)
  if (length === 0) return values
  if (direction === "long") values[length - 1] = 1
  if (direction === "short") values[length - 1] = -1
  return values
}

function indicatorPayloadRecord(response: IndicatorSeriesResponse): Record<string, unknown> {
  return (asRecord(response.plot_payload) ?? {}) as Record<string, unknown>
}

function alignIndicatorSeries(
  descriptor: IndicatorDescriptor,
  response: IndicatorSeriesResponse,
  dates: string[],
): IndicatorOverlaySeries {
  const valueByDate = new Map<string, number | null>()
  const overlayByDate = new Map<string, number | null>()
  const macdByDate = new Map<string, number | null>()
  const payload = indicatorPayloadRecord(response)
  const macdLine = Array.isArray(payload.macd_line) ? payload.macd_line : null

  response.dates.forEach((date, index) => {
    const key = chartTimeKey(date)
    if (!key) return
    const value = asNumber(response.indicator_values[index])
    const overlayValue = asNumber(response.indicator_overlay?.[index])
    const macdValue = macdLine ? asNumber(macdLine[index]) : null
    valueByDate.set(key, value)
    overlayByDate.set(key, overlayValue)
    macdByDate.set(key, macdValue)
  })

  return {
    id: descriptor.id,
    label: descriptor.label,
    values: dates.map((date) => valueByDate.get(date) ?? null),
    overlayValues: response.indicator_overlay
      ? dates.map((date) => overlayByDate.get(date) ?? null)
      : undefined,
    macdLineValues: macdLine
      ? dates.map((date) => macdByDate.get(date) ?? null)
      : undefined,
    axis: PRICE_AXIS_FAMILIES.has(descriptor.family) ? "price" : "indicator",
    family: descriptor.family,
    category: descriptor.category,
    params: descriptor.params,
  }
}

function useSignalIndicatorDescriptors(
  stock: DashboardStock,
  horizon: Horizon,
  signal: SignalDescriptor | null,
) {
  const [descriptors, setDescriptors] = useState<IndicatorDescriptor[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!signal) {
      setDescriptors([])
      setLoading(false)
      setError(null)
      return
    }

    if (signal.variant === "classic_ta" || signal.variant === "legacy_ta_simple") {
      setDescriptors(CLASSIC_DESCRIPTORS)
      setLoading(false)
      setError(null)
      return
    }

    let cancelled = false
    setLoading(true)
    setError(null)

    const request = signal.source === "wfo"
      ? fetchWfoSummary(stock.symbol, horizon, signal.variant ?? "expanded").then(descriptorsFromWfo)
      : fetchSignalEngineResult(stock.symbol, horizon, signal.variant ?? "expanded").then(descriptorsFromSignalEngine)

    request
      .then((nextDescriptors) => {
        if (cancelled) return
        setDescriptors(nextDescriptors)
        setError(nextDescriptors.length === 0 ? "missing" : null)
      })
      .catch(() => {
        if (cancelled) return
        setDescriptors([])
        setError("missing")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [horizon, signal?.source, signal?.variant, stock.symbol])

  return { descriptors, loading, error }
}

export function DashboardSignalChartPanel({
  stock,
  horizon,
  horizonDays,
  displayMode,
  technicalDirectionMode,
  evidenceHref,
}: DashboardSignalChartPanelProps) {
  const [range, setRange] = useState<RangeKey>("6M")
  const liveBar = useMemo(() => liveBarFromQuote(stock.live_quote) as IndicatorLiveBar | null, [stock.live_quote])
  const chartLiveBar = TECHNICAL_CHART_TIMEFRAME === "1D" ? liveBar : null
  const chartLiveBarKey = useMemo(() => JSON.stringify(chartLiveBar ?? null), [chartLiveBar])
  const signal = useMemo(
    () => resolveDashboardSignalDescriptor(stock, displayMode, technicalDirectionMode) as SignalDescriptor | null,
    [displayMode, stock, technicalDirectionMode],
  )
  const { data: history, isLoading: historyLoading } = useStockOhlcvHistory(stock.symbol, { timeframe: TECHNICAL_CHART_TIMEFRAME })
  const { descriptors, loading: descriptorsLoading, error: descriptorsError } = useSignalIndicatorDescriptors(stock, horizon, signal)
  const [indicatorSeries, setIndicatorSeries] = useState<IndicatorOverlaySeries[]>([])
  const [indicatorLoading, setIndicatorLoading] = useState(false)
  const [indicatorError, setIndicatorError] = useState(false)

  const merged = useMemo(() => chartBarsFromHistory(history?.bars, chartLiveBar), [history?.bars, chartLiveBar])
  const visibleBars = useMemo(() => sliceBars(merged.bars, range, TECHNICAL_CHART_TIMEFRAME), [merged.bars, range])
  const dates = useMemo(() => visibleBars.map((bar) => bar.date as string), [visibleBars])
  const open = useMemo(() => visibleBars.map((bar) => bar.open), [visibleBars])
  const high = useMemo(() => visibleBars.map((bar) => bar.high), [visibleBars])
  const low = useMemo(() => visibleBars.map((bar) => bar.low), [visibleBars])
  const close = useMemo(() => visibleBars.map((bar) => bar.close), [visibleBars])
  const position = useMemo(() => positionSeries(dates.length, signal?.direction), [dates.length, signal?.direction])
  const descriptorKeyValue = useMemo(
    () => descriptors.map((descriptor) => descriptorKey(descriptor.family, descriptor.params)).join("||"),
    [descriptors],
  )

  useEffect(() => {
    if (descriptors.length === 0 || dates.length === 0) {
      setIndicatorSeries([])
      setIndicatorLoading(false)
      setIndicatorError(false)
      return
    }

    let cancelled = false
    setIndicatorLoading(true)
    setIndicatorError(false)

    Promise.allSettled(
      descriptors.map(async (descriptor) => {
        const response = await fetchIndicatorSeries({
          symbol: stock.symbol,
          indicator: descriptor.family,
          params: descriptor.params,
          timeframe: TECHNICAL_CHART_TIMEFRAME,
          live_bar: chartLiveBar,
        })
        return alignIndicatorSeries(descriptor, response, dates)
      }),
    )
      .then((results) => {
        if (cancelled) return
        setIndicatorSeries(results.flatMap((result) => (result.status === "fulfilled" ? [result.value] : [])))
        setIndicatorError(results.some((result) => result.status === "rejected"))
      })
      .finally(() => {
        if (!cancelled) setIndicatorLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [dates, descriptorKeyValue, descriptors, chartLiveBar, chartLiveBarKey, stock.symbol])

  const latestClose = close.length > 0 ? close[close.length - 1] : null
  const statusLabel = merged.liveApplied ? "Live" : "Close"
  const signalLabel = signal?.signal_label || signal?.label || "No signal"
  const directionLabel = signal?.direction === "long" ? "Long" : signal?.direction === "short" ? "Short" : "Neutral"
  const hasChartData = dates.length >= 2 && close.length >= 2
  const showIndicatorUnavailable = !descriptorsLoading && !indicatorLoading && (descriptorsError || (signal && descriptors.length === 0))

  return (
    <div className="border-t border-border bg-background px-3 py-3">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="dashboard-mono text-[13px] font-bold">{stock.symbol}</span>
            <span className="rounded border border-border bg-card px-2 py-0.5 text-[11px] font-semibold text-muted-foreground">
              {directionLabel}
            </span>
            <span className="dashboard-mono text-[11px] text-muted-foreground">{statusLabel}</span>
          </div>
          <div className="mt-1 truncate text-[12px] text-muted-foreground">
            {signalLabel} · {latestClose != null ? latestClose.toLocaleString("fr-FR", { maximumFractionDigits: 2 }) : "--"} · {horizonDays} j · {TECHNICAL_CHART_TIMEFRAME}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          {RANGE_OPTIONS.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setRange(option)}
              className={cn(
                "h-7 rounded border px-2 text-[11px] font-semibold",
                range === option
                  ? "border-foreground bg-foreground text-background"
                  : "border-border bg-card text-muted-foreground hover:text-foreground",
              )}
            >
              {option}
            </button>
          ))}
        </div>
      </div>

      {historyLoading ? (
        <div className="h-[380px] rounded-md border border-dashed border-border bg-muted/20" />
      ) : hasChartData ? (
        <PriceSignalsChart
          dates={dates}
          open={open}
          high={high}
          low={low}
          close={close}
          position={position}
          title={`${stock.symbol} ${directionLabel}`}
          indicatorSeries={indicatorSeries}
          height={360}
          maxHeight={620}
        />
      ) : (
        <div className="rounded-md border border-dashed border-border px-4 py-10 text-center text-[12px] text-muted-foreground">
          Historique prix indisponible.
        </div>
      )}

      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted-foreground">
        <div>
          {descriptorsLoading || indicatorLoading
            ? "Chargement indicateurs..."
            : indicatorSeries.length > 0
              ? `${indicatorSeries.length} indicateurs`
              : showIndicatorUnavailable
                ? "Indicateurs indisponibles"
                : "Prix uniquement"}
          {indicatorError ? " · partiel" : ""}
        </div>
        <Link href={evidenceHref} className="font-semibold text-foreground hover:underline">
          Voir detail
        </Link>
      </div>
    </div>
  )
}
