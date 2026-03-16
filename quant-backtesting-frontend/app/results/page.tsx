"use client"

import { useState, useEffect, useMemo, Fragment } from "react"
import { toast } from "sonner"
import {
  Search, ChevronDown, ChevronRight, BarChart2, TrendingUp, TrendingDown, Minus,
  Loader2, RefreshCw, Target, Shield, Zap, ArrowUpDown,
} from "lucide-react"
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

// ─── types ───────────────────────────────────────────────────

type StrategyEntry = LeaderboardRow & { run_id: string }

type SymbolEntry = {
  symbol: string
  runCount: number
  strategies: StrategyEntry[]
  bestReturn: number | null
  bestSharpe: number | null
  bestCagr: number | null
}

type SortKey =
  | "total_return"
  | "cagr"
  | "sharpe"
  | "max_drawdown"
  | "win_pct"
  | "pnl"
  | "confidence_score"
  | "opportunity_score"
  | "n_fills"

type HorizonFilter = "all" | "short" | "medium" | "long"

const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: "total_return", label: "Return" },
  { value: "cagr", label: "CAGR" },
  { value: "sharpe", label: "Sharpe" },
  { value: "max_drawdown", label: "Max DD (asc)" },
  { value: "win_pct", label: "Win %" },
  { value: "pnl", label: "PnL" },
  { value: "confidence_score", label: "Confidence" },
  { value: "opportunity_score", label: "Opportunity" },
]

const HORIZON_LABELS: Record<string, string> = {
  short: "Court terme",
  medium: "Moyen terme",
  long: "Long terme",
}

const HORIZON_DETAIL: Record<string, string> = {
  short: "Train 252j / Test 63j / Step 21j / 5 ans",
  medium: "Train 504j / Test 126j / Step 21j / 10 ans",
  long: "Train 756j / Test 252j / Step 21j / 20 ans",
}

// ─── helpers ─────────────────────────────────────────────────

function numVal(v: number | null | undefined): number {
  return v == null || !Number.isFinite(Number(v)) ? -Infinity : Number(v)
}

function sortEntries(entries: StrategyEntry[], key: SortKey): StrategyEntry[] {
  return [...entries].sort((a, b) => {
    if (key === "max_drawdown") {
      // ascending (less drawdown = better)
      const av = a.max_drawdown ?? Infinity
      const bv = b.max_drawdown ?? Infinity
      return Number(av) - Number(bv)
    }
    return numVal(b[key]) - numVal(a[key])
  })
}

function ScoreGauge({ value, label, icon: Icon, color }: {
  value: number | null | undefined
  label: string
  icon: React.ElementType
  color: string
}) {
  const v = value ?? 0
  const pct = Math.min(100, Math.max(0, v))
  return (
    <div className="flex flex-col items-center gap-1">
      <div className="relative flex h-14 w-14 items-center justify-center">
        <svg viewBox="0 0 36 36" className="h-14 w-14 -rotate-90">
          <circle cx="18" cy="18" r="15.5" fill="none" stroke="currentColor"
            strokeWidth="3" className="text-border" />
          <circle cx="18" cy="18" r="15.5" fill="none" stroke="currentColor"
            strokeWidth="3" strokeDasharray={`${pct} 100`}
            strokeLinecap="round" className={color} />
        </svg>
        <Icon className={cn("absolute h-4 w-4", color)} />
      </div>
      <p className="text-xs font-semibold tabular-nums">{value != null ? formatNumber(v, 1) : "—"}</p>
      <p className="text-[10px] text-muted-foreground">{label}</p>
    </div>
  )
}

function SignalChip({ value }: { value: number | null | undefined }) {
  const v = value ?? 0
  if (v > 0) return <Badge className="bg-emerald-100 text-emerald-700 border-emerald-200 text-xs">ACHAT</Badge>
  if (v < 0) return <Badge className="bg-red-100 text-red-700 border-red-200 text-xs">VENTE</Badge>
  return <Badge variant="secondary" className="text-xs">NEUTRE</Badge>
}

function ReturnCell({ value }: { value: number | null | undefined }) {
  const v = value ?? 0
  const color = v > 0 ? "text-emerald-600" : v < 0 ? "text-red-600" : "text-muted-foreground"
  const Icon = v > 0 ? TrendingUp : v < 0 ? TrendingDown : Minus
  return (
    <span className={cn("inline-flex items-center gap-1 font-semibold tabular-nums text-xs", color)}>
      <Icon className="h-3 w-3" />
      {formatPercent(v)}
    </span>
  )
}

function HorizonBadge({ horizon }: { horizon: string | null | undefined }) {
  if (!horizon) return null
  const colors: Record<string, string> = {
    short: "bg-blue-100 text-blue-700 border-blue-200",
    medium: "bg-violet-100 text-violet-700 border-violet-200",
    long: "bg-amber-100 text-amber-700 border-amber-200",
  }
  return (
    <Badge className={cn("text-[10px] px-1.5", colors[horizon] ?? "bg-secondary text-secondary-foreground")}>
      {HORIZON_LABELS[horizon] ?? horizon}
    </Badge>
  )
}

function ParamsDisplay({ params }: { params: unknown }) {
  if (!params || typeof params !== "object") return <span className="text-muted-foreground text-xs">—</span>
  const entries = Object.entries(params as Record<string, unknown>)
    .filter(([k]) => !k.startsWith("__"))
    .slice(0, 8)
  return (
    <div className="flex flex-wrap gap-1">
      {entries.map(([k, v]) => (
        <span key={k} className="inline-flex items-center gap-0.5 rounded bg-secondary px-1.5 py-0.5 text-[10px] font-mono">
          <span className="text-muted-foreground">{k}:</span>
          <span className="font-semibold">{typeof v === "number" ? formatNumber(v) : String(v)}</span>
        </span>
      ))}
    </div>
  )
}

// ─── Strategy Detail Panel ────────────────────────────────────

function StrategyDetailPanel({ entry, onClose }: { entry: StrategyEntry; onClose: () => void }) {
  const [details, setDetails] = useState<MaterializedStrategyDetails | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState("plots")

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
      {/* Panel header */}
      <div className="flex items-center justify-between px-4 py-3 bg-secondary/40 border-b border-border">
        <div className="flex items-center gap-3">
          <BarChart2 className="h-4 w-4 text-primary" />
          <span className="font-semibold text-sm">{entry.strategy_kind} — {entry.symbol}</span>
          <HorizonBadge horizon={entry.horizon} />
          <SignalChip value={entry.signal_today} />
        </div>
        <div className="flex items-center gap-3">
          <div className="flex gap-4">
            <ScoreGauge value={entry.opportunity_score} label="Opportunité" icon={Zap} color="text-amber-500" />
            <ScoreGauge value={entry.confidence_score} label="Confiance" icon={Shield} color="text-blue-500" />
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>Fermer</Button>
        </div>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      )}

      {error && (
        <div className="px-4 py-6 text-sm text-red-600">Échec du chargement: {error}</div>
      )}

      {details && !loading && (
        <div className="p-4">
          {/* Best params */}
          {Boolean(entry.best_params_json) && (
            <div className="mb-4 rounded-lg border border-border bg-secondary/20 p-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">Paramètres optimaux</p>
              <ParamsDisplay params={entry.best_params_json} />
            </div>
          )}

          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="mb-4">
              {plotKeys.length > 0 && <TabsTrigger value="plots">Graphiques</TabsTrigger>}
              <TabsTrigger value="metrics">Métriques</TabsTrigger>
              {details.trade_performance.length > 0 && <TabsTrigger value="performance">Performance Trades</TabsTrigger>}
              {details.trade_ledger.length > 0 && <TabsTrigger value="ledger">Registre Trades</TabsTrigger>}
            </TabsList>

            {plotKeys.length > 0 && (
              <TabsContent value="plots" className="space-y-4">
                {plotKeys.map((key) => (
                  <Card key={key}>
                    <CardHeader className="pb-2 pt-3 px-4">
                      <CardTitle className="text-sm capitalize">{key.replace(/_/g, " ")}</CardTitle>
                    </CardHeader>
                    <CardContent className="px-2 pb-2">
                      <PlotlyChart figure={details.plots[key] as Parameters<typeof PlotlyChart>[0]["figure"]} />
                    </CardContent>
                  </Card>
                ))}
              </TabsContent>
            )}

            <TabsContent value="metrics">
              <Card>
                <CardContent className="p-0">
                  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-px bg-border">
                    {Object.entries(details.metrics).map(([k, v]) => (
                      <div key={k} className="bg-background p-3">
                        <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{k.replace(/_/g, " ")}</p>
                        <p className="font-mono text-sm font-semibold mt-0.5">
                          {typeof v === "number" ? formatNumber(v) : String(v ?? "—")}
                        </p>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            {details.trade_performance.length > 0 && (
              <TabsContent value="performance">
                <Card>
                  <CardContent className="p-0">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b bg-secondary/30">
                          <th className="px-4 py-2 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">Métrique</th>
                          <th className="px-4 py-2 text-right text-xs font-semibold uppercase tracking-wider text-muted-foreground">Valeur</th>
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

            {details.trade_ledger.length > 0 && (
              <TabsContent value="ledger">
                <Card>
                  <CardContent className="p-0 overflow-x-auto">
                    <table className="w-full text-xs whitespace-nowrap">
                      <thead>
                        <tr className="border-b bg-secondary/30">
                          {["Date", "Symbole", "Sens", "Prix Entrée", "Prix Sortie", "CMP", "Qté", "PnL Réalisé", "PnL Latent", "Notionnel", "Coût"].map((h) => (
                            <th key={h} className="px-3 py-2 text-left font-semibold uppercase tracking-wider text-muted-foreground">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {details.trade_ledger.map((row, i) => {
                          const pnl = Number(row.pnl_realise ?? row.pnl ?? 0)
                          const pnlLatent = Number(row.pnl_latent ?? 0)
                          return (
                            <tr key={i} className="border-b border-border/40 hover:bg-secondary/20">
                              <td className="px-3 py-1.5 font-mono">{String(row.timestamp ?? row.entry_time ?? "").slice(0, 10)}</td>
                              <td className="px-3 py-1.5 font-semibold">{String(row.symbol ?? "")}</td>
                              <td className="px-3 py-1.5">
                                <span className={cn("font-semibold", String(row.side ?? "").toUpperCase() === "BUY" ? "text-emerald-600" : "text-red-600")}>
                                  {String(row.side ?? "").toUpperCase() === "BUY" ? "ACHAT" : "VENTE"}
                                </span>
                              </td>
                              <td className="px-3 py-1.5 tabular-nums">{row.entry_price != null ? formatNumber(Number(row.entry_price)) : "—"}</td>
                              <td className="px-3 py-1.5 tabular-nums">{row.exit_price != null ? formatNumber(Number(row.exit_price)) : "—"}</td>
                              <td className="px-3 py-1.5 tabular-nums">{row.cmp != null ? formatNumber(Number(row.cmp)) : "—"}</td>
                              <td className="px-3 py-1.5 tabular-nums">{row.quantite != null ? formatNumber(Number(row.quantite)) : "—"}</td>
                              <td className={cn("px-3 py-1.5 tabular-nums font-semibold", pnl > 0 ? "text-emerald-600" : pnl < 0 ? "text-red-600" : "")}>{isFinite(pnl) ? formatNumber(pnl) : "—"}</td>
                              <td className={cn("px-3 py-1.5 tabular-nums font-semibold", pnlLatent > 0 ? "text-emerald-600" : pnlLatent < 0 ? "text-red-600" : "")}>{isFinite(pnlLatent) ? formatNumber(pnlLatent) : "—"}</td>
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

// ─── Symbol Leaderboard ───────────────────────────────────────

function SymbolLeaderboard({
  symbol,
  strategies,
  sortKey,
  onSortChange,
}: {
  symbol: string
  strategies: StrategyEntry[]
  sortKey: SortKey
  onSortChange: (k: SortKey) => void
}) {
  const [expandedKey, setExpandedKey] = useState<string | null>(null)

  const sorted = useMemo(() => sortEntries(strategies, sortKey), [strategies, sortKey])

  function rowKey(e: StrategyEntry) {
    return `${e.run_id}::${e.strategy_kind}::${e.rank ?? 0}`
  }

  return (
    <Card>
      <CardHeader className="pb-3 pt-4">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-base font-bold">{symbol} — Classement des stratégies</CardTitle>
            <p className="text-xs text-muted-foreground mt-0.5">{strategies.length} stratégie(s) • Cliquer une ligne pour voir les détails</p>
          </div>
          <div className="flex items-center gap-2">
            <ArrowUpDown className="h-3.5 w-3.5 text-muted-foreground" />
            <select
              className="rounded-md border border-border bg-background px-2 py-1.5 text-xs font-medium"
              value={sortKey}
              onChange={(e) => onSortChange(e.target.value as SortKey)}
            >
              {SORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-secondary/30">
                {["#", "Stratégie", "Horizon", "Return", "CAGR", "Sharpe", "Max DD", "Win %", "Trades", "PnL", "Opportunité", "Confiance", "Signal", "Paramètres", ""].map((h) => (
                  <th key={h} className="px-2.5 py-2.5 text-left text-[10px] font-bold uppercase tracking-wider text-muted-foreground whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((entry, idx) => {
                const key = rowKey(entry)
                const isExpanded = expandedKey === key
                return (
                  <Fragment key={key}>
                    <tr
                      className={cn(
                        "border-b border-border/50 transition-colors cursor-pointer",
                        isExpanded ? "bg-primary/5" : "hover:bg-secondary/40",
                        idx < 3 ? "font-medium" : ""
                      )}
                      onClick={() => setExpandedKey(isExpanded ? null : key)}
                    >
                      <td className="px-2.5 py-2.5">
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
                      <td className="px-2.5 py-2.5 font-semibold text-xs">{entry.strategy_kind}</td>
                      <td className="px-2.5 py-2.5"><HorizonBadge horizon={entry.horizon} /></td>
                      <td className="px-2.5 py-2.5"><ReturnCell value={entry.total_return} /></td>
                      <td className="px-2.5 py-2.5 tabular-nums text-xs">{entry.cagr != null ? formatPercent(entry.cagr) : "—"}</td>
                      <td className="px-2.5 py-2.5 tabular-nums text-xs">{entry.sharpe != null ? formatNumber(entry.sharpe) : "—"}</td>
                      <td className="px-2.5 py-2.5 tabular-nums text-xs text-red-600">{entry.max_drawdown != null ? formatPercent(entry.max_drawdown) : "—"}</td>
                      <td className="px-2.5 py-2.5 tabular-nums text-xs">{entry.win_pct != null ? formatPercent(entry.win_pct) : "—"}</td>
                      <td className="px-2.5 py-2.5 tabular-nums text-xs">{entry.n_fills ?? "—"}</td>
                      <td className="px-2.5 py-2.5 tabular-nums text-xs font-mono">{entry.pnl != null ? formatNumber(entry.pnl) : "—"}</td>
                      <td className="px-2.5 py-2.5">
                        {entry.opportunity_score != null ? (
                          <div className="flex items-center gap-1">
                            <div className="h-1.5 w-12 rounded-full bg-secondary overflow-hidden">
                              <div className="h-full rounded-full bg-amber-400" style={{ width: `${Math.min(100, entry.opportunity_score)}%` }} />
                            </div>
                            <span className="tabular-nums text-xs">{formatNumber(entry.opportunity_score, 1)}</span>
                          </div>
                        ) : <span className="text-muted-foreground text-xs">—</span>}
                      </td>
                      <td className="px-2.5 py-2.5">
                        {entry.confidence_score != null ? (
                          <div className="flex items-center gap-1">
                            <div className="h-1.5 w-12 rounded-full bg-secondary overflow-hidden">
                              <div className="h-full rounded-full bg-blue-400" style={{ width: `${Math.min(100, entry.confidence_score)}%` }} />
                            </div>
                            <span className="tabular-nums text-xs">{formatNumber(entry.confidence_score, 1)}</span>
                          </div>
                        ) : <span className="text-muted-foreground text-xs">—</span>}
                      </td>
                      <td className="px-2.5 py-2.5"><SignalChip value={entry.signal_today} /></td>
                      <td className="px-2.5 py-2.5 max-w-[200px]">
                        <ParamsDisplay params={entry.best_params_json} />
                      </td>
                      <td className="px-2.5 py-2.5 text-right">
                        {isExpanded
                          ? <ChevronDown className="h-4 w-4 text-muted-foreground ml-auto" />
                          : <ChevronRight className="h-4 w-4 text-muted-foreground ml-auto" />}
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr key={`${key}--detail`}>
                        <td colSpan={15} className="p-0">
                          <StrategyDetailPanel entry={entry} onClose={() => setExpandedKey(null)} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  )
}

// ─── Main Page ────────────────────────────────────────────────

export default function ResultsPage() {
  const [symbolMap, setSymbolMap] = useState<Map<string, SymbolEntry>>(new Map())
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const [search, setSearch] = useState("")
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [horizonFilter, setHorizonFilter] = useState<HorizonFilter>("all")
  const [sortKey, setSortKey] = useState<SortKey>("total_return")

  async function loadAll(showRefreshing = false) {
    if (showRefreshing) setRefreshing(true)
    else setLoading(true)
    try {
      const allRuns = await listRuns({ status: "succeeded", limit: 200 })

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
                map.set(sym, { symbol: sym, runCount: 0, strategies: [], bestReturn: null, bestSharpe: null, bestCagr: null })
              }
              map.get(sym)!.strategies.push(entry)
            }
          } catch { /* skip */ }
        })
      )

      for (const [, se] of map) {
        const runIds = new Set(se.strategies.map((s) => s.run_id))
        se.runCount = runIds.size
        const returns = se.strategies.map((s) => s.total_return).filter((v) => v != null && isFinite(Number(v))) as number[]
        const sharpes = se.strategies.map((s) => s.sharpe).filter((v) => v != null && isFinite(Number(v))) as number[]
        const cagrs = se.strategies.map((s) => s.cagr).filter((v) => v != null && isFinite(Number(v))) as number[]
        se.bestReturn = returns.length > 0 ? Math.max(...returns) : null
        se.bestSharpe = sharpes.length > 0 ? Math.max(...sharpes) : null
        se.bestCagr = cagrs.length > 0 ? Math.max(...cagrs) : null
      }

      setSymbolMap(map)
      if (!selectedSymbol && map.size > 0) setSelectedSymbol([...map.keys()][0])
    } catch (e) {
      toast.error(`Chargement échoué: ${e instanceof Error ? e.message : String(e)}`)
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

  // Filter strategies by horizon tab
  const visibleStrategies = useMemo(() => {
    if (!activeEntry) return []
    if (horizonFilter === "all") return activeEntry.strategies
    return activeEntry.strategies.filter((s) => s.horizon === horizonFilter)
  }, [activeEntry, horizonFilter])

  // Summary counts
  const totalSymbols = symbolMap.size
  const totalStrategies = [...symbolMap.values()].reduce((acc, s) => acc + s.strategies.length, 0)
  const totalRuns = useMemo(() => {
    const ids = new Set<string>()
    for (const s of symbolMap.values()) for (const st of s.strategies) if (st.run_id) ids.add(st.run_id)
    return ids.size
  }, [symbolMap])

  const horizonCounts = useMemo(() => {
    const counts: Record<string, number> = { all: 0, short: 0, medium: 0, long: 0 }
    if (!activeEntry) return counts
    counts.all = activeEntry.strategies.length
    for (const s of activeEntry.strategies) {
      const h = s.horizon ?? "unknown"
      if (h in counts) counts[h]++
    }
    return counts
  }, [activeEntry])

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Résultats Globaux</h1>
          <p className="text-sm text-muted-foreground">Performance agrégée de toutes les stratégies par action et horizon</p>
        </div>
        <Button variant="outline" size="sm" className="gap-1.5" onClick={() => loadAll(true)} disabled={refreshing}>
          <RefreshCw className={cn("h-3.5 w-3.5", refreshing && "animate-spin")} />
          Actualiser
        </Button>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Runs complétés", value: totalRuns },
          { label: "Actions uniques", value: totalSymbols },
          { label: "Stratégies testées", value: totalStrategies },
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

      {/* Horizon legend */}
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-xs text-muted-foreground font-medium">Horizons :</span>
        {(["short", "medium", "long"] as const).map((h) => (
          <div key={h} className="flex items-center gap-1.5 text-xs">
            <HorizonBadge horizon={h} />
            <span className="text-muted-foreground">{HORIZON_DETAIL[h]}</span>
          </div>
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
            <h3 className="font-semibold">Aucun résultat</h3>
            <p className="mt-1 text-sm text-muted-foreground">Lancez un backtest WFO pour voir les résultats ici.</p>
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
                  placeholder="Rechercher…"
                  className="pl-8 h-8 text-sm"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </div>
            </CardHeader>
            <CardContent className="p-0 pb-2">
              <div className="max-h-[600px] overflow-y-auto">
                {filteredSymbols.map((s) => (
                  <button
                    key={s.symbol}
                    onClick={() => setSelectedSymbol(s.symbol)}
                    className={cn(
                      "w-full text-left px-3 py-2.5 transition-colors flex items-center justify-between",
                      selectedSymbol === s.symbol
                        ? "bg-primary/10 border-l-2 border-primary"
                        : "hover:bg-secondary/50 border-l-2 border-transparent"
                    )}
                  >
                    <div>
                      <p className="font-semibold text-sm">{s.symbol}</p>
                      <p className="text-xs text-muted-foreground">
                        {s.strategies.length} stratégie{s.strategies.length > 1 ? "s" : ""} · {s.runCount} run{s.runCount > 1 ? "s" : ""}
                      </p>
                    </div>
                    <div className="text-right">
                      {s.bestReturn != null && (
                        <p className={cn("text-xs font-bold tabular-nums", s.bestReturn >= 0 ? "text-emerald-600" : "text-red-600")}>
                          {s.bestReturn >= 0 ? "+" : ""}{formatPercent(s.bestReturn)}
                        </p>
                      )}
                      {s.bestCagr != null && (
                        <p className="text-[10px] text-muted-foreground tabular-nums">
                          CAGR {s.bestCagr >= 0 ? "+" : ""}{formatPercent(s.bestCagr)}
                        </p>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Right: leaderboard with horizon tabs */}
          <div className="col-span-3 space-y-4">
            {activeEntry ? (
              <>
                {/* Horizon tabs */}
                <Tabs value={horizonFilter} onValueChange={(v) => setHorizonFilter(v as HorizonFilter)}>
                  <TabsList className="w-full justify-start">
                    <TabsTrigger value="all">
                      Tous
                      <span className="ml-1.5 rounded-full bg-secondary px-1.5 py-0.5 text-[10px] font-bold">{horizonCounts.all}</span>
                    </TabsTrigger>
                    <TabsTrigger value="short">
                      Court terme
                      <span className="ml-1.5 rounded-full bg-secondary px-1.5 py-0.5 text-[10px] font-bold">{horizonCounts.short}</span>
                    </TabsTrigger>
                    <TabsTrigger value="medium">
                      Moyen terme
                      <span className="ml-1.5 rounded-full bg-secondary px-1.5 py-0.5 text-[10px] font-bold">{horizonCounts.medium}</span>
                    </TabsTrigger>
                    <TabsTrigger value="long">
                      Long terme
                      <span className="ml-1.5 rounded-full bg-secondary px-1.5 py-0.5 text-[10px] font-bold">{horizonCounts.long}</span>
                    </TabsTrigger>
                  </TabsList>

                  {/* Horizon context bar */}
                  {horizonFilter !== "all" && (
                    <div className="mt-2 rounded-lg border border-border bg-secondary/30 px-3 py-2 text-xs text-muted-foreground flex items-center gap-2">
                      <Target className="h-3.5 w-3.5 shrink-0" />
                      <span><strong>{HORIZON_LABELS[horizonFilter]}</strong> — {HORIZON_DETAIL[horizonFilter]}</span>
                    </div>
                  )}

                  <TabsContent value={horizonFilter} className="mt-3">
                    {visibleStrategies.length === 0 ? (
                      <Card>
                        <CardContent className="py-12 text-center">
                          <p className="text-sm text-muted-foreground">
                            Aucune stratégie pour cet horizon. Lancez un run WFO avec l&apos;horizon &ldquo;{HORIZON_LABELS[horizonFilter] ?? horizonFilter}&rdquo;.
                          </p>
                        </CardContent>
                      </Card>
                    ) : (
                      <SymbolLeaderboard
                        symbol={activeEntry.symbol}
                        strategies={visibleStrategies}
                        sortKey={sortKey}
                        onSortChange={setSortKey}
                      />
                    )}
                  </TabsContent>
                </Tabs>
              </>
            ) : (
              <Card>
                <CardContent className="py-16 text-center">
                  <p className="text-sm text-muted-foreground">Sélectionnez une action pour voir son classement</p>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
