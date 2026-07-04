"use client"

import { useEffect, useMemo, useRef, useState } from "react"
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
import { useMarketCatalog, useStockOhlcvHistory } from "@/hooks/use-api"
import { formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"
import {
  getPortfolioBacktestUniverse,
  runPortfolioBacktest,
  type PortfolioBacktestBenchmark,
  type PortfolioBacktestLedgerRow,
  type PortfolioBacktestResult,
  type PortfolioBacktestTrade,
  type PortfolioBacktestUniverseSymbol,
} from "@/lib/api"

type Props = {
  horizon: string
}

const LEDGER_PAGE_SIZE = 200

function StatCard({
  label,
  value,
  tone,
  title,
}: {
  label: string
  value: string
  tone?: "pos" | "neg" | "neutral"
  title?: string
}) {
  return (
    <div className="claude-stat" title={title}>
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
  benchmark: PortfolioBacktestBenchmark | null | undefined,
  initialCapital: number,
) {
  if (curve.length < 2) return null
  const toPct = (equity: number) => ((equity - initialCapital) / initialCapital) * 100
  const data: Array<Record<string, unknown>> = [
    {
      x: curve.map((p) => p.date),
      y: curve.map((p) => toPct(p.equity)),
      type: "scatter",
      mode: "lines",
      name: "Portefeuille (modèle)",
      line: { color: "rgb(99,102,241)", width: 2 },
      fill: "tozeroy",
      fillcolor: "rgba(99,102,241,0.08)",
      hovertemplate: "%{x|%d/%m/%Y} — %{y:.2f}%<extra>Portefeuille</extra>",
    },
  ]
  if (benchmark && benchmark.curve.length >= 2) {
    data.push({
      x: benchmark.curve.map((p) => p.date),
      y: benchmark.curve.map((p) => toPct(p.equity)),
      type: "scatter",
      mode: "lines",
      name: "MASI (achat-conservation)",
      line: { color: "rgb(148,163,184)", width: 1.5 },
      hovertemplate: "%{x|%d/%m/%Y} — %{y:.2f}%<extra>MASI</extra>",
    })
  }
  return {
    data,
    layout: {
      margin: { t: 16, b: 40, l: 52, r: 16 },
      yaxis: { ticksuffix: "%", gridcolor: "rgba(0,0,0,0.06)" },
      xaxis: { type: "date", gridcolor: "rgba(0,0,0,0.06)" },
      showlegend: true,
      legend: { orientation: "h", x: 0, y: 1.08, font: { size: 11 } },
      plot_bgcolor: "transparent",
      paper_bgcolor: "transparent",
    },
  }
}

function shiftDate(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

function buildStockPricePlot(
  bars: Array<{ date: string; close?: number | null }>,
  trades: PortfolioBacktestTrade[],
  symbol: string,
  period: { start: string | null; end: string | null } | undefined,
) {
  const executed = trades.filter((t) => t.symbol === symbol && t.executed)
  const tradeDates = executed.flatMap((t) => [t.open_date, t.close_date]).filter(Boolean)
  const rawStart = period?.start ?? (tradeDates.length ? tradeDates.reduce((a, b) => (a < b ? a : b)) : null)
  const rawEnd = period?.end ?? (tradeDates.length ? tradeDates.reduce((a, b) => (a > b ? a : b)) : null)
  const clipStart = rawStart ? shiftDate(rawStart, -45) : null
  const clipEnd = rawEnd ? shiftDate(rawEnd, 45) : null

  const clipped = bars.filter(
    (b) =>
      b.close != null &&
      (!clipStart || b.date >= clipStart) &&
      (!clipEnd || b.date <= clipEnd),
  )
  if (clipped.length < 2) return null

  const data: Array<Record<string, unknown>> = [
    {
      x: clipped.map((b) => b.date),
      y: clipped.map((b) => b.close),
      type: "scatter",
      mode: "lines",
      name: "Clôture",
      line: { color: "rgb(100,116,139)", width: 1.5 },
      hovertemplate: "%{x|%d/%m/%Y} — %{y:.2f}<extra>Clôture</extra>",
    },
  ]

  // One semi-transparent segment per trade, colored by realized PnL.
  for (const t of executed) {
    const win = t.pnl_mad >= 0
    const hover =
      `${t.open_date} → ${t.close_date}<br>` +
      `${t.open_price.toFixed(2)} → ${t.close_price.toFixed(2)}<br>` +
      `Rendement : ${t.pnl_return >= 0 ? "+" : ""}${(t.pnl_return * 100).toFixed(2)}%<br>` +
      `PnL : ${t.pnl_mad >= 0 ? "+" : ""}${t.pnl_mad.toLocaleString("fr-FR", { maximumFractionDigits: 0 })} MAD`
    data.push({
      x: [t.open_date, t.close_date],
      y: [t.open_price, t.close_price],
      type: "scatter",
      mode: "lines",
      line: { color: win ? "rgba(16,185,129,0.45)" : "rgba(239,68,68,0.45)", width: 2 },
      hoverinfo: "text",
      text: [hover, hover],
      showlegend: false,
    })
  }

  const openHover = executed.map(
    (t) =>
      `${t.direction > 0 ? "Achat" : "Vente à découvert"} — ${t.open_date}<br>Prix : ${t.open_price.toFixed(2)}`,
  )
  const closeHover = executed.map(
    (t) =>
      `${t.direction > 0 ? "Vente" : "Rachat"} — ${t.close_date}<br>Prix : ${t.close_price.toFixed(2)}<br>` +
      `Rendement : ${t.pnl_return >= 0 ? "+" : ""}${(t.pnl_return * 100).toFixed(2)}%<br>` +
      `PnL : ${t.pnl_mad >= 0 ? "+" : ""}${t.pnl_mad.toLocaleString("fr-FR", { maximumFractionDigits: 0 })} MAD`,
  )
  if (executed.length > 0) {
    data.push(
      {
        x: executed.map((t) => t.open_date),
        y: executed.map((t) => t.open_price),
        type: "scatter",
        mode: "markers",
        name: "Entrée",
        marker: { symbol: "triangle-up", size: 10, color: "rgb(16,185,129)" },
        hoverinfo: "text",
        text: openHover,
      },
      {
        x: executed.map((t) => t.close_date),
        y: executed.map((t) => t.close_price),
        type: "scatter",
        mode: "markers",
        name: "Sortie",
        marker: { symbol: "triangle-down", size: 10, color: "rgb(239,68,68)" },
        hoverinfo: "text",
        text: closeHover,
      },
    )
  }

  return {
    data,
    layout: {
      margin: { t: 16, b: 40, l: 52, r: 16 },
      yaxis: { gridcolor: "rgba(0,0,0,0.06)" },
      xaxis: { type: "date", gridcolor: "rgba(0,0,0,0.06)" },
      showlegend: true,
      legend: { orientation: "h", x: 0, y: 1.08, font: { size: 11 } },
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

function fmtMad(v: number | null | undefined, decimals = 2): string {
  if (v == null || !Number.isFinite(v)) return "--"
  return v.toLocaleString("fr-FR", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

function ledgerPnlClass(v: number | null | undefined): string {
  if (v == null || v === 0) return "text-muted-foreground"
  return v > 0 ? "text-green-600 dark:text-green-400" : "text-destructive"
}

/** Relevé de compte — same visual model as AccountingTradeLedgerTable
 * (trade-ledger-table.tsx): sticky header, mono figures, green/red sides. */
function PortfolioAccountingLedger({
  rows,
  showSymbol = true,
  onDateHeaderClick,
  dateDir,
}: {
  rows: PortfolioBacktestLedgerRow[]
  showSymbol?: boolean
  onDateHeaderClick?: () => void
  dateDir?: 1 | -1
}) {
  if (rows.length === 0) {
    return (
      <p className="rounded border bg-muted/20 p-2 text-xs text-muted-foreground">
        Aucun mouvement exécuté pour cette période.
      </p>
    )
  }
  return (
    <div className="max-h-[420px] overflow-auto rounded border">
      <table className="w-full min-w-[1000px] text-xs">
        <thead className="sticky top-0 bg-muted/50">
          <tr>
            <th
              className={`px-2 py-1.5 text-left font-medium ${onDateHeaderClick ? "cursor-pointer select-none" : ""}`}
              onClick={onDateHeaderClick}
            >
              Date{onDateHeaderClick ? (dateDir === 1 ? " ↑" : " ↓") : ""}
            </th>
            {showSymbol ? <th className="px-2 py-1.5 text-left font-medium">Titre</th> : null}
            <th className="px-2 py-1.5 text-left font-medium">Sens</th>
            <th className="px-2 py-1.5 text-right font-medium">Quantité</th>
            <th className="px-2 py-1.5 text-right font-medium">Prix exécution</th>
            <th className="px-2 py-1.5 text-right font-medium">CMP</th>
            <th className="px-2 py-1.5 text-right font-medium">Montant (MAD)</th>
            <th className="px-2 py-1.5 text-right font-medium">PnL réalisé</th>
            <th className="px-2 py-1.5 text-right font-medium">PnL réalisé cumulé</th>
            <th className="px-2 py-1.5 text-right font-medium">Capital</th>
            <th className="px-2 py-1.5 text-right font-medium">Expo %</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/50">
          {rows.map((row, index) => {
            const sideLower = row.side.toLowerCase()
            const isBuy = sideLower.startsWith("achat") || sideLower.startsWith("rachat")
            return (
              <tr key={`${row.date}-${row.symbol}-${index}`} className="hover:bg-muted/20">
                <td className="px-2 py-1 font-mono">{row.date}</td>
                {showSymbol ? (
                  <td className="px-2 py-1 font-mono font-medium">{row.symbol}</td>
                ) : null}
                <td className="px-2 py-1">
                  <span
                    className={
                      isBuy
                        ? "font-semibold text-green-600 dark:text-green-400"
                        : "font-semibold text-red-500"
                    }
                  >
                    {row.side}
                  </span>
                </td>
                <td className="px-2 py-1 text-right font-mono">
                  {row.quantity != null ? fmtMad(row.quantity, 2) : "--"}
                </td>
                <td className="px-2 py-1 text-right font-mono">{fmtMad(row.prix_execution)}</td>
                <td className="px-2 py-1 text-right font-mono">{fmtMad(row.cmp)}</td>
                <td className="px-2 py-1 text-right font-mono">{fmtMad(row.montant, 0)}</td>
                <td className={`px-2 py-1 text-right font-mono font-semibold ${ledgerPnlClass(row.pnl_realise)}`}>
                  {row.pnl_realise != null ? fmtMad(row.pnl_realise, 0) : "--"}
                </td>
                <td className={`px-2 py-1 text-right font-mono font-semibold ${ledgerPnlClass(row.pnl_realise_cumule)}`}>
                  {fmtMad(row.pnl_realise_cumule, 0)}
                </td>
                <td className="px-2 py-1 text-right font-mono">{fmtMad(row.capital, 0)}</td>
                <td className="px-2 py-1 text-right font-mono">{row.exposition_pct.toFixed(1)}%</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function PortfolioBacktestPanel({ horizon }: Props) {
  const [initialCapital, setInitialCapital] = useState(100_000)
  const [longOnly, setLongOnly] = useState(true)
  // Off by default: exit-policy research found no TP/SL variant beats the plain
  // signal-flip exit out-of-sample (docs/plans/exit_policy_wfo_treatment_plan.md).
  // Kept as opt-in overrides for manual experimentation.
  const [tpEnabled, setTpEnabled] = useState(false)
  const [tpPct, setTpPct] = useState(5)
  const [slEnabled, setSlEnabled] = useState(false)
  const [slPct, setSlPct] = useState(5)
  const [startDate, setStartDate] = useState("")
  const [endDate, setEndDate] = useState("")
  const [result, setResult] = useState<PortfolioBacktestResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fullscreen, setFullscreen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
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
  const [activeKinds, setActiveKinds] = useState<Set<string>>(new Set())

  // Accounting ledger state
  const [ledgerSymbolFilter, setLedgerSymbolFilter] = useState<string>("__all__")
  const [ledgerDateDir, setLedgerDateDir] = useState<1 | -1>(1)
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
    getPortfolioBacktestUniverse({ horizon, long_only: longOnly })
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
        setActiveKinds(new Set(deduped.map((r) => kindOf.get(r.symbol) ?? "Other")))
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

  // Fullscreen via the browser Fullscreen API — state stays in sync with the
  // native fullscreenchange event so Esc (or any other exit path) flips the
  // icon back correctly. Plotly charts only listen to window "resize", so we
  // nudge one after the transition to make them fill/shrink to the new size.
  useEffect(() => {
    const onFullscreenChange = () => {
      const active = document.fullscreenElement === containerRef.current
      setFullscreen(active)
      window.setTimeout(() => window.dispatchEvent(new Event("resize")), 50)
    }
    document.addEventListener("fullscreenchange", onFullscreenChange)
    return () => document.removeEventListener("fullscreenchange", onFullscreenChange)
  }, [])

  async function toggleFullscreen() {
    if (document.fullscreenElement) {
      await document.exitFullscreen()
    } else {
      await containerRef.current?.requestFullscreen()
    }
  }

  // Kinds present in the current universe, with counts — drives the chip row.
  const kindsPresent = useMemo(() => {
    const counts = new Map<string, number>()
    for (const row of universe) {
      const kind = kindOf.get(row.symbol) ?? "Other"
      counts.set(kind, (counts.get(kind) ?? 0) + 1)
    }
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1])
  }, [universe, kindOf])

  const kindFilteredUniverse = useMemo(
    () => universe.filter((r) => activeKinds.has(kindOf.get(r.symbol) ?? "Other")),
    [universe, activeKinds, kindOf],
  )

  const filteredUniverse = useMemo(() => {
    const q = universeQuery.trim().toLowerCase()
    if (!q) return kindFilteredUniverse
    return kindFilteredUniverse.filter(
      (r) =>
        r.symbol.toLowerCase().includes(q) ||
        (displayNameOf.get(r.symbol) ?? "").toLowerCase().includes(q),
    )
  }, [kindFilteredUniverse, universeQuery, displayNameOf])

  const allSelected =
    kindFilteredUniverse.length > 0 && selected.size === kindFilteredUniverse.length

  function toggleSymbol(symbol: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(symbol)) next.delete(symbol)
      else next.add(symbol)
      return next
    })
  }

  function toggleKind(kind: string) {
    setActiveKinds((prev) => {
      const next = new Set(prev)
      if (next.has(kind)) {
        next.delete(kind)
        // Hide this kind's symbols from selection too — re-enabling only re-shows them.
        setSelected((prevSel) => {
          const nextSel = new Set(prevSel)
          for (const row of universe) {
            if ((kindOf.get(row.symbol) ?? "Other") === kind) nextSel.delete(row.symbol)
          }
          return nextSel
        })
      } else {
        next.add(kind)
      }
      return next
    })
  }

  function selectMasiOnly() {
    const masiKind = "MASI stocks"
    setActiveKinds(new Set([masiKind]))
    setSelected((prev) => {
      const next = new Set<string>()
      for (const symbol of prev) {
        if ((kindOf.get(symbol) ?? "Other") === masiKind) next.add(symbol)
      }
      return next
    })
  }

  function selectAll() {
    setSelected(new Set(kindFilteredUniverse.map((r) => r.symbol)))
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
      // Always send the explicit selection — an empty array means "no filter"
      // on the backend (i.e. every symbol, including non-MASI instruments),
      // which silently defeated universe filters like "MASI uniquement".
      const symbols = Array.from(selected)
      const res = await runPortfolioBacktest({
        symbols,
        horizon,
        initial_capital: initialCapital,
        take_profit_pct: tpEnabled ? tpPct / 100 : null,
        stop_loss_pct: slEnabled ? slPct / 100 : null,
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
  const equityPlot = result
    ? buildEquityPlot(result.equity_curve, result.benchmark, initialCapital)
    : null
  const totalReturnTone =
    m.total_return != null ? (m.total_return >= 0 ? "pos" : "neg") : "neutral"

  const universeLabel = universeLoading
    ? "Chargement…"
    : universe.length === 0
      ? "Aucun titre éligible"
      : allSelected
        ? `Tous les titres (${kindFilteredUniverse.length})`
        : `${selected.size} / ${kindFilteredUniverse.length} titres`

  // Accounting ledger computation — sourced from the backend `ledger`
  // (executed movements only, chronological).
  const ledgerSymbols = useMemo(() => {
    if (!result?.ledger) return []
    return Array.from(new Set(result.ledger.map((r) => r.symbol))).sort()
  }, [result])

  const filteredLedger = useMemo((): PortfolioBacktestLedgerRow[] => {
    if (!result?.ledger) return []
    let rows = result.ledger
    if (ledgerSymbolFilter !== "__all__") {
      rows = rows.filter((r) => r.symbol === ledgerSymbolFilter)
    }
    // Backend rows are chronological; descending is a simple reverse.
    return ledgerDateDir === 1 ? rows : [...rows].reverse()
  }, [result, ledgerSymbolFilter, ledgerDateDir])

  const ledgerVisible = filteredLedger.slice(0, ledgerPage * LEDGER_PAGE_SIZE)
  const hasMoreLedger = filteredLedger.length > ledgerVisible.length

  function toggleLedgerDateDir() {
    setLedgerDateDir((d) => (d === 1 ? -1 : 1))
    setLedgerPage(1)
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

  const ohlcvBars = ohlcvData?.bars ?? []

  const stockPricePlot = useMemo(
    () =>
      selectedStock && result && ohlcvBars.length > 0
        ? buildStockPricePlot(ohlcvBars, result.trades ?? [], selectedStock, result.period)
        : null,
    [selectedStock, result, ohlcvBars],
  )

  return (
    <div
      ref={containerRef}
      className={cn(
        "space-y-4",
        fullscreen && "h-screen overflow-y-auto bg-background p-4",
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
              onClick={toggleFullscreen}
              title={fullscreen ? "Quitter le plein écran" : "Plein écran"}
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
                    {kindsPresent.length > 1 ? (
                      <div className="mt-2 flex flex-wrap items-center gap-1">
                        {kindsPresent.map(([kind, count]) => {
                          const active = activeKinds.has(kind)
                          return (
                            <button
                              key={kind}
                              type="button"
                              onClick={() => toggleKind(kind)}
                              className={`rounded border px-1.5 py-0.5 text-[10px] ${
                                active
                                  ? "border-primary/40 bg-primary/10 text-primary"
                                  : "border-line bg-bg2 text-muted-foreground"
                              }`}
                            >
                              {kind} ({count})
                            </button>
                          )
                        })}
                        <button
                          type="button"
                          onClick={selectMasiOnly}
                          className="ml-auto rounded border border-line bg-bg2 px-1.5 py-0.5 text-[10px] text-muted-foreground hover:text-foreground"
                        >
                          MASI uniquement
                        </button>
                      </div>
                    ) : null}
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

            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Take Profit</Label>
              <div className="flex h-8 items-center gap-1.5">
                <Checkbox
                  checked={tpEnabled}
                  onCheckedChange={(v) => setTpEnabled(v === true)}
                />
                <Input
                  type="number"
                  min={0}
                  step={0.5}
                  value={tpPct}
                  disabled={!tpEnabled}
                  onChange={(e) => setTpPct(Number(e.target.value))}
                  className="h-8 w-16 font-mono text-xs"
                />
                <span className="text-xs text-muted-foreground">%</span>
              </div>
            </div>

            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Stop Loss</Label>
              <div className="flex h-8 items-center gap-1.5">
                <Checkbox
                  checked={slEnabled}
                  onCheckedChange={(v) => setSlEnabled(v === true)}
                />
                <Input
                  type="number"
                  min={0}
                  step={0.5}
                  value={slPct}
                  disabled={!slEnabled}
                  onChange={(e) => setSlPct(Number(e.target.value))}
                  className="h-8 w-16 font-mono text-xs"
                />
                <span className="text-xs text-muted-foreground">%</span>
              </div>
            </div>

            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="rounded border border-line bg-bg2 px-1.5 py-0.5">½-Kelly</span>
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
          {!tpEnabled && !slEnabled ? (
            <p className="mt-2 text-xs text-muted-foreground">
              TP/SL désactivés par défaut : l'étude exit-policy (WFO, OOS, corrigée du
              look-ahead) n'a trouvé aucune variante TP/SL qui batte la sortie signal-flip.
              Activez-les ci-dessus pour tester manuellement.
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

                  {/* Price chart with trades overlaid */}
                  <Card className="claude-card">
                    <CardHeader className="pb-1">
                      <CardTitle className="text-sm">
                        Prix &amp; trades exécutés — {selectedStock}
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="bt-chart">
                      {ohlcvLoading ? (
                        <Skeleton className="h-[360px] rounded" />
                      ) : stockPricePlot ? (
                        <PlotlyChart figure={stockPricePlot as never} />
                      ) : (
                        <p className="p-4 text-sm text-muted-foreground">
                          Données de prix indisponibles pour {selectedStock}.
                        </p>
                      )}
                    </CardContent>
                  </Card>

                  {/* Secondary: cumulative realized PnL */}
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

                  {/* Per-stock accounting ledger (executed movements only) */}
                  <Card className="claude-card">
                    <CardHeader className="pb-1">
                      <div className="flex items-center justify-between">
                        <CardTitle className="text-sm">
                          Relevé de compte — {selectedStock}
                        </CardTitle>
                        {result.ledger_truncated ? (
                          <span className="text-[11px] text-amber-600">
                            Limité à 4000 mouvements
                          </span>
                        ) : null}
                      </div>
                    </CardHeader>
                    <CardContent>
                      <PortfolioAccountingLedger
                        rows={ledgerVisible}
                        showSymbol={false}
                        onDateHeaderClick={toggleLedgerDateDir}
                        dateDir={ledgerDateDir}
                      />
                      <div className="mt-2 flex items-center justify-between text-[11px] text-muted-foreground">
                        <span>
                          {filteredLedger.length} mouvement{filteredLedger.length > 1 ? "s" : ""}
                          {stockStats && stockStats.n_skipped > 0
                            ? ` — ${stockStats.n_skipped} trade${stockStats.n_skipped > 1 ? "s" : ""} non exécuté${stockStats.n_skipped > 1 ? "s" : ""} (hors relevé)`
                            : ""}
                        </span>
                        {hasMoreLedger ? (
                          <button
                            type="button"
                            className="text-primary hover:underline"
                            onClick={() => setLedgerPage((p) => p + 1)}
                          >
                            Voir plus ({filteredLedger.length - ledgerVisible.length} restants)
                          </button>
                        ) : null}
                      </div>
                    </CardContent>
                  </Card>
                </>
              ) : (
                /* ── List mode ── */
                <>
                  {/* Global KPI rows */}
                  <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-5">
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
                      label="vs MASI"
                      title={
                        result.benchmark?.window
                          ? `Surperformance vs MASI achat-conservation, sur période commune ${result.benchmark.window.start} → ${result.benchmark.window.end} (stratégie ${result.benchmark.window.strategy_total_return >= 0 ? "+" : ""}${result.benchmark.window.strategy_total_return.toFixed(2)}% vs MASI ${result.benchmark.metrics.total_return >= 0 ? "+" : ""}${result.benchmark.metrics.total_return.toFixed(2)}%)`
                          : "Surperformance vs MASI achat-conservation (rendement total)"
                      }
                      value={
                        m.alpha_total_return != null
                          ? `${m.alpha_total_return >= 0 ? "+" : ""}${m.alpha_total_return.toFixed(2)}%`
                          : "--"
                      }
                      tone={
                        m.alpha_total_return != null
                          ? m.alpha_total_return >= 0
                            ? "pos"
                            : "neg"
                          : "neutral"
                      }
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
                      label="Sharpe ann."
                      title="Sharpe (hebdomadaire annualisé, x√52)"
                      value={m.sharpe != null ? formatNumber(m.sharpe, 2) : "--"}
                    />
                    <StatCard
                      label="Max Drawdown"
                      value={m.max_drawdown != null ? `-${m.max_drawdown.toFixed(2)}%` : "--"}
                      tone="neg"
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-5">
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
                    <StatCard
                      label="SL déclenché"
                      value={m.sl_applied_pct != null ? `${m.sl_applied_pct}%` : "--"}
                    />
                    <StatCard
                      label="Exposition moy. / max"
                      value={
                        m.avg_exposure_pct != null && m.max_exposure_pct != null
                          ? `${m.avg_exposure_pct.toFixed(0)}% / ${m.max_exposure_pct.toFixed(0)}%`
                          : "—"
                      }
                    />
                  </div>

                  {/* Global equity curve */}
                  <Card className="claude-card">
                    <CardHeader className="pb-1">
                      <CardTitle className="text-sm">
                        Courbe d'équité vs MASI (rendement cumulé)
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
                                <th className="r">PnL (MAD)</th>
                                <th className="r">Ignorés</th>
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
                                  <td
                                    className={`r font-mono ${
                                      s.total_pnl_mad >= 0 ? "text-emerald-600" : "text-red-600"
                                    }`}
                                  >
                                    {s.total_pnl_mad >= 0 ? "+" : ""}
                                    {s.total_pnl_mad.toLocaleString("fr-FR", {
                                      maximumFractionDigits: 0,
                                    })}
                                  </td>
                                  <td className="r font-mono text-muted-foreground">
                                    {s.n_skipped}
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

                  {/* Global accounting ledger with symbol filter dropdown */}
                  {result.ledger && result.ledger.length > 0 ? (
                    <Card className="claude-card">
                      <CardHeader className="pb-1">
                        <div className="flex items-center justify-between">
                          <CardTitle className="text-sm">
                            Relevé de compte (mouvements exécutés)
                          </CardTitle>
                          <div className="flex items-center gap-2">
                            {result.ledger_truncated ? (
                              <span className="text-[11px] text-amber-600">
                                Limité à 4000 mouvements
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
                        <PortfolioAccountingLedger
                          rows={ledgerVisible}
                          onDateHeaderClick={toggleLedgerDateDir}
                          dateDir={ledgerDateDir}
                        />
                        <div className="mt-2 flex items-center justify-between text-[11px] text-muted-foreground">
                          <span>
                            {filteredLedger.length} mouvement
                            {filteredLedger.length > 1 ? "s" : ""}
                            {ledgerSymbolFilter !== "__all__" ? ` — ${ledgerSymbolFilter}` : ""}
                            {" — les trades non exécutés n'apparaissent pas (voir « Ignorés » par titre)"}
                          </span>
                          {hasMoreLedger ? (
                            <button
                              type="button"
                              className="text-primary hover:underline"
                              onClick={() => setLedgerPage((p) => p + 1)}
                            >
                              Voir plus ({filteredLedger.length - ledgerVisible.length} restants)
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
