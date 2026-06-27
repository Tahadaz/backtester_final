"use client"

import { useEffect, useRef } from "react"
import { useParams, useRouter, useSearchParams } from "next/navigation"
import { ArrowLeft } from "lucide-react"
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  LineSeries,
  createChart,
  type CandlestickData,
  type IChartApi,
  type LineData,
  type Time,
} from "lightweight-charts"
import { useSupportResistanceMethodDetail } from "@/hooks/use-api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { formatNumber } from "@/lib/format"
import { horizonLabel } from "@/lib/horizon"
import type { SupportResistanceChart, SupportResistanceMethod } from "@/lib/api"

function fmtPrice(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "--"
  return formatNumber(value, 2)
}

function statusBadgeClass(status: string): string {
  if (status === "available") return "border-emerald-300 text-emerald-700"
  if (status === "ignored") return "border-amber-300 text-amber-700"
  return "border-slate-300 text-slate-600"
}

function normalizeInputValue(value: unknown): string {
  if (value == null) return "--"
  if (typeof value === "number") return formatNumber(value, 4)
  if (typeof value === "string" || typeof value === "boolean") return String(value)
  if (Array.isArray(value)) return `${value.length} elements`
  if (typeof value === "object") return `${Object.keys(value as Record<string, unknown>).length} champs`
  return String(value)
}

function methodKeyValues(method: SupportResistanceMethod | null): Array<{ key: string; value: string }> {
  const inputs = method?.inputs ?? {}
  return Object.entries(inputs)
    .filter(([key]) => key !== "chart" && key !== "representatives")
    .slice(0, 12)
    .map(([key, value]) => ({ key, value: normalizeInputValue(value) }))
}

function toTime(value: string): Time {
  return value as unknown as Time
}

function MethodChart({ chart }: { chart: SupportResistanceChart | null | undefined }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container || !chart || chart.bars.length === 0) return

    if (chartRef.current) {
      chartRef.current.remove()
      chartRef.current = null
    }

    const instance = createChart(container, {
      width: container.clientWidth,
      height: 360,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#64748b",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(148, 163, 184, 0.14)" },
        horzLines: { color: "rgba(148, 163, 184, 0.14)" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: false },
    })
    chartRef.current = instance

    const candle = instance.addSeries(CandlestickSeries, {
      upColor: "#16a34a",
      downColor: "#dc2626",
      borderDownColor: "#dc2626",
      borderUpColor: "#16a34a",
      wickDownColor: "#dc2626",
      wickUpColor: "#16a34a",
    })

    const candleData: CandlestickData[] = chart.bars
      .filter((bar) => bar.open != null && bar.high != null && bar.low != null && bar.close != null)
      .map((bar) => ({
        time: toTime(bar.date),
        open: bar.open!,
        high: bar.high!,
        low: bar.low!,
        close: bar.close!,
      }))
    candle.setData(candleData)

    const palette = ["#2563eb", "#f59e0b", "#7c3aed", "#059669", "#dc2626", "#0891b2", "#ca8a04", "#be123c"]
    chart.sources.forEach((source, index) => {
      const values = source.indicator.plot_values ?? []
      const lineData: LineData[] = []
      values.forEach((value, valueIndex) => {
        if (value == null || chart.bars[valueIndex] == null) return
        lineData.push({ time: toTime(chart.bars[valueIndex]!.date), value })
      })
      if (lineData.length === 0) return
      const line = instance.addSeries(LineSeries, {
        color: palette[index % palette.length] ?? "#2563eb",
        lineWidth: 2,
        priceLineVisible: true,
        lastValueVisible: true,
        crosshairMarkerVisible: false,
      })
      line.setData(lineData)
    })

    instance.timeScale().fitContent()
    const observer = new ResizeObserver(() => {
      instance.applyOptions({ width: container.clientWidth })
      instance.timeScale().fitContent()
    })
    observer.observe(container)

    return () => {
      observer.disconnect()
      instance.remove()
      chartRef.current = null
    }
  }, [chart])

  if (!chart || chart.bars.length === 0) {
    return <div className="rounded-md border bg-muted/20 p-4 text-xs text-muted-foreground">Chart indisponible pour cette methode.</div>
  }

  return <div ref={containerRef} className="w-full rounded-md border bg-background" />
}

export default function SupportResistanceMethodPage() {
  const params = useParams()
  const router = useRouter()
  const searchParams = useSearchParams()
  const methodId = decodeURIComponent(params.id as string)
  const symbol = (searchParams.get("symbol") ?? "").trim().toUpperCase()
  const horizon = (searchParams.get("horizon") ?? "monthly").trim().toLowerCase()
  const variant = (searchParams.get("variant") ?? "expanded").trim().toLowerCase()
  const cooldownBars = Number(searchParams.get("cooldown") ?? 0)
  const costBps = 33

  const detail = useSupportResistanceMethodDetail(methodId && symbol ? symbol : null, horizon, methodId, costBps, cooldownBars, variant, Boolean(symbol && methodId))

  if (!symbol) {
    return <div className="p-6 text-center text-sm text-muted-foreground">Parametre &quot;symbol&quot; manquant dans l&apos;URL.</div>
  }

  if (detail.isLoading && !detail.data) {
    return (
      <div className="mx-auto max-w-5xl space-y-4 p-6">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-80 w-full" />
      </div>
    )
  }

  if (detail.error || !detail.data) {
    return (
      <div className="mx-auto max-w-5xl p-6">
        <Card className="border-destructive/50">
          <CardContent className="py-8 text-center">
            <p className="text-sm font-medium text-destructive">Erreur lors du chargement de la methode SR</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {detail.error instanceof Error ? detail.error.message : "Methode introuvable"}
            </p>
          </CardContent>
        </Card>
      </div>
    )
  }

  const data = detail.data
  const method = data.method
  const inputRows = methodKeyValues(method)

  return (
    <div className="mx-auto max-w-5xl space-y-5 p-6">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => router.back()} className="gap-1">
          <ArrowLeft className="h-3.5 w-3.5" />
          Retour
        </Button>
        <div>
          <h1 className="text-base font-bold">{method.label}</h1>
          <p className="text-xs text-muted-foreground">
            {symbol} - {horizonLabel(horizon)} - {data.as_of}
          </p>
        </div>
      </div>

      {method.id === "score_inversion" && (
        <Card className="border-amber-300 bg-amber-50/60">
          <CardContent className="py-3 text-xs text-amber-900">
            Cette methode est calculee a la demande pour eviter de ralentir le chargement principal.
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="px-4 pb-2 pt-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <CardTitle className="text-sm">{method.label}</CardTitle>
              <p className="text-xs text-muted-foreground">{method.explanation || data.summary_explanation}</p>
            </div>
            <Badge variant="outline" className={`text-[10px] ${statusBadgeClass(method.status)}`}>
              {method.status}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4 px-4 pb-4">
          <MethodChart chart={data.chart ?? (method.inputs?.chart as SupportResistanceChart | undefined)} />
          <div className="grid gap-2 sm:grid-cols-3">
            <div className="rounded-md border bg-muted/20 p-3">
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Cloture</p>
              <p className="font-mono text-base font-semibold">{fmtPrice(data.current_close)}</p>
            </div>
            <div className="rounded-md border bg-emerald-50/60 p-3">
              <p className="text-[10px] uppercase tracking-wide text-emerald-700">Support methode</p>
              <p className="font-mono text-base font-semibold text-emerald-700">{fmtPrice(method.support)}</p>
            </div>
            <div className="rounded-md border bg-red-50/60 p-3">
              <p className="text-[10px] uppercase tracking-wide text-red-700">Resistance methode</p>
              <p className="font-mono text-base font-semibold text-red-700">{fmtPrice(method.resistance)}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="px-4 pb-2 pt-3">
          <CardTitle className="text-xs font-semibold">Contexte de calcul</CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-4">
          <div className="grid gap-2 sm:grid-cols-2">
            {inputRows.length > 0 ? (
              inputRows.map((row) => (
                <div key={row.key} className="flex items-center justify-between gap-2 rounded bg-muted/20 px-2 py-1.5">
                  <span className="text-[10px] text-muted-foreground">{row.key}</span>
                  <span className="text-[11px] font-mono">{row.value}</span>
                </div>
              ))
            ) : (
              <p className="text-xs text-muted-foreground">Aucun detail disponible.</p>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
