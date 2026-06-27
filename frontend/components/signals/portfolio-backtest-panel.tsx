"use client"

import { useEffect, useMemo, useState } from "react"
import { ArrowLeft, ChevronDown, Maximize2, Minimize2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { PlotlyChart } from "@/components/run/plotly-chart"
import { PriceSignalsChart } from "@/components/signals/price-signals-chart"
import { useMarketCatalog, useStockOhlcvHistory } from "@/hooks/use-api"
import { formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"
import {
  getPortfolioBacktestUniverse,
  runPortfolioBacktest,
  type PortfolioBacktestResult,
  type PortfolioBacktestTrade,
  type PortfolioBacktestUniverseSymbol,
} from "@/lib/api"

type Props = {
  horizon: string
}

const BACKTEST_VARIANT = "expanded"
const LEDGER_PAGE_SIZE = 200

function StatCard({
  label,
  value,
  tone,
}: {
  label: string
  value: string
  tone?: "pos" | "neg" | "neutral"
}) {
  return (
    <div className="claude-stat">
      <p className="lbl">{label}</p>
      <p
        className={`val ${
          tone === "pos"
            ? "text-emerald-600"
            : tone === "neg"
              ? "text-red-600"
              : ""
        }`}
      >
        {value}
      </p>
    </div>
  )
}

function buildEquityPlot(
  curve: Array<{ date: string; equity: number }>,
  initialCapital: number,
) {
  if (curve.length < 2) return null
  const dates = curve.map((p) => p.date)
  const returns = curve.map((p) => ((p.equity - initialCapital) / initialCapital) * 100)
  return {
    data: [
      {
        x: dates,
        y: returns,
        type: "scatter",
        mode: "lines",
        name: "Portfolio WFO",
        line: { color: "rgb(99,102,241)", width: 2 },
        fill: "tozeroy",
        fillcolor: "rgba(99,102,241,0.08)",
      },
    ],
    layout: {
      margin: { t: 16, b: 40, l: 52, r: 16 },
      yaxis: { ticksuffix: "%", gridcolor: "rgba(0,0,0,0.06)" },
      xaxis: { type: "date", gridcolor: "rgba(0,0,0,0.06)" },
      showlegend: false,
      plot_bgcolor: "transparent",
      paper_bgcolor: "transparent",
    },
  }
}

function buildStockEquityPlot(trades: PortfolioBacktestTrade[], symbol: string) {
  const symbolTrades = [...trades]
    .filter((t) => t.symbol === symbol && t.executed && t.close_date)
    .sort((a, b) => (a.close_date < b.close_date ? -1 : 1))
  if (symbolTrades.length < 2) return null
  let cumPnl = 0
  const points = symbolTrades.map((t) => {
    cumPnl += t.pnl_mad
    return { date: t.close_date, pnl: cumPnl }
  })
  const finalPnl = points[points.length - 1].pnl
  return {
    data: [
      {
        x: points.map((p) => p.date),
        y: points.map((p) => p.pnl),
        type: "scatter",
        mode: "lines",
        name: symbol,
        line: { color: finalPnl >= 0 ? "rgb(99,102,241)" : "rgb(239,68,68)", width: 2 },
        fill: "tozeroy",
        fillcolor:
          finalPnl >= 0 ? "rgba(99,102,241,0.08)" : "rgba(239,68,68,0.08)",
      },
    ],
    layout: {
      margin: { t: 16, b: 40, l: 72, r: 16 },
      yaxis: { ticksuffix: " MAD", gridcolor: "rgba(0,0,0,0.06)" },
      xaxis: { type: "date", gridcolor: "rgba(0,0,0,0.06)" },
      showlegend: false,
      plot_bgcolor: "transparent",
      paper_bgcolor: "transparent",
    },
  }
}

type SortKey = "open_date" | "pnl_return" | "pnl_mad"

export function PortfolioBacktestPanel({ horizon }: Props) {
  const [initialCapital, setInitialCapital] = useState(100_000)
  const [longOnly, setLongOnly] = useState(true)
  const [startDate, setStartDate] = useState("")
  const [endDate, setEndDate] = useState("")
  const [result, setResult] = useState<PortfolioBacktestResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fullscreen, setFullscreen] = useState(false)
  const [selectedStock, setSelectedStock] = useState<string | null>(null)

  // Universe of symbols that have qualifying WFO trades for this horizon/direction.
  const [universe, setUniverse] = useState<PortfolioBacktestUniverseSymbol[]>([])
  const [dateRange, setDateRange] = useState<{ min: string | null; max: string | null }>({
    min: null,
    max: null,
  })
  const [universeLoading, setUniverseLoading] = useState(false)
  const [universeError, setUniverseError] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [universeQuery, setUniverseQuery] = useState("")
  const [selectedKinds, setSelectedKinds] = useState<Set<string>>(new Set())

  // Trades ledger state
  const [ledgerSymbolFilter, setLedgerSymbolFilter] = useState<string>("__all__")
  const [ledgerSortKey, setLedgerSortKey] = useState<SortKey>("open_date")
  const [ledgerSortDir, setLedgerSortDir] = useState<1 | -1>(1)
  const [ledgerPage, setLedgerPage] = useState(1)

  const { data: catalog } = useMarketCatalog()
  const displayNameOf = useMemo(() => {
    const map = new Map<string, string>()
    for (const row of catalog ?? []) {
      if (row.display_name) map.set(row.symbol, row.display_name)
    }
    return map
  }, [catalog])

  const kindOf = useMemo(() => {
    const map = new Map<string, string>()
    for (const row of catalog ?? []) {
      const assetClass = row.asset_class ?? "equity"
      const assetType = (row.asset_type ?? "equity").toLowerCase()
      const region = (row.market_region ?? "").toLowerCase()
      let kind: string
      if (assetClass === "index") {
        kind = "Index"
      } else if (assetType === "equity") {
        if (region === "masi") kind = "MASI stocks"
        else if (region === "us") kind = "US stocks"
        else if (region === "european") kind = "European stocks"
        else if (region === "asian") kind = "Asian stocks"
        else kind = "Other stocks"
      } else {
        kind =
          assetType === "commodity" ? "Commodity"
          : assetType === "forex" ? "Forex"
          : assetType === "bond" ? "Bond"
          : assetType === "crypto" ? "Crypto"
          : "Other"
      }
      map.set(row.symbol, kind)
    }
    return map
  }, [catalog])

  // OHLCV history for selected stock — null key when in list mode so SWR skips the fetch
  const { data: ohlcvData, isLoading: ohlcvLoading } = useStockOhlcvHistory(selectedStock)

  // (Re)load the tradeable universe when the horizon or direction changes.
  // Clear stale results immediately so the previous direction's data is never shown.
  useEffect(() => {
    let cancelled = false
    setResult(null)
    setError(null)
    setSelectedStock(null)
    setLedgerSymbolFilter("__all__")
    setUniverseLoading(true)
    getPortfolioBacktestUniverse({ horizon, variant: BACKTEST_VARIANT, long_only: longOnly })
      .then((res) => {
        if (cancelled) return
        // Defensive frontend dedupe: keep first occurrence of each symbol
        const seen = new Set<string>()
        const deduped = res.symbols.filter((r) => {
          if (seen.has(r.symbol)) return false
          seen.add(r.symbol)
          return true
        })
        setUniverse(deduped)
        setSelected(new Set(deduped.map((r) => r.symbol)))
        setDateRange(res.date_range)
        // Pre-fill date inputs with available range if not set
        if (!startDate && res.date_range.min) setStartDate(res.date_range.min)
        if (!endDate && res.date_range.max) setEndDate(res.date_range.max)
      })
      .catch(() => {
        if (cancelled) return
        setUniverse([])
        setSelected(new Set())
        setDateRange({ min: null, max: null })
      })
      .finally(() => {
        if (!cancelled) setUniverseLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [horizon, longOnly])

  // Fullscreen: Escape key exits; lock body scroll while active
  useEffect(() => {
    if (!fullscreen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setFullscreen(false)
    }
    document.body.style.overflow = "hidden"
    window.addEventListener("keydown", onKey)
    return () => {
      document.body.style.overflow = ""
      window.removeEventListener("keydown", onKey)
    }
  }, [fullscreen])

  const filteredUniverse = useMemo(() => {
    const q = universeQuery.trim().toLowerCase()
    if (!q) return universe
    return universe.filter(
      (r) =>
        r.symbol.toLowerCase().includes(q) ||
        (displayNameOf.get(r.symbol) ?? "").toLowerCase().includes(q),
    )
  }, [universe, universeQuery, displayNameOf])

  const allSelected = universe.length > 0 && selected.size === universe.length

  function toggleSymbol(symbol: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(symbol)) next.delete(symbol)
      else next.add(symbol)
      return next
    })
  }

  function selectAll() {
    setSelected(new Set(universe.map((r) => r.symbol)))
  }

  function clearAll() {
    setSelected(new Set())
  }

  function openStockDetail(symbol: string) {
    setSelectedStock(symbol)
    setLedgerSymbolFilter(symbol)
    setLedgerPage(1)
  }

  function closeStockDetail() {
    setSelectedStock(null)
    setLedgerSymbolFilter("__all__")
    setLedgerPage(1)
  }

  async function handleRun() {
    setLoading(true)
    setError(null)
    setLedgerPage(1)
    setLedgerSymbolFilter("__all__")
    setSelectedStock(null)
    try {
      // An explicit full selection is equivalent to "all" on the backend.
      const symbols = allSelected ? [] : Array.from(selected)
      const res = await runPortfolioBacktest({
        symbols,
        horizon,
        variant: BACKTEST_VARIANT,
        initial_capital: initialCapital,
        take_profit_pct: 0.05,
        kelly_multiplier: 0.5,
        long_only: longOnly,
        start_date: startDate || undefined,
        end_date: endDate || undefined,
      })
      setResult(res)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Backtest failed")
    } finally {
      setLoading(false)
    }
  }

  const m = result?.metrics ?? {}
  const equityPlot = result ? buildEquityPlot(result.equity_curve, initialCapital) : null
  const totalReturnTone =
    m.total_return != null ? (m.total_return >= 0 ? "pos" : "neg") : "neutral"

  const universeLabel = universeLoading
    ? "Chargement…"
    : universe.length === 0
      ? "Aucun titre éligible"
      : allSelected
        ? `Tous les titres (${universe.length})`
        : `${selected.size} / ${universe.length} titres`

  // Trades ledger computation
  const ledgerSymbols = useMemo(() => {
    if (!result?.trades) return []
    return Array.from(new Set(result.trades.map((t) => t.symbol))).sort()
  }, [result])

  const filteredTrades = useMemo((): PortfolioBacktestTrade[] => {
    if (!result?.trades) return []
    let trades = result.trades
    if (ledgerSymbolFilter !== "__all__") {
      trades = trades.filter((t) => t.symbol === ledgerSymbolFilter)
    }
    return [...trades].sort((a, b) => {
      let cmp = 0
      if (ledgerSortKey === "open_date") {
        cmp = a.open_date < b.open_date ? -1 : a.open_date > b.open_date ? 1 : 0
      } else if (ledgerSortKey === "pnl_return") {
        cmp = a.pnl_return - b.pnl_return
      } else if (ledgerSortKey === "pnl_mad") {
        cmp = a.pnl_mad - b.pnl_mad
      }
      return cmp * ledgerSortDir
    })
  }, [result, ledgerSymbolFilter, ledgerSortKey, ledgerSortDir])

  const ledgerVisible = filteredTrades.slice(0, ledgerPage * LEDGER_PAGE_SIZE)
  const hasMoreLedger = filteredTrades.length > ledgerVisible.length

  function toggleLedgerSort(key: SortKey) {
    if (ledgerSortKey === key) {
      setLedgerSortDir((d) => (d === 1 ? -1 : 1))
    } else {
      setLedgerSortKey(key)
      setLedgerSortDir(-1) // default: highest first
    }
    setLedgerPage(1)
  }

  function SortHeader({
    col,
    label,
    className,
  }: {
    col: SortKey
    label: string
    className?: string
  }) {
    const active = ledgerSortKey === col
    return (
      <th
        className={`cursor-pointer select-none ${className ?? ""}`}
        onClick={() => toggleLedgerSort(col)}
      >
        {label}
        {active ? (ledgerSortDir === 1 ? " ↑" : " ↓") : ""}
      </th>
    )
  }

  // Per-stock detail data
  const stockStats = useMemo(
    () =>
      selectedStock && result
        ? (result.per_symbol.find((s) => s.symbol === selectedStock) ?? null)
        : null,
    [selectedStock, result],
  )

  const stockTotalPnl = useMemo(() => {
    if (!selectedStock || !result) return 0
    return (result.trades ?? [])
      .filter((t) => t.symbol === selectedStock && t.executed)
      .reduce((sum, t) => sum + t.pnl_mad, 0)
  }, [selectedStock, result])

  const stockEquityPlot = useMemo(
    () =>
      selectedStock && result ? buildStockEquityPlot(result.trades ?? [], selectedStock) : null,
    [selectedStock, result],
  )

  const stockTradeMarkers = useMemo((): Array<Record<string, unknown>> => {
    if (!selectedStock || !result) return []
    const rows: Array<Record<string, unknown>> = []
    for (const t of (result.trades ?? []).filter((t) => t.symbol === selectedStock)) {
      rows.push({ date: t.open_date, marker_label: t.direction > 0 ? "Achat" : "Short" })
      rows.push({ date: t.close_date, marker_label: t.direction > 0 ? "Vente" : "Cover" })
    }
    return rows
  }, [selectedStock, result])

  const ohlcvBars = ohlcvData?.bars ?? []

  return (
    <div
      className={cn(
        "space-y-4",
        fullscreen && "fixed inset-0 z-50 overflow-y-auto bg-background p-4",
      )}
    >
      {/* Config card */}
      <Card className="claude-card">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm">Backtest Portefeuille — Signaux WFO</CardTitle>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 gap-1.5 px-2 text-xs"
              onClick={() => setFullscreen((v) => !v)}
            >
              {fullscreen ? (
                <Minimize2 className="h-3.5 w-3.5" />
              ) : (
                <Maximize2 className="h-3.5 w-3.5" />
              )}
              {fullscreen ? "Quitter le plein écran" : "Plein écran"}
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Capital initial (MAD)</Label>
              <Input
                type="number"
                value={initialCapital}
                onChange={(e) => setInitialCapital(Number(e.target.value))}
                className="h-8 w-40 font-mono text-xs"
              />
            </div>

            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Sens des trades</Label>
              <ToggleGroup
                type="single"
                value={longOnly ? "long" : "both"}
                onValueChange={(v) => {
                  if (v) setLongOnly(v === "long")
                }}
                variant="outline"
                size="sm"
                className="h-8"
              >
                <ToggleGroupItem value="long" className="px-3 text-xs">
                  Long only
                </ToggleGroupItem>
                <ToggleGroupItem value="both" className="px-3 text-xs">
                  Long &amp; Short
                </ToggleGroupItem>
              </ToggleGroup>
            </div>

            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Période — Début</Label>
              <Input
                type="date"
                value={startDate}
                min={dateRange.min ?? undefined}
                max={dateRange.max ?? undefined}
                onChange={(e) => setStartDate(e.target.value)}
                className="h-8 w-36 font-mono text-xs"
              />
            </div>

            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Période — Fin</Label>
              <Input
                type="date"
                value={endDate}
                min={dateRange.min ?? undefined}
                max={dateRange.max ?? undefined}
                onChange={(e) => setEndDate(e.target.value)}
                className="h-8 w-36 font-mono text-xs"
              />
            </div>

            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Univers</Label>
              <Popover>
                <PopoverTrigger asChild>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 w-56 justify-between font-normal"
                    disabled={universeLoading || universe.length === 0}
                  >
                    <span className="truncate text-xs">{universeLabel}</span>
                    <ChevronDown className="h-3.5 w-3.5 opacity-60" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-72 p-0" align="start">
                  <div className="border-b border-line p-2">
                    <Input
                      value={universeQuery}
                      onChange={(e) => setUniverseQuery(e.target.value)}
                      placeholder="Rechercher un titre…"
                      className="h-7 text-xs"
                    />
                    <div className="mt-2 flex items-center justify-between text-[11px]">
                      <span className="text-muted-foreground">
                        {selected.size} sélectionné{selected.size > 1 ? "s" : ""}
                      </span>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          onClick={selectAll}
                          className="text-primary hover:underline"
                        >
                          Tout
                        </button>
                        <button
                          type="button"
                          onClick={clearAll}
                          className="text-muted-foreground hover:underline"
                        >
                          Aucun
                        </button>
                      </div>
                    </div>
                  </div>
                  <ScrollArea className="h-64">
                    <div className="p-1">
                      {filteredUniverse.length === 0 ? (
                        <p className="px-2 py-4 text-center text-xs text-muted-foreground">
                          Aucun titre.
                        </p>
                      ) : (
                        filteredUniverse.map((row) => (
                          <label
                            key={row.symbol}
                            className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 hover:bg-bg2"
                          >
                            <Checkbox
                              checked={selected.has(row.symbol)}
                              onCheckedChange={() => toggleSymbol(row.symbol)}
                            />
                            <span className="font-mono text-xs font-medium">{row.symbol}</span>
                            <span className="flex-1 truncate text-[11px] text-muted-foreground">
                              {displayNameOf.get(row.symbol) ?? ""}
                            </span>
                            <span className="font-mono text-[10px] text-muted-foreground">
                              {longOnly
                                ? `${row.n_long} L`
                                : `${row.n_long}L/${row.n_short}S`}
                            </span>
                          </label>
                        ))
                      )}
                    </div>
                  </ScrollArea>
                </PopoverContent>
              </Popover>
            </div>

            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="rounded border border-line bg-bg2 px-1.5 py-0.5">½-Kelly</span>
              <span className="rounded border border-line bg-bg2 px-1.5 py-0.5">TP 5%</span>
              <span className="rounded border border-line bg-bg2 px-1.5 py-0.5">OOS</span>
            </div>
            <Button
              type="button"
              size="sm"
              onClick={handleRun}
              disabled={loading || selected.size === 0}
              className="ml-auto"
            >
              {loading ? "Calcul..." : "Lancer"}
            </Button>
          </div>
          {selected.size === 0 && !universeLoading && universe.length > 0 ? (
            <p className="mt-2 text-xs text-muted-foreground">
              Sélectionnez au moins un titre dans l'univers.
            </p>
          ) : null}
          {error ? (
            <p className="mt-2 text-xs text-destructive">{error}</p>
          ) : null}
        </CardContent>
      </Card>

      {loading ? <Skeleton className="h-48 rounded-xl" /> : null}

      {result && !loading ? (
        <>
          {result.warnings.length > 0 ? (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {result.warnings.join(" ")}
            </div>
          ) : null}

          {result.equity_curve.length > 0 ? (
            <>
              {result.period?.start ? (
                <p className="text-[11px] text-muted-foreground">
                  Période réalisée :{" "}
                  <span className="font-mono">
                    {result.period.start} → {result.period.end ?? "…"}
                  </span>
                </p>
              ) : null}

              {/* ── Per-stock detail view ── */}
              {selectedStock ? (
                <>
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 gap-1.5 px-2 text-xs"
                      onClick={closeStockDetail}
                    >
                      <ArrowLeft className="h-3.5 w-3.5" />
                      Retour
                    </Button>
                    <span className="font-mono text-sm font-semibold">{selectedStock}</span>
                    {stockStats && !longOnly ? (
                      <span className="text-[11px] text-muted-foreground">
                        {stockStats.n_long ?? 0}L / {stockStats.n_short ?? 0}S
                      </span>
                    ) : null}
                  </div>

                  {/* Per-stock metrics row */}
                  {stockStats ? (
                    <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
                      <StatCard label="Trades" value={String(stockStats.n_trades)} />
                      <StatCard
                        label="Win Rate"
                        value={`${stockStats.win_rate.toFixed(1)}%`}
                        tone={stockStats.win_rate >= 50 ? "pos" : "neg"}
                      />
                      <StatCard
                        label="Moy. gain"
                        value={`+${stockStats.avg_win_pct.toFixed(2)}%`}
                        tone="pos"
                      />
                      <StatCard
                        label="Moy. perte"
                        value={`${stockStats.avg_loss_pct.toFixed(2)}%`}
                        tone="neg"
                      />
                      <StatCard
                        label="½-Kelly"
                        value={`${stockStats.kelly_pct.toFixed(1)}%`}
                      />
                      <StatCard
                        label="PnL total"
                        value={`${stockTotalPnl >= 0 ? "+" : ""}${stockTotalPnl.toLocaleString("fr-FR", { maximumFractionDigits: 0 })} MAD`}
                        tone={stockTotalPnl >= 0 ? "pos" : "neg"}
                      />
                    </div>
                  ) : null}

                  {/* Per-stock equity curve */}
                  {stockEquityPlot ? (
                    <Card className="claude-card">
                      <CardHeader className="pb-1">
                        <CardTitle className="text-sm">
                          PnL réalisé cumulé — {selectedStock}
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="bt-chart">
                        <PlotlyChart figure={stockEquityPlot as never} />
                      </CardContent>
                    </Card>
                  ) : null}

                  {/* Price chart with trade markers */}
                  <Card className="claude-card">
                    <CardHeader className="pb-1">
                      <CardTitle className="text-sm">
                        Graphique de prix — {selectedStock}
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      {ohlcvLoading ? (
                        <Skeleton className="h-[360px] rounded" />
                      ) : ohlcvBars.length === 0 ? (
                        <p className="p-4 text-sm text-muted-foreground">
                          Données de prix indisponibles pour {selectedStock}.
                        </p>
                      ) : (
                        <PriceSignalsChart
                          dates={ohlcvBars.map((b) => b.date)}
                          open={ohlcvBars.map((b) => b.open ?? null)}
                          high={ohlcvBars.map((b) => b.high ?? null)}
                          low={ohlcvBars.map((b) => b.low ?? null)}
                          close={ohlcvBars.map((b) => b.close ?? null)}
                          position={null}
                          tradeMarkers={stockTradeMarkers}
                          height={360}
                        />
                      )}
                    </CardContent>
                  </Card>

                  {/* Per-stock filtered trades ledger */}
                  {filteredTrades.length > 0 ? (
                    <Card className="claude-card">
                      <CardHeader className="pb-1">
                        <div className="flex items-center justify-between">
                          <CardTitle className="text-sm">
                            Trades — {selectedStock}
                          </CardTitle>
                          {result.trades_truncated ? (
                            <span className="text-[11px] text-amber-600">
                              Limité à 2000 trades
                            </span>
                          ) : null}
                        </div>
                      </CardHeader>
                      <CardContent>
                        <div className="overflow-x-auto rounded-md border border-line">
                          <table className="claude-table">
                            <thead>
                              <tr>
                                <th>Sens</th>
                                <SortHeader col="open_date" label="Ouverture" className="r" />
                                <th className="r">Clôture</th>
                                <th className="r">Prix ouv.</th>
                                <th className="r">Prix clôt.</th>
                                <SortHeader col="pnl_return" label="Rendement" className="r" />
                                <th className="r">TP</th>
                                <th className="r">Capital engagé</th>
                                <SortHeader col="pnl_mad" label="Gain/Perte" className="r" />
                              </tr>
                            </thead>
                            <tbody>
                              {ledgerVisible.map((t, i) => {
                                const isLong = t.direction > 0
                                const notExecuted = !t.executed
                                const pnlPos = t.pnl_mad >= 0
                                return (
                                  <tr
                                    key={`${t.symbol}-${t.open_date}-${i}`}
                                    className={notExecuted ? "opacity-50" : ""}
                                  >
                                    <td>
                                      <span
                                        className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                                          isLong
                                            ? "bg-emerald-100 text-emerald-700"
                                            : "bg-red-100 text-red-700"
                                        }`}
                                      >
                                        {isLong ? "Long" : "Short"}
                                      </span>
                                    </td>
                                    <td className="r font-mono text-[11px]">{t.open_date}</td>
                                    <td className="r font-mono text-[11px]">{t.close_date}</td>
                                    <td className="r font-mono text-[11px]">
                                      {t.open_price.toFixed(2)}
                                    </td>
                                    <td className="r font-mono text-[11px]">
                                      {t.close_price.toFixed(2)}
                                    </td>
                                    <td
                                      className={`r font-mono text-[11px] ${
                                        t.pnl_return >= 0 ? "text-emerald-600" : "text-red-600"
                                      }`}
                                    >
                                      {t.pnl_return >= 0 ? "+" : ""}
                                      {(t.pnl_return * 100).toFixed(2)}%
                                    </td>
                                    <td className="r">
                                      {t.tp_applied ? (
                                        <span className="rounded bg-amber-100 px-1 py-0.5 text-[10px] text-amber-700">
                                          TP
                                        </span>
                                      ) : null}
                                    </td>
                                    <td className="r font-mono text-[11px]">
                                      {notExecuted ? (
                                        <span className="rounded bg-muted px-1 py-0.5 text-[10px] text-muted-foreground">
                                          Capital épuisé
                                        </span>
                                      ) : (
                                        `${t.position_size.toLocaleString("fr-FR", {
                                          maximumFractionDigits: 0,
                                        })} MAD`
                                      )}
                                    </td>
                                    <td
                                      className={`r font-mono text-[11px] font-medium ${
                                        notExecuted
                                          ? "text-muted-foreground"
                                          : pnlPos
                                            ? "text-emerald-600"
                                            : "text-red-600"
                                      }`}
                                    >
                                      {notExecuted
                                        ? "—"
                                        : `${pnlPos ? "+" : ""}${t.pnl_mad.toLocaleString("fr-FR", {
                                            maximumFractionDigits: 0,
                                          })} MAD`}
                                    </td>
                                  </tr>
                                )
                              })}
                            </tbody>
                          </table>
                        </div>
                        <div className="mt-2 flex items-center justify-between text-[11px] text-muted-foreground">
                          <span>
                            {filteredTrades.length} trade{filteredTrades.length > 1 ? "s" : ""}
                          </span>
                          {hasMoreLedger ? (
                            <button
                              type="button"
                              className="text-primary hover:underline"
                              onClick={() => setLedgerPage((p) => p + 1)}
                            >
                              Voir plus ({filteredTrades.length - ledgerVisible.length} restants)
                            </button>
                          ) : null}
                        </div>
                      </CardContent>
                    </Card>
                  ) : null}
                </>
              ) : (
                /* ── List mode ── */
                <>
                  {/* Global KPI rows — Issue 1: Tailwind grid replaces .kpi4 */}
                  <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                    <StatCard
                      label="Rendement total"
                      value={
                        m.total_return != null
                          ? `${m.total_return >= 0 ? "+" : ""}${m.total_return.toFixed(2)}%`
                          : "--"
                      }
                      tone={totalReturnTone}
                    />
                    <StatCard
                      label="CAGR"
                      value={
                        m.cagr != null
                          ? `${m.cagr >= 0 ? "+" : ""}${m.cagr.toFixed(2)}%`
                          : "--"
                      }
                    />
                    <StatCard
                      label="Sharpe"
                      value={m.sharpe != null ? formatNumber(m.sharpe, 2) : "--"}
                    />
                    <StatCard
                      label="Max Drawdown"
                      value={m.max_drawdown != null ? `-${m.max_drawdown.toFixed(2)}%` : "--"}
                      tone="neg"
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                    <StatCard
                      label="Capital final"
                      value={
                        m.final_equity != null
                          ? `${m.final_equity.toLocaleString("fr-FR", { maximumFractionDigits: 0 })} MAD`
                          : "--"
                      }
                    />
                    <StatCard
                      label="Titres qualifiés"
                      value={String(result.n_symbols_qualified)}
                    />
                    <StatCard label="Trades total" value={String(m.n_trades ?? "--")} />
                    <StatCard
                      label="TP déclenché"
                      value={m.tp_applied_pct != null ? `${m.tp_applied_pct}%` : "--"}
                    />
                  </div>

                  {/* Global equity curve */}
                  <Card className="claude-card">
                    <CardHeader className="pb-1">
                      <CardTitle className="text-sm">
                        Courbe d'équité (rendement cumulé)
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="bt-chart">
                      {equityPlot ? (
                        <PlotlyChart figure={equityPlot as never} />
                      ) : (
                        <p className="p-4 text-sm text-muted-foreground">
                          Pas assez de données pour le graphique.
                        </p>
                      )}
                    </CardContent>
                  </Card>

                  {/* Par titre — click opens per-stock detail */}
                  {result.per_symbol.length > 0 ? (
                    <Card className="claude-card">
                      <CardHeader className="pb-1">
                        <CardTitle className="text-sm">Par titre</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <div className="overflow-x-auto rounded-md border border-line">
                          <table className="claude-table">
                            <thead>
                              <tr>
                                <th>Ticker</th>
                                <th className="r">½-Kelly</th>
                                <th className="r">Trades</th>
                                {!longOnly ? <th className="r">Long / Short</th> : null}
                                <th className="r">Win Rate</th>
                                <th className="r">Moy. gain</th>
                                <th className="r">Moy. perte</th>
                              </tr>
                            </thead>
                            <tbody>
                              {result.per_symbol.map((s, i) => (
                                <tr
                                  key={`${s.symbol}-${i}`}
                                  className="cursor-pointer hover:bg-bg2"
                                  onClick={() => openStockDetail(s.symbol)}
                                >
                                  <td className="font-mono font-medium">{s.symbol}</td>
                                  <td className="r font-mono">{s.kelly_pct.toFixed(1)}%</td>
                                  <td className="r font-mono">{s.n_trades}</td>
                                  {!longOnly ? (
                                    <td className="r font-mono text-muted-foreground">
                                      {s.n_long ?? 0} / {s.n_short ?? 0}
                                    </td>
                                  ) : null}
                                  <td className="r font-mono">{s.win_rate.toFixed(1)}%</td>
                                  <td className="r font-mono text-emerald-600">
                                    +{s.avg_win_pct.toFixed(2)}%
                                  </td>
                                  <td className="r font-mono text-red-600">
                                    {s.avg_loss_pct.toFixed(2)}%
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                        <p className="mt-1 text-[11px] text-muted-foreground">
                          Cliquez sur un titre pour voir son détail.
                        </p>
                      </CardContent>
                    </Card>
                  ) : null}

                  {/* Global trades ledger with symbol filter dropdown */}
                  {result.trades && result.trades.length > 0 ? (
                    <Card className="claude-card">
                      <CardHeader className="pb-1">
                        <div className="flex items-center justify-between">
                          <CardTitle className="text-sm">Liste des trades</CardTitle>
                          <div className="flex items-center gap-2">
                            {result.trades_truncated ? (
                              <span className="text-[11px] text-amber-600">
                                Limité à 2000 trades
                              </span>
                            ) : null}
                            <select
                              className="h-7 rounded border border-line bg-bg px-2 text-xs font-normal"
                              value={ledgerSymbolFilter}
                              onChange={(e) => {
                                setLedgerSymbolFilter(e.target.value)
                                setLedgerPage(1)
                              }}
                            >
                              <option value="__all__">Tous les titres</option>
                              {ledgerSymbols.map((sym) => (
                                <option key={sym} value={sym}>
                                  {sym}
                                </option>
                              ))}
                            </select>
                            {ledgerSymbolFilter !== "__all__" ? (
                              <button
                                type="button"
                                className="text-[11px] text-muted-foreground hover:underline"
                                onClick={() => {
                                  setLedgerSymbolFilter("__all__")
                                  setLedgerPage(1)
                                }}
                              >
                                Effacer
                              </button>
                            ) : null}
                          </div>
                        </div>
                      </CardHeader>
                      <CardContent>
                        <div className="overflow-x-auto rounded-md border border-line">
                          <table className="claude-table">
                            <thead>
                              <tr>
                                <th>Ticker</th>
                                <th>Sens</th>
                                <SortHeader col="open_date" label="Ouverture" className="r" />
                                <th className="r">Clôture</th>
                                <th className="r">Prix ouv.</th>
                                <th className="r">Prix clôt.</th>
                                <SortHeader col="pnl_return" label="Rendement" className="r" />
                                <th className="r">TP</th>
                                <th className="r">Capital engagé</th>
                                <SortHeader col="pnl_mad" label="Gain/Perte" className="r" />
                              </tr>
                            </thead>
                            <tbody>
                              {ledgerVisible.map((t, i) => {
                                const isLong = t.direction > 0
                                const notExecuted = !t.executed
                                const pnlPos = t.pnl_mad >= 0
                                return (
                                  <tr
                                    key={`${t.symbol}-${t.open_date}-${i}`}
                                    className={notExecuted ? "opacity-50" : ""}
                                  >
                                    <td className="font-mono font-medium">{t.symbol}</td>
                                    <td>
                                      <span
                                        className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                                          isLong
                                            ? "bg-emerald-100 text-emerald-700"
                                            : "bg-red-100 text-red-700"
                                        }`}
                                      >
                                        {isLong ? "Long" : "Short"}
                                      </span>
                                    </td>
                                    <td className="r font-mono text-[11px]">{t.open_date}</td>
                                    <td className="r font-mono text-[11px]">{t.close_date}</td>
                                    <td className="r font-mono text-[11px]">
                                      {t.open_price.toFixed(2)}
                                    </td>
                                    <td className="r font-mono text-[11px]">
                                      {t.close_price.toFixed(2)}
                                    </td>
                                    <td
                                      className={`r font-mono text-[11px] ${
                                        t.pnl_return >= 0 ? "text-emerald-600" : "text-red-600"
                                      }`}
                                    >
                                      {t.pnl_return >= 0 ? "+" : ""}
                                      {(t.pnl_return * 100).toFixed(2)}%
                                    </td>
                                    <td className="r">
                                      {t.tp_applied ? (
                                        <span className="rounded bg-amber-100 px-1 py-0.5 text-[10px] text-amber-700">
                                          TP
                                        </span>
                                      ) : null}
                                    </td>
                                    <td className="r font-mono text-[11px]">
                                      {notExecuted ? (
                                        <span className="rounded bg-muted px-1 py-0.5 text-[10px] text-muted-foreground">
                                          Capital épuisé
                                        </span>
                                      ) : (
                                        `${t.position_size.toLocaleString("fr-FR", {
                                          maximumFractionDigits: 0,
                                        })} MAD`
                                      )}
                                    </td>
                                    <td
                                      className={`r font-mono text-[11px] font-medium ${
                                        notExecuted
                                          ? "text-muted-foreground"
                                          : pnlPos
                                            ? "text-emerald-600"
                                            : "text-red-600"
                                      }`}
                                    >
                                      {notExecuted
                                        ? "—"
                                        : `${pnlPos ? "+" : ""}${t.pnl_mad.toLocaleString("fr-FR", {
                                            maximumFractionDigits: 0,
                                          })} MAD`}
                                    </td>
                                  </tr>
                                )
                              })}
                            </tbody>
                          </table>
                        </div>
                        <div className="mt-2 flex items-center justify-between text-[11px] text-muted-foreground">
                          <span>
                            {filteredTrades.length} trade{filteredTrades.length > 1 ? "s" : ""}
                            {ledgerSymbolFilter !== "__all__" ? ` — ${ledgerSymbolFilter}` : ""}
                          </span>
                          {hasMoreLedger ? (
                            <button
                              type="button"
                              className="text-primary hover:underline"
                              onClick={() => setLedgerPage((p) => p + 1)}
                            >
                              Voir plus ({filteredTrades.length - ledgerVisible.length} restants)
                            </button>
                          ) : null}
                        </div>
                      </CardContent>
                    </Card>
                  ) : null}
                </>
              )}
            </>
          ) : null}
        </>
      ) : null}
    </div>
  )
}
