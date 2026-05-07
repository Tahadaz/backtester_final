"use client"

import type { FactorStateEntry } from "@/lib/api"
import { CheckCircle2, XCircle } from "lucide-react"

const FACTOR_LABELS: Record<string, string> = {
  "^VIX": "VIX",
  "^GSPC": "S&P 500",
  "BZ=F": "Brent",
  "DX-Y.NYB": "DXY",
  "EURUSD=X": "EUR/USD",
  "^TNX": "US 10Y",
}

function formatMetric(value: number | null | undefined, form: string): string {
  if (value == null) return "—"
  if (form === "momentum") return `${(value * 100).toFixed(2)}%`
  if (form === "zscore") return value.toFixed(2)
  if (form === "change") return value.toFixed(3)
  if (form === "direction") return value > 0 ? "▲" : value < 0 ? "▼" : "–"
  return value.toFixed(3)
}

function formatValue(value: number): string {
  if (value >= 1000) return value.toLocaleString("fr-FR", { maximumFractionDigits: 0 })
  if (value >= 10) return value.toFixed(2)
  return value.toFixed(4)
}

type Props = {
  factors: FactorStateEntry[]
}

export function FactorXTaStateTable({ factors }: Props) {
  if (factors.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        Aucun facteur utilisé par les représentants survivors.
      </p>
    )
  }

  return (
    <div className="space-y-3">
      {factors.map((factor) => (
        <div key={factor.factor_ticker} className="rounded-lg border bg-card">
          {/* Factor header */}
          <div className="flex items-center justify-between gap-3 border-b px-3 py-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold">
                {FACTOR_LABELS[factor.factor_ticker] ?? factor.canonical_id}
              </span>
              <span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                {factor.factor_ticker}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs font-medium">{formatValue(factor.current_value)}</span>
              {factor.as_of && (
                <span className="text-[10px] text-muted-foreground">{factor.as_of}</span>
              )}
            </div>
          </div>

          {/* Conditions */}
          <div className="divide-y">
            {factor.conditions.map((cond) => (
              <div
                key={cond.condition_id}
                className="flex items-center gap-3 px-3 py-2"
              >
                {/* Active/inactive icon */}
                <div className="shrink-0">
                  {cond.is_active ? (
                    <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />
                  ) : (
                    <XCircle className="h-3.5 w-3.5 text-muted-foreground/50" />
                  )}
                </div>

                {/* Rule */}
                <div className="min-w-0 flex-1">
                  <span className="rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 font-mono text-[10px] text-amber-700">
                    {cond.human_rule}
                  </span>
                </div>

                {/* Current metric */}
                <div className="shrink-0 text-right">
                  <span
                    className={`font-mono text-[11px] ${
                      cond.is_active ? "text-green-700 font-medium" : "text-muted-foreground"
                    }`}
                  >
                    {formatMetric(cond.current_metric_value, cond.form)}
                  </span>
                </div>

                {/* Active label */}
                <div className="shrink-0">
                  <span
                    className={`text-[10px] font-medium ${
                      cond.is_active ? "text-green-700" : "text-muted-foreground"
                    }`}
                  >
                    {cond.is_active ? "ACTIF" : "INACTIF"}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
