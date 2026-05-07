"use client"

import type { PredictiveAbilityCell, PredictiveAbilityMatrix } from "@/lib/api"

const BUCKET_ORDER = ["strong_buy", "buy", "hold", "sell", "strong_sell"] as const
const BUCKET_LABELS: Record<string, string> = {
  strong_buy: "Strong Buy (>50)",
  buy: "Buy (15..50)",
  hold: "Hold (-15..15)",
  sell: "Sell (-50..-15)",
  strong_sell: "Strong Sell (<-50)",
}

function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return "—"
  return `${(v * 100).toFixed(digits)}%`
}

function meanColor(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "bg-muted/30"
  const pct = v * 100
  if (pct > 1.5) return "bg-emerald-500/40"
  if (pct > 0.5) return "bg-emerald-500/20"
  if (pct > 0.1) return "bg-emerald-500/10"
  if (pct > -0.1) return "bg-muted/30"
  if (pct > -0.5) return "bg-red-500/10"
  if (pct > -1.5) return "bg-red-500/20"
  return "bg-red-500/40"
}

interface BucketMatrixProps {
  matrix: PredictiveAbilityMatrix
}

export function BucketMatrix({ matrix }: BucketMatrixProps) {
  const cellByKey = new Map<string, PredictiveAbilityCell>()
  for (const c of matrix.cells) cellByKey.set(`${c.bucket}|${c.fwd_h}`, c)

  return (
    <div className="overflow-x-auto rounded-md border">
      <table className="w-full text-xs">
        <thead className="bg-muted/40">
          <tr>
            <th className="sticky left-0 z-10 bg-muted/60 px-3 py-2 text-left font-medium">
              Bucket
            </th>
            {matrix.fwd_horizons.map((h) => (
              <th key={h} className="px-2 py-2 text-center font-medium">{h}d</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {BUCKET_ORDER.map((bucket) => {
            const isToday = matrix.current_bucket === bucket
            return (
            <tr key={bucket} className={`border-t ${isToday ? "border-l-4 border-l-blue-500 bg-blue-50/30 dark:bg-blue-950/20" : ""}`}>
              <td className="sticky left-0 z-10 bg-background px-3 py-2 font-medium whitespace-nowrap">
                <span className="flex items-center gap-1.5">
                  {BUCKET_LABELS[bucket]}
                  {isToday && (
                    <span className="inline-flex items-center rounded-full bg-blue-100 px-1.5 py-0.5 text-[10px] font-semibold text-blue-700 dark:bg-blue-900 dark:text-blue-300">
                      aujourd&apos;hui
                    </span>
                  )}
                </span>
              </td>
              {matrix.fwd_horizons.map((h) => {
                const cell = cellByKey.get(`${bucket}|${h}`)
                if (!cell || cell.n < 5) {
                  return (
                    <td key={h} className="px-2 py-2 text-center text-muted-foreground">
                      <div className="text-[10px]">n={cell?.n ?? 0}</div>
                    </td>
                  )
                }
                return (
                  <td
                    key={h}
                    className={`px-2 py-2 text-center ${meanColor(cell.mean)}`}
                    title={
                      `n=${cell.n}\n` +
                      `mean: ${fmtPct(cell.mean, 3)}\n` +
                      `95% CI: [${fmtPct(cell.ci_lower, 3)}, ${fmtPct(cell.ci_upper, 3)}]\n` +
                      `hit: ${fmtPct(cell.hit_rate, 1)} ` +
                      `[${fmtPct(cell.hit_ci_lower, 1)}, ${fmtPct(cell.hit_ci_upper, 1)}]\n` +
                      `std: ${fmtPct(cell.std, 2)}`
                    }
                  >
                    <div className="font-mono font-semibold">{fmtPct(cell.mean, 2)}</div>
                    <div className="text-[10px] text-muted-foreground">
                      {fmtPct(cell.hit_rate, 0)} · n={cell.n}
                    </div>
                  </td>
                )
              })}
            </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
