"use client"

import { useEffect, useMemo, useRef } from "react"
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type CandlestickData,
  type IChartApi,
  type LineData,
  type SeriesMarker,
  type Time,
} from "lightweight-charts"
import { Skeleton } from "@/components/ui/skeleton"
import type { ConstructedSignalChart, SignalZoneChart as ZoneChartData } from "@/lib/api"

const FAMILY_LINE_COLORS: Record<string, string> = {
  sma: "#22c55e",
  macd: "#a855f7",
  rsi: "#f97316",
  obv: "#ec4899",
}

type ChartIndicatorPayload = Record<string, any>
type ShadeBand = {
  bars: Array<{ date: string }>
  startValues: Array<number | null>
  endValues: Array<number | null>
  series: any
  color: string
}

type PanelSlot = {
  priceScaleId: string
  top: number
  bottom: number
}

function toTime(dateStr: string): Time {
  return dateStr as unknown as Time
}

function hexToRgba(hex: string, alpha: number): string {
  const normalized = hex.replace("#", "")
  const full = normalized.length === 3
    ? normalized.split("").map((ch) => `${ch}${ch}`).join("")
    : normalized
  const parsed = Number.parseInt(full, 16)
  if (!Number.isFinite(parsed)) return `rgba(148, 163, 184, ${alpha})`
  const r = (parsed >> 16) & 255
  const g = (parsed >> 8) & 255
  const b = parsed & 255
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function isConstructedChart(data: ZoneChartData | ConstructedSignalChart | null | undefined): data is ConstructedSignalChart {
  return Boolean(data) && Array.isArray((data as ConstructedSignalChart).sources)
}

function renderSmaLayer(
  chart: IChartApi,
  famData: { representatives: Array<{ weight: number; indicator?: ChartIndicatorPayload | null }> },
  bars: Array<{ date: string }>,
) {
  for (const rep of famData.representatives) {
    if (!rep.indicator) continue
    const ind = rep.indicator
    const opacity = (0.3 + rep.weight * 0.7).toFixed(2)

    if (ind.type === "overlay" && ind.values) {
      const series = chart.addSeries(LineSeries, {
        color: `rgba(34, 197, 94, ${opacity})`,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      })
      const lineData: LineData[] = []
      const vals = ind.values as Array<number | null>
      for (let i = 0; i < bars.length && i < vals.length; i += 1) {
        if (vals[i] != null) lineData.push({ time: toTime(bars[i].date), value: vals[i]! })
      }
      series.setData(lineData)
    }

    if (ind.type === "overlay_dual") {
      if (ind.fast) {
        const fastSeries = chart.addSeries(LineSeries, {
          color: `rgba(34, 197, 94, ${opacity})`,
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        })
        const fastData: LineData[] = []
        const fastVals = ind.fast as Array<number | null>
        for (let i = 0; i < bars.length && i < fastVals.length; i += 1) {
          if (fastVals[i] != null) fastData.push({ time: toTime(bars[i].date), value: fastVals[i]! })
        }
        fastSeries.setData(fastData)
      }

      if (ind.slow) {
        const slowOpacity = (0.2 + rep.weight * 0.5).toFixed(2)
        const slowSeries = chart.addSeries(LineSeries, {
          color: `rgba(34, 197, 94, ${slowOpacity})`,
          lineWidth: 1,
          lineStyle: 2,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        })
        const slowData: LineData[] = []
        const slowVals = ind.slow as Array<number | null>
        for (let i = 0; i < bars.length && i < slowVals.length; i += 1) {
          if (slowVals[i] != null) slowData.push({ time: toTime(bars[i].date), value: slowVals[i]! })
        }
        slowSeries.setData(slowData)
      }
    }
  }
}

function renderObvLayer(
  chart: IChartApi,
  famData: { representatives: Array<{ weight: number; indicator?: ChartIndicatorPayload | null }> },
  bars: Array<{ date: string; volume?: number | null }>,
  volumeMargins?: { top: number; bottom: number },
) {
  const histSeries = chart.addSeries(HistogramSeries, {
    priceScaleId: "volume",
    lastValueVisible: false,
    priceLineVisible: false,
  })

  chart.priceScale("volume").applyOptions({
    scaleMargins: volumeMargins ?? { top: 0.85, bottom: 0 },
    borderVisible: false,
  })

  const histData = bars.map((bar, index) => {
    let accWeight = 0
    let distWeight = 0

    for (const rep of famData.representatives) {
      const barSignals = rep.indicator?.bar_signals as string[] | undefined
      if (!barSignals) continue
      const signal = barSignals[index]
      if (signal === "accumulation") accWeight += rep.weight
      else if (signal === "distribution") distWeight += rep.weight
    }

    let color = "rgba(161, 161, 170, 0.3)"
    if (accWeight > distWeight) {
      color = `rgba(34, 197, 94, ${Math.min(0.8, 0.3 + accWeight * 0.5).toFixed(2)})`
    } else if (distWeight > accWeight) {
      color = `rgba(239, 68, 68, ${Math.min(0.8, 0.3 + distWeight * 0.5).toFixed(2)})`
    }

    return { time: toTime(bar.date), value: (bar.volume ?? 0) as number, color }
  })

  histSeries.setData(histData)
}

function renderMacdMarkers(
  famData: { representatives: Array<{ weight: number; label: string; indicator?: ChartIndicatorPayload | null }> },
  bars: Array<{ date: string }>,
): SeriesMarker<Time>[] {
  const markers: SeriesMarker<Time>[] = []

  for (const rep of famData.representatives) {
    const crossovers = rep.indicator?.crossovers as Array<{ bar_index: number; direction: string }> | undefined
    if (!crossovers) continue

    const alpha = Math.max(0.4, rep.weight).toFixed(2)
    for (const crossover of crossovers) {
      if (crossover.bar_index < 0 || crossover.bar_index >= bars.length) continue
      const isBullish = crossover.direction === "bullish"
      markers.push({
        time: toTime(bars[crossover.bar_index].date),
        position: isBullish ? "belowBar" : "aboveBar",
        color: isBullish ? `rgba(34, 197, 94, ${alpha})` : `rgba(239, 68, 68, ${alpha})`,
        shape: isBullish ? "arrowUp" : "arrowDown",
        text: "",
      })
    }
  }

  return markers
}

interface RsiRepRef {
  weight: number
  values: Array<number | null>
  oversold: number
  overbought: number
}

function collectRsiReps(
  famData: { representatives: Array<{ weight: number; indicator?: ChartIndicatorPayload | null }> },
): RsiRepRef[] {
  const refs: RsiRepRef[] = []
  for (const rep of famData.representatives) {
    if (!rep.indicator || rep.indicator.type !== "secondary_yaxis") continue
    const values = rep.indicator.values as Array<number | null> | undefined
    const thresholds = rep.indicator.thresholds as [number, number] | undefined
    if (!values || !thresholds) continue
    refs.push({
      weight: rep.weight,
      values,
      oversold: thresholds[0],
      overbought: thresholds[1],
    })
  }
  return refs
}

function buildPanelSlots(count: number): { mainTop: number; mainBottom: number; slots: PanelSlot[] } {
  if (count === 0) {
    return { mainTop: 0.04, mainBottom: 0.06, slots: [] }
  }

  const mainTop = 0.04
  const bottomPadding = 0.04
  const gap = 0.03
  const mainHeight = count === 1 ? 0.58 : count === 2 ? 0.5 : count === 3 ? 0.44 : 0.4
  const remaining = 1 - mainTop - bottomPadding - mainHeight - gap * count
  const panelHeight = remaining / count
  const mainBottom = 1 - mainTop - mainHeight
  const slots: PanelSlot[] = []

  let currentTop = mainTop + mainHeight + gap
  for (let index = 0; index < count; index += 1) {
    const top = currentTop
    const bottom = 1 - (top + panelHeight)
    slots.push({ priceScaleId: `indicator-panel-${index}`, top, bottom })
    currentTop += panelHeight + gap
  }

  return { mainTop, mainBottom, slots }
}

function getSourceDisplayIndicator(source: ConstructedSignalChart["sources"][number]): ChartIndicatorPayload | null {
  if (source.wfo_range_active) return (source.wfo_end_indicator ?? source.wfo_start_indicator ?? source.indicator ?? null) as ChartIndicatorPayload | null
  return (source.indicator ?? null) as ChartIndicatorPayload | null
}

function getRepresentativeIndicators(source: ConstructedSignalChart["sources"][number]) {
  return source.representatives
    .map((rep) => ({
      weight: Number(rep.weight ?? 0),
      label: rep.label,
      indicator: (rep.indicator ?? null) as ChartIndicatorPayload | null,
    }))
    .filter((rep) => rep.indicator)
}

function sourceNeedsIndicatorPanel(source: ConstructedSignalChart["sources"][number]): boolean {
  if (source.source_kind === "family_ensemble") {
    return getRepresentativeIndicators(source).some((rep) => rep.indicator?.plot_axis === "indicator")
  }
  const indicator = getSourceDisplayIndicator(source)
  return indicator?.plot_axis === "indicator"
}

function valuesToLineData(
  bars: Array<{ date: string }>,
  values: Array<number | null>,
): LineData[] {
  return values
    .map((value, index) => value == null ? null : ({ time: toTime(bars[index].date), value }))
    .filter(Boolean) as LineData[]
}

function addHorizontalGuide(
  chart: IChartApi,
  bars: Array<{ date: string }>,
  priceScaleId: string,
  value: number,
  color: string,
) {
  const guide = chart.addSeries(LineSeries, {
    priceScaleId,
    color,
    lineWidth: 1,
    lineStyle: 2,
    priceLineVisible: false,
    lastValueVisible: false,
    crosshairMarkerVisible: false,
  })
  guide.setData(bars.map((bar) => ({ time: toTime(bar.date), value })))
  return guide
}

function renderIndicatorPayload(
  chart: IChartApi,
  indicator: ChartIndicatorPayload | null | undefined,
  bars: Array<{ date: string }>,
  color: string,
  options?: {
    priceScaleId?: string
    lineStyle?: number
    lineWidth?: number
    asRangeBoundary?: boolean
  },
): { series: any | null; plotValues: Array<number | null> | null } {
  if (!indicator) return { series: null, plotValues: null }

  const priceScaleId = options?.priceScaleId
  const lineStyle = options?.lineStyle ?? 0
  const lineWidth = Math.max(1, Math.min(4, Math.round(options?.lineWidth ?? 2))) as 1 | 2 | 3 | 4
  const plotValues = Array.isArray(indicator.plot_values) ? indicator.plot_values as Array<number | null> : null
  const plotKind = String(indicator.plot_kind ?? "")

  if (plotKind === "histogram" && plotValues && !options?.asRangeBoundary) {
    const histogram = chart.addSeries(HistogramSeries, {
      priceScaleId,
      lastValueVisible: false,
      priceLineVisible: false,
      base: 0,
    })
    histogram.setData(
      bars.map((bar, index) => {
        const value = plotValues[index]
        return {
          time: toTime(bar.date),
          value: value ?? 0,
          color: value == null ? hexToRgba(color, 0.08) : value >= 0 ? hexToRgba(color, 0.8) : "rgba(239, 68, 68, 0.75)",
        }
      }),
    )
    return { series: histogram, plotValues }
  }

  if (plotValues) {
    const line = chart.addSeries(LineSeries, {
      priceScaleId,
      color,
      lineWidth,
      lineStyle,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    line.setData(valuesToLineData(bars, plotValues))
    return { series: line, plotValues }
  }

  return { series: null, plotValues: null }
}

function sourceLegendDetail(
  source: ConstructedSignalChart["sources"][number],
): string | null {
  if (source.source_kind === "family_ensemble") {
    const reps = source.representatives
      .slice(0, 3)
      .map((rep) => `${rep.label} ${(rep.weight * 100).toFixed(0)}%`)
    if (reps.length > 0) return reps.join(" · ")
    if (source.indicator?.name) return String(source.indicator.name)
    return "Representative family variants"
  }

  if (source.wfo_range_active) {
    const startName = source.wfo_start_indicator?.name
    const endName = source.wfo_end_indicator?.name
    if (startName && endName) return `${String(startName)} -> ${String(endName)}`
    return source.indicator?.name ? String(source.indicator.name) : "WFO start/end range"
  }

  if (source.indicator?.name) return String(source.indicator.name)
  return null
}

interface Props {
  data: ZoneChartData | ConstructedSignalChart | null | undefined
  enabledFamilies: string[]
  isLoading: boolean
  isRefreshing?: boolean
  errorMessage?: string | null
  height?: number
}

export function SignalZoneChart({
  data,
  enabledFamilies,
  isLoading,
  isRefreshing,
  errorMessage,
  height = 400,
}: Props) {
  const wrapperRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const zoneCanvasRef = useRef<HTMLCanvasElement>(null)
  const chartRef = useRef<IChartApi | null>(null)

  const legendItems = useMemo(() => {
    if (!data) return []
    if (isConstructedChart(data)) {
      return data.sources.filter((source) => enabledFamilies.includes(source.family))
    }
    return enabledFamilies.map((family) => ({
      family,
      label: family.toUpperCase(),
      source_kind: "family_ensemble",
      source_mode_label: "Family score",
      wfo_range_active: false,
      wfo_param_names: [],
    }))
  }, [data, enabledFamilies])

  useEffect(() => {
    if (!data || !containerRef.current) return

    if (chartRef.current) {
      chartRef.current.remove()
      chartRef.current = null
    }

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#a1a1aa",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(161,161,170,0.08)" },
        horzLines: { color: "rgba(161,161,170,0.08)" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: false },
    })
    chartRef.current = chart

    const activeConstructedSources = isConstructedChart(data)
      ? data.sources.filter((source) => enabledFamilies.includes(source.family))
      : []
    const panelSources = activeConstructedSources.filter((source) => sourceNeedsIndicatorPanel(source))
    const panelLayout = buildPanelSlots(panelSources.length)
    chart.priceScale("right").applyOptions({
      borderVisible: false,
      scaleMargins: { top: panelLayout.mainTop, bottom: panelLayout.mainBottom },
    })

    const slotByScoreKey = new Map<string, PanelSlot>()
    const slotByPriceScaleId = new Map<string, PanelSlot>()
    panelSources.forEach((source, index) => {
      const slot = panelLayout.slots[index]
      if (!slot) return
      slotByScoreKey.set(source.score_key, slot)
      slotByPriceScaleId.set(slot.priceScaleId, slot)
    })
    const configuredPanelScales = new Set<string>()
    const configurePanelScale = (priceScaleId?: string) => {
      if (!priceScaleId || configuredPanelScales.has(priceScaleId)) return
      const slot = slotByPriceScaleId.get(priceScaleId)
      if (!slot) return
      chart.priceScale(priceScaleId).applyOptions({
        borderVisible: false,
        scaleMargins: { top: slot.top, bottom: slot.bottom },
      })
      configuredPanelScales.add(priceScaleId)
    }

    const candle = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderDownColor: "#ef4444",
      borderUpColor: "#22c55e",
      wickDownColor: "#ef4444",
      wickUpColor: "#22c55e",
    })

    const candleData: CandlestickData[] = data.bars
      .filter((bar) => bar.open != null && bar.high != null && bar.low != null && bar.close != null)
      .map((bar) => ({
        time: toTime(bar.date),
        open: bar.open!,
        high: bar.high!,
        low: bar.low!,
        close: bar.close!,
      }))
    candle.setData(candleData)

    const shadeBands: ShadeBand[] = []
    let rsiReps: RsiRepRef[] = []
    const markers: SeriesMarker<Time>[] = []

    if (isConstructedChart(data)) {
      for (const source of activeConstructedSources) {
        const color = FAMILY_LINE_COLORS[source.family] || "#888888"
        const reps = source.representatives.length > 0
          ? source.representatives
          : (source.indicator ? [{ weight: 1, label: source.label, indicator: source.indicator }] : [])
        const famData = { representatives: reps as Array<{ weight: number; label: string; indicator?: ChartIndicatorPayload | null }> }
        const slot = slotByScoreKey.get(source.score_key)

        if (source.source_kind === "family_ensemble") {
          const repIndicators = getRepresentativeIndicators(source)
          const familyPriceScaleId = slot?.priceScaleId

          if (source.family === "sma") {
            renderSmaLayer(chart, famData, data.bars)
            continue
          }

          if (slot) {
            const thresholdValues = new Set<number>()
            let zeroLine: number | null = null
            for (const rep of repIndicators) {
              const indicator = rep.indicator
              if (!indicator) continue
              if (zeroLine == null && indicator.zero_line != null) zeroLine = Number(indicator.zero_line)
              if (Array.isArray(indicator.thresholds)) {
                indicator.thresholds.forEach((threshold: number) => thresholdValues.add(Number(threshold)))
              }
            }
            if (zeroLine != null) {
              addHorizontalGuide(chart, data.bars, slot.priceScaleId, zeroLine, hexToRgba(color, 0.22))
              configurePanelScale(slot.priceScaleId)
            }
            thresholdValues.forEach((threshold) => {
              addHorizontalGuide(chart, data.bars, slot.priceScaleId, threshold, hexToRgba(color, 0.16))
              configurePanelScale(slot.priceScaleId)
            })
          }

          for (const rep of repIndicators) {
            const indicator = rep.indicator
            if (!indicator) continue
            const repColor = hexToRgba(color, Math.min(0.9, 0.2 + rep.weight * 0.65))
            const render = renderIndicatorPayload(chart, indicator, data.bars, repColor, {
              priceScaleId: familyPriceScaleId,
              lineWidth: source.family === "rsi" ? 2 : 1,
            })
            if (render.series) configurePanelScale(familyPriceScaleId)
          }

          if (source.family === "rsi") rsiReps.push(...collectRsiReps(famData))
          continue
        }

        const priceScaleId = slot?.priceScaleId
        const displayIndicator = source.indicator as ChartIndicatorPayload | null | undefined
        const startIndicator = source.wfo_start_indicator as ChartIndicatorPayload | null | undefined
        const endIndicator = source.wfo_end_indicator as ChartIndicatorPayload | null | undefined

        if (slot) {
          if (displayIndicator?.zero_line != null) {
            addHorizontalGuide(chart, data.bars, slot.priceScaleId, Number(displayIndicator.zero_line), hexToRgba(color, 0.25))
            configurePanelScale(slot.priceScaleId)
          }
          if (source.family === "rsi") {
            const thresholds = displayIndicator?.thresholds
            if (Array.isArray(thresholds)) {
              thresholds.forEach((threshold: number) => {
                addHorizontalGuide(chart, data.bars, slot.priceScaleId, threshold, hexToRgba(color, 0.18))
                configurePanelScale(slot.priceScaleId)
              })
            }
          }
        }

        if (source.wfo_range_active && startIndicator && endIndicator) {
          const startRender = renderIndicatorPayload(chart, startIndicator, data.bars, hexToRgba(color, 0.35), {
            priceScaleId,
            lineStyle: 2,
            lineWidth: 2,
            asRangeBoundary: true,
          })
          if (startRender.series) configurePanelScale(priceScaleId)
          const endRender = renderIndicatorPayload(chart, endIndicator, data.bars, color, {
            priceScaleId,
            lineWidth: 2,
            asRangeBoundary: true,
          })
          if (endRender.series) configurePanelScale(priceScaleId)
          if (startRender.series && startRender.plotValues && endRender.plotValues) {
            shadeBands.push({
              bars: data.bars,
              startValues: startRender.plotValues,
              endValues: endRender.plotValues,
              series: startRender.series,
              color,
            })
          }
        } else {
          const render = renderIndicatorPayload(chart, displayIndicator, data.bars, color, { priceScaleId })
          if (render.series) configurePanelScale(priceScaleId)
        }

        if (source.family === "macd" && Array.isArray(displayIndicator?.crossovers)) {
          const macdMarkers = renderMacdMarkers(
            { representatives: [{ weight: 1, label: source.label, indicator: displayIndicator }] },
            data.bars,
          )
          markers.push(...macdMarkers)
        }
      }
    } else {
      if (enabledFamilies.includes("sma") && data.families.sma) renderSmaLayer(chart, data.families.sma, data.bars)
      if (enabledFamilies.includes("obv") && data.families.obv) renderObvLayer(chart, data.families.obv, data.bars)
      if (enabledFamilies.includes("rsi") && data.families.rsi) rsiReps = collectRsiReps(data.families.rsi)
      if (enabledFamilies.includes("macd") && data.families.macd) markers.push(...renderMacdMarkers(data.families.macd, data.bars))
    }

    if (markers.length > 0) {
      markers.sort((a, b) => String(a.time).localeCompare(String(b.time)))
      createSeriesMarkers(candle, markers)
    }

    const drawOverlayCanvas = () => {
      const zoneCanvas = zoneCanvasRef.current
      const wrapper = wrapperRef.current
      if (!zoneCanvas || !wrapper) return

      const dpr = window.devicePixelRatio || 1
      const width = wrapper.clientWidth
      const chartHeight = wrapper.clientHeight
      if (width === 0 || chartHeight === 0) return

      if (zoneCanvas.width !== Math.round(width * dpr) || zoneCanvas.height !== Math.round(chartHeight * dpr)) {
        zoneCanvas.width = Math.round(width * dpr)
        zoneCanvas.height = Math.round(chartHeight * dpr)
      }
      zoneCanvas.style.width = `${width}px`
      zoneCanvas.style.height = `${chartHeight}px`

      const ctx = zoneCanvas.getContext("2d")
      if (!ctx) return

      ctx.setTransform(1, 0, 0, 1, 0, 0)
      ctx.clearRect(0, 0, zoneCanvas.width, zoneCanvas.height)
      ctx.scale(dpr, dpr)

      const timeScale = chart.timeScale()
      const mainPanelBottomPx = chartHeight * (1 - panelLayout.mainBottom)

      for (const rsiRep of rsiReps) {
        const shadeOpacity = (0.04 + rsiRep.weight * 0.08).toFixed(3)
        for (let i = 0; i < data.bars.length && i < rsiRep.values.length; i += 1) {
          const rsiValue = rsiRep.values[i]
          if (rsiValue == null) continue

          const x = timeScale.timeToCoordinate(toTime(data.bars[i].date))
          if (x === null) continue
          const nextX = i + 1 < data.bars.length ? timeScale.timeToCoordinate(toTime(data.bars[i + 1].date)) : null
          const barWidth = nextX !== null ? Math.max(nextX - x, 1) : 4

          if (rsiValue > rsiRep.overbought) {
            ctx.fillStyle = `rgba(239, 68, 68, ${shadeOpacity})`
            ctx.fillRect(x, 0, barWidth, mainPanelBottomPx)
          } else if (rsiValue < rsiRep.oversold) {
            ctx.fillStyle = `rgba(34, 197, 94, ${shadeOpacity})`
            ctx.fillRect(x, 0, barWidth, mainPanelBottomPx)
          }
        }
      }

      for (const band of shadeBands) {
        for (let index = 0; index < band.bars.length; index += 1) {
          const startValue = band.startValues[index]
          const endValue = band.endValues[index]
          if (startValue == null || endValue == null) continue

          const x = timeScale.timeToCoordinate(toTime(band.bars[index].date))
          if (x === null) continue
          const nextX = index + 1 < band.bars.length ? timeScale.timeToCoordinate(toTime(band.bars[index + 1].date)) : null
          const barWidth = nextX !== null ? Math.max(nextX - x, 1) : 4

          const y1 = band.series.priceToCoordinate(startValue)
          const y2 = band.series.priceToCoordinate(endValue)
          if (y1 == null || y2 == null) continue

          ctx.fillStyle = hexToRgba(band.color, 0.12)
          ctx.fillRect(x, Math.min(y1, y2), barWidth, Math.max(Math.abs(y2 - y1), 1))
        }
      }
    }

    chart.timeScale().subscribeVisibleLogicalRangeChange(drawOverlayCanvas)
    requestAnimationFrame(drawOverlayCanvas)
    chart.timeScale().fitContent()

    const container = containerRef.current
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        chart.applyOptions({ width: entry.contentRect.width })
        requestAnimationFrame(drawOverlayCanvas)
      }
    })
    observer.observe(container)

    return () => {
      observer.disconnect()
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(drawOverlayCanvas)
      chart.remove()
      chartRef.current = null
    }
  }, [data, enabledFamilies, height])

  if (isLoading) {
    return <Skeleton className="w-full" style={{ height }} />
  }

  if (errorMessage) {
    return (
      <div className="flex items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground" style={{ height }}>
        Signal preview failed to load: {errorMessage}
      </div>
    )
  }

  if (!data) {
    return (
      <div className="flex items-center justify-center rounded-md border border-dashed text-sm text-muted-foreground" style={{ height }}>
        Signal preview chart is unavailable for the current stock.
      </div>
    )
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Signal - {data.symbol}
        </span>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {legendItems.map((item) => {
            const color = FAMILY_LINE_COLORS[item.family] || "#888"
            return (
              <div key={`${item.family}-${item.label}`} className="flex items-center gap-1.5 rounded-full border bg-background px-2 py-1">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} />
                <span className="text-[9px] font-mono uppercase text-muted-foreground">{item.label}</span>
                {"source_mode_label" in item && item.source_mode_label ? (
                  <span className="text-[9px] text-muted-foreground">{item.source_mode_label}</span>
                ) : null}
              </div>
            )
          })}
        </div>
      </div>
      <div ref={wrapperRef} className="relative rounded-md border" style={{ height }}>
        <canvas ref={zoneCanvasRef} className="pointer-events-none absolute inset-0 z-0" />
        <div ref={containerRef} className="absolute inset-0 z-10" />
        {isRefreshing ? (
          <div className="pointer-events-none absolute inset-0 z-20 bg-background/35">
            <div className="absolute right-3 top-3 rounded-full border bg-background/90 px-3 py-1 text-[10px] font-medium uppercase tracking-wide text-muted-foreground shadow-sm">
              Updating preview
            </div>
          </div>
        ) : null}
      </div>
      <div className="flex flex-wrap items-center gap-3 text-[9px] text-muted-foreground">
        {legendItems.map((item) => (
          <div key={`foot-${item.family}-${item.label}`} className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: FAMILY_LINE_COLORS[item.family] || "#888" }} />
            <span>
              {item.label}
              {"source_mode_label" in item && item.source_mode_label ? ` / ${item.source_mode_label}` : ""}
              {"wfo_range_active" in item && item.wfo_range_active ? " / Start-End range" : ""}
              {"representatives" in item || "indicator" in item ? (() => {
                const detail = sourceLegendDetail(item as ConstructedSignalChart["sources"][number])
                return detail ? ` / ${detail}` : ""
              })() : ""}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
