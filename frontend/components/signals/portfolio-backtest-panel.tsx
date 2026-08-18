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
  ApiError,
  getHistoricalPortfolioSnapshot,
  createHistoricalPortfolioBacktest,
  createHistoricalOpportunityMaterialization,
  getHistoricalPortfolioBacktestResult,
  getHistoricalPortfolioDecisions,
  getHistoricalPortfolioBacktestStatus,
  getHistoricalOpportunityCoverage,
  getHistoricalOpportunityMaterialization,
  getPortfolioBacktestUniverse,
  runPortfolioBacktest,
  type PortfolioBacktestBenchmark,
  type PortfolioBacktestLedgerRow,
  type PortfolioBacktestResult,
  type PortfolioBacktestTrade,
  type PortfolioBacktestUniverseSymbol,
  type HistoricalPortfolioRunResult,
  type HistoricalPortfolioRunStatus,
  type HistoricalOpportunityCoverage,
  type HistoricalOpportunityMaterialization,
  type HistoricalDecisionRow,
} from "@/lib/api"

type Props = {
  horizon: string
}

const LEDGER_PAGE_SIZE = 200
const EDGE_CONDITION_OPTIONS = [
  ["sample_size", "Échantillon ≥ 30"],
  ["positive_expectancy", "Espérance nette positive"],
  ["positive_ci_lower", "Borne basse nette positive"],
  ["hit_rate_ci", "Borne du taux de réussite > 50 %"],
  ["mc_luck", "Test Monte-Carlo réussi"],
  ["label_shuffle", "Test de permutation réussi"],
  ["freshness", "Fraîcheur réussie"],
  ["proven_edge", "Edge net prouvé"],
] as const

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

function SnapshotAuditLegacyPanel({ horizon }: Props) {
  const [initialCapital, setInitialCapital] = useState(100_000)
  const [longOnly, setLongOnly] = useState(true)
  const [minEdgeScore, setMinEdgeScore] = useState(50)
  const [requiredEdgeConditions, setRequiredEdgeConditions] = useState<string[]>([
    "sample_size",
    "positive_expectancy",
  ])
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
  const [deselectedKinds, setDeselectedKinds] = useState<Set<string>>(new Set())

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
    getPortfolioBacktestUniverse({
      horizon,
      long_only: longOnly,
      min_edge_score: minEdgeScore,
      required_edge_conditions: requiredEdgeConditions,
    })
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
  }, [horizon, longOnly, minEdgeScore, requiredEdgeConditions.join("|")])

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

  const activeKinds = useMemo(() => {
    const all = new Set(universe.map((r) => kindOf.get(r.symbol) ?? "Other"))
    for (const d of deselectedKinds) all.delete(d)
    return all
  }, [universe, kindOf, deselectedKinds])

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
    setDeselectedKinds((prev) => {
      const next = new Set(prev)
      if (next.has(kind)) {
        next.delete(kind)
      } else {
        next.add(kind)
        // Hide this kind's symbols from selection too — re-enabling only re-shows them.
        setSelected((prevSel) => {
          const nextSel = new Set(prevSel)
          for (const row of universe) {
            if ((kindOf.get(row.symbol) ?? "Other") === kind) nextSel.delete(row.symbol)
          }
          return nextSel
        })
      }
      return next
    })
  }

  function selectMasiOnly() {
    const masiKind = "MASI stocks"
    setDeselectedKinds((prev) => {
      const next = new Set(prev)
      for (const [kind] of kindsPresent) {
        if (kind !== masiKind) next.add(kind)
      }
      return next
    })
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
        min_edge_score: minEdgeScore,
        required_edge_conditions: requiredEdgeConditions,
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

  // Auto-run when universe is fully loaded for the first time
  useEffect(() => {
    if (!universeLoading && universe.length > 0 && selected.size > 0 && !result && !loading && !error) {
      handleRun()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [universeLoading, universe.length])

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
              <Label className="text-xs text-muted-foreground">Edge minimum</Label>
              <Input
                type="number"
                min={0}
                max={100}
                step={1}
                value={minEdgeScore}
                onChange={(e) => setMinEdgeScore(Math.min(100, Math.max(0, Number(e.target.value) || 0)))}
                className="h-8 w-24 font-mono text-xs"
              />
            </div>

            <div className="space-y-1">
              <Label className="text-xs text-muted-foreground">Conditions requises</Label>
              <Popover>
                <PopoverTrigger asChild>
                  <Button variant="outline" size="sm" className="h-8 text-xs">
                    {requiredEdgeConditions.length} condition{requiredEdgeConditions.length === 1 ? "" : "s"}
                    <ChevronDown className="ml-1 h-3.5 w-3.5" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent align="start" className="w-72 space-y-2 p-3">
                  {EDGE_CONDITION_OPTIONS.map(([value, label]) => (
                    <label key={value} className="flex cursor-pointer items-center gap-2 text-xs">
                      <Checkbox
                        checked={requiredEdgeConditions.includes(value)}
                        onCheckedChange={(checked) => {
                          setRequiredEdgeConditions((current) =>
                            checked
                              ? Array.from(new Set([...current, value]))
                              : current.filter((item) => item !== value),
                          )
                        }}
                      />
                      <span>{label}</span>
                    </label>
                  ))}
                  <p className="text-[11px] text-muted-foreground">
                    Toutes les conditions cochées doivent être vraies.
                  </p>
                </PopoverContent>
              </Popover>
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

function pct(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : "Indisponible"
}

function pctOrDash(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : "—"
}

type PitEquityPoint = {
  date: string
  equity: number
  exposure?: number
}

type PitBenchmarkCurve = {
  curve?: Array<{ date: string; equity: number }>
  total_return?: number
}

type PitHorizon = "weekly" | "monthly" | "quarterly"
const PIT_HORIZONS: Array<{ value: PitHorizon; label: string }> = [
  { value: "weekly", label: "Hebdomadaire" },
  { value: "monthly", label: "Mensuel" },
  { value: "quarterly", label: "Trimestriel" },
]

function pitPageHorizon(value: string): PitHorizon {
  if (value === "monthly") return "monthly"
  if (value === "quarterly" || value === "long") return "quarterly"
  return "weekly"
}

function pitBenchmarksForCurve(
  curve: PitEquityPoint[],
  benchmarks: Record<string, any> | null | undefined,
): Record<string, any> | null {
  if (curve.length < 2) return null
  const literal = benchmarks?.full_investment_masi as PitBenchmarkCurve | undefined
  const literalByDate = new Map((literal?.curve ?? []).map((point) => [point.date, point.equity]))
  const aligned = curve.flatMap((point) => {
    const masiEquity = literalByDate.get(point.date)
    return typeof masiEquity === "number" && Number.isFinite(masiEquity) ? [{ point, masiEquity }] : []
  })
  if (aligned.length < 2) return null
  const fullCurve = aligned.map(({ point, masiEquity }) => ({ date: point.date, equity: masiEquity }))
  let matchedEquity = aligned[0].masiEquity
  const matchedCurve = [{ date: aligned[0].point.date, equity: matchedEquity }]
  for (let index = 1; index < aligned.length; index += 1) {
    const masiReturn = aligned[index].masiEquity / aligned[index - 1].masiEquity - 1
    const priorExposure = Number(aligned[index - 1].point.exposure ?? 0)
    matchedEquity *= 1 + masiReturn * priorExposure
    matchedCurve.push({ date: aligned[index].point.date, equity: matchedEquity })
  }
  const totalReturn = (points: Array<{ equity: number }>) => points.at(-1)!.equity / points[0].equity - 1
  return {
    available: true,
    full_investment_masi: { curve: fullCurve, total_return: totalReturn(fullCurve) },
    exposure_matched_masi: { curve: matchedCurve, total_return: totalReturn(matchedCurve) },
  }
}

function pitEquityFigure(
  curve: PitEquityPoint[],
  benchmarks: Record<string, any> | null | undefined,
) {
  if (curve.length < 2) return null
  const normalized = (points: Array<{ date: string; equity: number }>) => {
    const start = points.find((point) => Number.isFinite(point.equity) && point.equity > 0)?.equity
    if (start == null) return []
    return points.map((point) => ((point.equity / start) - 1) * 100)
  }
  const traces: Array<Record<string, unknown>> = [{
    x: curve.map((point) => point.date),
    y: normalized(curve),
    type: "scatter",
    mode: "lines",
    name: "Portefeuille PIT",
    line: { color: "rgb(79,70,229)", width: 2.4 },
    fill: "tozeroy",
    fillcolor: "rgba(79,70,229,0.08)",
    hovertemplate: "%{x|%d/%m/%Y} — %{y:.2f}%<extra>Portefeuille PIT</extra>",
  }]
  const addBenchmark = (key: string, name: string, color: string, dash?: string) => {
    const payload = benchmarks?.[key] as PitBenchmarkCurve | undefined
    const points = Array.isArray(payload?.curve) ? payload.curve : []
    if (points.length < 2) return
    traces.push({
      x: points.map((point) => point.date),
      y: normalized(points),
      type: "scatter",
      mode: "lines",
      name,
      line: { color, width: 1.6, ...(dash ? { dash } : {}) },
      hovertemplate: `%{x|%d/%m/%Y} — %{y:.2f}%<extra>${name}</extra>`,
    })
  }
  addBenchmark("full_investment_masi", "MASI investi", "rgb(100,116,139)")
  addBenchmark("exposure_matched_masi", "MASI à exposition égale", "rgb(14,165,233)", "dot")
  return {
    data: traces,
    layout: {
      margin: { t: 24, b: 42, l: 56, r: 20 },
      height: 360,
      yaxis: { title: "Rendement cumulé", ticksuffix: "%", gridcolor: "rgba(0,0,0,0.06)", zeroline: true },
      xaxis: { type: "date", gridcolor: "rgba(0,0,0,0.06)" },
      showlegend: true,
      legend: { orientation: "h", x: 0, y: 1.1, font: { size: 11 } },
      hovermode: "x unified",
      plot_bgcolor: "transparent",
      paper_bgcolor: "transparent",
    },
  }
}

function pitExposureFigure(curve: PitEquityPoint[]) {
  const points = curve.filter((point) => typeof point.exposure === "number" && Number.isFinite(point.exposure))
  if (points.length < 2) return null
  return {
    data: [{
      x: points.map((point) => point.date),
      y: points.map((point) => Number(point.exposure) * 100),
      type: "scatter",
      mode: "lines",
      name: "Exposition",
      line: { color: "rgb(16,185,129)", width: 1.8 },
      fill: "tozeroy",
      fillcolor: "rgba(16,185,129,0.10)",
      hovertemplate: "%{x|%d/%m/%Y} — %{y:.1f}%<extra>Exposition</extra>",
    }],
    layout: {
      margin: { t: 12, b: 40, l: 52, r: 16 },
      height: 220,
      yaxis: { title: "Capital exposé", ticksuffix: "%", range: [0, 100], gridcolor: "rgba(0,0,0,0.06)" },
      xaxis: { type: "date", gridcolor: "rgba(0,0,0,0.06)" },
      showlegend: false,
      plot_bgcolor: "transparent",
      paper_bgcolor: "transparent",
    },
  }
}

function pitMoney(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value)
    ? `${value.toLocaleString("fr-FR", { maximumFractionDigits: 0 })} MAD`
    : "—"
}

type CoverageGapDetail = {
  code: string
  missing_ranges: Array<{ start: string; end: string }>
  covered_intervals: Array<{ start: string; end: string }>
  materialization_in_progress: string | null
}

function PointInTimePortfolioBacktestPanel({ horizon }: Props) {
  const [view, setView] = useState<"reconstructed" | "audit">("reconstructed")
  const [startDate, setStartDate] = useState("2021-01-01")
  const [endDate, setEndDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [capacity, setCapacity] = useState<0.01 | 0.025 | 0.05 | 0.1>(0.01)
  const [runId, setRunId] = useState<string | null>(null)
  const [status, setStatus] = useState<HistoricalPortfolioRunStatus | null>(null)
  const [result, setResult] = useState<HistoricalPortfolioRunResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [coverage, setCoverage] = useState<HistoricalOpportunityCoverage | null>(null)
  const [coverageNonce, setCoverageNonce] = useState(0)
  const [coverageGap, setCoverageGap] = useState<CoverageGapDetail | null>(null)
  const [materialization, setMaterialization] = useState<HistoricalOpportunityMaterialization | null>(null)
  const [decisions, setDecisions] = useState<HistoricalDecisionRow[]>([])
  const [selectedDecisionKey, setSelectedDecisionKey] = useState<string | null>(null)
  const [snapshotComputedAt, setSnapshotComputedAt] = useState<string | null>(null)
  const [snapshotLoading, setSnapshotLoading] = useState(true)
  const [pitLedgerPage, setPitLedgerPage] = useState(1)
  const [selectedHorizons, setSelectedHorizons] = useState<PitHorizon[]>([pitPageHorizon(horizon)])
  const [selectedSymbols, setSelectedSymbols] = useState<Set<string>>(new Set())
  const [universeQuery, setUniverseQuery] = useState("")
  const [pitSelectedStock, setPitSelectedStock] = useState<string | null>(null)
  const [showLegacyCompatibility, setShowLegacyCompatibility] = useState(false)
  const pitUniverseInitialized = useRef(false)

  useEffect(() => {
    setSelectedHorizons([pitPageHorizon(horizon)])
    setPitSelectedStock(null)
    setPitLedgerPage(1)
  }, [horizon])

  // Show the persisted canonical backtest immediately on mount (like the fundamental
  // value-strategy snapshot) — no launch, no wait. A background run refreshes it.
  useEffect(() => {
    let stopped = false
    setSnapshotLoading(true)
    void getHistoricalPortfolioSnapshot(pitPageHorizon(horizon))
      .then((snap) => {
        if (stopped) return
        if (snap.snapshot_available && snap.result) {
          setResult(snap.result)
          setRunId(snap.result.run_id)
          setSnapshotComputedAt(snap.computed_at ?? null)
          if (typeof snap.result.config.start_date === "string") setStartDate(snap.result.config.start_date)
          if (typeof snap.result.config.end_date === "string") setEndDate(snap.result.config.end_date)
        }
        if (snap.computing) {
          setRunId(snap.computing.run_id)
        }
      })
      .catch(() => undefined)
      .finally(() => { if (!stopped) setSnapshotLoading(false) })
    return () => { stopped = true }
  }, [horizon])

  // coverageNonce also refetches after a launch or a finished run, so the panel never keeps
  // showing a stale "store empty" from before a materialization it did not start itself.
  useEffect(() => {
    let stopped = false
    setCoverage(null)
    void getHistoricalOpportunityCoverage({ start_date: startDate, end_date: endDate })
      .then((next) => { if (!stopped) setCoverage(next) })
      .catch(() => { if (!stopped) setCoverage(null) })
    return () => { stopped = true }
  }, [startDate, endDate, coverageNonce])

  useEffect(() => {
    const universe = coverage?.requested_symbols ?? []
    if (!universe.length) return
    if (!pitUniverseInitialized.current) {
      pitUniverseInitialized.current = true
      setSelectedSymbols(new Set(universe))
      return
    }
    setSelectedSymbols((current) => {
      return new Set([...current].filter((symbol) => universe.includes(symbol)))
    })
  }, [coverage?.requested_symbols])

  useEffect(() => {
    if (!materialization || !["queued", "running"].includes(materialization.status)) return
    let stopped = false
    const poll = async () => {
      const next = await getHistoricalOpportunityMaterialization(materialization.materialization_run_id)
      if (stopped) return
      setMaterialization(next)
      if (next.status === "succeeded") {
        setCoverage(await getHistoricalOpportunityCoverage({ start_date: startDate, end_date: endDate }))
      } else if (next.status === "failed") {
        setError(next.error_message || "Le pré-calcul PIT a échoué.")
      }
    }
    const timer = window.setInterval(() => { void poll().catch(() => undefined) }, 3000)
    return () => { stopped = true; window.clearInterval(timer) }
  }, [materialization, startDate, endDate])

  useEffect(() => {
    if (!runId || result) return
    let stopped = false
    const poll = async () => {
      try {
        const next = await getHistoricalPortfolioBacktestStatus(runId)
        if (stopped) return
        setStatus(next)
        if (next.status === "succeeded") {
          const completed = await getHistoricalPortfolioBacktestResult(runId)
          setResult(completed)
          if (typeof completed.config.start_date === "string") setStartDate(completed.config.start_date)
          if (typeof completed.config.end_date === "string") setEndDate(completed.config.end_date)
        } else if (next.status === "failed") {
          setError(next.error_message || "Le calcul a échoué.")
        }
      } catch (cause) {
        if (!stopped) setError(cause instanceof Error ? cause.message : "Statut indisponible")
      }
    }
    void poll()
    const timer = window.setInterval(poll, 3000)
    return () => { stopped = true; window.clearInterval(timer) }
  }, [runId, result])

  useEffect(() => {
    if (!result) return
    let stopped = false
    const load = async () => {
      const collected: HistoricalDecisionRow[] = []
      for (const selectedHorizon of selectedHorizons) {
        let page = 1
        while (true) {
          const response = await getHistoricalPortfolioDecisions({
            start_date: startDate, end_date: endDate, horizon: selectedHorizon, page, page_size: 200,
          })
          collected.push(...response.items)
          if (response.items.length === 0 || response.items.length >= response.total || page * 200 >= response.total) break
          page += 1
        }
      }
      if (!stopped) {
        setDecisions(collected)
        const winner = collected.find((item) => item.reconstructed_dashboard_winner)
        setSelectedDecisionKey(winner ? `${winner.decision_date}|${winner.symbol}|${winner.horizon}` : null)
      }
    }
    void load().catch((cause) => { if (!stopped) setError(cause instanceof Error ? cause.message : "Décisions PIT indisponibles") })
    return () => { stopped = true }
  }, [result, startDate, endDate, selectedHorizons])

  const launch = async () => {
    setError(null)
    setCoverageGap(null)
    setResult(null)
    setStatus(null)
    setCoverageNonce((value) => value + 1)
    try {
      const created = await createHistoricalPortfolioBacktest({
        start_date: startDate, end_date: endDate, capacity_fraction: capacity,
        initial_capital: 100_000, allow_partial_fills: true, horizons: selectedHorizons,
        symbols: selectedSymbols.size === (coverage?.requested_symbols.length ?? 0)
          ? []
          : [...selectedSymbols].sort(),
      })
      setRunId(created.run_id)
    } catch (cause) {
      const detail = cause instanceof ApiError ? (cause.detail as CoverageGapDetail | undefined) : undefined
      if (detail?.code === "pit_coverage_incomplete") {
        setCoverageGap(detail)
        if (detail.materialization_in_progress) {
          setMaterialization(await getHistoricalOpportunityMaterialization(detail.materialization_in_progress))
        }
        return
      }
      setError(cause instanceof Error ? cause.message : "Impossible de créer le calcul")
    }
  }

  const materialize = async () => {
    setError(null)
    try {
      setMaterialization(await createHistoricalOpportunityMaterialization({ start_date: startDate, end_date: endDate }))
      setCoverageGap(null)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Impossible de lancer le pré-calcul PIT")
    }
  }

  const selectedScenario = result?.equity_curves?.[String(capacity)]
  const resultHorizons = (Array.isArray(result?.config?.horizons)
    ? result.config.horizons
    : PIT_HORIZONS.map((item) => item.value)) as PitHorizon[]
  const horizonSelectionMatches = resultHorizons.length === selectedHorizons.length
    && selectedHorizons.every((item) => resultHorizons.includes(item))
  const projectedSleeve = selectedHorizons.length === 1
    ? selectedScenario?.sleeves?.[selectedHorizons[0]]
    : null
  const displayedPortfolio = horizonSelectionMatches ? selectedScenario?.combined : projectedSleeve
  const baseStats = displayedPortfolio?.statistics ?? {}
  const rawCombinedCurve = (Array.isArray(displayedPortfolio?.equity_curve)
    ? displayedPortfolio.equity_curve
    : []) as PitEquityPoint[]
  const resultStartDate = typeof result?.config?.start_date === "string" ? result.config.start_date : startDate
  const resultEndDate = typeof result?.config?.end_date === "string" ? result.config.end_date : endDate
  const combinedCurve = rawCombinedCurve.filter(
    (point) => point.date >= resultStartDate && point.date <= resultEndDate,
  )
  const displayedBenchmarks = useMemo(
    () => pitBenchmarksForCurve(combinedCurve, result?.benchmark_curves),
    [combinedCurve, result?.benchmark_curves],
  )
  const stats = {
    ...baseStats,
    full_investment_masi_return: displayedBenchmarks?.full_investment_masi?.total_return,
    exposure_matched_masi_return: displayedBenchmarks?.exposure_matched_masi?.total_return,
    excess_return_vs_full_investment_masi: typeof baseStats.absolute_return === "number"
      && typeof displayedBenchmarks?.full_investment_masi?.total_return === "number"
      ? baseStats.absolute_return - displayedBenchmarks.full_investment_masi.total_return : undefined,
    excess_return_vs_exposure_matched_masi: typeof baseStats.absolute_return === "number"
      && typeof displayedBenchmarks?.exposure_matched_masi?.total_return === "number"
      ? baseStats.absolute_return - displayedBenchmarks.exposure_matched_masi.total_return : undefined,
  }
  const equityFigure = useMemo(
    () => pitEquityFigure(combinedCurve, displayedBenchmarks),
    [combinedCurve, displayedBenchmarks],
  )
  const exposureFigure = useMemo(() => pitExposureFigure(combinedCurve), [combinedCurve])
  const sleeves = Object.fromEntries(Object.entries(selectedScenario?.sleeves ?? {}).filter(
    ([sleeveHorizon]) => selectedHorizons.includes(sleeveHorizon as PitHorizon),
  )) as Record<string, any>
  const pitTrades = ((Array.isArray(result?.trades) ? result.trades : []) as Array<Record<string, any>>).filter(
    (trade) => selectedHorizons.includes(trade.horizon as PitHorizon)
      && String(trade.decision_date ?? trade.entry_date ?? "") >= resultStartDate
      && String(trade.decision_date ?? trade.entry_date ?? "") <= resultEndDate,
  )
  const displayedPitTrades = pitSelectedStock
    ? pitTrades.filter((trade) => trade.symbol === pitSelectedStock)
    : pitTrades
  const visiblePitTrades = displayedPitTrades.slice(0, pitLedgerPage * LEDGER_PAGE_SIZE)
  const resultUniverse = ((result?.config?.symbols as string[] | undefined)?.length
    ? result?.config?.symbols
    : result?.config?.resolved_universe ?? []) as string[]
  const perStockRows = useMemo(() => resultUniverse.map((symbol) => {
    const trades = pitTrades.filter((trade) => trade.symbol === symbol)
    const closed = trades.filter((trade) => typeof trade.net_return === "number")
    const wins = closed.filter((trade) => Number(trade.net_return) > 0)
    const losses = closed.filter((trade) => Number(trade.net_return) <= 0)
    const kellyValues = trades
      .map((trade) => trade.kelly_fraction)
      .filter((value): value is number => typeof value === "number" && Number.isFinite(value))
    return {
      symbol,
      trades: trades.length,
      closed: closed.length,
      open: trades.filter((trade) => trade.status === "open_at_end" || trade.status === "open").length,
      hitRate: closed.length ? wins.length / closed.length : null,
      averageReturn: closed.length
        ? closed.reduce((total, trade) => total + Number(trade.net_return), 0) / closed.length : null,
      averageWin: wins.length
        ? wins.reduce((total, trade) => total + Number(trade.net_return), 0) / wins.length : null,
      averageLoss: losses.length
        ? losses.reduce((total, trade) => total + Number(trade.net_return), 0) / losses.length : null,
      kelly: kellyValues.length
        ? kellyValues.reduce((total, value) => total + value, 0) / kellyValues.length : null,
      pnl: trades.reduce((total, trade) => total + (typeof trade.realized_pnl === "number" ? trade.realized_pnl : 0), 0),
    }
  }), [resultUniverse, pitTrades])
  const pitSelectedStockStats = perStockRows.find((row) => row.symbol === pitSelectedStock) ?? null
  const pitChartTrades = useMemo((): PortfolioBacktestTrade[] => pitTrades.flatMap((trade) => {
    if (
      typeof trade.exit_date !== "string" || typeof trade.exit_price !== "number"
      || typeof trade.realized_pnl !== "number" || typeof trade.net_return !== "number"
    ) return []
    return [{
      symbol: String(trade.symbol), direction: trade.direction === "short" ? -1 : 1,
      open_date: String(trade.entry_date), close_date: trade.exit_date,
      open_price: Number(trade.entry_price), close_price: trade.exit_price,
      pnl_return: trade.net_return, effective_return: trade.net_return,
      tp_applied: false, sl_applied: false, position_size: Number(trade.entry_notional ?? 0),
      pnl_mad: trade.realized_pnl, executed: true, skip_reason: null,
    }]
  }), [pitTrades])
  const { data: pitOhlcvData, isLoading: pitOhlcvLoading } = useStockOhlcvHistory(pitSelectedStock)
  const pitStockPricePlot = useMemo(() => pitSelectedStock && (pitOhlcvData?.bars.length ?? 0) > 0
    ? buildStockPricePlot(
      pitOhlcvData!.bars, pitChartTrades, pitSelectedStock,
      { start: combinedCurve[0]?.date ?? null, end: combinedCurve.at(-1)?.date ?? null },
    ) : null,
  [pitSelectedStock, pitOhlcvData, pitChartTrades, combinedCurve])
  const pitStockEquityPlot = useMemo(
    () => pitSelectedStock ? buildStockEquityPlot(pitChartTrades, pitSelectedStock) : null,
    [pitSelectedStock, pitChartTrades],
  )
  const initialCapital = typeof result?.config?.initial_capital === "number" ? result.config.initial_capital : 100_000
  const pitLedgerRows = useMemo((): PortfolioBacktestLedgerRow[] => {
    const curveByDate = new Map(combinedCurve.map((point) => [point.date, point]))
    const events = displayedPitTrades.flatMap((trade) => {
      const quantity = Number(trade.entry_notional ?? 0) / Number(trade.entry_price ?? 1)
      const entry = {
        date: String(trade.entry_date), symbol: String(trade.symbol), side: "Achat",
        quantity, prix_execution: Number(trade.entry_price ?? 0), cmp: Number(trade.entry_price ?? 0),
        montant: Number(trade.entry_notional ?? 0) + Number(trade.entry_cost ?? 0), pnl_realise: null as number | null,
      }
      if (typeof trade.exit_date !== "string" || typeof trade.exit_price !== "number") return [entry]
      return [entry, {
        date: trade.exit_date, symbol: String(trade.symbol), side: "Vente",
        quantity, prix_execution: trade.exit_price, cmp: Number(trade.entry_price ?? 0),
        montant: quantity * trade.exit_price - Number(trade.exit_cost ?? 0),
        pnl_realise: typeof trade.realized_pnl === "number" ? trade.realized_pnl : null,
      }]
    }).sort((left, right) => left.date.localeCompare(right.date) || left.symbol.localeCompare(right.symbol))
    let cumulativePnl = 0
    return events.map((event) => {
      cumulativePnl += event.pnl_realise ?? 0
      const mark = curveByDate.get(event.date)
      return {
        ...event, pnl_realise_cumule: cumulativePnl,
        capital: Number(mark?.equity ?? initialCapital),
        exposition_pct: Number(mark?.exposure ?? 0) * 100,
      }
    })
  }, [combinedCurve, displayedPitTrades, initialCapital])
  const filteredUniverse = (coverage?.requested_symbols ?? []).filter((symbol) =>
    symbol.toLowerCase().includes(universeQuery.trim().toLowerCase()),
  )
  const finalEquity = combinedCurve.at(-1)?.equity
  const audit = result?.snapshot_audit
  const progress = typeof status?.progress?.progress_pct === "number" ? status.progress.progress_pct : null
  const coverageIntervals = coverage?.intervals ?? []
  const coverageMinStart = coverageIntervals.reduce(
    (earliest, interval) => earliest == null || interval.start < earliest ? interval.start : earliest,
    null as string | null,
  )
  const coverageMaxEnd = coverageIntervals.reduce(
    (latest, interval) => latest == null || interval.end > latest ? interval.end : latest,
    null as string | null,
  )
  const requestedRangeCovered = coverageIntervals.some(
    (interval) => interval.start <= startDate && interval.end >= endDate,
  )
  const coverageMessage = coverage == null
    ? "Vérification de la couverture PIT…"
    : coverageIntervals.length === 0
      ? "Store PIT vide — pré-calculez la période avant de lancer (section Avancé)"
      : requestedRangeCovered
        ? `✓ Opportunités historiques pré-calculées (${coverageMinStart} → ${coverageMaxEnd}) — prêt à lancer`
        : `Couverture PIT : ${coverageMinStart} → ${coverageMaxEnd} — les dates manquantes doivent être pré-calculées avant le lancement`
  const decisionGroups = useMemo(() => {
    const groups = new Map<string, HistoricalDecisionRow[]>()
    for (const item of decisions) {
      const key = `${item.decision_date}|${item.symbol}|${item.horizon}`
      groups.set(key, [...(groups.get(key) ?? []), item])
    }
    return groups
  }, [decisions])
  const selectedDecisions = selectedDecisionKey ? decisionGroups.get(selectedDecisionKey) ?? [] : []
  const executionEvents = Array.isArray(result?.diagnostics?.execution_events_v1)
    ? result?.diagnostics?.execution_events_v1 as Array<Record<string, any>>
    : []
  const selectedExecution = selectedDecisionKey
    ? executionEvents.find((item) => `${item.decision_date}|${item.symbol}|${item.horizon}` === selectedDecisionKey && item.scenario === "baseline")
    : null

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100">
        <p className="font-semibold">Backtest historique point-in-time — exécutions modélisées</p>
        <p className="mt-1 text-xs">
          Reconstitution hebdomadaire des opportunités avec les huit variantes WFO, informations arrêtées à chaque date,
          entrée J+1, sortie J+ sélectionnée, demi-Kelly sans échantillon de départ synthétique, coûts, glissement et ADV20.
          Méthodologie statistique dashboard v5 figée : cette reconstruction contrôle le point-in-time et l&apos;exécution,
          mais ne constitue pas une preuve de validité statistique de l&apos;edge.
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button variant={view === "reconstructed" ? "default" : "outline"} onClick={() => setView("reconstructed")}>Reconstitution point-in-time</Button>
        <Button variant={view === "audit" ? "default" : "outline"} onClick={() => setView("audit")}>Audit littéral DashboardSnapshot</Button>
      </div>

      <Card>
        <CardHeader><CardTitle className="text-sm">Backtest historique persistant</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {snapshotComputedAt ? (
            <p className="text-xs text-muted-foreground">
              Résultat affiché : reconstruction du {snapshotComputedAt.slice(0, 10)}. Les paramètres ci-dessous relancent un calcul de rafraîchissement.
            </p>
          ) : snapshotLoading ? (
            <p className="text-xs text-muted-foreground">Chargement du dernier backtest…</p>
          ) : null}
          <div className="grid gap-3 sm:grid-cols-4">
            <Label>Début<Input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></Label>
            <Label>Fin<Input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></Label>
            <Label>Capacité
              <select className="mt-1 h-9 w-full rounded-md border bg-background px-2" value={capacity} onChange={(event) => setCapacity(Number(event.target.value) as 0.01 | 0.025 | 0.05 | 0.1)}>
                <option value={0.01}>1% ADV20</option><option value={0.025}>2,5% ADV20</option>
                <option value={0.05}>5% ADV20</option><option value={0.1}>10% ADV20</option>
              </select>
            </Label>
            <div className="flex items-end"><Button className="w-full" variant="outline" disabled={!startDate || !endDate || selectedHorizons.length === 0 || selectedSymbols.size === 0 || status?.status === "running" || status?.status === "queued"} onClick={launch}>{result ? "Recalculer" : "Lancer le backtest"}</Button></div>
          </div>
          <div className="space-y-2">
            <Label>Horizons inclus dans ce backtest</Label>
            <div className="flex flex-wrap gap-2">
              {PIT_HORIZONS.map((item) => {
                const checked = selectedHorizons.includes(item.value)
                return <Button
                  key={item.value}
                  type="button"
                  size="sm"
                  variant={checked ? "default" : "outline"}
                  onClick={() => {
                    setSelectedHorizons((current) => checked
                      ? (current.length > 1 ? current.filter((value) => value !== item.value) : current)
                      : PIT_HORIZONS.map((option) => option.value).filter((value) => [...current, item.value].includes(value)))
                    setPitSelectedStock(null)
                    setPitLedgerPage(1)
                  }}
                >{item.label}</Button>
              })}
            </div>
            <p className="text-xs text-muted-foreground">
              L&apos;horizon actif de la page est sélectionné par défaut. Vous pouvez en combiner plusieurs avant de relancer.
            </p>
          </div>
          <details className="rounded-md border p-3">
            <summary className="cursor-pointer text-sm font-medium">
              Univers sélectionné ({selectedSymbols.size}/{coverage?.requested_symbols.length ?? 0})
            </summary>
            <div className="mt-3 space-y-2">
              <div className="flex flex-wrap gap-2">
                <Input className="max-w-xs" placeholder="Filtrer un ticker" value={universeQuery} onChange={(event) => setUniverseQuery(event.target.value)} />
                <Button size="sm" variant="outline" type="button" onClick={() => setSelectedSymbols(new Set(coverage?.requested_symbols ?? []))}>Tout sélectionner</Button>
              </div>
              <ScrollArea className="h-44 rounded-md border p-2">
                <div className="grid gap-2 sm:grid-cols-3 md:grid-cols-5">
                  {filteredUniverse.map((symbol) => <Label key={symbol} className="flex items-center gap-2 font-mono text-xs">
                    <Checkbox
                      checked={selectedSymbols.has(symbol)}
                      onCheckedChange={(next) => setSelectedSymbols((current) => {
                        const updated = new Set(current)
                        if (next) updated.add(symbol)
                        else if (updated.size > 1) updated.delete(symbol)
                        return updated
                      })}
                    />
                    {symbol}
                  </Label>)}
                </div>
              </ScrollArea>
            </div>
          </details>
          <p className="text-xs text-muted-foreground">
            {coverageMessage}.
            {materialization ? ` Pré-calcul ${materialization.status}${typeof materialization.progress.progress_pct === "number" ? ` (${materialization.progress.progress_pct}%)` : ""}.` : ""}
          </p>
          {status ? <p className="text-xs text-muted-foreground">Run {status.run_id} — {status.status}{progress != null ? ` (${progress}%)` : ""}. Un résultat partiel n&apos;est jamais affiché.</p> : null}
          {coverageGap ? (
            <div className="rounded-md border border-amber-300 bg-amber-50 p-3 text-xs text-amber-950 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100">
              <p className="font-semibold">Ces dates ne sont pas encore pré-calculées</p>
              <p className="mt-1">
                Période(s) manquante(s) :{" "}
                {coverageGap.missing_ranges.map((range) => `${range.start} → ${range.end}`).join(", ")}.
              </p>
              {coverageGap.materialization_in_progress ? (
                <p className="mt-1">Un pré-calcul est déjà en cours — patientez puis relancez le backtest.</p>
              ) : (
                <div className="mt-2">
                  <p>Lancez le pré-calcul de cette période uniquement, puis relancez le backtest.</p>
                  <Button className="mt-2" size="sm" variant="outline" onClick={materialize}>
                    Pré-calculer la période manquante
                  </Button>
                </div>
              )}
            </div>
          ) : null}
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
          <details className="text-xs text-muted-foreground">
            <summary>Avancé : gestion manuelle du store PIT</summary>
            <div className="mt-2 space-y-2">
              <Button variant="outline" disabled={!startDate || !endDate || materialization?.status === "running" || materialization?.status === "queued"} onClick={materialize}>
                {coverage?.available ? "Actualiser le PIT" : "Pré-calculer le PIT"}
              </Button>
              {materialization ? <p>Pré-calcul {materialization.status}{typeof materialization.progress.progress_pct === "number" ? ` (${materialization.progress.progress_pct}%)` : ""}.</p> : null}
              {error ? <p className="text-destructive">{error}</p> : null}
            </div>
          </details>
        </CardContent>
      </Card>

      {view === "reconstructed" && result && !displayedPortfolio ? (
        <Card><CardContent className="pt-4 text-sm text-muted-foreground">
          Ce résultat ne contient pas cette combinaison d&apos;horizons. Relancez le backtest pour calculer exactement {selectedHorizons.map((item) => PIT_HORIZONS.find((option) => option.value === item)?.label).join(" + ")}.
        </CardContent></Card>
      ) : null}

      {view === "reconstructed" && result && displayedPortfolio ? (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            <StatCard label="Rendement absolu" value={pct(stats.absolute_return)} />
            <StatCard label="CAGR" value={pct(stats.cagr)} />
            <StatCard label="Volatilité" value={pct(stats.volatility)} />
            <StatCard label="Sharpe" value={typeof stats.sharpe === "number" ? stats.sharpe.toFixed(2) : "Indisponible"} />
            <StatCard label="Drawdown max." value={pct(stats.max_drawdown)} tone="neg" />
            <StatCard label="Vs MASI investi" value={pct(stats.excess_return_vs_full_investment_masi)} />
            <StatCard label="Vs MASI expo." value={pct(stats.excess_return_vs_exposure_matched_masi)} />
            <StatCard label="Exposition moy." value={pct(stats.average_exposure)} />
            <StatCard label="VaR 1j 95%" value={pct(stats.var_1d_95)} />
            <StatCard label="ES 10j 95%" value={pct(stats.expected_shortfall_10d_95)} />
            <StatCard label="Trades" value={String(stats.trade_count ?? 0)} />
            <StatCard label="Coût" value={typeof stats.cost_impact_mad === "number" ? `${stats.cost_impact_mad.toLocaleString("fr-FR", { maximumFractionDigits: 0 })} MAD` : "Indisponible"} />
            <StatCard label="Capital initial" value={pitMoney(initialCapital)} />
            <StatCard label="Capital final" value={pitMoney(finalEquity)} />
            <StatCard label="Hit-rate" value={pct(stats.hit_rate)} />
            <StatCard label="Exposition max." value={pct(stats.maximum_exposure)} />
            <StatCard label="Turnover" value={pct(stats.turnover)} />
            <StatCard label="Rejets" value={String(stats.rejected_trade_count ?? 0)} />
          </div>

          <Card className="claude-card">
            <CardHeader className="pb-1">
              <CardTitle className="text-sm">Courbe d&apos;équité vs MASI · {startDate} → {endDate}</CardTitle>
            </CardHeader>
            <CardContent className="bt-chart">
              {equityFigure ? (
                <PlotlyChart figure={equityFigure as never} />
              ) : (
                <p className="p-4 text-sm text-muted-foreground">
                  La capacité sélectionnée ne contient pas assez de points pour tracer la courbe.
                </p>
              )}
            </CardContent>
          </Card>

          {exposureFigure ? (
            <Card className="claude-card">
              <CardHeader className="pb-1"><CardTitle className="text-sm">Exposition historique du portefeuille</CardTitle></CardHeader>
              <CardContent className="bt-chart"><PlotlyChart figure={exposureFigure as never} /></CardContent>
            </Card>
          ) : null}

          <Card className="claude-card">
            <CardHeader className="pb-1"><CardTitle className="text-sm">Détail des sleeves</CardTitle></CardHeader>
            <CardContent>
              <div className="overflow-x-auto rounded-md border border-line">
                <table className="claude-table">
                  <thead><tr>
                    <th>Horizon</th><th className="r">Rendement</th><th className="r">CAGR</th>
                    <th className="r">Sharpe</th><th className="r">Drawdown</th><th className="r">Exposition moy.</th>
                    <th className="r">Trades</th><th className="r">Coûts</th>
                  </tr></thead>
                  <tbody>
                    {Object.entries(sleeves).map(([sleeveHorizon, payload]) => {
                      const sleeveStats = payload?.statistics ?? {}
                      return <tr key={sleeveHorizon}>
                        <td className="font-medium capitalize">{sleeveHorizon}</td>
                        <td className="r font-mono">{pct(sleeveStats.absolute_return)}</td>
                        <td className="r font-mono">{pct(sleeveStats.cagr)}</td>
                        <td className="r font-mono">{typeof sleeveStats.sharpe === "number" ? sleeveStats.sharpe.toFixed(2) : "—"}</td>
                        <td className="r font-mono text-red-600">{pct(sleeveStats.max_drawdown)}</td>
                        <td className="r font-mono">{pct(sleeveStats.average_exposure)}</td>
                        <td className="r font-mono">{String(sleeveStats.trade_count ?? 0)}</td>
                        <td className="r font-mono">{pitMoney(sleeveStats.cost_impact_mad)}</td>
                      </tr>
                    })}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          <Card className="claude-card">
            <CardHeader className="pb-1">
              <div className="flex items-center justify-between gap-3">
                <CardTitle className="text-sm">Résultats par valeur · univers du run</CardTitle>
                <span className="text-xs text-muted-foreground">{resultUniverse.length} valeur(s)</span>
              </div>
            </CardHeader>
            <CardContent>
              <div className="max-h-80 overflow-auto rounded-md border border-line">
                <table className="claude-table">
                  <thead><tr><th>Ticker</th><th className="r">½-Kelly</th><th className="r">Trades</th><th className="r">Ouverts</th><th className="r">Win Rate</th><th className="r">Moy. gain</th><th className="r">Moy. perte</th><th className="r">PnL (MAD)</th></tr></thead>
                  <tbody>{perStockRows.map((row) => <tr
                    key={row.symbol}
                    className={cn("cursor-pointer", pitSelectedStock === row.symbol && "bg-muted")}
                    onClick={() => { setPitSelectedStock((current) => current === row.symbol ? null : row.symbol); setPitLedgerPage(1) }}
                  >
                    <td className="font-mono font-medium">{row.symbol}</td>
                    <td className="r font-mono">{pctOrDash(row.kelly)}</td>
                    <td className="r font-mono">{row.trades}</td>
                    <td className="r font-mono text-muted-foreground">{row.open}</td>
                    <td className="r font-mono">{pctOrDash(row.hitRate)}</td>
                    <td className="r font-mono text-emerald-600">{pctOrDash(row.averageWin)}</td>
                    <td className="r font-mono text-red-600">{pctOrDash(row.averageLoss)}</td>
                    <td className={cn("r font-mono", row.pnl >= 0 ? "text-emerald-600" : "text-red-600")}>{pitMoney(row.pnl)}</td>
                  </tr>)}</tbody>
                </table>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">Cliquez sur une valeur pour filtrer le journal des trades ci-dessous.</p>
            </CardContent>
          </Card>

          {pitSelectedStock && pitSelectedStockStats ? (
            <>
              <div className="flex items-center gap-2">
                <Button type="button" variant="ghost" size="sm" className="h-7 gap-1.5 px-2 text-xs" onClick={() => { setPitSelectedStock(null); setPitLedgerPage(1) }}>
                  <ArrowLeft className="h-3.5 w-3.5" /> Retour à l&apos;univers
                </Button>
                <span className="font-mono text-sm font-semibold">{pitSelectedStock}</span>
                <span className="text-xs text-muted-foreground">{selectedHorizons.join(" + ")}</span>
              </div>
              <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 lg:grid-cols-6">
                <StatCard label="Trades" value={String(pitSelectedStockStats.trades)} />
                <StatCard label="Win Rate" value={pctOrDash(pitSelectedStockStats.hitRate)} tone={(pitSelectedStockStats.hitRate ?? 0) >= 0.5 ? "pos" : "neg"} />
                <StatCard label="Moy. gain" value={pctOrDash(pitSelectedStockStats.averageWin)} tone="pos" />
                <StatCard label="Moy. perte" value={pctOrDash(pitSelectedStockStats.averageLoss)} tone="neg" />
                <StatCard label="½-Kelly moyen" value={pctOrDash(pitSelectedStockStats.kelly)} />
                <StatCard label="PnL total" value={pitMoney(pitSelectedStockStats.pnl)} tone={pitSelectedStockStats.pnl >= 0 ? "pos" : "neg"} />
              </div>
              <Card className="claude-card">
                <CardHeader className="pb-1"><CardTitle className="text-sm">Prix &amp; trades exécutés — {pitSelectedStock}</CardTitle></CardHeader>
                <CardContent className="bt-chart">
                  {pitOhlcvLoading ? <Skeleton className="h-[360px] rounded" />
                    : pitStockPricePlot ? <PlotlyChart figure={pitStockPricePlot as never} />
                      : <p className="p-4 text-sm text-muted-foreground">
                          {pitSelectedStockStats.closed === 0
                            ? `Aucun trade clôturé pour ${pitSelectedStock} sur les horizons sélectionnés.`
                            : `Données de prix indisponibles pour ${pitSelectedStock}.`}
                        </p>}
                </CardContent>
              </Card>
              {pitStockEquityPlot ? <Card className="claude-card">
                <CardHeader className="pb-1"><CardTitle className="text-sm">PnL réalisé cumulé — {pitSelectedStock}</CardTitle></CardHeader>
                <CardContent className="bt-chart"><PlotlyChart figure={pitStockEquityPlot as never} /></CardContent>
              </Card> : null}
            </>
          ) : null}

          <Card className="claude-card">
            <CardHeader className="pb-1">
              <div className="flex items-center justify-between gap-3">
                <CardTitle className="text-sm">Trades exécutés{pitSelectedStock ? ` · ${pitSelectedStock}` : ""}</CardTitle>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground">{displayedPitTrades.length} trade(s)</span>
                  {pitSelectedStock ? <Button size="sm" variant="ghost" onClick={() => { setPitSelectedStock(null); setPitLedgerPage(1) }}>Toutes les valeurs</Button> : null}
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {displayedPitTrades.length ? (
                <>
                  <div className="overflow-x-auto rounded-md border border-line">
                    <table className="claude-table">
                      <thead><tr>
                        <th>Ticker</th><th>Horizon</th><th>Variante</th><th>Décision</th><th>Entrée</th><th>Sortie</th>
                        <th className="r">Prix entrée</th><th className="r">Prix sortie</th><th className="r">Notionnel</th>
                        <th className="r">Rendement net</th><th className="r">PnL réalisé</th><th>Motif sortie</th>
                      </tr></thead>
                      <tbody>
                        {visiblePitTrades.map((trade, index) => {
                          const pnl = typeof trade.realized_pnl === "number" ? trade.realized_pnl : null
                          return <tr key={`${trade.symbol}-${trade.horizon}-${trade.entry_date}-${index}`}>
                            <td className="font-mono font-medium">{String(trade.symbol ?? "—")}</td>
                            <td className="capitalize">{String(trade.horizon ?? "—")}</td>
                            <td className="font-mono text-xs">{String(trade.variant ?? "—")}</td>
                            <td>{String(trade.decision_date ?? "—")}</td><td>{String(trade.entry_date ?? "—")}</td>
                            <td>{String(trade.exit_date ?? (trade.status === "open_at_end" ? "Ouvert" : "—"))}</td>
                            <td className="r font-mono">{typeof trade.entry_price === "number" ? trade.entry_price.toFixed(2) : "—"}</td>
                            <td className="r font-mono">{typeof trade.exit_price === "number" ? trade.exit_price.toFixed(2) : "—"}</td>
                            <td className="r font-mono">{pitMoney(trade.entry_notional)}</td>
                            <td className={cn("r font-mono", typeof trade.net_return === "number" && trade.net_return >= 0 ? "text-emerald-600" : "text-red-600")}>{pct(trade.net_return)}</td>
                            <td className={cn("r font-mono", pnl != null && pnl >= 0 ? "text-emerald-600" : "text-red-600")}>{pitMoney(pnl)}</td>
                            <td>{String(trade.exit_reason ?? trade.status ?? "—")}</td>
                          </tr>
                        })}
                      </tbody>
                    </table>
                  </div>
                  {visiblePitTrades.length < displayedPitTrades.length ? (
                    <div className="mt-2 text-right">
                      <Button size="sm" variant="outline" onClick={() => setPitLedgerPage((page) => page + 1)}>
                        Voir plus ({displayedPitTrades.length - visiblePitTrades.length} restants)
                      </Button>
                    </div>
                  ) : null}
                </>
              ) : <p className="text-sm text-muted-foreground">Aucun trade exécuté pour cette capacité.</p>}
            </CardContent>
          </Card>

          <Card className="claude-card">
            <CardHeader className="pb-1">
              <CardTitle className="text-sm">Relevé de compte{pitSelectedStock ? ` — ${pitSelectedStock}` : " (mouvements exécutés)"}</CardTitle>
            </CardHeader>
            <CardContent>
              <PortfolioAccountingLedger rows={pitLedgerRows} showSymbol={!pitSelectedStock} />
              {selectedHorizons.length > 1 ? <p className="mt-2 text-[11px] text-muted-foreground">
                Les mouvements conservent leur notionnel de sleeve; le capital et l&apos;exposition affichés correspondent à la courbe combinée equal-risk.
              </p> : null}
            </CardContent>
          </Card>

          <Card><CardContent className="pt-4 text-xs text-muted-foreground">
            <p>Période effectivement tracée: {combinedCurve[0]?.date ?? startDate} → {combinedCurve.at(-1)?.date ?? endDate} · Horizons: {selectedHorizons.map((item) => PIT_HORIZONS.find((option) => option.value === item)?.label).join(", ")}.</p>
            <p className="mt-1"><strong>MASI investi</strong> applique 100% des rendements quotidiens des cours de clôture MASI stockés. <strong>MASI à exposition égale</strong> utilise exactement les mêmes cours MASI, mais multiplie chaque rendement par l&apos;exposition du portefeuille observée la veille. Ce n&apos;est donc pas un indice synthétique différent.</p>
            <p className="mt-1">Capacité affichée: {(capacity * 100).toLocaleString("fr-FR")}% ADV20. Coûts: 33 pb/côté + glissement 5 pb/côté.</p>
            <p className="mt-1">Diagnostics: rendement, CAGR, volatilité, Sharpe, drawdown, exposition, hit-rate, turnover et VaR/ES calculés sur la courbe réalisée. Les métriques sans historique suffisant restent indisponibles.</p>
          </CardContent></Card>
          <Card>
            <CardHeader><CardTitle className="text-sm">Décisions PIT et exécution</CardTitle></CardHeader>
            <CardContent className="space-y-3 text-xs">
              <select className="h-9 w-full rounded-md border bg-background px-2" value={selectedDecisionKey ?? ""} onChange={(event) => setSelectedDecisionKey(event.target.value || null)}>
                <option value="">Sélectionner une semaine / valeur</option>
                {Array.from(decisionGroups.keys()).map((key) => <option key={key} value={key}>{key.replaceAll("|", " · ")}</option>)}
              </select>
              {selectedExecution ? <p>
                Action: <strong>{String(selectedExecution.execution_action)}</strong> · motif {String(selectedExecution.reason)} · éligible nouvelle entrée {selectedExecution.execution_eligible ? "oui" : "non"}
              </p> : null}
              {selectedDecisions.map((item) => (
                <details key={item.variant} className="rounded border p-2" open={item.reconstructed_dashboard_winner}>
                  <summary className="cursor-pointer">
                    {item.variant} · {item.status} · {item.actionable ? "actionnable" : "non actionnable"} · {item.reconstructed_dashboard_winner ? "gagnant dashboard" : "audit"}
                  </summary>
                  <div className="mt-2 grid gap-2 sm:grid-cols-2">
                    <pre className="overflow-auto rounded bg-muted p-2">{JSON.stringify(item.decision.category_scores, null, 2)}</pre>
                    <pre className="overflow-auto rounded bg-muted p-2">{JSON.stringify({ reasons: item.decision.actionability_reasons, rank: item.rank, evidence: item.decision.evidence }, null, 2)}</pre>
                  </div>
                </details>
              ))}
            </CardContent>
          </Card>
          {result.warnings.map((warning, index) => <p key={index} className="rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">{warning}</p>)}
        </div>
      ) : null}

      {view === "audit" ? (
        <Card>
          <CardHeader><CardTitle className="text-sm">Audit littéral des opportunités réellement stockées</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            {!result ? <p>Lancez ou chargez un run terminé pour comparer les dates de snapshots qui existaient réellement.</p> : (
              <>
                <p className="font-medium">Fenêtre courte: {audit?.coverage_start ?? "indisponible"} → {audit?.coverage_end ?? "indisponible"}</p>
                <p className="text-xs text-muted-foreground">Cet audit DashboardSnapshot n&apos;est pas statistiquement équivalent au backtest reconstruit de longue période. Aucune date sans snapshot n&apos;est inventée.</p>
                <p>{audit?.snapshot_dates?.length ?? 0} date(s) de snapshot · {audit?.comparisons?.length ?? 0} comparaison(s) · {audit?.discrepancy_count ?? 0} écart(s).</p>
                <p>Opportunités littérales auditées: {audit?.literal_opportunity_count ?? 0}. Les snapshots servent uniquement à l&apos;audit de fidélité et ne produisent aucune seconde courbe.</p>
                {(audit?.comparisons ?? []).slice(0, 200).map((row: any, index: number) => (
                  <div key={`${row.as_of_date}-${row.horizon}-${row.symbol}-${index}`} className="grid grid-cols-5 gap-2 border-t py-1 text-xs">
                    <span>{row.as_of_date}</span><span>{row.horizon}</span><span>{row.symbol}</span>
                    <span>{row.snapshot_variant ?? "absent"} → {row.reconstructed_variant ?? "absent"}</span>
                    <span className={row.matches ? "text-emerald-600" : "text-amber-700"}>{row.matches ? "Concordant" : "Écart"}</span>
                  </div>
                ))}
              </>
            )}
          </CardContent>
        </Card>
      ) : null}

      <details
        className="rounded-md border p-3 text-xs text-muted-foreground"
        onToggle={(event) => setShowLegacyCompatibility(event.currentTarget.open)}
      >
        <summary className="cursor-pointer font-medium">Ancien calcul de compatibilité (non point-in-time)</summary>
        {showLegacyCompatibility ? <div className="mt-3"><SnapshotAuditLegacyPanel horizon={horizon} /></div> : null}
      </details>
    </div>
  )
}

export function PortfolioBacktestPanel({ horizon }: Props) {
  return <PointInTimePortfolioBacktestPanel horizon={horizon} />
}
