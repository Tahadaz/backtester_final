"use client"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { FolderOpen, Plus } from "lucide-react"
import { cn } from "@/lib/utils"
import type { SavedStrategyListItem } from "@/lib/api"

const STATUS_COLORS: Record<string, string> = {
  draft: "bg-yellow-100 text-yellow-700",
  modified: "bg-orange-100 text-orange-700",
  saved: "bg-green-100 text-green-700",
  archived: "bg-gray-100 text-gray-500",
}

const STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  modified: "Modified",
  saved: "Saved",
  archived: "Archived",
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
    <div className={cn("flex h-full flex-col overflow-hidden rounded-lg border border-line bg-card shadow-xs", className)}>
      <div className="flex items-center justify-between border-b border-line px-3 py-2.5">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Saved Strategies
        </span>
        <Button size="sm" variant="ghost" onClick={onCreate} className="h-7 w-7 px-0 text-[10px]" title="New strategy">
          <Plus className="h-3 w-3" />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="space-y-2 p-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-14 w-full rounded-md" />
            ))}
          </div>
        ) : strategies && strategies.length > 0 ? (
          <div className="space-y-1 p-1.5">
            {strategies.map((s) => (
              <button
                key={s.id}
                onClick={() => onSelect(s.id)}
                className={cn(
                  "w-full rounded-md border px-2.5 py-2 text-left transition-colors",
                  activeId === s.id
                    ? "border-[oklch(0.82_0.06_260)] bg-[oklch(0.94_0.04_260_/_0.55)]"
                    : "border-transparent hover:border-line hover:bg-bg3",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-xs font-medium">{s.name}</span>
                  <Badge
                    variant="secondary"
                    className={cn("shrink-0 px-1.5 py-0 text-[9px]", STATUS_COLORS[s.status])}
                  >
                    {STATUS_LABELS[s.status] ?? s.status}
                  </Badge>
                </div>
                <div className="mt-1 flex items-center gap-2 text-[10px] text-muted-foreground">
                  <span>{s.basket_count} stock{s.basket_count === 1 ? "" : "s"}</span>
                  <span>-</span>
                  <span>{s.horizon === "short" ? "ST" : s.horizon === "medium" ? "MT" : "LT"}</span>
                  <span>-</span>
                  <span>{s.side_policy === "long_only" ? "Long" : "L/S"}</span>
                </div>
              </button>
            ))}
          </div>
        ) : (
          <div className="flex h-32 flex-col items-center justify-center gap-2 text-muted-foreground">
            <FolderOpen className="h-8 w-8 opacity-30" />
            <span className="text-xs">No strategies</span>
          </div>
        )}
      </div>
    </div>
  )
}
