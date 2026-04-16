"use client"

import { useMemo, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { SignalBadge } from "@/components/signal-badge"
import type { LeaderboardRow } from "@/lib/api"

interface StrategySignal {
  name: string
  signalValue: number
  cagr: number
}

interface StockSignalSummary {
  symbol: string
  strategies: StrategySignal[]
  buys: number
  sells: number
  holds: number
  majorityValue: number
}

function computeStockSummaries(rows: LeaderboardRow[]): StockSignalSummary[] {
  const bySymbol = new Map<string, LeaderboardRow[]>()
  for (const row of rows) {
    const existing = bySymbol.get(row.symbol) ?? []
    existing.push(row)
    bySymbol.set(row.symbol, existing)
  }

  return Array.from(bySymbol.entries()).map(([symbol, symbolRows]) => {
    const strategies: StrategySignal[] = symbolRows.map((r) => ({
      name: r.strategy_kind,
      signalValue: r.signal_today ?? 0,
      cagr: r.cagr ?? 0,
    }))
    const buys = strategies.filter((s) => s.signalValue > 0).length
    const sells = strategies.filter((s) => s.signalValue < 0).length
    const holds = strategies.filter((s) => s.signalValue === 0).length

    let majorityValue = 0
    if (buys > sells && buys > holds) majorityValue = 1
    else if (sells > buys && sells > holds) majorityValue = -1

    return { symbol, strategies, buys, sells, holds, majorityValue }
  })
}

function computeAggregation(rows: LeaderboardRow[]) {
  const strategies: StrategySignal[] = rows.map((r) => ({
    name: r.strategy_kind,
    signalValue: r.signal_today ?? 0,
    cagr: r.cagr ?? 0,
  }))

  const buys = strategies.filter((s) => s.signalValue > 0).length
  const sells = strategies.filter((s) => s.signalValue < 0).length
  const holds = strategies.filter((s) => s.signalValue === 0).length

  let majorityValue = 0
  if (buys > sells && buys > holds) majorityValue = 1
  else if (sells > buys && sells > holds) majorityValue = -1

  return { strategies, buys, sells, holds, majorityValue }
}

function StockOverviewGrid({ summaries }: { summaries: StockSignalSummary[] }) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Stock-Level Signal Overview</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {summaries.map((s) => (
            <div
              key={s.symbol}
              className="flex items-center justify-between rounded-lg border border-border bg-secondary/30 p-3"
            >
              <div>
                <p className="font-mono text-sm font-bold text-foreground">
                  {s.symbol}
                </p>
                <p className="text-[10px] text-muted-foreground">
                  B:{s.buys} S:{s.sells} H:{s.holds}
                </p>
              </div>
              <SignalBadge value={s.majorityValue} size="md" />
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

function SymbolDetail({ rows, symbol }: { rows: LeaderboardRow[]; symbol: string }) {
  const filtered = useMemo(
    () => rows.filter((r) => r.symbol === symbol),
    [rows, symbol]
  )
  const { strategies, buys, sells, holds, majorityValue } =
    useMemo(() => computeAggregation(filtered), [filtered])

  const [weights, setWeights] = useState<Record<string, number>>({})

  const getWeight = (name: string, defaultCagr: number) =>
    weights[name] ?? Math.max(0, defaultCagr)

  const weightedResult = useMemo(() => {
    let weightedSum = 0
    let totalWeight = 0
    strategies.forEach((s) => {
      const w = getWeight(s.name, s.cagr)
      weightedSum += s.signalValue * w
      totalWeight += w
    })
    if (totalWeight === 0) return 0
    const avg = weightedSum / totalWeight
    if (avg > 0.1) return 1
    if (avg < -0.1) return -1
    return 0
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strategies, weights])

  if (!strategies.length) return null

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">
          Strategy Signals & Final Decision
          <span className="ml-2 font-mono text-xs font-normal text-muted-foreground">
            {symbol}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        {/* Individual signals */}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
          {strategies.map((s) => (
            <div
              key={s.name}
              className="flex flex-col gap-1.5 rounded-lg border border-border bg-secondary/30 p-3"
            >
              <span className="text-xs font-semibold text-foreground">
                {s.name}
              </span>
              <SignalBadge value={s.signalValue} size="sm" />
            </div>
          ))}
        </div>

        {/* Aggregation */}
        <div className="grid gap-4 sm:grid-cols-2">
          {/* Majority Vote */}
          <div className="rounded-xl border border-border p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Majority Vote
            </p>
            <div className="mt-2">
              <SignalBadge value={majorityValue} size="lg" />
            </div>
            <p className="mt-2 text-xs text-muted-foreground">
              Buy: {buys} | Sell: {sells} | Hold: {holds}
            </p>
          </div>

          {/* Weighted Vote */}
          <div className="rounded-xl border border-border p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Weighted Vote
            </p>
            <div className="mt-2">
              <SignalBadge value={weightedResult} size="lg" />
            </div>
            <div className="mt-3 space-y-1.5">
              {strategies.map((s) => (
                <div key={s.name} className="flex items-center gap-2">
                  <span className="flex-1 truncate text-xs text-muted-foreground">
                    {s.name}
                  </span>
                  <Input
                    type="number"
                    step="0.01"
                    min="0"
                    value={getWeight(s.name, s.cagr).toFixed(4)}
                    onChange={(e) =>
                      setWeights((prev) => ({
                        ...prev,
                        [s.name]: Math.max(0, Number(e.target.value) || 0),
                      }))
                    }
                    className="h-7 w-20 font-mono text-[10px] text-right"
                  />
                </div>
              ))}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export function SignalAggregation({
  rows,
  symbol,
}: {
  rows: LeaderboardRow[]
  symbol?: string
}) {
  const stockSummaries = useMemo(() => computeStockSummaries(rows), [rows])
  const uniqueSymbols = useMemo(
    () => Array.from(new Set(rows.map((r) => r.symbol))),
    [rows]
  )

  const [activeSymbol, setActiveSymbol] = useState<string | null>(symbol ?? null)

  // If a specific symbol filter is set from outside, show detail view
  if (symbol) {
    return <SymbolDetail rows={rows} symbol={symbol} />
  }

  return (
    <div className="space-y-4">
      {/* Overview grid */}
      <StockOverviewGrid summaries={stockSummaries} />

      {/* Symbol selector */}
      {uniqueSymbols.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Detailed View</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {uniqueSymbols.map((sym) => {
                const summary = stockSummaries.find((s) => s.symbol === sym)
                const isActive = activeSymbol === sym
                return (
                  <button
                    key={sym}
                    onClick={() => setActiveSymbol(isActive ? null : sym)}
                    className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-semibold transition-all ${
                      isActive
                        ? "border-primary bg-primary/5 text-foreground ring-1 ring-primary"
                        : "border-border text-muted-foreground hover:border-primary/30 hover:bg-secondary/50"
                    }`}
                  >
                    <span className="font-mono">{sym}</span>
                    {summary && <SignalBadge value={summary.majorityValue} size="sm" />}
                  </button>
                )
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Detail view */}
      {activeSymbol && <SymbolDetail rows={rows} symbol={activeSymbol} />}
    </div>
  )
}
