"use client"

import { AlertTriangle, CheckCircle2, CircleSlash } from "lucide-react"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import type { StrategyReview } from "@/lib/api"
import type { StockStrategyConfigV2 } from "@/lib/strategy-v2"

interface ReviewTabProps {
  symbol: string
  stockConfig: StockStrategyConfigV2
  review?: StrategyReview
  directCompatibilityMessage?: string | null
}

function ReviewLine({
  label,
  value,
}: {
  label: string
  value: string
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border bg-background px-3 py-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </div>
  )
}

export function ReviewTab({
  symbol,
  stockConfig,
  review,
  directCompatibilityMessage,
}: ReviewTabProps) {
  const stockReview = review?.stocks.find((item) => item.symbol === symbol)
  const entrySummary = stockConfig.entry_rules.length === 0
    ? "No entry rules"
    : `${stockConfig.entry_rules.length} rule(s)`
  const exitSummary = stockConfig.exit_rules.length === 0
    ? "Risk-only exits"
    : `${stockConfig.exit_rules.length} rule(s)`

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Review</CardTitle>
        <CardDescription>
          Readiness, WFO count, and handoff quality checks before opening Backtest.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 lg:grid-cols-2">
          <ReviewLine label="Strategy type" value={stockConfig.strategy_type.replace("_", " ")} />
          <ReviewLine
            label="Signal construction"
            value={`${Object.values(stockConfig.signal_construction.families).filter((family) => family.enabled).length} family(ies) active`}
          />
          <ReviewLine label="Entry rules" value={entrySummary} />
          <ReviewLine label="Exit rules" value={exitSummary} />
        </div>

        {stockReview ? (
          <div className="grid gap-3 lg:grid-cols-3">
            <div className="rounded-xl border bg-muted/20 p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Stock readiness</p>
              <div className="mt-2 flex items-center gap-2 text-sm font-medium">
                {stockReview.ready ? (
                  <CheckCircle2 className="h-4 w-4 text-green-600" />
                ) : (
                  <CircleSlash className="h-4 w-4 text-destructive" />
                )}
                {stockReview.ready ? "Ready" : "Needs work"}
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                {stockReview.wfo_param_count} WFO parameter(s) detected for this stock.
              </p>
            </div>

            <div className="rounded-xl border bg-muted/20 p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Global WFO count</p>
              <p className="mt-2 text-lg font-semibold">{review?.total_wfo_param_count ?? 0}</p>
              <p className="mt-2 text-xs text-muted-foreground">
                Severity: {review?.wfo_param_severity ?? "ok"}.
              </p>
            </div>

            <div className="rounded-xl border bg-muted/20 p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Pardo guidance</p>
              <div className="mt-2 flex items-center gap-2 text-sm font-medium">
                {(review?.pardo_df_ok ?? false) ? (
                  <CheckCircle2 className="h-4 w-4 text-green-600" />
                ) : (
                  <AlertTriangle className="h-4 w-4 text-amber-600" />
                )}
                {(review?.pardo_df_ok ?? false) ? "Within guidance" : "Elevated complexity"}
              </div>
              <p className="mt-2 text-xs text-muted-foreground">{review?.pardo_df_message}</p>
            </div>
          </div>
        ) : null}

        {directCompatibilityMessage ? (
          <div className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
            {directCompatibilityMessage}
          </div>
        ) : null}

        {(stockReview?.warnings ?? []).length > 0 ? (
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Warnings</p>
            {(stockReview?.warnings ?? []).map((warning) => (
              <div key={warning} className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                {warning}
              </div>
            ))}
          </div>
        ) : null}

        {(stockReview?.blocking_issues ?? []).length > 0 ? (
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Blocking issues</p>
            {(stockReview?.blocking_issues ?? []).map((issue) => (
              <div key={issue} className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {issue}
              </div>
            ))}
          </div>
        ) : null}

        {(review?.blocking_issues ?? []).length > 0 ? (
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Global blocking issues</p>
            {(review?.blocking_issues ?? []).map((issue) => (
              <div key={issue} className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {issue}
              </div>
            ))}
          </div>
        ) : null}

        {(review?.global_warnings ?? []).length > 0 ? (
          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Global warnings</p>
            {(review?.global_warnings ?? []).map((warning) => (
              <div key={warning} className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                {warning}
              </div>
            ))}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}
