"use client"

import { formatPercent, formatNumber } from "@/lib/format"

interface Metrics {
  total_return?: number | null
  cagr?: number | null
  sharpe?: number | null
  max_drawdown?: number | null
  win_rate?: number | null
  n_trades?: number | null
}

function fmt(v: number | null | undefined, isPct = false) {
  if (v == null) return "—"
  return isPct ? formatPercent(v) : formatNumber(v, 2)
}

interface Tile {
  key: keyof Metrics
  label: string
  pct: boolean
  red?: boolean
  int?: boolean
}

const TILES: Tile[] = [
  { key: "total_return", label: "Rendement", pct: true },
  { key: "cagr",         label: "CAGR",      pct: true },
  { key: "sharpe",       label: "Sharpe",    pct: false },
  { key: "max_drawdown", label: "MaxDD",     pct: true, red: true },
  { key: "win_rate",     label: "Win%",      pct: true },
  { key: "n_trades",     label: "Trades",    pct: false, int: true },
]

export function MetricsKpiGrid({ metrics }: { metrics: Metrics }) {
  return (
    <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
      {TILES.map(({ key, label, pct, red, int: isInt }) => {
        const v = metrics[key]
        const display = v == null ? "—" : isInt ? String(v) : fmt(v, pct)
        return (
          <div key={key} className="rounded border bg-muted/20 p-2 text-center">
            <div className="text-[10px] text-muted-foreground mb-0.5">{label}</div>
            <div className={`text-sm font-semibold ${red && v != null && v < 0 ? "text-destructive" : ""}`}>
              {display}
            </div>
          </div>
        )
      })}
    </div>
  )
}
