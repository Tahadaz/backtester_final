"use client"

import Link from "next/link"
import { useState } from "react"
import { AlertCircle } from "lucide-react"
import { useDashboardData } from "@/hooks/use-dashboard"
import { useDashboardIndices } from "@/hooks/use-dashboard-indices"
import type { DashboardView, DashboardSector, DashboardStock, FamilyScore, Horizon } from "@/lib/dashboard-types"
import { createDashboardIndex, deleteDashboardIndex, updateDashboardIndex } from "@/lib/api"
import { HORIZONS, VIEWS } from "@/lib/dashboard-constants"
import { StockTable } from "@/components/dashboard-v1/stock-table"
import { SectorTable } from "@/components/dashboard-v1/sector-table"
import { IndexTab } from "@/components/dashboard-v1/index-tab"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"

const isPublicDashboardOnly = process.env.NEXT_PUBLIC_DASHBOARD_PUBLIC_ONLY === "true"

const ADV_THRESHOLD = 1000

function scoreToLabel(score: number | null): string {
  if (score == null) return "Neutre"
  if (score >= 60) return "Achat"
  if (score <= 40) return "Vente"
  return "Neutre"
}

function recomputeSectors(stocks: DashboardStock[]): DashboardSector[] {
  const groups = new Map<string, DashboardStock[]>()
  for (const stock of stocks) {
    const sector = stock.sector ?? "Autre"
    if (!groups.has(sector)) groups.set(sector, [])
    groups.get(sector)!.push(stock)
  }
  return Array.from(groups.entries()).map(([sector, members]) => {
    const aggScores = members
      .map((s) => s.aggregate_score_pct)
      .filter((v): v is number => v != null)
    const expandedAggScores = members
      .map((s) => s.expanded_aggregate_score_pct)
      .filter((v): v is number => v != null)
    const aggregate_score_pct = aggScores.length
      ? aggScores.reduce((a, b) => a + b, 0) / aggScores.length
      : null
    const expanded_aggregate_score_pct = expandedAggScores.length
      ? expandedAggScores.reduce((a, b) => a + b, 0) / expandedAggScores.length
      : null
    const families = [...new Set(members.flatMap((s) => Object.keys(s.per_family)))]
    const per_family: Record<string, FamilyScore> = {}
    for (const f of families) {
      const scores = members
        .map((s) => s.per_family[f]?.score_pct)
        .filter((v): v is number => v != null)
      if (scores.length) {
        const avg = scores.reduce((a, b) => a + b, 0) / scores.length
        per_family[f] = { score_pct: avg, label: scoreToLabel(avg) }
      }
    }
    const expandedFamilies = [...new Set(members.flatMap((s) => Object.keys(s.expanded_per_family ?? {})))]
    const expanded_per_family: Record<string, FamilyScore> = {}
    for (const f of expandedFamilies) {
      const scores = members
        .map((s) => s.expanded_per_family?.[f]?.score_pct)
        .filter((v): v is number => v != null)
      if (scores.length) {
        const avg = scores.reduce((a, b) => a + b, 0) / scores.length
        expanded_per_family[f] = { score_pct: avg, label: scoreToLabel(avg) }
      }
    }
    return {
      sector,
      stock_count: members.length,
      aggregate_score_pct,
      aggregate_signal_label: scoreToLabel(aggregate_score_pct),
      expanded_aggregate_score_pct,
      expanded_aggregate_signal_label: scoreToLabel(expanded_aggregate_score_pct),
      per_family,
      expanded_per_family,
    }
  })
}

export default function DashboardV1Page() {
  const [horizon, setHorizon] = useState<Horizon>("short")
  const [view, setView] = useState<DashboardView>("stocks")
  const [indexActionError, setIndexActionError] = useState<string | null>(null)
  const [liquidityFilter, setLiquidityFilter] = useState(true)
  const [signalView, setSignalView] = useState<"legacy" | "expanded">("legacy")

  const { data, error, isLoading } = useDashboardData(horizon)
  const { data: persistedIndices, error: indicesError, mutate: mutateIndices } = useDashboardIndices(!isPublicDashboardOnly)

  const allStocks = data?.stocks ?? []
  const filteredStocks = liquidityFilter
    ? allStocks.filter((s) => (s.adv ?? 0) >= ADV_THRESHOLD)
    : allStocks
  const filteredSectors = liquidityFilter
    ? recomputeSectors(filteredStocks)
    : (data?.sectors ?? [])

  const staticDefinitions = data?.custom_index_definitions ?? []
  const customDefinitions = isPublicDashboardOnly
    ? staticDefinitions
    : (persistedIndices ?? staticDefinitions)

  async function refreshIndices() {
    await mutateIndices()
  }

  async function handleCreateIndex(payload: { name: string; symbols: string[] }) {
    setIndexActionError(null)
    try {
      await createDashboardIndex(payload)
      await refreshIndices()
    } catch (createError) {
      setIndexActionError(createError instanceof Error ? createError.message : "Erreur lors de la creation de l'indice.")
      throw createError
    }
  }

  async function handleUpdateIndex(indexId: string, payload: { name: string; symbols: string[] }) {
    setIndexActionError(null)
    try {
      await updateDashboardIndex(indexId, payload)
      await refreshIndices()
    } catch (updateError) {
      setIndexActionError(updateError instanceof Error ? updateError.message : "Erreur lors de la mise a jour de l'indice.")
      throw updateError
    }
  }

  async function handleDeleteIndex(indexId: string) {
    setIndexActionError(null)
    try {
      await deleteDashboardIndex(indexId)
      await refreshIndices()
    } catch (deleteError) {
      setIndexActionError(deleteError instanceof Error ? deleteError.message : "Erreur lors de la suppression de l'indice.")
      throw deleteError
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Tableau de Bord V1</h1>
          <p className="text-sm text-muted-foreground">
            Signaux techniques - Marche MASI
            {data && (
              <span className="ml-2">
                - Mis a jour le {new Date(data.generated_at).toLocaleDateString("fr-FR")}
              </span>
            )}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 self-start">
          <button
            onClick={() => setLiquidityFilter((v) => !v)}
            className={`inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm font-medium transition-colors ${
              liquidityFilter
                ? "border-amber-300 bg-amber-50 text-amber-800"
                : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50"
            }`}
          >
            <span
              className={`h-2 w-2 rounded-full ${liquidityFilter ? "bg-amber-500" : "bg-slate-300"}`}
            />
            {liquidityFilter ? `Liquidite >= ${ADV_THRESHOLD.toLocaleString('fr-FR')} (actif)` : "Filtre liquidite"}
          </button>
          <button
            onClick={() => setSignalView((v) => (v === "legacy" ? "expanded" : "legacy"))}
            className={`inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm font-medium transition-colors ${
              signalView === "expanded"
                ? "border-blue-300 bg-blue-50 text-blue-800"
                : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50"
            }`}
          >
            <span className={`h-2 w-2 rounded-full ${signalView === "expanded" ? "bg-blue-500" : "bg-slate-300"}`} />
            {signalView === "expanded" ? "Vue Expanded (actif)" : "Vue Legacy"}
          </button>
        </div>
      </div>

      <Card className="border-slate-200 bg-white">
        <CardContent className="p-4 sm:p-5">
          <div className="flex flex-col gap-4">
            <div className="border-b border-slate-200 pb-3">
              <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">Parametres d'affichage</p>
              <p className="mt-1 text-sm text-slate-600">Choisissez l'horizon puis la vue a afficher.</p>
            </div>

            <div className="grid gap-4 xl:grid-cols-2">
              <div className="space-y-2">
                <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">1. Horizon de temps</p>
                <Tabs value={horizon} onValueChange={(value) => setHorizon(value as Horizon)}>
                  <TabsList className="grid h-auto w-full grid-cols-3 rounded-md border border-slate-300 bg-white p-1">
                    {HORIZONS.map((item) => (
                      <TabsTrigger
                        key={item.value}
                        value={item.value}
                        className="rounded-sm py-2 text-sm font-semibold text-slate-600 transition data-[state=active]:bg-slate-900 data-[state=active]:text-white"
                      >
                        {item.label}
                      </TabsTrigger>
                    ))}
                  </TabsList>
                </Tabs>
              </div>

              <div className="space-y-2">
                <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">2. Univers d'analyse</p>
                <div className="grid w-full grid-cols-3 gap-1 rounded-md border border-slate-300 bg-white p-1">
                  {VIEWS.map((item) => (
                    <button
                      key={item.value}
                      onClick={() => setView(item.value)}
                      className={`rounded-sm px-3 py-2 text-sm font-semibold transition-colors ${
                        view === item.value
                          ? "bg-slate-900 text-white"
                          : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
                      }`}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {isLoading && <LoadingSkeleton />}
      {error && <ErrorCard message={error.message} />}

      {data && (
        <>
          {view === "stocks" && <StockTable stocks={filteredStocks} horizon={horizon} signalView={signalView} />}
          {view === "sectors" && <SectorTable sectors={filteredSectors} stocks={filteredStocks} horizon={horizon} signalView={signalView} />}
          {view === "index" && (
            <IndexTab
              baseIndex={data.index}
              stocks={filteredStocks}
              customDefinitions={customDefinitions}
              readOnly={isPublicDashboardOnly}
              actionError={indexActionError ?? (indicesError ? indicesError.message : null)}
              onCreate={isPublicDashboardOnly ? undefined : handleCreateIndex}
              onUpdate={isPublicDashboardOnly ? undefined : handleUpdateIndex}
              onDelete={isPublicDashboardOnly ? undefined : handleDeleteIndex}
            />
          )}
        </>
      )}

      {data && data.stocks.length === 0 && (
        <Card>
          <CardContent className="py-12 text-center">
            {isPublicDashboardOnly ? (
              <p className="text-muted-foreground">
                Aucune donnee disponible. La prochaine publication mettra a jour les donnees du tableau de bord.
              </p>
            ) : (
              <p className="text-muted-foreground">
                Aucune donnee disponible. Chargez des donnees de marche depuis la page{" "}
                <Link href="/data" className="underline">
                  Data
                </Link>
                .
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-4 gap-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-20 rounded-lg" />
        ))}
      </div>
      <Skeleton className="h-96 rounded-lg" />
    </div>
  )
}

function ErrorCard({ message }: { message: string }) {
  return (
    <Card className="border-destructive">
      <CardContent className="flex items-center gap-3 py-6">
        <AlertCircle className="h-5 w-5 text-destructive" />
        <div>
          <p className="font-medium text-destructive">Erreur de chargement</p>
          <p className="text-sm text-muted-foreground">{message}</p>
        </div>
      </CardContent>
    </Card>
  )
}
