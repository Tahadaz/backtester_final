"use client"

import { useState, useMemo } from "react"
import { useMarketCatalog, usePersistedSignalEngineSummaries } from "@/hooks/use-api"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { Eye, EyeOff, Search } from "lucide-react"
import type { PersistedSignalEngineSummary } from "@/lib/api"

function signalLabel(score: number): { label: string; cls: string } {
  if (score > 50) return { label: "ACHAT FORT", cls: "bg-emerald-100 text-emerald-700" }
  if (score > 15) return { label: "ACHAT", cls: "bg-green-100 text-green-700" }
  if (score >= -15) return { label: "NEUTRE", cls: "bg-gray-100 text-gray-600" }
  if (score >= -50) return { label: "VENTE", cls: "bg-orange-100 text-orange-700" }
  return { label: "VENTE FORTE", cls: "bg-red-100 text-red-700" }
}

const CATEGORY_FILTERS = [
  { value: "all", label: "Tous" },
  { value: "equity", label: "Actions" },
  { value: "commodity", label: "MP" },
  { value: "forex", label: "FX" },
  { value: "bond", label: "Oblig." },
] as const

const SUBCATEGORY_FILTERS = [
  { value: "all", label: "Tous" },
  { value: "masi", label: "MASI" },
  { value: "us", label: "US" },
  { value: "european", label: "EU" },
  { value: "asian", label: "Asie" },
] as const

export function StockSidebar({
  selectedSymbol,
  onSelect,
  horizon,
  variant,
  cooldownBars,
  className,
}: {
  selectedSymbol: string | null
  onSelect: (symbol: string) => void
  horizon: string
  variant: string
  cooldownBars?: number
  className?: string
}) {
  const { data: catalog, isLoading } = useMarketCatalog()
  const [search, setSearch] = useState("")
  const [hideUnavailable, setHideUnavailable] = useState(false)
  const [categoryFilter, setCategoryFilter] = useState<string>("all")
  const [subcategoryFilter, setSubcategoryFilter] = useState<string>("all")

  const canonicalStocks = useMemo(
    () => (catalog ?? []).filter((r) => r.has_canonical_data),
    [catalog],
  )

  const symbolList = useMemo(
    () => canonicalStocks.map((r) => r.symbol),
    [canonicalStocks],
  )

  const { data: batchScores, isLoading: scoresLoading } = usePersistedSignalEngineSummaries(
    symbolList,
    horizon,
    variant,
  )

  const scoreMap = useMemo(() => {
    const map: Record<string, PersistedSignalEngineSummary> = {}
    if (batchScores) {
      for (const s of batchScores) map[s.symbol] = s
    }
    return map
  }, [batchScores])

  const filtered = useMemo(() => {
    return canonicalStocks.filter((r) => {
      // Category filter
      if (categoryFilter !== "all" && (r.asset_type ?? "equity") !== categoryFilter) return false
      // Subcategory filter (equity only)
      if (categoryFilter === "equity" && subcategoryFilter !== "all" && r.market_region !== subcategoryFilter) return false
      // Availability filter
      if (hideUnavailable && !scoresLoading) {
        const score = scoreMap[r.symbol]
        if (!score || score.aggregate_score_pct == null) return false
      }
      // Text search
      if (search) {
        const q = search.toLowerCase()
        if (
          !r.symbol.toLowerCase().includes(q) &&
          !(r.display_name?.toLowerCase().includes(q) ?? false)
        ) return false
      }
      return true
    })
  }, [canonicalStocks, categoryFilter, subcategoryFilter, hideUnavailable, scoresLoading, scoreMap, search])

  return (
    <div className={cn("flex flex-col border-r bg-card", className)}>
      {/* Category filter chips */}
      <div className="px-2 pt-2 pb-1 border-b">
        <div className="flex flex-wrap gap-0.5">
          {CATEGORY_FILTERS.map((f) => (
            <button
              key={f.value}
              onClick={() => {
                setCategoryFilter(f.value)
                setSubcategoryFilter("all")
              }}
              className={cn(
                "rounded px-2 py-0.5 text-[10px] font-semibold transition-colors border",
                categoryFilter === f.value
                  ? "bg-slate-900 text-white border-slate-900"
                  : "text-muted-foreground bg-background border-border hover:bg-accent",
              )}
            >
              {f.label}
            </button>
          ))}
        </div>

        {/* Subcategory chips — equity only */}
        {categoryFilter === "equity" && (
          <div className="flex flex-wrap gap-0.5 mt-1">
            {SUBCATEGORY_FILTERS.map((f) => (
              <button
                key={f.value}
                onClick={() => setSubcategoryFilter(f.value)}
                className={cn(
                  "rounded px-2 py-0.5 text-[10px] font-semibold transition-colors border",
                  subcategoryFilter === f.value
                    ? "bg-blue-700 text-white border-blue-700"
                    : "text-muted-foreground bg-background border-border hover:bg-accent",
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Search + hide toggle */}
      <div className="p-3 border-b">
        <div className="flex items-center gap-1.5">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              placeholder="Rechercher un titre…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="h-8 pl-8 text-xs"
            />
          </div>
          <button
            onClick={() => setHideUnavailable((v) => !v)}
            title={hideUnavailable ? "Afficher tous" : "Masquer non disponibles"}
            className={cn(
              "flex-shrink-0 p-1.5 rounded transition-colors",
              hideUnavailable
                ? "text-primary bg-primary/10"
                : "text-muted-foreground hover:text-foreground hover:bg-accent",
            )}
          >
            {hideUnavailable ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>

      <ScrollArea className="flex-1 min-h-0">
        {isLoading ? (
          <div className="p-3 space-y-2">
            {[...Array(12)].map((_, i) => (
              <Skeleton key={i} className="h-9 w-full" />
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <div className="p-4 text-center text-xs text-muted-foreground">
            Aucun titre trouvé
          </div>
        ) : (
          <div className="p-1">
            {filtered.map((row) => (
              <button
                key={row.symbol}
                onClick={() => onSelect(row.symbol)}
                className={cn(
                  "w-full flex flex-col gap-0.5 rounded-md px-3 py-2 text-left transition-colors",
                  "hover:bg-accent hover:text-accent-foreground",
                  selectedSymbol === row.symbol &&
                    "bg-accent text-accent-foreground"
                )}
              >
                {/* Line 1: symbol + signal badge */}
                <div className="flex items-center justify-between w-full">
                  <span className={cn(
                    "font-mono text-xs font-bold",
                    selectedSymbol === row.symbol && "text-foreground"
                  )}>
                    {row.symbol}
                  </span>
                  {scoreMap[row.symbol]?.aggregate_score_pct != null ? (() => {
                    const info = signalLabel(scoreMap[row.symbol].aggregate_score_pct!)
                    return (
                      <div className="flex items-center gap-1">
                        <span className={cn(
                          "text-[9px] font-semibold px-1.5 py-0.5 rounded whitespace-nowrap",
                          info.cls,
                        )}>
                          {info.label}
                        </span>
                        {scoreMap[row.symbol]?.is_stale ? (
                          <span className="text-[9px] text-amber-700">stale</span>
                        ) : null}
                      </div>
                    )
                  })() : scoresLoading ? (
                    <span className="text-[9px] text-muted-foreground animate-pulse">{"•••"}</span>
                  ) : null}
                </div>
                {/* Line 2: display name */}
                {row.display_name && (
                  <span className="text-[10px] text-muted-foreground truncate w-full">
                    {row.display_name}
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
      </ScrollArea>

      {!isLoading && (
        <div className="p-2 border-t text-[10px] text-muted-foreground text-center">
          {filtered.length} titre{filtered.length !== 1 ? "s" : ""}
        </div>
      )}
    </div>
  )
}
