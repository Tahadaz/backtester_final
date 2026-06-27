"use client"

import Link from "next/link"
import { useParams } from "next/navigation"
import { ArrowLeft } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import { useStrategyBacktestWindowDetail } from "@/hooks/use-api"
import { formatCurrency, formatDateTime, formatNumber, formatPercent } from "@/lib/format"

function toNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value
  if (typeof value === "string") {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

function formatValue(key: string, value: unknown): string {
  const numeric = toNumber(value)
  if (numeric == null) {
    if ((key.toLowerCase().includes("date") || key.toLowerCase().endsWith("_at")) && typeof value === "string") {
      return formatDateTime(value)
    }
    if (typeof value === "string") return value
    if (value == null) return "--"
    return JSON.stringify(value)
  }
  const normalized = key.toLowerCase()
  if (normalized.includes("return") || normalized.includes("drawdown") || normalized.includes("ratio") || normalized.includes("rate")) {
    return formatPercent(numeric)
  }
  if (normalized.includes("pnl") || normalized.includes("capital")) return formatCurrency(numeric)
  if (normalized.includes("date") || normalized.endsWith("_at")) return formatDateTime(String(value))
  return formatNumber(numeric, Number.isInteger(numeric) ? 0 : 4)
}

function KeyValueGrid({ value }: { value: Record<string, unknown> | null | undefined }) {
  if (!value || Object.keys(value).length === 0) {
    return <p className="text-sm text-muted-foreground">No values available.</p>
  }
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {Object.entries(value).map(([key, raw]) => (
        <div key={key} className="claude-stat">
          <p className="lbl">{key.replace(/_/g, " ")}</p>
          <p className="val !text-sm break-words">{formatValue(key, raw)}</p>
        </div>
      ))}
    </div>
  )
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-[520px] overflow-auto rounded-md border bg-muted/20 p-3 text-xs">
      {JSON.stringify(value ?? {}, null, 2)}
    </pre>
  )
}

export default function BacktestWindowDetailPage() {
  const params = useParams<{ runId: string; symbol: string; windowIndex: string }>()
  const runId = typeof params.runId === "string" ? params.runId : null
  const symbol = typeof params.symbol === "string" ? decodeURIComponent(params.symbol) : null
  const windowIndex = typeof params.windowIndex === "string" ? Number.parseInt(params.windowIndex, 10) : null
  const validWindowIndex = windowIndex != null && Number.isFinite(windowIndex) ? windowIndex : null
  const { data, isLoading, error } = useStrategyBacktestWindowDetail(runId, symbol, validWindowIndex)

  const summary = isRecord(data?.summary) ? data.summary : {}
  const detail = isRecord(data?.detail) ? data.detail : {}

  return (
    <div className="claude-page space-y-6">
      <div className="claude-page-h">
        <div>
          <h1>WFO Window</h1>
          <p className="sub">
            {symbol ?? "--"} window {validWindowIndex ?? "--"}
          </p>
        </div>
        <Button asChild variant="outline" size="sm" className="gap-2">
          <Link href={runId ? `/backtest?runId=${runId}` : "/backtest"}>
            <ArrowLeft className="h-4 w-4" />
            Back to run
          </Link>
        </Button>
      </div>

      {isLoading ? (
        <Skeleton className="h-72 rounded-xl" />
      ) : error ? (
        <Card className="claude-card">
          <CardContent className="p-8 text-sm text-destructive">
            {error instanceof Error ? error.message : "Window detail failed to load."}
          </CardContent>
        </Card>
      ) : data ? (
        <>
          <Card className="claude-card">
            <CardHeader>
              <CardTitle>Summary</CardTitle>
              <CardDescription>{data.symbol} / window {data.window_index}</CardDescription>
            </CardHeader>
            <CardContent>
              <KeyValueGrid value={summary} />
            </CardContent>
          </Card>

          <Card className="claude-card">
            <CardHeader>
              <CardTitle>Window Detail</CardTitle>
              <CardDescription>Persisted train, OOS, selected config, and diagnostics payload.</CardDescription>
            </CardHeader>
            <CardContent>
              <JsonBlock value={detail} />
            </CardContent>
          </Card>
        </>
      ) : (
        <Card className="claude-card">
          <CardContent className="p-8 text-sm text-muted-foreground">
            No persisted detail was returned for this window.
          </CardContent>
        </Card>
      )}
    </div>
  )
}
