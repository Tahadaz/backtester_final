"use client"

import type { IndicesCatalogRow } from "@/lib/api"
import { useIndexOhlcvHistory } from "@/hooks/use-api"
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"
import { OhlcvHistoryChart } from "@/components/data/ohlcv-history-chart"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import { FreshnessBadge } from "@/components/data/freshness-badge"

interface IndexDetailPanelProps {
  row: IndicesCatalogRow | null
  open: boolean
  onClose: () => void
}

export function IndexDetailPanel({ row, open, onClose }: IndexDetailPanelProps) {
  const { data: history, isLoading } = useIndexOhlcvHistory(open && row ? row.symbol : null)

  return (
    <Sheet open={open} onOpenChange={(o) => { if (!o) onClose() }}>
      <SheetContent side="right" className="w-full max-w-xl overflow-y-auto">
        <SheetHeader className="mb-4">
          <SheetTitle className="flex items-center gap-2 text-base">
            <span className="font-mono">{row?.symbol}</span>
            {row?.display_name && (
              <span className="text-sm font-normal text-muted-foreground">
                — {row.display_name}
              </span>
            )}
          </SheetTitle>
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            {row?.family && (
              <Badge variant="outline" className="text-[10px]">{row.family}</Badge>
            )}
            {row?.data_as_of && <FreshnessBadge dataAsOf={row.data_as_of} />}
            {row?.row_count != null && (
              <span>{row.row_count.toLocaleString()} barres</span>
            )}
            {row?.source_provider && (
              <span className="capitalize">{row.source_provider.replace(/_/g, " ")}</span>
            )}
          </div>
        </SheetHeader>

        {isLoading ? (
          <div className="space-y-3">
            <Skeleton className="h-52 w-full rounded-lg" />
            <Skeleton className="h-4 w-32" />
          </div>
        ) : history && history.bars.length > 0 ? (
          <OhlcvHistoryChart history={history} />
        ) : (
          <div className="flex min-h-32 items-center justify-center text-sm text-muted-foreground">
            Aucune donnée historique disponible.
          </div>
        )}
      </SheetContent>
    </Sheet>
  )
}
