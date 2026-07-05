"use client"

import { useMemo, useState } from "react"
import useSWR from "swr"
import { HelpCircle, RefreshCw } from "lucide-react"
import { PlotlyChart } from "@/components/run/plotly-chart"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import {
  fetchSfcPortfolioBacktest,
  fetchSfcPortfolioBacktestStatus,
  runSfcPortfolioBacktest,
  type SfcBacktestEquityPoint,
  type SfcBacktestSummaryRow,
} from "@/lib/api"
import { formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"

const SEGMENT_LABELS: Record<string, string> = {
  selection: "Sélection",
  proof: "Preuve",
  live: "Live",
}

const SEGMENT_COLORS: Record<string, string> = {
  selection: "rgb(148,163,184)",
  proof: "rgb(16,185,129)",
  live: "rgb(37,99,235)",
}

function pct(value: number | null | undefined, digits = 2) {
  if (value == null || !Number.isFinite(value)) return "--"
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(digits)}%`
}

function statTone(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value) || value === 0) return "neutral"
  return value > 0 ? "pos" : "neg"
}

function StatTile({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "pos" | "neg" | "neutral" }) {
  return (
    <div className="claude-stat">
      <p className="lbl">{label}</p>
      <p className={cn("val", tone === "pos" && "text-emerald-600", tone === "neg" && "text-red-600")}>{value}</p>
    </div>
  )
}

function summaryFor(rows: SfcBacktestSummaryRow[], segment: string) {
  return rows.find((row) => row.segment === segment) ?? null
}

function buildEquityFigure(points: SfcBacktestEquityPoint[]) {
  if (points.length < 2) return null
  const start = points[0]?.strategy || 1
  const yPct = (value: number | null | undefined) => (value == null ? null : ((value / start) - 1) * 100)
  const data: Array<Record<string, unknown>> = []
  for (const segment of ["selection", "proof", "live"]) {
    const segmentPoints = points.filter((point) => point.segment === segment)
    if (segmentPoints.length === 0) continue
    data.push({
      x: segmentPoints.map((point) => point.date),
      y: segmentPoints.map((point) => yPct(point.strategy)),
      type: "scatter",
      mode: "lines",
      name: SEGMENT_LABELS[segment],
      line: { color: SEGMENT_COLORS[segment], width: segment === "proof" ? 2.8 : 2 },
      fill: segment === "proof" ? "tozeroy" : undefined,
      fillcolor: segment === "proof" ? "rgba(16,185,129,0.08)" : undefined,
      hovertemplate: "%{x|%d/%m/%Y} — %{y:.2f}%<extra></extra>",
    })
  }
  const universe = points.filter((point) => point.universe_equal_weight != null)
  if (universe.length >= 2) {
    data.push({
      x: universe.map((point) => point.date),
      y: universe.map((point) => yPct(point.universe_equal_weight)),
      type: "scatter",
      mode: "lines",
      name: "Univers équipondéré",
      line: { color: "rgb(100,116,139)", width: 1.4, dash: "dot" },
      hovertemplate: "%{x|%d/%m/%Y} — %{y:.2f}%<extra>Univers</extra>",
    })
  }
  const masi = points.filter((point) => point.masi != null)
  if (masi.length >= 2) {
    data.push({
      x: masi.map((point) => point.date),
      y: masi.map((point) => yPct(point.masi)),
      type: "scatter",
      mode: "lines",
      name: "MASI",
      line: { color: "rgb(71,85,105)", width: 1.4, dash: "dash" },
      hovertemplate: "%{x|%d/%m/%Y} — %{y:.2f}%<extra>MASI</extra>",
    })
  }
  const shapes = ["selection", "proof", "live"].flatMap((segment) => {
    const segmentPoints = points.filter((point) => point.segment === segment)
    if (segmentPoints.length < 2) return []
    return [{
      type: "rect",
      xref: "x",
      yref: "paper",
      x0: segmentPoints[0].date,
      x1: segmentPoints[segmentPoints.length - 1].date,
      y0: 0,
      y1: 1,
      line: { width: 0 },
      fillcolor:
        segment === "proof"
          ? "rgba(16,185,129,0.045)"
          : segment === "live"
            ? "rgba(37,99,235,0.04)"
            : "rgba(148,163,184,0.055)",
      layer: "below",
    }]
  })
  return {
    data,
    layout: {
      margin: { t: 12, b: 40, l: 52, r: 16 },
      yaxis: { ticksuffix: "%", gridcolor: "rgba(0,0,0,0.06)" },
      xaxis: { type: "date", gridcolor: "rgba(0,0,0,0.06)" },
      showlegend: true,
      legend: { orientation: "h", x: 0, y: 1.12, font: { size: 11 } },
      shapes,
      plot_bgcolor: "transparent",
      paper_bgcolor: "transparent",
    },
  }
}

export function SfcPortfolioBacktestPanel() {
  const [rebalance, setRebalance] = useState<"monthly" | "quarterly">("monthly")
  const [costBps, setCostBps] = useState<33 | 75>(33)
  const [startDate, setStartDate] = useState("")
  const [endDate, setEndDate] = useState("")
  const [error, setError] = useState<string | null>(null)
  const { data, error: loadError, isLoading, mutate } = useSWR("sfc-portfolio-backtest", fetchSfcPortfolioBacktest, { refreshInterval: 0 })
  const { data: status, mutate: mutateStatus } = useSWR("sfc-portfolio-backtest-status", fetchSfcPortfolioBacktestStatus, { refreshInterval: 10_000 })
  const result = data?.result ?? null
  const proof = useMemo(() => summaryFor(result?.summary ?? [], "proof"), [result])
  const combined = useMemo(() => summaryFor(result?.summary ?? [], "combined"), [result])
  const figure = useMemo(() => buildEquityFigure(result?.equity_curve ?? []), [result])
  const latestJob = status?.jobs?.[0]
  const running = latestJob?.status === "queued" || latestJob?.status === "running" || latestJob?.status === "pending"

  async function triggerRun() {
    setError(null)
    try {
      await runSfcPortfolioBacktest({
        rebalance,
        cost_bps: costBps,
        start_date: startDate || null,
        end_date: endDate || null,
      })
      await mutateStatus()
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : "Recalcul impossible")
    }
  }

  return (
    <div className="dashboard-panel overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-bg2 px-4 py-3">
        <div>
          <h3 className="dashboard-section-title">Portefeuille SFC</h3>
          <div className="dashboard-meta">
            {data?.computed_at ? `Snapshot ${data.computed_at.slice(0, 10)} - ` : ""}
            {data?.validation_label ?? "validé sur 2023–2026 (une seule période de marché)"}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ToggleGroup type="single" value={rebalance} onValueChange={(value) => value && setRebalance(value as "monthly" | "quarterly")} className="h-8">
            <ToggleGroupItem value="monthly" className="h-8 px-3 text-[12px]">Mensuel</ToggleGroupItem>
            <ToggleGroupItem value="quarterly" className="h-8 px-3 text-[12px]">Trimestriel</ToggleGroupItem>
          </ToggleGroup>
          <ToggleGroup type="single" value={String(costBps)} onValueChange={(value) => value && setCostBps(Number(value) as 33 | 75)} className="h-8">
            <ToggleGroupItem value="33" className="h-8 px-3 text-[12px]">33 bps</ToggleGroupItem>
            <ToggleGroupItem value="75" className="h-8 px-3 text-[12px]">75 bps</ToggleGroupItem>
          </ToggleGroup>
          <Input type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} className="h-8 w-[142px] text-[12px]" />
          <Input type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} className="h-8 w-[142px] text-[12px]" />
          <Button type="button" size="sm" className="h-8 gap-1.5 rounded-md text-[12px]" onClick={() => void triggerRun()} disabled={running}>
            <RefreshCw className={cn("h-3.5 w-3.5", running && "animate-spin")} />
            Recalculer
          </Button>
          <span title="Long-only fixe: top tercile SFC équipondéré, sans Kelly ni short." className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted-foreground">
            <HelpCircle className="h-3.5 w-3.5" />
          </span>
        </div>
      </div>

      {isLoading ? <div className="p-3"><Skeleton className="h-[320px] rounded-md" /></div> : null}
      {loadError || error ? <div className="px-4 py-3 text-[12px] text-destructive">{error ?? "Snapshot SFC indisponible."}</div> : null}

      {result && !isLoading ? (
        <div className="space-y-3 p-3">
          <div>
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              {result.headline_label}
            </div>
            <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4 xl:grid-cols-6">
              <StatTile label="Rendement" value={pct(proof?.total_return)} tone={statTone(proof?.total_return)} />
              <StatTile label="CAGR" value={pct(proof?.cagr)} tone={statTone(proof?.cagr)} />
              <StatTile label="Sharpe ann." value={formatNumber(proof?.sharpe, 2)} />
              <StatTile label="Max drawdown" value={proof?.max_drawdown == null ? "--" : pct(proof.max_drawdown)} tone="neg" />
              <StatTile label="Hit-rate" value={pct(proof?.hit_rate)} />
              <StatTile label="Turnover moy." value={pct(proof?.avg_turnover)} />
            </div>
          </div>

          {combined ? (
            <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
              <StatTile label="Combiné rendement" value={pct(combined.total_return)} tone={statTone(combined.total_return)} />
              <StatTile label="Combiné CAGR" value={pct(combined.cagr)} tone={statTone(combined.cagr)} />
              <StatTile label="Active moy." value={pct(combined.mean_active_return)} tone={statTone(combined.mean_active_return)} />
              <StatTile label="IR" value={formatNumber(combined.information_ratio, 2)} />
            </div>
          ) : null}

          <div className="rounded-md border border-border">
            <div className="border-b border-border bg-bg2 px-3 py-2 text-[12px] font-semibold">Courbe d'équité</div>
            <div className="h-[360px] p-2">
              {figure ? <PlotlyChart figure={figure as never} /> : <div className="p-4 text-sm text-muted-foreground">Pas assez de données.</div>}
            </div>
          </div>

          <div className="grid gap-3 xl:grid-cols-2">
            <div className="overflow-hidden rounded-md border border-border">
              <div className="border-b border-border bg-bg2 px-3 py-2 text-[12px] font-semibold">Dernier portefeuille</div>
              <div className="max-h-[360px] overflow-auto">
                <table className="dashboard-table w-full min-w-[720px] text-[11px]">
                  <thead className="bg-bg2 text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 text-left">Titre</th>
                      <th className="px-3 py-2 text-left">Secteur</th>
                      <th className="px-3 py-2 text-right">SFC</th>
                      <th className="px-3 py-2 text-left">Piliers</th>
                      <th className="px-3 py-2 text-right">Poids</th>
                      <th className="px-3 py-2 text-left">Statut</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(result.latest_holdings ?? []).map((row) => (
                      <tr key={`${row.symbol}-${row.badge}`} className="border-b border-border/70">
                        <td className="dashboard-mono px-3 py-2 font-semibold">{row.symbol}</td>
                        <td className="px-3 py-2">{row.sector ?? "--"}</td>
                        <td className="dashboard-mono px-3 py-2 text-right">{formatNumber(row.sfc, 2)}</td>
                        <td className="px-3 py-2">
                          <div className="flex flex-wrap gap-1">
                            {["val", "qual", "fmom", "pmom"].map((key) => (
                              <span key={key} className="rounded border border-border bg-bg2 px-1.5 py-0.5 text-[9px] font-semibold">
                                {key.toUpperCase()} {formatNumber(row.pillars?.[key], 1)}
                              </span>
                            ))}
                          </div>
                        </td>
                        <td className="dashboard-mono px-3 py-2 text-right">{pct(row.weight, 1)}</td>
                        <td className="px-3 py-2">
                          <span className={cn("rounded px-2 py-0.5 text-[10px] font-semibold", row.badge === "in" ? "dashboard-chip-positive" : row.badge === "out" ? "border border-rose-400/40 bg-rose-500/10 text-rose-700" : "border border-border bg-bg2")}>
                            {row.badge === "in" ? "Entrée" : row.badge === "out" ? "Sortie" : "Conservé"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="overflow-hidden rounded-md border border-border">
              <div className="border-b border-border bg-bg2 px-3 py-2 text-[12px] font-semibold">Rebalances</div>
              <div className="max-h-[360px] overflow-auto">
                <table className="dashboard-table w-full min-w-[720px] text-[11px]">
                  <thead className="bg-bg2 text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 text-left">Date</th>
                      <th className="px-3 py-2 text-left">Segment</th>
                      <th className="px-3 py-2 text-right">Rendement</th>
                      <th className="px-3 py-2 text-right">vs univers</th>
                      <th className="px-3 py-2 text-right">Turnover</th>
                      <th className="px-3 py-2 text-right">Coût</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(result.rebalance_rows ?? []).slice(-16).reverse().map((row) => (
                      <tr key={`${row.date}-${row.period_end}`} className="border-b border-border/70">
                        <td className="dashboard-mono px-3 py-2">{row.date}</td>
                        <td className="px-3 py-2">{SEGMENT_LABELS[row.segment] ?? row.segment}</td>
                        <td className={cn("dashboard-mono px-3 py-2 text-right", statTone(row.strategy_return_net) === "pos" ? "dashboard-text-positive" : statTone(row.strategy_return_net) === "neg" ? "dashboard-text-negative" : "")}>{pct(row.strategy_return_net)}</td>
                        <td className={cn("dashboard-mono px-3 py-2 text-right", statTone(row.active_return) === "pos" ? "dashboard-text-positive" : statTone(row.active_return) === "neg" ? "dashboard-text-negative" : "")}>{pct(row.active_return)}</td>
                        <td className="dashboard-mono px-3 py-2 text-right">{pct(row.turnover)}</td>
                        <td className="dashboard-mono px-3 py-2 text-right">{pct(row.cost_drag)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <div className="dashboard-meta border-t border-border pt-2">
            Config gelée pmom_6_1 - hash {data?.config_hash ?? String(result.config?.config_hash ?? "--")} - long-only, sans Kelly
            {latestJob ? ` - dernier job ${latestJob.status}` : ""}
          </div>
        </div>
      ) : null}
    </div>
  )
}
