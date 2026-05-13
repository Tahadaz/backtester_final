"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineStyle,
  createChart,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type Time,
} from "lightweight-charts"
import type { OhlcvHistory } from "@/lib/api"

interface OhlcvHistoryChartProps {
  history: OhlcvHistory
  height?: number
}

type OhlcvBar = OhlcvHistory["bars"][number]

function toTime(date: string): Time {
  return date as unknown as Time
}

function parseLocalDate(value: string) {
  const [year, month, day] = value.split("-").map(Number)
  return new Date(year, month - 1, day, 12, 0, 0, 0)
}

function formatDateKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(
    date.getDate(),
  ).padStart(2, "0")}`
}

function dateKey(value: string | null | undefined) {
  const key = (value ?? "").slice(0, 10)
  return /^\d{4}-\d{2}-\d{2}$/.test(key) ? key : null
}

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value)
}

function decimalPlaces(value: number) {
  if (!Number.isFinite(value)) return 0
  const normalized = value.toString().toLowerCase()
  if (normalized.includes("e-")) {
    const [, exponent] = normalized.split("e-")
    return Number(exponent)
  }
  const parts = normalized.split(".")
  return parts[1]?.length ?? 0
}

function inferPricePrecision(bars: OhlcvBar[]) {
  let maxPrecision = 0

  for (const bar of bars) {
    for (const value of [bar.open, bar.high, bar.low, bar.close]) {
      if (finiteNumber(value)) {
        maxPrecision = Math.max(maxPrecision, decimalPlaces(value))
      }
    }
  }

  return Math.min(Math.max(maxPrecision, 2), 4)
}

function buildChartData(history: OhlcvHistory) {
  const barsByDate = new Map<string, OhlcvBar>()

  for (const bar of history.bars) {
    const key = dateKey(bar.date)
    if (!key) continue
    barsByDate.set(key, { ...bar, date: key })
  }

  const bars = [...barsByDate.values()].sort((a, b) => a.date.localeCompare(b.date))
  const candleData: CandlestickData[] = bars
    .filter(
      (bar) =>
        finiteNumber(bar.open) &&
        finiteNumber(bar.high) &&
        finiteNumber(bar.low) &&
        finiteNumber(bar.close),
    )
    .map((bar) => ({
      time: toTime(bar.date),
      open: bar.open!,
      high: bar.high!,
      low: bar.low!,
      close: bar.close!,
    }))

  const volumeData: HistogramData[] = bars
    .filter((bar) => finiteNumber(bar.volume))
    .map((bar) => {
      const rising = (bar.close ?? 0) >= (bar.open ?? bar.close ?? 0)
      return {
        time: toTime(bar.date),
        value: bar.volume ?? 0,
        color: rising ? "rgba(20, 184, 166, 0.55)" : "rgba(239, 68, 68, 0.55)",
      }
    })

  return { bars, candleData, volumeData }
}

function chartErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Erreur de rendu du graphique"
}

export function OhlcvHistoryChart({ history, height = 520 }: OhlcvHistoryChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const [chartError, setChartError] = useState<string | null>(null)
  const chartData = useMemo(() => buildChartData(history), [history])
  const precision = useMemo(() => inferPricePrecision(chartData.bars), [chartData.bars])

  useEffect(() => {
    const container = containerRef.current
    let observer: ResizeObserver | null = null
    let isDisposed = false

    function removeChart() {
      if (!chartRef.current) return
      try {
        chartRef.current.remove()
      } catch {
        // Chart teardown should never prevent the detail sheet from closing.
      }
      chartRef.current = null
    }

    removeChart()
    setChartError(null)

    if (!container || chartData.candleData.length === 0) {
      return () => removeChart()
    }

    function createOrResize(width: number) {
      if (isDisposed || !container) return
      const nextWidth = Math.max(1, Math.floor(width))
      const existingChart = chartRef.current

      if (existingChart) {
        try {
          existingChart.applyOptions({ width: nextWidth, height })
        } catch (error) {
          removeChart()
          if (!isDisposed) setChartError(chartErrorMessage(error))
        }
        return
      }

      try {
        const chart = createChart(container, {
          width: nextWidth,
          height,
          layout: {
            background: { type: ColorType.Solid, color: "transparent" },
            textColor: "#64748b",
            fontSize: 11,
            fontFamily: "var(--font-sans), system-ui, sans-serif",
            panes: {
              enableResize: true,
              separatorColor: "rgba(148, 163, 184, 0.28)",
              separatorHoverColor: "rgba(148, 163, 184, 0.38)",
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

        const pricePane = chart.panes()[0]
        const volumePane = chart.addPane(true)
        pricePane?.setStretchFactor(3)
        volumePane.setStretchFactor(1)

        const candleSeries = chart.addSeries(
          CandlestickSeries,
          {
            upColor: "#14b8a6",
            downColor: "#ef4444",
            borderUpColor: "#0f766e",
            borderDownColor: "#b91c1c",
            wickUpColor: "#0f766e",
            wickDownColor: "#b91c1c",
            priceLineVisible: false,
            priceFormat: {
              type: "price",
              precision,
              minMove: 1 / 10 ** precision,
            },
          },
          0,
        )

        const volumeSeries = chart.addSeries(
          HistogramSeries,
          {
            priceFormat: { type: "volume", precision: 0, minMove: 1 },
            priceLineVisible: false,
            lastValueVisible: false,
            base: 0,
          },
          1,
        )

        candleSeries.setData(chartData.candleData)
        volumeSeries.setData(chartData.volumeData)

        candleSeries.priceScale().applyOptions({
          scaleMargins: { top: 0.08, bottom: 0.04 },
          borderVisible: false,
        })
        volumeSeries.priceScale().applyOptions({
          scaleMargins: { top: 0.12, bottom: 0 },
          borderVisible: false,
        })

        volumeSeries.createPriceLine({
          price: 0,
          color: "rgba(148, 163, 184, 0.28)",
          lineWidth: 1,
          lineStyle: LineStyle.Solid,
          axisLabelVisible: false,
          title: "",
          lineVisible: true,
        })

        if (chartData.candleData.length > 1) {
          const lastBarDate = String(chartData.candleData[chartData.candleData.length - 1].time)
          const lastDate = parseLocalDate(lastBarDate)
          const startDate = new Date(lastDate)
          startDate.setFullYear(startDate.getFullYear() - 1)
          chart.timeScale().setVisibleRange({
            from: toTime(formatDateKey(startDate)),
            to: toTime(lastBarDate),
          })
        } else {
          chart.timeScale().fitContent()
        }
      } catch (error) {
        removeChart()
        if (!isDisposed) setChartError(chartErrorMessage(error))
      }
    }

    observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        createOrResize(entry.contentRect.width)
      }
    })
    observer.observe(container)
    createOrResize(container.clientWidth)

    return () => {
      isDisposed = true
      observer?.disconnect()
      removeChart()
    }
  }, [chartData.candleData, chartData.volumeData, height, precision])

  if (chartData.candleData.length === 0) {
    return (
      <div
        className="flex w-full items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 text-sm text-muted-foreground"
        style={{ height }}
      >
        Aucun chandelier OHLC valide.
      </div>
    )
  }

  return (
    <div className="relative w-full overflow-hidden rounded-xl" style={{ height }}>
      <div ref={containerRef} className="h-full w-full" />
      {chartError && (
        <div className="absolute inset-0 flex items-center justify-center bg-white/90 px-4 text-center text-sm text-muted-foreground">
          Graphique indisponible: {chartError}
        </div>
      )}
    </div>
  )
}
