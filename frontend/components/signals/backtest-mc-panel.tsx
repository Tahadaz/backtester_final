"use client"

import { useState, useCallback, useEffect, useMemo } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import {
  fetchIndicatorSeries,
  fetchSignalBacktestResults,
  triggerSignalBacktest,
  type SignalBacktestResult,
  type SignalBacktestResponse,
} from "@/lib/api"
import { formatPercent, formatNumber } from "@/lib/format"
import { MetricsKpiGrid } from "@/components/signals/metrics-kpi-grid"
import { TradeLedgerTable } from "@/components/signals/trade-ledger-table"
import { PriceSignalsChart, type IndicatorOverlaySeries } from "@/components/signals/price-signals-chart"
import { GlobalFanChart, buildFanTraces, buildFanLayout } from "@/components/signals/fan-chart"
import { ShuffledTradesPanel } from "@/components/signals/shuffled-trades-panel"
import { PlotlyChart } from "@/components/run/plotly-chart"

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CATEGORIES = ["tendance", "momentum", "oscillation", "volume"] as const
const CAT_LABELS: Record<string, string> = {
  tendance: "Tendance",
  momentum: "Momentum",
  oscillation: "Oscillation",
  volume: "Volume",
}
const DEFAULT_START = "2026-01-01"
type TabKey = "global" | "tendance" | "momentum" | "oscillation" | "volume" | "comparaison"

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

function fmt(v: number | null | undefined, isPct = false) {
  if (v == null) return "—"
  return isPct ? formatPercent(v) : formatNumber(v, 2)
}

type RepresentativeIndicator = {
  id: string
  family: string
  variant_id: string
  description: string
  params: Record<string, number>
  normalized_weight: number | null
  signal_label: string
  indicator_value: number | null
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value == null || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function asFiniteNumber(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value)) return null
  return value
}

function extractRepresentativeIndicators(row: SignalBacktestResult): RepresentativeIndicator[] {
  const diagnostics = asRecord((row as Record<string, unknown>).signal_diagnostics)
  const reps = diagnostics && Array.isArray(diagnostics.representatives) ? diagnostics.representatives : []
  const out: RepresentativeIndicator[] = []
  const seen = new Set<string>()

  for (const rawRep of reps) {
    const rep = asRecord(rawRep)
    if (!rep) continue
    const family = typeof rep.family === "string" ? rep.family : ""
    const variantId = typeof rep.variant_id === "string" ? rep.variant_id : ""
    if (!family || !variantId) continue
    const id = `${family}::${variantId}`
    if (seen.has(id)) continue
    seen.add(id)

    const params: Record<string, number> = {}
    const rawParams = asRecord(rep.params) ?? {}
    Object.entries(rawParams).forEach(([key, value]) => {
      const n = asFiniteNumber(value)
      if (n != null) params[key] = n
    })

    out.push({
      id,
      family,
      variant_id: variantId,
      description:
        (typeof rep.description === "string" && rep.description.trim()) ||
        (typeof rep.label === "string" && rep.label.trim()) ||
        variantId,
      params,
      normalized_weight: asFiniteNumber(rep.normalized_weight),
      signal_label: typeof rep.signal_label === "string" ? rep.signal_label : "",
      indicator_value: asFiniteNumber(rep.indicator_value),
    })
  }
  return out
}

// ---------------------------------------------------------------------------
// Helper: StaleBadge
// ---------------------------------------------------------------------------

function StaleBadge({ isStale, computedAt }: { isStale: boolean; computedAt: string | null }) {
  if (!computedAt) return null
  return (
    <Badge variant={isStale ? "destructive" : "outline"} className="text-xs">
      {isStale ? `Obsolète (${computedAt.slice(0, 10)})` : `Calculé ${computedAt.slice(0, 10)}`}
    </Badge>
  )
}

// ---------------------------------------------------------------------------
// Helper: FlatSignalBanner
// ---------------------------------------------------------------------------

function FlatSignalBanner({ onSwitchLongShort }: { onSwitchLongShort: () => void }) {
  return (
    <div className="rounded border border-amber-400/50 bg-amber-50 dark:bg-amber-950/20 p-3 text-xs text-amber-800 dark:text-amber-300 flex items-start gap-2">
      <span className="shrink-0 text-base">⚠️</span>
      <span>
        <strong>Signal plat</strong> — les signaux pondérés sont tous ≤ 0 sur cette période, donc aucun trade long n'est généré.
        Essayez le mode <strong>Long/Short</strong> pour capturer les signaux baissiers,
        ou vérifiez que des familles non provisoires existent pour ce symbole.
      </span>
      <Button size="sm" variant="outline" className="shrink-0 h-6 px-2 text-xs border-amber-400" onClick={onSwitchLongShort}>
        Passer en Long/Short
      </Button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Helper: ResultBlock — one full result section for a single scope+source row
// ---------------------------------------------------------------------------

function ResultBlock({
  row,
  symbol,
  onSwitchLongShort,
}: {
  row: SignalBacktestResult
  symbol: string
  onSwitchLongShort: () => void
}) {
  const trades = (row as Record<string, unknown>).trades as Record<string, unknown>[] | null | undefined
  const closeSeries = (row as Record<string, unknown>).close_series as number[] | null | undefined
  const positionSeries = (row as Record<string, unknown>).position_series as number[] | null | undefined
  const shuffleStats = (row as Record<string, unknown>).shuffle_stats as Record<string, unknown> | null | undefined
  const warningCode = (row as Record<string, unknown>).warning_code as string | null | undefined
  const representatives = useMemo(() => extractRepresentativeIndicators(row), [row])
  const [activeRepIds, setActiveRepIds] = useState<string[]>([])
  const [seriesByRepId, setSeriesByRepId] = useState<Record<string, IndicatorOverlaySeries>>({})
  const [loadingByRepId, setLoadingByRepId] = useState<Record<string, boolean>>({})
  const [errorByRepId, setErrorByRepId] = useState<Record<string, string>>({})

  useEffect(() => {
    setActiveRepIds([])
    setLoadingByRepId({})
    setErrorByRepId({})
  }, [row.scope, row.scope_key, row.source, row.window_start, row.window_end])

  const loadRepresentativeSeries = useCallback(
    async (rep: RepresentativeIndicator) => {
      if (seriesByRepId[rep.id]) return true

      setLoadingByRepId((prev) => ({ ...prev, [rep.id]: true }))
      try {
        const series = await fetchIndicatorSeries({
          symbol,
          indicator: rep.family,
          params: rep.params,
          timeframe: "1D",
        })
        const byDate = new Map<string, number | null>()
        series.dates.forEach((d, idx) => {
          const v = series.indicator_values[idx]
          byDate.set(d, typeof v === "number" && Number.isFinite(v) ? v : null)
        })
        const aligned = (row.dates ?? []).map((d) => byDate.get(d) ?? null)
        setSeriesByRepId((prev) => ({
          ...prev,
          [rep.id]: {
            id: rep.id,
            label: rep.description,
            values: aligned,
          },
        }))
        setErrorByRepId((prev) => {
          const next = { ...prev }
          delete next[rep.id]
          return next
        })
        return true
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err)
        setErrorByRepId((prev) => ({ ...prev, [rep.id]: msg }))
        return false
      } finally {
        setLoadingByRepId((prev) => ({ ...prev, [rep.id]: false }))
      }
    },
    [row.dates, seriesByRepId, symbol],
  )

  const toggleRepresentative = useCallback(
    async (rep: RepresentativeIndicator, checked: boolean) => {
      if (!checked) {
        setActiveRepIds((prev) => prev.filter((id) => id !== rep.id))
        return
      }

      const loaded = await loadRepresentativeSeries(rep)
      if (!loaded) return
      setActiveRepIds((prev) => (prev.includes(rep.id) ? prev : [...prev, rep.id]))
    },
    [loadRepresentativeSeries],
  )

  const activeIndicatorSeries = useMemo(
    () =>
      activeRepIds
        .map((id) => seriesByRepId[id])
        .filter((series): series is IndicatorOverlaySeries => Boolean(series)),
    [activeRepIds, seriesByRepId],
  )

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap">
        <Badge variant="outline" className="text-xs">{row.source}</Badge>
        <StaleBadge isStale={row.is_stale} computedAt={row.computed_at} />
      </div>

      <MetricsKpiGrid metrics={row.metrics} />

      {warningCode === "flat_signal" && (
        <FlatSignalBanner onSwitchLongShort={onSwitchLongShort} />
      )}

      {representatives.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
            Indicateurs représentatifs
          </h4>
          <div className="border rounded p-2 space-y-2 max-h-48 overflow-auto">
            {representatives.map((rep) => {
              const checked = activeRepIds.includes(rep.id)
              const loading = Boolean(loadingByRepId[rep.id])
              const err = errorByRepId[rep.id]
              return (
                <label key={rep.id} className="flex items-start gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={(e) => void toggleRepresentative(rep, e.target.checked)}
                    className="mt-0.5"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block font-medium truncate">{rep.description}</span>
                    <span className="block text-muted-foreground">
                      {rep.family.toUpperCase()}
                      {rep.normalized_weight != null ? ` • w=${formatNumber(rep.normalized_weight, 3)}` : ""}
                      {rep.signal_label ? ` • ${rep.signal_label}` : ""}
                      {rep.indicator_value != null ? ` • val=${formatNumber(rep.indicator_value, 3)}` : ""}
                    </span>
                    {err ? <span className="block text-destructive">{err}</span> : null}
                  </span>
                  {loading ? <span className="text-muted-foreground">Chargement…</span> : null}
                </label>
              )
            })}
          </div>
          <p className="mt-1 text-[11px] text-muted-foreground">
            Cochez pour afficher/masquer la série de l'indicateur sur le graphe ci-dessous.
          </p>
        </div>
      )}

      <div>
        <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
          Cours + signaux d'entrée/sortie
        </h4>
        <PriceSignalsChart
          close={closeSeries}
          position={positionSeries}
          dates={row.dates}
          indicatorSeries={activeIndicatorSeries}
        />
      </div>

      <div>
        <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
          Registre des trades
        </h4>
        <TradeLedgerTable trades={trades as Record<string, unknown>[] | null} />
      </div>

      <div>
        <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
          Monte Carlo — Block bootstrap
        </h4>
        <GlobalFanChart
          equity={row.equity}
          dates={row.dates}
          envelope={row.mc.envelope ?? null}
          stats={row.mc.stats ?? null}
        />
      </div>

      <ShuffledTradesPanel stats={shuffleStats as Parameters<typeof ShuffledTradesPanel>[0]["stats"]} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Helper: ScopeTab — renders 1 or 2 ResultBlocks (engine + WFO) for a scope
// ---------------------------------------------------------------------------

function ScopeTab({
  rows,
  symbol,
  onSwitchLongShort,
}: {
  rows: SignalBacktestResult[]
  symbol: string
  onSwitchLongShort: () => void
}) {
  if (rows.length === 0) {
    return (
      <div className="text-center text-muted-foreground text-sm py-8">
        Aucun résultat pour ce scope. Cliquez «\u00a0Calculer\u00a0».
      </div>
    )
  }
  return (
    <div className="space-y-8">
      {rows.map((row, idx) => (
        <ResultBlock
          key={`${row.source}-${row.scope}-${row.scope_key}-${row.window_start ?? idx}`}
          row={row}
          symbol={symbol}
          onSwitchLongShort={onSwitchLongShort}
        />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Helper: ComparaisonTab
// ---------------------------------------------------------------------------

type SortKey = "total_return" | "cagr" | "sharpe" | "max_drawdown" | "win_rate" | "n_trades"

function ComparaisonTab({
  results,
  symbol,
  onSwitchLongShort,
}: {
  results: SignalBacktestResult[]
  symbol: string
  onSwitchLongShort: () => void
}) {
  const [sortBy, setSortBy] = useState<SortKey>("sharpe")
  const [sortAsc, setSortAsc] = useState(false)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [minEv, setMinEv] = useState<string>("")

  const minEvNum = minEv !== "" ? parseFloat(minEv) : null

  const succeeded = results.filter((r) => {
    if (r.status !== "succeeded") return false
    if (minEvNum !== null && !Number.isNaN(minEvNum)) {
      const s = (r as Record<string, unknown>).shuffle_stats as Record<string, unknown> | null | undefined
      const ev = s?.status === "ok" ? (s.expected_return as number | null) : null
      if (ev == null || ev < minEvNum) return false
    }
    return true
  })
  const sorted = [...succeeded].sort((a, b) => {
    const va = a.metrics[sortBy] ?? (sortAsc ? Infinity : -Infinity)
    const vb = b.metrics[sortBy] ?? (sortAsc ? Infinity : -Infinity)
    return sortAsc ? va - vb : vb - va
  })

  const SORT_COLS: { key: SortKey; label: string }[] = [
    { key: "total_return", label: "Retour" },
    { key: "cagr",         label: "CAGR" },
    { key: "sharpe",       label: "Sharpe" },
    { key: "max_drawdown", label: "MaxDD" },
    { key: "win_rate",     label: "Win%" },
    { key: "n_trades",     label: "Trades" },
  ]

  const scopeLabel = (r: SignalBacktestResult) => {
    if (r.scope === "global") return "Global"
    if (r.scope === "per_category") return CAT_LABELS[r.scope_key] ?? r.scope_key
    return r.scope_key.replace(/\+/g, " + ")
  }

  const shuffleStats = (r: SignalBacktestResult) => {
    const s = (r as Record<string, unknown>).shuffle_stats as Record<string, unknown> | null | undefined
    return s?.status === "ok" ? (s.expected_return as number | null) : null
  }

  return (
    <div className="space-y-3">
      <div className="flex gap-3 flex-wrap text-xs text-muted-foreground items-center">
        <div className="flex gap-1 flex-wrap items-center">
          <span>Trier :</span>
          {SORT_COLS.map(({ key, label }) => (
            <button
              key={key}
              className={`px-2 py-1 rounded transition-colors ${sortBy === key ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}
              onClick={() => {
                if (sortBy === key) setSortAsc(!sortAsc)
                else { setSortBy(key); setSortAsc(key === "max_drawdown") }
              }}
            >
              {label}{sortBy === key ? (sortAsc ? " ↑" : " ↓") : ""}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1 ml-auto">
          <span className="whitespace-nowrap">EV/trade min :</span>
          <input
            type="number"
            step="0.01"
            placeholder="—"
            value={minEv}
            onChange={(e) => setMinEv(e.target.value)}
            className="w-20 px-2 py-1 rounded border bg-background text-foreground text-xs"
          />
        </div>
      </div>

      <div className="rounded border overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-muted/50">
            <tr>
              <th className="text-left py-2 px-3 font-medium">Scope</th>
              <th className="text-left py-2 px-2 font-medium">Source</th>
              <th className="text-right py-2 px-2 font-medium">Retour</th>
              <th className="text-right py-2 px-2 font-medium">CAGR</th>
              <th className="text-right py-2 px-2 font-medium">Sharpe</th>
              <th className="text-right py-2 px-2 font-medium">MaxDD</th>
              <th className="text-right py-2 px-2 font-medium">Win%</th>
              <th className="text-right py-2 px-2 font-medium">Trades</th>
              <th className="text-right py-2 px-2 font-medium">EV/trade</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/50">
            {sorted.map((r) => {
              const rowKey = `${r.scope}__${r.scope_key}__${r.source}`
              const isOpen = expanded === rowKey
              const ev = shuffleStats(r)
              return [
                <tr
                  key={rowKey}
                  className="cursor-pointer hover:bg-muted/30 transition-colors"
                  onClick={() => setExpanded(isOpen ? null : rowKey)}
                >
                  <td className="py-2 px-3 font-medium">{scopeLabel(r)}</td>
                  <td className="py-2 px-2">
                    <Badge
                      variant="outline"
                      className={`text-xs ${r.source === "engine" ? "border-blue-500 text-blue-600 dark:text-blue-400" : "border-purple-500 text-purple-600 dark:text-purple-400"}`}
                    >
                      {r.source === "engine" ? "A→G" : "WFO"}
                    </Badge>
                  </td>
                  <td className="text-right py-2 px-2 font-mono">{fmt(r.metrics.total_return, true)}</td>
                  <td className="text-right py-2 px-2 font-mono">{fmt(r.metrics.cagr, true)}</td>
                  <td className="text-right py-2 px-2 font-mono">{fmt(r.metrics.sharpe)}</td>
                  <td className="text-right py-2 px-2 font-mono text-destructive">{fmt(r.metrics.max_drawdown, true)}</td>
                  <td className="text-right py-2 px-2 font-mono">{fmt(r.metrics.win_rate, true)}</td>
                  <td className="text-right py-2 px-2 font-mono">{r.metrics.n_trades ?? "—"}</td>
                  <td className="text-right py-2 px-2 font-mono">{fmt(ev, true)}</td>
                </tr>,
                isOpen ? (
                  <tr key={`${rowKey}-expand`}>
                    <td colSpan={9} className="p-4 bg-muted/10">
                      <ResultBlock row={r} symbol={symbol} onSwitchLongShort={onSwitchLongShort} />
                    </td>
                  </tr>
                ) : null,
              ]
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main exported panel
// ---------------------------------------------------------------------------

interface BacktestMCPanelProps {
  symbol: string
  horizon: string
  variant?: "legacy" | "expanded" | "factor_x_ta"
}

export function BacktestMCPanel({ symbol, horizon, variant }: BacktestMCPanelProps) {
  const [source, setSource] = useState<"engine" | "wfo" | "both">("both")
  const [mcMethod, setMcMethod] = useState<"block_bootstrap" | "trade_bootstrap">("block_bootstrap")
  const [nPaths, setNPaths] = useState(2000)
  const [startDate, setStartDate] = useState(DEFAULT_START)
  const [endDate, setEndDate] = useState(todayIso())
  const [sidePolicy, setSidePolicy] = useState<"long_only" | "long_short">("long_only")

  const [loading, setLoading] = useState(false)
  const [triggering, setTriggering] = useState(false)
  const [data, setData] = useState<SignalBacktestResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<TabKey>("global")

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetchSignalBacktestResults(symbol, horizon, { variant: variant ?? "expanded" })
      setData(res)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(msg.startsWith("404")
        ? "Aucun résultat calculé. Cliquez « Calculer » pour lancer le backtest."
        : msg)
    } finally {
      setLoading(false)
    }
  }, [symbol, horizon])

  const trigger = useCallback(async () => {
    setTriggering(true)
    setError(null)
    try {
      await triggerSignalBacktest({
        symbol, horizon, variant: variant ?? "expanded",
        window_start: startDate,
        window_end: endDate,
        mc_config: { method: mcMethod, n_paths: nPaths, side_policy: sidePolicy },
      })
      setTimeout(load, 3000)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setTriggering(false)
    }
  }, [symbol, horizon, startDate, endDate, mcMethod, nPaths, sidePolicy, load])

  const switchLongShort = useCallback(() => {
    setSidePolicy("long_short")
  }, [])

  const results = data?.results ?? []
  const isStale = results.some((r) => r.is_stale)
  const firstComputed = results[0]?.computed_at ?? null

  // Build per-tab row sets
  const rowsFor = (scope: string, scopeKey: string) =>
    results.filter(
      (r) =>
        r.scope === scope &&
        r.scope_key === scopeKey &&
        r.status === "succeeded" &&
        (source === "both" || r.source === source),
    )

  const globalRows = rowsFor("global", "global")
  const catRows = (cat: string) => rowsFor("per_category", cat)

  const TABS: { key: TabKey; label: string }[] = [
    { key: "global",      label: "Global" },
    { key: "tendance",    label: "Tendance" },
    { key: "momentum",    label: "Momentum" },
    { key: "oscillation", label: "Oscillation" },
    { key: "volume",      label: "Volume" },
    { key: "comparaison", label: "Comparaison" },
  ]

  return (
    <div className="space-y-4">
      {/* Controls */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex flex-wrap gap-4 items-end">
            <div className="space-y-1">
              <Label className="text-xs">Source</Label>
              <div className="flex rounded border overflow-hidden text-xs">
                {(["engine", "wfo", "both"] as const).map((v) => (
                  <button
                    key={v}
                    className={`px-3 py-1.5 transition-colors ${source === v ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}
                    onClick={() => setSource(v)}
                  >
                    {v === "engine" ? "A→G Engine" : v === "wfo" ? "WFO" : "Les deux"}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Méthode MC</Label>
              <div className="flex rounded border overflow-hidden text-xs">
                {(["block_bootstrap", "trade_bootstrap"] as const).map((v) => (
                  <button
                    key={v}
                    className={`px-3 py-1.5 transition-colors ${mcMethod === v ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}
                    onClick={() => setMcMethod(v)}
                  >
                    {v === "block_bootstrap" ? "Block bootstrap" : "Trade bootstrap"}
                  </button>
                ))}
              </div>
            </div>

            <div className="space-y-1 w-24">
              <Label className="text-xs">Chemins MC</Label>
              <Input
                type="number" min={200} max={5000} step={100}
                value={nPaths}
                onChange={(e) => setNPaths(Math.max(200, Math.min(5000, Number(e.target.value))))}
                className="h-8 text-xs"
              />
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Début</Label>
              <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="h-8 text-xs w-36" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Fin</Label>
              <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="h-8 text-xs w-36" />
            </div>

            <div className="space-y-1">
              <Label className="text-xs">Sens</Label>
              <div className="flex rounded border overflow-hidden text-xs">
                {(["long_only", "long_short"] as const).map((v) => (
                  <button
                    key={v}
                    className={`px-3 py-1.5 transition-colors ${sidePolicy === v ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}
                    onClick={() => setSidePolicy(v)}
                  >
                    {v === "long_only" ? "Long only" : "Long/Short"}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex gap-2 items-end">
              <Button size="sm" onClick={load} disabled={loading} variant="outline">
                {loading ? "Chargement…" : "Charger"}
              </Button>
              <Button size="sm" onClick={trigger} disabled={triggering || loading}>
                {triggering ? "Envoi…" : "Calculer"}
              </Button>
            </div>

            {firstComputed && <StaleBadge isStale={isStale} computedAt={firstComputed} />}
          </div>

          {error && (
            <p className="mt-3 text-xs text-muted-foreground border rounded p-2 bg-muted/30">{error}</p>
          )}
        </CardContent>
      </Card>

      {loading && (
        <div className="space-y-3">
          <Skeleton className="h-10 w-full rounded" />
          <Skeleton className="h-64 w-full rounded" />
        </div>
      )}

      {!loading && data && (
        <>
          {/* Tab bar — scrollable on mobile */}
          <div className="overflow-x-auto">
            <div className="flex border-b min-w-max">
              {TABS.map(({ key, label }) => (
                <button
                  key={key}
                  onClick={() => setActiveTab(key)}
                  className={`px-4 py-2 text-sm transition-colors whitespace-nowrap border-b-2 -mb-px ${
                    activeTab === key
                      ? "border-primary text-primary font-semibold"
                      : "border-transparent text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Tab content */}
          <div className="pt-2">
            {activeTab === "global" && (
              <ScopeTab rows={globalRows} symbol={symbol} onSwitchLongShort={switchLongShort} />
            )}
            {(["tendance", "momentum", "oscillation", "volume"] as const).map(
              (cat) =>
                activeTab === cat && (
                  <ScopeTab key={cat} rows={catRows(cat)} symbol={symbol} onSwitchLongShort={switchLongShort} />
                ),
            )}
            {activeTab === "comparaison" && (
              <ComparaisonTab results={results} symbol={symbol} onSwitchLongShort={switchLongShort} />
            )}
          </div>
        </>
      )}

      {!loading && !data && !error && (
        <div className="text-center text-muted-foreground text-sm py-12">
          Cliquez « Charger » pour voir les résultats existants, ou « Calculer » pour lancer le backtest.
        </div>
      )}
    </div>
  )
}
