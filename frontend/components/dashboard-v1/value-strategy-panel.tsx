"use client"

import { useEffect, useMemo, useState } from "react"
import useSWR from "swr"
import { AlertTriangle, RefreshCw } from "lucide-react"
import { PlotlyChart } from "@/components/run/plotly-chart"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import {
  fetchValueStrategySnapshot,
  triggerValueStrategyRecompute,
  type ValueStrategyEquityCurvePoint,
  type ValueStrategyFreshness,
  type ValueStrategyHolding,
  type ValueStrategyTradeLedgerRow,
} from "@/lib/api"
import { formatNumber } from "@/lib/format"
import { cn } from "@/lib/utils"

function buildEquityFigure(
  points: ValueStrategyEquityCurvePoint[],
  benchmarks: { masi: boolean; masi20: boolean },
) {
  if (points.length < 2) return null
  const yPct = (value: number) => (value - 1) * 100
  const data: Record<string, unknown>[] = [
    {
      x: points.map((p) => p.date),
      y: points.map((p) => yPct(p.equity)),
      type: "scatter",
      mode: "lines",
      name: "Stratégie (net)",
      line: { color: "rgb(16,185,129)", width: 2.2 },
      fill: "tozeroy",
      fillcolor: "rgba(16,185,129,0.08)",
      hovertemplate: "%{x|%d/%m/%Y} — %{y:.2f}%<extra></extra>",
    },
  ]
  if (benchmarks.masi && points.some((p) => p.masi != null)) {
    data.push({
      x: points.map((p) => p.date),
      y: points.map((p) => (p.masi != null ? yPct(p.masi) : null)),
      type: "scatter",
      mode: "lines",
      name: "MASI",
      line: { color: "rgb(148,163,184)", width: 1.6, dash: "dot" },
      hovertemplate: "%{x|%d/%m/%Y} — %{y:.2f}%<extra>MASI</extra>",
    })
  }
  if (benchmarks.masi20 && points.some((p) => p.masi20 != null)) {
    data.push({
      x: points.map((p) => p.date),
      y: points.map((p) => (p.masi20 != null ? yPct(p.masi20) : null)),
      type: "scatter",
      mode: "lines",
      name: "MASI20",
      line: { color: "rgb(96,165,250)", width: 1.6, dash: "dash" },
      hovertemplate: "%{x|%d/%m/%Y} — %{y:.2f}%<extra>MASI20</extra>",
    })
  }
  return {
    data,
    layout: {
      autosize: true,
      height: 280,
      margin: { l: 48, r: 16, t: 12, b: 32 },
      xaxis: { showgrid: false },
      yaxis: { title: "Rendement cumulé (%)", ticksuffix: "%", zeroline: true },
      showlegend: true,
      legend: { orientation: "h", y: -0.15, font: { size: 10 } },
      paper_bgcolor: "transparent",
      plot_bgcolor: "transparent",
    },
    config: { displayModeBar: false, responsive: true },
  }
}

function tradeActionTone(action: string): string {
  return action === "BUY" ? "text-emerald-600" : "text-red-600"
}

const FRESHNESS_LABELS: Record<ValueStrategyFreshness["state"], string> = {
  fresh: "À jour",
  aging: "Vieillissant",
  stale: "Périmé",
  failed_refresh: "Dernier rafraîchissement échoué",
  no_snapshot: "Aucun instantané",
}

const FRESHNESS_TONE: Record<ValueStrategyFreshness["state"], string> = {
  fresh: "border-emerald-400/40 bg-emerald-500/10 text-emerald-700",
  aging: "border-sky-400/40 bg-sky-500/10 text-sky-700",
  stale: "border-amber-400/40 bg-amber-500/10 text-amber-800",
  failed_refresh: "border-rose-400/40 bg-rose-500/10 text-rose-700",
  no_snapshot: "border-border bg-muted text-muted-foreground",
}

function pct(value: unknown, digits = 1): string {
  const num = typeof value === "number" && Number.isFinite(value) ? value : null
  if (num == null) return "--"
  return `${num >= 0 ? "+" : ""}${(num * 100).toFixed(digits)}%`
}

function num(value: unknown, digits = 2): string {
  const n = typeof value === "number" && Number.isFinite(value) ? value : null
  if (n == null) return "--"
  return n.toFixed(digits)
}

function statTone(value: unknown) {
  const n = typeof value === "number" && Number.isFinite(value) ? value : null
  if (n == null || n === 0) return "neutral"
  return n > 0 ? "pos" : "neg"
}

function StatTile({ label, value, tone = "neutral" }: { label: string; value: string; tone?: "pos" | "neg" | "neutral" }) {
  return (
    <div className="claude-stat">
      <p className="lbl">{label}</p>
      <p className={cn("val", tone === "pos" && "text-emerald-600", tone === "neg" && "text-red-600")}>{value}</p>
    </div>
  )
}

const ARCHITECTURE_LABELS: Record<string, string> = {
  S1_bm: "Structural Value (B/M)",
  S2_cfp: "Cash-Flow Value (CF/P)",
  S3_composite: "Combined Value (transparent composite)",
  S4_sleeves: "Separate Sleeves (50/50)",
}

export function ValueStrategyPanel() {
  const { data, error, isLoading, mutate } = useSWR("value-strategy-snapshot", () => fetchValueStrategySnapshot(), {
    revalidateOnFocus: false,
    revalidateOnMount: true,
  })
  const [triggering, setTriggering] = useState(false)
  const [showMasi, setShowMasi] = useState(true)
  const [showMasi20, setShowMasi20] = useState(false)
  const equityPoints = data?.equity_curve ?? []
  const hasMasi = equityPoints.some((p) => p.masi != null)
  const hasMasi20 = equityPoints.some((p) => p.masi20 != null)
  const equityFigure = useMemo(
    () => buildEquityFigure(equityPoints, { masi: showMasi, masi20: showMasi20 }),
    [equityPoints, showMasi, showMasi20],
  )

  async function handleRecompute() {
    setTriggering(true)
    try {
      await triggerValueStrategyRecompute()
      // Recompute runs async on the worker (~minutes); poll until the snapshot's
      // computed_at actually advances instead of leaving the stale cached response
      // displayed indefinitely (SWR won't refetch this key on its own).
      const startedAt = data?.computed_at ?? null
      for (let attempt = 0; attempt < 40; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 5000))
        const fresh = await mutate()
        if (fresh?.computed_at && fresh.computed_at !== startedAt) break
      }
    } finally {
      setTriggering(false)
    }
  }

  useEffect(() => {
    if (data?.freshness?.state === "no_snapshot" && !triggering && !isLoading) {
      handleRecompute()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.freshness?.state, isLoading])

  if (isLoading) {
    return (
      <div className="dashboard-panel space-y-3 p-4">
        <Skeleton className="h-5 w-64" />
        <Skeleton className="h-24 w-full" />
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="dashboard-panel px-4 py-8 text-center text-sm text-muted-foreground">
        Aucun instantané de stratégie de valeur disponible pour l'instant.
      </div>
    )
  }

  const recommendedMetrics = data.strategy_metrics[data.recommended_architecture] ?? {}
  const holdings: ValueStrategyHolding[] = data.current_holdings
  const freshness = data.freshness
  const noSnapshot = freshness.state === "no_snapshot"
  const trades: ValueStrategyTradeLedgerRow[] = data.trade_ledger ?? []

  return (
    <div className="dashboard-panel overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-bg2 px-4 py-3">
        <div>
          <h3 className="dashboard-section-title">Stratégie de valeur — B/M &amp; CF/P</h3>
          <div className="dashboard-meta">
            {data.model_version} · {ARCHITECTURE_LABELS[data.recommended_architecture] ?? data.recommended_architecture} · stratégie au {data.as_of_date?.slice(0, 10) ?? "--"}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="border-amber-400/40 bg-amber-500/10 text-amber-800 text-[11px]">
            {data.research_status}
          </Badge>
          <Button variant="outline" size="sm" className="h-7 gap-1 text-[11px]" onClick={handleRecompute} disabled={triggering}>
            <RefreshCw className={cn("h-3 w-3", triggering && "animate-spin")} />
            {triggering ? "Lancement..." : "Recalculer"}
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2">
        <Badge variant="outline" className={cn("text-[11px]", FRESHNESS_TONE[freshness.state])}>
          {FRESHNESS_LABELS[freshness.state]}
        </Badge>
        <span className="dashboard-meta">
          {freshness.last_successful_computed_at
            ? `Dernier calcul réussi : ${freshness.last_successful_computed_at.slice(0, 16).replace("T", " ")} UTC (${freshness.age_days?.toFixed(1)} j)`
            : "Aucun calcul réussi enregistré"}
        </span>
      </div>

      {noSnapshot ? (
        <div className="px-4 py-8 text-center text-sm text-muted-foreground">
          {data.caveats[0] ?? "Aucun instantané disponible. Déclenchez un recalcul."}
        </div>
      ) : (
      <>
      <div className="grid grid-cols-2 gap-2 p-3 sm:grid-cols-4">
        <StatTile label="Rendement cumulé" value={pct(recommendedMetrics.cumulative_return)} tone={statTone(recommendedMetrics.cumulative_return)} />
        <StatTile label="Sharpe (net)" value={num(recommendedMetrics.sharpe)} tone={statTone(recommendedMetrics.sharpe)} />
        <StatTile label="Drawdown max" value={pct(recommendedMetrics.max_drawdown)} tone="neg" />
        <StatTile label="Turnover moyen" value={pct(recommendedMetrics.avg_turnover)} />
      </div>

      <div className="border-t border-border px-4 py-3">
        <div className="flex items-start gap-2 rounded-md border border-amber-400/30 bg-amber-500/5 px-3 py-2 text-[11px] text-amber-900">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <ul className="list-disc space-y-0.5 pl-3.5">
            {data.caveats.map((caveat) => (
              <li key={caveat}>{caveat}</li>
            ))}
          </ul>
        </div>
      </div>

      <div className="border-t border-border px-4 py-3">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div className="dashboard-meta">Courbe d'équité — réalisée, net de coûts (pas un diagnostic de rendements chevauchants)</div>
          <div className="flex items-center gap-3 text-[11px]">
            {hasMasi && (
              <label className="flex items-center gap-1.5 text-muted-foreground">
                <input type="checkbox" checked={showMasi} onChange={(e) => setShowMasi(e.target.checked)} className="h-3 w-3" />
                MASI
              </label>
            )}
            {hasMasi20 && (
              <label className="flex items-center gap-1.5 text-muted-foreground">
                <input type="checkbox" checked={showMasi20} onChange={(e) => setShowMasi20(e.target.checked)} className="h-3 w-3" />
                MASI20
              </label>
            )}
          </div>
        </div>
        {equityFigure ? <PlotlyChart figure={equityFigure as never} /> : <div className="p-4 text-center text-sm text-muted-foreground">Pas assez de points pour tracer la courbe.</div>}
      </div>

      <div className="border-t border-border px-4 py-3">
        <div className="dashboard-meta mb-2">Journal des transactions ({trades.length}{trades.length >= 500 ? "+, 500 plus récentes affichées" : ""})</div>
        {trades.length === 0 ? (
          <div className="py-4 text-center text-sm text-muted-foreground">Aucune transaction enregistrée.</div>
        ) : (
          <div className="max-h-80 overflow-y-auto rounded-md border border-border">
            <Table className="text-[12px]">
              <TableHeader>
                <TableRow className="sticky top-0 border-b border-border bg-bg2 hover:bg-bg2">
                  <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Date</TableHead>
                  <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Action</TableHead>
                  <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Titre</TableHead>
                  <TableHead className="h-auto px-3 py-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Vintage formé</TableHead>
                  <TableHead className="h-auto px-3 py-2 text-right text-[10px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Poids</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {trades.map((trade, idx) => (
                  <TableRow key={`${trade.date}-${trade.symbol}-${trade.action}-${idx}`} className="border-b border-border/70 hover:bg-bg2">
                    <TableCell className="dashboard-mono px-3 py-2 text-[11px] text-muted-foreground">{trade.date}</TableCell>
                    <TableCell className={cn("px-3 py-2 text-[11px] font-semibold", tradeActionTone(trade.action))}>{trade.action === "BUY" ? "Achat" : "Vente"}</TableCell>
                    <TableCell className="dashboard-mono px-3 py-2 text-[11px] font-semibold">{trade.symbol}</TableCell>
                    <TableCell className="dashboard-mono px-3 py-2 text-[11px] text-muted-foreground">{trade.vintage_formed}</TableCell>
                    <TableCell className="dashboard-mono px-3 py-2 text-right text-[11px]">{formatNumber(trade.weight * 100, 2)}%</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      <div className="border-t border-border px-4 py-3">
        <div className="dashboard-meta mb-2">Positions actuelles ({holdings.length})</div>
        <div className="flex flex-wrap gap-1.5">
          {holdings.map((holding) => (
            <Badge key={holding.symbol} variant="outline" className="dashboard-mono text-[10px]" title={holding.sector ?? undefined}>
              {holding.symbol} · {formatNumber(holding.target_weight * 100, 1)}%
            </Badge>
          ))}
        </div>
      </div>
      </>
      )}
    </div>
  )
}
