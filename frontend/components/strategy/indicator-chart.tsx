"use client"

import dynamic from "next/dynamic"
import { memo, useMemo } from "react"
import type { Config as PlotlyConfig, Data as PlotlyData, Layout as PlotlyLayout } from "plotly.js"
import type { PlotParams } from "react-plotly.js"
import { AlertCircle } from "lucide-react"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  INDICATOR_FAMILY_ORDER,
  INDICATOR_META_BY_KEY,
  type IndicatorFamilyKey,
} from "./indicator-config"
import type { IndicatorSeriesResponse } from "@/lib/api"
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

type PlotPayload = Record<string, unknown>
type PlotlyAxisRef =
  | "y"
  | "y2"
  | "y3"
  | "y4"
  | "y5"
  | "y6"
  | "y7"
  | "y8"
  | "y9"
  | "y10"
  | "y11"
  | "y12"
  | "y13"
  | "y14"
  | "y15"
  | "y16"
  | "y17"
  | "y18"
  | "y19"
  | "y20"
  | "y21"

const FAMILY_COLORS: Record<IndicatorFamilyKey, string> = {
  sma: "#2563eb",
  ema: "#0f766e",
  ema_cross: "#0ea5e9",
  ichimoku: "#14b8a6",
  psar: "#1d4ed8",
  macd: "#9333ea",
  roc: "#8b5cf6",
  trix: "#7c3aed",
  adx: "#6d28d9",
  tsi: "#a855f7",
  rsi: "#f97316",
  stochastic: "#f59e0b",
  cci: "#ea580c",
  mfi: "#fb923c",
  uo: "#f97316",
  obv: "#10b981",
  cmf: "#059669",
  ad: "#16a34a",
  vwap: "#14b8a6",
  fi: "#0d9488",
}

function sanitizeY(values: Array<number | null | undefined>): Array<number | null> {
  return values.map((value) => (typeof value === "number" && Number.isFinite(value) ? value : null))
}

function numericSeries(value: unknown): Array<number | null> {
  return Array.isArray(value) ? sanitizeY(value as Array<number | null | undefined>) : []
}

function lineTrace(
  x: string[],
  y: Array<number | null | undefined>,
  name: string,
  color: string,
  yaxis: PlotlyAxisRef,
  options?: {
    width?: number
    dash?: "solid" | "dash" | "dot"
    fill?: "tonexty"
    fillcolor?: string
    mode?: "lines" | "markers"
  },
): PlotlyData {
  return {
    type: "scatter",
    mode: options?.mode ?? "lines",
    x,
    y: sanitizeY(y),
    name,
    yaxis,
    line:
      options?.mode === "markers"
        ? undefined
        : { color, width: options?.width ?? 2, dash: options?.dash ?? "solid" },
    marker: options?.mode === "markers" ? { color, size: 6 } : undefined,
    fill: options?.fill,
    fillcolor: options?.fillcolor,
    connectgaps: false,
  }
}

function axisKeyFor(axis: PlotlyAxisRef): "yaxis" | `yaxis${number}` {
  return axis === "y" ? "yaxis" : (`yaxis${axis.slice(1)}` as `yaxis${number}`)
}

function horizontalShape(
  axis: PlotlyAxisRef,
  value: number,
  color: string,
): NonNullable<PlotlyLayout["shapes"]>[number] {
  return {
    type: "line",
    xref: "paper",
    x0: 0,
    x1: 1,
    yref: axis,
    y0: value,
    y1: value,
    line: { color, width: 1, dash: "dot" },
  }
}

function renderOverlayPayload(
  traces: PlotlyData[],
  payload: PlotPayload,
  response: IndicatorSeriesResponse,
  family: IndicatorFamilyKey,
) {
  const axis: PlotlyAxisRef = "y"
  const color = FAMILY_COLORS[family]
  const title = INDICATOR_META_BY_KEY[family].shortLabel
  const kind = String(payload.type ?? "")

  if (kind === "overlay") {
    traces.push(
      lineTrace(
        response.dates,
        numericSeries(payload.values),
        String(payload.name ?? title),
        color,
        axis,
      ),
    )
    return
  }

  if (kind === "overlay_dual") {
    traces.push(
      lineTrace(
        response.dates,
        numericSeries(payload.fast),
        String(payload.fast_label ?? `${title} Fast`),
        color,
        axis,
      ),
    )
    traces.push(
      lineTrace(
        response.dates,
        numericSeries(payload.slow),
        String(payload.slow_label ?? `${title} Slow`),
        "#7c3aed",
        axis,
        { dash: "dash" },
      ),
    )
    return
  }

  if (kind === "overlay_cloud") {
    traces.push(
      lineTrace(response.dates, numericSeries(payload.tenkan_sen), "Tenkan", "#f97316", axis),
    )
    traces.push(
      lineTrace(response.dates, numericSeries(payload.kijun_sen), "Kijun", "#2563eb", axis),
    )
    traces.push(
      lineTrace(response.dates, numericSeries(payload.senkou_a), "Senkou A", "#16a34a", axis),
    )
    traces.push(
      lineTrace(response.dates, numericSeries(payload.senkou_b), "Senkou B", "#dc2626", axis, {
        fill: "tonexty",
        fillcolor: "rgba(37, 99, 235, 0.10)",
      }),
    )
    return
  }

  if (kind === "overlay_dots") {
    traces.push(
      lineTrace(
        response.dates,
        numericSeries(payload.values),
        String(payload.name ?? title),
        color,
        axis,
        { mode: "markers" },
      ),
    )
    return
  }

  if (kind === "overlay_band") {
    traces.push(
      lineTrace(
        response.dates,
        numericSeries(payload.values),
        String(payload.name ?? title),
        color,
        axis,
      ),
    )
    traces.push(
      lineTrace(response.dates, numericSeries(payload.upper), "Upper Band", "#94a3b8", axis, {
        dash: "dot",
        width: 1,
      }),
    )
    traces.push(
      lineTrace(response.dates, numericSeries(payload.lower), "Lower Band", "#94a3b8", axis, {
        dash: "dot",
        width: 1,
        fill: "tonexty",
        fillcolor: "rgba(148, 163, 184, 0.10)",
      }),
    )
  }
}

function renderSecondaryPayload(
  traces: PlotlyData[],
  shapes: NonNullable<PlotlyLayout["shapes"]>,
  axisRanges: Partial<Record<PlotlyAxisRef, [number, number]>>,
  response: IndicatorSeriesResponse,
  family: IndicatorFamilyKey,
  axis: PlotlyAxisRef,
) {
  const payload = (response.plot_payload ?? {}) as PlotPayload
  const color = FAMILY_COLORS[family]
  const title = INDICATOR_META_BY_KEY[family].shortLabel

  if (Array.isArray(payload.thresholds)) {
    for (const threshold of payload.thresholds) {
      if (typeof threshold === "number") {
        shapes.push(horizontalShape(axis, threshold, "#a1a1aa"))
      }
    }
  }
  if (payload.zero_line) {
    shapes.push(horizontalShape(axis, 0, "#94a3b8"))
  }
  if (
    Array.isArray(payload.y_range) &&
    payload.y_range.length === 2 &&
    typeof payload.y_range[0] === "number" &&
    typeof payload.y_range[1] === "number"
  ) {
    axisRanges[axis] = [payload.y_range[0], payload.y_range[1]]
  }

  if (Array.isArray(payload.histogram)) {
    const histogram = numericSeries(payload.histogram)
    traces.push({
      type: "bar",
      x: response.dates,
      y: histogram,
      name: `${title} Histogram`,
      yaxis: axis,
      marker: {
        color: histogram.map((value) =>
          value == null
            ? "rgba(148,163,184,0.2)"
            : value >= 0
              ? "rgba(22,163,74,0.75)"
              : "rgba(220,38,38,0.75)",
        ),
      },
      opacity: 0.8,
    })
    if (Array.isArray(payload.macd_line)) {
      traces.push(lineTrace(response.dates, numericSeries(payload.macd_line), `${title} Line`, color, axis))
    }
    if (Array.isArray(payload.signal_line)) {
      traces.push(
        lineTrace(response.dates, numericSeries(payload.signal_line), `${title} Signal`, "#f59e0b", axis),
      )
    }
    return
  }

  if (Array.isArray(payload.values)) {
    traces.push(
      lineTrace(
        response.dates,
        numericSeries(payload.values),
        String(payload.name ?? title),
        color,
        axis,
      ),
    )
  }
  if (Array.isArray(payload.ema_values)) {
    traces.push(
      lineTrace(
        response.dates,
        numericSeries(payload.ema_values),
        `${title} EMA`,
        "#f59e0b",
        axis,
        { dash: "dash" },
      ),
    )
  }
  for (const [key, label, traceColor] of [
    ["plus_di", "+DI", "#16a34a"],
    ["minus_di", "-DI", "#dc2626"],
    ["adx", "ADX", "#0f172a"],
    ["k", "%K", "#8b5cf6"],
    ["d", "%D", "#f97316"],
    ["obv", title, color],
    ["ad", title, color],
  ] as const) {
    if (Array.isArray(payload[key])) {
      traces.push(lineTrace(response.dates, numericSeries(payload[key]), label, traceColor, axis))
    }
  }
}

export const IndicatorChart = memo(function IndicatorChart({
  priceSeries,
  priceLoading,
  priceError,
  families,
}: IndicatorChartProps) {
  const enabledFamilies = useMemo(
    () => INDICATOR_FAMILY_ORDER.filter((family) => families[family].enabled),
    [families],
  )

  const activeResponses = useMemo(
    () =>
      INDICATOR_FAMILY_ORDER
        .filter((family) => families[family].enabled && families[family].data)
        .map((family) => ({
          family,
          response: families[family].data!,
          payload: (families[family].data?.plot_payload ?? null) as PlotPayload | null,
        })),
    [families],
  )

  const fallbackSeries = activeResponses[0]?.response ?? null
  const baseSeries =
    priceSeries ??
    (fallbackSeries
      ? { dates: fallbackSeries.dates, close: fallbackSeries.close }
      : null)

  const figure = useMemo(() => {
    if (!baseSeries) return null
    if (enabledFamilies.length === 0 && activeResponses.length === 0) return null

    const traces: PlotlyData[] = []
    const shapes: NonNullable<PlotlyLayout["shapes"]> = []
    const axisRanges: Partial<Record<PlotlyAxisRef, [number, number]>> = {}
    const secondaryFamilies = activeResponses.filter(
      ({ payload }) => String(payload?.type ?? "") === "secondary_yaxis",
    )
    const nSubplots = secondaryFamilies.length
    const gap = nSubplots > 0 ? Math.min(0.015, 0.18 / nSubplots) : 0
    const mainHeight = nSubplots > 0 ? 0.36 : 1
    const available = 1 - mainHeight - gap * nSubplots
    const subHeight = nSubplots > 0 ? Math.max(available / nSubplots, 0.02) : 0
    const mainDomain: [number, number] = nSubplots > 0 ? [1 - mainHeight, 1] : [0, 1]

    traces.push(lineTrace(baseSeries.dates, baseSeries.close, "Close", "#0f172a", "y"))

    for (const { family, payload, response } of activeResponses) {
      if (!payload) {
        traces.push(
          lineTrace(
            response.dates,
            response.indicator_values,
            INDICATOR_META_BY_KEY[family].shortLabel,
            FAMILY_COLORS[family],
            "y",
          ),
        )
        if (response.indicator_overlay) {
          traces.push(
            lineTrace(
              response.dates,
              response.indicator_overlay,
              `${INDICATOR_META_BY_KEY[family].shortLabel} Overlay`,
              "#f59e0b",
              "y",
              { dash: "dash" },
            ),
          )
        }
        continue
      }

      const type = String(payload.type ?? "")
      if (type !== "secondary_yaxis") {
        renderOverlayPayload(traces, payload, response, family)
      }
    }

    secondaryFamilies.forEach(({ family, response }, index) => {
      const axis = `y${index + 2}` as PlotlyAxisRef
      renderSecondaryPayload(traces, shapes, axisRanges, response, family, axis)
    })

    const layout: Partial<PlotlyLayout> & Record<string, unknown> = {
      autosize: true,
      height: 360 + nSubplots * 180,
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
      hovermode: "x unified",
      barmode: "overlay",
      showlegend: true,
      legend: { orientation: "h", y: 1.06 },
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
    secondaryFamilies.forEach(({ family }, index) => {
      const axis = `y${index + 2}` as PlotlyAxisRef
      const key = axisKeyFor(axis)
      const bottom = top - subHeight
      layout[key] = {
        domain: [bottom, top],
        title: { text: INDICATOR_META_BY_KEY[family].shortLabel },
        showgrid: true,
        gridcolor: "oklch(0.91 0.005 250)",
        zeroline: true,
        range: axisRanges[axis],
      }
      top = bottom - gap
    })

    return { data: traces, layout }
  }, [activeResponses, baseSeries, enabledFamilies.length])

  const config = useMemo<Partial<PlotlyConfig>>(
    () => ({
      responsive: true,
      displaylogo: false,
      modeBarButtonsToRemove: ["lasso2d", "select2d"],
    }),
    [],
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
