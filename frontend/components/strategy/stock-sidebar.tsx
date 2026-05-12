"use client"

import { useMemo, useState } from "react"
import { useMarketCatalog, usePersistedSignalEngineSummaries } from "@/hooks/use-api"
import { HorizonSelector } from "@/components/strategy/horizon-selector"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { Eye, EyeOff, Search } from "lucide-react"
import type { PersistedSignalEngineSummary } from "@/lib/api"

function scoreText(score: number | null | undefined): string {
  if (score == null || !Number.isFinite(score)) return "--"
  return `${score >= 0 ? "+" : ""}${score.toFixed(0)}`
}

function signalPillText(score: number | null | undefined, loading: boolean): string {
  if (loading && score == null) return "..."
  if (score == null) return "No run"
  return signalLabel(score)
}

function signalLabel(score: number): string {
  if (score > 50) return "Achat fort"
  if (score > 15) return "Achat"
  if (score >= -15) return "Neutre"
  if (score >= -50) return "Vente"
  return "Vente forte"
}

function signalToneClasses(score: number | null | undefined): string {
  if (score == null) return "border-border bg-muted/20 text-muted-foreground"
  if (score > 15) return "border-emerald-200 bg-emerald-50 text-emerald-700"
  if (score < -15) return "border-red-200 bg-red-50 text-red-700"
  return "border-border bg-muted/30 text-muted-foreground"
}

export function StockSidebar({
  selectedSymbol,
  onSelect,
  horizon,
  onHorizonChange,
  variant,
  className,
}: {
  selectedSymbol: string | null
  onSelect: (symbol: string) => void
  horizon: string
  onHorizonChange: (value: string) => void
  variant: string
  cooldownBars?: number
  className?: string
}) {
  const { data: catalog, isLoading } = useMarketCatalog()
  const [search, setSearch] = useState("")
  const [hideUnavailable, setHideUnavailable] = useState(false)

  const canonicalStocks = useMemo(
    () => (catalog ?? []).filter((row) => row.has_canonical_data),
    [catalog],
  )

  const symbolList = useMemo(
    () => canonicalStocks.map((row) => row.symbol),
    [canonicalStocks],
  )

  const { data: batchScores, isLoading: scoresLoading } = usePersistedSignalEngineSummaries(
    symbolList,
    horizon,
    variant,
  )

  const scoreMap = useMemo(() => {
    const map: Record<string, PersistedSignalEngineSummary> = {}
    for (const row of batchScores ?? []) map[row.symbol] = row
    return map
  }, [batchScores])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return canonicalStocks.filter((row) => {
      const score = scoreMap[row.symbol]
      if (hideUnavailable && !scoresLoading && score?.aggregate_score_pct == null) return false
      if (!q) return true
      return (
        row.symbol.toLowerCase().includes(q) ||
        (row.display_name?.toLowerCase().includes(q) ?? false)
      )
    })
  }, [canonicalStocks, hideUnavailable, scoresLoading, scoreMap, search])

  return (
    <aside className={cn("flex min-h-0 flex-col overflow-hidden border-r border-line bg-card", className)}>
      <div className="border-b border-line px-2.5 py-2">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
            Titres
          </span>
          <span className="font-mono text-[10px] text-muted-foreground">
            {filtered.length} / {canonicalStocks.length}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="relative min-w-0 flex-1">
            <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Rechercher un titre..."
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              className="h-7 rounded-md border-line bg-bg2 pl-7 text-xs shadow-none"
            />
          </div>
          <button
            type="button"
            onClick={() => setHideUnavailable((value) => !value)}
            title={hideUnavailable ? "Afficher tous" : "Masquer non disponibles"}
            className={cn(
              "grid h-7 w-7 shrink-0 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-bg3 hover:text-foreground",
              hideUnavailable && "bg-accent text-accent-foreground",
            )}
          >
            {hideUnavailable ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>

      <ScrollArea className="min-h-0 flex-1 signals-scrollbar">
        {isLoading ? (
          <div className="space-y-1 p-1">
            {[...Array(12)].map((_, index) => (
              <Skeleton key={index} className="h-[45px] w-full rounded-md" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="p-4 text-center text-xs text-muted-foreground">
            Aucun titre trouve
          </div>
        ) : (
          <div className="space-y-1 p-1.5">
            {filtered.map((row) => {
              const score = scoreMap[row.symbol]
              const value = score?.aggregate_score_pct ?? null
              return (
                <button
                  key={row.symbol}
                  type="button"
                  onClick={() => onSelect(row.symbol)}
                  className={cn(
                    "grid w-full grid-cols-[minmax(0,1fr)_76px] items-center gap-2 rounded-md border border-transparent px-2.5 py-2 text-left transition-colors hover:border-line hover:bg-bg3",
                    selectedSymbol === row.symbol && "border-primary/30 bg-primary/10 text-foreground",
                  )}
                >
                  <span className="min-w-0">
                    <span className="flex min-w-0 items-center gap-1.5">
                      <span className="font-mono text-xs font-bold">{row.symbol}</span>
                      <span className="truncate rounded border border-line bg-bg2 px-1 text-[9px] text-muted-foreground">
                        {row.market_region ?? row.market ?? row.asset_type}
                      </span>
                    </span>
                    <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">
                      {row.display_name ?? row.sector ?? row.asset_type}
                    </span>
                  </span>
                  <span className="flex min-w-0 flex-col items-end gap-0.5">
                    <span
                      title={value != null ? signalLabel(value) : undefined}
                      className={cn(
                        "inline-flex max-w-full justify-center rounded border px-1.5 py-0.5 text-[10px] font-bold leading-4",
                        signalToneClasses(value),
                      )}
                    >
                      <span className="truncate">{signalPillText(value, scoresLoading)}</span>
                    </span>
                    <span className="font-mono text-[10px] text-muted-foreground">
                      {scoreText(value)}
                    </span>
                  </span>
                </button>
              )
            })}
          </div>
        )}
      </ScrollArea>

      <div className="border-t border-line p-2">
        <div className="mb-1.5 text-[10px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
          Horizon
        </div>
        <HorizonSelector value={horizon} onChange={onHorizonChange} compact />
      </div>
    </aside>
  )
}
