"use client"

import { useState, useMemo } from "react"
import { useMarketCatalog, useBatchScores } from "@/hooks/use-api"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { Search } from "lucide-react"
import type { BatchScore } from "@/lib/api"

function signalLabel(score: number): { label: string; cls: string } {
  if (score > 50) return { label: "ACHAT FORT", cls: "bg-emerald-100 text-emerald-700" }
  if (score > 15) return { label: "ACHAT", cls: "bg-green-100 text-green-700" }
  if (score >= -15) return { label: "NEUTRE", cls: "bg-gray-100 text-gray-600" }
  if (score >= -50) return { label: "VENTE", cls: "bg-orange-100 text-orange-700" }
  return { label: "VENTE FORTE", cls: "bg-red-100 text-red-700" }
}

export function StockSidebar({
  selectedSymbol,
  onSelect,
  horizon,
  cooldownBars,
  className,
}: {
  selectedSymbol: string | null
  onSelect: (symbol: string) => void
  horizon: string
  cooldownBars?: number
  className?: string
}) {
  const { data: catalog, isLoading } = useMarketCatalog()
  const [search, setSearch] = useState("")

  const canonicalStocks = useMemo(
    () => (catalog ?? []).filter((r) => r.has_canonical_data),
    [catalog],
  )

  const symbolList = useMemo(
    () => canonicalStocks.map((r) => r.symbol),
    [canonicalStocks],
  )

  const { data: batchScores, isLoading: scoresLoading } = useBatchScores(symbolList, horizon, cooldownBars)

  const scoreMap = useMemo(() => {
    const map: Record<string, BatchScore> = {}
    if (batchScores) {
      for (const s of batchScores) map[s.symbol] = s
    }
    return map
  }, [batchScores])

  const filtered = canonicalStocks.filter((r) => {
    if (!search) return true
    const q = search.toLowerCase()
    return (
      r.symbol.toLowerCase().includes(q) ||
      (r.display_name?.toLowerCase().includes(q) ?? false)
    )
  })

  return (
    <div className={cn("flex flex-col border-r bg-card", className)}>
      <div className="p-3 border-b">
        <div className="relative">
          <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            placeholder="Rechercher un titre…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-8 pl-8 text-xs"
          />
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
                      <span className={cn(
                        "text-[9px] font-semibold px-1.5 py-0.5 rounded whitespace-nowrap",
                        info.cls,
                      )}>
                        {info.label}
                      </span>
                    )
                  })() : scoresLoading ? (
                    <span className="text-[9px] text-muted-foreground animate-pulse">{"\u2022\u2022\u2022"}</span>
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
