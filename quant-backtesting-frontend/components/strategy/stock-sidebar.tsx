"use client"

import { useState } from "react"
import { useMarketCatalog } from "@/hooks/use-api"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import { Search } from "lucide-react"

export function StockSidebar({
  selectedSymbol,
  onSelect,
  className,
}: {
  selectedSymbol: string | null
  onSelect: (symbol: string) => void
  className?: string
}) {
  const { data: catalog, isLoading } = useMarketCatalog()
  const [search, setSearch] = useState("")

  const filtered = (catalog ?? [])
    .filter((r) => r.has_canonical_data)
    .filter((r) => {
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

      <ScrollArea className="flex-1">
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
                  "w-full flex items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors",
                  "hover:bg-accent hover:text-accent-foreground",
                  selectedSymbol === row.symbol &&
                    "bg-accent text-accent-foreground font-semibold"
                )}
              >
                <span className="font-mono text-xs font-bold min-w-[60px]">
                  {row.symbol}
                </span>
                <span className="text-xs text-muted-foreground truncate">
                  {row.display_name ?? ""}
                </span>
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
