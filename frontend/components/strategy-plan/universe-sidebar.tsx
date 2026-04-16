"use client"

import { useState } from "react"
import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import { Search } from "lucide-react"
import type { UniverseStock } from "@/lib/api"

interface UniverseSidebarProps {
  stocks: UniverseStock[] | undefined
  isLoading: boolean
  selectedSymbol: string | null
  onSelect: (symbol: string) => void
  className?: string
}

function signalBadge(score: number | null) {
  if (score == null) return { label: "N/A", cls: "bg-gray-100 text-gray-600" }
  if (score > 50) return { label: "ACHAT FORT", cls: "bg-emerald-100 text-emerald-700" }
  if (score > 15) return { label: "ACHAT", cls: "bg-green-100 text-green-700" }
  if (score >= -15) return { label: "NEUTRE", cls: "bg-gray-100 text-gray-600" }
  if (score >= -50) return { label: "VENTE", cls: "bg-orange-100 text-orange-700" }
  return { label: "VENTE FORTE", cls: "bg-red-100 text-red-700" }
}

export function UniverseSidebar({
  stocks,
  isLoading,
  selectedSymbol,
  onSelect,
  className,
}: UniverseSidebarProps) {
  const [search, setSearch] = useState("")

  const filtered = stocks?.filter((s) => {
    const q = search.toLowerCase()
    return (
      s.symbol.toLowerCase().includes(q) ||
      (s.display_name ?? "").toLowerCase().includes(q) ||
      (s.sector ?? "").toLowerCase().includes(q)
    )
  })

  const eligible = filtered?.filter((s) => s.eligible) ?? []
  const ineligible = filtered?.filter((s) => !s.eligible) ?? []

  return (
    <div className={cn("flex flex-col border-r border-border bg-card", className)}>
      {/* Search */}
      <div className="p-2 border-b border-border">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <input
            type="text"
            placeholder="Rechercher un titre…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-md border border-border bg-background pl-7 pr-2 py-1.5 text-xs placeholder:text-muted-foreground"
          />
        </div>
      </div>

      {/* Stock list */}
      <ScrollArea className="flex-1">
        <div className="p-1 space-y-px">
          {isLoading &&
            Array.from({ length: 8 }).map((_, i) => (
              <Skeleton key={i} className="h-10 w-full rounded-md" />
            ))}

          {!isLoading && eligible.length === 0 && ineligible.length === 0 && (
            <p className="p-3 text-xs text-muted-foreground text-center">
              Aucun titre trouvé
            </p>
          )}

          {eligible.map((stock) => {
            const badge = signalBadge(stock.signal_score)
            const isActive = selectedSymbol === stock.symbol
            return (
              <button
                key={stock.symbol}
                onClick={() => onSelect(stock.symbol)}
                className={cn(
                  "w-full flex items-center justify-between rounded-md px-2 py-1.5 text-left transition-colors",
                  isActive
                    ? "bg-primary/10 border border-primary/20"
                    : "hover:bg-muted/50"
                )}
              >
                <div className="min-w-0">
                  <div className="text-xs font-bold font-mono truncate">
                    {stock.symbol}
                  </div>
                  <div className="text-[10px] text-muted-foreground truncate">
                    {stock.display_name ?? stock.sector ?? ""}
                  </div>
                </div>
                <Badge className={cn("text-[9px] px-1.5 py-0 shrink-0 ml-1", badge.cls)}>
                  {badge.label}
                </Badge>
              </button>
            )
          })}

          {ineligible.length > 0 && (
            <>
              <div className="px-2 pt-2 pb-1">
                <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                  Exclus ({ineligible.length})
                </span>
              </div>
              {ineligible.map((stock) => (
                <button
                  key={stock.symbol}
                  onClick={() => onSelect(stock.symbol)}
                  className="w-full flex items-center justify-between rounded-md px-2 py-1.5 text-left opacity-50 hover:opacity-75 transition-opacity"
                >
                  <div className="min-w-0">
                    <div className="text-xs font-mono truncate">{stock.symbol}</div>
                    <div className="text-[10px] text-muted-foreground truncate">
                      {stock.exclusion_reason}
                    </div>
                  </div>
                </button>
              ))}
            </>
          )}
        </div>
      </ScrollArea>

      {/* Footer */}
      <div className="border-t border-border px-3 py-2">
        <span className="text-[10px] text-muted-foreground">
          {eligible.length} éligible(s) / {stocks?.length ?? 0} titre(s)
        </span>
      </div>
    </div>
  )
}
