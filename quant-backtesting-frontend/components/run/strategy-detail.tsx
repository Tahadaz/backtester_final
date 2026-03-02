"use client"

import { useEffect, useMemo, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { SignalBadge } from "@/components/signal-badge"
import { formatDate, formatNumber, formatPercent } from "@/lib/format"
import {
  fetchArtifactJson,
  type LeaderboardRow,
  type PlotlyFigure,
} from "@/lib/api"
import { Download, X } from "lucide-react"
import { PlotlyChart } from "@/components/run/plotly-chart"

function parseBestParams(raw: unknown): Record<string, unknown> {
  if (!raw) return {}
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw) as unknown
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>
      }
    } catch {
      return {}
    }
    return {}
  }
  if (typeof raw === "object" && !Array.isArray(raw)) {
    return raw as Record<string, unknown>
  }
  return {}
}

function nestedRecordField(
  parent: Record<string, unknown>,
  key: string
): Record<string, unknown> {
  const value = parent[key]
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>
  }
  return {}
}

function flattenRecord(
  value: Record<string, unknown>,
  prefix = "",
  out: Record<string, unknown> = {}
): Record<string, unknown> {
  for (const [key, raw] of Object.entries(value)) {
    const nextKey = prefix ? `${prefix}.${key}` : key
    if (raw && typeof raw === "object" && !Array.isArray(raw)) {
      flattenRecord(raw as Record<string, unknown>, nextKey, out)
      continue
    }
    out[nextKey] = raw
  }
  return out
}

function extractGroupedParams(params: Record<string, unknown>): {
  strategy: Record<string, unknown>
  portfolio: Record<string, unknown>
} {
  const strategyNested = flattenRecord(nestedRecordField(params, "strategy"))
  const portfolioNested = flattenRecord(nestedRecordField(params, "portfolio"))
  const strategyFlat: Record<string, unknown> = {}
  const portfolioFlat: Record<string, unknown> = {}

  for (const [key, val] of Object.entries(params)) {
    if (key.startsWith("strategy.")) {
      strategyFlat[key.slice("strategy.".length)] = val
      continue
    }
    if (key.startsWith("portfolio.")) {
      portfolioFlat[key.slice("portfolio.".length)] = val
    }
  }

  return {
    strategy: { ...strategyFlat, ...strategyNested },
    portfolio: { ...portfolioFlat, ...portfolioNested },
  }
}

export function StrategyDetail({
  row,
  runId,
  onClose,
}: {
  row: LeaderboardRow
  runId: string
  onClose: () => void
}) {
  const [plotJson, setPlotJson] = useState<PlotlyFigure | null>(null)
  const [plotLoading, setPlotLoading] = useState(false)
  const [plotError, setPlotError] = useState<string | null>(null)

  const params = useMemo(
    () => parseBestParams(row.best_params_json),
    [row.best_params_json]
  )
  const { strategy: strategyParams, portfolio: portfolioParams } = useMemo(
    () => extractGroupedParams(params),
    [params]
  )

  useEffect(() => {
    void runId
    let cancelled = false
    const plotUrl = row.plot_url

    if (!plotUrl) {
      setPlotJson(null)
      setPlotError("No plot_url available for this strategy.")
      setPlotLoading(false)
      return
    }
    const safePlotUrl = plotUrl

    async function loadPlot() {
      setPlotLoading(true)
      setPlotError(null)
      try {
        const fig = await fetchArtifactJson(safePlotUrl)
        if (!cancelled) setPlotJson(fig)
      } catch (err) {
        if (!cancelled) {
          setPlotJson(null)
          setPlotError(
            err instanceof Error ? err.message : "Failed to load plot JSON"
          )
        }
      } finally {
        if (!cancelled) setPlotLoading(false)
      }
    }

    loadPlot()
    return () => {
      cancelled = true
    }
  }, [row.plot_url, runId])

  function downloadPlotJson() {
    if (!plotJson) return
    const blob = new Blob([JSON.stringify(plotJson, null, 2)], {
      type: "application/json",
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${row.symbol}_${row.strategy_kind}_plot.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="p-4">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 font-mono text-sm font-bold text-primary">
                {row.symbol.slice(0, 3)}
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="font-bold text-foreground">{row.symbol}</h2>
                  <span className="rounded-md bg-secondary px-2 py-0.5 text-xs font-semibold text-secondary-foreground">
                    {row.strategy_kind}
                  </span>
                  <SignalBadge value={row.signal_today} />
                </div>
                {row.signal_date && (
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    Signal date: {formatDate(row.signal_date)}
                  </p>
                )}
              </div>
            </div>
            <Button variant="ghost" size="icon" onClick={onClose} className="h-8 w-8">
              <X className="h-4 w-4" />
              <span className="sr-only">Close detail</span>
            </Button>
          </div>

          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {[
              {
                label: "CAGR",
                value: formatPercent(row.cagr),
                color:
                  (row.cagr ?? 0) >= 0
                    ? "text-[oklch(0.45_0.15_165)]"
                    : "text-destructive",
              },
              {
                label: "Total Return",
                value: formatPercent(row.total_return),
                color:
                  (row.total_return ?? 0) >= 0
                    ? "text-[oklch(0.45_0.15_165)]"
                    : "text-destructive",
              },
              { label: "PnL", value: formatNumber(row.pnl) },
              { label: "Sharpe", value: formatNumber(row.sharpe) },
              {
                label: "Max DD",
                value: formatPercent(row.max_drawdown),
                color: "text-destructive",
              },
              { label: "Efficiency", value: formatNumber(row.efficiency) },
            ].map((m) => (
              <div
                key={m.label}
                className="rounded-lg border border-border bg-secondary/30 p-2.5"
              >
                <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                  {m.label}
                </p>
                <p className={`font-mono text-sm font-bold ${m.color || "text-foreground"}`}>
                  {m.value}
                </p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="text-base">Price / Indicators / Trades</CardTitle>
            {plotJson && (
              <Button
                variant="outline"
                size="sm"
                onClick={downloadPlotJson}
                className="h-7 gap-1 text-xs"
              >
                <Download className="h-3 w-3" />
                JSON
              </Button>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {plotLoading ? (
            <Skeleton className="h-96 rounded-lg" />
          ) : plotError ? (
            <div className="flex h-48 items-center justify-center rounded-lg border border-dashed border-border text-sm text-muted-foreground">
              Plot not available ({plotError})
            </div>
          ) : plotJson ? (
            <PlotlyChart figure={plotJson} />
          ) : null}
        </CardContent>
      </Card>

      {(Object.keys(strategyParams).length > 0 ||
        Object.keys(portfolioParams).length > 0) && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Best Parameters</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 sm:grid-cols-2">
              {Object.keys(strategyParams).length > 0 && (
                <div className="rounded-lg border border-border p-3">
                  <p className="mb-2 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                    Strategy
                  </p>
                  {Object.entries(strategyParams).map(([key, val]) => (
                    <div
                      key={key}
                      className="flex items-center justify-between border-b border-border/50 py-1.5 last:border-0"
                    >
                      <span className="text-xs text-muted-foreground">{key}</span>
                      <span className="font-mono text-xs font-semibold text-foreground">
                        {String(val)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
              {Object.keys(portfolioParams).length > 0 && (
                <div className="rounded-lg border border-border p-3">
                  <p className="mb-2 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
                    Portfolio
                  </p>
                  {Object.entries(portfolioParams).map(([key, val]) => (
                    <div
                      key={key}
                      className="flex items-center justify-between border-b border-border/50 py-1.5 last:border-0"
                    >
                      <span className="text-xs text-muted-foreground">{key}</span>
                      <span className="font-mono text-xs font-semibold text-foreground">
                        {String(val)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
