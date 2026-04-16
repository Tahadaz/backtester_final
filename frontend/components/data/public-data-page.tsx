"use client"

import { useState } from "react"
import { SignalBadge } from "@/components/dashboard-v1/signal-badge"
import { HORIZONS, formatScore } from "@/lib/dashboard-constants"
import { useDashboardData } from "@/hooks/use-dashboard"
import type { Horizon } from "@/lib/dashboard-types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"

export function PublicDataPage() {
  const [horizon, setHorizon] = useState<Horizon>("short")
  const { data, error, isLoading } = useDashboardData(horizon)

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Donnees publiques (lecture seule)</h1>
          <p className="text-sm text-muted-foreground">
            Snapshot statique pour la publication GitHub Pages.
          </p>
        </div>
        {data && (
          <p className="text-xs text-muted-foreground">
            Derniere mise a jour: {new Date(data.generated_at).toLocaleString("fr-FR")}
          </p>
        )}
      </div>

      <Tabs value={horizon} onValueChange={(value) => setHorizon(value as Horizon)}>
        <TabsList>
          {HORIZONS.map((item) => (
            <TabsTrigger key={item.value} value={item.value} className="text-xs">
              {item.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {isLoading && (
        <div className="space-y-2">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-10 w-full" />
          ))}
        </div>
      )}

      {error && (
        <Card className="border-destructive">
          <CardContent className="py-4">
            <p className="text-sm text-destructive">Erreur de chargement: {error.message}</p>
          </CardContent>
        </Card>
      )}

      {data && (
        <Card>
          <CardHeader className="px-5 pb-3 pt-4">
            <CardTitle className="text-sm font-semibold">
              Univers actions ({data.stocks.length} titres)
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0 pb-2">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Ticker</TableHead>
                  <TableHead>Nom</TableHead>
                  <TableHead>Secteur</TableHead>
                  <TableHead>Tendance</TableHead>
                  <TableHead>Momentum</TableHead>
                  <TableHead>Oscillation</TableHead>
                  <TableHead>Volume</TableHead>
                  <TableHead className="text-right">Signal technique global</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.stocks.map((stock) => (
                  <TableRow key={stock.symbol}>
                    <TableCell className="font-mono font-semibold">{stock.symbol}</TableCell>
                    <TableCell className="text-muted-foreground">{stock.display_name ?? "-"}</TableCell>
                    <TableCell className="text-muted-foreground">{stock.sector ?? "-"}</TableCell>
                    <TableCell>
                      <SignalBadge label={stock.per_family.sma?.label ?? null} />
                    </TableCell>
                    <TableCell>
                      <SignalBadge label={stock.per_family.macd?.label ?? null} />
                    </TableCell>
                    <TableCell>
                      <SignalBadge label={stock.per_family.rsi?.label ?? null} />
                    </TableCell>
                    <TableCell>
                      <SignalBadge label={stock.per_family.obv?.label ?? null} />
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-2">
                        <SignalBadge label={stock.aggregate_signal_label} />
                        {stock.aggregate_score_pct != null && (
                          <span className="font-mono text-xs font-semibold">
                            {formatScore(stock.aggregate_score_pct)}
                          </span>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
