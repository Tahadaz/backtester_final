"use client"

import { useEffect, useMemo, useRef } from "react"
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

function toTime(date: string): Time {
  return date as unknown as Time
}

function parseLocalDate(value: string) {
  const [year, month, day] = value.split("-").map(Number)
  return new Date(year, month - 1, day, 12, 0, 0, 0)
}

function formatDateKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(
    date.getDate()
  ).padStart(2, "0")}`
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

function inferPricePrecision(history: OhlcvHistory) {
  let maxPrecision = 0

  for (const bar of history.bars) {
    for (const value of [bar.open, bar.high, bar.low, bar.close]) {
      if (value != null) {
        maxPrecision = Math.max(maxPrecision, decimalPlaces(value))
      }
    }
  }

  return Math.min(Math.max(maxPrecision, 2), 4)
}

export function OhlcvHistoryChart({ history, height = 520 }: OhlcvHistoryChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const precision = useMemo(() => inferPricePrecision(history), [history])

  useEffect(() => {
    const container = containerRef.current
    if (!container || history.bars.length === 0) return

    if (chartRef.current) {
      chartRef.current.remove()
      chartRef.current = null
    }

    const chart = createChart(container, {
      width: container.clientWidth,
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
    pricePane.setStretchFactor(3)
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
      0
    )

    const volumeSeries = chart.addSeries(
      HistogramSeries,
      {
        priceFormat: { type: "volume", precision: 0, minMove: 1 },
        priceLineVisible: false,
        lastValueVisible: false,
        base: 0,
      },
      1
    )

    const candleData: CandlestickData[] = history.bars
      .filter((bar) => bar.open != null && bar.high != null && bar.low != null && bar.close != null)
      .map((bar) => ({
        time: toTime(bar.date),
        open: bar.open!,
        high: bar.high!,
        low: bar.low!,
        close: bar.close!,
      }))

    const volumeData: HistogramData[] = history.bars
      .filter((bar) => bar.volume != null)
      .map((bar) => {
        const rising = (bar.close ?? 0) >= (bar.open ?? bar.close ?? 0)
        return {
          time: toTime(bar.date),
          value: bar.volume ?? 0,
          color: rising ? "rgba(20, 184, 166, 0.55)" : "rgba(239, 68, 68, 0.55)",
        }
      })

    candleSeries.setData(candleData)
    volumeSeries.setData(volumeData)

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

    if (candleData.length > 1) {
      const lastBarDate = history.bars[history.bars.length - 1].date
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

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        chart.applyOptions({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        })
      }
    })
    observer.observe(container)

    return () => {
      observer.disconnect()
      chart.remove()
      chartRef.current = null
    }
  }, [height, history, precision])

  return <div ref={containerRef} className="w-full overflow-hidden rounded-xl" style={{ height }} />
}
