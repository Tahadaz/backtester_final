"use client"

import { useMemo, useState } from "react"
import { Loader2 } from "lucide-react"

import { PlotlyChart } from "@/components/run/plotly-chart"
import { TradesTable } from "@/components/strategy/trade-ledger-table"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useWfoFoldBacktest } from "@/hooks/use-api"
import type { PlotlyFigure } from "@/lib/api"
import { cn } from "@/lib/utils"

type Phase = "train" | "test"

export function WfoFoldBacktestPanel({
  symbol,
  horizon,
  variant,
  category,
  foldIndex,
  sr = false,
  timeframe = "1D",
  costBps,
  cooldownBars,
}: {
  symbol: string
  horizon: string
  variant: string
  category: string
  foldIndex: number
  sr?: boolean
  timeframe?: string
  costBps?: number
  cooldownBars?: number
}) {
  const { data, isLoading, error } = useWfoFoldBacktest({
    symbol,
    horizon,
    variant,
    category,
    foldIndex,
    sr,
    timeframe,
    costBps,
    cooldownBars,
  })
  const [selectedPhase, setSelectedPhase] = useState<Phase>("test")
  const activePeriod = useMemo(
    () => data?.periods.find((period) => period.phase === selectedPhase)
      ?? data?.periods.find((period) => period.phase === "test")
      ?? data?.periods[0]
      ?? null,
    [data?.periods, selectedPhase],
  )

  if (isLoading) {
    return (
      <div className="flex items-center justify-center border-t bg-background py-10">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }
  if (error || !data) {
    return (
      <div className="border-t bg-background px-4 py-6 text-sm text-red-600">
        Echec du chargement du backtest: {error instanceof Error ? error.message : "Erreur inconnue"}
      </div>
    )
  }
  if (data.status !== "ok" || !activePeriod) {
    return (
      <div className="border-t bg-background px-4 py-6 text-sm text-muted-foreground">
        Aucun backtest disponible pour ce fold{data.note ? `: ${data.note}` : "."}
      </div>
    )
  }

  const pnl = activePeriod.pnl_100k ?? activePeriod.pnl
  return (
    <div className="space-y-3 border-t bg-background p-4">
      <div>
        <p className="text-xs font-semibold">{data.description ?? data.winner_variant_id ?? data.pair_id ?? "Gagnant du fold"}</p>
        <p className="text-[10px] text-muted-foreground">Backtest du gagnant sur les periodes train et test du fold.</p>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {data.periods.map((period) => (
          <button
            key={period.phase}
            type="button"
            onClick={() => setSelectedPhase(period.phase)}
            className={cn(
              "rounded-md border px-2 py-1 text-[10px] font-medium transition-colors",
              selectedPhase === period.phase
                ? "border-primary bg-primary text-primary-foreground"
                : period.sharpe > 0
                  ? "border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                  : "border-red-200 bg-red-50 text-red-700 hover:bg-red-100",
            )}
          >
            {period.phase === "train" ? "Train" : "Test"} ({period.start_date} → {period.end_date})
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-4 text-xs">
        <div>
          <span className="text-muted-foreground">Sharpe: </span>
          <span className={cn("font-mono font-semibold", activePeriod.sharpe > 0 ? "text-green-700" : "text-red-700")}>
            {activePeriod.sharpe.toFixed(2)}
          </span>
        </div>
        <div>
          <span className="text-muted-foreground">PnL (100k): </span>
          <span className={cn("font-mono font-semibold", pnl > 0 ? "text-green-700" : "text-red-700")}>
            {pnl.toLocaleString(undefined, { maximumFractionDigits: 2 })}
          </span>
        </div>
        <div>
          <span className="text-muted-foreground">Trades: </span>
          <span className="font-mono font-semibold">{activePeriod.n_trades}</span>
        </div>
      </div>

      <Tabs defaultValue="graphiques">
        <TabsList className="mb-3">
          <TabsTrigger value="graphiques">Graphiques</TabsTrigger>
          <TabsTrigger value="registre">Registre</TabsTrigger>
        </TabsList>
        <TabsContent value="graphiques" className="space-y-3">
          <Card>
            <CardHeader className="px-4 pb-2 pt-3">
              <CardTitle className="text-sm">Prix et signaux</CardTitle>
            </CardHeader>
            <CardContent className="px-2 pb-2">
              <PlotlyChart figure={activePeriod.plot as PlotlyFigure} />
            </CardContent>
          </Card>
          {activePeriod.equity_plot ? (
            <Card>
              <CardHeader className="px-4 pb-2 pt-3"><CardTitle className="text-sm">Courbe Equity</CardTitle></CardHeader>
              <CardContent className="px-2 pb-2"><PlotlyChart figure={activePeriod.equity_plot as PlotlyFigure} /></CardContent>
            </Card>
          ) : null}
          {activePeriod.drawdown_plot ? (
            <Card>
              <CardHeader className="px-4 pb-2 pt-3"><CardTitle className="text-sm">Drawdown</CardTitle></CardHeader>
              <CardContent className="px-2 pb-2"><PlotlyChart figure={activePeriod.drawdown_plot as PlotlyFigure} /></CardContent>
            </Card>
          ) : null}
        </TabsContent>
        <TabsContent value="registre">
          <TradesTable trades={activePeriod.trades} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
