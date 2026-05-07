"use client"

import { useSignalEvaluation } from "@/hooks/use-api"
import type { SignalEvaluationReport } from "@/lib/api"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { Badge } from "@/components/ui/badge"
import { ICBadge } from "./ic-badge"
import { DSRBadge } from "./dsr-badge"

interface SignalEvaluationPanelProps {
  symbol: string
  category: string
  horizon: string
}

function MetricRow({ label, value, unit = "" }: { label: string; value: string | number | null; unit?: string }) {
  return (
    <div className="flex items-center justify-between py-1 text-xs border-b last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono tabular-nums">
        {value == null || (typeof value === "number" && !isFinite(value))
          ? "—"
          : `${typeof value === "number" ? value.toFixed(2) : value}${unit}`}
      </span>
    </div>
  )
}

function ICDecayChart({ report }: { report: SignalEvaluationReport }) {
  const { horizons, ic_values, ic_ci_lower, ic_ci_upper } = report.ic_curve
  const maxAbs = Math.max(...ic_values.map(Math.abs).filter(isFinite), 0.01)

  return (
    <div className="space-y-1">
      <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide">IC Decay</p>
      <div className="flex items-end gap-1.5 h-16">
        {horizons.map((h, i) => {
          const ic = ic_values[i]
          if (!isFinite(ic)) return <div key={h} className="flex-1 bg-muted/30 rounded-sm" style={{ height: "4px" }} />
          const height = Math.max(4, Math.abs(ic) / maxAbs * 52)
          const color = ic > 0 ? "bg-emerald-500" : "bg-red-400"
          return (
            <div key={h} className="flex-1 flex flex-col items-center gap-0.5">
              <span className="text-[9px] font-mono">{(ic * 100).toFixed(0)}%</span>
              <div className={`w-full rounded-sm ${color}`} style={{ height: `${height}px` }} />
              <span className="text-[9px] text-muted-foreground">d{h}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function SignalEvaluationPanel({ symbol, category, horizon }: SignalEvaluationPanelProps) {
  const { data: report, isLoading, error } = useSignalEvaluation(symbol, category, horizon)

  if (isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="text-sm text-destructive py-4 text-center">
        Erreur de calcul — vérifiez que le WFO a été lancé pour ce signal.
      </div>
    )
  }

  if (!report) return null

  const { portfolio, robustness } = report

  return (
    <div className="space-y-4">
      {/* IC decay chart */}
      <ICDecayChart report={report} />

      {/* Summary badges */}
      <div className="flex flex-wrap gap-1.5">
        <DSRBadge dsr={robustness.dsr} psr={robustness.psr} />
        <Badge variant="outline" className="text-[10px]">
          PSR {Math.round(robustness.psr * 100)}%
        </Badge>
        <Badge variant="outline" className="text-[10px]">
          {report.n_obs} obs
        </Badge>
      </div>

      {/* Portfolio stats */}
      <div>
        <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-1">Performance</p>
        <MetricRow label="Sharpe (annualisé)" value={portfolio.sharpe} />
        <MetricRow label="Sharpe net de frais" value={portfolio.after_cost_sharpe} />
        <MetricRow label="Sortino" value={portfolio.sortino} />
        <MetricRow label="Max Drawdown" value={portfolio.max_drawdown} unit="%" />
        <MetricRow label="Hit Rate" value={Math.round(report.hit_rate_h1 * 100)} unit="%" />
        <MetricRow label="Profit Factor" value={portfolio.profit_factor} />
        <MetricRow label="Retour total" value={portfolio.total_return} unit="%" />
      </div>

      {/* Robustness */}
      <div>
        <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide mb-1">Robustesse</p>
        <MetricRow label="DSR" value={Math.round(robustness.dsr * 100)} unit="%" />
        <MetricRow label="PSR (vs SR=0)" value={Math.round(robustness.psr * 100)} unit="%" />
        <MetricRow
          label="IC Bootstrap CI"
          value={`[${(robustness.ic_bootstrap_ci[0] * 100).toFixed(0)}%, ${(robustness.ic_bootstrap_ci[1] * 100).toFixed(0)}%]`}
        />
        <MetricRow
          label="Sharpe Bootstrap CI"
          value={`[${robustness.sharpe_bootstrap_ci[0].toFixed(2)}, ${robustness.sharpe_bootstrap_ci[1].toFixed(2)}]`}
        />
        <MetricRow label="IC CV" value={robustness.ic_cv} />
        <MetricRow label="t-stat cond." value={report.conditional_return_tstat} />
      </div>
    </div>
  )
}
