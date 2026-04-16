"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import type { MetricRow } from "@/lib/api"

export function MetricsTable({
  rows,
  isLoading,
}: {
  rows: MetricRow[] | undefined
  isLoading: boolean
}) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Metrics</CardTitle>
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
          <CardTitle className="text-base">Metrics</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="py-8 text-center text-sm text-muted-foreground">
            No metrics available
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Metrics</CardTitle>
      </CardHeader>
      <CardContent className="px-0 pb-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="px-3 py-2.5 text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
                  Symbol
                </th>
                <th className="px-3 py-2.5 text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
                  Metric
                </th>
                <th className="px-3 py-2.5 text-right text-xs font-bold uppercase tracking-wider text-muted-foreground">
                  Value
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, idx) => (
                <tr
                  key={idx}
                  className="border-b border-border/50 transition-colors hover:bg-secondary/50"
                >
                  <td className="px-3 py-2.5 font-mono text-xs font-semibold">
                    {row.symbol || "--"}
                  </td>
                  <td className="px-3 py-2.5 text-xs text-foreground">
                    {row.metric_name}
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-xs font-medium">
                    {String(row.metric_value)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}
