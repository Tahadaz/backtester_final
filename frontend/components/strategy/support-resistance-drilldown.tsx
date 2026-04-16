"use client"

import { useRouter } from "next/navigation"
import { useSupportResistance } from "@/hooks/use-api"
import { formatNumber } from "@/lib/format"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"

function fmtPrice(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "--"
  return formatNumber(value, 2)
}

function fmtPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "--"
  return `${formatNumber(value, 2)}%`
}

export function SupportResistanceDrilldown({
  symbol,
  horizon,
  cooldownBars,
  costBps,
}: {
  symbol: string
  horizon: string
  cooldownBars?: number
  costBps?: number
}) {
  const router = useRouter()
  const summary = useSupportResistance(symbol, horizon, costBps, cooldownBars)

  if (summary.isLoading && !summary.data) {
    return (
      <Card>
        <CardHeader className="pb-2 pt-3">
          <CardTitle className="text-sm">Support et resistance</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 pt-0">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-16 w-full" />
        </CardContent>
      </Card>
    )
  }

  if (summary.error) {
    const message = summary.error instanceof Error ? summary.error.message : "Erreur inconnue"
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

  if (!summary.data) return null

  const data = summary.data
  const hasOptimal = data.optimal_status === "ready"
  const supportLabel = hasOptimal ? "Support optimal" : "Support preview"
  const resistanceLabel = hasOptimal ? "Resistance optimale" : "Resistance preview"
  const supportValue = hasOptimal ? data.optimal_support : (data.preview_support ?? data.final_support)
  const resistanceValue = hasOptimal ? data.optimal_resistance : (data.preview_resistance ?? data.final_resistance)
  const supportSource = hasOptimal ? data.selected_support_method_id : (data.preview_support_method_id ?? data.selected_support_method_id)
  const resistanceSource = hasOptimal ? data.selected_resistance_method_id : (data.preview_resistance_method_id ?? data.selected_resistance_method_id)

  return (
    <Card
      className="cursor-pointer transition-colors hover:border-primary/50"
      onClick={() =>
        router.push(
          `/signals/sr-family?symbol=${encodeURIComponent(symbol)}&horizon=${encodeURIComponent(horizon)}&cooldown=${cooldownBars ?? 0}`,
        )
      }
    >
      <CardHeader className="pb-2 pt-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <CardTitle className="text-sm">Support et resistance</CardTitle>
            <p className="text-xs text-muted-foreground">{data.summary_explanation}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="text-[10px]">
              Tendance {data.trend_score_pct != null ? fmtPct(data.trend_score_pct) : "--"}
            </Badge>
            <Badge variant="outline" className="text-[10px] text-muted-foreground">
              {data.as_of}
            </Badge>
            <Badge
              variant="outline"
              className={`text-[10px] ${
                hasOptimal ? "border-emerald-300 text-emerald-700" : "border-amber-300 text-amber-700"
              }`}
            >
              {hasOptimal ? "Optimal pret" : "Optimal a calculer"}
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
        <p className="text-[10px] text-muted-foreground">
          Cliquez pour tester les combinaisons support x resistance
        </p>
      </CardContent>
    </Card>
  )
}
