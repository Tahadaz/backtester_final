"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { formatNumber, formatDateTime } from "@/lib/format"
import { ChevronRight } from "lucide-react"

interface FillRow {
  [key: string]: unknown
}

export function FillsTable({
  rows,
  isLoading,
  nextCursor,
  onLoadMore,
  title = "Trade Fills",
}: {
  rows: FillRow[] | undefined
  isLoading: boolean
  nextCursor?: string
  onLoadMore?: () => void
  title?: string
}) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">{title}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-8 rounded-lg" />
          ))}
        </CardContent>
      </Card>
    )
  }

  if (!rows?.length) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">{title}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="py-8 text-center text-sm text-muted-foreground">
            No data available
          </p>
        </CardContent>
      </Card>
    )
  }

  const headers = Object.keys(rows[0])

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">{title}</CardTitle>
          <span className="text-xs text-muted-foreground">
            {rows.length} rows
          </span>
        </div>
      </CardHeader>
      <CardContent className="px-0 pb-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                {headers.map((h) => (
                  <th
                    key={h}
                    className="px-3 py-2.5 text-left text-xs font-bold uppercase tracking-wider text-muted-foreground whitespace-nowrap"
                  >
                    {h.replace(/_/g, " ")}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, idx) => (
                <tr
                  key={idx}
                  className="border-b border-border/50 transition-colors hover:bg-secondary/50"
                >
                  {headers.map((h) => {
                    const val = row[h]
                    const isNum =
                      typeof val === "number" && Number.isFinite(val)
                    return (
                      <td
                        key={h}
                        className={`px-3 py-2 text-xs whitespace-nowrap ${isNum ? "text-right font-mono" : ""}`}
                      >
                        {isNum ? formatNumber(val as number) : String(val ?? "--")}
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {nextCursor && onLoadMore && (
          <div className="border-t border-border p-3 text-center">
            <Button
              variant="outline"
              size="sm"
              onClick={onLoadMore}
              className="gap-1 text-xs"
            >
              Load More
              <ChevronRight className="h-3 w-3" />
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
