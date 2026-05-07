"use client"

import { PlotlyChart } from "@/components/run/plotly-chart"
import { formatPercent, formatNumber } from "@/lib/format"

export interface MCEnvelope {
  p05: number[]
  p25: number[]
  p50: number[]
  p75: number[]
  p95: number[]
}

export interface MCStats {
  total_return?: { p05?: number | null; p50?: number | null; p95?: number | null } | null
  cagr?:         { p05?: number | null; p50?: number | null; p95?: number | null } | null
  sharpe?:       { p05?: number | null; p50?: number | null; p95?: number | null } | null
  max_drawdown?: { p05?: number | null; p50?: number | null; p95?: number | null } | null
  var95?: number | null
  cvar95?: number | null
  prob_positive_terminal?: number | null
}

export function buildFanTraces(
  dates: string[],
  equity: number[],
  envelope: MCEnvelope | null,
  label: string,
): Record<string, unknown>[] {
  const traces: Record<string, unknown>[] = []
  if (envelope) {
    traces.push({ x: dates, y: envelope.p95, type: "scatter", mode: "lines", line: { color: "rgba(99,102,241,0.15)", width: 0 }, showlegend: false, hoverinfo: "skip", name: "p95" })
    traces.push({ x: dates, y: envelope.p05, type: "scatter", mode: "lines", fill: "tonexty", fillcolor: "rgba(99,102,241,0.10)", line: { color: "rgba(99,102,241,0.15)", width: 0 }, showlegend: false, hoverinfo: "skip", name: "p05" })
    traces.push({ x: dates, y: envelope.p75, type: "scatter", mode: "lines", line: { color: "rgba(99,102,241,0.25)", width: 0 }, showlegend: false, hoverinfo: "skip", name: "p75" })
    traces.push({ x: dates, y: envelope.p25, type: "scatter", mode: "lines", fill: "tonexty", fillcolor: "rgba(99,102,241,0.18)", line: { color: "rgba(99,102,241,0.25)", width: 0 }, showlegend: false, hoverinfo: "skip", name: "p25" })
    traces.push({ x: dates, y: envelope.p50, type: "scatter", mode: "lines", line: { color: "rgba(99,102,241,0.7)", width: 1, dash: "dot" }, name: "MC médiane", showlegend: true })
  }
  traces.push({ x: dates, y: equity, type: "scatter", mode: "lines", line: { color: "#6366f1", width: 2 }, name: label, showlegend: true })
  return traces
}

export function buildFanLayout(title: string, compact = false): Record<string, unknown> {
  return {
    title: compact ? undefined : { text: title, font: { size: 13 } },
    height: compact ? 180 : 320,
    margin: compact ? { t: 8, b: 30, l: 40, r: 8 } : { t: 36, b: 40, l: 50, r: 16 },
    showlegend: !compact,
    xaxis: { type: "date", tickfont: { size: 10 } },
    yaxis: { title: compact ? "" : "Valeur (normalisée)", tickformat: ".2f", tickfont: { size: 10 } },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: "currentColor" },
  }
}

function fmt(v: number | null | undefined, isPct = false) {
  if (v == null) return "—"
  return isPct ? formatPercent(v) : formatNumber(v, 2)
}

function BandCell({ band }: { band: { p05?: number | null; p50?: number | null; p95?: number | null } | null | undefined }) {
  if (!band) return <span className="text-muted-foreground">—</span>
  return (
    <span className="font-mono text-xs">
      {fmt(band.p05, true)} / <strong>{fmt(band.p50, true)}</strong> / {fmt(band.p95, true)}
    </span>
  )
}

export function SmallFanChart({
  equity,
  dates,
  envelope,
  label,
}: {
  equity: number[] | null
  dates: string[] | null
  envelope: MCEnvelope | null
  label: string
}) {
  if (!equity || !dates) return <div className="text-xs text-muted-foreground">Pas de données</div>
  const traces = buildFanTraces(dates, equity, envelope, label)
  return <PlotlyChart figure={{ data: traces, layout: buildFanLayout(label, true) }} />
}

export function GlobalFanChart({
  equity,
  dates,
  envelope,
  stats,
  title,
}: {
  equity: number[] | null
  dates: string[] | null
  envelope: MCEnvelope | null
  stats: MCStats | null
  title?: string
}) {
  if (!equity || !dates) return <div className="text-xs text-muted-foreground">Pas de données</div>
  const traces = buildFanTraces(dates, equity, envelope, "Courbe réalisée")
  return (
    <div className="space-y-3">
      <PlotlyChart figure={{ data: traces, layout: buildFanLayout(title ?? "Monte Carlo — Block Bootstrap", false) }} />
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
              {([
                ["CAGR", stats.cagr, true],
                ["Rendement total", stats.total_return, true],
                ["Sharpe", stats.sharpe, false],
                ["Max Drawdown", stats.max_drawdown, true],
              ] as [string, typeof stats.cagr, boolean][]).map(([label, band, isPct]) => (
                <tr key={label}>
                  <td className="py-1 pr-4 text-muted-foreground">{label}</td>
                  <td className="text-right py-1 px-2 font-mono">{fmt(band?.p05, isPct)}</td>
                  <td className="text-right py-1 px-2 font-mono font-semibold">{fmt(band?.p50, isPct)}</td>
                  <td className="text-right py-1 pl-2 font-mono">{fmt(band?.p95, isPct)}</td>
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
