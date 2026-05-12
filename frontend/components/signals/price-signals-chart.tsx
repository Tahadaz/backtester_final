"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type LineData,
  type SeriesMarker,
  type Time,
} from "lightweight-charts"
import { filterTradeMarkersByKind, normalizeTradeMarkers } from "@/lib/trade-marker-utils"
import { cn } from "@/lib/utils"

export interface IndicatorOverlaySeries {
  id: string
  label: string
  values: Array<number | null>
  overlayValues?: Array<number | null>
  macdLineValues?: Array<number | null>
  axis?: "price" | "indicator"
  family?: string
  category?: string
  params?: Record<string, number>
}

interface PriceSignalsChartProps {
  open?: number[] | null | undefined
  high?: number[] | null | undefined
  low?: number[] | null | undefined
  close: number[] | null | undefined
  position: number[] | null | undefined
  dates: string[] | null | undefined
  title?: string
  indicatorSeries?: IndicatorOverlaySeries[]
  tradeMarkers?: Array<Record<string, unknown>> | null
  height?: number
  maxHeight?: number
}

const COLORS = [
  "#2563eb",
  "#0f766e",
  "#7c3aed",
  "#ea580c",
  "#0891b2",
  "#db2777",
  "#65a30d",
  "#0d9488",
]

const PRICE_AXIS_FAMILIES = new Set(["sma", "ema", "ema_cross", "ichimoku", "psar", "vwap"])
const RSI_STYLE_FAMILIES = new Set(["rsi", "mfi", "stochastic", "uo"])
const MARKER_KIND_ORDER = ["buy", "sell", "short", "cover"] as const
const MARKER_META: Record<TradeMarkerKind, { label: string; color: string }> = {
  buy: { label: "Buy", color: "#16a34a" },
  sell: { label: "Sell", color: "#f97316" },
  short: { label: "Short", color: "#dc2626" },
  cover: { label: "Cover", color: "#7c3aed" },
}
const CATEGORY_ORDER = ["tendance", "momentum", "oscillation", "volume"] as const
const CATEGORY_LABELS: Record<string, string> = {
  tendance: "Tendance",
  momentum: "Momentum",
  oscillation: "Oscillation",
  volume: "Volume",
}

type PanelKind = "rsi" | "macd" | "oscillator" | "indicator"
type TradeMarkerKind = typeof MARKER_KIND_ORDER[number]
type IndicatorCategory = typeof CATEGORY_ORDER[number] | string
type ChartTradeMarker = SeriesMarker<Time> & { kind: TradeMarkerKind }

type IndicatorPanel = {
  key: string
  title: string
  kind: PanelKind
  series: IndicatorOverlaySeries[]
}

function toTime(date: string): Time {
  return date as unknown as Time
}

function finiteValue(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

function lowerText(series: IndicatorOverlaySeries) {
  return `${series.family ?? ""} ${series.id} ${series.label}`.toLowerCase()
}

function indicatorFamily(series: IndicatorOverlaySeries): string {
  const explicit = series.family?.toLowerCase().trim()
  if (explicit) return explicit
  const text = lowerText(series)
  if (text.includes("macd")) return "macd"
  if (text.includes("rsi")) return "rsi"
  if (text.includes("mfi")) return "mfi"
  if (text.includes("stochastic") || text.includes("%k") || text.includes("%d")) return "stochastic"
  if (text.includes("ultimate") || text.includes("uo")) return "uo"
  if (text.includes("obv")) return "obv"
  if (text.includes("adx")) return "adx"
  if (text.includes("cci")) return "cci"
  return "indicator"
}

function panelMetaFor(series: IndicatorOverlaySeries): { key: string; title: string; kind: PanelKind } {
  const family = indicatorFamily(series)
  if (family === "macd") return { key: "macd", title: "MACD", kind: "macd" }
  if (family === "rsi") return { key: "rsi", title: "RSI", kind: "rsi" }
  if (RSI_STYLE_FAMILIES.has(family)) {
    const title = family === "mfi" ? "MFI" : family === "stochastic" ? "Stochastic" : "Oscillator"
    return { key: family, title, kind: "oscillator" }
  }
  return { key: family, title: family.toUpperCase(), kind: "indicator" }
}

function isPriceSeries(series: IndicatorOverlaySeries): boolean {
  if (series.axis === "price") return true
  if (series.axis === "indicator") return false
  return PRICE_AXIS_FAMILIES.has(indicatorFamily(series))
}

function lineData(dates: string[], values: Array<number | null | undefined>): LineData[] {
  const data: LineData[] = []
  const length = Math.min(dates.length, values.length)
  for (let index = 0; index < length; index += 1) {
    const value = finiteValue(values[index])
    if (value != null) data.push({ time: toTime(dates[index]!), value })
  }
  return data
}

function candleData(
  dates: string[],
  open: Array<number | null | undefined>,
  high: Array<number | null | undefined>,
  low: Array<number | null | undefined>,
  close: Array<number | null | undefined>,
): CandlestickData[] {
  const data: CandlestickData[] = []
  const length = Math.min(dates.length, open.length, high.length, low.length, close.length)
  for (let index = 0; index < length; index += 1) {
    const openValue = finiteValue(open[index])
    const highValue = finiteValue(high[index])
    const lowValue = finiteValue(low[index])
    const closeValue = finiteValue(close[index])
    if (openValue == null || highValue == null || lowValue == null || closeValue == null) continue
    data.push({
      time: toTime(dates[index]!),
      open: openValue,
      high: highValue,
      low: lowValue,
      close: closeValue,
    })
  }
  return data
}

function histogramData(dates: string[], values: Array<number | null | undefined>): HistogramData[] {
  const data: HistogramData[] = []
  const length = Math.min(dates.length, values.length)
  for (let index = 0; index < length; index += 1) {
    const value = finiteValue(values[index])
    if (value == null) continue
    data.push({
      time: toTime(dates[index]!),
      value,
      color: value >= 0 ? "rgba(22, 163, 74, 0.78)" : "rgba(220, 38, 38, 0.78)",
    })
  }
  return data
}

function panelSubtitle(series: IndicatorOverlaySeries) {
  const family = indicatorFamily(series)
  if (family === "macd") return "histogram + MACD + signal"
  if (family === "rsi") {
    const low = series.params?.oversold ?? 30
    const high = series.params?.overbought ?? 70
    return `oversold ${low} / overbought ${high}`
  }
  if (RSI_STYLE_FAMILIES.has(family)) return "threshold pane"
  if (isPriceSeries(series)) return "price overlay"
  return "indicator pane"
}

function buildPanels(series: IndicatorOverlaySeries[]): IndicatorPanel[] {
  return Array.from(
    series.reduce((map, item) => {
      const meta = panelMetaFor(item)
      const existing = map.get(meta.key)
      if (existing) {
        existing.series.push(item)
        return map
      }
      map.set(meta.key, { ...meta, series: [item] })
      return map
    }, new Map<string, IndicatorPanel>()).values(),
  )
}

function dedupeIndicatorSeries(series: IndicatorOverlaySeries[]): IndicatorOverlaySeries[] {
  const seen = new Set<string>()
  const out: IndicatorOverlaySeries[] = []
  for (const item of series) {
    if (seen.has(item.id)) continue
    seen.add(item.id)
    out.push(item)
  }
  return out
}

function orderedIndicatorCategories(series: IndicatorOverlaySeries[]): IndicatorCategory[] {
  const present = new Set(series.map((item) => item.category).filter((category): category is string => Boolean(category)))
  return [
    ...CATEGORY_ORDER.filter((category) => present.has(category)),
    ...Array.from(present).filter((category) => !CATEGORY_ORDER.includes(category as typeof CATEGORY_ORDER[number])).sort(),
  ]
}

function createTradeMarkers(
  dates: string[],
  close: number[],
  position: number[],
): ChartTradeMarker[] {
  const markers: ChartTradeMarker[] = []
  const length = Math.min(dates.length, close.length, position.length)
  for (let index = 1; index < length; index += 1) {
    const prev = position[index - 1] ?? 0
    const cur = position[index] ?? 0
    const time = toTime(dates[index]!)
    if (cur === prev) continue

    if (prev > 0 && cur < prev) {
      markers.push({ kind: "sell", time, position: "aboveBar", color: "#f97316", shape: "arrowDown", text: "Sell" })
    }
    if (prev < 0 && cur > prev) {
      markers.push({ kind: "cover", time, position: "belowBar", color: "#7c3aed", shape: "arrowUp", text: "Cover" })
    }
    if (cur > 0 && cur > Math.max(prev, 0)) {
      markers.push({ kind: "buy", time, position: "belowBar", color: "#16a34a", shape: "arrowUp", text: "Buy" })
    }
    if (cur < 0 && cur < Math.min(prev, 0)) {
      markers.push({ kind: "short", time, position: "aboveBar", color: "#dc2626", shape: "arrowDown", text: "Short" })
    }
  }
  return markers
}

function createExplicitTradeMarkers(
  markers: NonNullable<PriceSignalsChartProps["tradeMarkers"]>,
): ChartTradeMarker[] {
  return normalizeTradeMarkers(markers).map((marker): ChartTradeMarker => {
    const text = marker.label || (
      marker.kind === "short" ? "Short"
        : marker.kind === "cover" ? "Cover"
          : marker.kind === "sell" ? "Sell"
            : "Buy"
    )
    if (marker.kind === "short") {
      return { kind: "short", time: toTime(marker.date), position: "aboveBar", color: "#dc2626", shape: "arrowDown", text }
    }
    if (marker.kind === "cover") {
      return { kind: "cover", time: toTime(marker.date), position: "belowBar", color: "#7c3aed", shape: "arrowUp", text }
    }
    if (marker.kind === "sell") {
      return { kind: "sell", time: toTime(marker.date), position: "aboveBar", color: "#f97316", shape: "arrowDown", text }
    }
    return { kind: "buy", time: toTime(marker.date), position: "belowBar", color: "#16a34a", shape: "arrowUp", text }
  })
}

function stripMarkerKind(marker: ChartTradeMarker): SeriesMarker<Time> {
  const { kind: _kind, ...seriesMarker } = marker
  return seriesMarker
}

export function PriceSignalsChart({
  open,
  high,
  low,
  close,
  position,
  dates,
  title,
  indicatorSeries,
  tradeMarkers,
  height = 360,
  maxHeight = 560,
}: PriceSignalsChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(() => new Set())
  const [hiddenCategories, setHiddenCategories] = useState<Set<string>>(() => new Set())
  const [hiddenMarkerKinds, setHiddenMarkerKinds] = useState<Set<TradeMarkerKind>>(() => new Set())

  const allIndicators = useMemo(() => dedupeIndicatorSeries(indicatorSeries ?? []), [indicatorSeries])
  const indicatorCategories = useMemo(() => orderedIndicatorCategories(allIndicators), [allIndicators])
  const colorById = useMemo(
    () => new Map(allIndicators.map((series, index) => [series.id, COLORS[index % COLORS.length]])),
    [allIndicators],
  )
  const visibleIndicators = useMemo(
    () => allIndicators.filter((series) => !hiddenIds.has(series.id) && !hiddenCategories.has(series.category ?? "")),
    [allIndicators, hiddenCategories, hiddenIds],
  )
  const priceIndicators = useMemo(() => visibleIndicators.filter(isPriceSeries), [visibleIndicators])
  const indicatorPanels = useMemo(
    () => buildPanels(visibleIndicators.filter((series) => !isPriceSeries(series))),
    [visibleIndicators],
  )
  const priceCandleData = useMemo(() => {
    if (!dates || !open || !high || !low || !close) return []
    if (
      open.length !== dates.length
      || high.length !== dates.length
      || low.length !== dates.length
      || close.length !== dates.length
    ) {
      return []
    }
    return candleData(dates, open, high, low, close)
  }, [close, dates, high, low, open])
  const hasCandleData = priceCandleData.length >= 2
  const allTradeMarkers = useMemo(() => {
    if (!dates || !close || !position || close.length < 2) return []
    return tradeMarkers?.length
      ? createExplicitTradeMarkers(tradeMarkers)
      : createTradeMarkers(dates, close, position)
  }, [close, dates, position, tradeMarkers])
  const markerKinds = useMemo(
    () => MARKER_KIND_ORDER.filter((kind) => allTradeMarkers.some((marker) => marker.kind === kind)),
    [allTradeMarkers],
  )
  const visibleMarkerKinds = useMemo(
    () => MARKER_KIND_ORDER.filter((kind) => markerKinds.includes(kind) && !hiddenMarkerKinds.has(kind)),
    [hiddenMarkerKinds, markerKinds],
  )
  const visibleTradeMarkers = useMemo(
    () => filterTradeMarkersByKind(allTradeMarkers, visibleMarkerKinds).map(stripMarkerKind),
    [allTradeMarkers, visibleMarkerKinds],
  )
  const compressedHeight = indicatorPanels.length > 0 ? 320 + indicatorPanels.length * 82 : height
  const chartHeight = Math.min(maxHeight, Math.max(height, compressedHeight))

  useEffect(() => {
    setHiddenIds((prev) => {
      const valid = new Set((indicatorSeries ?? []).map((series) => series.id))
      const next = new Set(Array.from(prev).filter((id) => valid.has(id)))
      return next.size === prev.size ? prev : next
    })
  }, [indicatorSeries])

  useEffect(() => {
    setHiddenCategories((prev) => {
      const valid = new Set(indicatorCategories)
      const next = new Set(Array.from(prev).filter((category) => valid.has(category)))
      return next.size === prev.size ? prev : next
    })
  }, [indicatorCategories])

  useEffect(() => {
    setHiddenMarkerKinds((prev) => {
      const valid = new Set(markerKinds)
      const next = new Set(Array.from(prev).filter((kind) => valid.has(kind)))
      return next.size === prev.size ? prev : next
    })
  }, [markerKinds])

  useEffect(() => {
    const container = containerRef.current
    if (!container || !close || !position || !dates || close.length < 2) return

    if (chartRef.current) {
      chartRef.current.remove()
      chartRef.current = null
    }

    const chart = createChart(container, {
      width: container.clientWidth || 720,
      height: chartHeight,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#64748b",
        fontSize: 11,
        fontFamily: "var(--font-sans), system-ui, sans-serif",
        panes: {
          enableResize: true,
          separatorColor: "rgba(148, 163, 184, 0.28)",
          separatorHoverColor: "rgba(148, 163, 184, 0.42)",
        },
        attributionLogo: true,
      },
      grid: {
        vertLines: { color: "rgba(148, 163, 184, 0.12)" },
        horzLines: { color: "rgba(148, 163, 184, 0.12)" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderVisible: false },
      timeScale: {
        borderVisible: false,
        timeVisible: true,
        secondsVisible: false,
      },
    })
    chartRef.current = chart

    for (let index = 0; index < indicatorPanels.length; index += 1) {
      chart.addPane(true)
    }

    const panes = chart.panes()
    panes[0]?.setStretchFactor(indicatorPanels.length > 0 ? 5 : 1)
    indicatorPanels.forEach((panel, index) => {
      panes[index + 1]?.setStretchFactor(panel.kind === "macd" ? 2 : panel.kind === "indicator" ? 1 : 1.25)
    })

    if (hasCandleData) {
      const priceSeries = chart.addSeries(
        CandlestickSeries,
        {
          upColor: "#14b8a6",
          downColor: "#ef4444",
          borderUpColor: "#0f766e",
          borderDownColor: "#b91c1c",
          wickUpColor: "#0f766e",
          wickDownColor: "#b91c1c",
          priceLineVisible: false,
          lastValueVisible: true,
        },
        0,
      )
      priceSeries.setData(priceCandleData)
      createSeriesMarkers(priceSeries, visibleTradeMarkers)
      priceSeries.priceScale().applyOptions({
        scaleMargins: { top: 0.08, bottom: 0.06 },
        borderVisible: false,
      })
    } else {
      const priceSeries = chart.addSeries(
        LineSeries,
        {
          color: "#334155",
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: true,
          crosshairMarkerVisible: true,
        },
        0,
      )
      priceSeries.setData(lineData(dates, close))
      createSeriesMarkers(priceSeries, visibleTradeMarkers)
      priceSeries.priceScale().applyOptions({
        scaleMargins: { top: 0.08, bottom: 0.06 },
        borderVisible: false,
      })
    }

    priceIndicators.forEach((series) => {
      const color = colorById.get(series.id) ?? COLORS[0]
      const line = chart.addSeries(
        LineSeries,
        {
          color,
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        },
        0,
      )
      line.setData(lineData(dates, series.values))
      if (series.overlayValues) {
        const overlay = chart.addSeries(
          LineSeries,
          {
            color,
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
          },
          0,
        )
        overlay.setData(lineData(dates, series.overlayValues))
      }
    })

    indicatorPanels.forEach((panel, panelIndex) => {
      const paneIndex = panelIndex + 1
      let macdZeroLineAdded = false
      let oscillatorThresholdsAdded = false
      panel.series.forEach((series, seriesIndex) => {
        const color = colorById.get(series.id) ?? COLORS[(panelIndex + seriesIndex) % COLORS.length]
        const family = indicatorFamily(series)

        if (panel.kind === "macd") {
          const hist = chart.addSeries(
            HistogramSeries,
            {
              priceLineVisible: false,
              lastValueVisible: false,
              base: 0,
              priceFormat: { type: "price", precision: 4, minMove: 0.0001 },
            },
            paneIndex,
          )
          hist.setData(histogramData(dates, series.values))

          const referenceSeries = series.macdLineValues ?? series.overlayValues ?? series.values
          const line = chart.addSeries(
            LineSeries,
            {
              color,
              lineWidth: 2,
              priceLineVisible: false,
              lastValueVisible: false,
              crosshairMarkerVisible: false,
              priceFormat: { type: "price", precision: 4, minMove: 0.0001 },
            },
            paneIndex,
          )
          line.setData(lineData(dates, referenceSeries))

          if (series.overlayValues) {
            const signal = chart.addSeries(
              LineSeries,
              {
                color: "#f59e0b",
                lineWidth: 2,
                priceLineVisible: false,
                lastValueVisible: false,
                crosshairMarkerVisible: false,
                priceFormat: { type: "price", precision: 4, minMove: 0.0001 },
              },
              paneIndex,
            )
            signal.setData(lineData(dates, series.overlayValues))
          }

          if (!macdZeroLineAdded) {
            macdZeroLineAdded = true
            line.createPriceLine({
              price: 0,
              color: "rgba(100, 116, 139, 0.9)",
              lineWidth: 1,
              lineStyle: LineStyle.Dashed,
              axisLabelVisible: true,
              title: "Zero",
            })
          }
          line.priceScale().applyOptions({ borderVisible: false })
          return
        }

        const line = chart.addSeries(
          LineSeries,
          {
            color,
            lineWidth: panel.kind === "rsi" || panel.kind === "oscillator" ? 2 : 1,
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: false,
          },
          paneIndex,
        )
        line.setData(lineData(dates, series.values))

        if (series.overlayValues) {
          const overlay = chart.addSeries(
            LineSeries,
            {
              color: "#f59e0b",
              lineWidth: 1,
              lineStyle: family === "adx" ? LineStyle.Solid : LineStyle.Dashed,
              priceLineVisible: false,
              lastValueVisible: false,
              crosshairMarkerVisible: false,
            },
            paneIndex,
          )
          overlay.setData(lineData(dates, series.overlayValues))
        }

        if ((panel.kind === "rsi" || panel.kind === "oscillator") && !oscillatorThresholdsAdded) {
          oscillatorThresholdsAdded = true
          const low = series.params?.oversold ?? (family === "stochastic" ? 20 : 30)
          const high = series.params?.overbought ?? (family === "stochastic" ? 80 : 70)
          line.createPriceLine({
            price: low,
            color: "#16a34a",
            lineWidth: 2,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: `Oversold ${low}`,
          })
          line.createPriceLine({
            price: high,
            color: "#dc2626",
            lineWidth: 2,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: `Overbought ${high}`,
          })
          line.createPriceLine({
            price: 50,
            color: "rgba(100, 116, 139, 0.5)",
            lineWidth: 1,
            lineStyle: LineStyle.Dotted,
            axisLabelVisible: false,
            title: "",
          })
          line.priceScale().applyOptions({
            scaleMargins: { top: 0.08, bottom: 0.08 },
            borderVisible: false,
          })
        } else if (panel.kind !== "rsi" && panel.kind !== "oscillator") {
          line.priceScale().applyOptions({ borderVisible: false })
        }
      })
    })

    chart.timeScale().fitContent()

    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0]
      if (!entry) return
      chart.applyOptions({ width: Math.round(entry.contentRect.width), height: chartHeight })
    })
    resizeObserver.observe(container)

    return () => {
      resizeObserver.disconnect()
      chart.remove()
      chartRef.current = null
    }
  }, [chartHeight, close, colorById, dates, hasCandleData, indicatorPanels, position, priceCandleData, priceIndicators, visibleTradeMarkers])

  if (!close || !position || !dates || close.length < 2) {
    return (
      <p className="rounded border bg-muted/20 p-2 text-xs text-muted-foreground">
        Serie de prix non disponible pour ce resultat.
      </p>
    )
  }

  const toggleIndicator = (id: string) => {
    setHiddenIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleCategory = (category: string) => {
    setHiddenCategories((prev) => {
      const next = new Set(prev)
      if (next.has(category)) next.delete(category)
      else next.add(category)
      return next
    })
  }

  const toggleMarkerKind = (kind: TradeMarkerKind) => {
    setHiddenMarkerKinds((prev) => {
      const next = new Set(prev)
      if (next.has(kind)) next.delete(kind)
      else next.add(kind)
      return next
    })
  }

  return (
    <div className="space-y-2">
      {title ? <div className="text-xs font-semibold text-foreground">{title}</div> : null}
      {markerKinds.length > 0 ? (
        <div className="signals-scrollbar flex gap-1.5 overflow-x-auto rounded-md border border-line bg-bg2 p-1">
          {markerKinds.map((kind) => {
            const hidden = hiddenMarkerKinds.has(kind)
            const meta = MARKER_META[kind]
            return (
              <button
                key={kind}
                type="button"
                onClick={() => toggleMarkerKind(kind)}
                className={cn(
                  "inline-flex h-7 shrink-0 items-center gap-2 rounded-md border bg-card px-2 text-[11px] transition-opacity",
                  hidden && "opacity-45",
                )}
                style={{ borderColor: hidden ? "var(--line)" : meta.color }}
                title={hidden ? `Afficher ${meta.label}` : `Masquer ${meta.label}`}
              >
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: meta.color }} />
                <span className="font-semibold">{meta.label}</span>
              </button>
            )
          })}
        </div>
      ) : null}
      {indicatorCategories.length > 0 ? (
        <div className="signals-scrollbar flex gap-1.5 overflow-x-auto rounded-md border border-line bg-bg2 p-1">
          {indicatorCategories.map((category) => {
            const hidden = hiddenCategories.has(category)
            return (
              <button
                key={category}
                type="button"
                onClick={() => toggleCategory(category)}
                className={cn(
                  "inline-flex h-7 shrink-0 items-center rounded-md border border-line bg-card px-2 text-[11px] font-semibold transition-opacity",
                  hidden && "opacity-45",
                )}
                title={hidden ? `Afficher ${CATEGORY_LABELS[category] ?? category}` : `Masquer ${CATEGORY_LABELS[category] ?? category}`}
              >
                {CATEGORY_LABELS[category] ?? category}
              </button>
            )
          })}
        </div>
      ) : null}
      {allIndicators.length > 0 ? (
        <div className="signals-scrollbar flex gap-1.5 overflow-x-auto rounded-md border border-line bg-bg2 p-1">
          {allIndicators.map((series, index) => {
            const hidden = hiddenIds.has(series.id) || hiddenCategories.has(series.category ?? "")
            const color = colorById.get(series.id) ?? COLORS[index % COLORS.length]
            return (
              <button
                key={series.id}
                type="button"
                onClick={() => toggleIndicator(series.id)}
                className={cn(
                  "inline-flex h-7 max-w-[220px] shrink-0 items-center gap-2 rounded-md border bg-card px-2 text-left text-[11px] transition-opacity",
                  hidden && "opacity-45",
                )}
                style={{ borderColor: hidden ? "var(--line)" : color }}
                title={series.label}
              >
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: color }} />
                <span className="min-w-0">
                  <span className="block truncate font-semibold leading-3">{series.label}</span>
                  <span className="block truncate text-[10px] leading-3 text-muted-foreground">
                    {panelSubtitle(series)}
                  </span>
                </span>
              </button>
            )
          })}
        </div>
      ) : null}
      <div
        ref={containerRef}
        className="h-[var(--chart-height)] w-full overflow-hidden rounded-md border border-line bg-card"
        style={{ "--chart-height": `${chartHeight}px` } as React.CSSProperties}
      />
    </div>
  )
}
