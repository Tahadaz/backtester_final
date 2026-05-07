"use client"

import dynamic from "next/dynamic"
import { memo, useMemo } from "react"
import type { Config as PlotlyConfig, Data as PlotlyData, Layout as PlotlyLayout } from "plotly.js"
import type { PlotParams } from "react-plotly.js"
import { AlertCircle } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Alert, AlertDescription } from "@/components/ui/alert"
import type { IndicatorExplorerState, IndicatorPriceSeries } from "./indicator-explorer"

const Plot = dynamic<PlotParams>(() => import("react-plotly.js"), {
  ssr: false,
  loading: () => (
    <div className="flex h-[420px] items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
      Loading chart...
    </div>
  ),
})

type IndicatorChartProps = {
  priceSeries: IndicatorPriceSeries | null
  priceLoading: boolean
  priceError: string | null
  families: IndicatorExplorerState
}

type SubplotFamily = "rsi" | "macd" | "obv"
type PlotlyAxisRef = "y" | "y2" | "y3" | "y4" | "y5"

function sanitizeY(values: Array<number | null | undefined>): Array<number | null> {
  return values.map((value) => value ?? null)
}

function lineTrace(
  x: string[],
  y: Array<number | null | undefined>,
  name: string,
  color: string,
  yaxis: PlotlyAxisRef,
): PlotlyData {
  return {
    type: "scatter",
    mode: "lines",
    x,
    y: sanitizeY(y),
    name,
    yaxis,
    line: { color, width: 2 },
    connectgaps: false,
  }
}

export const IndicatorChart = memo(function IndicatorChart({
  priceSeries,
  priceLoading,
  priceError,
  families,
}: IndicatorChartProps) {
  const activeFamilies = {
    sma: families.sma.enabled ? families.sma.data : null,
    rsi: families.rsi.enabled ? families.rsi.data : null,
    macd: families.macd.enabled ? families.macd.data : null,
    obv: families.obv.enabled ? families.obv.data : null,
  }

  const fallbackSeries = activeFamilies.sma ?? activeFamilies.rsi ?? activeFamilies.macd ?? activeFamilies.obv
  const baseSeries = priceSeries ?? (fallbackSeries ? { dates: fallbackSeries.dates, close: fallbackSeries.close } : null)

  const figure = useMemo(() => {
    if (!baseSeries) return null

    const traces: PlotlyData[] = []
    const shapes: NonNullable<PlotlyLayout["shapes"]> = []
    const subplots: SubplotFamily[] = []

    if (activeFamilies.rsi) subplots.push("rsi")
    if (activeFamilies.macd) subplots.push("macd")
    if (activeFamilies.obv) subplots.push("obv")

    const nSubplots = subplots.length
    const gap = nSubplots > 0 ? 0.02 : 0
    const mainHeight = nSubplots > 0 ? 0.48 : 1
    const subHeight = nSubplots > 0 ? (1 - mainHeight - gap * nSubplots) / nSubplots : 0
    const mainDomain: [number, number] = nSubplots > 0 ? [1 - mainHeight, 1] : [0, 1]

    const subplotAxisByFamily = new Map<SubplotFamily, PlotlyAxisRef>()
    let nextTop = mainDomain[0] - gap

    subplots.forEach((family, index) => {
      const axisName = `y${index + 2}` as PlotlyAxisRef
      subplotAxisByFamily.set(family, axisName)
      nextTop -= subHeight
      nextTop -= gap
    })

    traces.push(
      lineTrace(
        baseSeries.dates,
        baseSeries.close,
        "Close",
        "#0f172a",
        "y",
      )
    )

    if (activeFamilies.sma) {
      traces.push(
        lineTrace(
          activeFamilies.sma.dates,
          activeFamilies.sma.indicator_values,
          `SMA ${activeFamilies.sma.params.period ?? ""}`.trim(),
          "#2563eb",
          "y",
        )
      )
    }

    if (activeFamilies.rsi) {
      const axisName = subplotAxisByFamily.get("rsi") ?? "y2"
      traces.push(
        lineTrace(
          activeFamilies.rsi.dates,
          activeFamilies.rsi.indicator_values,
          `RSI ${activeFamilies.rsi.params.period ?? ""}`.trim(),
          "#7c3aed",
          axisName,
        )
      )
      const oversold = Number(activeFamilies.rsi.params.oversold ?? 30)
      const overbought = Number(activeFamilies.rsi.params.overbought ?? 70)
      for (const level of [oversold, overbought]) {
        shapes.push({
          type: "line",
          xref: "paper",
          x0: 0,
          x1: 1,
          yref: axisName,
          y0: level,
          y1: level,
          line: { color: "#a1a1aa", width: 1, dash: "dot" },
        })
      }
    }

    if (activeFamilies.macd) {
      const axisName = subplotAxisByFamily.get("macd") ?? "y2"
      traces.push({
        type: "bar",
        x: activeFamilies.macd.dates,
        y: sanitizeY(activeFamilies.macd.indicator_values),
        name: "MACD Histogram",
        yaxis: axisName,
        marker: {
          color: activeFamilies.macd.indicator_values.map((value) =>
            (value ?? 0) >= 0 ? "#16a34a" : "#dc2626"
          ),
        },
        opacity: 0.75,
      })
      traces.push(
        lineTrace(
          activeFamilies.macd.dates,
          activeFamilies.macd.indicator_overlay ?? [],
          "MACD Signal",
          "#f59e0b",
          axisName,
        )
      )
    }

    if (activeFamilies.obv) {
      const axisName = subplotAxisByFamily.get("obv") ?? "y2"
      traces.push(
        lineTrace(
          activeFamilies.obv.dates,
          activeFamilies.obv.indicator_values,
          `OBV EMA ${activeFamilies.obv.params.ema_period ?? ""}`.trim(),
          "#0891b2",
          axisName,
        )
      )
      for (const level of [-0.1, -0.03, 0.03, 0.1]) {
        shapes.push({
          type: "line",
          xref: "paper",
          x0: 0,
          x1: 1,
          yref: axisName,
          y0: level,
          y1: level,
          line: { color: "#a1a1aa", width: 1, dash: "dot" },
        })
      }
    }

    const layout: Partial<PlotlyLayout> & Record<string, unknown> = {
      autosize: true,
      height: 360 + nSubplots * 180,
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      hovermode: "x unified",
      showlegend: true,
      legend: { orientation: "h", y: 1.08 },
      margin: { l: 52, r: 16, t: 32, b: 36 },
      shapes,
      font: {
        family: "var(--font-sans), system-ui, sans-serif",
        size: 11,
        color: "oklch(0.50 0.01 250)",
      },
      xaxis: {
        domain: [0, 1],
        showgrid: true,
        gridcolor: "oklch(0.91 0.005 250)",
        showspikes: true,
        spikemode: "across",
        spikesnap: "cursor",
      },
      yaxis: {
        domain: mainDomain,
        title: { text: "Prix" },
        showgrid: true,
        gridcolor: "oklch(0.91 0.005 250)",
      },
    }

    let top = mainDomain[0] - gap
    subplots.forEach((family, index) => {
      const axisKey = `yaxis${index + 2}`
      const bottom = top - subHeight
      const axis: Record<string, unknown> = {
        domain: [bottom, top],
        showgrid: true,
        gridcolor: "oklch(0.91 0.005 250)",
      }

      if (family === "rsi") {
        axis.title = { text: "RSI" }
        axis.range = [0, 100]
      } else if (family === "macd") {
        axis.title = { text: "MACD" }
        axis.zeroline = true
      } else {
        axis.title = { text: "OBV" }
        axis.zeroline = true
      }

      layout[axisKey] = axis
      top = bottom - gap
    })

    return { data: traces, layout }
  }, [activeFamilies.macd, activeFamilies.obv, activeFamilies.rsi, activeFamilies.sma, baseSeries])

  const config = useMemo<Partial<PlotlyConfig>>(
    () => ({
      responsive: true,
      displaylogo: false,
      modeBarButtonsToRemove: ["lasso2d", "select2d"],
    }),
    []
  )

  if (!figure) {
    if (priceLoading) {
      return (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Explorateur</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex h-[420px] items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
              Chargement des prix...
            </div>
          </CardContent>
        </Card>
      )
    }

    if (priceError) {
      return (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Explorateur</CardTitle>
          </CardHeader>
          <CardContent>
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{priceError}</AlertDescription>
            </Alert>
          </CardContent>
        </Card>
      )
    }

    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Explorateur</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex h-[420px] items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
            Activez un indicateur pour commencer l'exploration.
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm">Explorateur</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="w-full overflow-hidden rounded-lg">
          <Plot
            data={figure.data as PlotlyData[]}
            layout={figure.layout}
            config={config}
            style={{ width: "100%", height: `${figure.layout.height ?? 420}px` }}
            useResizeHandler
          />
        </div>
      </CardContent>
    </Card>
  )
})
