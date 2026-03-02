"use client"

import { useState, useEffect, useMemo } from "react"
import { toast } from "sonner"
import { Search, ChevronDown, ChevronRight, BarChart2, TrendingUp, TrendingDown, Minus, Loader2, RefreshCw, ArrowUpRight } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import { PlotlyChart } from "@/components/run/plotly-chart"
import {
  listRuns,
  getLeaderboard,
  materializeStrategyDetails,
  type Run,
  type LeaderboardRow,
  type MaterializedStrategyDetails,
} from "@/lib/api"
import { formatNumber, formatPercent, formatDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"

// ─────────────────────────── types ───────────────────────────

type StrategyEntry = LeaderboardRow & { run_id: string }

type SymbolEntry = {
  symbol: string
  runCount: number
  strategies: StrategyEntry[]
  bestReturn: number | null
  bestSharpe: number | null
}

// ─────────────────────────── helpers ─────────────────────────

function numVal(v: number | null | undefined): number {
  return v === null || v === undefined || !Number.isFinite(Number(v)) ? -Infinity : Number(v)
}

function SignalChip({ value }: { value: number | null | undefined }) {
  const v = value ?? 0
  if (v > 0) return <Badge className="bg-emerald-100 text-emerald-700 border-emerald-200 font-semibold text-xs">BUY</Badge>
  if (v < 0) return <Badge className="bg-red-100 text-red-700 border-red-200 font-semibold text-xs">SELL</Badge>
  return <Badge variant="secondary" className="text-xs">HOLD</Badge>
}

function ReturnCell({ value }: { value: number | null | undefined }) {
  const v = value ?? 0
  const color = v > 0 ? "text-emerald-600" : v < 0 ? "text-red-600" : "text-muted-foreground"
  const Icon = v > 0 ? TrendingUp : v < 0 ? TrendingDown : Minus
  return (
    <span className={cn("inline-flex items-center gap-1 font-semibold tabular-nums", color)}>
      <Icon className="h-3.5 w-3.5" />
      {formatPercent(v)}
    </span>
  )
}

// ─────────────────────────── Strategy Detail Panel ────────────

function StrategyDetailPanel({ entry, onClose }: { entry: StrategyEntry; onClose: () => void }) {
  const [details, setDetails] = useState<MaterializedStrategyDetails | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    materializeStrategyDetails(entry.run_id, { symbol: entry.symbol, strategy_kind: entry.strategy_kind })
      .then((d) => { if (!cancelled) { setDetails(d); setLoading(false) } })
      .catch((e) => { if (!cancelled) { setError(String(e?.message || e)); setLoading(false) } })
    return () => { cancelled = true }
  }, [entry.run_id, entry.symbol, entry.strategy_kind])

  const plotKeys = details ? Object.keys(details.plots) : []

  return (
    <div className="border-t border-border bg-background">
      <div className="flex items-center justify-between px-4 py-3 bg-secondary/40">
        <div className="flex items-center gap-3">
          <BarChart2 className="h-4 w-4 text-primary" />
          <span className="font-semibold text-sm">{entry.strategy_kind} — {entry.symbol}</span>
          <SignalChip value={entry.signal_today} />
        </div>
        <Button variant="ghost" size="sm" onClick={onClose}>Close</Button>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      )}

      {error && (
        <div className="px-4 py-6 text-sm text-red-600">Failed to load details: {error}</div>
      )}

      {details && !loading && (
        <div className="p-4">
          <Tabs defaultValue={plotKeys.length > 0 ? "plots" : "metrics"}>
            <TabsList className="mb-4">
              {plotKeys.length > 0 && <TabsTrigger value="plots">Charts</TabsTrigger>}
              <TabsTrigger value="metrics">Metrics</TabsTrigger>
              {details.trade_performance.length > 0 && <TabsTrigger value="performance">Trade Performance</TabsTrigger>}
              {details.trade_ledger.length > 0 && <TabsTrigger value="ledger">Trades Ledger</TabsTrigger>}
            </TabsList>

            {/* PLOTS */}
            {plotKeys.length > 0 && (
              <TabsContent value="plots" className="space-y-4">
                {plotKeys.map((key) => (
                  <Card key={key}>
                    <CardHeader className="pb-2 pt-3 px-4">
                      <CardTitle className="text-sm capitalize">{key.replace(/_/g, " ")}</CardTitle>
                    </CardHeader>
                    <CardContent className="px-2 pb-2">
                      <PlotlyChart
                        figure={details.plots[key] as Parameters<typeof PlotlyChart>[0]["figure"]}
                      />
                    </CardContent>
                  </Card>
                ))}
              </TabsContent>
            )}

            {/* METRICS */}
            <TabsContent value="metrics">
              <Card>
                <CardContent className="p-0">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b bg-secondary/30">
                        <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">Metric</th>
                        <th className="px-4 py-2 text-right text-xs font-semibold uppercase tracking-wider text-muted-foreground">Value</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(details.metrics).map(([k, v]) => (
                        <tr key={k} className="border-b border-border/50 hover:bg-secondary/20">
                          <td className="px-4 py-2 font-medium capitalize">{k.replace(/_/g, " ")}</td>
                          <td className="px-4 py-2 text-right tabular-nums font-mono text-xs">
                            {typeof v === "number" ? formatNumber(v) : String(v ?? "—")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardContent>
              </Card>
            </TabsContent>

            {/* TRADE PERFORMANCE */}
            {details.trade_performance.length > 0 && (
              <TabsContent value="performance">
                <Card>
                  <CardContent className="p-0">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b bg-secondary/30">
                          <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">Metric</th>
                          <th className="px-4 py-2 text-right text-xs font-semibold uppercase tracking-wider text-muted-foreground">Value</th>
                        </tr>
                      </thead>
                      <tbody>
                        {details.trade_performance.map((row, i) => (
                          <tr key={i} className="border-b border-border/50 hover:bg-secondary/20">
                            <td className="px-4 py-2 font-medium capitalize">{String(row.metric ?? "").replace(/_/g, " ")}</td>
                            <td className="px-4 py-2 text-right tabular-nums font-mono text-xs">
                              {typeof row.value === "number" ? formatNumber(row.value as number) : String(row.value ?? "—")}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </CardContent>
                </Card>
              </TabsContent>
            )}

            {/* TRADES LEDGER */}
            {details.trade_ledger.length > 0 && (
              <TabsContent value="ledger">
                <Card>
                  <CardContent className="p-0 overflow-x-auto">
                    <table className="w-full text-xs whitespace-nowrap">
                      <thead>
                        <tr className="border-b bg-secondary/30">
                          {["Date", "Symbol", "Side", "Entry Price", "Exit Price", "CMP", "Qty", "PnL Réalisé", "PnL Latent", "Notional", "Cost"].map((h) => (
                            <th key={h} className="px-3 py-2 text-left font-semibold uppercase tracking-wider text-muted-foreground">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {details.trade_ledger.map((row, i) => {
                          const pnl = Number(row.pnl_realise ?? row.pnl ?? 0)
                          const pnlColor = pnl > 0 ? "text-emerald-600" : pnl < 0 ? "text-red-600" : ""
                          const pnlLatent = Number(row.pnl_latent ?? 0)
                          const pnlLatentColor = pnlLatent > 0 ? "text-emerald-600" : pnlLatent < 0 ? "text-red-600" : ""
                          return (
                            <tr key={i} className="border-b border-border/40 hover:bg-secondary/20">
                              <td className="px-3 py-1.5 font-mono">{String(row.timestamp ?? row.entry_time ?? "").slice(0, 10)}</td>
                              <td className="px-3 py-1.5 font-semibold">{String(row.symbol ?? "")}</td>
                              <td className="px-3 py-1.5">
                                <span className={cn("font-semibold", String(row.side ?? "").toUpperCase() === "BUY" ? "text-emerald-600" : "text-red-600")}>
                                  {String(row.side ?? "").toUpperCase()}
                                </span>
                              </td>
                              <td className="px-3 py-1.5 tabular-nums">{row.entry_price != null ? formatNumber(Number(row.entry_price)) : "—"}</td>
                              <td className="px-3 py-1.5 tabular-nums">{row.exit_price != null ? formatNumber(Number(row.exit_price)) : "—"}</td>
                              <td className="px-3 py-1.5 tabular-nums">{row.cmp != null ? formatNumber(Number(row.cmp)) : "—"}</td>
                              <td className="px-3 py-1.5 tabular-nums">{row.quantite != null ? formatNumber(Number(row.quantite)) : "—"}</td>
                              <td className={cn("px-3 py-1.5 tabular-nums font-semibold", pnlColor)}>{isFinite(pnl) ? formatNumber(pnl) : "—"}</td>
                              <td className={cn("px-3 py-1.5 tabular-nums font-semibold", pnlLatentColor)}>{isFinite(pnlLatent) ? formatNumber(pnlLatent) : "—"}</td>
                              <td className="px-3 py-1.5 tabular-nums">{row.notional != null ? formatNumber(Number(row.notional)) : "—"}</td>
                              <td className="px-3 py-1.5 tabular-nums">{row.cost != null ? formatNumber(Number(row.cost)) : "—"}</td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </CardContent>
                </Card>
              </TabsContent>
            )}
          </Tabs>
        </div>
      )}
    </div>
  )
}

// ─────────────────────────── Leaderboard for a symbol ────────

function SymbolLeaderboard({ symbol, strategies }: { symbol: string; strategies: StrategyEntry[] }) {
  const [expandedKey, setExpandedKey] = useState<string | null>(null)

  const sorted = useMemo(() =>
    [...strategies].sort((a, b) => numVal(b.total_return) - numVal(a.total_return)),
    [strategies]
  )

  function rowKey(e: StrategyEntry) {
    return `${e.run_id}::${e.strategy_kind}::${e.rank ?? 0}`
  }

  return (
    <Card>
      <CardHeader className="pb-3 pt-4">
        <CardTitle className="text-base font-bold">{symbol} — Strategy Leaderboard</CardTitle>
        <p className="text-xs text-muted-foreground">{strategies.length} strategies across all runs</p>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-secondary/30">
                {["#", "Strategy", "Return", "Sharpe", "Max DD", "Win %", "Trades", "Signal", "Run", ""].map((h) => (
                  <th key={h} className="px-3 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((entry, idx) => {
                const key = rowKey(entry)
                const isExpanded = expandedKey === key
                return (
                  <>
                    <tr
                      key={key}
                      className={cn(
                        "border-b border-border/50 transition-colors cursor-pointer",
                        isExpanded ? "bg-primary/5" : "hover:bg-secondary/40"
                      )}
                      onClick={() => setExpandedKey(isExpanded ? null : key)}
                    >
                      <td className="px-3 py-2.5">
                        <span className={cn(
                          "inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold",
                          idx === 0 ? "bg-amber-100 text-amber-700" :
                          idx === 1 ? "bg-slate-100 text-slate-600" :
                          idx === 2 ? "bg-orange-100 text-orange-600" :
                          "bg-secondary text-muted-foreground"
                        )}>
                          {idx + 1}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 font-semibold">{entry.strategy_kind}</td>
                      <td className="px-3 py-2.5"><ReturnCell value={entry.total_return} /></td>
                      <td className="px-3 py-2.5 tabular-nums">{entry.sharpe != null ? formatNumber(entry.sharpe) : "—"}</td>
                      <td className="px-3 py-2.5 tabular-nums text-red-600">{entry.max_drawdown != null ? formatPercent(entry.max_drawdown) : "—"}</td>
                      <td className="px-3 py-2.5 tabular-nums">{entry.win_pct != null ? formatPercent(entry.win_pct) : "—"}</td>
                      <td className="px-3 py-2.5 tabular-nums">{entry.n_fills ?? "—"}</td>
                      <td className="px-3 py-2.5"><SignalChip value={entry.signal_today} /></td>
                      <td className="px-3 py-2.5">
                        <span className="font-mono text-xs text-muted-foreground">{entry.run_id.slice(0, 8)}</span>
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        {isExpanded
                          ? <ChevronDown className="h-4 w-4 text-muted-foreground ml-auto" />
                          : <ChevronRight className="h-4 w-4 text-muted-foreground ml-auto" />}
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr key={`${key}--detail`}>
                        <td colSpan={10} className="p-0">
                          <StrategyDetailPanel
                            entry={entry}
                            onClose={() => setExpandedKey(null)}
                          />
                        </td>
                      </tr>
                    )}
                  </>
                )
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}

// ─────────────────────────── Main Page ───────────────────────

export default function ResultsPage() {
  const [runs, setRuns] = useState<Run[]>([])
  const [symbolMap, setSymbolMap] = useState<Map<string, SymbolEntry>>(new Map())
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const [search, setSearch] = useState("")
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  async function loadAll(showRefreshing = false) {
    if (showRefreshing) setRefreshing(true)
    else setLoading(true)
    try {
      const allRuns = await listRuns({ status: "succeeded", limit: 100 })
      setRuns(allRuns)

      const map = new Map<string, SymbolEntry>()

      await Promise.allSettled(
        allRuns.map(async (run) => {
          try {
            const rows = await getLeaderboard(run.run_id)
            for (const row of rows) {
              const sym = row.symbol
              if (!sym) continue
              const entry: StrategyEntry = { ...row, run_id: run.run_id }
              if (!map.has(sym)) {
                map.set(sym, {
                  symbol: sym,
                  runCount: 0,
                  strategies: [],
                  bestReturn: null,
                  bestSharpe: null,
                })
              }
              const se = map.get(sym)!
              se.strategies.push(entry)
            }
          } catch {
            // skip failed leaderboard fetches
          }
        })
      )

      // compute run counts and best metrics
      for (const [, se] of map) {
        const runIds = new Set(se.strategies.map((s) => s.run_id))
        se.runCount = runIds.size
        const returns = se.strategies.map((s) => s.total_return).filter((v) => v != null && isFinite(Number(v))) as number[]
        const sharpes = se.strategies.map((s) => s.sharpe).filter((v) => v != null && isFinite(Number(v))) as number[]
        se.bestReturn = returns.length > 0 ? Math.max(...returns) : null
        se.bestSharpe = sharpes.length > 0 ? Math.max(...sharpes) : null
      }

      setSymbolMap(map)

      // auto-select first symbol
      if (!selectedSymbol && map.size > 0) {
        setSelectedSymbol([...map.keys()][0])
      }
    } catch (e) {
      toast.error(`Failed to load results: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  useEffect(() => { loadAll() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const filteredSymbols = useMemo(() => {
    const q = search.trim().toLowerCase()
    const all = [...symbolMap.values()].sort((a, b) => numVal(b.bestReturn) - numVal(a.bestReturn))
    return q ? all.filter((s) => s.symbol.toLowerCase().includes(q)) : all
  }, [symbolMap, search])

  const activeEntry = selectedSymbol ? symbolMap.get(selectedSymbol) ?? null : null

  // summary stats
  const totalRuns = runs.length
  const totalSymbols = symbolMap.size
  const totalStrategies = [...symbolMap.values()].reduce((acc, s) => acc + s.strategies.length, 0)

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">All Results</h1>
          <p className="text-sm text-muted-foreground">Aggregated strategy performance across all runs and tickers</p>
        </div>
        <Button variant="outline" size="sm" className="gap-1.5" onClick={() => loadAll(true)} disabled={refreshing}>
          <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
          Refresh
        </Button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Completed Runs", value: totalRuns },
          { label: "Unique Tickers", value: totalSymbols },
          { label: "Total Strategies", value: totalStrategies },
        ].map((s) => (
          <Card key={s.label}>
            <CardContent className="flex items-center gap-3 p-4">
              <div>
                <p className="text-2xl font-bold">{s.value}</p>
                <p className="text-xs text-muted-foreground">{s.label}</p>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {loading ? (
        <div className="grid grid-cols-4 gap-4">
          <Skeleton className="h-[500px] rounded-xl col-span-1" />
          <Skeleton className="h-[500px] rounded-xl col-span-3" />
        </div>
      ) : symbolMap.size === 0 ? (
        <Card>
          <CardContent className="py-16 text-center">
            <BarChart2 className="mx-auto mb-3 h-10 w-10 text-muted-foreground/40" />
            <h3 className="font-semibold">No results yet</h3>
            <p className="mt-1 text-sm text-muted-foreground">Run a backtest to see strategy results here.</p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-4 gap-4 items-start">
          {/* Left: ticker list */}
          <Card className="col-span-1 sticky top-20">
            <CardHeader className="pb-2 pt-3 px-3">
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                  placeholder="Search tickers…"
                  className="pl-8 h-8 text-sm"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
            </CardHeader>
            <CardContent className="p-0 pb-2">
              <div className="max-h-[520px] overflow-y-auto">
                {filteredSymbols.map((s) => (
                  <button
                    key={s.symbol}
                    onClick={() => setSelectedSymbol(s.symbol)}
                    className={cn(
                      "w-full text-left px-3 py-2.5 transition-colors flex items-center justify-between group",
                      selectedSymbol === s.symbol
                        ? "bg-primary/10 border-l-2 border-primary"
                        : "hover:bg-secondary/50 border-l-2 border-transparent"
                    )}
                  >
                    <div>
                      <p className="font-semibold text-sm">{s.symbol}</p>
                      <p className="text-xs text-muted-foreground">{s.strategies.length} strategies · {s.runCount} run{s.runCount !== 1 ? "s" : ""}</p>
                    </div>
                    <div className="text-right">
                      {s.bestReturn != null && (
                        <p className={cn("text-xs font-bold tabular-nums", s.bestReturn >= 0 ? "text-emerald-600" : "text-red-600")}>
                          {s.bestReturn >= 0 ? "+" : ""}{formatPercent(s.bestReturn)}
                        </p>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Right: leaderboard */}
          <div className="col-span-3">
            {activeEntry ? (
              <SymbolLeaderboard symbol={activeEntry.symbol} strategies={activeEntry.strategies} />
            ) : (
              <Card>
                <CardContent className="py-16 text-center">
                  <ArrowUpRight className="mx-auto mb-3 h-8 w-8 text-muted-foreground/40" />
                  <p className="text-sm text-muted-foreground">Select a ticker to view its strategy leaderboard</p>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
