"use client"

import { buildFanTraces, buildFanLayout, type MCEnvelope } from "@/components/signals/fan-chart"
import { PlotlyChart } from "@/components/run/plotly-chart"
import { formatPercent, formatNumber } from "@/lib/format"

interface ShuffleStats {
  status: string
  n_trades: number
  expected_return?: number | null
  ci95?: [number, number] | null
  prob_positive?: number | null
  var95?: number | null
  cvar95?: number | null
  envelope?: MCEnvelope | null
}

function fmt(v: number | null | undefined, isPct = false) {
  if (v == null) return "—"
  return isPct ? formatPercent(v) : formatNumber(v, 3)
}

export function ShuffledTradesPanel({ stats }: { stats: ShuffleStats | null | undefined }) {
  if (!stats) return null

  if (stats.status === "insufficient_trades") {
    return (
      <div className="rounded border border-dashed p-3 text-xs text-muted-foreground bg-muted/10">
        Analyse shuffle non disponible — trades insuffisants ({stats.n_trades} trade{stats.n_trades !== 1 ? "s" : ""}, minimum 3 requis).
      </div>
    )
  }

  const tradeLabels = stats.envelope
    ? Array.from({ length: stats.envelope.p50.length }, (_, i) => String(i + 1))
    : []
  const realized = stats.envelope?.p50 ?? null

  return (
    <div className="space-y-3">
      <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
        Analyse shuffled trades ({stats.n_trades} trades)
      </h4>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <div className="rounded border bg-muted/20 p-2 text-center">
          <div className="text-[10px] text-muted-foreground mb-0.5">EV / trade</div>
          <div className="text-sm font-semibold">{fmt(stats.expected_return, true)}</div>
          {stats.ci95 && (
            <div className="text-[9px] text-muted-foreground font-mono">
              [{fmt(stats.ci95[0], true)}, {fmt(stats.ci95[1], true)}]
            </div>
          )}
        </div>
        <div className="rounded border bg-muted/20 p-2 text-center">
          <div className="text-[10px] text-muted-foreground mb-0.5">Prob. positif</div>
          <div className="text-sm font-semibold">{fmt((stats.prob_positive ?? 0) * 100)}%</div>
        </div>
        <div className="rounded border bg-muted/20 p-2 text-center">
          <div className="text-[10px] text-muted-foreground mb-0.5">VaR 95%</div>
          <div className="text-sm font-semibold text-destructive">{fmt(stats.var95, true)}</div>
        </div>
        <div className="rounded border bg-muted/20 p-2 text-center">
          <div className="text-[10px] text-muted-foreground mb-0.5">CVaR 95%</div>
          <div className="text-sm font-semibold text-destructive">{fmt(stats.cvar95, true)}</div>
        </div>
      </div>

      {stats.envelope && realized && tradeLabels.length > 0 && (
        <PlotlyChart
          figure={{
            data: buildFanTraces(tradeLabels, realized, stats.envelope, "Médiane MC"),
            layout: {
              ...buildFanLayout("Equity cumulée shufflée (par trade)", false),
              height: 200,
              xaxis: { title: "Trade #", tickfont: { size: 10 } },
            },
          }}
        />
      )}
    </div>
  )
}
