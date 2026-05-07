"use client"

import { PlotlyChart } from "@/components/run/plotly-chart"

export interface IndicatorOverlaySeries {
  id: string
  label: string
  values: Array<number | null>
}

interface PriceSignalsChartProps {
  close: number[] | null | undefined
  position: number[] | null | undefined
  dates: string[] | null | undefined
  title?: string
  indicatorSeries?: IndicatorOverlaySeries[]
}

const OVERLAY_COLORS = [
  "#f59e0b",
  "#22d3ee",
  "#a78bfa",
  "#f43f5e",
  "#84cc16",
  "#38bdf8",
  "#fb7185",
  "#14b8a6",
]

export function PriceSignalsChart({ close, position, dates, title, indicatorSeries }: PriceSignalsChartProps) {
  if (!close || !position || !dates || close.length < 2) {
    return (
      <p className="text-xs text-muted-foreground border rounded p-2 bg-muted/20">
        Série de prix non disponible — re-lancez le backtest.
      </p>
    )
  }

  const buyX: string[] = []
  const buyY: number[] = []
  const sellX: string[] = []
  const sellY: number[] = []
  const shortX: string[] = []
  const shortY: number[] = []
  const coverX: string[] = []
  const coverY: number[] = []

  for (let i = 1; i < position.length; i++) {
    const prev = position[i - 1]
    const cur = position[i]
    const d = dates[i] ?? ""
    const p = close[i] ?? 0
    if (prev === 0 && cur > 0) { buyX.push(d); buyY.push(p) }
    else if (prev > 0 && cur === 0) { sellX.push(d); sellY.push(p) }
    else if (prev === 0 && cur < 0) { shortX.push(d); shortY.push(p) }
    else if (prev < 0 && cur === 0) { coverX.push(d); coverY.push(p) }
  }

  const traces: Record<string, unknown>[] = [
    {
      x: dates, y: close, type: "scatter", mode: "lines",
      line: { color: "#94a3b8", width: 1.5 },
      name: "Cours", showlegend: true,
    },
    {
      x: buyX, y: buyY, type: "scatter", mode: "markers",
      marker: { symbol: "triangle-up", size: 9, color: "#22c55e" },
      name: "Achat", showlegend: true,
    },
    {
      x: sellX, y: sellY, type: "scatter", mode: "markers",
      marker: { symbol: "triangle-down", size: 9, color: "#f97316" },
      name: "Vente", showlegend: true,
    },
  ]
  if (shortX.length) {
    traces.push({
      x: shortX, y: shortY, type: "scatter", mode: "markers",
      marker: { symbol: "triangle-down", size: 9, color: "#ef4444" },
      name: "Short", showlegend: true,
    })
    traces.push({
      x: coverX, y: coverY, type: "scatter", mode: "markers",
      marker: { symbol: "triangle-up", size: 9, color: "#a78bfa" },
      name: "Rachat", showlegend: true,
    })
  }
  if (indicatorSeries && indicatorSeries.length > 0) {
    indicatorSeries.forEach((series, idx) => {
      traces.push({
        x: dates,
        y: series.values,
        type: "scatter",
        mode: "lines",
        yaxis: "y2",
        line: { width: 1.2, color: OVERLAY_COLORS[idx % OVERLAY_COLORS.length] },
        opacity: 0.9,
        name: series.label,
        showlegend: true,
      })
    })
  }

  const layout: Record<string, unknown> = {
    title: title ? { text: title, font: { size: 12 } } : undefined,
    height: 260,
    margin: { t: title ? 32 : 8, b: 36, l: 50, r: 8 },
    xaxis: { type: "date", tickfont: { size: 10 } },
    yaxis: { tickfont: { size: 10 } },
    yaxis2: indicatorSeries && indicatorSeries.length > 0
      ? { overlaying: "y", side: "right", tickfont: { size: 10 }, showgrid: false }
      : undefined,
    legend: { orientation: "h", y: -0.2, font: { size: 10 } },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: "currentColor" },
  }

  return <PlotlyChart figure={{ data: traces, layout }} />
}
