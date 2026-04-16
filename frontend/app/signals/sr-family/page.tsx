"use client"

import { Suspense, useMemo } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { ArrowLeft } from "lucide-react"
import { useSupportResistanceVariants } from "@/hooks/use-api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { formatNumber } from "@/lib/format"
import type { SupportResistanceMethod } from "@/lib/api"

function fmtPrice(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "--"
  return formatNumber(value, 2)
}

function statusBadge(status: string): string {
  if (status === "selected") return "border-emerald-300 text-emerald-700 bg-emerald-50"
  if (status === "percentile_cutoff") return "border-amber-300 text-amber-700 bg-amber-50"
  if (status === "available") return "border-emerald-300 text-emerald-700 bg-emerald-50"
  if (status === "ignored") return "border-amber-300 text-amber-700 bg-amber-50"
  return "border-slate-300 text-slate-600 bg-slate-50"
}

function fmtPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "--"
  return `${(value * 100).toFixed(1)}%`
}

function SupportResistanceFamilyContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const symbol = (searchParams.get("symbol") ?? "").trim().toUpperCase()
  const horizon = (searchParams.get("horizon") ?? "medium").trim().toLowerCase()
  const cooldownBars = Number(searchParams.get("cooldown") ?? 0)
  const costBps = 33

  const variants = useSupportResistanceVariants(symbol || null, horizon || null, costBps, cooldownBars, Boolean(symbol))
  const sortedAll = useMemo(
    () =>
      [...(variants.data?.all_variants ?? [])].sort(
        (a, b) => b.reliability_score - a.reliability_score || a.variant_id.localeCompare(b.variant_id),
      ),
    [variants.data?.all_variants],
  )

  if (!symbol) {
    return <div className="p-6 text-center text-sm text-muted-foreground">Parametre &quot;symbol&quot; manquant dans l&apos;URL.</div>
  }

  if (variants.isLoading && !variants.data) {
    return (
      <div className="mx-auto max-w-6xl space-y-4 p-6">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-52 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    )
  }

  if (variants.error || !variants.data) {
    return (
      <div className="mx-auto max-w-5xl p-6">
        <Card className="border-destructive/50">
          <CardContent className="py-8 text-center">
            <p className="text-sm font-medium text-destructive">Erreur lors du chargement de la famille SR</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {variants.error instanceof Error ? variants.error.message : "Erreur inconnue"}
            </p>
          </CardContent>
        </Card>
      </div>
    )
  }

  const data = variants.data
  const bestVariant = sortedAll.find((variant) => variant.variant_id === data.best_variant_id) ?? sortedAll[0] ?? null

  return (
    <div className="mx-auto max-w-6xl space-y-5 p-6">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => router.back()} className="gap-1">
          <ArrowLeft className="h-3.5 w-3.5" />
          Retour
        </Button>
        <div>
          <h1 className="text-base font-bold">Support et resistance</h1>
          <p className="text-xs text-muted-foreground">
            {symbol} - {horizon} - {data.as_of}
          </p>
        </div>
      </div>

      <Card>
        <CardContent className="space-y-3 p-4">
          <p className="text-xs text-muted-foreground">{data.score_explanation}</p>
          <div className="grid gap-2 sm:grid-cols-4">
            <LevelBadge label="Cloture" value={data.current_close} />
            <LevelBadge label="Support optimal" value={data.final_support} tone="support" />
            <LevelBadge label="Resistance optimale" value={data.final_resistance} tone="resistance" />
            <div className="rounded-md border bg-muted/20 p-3">
              <p className="text-[10px] uppercase tracking-wide text-muted-foreground">Meilleur couple</p>
              <p className="break-all font-mono text-xs font-semibold">{data.best_variant_id ?? "--"}</p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2 text-[11px]">
            <Badge variant="outline">Apercu S {fmtPrice(data.preview_support)}</Badge>
            <Badge variant="outline">Apercu R {fmtPrice(data.preview_resistance)}</Badge>
            <Badge variant="outline">{data.optimal_status}</Badge>
            {bestVariant && (
              <Badge variant="outline">Objectif SR {fmtPct(bestVariant.sr_objective_score ?? bestVariant.reliability_score)}</Badge>
            )}
          </div>
        </CardContent>
      </Card>

      <section className="space-y-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold">Methodes</h2>
          <Badge variant="outline" className="text-[10px]">
            {data.methods.length}
          </Badge>
        </div>
        <div className="grid gap-3 lg:grid-cols-2">
          {data.methods.map((method) => (
            <MethodCard
              key={method.id}
              method={method}
              onOpen={() =>
                router.push(
                  `/signals/sr-method/${encodeURIComponent(method.id)}?symbol=${encodeURIComponent(symbol)}&horizon=${encodeURIComponent(horizon)}&cooldown=${cooldownBars}`,
                )
              }
            />
          ))}
        </div>
      </section>

      <Card>
        <CardHeader className="px-4 pb-2 pt-3">
          <CardTitle className="text-xs font-semibold">Couples S/R testes ({sortedAll.length})</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b bg-secondary/30 text-muted-foreground">
                  <th className="px-3 py-2 text-left font-medium">Variante</th>
                  <th className="px-3 py-2 text-right font-medium">Support</th>
                  <th className="px-3 py-2 text-right font-medium">Resistance</th>
                  <th className="px-3 py-2 text-right font-medium">PnL 100k</th>
                  <th className="px-3 py-2 text-right font-medium">Drawdown</th>
                  <th className="px-3 py-2 text-right font-medium">Regularite</th>
                  <th className="px-3 py-2 text-right font-medium">Objectif SR</th>
                </tr>
              </thead>
              <tbody>
                {sortedAll.map((variant, index) => (
                  <tr
                    key={variant.variant_id}
                    className={`cursor-pointer border-b border-border/50 hover:bg-secondary/20 ${
                      variant.variant_id === data.best_variant_id ? "bg-emerald-50/40" : ""
                    }`}
                    onClick={() =>
                      router.push(
                        `/signals/sr-variant/${encodeURIComponent(variant.variant_id)}?symbol=${encodeURIComponent(symbol)}&horizon=${encodeURIComponent(horizon)}&cooldown=${cooldownBars}`,
                      )
                    }
                  >
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium">#{index + 1}</span>
                        {variant.variant_id === data.best_variant_id && (
                          <Badge variant="outline" className="border-emerald-300 text-[10px] text-emerald-700">
                            Meilleur couple
                          </Badge>
                        )}
                      </div>
                      <div className="font-medium">{variant.description}</div>
                      <div className="font-mono text-[10px] text-muted-foreground">{variant.variant_id}</div>
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-emerald-700">
                      {fmtPrice(variant.support_level)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono text-red-700">
                      {fmtPrice(variant.resistance_level)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono">{formatNumber(variant.total_pnl, 0)}</td>
                    <td className="px-3 py-2 text-right font-mono">{fmtPct(variant.mean_max_drawdown)}</td>
                    <td className="px-3 py-2 text-right font-mono">{fmtPct(variant.fraction_positive_windows)}</td>
                    <td className="px-3 py-2 text-right font-mono">
                      {fmtPct(variant.sr_objective_score ?? variant.reliability_score)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

export default function SupportResistanceFamilyPage() {
  return (
    <Suspense>
      <SupportResistanceFamilyContent />
    </Suspense>
  )
}

function LevelBadge({
  label,
  value,
  tone,
}: {
  label: string
  value: number | null | undefined
  tone?: "support" | "resistance"
}) {
  const cls =
    tone === "support"
      ? "bg-emerald-50/60 text-emerald-700"
      : tone === "resistance"
        ? "bg-red-50/60 text-red-700"
        : "bg-muted/20"
  return (
    <div className={`rounded-md border p-3 ${cls}`}>
      <p className="text-[10px] uppercase tracking-wide opacity-80">{label}</p>
      <p className="font-mono text-base font-semibold">{fmtPrice(value)}</p>
    </div>
  )
}

function MethodCard({ method, onOpen }: { method: SupportResistanceMethod; onOpen: () => void }) {
  return (
    <Card className="cursor-pointer transition-colors hover:border-primary/50" onClick={onOpen}>
      <CardContent className="space-y-3 p-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-sm font-semibold">{method.label}</p>
              <Badge variant="outline" className={`text-[10px] ${statusBadge(method.status)}`}>
                {method.status}
              </Badge>
              {method.selected_for_support && (
                <Badge variant="outline" className="border-emerald-300 text-[10px] text-emerald-700">
                  Support optimal
                </Badge>
              )}
              {method.selected_for_resistance && (
                <Badge variant="outline" className="border-red-300 text-[10px] text-red-700">
                  Resistance optimale
                </Badge>
              )}
            </div>
            <p className="text-xs text-muted-foreground">{method.explanation || "Aucun detail disponible."}</p>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2 text-[11px]">
          <div className="rounded border bg-emerald-50/40 p-2">
            <p className="text-emerald-700/80">Support</p>
            <p className="font-mono font-semibold text-emerald-700">{fmtPrice(method.support)}</p>
          </div>
          <div className="rounded border bg-red-50/40 p-2">
            <p className="text-red-700/80">Resistance</p>
            <p className="font-mono font-semibold text-red-700">{fmtPrice(method.resistance)}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
