"use client"

import dynamic from "next/dynamic"
import { memo, useMemo } from "react"
import type {
  Config as PlotlyConfig,
  Data as PlotlyData,
  Frame as PlotlyFrame,
  Layout as PlotlyLayout,
} from "plotly.js"
import type { PlotParams } from "react-plotly.js"
import type { PlotlyFigure } from "@/lib/api"

const Plot = dynamic<PlotParams>(() => import("react-plotly.js"), {
  ssr: false,
  loading: () => (
    <div className="flex h-96 items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
      Loading chart...
    </div>
  ),
})

type PlotlyChartProps = {
  figure?: PlotlyFigure
  data?: PlotlyFigure
}

export const PlotlyChart = memo(function PlotlyChart({ figure, data }: PlotlyChartProps) {
  const chartFigure = figure ?? data
  if (!chartFigure) return null

  const plotData = useMemo<PlotlyData[]>(
    () => chartFigure.data.map((trace) => trace as unknown as PlotlyData),
    [chartFigure.data]
  )

  const plotFrames = useMemo<PlotlyFrame[] | undefined>(
    () => chartFigure.frames?.map((frame) => frame as unknown as PlotlyFrame),
    [chartFigure.frames]
  )

  const plotLayout = useMemo<Partial<PlotlyLayout>>(() => {
    const base = chartFigure.layout as Partial<PlotlyLayout>
    const baseXAxis = (base.xaxis ?? {}) as Partial<PlotlyLayout["xaxis"]>
    const baseYAxis = (base.yaxis ?? {}) as Partial<PlotlyLayout["yaxis"]>

    return {
      ...base,
      autosize: true,
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      font: {
        family: "var(--font-sans), system-ui, sans-serif",
        size: 11,
        color: "oklch(0.50 0.01 250)",
      },
      margin: { l: 50, r: 20, t: 40, b: 40, ...((base.margin ?? {}) as Record<string, number>) },
      xaxis: {
        ...baseXAxis,
        gridcolor: "oklch(0.91 0.005 250)",
        zerolinecolor: "oklch(0.91 0.005 250)",
      },
      yaxis: {
        ...baseYAxis,
        gridcolor: "oklch(0.91 0.005 250)",
        zerolinecolor: "oklch(0.91 0.005 250)",
      },
    }
  }, [chartFigure.layout])

  const plotConfig = useMemo<Partial<PlotlyConfig>>(
    () => ({
      responsive: true,
      displayModeBar: true,
      displaylogo: false,
      modeBarButtonsToRemove: ["lasso2d", "select2d"],
    }),
    []
  )

  return (
    <div className="w-full overflow-hidden rounded-lg">
      <Plot
        data={plotData}
        layout={plotLayout}
        frames={plotFrames}
        config={plotConfig}
        style={{ width: "100%", height: "400px" }}
        useResizeHandler
      />
    </div>
  )
})
