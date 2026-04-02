"use client"

import { useEffect, useRef } from "react"
import {
  createChart,
  createSeriesMarkers,
  CandlestickSeries,
  LineSeries,
  HistogramSeries,
  ColorType,
  CrosshairMode,
  type IChartApi,
  type CandlestickData,
  type LineData,
  type Time,
  type SeriesMarker,
} from "lightweight-charts"
import { Skeleton } from "@/components/ui/skeleton"
import type { SignalZoneChart as ZoneChartData } from "@/lib/api"

const FAMILY_LINE_COLORS: Record<string, string> = {
  sma: "#22c55e",
  macd: "#a855f7",
  rsi: "#f97316",
  obv: "#ec4899",
}

function toTime(dateStr: string): Time {
  return dateStr as unknown as Time
}

function renderSmaLayer(
  chart: IChartApi,
  famData: { representatives: Array<{ weight: number; indicator?: Record<string, any> | null }> },
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
      const vals = ind.values as (number | null)[]
      for (let i = 0; i < bars.length && i < vals.length; i++) {
        if (vals[i] != null) {
          lineData.push({ time: toTime(bars[i].date), value: vals[i]! })
        }
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
        const fVals = ind.fast as (number | null)[]
        for (let i = 0; i < bars.length && i < fVals.length; i++) {
          if (fVals[i] != null) {
            fastData.push({ time: toTime(bars[i].date), value: fVals[i]! })
          }
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
        const sVals = ind.slow as (number | null)[]
        for (let i = 0; i < bars.length && i < sVals.length; i++) {
          if (sVals[i] != null) {
            slowData.push({ time: toTime(bars[i].date), value: sVals[i]! })
          }
        }
        slowSeries.setData(slowData)
      }
    }
  }
}

function renderObvLayer(
  chart: IChartApi,
  famData: { representatives: Array<{ weight: number; indicator?: Record<string, any> | null }> },
  bars: Array<{ date: string; volume?: number | null }>,
) {
  const histSeries = chart.addSeries(HistogramSeries, {
    priceScaleId: "volume",
    lastValueVisible: false,
    priceLineVisible: false,
  })

  chart.priceScale("volume").applyOptions({
    scaleMargins: { top: 0.85, bottom: 0 },
  })

  const histData = bars.map((b, i) => {
    let accWeight = 0
    let distWeight = 0

    for (const rep of famData.representatives) {
      const barSignals = rep.indicator?.bar_signals as string[] | undefined
      if (!barSignals) continue
      const sig = barSignals[i]
      if (sig === "accumulation") accWeight += rep.weight
      else if (sig === "distribution") distWeight += rep.weight
    }

    let color = "rgba(161, 161, 170, 0.3)"
    if (accWeight > distWeight) {
      const intensity = Math.min(0.8, 0.3 + accWeight * 0.5).toFixed(2)
      color = `rgba(34, 197, 94, ${intensity})`
    } else if (distWeight > accWeight) {
      const intensity = Math.min(0.8, 0.3 + distWeight * 0.5).toFixed(2)
      color = `rgba(239, 68, 68, ${intensity})`
    }

    return { time: toTime(b.date), value: (b.volume ?? 0) as number, color }
  })

  histSeries.setData(histData)
}

function renderMacdMarkers(
  famData: { representatives: Array<{ weight: number; label: string; indicator?: Record<string, any> | null }> },
  bars: Array<{ date: string }>,
): SeriesMarker<Time>[] {
  const markers: SeriesMarker<Time>[] = []

  for (const rep of famData.representatives) {
    const crossovers = rep.indicator?.crossovers as
      | Array<{ bar_index: number; direction: string }>
      | undefined
    if (!crossovers) continue

    const alpha = Math.max(0.4, rep.weight).toFixed(2)

    for (const xo of crossovers) {
      if (xo.bar_index < 0 || xo.bar_index >= bars.length) continue
      const isBullish = xo.direction === "bullish"
      markers.push({
        time: toTime(bars[xo.bar_index].date),
        position: isBullish ? "belowBar" : "aboveBar",
        color: isBullish
          ? `rgba(34, 197, 94, ${alpha})`
          : `rgba(239, 68, 68, ${alpha})`,
        shape: isBullish ? "arrowUp" : "arrowDown",
        text: "",
      })
    }
  }

  return markers
}

interface RsiRepRef {
  weight: number
  values: (number | null)[]
  oversold: number
  overbought: number
}

function collectRsiReps(
  famData: { representatives: Array<{ weight: number; indicator?: Record<string, any> | null }> },
): RsiRepRef[] {
  const refs: RsiRepRef[] = []
  for (const rep of famData.representatives) {
    if (!rep.indicator || rep.indicator.type !== "secondary_yaxis") continue
    const vals = rep.indicator.values as (number | null)[] | undefined
    const thresholds = rep.indicator.thresholds as [number, number] | undefined
    if (!vals || !thresholds) continue
    refs.push({
      weight: rep.weight,
      values: vals,
      oversold: thresholds[0],
      overbought: thresholds[1],
    })
  }
  return refs
}

interface Props {
  data: ZoneChartData | null | undefined
  enabledFamilies: string[]
  isLoading: boolean
  height?: number
}

export function SignalZoneChart({
  data,
  enabledFamilies,
  isLoading,
  height = 400,
}: Props) {
  const wrapperRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const zoneCanvasRef = useRef<HTMLCanvasElement>(null)
  const chartRef = useRef<IChartApi | null>(null)

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

    const candle = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderDownColor: "#ef4444",
      borderUpColor: "#22c55e",
      wickDownColor: "#ef4444",
      wickUpColor: "#22c55e",
    })

    const candleData: CandlestickData[] = data.bars
      .filter((b) => b.open != null && b.high != null && b.low != null && b.close != null)
      .map((b) => ({
        time: toTime(b.date),
        open: b.open!,
        high: b.high!,
        low: b.low!,
        close: b.close!,
      }))

    candle.setData(candleData)

    if (enabledFamilies.includes("sma") && data.families.sma) {
      renderSmaLayer(chart, data.families.sma, data.bars)
    }

    if (enabledFamilies.includes("obv") && data.families.obv) {
      renderObvLayer(chart, data.families.obv, data.bars)
    }

    let rsiReps: RsiRepRef[] = []
    if (enabledFamilies.includes("rsi") && data.families.rsi) {
      rsiReps = collectRsiReps(data.families.rsi)
    }

    const markers: SeriesMarker<Time>[] = []
    if (enabledFamilies.includes("macd") && data.families.macd) {
      const macdMarkers = renderMacdMarkers(data.families.macd, data.bars)
      markers.push(...macdMarkers)
    }
    if (markers.length > 0) {
      markers.sort((a, b) => (a.time as string).localeCompare(b.time as string))
      createSeriesMarkers(candle, markers)
    }

    const drawZones = () => {
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

      for (const rsiRep of rsiReps) {
        const shadeOpacity = (0.04 + rsiRep.weight * 0.08).toFixed(3)
        for (let i = 0; i < data.bars.length && i < rsiRep.values.length; i++) {
          const rsiVal = rsiRep.values[i]
          if (rsiVal == null) continue

          const x = timeScale.timeToCoordinate(toTime(data.bars[i].date))
          if (x === null) continue

          const nextX =
            i + 1 < data.bars.length
              ? timeScale.timeToCoordinate(toTime(data.bars[i + 1].date))
              : null
          const barWidth = nextX !== null ? Math.max(nextX - x, 1) : 4

          if (rsiVal > rsiRep.overbought) {
            ctx.fillStyle = `rgba(239, 68, 68, ${shadeOpacity})`
            ctx.fillRect(x, 0, barWidth, chartHeight)
          } else if (rsiVal < rsiRep.oversold) {
            ctx.fillStyle = `rgba(34, 197, 94, ${shadeOpacity})`
            ctx.fillRect(x, 0, barWidth, chartHeight)
          }
        }
      }
    }

    chart.timeScale().subscribeVisibleLogicalRangeChange(drawZones)
    requestAnimationFrame(drawZones)
    chart.timeScale().fitContent()

    const container = containerRef.current
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        chart.applyOptions({ width: entry.contentRect.width })
        requestAnimationFrame(drawZones)
      }
    })
    observer.observe(container)

    return () => {
      observer.disconnect()
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(drawZones)
      chart.remove()
      chartRef.current = null
    }
  }, [data, enabledFamilies, height])

  if (isLoading) {
    return <Skeleton className="w-full" style={{ height }} />
  }

  if (!data) {
    return null
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Signal - {data.symbol}
        </span>
        <div className="flex items-center gap-2">
          {enabledFamilies.map((fam) => {
            const c = FAMILY_LINE_COLORS[fam] || "#888"
            return (
              <div key={fam} className="flex items-center gap-1">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: c }}
                />
                <span className="text-[9px] font-mono text-muted-foreground uppercase">
                  {fam}
                </span>
              </div>
            )
          })}
        </div>
      </div>
      <div
        ref={wrapperRef}
        className="relative rounded-md border"
        style={{ height }}
      >
        <canvas
          ref={zoneCanvasRef}
          className="pointer-events-none absolute inset-0 z-0"
        />
        <div
          ref={containerRef}
          className="absolute inset-0 z-10"
        />
      </div>
      <div className="flex flex-wrap items-center gap-3 text-[9px] text-muted-foreground">
        {enabledFamilies.includes("sma") && (
          <div className="flex items-center gap-1">
            <span className="inline-block h-0.5 w-3 rounded-full bg-green-500" />
            <span>Tendance (SMA)</span>
          </div>
        )}
        {enabledFamilies.includes("macd") && (
          <div className="flex items-center gap-1">
            <span className="text-green-500 text-[8px]">&#9650;</span>
            <span className="text-red-500 text-[8px]">&#9660;</span>
            <span>Momentum (MACD)</span>
          </div>
        )}
        {enabledFamilies.includes("rsi") && (
          <div className="flex items-center gap-1">
            <span className="inline-block h-2 w-3 rounded-sm bg-orange-500/30" />
            <span>Oscillation (RSI)</span>
          </div>
        )}
        {enabledFamilies.includes("obv") && (
          <div className="flex items-center gap-1">
            <span className="inline-block h-2 w-1.5 rounded-sm bg-green-500/50" />
            <span className="inline-block h-2 w-1.5 rounded-sm bg-red-500/50" />
            <span>Volume (OBV)</span>
          </div>
        )}
      </div>
    </div>
  )
}
