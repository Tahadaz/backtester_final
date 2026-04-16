"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { SignalBadge } from "@/components/dashboard-v1/signal-badge"
import type { SupportResistanceMethod, SupportResistanceResponse } from "@/lib/api"
import { formatNumber } from "@/lib/format"

function fmtPrice(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "--"
  return formatNumber(value, 2)
}

function fmtPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "--"
  return `${formatNumber(value, 2)}%`
}

function statusBadgeClass(status: string): string {
  if (status === "available") return "border-emerald-300 text-emerald-700"
  if (status === "ignored") return "border-amber-300 text-amber-700"
  return "border-slate-300 text-slate-600"
}

function methodDetails(method: SupportResistanceMethod): string[] {
  const inputs = method.inputs ?? {}

  if (method.id === "ma_anchor") {
    return [
      `Ancre ${fmtPrice((inputs.anchor as number | null | undefined) ?? null)}`,
      `${String(inputs.representative_count ?? 0)} reps`,
    ]
  }

  if (method.id === "score_inversion") {
    const thresholds = (inputs.thresholds ?? {}) as Record<string, unknown>
    return [
      `Ref ${fmtPrice((inputs.support_reference as number | null | undefined) ?? null)}`,
      `Seuils ${String(thresholds.buy ?? "--")}/${String(thresholds.sell ?? "--")}`,
    ]
  }

  if (method.id === "swing_levels") {
    const supports = Array.isArray(inputs.supports) ? inputs.supports.length : 0
    const resistances = Array.isArray(inputs.resistances) ? inputs.resistances.length : 0
    return [
      `Lookback ${String(inputs.lookback ?? "--")}`,
      `${String(inputs.left_bars ?? "--")}L/${String(inputs.right_bars ?? "--")}R`,
      `${supports}/${resistances} niveaux`,
    ]
  }

  if (method.id === "pivot_points") {
    return [
      `PP ${fmtPrice((inputs.pp as number | null | undefined) ?? null)}`,
      `S1 ${fmtPrice((inputs.s1 as number | null | undefined) ?? null)}`,
      `R1 ${fmtPrice((inputs.r1 as number | null | undefined) ?? null)}`,
    ]
  }

  if (method.id === "quantile_extrema_atr") {
    return [
      `q20 ${fmtPrice((inputs.support_q20 as number | null | undefined) ?? null)}`,
      `q80 ${fmtPrice((inputs.resistance_q80 as number | null | undefined) ?? null)}`,
      `ATR ${fmtPct(((inputs.atr_ratio_20 as number | null | undefined) ?? null) != null ? Number(inputs.atr_ratio_20) * 100 : null)}`,
    ]
  }

  if (method.id === "fibonacci_retracement") {
    return [
      `H ${fmtPrice((inputs.swing_high as number | null | undefined) ?? null)}`,
      `L ${fmtPrice((inputs.swing_low as number | null | undefined) ?? null)}`,
      `Lookback ${String(inputs.lookback ?? "--")}`,
    ]
  }

  return []
}

function MethodRow({ method }: { method: SupportResistanceMethod }) {
  const details = methodDetails(method)

  return (
    <div className="rounded-md border p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold">{method.label}</p>
            <Badge variant="outline" className={`text-[10px] ${statusBadgeClass(method.status)}`}>
              {method.status}
            </Badge>
            {method.selected_for_support && (
              <Badge variant="outline" className="border-blue-300 text-[10px] text-blue-700">
                Support retenu
              </Badge>
            )}
            {method.selected_for_resistance && (
              <Badge variant="outline" className="border-rose-300 text-[10px] text-rose-700">
                Resistance retenue
              </Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground">{method.explanation || "Aucune precision."}</p>
          {details.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {details.map((detail) => (
                <Badge key={`${method.id}-${detail}`} variant="secondary" className="text-[10px] font-normal">
                  {detail}
                </Badge>
              ))}
            </div>
          )}
        </div>

        <div className="grid min-w-[170px] grid-cols-2 gap-2 text-right">
          <div className="rounded bg-muted/30 px-2 py-1.5">
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Support</p>
            <p className="font-mono text-sm font-semibold text-emerald-600">{fmtPrice(method.support)}</p>
          </div>
          <div className="rounded bg-muted/30 px-2 py-1.5">
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Resistance</p>
            <p className="font-mono text-sm font-semibold text-red-600">{fmtPrice(method.resistance)}</p>
          </div>
        </div>
      </div>
    </div>
  )
}

export function SupportResistanceCard({
  data,
  isLoading,
  error,
}: {
  data: SupportResistanceResponse | null | undefined
  isLoading: boolean
  error: unknown
}) {
  if (isLoading && !data) {
    return (
      <Card>
        <CardHeader className="pb-2 pt-3">
          <CardTitle className="text-sm">Support et resistance</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 pt-0">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    )
  }

  if (error) {
    const message = error instanceof Error ? error.message : "Erreur inconnue"
    return (
      <Card className="border-amber-300">
        <CardHeader className="pb-2 pt-3">
          <CardTitle className="text-sm">Support et resistance</CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          <p className="text-xs text-muted-foreground">{message}</p>
        </CardContent>
      </Card>
    )
  }

  if (!data) return null
  const hasOptimal = data.optimal_status === "ready"
  const supportLabel = hasOptimal ? "Support optimal" : "Support preview"
  const resistanceLabel = hasOptimal ? "Resistance optimale" : "Resistance preview"
  const supportValue = hasOptimal ? data.optimal_support : data.preview_support
  const resistanceValue = hasOptimal ? data.optimal_resistance : data.preview_resistance
  const supportSource = hasOptimal ? data.selected_support_method_id : data.preview_support_method_id
  const resistanceSource = hasOptimal ? data.selected_resistance_method_id : data.preview_resistance_method_id

  return (
    <Card>
      <CardHeader className="pb-2 pt-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <CardTitle className="text-sm">Support et resistance</CardTitle>
            <p className="text-xs text-muted-foreground">{data.summary_explanation}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <SignalBadge label={data.trend_label} />
            <Badge variant="outline" className="text-[10px]">
              Tendance {data.trend_score_pct != null ? fmtPct(data.trend_score_pct) : "--"}
            </Badge>
            <Badge variant="outline" className="text-[10px] text-muted-foreground">
              {data.as_of}
            </Badge>
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-3 pt-0">
        <div className="grid gap-2 sm:grid-cols-3">
          <div className="rounded-md border bg-muted/20 p-3">
            <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Cloture</p>
            <p className="font-mono text-base font-semibold">{fmtPrice(data.current_close)}</p>
          </div>
          <div className="rounded-md border bg-emerald-50/60 p-3">
            <p className="text-[10px] uppercase tracking-wide text-emerald-700">{supportLabel}</p>
            <p className="font-mono text-base font-semibold text-emerald-700">{fmtPrice(supportValue)}</p>
            <p className="text-[10px] text-emerald-700/80">{supportSource ?? "--"}</p>
          </div>
          <div className="rounded-md border bg-red-50/60 p-3">
            <p className="text-[10px] uppercase tracking-wide text-red-700">{resistanceLabel}</p>
            <p className="font-mono text-base font-semibold text-red-700">{fmtPrice(resistanceValue)}</p>
            <p className="text-[10px] text-red-700/80">{resistanceSource ?? "--"}</p>
          </div>
        </div>

        <div className="space-y-2">
          {data.methods.map((method) => (
            <MethodRow key={method.id} method={method} />
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
