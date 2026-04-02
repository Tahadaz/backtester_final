"use client"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Plus, FolderOpen } from "lucide-react"
import { cn } from "@/lib/utils"
import type { SavedStrategyListItem } from "@/lib/api"

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-yellow-100 text-yellow-700",
  modified: "bg-orange-100 text-orange-700",
  saved: "bg-green-100 text-green-700",
  archived: "bg-gray-100 text-gray-500",
}

const STATUS_LABELS: Record<string, string> = {
  draft: "Brouillon",
  modified: "Modifié",
  saved: "Sauvegardé",
  archived: "Archivé",
}

interface StrategyRailProps {
  strategies: SavedStrategyListItem[] | undefined
  isLoading: boolean
  activeId: string | null
  onSelect: (id: string) => void
  onCreate: () => void
  className?: string
}

export function StrategyRail({
  strategies,
  isLoading,
  activeId,
  onSelect,
  onCreate,
  className,
}: StrategyRailProps) {
  return (
    <div className={cn("flex flex-col h-full border-r bg-muted/30", className)}>
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          Stratégies
        </span>
        <Button size="sm" variant="outline" onClick={onCreate} className="h-6 text-[10px] gap-1 px-2">
          <Plus className="h-3 w-3" />
          Nouvelle
        </Button>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="space-y-2 p-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-14 w-full rounded-md" />
            ))}
          </div>
        ) : strategies && strategies.length > 0 ? (
          <div className="p-2 space-y-1">
            {strategies.map((s) => (
              <button
                key={s.id}
                onClick={() => onSelect(s.id)}
                className={cn(
                  "w-full text-left rounded-md px-3 py-2.5 transition-colors",
                  activeId === s.id
                    ? "bg-primary/10 border border-primary/20"
                    : "hover:bg-muted border border-transparent"
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium truncate">{s.name}</span>
                  <Badge
                    variant="secondary"
                    className={cn("text-[9px] px-1.5 py-0 shrink-0", STATUS_COLORS[s.status])}
                  >
                    {STATUS_LABELS[s.status] ?? s.status}
                  </Badge>
                </div>
                <div className="flex items-center gap-2 mt-1 text-[10px] text-muted-foreground">
                  <span>{s.basket_count} titre{s.basket_count !== 1 ? "s" : ""}</span>
                  <span>·</span>
                  <span>{s.horizon === "short" ? "CT" : s.horizon === "medium" ? "MT" : "LT"}</span>
                  <span>·</span>
                  <span>{s.side_policy === "long_only" ? "Long" : "L/S"}</span>
                </div>
              </button>
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center h-32 gap-2 text-muted-foreground">
            <FolderOpen className="h-8 w-8 opacity-30" />
            <span className="text-xs">Aucune stratégie</span>
          </div>
        )}
      </div>
    </div>
  )
}
