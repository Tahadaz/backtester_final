"use client"

import { useState, useCallback } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { PlotlyChart } from "@/components/run/plotly-chart"
import {
  fetchSignalBacktestResults,
  triggerSignalBacktest,
  type SignalBacktestResult,
  type SignalBacktestResponse,
} from "@/lib/api"
import { formatPercent, formatNumber } from "@/lib/format"

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CATEGORIES = ["tendance", "momentum", "oscillation", "volume"] as const
const DEFAULT_START = "2026-01-01"

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

const CATEGORY_LABELS: Record<string, string> = {
  tendance: "Tendance",
  momentum: "Momentum",
  oscillation: "Oscillation",
  volume: "Volume",
}

// ---------------------------------------------------------------------------
// Fan chart builder (Plotly traces)
// ---------------------------------------------------------------------------

function buildFanTraces(
  dates: string[],
  equity: number[],
  envelope: { p05: number[]; p25: number[]; p50: number[]; p75: number[]; p95: number[] } | null,
  label: string
) {
  const traces: Record<string, unknown>[] = []

  if (envelope) {
    // Outer band p05/p95
    traces.push({
      x: dates, y: envelope.p95, type: "scatter", mode: "lines",
      line: { color: "rgba(99,102,241,0.15)", width: 0 },
      showlegend: false, hoverinfo: "skip", name: "p95",
    })
    traces.push({
      x: dates, y: envelope.p05, type: "scatter", mode: "lines", fill: "tonexty",
      fillcolor: "rgba(99,102,241,0.10)", line: { color: "rgba(99,102,241,0.15)", width: 0 },
      showlegend: false, hoverinfo: "skip", name: "p05",
    })
    // Inner band p25/p75
    traces.push({
      x: dates, y: envelope.p75, type: "scatter", mode: "lines",
      line: { color: "rgba(99,102,241,0.25)", width: 0 },
      showlegend: false, hoverinfo: "skip", name: "p75",
    })
    traces.push({
      x: dates, y: envelope.p25, type: "scatter", mode: "lines", fill: "tonexty",
      fillcolor: "rgba(99,102,241,0.18)", line: { color: "rgba(99,102,241,0.25)", width: 0 },
      showlegend: false, hoverinfo: "skip", name: "p25",
    })
    // Median path
    traces.push({
      x: dates, y: envelope.p50, type: "scatter", mode: "lines",
      line: { color: "rgba(99,102,241,0.7)", width: 1, dash: "dot" },
      name: "MC médiane", showlegend: true,
    })
  }

  // Realized equity
  traces.push({
    x: dates, y: equity, type: "scatter", mode: "lines",
    line: { color: "#6366f1", width: 2 },
    name: label, showlegend: true,
  })

  return traces
}

function buildFanLayout(title: string, compact = false): Record<string, unknown> {
  return {
    title: compact ? undefined : { text: title, font: { size: 13 } },
    height: compact ? 180 : 340,
    margin: compact ? { t: 8, b: 30, l: 40, r: 8 } : { t: 36, b: 40, l: 50, r: 16 },
    showlegend: !compact,
    xaxis: { type: "date", tickfont: { size: 10 } },
    yaxis: { title: compact ? "" : "Valeur (normalisée)", tickformat: ".2f", tickfont: { size: 10 } },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: "currentColor" },
  }
}

// ---------------------------------------------------------------------------
// Metric helpers
// ---------------------------------------------------------------------------

function fmt(value: number | null | undefined, isPercent = false) {
  if (value == null) return "—"
  return isPercent ? formatPercent(value) : formatNumber(value, 2)
}

function BandCell({ band }: { band: { p05?: number | null; p50?: number | null; p95?: number | null } | null | undefined }) {
  if (!band) return <span className="text-muted-foreground">—</span>
  return (
    <span className="font-mono text-xs">
      {fmt(band.p05, true)} / <strong>{fmt(band.p50, true)}</strong> / {fmt(band.p95, true)}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StaleBadge({ isStale, computedAt }: { isStale: boolean; computedAt: string | null }) {
  if (!computedAt) return null
  const date = computedAt.slice(0, 10)
  return (
    <Badge variant={isStale ? "destructive" : "outline"} className="text-xs">
      {isStale ? `Obsolète (${date})` : `Calculé ${date}`}
    </Badge>
  )
}

function KpiStrip({ metrics }: { metrics: SignalBacktestResult["metrics"] }) {
  return (
    <div className="grid grid-cols-3 gap-1 text-center text-xs mt-1">
      <div><span className="text-muted-foreground">Ret. </span><strong>{fmt(metrics.total_return, true)}</strong></div>
      <div><span className="text-muted-foreground">Sharpe </span><strong>{fmt(metrics.sharpe)}</strong></div>
      <div><span className="text-muted-foreground">MaxDD </span><strong className="text-destructive">{fmt(metrics.max_drawdown, true)}</strong></div>
    </div>
  )
}

function SmallFanChart({ result, label }: { result: SignalBacktestResult; label: string }) {
  if (!result.equity || !result.dates) return <div className="text-xs text-muted-foreground">Pas de données</div>
  const traces = buildFanTraces(result.dates, result.equity, result.mc.envelope ?? null, label)
  return (
    <div>
      <PlotlyChart figure={{ data: traces, layout: buildFanLayout(label, true) }} />
      <KpiStrip metrics={result.metrics} />
    </div>
  )
}

function GlobalFanChart({ result }: { result: SignalBacktestResult }) {
  if (!result.equity || !result.dates) return <div className="text-xs text-muted-foreground">Pas de données</div>
  const traces = buildFanTraces(result.dates, result.equity, result.mc.envelope ?? null, "Courbe réalisée")
  const stats = result.mc.stats
  return (
    <div className="space-y-4">
      <PlotlyChart figure={{ data: traces, layout: buildFanLayout("Score technique global", false) }} />
      {stats && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="border-b">
                <th className="text-left py-1 pr-4 text-muted-foreground font-normal">Métrique</th>
                <th className="text-right py-1 px-2 text-muted-foreground font-normal">p05</th>
                <th className="text-right py-1 px-2 font-medium">p50</th>
                <th className="text-right py-1 pl-2 text-muted-foreground font-normal">p95</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50">
              {[
                ["CAGR", stats.cagr, true],
                ["Rendement total", stats.total_return, true],
                ["Sharpe", stats.sharpe, false],
                ["Max Drawdown", stats.max_drawdown, true],
              ].map(([label, band, isPct]) => (
                <tr key={label as string}>
                  <td className="py-1 pr-4 text-muted-foreground">{label as string}</td>
                  <td className="text-right py-1 px-2 font-mono">{fmt((band as { p05?: number | null })?.p05, isPct as boolean)}</td>
                  <td className="text-right py-1 px-2 font-mono font-semibold">{fmt((band as { p50?: number | null })?.p50, isPct as boolean)}</td>
                  <td className="text-right py-1 pl-2 font-mono">{fmt((band as { p95?: number | null })?.p95, isPct as boolean)}</td>
                </tr>
              ))}
              <tr>
                <td className="py-1 pr-4 text-muted-foreground">VaR 95%</td>
                <td colSpan={3} className="text-right py-1 font-mono">{fmt(stats.var95, true)}</td>
              </tr>
              <tr>
                <td className="py-1 pr-4 text-muted-foreground">CVaR 95%</td>
                <td colSpan={3} className="text-right py-1 font-mono">{fmt(stats.cvar95, true)}</td>
              </tr>
              <tr>
                <td className="py-1 pr-4 text-muted-foreground">Prob. rendement positif</td>
                <td colSpan={3} className="text-right py-1 font-mono">{fmt((stats.prob_positive_terminal ?? 0) * 100)}%</td>
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function CombinationsTable({
  results,
  onExpand,
  expanded,
}: {
  results: SignalBacktestResult[]
  onExpand: (key: string) => void
  expanded: string | null
}) {
  const [sortBy, setSortBy] = useState<"sharpe" | "cagr" | "max_drawdown" | "win_rate">("sharpe")
  const sorted = [...results].sort((a, b) => {
    const va = a.metrics[sortBy] ?? -Infinity
    const vb = b.metrics[sortBy] ?? -Infinity
    return sortBy === "max_drawdown" ? va - vb : vb - va
  })

  return (
    <div className="space-y-2">
      <div className="flex gap-2 text-xs text-muted-foreground items-center">
        <span>Trier par:</span>
        {(["sharpe", "cagr", "max_drawdown", "win_rate"] as const).map((k) => (
          <Button
            key={k}
            variant={sortBy === k ? "secondary" : "ghost"}
            size="sm"
            className="h-6 px-2 text-xs"
            onClick={() => setSortBy(k)}
          >
            {k === "max_drawdown" ? "MaxDD" : k === "win_rate" ? "Win%" : k.charAt(0).toUpperCase() + k.slice(1)}
          </Button>
        ))}
      </div>
      <div className="rounded border overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-muted/50">
            <tr>
              <th className="text-left py-2 px-3 font-medium">Combinaison</th>
              <th className="text-left py-2 px-2 font-medium">Source</th>
              <th className="text-right py-2 px-2 font-medium">Sharpe</th>
              <th className="text-right py-2 px-2 font-medium">CAGR</th>
              <th className="text-right py-2 px-2 font-medium">MaxDD</th>
              <th className="text-right py-2 px-2 font-medium">Trades</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/50">
            {sorted.map((r) => {
              const rowKey = `${r.scope_key}__${r.source}`
              const isOpen = expanded === rowKey
              return [
                <tr
                  key={rowKey}
                  className="cursor-pointer hover:bg-muted/30 transition-colors"
                  onClick={() => onExpand(isOpen ? "" : rowKey)}
                >
                  <td className="py-2 px-3 font-medium">{r.scope_key.replace(/\+/g, " + ")}</td>
                  <td className="py-2 px-2">
                    <Badge variant="outline" className="text-xs">{r.source}</Badge>
                  </td>
                  <td className="text-right py-2 px-2 font-mono">{fmt(r.metrics.sharpe)}</td>
                  <td className="text-right py-2 px-2 font-mono">{fmt(r.metrics.cagr, true)}</td>
                  <td className="text-right py-2 px-2 font-mono text-destructive">{fmt(r.metrics.max_drawdown, true)}</td>
                  <td className="text-right py-2 px-2 font-mono">{r.metrics.n_trades ?? "—"}</td>
                </tr>,
                isOpen && r.equity && r.dates ? (
                  <tr key={`${rowKey}-chart`}>
                    <td colSpan={6} className="p-3 bg-muted/10">
                      <PlotlyChart
                        figure={{
                          data: buildFanTraces(r.dates, r.equity, r.mc.envelope ?? null, r.scope_key),
                          layout: buildFanLayout(r.scope_key, true),
                        }}
                      />
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
// Main panel
// ---------------------------------------------------------------------------

interface BacktestMCPanelProps {
  symbol: string
  horizon: string
}

export function BacktestMCPanel({ symbol, horizon }: BacktestMCPanelProps) {
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
  const [expandedCombo, setExpandedCombo] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetchSignalBacktestResults(symbol, horizon, {
        variant: "expanded",
        source: source === "both" ? undefined : source,
      })
      setData(res)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      if (msg.startsWith("404")) {
        setError("Aucun résultat calculé. Cliquez «\u00a0Calculer\u00a0» pour lancer le backtest.")
      } else {
        setError(msg)
      }
    } finally {
      setLoading(false)
    }
  }, [symbol, horizon, source])

  const trigger = useCallback(async () => {
    setTriggering(true)
    setError(null)
    try {
      await triggerSignalBacktest({
        symbol, horizon, variant: "expanded",
        window_start: startDate,
        window_end: endDate,
        mc_config: {
          method: mcMethod,
          n_paths: nPaths,
          side_policy: sidePolicy,
        },
      })
      // Poll after a short delay
      setTimeout(load, 3000)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setTriggering(false)
    }
  }, [symbol, horizon, startDate, endDate, mcMethod, nPaths, sidePolicy, load])

  // Partition results by scope × source
  const byKey = (results: SignalBacktestResult[], targetScope: string, targetSource?: string) =>
    results.filter(
      (r) =>
        r.scope === targetScope &&
        r.status === "succeeded" &&
        (targetSource ? r.source === targetSource : true)
    )

  const results = data?.results ?? []
  const filteredResults = source === "both" ? results : results.filter((r) => r.source === source)
  const catResults = byKey(filteredResults, "per_category")
  const globalResults = byKey(filteredResults, "global")
  const comboResults = byKey(filteredResults, "combination")

  const isStale = filteredResults.some((r) => r.is_stale)
  const firstComputed = filteredResults[0]?.computed_at ?? null

  return (
    <div className="space-y-5">
      {/* Controls */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex flex-wrap gap-4 items-end">
            {/* Source */}
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

            {/* MC Method */}
            <div className="space-y-1">
              <Label className="text-xs">Méthode Monte Carlo</Label>
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

            {/* n_paths */}
            <div className="space-y-1 w-24">
              <Label className="text-xs">Chemins MC</Label>
              <Input
                type="number" min={200} max={5000} step={100}
                value={nPaths}
                onChange={(e) => setNPaths(Math.max(200, Math.min(5000, Number(e.target.value))))}
                className="h-8 text-xs"
              />
            </div>

            {/* Dates */}
            <div className="space-y-1">
              <Label className="text-xs">Début</Label>
              <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="h-8 text-xs w-36" />
            </div>
            <div className="space-y-1">
              <Label className="text-xs">Fin</Label>
              <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className="h-8 text-xs w-36" />
            </div>

            {/* Side policy */}
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

            {/* Action buttons */}
            <div className="flex gap-2 items-end">
              <Button size="sm" onClick={load} disabled={loading} variant="outline">
                {loading ? "Chargement…" : "Charger"}
              </Button>
              <Button size="sm" onClick={trigger} disabled={triggering || loading}>
                {triggering ? "Envoi…" : "Calculer"}
              </Button>
            </div>

            {/* Stale indicator */}
            {firstComputed && <StaleBadge isStale={isStale} computedAt={firstComputed} />}
          </div>

          {error && (
            <p className="mt-3 text-xs text-muted-foreground border rounded p-2 bg-muted/30">{error}</p>
          )}
        </CardContent>
      </Card>

      {loading && (
        <div className="grid grid-cols-2 gap-3">
          {[1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-48 rounded" />)}
        </div>
      )}

      {!loading && data && (
        <>
          {/* Section 1 — Par catégorie */}
          {catResults.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold mb-3">Par catégorie</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {CATEGORIES.map((cat) => {
                  const matches = catResults.filter((r) => r.scope_key === cat)
                  return matches.map((res) => (
                    <Card key={`${cat}-${res.source}`}>
                      <CardHeader className="py-2 px-4">
                        <CardTitle className="text-xs font-medium flex items-center justify-between">
                          {CATEGORY_LABELS[cat]}
                          <Badge variant="outline" className="text-xs">{res.source}</Badge>
                        </CardTitle>
                      </CardHeader>
                      <CardContent className="px-4 pb-3">
                        <SmallFanChart result={res} label={CATEGORY_LABELS[cat]} />
                      </CardContent>
                    </Card>
                  ))
                })}
              </div>
            </div>
          )}

          {/* Section 2 — Global */}
          {globalResults.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold mb-3">Score technique global</h3>
              <Card>
                <CardContent className="pt-4">
                  <div className="space-y-6">
                    {globalResults.map((result) => (
                      <div key={`global-${result.source}`} className="space-y-2">
                        <div className="flex items-center gap-2">
                          <Badge variant="outline" className="text-xs">{result.source}</Badge>
                          <StaleBadge isStale={result.is_stale} computedAt={result.computed_at} />
                        </div>
                        <GlobalFanChart result={result} />
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </div>
          )}

          {/* Section 3 — Combinations */}
          {comboResults.length > 0 && (
            <div>
              <h3 className="text-sm font-semibold mb-3">
                Combinaisons de catégories
                <span className="ml-2 text-xs font-normal text-muted-foreground">
                  ({comboResults.length} backtests)
                </span>
              </h3>
              <CombinationsTable
                results={comboResults}
                onExpand={setExpandedCombo}
                expanded={expandedCombo}
              />
            </div>
          )}

          {filteredResults.length === 0 && (
            <div className="text-center text-muted-foreground text-sm py-12">
              Aucun résultat disponible. Cliquez «\u00a0Calculer\u00a0» pour lancer le backtest.
            </div>
          )}
        </>
      )}
    </div>
  )
}
